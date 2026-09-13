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
| `EffortMapping` | `requested: str`, `provider_param: str`, `provider_value: str \| int` | Recorded in the session (`ReviewSession.model` gains a sibling field `provider_info`, see below). `provider_value` is an integer on Gemini 2.5 models, whose control is `thinking_budget`. An adapter that cannot express the requested level for the chosen model fails fast with a named error; it never silently downgrades. |
| `ToolCallRequest` | `call_id: str`, `name: str`, `arguments: dict` | Arguments parsed by the adapter (OpenAI JSON string, Gemini dict) before validation. |
| `ToolCallResult` | `call_id: str`, `payload: dict`, `is_error: bool` | Encoded by the adapter (OpenAI `function_call_output` string, Gemini `function_response` dict). |
| `AgentEvent` | see section 2 | Emitted through `on_event`. |

`ReviewSession` gains two optional fields in the same minor bump of the review-session
contract (T016): `provider_info`: `{provider, model, effort_mapping, key_source}`, and
`retry_of: session_id | null`, which links a session started by the pane's Retry action to
the failed session it replaces (spec Edge Cases).

There is no module-level default model. `tools/context.py` must not carry one: the default
comes from `agent/settings.py` per provider (`gpt-5.6` for OpenAI, `gemini-3.5-flash` for
Gemini, the scripted id for `fake`), so no code path can write a Claude model id into
`session.json` (FR-026).

## 2. Chat event stream

Every event: `seq: int` (monotonic per session), `at: ISO 8601`, `type`, and a type-specific
body. Written to `events.jsonl` and streamed as server-sent events with `id = seq`.

| `type` | Body | Producer |
|--------|------|----------|
| `session.started` | `session_id`, `package_id`, `provider`, `model`, `effort_mapping` | runner |
| `text.delta` | `text` | adapter |
| `text.done` | `text` (full turn text) | adapter |
| `tool.started` | `step_index`, `tool`, `arguments` | registry |
| `tool.finished` | `step_index`, `status: ok \| error`, `result_summary`, `elapsed_s`, `error` | registry |
| `finding` | the full `Finding` | check tools |
| `evidence.requested` | `EvidenceRequest` | session tools |
| `evidence.answered` | `request_id`, `answer` | server (engineer) |
| `disposition` | `finding_id`, `Disposition` | server (engineer) |
| `coverage` | `bucket`, `CoverageItem` | tools |
| `turn.ended` | `reason: end \| max_steps \| error \| stopped \| truncated` | runner |
| `session.ended` | `ended_at`, `timing` | runner |
| `error` | `error_class`, `message` (redacted), `retryable: bool` | any |

Rule: events are append-only; the pane rebuilds its view from `events.jsonl` on reconnect
using `Last-Event-ID`.

`contracts/chat-events.schema.json` is authoritative: on any disagreement with this table the
schema wins, and this table is corrected. `stopped` is emitted by `POST /stop` before
`session.ended`; `truncated` is emitted when the provider ends a turn on its output ceiling
(OpenAI `status: "incomplete"` with `incomplete_details.reason == "max_output_tokens"`), and
the runner writes an `unresolved` coverage item for it so a cut-short answer is never read as
a completed one.

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
| `retry_of` | chat_id \| null | Set when the session was started by the pane's Retry action after a failed session; also written to `ReviewSession.retry_of`. |
| `token` | str | Per-launch secret required on every HTTP call. Never returned by `GET /sessions/{chat_id}`, and neither is `bridge`. |

Transitions: `idle → extracting → running → (waiting_engineer ↔ running)* → ended`, plus
`ended → running` when the engineer sends a follow-up or answers an evidence request on a
session whose previous turn already ended (FR-006, US1 acceptance scenarios 4 and 5); any
state `→ failed` on an unrecoverable error, and `failed` still writes `session.ended`.
`failed` is terminal: its only exit is a new `ChatSession` carrying `retry_of`.
`POST /messages`, `POST /evidence` and `POST /disposition` are accepted in `running`
(409 while a turn is running), `waiting_engineer` and `ended`; in `failed` they are 409.

### Resume semantics (a second turn in the same session)

Feature 001's `finalize_session` appends coverage and sets `ended_at` on every call, which is
correct once and wrong twice. A session that can be resumed obeys these rules, and T014
asserts each of them:

1. **Finalization is idempotent.** `finalize_session` *rebuilds* the closeout and
   evidence-request coverage from the session's current state instead of appending to it, so
   a second finalization produces the same items rather than duplicates.
2. **An answered request stops being unresolved.** When `answer_evidence` marks a request
   answered, the `coverage.evidence_request` item written for it is removed (or rewritten to
   the bucket the re-run produces); an answered request never remains in the report as
   unresolved.
3. **A re-evaluated check has one verdict.** When a check is re-run after its blocking
   evidence request is answered, the new `Finding` replaces the prior one: it keeps the same
   finding id, or carries `supersedes: <finding_id>` and the superseded finding is excluded
   from the report body and from the severity counts. The report never shows two
   contradictory verdicts for one check.
4. **`max_steps` is a per-turn budget.** The runner compares the steps taken *this turn*
   against `max_steps`; the cumulative step count is recorded separately on the session. A
   resumed turn never no-ops because an earlier turn exhausted the budget.
5. **`ended_at` and `timing` are rewritten on every finalization** and always end non-null,
   including on the provider-failure path (FR-008).

## 4. Settings (C#, per Windows user)

`%APPDATA%\SwReview\settings.json`, schema in `contracts/settings.schema.json`:

| Field | Type | Rules |
|-------|------|-------|
| `version` | int | 1. |
| `provider` | `openai \| gemini \| fake` | Default `openai`. `fake` is the scripted development provider and is offered by the Settings UI only in a development build; a release build refuses to load a settings file naming it (FR-027). |
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
| `ToolService` | `pipe_name` (`swreview-<guid>`), `review_secret`, `chat_secret`, `log_path`, `requests_served`, `circuit_open: bool` | Hosted in the add-in; the pipe carries a current-user-only `PipeSecurity`; the secret on every request line selects the command scope (`contracts/README.md`). Per request, `log_path` records the command, elapsed time, and the **distinct set of interop member names `SwGate` gated during that request** plus any `MutatingCallError` refusal - a per-call line would be tens of thousands of writes on the SOLIDWORKS thread, a per-request set is cheap and is what SC-004 is checked against. |
| `TerminalSession` | `cli: codex \| gemini`, `version`, `exe_path`, `launch_command[]`, `profile_paths[]`, `cwd`, `cols`, `rows`, `pid` | One at a time per pane; profile regenerated at start. `cwd` is the current chat session's run folder, else a freshly created `<run_root>/<yyyyMMdd-HHmmss>-terminal`. `launch_command` is the resolved executable plus arguments: a `.exe` runs directly, a `.cmd`/`.bat` shim runs as `cmd.exe /c "<path>" <args>`, a `.ps1` as `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<path>"`; `CreateProcess` (which ConPTY requires) cannot execute a shim directly and the Gemini CLI ships as `gemini.cmd`. |
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
