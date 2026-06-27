import os

# Helper to load numeric env vars safely
def get_env_int(key: str, default: int) -> int:
    val = os.getenv(key, "")
    if val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
        return int(val)
    return default


def _proxy_url() -> str | None:
    """Return a single SOCKS5/HTTP proxy URL from legacy or conventional env vars."""
    for key in ("SOCKS5_PROXY", "ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        val = os.getenv(key, "").strip()
        if val and val.lower() != "none":
            return val
    return None

# Bale Bot API token (from @botfather on Bale)
BALE_TOKEN = os.getenv("BALE_TOKEN", "YOUR_BALE_TOKEN_HERE")

# Hardcoded Creator ID (Your numeric Bale User ID)
SYSTEM_CREATOR_ID = get_env_int("SYSTEM_CREATOR_ID", 0)

# Private Bale Log Channel ID (e.g. -100123456789)
LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID", 0)  # Leave 0 if not used

# GitHub Personal Access Token (PAT) with basic read scopes
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_PAT_HERE")

# ---------------------------------------------------------------------------
# Optional proxy configuration (only needed in blocked networks like your WSL)
# On a foreign VPS where YouTube/X/Instagram/TikTok are reachable, leave unset.
# Examples:
#   SOCKS5_PROXY=socks5://127.0.0.1:10808
#   ALL_PROXY=socks5://127.0.0.1:10808
#   HTTP_PROXY=http://127.0.0.1:10809
# ---------------------------------------------------------------------------
PROXY_URL = _proxy_url()
AIOHTTP_PROXY = PROXY_URL  # Used by all aiohttp ClientSession calls
YTDLP_PROXY = PROXY_URL    # Passed to yt-dlp's 'proxy' option
REQUESTS_PROXY = PROXY_URL # Used by utils.logger (Bale log channel)

# Database and Cookie paths
DB_FILE = "database.json"
YT_COOKIES = "ytcookies.txt"
IG_COOKIES = "igcookies.txt"
TT_COOKIES = "ttcookies.txt"
X_COOKIES = "xcookies.txt"
COOKIES_FILE = "cookies.txt"