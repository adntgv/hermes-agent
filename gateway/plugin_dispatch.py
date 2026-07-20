"""Narrow contracts for optional gateway message-dispatch plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Mapping, Optional

from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


@dataclass(frozen=True)
class GatewayDispatchRequest:
    """An authorized external event offered to a gateway plugin."""

    event: MessageEvent
    source: SessionSource


@dataclass(frozen=True)
class GatewayDispatchDecision:
    """Whether a plugin passed or fully handled an offered event."""

    action: Literal["pass", "handled"]
    response: Optional[str] = None

    @classmethod
    def pass_(cls) -> "GatewayDispatchDecision":
        return cls(action="pass")

    @classmethod
    def handled(cls, response: Optional[str] = None) -> "GatewayDispatchDecision":
        return cls(action="handled", response=response)


@dataclass(frozen=True)
class GatewayAgentTurnResult:
    """Normalized result of one core-owned gateway agent turn."""

    final_response: str = ""
    session_id: Optional[str] = None
    failed: bool = False


SendCallback = Callable[..., Awaitable[Any]]
RunAgentTurnCallback = Callable[
    [MessageEvent, SessionSource], Awaitable[Any]
]


class GatewayDispatchServices:
    """Restricted host operations available to dispatch plugins."""

    __slots__ = ("_send", "_run_agent_turn")

    def __init__(
        self,
        *,
        send: SendCallback,
        run_agent_turn: RunAgentTurnCallback,
    ) -> None:
        self._send = send
        self._run_agent_turn = run_agent_turn

    async def send(
        self,
        source: SessionSource,
        text: str,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        return await self._send(source, text, metadata=metadata)

    async def run_agent_turn(
        self,
        event: MessageEvent,
        source: SessionSource,
    ) -> GatewayAgentTurnResult:
        result = await self._run_agent_turn(event, source)
        if isinstance(result, GatewayAgentTurnResult):
            return result
        if isinstance(result, dict):
            return GatewayAgentTurnResult(
                final_response=str(result.get("final_response") or ""),
                session_id=(
                    str(result["session_id"])
                    if result.get("session_id") is not None
                    else None
                ),
                failed=bool(result.get("failed", False)),
            )
        return GatewayAgentTurnResult(final_response=str(result or ""))
