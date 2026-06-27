# modules/translate/api.py
import aiohttp

async def google_translate_async(text: str, src_lang: str, dst_lang: str) -> str:
    """Direct asynchronous HTTP call to Google's translation API."""
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": src_lang,
        "tl": dst_lang,
        "dt": "t",
        "q": text
    }
    timeout = aiohttp.ClientTimeout(total=15, connect=10)
    import config
    async with aiohttp.ClientSession(timeout=timeout) as session:
        proxy = getattr(config, "AIOHTTP_PROXY", None)
        async with session.get(url, params=params, proxy=proxy) as response:
            if response.status != 200:
                raise RuntimeError(f"Google Translation API returned HTTP Error: {response.status}")
            result = await response.json()
            try:
                translations = [item[0] for item in result[0] if item[0]]
                return "".join(translations)
            except (IndexError, TypeError):
                raise ValueError("Failed to parse Google Translation API payload.")