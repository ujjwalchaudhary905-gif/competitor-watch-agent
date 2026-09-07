"""Company profile enrichment - reads a competitor's own public About/Team page (if
one exists) and summarizes who's behind it and notable facts, straight from their own
published words. This is deliberately NOT LinkedIn or any social/login-gated source -
same "their own public page" pattern as pricing/blog, just a different page.
"""

import re

from pydantic import BaseModel, Field
from strands import Agent, tool

from src.model import get_model
from src.tools.discover_tool import _looks_like_real_page
from src.tools.fetch_tool import fetch_page
from src.trace import log_step

_ABOUT_PATHS = ["/about", "/about-us", "/team", "/company", "/who-we-are", "/our-story"]

_SYSTEM_PROMPT = """You are a research analyst summarizing a company's own About/Team
page for a competing small business owner. Extract only facts actually stated on the
page (founders/leadership named, founding story, company size/age, mission, notable
achievements) - never infer or invent anything not present in the text. If the page
has little substantive content, say so plainly rather than padding the summary.
"""


class CompanyProfile(BaseModel):
    summary: str = Field(description="2-4 sentences on who's behind the company and what's notable, based only on the page text.")
    facts: list[str] = Field(description="Specific facts found on the page (e.g. founder names, founding year, team size, mission statement).")


@tool
def research_company_profile(competitor_id: str, competitor_name: str, domain: str) -> dict:
    """Look for a competitor's own public About/Team page and summarize who's behind the company and notable facts, straight from their own published words (never invented, never from LinkedIn or any social/login-gated source).

    Args:
        competitor_id: Short identifier for the competitor.
        competitor_name: The competitor's display name.
        domain: Bare domain, e.g. "vagaro.com" (no scheme, no "www.").
    """
    domain = domain.lower().removeprefix("www.").strip("/")
    domain = re.sub(r"^https?://", "", domain)

    page_text = None
    found_url = None
    for path in _ABOUT_PATHS:
        url = f"https://{domain}{path}"
        text = fetch_page(url)
        if _looks_like_real_page(text):
            page_text = text
            found_url = url
            break

    if page_text is None:
        log_step("profile", competitor_name=competitor_name, result="no_about_page_found")
        return {"found": False, "summary": "No public About/Team page found for this competitor."}

    agent = Agent(model=get_model(), system_prompt=_SYSTEM_PROMPT)
    result = agent(
        [{"role": "user", "content": [{"text": f"About page for {competitor_name} ({found_url}):\n\n{page_text}"}]}],
        structured_output_model=CompanyProfile,
    )
    profile: CompanyProfile = result.structured_output

    log_step("profile", competitor_name=competitor_name, url=found_url, result="found", facts=profile.facts)
    return {"found": True, "url": found_url, "summary": profile.summary, "facts": profile.facts}
