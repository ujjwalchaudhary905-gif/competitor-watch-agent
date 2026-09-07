"""Stage 5 — rank and dedupe substantive findings across ALL competitors into a top-3 list.

This is itself an agent judgment call: two competitors making similar moves should be
merged into one item, and severity alone shouldn't decide rank — a "medium" severity
item that's easy and urgent to act on can outrank a "high" severity item that's vague.

Critical distinction this stage must preserve: a finding can be either an ACTUAL
detected change (a real diff against a prior snapshot) or a BASELINE observation (the
first time a competitor's page was ever seen, so there is nothing to compare against).
Baseline findings must never be reworded as if something changed - that's a fabricated
event. `is_baseline` on the input findings is carried straight through to the output,
never re-derived or dropped.

A real bug shipped and was caught live: a competitor the worthiness gate had explicitly
marked NOT relevant still ended up as the #1 recommended priority action, because the
gate's verdict was reported in a separate section of the output instead of actually
filtering what reached this stage. The fix is a MECHANICAL filter here in Python, not
a prompt request - `competitor_relevant` is required on every finding, and anything not
explicitly marked relevant is dropped before the model ever sees it, so a sloppy
orchestrator call can't leak a rejected competitor through no matter what it asks for.
"""

from pydantic import BaseModel
from strands import Agent, tool

from src.model import get_model
from src.schemas import PrioritizedItem
from src.trace import log_step

_SYSTEM_PROMPT = """You are a competitive-intelligence lead briefing a busy small-business owner
who has five minutes to read this. You are given a list of substantive findings, each
already scoped to what it means for this specific business (competitor, observation,
impact, severity, and whether it's a baseline observation or an actual detected change).

Produce UP TO 3 items this business should act on this week, ranked most urgent first -
"up to" means 0, 1, 2, or 3 are all valid outputs, and none of them require an
explanation or apology. This has been a repeated real failure: low-value findings have
been padded into a 3rd slot purely to fill the list, including once promoting a
finding about a competitor the business's own worthiness check had already flagged as
not worth monitoring. Padding is a worse failure than a short list. Before including
any item, ask: "if I could only tell the owner ONE sentence this week, does this item
earn a place in it on its own merits?" If not, cut it - do not keep it to reach 3.

- Merge/dedupe findings that are really the same underlying move (e.g. two competitors
  both added live chat -> one "industry is adding live chat" item, not two).
- Look across ALL findings for a shared pattern before ranking individually - if
  multiple competitors show the same trait (e.g. three of four offer a free tier),
  that is a CATEGORY NORM, not N separate individual threats: say so explicitly as one
  item ("free entry tiers are standard in this category; here's what competitors
  actually charge for beyond that"), not as an urgent reaction to any single
  competitor's free offering.
- Rank by real urgency and actionability, not just the severity label — a clear,
  cheap, high-leverage response can outrank a vague "high severity" note.
- Each item's "why_it_matters" should also justify its rank relative to neighbors.

CRITICAL: Copy each finding's is_baseline flag through unchanged - never invent a
change that didn't happen. If is_baseline is true, "observation" must describe the
competitor's CURRENT state only - words like "now", "recently", "has shifted",
"pivoted", "changed to" are forbidden for baseline items, since there is no prior
snapshot proving any movement occurred. A baseline item can still be ranked highly
(e.g. "their current pricing already undercuts you") - it just cannot be described as
a move or event. When merging two findings with different is_baseline values, keep
them separate rather than blending a real change with a baseline observation.

Some findings may reference numbers the business's own site claims about itself
(revenue lift, engagement stats). These are self-reported marketing claims, not
verified facts - if you reference one, attribute it ("they claim/advertise X"), never
restate it as an established fact.
"""


class PrioritizationResult(BaseModel):
    items: list[PrioritizedItem]


@tool
def prioritize_findings(findings: list[dict]) -> list[dict]:
    """Rank and dedupe substantive, impact-analyzed findings from across all competitors into a top-3 (or fewer) action list, ordered most urgent first.

    Args:
        findings: List of finding dicts, each with competitor_id, competitor_name, observation, impact_summary, severity, is_baseline, competitor_relevant (from that competitor's assess_competitor_worthiness "relevant" result - REQUIRED, never omit).
    """
    dropped = [f for f in findings if not f.get("competitor_relevant", False)]
    findings = [f for f in findings if f.get("competitor_relevant", False)]

    for f in dropped:
        log_step(
            "prioritize",
            result="dropped_not_relevant",
            competitor_name=f.get("competitor_name", "?"),
            reason="competitor_relevant was false or missing - a rejected/unverified competitor cannot reach prioritization",
        )

    if not findings:
        return []

    findings_text = "\n\n".join(
        f"- Competitor: {f['competitor_name']} (id: {f['competitor_id']})\n"
        f"  {'Current state (baseline, NOT a change)' if f.get('is_baseline') else 'Change detected'}: {f['observation']}\n"
        f"  Impact on my business: {f['impact_summary']}\n"
        f"  Severity: {f['severity']}\n"
        f"  is_baseline: {f.get('is_baseline', False)}"
        for f in findings
    )

    agent = Agent(model=get_model(), system_prompt=_SYSTEM_PROMPT)
    result: PrioritizationResult = agent.structured_output(
        PrioritizationResult,
        f"Findings to prioritize:\n\n{findings_text}",
    )
    for item in result.items:
        log_step(
            "prioritize",
            rank=item.rank,
            competitor_name=item.competitor_name,
            is_baseline=item.is_baseline,
            observation=item.observation,
            why_it_matters=item.why_it_matters,
        )
    return [item.model_dump() for item in result.items]
