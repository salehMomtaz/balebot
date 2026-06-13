# modules/github/router.py
import os
import re
import uuid
import glob
import shutil
import asyncio
import urllib.parse
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
    get_files_explorer_keyboard
)

github_router = Router()

# Stateful Session Cache mapping short IDs to real parameters
# Structure: { gh_id: { "owner": "...", "repo": "...", "path": "/", "page": 1, "items_list": [] } }
GITHUB_CACHE = {}

# Regex compilers for clean URL capture
REPO_REGEX = re.compile(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/?$")
SUB_REGEX = re.compile(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/(issues|pull|discussions)/(\d+)/?$")
GIST_REGEX = re.compile(r"https?://gist\.github\.com/([^/]+)/([a-f0-9]+)/?$")

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
        await callback_query.answer("⚠️ Session expired. Please resend your repository link.", show_alert=True)
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

    elif action == "branches":
        await callback_query.message.edit_text("🔍 Fetching branches...")
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
            data = await fetch_github_api(api_url)
            await callback_query.message.edit_text(
                text=f"🌿 *Branches inside: {owner}/{repo}*\nSelect a branch to download its ZIP package:",
                reply_markup=get_branches_keyboard(gh_id, data)
            )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch branches:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action.startswith("branch_select"):
        branch_name = parts[3]
        await callback_query.message.edit_text("⏳ Request enqueued in Job Queue...")
        
        async def queued_branch_zip_job():
            await callback_query.message.edit_text(f"⚡ Starting ZIP stream download for branch `{branch_name}`...")
            os.makedirs("cache", exist_ok=True)
            temp_zip_path = f"cache/{gh_id}_{repo}_{branch_name}.zip"
            zip_api_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{branch_name}"
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(zip_api_url, headers=get_github_headers()) as response:
                        if response.status != 200:
                            raise RuntimeError(f"GitHub returned HTTP Error: {response.status}")
                        with open(temp_zip_path, "wb") as f:
                            f.write(await response.read())
                            
                await callback_query.message.edit_text("📤 Uploading repository ZIP package...")
                
                from main import bot as main_bot
                await process_split_and_upload(
                    bot=main_bot,
                    chat_id=callback_query.message.chat.id,
                    file_path=temp_zip_path,
                    action='d',
                    title=f"{repo}_{branch_name}.zip",
                    uploader="GitHub",
                    duration=0,
                    thumb_path=None,
                    progress_msg=callback_query.message
                )
                from main import log_event
                await log_event(f"📦 **GitHub Cloner:** ZIP package of `{owner}/{repo}` (branch `{branch_name}`) uploaded.")
            except Exception as e:
                await callback_query.message.edit_text(f"❌ *GitHub Branch ZIP Cloner failed:* {e}", reply_markup=back_gh_markup)
                from main import log_event
                await log_event(f"❌ **GitHub Cloner Error:** Failed to clone branch `{branch_name}`. Details: `{str(e)}`")

        await queue.add_task(user_id, callback_query.message, queued_branch_zip_job)
        await callback_query.answer()

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
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
            data = await fetch_github_api(api_url)
            meta["items_list"] = data  # Cache the items list in RAM
            
            keyboard = get_files_explorer_keyboard(gh_id, data, "/", 1)
            await callback_query.message.edit_text(
                text=f"📁 *Repository File Explorer*\n\n"
                     f"📦 *Repository:* `{owner}/{repo}`\n"
                     f"📂 *Active Path:* `/`\n"
                     f"📄 Page `{1}` | Displaying `{len(data)}` items:",
                reply_markup=keyboard
            )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to launch explorer:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action.startswith("file_page"):
        target_page = int(parts[3])
        meta["page"] = target_page
        
        items = meta["items_list"]
        path = meta["path"]
        
        keyboard = get_files_explorer_keyboard(gh_id, items, path, target_page)
        await callback_query.message.edit_text(
            text=f"📁 *Repository File Explorer*\n\n"
                 f"📦 *Repository:* `{owner}/{repo}`\n"
                 f"📂 *Active Path:* `{path}`\n"
                 f"📄 Page `{target_page}` | Displaying `{len(items)}` items:",
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
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
            if parent_path != "/":
                api_url += f"{parent_path}"
                
            data = await fetch_github_api(api_url)
            meta["items_list"] = data
            
            keyboard = get_files_explorer_keyboard(gh_id, data, parent_path, 1)
            await callback_query.message.edit_text(
                text=f"📁 *Repository File Explorer*\n\n"
                     f"📦 *Repository:* `{owner}/{repo}`\n"
                     f"📂 *Active Path:* `{parent_path}`\n"
                     f"📄 Page `{1}` | Displaying `{len(data)}` items:",
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
                
                api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{item_path}"
                data = await fetch_github_api(api_url)
                meta["items_list"] = data
                
                keyboard = get_files_explorer_keyboard(gh_id, data, f"/{item_path}", 1)
                await callback_query.message.edit_text(
                    text=f"📁 *Repository File Explorer*\n\n"
                         f"📦 *Repository:* `{owner}/{repo}`\n"
                         f"📂 *Active Path:* `/{item_path}`\n"
                         f"📄 Page `{1}` | Displaying `{len(data)}` items:",
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
                temp_file_path = f"cache/{gh_id}_{item_name}"
                raw_download_url = selected_item["download_url"]
                
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(raw_download_url) as response:
                            if response.status != 200:
                                raise RuntimeError(f"Failed to fetch raw file: {response.status}")
                            with open(temp_file_path, "wb") as f:
                                f.write(await response.read())
                                
                    # Send document directly
                    await upload_file_direct_to_bale(
                        method="sendDocument",
                        chat_id=user_id,
                        file_path=temp_file_path,
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