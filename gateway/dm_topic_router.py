"""Telegram DM -> workspace topic routing helpers.

This module is intentionally pure-ish and config-gated.  It decides whether an
incoming Telegram DM should be mirrored into a configured workspace topic, builds
stable route packets, and persists an idempotent per-message route ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_hermes_home

from gateway.config import Platform, PlatformConfig


GENERAL_THREAD_IDS = {None, "", "1"}
ROUTED_PACKET_MARKER = "[HERMES_ROUTED_DM]"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class KeywordRoute:
    pattern: str
    thread_id: str
    title: str = ""
    chat_id: Optional[str] = None


@dataclass
class DmWorkspaceRouterConfig:
    enabled: bool = False
    strategy: str = "deterministic"
    workspace_chat_id: Optional[str] = None
    workspace_name: str = "workspace"
    default_thread_id: Optional[str] = None
    default_topic_title: str = "Workspace"
    triage_thread_id: Optional[str] = None
    ack_dm: bool = True
    mirror_intake: bool = True
    allowed_user_ids: set[str] = field(default_factory=set)
    keyword_routes: list[KeywordRoute] = field(default_factory=list)


@dataclass
class RouteDestination:
    chat_id: str
    thread_id: str
    topic_title: str
    chat_name: str = "workspace"


@dataclass
class RouteDecision:
    routed: bool
    destination: Optional[RouteDestination] = None
    strategy: str = "none"
    confidence: float = 0.0
    reason: str = ""


@dataclass
class TopicCandidate:
    thread_id: str
    title: str
    purpose: str = ""
    pinned_facts: list[str] = field(default_factory=list)
    open_loops: list[str] = field(default_factory=list)


def load_dm_workspace_router_config(platform_config: Optional[PlatformConfig]) -> DmWorkspaceRouterConfig:
    """Load router config from a Telegram PlatformConfig.extra mapping."""
    if platform_config is None:
        return DmWorkspaceRouterConfig()
    extra = getattr(platform_config, "extra", None) or {}
    raw = extra.get("dm_workspace_router") if isinstance(extra, dict) else None
    if not isinstance(raw, dict):
        return DmWorkspaceRouterConfig()

    keyword_routes: list[KeywordRoute] = []
    for item in raw.get("keyword_routes") or []:
        if not isinstance(item, dict):
            continue
        thread_id = _string_or_none(item.get("thread_id"))
        pattern = _string_or_none(item.get("pattern"))
        if not pattern or not is_valid_topic_thread_id(thread_id):
            continue
        keyword_routes.append(
            KeywordRoute(
                pattern=pattern,
                thread_id=str(thread_id),
                title=_string_or_none(item.get("title")) or _string_or_none(item.get("topic_title")) or "Workspace",
                chat_id=_string_or_none(item.get("chat_id")),
            )
        )

    allowed = raw.get("allowed_user_ids") or []
    if isinstance(allowed, (str, int)):
        allowed_set = {str(allowed)}
    else:
        allowed_set = {str(v) for v in allowed if v is not None}

    return DmWorkspaceRouterConfig(
        enabled=bool(raw.get("enabled", False)),
        strategy=_string_or_none(raw.get("strategy")) or "deterministic",
        workspace_chat_id=_string_or_none(raw.get("workspace_chat_id")),
        workspace_name=_string_or_none(raw.get("workspace_name")) or "workspace",
        default_thread_id=_string_or_none(raw.get("default_thread_id")),
        default_topic_title=_string_or_none(raw.get("default_topic_title"))
        or _string_or_none(raw.get("default_topic"))
        or "Workspace",
        triage_thread_id=_string_or_none(raw.get("triage_thread_id")),
        ack_dm=bool(raw.get("ack_dm", True)),
        mirror_intake=bool(raw.get("mirror_intake", True)),
        allowed_user_ids=allowed_set,
        keyword_routes=keyword_routes,
    )


def load_topic_candidates(config: DmWorkspaceRouterConfig, registry_path: Optional[Path | str] = None) -> list[TopicCandidate]:
    """Load semantic routing candidates from the durable Telegram topic registry."""
    if not config.workspace_chat_id:
        return []
    path = Path(registry_path) if registry_path else get_hermes_home() / "gateway" / "telegram_topics.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    chats = data.get("telegram_topics") if isinstance(data, dict) else None
    chat = chats.get(str(config.workspace_chat_id)) if isinstance(chats, dict) else None
    topics = chat.get("topics") if isinstance(chat, dict) else None
    if not isinstance(topics, dict):
        return []
    candidates: list[TopicCandidate] = []
    for thread_id, meta in topics.items():
        if not is_valid_topic_thread_id(thread_id) or not isinstance(meta, dict):
            continue
        status = str(meta.get("status") or "active").lower()
        if status in {"closed", "archived", "disabled"}:
            continue
        title = _string_or_none(meta.get("title")) or f"Topic {thread_id}"
        purpose = _string_or_none(meta.get("purpose_summary")) or ""
        pinned = [str(v) for v in (meta.get("pinned_facts") or [])[:5] if v]
        loops = [str(v) for v in (meta.get("open_loops") or [])[:5] if v]
        if not purpose and not pinned and not loops and title.startswith("Topic "):
            continue
        candidates.append(
            TopicCandidate(
                thread_id=str(thread_id),
                title=title,
                purpose=purpose,
                pinned_facts=pinned,
                open_loops=loops,
            )
        )
    return sorted(candidates, key=lambda c: c.thread_id)


def is_valid_topic_thread_id(thread_id: Any) -> bool:
    """Return True for routable non-General Telegram forum topic ids."""
    if thread_id is None:
        return False
    return str(thread_id).strip() not in {"", "1"}


def build_telegram_topic_deeplink(chat_id: Any, thread_id: Any) -> Optional[str]:
    """Return a Telegram link that opens a forum topic when possible.

    Private supergroup links use Telegram's ``/c/<internal-id>/<message-id>``
    form.  Forum topic ids are the root message ids for those topics, so linking
    to the thread id opens the topic itself.  Public ``@username`` destinations
    are supported defensively for future configs, while General/blank topics do
    not get a link because Telegram does not expose a stable forum-thread URL
    for them.
    """
    if not is_valid_topic_thread_id(thread_id):
        return None
    chat = _string_or_none(chat_id)
    thread = _string_or_none(thread_id)
    if not chat or not thread:
        return None

    if chat.startswith("-100") and chat[4:].isdigit():
        return f"https://t.me/c/{chat[4:]}/{thread}"
    if chat.startswith("@") and len(chat) > 1:
        return f"https://t.me/{chat[1:]}/{thread}"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,}", chat):
        return f"https://t.me/{chat}/{thread}"
    return None


def format_route_destination(destination: RouteDestination, *, include_thread: bool = True) -> str:
    """Human-readable destination label with a topic deeplink when available."""
    label = f"{destination.chat_name} / {destination.topic_title}"
    link = build_telegram_topic_deeplink(destination.chat_id, destination.thread_id)
    if link:
        label += f" — [open topic]({link})"
    if include_thread:
        label += f" (thread {destination.thread_id})"
    return label


def is_routable_telegram_dm(event: Any, config: DmWorkspaceRouterConfig) -> bool:
    """Check deterministic applicability before any topic send occurs."""
    if not config.enabled or event is None:
        return False
    if bool(getattr(event, "internal", False)):
        return False
    source = getattr(event, "source", None)
    if source is None:
        return False
    if getattr(source, "platform", None) != Platform.TELEGRAM:
        return False
    if getattr(source, "chat_type", None) != "dm":
        return False
    if getattr(source, "thread_id", None):
        return False
    user_id = _string_or_none(getattr(source, "user_id", None))
    if config.allowed_user_ids and user_id not in config.allowed_user_ids:
        return False
    if ROUTED_PACKET_MARKER in (getattr(event, "text", "") or ""):
        return False
    return True


def _triage_or_not_routed(config: DmWorkspaceRouterConfig, reason: str) -> RouteDecision:
    if is_valid_topic_thread_id(config.triage_thread_id):
        return RouteDecision(
            routed=True,
            destination=RouteDestination(
                chat_id=config.workspace_chat_id or "",
                thread_id=str(config.triage_thread_id),
                topic_title="Workspace triage",
                chat_name=config.workspace_name,
            ),
            strategy="triage",
            confidence=0.25,
            reason=reason,
        )
    return RouteDecision(False, reason=reason)


def _render_topic_candidates(candidates: list[TopicCandidate]) -> str:
    blocks: list[str] = []
    for c in candidates:
        parts = [f"thread_id={c.thread_id}", f"title={c.title}"]
        if c.purpose:
            parts.append(f"purpose={c.purpose}")
        if c.pinned_facts:
            parts.append("facts=" + "; ".join(c.pinned_facts))
        if c.open_loops:
            parts.append("open_loops=" + "; ".join(c.open_loops))
        blocks.append(" | ".join(parts))
    return "\n".join(blocks)


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end >= start:
        raw = raw[start : end + 1]
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


async def async_select_destination(
    text: str,
    config: DmWorkspaceRouterConfig,
    *,
    candidates: Optional[list[TopicCandidate]] = None,
    llm_call: Any = None,
) -> RouteDecision:
    """Select a destination. In llm_context mode, route by topic registry semantics."""
    if (config.strategy or "").strip().lower() not in {"llm", "llm_context", "semantic"}:
        return select_destination(text, config)
    if not config.enabled:
        return RouteDecision(False, reason="router disabled")
    if not config.workspace_chat_id:
        return RouteDecision(False, reason="no workspace destination chat configured")

    topic_candidates = candidates if candidates is not None else load_topic_candidates(config)
    valid = {c.thread_id: c for c in topic_candidates if is_valid_topic_thread_id(c.thread_id)}
    if not valid:
        return _triage_or_not_routed(config, "no semantic topic registry candidates available")

    prompt = (
        "Choose the Telegram forum topic that best matches Aidyn's DM based on semantic context, "
        "topic purpose, pinned facts, and open loops. Do not use keyword/regex rules. "
        "Return JSON only: {\"thread_id\":\"...\",\"confidence\":0.0-1.0,\"reason\":\"short\"}.\n\n"
        f"Aidyn DM:\n{text or ''}\n\nAvailable topics:\n{_render_topic_candidates(topic_candidates)}"
    )
    try:
        if llm_call is None:
            from agent.auxiliary_client import async_call_llm, extract_content_or_reasoning

            response = await async_call_llm(
                task="dm_topic_router",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=180,
                timeout=20,
            )
            content = extract_content_or_reasoning(response)
        else:
            response = await llm_call(
                task="dm_topic_router",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=180,
                timeout=20,
            )
            if isinstance(response, str):
                content = response
            else:
                from agent.auxiliary_client import extract_content_or_reasoning

                content = extract_content_or_reasoning(response)
        data = _extract_json_object(content)
    except Exception as exc:
        return _triage_or_not_routed(config, f"LLM topic routing failed: {exc}")

    selected = _string_or_none(data.get("thread_id"))
    if selected not in valid:
        return _triage_or_not_routed(config, f"LLM selected unknown thread_id: {selected}")
    candidate = valid[selected]
    try:
        confidence = float(data.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return RouteDecision(
        routed=True,
        destination=RouteDestination(
            chat_id=config.workspace_chat_id,
            thread_id=candidate.thread_id,
            topic_title=candidate.title,
            chat_name=config.workspace_name,
        ),
        strategy="llm_context",
        confidence=confidence,
        reason=_string_or_none(data.get("reason")) or "LLM selected topic from registry context",
    )


def select_destination(text: str, config: DmWorkspaceRouterConfig) -> RouteDecision:
    """Select a configured destination topic using deterministic rules."""
    if not config.enabled:
        return RouteDecision(False, reason="router disabled")
    if not config.workspace_chat_id:
        return RouteDecision(False, reason="no workspace destination chat configured")

    for route in config.keyword_routes:
        chat_id = route.chat_id or config.workspace_chat_id
        if chat_id != config.workspace_chat_id:
            continue
        try:
            matched = re.search(route.pattern, text or "") is not None
        except re.error:
            matched = False
        if matched and is_valid_topic_thread_id(route.thread_id):
            return RouteDecision(
                routed=True,
                destination=RouteDestination(
                    chat_id=chat_id,
                    thread_id=route.thread_id,
                    topic_title=route.title or config.default_topic_title,
                    chat_name=config.workspace_name,
                ),
                strategy="keyword",
                confidence=1.0,
                reason=f"matched keyword route: {route.pattern}",
            )

    if is_valid_topic_thread_id(config.default_thread_id):
        return RouteDecision(
            routed=True,
            destination=RouteDestination(
                chat_id=config.workspace_chat_id,
                thread_id=str(config.default_thread_id),
                topic_title=config.default_topic_title,
                chat_name=config.workspace_name,
            ),
            strategy="default",
            confidence=0.5,
            reason="used default workspace topic",
        )

    if is_valid_topic_thread_id(config.triage_thread_id):
        return RouteDecision(
            routed=True,
            destination=RouteDestination(
                chat_id=config.workspace_chat_id,
                thread_id=str(config.triage_thread_id),
                topic_title="Workspace triage",
                chat_name=config.workspace_name,
            ),
            strategy="triage",
            confidence=0.25,
            reason="used triage workspace topic",
        )

    return RouteDecision(False, reason="no routable destination topic configured")


def origin_key_for_event(event: Any) -> str:
    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", "unknown"))
    chat_id = _string_or_none(getattr(source, "chat_id", None)) or "unknown"
    thread_id = _string_or_none(getattr(source, "thread_id", None)) or "none"
    message_id = _string_or_none(getattr(event, "message_id", None)) or _string_or_none(getattr(source, "message_id", None))
    if not message_id:
        update_id = _string_or_none(getattr(event, "platform_update_id", None))
        if update_id:
            message_id = f"update:{update_id}"
        else:
            digest = hashlib.sha256((getattr(event, "text", "") or "").encode("utf-8")).hexdigest()[:16]
            message_id = f"hash:{digest}"
    return f"{platform}:{chat_id}:{thread_id}:{message_id}"


def build_route_id(event: Any, decision: RouteDecision) -> str:
    digest_input = "|".join(
        [
            origin_key_for_event(event),
            getattr(decision.destination, "chat_id", "") if decision.destination else "",
            getattr(decision.destination, "thread_id", "") if decision.destination else "",
        ]
    )
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:8]
    return f"R-{datetime.now().strftime('%Y%m%d')}-{digest}"


def _quote_user_text(text: str) -> str:
    lines = (text or "").splitlines() or [""]
    return "\n".join(f"> {line}" for line in lines)


def build_routed_work_packet(event: Any, decision: RouteDecision, route_id: str) -> str:
    if not decision.destination:
        raise ValueError("cannot build routed packet without destination")
    source = getattr(event, "source", None)
    user_name = _string_or_none(getattr(source, "user_name", None)) or "unknown user"
    user_id = _string_or_none(getattr(source, "user_id", None)) or "unknown"
    origin_mid = _string_or_none(getattr(event, "message_id", None)) or _string_or_none(getattr(source, "message_id", None)) or "unknown"
    dest = decision.destination
    dest_label = format_route_destination(dest)
    return (
        f"{ROUTED_PACKET_MARKER}\n"
        f"Route ID: {route_id}\n"
        f"Origin: Telegram DM with {user_name} ({user_id}), message {origin_mid}\n"
        f"Destination: {dest_label}\n"
        "Mode: visible topic execution; do the work in this topic.\n\n"
        "Aidyn wrote:\n"
        f"{_quote_user_text(getattr(event, 'text', '') or '')}\n\n"
        "Router decision:\n"
        f"- Strategy: {decision.strategy}\n"
        f"- Reason: {decision.reason}\n"
        f"- Confidence: {decision.confidence:.2f}\n\n"
        "Task:\n"
        "Handle this as Aidyn's request. Post progress here if non-trivial. "
        f"Use `[ROUTE {route_id}] Final` in the final topic answer."
    )


def build_dm_ack(decision: RouteDecision, route_id: str, *, already: bool = False) -> str:
    if not decision.destination:
        return f"Routing failed. Route ID: {route_id}. No destination topic was selected."
    prefix = "Already routed" if already else "Routed"
    dest = decision.destination
    dest_label = format_route_destination(dest, include_thread=False)
    return (
        f"{prefix} to {dest_label}.\n"
        f"Route ID: {route_id}\n"
        "I’ll work there visibly and keep this DM as the control plane."
    )


def build_dm_failure_ack(decision: RouteDecision, route_id: str, error: str) -> str:
    target = "selected topic"
    if decision.destination:
        target = f"{decision.destination.chat_name} / {decision.destination.topic_title}"
    return f"Routing failed to {target}.\nRoute ID: {route_id}\nError: {error}"


class DmTopicRouteLedger:
    """Small JSON route ledger for idempotency and later callbacks."""

    def __init__(self, path: Optional[Path | str] = None):
        self.path = Path(path) if path else get_hermes_home() / "gateway" / "telegram_dm_topic_routes.json"
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "routes": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("routes"), dict):
                raise ValueError("bad ledger shape")
            data.setdefault("version", 1)
            return data
        except Exception:
            return {"version": 1, "routes": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def get_by_origin_key(self, origin_key: str) -> Optional[dict[str, Any]]:
        return self.data.get("routes", {}).get(origin_key)

    def begin_route(self, event: Any, decision: RouteDecision, route_id: Optional[str] = None) -> dict[str, Any]:
        key = origin_key_for_event(event)
        existing = self.get_by_origin_key(key)
        if existing:
            return existing
        if not decision.destination:
            raise ValueError("cannot begin route without destination")
        source = getattr(event, "source", None)
        text = getattr(event, "text", "") or ""
        now = _now_iso()
        record = {
            "route_id": route_id or build_route_id(event, decision),
            "origin_key": key,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "origin": {
                "platform": getattr(getattr(source, "platform", None), "value", None),
                "chat_id": _string_or_none(getattr(source, "chat_id", None)),
                "chat_type": _string_or_none(getattr(source, "chat_type", None)),
                "thread_id": _string_or_none(getattr(source, "thread_id", None)),
                "user_id": _string_or_none(getattr(source, "user_id", None)),
                "user_name": _string_or_none(getattr(source, "user_name", None)),
                "message_id": _string_or_none(getattr(event, "message_id", None)) or _string_or_none(getattr(source, "message_id", None)),
                "platform_update_id": getattr(event, "platform_update_id", None),
            },
            "destination": {
                "platform": "telegram",
                "chat_id": decision.destination.chat_id,
                "chat_name": decision.destination.chat_name,
                "thread_id": decision.destination.thread_id,
                "topic_title": decision.destination.topic_title,
            },
            "decision": {
                "strategy": decision.strategy,
                "confidence": decision.confidence,
                "reason": decision.reason,
            },
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "destination_message_id": None,
            "error": None,
        }
        self.data.setdefault("routes", {})[key] = record
        self._save()
        return record

    def mark_sent(self, origin_key: str, destination_message_id: Optional[str] = None) -> dict[str, Any]:
        record = self.data.setdefault("routes", {}).setdefault(origin_key, {"origin_key": origin_key})
        record["status"] = "sent"
        record["updated_at"] = _now_iso()
        if destination_message_id is not None:
            record["destination_message_id"] = str(destination_message_id)
        record["error"] = None
        self._save()
        return record

    def mark_processing(self, origin_key: str) -> dict[str, Any]:
        record = self.data.setdefault("routes", {}).setdefault(origin_key, {"origin_key": origin_key})
        record["status"] = "processing"
        record["updated_at"] = _now_iso()
        record["error"] = None
        self._save()
        return record

    def mark_done(self, origin_key: str, final_message_id: Optional[str] = None) -> dict[str, Any]:
        record = self.data.setdefault("routes", {}).setdefault(origin_key, {"origin_key": origin_key})
        record["status"] = "done"
        record["updated_at"] = _now_iso()
        if final_message_id is not None:
            record["final_message_id"] = str(final_message_id)
        record["error"] = None
        self._save()
        return record

    def mark_failed(self, origin_key: str, error: str) -> dict[str, Any]:
        record = self.data.setdefault("routes", {}).setdefault(origin_key, {"origin_key": origin_key})
        record["status"] = "failed"
        record["updated_at"] = _now_iso()
        record["error"] = str(error)
        self._save()
        return record
