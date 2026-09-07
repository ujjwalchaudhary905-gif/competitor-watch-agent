"""Tests for the mechanical tie-detection in comparative visual scoring.

A real regression happened twice: independent-per-site scoring collapsed to a
template once (fixed by comparing all sites in one call), then the comparative
version ALSO collapsed on a later run (three of four sites scored an identical 8/9)
because the original instructions left an escape hatch for "genuinely
indistinguishable" sites. These tests cover the mechanical duplicate-detection added
to catch that regardless of what the model decides - no API key needed, since this is
pure Python logic over already-produced scores.
"""

from src.tools.visual_tool import RankedVisualAssessment, _find_duplicates


def _assessment(name, rank, friendliness, professionalism):
    return RankedVisualAssessment(
        name=name,
        rank=rank,
        friendliness_score=friendliness,
        professionalism_score=professionalism,
        first_impression="x",
        strengths=["x"],
        weaknesses=["x"],
    )


def test_no_duplicates_when_everything_differentiated():
    assessments = [
        _assessment("A", 1, 9, 9),
        _assessment("B", 2, 6, 8),
        _assessment("C", 3, 7, 7),
        _assessment("D", 4, 4, 8),
    ]
    assert _find_duplicates(assessments) == []


def test_detects_duplicate_rank():
    assessments = [
        _assessment("A", 1, 9, 9),
        _assessment("B", 1, 6, 8),
    ]
    problems = _find_duplicates(assessments)
    assert any("rank 1" in p for p in problems)


def test_detects_duplicate_score_pair_even_with_unique_ranks():
    assessments = [
        _assessment("A", 1, 8, 9),
        _assessment("B", 2, 8, 9),
        _assessment("C", 3, 8, 9),
        _assessment("D", 4, 9, 8),
    ]
    problems = _find_duplicates(assessments)
    assert any("A" in p and "B" in p and "C" in p for p in problems)
