"""Tests for durable Telegram DM -> topic route ledger."""

import json

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _event(message_id="m1", text="hello"):
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="289",
            chat_type="dm",
            user_id="289",
            user_name="Aidyn",
        ),
        message_id=message_id,
        platform_update_id=42,
    )


def test_route_ledger_creates_route_record(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from gateway.dm_topic_router import DmTopicRouteLedger, RouteDestination, RouteDecision

    ledger = DmTopicRouteLedger()
    decision = RouteDecision(
        routed=True,
        destination=RouteDestination(chat_id="-10042", thread_id="143", topic_title="Workspace", chat_name="horkspace"),
        strategy="default",
        confidence=0.5,
        reason="default topic",
    )

    record = ledger.begin_route(_event(), decision, route_id="R-test")

    assert record["route_id"] == "R-test"
    assert record["status"] == "pending"
    assert record["origin"]["chat_id"] == "289"
    assert record["destination"]["thread_id"] == "143"
    assert ledger.get_by_origin_key(record["origin_key"])["route_id"] == "R-test"


def test_route_ledger_is_idempotent_for_same_origin_message(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from gateway.dm_topic_router import DmTopicRouteLedger, RouteDestination, RouteDecision

    ledger = DmTopicRouteLedger()
    decision = RouteDecision(
        routed=True,
        destination=RouteDestination(chat_id="-10042", thread_id="143", topic_title="Workspace"),
    )

    first = ledger.begin_route(_event(), decision, route_id="R-one")
    second = ledger.begin_route(_event(), decision, route_id="R-two")

    assert second["route_id"] == first["route_id"]
    assert len(ledger.data["routes"]) == 1


def test_route_ledger_marks_send_success_and_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from gateway.dm_topic_router import DmTopicRouteLedger, RouteDestination, RouteDecision

    ledger = DmTopicRouteLedger()
    decision = RouteDecision(
        routed=True,
        destination=RouteDestination(chat_id="-10042", thread_id="143", topic_title="Workspace"),
    )
    record = ledger.begin_route(_event(), decision, route_id="R-test")

    sent = ledger.mark_sent(record["origin_key"], destination_message_id="777")
    assert sent["status"] == "sent"
    assert sent["destination_message_id"] == "777"

    failed = ledger.mark_failed(record["origin_key"], "boom")
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"


def test_route_ledger_loads_empty_on_missing_or_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from gateway.dm_topic_router import DmTopicRouteLedger

    ledger = DmTopicRouteLedger()
    assert ledger.data == {"version": 1, "routes": {}}

    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    ledger.path.write_text("not json", encoding="utf-8")

    reloaded = DmTopicRouteLedger()
    assert reloaded.data == {"version": 1, "routes": {}}
