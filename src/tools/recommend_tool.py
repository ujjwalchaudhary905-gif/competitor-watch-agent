"""Stage 6 — for each prioritized item, propose a concrete action AND name a real tool/service to execute it."""

from pydantic import BaseModel
from strands import Agent, tool

from src.config import load_business_profile
from src.model import get_model
from src.schemas import Recommendation
from src.trace import log_step

_SYSTEM_PROMPT = """You are a pragmatic small-business advisor. For each prioritized competitive
finding, propose ONE specific, concrete action the business owner could take this week,
and name a REAL, currently-existing tool or service (by actual product name) that would
help execute that action — e.g. "add live chat like Competitor A did -> try Crisp or
Intercom", "match the price drop with a limited-time promo -> run it through Stripe
Billing's coupon feature". Avoid vague advice like "improve your marketing" — be as
concrete as the finding allows. Use the business's own profile to keep the action
realistic for its size and pricing, and appropriate to its target region if one is
given (e.g. a regionally relevant tool/marketing channel over a generic one).

Match the suggested tool's price/complexity to the business's own apparent stage -
infer stage ONLY from explicit evidence actually present in its description/site
content (an explicit funding round, a stated team size, a stated customer count, its
own pricing level). Do NOT infer "funded" or "growth-stage" from a site merely
sounding sophisticated, professional, or ambitious - polished copy is not evidence of
budget. If you find no explicit evidence of scale/funding, default to assuming the
business is small/self-serve-budget, not the reverse - the safe default is the cheaper
tool. NEVER recommend an enterprise-tier tool (typically five-figure-plus annual
contracts, sales-assisted onboarding, built for large teams) to a business with no
confirmed evidence of that scale - prefer a free tier, a self-serve low-cost tool, or a
manual/spreadsheet approach. It is worse to recommend an oversized tool than a simpler
one, and it is worse to justify that recommendation with an invented assumption about
the business's funding than to just default to the cheap option.

Some items reference facts the business's OWN site claims about itself (e.g. a
specific revenue-lift or savings figure). Treat these as the business's marketing
claims, not verified facts - never restate one as an established number in your
rationale (write "you claim/advertise X", not "you deliver X"), and never use an
unverified self-reported figure as the load-bearing justification for an action.

If an item's finding is baseline (is_baseline true, i.e. a first-ever look at that
competitor rather than a detected change), frame the action around current
competitive positioning ("differentiate against their existing X"), never as a
reaction to a supposed recent move ("counter their pivot", "in response to their
change") - no move was observed, only a current state.

REVERSIBILITY FILTER — this has been a repeated real failure across multiple runs:
every prioritized finding kept generating a pricing/packaging/positioning change
framed as a one-week shippable task ("launch a freemium tier this week", "publish
$19/mo pricing this week", "restructure pricing to counter Competitor X"). These are
the highest-blast-radius, hardest-to-reverse actions a business can take, and they are
not week-long tasks. Every recommendation must set action_type:
- "decision_to_evaluate" for ANYTHING touching pricing, packaging, tiers, or the
  business's fundamental market positioning - no exceptions, regardless of how minor
  it sounds. Frame the action as a decision to make with named evidence to gather
  first (e.g. "run a 2-week pricing survey with N existing customers before deciding
  whether to add a free tier" / "review 3 competitors' actual paid-feature boundaries
  before choosing where yours sits"), never as something to ship this week. If the
  business's own site/description mentions named enterprise or channel-partner
  relationships, say explicitly that any pricing move risks undercutting those deals
  and needs their input first.
- "ship_this_week" only for genuinely reversible, low-blast-radius actions - content,
  messaging, a landing page, an ad test, a battlecard, outreach. These CAN be framed
  as a concrete task to ship this week.
Also, never base ANY recommendation - pricing or otherwise - on a competitor whose own
finding notes regional or relevance uncertainty.
"""


class RecommendationResult(BaseModel):
    recommendations: list[Recommendation]


@tool
def recommend_actions(prioritized_items: list[dict], your_current_site_excerpt: str = "") -> list[dict]:
    """Propose a concrete action and name a real tool/service for each prioritized competitive finding.

    Args:
        prioritized_items: List of prioritized item dicts, each with rank, competitor_name, observation, why_it_matters, is_baseline.
        your_current_site_excerpt: Optional excerpt of what the business's own site currently says (from research_own_business), so recommendations are grounded in what the business actually has today, not just the typed description.
    """
    if not prioritized_items:
        return []

    business = load_business_profile()

    site_block = (
        f"What your site actually currently says (live fetched - note any specific numbers/claims here are the business's OWN marketing, not independently verified facts):\n{your_current_site_excerpt}\n\n"
        if your_current_site_excerpt
        else ""
    )
    region_line = f"Target region: {business.region}\n" if business.region else ""

    items_text = "\n\n".join(
        f"- Rank {item['rank']}: {item['competitor_name']} — "
        f"{'[BASELINE - current state, not a change]' if item.get('is_baseline') else '[CHANGE DETECTED]'} "
        f"{item['observation']}\n"
        f"  Why it matters: {item['why_it_matters']}"
        for item in prioritized_items
    )

    agent = Agent(model=get_model(), system_prompt=_SYSTEM_PROMPT)
    result: RecommendationResult = agent.structured_output(
        RecommendationResult,
        (
            f"MY BUSINESS:\n"
            f"Name: {business.name}\n"
            f"{region_line}"
            f"{site_block}"
            f"Description: {business.description}\n\n"
            f"PRIORITIZED FINDINGS:\n{items_text}"
        ),
    )
    for r in result.recommendations:
        log_step(
            "recommend",
            rank=r.rank,
            action_type=r.action_type,
            action=r.action,
            suggested_tool=r.suggested_tool,
            rationale=r.rationale,
        )
    return [r.model_dump() for r in result.recommendations]
