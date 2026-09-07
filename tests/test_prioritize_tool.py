"""Tests for the mechanical relevance filter in prioritize_findings.

A real bug shipped: a competitor the worthiness gate marked NOT relevant still reached
the final report as the #1 recommended action, because relevance was reported
alongside the pipeline instead of gating entry into it. These tests cover the Python-
level filter added to fix that - no API key needed, since a finding list that's empty
after filtering returns before ever calling the model.
"""

from src.tools.prioritize_tool import prioritize_findings


def test_all_findings_rejected_returns_empty_without_calling_model():
    findings = [
        {
            "competitor_id": "archiwise",
            "competitor_name": "ArchiWise",
            "observation": "ArchiWise prices at $30-624/month.",
            "impact_summary": "Undercuts our pricing.",
            "severity": "high",
            "is_baseline": True,
            "competitor_relevant": False,
        },
        {
            "competitor_id": "altus",
            "competitor_name": "Altus Group",
            "observation": "Altus offers portfolio analytics.",
            "impact_summary": "Different market segment.",
            "severity": "low",
            "is_baseline": True,
            "competitor_relevant": False,
        },
    ]
    # If this reached the model without an ANTHROPIC_API_KEY it would raise -
    # returning [] here proves the filter runs (and short-circuits) before that.
    assert prioritize_findings(findings) == []


def test_finding_missing_competitor_relevant_is_dropped_not_included():
    findings = [
        {
            "competitor_id": "acme",
            "competitor_name": "Acme",
            "observation": "Acme raised prices.",
            "impact_summary": "Some impact.",
            "severity": "medium",
            "is_baseline": False,
            # competitor_relevant deliberately omitted - must fail closed, not default to included.
        }
    ]
    assert prioritize_findings(findings) == []


def test_empty_input_returns_empty():
    assert prioritize_findings([]) == []
