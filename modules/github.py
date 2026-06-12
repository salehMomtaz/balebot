# modules/github.py
import os
import re
import uuid
import asyncio
from datetime import datetime, timedelta
import aiohttp
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery,
    FSInputFile
)
import config
from utils.gate import is_authorized
from utils.shared import queue, DOWNLOAD_CACHE
from utils.uploader_handler import process_split_and_upload

# Initialize the modular GitHub router
github_router = Router()

# In-memory dictionary to protect callback_data from exceeding 64 bytes
# Structure: { "gh_abcd1234": { "owner": "...", "repo": "..." } }
GITHUB_CACHE = {}

# Regex compilers for clean URL capture
REPO_REGEX = re.compile(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/?$")
SUB_REGEX = re.compile(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/(issues|pull|discussions)/(\d+)/?$")
GIST_REGEX = re.compile(r"https?://gist\.github\.com/([^/]+)/([a-f0-9]+)/?$")

def get_github_headers() -> dict:
    """Generate headers with auth keys if present to elevate rate limits to 5,000/hr."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "balebot-github-assistant"
    }
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"token {config.GITHUB_TOKEN}"
    return headers

async def fetch_github_api(url: str) -> dict:
    """Helper to perform non-blocking async GET requests to GitHub API."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=get_github_headers(), timeout=15) as response:
            if response.status == 403:
                raise RuntimeError("GitHub API Rate limit exceeded. Please configure GITHUB_TOKEN.")
            if response.status == 404:
                raise FileNotFoundError("Specified GitHub resource not found.")
            if response.status != 200:
                raise RuntimeError(f"GitHub returned HTTP Error: {response.status}")
            return await response.json()

# =========================================================================
# Group 1 Handlers: Link Interceptors
# =========================================================================

@github_router.message(
    filters.text & 
    filters.private & 
    filters.create(lambda _, __, m: REPO_REGEX.match(m.text.strip().split("|")[0].strip()) is not None),
    group=1
)
async def github_repo_link_handler(message: Message):
    """Intercepts standard repository links and presents the control panel."""
    user_id = message.from_user.id
    if not is_authorized(user_id):
        return
        
    text = message.text.strip().split("|")[0].strip()
    match = REPO_REGEX.match(text)
    owner = match.group(1)
    repo = match.group(2)
    
    # Generate unique 8-character ID and save to cache
    gh_id = f"gh_{str(uuid.uuid4())[:8]}"
    GITHUB_CACHE[gh_id] = {"owner": owner, "repo": repo}
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Download (ZIP)", callback_data=f"gh:{gh_id}:zip")],
        [InlineKeyboardButton(text="🌿 Branches", callback_data=f"gh:{gh_id}:branches"), InlineKeyboardButton(text="📜 Commits", callback_data=f"gh:{gh_id}:commits")],
        [InlineKeyboardButton(text="📖 README", callback_data=f"gh:{gh_id}:readme"), InlineKeyboardButton(text="📊 Info", callback_data=f"gh:{gh_id}:info")],
        [InlineKeyboardButton(text="❌ Close Console", callback_data=f"gh:{gh_id}:close")]
    ])
    
    await message.reply(
        text=f"🐙 *GitHub Repository Browser*\n\n"
             f"📁 *Repository:* `{owner}/{repo}`\n"
             f"🔗 *URL:* https://github.com/{owner}/{repo}\n\n"
             f"Select an administration action:",
        reply_markup=keyboard
    )

@github_router.message(
    filters.text & 
    filters.private & 
    filters.create(lambda _, __, m: SUB_REGEX.match(m.text.strip()) is not None),
    group=1
)
async def github_sub_link_handler(message: Message):
    """Intercepts issues, pull requests, and discussions links directly."""
    user_id = message.from_user.id
    if not is_authorized(user_id):
        return
        
    text = message.text.strip()
    match = SUB_REGEX.match(text)
    owner, repo, sub_type, num = match.groups()
    
    # GitHub unifies both Issues and PRs under the issues endpoint for metadata
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
        
        # Truncate body preview safely
        body_preview = body[:400] + "..." if len(body) > 400 else body
        
        emoji = "📋"
        if sub_type == "pull":
            emoji = "🔀"
        elif sub_type == "discussions":
            emoji = "💬"
            
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
    filters.text & 
    filters.private & 
    filters.create(lambda _, __, m: GIST_REGEX.match(m.text.strip()) is not None),
    group=1
)
async def github_gist_link_handler(message: Message, bot: Bot):
    """Intercepts Gist links and delivers raw files directly."""
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
            file_size = file_data.get("size", 0)
            
            # Write file locally and send
            temp_path = f"cache/{uuid.uuid4().hex[:6]}_{filename}"
            async with aiohttp.ClientSession() as session:
                async with session.get(raw_url) as response:
                    if response.status == 200:
                        with open(temp_path, "wb") as f:
                            f.write(await response.read())
                            
            # Native send
            await bot.send_document(
                chat_id=user_id,
                document=FSInputFile(temp_path),
                caption=f"📁 *Gist File:* `{filename}`"
            )
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ *Failed to fetch Gist:* {e}")

# =========================================================================
# Group 1 Handlers: Search and Trend Commands
# =========================================================================

@github_router.message(Command("search"))
async def github_search_handler(message: Message):
    """Allows searching repositories based on stars."""
    query = message.text[7:].strip()
    if not query:
        await message.reply("⚠️ *Usage:* `/search <query>` (e.g. `/search django`)")
        return
        
    status_msg = await message.reply("🔍 Searching GitHub...")
    try:
        api_url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&sort=stars&order=desc"
        data = await fetch_github_api(api_url)
        items = data.get("items", [])[:5]
        
        if not items:
            await status_msg.edit_text("ℹ️ No repositories found matching your query.")
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
    """Lists the last 5 updated repositories of a user."""
    username = message.text[5:].strip()
    if not username:
        await message.reply("⚠️ *Usage:* `/user <username>` (e.g. `/user torvalds`)")
        return
        
    status_msg = await message.reply("🔍 Fetching user repositories...")
    try:
        api_url = f"https://api.github.com/users/{username}/repos?sort=updated"
        repos = await fetch_github_api(api_url)[:5]
        
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
    """Calculates weekly trends by searching repos created in the last 7 days sorted by stars."""
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
# Group 2 Callback Dispatcher: Handles Inline Button Operations
# =========================================================================

@github_router.callback_query(F.data.startswith("gh:"))
async def github_callback_handler(callback_query: CallbackQuery, bot: Bot):
    data = callback_query.data
    _, gh_id, action = data.split(":")
    user_id = callback_query.from_user.id
    
    meta = GITHUB_CACHE.get(gh_id)
    if not meta:
        await callback_query.answer("⚠️ Session expired. Please send the link again.", show_alert=True)
        return
        
    owner = meta["owner"]
    repo = meta["repo"]
    
    # Common Back markup definition
    back_gh_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Back to Repo Menu", callback_data=f"gh:{gh_id}:back")]
    ])

    if action == "close":
        GITHUB_CACHE.pop(gh_id, None)
        await callback_query.message.delete()
        await callback_query.answer("Console closed.")
        
    elif action == "back":
        doc_status = "✅" if is_document_mode(user_id) else "❌"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Download (ZIP)", callback_data=f"gh:{gh_id}:zip")],
            [InlineKeyboardButton(text="🌿 Branches", callback_data=f"gh:{gh_id}:branches"), InlineKeyboardButton(text="📜 Commits", callback_data=f"gh:{gh_id}:commits")],
            [InlineKeyboardButton(text="📖 README", callback_data=f"gh:{gh_id}:readme"), InlineKeyboardButton(text="📊 Info", callback_data=f"gh:{gh_id}:info")],
            [InlineKeyboardButton(text="❌ Close Console", callback_data=f"gh:{gh_id}:close")]
        ])
        await callback_query.message.edit_text(
            text=f"🐙 *GitHub Repository Browser*\n\n"
                 f"📁 *Repository:* `{owner}/{repo}`\n"
                 f"🔗 *URL:* https://github.com/{owner}/{repo}\n\n"
                 f"Select an administration action:",
            reply_markup=keyboard
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
            branches_list = [f"• `{branch['name']}`" for branch in data]
            text = f"🌿 *Branches inside: {owner}/{repo}*\n\n" + "\n".join(branches_list)
            await callback_query.message.edit_text(text, reply_markup=back_gh_markup)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch branches:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "commits":
        await callback_query.message.edit_text("🔍 Fetching commits...")
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
            data = await fetch_github_api(api_url)[:5]
            
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
            # We request raw README content using specialized header
            headers = get_github_headers()
            headers["Accept"] = "application/vnd.github.v3.raw"
            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Failed to fetch raw README: {response.status}")
                    readme_text = await response.text()
            
            # Safe boundary check: if README exceeds 3,500 characters, upload as a .txt file
            if len(readme_text) > 3500:
                os.makedirs("cache", exist_ok=True)
                temp_readme_path = f"cache/{gh_id}_README.txt"
                with open(temp_readme_path, "w", encoding="utf-8") as f:
                    f.write(readme_text)
                    
                await bot.send_document(
                    chat_id=user_id,
                    document=FSInputFile(temp_readme_path),
                    caption=f"📖 *README File:* `{owner}/{repo}`"
                )
                if os.path.exists(temp_readme_path):
                    os.remove(temp_readme_path)
                    
                await callback_query.message.edit_text("📥 README was too long for text limit and has been delivered as a file attachment.", reply_markup=back_gh_markup)
            else:
                await callback_query.message.edit_text(
                    text=f"📖 *README: {owner}/{repo}*\n\n```\n{readme_text}\n```",
                    reply_markup=back_gh_markup
                )
        except Exception as e:
            await callback_query.message.edit_text(f"❌ *Failed to fetch README:* {e}", reply_markup=back_gh_markup)
        await callback_query.answer()

    elif action == "zip":
        # Dynamic async queue download job
        await callback_query.message.edit_text("⏳ Download request enqueued in Job Queue...")
        
        async def queued_zip_job():
            await callback_query.message.edit_text("⚡ Starting ZIP stream download from GitHub...")
            os.makedirs("cache", exist_ok=True)
            temp_zip_path = f"cache/{gh_id}_{repo}.zip"
            zip_api_url = f"https://api.github.com/repos/{owner}/{repo}/zipball"
            
            try:
                # Direct chunked file stream from GitHub to save RAM
                async with aiohttp.ClientSession() as session:
                    async with session.get(zip_api_url, headers=get_github_headers()) as response:
                        if response.status != 200:
                            raise RuntimeError(f"GitHub returned HTTP Error: {response.status}")
                        with open(temp_zip_path, "wb") as f:
                            f.write(await response.read())
                            
                await callback_query.message.edit_text("📤 Uploading repository ZIP package...")
                
                # Handover to Toyota sequential splitting uploader (Capped at 48MB parts!)
                from main import app, premium_app
                await process_split_and_upload(
                    bot_client=app,
                    premium_client=premium_app,
                    chat_id=callback_query.message.chat.id,
                    file_path=temp_zip_path,
                    action='d',
                    title=f"{repo}.zip",
                    uploader="GitHub",
                    duration=0,
                    thumb_path=None,
                    progress_msg=callback_query.message
                )
                
                GITHUB_CACHE.pop(gh_id, None)
                from main import log_event
                await log_event(f"📦 **GitHub Cloner:** ZIP package of `{owner}/{repo}` successfully uploaded.")
                
            except Exception as e:
                await callback_query.message.edit_text(f"❌ *GitHub ZIP Cloner failed:* {e}", reply_markup=back_gh_markup)
                from main import log_event
                await log_event(f"❌ **GitHub Cloner Error:** Failed to clone `{owner}/{repo}`. Details: `{str(e)}`")

        await queue.add_task(user_id, callback_query.message, queued_zip_job)