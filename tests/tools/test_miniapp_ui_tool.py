import json
from pathlib import Path

from tools import miniapp_ui_tool


def _seed_miniapp(root: Path) -> None:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<main class="ic-shell" data-command-url="/miniapp/api/command"></main>'
        '<script src="https://telegram.org/js/telegram-web-app.js"></script>'
        '<link rel="stylesheet" href="/miniapp/assets/styles.css">'
        '<script src="/miniapp/assets/app.js"></script>',
        encoding="utf-8",
    )
    (root / "assets" / "app.js").write_text(
        "const InfiniteCanvasApp = { init() {} };\n"
        "document.addEventListener('DOMContentLoaded', () => InfiniteCanvasApp.init());\n",
        encoding="utf-8",
    )
    (root / "assets" / "styles.css").write_text(".ic-shell { min-height: 100vh; }\n", encoding="utf-8")


def test_miniapp_ui_list_reports_validation(monkeypatch, tmp_path):
    _seed_miniapp(tmp_path)
    monkeypatch.setattr(miniapp_ui_tool, "_MINIAPP_ROOT", tmp_path)

    data = json.loads(miniapp_ui_tool.miniapp_ui(action="list"))

    assert data["success"] is True
    assert data["validation"]["ok"] is True
    assert {entry["path"] for entry in data["files"]} == {"index.html", "assets/app.js", "assets/styles.css"}


def test_miniapp_ui_rejects_and_restores_invalid_js(monkeypatch, tmp_path):
    _seed_miniapp(tmp_path)
    monkeypatch.setattr(miniapp_ui_tool, "_MINIAPP_ROOT", tmp_path)
    app = tmp_path / "assets" / "app.js"
    original = app.read_text(encoding="utf-8")

    data = json.loads(miniapp_ui_tool.miniapp_ui(action="write", path="assets/app.js", content="function broken() {"))

    assert data["success"] is False
    assert "validation failed" in data["error"]
    assert app.read_text(encoding="utf-8") == original


def test_miniapp_ui_blocks_paths_outside_allowed_scope(monkeypatch, tmp_path):
    _seed_miniapp(tmp_path)
    monkeypatch.setattr(miniapp_ui_tool, "_MINIAPP_ROOT", tmp_path)

    data = json.loads(miniapp_ui_tool.miniapp_ui(action="read", path="../config.yaml"))

    assert data["success"] is False
    assert "Path must be one of" in data["error"]
