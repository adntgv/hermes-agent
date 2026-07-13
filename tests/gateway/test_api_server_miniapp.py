"""Focused tests for the API-server Hermes miniapp report route seam."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter, security_headers_middleware
import gateway.visual_report_store as report_store


@pytest.fixture
def adapter():
    return APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "key": "«redacted:sk-…»",
                "miniapp": {
                    "app_name": "Hermes Test Miniapp",
                    "accent": "#2563eb",
                    "dangerous_secret": "must-not-leak",
                },
            },
        )
    )


def _create_miniapp_app(adapter: APIServerAdapter) -> web.Application:
    app = web.Application(middlewares=[security_headers_middleware])
    adapter._register_miniapp_routes(app)
    return app


@pytest.mark.asyncio
async def test_miniapp_shell_routes_are_public_no_store_and_csp_compatible(adapter):
    app = _create_miniapp_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        for path in ("/miniapp", "/miniapp/", "/miniapp/index.html"):
            resp = await cli.get(path)
            body = await resp.text()

            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            assert "Hermes Report" in body
            assert "collaboration-board" not in body
            assert "Authorization" not in body
            assert resp.headers["Cache-Control"] == "no-store"
            csp = resp.headers["Content-Security-Policy"]
            assert "default-src 'self'" in csp
            assert "script-src 'self' https://telegram.org" in csp
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert resp.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_miniapp_config_is_browser_safe_and_report_only(adapter):
    app = _create_miniapp_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        resp = await cli.get("/miniapp/config.json")
        payload = await resp.json()
        raw = await resp.text()

    assert resp.status == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert payload["app_name"] == "Hermes Test Miniapp"
    assert payload["accent"] == "#2563eb"
    assert payload["endpoints"] == {"report_latest": "/miniapp/api/report/latest"}
    assert "board" not in raw.lower()
    assert "visual_registry" not in raw
    assert "«redacted:sk-…»" not in raw
    assert "must-not-leak" not in raw
    assert "dangerous_secret" not in raw


@pytest.mark.asyncio
async def test_latest_report_route_returns_saved_report_no_store(adapter, monkeypatch, tmp_path):
    monkeypatch.setattr(report_store, "get_hermes_home", lambda: tmp_path)
    saved = report_store.save_latest_report(
        {"title": "Real weekly report", "summary": "Grounded", "blocks": [{"type": "metric", "label": "A", "value": "1"}]},
        source_response="# Source",
        source_metadata={"response_id": "r1"},
        event_metadata={"platform": "telegram", "chat_id": "c", "thread_id": "t"},
        generated_at="2026-07-11T12:00:00Z",
    )
    app = _create_miniapp_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        resp = await cli.get("/miniapp/api/report/latest")
        payload = await resp.json()

    assert resp.status == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert payload["success"] is True
    assert payload["report"] == saved
    assert payload["report"]["plan"]["title"] == "Real weekly report"


@pytest.mark.asyncio
async def test_latest_report_route_returns_useful_404_when_empty(adapter, monkeypatch, tmp_path):
    monkeypatch.setattr(report_store, "get_hermes_home", lambda: tmp_path)
    app = _create_miniapp_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        resp = await cli.get("/miniapp/api/report/latest")
        payload = await resp.json()

    assert resp.status == 404
    assert resp.headers["Cache-Control"] == "no-store"
    assert payload == {"success": False, "error": "No report has been generated yet", "report": None}


@pytest.mark.asyncio
async def test_board_and_registry_routes_are_not_registered(adapter):
    app = _create_miniapp_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        get_board = await cli.get("/miniapp/api/board")
        post_board = await cli.post("/miniapp/api/board", json={"action": "get"})
        registry = await cli.get("/miniapp/api/visual-registry")

    assert get_board.status == 404
    assert post_board.status == 404
    assert registry.status == 404


@pytest.mark.asyncio
async def test_miniapp_assets_are_served_no_store_and_traversal_is_blocked(adapter):
    app = _create_miniapp_app(adapter)
    async with TestClient(TestServer(app)) as cli:
        asset_resp = await cli.get("/miniapp/assets/app.js")
        asset_body = await asset_resp.text()
        traversal_resp = await cli.get("/miniapp/assets/%2e%2e%5cindex.html")

    assert asset_resp.status == 200
    assert "window.__hermesMiniappReady" in asset_body
    assert "window.__hermesReportReady" in asset_body
    assert "javascript" in asset_resp.headers.get("Content-Type", "")
    assert asset_resp.headers["Cache-Control"] == "no-store"
    assert asset_resp.headers["X-Content-Type-Options"] == "nosniff"
    assert traversal_resp.status == 403
