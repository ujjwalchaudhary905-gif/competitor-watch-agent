"""Posting/update cadence - derived entirely from this project's own monitoring
history (data/run_log.jsonl), not a new scrape. Answers "how often does this
competitor actually change this page" so the business owner can judge how active or
stale a competitor's public presence is. Needs a few real runs over time to have
anything to say - this is a feature of repeated monitoring, not a one-shot lookup.
"""

import json
from datetime import datetime
from pathlib import Path

from strands import tool

_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "run_log.jsonl"


def _load_snapshot_events(competitor_id: str, url: str) -> list[dict]:
    if not _LOG_PATH.exists():
        return []

    events = []
    with _LOG_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("stage") == "snapshot" and record.get("competitor_id") == competitor_id and record.get("url") == url:
                events.append(record)
    return events


@tool
def get_update_cadence(competitor_id: str, url: str) -> dict:
    """Compute how often a competitor's page has actually changed, based on this project's own past monitoring runs for that competitor+url - not a new fetch, purely derived from data/run_log.jsonl history.

    Returns observed_runs, changes_detected, average_days_between_changes (null if not
    enough history), and a plain-English summary. Honestly reports when there isn't
    enough history yet rather than guessing from a single run.

    Args:
        competitor_id: Short identifier for the competitor.
        url: The specific URL to check update cadence for.
    """
    events = _load_snapshot_events(competitor_id, url)

    if len(events) < 2:
        return {
            "observed_runs": len(events),
            "changes_detected": 0,
            "average_days_between_changes": None,
            "summary": (
                "Not enough monitoring history yet to judge update cadence - "
                "run the pipeline a few more times over several days to see a pattern."
            ),
        }

    timestamps = sorted(datetime.fromisoformat(e["ts"]) for e in events)
    span_days = (timestamps[-1] - timestamps[0]).total_seconds() / 86400
    change_events = [e for e in events if e.get("result") == "changed"]

    if not change_events:
        summary = (
            f"No changes detected across {len(events)} monitoring runs spanning "
            f"~{round(span_days, 1)} days - this page appears static or rarely updated."
        )
        avg_days_between_changes = None
    else:
        avg_days_between_changes = round(span_days / len(change_events), 1) if span_days > 0 else 0.0
        summary = (
            f"Changed {len(change_events)} time(s) across {len(events)} monitoring runs "
            f"spanning ~{round(span_days, 1)} days (roughly every {avg_days_between_changes} days)."
        )

    return {
        "observed_runs": len(events),
        "changes_detected": len(change_events),
        "average_days_between_changes": avg_days_between_changes,
        "summary": summary,
    }
