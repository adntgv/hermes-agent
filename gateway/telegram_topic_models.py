"""Durable per-topic model overrides for Telegram forum topics."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_hermes_home
from utils import atomic_json_write


_FILENAME = "telegram_topic_models.json"
_ALLOWED_KEYS = ("model", "provider", "base_url")


class TelegramTopicModelStore:
    """Profile-local JSON store keyed by Telegram chat and forum topic."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else get_hermes_home() / "gateway" / _FILENAME
        self._lock = threading.RLock()
        self._loaded = False
        self._models: dict[str, dict[str, str]] = {}

    @staticmethod
    def _key(chat_id: Any, thread_id: Any) -> str:
        chat = str(chat_id or "").strip()
        thread = str(thread_id or "").strip()
        if not chat or not thread:
            raise ValueError("Telegram topic model requires chat_id and thread_id")
        return f"{chat}:{thread}"

    @staticmethod
    def _clean(value: Optional[dict[str, Any]]) -> Optional[dict[str, str]]:
        if not isinstance(value, dict):
            return None
        result = {
            key: str(raw).strip()
            for key, raw in value.items()
            if key in _ALLOWED_KEYS and raw not in (None, "") and str(raw).strip()
        }
        return result or None

    def _load_locked(self) -> None:
        if self._loaded:
            return
        try:
            import json

            data = json.loads(self.path.read_text(encoding="utf-8"))
            entries = data.get("topics", data) if isinstance(data, dict) else {}
            if isinstance(entries, dict):
                self._models = {
                    str(key): cleaned
                    for key, value in entries.items()
                    if (cleaned := self._clean(value)) is not None
                }
        except (FileNotFoundError, OSError, ValueError, TypeError):
            self._models = {}
        self._loaded = True

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self.path, {"version": 1, "topics": self._models})

    def get(self, chat_id: Any, thread_id: Any) -> Optional[dict[str, str]]:
        with self._lock:
            self._load_locked()
            value = self._models.get(self._key(chat_id, thread_id))
            return dict(value) if value else None

    def set(self, chat_id: Any, thread_id: Any, override: dict[str, Any]) -> dict[str, str]:
        cleaned = self._clean(override)
        if not cleaned or not cleaned.get("model"):
            raise ValueError("Telegram topic model requires a non-empty model")
        with self._lock:
            self._load_locked()
            self._models[self._key(chat_id, thread_id)] = cleaned
            self._save_locked()
            return dict(cleaned)

    def clear(self, chat_id: Any, thread_id: Any) -> bool:
        with self._lock:
            self._load_locked()
            removed = self._models.pop(self._key(chat_id, thread_id), None) is not None
            if removed:
                self._save_locked()
            return removed

    def list_for_chat(self, chat_id: Any) -> dict[str, dict[str, str]]:
        prefix = f"{str(chat_id or '').strip()}:"
        with self._lock:
            self._load_locked()
            return {
                key: dict(value)
                for key, value in self._models.items()
                if key.startswith(prefix)
            }


_default_store: Optional[TelegramTopicModelStore] = None
_default_store_lock = threading.Lock()


def get_telegram_topic_model_store() -> TelegramTopicModelStore:
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = TelegramTopicModelStore()
        return _default_store
