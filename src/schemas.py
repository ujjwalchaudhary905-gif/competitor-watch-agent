"""Shared data shapes passed between pipeline stages."""

from typing import Literal

from pydantic import BaseModel, Field


class PrioritizedItem(BaseModel):
    rank: int = Field(description="1 = most urgent")
    competitor_name: str
    is_baseline: bool = Field(
        description="True if this reflects the competitor's current/baseline state (no prior snapshot to compare against) rather than an actual detected change. Must be preserved from the underlying finding, never inferred."
    )
    observation: str = Field(
        description="What was observed. If is_baseline is true, this MUST describe current state only ('X currently prices at $Y') - change-implying language ('now', 'recently', 'has shifted', 'pivoted') is forbidden. If is_baseline is false, this describes the actual detected change."
    )
    why_it_matters: str = Field(description="Why this made the top list, and why ahead/behind neighbors.")


class Recommendation(BaseModel):
    rank: int
    action_type: Literal["ship_this_week", "decision_to_evaluate"] = Field(
        description="ship_this_week: a reversible, low-blast-radius action (content, messaging, a landing page, an ad test) that can genuinely be shipped in a week. decision_to_evaluate: ANY change to pricing, packaging, or fundamental market positioning - always this category regardless of how simple it sounds, since these are hard to reverse and carry outsized risk. Required, and pricing/packaging/positioning changes must never be ship_this_week."
    )
    action: str = Field(
        description="For ship_this_week: a specific, concrete action to take. For decision_to_evaluate: frame as a decision to make, not a task to ship - name the specific evidence to gather before committing (e.g. 'survey N customers on price sensitivity before changing tiers'), not 'launch X this week'."
    )
    suggested_tool: str = Field(description="A real, named tool/service that would help execute the action (for decision_to_evaluate, a tool that helps gather the evidence, not implement the change).")
    rationale: str = Field(description="Why this action + tool pairing addresses the prioritized item.")
