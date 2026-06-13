# modules/direct_dl/api.py
import urllib.parse
import aiohttp

async def fetch_markdown_text(url: str) -> tuple[str, str]:
    """
    Queries the official urltomarkdown API asynchronously.
    Extracts clear markdown formatting and retrieves the page title natively from HTTP headers.
    """
    encoded_url = urllib.parse.quote(url, safe="")
    api_url = f"https://urltomarkdown.herokuapp.com/?url={encoded_url}&title=true&links=false"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"urltomarkdown API returned HTTP error: {response.status}")
            
            raw_title = response.headers.get("X-Title", "Webpage")
            title = urllib.parse.unquote(raw_title).strip()
            markdown_text = await response.text()
            return title, markdown_text