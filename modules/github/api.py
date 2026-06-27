# modules/github/api.py
import aiohttp
import config

def get_github_headers() -> dict:
    """Generate headers with auth keys if present to elevate rate limits to 5,000/hr."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "balebot-github-assistant"
    }
    github_token = (config.GITHUB_TOKEN or "").strip()
    if github_token and github_token != "YOUR_GITHUB_PAT_HERE":
        headers["Authorization"] = f"token {github_token}"
    return headers

async def fetch_github_api(url: str) -> dict:
    """Helper to perform non-blocking async GET requests to GitHub API."""
    import config
    timeout = aiohttp.ClientTimeout(total=45, connect=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        proxy = getattr(config, "AIOHTTP_PROXY", None)
        async with session.get(url, headers=get_github_headers(), proxy=proxy) as response:
            if response.status == 403:
                raise RuntimeError("GitHub API Rate limit exceeded. Please configure GITHUB_TOKEN.")
            if response.status == 404:
                raise FileNotFoundError("Specified GitHub resource not found.")
            if response.status != 200:
                raise RuntimeError(f"GitHub returned HTTP Error: {response.status}")
            return await response.json()
