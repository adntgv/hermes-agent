# Telegram Workspace Plugin Extraction Implementation Plan

> **For Hermes:** Execute incrementally with strict RED → GREEN → REFACTOR. Sol owns architecture and acceptance; GPT-5.6 Terra/Luna workers may implement or review bounded slices.

**Goal:** Move Aidyn-specific Telegram topic registry, commands, context, and DM-to-topic workspace routing out of Hermes core into an independently installable plugin while preserving Telegram transport/session behavior.

**Architecture:** Keep Telegram transport, `SessionSource.thread_id`, session-key isolation, authorization, and outbound thread propagation in core. Add only generic, tested plugin seams: an async post-authorization dispatch hook, a restricted send/run-turn facade, ephemeral per-turn context contributions, and context-aware gateway commands. Install Aidyn behavior as a standalone plugin outside the Hermes source tree.

**Tech stack:** Python 3.11+, pytest, Hermes Python plugin API, python-telegram-bot adapter, JSON profile-local state.

**Source:** https://hermes-agent.nousresearch.com/docs/developer-guide/plugins

---

## Non-goals

- Do not replace or subclass the full Telegram adapter.
- Do not change Telegram Bot API polling, media, retry, typing, auth, or General-topic behavior.
- Do not redesign registry/ledger storage while extracting it.
- Do not activate dormant topic compaction in the behavior-preserving phase.
- Do not move rich HTML/visual-report delivery, miniapp UI, Kazakh subtitles, or Alem provider behavior into this plugin.

## Invariants

- Existing Telegram group/topic session keys remain unchanged.
- Existing DM topic mode remains unchanged and separate from workspace routing.
- Authorization runs before custom workspace routing.
- Internal events never recursively re-enter custom routing.
- Disabled or broken plugin fails open to standard Hermes behavior.
- Topic A context never appears in Topic B.
- Plugin context is ephemeral user-turn context, not mutable system-prompt state.
- Existing registry and ledger JSON paths remain readable during migration.

## Phase 0 — Characterization and development isolation

### Task 0.1: Create isolated worktree

**Status:** Complete.

**Path:** `/root/.hermes/worktrees/telegram-workspace-plugin`

**Branch:** `refactor/telegram-workspace-plugin`

### Task 0.2: Freeze current DM routing behavior

**Files:**
- Modify: `tests/gateway/test_dm_topic_router_gateway.py`
- Modify when needed: `tests/gateway/test_dm_topic_router.py`
- Modify when needed: `tests/gateway/test_dm_topic_route_ledger.py`

**Acceptance criteria:**
- Authorized qualifying DM routes exactly once.
- Target agent turn uses destination chat/thread source.
- Duplicate origin does not resend or rerun.
- Send failure does not run target agent.
- Unauthorized/internal/group/thread events bypass router.
- Plugin-disabled path remains ordinary gateway behavior.

**Verification:**
```bash
python -m pytest tests/gateway/test_dm_topic_router.py tests/gateway/test_dm_topic_route_ledger.py tests/gateway/test_dm_topic_router_gateway.py -q -o 'addopts='
```

## Phase 1 — Generic async post-auth dispatch seam

### Task 1.1: Add async plugin-hook invocation

**Files:**
- Test: `tests/hermes_cli/test_plugins.py`
- Modify: `hermes_cli/plugins.py`

**RED:** Add tests proving async callbacks are awaited, sync callbacks still work, exceptions fail open, and registration order is deterministic.

**GREEN:** Add `PluginManager.ainvoke_hook()` and module-level `ainvoke_hook()` without modifying synchronous `invoke_hook()` semantics.

**Verification:**
```bash
python -m pytest tests/hermes_cli/test_plugins.py -q -o 'addopts='
```

### Task 1.2: Add restricted gateway dispatch contracts

**Files:**
- Create: `gateway/plugin_dispatch.py`
- Test: `tests/gateway/test_plugin_dispatch.py`

**Contracts:**
- `GatewayDispatchRequest`
- `GatewayDispatchDecision`
- `GatewayAgentTurnResult`
- `GatewayDispatchServices` protocol/facade

**Acceptance criteria:**
- Plugins can send through the source-selected adapter.
- Plugins can request exactly one agent turn through core-owned session/run-generation logic.
- No adapter map, GatewayRunner internals, config object, or unrestricted runner object is exposed.

### Task 1.3: Invoke the new hook after authorization

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_plugin_dispatch.py`

**Hook:** `post_gateway_auth_dispatch`

**Acceptance criteria:**
- Runs after authorization and before ordinary command/session/agent handling.
- Does not run for internal events.
- First valid handled decision wins.
- Invalid results and hook failures fail open.
- Handled response returns through existing outer delivery path.

**Checkpoint verification:**
```bash
python -m pytest tests/hermes_cli/test_plugins.py tests/gateway/test_plugin_dispatch.py tests/gateway/test_dm_topic_router_gateway.py -q -o 'addopts='
```

## Phase 2 — Standalone DM workspace router plugin

### Task 2.1: Create standalone plugin repository

**Repository:** `/root/workspace/hermes-plugins/telegram-workspace`

**Files:**
- `plugin.yaml`
- `__init__.py`
- `config.py`
- `models.py`
- `routing.py`
- `route_ledger.py`
- `packets.py`
- `dispatch.py`
- `tests/`

**Acceptance criteria:**
- Plugin is disabled until explicitly enabled.
- No Aidyn identity, chat ID, topic ID, or secret is hardcoded in source.
- Existing config and ledger formats remain readable.

### Task 2.2: Move pure router logic

**Source:** `gateway/dm_topic_router.py`

**Acceptance criteria:**
- Existing pure config/routing/packet/ledger tests pass against plugin modules.
- General topic is never selected.
- Semantic selection validates returned thread IDs against registry candidates.
- Raw exception details are redacted before user-facing failure messages.
- `ack_dm` and `mirror_intake` are explicitly honored or documented as compatibility behavior.

### Task 2.3: Move gateway integration into plugin hook

**Acceptance criteria:**
- Uses only the new dispatch request/services API.
- Existing visible intake, route ID, topic execution, final delivery, and idempotency behavior is preserved.
- Plugin failure fails open.
- No import of `gateway.dm_topic_router` remains in `gateway/run.py`.

**Verification:**
```bash
python -m pytest /root/workspace/hermes-plugins/telegram-workspace/tests -q -o 'addopts='
python -m pytest tests/gateway/test_plugin_dispatch.py tests/gateway/test_dm_topic_router_gateway.py -q -o 'addopts='
```

## Phase 3 — Topic registry ownership

### Task 3.1: Move registry implementation

**Source:** `gateway/telegram_topics.py`

**Plugin files:**
- `topic_registry.py`
- `tests/test_topic_registry.py`

**Acceptance criteria:**
- Existing `$HERMES_HOME/gateway/telegram_topics.json` remains readable.
- Atomic writes and bounded/deduplicated fields remain.
- Plugin-disabled runtime performs no registry read/write.
- Topic records never bleed across chat/thread keys.

### Task 3.2: Record discovered topics via the post-auth event hook

**Files:**
- Plugin: `dispatch.py`
- Modify: `plugins/platforms/telegram/adapter.py` to remove plugin-specific registry import only after plugin test passes.

**Acceptance criteria:**
- Core adapter continues parsing `chat_topic`, `thread_id`, `message_id`, and `auto_skill`.
- Plugin records normalized event metadata.
- Core Telegram adapter has no import of plugin registry code.

## Phase 4 — Ephemeral topic context

### Task 4.1: Add gateway turn-context contribution hook

**Files:**
- Modify: `hermes_cli/plugins.py`
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_plugin_turn_context.py`

**Hook:** `gateway_turn_context`

**Acceptance criteria:**
- Contribution is appended to the current user turn only.
- Contribution is not persisted to transcript.
- System prompt remains byte-stable.
- Hook failure is non-fatal.

### Task 4.2: Move topic context formatter into plugin

**Acceptance criteria:**
- Current topic title/purpose/facts/open-loops context remains available.
- Topic A/B isolation is tested.
- Remove `SessionContext.topic_context` and Telegram registry import from `gateway/session.py` only after parity tests pass.

## Phase 5 — Context-aware gateway commands

### Task 5.1: Add `register_gateway_command`

**Files:**
- Modify: `hermes_cli/plugins.py`
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_plugin_gateway_commands.py`

**Acceptance criteria:**
- Handler receives authorized `event`, `source`, raw args, and restricted services.
- Built-in commands retain precedence.
- Generic CLI plugin commands keep their current raw-args-only API.

### Task 5.2: Move `/topic` and `/topics`

**Acceptance criteria:**
- `/topic set`, `/topic skills`, `/topic memory`, and `/topics` match current behavior.
- Commands reject DM/non-thread contexts.
- Remove group topic command implementation from `gateway/slash_commands.py` after parity tests pass.

## Phase 6 — Remove old core ownership

### Task 6.1: Delete direct custom imports and modules

**Remove after all parity tests pass:**
- `gateway/dm_topic_router.py`
- `gateway/telegram_topics.py`
- custom topic registry imports from Telegram adapter/session/run/slash commands

**Acceptance criteria:**
- Search finds no remaining core import of plugin-owned modules.
- Existing native Telegram DM-topic tests remain green.

### Task 6.2: Install plugin and migrate configuration

**Install target:** `$HERMES_HOME/plugins/telegram-workspace`

**Acceptance criteria:**
- Plugin listed by `hermes plugins list`.
- Plugin enabled only after tests and config validation.
- Existing registry and ledger are backed up before first live run.
- Gateway restart occurs only after all verification passes.

## Phase 7 — Verification and rollout

### Focused verification

```bash
python -m pytest \
  tests/hermes_cli/test_plugins.py \
  tests/gateway/test_plugin_dispatch.py \
  tests/gateway/test_plugin_turn_context.py \
  tests/gateway/test_plugin_gateway_commands.py \
  tests/gateway/test_telegram_topics.py \
  tests/gateway/test_dm_topic_router.py \
  tests/gateway/test_dm_topic_route_ledger.py \
  tests/gateway/test_dm_topic_router_gateway.py \
  tests/gateway/test_telegram_topic_mode.py \
  tests/gateway/test_telegram_thread_fallback.py \
  -q -o 'addopts='
```

### Broader verification

```bash
python -m pytest tests/gateway/test_telegram_*.py tests/hermes_cli/test_plugins.py -q -o 'addopts='
python -m py_compile hermes_cli/plugins.py gateway/plugin_dispatch.py gateway/run.py
```

### Manual validation

1. Plugin disabled: ordinary Telegram DM and group topic behavior unchanged.
2. Plugin enabled: `/topics` lists observed workspace topics.
3. `/topic memory` shows only current topic.
4. A test DM routes once into the chosen topic.
5. Duplicate delivery does not rerun.
6. Restart gateway; registry and ledger persist.
7. Disable plugin; ordinary Telegram continues to work.

## Deferred feature: topic compaction

`update_topic_memory_from_transcript()` currently has no production call site. It will be implemented later as a new opt-in feature, after extraction, with separate tests and bounded auxiliary-model cost. It is not part of behavior-preserving acceptance.

## Rollback

- Disable `telegram-workspace` plugin in config.
- Restart gateway.
- Core Telegram transport/session behavior remains available.
- During staged migration, old core path remains behind a temporary compatibility flag until live plugin validation passes.
