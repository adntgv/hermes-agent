"""Durable Telegram group/forum topic registry.

The registry stores compact, topic-scoped metadata for Telegram forum topics so
Hermes can keep separate persistent context per ``(chat_id, thread_id)`` without
putting topic facts into global memory.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from hermes_constants import get_hermes_home


_REGISTRY_LOCK = threading.RLock()
_MAX_LIST_ITEMS = 20
_MAX_TEXT_CHARS = 3000
_MAX_TRANSCRIPT_CHARS = 12000
_MIN_COMPACT_MESSAGES = 6
_COMPACT_DELTA_MESSAGES = 4
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_text(value: Any, *, max_chars: int = _MAX_TEXT_CHARS) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def _clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw = [values]
    else:
        try:
            raw = list(values)
        except TypeError:
            raw = [values]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _clean_text(item, max_chars=500)
        if not text:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        dedup_key = text.casefold()
        if dedup_key in seen:
            continue
        cleaned.append(text)
        seen.add(dedup_key)
        if len(cleaned) >= _MAX_LIST_ITEMS:
            break
    return cleaned


def _merge_lists(*lists: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for values in lists:
        for item in _clean_list(values):
            key = item.casefold()
            if key in seen:
                continue
            merged.append(item)
            seen.add(key)
            if len(merged) >= _MAX_LIST_ITEMS:
                return merged
    return merged


def _format_transcript(transcript: list[dict[str, Any]], *, max_chars: int = _MAX_TRANSCRIPT_CHARS) -> str:
    lines: list[str] = []
    for msg in transcript:
        role = str(msg.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _clean_text(msg.get("content"), max_chars=1500)
        if not content:
            continue
        lines.append(f"{role.upper()}: {content}")
    text = "\n\n".join(lines)
    if len(text) > max_chars:
        text = text[-max_chars:]
        first_break = text.find("\n\n")
        if first_break > 0:
            text = text[first_break + 2 :]
        text = "…[older topic transcript truncated]\n" + text
    return text


def parse_topic_memory_delta(raw: Any) -> dict[str, Any]:
    """Parse an LLM JSON object into a topic-memory delta dict."""
    if isinstance(raw, dict):
        return raw
    text = _clean_text(raw, max_chars=10000) or ""
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class TelegramTopicRegistry:
    """Profile-local JSON registry keyed by Telegram chat id and thread id."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else get_hermes_home() / "gateway" / "telegram_topics.json"

    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "telegram_topics": {}}

    def load(self) -> dict[str, Any]:
        with _REGISTRY_LOCK:
            if not self.path.exists():
                return self._empty()
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return self._empty()
            if not isinstance(data, dict):
                return self._empty()
            data.setdefault("version", 1)
            topics = data.setdefault("telegram_topics", {})
            if not isinstance(topics, dict):
                data["telegram_topics"] = {}
            return data

    def save(self, data: dict[str, Any]) -> None:
        with _REGISTRY_LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self.path)

    def _ensure_topic(self, data: dict[str, Any], chat_id: str, thread_id: str) -> dict[str, Any]:
        chat_key = str(chat_id)
        thread_key = str(thread_id)
        chats = data.setdefault("telegram_topics", {})
        chat_record = chats.setdefault(chat_key, {})
        chat_record.setdefault("chat_id", chat_key)
        chat_record.setdefault("topics", {})
        topics = chat_record.setdefault("topics", {})
        now = _now_iso()
        topic = topics.setdefault(
            thread_key,
            {
                "thread_id": thread_key,
                "title": None,
                "purpose_summary": None,
                "pinned_facts": [],
                "open_loops": [],
                "auto_skills": [],
                "status": "open",
                "source": "discovered",
                "last_compacted_at": None,
                "last_compacted_message_count": 0,
                "discovered_at": now,
                "updated_at": now,
            },
        )
        return topic

    def record_topic(
        self,
        *,
        chat_id: str,
        thread_id: str,
        chat_title: Any = None,
        title: Any = None,
        purpose_summary: Any = None,
        pinned_facts: Any = None,
        open_loops: Any = None,
        auto_skills: Any = None,
        status: Any = None,
        source: str = "discovered",
        latest_session_key: Any = None,
        latest_session_id: Any = None,
        latest_message_id: Any = None,
    ) -> dict[str, Any]:
        """Create/update a topic record and return a copy of it."""
        with _REGISTRY_LOCK:
            data = self.load()
            topic = self._ensure_topic(data, str(chat_id), str(thread_id))
            chat_record = data["telegram_topics"][str(chat_id)]
            chat_record["chat_title"] = _clean_text(chat_title) or chat_record.get("chat_title")
            chat_record["updated_at"] = _now_iso()

            updates = {
                "title": _clean_text(title, max_chars=200),
                "purpose_summary": "" if purpose_summary == "" else _clean_text(purpose_summary),
                "status": _clean_text(status, max_chars=80),
                "source": _clean_text(source, max_chars=80),
                "latest_session_key": _clean_text(latest_session_key, max_chars=300),
                "latest_session_id": _clean_text(latest_session_id, max_chars=120),
                "latest_message_id": _clean_text(latest_message_id, max_chars=80),
            }
            for key, value in updates.items():
                if value is not None:
                    topic[key] = value
            if pinned_facts is not None:
                topic["pinned_facts"] = _clean_list(pinned_facts)
            if open_loops is not None:
                topic["open_loops"] = _clean_list(open_loops)
            if auto_skills is not None:
                topic["auto_skills"] = _clean_list(auto_skills)
            topic["updated_at"] = _now_iso()
            self.save(data)
            return deepcopy(topic)

    def record_message(
        self,
        *,
        chat_id: str,
        thread_id: str,
        chat_title: Any = None,
        topic_title: Any = None,
        message_id: Any = None,
        auto_skill: Any = None,
    ) -> dict[str, Any]:
        skills = None
        if auto_skill:
            skills = auto_skill if isinstance(auto_skill, list) else [auto_skill]
        return self.record_topic(
            chat_id=str(chat_id),
            thread_id=str(thread_id),
            chat_title=chat_title,
            title=topic_title,
            latest_message_id=message_id,
            auto_skills=skills,
            source="message",
        )

    def update_topic_memory(self, *, chat_id: str, thread_id: str, pinned_facts: Any = None, open_loops: Any = None, purpose_summary: Any = None) -> dict[str, Any]:
        return self.record_topic(
            chat_id=str(chat_id),
            thread_id=str(thread_id),
            purpose_summary=purpose_summary,
            pinned_facts=pinned_facts,
            open_loops=open_loops,
            source="memory",
        )

    def apply_memory_delta(
        self,
        *,
        chat_id: str,
        thread_id: str,
        delta: dict[str, Any],
        compacted_message_count: Optional[int] = None,
    ) -> dict[str, Any]:
        """Merge a structured summarizer delta into compact topic memory."""
        delta = delta if isinstance(delta, dict) else {}
        with _REGISTRY_LOCK:
            data = self.load()
            topic = self._ensure_topic(data, str(chat_id), str(thread_id))
            purpose = _clean_text(delta.get("purpose_summary")) or topic.get("purpose_summary")
            decisions = [f"Decision: {item}" for item in _clean_list(delta.get("decisions"))]
            topic["purpose_summary"] = purpose
            topic["pinned_facts"] = _merge_lists(
                topic.get("pinned_facts"),
                delta.get("pinned_facts"),
                delta.get("facts"),
                decisions,
            )
            topic["open_loops"] = _merge_lists(
                topic.get("open_loops"),
                delta.get("open_loops"),
                delta.get("next_steps"),
            )
            if compacted_message_count is not None:
                try:
                    topic["last_compacted_message_count"] = max(0, int(compacted_message_count))
                except (TypeError, ValueError):
                    pass
            topic["last_compacted_at"] = _now_iso()
            topic["source"] = "memory"
            topic["updated_at"] = _now_iso()
            self.save(data)
            return deepcopy(topic)

    def get_topic(self, chat_id: str, thread_id: str) -> Optional[dict[str, Any]]:
        data = self.load()
        try:
            topic = data["telegram_topics"][str(chat_id)]["topics"][str(thread_id)]
        except KeyError:
            return None
        return deepcopy(topic)

    def list_topics(self, chat_id: str) -> list[dict[str, Any]]:
        data = self.load()
        topics = data.get("telegram_topics", {}).get(str(chat_id), {}).get("topics", {})
        return [deepcopy(v) for _, v in sorted(topics.items(), key=lambda kv: str(kv[0]))]

    def audit_sessions_file(self, sessions_file: Optional[str | Path] = None) -> dict[str, int]:
        """Backfill/update Telegram forum topics discovered in sessions.json.

        Telegram Bot API cannot enumerate arbitrary historical forum topics, but
        Hermes' session index remembers origins for topics the gateway already
        saw. This read-only audit source lets the durable topic registry recover
        those lanes after registry loss or feature rollout.
        """
        path = Path(sessions_file) if sessions_file else get_hermes_home() / "sessions" / "sessions.json"
        result = {"scanned": 0, "eligible": 0, "created": 0, "updated": 0, "skipped": 0}
        if not path.exists():
            return result
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Could not read Telegram topic audit sessions file: %s", path)
            return result
        if not isinstance(raw, dict):
            return result

        for session_key, entry in raw.items():
            result["scanned"] += 1
            if not isinstance(entry, dict):
                result["skipped"] += 1
                continue
            origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
            platform = origin.get("platform") or entry.get("platform")
            chat_type = origin.get("chat_type") or entry.get("chat_type")
            chat_id = origin.get("chat_id")
            thread_id = origin.get("thread_id")

            if (not chat_id or not thread_id) and str(platform) == "telegram":
                parts = str(session_key).split(":")
                try:
                    idx = parts.index("telegram")
                    if len(parts) > idx + 3 and parts[idx + 1] in {"group", "channel", "thread"}:
                        chat_id = chat_id or parts[idx + 2]
                        thread_id = thread_id or parts[idx + 3]
                        chat_type = chat_type or parts[idx + 1]
                except ValueError:
                    pass

            if str(platform) != "telegram" or not chat_id or not thread_id or str(chat_type) == "dm":
                result["skipped"] += 1
                continue

            result["eligible"] += 1
            existing = self.get_topic(str(chat_id), str(thread_id))
            self.record_topic(
                chat_id=str(chat_id),
                thread_id=str(thread_id),
                chat_title=origin.get("chat_name"),
                title=None if existing and existing.get("title") else origin.get("chat_topic"),
                source=existing.get("source") if existing and existing.get("source") else "sessions_audit",
                latest_session_key=entry.get("session_key") or session_key,
                latest_session_id=entry.get("session_id"),
            )
            if existing:
                result["updated"] += 1
            else:
                result["created"] += 1
        return result

    def format_topic_context(self, *, chat_id: str, thread_id: str, chat_name: Optional[str] = None) -> str:
        topic = self.get_topic(chat_id, thread_id)
        if not topic:
            return ""
        title = topic.get("title") or f"Topic {thread_id}"
        group_label = chat_name or str(chat_id)
        lines = [
            f"**Telegram group topic:** {group_label} / {title}",
            f"**Topic ID:** {thread_id}",
        ]
        if topic.get("purpose_summary"):
            lines.append(f"**Topic purpose:** {topic['purpose_summary']}")
        facts = _clean_list(topic.get("pinned_facts"))
        loops = _clean_list(topic.get("open_loops"))
        if facts:
            lines.append("**Topic memory:**")
            lines.extend(f"- {fact}" for fact in facts[:8])
        if loops:
            lines.append("**Open loops:**")
            lines.extend(f"- {loop}" for loop in loops[:8])
        return "\n".join(lines)


def build_topic_memory_update_prompt(
    *,
    registry: TelegramTopicRegistry,
    chat_id: str,
    thread_id: str,
    transcript: list[dict[str, Any]],
) -> str:
    """Build a strict, topic-scoped prompt for compact memory extraction."""
    topic = registry.get_topic(chat_id, thread_id) or {}
    transcript_text = _format_transcript(transcript)
    current_memory = {
        "title": topic.get("title"),
        "purpose_summary": topic.get("purpose_summary"),
        "pinned_facts": _clean_list(topic.get("pinned_facts")),
        "open_loops": _clean_list(topic.get("open_loops")),
    }
    return (
        "You maintain compact memory for exactly one Telegram group forum topic.\n"
        "Do not include facts from other topics, global user preferences, secrets, credentials, or raw private data.\n"
        "Return ONLY a JSON object with keys: purpose_summary, pinned_facts, open_loops, decisions.\n"
        "- purpose_summary: one sentence describing this topic's ongoing purpose.\n"
        "- pinned_facts: durable facts needed to continue future work in this topic.\n"
        "- open_loops: unresolved tasks/questions for this topic.\n"
        "- decisions: explicit decisions reached in this topic.\n\n"
        f"Telegram chat_id: {chat_id}\n"
        f"Telegram thread_id: {thread_id}\n"
        f"Topic title: {topic.get('title') or f'Topic {thread_id}'}\n\n"
        f"CURRENT COMPACT TOPIC MEMORY:\n{json.dumps(current_memory, ensure_ascii=False, indent=2)}\n\n"
        f"CURRENT TOPIC TRANSCRIPT EXCERPT ONLY:\n{transcript_text}\n"
    )


def should_update_topic_memory(
    *,
    registry: TelegramTopicRegistry,
    chat_id: str,
    thread_id: str,
    message_count: int,
    min_messages: int = _MIN_COMPACT_MESSAGES,
    delta_messages: int = _COMPACT_DELTA_MESSAGES,
) -> bool:
    topic = registry.get_topic(chat_id, thread_id) or {}
    if message_count < min_messages:
        return False
    try:
        last = int(topic.get("last_compacted_message_count") or 0)
    except (TypeError, ValueError):
        last = 0
    return message_count - last >= delta_messages


def merge_topic_auto_skills(
    *,
    chat_id: str,
    thread_id: str,
    event_auto_skill: Any = None,
    registry: Optional[TelegramTopicRegistry] = None,
) -> Any:
    """Merge config/event auto skills with persisted per-topic skill bindings."""
    existing = event_auto_skill if isinstance(event_auto_skill, list) else ([event_auto_skill] if event_auto_skill else [])
    registry = registry or TelegramTopicRegistry()
    topic = registry.get_topic(chat_id, thread_id) or {}
    merged = _merge_lists(existing, topic.get("auto_skills"))
    if not merged:
        return None
    return merged[0] if len(merged) == 1 else merged


async def update_topic_memory_from_transcript(
    *,
    registry: TelegramTopicRegistry,
    chat_id: str,
    thread_id: str,
    transcript: list[dict[str, Any]],
    summarizer: Optional[Callable[[str], Awaitable[Any]]] = None,
) -> Optional[dict[str, Any]]:
    """Summarize a topic transcript excerpt into compact durable topic memory."""
    message_count = len([m for m in transcript if m.get("role") in {"user", "assistant"} and m.get("content")])
    if not should_update_topic_memory(
        registry=registry,
        chat_id=chat_id,
        thread_id=thread_id,
        message_count=message_count,
    ):
        return None
    prompt = build_topic_memory_update_prompt(
        registry=registry,
        chat_id=chat_id,
        thread_id=thread_id,
        transcript=transcript,
    )
    if summarizer is None:
        async def summarizer(p: str) -> Any:
            from agent.auxiliary_client import async_call_llm, extract_content_or_reasoning
            response = await async_call_llm(
                task="telegram_topic_memory",
                messages=[
                    {"role": "system", "content": "Extract compact Telegram topic memory. Return JSON only."},
                    {"role": "user", "content": p},
                ],
                temperature=0.1,
                max_tokens=900,
            )
            return extract_content_or_reasoning(response)
    try:
        delta = parse_topic_memory_delta(await summarizer(prompt))
    except Exception as exc:
        logger.debug("Telegram topic memory summarization failed: %s", exc)
        return None
    if not delta:
        return None
    return registry.apply_memory_delta(
        chat_id=chat_id,
        thread_id=thread_id,
        delta=delta,
        compacted_message_count=message_count,
    )
