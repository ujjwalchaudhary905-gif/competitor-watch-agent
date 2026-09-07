"""Competitor discovery — for a user who doesn't know who their competitors are.

Candidates come from three sources, tried in order, all then verified the same way:
1. Real web content FIRST - search "<business> alternatives"/"competitors", fetch a
   real "alternatives" page (e.g. a G2/listicle-style page), and have a nested Agent
   verify it's actually about the same business (names collide) before extracting the
   competitor names actually listed there. This catches current/niche competitive
   dynamics a model's training data alone can miss (a small or recently-relevant
   competitor won't be in memory but will be in current web content).
2. Category/feature search, if #1 finds nothing usable - some niches have no
   G2/listicle presence at all (verified live: a digital play-therapy tool had none),
   so this searches by product category/feature phrases instead of business name and
   treats organic search results themselves as candidate competitor homepages.
3. A nested Agent's own knowledge, as a final fallback/supplement, proposing real,
   currently-operating competitor names AND their likely domain from memory.

Every candidate from either source is verified with a live fetch (never trusted
blindly) - if the given/guessed domain doesn't resolve, a keyless web search
(DuckDuckGo's HTML endpoint) is a fallback before giving up on that candidate. Common
pricing/blog paths are then probed with real fetches to find working URLs.
"""

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from strands import Agent, tool

from src.model import get_model
from src.tools.fetch_tool import fetch_page
from src.tools.worthiness_tool import assess_competitor_worthiness
from src.trace import log_step

_SEARCH_TIMEOUT = 15
# DuckDuckGo's HTML endpoint bot-detects non-browser User-Agents (and rate-limits
# aggressively regardless), so this is only a fallback - the primary path is the LLM's
# own knowledge of the company's domain, verified by a real fetch.
_SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_NON_PRIMARY_DOMAINS = {
    "facebook.com", "linkedin.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "wikipedia.org", "reddit.com", "g2.com", "capterra.com",
    "trustpilot.com", "crunchbase.com", "glassdoor.com", "producthunt.com",
    "apps.apple.com", "play.google.com", "medium.com",
}

_PRICING_PATHS = ["/pricing", "/plans", "/pricing-plans", "/price"]
_BLOG_PATHS = ["/blog", "/changelog", "/updates", "/news", "/resources"]

_SYSTEM_PROMPT = """You are a market research analyst. Given a small business's own
profile (name, site, description, pricing, and target region if given), name real,
currently operating companies that compete for the SAME specific customer with the
SAME specific need described - not just the same broad industry. If the business
serves a narrow niche (a specific exam, certification, region, profession, or customer
segment), prioritize competitors that target that exact same niche over generic
category leaders that merely happen to touch the same broad space. A niche competitor
most people haven't heard of is a better answer than a famous generalist that only
overlaps loosely.

If a target region is given, this is a hard filter, not a nice-to-have: prioritize
competitors that actually serve customers in that region. A well-known company that
doesn't operate or ship there is not a useful competitor even if the product category
matches - regional availability, pricing, and market presence matter as much as the
product/niche match.

For each candidate, give its actual public website domain (e.g. "vagaro.com", not a
URL, no "www.") and explain in "reason" specifically how directly it competes for the
same customer/need (not just "same industry"), including region-fit if a region was given.

Use your general knowledge of the industry. Only name real companies you are
confident actually exist and are still operating, with a domain you are confident is
correct - never invent a company or guess at a domain you're not sure of. If you
genuinely don't know enough real, tightly-relevant competitors to reach the requested
count, return fewer rather than padding the list with loosely-relevant generalists.
"""


class CandidateCompetitor(BaseModel):
    name: str = Field(description="The real company's name.")
    domain: str = Field(description='Bare domain, e.g. "vagaro.com" - no scheme, no "www.".')
    reason: str = Field(description="One sentence on why this is a relevant competitor.")


class CompetitorCandidates(BaseModel):
    candidates: list[CandidateCompetitor]


def _propose_candidates(
    business_name: str,
    business_description: str,
    count: int,
    region: str = "",
    exclude_names: list[str] | None = None,
) -> list[CandidateCompetitor]:
    exclude_block = (
        f"\nDo NOT repeat any of these already-considered names: {', '.join(exclude_names)}.\n"
        if exclude_names
        else ""
    )
    region_block = f"Target region: {region}\n" if region else ""

    agent = Agent(model=get_model(), system_prompt=_SYSTEM_PROMPT)
    result: CompetitorCandidates = agent.structured_output(
        CompetitorCandidates,
        (
            f"MY BUSINESS:\nName: {business_name}\nDescription: {business_description}\n{region_block}"
            f"{exclude_block}\n"
            f"Name up to {count} real competitors with their domains."
        ),
    )
    return result.candidates[:count]


_WEB_EXTRACTION_SYSTEM_PROMPT = """You are verifying and extracting real competitor
names from a webpage that claims to list alternatives/competitors for a specific
business.

FIRST, check whether this page is actually about the SAME business as the one
described - company names collide (e.g. two unrelated companies both named "Accord").
If this page's own description of the business doesn't match what's given (different
product category, different core function), set same_business to false and return no
candidates - do not force a match.

If it IS the same business, extract the real competitor/alternative company names
ACTUALLY LISTED on this page (never invent one that isn't there), and give each one's
real public website domain from your own knowledge (bare domain, no scheme/"www").
Skip any name you're not confident of the domain for rather than guessing.
"""


class WebSourcedCandidates(BaseModel):
    same_business: bool = Field(description="Whether this page is genuinely about the same business described, not a different company sharing the name.")
    candidates: list[CandidateCompetitor] = Field(description="Competitor names actually listed on the page, with domains.")


def _source_candidates_from_search(
    business_name: str, business_description: str, business_site: str = "", max_sources: int = 4
) -> list[CandidateCompetitor]:
    """Ground candidate sourcing in real, current web content (e.g. G2/alternative-page
    style listicles) rather than relying only on the LLM's training-data memory, which
    can miss recent or niche competitive dynamics for smaller/newer companies.

    business_site is used purely to disambiguate the search query (many short/common
    business names collide with unrelated things - a car model, a generic English
    word, another company entirely) - it is never trusted as a source itself."""
    candidates: list[CandidateCompetitor] = []
    seen_domains: set[str] = set()
    sources_read = 0

    site_hint = f" {business_site}" if business_site else ""
    queries = [f"{business_name}{site_hint} alternatives", f"{business_name}{site_hint} competitors"]
    if site_hint:
        # A plain name query can be dominated by an unrelated same-name entity (a car
        # model, a common word) - a query with no site hint is still worth trying since
        # it sometimes surfaces broader "vs" discussion the site-qualified query misses.
        queries.append(f"{business_name} alternatives")

    for query in queries:
        for url in _web_search(query):
            if sources_read >= max_sources:
                return candidates

            domain = urlparse(url).netloc.lower().removeprefix("www.")
            if not domain or domain in seen_domains:
                continue
            seen_domains.add(domain)

            text = fetch_page(url)
            if text.startswith("ERROR:") or len(text) < 300:
                continue

            sources_read += 1
            agent = Agent(model=get_model(), system_prompt=_WEB_EXTRACTION_SYSTEM_PROMPT)
            result = agent(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": (
                                    f"BUSINESS DESCRIBED: {business_name} - {business_description}\n\n"
                                    f"PAGE CONTENT (from {url}):\n{text[:4000]}"
                                )
                            }
                        ],
                    }
                ],
                structured_output_model=WebSourcedCandidates,
            )
            parsed: WebSourcedCandidates = result.structured_output

            log_step(
                "discover",
                source_url=url,
                same_business=parsed.same_business,
                extracted=[c.name for c in parsed.candidates],
            )
            if parsed.same_business:
                candidates.extend(parsed.candidates)

    return candidates


_CATEGORY_PHRASE_SYSTEM_PROMPT = """You are a market researcher. Given a business's own
description, produce 2-4 short search phrases a savvy researcher would type into a
search engine to find its REAL competitors by PRODUCT CATEGORY and core function/
feature - not by searching for the business's own name. A real competitor's own
homepage should plausibly rank on the first page of results for these phrases (e.g.
for a virtual sandtray therapy app: "virtual sandtray for therapists", "digital play
therapy tools online" - not the business's own brand name).

Avoid phrases so broad they'd surface irrelevant results (e.g. just "therapy
software"), and avoid anything so narrow/branded it would only surface the described
business itself. Think about what a genuine competing PRODUCT would advertise itself
with, not what an analyst would call the industry.
"""


class CategorySearchPhrases(BaseModel):
    phrases: list[str] = Field(description="2-4 category/feature search phrases, not brand names.")


def _generate_category_search_phrases(business_name: str, business_description: str) -> list[str]:
    agent = Agent(model=get_model(), system_prompt=_CATEGORY_PHRASE_SYSTEM_PROMPT)
    result: CategorySearchPhrases = agent.structured_output(
        CategorySearchPhrases,
        f"Business: {business_name}\nDescription: {business_description}",
    )
    return result.phrases


_CATEGORY_MATCH_SYSTEM_PROMPT = """You are checking whether a fetched webpage belongs to
a genuine competing product/company in the same category as a described business - a
DIFFERENT real company offering a similar core function, not a directory, aggregator,
news article, forum thread, review site, or the described business's own site.

Given the business's description and this page's content: does this page describe a
real, distinct company/product competing in the same category (same core
function/workflow, same type of customer)? If yes, extract that company's actual
display/brand name AS IT APPEARS on the page (not the domain name) and explain briefly
why it's a category match - name the shared core function specifically, not just a
shared industry or buzzword. If this page is not a genuine competing product, set
is_competitor to false and leave company_name empty.
"""


class CategoryMatchResult(BaseModel):
    is_competitor: bool = Field(description="True only if this page is a genuine different company competing in the same category via the same core function.")
    company_name: str = Field(default="", description="The company's actual display/brand name as it appears on the page, if is_competitor is true.")
    reason: str = Field(description="Why this is (or isn't) a category match, naming the shared core function.")


def _source_candidates_from_category_search(
    business_name: str, business_description: str, business_site: str = "", max_sources: int = 6
) -> list[CandidateCompetitor]:
    """Fallback for niches with no G2/listicle presence (a real gap found live: a
    digital play-therapy tool had no "alternatives" page anywhere online, so the
    name-based search in _source_candidates_from_search returned nothing, and the
    memory-based fallback proposed off-target generalists). Instead of searching for
    the business's own name, this searches by PRODUCT CATEGORY/feature phrases and
    treats organic search results themselves as candidate competitor homepages -
    every genuine competitor found this way was surfaced on the first page of a
    category query the listicle-search approach never tried."""
    phrases = _generate_category_search_phrases(business_name, business_description)
    log_step("discover", source="category_search", phrases=phrases)

    own_domain = urlparse(business_site if "://" in business_site else f"https://{business_site}").netloc.lower().removeprefix("www.") if business_site else ""

    candidates: list[CandidateCompetitor] = []
    seen_domains: set[str] = set()
    sources_read = 0

    for phrase in phrases:
        for url in _web_search(phrase):
            if sources_read >= max_sources:
                return candidates

            domain = urlparse(url).netloc.lower().removeprefix("www.")
            if not domain or domain in seen_domains or domain in _NON_PRIMARY_DOMAINS or domain == own_domain:
                continue
            seen_domains.add(domain)

            text = fetch_page(url)
            if text.startswith("ERROR:") or len(text) < 300:
                continue

            sources_read += 1
            agent = Agent(model=get_model(), system_prompt=_CATEGORY_MATCH_SYSTEM_PROMPT)
            result = agent(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": (
                                    f"BUSINESS DESCRIBED: {business_name} - {business_description}\n\n"
                                    f"PAGE CONTENT (from {url}):\n{text[:4000]}"
                                )
                            }
                        ],
                    }
                ],
                structured_output_model=CategoryMatchResult,
            )
            parsed: CategoryMatchResult = result.structured_output

            log_step(
                "discover",
                source_url=url,
                is_competitor=parsed.is_competitor,
                company_name=parsed.company_name,
                reason=parsed.reason,
            )
            if parsed.is_competitor and parsed.company_name:
                candidates.append(CandidateCompetitor(name=parsed.company_name, domain=domain, reason=parsed.reason))

    return candidates


def _web_search(query: str) -> list[str]:
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": _SEARCH_USER_AGENT},
            timeout=_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    return [a.get("href") for a in soup.select("a.result__a") if a.get("href")]


def _search_fallback_domain(company_name: str) -> str | None:
    for url in _web_search(f"{company_name} official website"):
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        if domain and domain not in _NON_PRIMARY_DOMAINS:
            return domain
    return None


def _looks_like_real_page(text: str) -> bool:
    if text.startswith("ERROR:"):
        return False
    if len(text) < 200:
        return False
    return not re.search(r"\b404\b|page not found", text[:300], re.IGNORECASE)


def _find_working_path(domain: str, candidate_paths: list[str]) -> str | None:
    for path in candidate_paths:
        text = fetch_page(f"https://{domain}{path}")
        if _looks_like_real_page(text):
            return f"https://{domain}{path}"
    return None


def _resolve_and_vet_candidate(candidate: CandidateCompetitor, business_description: str, region: str = "") -> dict | None:
    """Resolve a candidate's real domain, vet it for legitimacy/relevance, and find its
    pricing/blog URLs. Returns None if the candidate can't be resolved or doesn't pass
    the worthiness gate."""
    domain = candidate.domain.lower().removeprefix("www.").strip("/")
    homepage_text = fetch_page(f"https://{domain}/")

    if not _looks_like_real_page(homepage_text):
        # Some sites reject the bare apex domain (SSL cert mismatch, routing) but
        # work fine with "www." - cheap to retry before giving up.
        www_text = fetch_page(f"https://www.{domain}/")
        if _looks_like_real_page(www_text):
            domain = f"www.{domain}"
            homepage_text = www_text
        else:
            fallback_domain = _search_fallback_domain(candidate.name)
            fallback_text = fetch_page(f"https://{fallback_domain}/") if fallback_domain else ""
            if fallback_domain and _looks_like_real_page(fallback_text):
                domain = fallback_domain
                homepage_text = fallback_text
            else:
                log_step("discover", competitor_name=candidate.name, domain=candidate.domain, result="unresolved")
                return None

    worthiness = assess_competitor_worthiness(
        candidate.name, business_description, homepage_text, region=region, domain=domain
    )
    # A candidate makes the list if it's legitimate + relevant, AND either worth active
    # monitoring OR strategically important enough to be aware of even if it won't give
    # actionable weekly signals (these two are independent - see worthiness_tool.py).
    should_include = (
        worthiness["legitimate"]
        and worthiness["relevant"]
        and (worthiness["worth_monitoring"] or worthiness["strategic_importance"] == "high")
    )
    if not should_include:
        log_step(
            "discover",
            competitor_name=candidate.name,
            domain=domain,
            result="rejected",
            legitimate=worthiness["legitimate"],
            relevant=worthiness["relevant"],
            strategic_importance=worthiness["strategic_importance"],
            reasoning=worthiness["reasoning"],
        )
        return None

    pricing_url = _find_working_path(domain, _PRICING_PATHS)
    blog_url = _find_working_path(domain, _BLOG_PATHS)

    urls = [u for u in (pricing_url, blog_url) if u] or [f"https://{domain}/"]
    competitor_id = re.sub(r"[^a-z0-9]+", "", candidate.name.lower())

    log_step(
        "discover",
        competitor_name=candidate.name,
        domain=domain,
        result="resolved",
        pricing_url=pricing_url,
        blog_url=blog_url,
        worth_monitoring=worthiness["worth_monitoring"],
        strategic_importance=worthiness["strategic_importance"],
        worthiness_reasoning=worthiness["reasoning"],
    )
    return {
        "id": competitor_id,
        "name": candidate.name,
        "urls": urls,
        "worth_monitoring": worthiness["worth_monitoring"],
        "strategic_importance": worthiness["strategic_importance"],
        "worthiness_reasoning": worthiness["reasoning"],
    }


_MAX_DISCOVERY_ROUNDS = 3


@tool
def discover_competitors(
    business_name: str, business_description: str, count: int = 4, region: str = "", business_site: str = ""
) -> list[dict]:
    """Propose real competitors for a business that doesn't already have a competitor list, then resolve each to a working pricing page URL (and blog/changelog URL if one can be found).

    Combines LLM judgment (naming plausible real competitors and their domain from
    general market knowledge) with live fetch verification - a proposed domain is
    never trusted blindly, and a keyless web search is only used as a fallback if the
    LLM-proposed domain doesn't resolve - and a legitimacy/relevance worthiness gate
    (assess_competitor_worthiness) that rejects illegitimate, off-niche, or (when a
    region is given) region-mismatched candidates. Since candidate proposals are
    stochastic and a narrow niche/region can produce an all-reject round, this retries
    with fresh (non-repeated) candidates for up to a few rounds if it hasn't yet found
    enough that pass, rather than giving up after one attempt.

    Args:
        business_name: The user's business name.
        business_description: 2-3 sentences describing the business, its market, and pricing.
        count: How many competitors to try to find (default 4).
        region: Optional target region/market (e.g. "Canada", "United States", "Morocco"). When given, competitors are filtered to those actually serving that region, not just the same product niche.
        business_site: Optional site (e.g. "inaccord.com") used only to disambiguate the web search query when the business name is short/common/collides with something unrelated (a car model, a generic word, another company) - never trusted as a source itself.
    """
    competitors: list[dict] = []
    tried_names: list[str] = []

    # Ground candidate sourcing in real, current web content FIRST - the LLM's own
    # training-data memory alone can miss recent or niche competitive dynamics for
    # smaller/newer companies (e.g. a competitor that only became relevant recently).
    web_candidates = _source_candidates_from_search(business_name, business_description, business_site)
    if not web_candidates:
        # No usable "alternatives" page exists for this business - common in niches
        # with no G2/listicle presence. Fall back to searching by product category
        # instead of by business name before resorting to pure memory recall.
        web_candidates = _source_candidates_from_category_search(business_name, business_description, business_site)
    if web_candidates:
        log_step("discover", source="web", proposed=[f"{c.name} ({c.domain})" for c in web_candidates])
        tried_names.extend(c.name for c in web_candidates)
        for candidate in web_candidates:
            if len(competitors) >= count:
                break
            resolved = _resolve_and_vet_candidate(candidate, business_description, region=region)
            if resolved:
                competitors.append(resolved)

    for round_num in range(_MAX_DISCOVERY_ROUNDS):
        still_needed = count - len(competitors)
        if still_needed <= 0:
            break

        candidates = _propose_candidates(
            business_name, business_description, still_needed, region=region, exclude_names=tried_names
        )
        if not candidates:
            break

        log_step("discover", round=round_num + 1, proposed=[f"{c.name} ({c.domain})" for c in candidates])
        tried_names.extend(c.name for c in candidates)

        for candidate in candidates:
            resolved = _resolve_and_vet_candidate(candidate, business_description, region=region)
            if resolved:
                competitors.append(resolved)

    return competitors
