# modules/github/api.py
import aiohttp
import config

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