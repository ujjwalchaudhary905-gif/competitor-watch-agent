"""Stage 2 — store a snapshot per (competitor, url) and diff new content against the last one."""

import difflib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from strands import tool

from src.tools.fetch_tool import fetch_page
from src.trace import log_step

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "snapshots.db"


def _get_connection() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            competitor_id TEXT NOT NULL,
            url TEXT NOT NULL,
            content TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (competitor_id, url)
        )
        """
    )
    return conn


def _diff_and_store(competitor_id: str, url: str, new_content: str) -> str:
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT content FROM snapshots WHERE competitor_id = ? AND url = ?",
            (competitor_id, url),
        ).fetchone()

        old_content = row[0] if row else None

        conn.execute(
            """
            INSERT INTO snapshots (competitor_id, url, content, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(competitor_id, url) DO UPDATE SET
                content = excluded.content,
                fetched_at = excluded.fetched_at
            """,
            (competitor_id, url, new_content, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    if old_content is None:
        log_step("snapshot", competitor_id=competitor_id, url=url, result="new_page")
        return f"NEW_PAGE: {new_content[:3000]}"

    if old_content == new_content:
        log_step("snapshot", competitor_id=competitor_id, url=url, result="no_change")
        return "NO_CHANGE"

    diff = "\n".join(
        difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"{competitor_id}:{url} (previous)",
            tofile=f"{competitor_id}:{url} (latest)",
            lineterm="",
        )
    )
    log_step("snapshot", competitor_id=competitor_id, url=url, result="changed", diff_lines=diff.count("\n") + 1)
    return diff


@tool
def diff_against_last_snapshot(competitor_id: str, url: str, new_content: str) -> str:
    """Compare newly fetched page content against the last stored snapshot for this competitor+url, then store the new content as the latest snapshot.

    Returns a unified diff. If there is no prior snapshot, returns "NEW_PAGE: <first 500 chars>"
    since there is nothing to diff against yet. Returns "NO_CHANGE" if content is identical.

    Args:
        competitor_id: Short identifier for the competitor (e.g. "acme").
        url: The URL this content was fetched from.
        new_content: The freshly fetched page text to compare and store.
    """
    return _diff_and_store(competitor_id, url, new_content)


@tool
def fetch_and_diff(competitor_id: str, url: str) -> str:
    """Fetch a competitor's page and diff it against the last stored snapshot in one step, storing the new content as the latest snapshot.

    Use this instead of fetch_page + diff_against_last_snapshot when orchestrating a
    multi-page run: it avoids ever having to pass the full page text through a tool
    call argument, since the fetch happens inside this tool.

    Returns a unified diff, "NEW_PAGE: <first 500 chars>" if there is no prior
    snapshot, "NO_CHANGE" if content is identical, or "ERROR: ..." if the fetch failed.

    Args:
        competitor_id: Short identifier for the competitor (e.g. "acme").
        url: The URL to fetch and diff.
    """
    new_content = fetch_page(url)
    if new_content.startswith("ERROR:"):
        return new_content
    return _diff_and_store(competitor_id, url, new_content)
