import json

from src.tools import cadence_tool


def _write_log(tmp_path, records):
    log_path = tmp_path / "run_log.jsonl"
    with log_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return log_path


def test_insufficient_history_reported_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(cadence_tool, "_LOG_PATH", _write_log(tmp_path, []))
    result = cadence_tool.get_update_cadence("acme", "https://acme.test/pricing")
    assert result["observed_runs"] == 0
    assert result["average_days_between_changes"] is None
    assert "Not enough monitoring history" in result["summary"]


def test_no_changes_across_multiple_runs(tmp_path, monkeypatch):
    records = [
        {"stage": "snapshot", "competitor_id": "acme", "url": "https://acme.test/pricing", "result": "new_page", "ts": "2026-01-01T00:00:00+00:00"},
        {"stage": "snapshot", "competitor_id": "acme", "url": "https://acme.test/pricing", "result": "no_change", "ts": "2026-01-05T00:00:00+00:00"},
        {"stage": "snapshot", "competitor_id": "acme", "url": "https://acme.test/pricing", "result": "no_change", "ts": "2026-01-10T00:00:00+00:00"},
    ]
    monkeypatch.setattr(cadence_tool, "_LOG_PATH", _write_log(tmp_path, records))
    result = cadence_tool.get_update_cadence("acme", "https://acme.test/pricing")
    assert result["observed_runs"] == 3
    assert result["changes_detected"] == 0
    assert result["average_days_between_changes"] is None
    assert "static" in result["summary"]


def test_computes_average_days_between_changes(tmp_path, monkeypatch):
    records = [
        {"stage": "snapshot", "competitor_id": "acme", "url": "https://acme.test/blog", "result": "new_page", "ts": "2026-01-01T00:00:00+00:00"},
        {"stage": "snapshot", "competitor_id": "acme", "url": "https://acme.test/blog", "result": "changed", "ts": "2026-01-11T00:00:00+00:00"},
        {"stage": "snapshot", "competitor_id": "acme", "url": "https://acme.test/blog", "result": "changed", "ts": "2026-01-21T00:00:00+00:00"},
    ]
    monkeypatch.setattr(cadence_tool, "_LOG_PATH", _write_log(tmp_path, records))
    result = cadence_tool.get_update_cadence("acme", "https://acme.test/blog")
    assert result["observed_runs"] == 3
    assert result["changes_detected"] == 2
    assert result["average_days_between_changes"] == 10.0


def test_ignores_other_competitors_and_urls(tmp_path, monkeypatch):
    records = [
        {"stage": "snapshot", "competitor_id": "acme", "url": "https://acme.test/pricing", "result": "new_page", "ts": "2026-01-01T00:00:00+00:00"},
        {"stage": "snapshot", "competitor_id": "beta", "url": "https://beta.test/pricing", "result": "changed", "ts": "2026-01-02T00:00:00+00:00"},
        {"stage": "materiality", "competitor_id": "acme", "materiality": "substantive"},
    ]
    monkeypatch.setattr(cadence_tool, "_LOG_PATH", _write_log(tmp_path, records))
    result = cadence_tool.get_update_cadence("acme", "https://acme.test/pricing")
    assert result["observed_runs"] == 1
