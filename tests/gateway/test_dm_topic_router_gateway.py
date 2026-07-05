"""Gateway integration tests for Telegram DM -> workspace topic router."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, SendResult
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_dm_event(text="please route this", *, user_id="289", message_id="m1", internal=False):
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id=user_id,
            chat_type="dm",
            user_id=user_id,
            user_name="Aidyn",
            message_id=message_id,
        ),
        message_id=message_id,
        platform_update_id=42,
        internal=internal,
    )


def _make_group_event(text="topic prompt", *, thread_id="143"):
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="-10042",
            chat_name="horkspace",
            chat_type="group",
            user_id="289",
            user_name="Aidyn",
            thread_id=thread_id,
        ),
        message_id="gm1",
    )


def _make_runner(*, router_enabled=True, authorized=True):
    from gateway.run import GatewayRunner

    extra = {}
    if router_enabled:
        extra["dm_workspace_router"] = {
            "enabled": True,
            "workspace_chat_id": "-10042",
            "workspace_name": "horkspace",
            "default_thread_id": "143",
            "default_topic_title": "Workspace",
            "allowed_user_ids": ["289"],
        }
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="fake", extra=extra)},
        thread_sessions_per_user=False,
    )
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=SendResult(success=True, message_id="777"))
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), emit_collect=AsyncMock(return_value=[]), loaded_hooks=False)
    runner.session_store = MagicMock()
    runner.session_store._generate_session_key.side_effect = lambda source: build_session_key(source)
    runner.session_store.get_or_create_session.side_effect = lambda source, force_new=False: SessionEntry(
        session_key=build_session_key(source),
        session_id="sess",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type=source.chat_type,
        origin=source,
    )
    runner.session_store.has_any_sessions.return_value = True
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._queued_events = {}
    runner._busy_ack_ts = {}
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._session_db = None
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._draining = False
    runner._busy_input_mode = "interrupt"
    runner._update_prompt_pending = {}
    runner._is_user_authorized = lambda _source: authorized
    runner._get_unauthorized_dm_behavior = lambda _platform, **_kwargs: "ignore"
    runner._session_key_for_source = lambda source: build_session_key(source)
    runner._set_session_env = lambda _context: None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._send_voice_reply = AsyncMock()
    runner._capture_gateway_honcho_if_configured = lambda *args, **kwargs: None
    runner._emit_gateway_run_progress = AsyncMock()
    runner._invalidate_session_run_generation = MagicMock()
    runner._begin_session_run_generation = MagicMock(return_value=1)
    runner._is_session_run_current = MagicMock(return_value=True)
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": False}}
    runner._release_running_agent_state = MagicMock()
    runner._evict_cached_agent = MagicMock()
    runner._clear_session_boundary_security_state = MagicMock()
    runner._set_session_reasoning_override = MagicMock()
    runner._format_session_info = MagicMock(return_value="")
    runner.pairing_store = MagicMock()
    runner._handle_message_with_agent = AsyncMock(return_value="agent response")
    return runner


def test_authorized_telegram_dm_routes_to_topic_and_runs_agent_in_topic(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        runner = _make_runner(router_enabled=True, authorized=True)

        result = await runner._handle_message(_make_dm_event("please route workspace task"))
        return runner, result

    runner, result = asyncio.run(_run())

    assert "Routed to horkspace / Workspace" in result
    assert "Route ID:" in result
    runner._handle_message_with_agent.assert_awaited_once()
    routed_event = runner._handle_message_with_agent.await_args.args[0]
    assert routed_event.internal is True
    assert routed_event.source.chat_type == "group"
    assert routed_event.source.thread_id == "143"
    assert runner.adapters[Platform.TELEGRAM].send.await_count == 4
    chat_id, packet = runner.adapters[Platform.TELEGRAM].send.await_args_list[0].args[:2]
    assert chat_id == "-10042"
    assert "[HERMES_ROUTED_DM]" in packet
    assert "please route workspace task" in packet
    assert runner.adapters[Platform.TELEGRAM].send.await_args_list[0].kwargs["metadata"]["thread_id"] == "143"
    assert "Started visible execution" in runner.adapters[Platform.TELEGRAM].send.await_args_list[1].args[1]
    assert "[open topic](https://t.me/c/42/143)" in runner.adapters[Platform.TELEGRAM].send.await_args_list[1].args[1]
    assert "[ROUTE" in runner.adapters[Platform.TELEGRAM].send.await_args_list[2].args[1]
    assert "Done in horkspace / Workspace" in runner.adapters[Platform.TELEGRAM].send.await_args_list[3].args[1]
    assert "[open topic](https://t.me/c/42/143)" in runner.adapters[Platform.TELEGRAM].send.await_args_list[3].args[1]


def test_router_disabled_authorized_dm_runs_normal_agent(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        runner = _make_runner(router_enabled=False, authorized=True)

        result = await runner._handle_message(_make_dm_event())
        return runner, result

    runner, result = asyncio.run(_run())

    assert result == "agent response"
    runner._handle_message_with_agent.assert_awaited_once()
    runner.adapters[Platform.TELEGRAM].send.assert_not_called()


def test_unauthorized_dm_does_not_route(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        runner = _make_runner(router_enabled=True, authorized=False)

        result = await runner._handle_message(_make_dm_event())
        return runner, result

    runner, result = asyncio.run(_run())

    assert result is None
    runner._handle_message_with_agent.assert_not_called()
    runner.adapters[Platform.TELEGRAM].send.assert_not_called()


def test_group_topic_message_bypasses_router_and_runs_agent_normally(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        runner = _make_runner(router_enabled=True, authorized=True)

        result = await runner._handle_message(_make_group_event())
        return runner, result

    runner, result = asyncio.run(_run())

    assert result == "agent response"
    runner._handle_message_with_agent.assert_awaited_once()
    runner.adapters[Platform.TELEGRAM].send.assert_not_called()


def test_topic_send_failure_returns_failure_ack_and_skips_private_agent(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        runner = _make_runner(router_enabled=True, authorized=True)
        runner.adapters[Platform.TELEGRAM].send = AsyncMock(return_value=SendResult(success=False, error="boom"))

        result = await runner._handle_message(_make_dm_event())
        return runner, result

    runner, result = asyncio.run(_run())

    assert "Routing failed" in result
    assert "boom" in result
    runner._handle_message_with_agent.assert_not_called()


def test_duplicate_origin_message_returns_existing_ack_without_second_topic_send(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        runner = _make_runner(router_enabled=True, authorized=True)
        event = _make_dm_event(message_id="same")

        first = await runner._handle_message(event)
        second = await runner._handle_message(event)
        return runner, first, second

    runner, first, second = asyncio.run(_run())

    assert "Routed to" in first
    assert "Already routed" in second
    # First DM routes once, runs visibly in-topic, publishes final, and sends a
    # compact DM callback. The duplicate DM only returns an acknowledgement and
    # must not create another topic packet or second agent run.
    assert runner.adapters[Platform.TELEGRAM].send.await_count == 4
    runner._handle_message_with_agent.assert_awaited_once()
