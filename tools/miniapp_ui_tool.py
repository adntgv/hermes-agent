#!/usr/bin/env python3
"""Scoped miniapp UI editing tool.

This tool intentionally exposes only the Telegram miniapp shell files so a
miniapp-originated Hermes turn can change the UI without general filesystem or
terminal access.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from tools.registry import registry

_MINIAPP_ROOT = Path(__file__).resolve().parents[1] / "gateway" / "miniapp"
_ALLOWED_FILES = {
    "index.html",
    "assets/app.js",
    "assets/styles.css",
}


def _resolve_allowed(path: str) -> Path:
    rel = str(path or "").strip().lstrip("/")
    if rel not in _ALLOWED_FILES:
        raise ValueError(f"Path must be one of: {', '.join(sorted(_ALLOWED_FILES))}")
    candidate = (_MINIAPP_ROOT / rel).resolve()
    candidate.relative_to(_MINIAPP_ROOT.resolve())
    return candidate


def _backup_file(target: Path) -> Path:
    backup_dir = _MINIAPP_ROOT / ".hermes-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{target.name}.bak"
    if target.exists():
        shutil.copy2(target, backup)
    return backup


def _validate_balance(text: str, open_char: str, close_char: str) -> bool:
    depth = 0
    for char in text:
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _validate_all() -> Dict[str, object]:
    """Run cheap guardrails that catch the common miniapp-breaking edits."""
    errors: List[str] = []
    warnings: List[str] = []

    index = _resolve_allowed("index.html")
    app = _resolve_allowed("assets/app.js")
    css = _resolve_allowed("assets/styles.css")

    for rel in sorted(_ALLOWED_FILES):
        if not _resolve_allowed(rel).exists():
            errors.append(f"missing required file: {rel}")

    if index.exists():
        html = index.read_text(encoding="utf-8")
        for needle in ("telegram-web-app.js", "/miniapp/assets/app.js", "/miniapp/assets/styles.css"):
            if needle not in html:
                errors.append(f"index.html missing {needle}")
        if "data-command-url=\"/miniapp/api/command\"" not in html:
            warnings.append("index.html does not expose the scoped miniapp command endpoint")
        if not ("<main" in html and "</main>" in html):
            errors.append("index.html must keep a <main> shell")

    if app.exists():
        js = app.read_text(encoding="utf-8")
        if "DOMContentLoaded" not in js or "InfiniteCanvasApp.init" not in js:
            errors.append("assets/app.js must initialize the miniapp on DOMContentLoaded")
        if not _validate_balance(js, "{", "}"):
            errors.append("assets/app.js has unbalanced braces")
        node = shutil.which("node")
        if node:
            proc = subprocess.run([node, "--check", str(app)], text=True, capture_output=True, timeout=10)
            if proc.returncode != 0:
                errors.append("assets/app.js syntax check failed: " + (proc.stderr or proc.stdout).strip()[:500])
        else:
            warnings.append("node is unavailable; skipped JS parser check")

    if css.exists():
        css_text = css.read_text(encoding="utf-8")
        if not _validate_balance(css_text, "{", "}"):
            errors.append("assets/styles.css has unbalanced braces")
        if ".ic-shell" not in css_text:
            warnings.append("assets/styles.css does not define the current miniapp shell class")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _restore_backup(target: Path, backup: Path) -> None:
    if backup.exists():
        shutil.copy2(backup, target)


def miniapp_ui(
    action: str = "list",
    path: Optional[str] = None,
    content: Optional[str] = None,
    old_string: Optional[str] = None,
    new_string: Optional[str] = None,
) -> str:
    """List/read/write/replace only the live miniapp UI files."""
    try:
        action = str(action or "list").strip().lower()
        if action == "list":
            files = []
            for rel in sorted(_ALLOWED_FILES):
                p = _resolve_allowed(rel)
                files.append({"path": rel, "exists": p.exists(), "bytes": p.stat().st_size if p.exists() else 0})
            return json.dumps(
                {"success": True, "root": str(_MINIAPP_ROOT), "files": files, "validation": _validate_all()},
                ensure_ascii=False,
            )

        if not path:
            raise ValueError("path is required for this action")
        target = _resolve_allowed(path)

        if action == "read":
            text = target.read_text(encoding="utf-8")
            return json.dumps({"success": True, "path": str(target), "content": text, "validation": _validate_all()}, ensure_ascii=False)

        if action == "write":
            if content is None:
                raise ValueError("content is required for write")
            backup = _backup_file(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            validation = _validate_all()
            if not validation["ok"]:
                raw_errors = validation.get("errors", [])
                errors = raw_errors if isinstance(raw_errors, list) else [raw_errors]
                _restore_backup(target, backup)
                raise ValueError("miniapp validation failed; restored previous file: " + "; ".join(str(error) for error in errors))
            return json.dumps({"success": True, "path": str(target), "bytes": target.stat().st_size, "validation": validation}, ensure_ascii=False)

        if action == "replace":
            if old_string is None or new_string is None:
                raise ValueError("old_string and new_string are required for replace")
            text = target.read_text(encoding="utf-8")
            count = text.count(old_string)
            if count != 1:
                raise ValueError(f"old_string must occur exactly once; found {count}")
            backup = _backup_file(target)
            updated = text.replace(old_string, new_string, 1)
            target.write_text(updated, encoding="utf-8")
            validation = _validate_all()
            if not validation["ok"]:
                raw_errors = validation.get("errors", [])
                errors = raw_errors if isinstance(raw_errors, list) else [raw_errors]
                _restore_backup(target, backup)
                raise ValueError("miniapp validation failed; restored previous file: " + "; ".join(str(error) for error in errors))
            return json.dumps({"success": True, "path": str(target), "replacements": 1, "bytes": target.stat().st_size, "validation": validation}, ensure_ascii=False)

        raise ValueError("action must be one of: list, read, write, replace")
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


MINIAPP_UI_SCHEMA = {
    "name": "miniapp_ui",
    "description": (
        "Safely edit Aidyn's Telegram miniapp UI. Scope is limited to index.html, "
        "assets/app.js, and assets/styles.css under gateway/miniapp. Use this for "
        "micro-frontend UI changes submitted from /miniapp."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "write", "replace"],
                "default": "list",
                "description": "Operation to perform.",
            },
            "path": {
                "type": "string",
                "enum": ["index.html", "assets/app.js", "assets/styles.css"],
                "description": "Miniapp UI file to read or modify.",
            },
            "content": {"type": "string", "description": "Full file content for write."},
            "old_string": {"type": "string", "description": "Exact unique text to replace."},
            "new_string": {"type": "string", "description": "Replacement text."},
        },
        "required": [],
    },
}


registry.register(
    name="miniapp_ui",
    toolset="miniapp",
    schema=MINIAPP_UI_SCHEMA,
    handler=lambda args, **kw: miniapp_ui(
        action=args.get("action", "list"),
        path=args.get("path"),
        content=args.get("content"),
        old_string=args.get("old_string"),
        new_string=args.get("new_string"),
    ),
    emoji="▤",
)
