"""Compares the business's typed description (config/business.json) against what its
own site actually says (from research_own_business), to find specifics the owner
didn't think to type - exact features, audience nuances, differentiators, tone - that
would sharpen competitor discovery if included. Also produces a denser, improved
description for future discovery/analysis runs.
"""

from pydantic import BaseModel, Field
from strands import Agent, tool

from src.model import get_model
from src.trace import log_step

_SYSTEM_PROMPT = """You are a positioning consultant. You are given a business's own
typed description (currently used to find competitors and reason about competitive
impact) and the actual live text of their real website.

Identify specific things the typed description is MISSING that would matter for
finding truly relevant, niche-accurate competitors - concrete features, exact target
audience/niche details, differentiators, unique mechanisms or approach, tone/voice.
Only list things actually present on the site that aren't reflected in the
description - never invent anything.

Then write an improved description: 3-6 sentences, denser with the specifics you
found, still concise enough to hand to a competitor-discovery step.
"""


class DescriptionGapAnalysis(BaseModel):
    missing_points: list[str] = Field(description="Specific things the typed description omits that the real site reveals.")
    improved_description: str = Field(description="A denser, more specific description incorporating those points.")


@tool
def analyze_description_gap(business_name: str, typed_description: str, site_content: str) -> dict:
    """Compare the business's typed description against its own real site content to find missing specifics, and produce an improved description for sharper competitor discovery/analysis.

    Args:
        business_name: The business's name.
        typed_description: The current free-text description from config/business.json.
        site_content: Live-fetched excerpt of the business's own site (from research_own_business).
    """
    agent = Agent(model=get_model(), system_prompt=_SYSTEM_PROMPT)
    result = agent(
        [
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"Business: {business_name}\n\n"
                            f"TYPED DESCRIPTION:\n{typed_description}\n\n"
                            f"ACTUAL SITE CONTENT:\n{site_content}"
                        )
                    }
                ],
            }
        ],
        structured_output_model=DescriptionGapAnalysis,
    )
    analysis: DescriptionGapAnalysis = result.structured_output

    log_step("description_gap", business_name=business_name, missing_points=analysis.missing_points)
    return {"missing_points": analysis.missing_points, "improved_description": analysis.improved_description}
