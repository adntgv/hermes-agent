from unittest.mock import patch

from run_agent import AIAgent


def test_agent_reads_model_max_tokens_from_config_when_not_explicit():
    cfg = {
        "model": {
            "default": "qwen3-6",
            "provider": "alem",
            "context_length": 262144,
            "max_tokens": 81920,
        },
        "agent": {},
    }

    with (
        patch("hermes_cli.config.load_config_readonly", return_value=cfg),
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.model_metadata.get_model_context_length", return_value=262144),
    ):
        agent = AIAgent(model="qwen3-6", provider="custom", base_url="https://llm.alem.ai/v1", api_key="sk-test", quiet_mode=True)

    assert agent.max_tokens == 81920


def test_explicit_max_tokens_overrides_config():
    cfg = {
        "model": {
            "default": "qwen3-6",
            "provider": "alem",
            "context_length": 262144,
            "max_tokens": 81920,
        },
        "agent": {},
    }

    with (
        patch("hermes_cli.config.load_config_readonly", return_value=cfg),
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.model_metadata.get_model_context_length", return_value=262144),
    ):
        agent = AIAgent(model="qwen3-6", provider="custom", base_url="https://llm.alem.ai/v1", api_key="sk-test", max_tokens=1234, quiet_mode=True)

    assert agent.max_tokens == 1234
