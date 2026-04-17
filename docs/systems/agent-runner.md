# Agent Runner

`core/agent/runner.py` — the `QThread` that drives the Claude-native
trading loop. One fresh Claude Code subprocess per iteration, streamed
through `claude-agent-sdk.query()`, with hard wall-clock and tool-call
caps enforced in Python.

## Purpose

Phase 4+ of the rebuild: Claude is the brain and this file is the only
place that talks to the Claude Agent SDK. The rest of the app sees a
`QThread` with Qt signals — nothing above this layer needs to know how
subprocesses or asyncio event loops work.

## Lifecycle

```
MainWindow.start_agent()
    └── AgentRunner(config_path, broker_service, db_path).start()
            │
            └── run()  (QThread entry)
                    │
                    └── asyncio.run(_loop())
                            │
                            while not stop:
                                _run_one_iteration()      ← one subprocess
                                _sleep_respecting_cadence()
```

Each iteration:

1. `init_agent_context(...)` populates the per-iteration context
   (config, broker, db, risk manager, paper flag, iteration id).
2. `create_sdk_mcp_server(name="blank", tools=ALL_TOOLS)` registers an
   in-process MCP server.
3. `claude_agent_sdk.query(prompt, options)` spawns the Claude Code
   subprocess. `options.allowed_tools` is hard-capped to
   `mcp__blank__*` so the agent cannot shell out.
4. Async iterator yields messages — tool calls, tool results, text
   chunks. Each yields a Qt signal.
5. Wall-clock deadline and tool-call counter are checked at every
   message boundary. Breaking the async generator triggers the SDK's
   subprocess cleanup.
6. `clear_agent_context()` runs in `finally`.

## Qt signals

| Signal | Payload | Meaning |
|--------|---------|---------|
| `status_changed` | `bool` | `True` when loop is alive |
| `iteration_started` | `str iteration_id` | New subprocess about to spawn |
| `iteration_finished` | `str iteration_id, str summary` | End-of-iteration (clean or wall-clock) |
| `tool_use` | `dict {name, input, iteration_id}` | MCP tool call fired |
| `tool_result` | `dict {content, is_error, iteration_id}` | Tool call result |
| `text_chunk` | `str` | Raw assistant text block |
| `log_line` | `str` | Pre-formatted journal line for the agent log panel |
| `error_occurred` | `str` | Fatal runner error |

All signals auto-marshal onto the GUI thread via `Qt.QueuedConnection`,
so slots are safe to touch widgets directly.

## Control API

```python
runner.send_user_message(text: str) -> None
    # Queues a user message; sets _interrupt_sleep so the next
    # iteration fires immediately with the message prepended.

runner.request_stop() -> None
    # Soft-stop flag checked at every message boundary and during
    # sleep. Current iteration can finish cleanly.
```

Kill is soft-stop + 3 second `wait()` + `terminate()` — all handled by
`MainWindow.closeEvent` and the agent log panel's Kill button.

## Hard caps

| Cap | Default | Source |
|-----|---------|--------|
| `cadence_seconds` floor | 30 | `CADENCE_FLOOR_SECONDS` in runner |
| `cadence_seconds` default | 45 | `config.agent.cadence_seconds` — aggressive for day/swing trading |
| `max_tool_calls_per_iter` | 40 | `config.agent.max_tool_calls_per_iter` |
| `max_iter_seconds` | 360 | `config.agent.max_iter_seconds` |
| Paper mode lock | `true` | `config.agent.paper_mode` → forces `broker.type="log"` |

The runner re-reads `config.json` on every iteration, so cadence and
cap changes take effect on the next wake.

## Paper-mode enforcement

`_force_paper_config(cfg)` deep-copies the loaded config and, if
`agent.paper_mode` is true, overrides `broker.type = "log"`. The
forced config is what the per-iteration `broker_service` and
`AgentContext` see. Live trading only kicks in when the user
explicitly flips paper mode off **and** configures a real broker.

## Model + effort

The supervisor runs Claude Opus 4.7 at `effort="max"`. The SDK's
`ClaudeAgentOptions.effort` field takes `low | medium | high | max`
(SDK ≥ 0.1.59) and is populated from `model_router.supervisor_effort`.
No separate grader agent — the supervisor assesses its own iteration
output and writes the journal summary.

Chat and research workers get their own effort accessors:

- `chat_worker_effort(config, tier)` — `high` for the decision tier,
  `medium` for the info tier.
- `research_effort(config, role)` — `high` for deep (Opus) roles,
  `medium` for medium (Sonnet) roles, `low` for quick (Haiku) roles.

Config lives under the `ai` block (plain-string model IDs + `effort_*`
keys). See `docs/ARCHITECTURE.md` "Model routing + effort".

## Dependencies

- `claude-agent-sdk>=0.1.59` (pinned in `requirements.txt`)
- `PySide6.QtCore` (`QThread`, `Signal`)
- `core/agent/mcp_server.py` — `build_mcp_server()` factory + `allowed_tool_names()`
- `core/agent/context.py` — per-iteration context
- `core/agent/prompts.py` — system prompt template
- `core/broker_service.py`, `core/risk_manager.py`, `core/database.py`
