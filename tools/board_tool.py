#!/usr/bin/env python3
"""Hermes Board tool.

Lets the agent manipulate the same Telegram miniapp board that Aidyn can edit in
/miniapp: create notes/frames, move/update/delete them, clear the canvas, or
leave visible Hermes live messages.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from gateway.miniapp_board import apply_board_action, board_state_path
from tools.registry import registry


def board_tool(
    action: str = "get",
    item_id: Optional[str] = None,
    type: str = "note",
    text: Optional[str] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    w: Optional[float] = None,
    h: Optional[float] = None,
    items: Optional[list[dict[str, Any]]] = None,
    detail: Optional[str] = None,
) -> str:
    result = apply_board_action(
        action,
        item_id=item_id,
        type=type,
        text=text,
        x=x,
        y=y,
        w=w,
        h=h,
        items=items,
        detail=detail,
    )
    result["path"] = str(board_state_path())
    return json.dumps(result, ensure_ascii=False)


BOARD_SCHEMA = {
    "name": "board",
    "description": (
        "Interact with Aidyn through the shared Hermes Telegram miniapp board. "
        "Use this to read the canvas, create notes/frames, update text, move/delete objects, "
        "clear the board, or leave a visible Hermes live message. The WebApp polls this state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "create", "update", "move", "delete", "clear", "message", "set"],
                "description": "Board operation. Omit or use get to inspect current board state.",
                "default": "get",
            },
            "item_id": {
                "type": "string",
                "description": "Existing board item id for update/move/delete. Returned by get/create.",
            },
            "type": {
                "type": "string",
                "enum": ["note", "frame"],
                "description": "Item type for create/update. Notes are sticky cards; frames are larger containers.",
                "default": "note",
            },
            "text": {
                "type": "string",
                "description": "Text for create/update, or message text for action=message.",
            },
            "x": {"type": "number", "description": "Board x coordinate."},
            "y": {"type": "number", "description": "Board y coordinate."},
            "w": {"type": "number", "description": "Optional item width."},
            "h": {"type": "number", "description": "Optional item height."},
            "items": {
                "type": "array",
                "description": "Full item list for action=set. Normally prefer create/update/move/delete.",
                "items": {"type": "object"},
            },
            "detail": {
                "type": "string",
                "description": "Optional event detail shown in the Hermes live feed.",
            },
        },
        "required": [],
    },
}


registry.register(
    name="board",
    toolset="board",
    schema=BOARD_SCHEMA,
    handler=lambda args, **kw: board_tool(
        action=args.get("action", "get"),
        item_id=args.get("item_id"),
        type=args.get("type", "note"),
        text=args.get("text"),
        x=args.get("x"),
        y=args.get("y"),
        w=args.get("w"),
        h=args.get("h"),
        items=args.get("items"),
        detail=args.get("detail"),
    ),
    emoji="▣",
)
