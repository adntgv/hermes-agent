from types import SimpleNamespace

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionSource, build_session_context


def test_session_context_can_be_enriched_by_plugin(monkeypatch):
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-10042",
        chat_type="group",
        user_id="289",
        thread_id="143",
    )
    config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True)})
    seen = {}

    def _hook(name, **kwargs):
        seen["name"] = name
        seen["source"] = kwargs["source"]
        return [{"topic_context": "plugin-owned topic context"}]

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", _hook)

    context = build_session_context(source, config, SimpleNamespace(
        session_key="k", session_id="s", created_at=None, updated_at=None
    ))

    assert seen == {"name": "enrich_gateway_session_context", "source": source}
    assert context.topic_context == "plugin-owned topic context"
