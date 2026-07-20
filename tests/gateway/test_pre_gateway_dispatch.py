"""Tests for the pre_gateway_dispatch plugin hook.

The hook allows plugins to intercept incoming messages before auth and
agent dispatch. It runs in _handle_message and acts on returned action
dicts: {"action": "skip"|"rewrite"|"allow"}.
"""

import asyncio
import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.plugin_dispatch import GatewayDispatchDecision
from gateway.session import SessionSource


def _clear_auth_env(monkeypatch) -> None:
    for key in (
        "TELEGRAM_ALLOWED_USERS",
        "WHATSAPP_ALLOWED_USERS",
        "GATEWAY_ALLOWED_USERS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "WHATSAPP_ALLOW_ALL_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(key, raising=False)


def _make_event(text: str = "hello", platform: Platform = Platform.WHATSAPP) -> MessageEvent:
    return MessageEvent(
        text=text,
        message_id="m1",
        source=SessionSource(
            platform=platform,
            user_id="15551234567@s.whatsapp.net",
            chat_id="15551234567@s.whatsapp.net",
            user_name="tester",
            chat_type="dm",
        ),
    )


def _make_runner(platform: Platform):
    from gateway.run import GatewayRunner

    config = GatewayConfig(
        platforms={platform: PlatformConfig(enabled=True)},
    )
    runner = object.__new__(GatewayRunner)
    runner.config = config
    adapter = SimpleNamespace(send=AsyncMock())
    runner.adapters = {platform: adapter}
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = False
    runner.pairing_store._is_rate_limited.return_value = False
    runner.session_store = MagicMock()
    runner._running_agents = {}
    runner._update_prompt_pending = {}
    return runner, adapter


@pytest.mark.asyncio
async def test_hook_skip_short_circuits_dispatch(monkeypatch):
    """A plugin returning {'action': 'skip'} drops the message before auth."""
    _clear_auth_env(monkeypatch)

    def _fake_hook(name, **kwargs):
        if name == "pre_gateway_dispatch":
            return [{"action": "skip", "reason": "plugin-handled"}]
        return []

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", _fake_hook)

    runner, adapter = _make_runner(Platform.WHATSAPP)

    result = await runner._handle_message(_make_event("hi"))

    assert result is None
    adapter.send.assert_not_awaited()
    runner.pairing_store.generate_code.assert_not_called()


@pytest.mark.asyncio
async def test_hook_rewrite_replaces_event_text(monkeypatch):
    """A plugin returning {'action': 'rewrite', 'text': ...} mutates event.text."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")

    seen_text = {}

    def _fake_hook(name, **kwargs):
        if name == "pre_gateway_dispatch":
            return [{"action": "rewrite", "text": "REWRITTEN"}]
        return []

    async def _capture(event, source, _quick_key, _run_generation):
        seen_text["value"] = event.text
        return "ok"

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", _fake_hook)

    runner, _adapter = _make_runner(Platform.WHATSAPP)
    runner._handle_message_with_agent = _capture  # noqa: SLF001

    await runner._handle_message(_make_event("original"))

    assert seen_text.get("value") == "REWRITTEN"


@pytest.mark.asyncio
async def test_hook_allow_falls_through_to_auth(monkeypatch):
    """A plugin returning {'action': 'allow'} continues to normal dispatch."""
    _clear_auth_env(monkeypatch)
    # No allowed users set → auth fails → pairing flow triggers.
    monkeypatch.delenv("WHATSAPP_ALLOWED_USERS", raising=False)

    def _fake_hook(name, **kwargs):
        if name == "pre_gateway_dispatch":
            return [{"action": "allow"}]
        return []

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", _fake_hook)

    runner, adapter = _make_runner(Platform.WHATSAPP)
    runner.pairing_store.generate_code.return_value = "12345"

    result = await runner._handle_message(_make_event("hi"))

    # auth chain ran → pairing code was generated
    assert result is None
    runner.pairing_store.generate_code.assert_called_once()


@pytest.mark.asyncio
async def test_hook_exception_does_not_break_dispatch(monkeypatch):
    """A raising plugin hook does not break the gateway."""
    _clear_auth_env(monkeypatch)
    monkeypatch.delenv("WHATSAPP_ALLOWED_USERS", raising=False)

    def _fake_hook(name, **kwargs):
        raise RuntimeError("plugin blew up")

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", _fake_hook)

    runner, _adapter = _make_runner(Platform.WHATSAPP)
    runner.pairing_store.generate_code.return_value = None

    # Should not raise; falls through to auth chain.
    result = await runner._handle_message(_make_event("hi"))
    assert result is None


@pytest.mark.asyncio
async def test_internal_events_bypass_hook(monkeypatch):
    """Internal events (event.internal=True) skip the plugin hook entirely."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")

    called = {"count": 0}

    def _fake_hook(name, **kwargs):
        called["count"] += 1
        return [{"action": "skip"}]

    async def _capture(event, source, _quick_key, _run_generation):
        return "ok"

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", _fake_hook)

    runner, _adapter = _make_runner(Platform.WHATSAPP)
    runner._handle_message_with_agent = _capture  # noqa: SLF001

    event = _make_event("hi")
    event.internal = True

    # Even though the hook would say skip, internal events bypass it.
    await runner._handle_message(event)
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_post_auth_dispatch_plugin_can_send_and_run_target_turn(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    runner, adapter = _make_runner(Platform.WHATSAPP)
    seen = {}

    async def _capture(event, source, _quick_key, _run_generation):
        seen["event"] = event
        seen["source"] = source
        return {"final_response": "target done", "session_id": "s-target"}

    async def _fake_async_hook(name, **kwargs):
        assert name == "post_gateway_auth_dispatch"
        request = kwargs["request"]
        services = kwargs["services"]
        await services.send(request.source, "plugin start", metadata={"tag": "x"})
        target_source = dataclasses.replace(
            request.source,
            chat_id="target-chat",
            chat_type="group",
            thread_id="143",
        )
        target_event = dataclasses.replace(request.event, source=target_source)
        turn = await services.run_agent_turn(target_event, target_source)
        assert turn.final_response == "target done"
        assert turn.session_id == "s-target"
        return [GatewayDispatchDecision.handled("plugin ack")]

    monkeypatch.setattr("hermes_cli.plugins.ainvoke_hook", _fake_async_hook)
    runner._handle_message_with_agent = _capture

    result = await runner._handle_message(_make_event("route me"))

    assert result == "plugin ack"
    adapter.send.assert_awaited_once()
    assert seen["source"].chat_id == "target-chat"
    assert seen["source"].thread_id == "143"
    assert seen["event"].internal is True


@pytest.mark.asyncio
async def test_post_auth_dispatch_hook_never_sees_unauthorized_or_internal_events(monkeypatch):
    _clear_auth_env(monkeypatch)
    called = []

    async def _fake_async_hook(name, **kwargs):
        called.append(name)
        return [GatewayDispatchDecision.handled("should not run")]

    monkeypatch.setattr("hermes_cli.plugins.ainvoke_hook", _fake_async_hook)
    runner, _adapter = _make_runner(Platform.WHATSAPP)
    runner.pairing_store.generate_code.return_value = None

    assert await runner._handle_message(_make_event("unauthorized")) is None

    internal = _make_event("internal")
    internal.internal = True
    runner._handle_message_with_agent = AsyncMock(return_value="normal")
    assert await runner._handle_message(internal) == "normal"
    assert "post_gateway_auth_dispatch" not in called
    assert called == ["post_gateway_turn"]


@pytest.mark.asyncio
async def test_post_gateway_turn_hook_receives_completed_authorized_turn(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    calls = []

    async def _fake_async_hook(name, **kwargs):
        calls.append((name, kwargs))
        return []

    monkeypatch.setattr("hermes_cli.plugins.ainvoke_hook", _fake_async_hook)
    runner, _adapter = _make_runner(Platform.WHATSAPP)
    runner._handle_message_with_agent = AsyncMock(
        return_value={"final_response": "done", "session_id": "s1"}
    )
    event = _make_event("finish")

    result = await runner._handle_message(event)

    assert result["final_response"] == "done"
    assert [name for name, _ in calls] == [
        "post_gateway_auth_dispatch",
        "post_gateway_turn",
    ]
    turn_kwargs = calls[-1][1]
    assert turn_kwargs["event"] is event
    assert turn_kwargs["source"] == event.source
    assert turn_kwargs["result"] == result


@pytest.mark.asyncio
async def test_post_auth_dispatch_is_serialized_per_session(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    active = 0
    maximum = 0

    async def _fake_async_hook(name, **_kwargs):
        nonlocal active, maximum
        if name != "post_gateway_auth_dispatch":
            return []
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.02)
        active -= 1
        return []

    async def _normal(*_args, **_kwargs):
        await asyncio.sleep(0.01)
        return "normal"

    monkeypatch.setattr("hermes_cli.plugins.ainvoke_hook", _fake_async_hook)
    runner, _adapter = _make_runner(Platform.WHATSAPP)
    runner._handle_message_with_agent = AsyncMock(side_effect=_normal)

    await asyncio.gather(
        runner._handle_message(_make_event("one")),
        runner._handle_message(_make_event("two")),
    )

    assert maximum == 1


@pytest.mark.asyncio
async def test_dispatch_service_rejects_different_target_user(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")

    async def _fake_async_hook(name, **kwargs):
        if name != "post_gateway_auth_dispatch":
            return []
        request = kwargs["request"]
        services = kwargs["services"]
        target_source = dataclasses.replace(request.source, user_id="other-user")
        target_event = dataclasses.replace(request.event, source=target_source)
        await services.run_agent_turn(target_event, target_source)
        return []

    monkeypatch.setattr("hermes_cli.plugins.ainvoke_hook", _fake_async_hook)
    runner, _adapter = _make_runner(Platform.WHATSAPP)
    runner._handle_message_with_agent = AsyncMock(return_value="must not run")

    result = await runner._handle_message(_make_event("route elsewhere"))

    assert "failed safely" in result
    runner._handle_message_with_agent.assert_not_awaited()
