"""Fetches the user's OWN business site live, so impact/recommendation reasoning is
grounded in what the site actually currently says - not just the free-text
description typed into config/business.json, which can drift out of date or omit
things (features, exact pricing wording, positioning) the owner didn't think to type.
"""

from strands import tool

from src.tools.fetch_tool import fetch_page
from src.trace import log_step

_EXCERPT_CHARS = 3000


@tool
def research_own_business(site: str) -> dict:
    """Fetch the user's own business site live and return its actual current content, so later analysis can be grounded in real current pricing/features/positioning rather than only the typed description.

    Args:
        site: The business's own site, e.g. "frenchly.app" or "https://frenchly.app".
    """
    url = site if site.startswith(("http://", "https://")) else f"https://{site}"
    text = fetch_page(url)

    if text.startswith("ERROR:"):
        log_step("own_site", url=url, result="error")
        return {"fetched": False, "url": url, "content": ""}

    log_step("own_site", url=url, result="ok", chars=len(text))
    return {"fetched": True, "url": url, "content": text[:_EXCERPT_CHARS]}
