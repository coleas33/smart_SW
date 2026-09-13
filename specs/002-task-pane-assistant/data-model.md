# Data Model: Task Pane Assistant

**Feature**: `002-task-pane-assistant` | **Date**: 2026-09-13 | **Spec**: [spec.md](spec.md)

Feature 001's `EvidencePackage`, `ReviewSession`, `Finding`, `EvidenceRequest`, `Coverage`,
and `Disposition` are reused unchanged. This feature adds the provider layer types, the
chat event stream, the pane's settings and process records, and the general-chat log.

## 1. Provider layer (Python)

| Type | Fields | Rules |
|------|--------|-------|
| `ToolSpec` | `name: str`, `description: str`, `schema: dict` (canonical JSON Schema), `fn: Callable` | Built once per tool from the signature and docstring; `name` ≤ 60 chars, `[a-z0-9_]`. |
| `ProviderName` | `"openai" \| "gemini" \| "fake"` | No other value is constructible. |
| `ProviderSettings` | `provider: ProviderName`, `model: str`, `effort: "low" \| "medium" \| "high" \| "xhigh"`, `api_key: SecretStr \| None`, `key_source: "settings" \| "env" \| "none"`, `base_url: str \| None`, `enterprise: {project, location} \| None` | `api_key` never serializes; `model_dump` excludes it; `__repr__` redacts. |
| `EffortMapping` | `requested: str`, `provider_param: str`, `provider_value: str` | Recorded in the session (`ReviewSession.model` gains a sibling field `provider_info`, see below). |
| `ToolCallRequest` | `call_id: str`, `name: str`, `arguments: dict` | Arguments parsed by the adapter (OpenAI JSON string, Gemini dict) before validation. |
| `ToolCallResult` | `call_id: str`, `payload: dict`, `is_error: bool` | Encoded by the adapter (OpenAI `function_call_output` string, Gemini `function_response` dict). |
| `AgentEvent` | see section 2 | Emitted through `on_event`. |

`ReviewSession` gains one optional field, `provider_info`: `{provider, model, effort_mapping,
key_source}`; the review-session contract is bumped to a minor version.

## 2. Chat event stream

Every event: `seq: int` (monotonic per session), `at: ISO 8601`, `type`, and a type-specific
body. Written to `events.jsonl` and streamed as server-sent events with `id = seq`.

| `type` | Body | Producer |
|--------|------|----------|
| `session.started` | `session_id`, `package_id`, `provider`, `model` | runner |
| `text.delta` | `text` | adapter |
| `text.done` | `text` (full turn text) | adapter |
| `tool.started` | `step_index`, `tool`, `arguments` | registry |
| `tool.finished` | `step_index`, `status: ok \| error`, `result_summary`, `elapsed_s`, `error` | registry |
| `finding` | the full `Finding` | check tools |
| `evidence.requested` | `EvidenceRequest` | session tools |
| `evidence.answered` | `request_id`, `answer` | server (engineer) |
| `disposition` | `finding_id`, `Disposition` | server (engineer) |
| `coverage` | `bucket`, `CoverageItem` | tools |
| `turn.ended` | `reason: end \| max_steps \| error` | runner |
| `session.ended` | `ended_at`, `timing` | runner |
| `error` | `error_class`, `message` (redacted), `retryable: bool` | any |

Rule: events are append-only; the pane rebuilds its view from `events.jsonl` on reconnect
using `Last-Event-ID`.

## 3. Chat session (Python, `chat/sessions.py`)

| Field | Type | Rules |
|-------|------|-------|
| `chat_id` | uuid | Distinct from `ReviewSession.session_id`. |
| `run_dir` | path | Contains `package.json`; the review session and events live here. |
| `review_session_id` | uuid | Set when the runner starts. |
| `state` | `idle \| extracting \| running \| waiting_engineer \| ended \| failed` | `waiting_engineer` while an evidence request is open and no turn is running. |
| `messages` | provider-neutral history: `[{role: user \| assistant \| tool, ...}]` | Owned by the runner; adapters translate. |
| `open_requests` | list of `EvidenceRequest` ids | Cleared on answer. |
| `events_path` | path | `events.jsonl`. |
| `token` | str | Per-launch secret required on every HTTP call. |

Transitions: `idle → extracting → running → (waiting_engineer ↔ running)* → ended`;
any state `→ failed` on an unrecoverable error, and `failed` still writes `session.ended`.

## 4. Settings (C#, per Windows user)

`%APPDATA%\SwReview\settings.json`, schema in `contracts/settings.schema.json`:

| Field | Type | Rules |
|-------|------|-------|
| `version` | int | 1. |
| `provider` | `openai \| gemini` | Default `openai`. |
| `model` | string | Default per provider. |
| `effort` | string | Default `high`. |
| `api_key_protected` | base64 | DPAPI `CurrentUser` scope; absent when unset. |
| `base_url` | string \| null | Enterprise gateway. |
| `gemini_enterprise` | `{project, location}` \| null | |
| `terminal_cli` | `codex \| gemini` | Last choice. |
| `python` | string \| null | Explicit interpreter or `uv` path override. |
| `run_root` | string | Default `%USERPROFILE%\Documents\SwReview\runs`. |

## 5. Pane process records (C#)

| Type | Fields | Rules |
|------|--------|-------|
| `BackendProcess` | `pid`, `port`, `token`, `log_path`, `started_at`, `healthy: bool` | Started with the key in the environment only; killed on unload via a job object. |
| `ToolService` | `pipe_name` (`swreview-<guid>`), `secret`, `log_path`, `requests_served`, `circuit_open: bool` | Hosted in the add-in; secret checked on every request line. |
| `TerminalSession` | `cli: codex \| gemini`, `version`, `exe_path`, `profile_paths[]`, `cwd`, `cols`, `rows`, `pid` | One at a time per pane; profile regenerated at start. |
| `PageMessage` | `type`, `payload` | See `contracts/pane-host-messages.md`. |

## 6. General chat log (`chat-log.jsonl`)

One line per MCP tool call: `{at, cli, tool, arguments, status, result_summary, elapsed_s,
error}`. Written by the MCP server; the pane shows the count on the Terminal tab.

## 7. Relationships

```text
ChatSession 1 run_dir 1 EvidencePackage
ChatSession 1 ReviewSession (feature 001) ; ReviewSession 0..* Finding
ChatSession 1 events.jsonl ; AgentEvent * -> events.jsonl and SSE
ProviderSettings -> AgentProvider (one active per session)
ToolService 1 per add-in instance ; used by ChatSession tools and by the MCP server
TerminalSession 0..1 per pane ; TerminalSession -> generated profiles -> MCP server -> ToolService
```
