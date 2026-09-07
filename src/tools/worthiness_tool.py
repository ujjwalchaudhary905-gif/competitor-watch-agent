"""A gatekeeper agent: given a candidate competitor's actual page content (and,
when available, how often it's been observed to update), judges whether the site is
(a) legitimate - a real, functioning business, not a broken/placeholder/dead page,
(b) genuinely relevant to the user's specific niche, not just loosely adjacent, and
(c) worth continuing to spend ACTIVE monitoring time on. This automates the same
judgment a human would make skimming a candidate site before deciding to track it.

worth_monitoring and strategic_importance are deliberately separate fields, not one.
A huge platform can be strategically important to know about (its trajectory could
eventually threaten you) while being useless to check weekly for actionable signals
(its blog posts monthly, changes glacially, and a report once conflated these -
telling a business to check a giant platform's blog every week for a threat described
as "12-18 months out," which is not an actionable weekly monitoring cadence).

Region-fit was originally judged from whatever page_content happened to be passed in -
which meant ruling out a competitor's entire market ("this is US-only") on weak signals
like the word "nationwide," rather than checking the pages that would actually answer
it. When a domain is given alongside a region, this tool now fetches likely
region-evidence pages itself (coverage/pricing/FAQ/about) rather than leaving that to
chance or to whatever the orchestrator happened to already have on hand.
"""

from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent, tool

from src.model import get_model
from src.trace import log_step

_REGION_EVIDENCE_PATHS = ["/coverage", "/pricing", "/faq", "/about", "/locations"]

_SYSTEM_PROMPT = """You are a skeptical competitive-intelligence gatekeeper. You decide
whether a candidate competitor is worth a small business owner's attention, and in what way.

Judge from the page content given (and update-activity history, if any):

1. legitimate: Is this a real, functioning business/product page - not a broken site,
   parked domain, placeholder template, or dead/abandoned page?

2. relevant: Use this concrete test, not a vibes-based industry-overlap check: would a
   buyer evaluating the described business ALSO seriously put this candidate on their
   shortlist for the SAME underlying need - i.e. would they choose ONE OR THE OTHER to
   solve the same core workflow/problem? Sharing an industry, using AI, or using
   similar marketing language ("playbooks", "AI-driven", buzzwords that have become
   generic across an entire category) is NOT enough - identify each one's PRIMARY
   function/workflow explicitly and compare those, not the marketing copy. Apply this
   test the same way every time - do not be stricter on one candidate and looser on
   another for the same underlying reason.

   If a target region is given, region-fit is part of relevance, not separate - but
   this is a factual claim, not a vibe, and it must be backed by explicit evidence in
   the page content given (a coverage list, an explicit country/state list, an FAQ
   answer, a pricing page scoped to a region) - not inferred from a single word like
   "nationwide" or a hunch about where the blog "sounds like" it's targeting.
   Certifications and compliance badges (HIPAA, SOC 2, GDPR, PCI) are NEVER evidence of
   geographic restriction - a HIPAA-compliant platform can and often does serve
   non-US clients too, since HIPAA governs data handling, not market availability.
   Do not use a compliance mention as a geography signal in either direction. If the
   given content (including the extra pages fetched for this, if any) doesn't
   explicitly confirm or rule out the region, say plainly that region fit is
   UNCONFIRMED rather than leaning on weak proxies - and default toward NOT rejecting
   on regional grounds without a specific quote or fact, since wrongly excluding a
   real competitor is its own failure mode.

3. worth_monitoring: Should this specifically be checked often/actively for near-term,
   actionable signals (pricing/feature changes worth reacting to this week or month)?
   This is about MONITORING CADENCE, not overall importance. A giant, slow-moving
   platform can be important to be aware of while being a poor use of active
   monitoring time if it only updates rarely or its threat is a long-term trend, not
   an imminent event.

4. strategic_importance: Independent of monitoring cadence, how much should the
   business owner be aware of this player's existence and trajectory at all -
   "low"/"medium"/"high"? A "high" strategic_importance + worth_monitoring=false
   combination is valid and common (e.g. a large platform whose eventual feature
   expansion could commoditize you, but whose week-to-week activity gives you nothing
   actionable to watch for) - do not force these to agree.

Be honest and specific in your reasoning - name the concrete evidence (or lack of it)
from the page content itself, quote the specific fact behind any regional-fit claim,
and explicitly name the PRIMARY function you compared for the relevance test.
"""


class WorthinessAssessment(BaseModel):
    legitimate: bool = Field(description="Real, functioning business page - not broken/placeholder/dead.")
    relevant: bool = Field(description="Genuinely serves the same specific niche/customer via the same primary function, not just loosely adjacent or sharing marketing buzzwords.")
    worth_monitoring: bool = Field(description="Worth ACTIVE, frequent monitoring for near-term actionable signals - not the same as strategic_importance.")
    strategic_importance: Literal["low", "medium", "high"] = Field(
        description="How much the owner should be aware of this player's existence/trajectory, independent of monitoring cadence."
    )
    reasoning: str = Field(description="1-3 sentences of concrete, specific justification, naming the primary function compared for relevance and quoting evidence for any regional-fit claim.")


def _fetch_region_evidence(domain: str) -> str:
    from src.tools.fetch_tool import fetch_page  # local import to avoid a cycle at module load time

    domain = domain.lower().removeprefix("www.").strip("/")
    blocks = []
    for path in _REGION_EVIDENCE_PATHS:
        text = fetch_page(f"https://{domain}{path}")
        if not text.startswith("ERROR:") and len(text) > 200:
            blocks.append(f"--- {path} ---\n{text[:1500]}")
        if len(blocks) >= 2:  # two extra pages is plenty; keep this cheap
            break
    return "\n\n".join(blocks)


@tool
def assess_competitor_worthiness(
    competitor_name: str,
    business_description: str,
    page_content: str,
    update_activity_summary: str = "",
    region: str = "",
    domain: str = "",
) -> dict:
    """Judge whether a candidate/existing competitor is legitimate, genuinely relevant to the business's specific niche (and target region, if given), worth active monitoring, and how strategically important it is - these last two are independent, not the same judgment.

    Args:
        competitor_name: The candidate/competitor's display name.
        business_description: The user's own business description, to judge niche relevance against.
        page_content: Fetched text content of the competitor's page (homepage or similar).
        update_activity_summary: Optional summary from get_update_cadence (how often this page has actually changed over past monitoring runs). Leave blank if unavailable (e.g. a brand-new candidate).
        region: Optional target region/market (e.g. "Canada", "United States") the business serves - factored into relevance.
        domain: Optional bare domain (e.g. "archiwise.ai") - when given alongside region, this tool fetches likely region-evidence pages itself (coverage/pricing/FAQ/about) rather than ruling on geography from page_content alone.
    """
    activity_block = f"\nUpdate activity history: {update_activity_summary}\n" if update_activity_summary else "\nUpdate activity history: none yet (brand new candidate or first run).\n"
    region_block = f"Target region: {region}\n" if region else ""

    region_evidence = ""
    if region and domain:
        region_evidence = _fetch_region_evidence(domain)

    evidence_block = (
        f"\nADDITIONAL PAGES FETCHED TO VERIFY REGIONAL COVERAGE (check these before ruling on geography):\n{region_evidence}\n"
        if region_evidence
        else ""
    )

    agent = Agent(model=get_model(), system_prompt=_SYSTEM_PROMPT)
    result = agent(
        [
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"MY BUSINESS (for relevance comparison): {business_description}\n"
                            f"{region_block}\n"
                            f"CANDIDATE: {competitor_name}\n"
                            f"{activity_block}\n"
                            f"PAGE CONTENT:\n{page_content[:4000]}"
                            f"{evidence_block}"
                        )
                    }
                ],
            }
        ],
        structured_output_model=WorthinessAssessment,
    )
    assessment: WorthinessAssessment = result.structured_output

    log_step(
        "worthiness",
        competitor_name=competitor_name,
        legitimate=assessment.legitimate,
        relevant=assessment.relevant,
        worth_monitoring=assessment.worth_monitoring,
        strategic_importance=assessment.strategic_importance,
        reasoning=assessment.reasoning,
        region_evidence_fetched=bool(region_evidence),
    )
    return assessment.model_dump()
