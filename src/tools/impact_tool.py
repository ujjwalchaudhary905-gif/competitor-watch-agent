"""Stage 4 — for a substantive diff, reason about what it specifically means for MY business.

Critical distinction: a diff is an ACTUAL detected change (there was a prior snapshot,
and it moved). A first-ever look at a competitor's page (no prior snapshot to compare
against) is a BASELINE observation - there is no evidence anything changed, only that
this is what the page currently says. Treating a baseline observation as a change is a
fabricated event, and it happened in production: a report once opened with "Competitor
X has pivoted dramatically" on a page that had never been seen before. `is_first_look`
switches into a mode where change-implying language is banned and mechanically
enforced (regex-checked, regenerated once if violated), not just requested.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent, tool

from src.config import load_business_profile
from src.model import get_model
from src.trace import log_step

_CHANGE_SYSTEM_PROMPT = """You are a competitive strategist advising one specific small business.

You will be given:
- That business's own profile (name, site, description, pricing, target region if given) as typed by the owner.
- Optionally, an excerpt of what the business's own site ACTUALLY currently says (live
  fetched) — trust this over the typed description where they conflict, since the
  typed description can be outdated or incomplete about exact current pricing/features.
  Any specific numbers/claims in it are the business's OWN marketing, not independently
  verified facts - if you reference one, attribute it ("they claim X"), don't state it
  as an established fact.
- A substantive change a named competitor just made (as a diff and/or summary), already
  confirmed real by comparing two snapshots.

Write a concrete, specific analysis of what this change means FOR THIS BUSINESS —
not a generic summary of the competitor's change. Reference the business's own
pricing/positioning by name where relevant (e.g. "Competitor X cut price to $14.99,
undercutting your $19.99 tier by $5"). If the change has no real bearing on this
business, say so plainly and rate severity low.
"""

_BASELINE_SYSTEM_PROMPT = """You are a competitive strategist advising one specific small business.

You will be given:
- That business's own profile (name, site, description, pricing, target region if given) as typed by the owner.
- Optionally, an excerpt of what the business's own site ACTUALLY currently says (live
  fetched) — trust this over the typed description where they conflict. Any specific
  numbers/claims in it are the business's OWN marketing, not independently verified
  facts - if you reference one, attribute it ("they claim X"), don't state it as fact.
- The CURRENT content of a competitor's page. This is the FIRST time this page has ever
  been observed - there is no prior snapshot, so there is NO EVIDENCE anything changed.

Write a concrete, specific analysis of what this competitor's CURRENT position means
for this business — a baseline read of where things stand today, not a change. This is
not optional phrasing: you have zero evidence of any change, addition, pivot, or shift,
so describing one would be fabricating an event that may not exist. Use only
present-tense, current-state language ("they price at $X", "their site emphasizes Y").
Words and phrases like "now", "recently", "has shifted/pivoted/moved/changed",
"newly", "no longer", "used to" are FORBIDDEN in this analysis - there is nothing to
compare against, so none of that language is earned. If the current position has no
real bearing on this business, say so plainly and rate severity low.
"""

_BASELINE_BANNED_PATTERN = re.compile(
    r"\b(pivot(?:ed|s|ing)?|shift(?:ed|s|ing)?|chang(?:ed|es|ing)|has (?:moved|switched|added|introduced)|"
    r"recently|now offers?|newly|used to|previously|no longer|a move (?:to|toward)|dramatically)\b",
    re.IGNORECASE,
)


class ImpactAnalysis(BaseModel):
    impact_summary: str = Field(
        description="1-3 sentences on what this means specifically for the business, referencing its own pricing/positioning by name."
    )
    severity: Literal["low", "medium", "high"] = Field(
        description="How urgently this business should react."
    )


def _analyze(system_prompt: str, prompt: str) -> ImpactAnalysis:
    agent = Agent(model=get_model(), system_prompt=system_prompt)
    return agent.structured_output(ImpactAnalysis, prompt)


@tool
def analyze_impact(
    competitor_name: str,
    change_summary: str,
    your_current_site_excerpt: str = "",
    is_first_look: bool = False,
) -> dict:
    """Reason about what a competitor's substantive change (or, for a first-ever look at their page, their current position) means specifically for the user's own business.

    Args:
        competitor_name: The competitor's display name.
        change_summary: For a real detected change, describe the CHANGE (not the raw diff). For a first-ever look at a competitor's page (is_first_look=True), describe their CURRENT pricing/features/positioning instead - there is no change to describe.
        your_current_site_excerpt: Optional excerpt of what the business's own site currently says (from research_own_business), to ground the analysis in real current state rather than only the typed description.
        is_first_look: True if this is the first time this competitor's page has ever been seen (no prior snapshot exists) - forces a baseline-only analysis with no change-implying language, since no change can be confirmed. False (default) for an actual detected diff.
    """
    business = load_business_profile()

    site_block = (
        f"\nWhat your site actually currently says (live fetched, trust this over the description above where they conflict):\n{your_current_site_excerpt}\n"
        if your_current_site_excerpt
        else ""
    )
    region_line = f"Target region: {business.region}\n" if business.region else ""

    label = "COMPETITOR'S CURRENT PAGE (first time observed, not a change)" if is_first_look else "COMPETITOR CHANGE"
    prompt = (
        f"MY BUSINESS:\n"
        f"Name: {business.name}\n"
        f"Site: {business.site}\n"
        f"{region_line}"
        f"Description: {business.description}\n"
        f"{site_block}\n"
        f"{label}:\n"
        f"Competitor: {competitor_name}\n"
        f"Content: {change_summary}"
    )

    system_prompt = _BASELINE_SYSTEM_PROMPT if is_first_look else _CHANGE_SYSTEM_PROMPT
    result = _analyze(system_prompt, prompt)

    if is_first_look and _BASELINE_BANNED_PATTERN.search(result.impact_summary):
        log_step("impact", competitor_name=competitor_name, warning="baseline_language_violation_retrying")
        corrective_prompt = (
            prompt
            + "\n\nYour previous answer used change-implying language, which is forbidden here since "
            "there is no prior snapshot and no confirmed change. Rewrite using ONLY present-tense, "
            "current-state phrasing (e.g. 'they price at $X', 'their site emphasizes Y') - do not use "
            "any word implying movement, recency, or a shift from a prior state."
        )
        retried = _analyze(system_prompt, corrective_prompt)
        if not _BASELINE_BANNED_PATTERN.search(retried.impact_summary):
            result = retried
        else:
            log_step("impact", competitor_name=competitor_name, warning="baseline_language_violation_unresolved")

    log_step(
        "impact",
        competitor_name=competitor_name,
        is_baseline=is_first_look,
        severity=result.severity,
        impact_summary=result.impact_summary,
    )
    return {"impact_summary": result.impact_summary, "severity": result.severity, "is_baseline": is_first_look}
