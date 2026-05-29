"""Persistent shared state for the Hermes Telegram miniapp board.

Both the API server and the ``board`` agent tool use this module so Hermes can
manipulate the same canvas that Aidyn sees in the Telegram WebApp.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home

BOARD_VERSION = 1
MAX_ITEMS = 200
MAX_EVENTS = 80
MAX_TEXT_CHARS = 2_000
_VALID_ITEM_TYPES = {"note", "frame"}
_LOCK = RLock()


def board_state_path() -> Path:
    """Return the profile-scoped board state path."""
    return get_hermes_home() / "gateway" / "miniapp_board.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _empty_state() -> Dict[str, Any]:
    return {
        "version": BOARD_VERSION,
        "revision": 0,
        "updated_at": _now_ms(),
        "items": [],
        "events": [],
    }


def _coerce_number(value: Any, default: float = 0.0, *, min_value: float = -100_000.0, max_value: float = 100_000.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number < min_value:
        return min_value
    if number > max_value:
        return max_value
    return number


def _coerce_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


def _coerce_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    item_type = str(raw.get("type") or "note").strip().lower()
    if item_type not in _VALID_ITEM_TYPES:
        item_type = "note"
    item_id = _coerce_text(raw.get("id"), "") or f"item-{uuid.uuid4().hex[:10]}"
    default_w = 250 if item_type == "frame" else 176
    default_h = 160 if item_type == "frame" else 124
    return {
        "id": item_id[:80],
        "type": item_type,
        "x": round(_coerce_number(raw.get("x"), 0.0)),
        "y": round(_coerce_number(raw.get("y"), 0.0)),
        "w": round(_coerce_number(raw.get("w"), default_w, min_value=40, max_value=3_000)),
        "h": round(_coerce_number(raw.get("h"), default_h, min_value=40, max_value=3_000)),
        "text": _coerce_text(raw.get("text"), "New frame" if item_type == "frame" else "New note"),
    }


def _coerce_items(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for raw in items[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        item = _coerce_item(raw)
        if item["id"] in seen:
            item["id"] = f"{item['id']}-{uuid.uuid4().hex[:4]}"
        seen.add(item["id"])
        out.append(item)
    return out


def _coerce_state(raw: Any) -> Dict[str, Any]:
    state = _empty_state()
    if not isinstance(raw, dict):
        return state
    try:
        state["revision"] = max(0, int(raw.get("revision", 0)))
    except (TypeError, ValueError):
        state["revision"] = 0
    try:
        state["updated_at"] = int(raw.get("updated_at") or _now_ms())
    except (TypeError, ValueError):
        state["updated_at"] = _now_ms()
    state["items"] = _coerce_items(raw.get("items"))
    events = raw.get("events")
    if isinstance(events, list):
        state["events"] = [event for event in events[-MAX_EVENTS:] if isinstance(event, dict)]
    return state


def load_board_state(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the persisted board state, returning an empty board if missing/corrupt."""
    target = path or board_state_path()
    with _LOCK:
        try:
            return _coerce_state(json.loads(target.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return _empty_state()
        except (OSError, json.JSONDecodeError):
            return _empty_state()


def save_board_state(state: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    """Atomically save a validated board state and return the saved value."""
    target = path or board_state_path()
    clean = _coerce_state(state)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True)
    with _LOCK:
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.write("\n")
            os.replace(tmp_name, target)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
    return clean


def _record_event(state: Dict[str, Any], action: str, detail: str = "", item: Optional[Dict[str, Any]] = None) -> None:
    state.setdefault("events", [])
    event: Dict[str, Any] = {
        "id": f"evt-{uuid.uuid4().hex[:10]}",
        "at": _now_ms(),
        "actor": "Hermes",
        "action": action,
        "detail": _coerce_text(detail, ""),
    }
    if item:
        event["item_id"] = item.get("id")
        event["x"] = item.get("x")
        event["y"] = item.get("y")
    state["events"] = (state["events"] + [event])[-MAX_EVENTS:]


def apply_board_action(action: str, **kwargs: Any) -> Dict[str, Any]:
    """Apply an action to the shared board and persist it.

    Supported actions: ``get``, ``set``, ``create``, ``update``, ``move``,
    ``delete``, ``clear``, and ``message``.
    """
    normalized = str(action or "get").strip().lower()
    state = load_board_state()

    if normalized == "get":
        return {"success": True, "action": "get", "board": state}

    if normalized == "set":
        state["items"] = _coerce_items(kwargs.get("items"))
        detail = _coerce_text(kwargs.get("detail"), "Board synced")
        _record_event(state, "set", detail)
    elif normalized == "create":
        item = _coerce_item({
            "id": kwargs.get("item_id") or kwargs.get("id"),
            "type": kwargs.get("type") or "note",
            "text": kwargs.get("text"),
            "x": kwargs.get("x"),
            "y": kwargs.get("y"),
            "w": kwargs.get("w"),
            "h": kwargs.get("h"),
        })
        state["items"].append(item)
        state["items"] = state["items"][-MAX_ITEMS:]
        _record_event(state, "create", f"Created {item['type']}: {item['text'][:80]}", item)
    elif normalized in {"update", "move"}:
        item_id = _coerce_text(kwargs.get("item_id") or kwargs.get("id"), "")
        item = next((entry for entry in state["items"] if entry.get("id") == item_id), None)
        if not item:
            return {"success": False, "error": f"Item not found: {item_id}", "board": state}
        if normalized == "update" and "text" in kwargs and kwargs.get("text") is not None:
            item["text"] = _coerce_text(kwargs.get("text"), item.get("text", ""))
        if "type" in kwargs and kwargs.get("type") in _VALID_ITEM_TYPES:
            item["type"] = kwargs.get("type")
        for key in ("x", "y", "w", "h"):
            if key in kwargs and kwargs.get(key) is not None:
                if key in {"w", "h"}:
                    item[key] = round(_coerce_number(kwargs.get(key), item.get(key, 100), min_value=40, max_value=3_000))
                else:
                    item[key] = round(_coerce_number(kwargs.get(key), item.get(key, 0)))
        _record_event(state, normalized, f"{normalized.title()} {item_id}", item)
    elif normalized == "delete":
        item_id = _coerce_text(kwargs.get("item_id") or kwargs.get("id"), "")
        before = len(state["items"])
        state["items"] = [entry for entry in state["items"] if entry.get("id") != item_id]
        if len(state["items"]) == before:
            return {"success": False, "error": f"Item not found: {item_id}", "board": state}
        _record_event(state, "delete", f"Deleted {item_id}")
    elif normalized == "clear":
        state["items"] = []
        _record_event(state, "clear", _coerce_text(kwargs.get("detail"), "Board cleared by Hermes"))
    elif normalized == "message":
        _record_event(state, "message", _coerce_text(kwargs.get("text") or kwargs.get("detail"), "Hermes is here"))
    else:
        return {"success": False, "error": f"Unsupported action: {normalized}", "board": state}

    state["revision"] = int(state.get("revision", 0)) + 1
    state["updated_at"] = _now_ms()
    saved = save_board_state(state)
    return {"success": True, "action": normalized, "board": deepcopy(saved)}
