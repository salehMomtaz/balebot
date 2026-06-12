import os

# Bale Bot API token (from @botfather on Bale)
BALE_TOKEN = os.getenv("BALE_TOKEN", "YOUR_BALE_TOKEN_HERE")

# Hardcoded Creator ID (Your numeric Bale User ID)
SYSTEM_CREATOR_ID = int(os.getenv("SYSTEM_CREATOR_ID", "YOUR_NUMERIC_ID_HERE"))

# Private Bale Log Channel ID (e.g. -100123456789)
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))  # Leave 0 if not used

# GitHub Personal Access Token (PAT) with basic read scopes
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_PAT_HERE")

# FastAPI / Streaming configurations
# Example: "https://www.knxv.ir:9090" or "http://YOUR_VPS_IP:9090"
DOMAIN = os.getenv("DOMAIN", "http://YOUR_VPS_IP:9090") 

# Database and Cookie paths
DB_FILE = "database.json"
YT_COOKIES = "ytcookies.txt"
IG_COOKIES = "igcookies.txt"
TT_COOKIES = "ttcookies.txt"
X_COOKIES = "xcookies.txt"
COOKIES_FILE = "cookies.txt"

# SSL Certificate Paths (Optional: Leave empty "" to run over standard HTTP on port 9090)
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "")
SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "")