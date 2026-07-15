import builtins
import re
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock

import pytest

import agent.secret_scope as secret_scope

import gateway.run as run_mod
import gateway.telegram_long_response_html as long_html
import tools.lazy_deps as lazy_deps
from gateway.config import Platform
from gateway.run import GatewayRunner


SAMPLE_RESPONSE = """# Build plan

We should optimize the long-response experience.

## Goals
- Reduce reading effort
- Show meaning quickly
- Keep the full response available

## Steps
1. Generate a visual digest
2. Send the original full HTML too

Status: proposed
Owner: Hermes
"""

SAMPLE_PLAN = {
    "title": "Long-response delivery redesign",
    "summary": "Use an LLM-planned visual companion first, while keeping the full raw HTML as a faithful fallback.",
    "theme_hint": "plan",
    "metrics": [
        {"label": "Artifacts", "value": "2"},
        {"label": "Primary", "value": "Visual digest"},
    ],
    "blocks": [
        {
            "type": "key_points",
            "title": "Why this matters",
            "items": [
                "Reduce time-to-understanding on mobile.",
                "Preserve the original full response for exact detail.",
            ],
        },
        {
            "type": "sequence",
            "title": "Delivery flow",
            "steps": [
                {"title": "Plan", "detail": "Auxiliary LLM chooses the best representation."},
                {"title": "Render", "detail": "HTML renderer turns the plan into a visual artifact."},
                {"title": "Deliver", "detail": "Telegram gets digest first, then raw HTML if enabled."},
            ],
        },
        {
            "type": "mermaid",
            "title": "Flow",
            "caption": "Planner-first flow",
            "code": "flowchart TD\nA[Long answer] --> B[LLM planner]\nB --> C[Visual digest]\nB --> D[Raw HTML]",
        },
    ],
}


def _event() -> SimpleNamespace:
    return SimpleNamespace(
        source=SimpleNamespace(
            platform=Platform.TELEGRAM,
            chat_id="289310951",
            thread_id="main",
            chat_topic="Home",
        )
    )


def _runner() -> GatewayRunner:
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner._reply_anchor_for_event = lambda _event: None
    runner._thread_metadata_for_source = lambda _source, _reply: {"thread_id": "main"}
    return runner


def test_long_response_config_parses_visual_digest(monkeypatch):
    runner = _runner()
    monkeypatch.setattr(
        run_mod,
        "_load_gateway_config",
        lambda: {
            "telegram": {
                "long_response_html": {
                    "enabled": True,
                    "threshold_chars": 1200,
                    "threshold_lines": 14,
                    "notice": "raw notice",
                    "caption": "raw caption",
                    "visual_digest": {
                        "enabled": True,
                        "caption": "digest caption",
                        "send_raw_html": False,
                    },
                    "hosting": {
                        "enabled": True,
                        "endpoint_url": "https://objects.example.test",
                        "bucket": "reports",
                        "public_base_url": "https://reports.example.test",
                        "loader_url": "https://reports.example.test/long-responses/loader/index.html",
                        "loader_version": "2",
                        "key_prefix": "long-responses",
                        "access_key_env": "REPORTS_ACCESS_KEY",
                        "secret_key_env": "REPORTS_SECRET_KEY",
                        "link_text": "Open full response",
                        "fallback_to_attachment": True,
                    },
                }
            }
        },
    )

    cfg = runner._telegram_long_response_html_config()
    assert cfg["enabled"] is True
    assert cfg["threshold_chars"] == 1200
    assert cfg["visual_digest"]["enabled"] is True
    assert cfg["visual_digest"]["caption"] == "digest caption"
    assert cfg["visual_digest"]["send_raw_html"] is False
    assert cfg["visual_digest"]["link_text"] == "Open visual report"
    assert cfg["hosting"] == {
        "enabled": True,
        "endpoint_url": "https://objects.example.test",
        "bucket": "reports",
        "public_base_url": "https://reports.example.test",
        "loader_url": "https://reports.example.test/long-responses/loader/index.html",
        "loader_version": "2",
        "key_prefix": "long-responses",
        "access_key_env": "REPORTS_ACCESS_KEY",
        "secret_key_env": "REPORTS_SECRET_KEY",
        "link_text": "Open full response",
        "fallback_to_attachment": True,
    }


@pytest.mark.asyncio
async def test_long_response_delivery_returns_hosted_link_without_attachment(monkeypatch, tmp_path):
    runner = _runner()
    runner._host_long_response_html = AsyncMock(
        return_value="https://reports.example.test/long-responses/token/index.html"
    )
    adapter = SimpleNamespace(send_document=AsyncMock())
    runner.adapters = {Platform.TELEGRAM: adapter}
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        run_mod,
        "_load_gateway_config",
        lambda: {
            "telegram": {
                "long_response_html": {
                    "enabled": True,
                    "threshold_chars": 10,
                    "threshold_lines": 2,
                    "hosting": {
                        "enabled": True,
                        "link_text": "Open full response",
                    },
                }
            }
        },
    )

    result = await runner._maybe_deliver_long_telegram_response_as_html(_event(), SAMPLE_RESPONSE)

    assert result == "[Open full response](https://reports.example.test/long-responses/token/index.html)"
    runner._host_long_response_html.assert_awaited_once()
    adapter.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_response_delivery_hosts_visual_digest_instead_of_wrapped_markdown(monkeypatch, tmp_path):
    runner = _runner()
    runner._plan_visual_digest = AsyncMock(return_value=SAMPLE_PLAN)
    runner._host_long_response_html = AsyncMock(
        return_value="https://reports.example.test/long-responses/visual-token/index.html"
    )
    adapter = SimpleNamespace(send_document=AsyncMock())
    runner.adapters = {Platform.TELEGRAM: adapter}
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        run_mod,
        "_load_gateway_config",
        lambda: {
            "telegram": {
                "long_response_html": {
                    "enabled": True,
                    "threshold_chars": 10,
                    "threshold_lines": 2,
                    "visual_digest": {
                        "enabled": True,
                        "link_text": "Open visual report",
                        "send_raw_html": False,
                    },
                    "hosting": {
                        "enabled": True,
                        "fallback_to_attachment": True,
                    },
                }
            }
        },
    )

    result = await runner._maybe_deliver_long_telegram_response_as_html(_event(), SAMPLE_RESPONSE)

    assert result == "[Open visual report](https://reports.example.test/long-responses/visual-token/index.html)"
    hosted_path = runner._host_long_response_html.await_args.args[0]
    assert hosted_path.endswith("-visual.html")
    adapter.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_response_hosting_failure_falls_back_to_attachment(monkeypatch, tmp_path):
    runner = _runner()
    runner._host_long_response_html = AsyncMock(return_value=None)
    adapter = SimpleNamespace(send_document=AsyncMock(return_value=SimpleNamespace(success=True)))
    runner.adapters = {Platform.TELEGRAM: adapter}
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        run_mod,
        "_load_gateway_config",
        lambda: {
            "telegram": {
                "long_response_html": {
                    "enabled": True,
                    "threshold_chars": 10,
                    "threshold_lines": 2,
                    "notice": "Attachment fallback used.",
                    "hosting": {
                        "enabled": True,
                        "fallback_to_attachment": True,
                    },
                }
            }
        },
    )

    result = await runner._maybe_deliver_long_telegram_response_as_html(_event(), SAMPLE_RESPONSE)

    assert result == "Attachment fallback used."
    adapter.send_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_hosting_uses_profile_scoped_secrets_and_opaque_https_url(monkeypatch, tmp_path):
    runner = _runner()
    artifact = tmp_path / "response.html"
    artifact.write_text("<p>safe</p>")
    captured = {}

    class FakeClient:
        def upload_file(self, file_path, bucket, object_key, ExtraArgs):
            captured.update(
                file_path=file_path,
                bucket=bucket,
                object_key=object_key,
                extra_args=ExtraArgs,
            )

    def fake_client(*args, **kwargs):
        captured["client_kwargs"] = kwargs
        return FakeClient()

    monkeypatch.setattr(
        lazy_deps,
        "ensure",
        lambda feature, prompt=False: captured.setdefault("ensure_calls", []).append((feature, prompt)),
    )
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_client))
    monkeypatch.setitem(sys.modules, "botocore", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "botocore.client", SimpleNamespace(Config=lambda **kwargs: kwargs))
    token = secret_scope.set_secret_scope({"REPORT_ACCESS": "scoped-user", "REPORT_SECRET": "scoped-secret"})
    try:
        url = await runner._host_long_response_html(
            str(artifact),
            {
                "endpoint_url": "https://objects.example.test",
                "bucket": "reports",
                "public_base_url": "https://reports.example.test",
                "loader_url": "https://reports.example.test/long-responses/loader/index.html",
                "loader_version": "2",
                "key_prefix": "long-responses",
                "access_key_env": "REPORT_ACCESS",
                "secret_key_env": "REPORT_SECRET",
            },
        )
    finally:
        secret_scope.reset_secret_scope(token)

    assert url is not None
    parsed_url = urlparse(url)
    assert parsed_url.scheme == "https"
    assert parsed_url.netloc == "reports.example.test"
    assert parsed_url.path == "/long-responses/loader/index.html"
    assert parse_qs(parsed_url.query) == {"v": ["2"]}
    target_path = parse_qs(parsed_url.fragment)["path"][0]
    assert re.fullmatch(r"/long-responses/[A-Za-z0-9_-]{24}/index\.html", target_path)
    assert re.fullmatch(r"long-responses/[A-Za-z0-9_-]{24}/index\.html", captured["object_key"])
    assert captured["ensure_calls"] == [("platform.telegram.long_response_hosting", False)]
    assert captured["client_kwargs"]["aws_access_key_id"] == "scoped-user"
    assert captured["client_kwargs"]["aws_secret_access_key"] == "scoped-secret"
    assert captured["bucket"] == "reports"
    assert captured["extra_args"] == {
        "ContentType": "text/html; charset=utf-8",
        "CacheControl": "private, no-store",
    }


@pytest.mark.asyncio
async def test_hosting_rejects_non_https_public_url_before_upload(monkeypatch, tmp_path):
    runner = _runner()
    artifact = tmp_path / "response.html"
    artifact.write_text("<p>safe</p>")
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda *args, **kwargs: pytest.fail("must not upload")),
    )
    monkeypatch.setitem(sys.modules, "botocore", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "botocore.client", SimpleNamespace(Config=lambda **kwargs: kwargs))
    token = secret_scope.set_secret_scope({"REPORT_ACCESS": "user", "REPORT_SECRET": "secret"})
    try:
        url = await runner._host_long_response_html(
            str(artifact),
            {
                "endpoint_url": "http://minio.internal",
                "bucket": "reports",
                "public_base_url": "http://reports.example.test",
                "access_key_env": "REPORT_ACCESS",
                "secret_key_env": "REPORT_SECRET",
            },
        )
    finally:
        secret_scope.reset_secret_scope(token)

    assert url is None


@pytest.mark.asyncio
async def test_hosting_rejects_invalid_loader_before_upload(monkeypatch, tmp_path):
    runner = _runner()
    artifact = tmp_path / "response.html"
    artifact.write_text("<p>safe</p>")
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda *args, **kwargs: pytest.fail("must not upload")),
    )
    monkeypatch.setitem(sys.modules, "botocore", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "botocore.client", SimpleNamespace(Config=lambda **kwargs: kwargs))
    token = secret_scope.set_secret_scope({"REPORT_ACCESS": "user", "REPORT_SECRET": "secret"})
    try:
        url = await runner._host_long_response_html(
            str(artifact),
            {
                "endpoint_url": "https://objects.example.test",
                "bucket": "reports",
                "public_base_url": "https://reports.example.test",
                "loader_url": "https://other-origin.example.test/loader.html",
                "loader_version": "invalid version with spaces",
                "access_key_env": "REPORT_ACCESS",
                "secret_key_env": "REPORT_SECRET",
            },
        )
    finally:
        secret_scope.reset_secret_scope(token)

    assert url is None


@pytest.mark.asyncio
async def test_hosting_upload_error_returns_none_for_attachment_fallback(monkeypatch, tmp_path):
    runner = _runner()
    artifact = tmp_path / "response.html"
    artifact.write_text("<p>safe</p>")

    class FailingClient:
        def upload_file(self, *args, **kwargs):
            raise RuntimeError("simulated upload failure")

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *args, **kwargs: FailingClient()))
    monkeypatch.setitem(sys.modules, "botocore", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "botocore.client", SimpleNamespace(Config=lambda **kwargs: kwargs))
    token = secret_scope.set_secret_scope({"REPORT_ACCESS": "user", "REPORT_SECRET": "secret"})
    try:
        url = await runner._host_long_response_html(
            str(artifact),
            {
                "endpoint_url": "https://objects.example.test",
                "bucket": "reports",
                "public_base_url": "https://reports.example.test",
                "access_key_env": "REPORT_ACCESS",
                "secret_key_env": "REPORT_SECRET",
            },
        )
    finally:
        secret_scope.reset_secret_scope(token)

    assert url is None


@pytest.mark.asyncio
async def test_hosting_missing_boto3_returns_none_for_attachment_fallback(monkeypatch, tmp_path):
    runner = _runner()
    artifact = tmp_path / "response.html"
    artifact.write_text("<p>safe</p>")
    real_import = builtins.__import__

    def import_without_boto3(name, *args, **kwargs):
        if name == "boto3":
            raise ImportError("simulated missing boto3")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "boto3", raising=False)
    monkeypatch.setattr(builtins, "__import__", import_without_boto3)
    token = secret_scope.set_secret_scope({"REPORT_ACCESS": "user", "REPORT_SECRET": "secret"})
    try:
        url = await runner._host_long_response_html(
            str(artifact),
            {
                "endpoint_url": "https://objects.example.test",
                "bucket": "reports",
                "public_base_url": "https://reports.example.test",
                "access_key_env": "REPORT_ACCESS",
                "secret_key_env": "REPORT_SECRET",
            },
        )
    finally:
        secret_scope.reset_secret_scope(token)

    assert url is None


def test_long_response_html_escapes_raw_html_and_sets_restrictive_csp(monkeypatch, tmp_path):
    runner = _runner()
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)

    path = runner._write_long_response_html_file(
        "# Safe heading\n\n"
        "> quoted text\n\n"
        "<https://example.com>\n\n"
        "Inline `<span>` code.\n\n"
        "```html\n<div>fenced</div>\n```\n\n"
        "[unsafe](javascript:alert(1))\n\n"
        "<img src=x onerror=alert(1)>\n\n"
        "<script>globalThis.PWNED=1</script>",
        _event(),
        ts="20260713T213500Z",
    )
    html_doc = (tmp_path / "artifacts" / "telegram-long-responses" / path.split("/")[-1]).read_text()

    assert "<script>globalThis.PWNED=1</script>" not in html_doc
    assert "&lt;script&gt;globalThis.PWNED=1&lt;/script&gt;" in html_doc
    assert "<blockquote>" in html_doc and "quoted text" in html_doc
    assert '<a href="https://example.com">https://example.com</a>' in html_doc
    assert "<code>&lt;span&gt;</code>" in html_doc
    assert "<code>&amp;lt;span&amp;gt;</code>" not in html_doc
    assert "<pre><code class=\"language-html\">&lt;div&gt;fenced&lt;/div&gt;" in html_doc
    assert "javascript:" not in html_doc
    assert "onerror" not in html_doc
    assert "Content-Security-Policy" in html_doc
    assert "script-src 'none'" in html_doc
    assert '<meta name="referrer" content="no-referrer">' in html_doc


def test_parse_visual_digest_plan_supports_json_fences():
    raw = """```json
{
  \"title\": \"Architecture\",
  \"summary\": \"Planner chooses the representation.\",
  \"blocks\": [
    {\"type\": \"key_points\", \"items\": [\"A\", \"B\"]}
  ]
}
```"""

    plan = long_html.parse_visual_digest_plan(raw, SAMPLE_RESPONSE)
    assert plan is not None
    assert plan["title"] == "Architecture"
    assert plan["blocks"][0]["type"] == "key_points"


def test_normalize_visual_plan_supports_representation_first_blocks():
    raw = {
        "title": "Execution board",
        "summary": "Visual model of the week.",
        "blocks": [
            {
                "type": "gantt",
                "title": "Week",
                "columns": ["Mon", "Tue", "Wed"],
                "lanes": [
                    {"label": "KTO", "color": "cyan", "segments": [{"start": 0, "end": 2, "label": "Validate"}]}
                ],
            },
            {
                "type": "progress",
                "title": "Completion",
                "items": [{"label": "KTO", "value": 35, "detail": "Demo path"}],
            },
            {
                "type": "kanban",
                "title": "State",
                "columns": [{"title": "Waiting", "items": [{"title": "Prices", "detail": "Waiting on 1C", "tag": "blocked"}]}],
            },
            {
                "type": "priority_matrix",
                "title": "Priority",
                "quadrants": [{"key": "high_high", "title": "Do now", "items": ["KTO demo"]}],
            },
            {
                "type": "dependency_graph",
                "title": "Dependencies",
                "nodes": [{"id": "sensor", "label": "Sensor API", "status": "waiting"}],
                "edges": [{"from": "sensor", "to": "demo", "label": "unblocks"}],
            },
            {
                "type": "flowchart",
                "title": "Exit flow",
                "steps": [{"id": "notify", "title": "Notify team", "detail": "Set date"}],
            },
            {
                "type": "details",
                "title": "Full detail",
                "sections": [{"title": "KTO tasks", "items": ["Server", "Sensors"]}],
            },
        ],
    }

    plan = long_html.normalize_visual_digest_plan(raw, SAMPLE_RESPONSE)

    assert [block["type"] for block in plan["blocks"]] == [
        "gantt", "progress", "kanban", "priority_matrix", "dependency_graph", "flowchart", "details"
    ]
    assert plan["blocks"][0]["lanes"][0]["segments"][0] == {"start": 0, "end": 2, "label": "Validate"}
    assert plan["blocks"][1]["items"][0]["value"] == 35


def test_normalize_visual_plan_supports_manifest_telegram_fallback_types():
    raw = {
        "title": "Fallback parity",
        "summary": "Every advertised Telegram fallback must normalize safely.",
        "blocks": [
            {
                "type": "metric",
                "title": "Revenue",
                "label": "MRR",
                "value": "$12k",
                "trend": {"direction": "up", "label": "+8% month over month"},
            },
            {
                "type": "chart",
                "title": "Channel mix",
                "kind": "bar",
                "data": [
                    {"label": "Search", "value": 42},
                    {"label": "Direct", "value": 27},
                ],
                "valueLabel": "sessions",
            },
            {
                "type": "chart",
                "title": "Budget share",
                "kind": "donut",
                "data": [
                    {"label": "Build", "value": 60},
                    {"label": "Ops", "value": 40},
                ],
                "valueLabel": "%",
            },
            {
                "type": "canvas_network",
                "title": "Team graph",
                "nodes": [
                    {"id": "api", "label": "API", "group": "backend", "x": 10, "y": 20},
                    {"id": "web", "label": "Web", "group": "frontend", "x": 80, "y": 65},
                ],
                "edges": [{"from": "api", "to": "web", "label": "feeds"}],
            },
            {
                "type": "three_scene",
                "title": "Layer map",
                "objects": [
                    {"id": "db", "label": "Database", "size": 3, "position": [0, 0, -2]},
                    {"id": "api", "label": "API service", "size": 2, "position": [1, 2, 1]},
                ],
            },
        ],
    }

    plan = long_html.normalize_visual_digest_plan(raw, SAMPLE_RESPONSE)

    assert [block["type"] for block in plan["blocks"]] == [
        "metric",
        "chart",
        "chart",
        "canvas_network",
        "three_scene",
    ]
    assert plan["blocks"][0]["trend"] == {"direction": "up", "label": "+8% month over month"}
    assert plan["blocks"][1]["kind"] == "bar"
    assert plan["blocks"][2]["kind"] == "donut"
    assert plan["blocks"][3]["nodes"][0]["x"] == 10
    assert plan["blocks"][4]["objects"][1]["position"] == [1, 2, 1]


def test_write_visual_digest_html_file_persists_latest_report(monkeypatch, tmp_path):
    runner = _runner()
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    import gateway.visual_report_store as report_store
    monkeypatch.setattr(report_store, "get_hermes_home", lambda: tmp_path)
    plan = long_html.normalize_visual_digest_plan({
        "title": "Fallback parity",
        "summary": "Static fallbacks preserve the meaning without requiring scripts or canvas.",
        "blocks": [
            {"type": "metric", "title": "Revenue", "label": "MRR", "value": "$12k", "trend": {"direction": "up", "label": "+8%"}},
            {"type": "chart", "title": "Channel mix", "kind": "bar", "data": [{"label": "Search", "value": 42}, {"label": "Direct", "value": 27}], "valueLabel": "sessions"},
            {"type": "chart", "title": "Budget share", "kind": "donut", "data": [{"label": "Build", "value": 60}, {"label": "Ops", "value": 40}], "valueLabel": "%"},
            {"type": "canvas_network", "title": "Team graph", "nodes": [{"id": "api", "label": "API", "x": 10, "y": 20}, {"id": "web", "label": "Web", "x": 80, "y": 65}], "edges": [{"from": "api", "to": "web", "label": "feeds"}]},
            {"type": "three_scene", "title": "Layer map", "objects": [{"id": "db", "label": "Database", "size": 3, "position": [0, 0, -2]}, {"id": "api", "label": "API service", "size": 2, "position": [1, 2, 1]}]},
        ],
    }, SAMPLE_RESPONSE)

    path = runner._write_visual_digest_html_file(SAMPLE_RESPONSE, _event(), plan=plan, ts="20260709T202606Z")
    html_doc = open(path, encoding="utf-8").read()

    for marker in ["metric-tile", "chart-fallback chart-bar", "chart-fallback chart-donut", "canvas-network-fallback", "three-scene-fallback"]:
        assert marker in html_doc
    for readable in ["MRR", "$12k", "+8%", "Search", "42 sessions", "Build", "60%", "API", "feeds", "Database", "position 0, 0, -2"]:
        assert readable in html_doc
    assert "<canvas" not in html_doc.lower()
    assert "webgl" not in html_doc.lower()

    latest = report_store.load_latest_report()
    assert latest is not None
    assert latest["plan"]["title"] == "Fallback parity"
    assert latest["source"]["text"] == SAMPLE_RESPONSE
    assert latest["context"]["chat_id"] == "289310951"
    assert latest["context"]["thread_id"] == "main"
    assert latest["context"]["topic"] == "Home"


def test_manifest_telegram_fallback_types_are_normalized_from_minimal_examples():
    examples = {
        "metric": {"type": "metric", "title": "Metric", "label": "Status", "value": "Green"},
        "progress": {"type": "progress", "title": "Progress", "items": [{"label": "Done", "value": 50}]},
        "timeline": {"type": "timeline", "title": "Timeline", "items": [{"label": "Now", "title": "Ship"}]},
        "gantt": {"type": "gantt", "title": "Gantt", "columns": ["Mon"], "lanes": [{"label": "Work", "segments": [{"start": 0, "end": 1, "label": "Ship"}]}]},
        "kanban": {"type": "kanban", "title": "Kanban", "columns": [{"title": "Doing", "cards": [{"title": "Ship"}]}]},
        "priority_matrix": {"type": "priority_matrix", "title": "Matrix", "quadrants": [{"key": "high_high", "title": "Do", "items": ["Ship"]}]},
        "dependency_graph": {"type": "dependency_graph", "title": "Graph", "nodes": [{"id": "a", "label": "A"}], "edges": []},
        "flow": {"type": "flow", "title": "Flow", "steps": [{"id": "s", "label": "Ship"}]},
        "comparison_table": {"type": "comparison_table", "title": "Compare", "columns": ["Option"], "rows": [{"label": "A", "values": []}]},
        "chart": {"type": "chart", "title": "Chart", "kind": "bar", "data": [{"label": "A", "value": 1}]},
        "canvas_network": {"type": "canvas_network", "title": "Network", "nodes": [{"id": "a", "label": "A", "x": 0, "y": 0}], "edges": []},
        "three_scene": {"type": "three_scene", "title": "Scene", "objects": [{"id": "a", "label": "A", "size": 1, "position": [0, 0, 0]}]},
        "details": {"type": "details", "title": "Details", "sections": [{"title": "Facts", "content": ["Ship"]}]},
    }
    manifest_types = {
        entry["type"]
        for entry in long_html.load_visual_report_registry_manifest_for_prompt()
        if entry["supportsTelegramFallback"]
    }

    assert manifest_types == set(examples)
    for component_type, block in examples.items():
        plan = long_html.normalize_visual_digest_plan({"blocks": [block]}, SAMPLE_RESPONSE)
        assert plan is not None, component_type
        assert plan["blocks"][0]["type"] in {component_type, "flowchart"}


def test_write_visual_digest_html_file_renders_representation_first_blocks(monkeypatch, tmp_path):
    runner = _runner()
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    plan = long_html.normalize_visual_digest_plan({
        "title": "Execution board",
        "summary": "Visual model of the week.",
        "blocks": [
            {"type": "gantt", "title": "Week", "columns": ["Mon", "Tue"], "lanes": [{"label": "KTO", "segments": [{"start": 0, "end": 1, "label": "Server"}]}]},
            {"type": "progress", "title": "Progress", "items": [{"label": "KTO", "value": 35}]},
            {"type": "kanban", "title": "Board", "columns": [{"title": "Waiting", "items": [{"title": "1C prices"}]}]},
            {"type": "priority_matrix", "title": "Matrix", "quadrants": [{"key": "high_high", "title": "Do now", "items": ["KTO demo"]}]},
            {"type": "dependency_graph", "title": "Graph", "nodes": [{"id": "a", "label": "Sensor API"}, {"id": "b", "label": "Demo"}], "edges": [{"from": "a", "to": "b"}]},
            {"type": "flowchart", "title": "Exit", "steps": [{"id": "one", "title": "Notify"}, {"id": "two", "title": "Transfer"}]},
            {"type": "details", "title": "All tasks", "sections": [{"title": "KTO", "items": ["Server", "Sensors"]}]},
        ],
    }, SAMPLE_RESPONSE)

    path = runner._write_visual_digest_html_file(SAMPLE_RESPONSE, _event(), plan=plan, ts="20260709T202605Z")
    html_doc = open(path, encoding="utf-8").read()

    for marker in ["visual-gantt", "progress-ring", "kanban-board", "priority-matrix", "dependency-graph", "visual-flow", "detail-sections"]:
        assert marker in html_doc
    assert "<details class=\"full-body\">" in html_doc
    assert "<section class=\"panel full-body\">" not in html_doc


def test_visual_planner_prompt_requires_representation_before_layout():
    runner = _runner()
    messages = runner._build_visual_digest_planner_messages(_event(), SAMPLE_RESPONSE)
    prompt = "\n".join(message["content"] for message in messages)

    assert "gantt" in prompt
    assert "priority_matrix" in prompt
    assert "dependency_graph" in prompt
    assert "representation" in prompt.lower()
    assert "Do not default to hero" in prompt
    assert "flatten component-specific fields" in prompt
    assert '"payload"' not in prompt


def test_visual_planner_prompt_uses_loaded_registry_manifest(monkeypatch):
    runner = _runner()
    monkeypatch.setattr(
        run_mod,
        "_load_visual_report_registry_manifest_for_prompt",
        lambda: [
            {
                "type": "custom_swimlane",
                "label": "Custom swimlane",
                "description": "Temporary injected test type.",
                "rendererMode": "telegram-fallback",
                "supportsTelegramFallback": True,
                "accessibilitySummary": "Rows and cards remain readable as text.",
                "dataShape": "{ lanes: [{ label, cards: [{ title }] }] }",
                "selectionGuidance": "Use for custom test state lanes.",
            }
        ],
    )

    messages = runner._build_visual_digest_planner_messages(_event(), SAMPLE_RESPONSE)
    prompt = "\n".join(message["content"] for message in messages)

    assert "custom_swimlane" in prompt
    assert "Temporary injected test type" in prompt
    assert "only select registered visual report component types" in prompt


def test_visual_report_registry_manifest_loader_reads_json():
    manifest = long_html.load_visual_report_registry_manifest_for_prompt()
    types = {entry["type"] for entry in manifest}

    assert {"metric", "progress", "timeline", "gantt", "kanban", "details"}.issubset(types)
    for entry in manifest:
        assert set(entry) == {
            "type",
            "label",
            "description",
            "rendererMode",
            "supportsTelegramFallback",
            "accessibilitySummary",
            "dataShape",
            "selectionGuidance",
        }
        assert len(entry["description"]) <= 220


def test_write_visual_digest_html_file_creates_planner_based_artifact(monkeypatch, tmp_path):
    runner = _runner()
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)

    path = runner._write_visual_digest_html_file(
        SAMPLE_RESPONSE,
        _event(),
        plan=SAMPLE_PLAN,
        ts="20260709T202604Z",
    )

    html_doc = (tmp_path / "artifacts" / "telegram-long-responses" / "response-289310951-main-20260709T202604Z-visual.html").read_text()
    assert path.endswith("-visual.html")
    assert "Visual digest · Hermes" in html_doc
    assert "Long-response delivery redesign" in html_doc
    assert "Why this matters" in html_doc
    assert "Planner-first flow" in html_doc
    assert "How this was made." in html_doc


@pytest.mark.asyncio
async def test_long_response_delivery_sends_visual_then_raw(monkeypatch, tmp_path):
    runner = _runner()
    runner._plan_visual_digest = AsyncMock(return_value=SAMPLE_PLAN)
    adapter = SimpleNamespace(send_document=AsyncMock(side_effect=[
        SimpleNamespace(success=True),
        SimpleNamespace(success=True),
    ]))
    runner.adapters = {Platform.TELEGRAM: adapter}
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        run_mod,
        "_load_gateway_config",
        lambda: {
            "telegram": {
                "long_response_html": {
                    "enabled": True,
                    "threshold_chars": 10,
                    "threshold_lines": 2,
                    "visual_digest": {
                        "enabled": True,
                        "caption": "digest",
                        "send_raw_html": True,
                    },
                }
            }
        },
    )

    result = await runner._maybe_deliver_long_telegram_response_as_html(_event(), SAMPLE_RESPONSE)

    assert result == "Visual digest and full response are attached as HTML files."
    assert adapter.send_document.await_count == 2
    first = adapter.send_document.await_args_list[0].kwargs
    second = adapter.send_document.await_args_list[1].kwargs
    assert first["file_name"].endswith("-visual.html")
    assert second["file_name"].endswith(".html") and not second["file_name"].endswith("-visual.html")


@pytest.mark.asyncio
async def test_long_response_delivery_can_send_visual_only(monkeypatch, tmp_path):
    runner = _runner()
    runner._plan_visual_digest = AsyncMock(return_value=SAMPLE_PLAN)
    adapter = SimpleNamespace(send_document=AsyncMock(return_value=SimpleNamespace(success=True)))
    runner.adapters = {Platform.TELEGRAM: adapter}
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        run_mod,
        "_load_gateway_config",
        lambda: {
            "telegram": {
                "long_response_html": {
                    "enabled": True,
                    "threshold_chars": 10,
                    "threshold_lines": 2,
                    "visual_digest": {
                        "enabled": True,
                        "caption": "digest",
                        "send_raw_html": False,
                    },
                }
            }
        },
    )

    result = await runner._maybe_deliver_long_telegram_response_as_html(_event(), SAMPLE_RESPONSE)

    assert result == "Visual digest is attached as an HTML file."
    assert adapter.send_document.await_count == 1
    only_call = adapter.send_document.await_args.kwargs
    assert only_call["file_name"].endswith("-visual.html")


@pytest.mark.asyncio
async def test_long_response_delivery_falls_back_to_raw_when_planner_has_no_plan(monkeypatch, tmp_path):
    runner = _runner()
    runner._plan_visual_digest = AsyncMock(return_value=None)
    adapter = SimpleNamespace(send_document=AsyncMock(return_value=SimpleNamespace(success=True)))
    runner.adapters = {Platform.TELEGRAM: adapter}
    monkeypatch.setattr(long_html, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        run_mod,
        "_load_gateway_config",
        lambda: {
            "telegram": {
                "long_response_html": {
                    "enabled": True,
                    "threshold_chars": 10,
                    "threshold_lines": 2,
                    "notice": "Full response is attached as an HTML file.",
                    "caption": "raw",
                    "visual_digest": {
                        "enabled": True,
                        "caption": "digest",
                        "send_raw_html": False,
                    },
                }
            }
        },
    )

    result = await runner._maybe_deliver_long_telegram_response_as_html(_event(), SAMPLE_RESPONSE)

    assert result == "Full response is attached as an HTML file."
    assert adapter.send_document.await_count == 1
    only_call = adapter.send_document.await_args.kwargs
    assert only_call["file_name"].endswith(".html")
    assert not only_call["file_name"].endswith("-visual.html")
