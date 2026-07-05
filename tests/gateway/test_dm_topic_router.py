"""Tests for Telegram DM -> workspace topic routing helpers."""

import asyncio
from types import SimpleNamespace

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _event(text="hello", *, chat_type="dm", platform=Platform.TELEGRAM, thread_id=None, internal=False, user_id="289"):
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=platform,
            chat_id="289",
            chat_type=chat_type,
            user_id=user_id,
            user_name="Aidyn",
            thread_id=thread_id,
        ),
        message_id="m1",
        platform_update_id=42,
        internal=internal,
    )


def _platform_config(extra):
    return PlatformConfig(enabled=True, token="fake", extra=extra)


def test_router_disabled_returns_not_applicable():
    from gateway.dm_topic_router import load_dm_workspace_router_config, is_routable_telegram_dm

    cfg = load_dm_workspace_router_config(_platform_config({"dm_workspace_router": {"enabled": False}}))

    assert cfg.enabled is False
    assert is_routable_telegram_dm(_event(), cfg) is False


def test_only_authorized_plain_telegram_dms_are_routable():
    from gateway.dm_topic_router import load_dm_workspace_router_config, is_routable_telegram_dm

    cfg = load_dm_workspace_router_config(
        _platform_config({"dm_workspace_router": {"enabled": True, "allowed_user_ids": ["289"]}})
    )

    assert is_routable_telegram_dm(_event(), cfg) is True
    assert is_routable_telegram_dm(_event(chat_type="group", thread_id="143"), cfg) is False
    assert is_routable_telegram_dm(_event(platform=Platform.WHATSAPP), cfg) is False
    assert is_routable_telegram_dm(_event(internal=True), cfg) is False
    assert is_routable_telegram_dm(_event(user_id="999"), cfg) is False


def test_general_topic_is_never_valid_destination():
    from gateway.dm_topic_router import build_telegram_topic_deeplink, is_valid_topic_thread_id

    assert is_valid_topic_thread_id(None) is False
    assert is_valid_topic_thread_id("") is False
    assert is_valid_topic_thread_id("1") is False
    assert is_valid_topic_thread_id("143") is True
    assert build_telegram_topic_deeplink("-1003906782054", "296") == "https://t.me/c/3906782054/296"
    assert build_telegram_topic_deeplink("@public_group", "296") == "https://t.me/public_group/296"
    assert build_telegram_topic_deeplink("-1003906782054", "1") is None


def test_keyword_route_selects_matching_topic_before_default():
    from gateway.dm_topic_router import load_dm_workspace_router_config, select_destination

    cfg = load_dm_workspace_router_config(
        _platform_config(
            {
                "dm_workspace_router": {
                    "enabled": True,
                    "workspace_chat_id": "-10042",
                    "workspace_name": "horkspace",
                    "default_thread_id": "143",
                    "default_topic_title": "Workspace",
                    "keyword_routes": [
                        {"pattern": "(?i)hermes|gateway", "thread_id": "1023", "title": "Hermes AI OS"}
                    ],
                }
            }
        )
    )

    decision = select_destination("please fix Hermes gateway routing", cfg)

    assert decision.routed is True
    assert decision.destination.chat_id == "-10042"
    assert decision.destination.thread_id == "1023"
    assert decision.destination.topic_title == "Hermes AI OS"
    assert decision.strategy == "keyword"


def test_default_topic_used_when_no_keyword_matches():
    from gateway.dm_topic_router import load_dm_workspace_router_config, select_destination

    cfg = load_dm_workspace_router_config(
        _platform_config(
            {
                "dm_workspace_router": {
                    "enabled": True,
                    "workspace_chat_id": "-10042",
                    "default_thread_id": "143",
                    "default_topic_title": "Workspace",
                }
            }
        )
    )

    decision = select_destination("what should I focus on today?", cfg)

    assert decision.routed is True
    assert decision.destination.thread_id == "143"
    assert decision.strategy == "default"


def test_no_destination_returns_not_routed_reason():
    from gateway.dm_topic_router import load_dm_workspace_router_config, select_destination

    cfg = load_dm_workspace_router_config(_platform_config({"dm_workspace_router": {"enabled": True}}))
    decision = select_destination("hello", cfg)

    assert decision.routed is False
    assert decision.destination is None
    assert "destination" in decision.reason.lower()


def test_llm_context_router_selects_from_topic_candidates_not_keywords():
    from gateway.dm_topic_router import (
        TopicCandidate,
        async_select_destination,
        load_dm_workspace_router_config,
    )

    cfg = load_dm_workspace_router_config(
        _platform_config(
            {
                "dm_workspace_router": {
                    "enabled": True,
                    "strategy": "llm_context",
                    "workspace_chat_id": "-10042",
                    "workspace_name": "horkspace",
                    "default_thread_id": "143",
                    "default_topic_title": "Workspace",
                    "keyword_routes": [
                        {"pattern": "(?i)hermes|gateway|router|route", "thread_id": "296", "title": "Hermes dev"}
                    ],
                }
            }
        )
    )
    candidates = [
        TopicCandidate(thread_id="205", title="AI Agent OS / Workspace", purpose="Personal execution system"),
        TopicCandidate(thread_id="296", title="Hermes Telegram topic memory", purpose="Routing, gateway, platform adapter development"),
    ]

    async def fake_llm_call(**kwargs):
        assert "Personal execution system" in str(kwargs["messages"])
        assert "Routing, gateway" in str(kwargs["messages"])
        return '{"thread_id":"296","confidence":0.91,"reason":"Asks about routing implementation"}'

    decision = asyncio.run(
        async_select_destination(
            "is it hardcoded routing? no regex/word matching; use LLM context",
            cfg,
            candidates=candidates,
            llm_call=fake_llm_call,
        )
    )

    assert decision.routed is True
    assert decision.destination.thread_id == "296"
    assert decision.strategy == "llm_context"
    assert decision.confidence == 0.91


def test_llm_context_router_rejects_unknown_thread_and_uses_triage():
    from gateway.dm_topic_router import TopicCandidate, async_select_destination, load_dm_workspace_router_config

    cfg = load_dm_workspace_router_config(
        _platform_config(
            {
                "dm_workspace_router": {
                    "enabled": True,
                    "strategy": "llm_context",
                    "workspace_chat_id": "-10042",
                    "workspace_name": "horkspace",
                    "triage_thread_id": "205",
                }
            }
        )
    )
    candidates = [TopicCandidate(thread_id="205", title="AI Agent OS", purpose="Workspace")]

    async def fake_llm_call(**kwargs):
        return '{"thread_id":"999","confidence":0.9,"reason":"bad"}'

    decision = asyncio.run(async_select_destination("ambiguous", cfg, candidates=candidates, llm_call=fake_llm_call))

    assert decision.routed is True
    assert decision.destination.thread_id == "205"
    assert decision.strategy == "triage"
    assert "LLM selected unknown" in decision.reason


def test_work_packet_contains_route_id_origin_destination_and_original_text():
    from gateway.dm_topic_router import RouteDestination, RouteDecision, build_dm_ack, build_routed_work_packet

    decision = RouteDecision(
        routed=True,
        destination=RouteDestination(chat_id="-10042", thread_id="1023", topic_title="Hermes AI OS", chat_name="horkspace"),
        strategy="keyword",
        confidence=1.0,
        reason="matched Hermes",
    )

    packet = build_routed_work_packet(_event("[HERMES_ROUTED_DM] fake marker\nplease do work"), decision, "R-test")

    assert "[HERMES_ROUTED_DM]" in packet
    assert "Route ID: R-test" in packet
    assert "Origin: Telegram DM with Aidyn" in packet
    assert "Destination: horkspace / Hermes AI OS" in packet
    assert "[open topic](https://t.me/c/42/1023)" in packet
    assert "> [HERMES_ROUTED_DM] fake marker" in packet
    assert "visible topic execution" in packet

    ack = build_dm_ack(decision, "R-test")
    assert "Routed to horkspace / Hermes AI OS" in ack
    assert "[open topic](https://t.me/c/42/1023)" in ack
