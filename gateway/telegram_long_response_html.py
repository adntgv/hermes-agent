"""Helpers for Telegram long-response HTML artifacts.

The raw HTML attachment preserves the original response. The visual digest is
rendered from an LLM-produced plan rather than hardcoded markdown heuristics,
so the model chooses the representation and this module focuses on rendering.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from hermes_constants import get_hermes_home

_SAFE_HTML_TAGS = frozenset({
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "img", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul",
})
_VOID_HTML_TAGS = frozenset({"br", "hr", "img"})
_DANGEROUS_HTML_TAGS = frozenset({
    "base", "embed", "form", "iframe", "link", "meta", "object", "script", "style",
})


def _safe_html_url(value: str, *, image: bool = False) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "/", "./", "../")):
        return True
    parsed = urlparse(stripped)
    allowed = {"http", "https"} if image else {"http", "https", "mailto", "tg"}
    return parsed.scheme.lower() in allowed and bool(parsed.netloc or parsed.scheme in {"mailto", "tg"})


class _RenderedHtmlSanitizer(HTMLParser):
    """Allow Markdown's structural HTML while neutralizing raw executable HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def _safe_attrs(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> str:
        kept: list[str] = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = raw_value or ""
            allowed = False
            if tag == "a" and name in {"href", "title"}:
                allowed = name == "title" or _safe_html_url(value)
            elif tag == "img" and name in {"src", "alt", "title"}:
                allowed = name != "src" or _safe_html_url(value, image=True)
            elif tag == "code" and name == "class":
                allowed = bool(re.fullmatch(r"language-[A-Za-z0-9_+.-]+", value))
            elif tag in {"th", "td"} and name == "align":
                allowed = value.lower() in {"left", "center", "right"}
            elif tag.startswith("h") and name == "id":
                allowed = bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))
            if allowed:
                kept.append(f' {name}="{html.escape(value, quote=True)}"')
        return "".join(kept)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in _SAFE_HTML_TAGS:
            suffix = " /" if tag in _VOID_HTML_TAGS else ""
            self.parts.append(f"<{tag}{self._safe_attrs(tag, attrs)}{suffix}>")
        elif tag in _DANGEROUS_HTML_TAGS:
            self.parts.append(html.escape(self.get_starttag_text() or f"<{tag}>", quote=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SAFE_HTML_TAGS and tag not in _VOID_HTML_TAGS:
            self.parts.append(f"</{tag}>")
        elif tag in _DANGEROUS_HTML_TAGS:
            self.parts.append(f"&lt;/{tag}&gt;")

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return


def sanitize_rendered_markdown_html(rendered_html: str) -> str:
    sanitizer = _RenderedHtmlSanitizer()
    sanitizer.feed(rendered_html)
    sanitizer.close()
    return "".join(sanitizer.parts)


_VISUAL_REPORT_MANIFEST_RELATIVE_PATH = Path("web/src/features/visual-reports/manifest.json")
_VISUAL_REPORT_MANIFEST_PROMPT_FIELDS = (
    "type",
    "label",
    "description",
    "rendererMode",
    "supportsTelegramFallback",
    "accessibilitySummary",
    "dataShape",
    "selectionGuidance",
)
_VISUAL_REPORT_MANIFEST_STRING_LIMITS = {
    "type": 64,
    "label": 80,
    "description": 220,
    "rendererMode": 32,
    "accessibilitySummary": 220,
    "dataShape": 360,
    "selectionGuidance": 260,
}

_SAFE_VISUAL_REPORT_REGISTRY_FALLBACK: tuple[dict[str, Any], ...] = (
    {"type": "metric", "label": "Metric", "description": "Single headline number or compact fact with optional trend.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Headline metric and trend text are exposed as readable text.", "dataShape": "{ label, value, trend? }", "selectionGuidance": "Use for exact values, counts, dates, states, owners, or short facts explicitly present in the source."},
    {"type": "progress", "label": "Progress", "description": "Progress bar with numeric value and optional segment counts.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Progress value is exposed with readable labels.", "dataShape": "{ value, max, label, segments? }", "selectionGuidance": "Use only when the source provides grounded completion, quota, percentage, or count-over-total values."},
    {"type": "timeline", "label": "Timeline", "description": "Linear dated milestones with status and optional owner.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Milestones are presented as an ordered list with dates and status.", "dataShape": "{ items: [{ label, start, end?, status, owner? }] }", "selectionGuidance": "Use when chronology, milestones, deadlines, or ordered dated events are central."},
    {"type": "gantt", "label": "Gantt", "description": "Lane-based schedule bars across a start/end date range.", "rendererMode": "rich", "supportsTelegramFallback": True, "accessibilitySummary": "Schedule bars are paired with readable labels, lanes, and dates.", "dataShape": "{ start, end, items: [{ label, start, end?, status, owner?, lane }] }", "selectionGuidance": "Use for project work distributed over time, parallel lanes, phases, or durations."},
    {"type": "kanban", "label": "Kanban", "description": "Column-based board of cards grouped by state or category.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Cards are grouped under readable section headings.", "dataShape": "{ columns: [{ title, cards: [{ title, meta? }] }] }", "selectionGuidance": "Use when items are best understood by status, queue, ownership bucket, or workflow state."},
    {"type": "priority_matrix", "label": "Priority matrix", "description": "Impact/effort or urgency/importance matrix.", "rendererMode": "rich", "supportsTelegramFallback": True, "accessibilitySummary": "Items are positioned by priority axes and listed in text fallback.", "dataShape": "{ xLabel, yLabel, items: [{ label, x, y, quadrant? }] }", "selectionGuidance": "Use when tradeoffs, prioritization, impact versus effort, or urgency versus importance are explicit."},
    {"type": "dependency_graph", "label": "Dependency graph", "description": "Nodes and directed edges showing prerequisites or unblock relationships.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Graph is backed by an accessible adjacency list.", "dataShape": "{ nodes: [{ id, label, group? }], edges: [{ from, to, label? }] }", "selectionGuidance": "Use when prerequisites, blockers, ownership handoffs, or cause-and-effect relationships matter."},
    {"type": "flow", "label": "Flow", "description": "Ordered process steps with optional detail per step.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Process is exposed as numbered flow steps.", "dataShape": "{ steps: [{ label, detail? }] }", "selectionGuidance": "Use for procedures, decision flows, pipelines, handoff sequences, or causal step-by-step explanations."},
    {"type": "comparison_table", "label": "Comparison table", "description": "Responsive matrix comparing options by columns and rows.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Native table uses column and row headers.", "dataShape": "{ columns: [string], rows: [{ label, values: [string] }] }", "selectionGuidance": "Use when options, tradeoffs, alternatives, or before/after states need side-by-side comparison."},
    {"type": "chart", "label": "Chart", "description": "Mobile-legible bar, line, area, or donut chart.", "rendererMode": "rich", "supportsTelegramFallback": True, "accessibilitySummary": "Chart is backed by a visible data list.", "dataShape": "{ kind, data: [{ label, value, series? }], valueLabel? }", "selectionGuidance": "Use for explicit numeric distributions, trends, proportions, or series in the source; do not invent data."},
    {"type": "canvas_network", "label": "Canvas network", "description": "Static network with node coordinates and fallback list.", "rendererMode": "rich", "supportsTelegramFallback": True, "accessibilitySummary": "Canvas diagram includes a static edge list fallback.", "dataShape": "{ nodes: [{ id, label, x, y }], edges: [{ from, to, label? }] }", "selectionGuidance": "Use for dense relationship maps where clusters matter."},
    {"type": "three_scene", "label": "Three scene", "description": "3D scene with objects in space and WebGL fallback.", "rendererMode": "rich", "supportsTelegramFallback": True, "accessibilitySummary": "3D objects are described in a text fallback.", "dataShape": "{ objects: [{ id, label, size, position: [x, y, z] }] }", "selectionGuidance": "Use sparingly for spatial concepts or layered systems that benefit from 3D placement."},
    {"type": "details", "label": "Details", "description": "Accessible expandable sections for lossless supporting detail.", "rendererMode": "telegram-fallback", "supportsTelegramFallback": True, "accessibilitySummary": "Native details sections preserve full task text and supporting evidence.", "dataShape": "{ sections: [{ title, content: [string] }] }", "selectionGuidance": "Use to preserve exact tasks, evidence, caveats, commands, or source details that would otherwise be lost."},
)


def _sanitize_manifest_entry(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    sanitized: dict[str, Any] = {}
    for field in _VISUAL_REPORT_MANIFEST_PROMPT_FIELDS:
        if field == "supportsTelegramFallback":
            sanitized[field] = bool(raw.get(field))
            continue
        value = raw.get(field)
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        if not text:
            return None
        sanitized[field] = text[: _VISUAL_REPORT_MANIFEST_STRING_LIMITS[field]]
    if sanitized["rendererMode"] not in {"rich", "telegram-fallback"}:
        sanitized["rendererMode"] = "rich"
    return sanitized


def _sanitize_manifest_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    sanitized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in entries[:32]:
        entry = _sanitize_manifest_entry(raw)
        if not entry or entry["type"] in seen:
            continue
        seen.add(entry["type"])
        sanitized.append(entry)
    return sanitized


def load_visual_report_registry_manifest_for_prompt(manifest_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Load the visual-report registry manifest for prompt injection.

    Uses a repository/package-relative path instead of cwd, and returns a
    sanitized built-in fallback if the JSON manifest is unavailable or invalid.
    """
    path = manifest_path or (Path(__file__).resolve().parents[1] / _VISUAL_REPORT_MANIFEST_RELATIVE_PATH)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = _sanitize_manifest_entries(raw.get("components") if isinstance(raw, dict) else raw)
        if entries:
            return entries
    except Exception:
        pass
    return _sanitize_manifest_entries(list(_SAFE_VISUAL_REPORT_REGISTRY_FALLBACK))


def build_artifact_paths(event: Any, ts: Optional[str] = None) -> tuple[str, str, str]:
    """Return timestamp plus raw/visual artifact paths for a Telegram response."""
    ts = ts or datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_chat = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(getattr(event.source, "chat_id", None) or "chat"))[:64]
    thread = str(getattr(event.source, "thread_id", "") or "main")
    safe_thread = re.sub(r"[^A-Za-z0-9_.-]+", "_", thread)[:64]
    out_dir = get_hermes_home() / "artifacts" / "telegram-long-responses"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"response-{safe_chat}-{safe_thread}-{ts}"
    return ts, str(out_dir / f"{base}.html"), str(out_dir / f"{base}-visual.html")


def strip_markdown_text(text: str) -> str:
    """Return a compact plain-text approximation of markdown content."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text)
    text = re.sub(r"^\s*[-*+]\s+\[[ xX]\]\s+", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text)
    text = re.sub(r"[*_~>]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_title_from_response(response: str) -> str:
    for raw in response.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^#{1,6}\s+", line):
            return strip_markdown_text(line)[:120] or "Hermes visual digest"
        cleaned = strip_markdown_text(line)
        if cleaned:
            return cleaned[:120]
    return "Hermes visual digest"


def _coerce_string(value: Any, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    return str(value).strip() or fallback


def _coerce_int(value: Any, *, fallback: int = 0, minimum: int = 0, maximum: int = 100) -> int:
    try:
        cooked = int(float(value))
    except (TypeError, ValueError):
        cooked = fallback
    return max(minimum, min(maximum, cooked))


def _coerce_float(value: Any, *, fallback: float = 0.0, minimum: float = 0.0, maximum: float = 100.0) -> float:
    try:
        cooked = float(value)
    except (TypeError, ValueError):
        cooked = fallback
    return max(minimum, min(maximum, cooked))


def _safe_identifier(value: Any, *, fallback: str) -> str:
    cooked = re.sub(r"[^A-Za-z0-9_-]+", "-", _coerce_string(value, fallback=fallback)).strip("-")
    return (cooked or fallback)[:48]


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return stripped


def parse_visual_digest_plan(text: str, response: str) -> Optional[dict]:
    """Parse a planner LLM response into a normalized visual-digest plan."""
    candidate = _strip_json_fence(text)
    decoder = json.JSONDecoder()
    plan_obj = None

    for probe in (candidate, text):
        if not probe:
            continue
        try:
            plan_obj = json.loads(probe)
            break
        except Exception:
            pass
        start = probe.find("{")
        while start != -1:
            try:
                obj, _end = decoder.raw_decode(probe[start:])
                plan_obj = obj
                break
            except Exception:
                start = probe.find("{", start + 1)
        if plan_obj is not None:
            break

    if not isinstance(plan_obj, dict):
        return None
    return normalize_visual_digest_plan(plan_obj, response)


def normalize_visual_digest_plan(plan: dict, response: str) -> Optional[dict]:
    """Normalize planner JSON into the supported rendering schema."""
    title = _coerce_string(plan.get("title"), fallback=_extract_title_from_response(response))[:140]
    summary = _coerce_string(
        plan.get("summary"),
        fallback="LLM-designed visual companion for this long response.",
    )[:320]
    theme_hint = _coerce_string(plan.get("theme_hint"), fallback="briefing")[:40]

    metrics = []
    for raw in plan.get("metrics") or []:
        if not isinstance(raw, dict):
            continue
        label = _coerce_string(raw.get("label"))[:32]
        value = _coerce_string(raw.get("value"))[:48]
        if label and value:
            metrics.append({"label": label, "value": value})
        if len(metrics) >= 8:
            break

    blocks = []
    for raw in plan.get("blocks") or []:
        if not isinstance(raw, dict):
            continue
        payload = raw.get("payload")
        if isinstance(payload, dict):
            raw = {**payload, **raw}
        block_type = _coerce_string(raw.get("type")).lower()
        if not block_type:
            continue
        title_text = _coerce_string(raw.get("title"))[:120]

        if block_type == "key_points":
            items = [_coerce_string(item)[:220] for item in (raw.get("items") or []) if _coerce_string(item)]
            if items:
                blocks.append({"type": block_type, "title": title_text or "What matters", "items": items[:8]})
        elif block_type == "insight_cards":
            items = []
            for item in raw.get("items") or []:
                if not isinstance(item, dict):
                    continue
                label = _coerce_string(item.get("label"))[:40]
                value = _coerce_string(item.get("value"))[:120]
                detail = _coerce_string(item.get("detail"))[:200]
                if label and value:
                    items.append({"label": label, "value": value, "detail": detail})
                if len(items) >= 8:
                    break
            if items:
                blocks.append({"type": block_type, "title": title_text or "Fast orientation", "items": items})
        elif block_type == "sequence":
            steps = []
            for item in raw.get("steps") or []:
                if not isinstance(item, dict):
                    continue
                step_title = _coerce_string(item.get("title"))[:100]
                detail = _coerce_string(item.get("detail"))[:260]
                if step_title or detail:
                    steps.append({"title": step_title or f"Step {len(steps) + 1}", "detail": detail})
                if len(steps) >= 8:
                    break
            if steps:
                blocks.append({"type": block_type, "title": title_text or "Flow", "steps": steps})
        elif block_type == "comparison_table":
            columns = [_coerce_string(col)[:40] for col in (raw.get("columns") or []) if _coerce_string(col)]
            rows = []
            for row in raw.get("rows") or []:
                if isinstance(row, dict):
                    cooked = [_coerce_string(row.get("label"))[:120]] + [
                        _coerce_string(cell)[:120] for cell in (row.get("values") or [])
                    ]
                elif isinstance(row, list):
                    cooked = [_coerce_string(cell)[:120] for cell in row]
                else:
                    continue
                if columns and cooked:
                    rows.append(cooked[: len(columns)])
                if len(rows) >= 12:
                    break
            if columns and rows:
                blocks.append({"type": block_type, "title": title_text or "Compare", "columns": columns, "rows": rows})
        elif block_type == "timeline":
            items = []
            for item in raw.get("items") or []:
                if not isinstance(item, dict):
                    continue
                label = _coerce_string(item.get("label"))[:40]
                item_title = _coerce_string(item.get("title"))[:100]
                detail = _coerce_string(item.get("detail"))[:220]
                if label or item_title or detail:
                    items.append({"label": label, "title": item_title, "detail": detail})
                if len(items) >= 8:
                    break
            if items:
                blocks.append({"type": block_type, "title": title_text or "Timeline", "items": items})
        elif block_type == "mermaid":
            code = _coerce_string(raw.get("code"))
            caption = _coerce_string(raw.get("caption"))[:180]
            if code:
                blocks.append({"type": block_type, "title": title_text or "Diagram", "code": code, "caption": caption})
        elif block_type == "checklist":
            items = []
            for item in raw.get("items") or []:
                if isinstance(item, dict):
                    text = _coerce_string(item.get("text"))[:220]
                    done = bool(item.get("done"))
                else:
                    text = _coerce_string(item)[:220]
                    done = False
                if text:
                    items.append({"text": text, "done": done})
                if len(items) >= 10:
                    break
            if items:
                blocks.append({"type": block_type, "title": title_text or "Checklist", "items": items})
        elif block_type == "callout":
            tone = _coerce_string(raw.get("tone"), fallback="info").lower()
            if tone not in {"info", "warn", "success"}:
                tone = "info"
            text_value = _coerce_string(raw.get("text"))[:420]
            if text_value:
                blocks.append({"type": block_type, "title": title_text or "Note", "tone": tone, "text": text_value})
        elif block_type == "markdown":
            markdown_text = _coerce_string(raw.get("markdown"))
            if markdown_text:
                blocks.append({"type": block_type, "title": title_text or "Details", "markdown": markdown_text})
        elif block_type == "metric":
            label = _coerce_string(raw.get("label"))[:60]
            value = _coerce_string(raw.get("value"))[:80]
            trend_raw = raw.get("trend") if isinstance(raw.get("trend"), dict) else {}
            trend_label = _coerce_string(trend_raw.get("label"))[:100]
            trend_direction = _coerce_string(trend_raw.get("direction"), fallback="flat").lower()[:12]
            if trend_direction not in {"up", "down", "flat"}:
                trend_direction = "flat"
            if label and value:
                block = {"type": block_type, "title": title_text or label, "label": label, "value": value}
                if trend_label:
                    block["trend"] = {"direction": trend_direction, "label": trend_label}
                blocks.append(block)
        elif block_type == "chart":
            kind = _coerce_string(raw.get("kind"), fallback="bar").lower()
            if kind not in {"bar", "line", "area", "donut"}:
                kind = "bar"
            data = []
            for index, point in enumerate(raw.get("data") or []):
                if not isinstance(point, dict):
                    continue
                label = _coerce_string(point.get("label"))[:60]
                if not label:
                    continue
                data.append({
                    "label": label,
                    "value": _coerce_float(point.get("value"), minimum=-1_000_000_000, maximum=1_000_000_000),
                    "series": _coerce_string(point.get("series"))[:40],
                    "color": _safe_identifier(point.get("color"), fallback=f"tone-{index % 6}"),
                })
                if len(data) >= 12:
                    break
            if data:
                blocks.append({"type": block_type, "title": title_text or "Chart", "kind": kind, "data": data, "valueLabel": _coerce_string(raw.get("valueLabel") or raw.get("value_label"))[:40]})
        elif block_type == "canvas_network":
            nodes = []
            node_ids = set()
            for index, node in enumerate(raw.get("nodes") or []):
                if not isinstance(node, dict):
                    continue
                node_id = _safe_identifier(node.get("id"), fallback=f"node-{index}")
                label = _coerce_string(node.get("label"))[:80]
                if label and node_id not in node_ids:
                    node_ids.add(node_id)
                    nodes.append({
                        "id": node_id,
                        "label": label,
                        "group": _coerce_string(node.get("group"))[:40],
                        "x": _coerce_float(node.get("x"), maximum=100),
                        "y": _coerce_float(node.get("y"), maximum=100),
                    })
                if len(nodes) >= 18:
                    break
            edges = []
            for edge in raw.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                source = _safe_identifier(edge.get("from"), fallback="")
                target = _safe_identifier(edge.get("to"), fallback="")
                if source and target:
                    edges.append({"from": source, "to": target, "label": _coerce_string(edge.get("label"))[:60]})
                if len(edges) >= 28:
                    break
            if nodes:
                blocks.append({"type": block_type, "title": title_text or "Network", "nodes": nodes, "edges": edges})
        elif block_type == "three_scene":
            objects = []
            for index, obj in enumerate(raw.get("objects") or []):
                if not isinstance(obj, dict):
                    continue
                label = _coerce_string(obj.get("label"))[:80]
                position_raw = obj.get("position") if isinstance(obj.get("position"), list) else []
                position = [
                    _coerce_float(position_raw[i] if i < len(position_raw) else 0, minimum=-1000, maximum=1000)
                    for i in range(3)
                ]
                if label:
                    objects.append({
                        "id": _safe_identifier(obj.get("id"), fallback=f"object-{index}"),
                        "label": label,
                        "size": _coerce_float(obj.get("size"), fallback=1, minimum=0, maximum=1000),
                        "position": position,
                    })
                if len(objects) >= 16:
                    break
            if objects:
                blocks.append({"type": block_type, "title": title_text or "Spatial map", "objects": objects})
        elif block_type == "gantt":
            columns = [_coerce_string(value)[:24] for value in (raw.get("columns") or []) if _coerce_string(value)][:14]
            lanes = []
            for lane_index, lane in enumerate(raw.get("lanes") or []):
                if not isinstance(lane, dict):
                    continue
                label = _coerce_string(lane.get("label"))[:60]
                segments = []
                for segment in lane.get("segments") or []:
                    if not isinstance(segment, dict) or not columns:
                        continue
                    start = _coerce_int(segment.get("start"), maximum=len(columns) - 1)
                    end = _coerce_int(segment.get("end"), fallback=start + 1, minimum=start + 1, maximum=len(columns))
                    segment_label = _coerce_string(segment.get("label"))[:80]
                    segments.append({"start": start, "end": end, "label": segment_label})
                if label and segments:
                    lanes.append({"label": label, "color": _safe_identifier(lane.get("color"), fallback=f"tone-{lane_index % 6}"), "segments": segments[:10]})
            if columns and lanes:
                blocks.append({"type": block_type, "title": title_text or "Timeline", "columns": columns, "lanes": lanes[:12]})
        elif block_type == "progress":
            items = []
            for index, item in enumerate(raw.get("items") or []):
                if not isinstance(item, dict):
                    continue
                label = _coerce_string(item.get("label"))[:60]
                if label:
                    items.append({
                        "label": label,
                        "value": _coerce_int(item.get("value")),
                        "detail": _coerce_string(item.get("detail"))[:160],
                        "color": _safe_identifier(item.get("color"), fallback=f"tone-{index % 6}"),
                    })
            if items:
                blocks.append({"type": block_type, "title": title_text or "Progress", "items": items[:12]})
        elif block_type == "kanban":
            columns = []
            for column in raw.get("columns") or []:
                if not isinstance(column, dict):
                    continue
                items = []
                for item in (column.get("items") or column.get("cards") or []):
                    if not isinstance(item, dict):
                        continue
                    item_title = _coerce_string(item.get("title"))[:100]
                    if item_title:
                        items.append({"title": item_title, "detail": _coerce_string(item.get("detail"))[:180], "tag": _coerce_string(item.get("tag"))[:32]})
                column_title = _coerce_string(column.get("title"))[:50]
                if column_title:
                    columns.append({"title": column_title, "items": items[:12]})
            if columns:
                blocks.append({"type": block_type, "title": title_text or "Board", "columns": columns[:6]})
        elif block_type == "priority_matrix":
            quadrants = []
            valid_keys = {"high_high", "high_low", "low_high", "low_low"}
            for index, quadrant in enumerate(raw.get("quadrants") or []):
                if not isinstance(quadrant, dict):
                    continue
                key = _coerce_string(quadrant.get("key"), fallback="high_high").lower()
                if key not in valid_keys:
                    key = ["high_high", "high_low", "low_high", "low_low"][index % 4]
                items = [_coerce_string(item)[:100] for item in (quadrant.get("items") or []) if _coerce_string(item)][:10]
                quadrants.append({"key": key, "title": _coerce_string(quadrant.get("title"), fallback=key.replace("_", " ").title())[:60], "items": items})
            if quadrants:
                blocks.append({"type": block_type, "title": title_text or "Priority matrix", "quadrants": quadrants[:4]})
        elif block_type == "dependency_graph":
            nodes = []
            node_ids = set()
            for index, node in enumerate(raw.get("nodes") or []):
                if not isinstance(node, dict):
                    continue
                node_id = _safe_identifier(node.get("id"), fallback=f"node-{index}")
                label = _coerce_string(node.get("label"))[:80]
                if label and node_id not in node_ids:
                    node_ids.add(node_id)
                    nodes.append({"id": node_id, "label": label, "status": _coerce_string(node.get("status"), fallback="neutral")[:24]})
            edges = []
            for edge in raw.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                source = _safe_identifier(edge.get("from"), fallback="")
                target = _safe_identifier(edge.get("to"), fallback="")
                if source and target:
                    edges.append({"from": source, "to": target, "label": _coerce_string(edge.get("label"))[:60]})
            if nodes:
                blocks.append({"type": block_type, "title": title_text or "Dependencies", "nodes": nodes[:16], "edges": edges[:24]})
        elif block_type in {"flow", "flowchart"}:
            steps = []
            for index, step in enumerate(raw.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                step_title = _coerce_string(step.get("title") or step.get("label"))[:100]
                if step_title:
                    steps.append({"id": _safe_identifier(step.get("id"), fallback=f"step-{index}"), "title": step_title, "detail": _coerce_string(step.get("detail"))[:180], "status": _coerce_string(step.get("status"), fallback="neutral")[:24]})
            if steps:
                blocks.append({"type": block_type, "title": title_text or "Flow", "steps": steps[:12]})
        elif block_type == "details":
            sections = []
            for section in raw.get("sections") or []:
                if not isinstance(section, dict):
                    continue
                section_title = _coerce_string(section.get("title"))[:100]
                items = [
                    _coerce_string(item)[:240]
                    for item in (section.get("items") or section.get("content") or [])
                    if _coerce_string(item)
                ][:30]
                if section_title and items:
                    sections.append({"title": section_title, "items": items})
            if sections:
                blocks.append({"type": block_type, "title": title_text or "Details", "sections": sections[:12]})

    if not blocks:
        return None

    return {
        "title": title,
        "summary": summary,
        "theme_hint": theme_hint,
        "metrics": metrics,
        "blocks": blocks,
    }


def write_long_response_html_file(
    response: str,
    event: Any,
    render_md_to_html: Callable[[str], str],
    *,
    ts: Optional[str] = None,
) -> str:
    """Write a self-contained HTML rendering of a long gateway response."""
    ts, path, _ = build_artifact_paths(event, ts)
    topic = html.escape(str(getattr(event.source, "chat_topic", "") or ""))
    rendered = render_md_to_html(response)
    Path(path).write_text(
        "<!doctype html>\n"
        "<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<meta name=\"referrer\" content=\"no-referrer\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'\">"
        "<title>Hermes response</title>"
        "<style>"
        ":root{color-scheme:dark light}html,body{width:100%;max-width:100%;overflow-x:hidden}body{margin:0;padding:24px;font:16px/1.55 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#0f1115;color:#f2f4f8}"
        "main{max-width:860px;margin:0 auto}h1{font-size:20px;margin:0 0 8px}.meta{color:#9aa4b2;margin-bottom:20px;font-size:13px}"
        ".response-body h1,.response-body h2,.response-body h3,.response-body h4,.response-body h5,.response-body h6{margin:1em 0 0.4em;font-weight:600;line-height:1.3}"
        ".response-body h2{font-size:18px;border-bottom:1px solid #2a2f3a;padding-bottom:6px}"
        ".response-body h3{font-size:17px}"
        ".response-body p{margin:0.6em 0}"
        ".response-body ul,.response-body ol{margin:0.4em 0;padding-left:1.5em}"
        ".response-body li{margin:0.2em 0}"
        ".response-body blockquote{border-left:3px solid #3b82f6;padding:8px 14px;margin:0.6em 0;background:#171a21;border-radius:0 8px 8px 0;color:#b0b8c4}"
        ".response-body code{background:#171a21;padding:2px 6px;border-radius:4px;font-size:0.9em;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}"
        ".response-body pre{white-space:pre-wrap;word-break:break-word;background:#171a21;border:1px solid #2a2f3a;border-radius:14px;padding:18px;overflow:auto}"
        ".response-body pre code{background:none;padding:0}"
        ".response-body table{border-collapse:collapse;width:100%;margin:0.8em 0;display:block;overflow-x:auto}"
        ".response-body th,.response-body td{border:1px solid #2a2f3a;padding:8px 12px;text-align:left}"
        ".response-body th{background:#171a21;font-weight:600}"
        ".response-body tr:nth-child(even){background:#14171e}"
        ".response-body hr{border:none;border-top:1px solid #2a2f3a;margin:1.2em 0}"
        ".response-body a{color:#60a5fa;text-decoration:none}"
        ".response-body a:hover{text-decoration:underline}"
        ".response-body img{max-width:100%;border-radius:8px}"
        ".response-body input[type=checkbox]{margin-right:6px}"
        "</style></head><body><main>"
        f"<h1>Hermes response</h1><div class=\"meta\">{ts}{' · ' + topic if topic else ''}</div>"
        f'<div class="response-body">{rendered}</div>'
        "</main></body></html>\n",
        encoding="utf-8",
    )
    return path


def write_visual_digest_html_file(
    response: str,
    event: Any,
    render_md_to_html: Callable[[str], str],
    *,
    plan: dict,
    ts: Optional[str] = None,
) -> str:
    """Write a mobile-first visual digest companion HTML from an LLM plan."""
    ts, _, path = build_artifact_paths(event, ts)
    topic = html.escape(str(getattr(event.source, "chat_topic", "") or ""))
    title = html.escape(plan["title"])
    summary = html.escape(plan["summary"])
    metrics_html = "".join(
        f'<div class="chip"><span>{html.escape(metric["label"])}</span><strong>{html.escape(metric["value"])}</strong></div>'
        for metric in plan.get("metrics") or []
    )
    blocks_html = []

    for block in plan.get("blocks") or []:
        block_type = block.get("type")
        block_title = html.escape(block.get("title") or "")
        if block_type == "key_points":
            items_html = "".join(f"<li>{html.escape(item)}</li>" for item in block.get("items") or [])
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><ol class="takeaways">{items_html}</ol></section>'
            )
        elif block_type == "insight_cards":
            cards_html = "".join(
                '<div class="fact">'
                f'<span>{html.escape(item["label"])}</span>'
                f'<strong>{html.escape(item["value"])}</strong>'
                + (f'<p>{html.escape(item["detail"])}</p>' if item.get("detail") else "")
                + '</div>'
                for item in block.get("items") or []
            )
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><div class="fact-grid">{cards_html}</div></section>'
            )
        elif block_type == "sequence":
            steps_html = "".join(
                f'<li><span class="step-index">{idx}</span><div><strong>{html.escape(step["title"])}</strong>'
                + (f'<p>{html.escape(step["detail"])}</p>' if step.get("detail") else "")
                + '</div></li>'
                for idx, step in enumerate(block.get("steps") or [], start=1)
            )
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><ol class="process">{steps_html}</ol></section>'
            )
        elif block_type == "comparison_table":
            cols = block.get("columns") or []
            head_html = "".join(f"<th>{html.escape(col)}</th>" for col in cols)
            rows_html = "".join(
                '<tr>' + ''.join(
                    f'<td data-label="{html.escape(cols[index] if index < len(cols) else "Value")}">{html.escape(cell)}</td>'
                    for index, cell in enumerate(row)
                ) + '</tr>'
                for row in block.get("rows") or []
            )
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><div class="table-wrap"><table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table></div></section>'
            )
        elif block_type == "timeline":
            items_html = "".join(
                '<li class="timeline-item">'
                f'<span class="timeline-label">{html.escape(item.get("label") or "")}</span>'
                '<div>'
                + (f'<strong>{html.escape(item.get("title") or "")}</strong>' if item.get("title") else "")
                + (f'<p>{html.escape(item.get("detail") or "")}</p>' if item.get("detail") else "")
                + '</div></li>'
                for item in block.get("items") or []
            )
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><ol class="timeline">{items_html}</ol></section>'
            )
        elif block_type == "mermaid":
            caption = block.get("caption") or ""
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2>'
                + (f'<p class="diagram-caption">{html.escape(caption)}</p>' if caption else "")
                + f'<pre class="mermaid">{html.escape(block.get("code") or "")}</pre></section>'
            )
        elif block_type == "checklist":
            items_html = "".join(
                '<li class="check-item">'
                f'<span class="check-mark">{"✓" if item.get("done") else "○"}</span>'
                f'<span>{html.escape(item.get("text") or "")}</span>'
                '</li>'
                for item in block.get("items") or []
            )
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><ul class="checklist">{items_html}</ul></section>'
            )
        elif block_type == "callout":
            tone = html.escape(block.get("tone") or "info")
            blocks_html.append(
                f'<section class="panel callout callout-{tone}"><h2>{block_title}</h2><p>{html.escape(block.get("text") or "")}</p></section>'
            )
        elif block_type == "markdown":
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><div class="section-body">{render_md_to_html(block.get("markdown") or "")}</div></section>'
            )
        elif block_type == "metric":
            trend = block.get("trend") or {}
            trend_label = trend.get("label") or ""
            trend_direction = html.escape(trend.get("direction") or "flat")
            blocks_html.append(
                f'<section class="panel"><h2>{block_title}</h2><div class="metric-tile trend-{trend_direction}">'
                f'<span>{html.escape(block.get("label") or "")}</span><strong>{html.escape(block.get("value") or "")}</strong>'
                + (f'<p>{html.escape(trend_label)}</p>' if trend_label else '')
                + '</div></section>'
            )
        elif block_type == "chart":
            data = block.get("data") or []
            values = [float(point.get("value") or 0) for point in data]
            max_value = max([abs(value) for value in values] or [1]) or 1
            value_label = block.get("valueLabel") or ""
            def _format_chart_value(value: Any) -> str:
                number = float(value or 0)
                text = str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")
                if value_label == "%":
                    return f"{text}%"
                return f"{text} {html.escape(value_label)}" if value_label else text
            if block.get("kind") == "donut":
                total = sum(max(0, value) for value in values) or 1
                offset = 0.0
                circles = []
                for point, value in zip(data, values):
                    percent = max(0, value) / total * 100
                    circles.append(
                        f'<circle class="donut-slice {html.escape(point.get("color") or "tone-0")}" cx="60" cy="60" r="42" pathLength="100" stroke-dasharray="{percent:.2f} {100 - percent:.2f}" stroke-dashoffset="{-offset:.2f}" />'
                    )
                    offset += percent
                chart_visual = '<svg class="donut-svg" viewBox="0 0 120 120" role="img" aria-label="Donut chart"><circle class="donut-track" cx="60" cy="60" r="42" />' + ''.join(circles) + '</svg>'
                chart_class = "chart-fallback chart-donut"
            else:
                bars = ''.join(
                    '<div class="chart-bar-row">'
                    f'<span>{html.escape(point.get("label") or "")}</span>'
                    f'<div class="chart-bar-track"><i class="{html.escape(point.get("color") or "tone-0")}" style="width:{min(100, abs(float(point.get("value") or 0)) / max_value * 100):.2f}%"></i></div>'
                    f'<b>{_format_chart_value(point.get("value"))}</b>'
                    '</div>'
                    for point in data
                )
                chart_visual = f'<div class="bar-chart-svg" role="img" aria-label="Bar chart">{bars}</div>'
                chart_class = "chart-fallback chart-bar"
            list_items = ''.join(
                f'<li><span>{html.escape(point.get("label") or "")}</span><strong>{_format_chart_value(point.get("value"))}</strong></li>'
                for point in data
            )
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="{chart_class}">{chart_visual}<ul class="chart-values">{list_items}</ul></div></section>')
        elif block_type == "canvas_network":
            nodes = block.get("nodes") or []
            node_lookup = {node["id"]: node for node in nodes}
            edge_lines = ''.join(
                f'<line x1="{node_lookup.get(edge["from"], {}).get("x", 0)}" y1="{node_lookup.get(edge["from"], {}).get("y", 0)}" x2="{node_lookup.get(edge["to"], {}).get("x", 0)}" y2="{node_lookup.get(edge["to"], {}).get("y", 0)}" />'
                for edge in block.get("edges") or []
            )
            node_marks = ''.join(
                f'<g><circle cx="{node.get("x", 0)}" cy="{node.get("y", 0)}" r="5"/><text x="{node.get("x", 0)}" y="{node.get("y", 0) + 12}">{html.escape(node.get("label") or "")}</text></g>'
                for node in nodes
            )
            adjacency = ''.join(
                '<li>'
                f'{html.escape((node_lookup.get(edge["from"]) or {}).get("label", edge["from"]))} → {html.escape((node_lookup.get(edge["to"]) or {}).get("label", edge["to"]))}'
                + (f' <em>{html.escape(edge.get("label") or "")}</em>' if edge.get("label") else '')
                + '</li>'
                for edge in block.get("edges") or []
            ) or ''.join(f'<li>{html.escape(node.get("label") or "")}</li>' for node in nodes)
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="canvas-network-fallback"><svg viewBox="0 0 100 100" role="img" aria-label="Static network diagram">{edge_lines}{node_marks}</svg><h3>Connections</h3><ul>{adjacency}</ul></div></section>')
        elif block_type == "three_scene":
            objects = block.get("objects") or []
            def _coord(value: Any) -> str:
                number = float(value or 0)
                return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")
            markers = ''.join(
                f'<div class="scene-object" style="left:{50 + float(obj.get("position", [0, 0, 0])[0]) * 8:.2f}%;top:{50 - float(obj.get("position", [0, 0, 0])[1]) * 8:.2f}%"><span>{html.escape(obj.get("label") or "")}</span></div>'
                for obj in objects
            )
            object_list = ''.join(
                f'<li><strong>{html.escape(obj.get("label") or "")}</strong>: size {_coord(obj.get("size"))}; position {", ".join(_coord(value) for value in obj.get("position", [0, 0, 0]))}</li>'
                for obj in objects
            )
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="three-scene-fallback"><div class="scene-map" role="img" aria-label="2D projection of object positions">{markers}</div><ul>{object_list}</ul></div></section>')
        elif block_type == "gantt":
            columns = block.get("columns") or []
            template = f"minmax(100px,1.3fr) repeat({len(columns)},minmax(62px,1fr))"
            header = '<div class="gantt-corner"></div>' + ''.join(f'<div class="gantt-day">{html.escape(column)}</div>' for column in columns)
            lane_rows = []
            for lane in block.get("lanes") or []:
                segments = ''.join(
                    f'<div class="gantt-segment {html.escape(lane.get("color") or "tone-0")}" style="grid-column:{segment["start"] + 2}/{segment["end"] + 2}">{html.escape(segment.get("label") or "")}</div>'
                    for segment in lane.get("segments") or []
                )
                lane_rows.append(f'<div class="gantt-label">{html.escape(lane.get("label") or "")}</div><div class="gantt-slots" style="grid-column:2/{len(columns) + 2}"></div>{segments}')
            blocks_html.append(f'<section class="panel wide-panel"><h2>{block_title}</h2><div class="visual-gantt"><div class="gantt-grid" style="grid-template-columns:{template}">{header}{"".join(lane_rows)}</div></div></section>')
        elif block_type == "progress":
            items_html = ''.join(
                '<div class="progress-item">'
                f'<div class="progress-ring {html.escape(item.get("color") or "tone-0")}" style="--value:{item.get("value", 0)}"><span>{item.get("value", 0)}%</span></div>'
                f'<div><strong>{html.escape(item.get("label") or "")}</strong>'
                + (f'<p>{html.escape(item.get("detail") or "")}</p>' if item.get("detail") else '')
                + '</div></div>'
                for item in block.get("items") or []
            )
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="progress-grid">{items_html}</div></section>')
        elif block_type == "kanban":
            columns_html = ''
            for column in block.get("columns") or []:
                cards = ''.join(
                    '<div class="kanban-item">'
                    f'<strong>{html.escape(item.get("title") or "")}</strong>'
                    + (f'<p>{html.escape(item.get("detail") or "")}</p>' if item.get("detail") else '')
                    + (f'<span>{html.escape(item.get("tag") or "")}</span>' if item.get("tag") else '')
                    + '</div>'
                    for item in column.get("items") or []
                )
                empty_state = '<div class="kanban-empty">No items</div>'
                columns_html += f'<div class="kanban-column"><h3>{html.escape(column.get("title") or "")}</h3>{cards or empty_state}</div>'
            blocks_html.append(f'<section class="panel wide-panel"><h2>{block_title}</h2><div class="kanban-board">{columns_html}</div></section>')
        elif block_type == "priority_matrix":
            quadrants = {quadrant.get("key"): quadrant for quadrant in block.get("quadrants") or []}
            matrix_html = ''
            for key in ("high_high", "high_low", "low_high", "low_low"):
                quadrant = quadrants.get(key) or {"title": key.replace("_", " ").title(), "items": []}
                items = ''.join(f'<li>{html.escape(item)}</li>' for item in quadrant.get("items") or [])
                matrix_html += f'<div class="matrix-quadrant {key}"><h3>{html.escape(quadrant.get("title") or "")}</h3><ul>{items}</ul></div>'
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="matrix-axis matrix-y">Impact ↑</div><div class="priority-matrix">{matrix_html}</div><div class="matrix-axis matrix-x">Urgency →</div></section>')
        elif block_type == "dependency_graph":
            node_lookup = {node["id"]: node for node in block.get("nodes") or []}
            nodes_html = ''.join(f'<div class="dependency-node status-{html.escape(node.get("status") or "neutral")}" id="node-{html.escape(node["id"])}">{html.escape(node["label"])}</div>' for node in block.get("nodes") or [])
            edges_html = ''.join(
                '<div class="dependency-edge">'
                f'<span>{html.escape((node_lookup.get(edge["from"]) or {}).get("label", edge["from"]))}</span><b>→</b><span>{html.escape((node_lookup.get(edge["to"]) or {}).get("label", edge["to"]))}</span>'
                + (f'<em>{html.escape(edge.get("label") or "")}</em>' if edge.get("label") else '') + '</div>'
                for edge in block.get("edges") or []
            )
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="dependency-graph"><div class="dependency-nodes">{nodes_html}</div><div class="dependency-edges">{edges_html}</div></div></section>')
        elif block_type in {"flow", "flowchart"}:
            steps = block.get("steps") or []
            steps_html = ''
            for index, step in enumerate(steps):
                steps_html += f'<div class="flow-node status-{html.escape(step.get("status") or "neutral")}"><span>{index + 1}</span><div><strong>{html.escape(step.get("title") or "")}</strong>' + (f'<p>{html.escape(step.get("detail") or "")}</p>' if step.get("detail") else '') + '</div></div>'
                if index < len(steps) - 1:
                    steps_html += '<div class="flow-arrow">↓</div>'
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="visual-flow">{steps_html}</div></section>')
        elif block_type == "details":
            sections_html = ''.join(
                '<details open><summary>' + html.escape(section.get("title") or "") + '</summary><ul>'
                + ''.join(f'<li>{html.escape(item)}</li>' for item in section.get("items") or [])
                + '</ul></details>'
                for section in block.get("sections") or []
            )
            blocks_html.append(f'<section class="panel"><h2>{block_title}</h2><div class="detail-sections">{sections_html}</div></section>')

    full_rendered = render_md_to_html(response)
    document = (
        "<!doctype html>\n"
        "<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
        f"<title>{title} — visual digest</title>"
        "<style>"
        ":root{color-scheme:dark;--bg:#08111f;--panel:#0f1b2d;--ink:#ecf2ff;--muted:#99a8c6;--line:#243753;--accent:#7dd3fc;--accent-2:#a78bfa;--success:#34d399;--warn:#fbbf24;--shadow:0 24px 60px rgba(0,0,0,.28)}"
        "*{box-sizing:border-box}html,body{margin:0;width:100%;max-width:100%;overflow-x:hidden;background:radial-gradient(circle at top,#102544 0,#08111f 55%,#050b14 100%);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Inter,sans-serif}"
        "body{padding:18px 14px 42px;line-height:1.5;overflow-wrap:anywhere}a{color:inherit;text-decoration:none}img,svg,canvas,video{max-width:100%}main{width:100%;max-width:1100px;min-width:0;margin:0 auto;display:grid;gap:16px}main>*{min-width:0}"
        ".hero,.panel,.full-body{min-width:0;max-width:100%;background:linear-gradient(180deg,rgba(18,35,58,.95),rgba(12,23,40,.92));border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow)}"
        ".hero{padding:22px 18px;position:relative;overflow:hidden}.hero::after{content:'';position:absolute;inset:auto -10% -25% 35%;height:240px;background:radial-gradient(circle,rgba(125,211,252,.18),transparent 62%);pointer-events:none}"
        ".eyebrow{display:inline-flex;gap:8px;align-items:center;padding:6px 10px;border-radius:999px;background:rgba(125,211,252,.12);color:#d8f4ff;border:1px solid rgba(125,211,252,.18);font-size:12px;letter-spacing:.04em;text-transform:uppercase}"
        "h1{margin:14px 0 10px;font-size:clamp(28px,7vw,44px);line-height:1.06;max-width:16ch}.lede{margin:0;max-width:68ch;color:#d5e1fb;font-size:16px}.meta{margin-top:12px;color:var(--muted);font-size:13px}"
        ".chip-grid,.fact-grid{display:grid;gap:12px}.chip-grid{grid-template-columns:repeat(auto-fit,minmax(120px,1fr));margin-top:18px}.chip{padding:12px 13px;border-radius:18px;background:rgba(8,17,31,.55);border:1px solid rgba(125,211,252,.16)}"
        ".chip span,.fact span,.timeline-label{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}.chip strong,.fact strong{display:block;margin-top:6px;font-size:18px;line-height:1.2}"
        ".panel{padding:18px}.panel h2{margin:0 0 12px;font-size:18px}.panel p{margin:0;color:#d6e1f7}.takeaways{margin:0;padding-left:20px;display:grid;gap:10px}.takeaways li{padding-left:4px}"
        ".fact-grid{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}.fact{padding:14px;border-radius:18px;background:rgba(8,17,31,.45);border:1px solid rgba(52,211,153,.18)}.fact p{margin-top:8px;color:#d2ddf5}"
        ".metric-tile{padding:18px;border-radius:20px;background:linear-gradient(135deg,rgba(125,211,252,.18),rgba(167,139,250,.14));border:1px solid rgba(125,211,252,.25)}.metric-tile span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.metric-tile strong{display:block;margin-top:8px;font-size:clamp(30px,12vw,54px);line-height:1}.metric-tile p{margin-top:10px!important;color:#d6e8ff}.trend-up p{color:#bbf7d0}.trend-down p{color:#fecdd3}"
        ".chart-fallback{display:grid;gap:14px}.chart-values{margin:0;padding-left:20px;display:grid;gap:6px}.chart-values li{display:flex;justify-content:space-between;gap:12px}.chart-values span{color:var(--muted)}.chart-bar-row{display:grid;grid-template-columns:minmax(64px,.8fr) 1fr auto;gap:8px;align-items:center;margin:8px 0}.chart-bar-row span,.chart-bar-row b{font-size:12px}.chart-bar-track{height:18px;border-radius:999px;background:rgba(125,211,252,.12);overflow:hidden}.chart-bar-track i{display:block;height:100%;border-radius:999px;background:var(--accent)}.donut-svg{width:min(190px,55vw);margin:auto;display:block;transform:rotate(-90deg)}.donut-track{fill:none;stroke:rgba(125,211,252,.13);stroke-width:18}.donut-slice{fill:none;stroke:var(--accent);stroke-width:18}"
        ".canvas-network-fallback svg{width:100%;min-height:220px;border:1px solid var(--line);border-radius:16px;background:rgba(8,17,31,.35)}.canvas-network-fallback line{stroke:rgba(125,211,252,.45);stroke-width:1.2}.canvas-network-fallback circle{fill:var(--accent)}.canvas-network-fallback text{fill:var(--ink);font-size:5px}.canvas-network-fallback h3{margin:12px 0 6px;font-size:13px}.canvas-network-fallback ul,.three-scene-fallback ul{margin:0;padding-left:20px;display:grid;gap:6px}.canvas-network-fallback em{color:var(--muted)}"
        ".scene-map{position:relative;height:240px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(90deg,rgba(125,211,252,.08) 1px,transparent 1px),linear-gradient(0deg,rgba(125,211,252,.08) 1px,transparent 1px),rgba(8,17,31,.35);background-size:20px 20px;overflow:hidden}.scene-map:before,.scene-map:after{content:'';position:absolute;background:rgba(125,211,252,.18)}.scene-map:before{left:50%;top:0;bottom:0;width:1px}.scene-map:after{top:50%;left:0;right:0;height:1px}.scene-object{position:absolute;transform:translate(-50%,-50%);max-width:42%;padding:7px 9px;border-radius:999px;background:#13233a;border:1px solid rgba(167,139,250,.45);font-size:11px;font-weight:700}.three-scene-fallback ul{margin-top:12px}"
        ".process{list-style:none;margin:0;padding:0;display:grid;gap:12px;min-width:0}.process li{display:grid;grid-template-columns:42px minmax(0,1fr);gap:12px;align-items:flex-start;min-width:0;padding:14px;border-radius:18px;background:rgba(8,17,31,.45);border:1px solid rgba(167,139,250,.2)}.process li>div{min-width:0}"
        ".step-index{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(180deg,rgba(167,139,250,.35),rgba(125,211,252,.18));font-weight:700}.process strong{display:block;margin-bottom:6px}.process p{margin:0;color:#dbe6ff}"
        ".timeline{list-style:none;margin:0;padding:0;display:grid;gap:14px}.timeline-item{display:grid;grid-template-columns:92px 1fr;gap:12px;align-items:flex-start;padding:14px;border-radius:18px;background:rgba(8,17,31,.45);border:1px solid rgba(125,211,252,.16)}.timeline-item strong{display:block;margin-bottom:6px}"
        ".table-wrap{width:100%;max-width:100%;min-width:0;overflow-x:auto;-webkit-overflow-scrolling:touch}.table-wrap table{width:100%;border-collapse:collapse}.table-wrap th,.table-wrap td{border:1px solid rgba(125,211,252,.14);padding:8px 10px;text-align:left}.table-wrap th{background:rgba(15,27,45,.92)}"
        ".mermaid{white-space:pre-wrap;word-break:break-word;overflow:auto;background:#07101d;border:1px solid rgba(125,211,252,.12);border-radius:16px;padding:14px;color:#e8f0ff}.diagram-caption{margin-bottom:10px;color:#d2ddf5}"
        ".checklist{list-style:none;margin:0;padding:0;display:grid;gap:10px}.check-item{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;border-radius:16px;background:rgba(8,17,31,.45);border:1px solid rgba(52,211,153,.18)}.check-mark{font-weight:700;color:#dff7ed}"
        ".callout{border-left:4px solid var(--accent)}.callout-warn{border-left-color:var(--warn)}.callout-success{border-left-color:var(--success)}"
        ".wide-panel{overflow:hidden}.visual-gantt{overflow-x:auto}.gantt-grid{min-width:680px;display:grid;position:relative;border-top:1px solid var(--line);border-left:1px solid var(--line)}.gantt-grid>div{border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-height:42px;padding:8px}.gantt-day{text-align:center;color:var(--muted);font-size:12px}.gantt-label{font-weight:700}.gantt-slots{grid-row:auto;min-height:42px;background:repeating-linear-gradient(90deg,transparent 0,transparent calc(14.285% - 1px),rgba(125,211,252,.1) calc(14.285% - 1px),rgba(125,211,252,.1) 14.285%)}.gantt-segment{z-index:2;align-self:center;margin:5px;border-radius:8px!important;min-height:30px!important;padding:6px 8px!important;background:var(--accent);color:#06101b;font-size:11px;font-weight:800}"
        ".progress-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.progress-item{display:flex;align-items:center;gap:12px;padding:12px;border:1px solid var(--line);border-radius:16px;background:rgba(8,17,31,.45)}.progress-ring{--ring:var(--accent);width:72px;height:72px;border-radius:50%;display:grid;place-items:center;flex:none;background:conic-gradient(var(--ring) calc(var(--value)*1%),rgba(125,211,252,.12) 0);position:relative}.progress-ring:after{content:'';position:absolute;inset:8px;border-radius:50%;background:var(--panel)}.progress-ring span{z-index:1;font-weight:800}.progress-item p{font-size:12px;color:var(--muted)}"
        ".kanban-board{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.kanban-column{padding:10px;border:1px solid var(--line);border-radius:16px;background:rgba(8,17,31,.36)}.kanban-column h3{margin:0 0 9px;font-size:13px}.kanban-item{padding:10px;margin-top:8px;border-radius:12px;background:#13233a;border:1px solid rgba(125,211,252,.14)}.kanban-item p{margin-top:5px!important;font-size:12px;color:var(--muted)}.kanban-item span{display:inline-block;margin-top:7px;padding:3px 6px;border-radius:999px;background:rgba(251,191,36,.13);color:#ffe39a;font-size:10px}.kanban-empty{color:var(--muted);font-size:12px}"
        ".priority-matrix{display:grid;grid-template-columns:1fr 1fr;gap:8px}.matrix-quadrant{min-height:130px;padding:12px;border-radius:14px;border:1px solid var(--line);background:#101c2f}.matrix-quadrant.high_high{border-color:rgba(251,113,133,.5)}.matrix-quadrant.high_low{border-color:rgba(251,191,36,.45)}.matrix-quadrant.low_high{border-color:rgba(125,211,252,.4)}.matrix-quadrant.low_low{opacity:.75}.matrix-quadrant h3{margin:0 0 8px;font-size:13px}.matrix-quadrant ul{margin:0;padding-left:18px;font-size:12px}.matrix-axis{color:var(--muted);font-size:11px}.matrix-x{text-align:right;margin-top:5px}.matrix-y{margin-bottom:5px}"
        ".dependency-nodes{display:flex;flex-wrap:wrap;gap:8px}.dependency-node{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#13233a;font-weight:700;font-size:12px}.status-waiting,.status-blocked{border-color:rgba(251,191,36,.55)!important}.status-done{border-color:rgba(52,211,153,.55)!important}.dependency-edges{display:grid;gap:7px;margin-top:12px}.dependency-edge{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:center;padding:8px;border-radius:10px;background:rgba(8,17,31,.4);font-size:11px}.dependency-edge b{color:var(--accent);font-size:18px}.dependency-edge em{grid-column:1/-1;color:var(--muted);text-align:center}"
        ".visual-flow{display:grid;justify-items:center}.flow-node{width:min(100%,520px);display:grid;grid-template-columns:38px 1fr;gap:10px;padding:12px;border-radius:14px;border:1px solid var(--line);background:#13233a}.flow-node>span{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:rgba(125,211,252,.14);font-weight:800}.flow-node p{font-size:12px;color:var(--muted)}.flow-arrow{color:var(--accent);font-size:22px;line-height:1.2}.detail-sections details,.full-body{border:1px solid var(--line);border-radius:14px;padding:12px;margin-top:8px;background:rgba(8,17,31,.35)}.detail-sections summary,.full-body summary{cursor:pointer;font-weight:700}.detail-sections ul{margin:9px 0 0;padding-left:20px}.detail-sections li{margin:5px 0}"
        ".tone-0{--ring:#7dd3fc}.tone-1{--ring:#a78bfa}.tone-2{--ring:#34d399}.tone-3{--ring:#fbbf24}.tone-4{--ring:#fb7185}.tone-5{--ring:#60a5fa}.cyan{--ring:#7dd3fc}.green{--ring:#34d399}.amber{--ring:#fbbf24}.violet{--ring:#a78bfa}"
        ".section-body h1,.section-body h2,.section-body h3,.section-body h4{margin:1em 0 .45em}.section-body p{margin:.65em 0;color:#eaf0ff}.section-body ul,.section-body ol{padding-left:1.3em}.section-body blockquote{margin:.8em 0;padding:10px 14px;border-left:3px solid var(--accent);background:rgba(15,27,45,.78);border-radius:0 12px 12px 0;color:#d6e4ff}"
        ".section-body pre{white-space:pre-wrap;word-break:break-word;overflow:auto;background:#07101d;border:1px solid rgba(125,211,252,.12);border-radius:16px;padding:14px;color:#e8f0ff}.section-body code{background:rgba(125,211,252,.08);padding:2px 6px;border-radius:6px}.section-body table{width:100%;border-collapse:collapse;display:block;overflow-x:auto}.section-body th,.section-body td{border:1px solid rgba(125,211,252,.14);padding:8px 10px;text-align:left}.section-body th{background:rgba(15,27,45,.92)}"
        ".footer-note{color:var(--muted);font-size:13px}.full-body{margin-top:8px}"
        "@media (max-width:600px){.hero{padding:18px 16px}.panel{padding:16px;border-radius:18px}.panel h2{font-size:20px;line-height:1.2}.fact-grid,.progress-grid,.kanban-board,.priority-matrix{grid-template-columns:1fr}.timeline-item{grid-template-columns:1fr}.process li{grid-template-columns:36px minmax(0,1fr);gap:10px;padding:12px}.step-index{width:36px;height:36px;border-radius:11px}.table-wrap{overflow:visible}.table-wrap table,.table-wrap tbody,.table-wrap tr,.table-wrap td{display:block;width:100%}.table-wrap thead{display:none}.table-wrap tbody{display:grid;gap:10px}.table-wrap tr{padding:10px 12px;border:1px solid rgba(125,211,252,.18);border-radius:14px;background:rgba(8,17,31,.45)}.table-wrap td{display:grid;grid-template-columns:minmax(88px,.8fr) minmax(0,1.2fr);gap:10px;border:0;border-bottom:1px solid rgba(125,211,252,.12);padding:9px 0}.table-wrap td:last-child{border-bottom:0}.table-wrap td:before{content:attr(data-label);color:var(--muted);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}}"
        "@media (min-width:860px){body{padding:24px 20px 56px}.hero{padding:28px 24px}.panel{padding:20px}}"
        "</style>"
        "<script type=\"module\">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';mermaid.initialize({startOnLoad:true,theme:'dark'});</script>"
        "</head><body><main>"
        f"<section class=\"hero\"><div class=\"eyebrow\">Visual digest · Hermes</div><h1>{title}</h1><p class=\"lede\">{summary}</p><div class=\"meta\">{html.escape(ts)}{' · ' + topic if topic else ''}</div><div class=\"chip-grid\">{metrics_html}</div></section>"
        + "".join(blocks_html)
        + f"<details class=\"full-body\"><summary>Full source response</summary><div class=\"section-body\">{full_rendered}</div></details>"
        + "<section class=\"panel footer-note\"><strong>How this was made.</strong> Representation-first: an auxiliary LLM analyzed the source, selected visual encodings, and returned a structured visual specification. The renderer did not infer this layout from Markdown headings.</section>"
        + "</main></body></html>\n"
    )
    Path(path).write_text(document, encoding="utf-8")
    return path
