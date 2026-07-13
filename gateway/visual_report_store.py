"""Profile-scoped persistence for generated visual reports.

The miniapp reads only this sanitized store.  It deliberately keeps secrets and
raw gateway config out of the browser payload.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.redact import redact_sensitive_text
from hermes_constants import get_hermes_home

MAX_BLOCKS = 64
MAX_METRICS = 16
MAX_SOURCE_TEXT_CHARS = 24_000
MAX_METADATA_DEPTH = 12
MAX_METADATA_ITEMS = 80
MAX_STRING_CHARS = 2_000
_SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|authorization|credential|bearer)", re.IGNORECASE)


def report_store_dir() -> Path:
    return get_hermes_home() / "gateway" / "visual_reports"


def latest_report_path() -> Path:
    return report_store_dir() / "latest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, *, limit: int = MAX_STRING_CHARS) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = redact_sensitive_text(text)
    return text[:limit]


def _sanitize_metadata(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_METADATA_DEPTH:
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:MAX_METADATA_ITEMS]:
            key_text = _clean_text(key, limit=80)
            if not key_text or _SECRET_KEY_RE.search(key_text):
                continue
            cooked = _sanitize_metadata(item, depth=depth + 1)
            if cooked is not None:
                result[key_text] = cooked
        return result
    if isinstance(value, list):
        return [item for item in (_sanitize_metadata(item, depth=depth + 1) for item in value[:MAX_METADATA_ITEMS]) if item is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _clean_text(value, limit=MAX_STRING_CHARS) if isinstance(value, str) else value
    return _clean_text(value, limit=MAX_STRING_CHARS)


def _sanitize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    cooked = _sanitize_metadata(deepcopy(plan))
    if not isinstance(cooked, dict):
        cooked = {}
    if isinstance(cooked.get("metrics"), list):
        cooked["metrics"] = cooked["metrics"][:MAX_METRICS]
    if isinstance(cooked.get("blocks"), list):
        cooked["blocks"] = cooked["blocks"][:MAX_BLOCKS]
    return cooked


def _sanitize_context(event_metadata: Optional[dict[str, Any]]) -> dict[str, str]:
    raw = event_metadata or {}
    return {
        "platform": _clean_text(raw.get("platform"), limit=80),
        "chat_id": _clean_text(raw.get("chat_id"), limit=120),
        "thread_id": _clean_text(raw.get("thread_id"), limit=120),
        "topic": _clean_text(raw.get("topic") or raw.get("chat_topic"), limit=160),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def save_latest_report(
    plan: dict[str, Any],
    *,
    source_response: str = "",
    source_metadata: Optional[dict[str, Any]] = None,
    event_metadata: Optional[dict[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    """Persist the latest visual report and return the browser-safe payload."""
    report = {
        "generated_at": generated_at or _utc_now(),
        "plan": _sanitize_plan(plan),
        "source": {
            "text": _clean_text(source_response, limit=MAX_SOURCE_TEXT_CHARS),
            "length": len(source_response or ""),
            "metadata": _sanitize_metadata(source_metadata or {}),
        },
        "context": _sanitize_context(event_metadata),
    }
    payload = {"success": True, "report": report}
    _atomic_write_json(latest_report_path(), payload)
    return report


def load_latest_report() -> Optional[dict[str, Any]]:
    """Load the latest sanitized report payload, or None when unavailable."""
    path = latest_report_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("report"), dict):
        return None
    return payload["report"]


def list_recent_reports(limit: int = 10) -> list[dict[str, Any]]:
    """Reserved bounded history seam.  Currently returns latest only."""
    latest = load_latest_report()
    return [latest] if latest and limit > 0 else []
