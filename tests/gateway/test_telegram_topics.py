"""Tests for Telegram forum topic registry and topic-scoped context."""

from types import SimpleNamespace

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import (
    SessionEntry,
    SessionSource,
    build_session_context,
    build_session_context_prompt,
)


def test_topic_registry_persists_label_purpose_and_open_loops(tmp_path, monkeypatch):
    """Topic records survive reloads and keep compact topic memory."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.telegram_topics import TelegramTopicRegistry

    registry = TelegramTopicRegistry()
    registry.record_topic(
        chat_id="-100123",
        thread_id="296",
        chat_title="horkspace",
        title="Hermes platform docs",
        purpose_summary="Design native Telegram topic memory for Hermes.",
        source="manual",
    )
    registry.update_topic_memory(
        chat_id="-100123",
        thread_id="296",
        pinned_facts=["Old Telegram history is out of scope."],
        open_loops=["Implement JSON topic registry."],
    )

    reloaded = TelegramTopicRegistry()
    record = reloaded.get_topic("-100123", "296")

    assert record is not None
    assert record["title"] == "Hermes platform docs"
    assert record["purpose_summary"] == "Design native Telegram topic memory for Hermes."
    assert record["pinned_facts"] == ["Old Telegram history is out of scope."]
    assert record["open_loops"] == ["Implement JSON topic registry."]


def test_topic_registry_audits_sessions_json_for_missing_topics(tmp_path, monkeypatch):
    """Historical Telegram group topics from sessions.json can be backfilled into the registry."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    import json
    from datetime import datetime

    from gateway.telegram_topics import TelegramTopicRegistry

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    sessions_file = sessions_dir / "sessions.json"
    now = datetime.now().isoformat()
    sessions_file.write_text(
        json.dumps(
            {
                "agent:main:telegram:group:-100123:296": {
                    "session_key": "agent:main:telegram:group:-100123:296",
                    "session_id": "20260505_topic_296",
                    "created_at": now,
                    "updated_at": now,
                    "platform": "telegram",
                    "chat_type": "group",
                    "origin": {
                        "platform": "telegram",
                        "chat_id": "-100123",
                        "chat_name": "horkspace",
                        "chat_type": "group",
                        "user_id": "42",
                        "user_name": "Aidyn",
                        "thread_id": "296",
                        "chat_topic": "Hermes platform docs",
                    },
                },
                "agent:main:telegram:dm:42": {
                    "session_key": "agent:main:telegram:dm:42",
                    "session_id": "dm",
                    "created_at": now,
                    "updated_at": now,
                    "platform": "telegram",
                    "chat_type": "dm",
                    "origin": {
                        "platform": "telegram",
                        "chat_id": "42",
                        "chat_type": "dm",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    registry = TelegramTopicRegistry()
    result = registry.audit_sessions_file(sessions_file)
    topic = registry.get_topic("-100123", "296")

    assert result == {"scanned": 2, "eligible": 1, "created": 1, "updated": 0, "skipped": 1}
    assert topic is not None
    assert topic["title"] == "Hermes platform docs"
    assert topic["latest_session_key"] == "agent:main:telegram:group:-100123:296"
    assert topic["latest_session_id"] == "20260505_topic_296"
    assert topic["source"] == "sessions_audit"

    result = registry.audit_sessions_file(sessions_file)
    assert result["created"] == 0
    assert result["updated"] == 1


def test_telegram_topic_memory_is_injected_into_session_prompt(tmp_path, monkeypatch):
    """Current Telegram topic gets its own registry summary in the system context."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.telegram_topics import TelegramTopicRegistry

    TelegramTopicRegistry().record_topic(
        chat_id="-100123",
        thread_id="296",
        chat_title="horkspace",
        title="Hermes platform docs",
        purpose_summary="Design native Telegram topic memory for Hermes.",
        pinned_facts=["Old Telegram history is out of scope."],
        open_loops=["Add /topic command."],
        source="manual",
    )

    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-100123",
        chat_name="horkspace",
        chat_type="group",
        user_id="42",
        user_name="Aidyn",
        thread_id="296",
    )
    entry = SessionEntry(
        session_key="agent:main:telegram:group:-100123:296",
        session_id="20260505_topic",
        created_at=__import__("datetime").datetime.now(),
        updated_at=__import__("datetime").datetime.now(),
    )
    config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="fake")},
        thread_sessions_per_user=False,
    )

    prompt = build_session_context_prompt(build_session_context(source, config, entry))

    assert "**Telegram group topic:** horkspace / Hermes platform docs" in prompt
    assert "**Topic ID:** 296" in prompt
    assert "Design native Telegram topic memory for Hermes." in prompt
    assert "Old Telegram history is out of scope." in prompt
    assert "Add /topic command." in prompt


def test_telegram_adapter_discovers_group_topic_into_registry(tmp_path, monkeypatch):
    """Building a Telegram forum MessageEvent records the topic lane for future turns."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.platforms import telegram as telegram_mod
    from gateway.platforms.telegram import TelegramAdapter
    from gateway.telegram_topics import TelegramTopicRegistry

    config = PlatformConfig(
        enabled=True,
        token="fake",
        extra={
            "group_topics": [
                {
                    "chat_id": "-100123",
                    "topics": [
                        {
                            "thread_id": "296",
                            "name": "Hermes platform docs",
                            "skill": "hermes-agent",
                        }
                    ],
                }
            ]
        },
    )
    adapter = object.__new__(TelegramAdapter)
    adapter.config = config
    adapter._config = config
    adapter._platform = Platform.TELEGRAM
    adapter.platform = Platform.TELEGRAM
    adapter._dm_topics = {}
    adapter._dm_topics_config = []

    message = SimpleNamespace(
        text="let's design topic memory",
        caption=None,
        chat=SimpleNamespace(
            id=-100123,
            type=telegram_mod.ChatType.SUPERGROUP,
            is_forum=True,
            title="horkspace",
        ),
        from_user=SimpleNamespace(id=42, full_name="Aidyn"),
        message_thread_id=296,
        reply_to_message=None,
        message_id=10,
        date=None,
        forum_topic_created=None,
        forum_topic_edited=None,
        forum_topic_closed=None,
        forum_topic_reopened=None,
    )

    event = adapter._build_message_event(message, msg_type=SimpleNamespace(value="text"))
    record = TelegramTopicRegistry().get_topic("-100123", "296")

    assert event.source.chat_topic == "Hermes platform docs"
    assert event.auto_skill == "hermes-agent"
    assert record is not None
    assert record["title"] == "Hermes platform docs"
    assert record["latest_message_id"] == "10"


def test_topic_command_set_updates_current_topic(tmp_path, monkeypatch):
    """/topic set lets users manually label and describe the current Telegram topic."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.run import GatewayRunner
    from gateway.telegram_topics import TelegramTopicRegistry

    runner = object.__new__(GatewayRunner)
    event = MessageEvent(
        text="/topic set Hermes platform docs :: Native Telegram group/topic memory from now on",
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="-100123",
            chat_name="horkspace",
            chat_type="group",
            user_id="42",
            user_name="Aidyn",
            thread_id="296",
        ),
        message_id="11",
    )

    response = __import__("asyncio").run(runner._handle_topic_command(event))
    record = TelegramTopicRegistry().get_topic("-100123", "296")

    assert "Updated topic" in response
    assert record["title"] == "Hermes platform docs"
    assert record["purpose_summary"] == "Native Telegram group/topic memory from now on"


def test_registry_applies_structured_topic_memory_delta(tmp_path, monkeypatch):
    """Topic memory compaction merges structured purpose/fact/loop deltas safely."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.telegram_topics import TelegramTopicRegistry

    registry = TelegramTopicRegistry()
    registry.record_topic(
        chat_id="-100123",
        thread_id="296",
        title="Hermes platform docs",
        purpose_summary="Initial purpose",
        pinned_facts=["Existing fact"],
        open_loops=["Existing loop"],
    )

    updated = registry.apply_memory_delta(
        chat_id="-100123",
        thread_id="296",
        delta={
            "purpose_summary": "Design native Telegram group topic support.",
            "pinned_facts": ["Existing fact", "Thread 296 is about Hermes Telegram adapter work."],
            "open_loops": ["Existing loop", "Ship /topic skills command."],
            "decisions": ["Enhance built-in Telegram adapter instead of making a duplicate plugin."],
        },
        compacted_message_count=9,
    )

    assert updated["purpose_summary"] == "Design native Telegram group topic support."
    assert updated["pinned_facts"] == [
        "Existing fact",
        "Thread 296 is about Hermes Telegram adapter work.",
        "Decision: Enhance built-in Telegram adapter instead of making a duplicate plugin.",
    ]
    assert updated["open_loops"] == ["Existing loop", "Ship /topic skills command."]
    assert updated["last_compacted_message_count"] == 9


def test_build_topic_memory_update_prompt_is_topic_scoped(tmp_path, monkeypatch):
    """The summarization prompt includes only the current topic transcript and current topic memory."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.telegram_topics import TelegramTopicRegistry, build_topic_memory_update_prompt

    registry = TelegramTopicRegistry()
    registry.record_topic(
        chat_id="-100123",
        thread_id="296",
        title="Hermes platform docs",
        purpose_summary="Design native Telegram topic memory.",
        pinned_facts=["Current-topic fact"],
    )
    registry.record_topic(
        chat_id="-100123",
        thread_id="137",
        title="Unrelated",
        purpose_summary="Unrelated topic purpose must not leak.",
        pinned_facts=["Other-topic fact"],
    )

    prompt = build_topic_memory_update_prompt(
        registry=registry,
        chat_id="-100123",
        thread_id="296",
        transcript=[
            {"role": "user", "content": "We decided to enhance the built-in Telegram adapter."},
            {"role": "assistant", "content": "Next open loop: implement /topic skills."},
        ],
    )

    assert "Hermes platform docs" in prompt
    assert "Current-topic fact" in prompt
    assert "enhance the built-in Telegram adapter" in prompt
    assert "Unrelated topic purpose" not in prompt
    assert "Other-topic fact" not in prompt
    assert '"purpose_summary"' in prompt
    assert '"pinned_facts"' in prompt
    assert '"open_loops"' in prompt


def test_topic_command_skills_and_memory_subcommands(tmp_path, monkeypatch):
    """/topic skills binds auto-loaded skills and /topic memory shows compact memory only."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.run import GatewayRunner
    from gateway.telegram_topics import TelegramTopicRegistry

    runner = object.__new__(GatewayRunner)
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-100123",
        chat_name="horkspace",
        chat_type="group",
        user_id="42",
        user_name="Aidyn",
        thread_id="296",
    )
    event = MessageEvent(
        text="/topic skills hermes-agent, test-driven-development",
        message_type=MessageType.TEXT,
        source=source,
        message_id="12",
    )

    response = __import__("asyncio").run(runner._handle_topic_command(event))
    record = TelegramTopicRegistry().get_topic("-100123", "296")

    assert "Updated topic skills" in response
    assert record["auto_skills"] == ["hermes-agent", "test-driven-development"]

    TelegramTopicRegistry().update_topic_memory(
        chat_id="-100123",
        thread_id="296",
        purpose_summary="Design topic memory.",
        pinned_facts=["Fact A"],
        open_loops=["Loop B"],
    )
    event.text = "/topic memory"
    response = __import__("asyncio").run(runner._handle_topic_command(event))

    assert "Design topic memory." in response
    assert "Fact A" in response
    assert "Loop B" in response


def test_topics_alias_lists_known_group_topics(tmp_path, monkeypatch):
    """/topics is a convenience alias for listing known topics in the current group."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.run import GatewayRunner
    from gateway.telegram_topics import TelegramTopicRegistry

    registry = TelegramTopicRegistry()
    registry.record_topic(chat_id="-100123", thread_id="296", title="Hermes platform docs")
    registry.record_topic(chat_id="-100123", thread_id="137", title="Strategy")

    runner = object.__new__(GatewayRunner)
    event = MessageEvent(
        text="/topics",
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="-100123",
            chat_name="horkspace",
            chat_type="group",
            user_id="42",
            user_name="Aidyn",
            thread_id="296",
        ),
    )

    response = __import__("asyncio").run(runner._handle_topic_command(event))

    assert "Known topics" in response
    assert "Hermes platform docs" in response
    assert "Strategy" in response


def test_registry_auto_skills_merge_with_event_auto_skill(tmp_path, monkeypatch):
    """Topic-bound skills persisted in the registry are available for auto-load next turn."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from gateway.telegram_topics import TelegramTopicRegistry, merge_topic_auto_skills

    TelegramTopicRegistry().record_topic(
        chat_id="-100123",
        thread_id="296",
        auto_skills=["hermes-agent", "test-driven-development"],
    )

    merged = merge_topic_auto_skills(
        chat_id="-100123",
        thread_id="296",
        event_auto_skill="hermes-agent",
    )

    assert merged == ["hermes-agent", "test-driven-development"]
