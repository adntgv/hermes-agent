"""Source-level checks for the no-build miniapp report reader."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "gateway" / "miniapp"
REQUIRED_TYPES = [
    "metric",
    "progress",
    "timeline",
    "gantt",
    "kanban",
    "priority_matrix",
    "dependency_graph",
    "flow",
    "flowchart",
    "comparison_table",
    "chart",
    "canvas_network",
    "three_scene",
    "details",
    "key_points",
    "insight_cards",
    "sequence",
    "checklist",
    "callout",
    "markdown",
    "mermaid",
]


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_report_miniapp_sources_have_no_board_gallery_or_fake_samples():
    combined = "\n".join(_text(path) for path in ["index.html", "assets/app.js", "assets/styles.css"])
    banned = [
        "collaboration-board",
        "board-canvas",
        "boardEndpoint",
        "localStorage",
        "visual report capability gallery",
        "Search capabilities",
        "fake",
        "sample",
        "STORAGE_KEY",
    ]
    for marker in banned:
        assert marker.lower() not in combined.lower(), marker


def test_report_renderer_declares_required_type_support_and_safe_dom_contract():
    app = _text("assets/app.js")

    for component_type in REQUIRED_TYPES:
        assert component_type in app
    assert "report_latest" in app
    assert "window.__hermesMiniappReady = true" in app
    assert "window.__hermesReportReady = true" in app
    assert ".innerHTML" not in app
    assert "insertAdjacentHTML" not in app
    assert "DOMParser" not in app


def test_report_miniapp_uses_medium_like_editorial_shell():
    html = _text("index.html")
    css = _text("assets/styles.css")

    assert "Hermes Report" in html
    assert "max-width: 760px" in css
    assert "box-shadow" not in css
    assert "linear-gradient" not in css
    assert "border-radius: 999" not in css
    assert "overflow-x: hidden" in css
    assert "serif" in css
    assert "@media (prefers-color-scheme: dark)" in css
