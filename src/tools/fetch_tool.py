"""Stage 1 — fetch public competitor pages (pricing, blog, changelog) as clean text.

Plain HTTP GET only. No login, no JS rendering, no social/SEO APIs.
"""

import re

import requests
from bs4 import BeautifulSoup
from strands import tool

from src.trace import log_step

_USER_AGENT = "CompetitorWatchAgent/0.1 (+hackathon project; public-page fetch only)"
_TIMEOUT_SECONDS = 15
_MAX_CHARS = 6_000  # keep page text bounded so diffs stay cheap for the orchestrator to reason/pass around


_ZERO_PLUS_COUNTER_PATTERN = re.compile(r"^0\+(\s+\S.*)?$", re.MULTILINE)


def _flag_unrendered_counters(text: str) -> str:
    """"0+" is how a JS count-up animation (e.g. "1,500,000+ Parcels") looks in the raw
    HTML we fetch, since plain requests+BeautifulSoup never runs the script that would
    animate it to its real value. Nobody intentionally advertises "0+ customers" - so
    this pattern is flagged rather than passed through as if it were a real stat (a
    wrong "covers 0 counties" claim in a report is worse than admitting we don't know)."""
    return _ZERO_PLUS_COUNTER_PATTERN.sub(r"[STAT UNAVAILABLE - likely an unrendered JS counter, not a real 0]\1", text)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _flag_unrendered_counters(text)
    return text[:_MAX_CHARS]


@tool
def fetch_page(url: str) -> str:
    """Fetch a single public web page (e.g. a competitor's pricing or blog page) and return its visible text content, stripped of HTML/scripts/nav chrome.

    Args:
        url: The full URL of the public page to fetch.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        log_step("fetch", url=url, status="error", error=str(exc))
        return f"ERROR: could not fetch {url}: {exc}"

    text = _html_to_text(response.text)
    log_step("fetch", url=url, status="ok", chars=len(text))
    return text


def fetch_competitor_pages(urls: list[str]) -> dict[str, str]:
    """Fetch multiple URLs and return a dict of url -> text content (helper, not exposed as an SDK tool)."""
    return {url: fetch_page(url) for url in urls}
