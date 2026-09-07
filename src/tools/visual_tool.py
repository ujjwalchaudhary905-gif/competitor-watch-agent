"""Visual UI/UX assessment — screenshots multiple public pages and has Claude critique
and RANK them against each other in one call, the same "real judgment" pattern used
elsewhere in this project but applied to pixels instead of text. Public pages only,
same as the rest of the fetch pipeline - no login-gated pages, no private/internal views.

Scoring every site independently (one isolated call per competitor) was tried first
and regressed to a template: four unrelated sites all scored 7/9 or 6/8 with the
identical "feels corporate and cold, no testimonials" critique repeated verbatim. A
score with no variance carries no information - you can't rank or alert on it. Forcing
one call to compare all sites side by side, with an explicit rank order, is the fix:
the model has to justify why each site is better or worse than its neighbors, which is
a fundamentally different (and harder to fake generically) task than "score this site
in isolation."

That fix regressed on a later run (three of four sites scored an identical 8/9 again),
because the original instructions still allowed an escape hatch ("unless they are
genuinely indistinguishable") the model used as a way out. Two changes: the escape
hatch is gone - ties are never acceptable, full stop - and there's now a mechanical
check after the call that detects duplicate rank or duplicate score pairs and forces
one retry with the specific duplicates named, rather than trusting the instruction alone.
"""

from playwright.sync_api import sync_playwright
from pydantic import BaseModel, Field
from strands import Agent, tool

from src.model import get_model
from src.trace import log_step

_VIEWPORT = {"width": 1280, "height": 900}
_NAV_TIMEOUT_MS = 20_000

_SYSTEM_PROMPT = """You are a UI/UX critic helping a small business owner understand how
their own site and their competitors' sites compare to each other visually - not how
each looks in isolation, but how they stack up side by side.

You will be given several screenshots, each labeled with a name (one of them is the
business's own site). Compare them against each other and produce a RANKED list
(rank 1 = best overall impression) with scores and reasoning for every one.

Hard requirements, because independent per-site scoring has failed before by
regressing to a generic template with no variance between sites:
- Rank is a strict ordering: 1, 2, 3, ... with NO TIES, ever. Every site you're shown
  differs in at least some real visual detail once you actually look - font choice,
  spacing, color saturation, image quality, button style, information density. Find
  that detail and use it. "They're basically the same" is not an acceptable
  conclusion here; keep looking at the actual pixels until you find what differs.
- Scores must differentiate the same way - do not give the same friendliness/
  professionalism pair to two different sites. If you catch yourself about to repeat a
  score you already used, that is a signal you haven't looked closely enough yet, not
  a sign the sites are equal.
- Every weakness/strength must be SPECIFIC to that site's actual screenshot (colors,
  layout choices, specific copy, specific visible elements) - never a generic line like
  "feels corporate, no testimonials" that could apply to any B2B site without having
  looked at it.
- Each site's reasoning must reference at least one other site by name to justify its
  relative rank ("more cluttered than X's layout", "warmer palette than Y but weaker
  CTA clarity") - a score with no comparison to its neighbors is not acceptable here.
"""


class RankedVisualAssessment(BaseModel):
    name: str = Field(description="The site's name, exactly as given.")
    rank: int = Field(description="1 = best overall impression among all sites compared. Strict ordering - no ties, ever.")
    friendliness_score: int = Field(description="1-10, differentiated relative to the other sites compared.")
    professionalism_score: int = Field(description="1-10, differentiated relative to the other sites compared.")
    first_impression: str = Field(description="1-2 sentences, specific to this site, referencing at least one other site for comparison.")
    strengths: list[str] = Field(description="Specific, concrete visual/UX strengths unique to this site's actual screenshot.")
    weaknesses: list[str] = Field(description="Specific, concrete visual/UX weaknesses unique to this site's actual screenshot.")


class ComparativeVisualResult(BaseModel):
    assessments: list[RankedVisualAssessment]


def _find_duplicates(assessments: list["RankedVisualAssessment"]) -> list[str]:
    """Returns human-readable descriptions of any duplicate ranks or duplicate score
    pairs found, or [] if every site is genuinely differentiated."""
    problems = []

    ranks = [a.rank for a in assessments]
    if len(set(ranks)) != len(ranks):
        dupes = {r for r in ranks if ranks.count(r) > 1}
        for r in dupes:
            names = [a.name for a in assessments if a.rank == r]
            problems.append(f"rank {r} was given to more than one site: {', '.join(names)}")

    score_pairs: dict[tuple[int, int], list[str]] = {}
    for a in assessments:
        key = (a.friendliness_score, a.professionalism_score)
        score_pairs.setdefault(key, []).append(a.name)
    for (friendliness, professionalism), names in score_pairs.items():
        if len(names) > 1:
            problems.append(
                f"friendliness={friendliness}/professionalism={professionalism} was given to more than one site: {', '.join(names)}"
            )

    return problems


def _capture_screenshot(url: str) -> bytes | None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport=_VIEWPORT)
                page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                return page.screenshot(type="png")
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - any Playwright/navigation failure just means "couldn't assess"
        return None


@tool
def assess_visual_designs(sites: list[dict]) -> list[dict]:
    """Screenshot several public pages (the business's own site plus its competitors) and have Claude critique and RANK them against each other in one comparison, so scores actually differentiate instead of each site being judged in isolation.

    Args:
        sites: List of {"name": str, "url": str} - include the business's own site (name it clearly, e.g. "Your site (Acme)") alongside every competitor to compare against.
    """
    screenshots: dict[str, bytes] = {}
    failed: list[str] = []
    for site in sites:
        shot = _capture_screenshot(site["url"])
        if shot is None:
            failed.append(site["name"])
            log_step("visual", competitor_name=site["name"], url=site["url"], result="screenshot_failed")
        else:
            screenshots[site["name"]] = shot

    if not screenshots:
        return [{"name": s["name"], "assessed": False, "reason": f"Could not load/screenshot {s['url']}."} for s in sites]

    content = [
        {
            "text": (
                "Compare these sites and produce a ranked assessment for each, per your "
                "instructions - differentiated scores, specific evidence, comparisons to "
                "neighbors. Sites, in order: " + ", ".join(screenshots.keys())
            )
        }
    ]
    for name, shot in screenshots.items():
        content.append({"text": f"--- {name} ---"})
        content.append({"image": {"format": "png", "source": {"bytes": shot}}})

    agent = Agent(model=get_model(max_tokens=4096), system_prompt=_SYSTEM_PROMPT)
    result = agent([{"role": "user", "content": content}], structured_output_model=ComparativeVisualResult)
    parsed: ComparativeVisualResult = result.structured_output

    duplicates = _find_duplicates(parsed.assessments)
    if duplicates:
        log_step("visual", result="duplicate_scores_retrying", duplicates=duplicates)
        corrective_message = {
            "role": "user",
            "content": [
                {
                    "text": (
                        "You gave duplicate scores/ranks, which is not allowed: "
                        + "; ".join(duplicates)
                        + ". Look at the actual screenshots again and find a real visual "
                        "difference between the tied sites (spacing, saturation, image "
                        "quality, density, button style - something is different). Rewrite "
                        "the full ranked assessment with every rank and score pair unique."
                    )
                }
            ],
        }
        retry_result = agent([corrective_message], structured_output_model=ComparativeVisualResult)
        retried: ComparativeVisualResult = retry_result.structured_output
        if not _find_duplicates(retried.assessments):
            parsed = retried
        else:
            log_step("visual", result="duplicate_scores_unresolved_after_retry")

    output = []
    for assessment in parsed.assessments:
        log_step(
            "visual",
            competitor_name=assessment.name,
            result="assessed",
            rank=assessment.rank,
            friendliness_score=assessment.friendliness_score,
            professionalism_score=assessment.professionalism_score,
        )
        output.append({"assessed": True, **assessment.model_dump()})

    for name in failed:
        output.append({"name": name, "assessed": False, "reason": "Could not load/screenshot this site."})

    return output
