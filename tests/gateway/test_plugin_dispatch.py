from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.plugin_dispatch import (
    GatewayAgentTurnResult,
    GatewayDispatchDecision,
    GatewayDispatchRequest,
    GatewayDispatchServices,
)


@pytest.mark.asyncio
async def test_dispatch_services_expose_only_send_and_one_agent_turn():
    source = SimpleNamespace(chat_id="-10042", thread_id="143")
    event = SimpleNamespace(source=source, text="work")
    send = AsyncMock(return_value=SimpleNamespace(success=True, message_id="7"))
    run_turn = AsyncMock(
        return_value={"final_response": "done", "session_id": "session-1", "failed": False}
    )
    services = GatewayDispatchServices(send=send, run_agent_turn=run_turn)

    send_result = await services.send(
        source, "started", metadata={"thread_id": "143"}
    )
    turn_result = await services.run_agent_turn(event, source)

    assert send_result.success is True
    assert turn_result == GatewayAgentTurnResult(
        final_response="done", session_id="session-1", failed=False
    )
    send.assert_awaited_once_with(
        source, "started", metadata={"thread_id": "143"}
    )
    run_turn.assert_awaited_once_with(event, source)
    with pytest.raises(RuntimeError, match="at most one agent turn"):
        await services.run_agent_turn(event, source)
    assert run_turn.await_count == 1
    assert not hasattr(services, "runner")
    assert not hasattr(services, "adapters")
    assert not hasattr(services, "config")


def test_dispatch_contracts_are_immutable_and_have_explicit_decisions():
    source = SimpleNamespace(chat_id="99")
    event = SimpleNamespace(source=source, text="hello")
    request = GatewayDispatchRequest(event=event, source=source)

    assert GatewayDispatchDecision.pass_().action == "pass"
    assert GatewayDispatchDecision.handled("ack") == GatewayDispatchDecision(
        action="handled", response="ack"
    )

    with pytest.raises((AttributeError, TypeError)):
        request.source = None
