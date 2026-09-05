from pathlib import Path
from unittest.mock import MagicMock

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.session import SessionSource
from gateway.telegram_topic_models import TelegramTopicModelStore
from hermes_cli.commands import resolve_command


def test_topic_model_store_is_profile_local_and_topic_scoped(tmp_path: Path):
    path = tmp_path / "gateway" / "telegram_topic_models.json"
    store = TelegramTopicModelStore(path)

    stored = store.set(
        "-1003906782054",
        "296",
        {
            "model": "qwen3-6",
            "provider": "alem",
            "base_url": "https://llm.alem.ai/v1",
            "api_key": "must-not-persist",
        },
    )

    assert stored == {
        "model": "qwen3-6",
        "provider": "alem",
        "base_url": "https://llm.alem.ai/v1",
    }
    assert store.get("-1003906782054", "296") == stored
    assert store.get("-1003906782054", "12237") is None
    assert "must-not-persist" not in path.read_text(encoding="utf-8")


def test_topic_model_store_clear_is_idempotent(tmp_path: Path):
    store = TelegramTopicModelStore(tmp_path / "models.json")
    assert store.clear("chat", "thread") is False
    store.set("chat", "thread", {"model": "gpt-test"})
    assert store.clear("chat", "thread") is True
    assert store.clear("chat", "thread") is False


def test_topic_command_is_gateway_resolvable():
    command = resolve_command("topic")
    assert command is not None
    assert "model" in command.args_hint


def test_forum_topic_source_has_thread_identity():
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-1003906782054",
        chat_type="group",
        thread_id="296",
    )
    assert source.thread_id == "296"


def test_topic_model_override_wins_over_session_override(tmp_path, monkeypatch):
    from gateway.config import GatewayConfig, PlatformConfig
    from gateway.run import GatewayRunner

    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-1003906782054",
        chat_type="group",
        thread_id="296",
    )
    store = TelegramTopicModelStore(tmp_path / "models.json")
    store.set(source.chat_id, source.thread_id, {"model": "topic-model", "provider": "topic-provider"})
    monkeypatch.setattr(
        "gateway.telegram_topic_models.get_telegram_topic_model_store",
        lambda: store,
    )
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda _cfg: "global-model")
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {"provider": "global-provider", "api_key": "global-key"},
    )
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs_for_provider",
        lambda provider: {"provider": provider, "api_key": f"{provider}-key", "model": "ignored"},
    )

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="tok")}
    )
    runner._session_model_overrides = {
        runner._session_key_for_source(source): {
            "model": "session-model",
            "provider": "session-provider",
            "api_key": "session-key",
        }
    }
    runner._last_resolved_model = {}
    runner.session_store = MagicMock()
    runner.session_store.get_model_override.return_value = None

    model, runtime = runner._resolve_session_agent_runtime(source=source)

    assert model == "topic-model"
    assert runtime["provider"] == "topic-provider"
    assert runtime["api_key"] == "topic-provider-key"
