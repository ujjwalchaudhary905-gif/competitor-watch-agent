import sqlite3
from pathlib import Path

import pytest

from src.tools import snapshot_tool


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_tool, "_DB_PATH", tmp_path / "snapshots.db")
    yield


def test_first_fetch_returns_new_page():
    result = snapshot_tool.diff_against_last_snapshot("acme", "https://acme.test/pricing", "Plan A: $19.99/mo")
    assert result.startswith("NEW_PAGE:")


def test_second_identical_fetch_returns_no_change():
    snapshot_tool.diff_against_last_snapshot("acme", "https://acme.test/pricing", "Plan A: $19.99/mo")
    result = snapshot_tool.diff_against_last_snapshot("acme", "https://acme.test/pricing", "Plan A: $19.99/mo")
    assert result == "NO_CHANGE"


def test_changed_content_returns_unified_diff():
    snapshot_tool.diff_against_last_snapshot("acme", "https://acme.test/pricing", "Plan A: $19.99/mo")
    result = snapshot_tool.diff_against_last_snapshot("acme", "https://acme.test/pricing", "Plan A: $14.99/mo")
    assert "-Plan A: $19.99/mo" in result
    assert "+Plan A: $14.99/mo" in result


def test_snapshots_are_isolated_per_competitor_and_url():
    snapshot_tool.diff_against_last_snapshot("acme", "https://acme.test/pricing", "content A")
    result = snapshot_tool.diff_against_last_snapshot("beta", "https://beta.test/pricing", "content B")
    assert result.startswith("NEW_PAGE:")
