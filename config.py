import os

# Helper to load numeric env vars safely
def get_env_int(key: str, default: int) -> int:
    val = os.getenv(key, "")
    if val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
        return int(val)
    return default

# Bale Bot API token (from @botfather on Bale)
BALE_TOKEN = os.getenv("BALE_TOKEN", "YOUR_BALE_TOKEN_HERE")

# Hardcoded Creator ID (Your numeric Bale User ID)
SYSTEM_CREATOR_ID = get_env_int("SYSTEM_CREATOR_ID", 0)

# Private Bale Log Channel ID (e.g. -100123456789)
LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID", 0)  # Leave 0 if not used

# GitHub Personal Access Token (PAT) with basic read scopes
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_PAT_HERE")

# Database and Cookie paths
DB_FILE = "database.json"
YT_COOKIES = "ytcookies.txt"
IG_COOKIES = "igcookies.txt"
TT_COOKIES = "ttcookies.txt"
X_COOKIES = "xcookies.txt"
COOKIES_FILE = "cookies.txt"