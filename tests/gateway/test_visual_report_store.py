"""Tests for profile-scoped visual report persistence."""

import json
from pathlib import Path

import pytest

import gateway.visual_report_store as store


def _plan(block_count: int = 1) -> dict:
    return {
        "title": "<Weekly> plan",
        "summary": "Actual weekly report",
        "metrics": [{"label": "Workstreams", "value": "4"}],
        "blocks": [
            {"type": "metric", "title": f"Metric {index}", "label": "Done", "value": str(index)}
            for index in range(block_count)
        ],
    }


def test_save_and_load_latest_report_round_trips_profile_scoped_atomically(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "get_hermes_home", lambda: tmp_path)

    saved = store.save_latest_report(
        _plan(),
        source_response="# Weekly\nDo the work",
        source_metadata={"response_id": "resp_1", "secret": "sk-test-secret-secret-secret"},
        event_metadata={"platform": "telegram", "chat_id": "289310951", "thread_id": "11", "topic": "weekly"},
        generated_at="2026-07-11T12:00:00Z",
    )
    loaded = store.load_latest_report()

    assert saved == loaded
    assert loaded["plan"]["title"] == "<Weekly> plan"
    assert loaded["source"]["text"] == "# Weekly\nDo the work"
    assert loaded["source"]["metadata"]["response_id"] == "resp_1"
    assert "secret" not in loaded["source"]["metadata"]
    assert loaded["context"] == {
        "platform": "telegram",
        "chat_id": "289310951",
        "thread_id": "11",
        "topic": "weekly",
    }
    path = tmp_path / "gateway" / "visual_reports" / "latest.json"
    assert path.is_file()
    assert path.resolve().is_relative_to(tmp_path.resolve())
    leftovers = list(path.parent.glob("*.tmp"))
    assert leftovers == []
    assert json.loads(path.read_text(encoding="utf-8"))["success"] is True


def test_save_latest_report_sanitizes_bounds_and_browser_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "get_hermes_home", lambda: tmp_path)
    huge_plan = _plan(block_count=80)
    huge_plan["extra"] = "x" * 100_000
    source = "visible " + "sk-live-secret-secret-secret-secret" + " " + ("x" * 80_000)

    saved = store.save_latest_report(
        huge_plan,
        source_response=source,
        source_metadata={"api_key": "should-not-leak", "safe": "ok", "nested": {"token": "no", "id": "yes"}},
        event_metadata={"platform": "telegram", "chat_id": 289310951, "thread_id": None, "topic": "T" * 500},
        generated_at="2026-07-11T12:00:00Z",
    )
    raw = json.dumps(saved)

    assert len(saved["plan"]["blocks"]) <= store.MAX_BLOCKS
    assert len(saved["source"]["text"]) <= store.MAX_SOURCE_TEXT_CHARS
    assert saved["context"]["chat_id"] == "289310951"
    assert len(saved["context"]["topic"]) <= 160
    assert "should-not-leak" not in raw
    assert "api_key" not in raw
    assert "token" not in raw
    assert "sk-live-secret" not in raw
    assert saved["source"]["metadata"] == {"safe": "ok", "nested": {"id": "yes"}}


def test_load_latest_report_returns_none_for_missing_or_corrupt(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "get_hermes_home", lambda: tmp_path)
    assert store.load_latest_report() is None

    path = tmp_path / "gateway" / "visual_reports" / "latest.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")
    assert store.load_latest_report() is None
