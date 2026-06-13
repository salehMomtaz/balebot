# modules/github/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_repo_menu_keyboard(gh_id: str) -> InlineKeyboardMarkup:
    """Returns the main, compact control panel keyboard for GitHub repository links."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Download (ZIP)", callback_data=f"gh:{gh_id}:zip")],
        [InlineKeyboardButton(text="🌿 Branches", callback_data=f"gh:{gh_id}:branches"), InlineKeyboardButton(text="📜 Commits", callback_data=f"gh:{gh_id}:commits")],
        [InlineKeyboardButton(text="📖 README", callback_data=f"gh:{gh_id}:readme"), InlineKeyboardButton(text="📁 Files", callback_data=f"gh:{gh_id}:files")],
        [InlineKeyboardButton(text="📊 Info", callback_data=f"gh:{gh_id}:info"), InlineKeyboardButton(text="❌ Close Console", callback_data=f"gh:{gh_id}:close")]
    ])

def get_back_keyboard(gh_id: str) -> InlineKeyboardMarkup:
    """Returns the standard back button returning to the main repository index."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Back to Repo Menu", callback_data=f"gh:{gh_id}:back")]
    ])

def get_branches_keyboard(gh_id: str, branches: list) -> InlineKeyboardMarkup:
    """Generates inline buttons for every branch. Clicking a branch downloads its ZIP."""
    keyboard_rows = []
    for branch in branches[:10]:  # Limit to top 10 branches for UI safety
        name = branch["name"]
        keyboard_rows.append([InlineKeyboardButton(text=f"🌿 {name}", callback_data=f"gh:{gh_id}:branch_select:{name}")])
    keyboard_rows.append([InlineKeyboardButton(text="◀️ Back to Repo Menu", callback_data=f"gh:{gh_id}:back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

def get_releases_keyboard(gh_id: str, releases: list) -> InlineKeyboardMarkup:
    """Generates inline buttons to download assets of specific release versions."""
    keyboard_rows = []
    for rel in releases[:5]:  # Limit to last 5 releases for UI safety
        tag = rel["tag_name"]
        keyboard_rows.append([InlineKeyboardButton(text=f"📦 Download {tag}", callback_data=f"gh:{gh_id}:rel_select:{tag}")])
    keyboard_rows.append([InlineKeyboardButton(text="◀️ Back to Repo Menu", callback_data=f"gh:{gh_id}:back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

def get_files_explorer_keyboard(gh_id: str, items: list, path: str, page: int) -> InlineKeyboardMarkup:
    """
    Builds the active, pageable File Explorer inline keyboard.
    Splits items into 8-per-page lists with Back, Up, and Page navigation buttons.
    """
    keyboard_rows = []
    
    # 1. Add Parent Directory navigation button if we are inside a subfolder
    if path != "/":
        keyboard_rows.append([InlineKeyboardButton(text="📁 .. Parent Directory", callback_data=f"gh:{gh_id}:file_up")])
        
    # 2. Paginate items safely (8 per page)
    start_idx = (page - 1) * 8
    end_idx = start_idx + 8
    page_items = items[start_idx:end_idx]
    
    for idx, item in enumerate(page_items):
        name = item["name"]
        item_type = item["type"]
        actual_index = start_idx + idx
        
        # Format labels
        emoji = "📁" if item_type == "dir" else "📄"
        label = f"{emoji} {name}"
        keyboard_rows.append([InlineKeyboardButton(text=label, callback_data=f"gh:{gh_id}:file_nav:{actual_index}")])
        
    # 3. Add Pagination Buttons
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"gh:{gh_id}:file_page:{page - 1}"))
    if end_idx < len(items):
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"gh:{gh_id}:file_page:{page + 1}"))
        
    if nav_row:
        keyboard_rows.append(nav_row)
        
    # 4. Add Back button
    keyboard_rows.append([InlineKeyboardButton(text="◀️ Back to Repo Menu", callback_data=f"gh:{gh_id}:back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)