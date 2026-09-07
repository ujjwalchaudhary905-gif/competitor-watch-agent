"""Lightweight structured trace logging — every pipeline decision, printed and persisted.

Needed so the demo can show *why* each step happened (which competitor, what changed,
why prioritized, why recommended), not just the final output.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "run_log.jsonl"


def log_step(stage: str, **fields: object) -> None:
    """Print a one-line human-readable trace entry and append the full record as JSONL."""
    record = {"stage": stage, "ts": datetime.now(timezone.utc).isoformat(), **fields}

    headline = " | ".join(f"{k}={v}" for k, v in fields.items() if not isinstance(v, (list, dict)))
    print(f"[{stage}] {headline}")

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")
