# modules/github/router.py
import os
import re
import uuid
import glob
import shutil
import asyncio
import urllib.parse
import zipfile
from datetime import datetime, timedelta
import aiohttp
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
import config
from utils.gate import is_authorized
from utils.shared import queue
from operators.uploader import process_split_and_upload, upload_file_direct_to_bale
from modules.github.api import fetch_github_api, get_github_headers
from modules.github.keyboards import (
    get_repo_menu_keyboard,
    get_back_keyboard,
    get_branches_keyboard,
    get_releases_keyboard,
    get_files_explorer_keyboard,
    get_tags_keyboard
)

github_router = Router()

# Stateful Session Cache mapping short IDs to real parameters
# Structure: { gh_id: { "owner": "...", "repo": "...", "path": "/", "page": 1, "items_list": [] } }
GITHUB_CACHE = {}

MAX_GITHUB_ZIP_FILES = int(os.getenv("GITHUB_ZIP_MAX_FILES", "750"))
MAX_GITHUB_ZIP_BYTES = int(os.getenv("GITHUB_ZIP_MAX_BYTES", str(512 * 1024 * 1024)))

# Regex compilers for clean URL capture
REPO_REGEX = re.compile(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/?$")
SUB_REGEX = re.compile(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/(issues|pull|discussions)/(\d+)/?$")
GIST_REGEX = re.compile(r"https?://gist\.github\.com/([^/]+)/([a-f0-9]+)/?$")

def safe_cache_filename(value: str, fallback: str = "download") -> str:
    """Return a compact filename safe for local cache paths."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return cleaned or fallback

def current_branch(meta: dict) -> str | None:
    """Return the selected branch/ref; None means GitHub's default branch."""
    return meta.get("branch")

def display_branch(meta: dict) -> str:
    """Return a user-facing branch label."""
    return current_branch(meta) or "default"

def repo_zip_url(owner: str, repo: str, branch: str | None = None) -> str:
    """Build GitHub's native archive URL for a full repository ZIP."""
    base_url = f"https://api.github.com/repos/{owner}/{repo}/zipball"
    if not branch:
        return base_url
    return f"{base_url}/{urllib.parse.quote(branch, safe='')}"

def contents_api_url(owner: str, repo: str, path: str, branch: str | None = None) -> str:
    """Build GitHub Contents API URL for the selected folder path."""
    normalized_path = path.strip("/")
    url = f"https://api.github.com/repos/{owner}/{repo}/contents"
    if normalized_path:
        url += f"/{urllib.parse.quote(normalized_path, safe='/')}"
    if branch:
        url += f"?ref={urllib.parse.quote(branch, safe='')}"
    return url

def markdown_link(title: str, url: str) -> str:
    """Build a simple markdown link with a sanitized title."""
    return f"[{title.replace(']', ')')}]({url})"

def human_size(size_bytes: int) -> str:
    """Return compact human-readable byte sizes."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"

async def stream_url_to_file(url: str, file_path: str, headers: dict | None = None) -> None:
    """Download a URL to disk without loading the full response into memory."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=1800) as response:
            if response.status != 200:
                raise RuntimeError(f"Remote server returned HTTP Error: {response.status}")
            with open(file_path, "wb") as f:
                async for chunk in response.content.iter_chunked(512 * 1024):
                    f.write(chunk)

async def write_url_to_zip(session: aiohttp.ClientSession, url: str, zip_file: zipfile.ZipFile, arcname: str, headers: dict) -> None:
    """Stream one remote file directly into an open ZIP archive."""
    async with session.get(url, headers=headers, timeout=1800) as response:
        if response.status != 200:
            raise RuntimeError(f"Failed to fetch `{arcname}`: HTTP {response.status}")
        with zip_file.open(arcname, "w") as target:
            async for chunk in response.content.iter_chunked(512 * 1024):
                target.write(chunk)

async def add_github_contents_to_zip(
    session: aiohttp.ClientSession,
    owner: str,
    repo: str,
    path: str,
    root_path: str,
    zip_root: str,
    zip_file: zipfile.ZipFile,
    counters: dict,
    branch: str | None,
) -> None:
    """Recursively add a GitHub folder's files to a local ZIP archive."""
    data = await fetch_github_api(contents_api_url(owner, repo, path, branch))
    items = data if isinstance(data, list) else [data]

    for item in items:
        item_type = item.get("type")
        item_path = item.get("path", "")

        if item_type == "dir":
            await add_github_contents_to_zip(session, owner, repo, item_path, root_path, zip_root, zip_file, counters, branch)
            continue

        if item_type != "file":
            continue

        file_size = int(item.get("size") or 0)
        if counters["files"] + 1 > MAX_GITHUB_ZIP_FILES:
            raise RuntimeError(f"Folder has more than {MAX_GITHUB_ZIP_FILES} files. Narrow the path and retry.")
        if counters["bytes"] + file_size > MAX_GITHUB_ZIP_BYTES:
            max_mb = MAX_GITHUB_ZIP_BYTES // (1024 * 1024)
            raise RuntimeError(f"Folder is larger than {max_mb} MB. Narrow the path and retry.")

        relative_path = item_path
        if root_path and item_path.startswith(f"{root_path}/"):
            relative_path = item_path[len(root_path) + 1:]
        elif root_path and item_path == root_path:
            relative_path = os.path.basename(item_path)

        headers = get_github_headers()
        headers["Accept"] = "application/vnd.github.raw"
        arcname = f"{zip_root}/{relative_path}".replace("\\", "/")

        await write_url_to_zip(session, item["url"], zip_file, arcname, headers)
        counters["files"] += 1
        counters["bytes"] += file_size

async def create_github_folder_zip(owner: str, repo: str, path: str, branch: str | None, zip_path: str) -> dict:
    """Create a ZIP for the currently browsed GitHub folder without third-party services."""
    normalized_path = path.strip("/")
    zip_root = safe_cache_filename(os.path.basename(normalized_path) if normalized_path else repo, repo)
    counters = {"files": 0, "bytes": 0}

    async with aiohttp.ClientSession() as session:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            await add_github_contents_to_zip(
                session=session,
                owner=owner,
                repo=repo,
                path=normalized_path,
                root_path=normalized_path,
                zip_root=zip_root,
                zip_file=zip_file,
                counters=counters,
                branch=branch,
            )

    if counters["files"] == 0:
        raise RuntimeError("No downloadable files were found in this folder.")
    return counters

async def enqueue_github_zip_job(callback_query: CallbackQuery, user_id: int, owner: str, repo: str, source_url: str, file_stem: str, description: str) -> None:
    """Queue a ZIP download/upload job and deliver it through Bale as a document."""
    safe_stem = safe_cache_filename(file_stem, repo)
    temp_zip_path = f"cache/{uuid.uuid4().hex[:8]}_{safe_stem}.zip"

    async def queued_zip_job():
        os.makedirs("cache", exist_ok=True)
        try:
            await callback_query.message.edit_text(f"⚡ Downloading `{description}` ZIP package...")
            await stream_url_to_file(source_url, temp_zip_path, get_github_headers())
            await callback_query.message.edit_text("📤 Uploading ZIP package to Bale...")

            await process_split_and_upload(
                bot=callback_query.bot,
                chat_id=callback_query.message.chat.id,
                file_path=temp_zip_path,
                action='d',
                title=f"{safe_stem}.zip",
                uploader="GitHub",
                duration=0,
                thumb_path=None,
                progress_msg=callback_query.message
            )

            from main import log_event
            await log_event(f"📦 *GitHub ZIP:* `{description}` from `{owner}/{repo}` uploaded for User `{user_id}`.")
        except Exception as e:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
            await callback_query.message.edit_text(f"❌ *GitHub ZIP download failed:* {e}", reply_markup=get_back_keyboard(callback_query.data.split(':')[1]))
            from main import log_event
            await log_event(f"❌ *GitHub ZIP Error:* Failed `{description}` from `{owner}/{repo}`. Details: `{str(e)}`")

    await queue.add_task(user_id, callback_query.message, queued_zip_job)

async def enqueue_github_folder_zip_job(callback_query: CallbackQuery, user_id: int, owner: str, repo: str, path: str, branch: str | None, file_stem: str, description: str) -> None:
    """Queue a local recursive folder ZIP build and upload."""
    safe_stem = safe_cache_filename(file_stem, repo)
    temp_zip_path = f"cache/{uuid.uuid4().hex[:8]}_{safe_stem}.zip"

    async def queued_zip_job():
        os.makedirs("cache", exist_ok=True)
        try:
            await callback_query.message.edit_text(f"⚡ Building ZIP for `{description}`...")
            counters = await create_github_folder_zip(owner, repo, path, branch, temp_zip_path)
            await callback_query.message.edit_text(
                f"📤 Uploading `{description}` ZIP ({counters['files']} files)..."
            )

            await process_split_and_upload(
                bot=callback_query.bot,
                chat_id=callback_query.message.chat.id,
                file_path=temp_zip_path,
                action='d',
                title=f"{safe_stem}.zip",
                uploader="GitHub",
                duration=0,
                thumb_path=None,
                progress_msg=callback_query.message
            )

            from main import log_event
            await log_event(f"📦 *GitHub Folder ZIP:* `{description}` from `{owner}/{repo}` uploaded for User `{user_id}`.")
        except Exception as e:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
            await callback_query.message.edit_text(f"❌ *GitHub folder ZIP failed:* {e}", reply_markup=get_back_keyboard(callback_query.data.split(':')[1]))
            from main import log_event
            await log_event(f"❌ *GitHub Folder ZIP Error:* Failed `{description}` from `{owner}/{repo}`. Details: `{str(e)}`")

    await queue.add_task(user_id, callback_query.message, queued_zip_job)

# =========================================================================
# Link Interceptors (Pure aiogram v3 Syntax)
# =========================================================================

@github_router.message(
    F.text,
    F.chat.type == "private",
    lambda message: REPO_REGEX.match(message.text.strip().split("|")[0].strip()) is not None
)
async def github_repo_link_handler(message: Message):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        return

    text = message.text.strip().split("|")[0].strip()
    match = REPO_REGEX.match(text)
    owner, repo = match.groups()

    # Generate unique 8-character ID and save to cache
    gh_id = f"gh_{str(uuid.uuid4())[:8]}"
    GITHUB_CACHE[gh_id] = {
        "owner": owner,
        "repo": repo,
        "path": "/",
        "page": 1,
        "items_list": []
    }

    await message.reply(
        text=f"🐙 *GitHub Repository Browser*\n\n"
             f"📁 *Repository:* `{owner}/{repo}`\n"
             f"🔗 *URL:* https://github.com/{owner}/{repo}\n\n"
             f"Select an action:",
        reply_markup=get_repo_menu_keyboard(gh_id)
    )

@github_router.message(
    F.text,
    F.chat.type == "private",
    lambda message: SUB_REGEX.match(message.text.strip()) is not None
)
async def github_sub_link_handler(message: Message):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        return

    text = message.text.strip()
    match = SUB_REGEX.match(text)
    owner, repo, sub_type, num = match.groups()

    api_sub_type = "issues" if sub_type == "pull" else sub_type
    api_url = f"https://api.github.com/repos/{owner}/{repo}/{api_sub_type}/{num}"

    status_msg = await message.reply("🔍 Extracting thread data...")
    try:
        data = await fetch_github_api(api_url)
        title = data.get("title", "No Title")
        state = data.get("state", "unknown").upper()
        author = data.get("user", {}).get("login", "unknown")
        created_at = data.get("created_at", "")[:10]
        body = data.get("body") or ""

        body_preview = body[:400] + "..." if len(body) > 400 else body
        emoji = "🔀" if sub_type == "pull" else ("💬" if sub_type == "discussions" else "📋")

        await status_msg.edit_text(
            text=f"{emoji} *GitHub Thread: #{num}*\n\n"
                 f"🏷️ *Title:* `{title}`\n"
                 f"⚙️ *Type:* `{sub_type.upper()}`\n"
                 f"🟢 *Status:* `{state}`\n"
                 f"👤 *Author:* `{author}`\n"
                 f"📅 *Created:* `{created_at}`\n\n"
                 f"📝 *Description Preview:*\n```\n{body_preview}\n```"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ *Failed to fetch thread:* {e}")

@github_router.message(
    F.text,
    F.chat.type == "private",
    lambda message: GIST_REGEX.match(message.text.strip()) is not None
)
async def github_gist_link_handler(message: Message, bot: Bot):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        return

    text = message.text.strip()
    match = GIST_REGEX.match(text)
    owner, gist_id = match.groups()

    status_msg = await message.reply("🔍 Extracting Gist files...")
    try:
        api_url = f"https://api.github.com/gists/{gist_id}"
        data = await fetch_github_api(api_url)
        description = data.get("description") or "No Description"
        files = data.get("files", {})

        await status_msg.edit_text(f"📦 *Gist:* `{gist_id}`\n📝 *Description:* `{description}`\n\n📤 Delivering files...")

        os.makedirs("cache", exist_ok=True)
        for filename, file_data in files.items():
            raw_url = file_data.get("raw_url")
            temp_path = f"cache/{uuid.uuid4().hex[:6]}_{filename}"
            async with aiohttp.ClientSession() as session:
                async with session.get(raw_url) as response:
                    if response.status == 200:
                        with open(temp_path, "wb") as f:
                            f.write(await response.read())

            await upload_file_direct_to_bale(
                method="sendDocument",
                chat_id=user_id,
                file_path=temp_path,
                caption=f"📁 *Gist File:* `{filename}`"
            )
            if os.path.exists(temp_path):
                os.remove(temp_path)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ *Failed to fetch Gist:* {e}")

# =========================================================================
# Commands Implementation (Search and Trend)
# =========================================================================

@github_router.message(Command("search"))
async def github_search_handler(message: Message):
    query = message.text[7:].strip()
    if not query:
        await message.reply("⚠️ *Usage:* `/search <query>`")
        return
    status_msg = await message.reply("🔍 Searching GitHub...")
    try:
        api_url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&sort=stars&order=desc"
        data = await fetch_github_api(api_url)
        items = data.get("items", [])[:5]
        if not items:
            await status_msg.edit_text("ℹ️ No repositories found matching query.")
            return
        results = []
        for idx, item in enumerate(items, 1):
            results.append(
                f"{idx}. *{item['full_name']}*\n"
                f"   ⭐ Stars: `{item['stargazers_count']}` | 🍴 Forks: `{item['forks_count']}`\n"
                f"   🔗 [Link](https://github.com/{item['full_name']})"
            )
        await status_msg.edit_text("🔍 *GitHub Top Search Results:*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Search Failed:* {e}")

@github_router.message(Command("user"))
async def github_user_handler(message: Message):
    username = message.text[5:].strip()
    if not username:
        await message.reply("⚠️ *Usage:* `/user <username>`")
        return
    status_msg = await message.reply("🔍 Fetching user repositories...")
    try:
        api_url = f"https://api.github.com/users/{username}/repos?sort=updated"
        repos = await fetch_github_api(api_url)
        repos = repos[:5]
        if not repos:
            await status_msg.edit_text("ℹ️ No repositories found for this user.")
            return
        results = []
        for idx, repo in enumerate(repos, 1):
            results.append(
                f"{idx}. *{repo['name']}*\n"
                f"   ⭐ Stars: `{repo['stargazers_count']}` | 📅 Updated: `{repo['updated_at'][:10]}`\n"
                f"   🔗 [Link](https://github.com/{username}/{repo['name']})"
            )
        await status_msg.edit_text(f"👤 *User:* `{username}` *Updated Repositories:*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Failed to fetch user:* {e}")

@github_router.message(Command("trend"))
async def github_trend_handler(message: Message):
    status_msg = await message.reply("🔍 Fetching weekly trending repositories...")
    try:
        since_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        api_url = f"https://api.github.com/search/repositories?q=created:>{since_date}&sort=stars&order=desc"
        data = await fetch_github_api(api_url)
        items = data.get("items", [])[:5]
        results = []
        for idx, item in enumerate(items, 1):
            results.append(
                f"{idx}. *{item['full_name']}*\n"
                f"   ⭐ Stars: `{item['stargazers_count']}` | 🗣️ Language: `{item.get('language') or 'None'}`\n"
                f"   🔗 [Link](https://github.com/{item['full_name']})"
            )
        await status_msg.edit_text("🔥 *GitHub Weekly Trending Repositories:*\n\n" + "\n\n".join(results))
    except Exception as e:
        await status_msg.edit_text(f"❌ *Failed to fetch trends:* {e}")

# =========================================================================
# Callback Query Dispatcher (Stateful Navigational Operations)
# =========================================================================

@github_router.callback_query(F.data.startswith("gh:"))
async def github_callback_handler(callback_query: CallbackQuery, bot: Bot):
    data = callback_query.data
    parts = data.split(":")

    gh_id = parts[1]
    action = parts[2]
    user_id = callback_query.from_user.id

    meta = GITHUB_CACHE.get(gh_id)
    if not meta:
        try:
            await callback_query.message.edit_text(
                text="⚠️ *Session Ended*\n\nThis console session has expired or the bot has been restarted. Please send a new link to start a new session."
            )
        except Exception:
            pass
        await callback_query.answer("Session expired.", show_alert=True)
        return

    owner = meta["owner"]
    repo = meta["repo"]
    back_gh_markup = get_back_keyboard(gh_id)

    if action == "close":
        GITHUB_CACHE.pop(gh_id, None)
        await callback_query.message.delete()
        await callback_query.answer("Console closed.")

    elif action == "back":
        await callback_query.message.edit_text(
            text=f"🐙 *GitHub Repository Browser*\n\n"
                 f"📁 *Repository:* `{owner}/{repo}`\n"
                 f"🔗 *URL:* https://github.com/{owner}/{repo}\n\n"
                 f"Select an action:",
            reply_markup=get_repo_menu_keyboard(gh_id)
        )
        await callback_query.answer()
    
    elif action == "tags":
        await callback_query.message.edit_text("🔍 Fetching tags...")
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/tags"
            data = await fetch_github_api(api_url)
            meta["tags"] = data[:10]
            if not data:
                await callback_query.message.edit_text("ℹ️ No tags found for this repository.", reply_markup=back_gh_markup)
            else:
                tag_lines = [f"{idx}. *{tag['name']}*" for idx, tag in enumerate(data[:10], start=1)]
                await callback_query.message.edit_text(
                    text=f"🏷️ *Tags inside: {owner}/{repo}*\nSelect a tag to download its ZIP package:\n\n" + "\n".join(tag_lines),
                    reply_markup=get_tags_keyboard(gh_id, data)
                )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch tags:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "tag":
        tag_index = int(parts[3])
        tags = meta.get("tags") or []
        if tag_index < 0 or tag_index >= len(tags):
            await callback_query.answer("⚠️ Tag session expired. Open tags again.", show_alert=True)
            return

        tag_name = tags[tag_index]["name"]
        meta["branch"] = tag_name
        await callback_query.message.edit_text("⏳ Request enqueued in Job Queue...")
        await callback_query.answer("Tag ZIP enqueued.")

        await enqueue_github_zip_job(
            callback_query=callback_query,
            user_id=user_id,
            owner=owner,
            repo=repo,
            source_url=repo_zip_url(owner, repo, tag_name),
            file_stem=f"{repo}_{tag_name}",
            description=f"{owner}/{repo}@{tag_name}"
        )

    elif action == "discussions":
        discussions_url = f"https://github.com/{owner}/{repo}/discussions"
        await callback_query.message.edit_text(
            text=f"💬 *Discussions: {owner}/{repo}*\n\n"
                 f"GitHub Discussions is a collaborative forum for community conversations, Q&A, and ideas.\n\n"
                 f"👉 {markdown_link('Open GitHub Discussions Page', discussions_url)}",
            reply_markup=back_gh_markup
        )
        await callback_query.answer()

    elif action == "zip":
        branch = current_branch(meta)
        branch_label = display_branch(meta)
        await callback_query.message.edit_text("⏳ Request enqueued in Job Queue...")
        await callback_query.answer("Repository ZIP enqueued.")
        await enqueue_github_zip_job(
            callback_query=callback_query,
            user_id=user_id,
            owner=owner,
            repo=repo,
            source_url=repo_zip_url(owner, repo, branch),
            file_stem=f"{repo}_{branch_label}",
            description=f"{owner}/{repo}@{branch_label}"
        )

    elif action == "info":
        await callback_query.message.edit_text("🔍 Fetching metadata...")
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}"
            data = await fetch_github_api(api_url)

            description = data.get("description") or "No Description Provided."
            stars = data.get("stargazers_count", 0)
            forks = data.get("forks_count", 0)
            issues = data.get("open_issues_count", 0)
            lang = data.get("language") or "None"
            created_at = data.get("created_at", "")[:10]
            license_name = data.get("license", {}).get("name") if data.get("license") else "None"

            await callback_query.message.edit_text(
                text=f"📊 *Repository Info: {owner}/{repo}*\n\n"
                     f"📝 *Description:* `{description}`\n\n"
                     f"⭐ Stars: `{stars}` | 🍴 Forks: `{forks}`\n"
                     f"📋 Issues: `{issues}` | 🗣️ Language: `{lang}`\n"
                     f"🛡️ License: `{license_name}`\n"
                     f"📅 Created: `{created_at}`",
                reply_markup=back_gh_markup
            )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch repository info:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "clone":
        clone_url = f"https://github.com/{owner}/{repo}.git"
        ssh_url = f"git@github.com:{owner}/{repo}.git"
        await callback_query.message.edit_text(
            text=f"🔗 *Clone Links: {owner}/{repo}*\n\n"
                 f"*HTTPS:*\n`git clone {clone_url}`\n\n"
                 f"*SSH:*\n`git clone {ssh_url}`",
            reply_markup=back_gh_markup
        )
        await callback_query.answer()

    elif action == "languages":
        await callback_query.message.edit_text("🔍 Fetching language stats...")
        try:
            data = await fetch_github_api(f"https://api.github.com/repos/{owner}/{repo}/languages")
            total = sum(data.values())
            if total == 0:
                text = f"📊 *Languages: {owner}/{repo}*\n\nNo language statistics available."
            else:
                lines = []
                for language, size in sorted(data.items(), key=lambda item: item[1], reverse=True)[:10]:
                    percent = (size / total) * 100
                    lines.append(f"• *{language}:* `{percent:.1f}%` (`{human_size(size)}`)")
                text = f"📊 *Languages: {owner}/{repo}*\n\n" + "\n".join(lines)
            await callback_query.message.edit_text(text, reply_markup=back_gh_markup)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch languages:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "license":
        await callback_query.message.edit_text("🔍 Fetching license...")
        try:
            data = await fetch_github_api(f"https://api.github.com/repos/{owner}/{repo}/license")
            license_info = data.get("license") or {}
            name = license_info.get("name") or data.get("name") or "Unknown"
            spdx = license_info.get("spdx_id") or "NOASSERTION"
            html_url = data.get("html_url") or f"https://github.com/{owner}/{repo}"
            text = f"📄 *License: {owner}/{repo}*\n\n*Name:* `{name}`\n*SPDX:* `{spdx}`\n🔗 {markdown_link('Open license file', html_url)}"
            await callback_query.message.edit_text(text, reply_markup=back_gh_markup)
        except FileNotFoundError:
            await callback_query.message.edit_text(f"ℹ️ No license file found for `{owner}/{repo}`.", reply_markup=back_gh_markup)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch license:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "contributors":
        await callback_query.message.edit_text("🔍 Fetching contributors...")
        try:
            data = await fetch_github_api(f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=10")
            if not data:
                text = f"👥 *Contributors: {owner}/{repo}*\n\nNo contributors found."
            else:
                lines = []
                for index, contributor in enumerate(data[:10], start=1):
                    login = contributor.get("login", "unknown")
                    contributions = contributor.get("contributions", 0)
                    profile_url = contributor.get("html_url", f"https://github.com/{login}")
                    lines.append(f"{index}. {markdown_link(login, profile_url)} — `{contributions}` commits")
                text = f"👥 *Contributors: {owner}/{repo}*\n\n" + "\n".join(lines)
            await callback_query.message.edit_text(text, reply_markup=back_gh_markup)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch contributors:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action in {"issues", "pulls"}:
        is_pulls = action == "pulls"
        label = "Pull Requests" if is_pulls else "Open Issues"
        emoji = "🔀" if is_pulls else "📋"
        endpoint = "pulls" if is_pulls else "issues"
        await callback_query.message.edit_text(f"🔍 Fetching {label.lower()}...")
        try:
            data = await fetch_github_api(f"https://api.github.com/repos/{owner}/{repo}/{endpoint}?state=open&per_page=10")
            if not is_pulls:
                data = [item for item in data if "pull_request" not in item]

            if not data:
                text = f"{emoji} *{label}: {owner}/{repo}*\n\nNo open items found."
            else:
                lines = []
                for index, item in enumerate(data[:10], start=1):
                    number = item.get("number")
                    title = item.get("title", "Untitled")
                    url = item.get("html_url", f"https://github.com/{owner}/{repo}")
                    lines.append(f"{index}. `#{number}` {markdown_link(title[:90], url)}")
                text = f"{emoji} *{label}: {owner}/{repo}*\n\n" + "\n".join(lines)
            await callback_query.message.edit_text(text, reply_markup=back_gh_markup)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch {label.lower()}:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "branches":
        await callback_query.message.edit_text("🔍 Fetching branches...")
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
            data = await fetch_github_api(api_url)
            meta["branches"] = data[:10]
            await callback_query.message.edit_text(
                text=f"🌿 *Branches inside: {owner}/{repo}*\nSelect a branch to download its ZIP package:",
                reply_markup=get_branches_keyboard(gh_id, data)
            )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch branches:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "releases":
        await callback_query.message.edit_text("🔍 Fetching releases...")
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
            data = await fetch_github_api(api_url)
            if not data:
                tags = await fetch_github_api(f"https://api.github.com/repos/{owner}/{repo}/tags")
                data = [{"tag_name": tag["name"], "published_at": None, "prerelease": False, "draft": False} for tag in tags[:10]]
            releases = data[:10]
            meta["releases"] = releases

            release_lines = []
            for index, release in enumerate(releases, start=1):
                tag = release.get("tag_name", "unknown")
                published_at = (release.get("published_at") or "")[:10] or "tag only"
                badges = []
                if release.get("prerelease"):
                    badges.append("pre-release")
                if release.get("draft"):
                    badges.append("draft")
                suffix = f" ({', '.join(badges)})" if badges else ""
                release_lines.append(f"{index}. *{tag}* | 📅 `{published_at}`{suffix}")

            if not release_lines:
                await callback_query.message.edit_text("ℹ️ No releases or tags found for this repository.", reply_markup=back_gh_markup)
            else:
                await callback_query.message.edit_text(
                    text=f"🏷️ *Releases for {owner}/{repo}*\n\n" + "\n".join(release_lines),
                    reply_markup=get_releases_keyboard(gh_id, releases)
                )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch releases:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "release":
        release_index = int(parts[3])
        releases = meta.get("releases") or []
        if release_index < 0 or release_index >= len(releases):
            await callback_query.answer("⚠️ Release session expired. Open releases again.", show_alert=True)
            return

        tag_name = releases[release_index]["tag_name"]
        meta["branch"] = tag_name
        await callback_query.message.edit_text("⏳ Release ZIP request enqueued in Job Queue...")
        await callback_query.answer("Release ZIP enqueued.")
        await enqueue_github_zip_job(
            callback_query=callback_query,
            user_id=user_id,
            owner=owner,
            repo=repo,
            source_url=repo_zip_url(owner, repo, tag_name),
            file_stem=f"{repo}_{tag_name}",
            description=f"{owner}/{repo}@{tag_name}"
        )

    elif action == "branch":
        branch_index = int(parts[3])
        branches = meta.get("branches") or []
        if branch_index < 0 or branch_index >= len(branches):
            await callback_query.answer("⚠️ Branch session expired. Open branches again.", show_alert=True)
            return

        branch_name = branches[branch_index]["name"]
        meta["branch"] = branch_name
        await callback_query.message.edit_text("⏳ Request enqueued in Job Queue...")
        await callback_query.answer("Branch ZIP enqueued.")

        await enqueue_github_zip_job(
            callback_query=callback_query,
            user_id=user_id,
            owner=owner,
            repo=repo,
            source_url=repo_zip_url(owner, repo, branch_name),
            file_stem=f"{repo}_{branch_name}",
            description=f"{owner}/{repo}@{branch_name}"
        )

    elif action == "commits":
        await callback_query.message.edit_text("🔍 Fetching commits...")
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
            data = await fetch_github_api(api_url)
            data = data[:5]

            commits_list = []
            for commit in data:
                sha = commit["sha"][:7]
                author = commit["commit"]["author"]["name"]
                message = commit["commit"]["message"].split("\n")[0]
                date = commit["commit"]["author"]["date"][:10]
                commits_list.append(f"• `{date}` | `[{sha}]` `{author}`: {message}")

            text = f"📜 *Last 5 Commits inside: {owner}/{repo}*\n\n" + "\n".join(commits_list)
            await callback_query.message.edit_text(text, reply_markup=back_gh_markup)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch commits:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "readme":
        await callback_query.message.edit_text("🔍 Fetching README...")
        try:
            headers = get_github_headers()
            headers["Accept"] = "application/vnd.github.v3.raw"
            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Failed to fetch raw README: {response.status}")
                    readme_text = await response.text()

            if len(readme_text) > 3500:
                os.makedirs("cache", exist_ok=True)
                temp_readme_path = f"cache/{gh_id}_README.txt"
                with open(temp_readme_path, "w", encoding="utf-8") as f:
                    f.write(readme_text)

                await upload_file_direct_to_bale(
                    method="sendDocument",
                    chat_id=user_id,
                    file_path=temp_readme_path,
                    caption=f"📖 *README File:* `{owner}/{repo}`"
                )
                if os.path.exists(temp_readme_path):
                    os.remove(temp_readme_path)
                await callback_query.message.edit_text("📥 README was too long for text limit and has been delivered as file.", reply_markup=back_gh_markup)
            else:
                await callback_query.message.edit_text(
                    text=f"📖 *README: {owner}/{repo}*\n\n```\n{readme_text}\n```",
                    reply_markup=back_gh_markup
                )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch README:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    # =========================================================================
    # File Explorer Stateful Handlers
    # =========================================================================
    elif action == "files":
        await callback_query.message.edit_text("🔍 Loading directory contents...")
        try:
            # Set up starting path boundaries
            meta["path"] = "/"
            meta["page"] = 1

            api_url = contents_api_url(owner, repo, "/", current_branch(meta))
            data = await fetch_github_api(api_url)
            meta["items_list"] = data  # Cache the items list in RAM

            total = len(data)
            start = 1
            end = min(8, total)
            keyboard = get_files_explorer_keyboard(gh_id, data, "/", 1)
            await callback_query.message.edit_text(
                text=f"📁 *Repository File Explorer*\n\n"
                     f"📦 *Repository:* `{owner}/{repo}`\n"
                     f"🌿 *Branch:* `{display_branch(meta)}`\n"
                     f"📂 *Active Path:* `/`\n"
                     f"📄 Page `{1}` | Showing `{start}-{end}` of `{total}` items:",
                reply_markup=keyboard
            )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to launch explorer:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "file_zip":
        path = meta.get("path", "/")
        branch = current_branch(meta)
        branch_label = display_branch(meta)
        folder_name = os.path.basename(path.strip("/")) if path != "/" else repo
        file_stem = f"{repo}_{folder_name}_{branch_label}"
        description = f"{owner}/{repo}:{path}@{branch_label}"
        await callback_query.message.edit_text("⏳ Folder ZIP request enqueued in Job Queue...")
        await callback_query.answer("Folder ZIP enqueued.")
        await enqueue_github_folder_zip_job(
            callback_query=callback_query,
            user_id=user_id,
            owner=owner,
            repo=repo,
            path=path,
            branch=branch,
            file_stem=file_stem,
            description=description
        )

    elif action.startswith("file_page"):
        target_page = int(parts[3])
        meta["page"] = target_page

        items = meta["items_list"]
        path = meta["path"]
        total = len(items)
        start = (target_page - 1) * 8 + 1
        end = min(target_page * 8, total)

        keyboard = get_files_explorer_keyboard(gh_id, items, path, target_page)
        await callback_query.message.edit_text(
            text=f"📁 *Repository File Explorer*\n\n"
                 f"📦 *Repository:* `{owner}/{repo}`\n"
                 f"🌿 *Branch:* `{display_branch(meta)}`\n"
                 f"📂 *Active Path:* `{path}`\n"
                 f"📄 Page `{target_page}` | Showing `{start}-{end}` of `{total}` items:",
            reply_markup=keyboard
        )
        await callback_query.answer()

    elif action == "file_up":
        await callback_query.message.edit_text("🔍 Moving to parent directory...")
        try:
            current_path = meta["path"]
            # Strip last directory node to get parent path (e.g. "/utils/gate" -> "/utils")
            parent_path = "/" + "/".join([node for node in current_path.split("/") if node][:-1])
            if parent_path == "":
                parent_path = "/"

            meta["path"] = parent_path
            meta["page"] = 1

            api_url = contents_api_url(owner, repo, parent_path, current_branch(meta))

            data = await fetch_github_api(api_url)
            meta["items_list"] = data

            total = len(data)
            start = 1
            end = min(8, total)
            keyboard = get_files_explorer_keyboard(gh_id, data, parent_path, 1)
            await callback_query.message.edit_text(
                text=f"📁 *Repository File Explorer*\n\n"
                     f"📦 *Repository:* `{owner}/{repo}`\n"
                     f"🌿 *Branch:* `{display_branch(meta)}`\n"
                     f"📂 *Active Path:* `{parent_path}`\n"
                     f"📄 Page `{1}` | Showing `{start}-{end}` of `{total}` items:",
                reply_markup=keyboard
            )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to navigate up:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action.startswith("file_nav"):
        item_idx = int(parts[3])
        items = meta["items_list"]
        selected_item = items[item_idx]
        item_type = selected_item["type"]
        item_name = selected_item["name"]
        item_path = selected_item["path"]

        if item_type == "dir":
            await callback_query.message.edit_text(f"🔍 Entering `{item_name}`...")
            try:
                meta["path"] = f"/{item_path}"
                meta["page"] = 1

                api_url = contents_api_url(owner, repo, item_path, current_branch(meta))
                data = await fetch_github_api(api_url)
                meta["items_list"] = data

                total = len(data)
                start = 1
                end = min(8, total)
                keyboard = get_files_explorer_keyboard(gh_id, data, f"/{item_path}", 1)
                await callback_query.message.edit_text(
                    text=f"📁 *Repository File Explorer*\n\n"
                         f"📦 *Repository:* `{owner}/{repo}`\n"
                         f"🌿 *Branch:* `{display_branch(meta)}`\n"
                         f"📂 *Active Path:* `/{item_path}`\n"
                         f"📄 Page `{1}` | Showing `{start}-{end}` of `{total}` items:",
                    reply_markup=keyboard
                )
            except Exception as e:
                await callback_query.message.edit_text(f"❌ *Failed to enter directory:* {e}", reply_markup=back_gh_markup)
            await callback_query.answer()

        elif item_type == "file":
            # Direct file download and transfer!
            await callback_query.answer(f"📥 Enqueueing download for {item_name}...", show_alert=True)

            async def queued_file_job():
                os.makedirs("cache", exist_ok=True)
                # Keep the original filename in the multipart upload while keeping the local path unique
                safe_name = safe_cache_filename(item_name)
                temp_file_path = f"cache/{gh_id}_{safe_name}"
                raw_download_url = selected_item["download_url"]

                try:
                    await stream_url_to_file(raw_download_url, temp_file_path)

                    # Send document directly with the original filename preserved
                    await upload_file_direct_to_bale(
                        method="sendDocument",
                        chat_id=user_id,
                        file_path=temp_file_path,
                        filename=item_name,
                        caption=f"📄 *File delivered:* `{item_name}`"
                    )

                    from main import log_event
                    await log_event(f"📄 **GitHub Explorer:** Successfully transferred file `{item_name}` for User `{user_id}`.")
                except Exception as e:
                    await callback_query.message.reply(text=f"❌ *Failed to download file {item_name}:* {e}")
                finally:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)

            # Enqueue file download
            await queue.add_task(user_id, callback_query.message, queued_file_job)
