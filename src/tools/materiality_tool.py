"""Stage 3 — judge whether a diff is a trivial copy tweak or a substantive business change.

This is a real reasoning call (a nested Strands Agent with structured output), not
keyword/regex matching — the same price change can read as trivial or substantive
depending on context, and only a model reading the surrounding text can tell.
"""

from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent, tool

from src.model import get_model
from src.trace import log_step

_SYSTEM_PROMPT = """You are a meticulous competitive-intelligence analyst.

You are given a unified diff of a competitor's public web page (pricing page, blog,
or changelog) between two fetches. Decide whether the change is:

- "trivial": copy edits, typo fixes, rewording, reformatting, date/footer updates,
  reordering of existing items with no substantive change in meaning.
- "substantive": a price change, a new or removed pricing tier, a new or discontinued
  feature, a new product/plan, a policy change (e.g. refund/contract terms), or
  anything else that could change a prospective customer's decision.

Judge based on business meaning, not the size of the diff — a one-character price
change ($19 -> $14) is substantive; a large paragraph reworded to say the same thing
is trivial. Be skeptical of anything that looks like marketing fluff churn.
"""


class MaterialityJudgment(BaseModel):
    materiality: Literal["trivial", "substantive"] = Field(
        description="Whether the change matters to a competitor-watching business owner."
    )
    reasoning: str = Field(description="One or two sentences explaining the call.")


@tool
def judge_materiality(competitor_id: str, diff_text: str) -> dict:
    """Classify a competitor page diff as 'trivial' or 'substantive' using real judgment about business meaning, not keyword matching.

    Args:
        competitor_id: Short identifier for the competitor this diff belongs to.
        diff_text: The unified diff text to classify (from diff_against_last_snapshot).
    """
    if diff_text in ("NO_CHANGE",):
        log_step("materiality", competitor_id=competitor_id, materiality="trivial", reasoning="No change detected.")
        return {"materiality": "trivial", "reasoning": "No change detected."}

    agent = Agent(model=get_model(), system_prompt=_SYSTEM_PROMPT)
    result: MaterialityJudgment = agent.structured_output(
        MaterialityJudgment,
        f"Competitor: {competitor_id}\n\nDiff:\n{diff_text}",
    )
    log_step("materiality", competitor_id=competitor_id, materiality=result.materiality, reasoning=result.reasoning)
    return {"materiality": result.materiality, "reasoning": result.reasoning}
