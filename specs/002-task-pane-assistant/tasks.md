---

description: "Task list for the Task Pane Assistant"
---

# Tasks: Task Pane Assistant

**Input**: Design documents from `/specs/002-task-pane-assistant/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md; feature 001 complete through its wiring tasks.

**Tests**: REQUIRED (constitution Principle III). Test tasks precede implementation in every phase; feature 001 golden baselines must not change.

**Organization**: Foundational provider port first (it removes the Anthropic dependency and every story needs it), then US2 (settings), US1 (review chat), US4 (in-process tool service), US3 (terminal general chat), polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on incomplete tasks)
- **[Story]**: US1 review chat, US2 provider settings, US3 general chat, US4 in-process tool service
- Paths are relative to the repository root

## Path Conventions

- Python: `reviewer/src/swreview/`, tests in `reviewer/tests/`
- C#: `extractor/SwReview.AddIn/`, `extractor/SwReview.Extractor/`, tests in `extractor/SwReview.Extractor.Tests/` and a new `extractor/SwReview.AddIn.Tests/`
- Vendored web assets: `extractor/SwReview.AddIn/Review/ReviewPage/`, `extractor/SwReview.AddIn/Terminal/TerminalPage/`

---

## Phase 1: Setup

- [ ] T001 Update `reviewer/pyproject.toml`: add `openai`, `google-genai`, `mcp`, `starlette`, `sse-starlette`, `uvicorn`, `httpx`; dev `respx`; remove `anthropic`; add console entry points `swreview-chat = "swreview.chat.__main__:main"` and `swreview-mcp = "swreview.mcp.server:main"`; run `uv sync --all-extras`
- [ ] T002 [P] Create `extractor/SwReview.AddIn.Tests/SwReview.AddIn.Tests.csproj` (xUnit, net48, x64, references `SwReview.AddIn` and `SwReview.Extractor`) and add it to `extractor/SwReview.sln`
- [ ] T003 [P] Add `Microsoft.Web.WebView2` (pinned) to `extractor/SwReview.AddIn/SwReview.AddIn.csproj` with `WebView2Loader.dll` copied to output; add `<Content>` items for `Review/ReviewPage/**` and `Terminal/TerminalPage/**` copied to `web/`
- [ ] T004 [P] Vendor xterm.js and `@xterm/addon-fit` (pinned versions, MIT) into `extractor/SwReview.AddIn/Terminal/TerminalPage/vendor/` with a `LICENSES.md` listing versions and licenses; no CDN references anywhere
- [ ] T005 [P] Add `.gitignore` entries: `extractor/SwReview.AddIn/web/`, `**/.swreview-cli/`, `%APPDATA%`-style settings never in repo; add `benchmarks/**/chat-log.jsonl` and `**/events.jsonl` under `runs/` ignore

---

## Phase 2: Foundational (provider layer and runner port)

**Purpose**: One `AgentProvider` protocol with OpenAI, Gemini, and fake adapters; runner and registry free of the Anthropic SDK; uniform events; `--provider` on the CLI.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T006 Write `reviewer/tests/unit/test_provider_schema.py`: for every function in `tools/registry.py`'s registrations, `providers/schema.py:canonical_schema(fn)` yields `type: object`, properties with descriptions from the Google-style docstring, `required` matching non-default parameters, nested `SourceRef` definitions inlined; `strictify()` sets `additionalProperties: false` on every object, moves every property into `required`, rewrites optional parameters to `["T", "null"]`, and has no `$defs`; `gemini_adapt()` removes `additionalProperties` and `$defs` and keeps nullable unions; a golden comparison of every tool's canonical schema against the feature 001 tool table names in `contracts/agent-tools.md`
- [ ] T007 Implement `reviewer/src/swreview/agent/providers/schema.py`: `canonical_schema(fn)` via `pydantic.TypeAdapter(fn).json_schema(ref_template=...)` plus a docstring `Args:` parser; `strictify(schema)`; `gemini_adapt(schema)`; `ToolSpec` dataclass builder `tool_spec(fn)`
- [ ] T008 Write `reviewer/tests/unit/test_provider_protocol.py`: `AgentEvent` model validates against `specs/002-task-pane-assistant/contracts/chat-events.schema.json` for every event type; `ProviderName` rejects unknown values; `EffortMapping` is recorded; the `providers.get(name)` registry returns the adapter class and raises for `anthropic`/`claude`
- [ ] T009 Implement `reviewer/src/swreview/agent/providers/__init__.py`: `AgentProvider` protocol (`run(system, messages, tools, effort, max_steps, on_event) -> TurnResult`), `AgentEvent`, `ToolCallRequest`, `ToolCallResult`, `EffortMapping`, `ProviderName`, registry
- [ ] T010 Write `reviewer/tests/unit/test_fake_provider.py`: scripted tool calls and text; emits `text.delta`, `tool.started/finished` through the registry, stops at `max_steps`; deterministic
- [ ] T011 Implement `reviewer/src/swreview/agent/providers/fake.py` (script-driven provider used by tests and by the pane's development mode)
- [ ] T012 Write `reviewer/tests/unit/test_registry_provider_neutral.py`: `RecordedTool.call(arguments) -> ToolCallResult` returns `(payload, is_error)` without raising, validates arguments with `pydantic.validate_call`, records the step, converts exceptions to error payloads and `failed` coverage; no `anthropic` import anywhere under `src/` (assert with an import scan)
- [ ] T013 Port `reviewer/src/swreview/tools/registry.py`: drop `BetaFunctionTool`/`ToolError`; `RecordedTool` wraps a `ToolSpec`; `ToolRegistry.build(ctx) -> list[RecordedTool]`; keep `REGISTRATIONS` and `fail_tool`
- [ ] T014 Write `reviewer/tests/unit/test_runner_provider.py` (replace the anthropic-based fake in `test_agent_runner.py`): runner drives an `AgentProvider`; multi-turn `continue_session(chat, text)` appends a user turn; `answer_evidence(request_id, answer)` marks the request answered and resumes; `max_steps` and `fail_tool`; events written to `events.jsonl` in order with monotonic `seq`; `session.started` carries `provider_info`; final `session.json` validates against the (minor-bumped) review-session contract
- [ ] T015 Port `reviewer/src/swreview/agent/runner.py`: `run_review(..., provider: AgentProvider, model, effort)`; `ReviewRun` object with `continue_session` and `answer_evidence`; event emission via an `EventSink` that writes `events.jsonl` and fans out to callbacks; `provider_info` on the session
- [ ] T016 Bump `specs/001-agentic-design-review/contracts/review-session.schema.json` with optional `provider_info` (provider, model, effort_mapping, key_source) and update `reviewer/src/swreview/report/session.py` and its test
- [ ] T017 Write `reviewer/tests/unit/test_openai_provider.py` with `respx`: request shape (`tools` flat with `strict: true`, `instructions`, `reasoning.effort`, `max_output_tokens`, `parallel_tool_calls`), full-list history with `response.output` echoed including reasoning items, `function_call` → validated call → `function_call_output`, streaming events mapped to `text.delta`/`tool.started`/`tool.finished`, error mapping for `AuthenticationError`, `RateLimitError`, `APIConnectionError`, key redaction in error text, effort mapping recorded
- [ ] T018 Implement `reviewer/src/swreview/agent/providers/openai_provider.py` (Responses API, streaming, strictified tools, `instructions`, `reasoning={"effort": ...}`, `max_output_tokens=16000`)
- [ ] T019 Write `reviewer/tests/unit/test_gemini_provider.py` with a stubbed `genai.Client`: `FunctionDeclaration(parameters_json_schema=gemini_adapt(...))`, `automatic_function_calling.disable=True`, `system_instruction`, `thinking_config.thinking_level` mapping (and `thinking_budget` for 2.5 models), `function_call` parts → validated call → `Part.from_function_response` with `id`, streaming chunks synthesized into events, error mapping for `ClientError` 401/429 and `ServerError`, redaction
- [ ] T020 Implement `reviewer/src/swreview/agent/providers/gemini_provider.py` (`generate_content_stream`, manual loop, `role="tool"` responses)
- [ ] T021 Write `reviewer/tests/unit/test_provider_settings.py`: precedence settings-over-env with `key_source` reported; `SecretStr` never in `model_dump`, `repr`, or logs; `redact(text, secrets)` masks every configured key; default models per provider; `enterprise` mapping for Gemini
- [ ] T022 Implement `reviewer/src/swreview/agent/settings.py` (`ProviderSettings`, `from_env()`, `redact()`, `configure_logging_redaction()`)
- [ ] T023 Update `reviewer/src/swreview/cli.py`: `--provider openai|gemini|fake` (default `openai`), `--model`, `--effort` on `review` and `benchmark run`; `REVIEW_CLIENT` hook replaced by a `provider_factory` hook; `benchmark/runner.py` passes provider and model; update `tests/unit/test_cli.py` and `test_answer_key_isolation.py` fakes
- [ ] T024 Write `reviewer/tests/unit/test_events_schema.py`: every event the runner and tools can emit validates against `contracts/chat-events.schema.json` (resolve the feature 001 `$ref`s), and `events.jsonl` from a fake run round-trips
- [ ] T025 Run the full suite; confirm feature 001 goldens unchanged and `uv pip show anthropic` reports not installed

**Checkpoint**: `swreview review --provider fake` produces a session and `events.jsonl`; OpenAI and Gemini adapters pass recorded tests.

---

## Phase 3: User Story 2 - Provider Settings (Priority: P2)

**Goal**: Per-user settings with a protected key, settings UI in the Review page, backend started with the key in its environment.

**Independent Test**: quickstart Scenario 2 (fake and recorded providers).

- [ ] T026 [P] [US2] Write `extractor/SwReview.AddIn.Tests/UserSettingsTests.cs`: round trip to a temp `settings.json` validating against `contracts/settings.schema.json`; key protected with DPAPI `CurrentUser` and unreadable when the ciphertext is copied to a different user context (simulate by tampering); missing file yields defaults (`openai`, default model, `high`, `codex`, run root); `key_source` reported
- [ ] T027 [P] [US2] Write `extractor/SwReview.AddIn.Tests/RedactionTests.cs`: every configured secret is masked in log lines and exception messages, including URL-encoded and JSON-escaped forms
- [ ] T028 [US2] Implement `extractor/SwReview.AddIn/Settings/UserSettings.cs` and `Settings/Redaction.cs`
- [ ] T029 [P] [US2] Write `reviewer/tests/unit/test_cli_audit_secrets.py`: `swreview audit-secrets <dir>...` exits 1 and names the file when any configured key (from env) appears in files under the directories; 0 otherwise
- [ ] T030 [US2] Implement `audit-secrets` in `reviewer/src/swreview/cli.py`
- [ ] T031 [US2] Write `extractor/SwReview.AddIn.Tests/PageMessageTests.cs`: `settings.get`, `settings.save`, `models.list` messages per `contracts/pane-host-messages.md`, including that `settings.save` never echoes the key and that `init` omits it
- [ ] T032 [US2] Implement the Review page skeleton `extractor/SwReview.AddIn/Review/ReviewPage/{index.html,app.js,app.css}` with the Settings section (provider, model list, key field, effort, base URL, enterprise fields, Save) and the `ready`/`init`/`settings.*`/`models.list` messages; and `extractor/SwReview.AddIn/Review/ReviewHost.cs` handling those messages
- [ ] T033 [US2] Write `extractor/SwReview.AddIn.Tests/BackendProcessTests.cs` against a stub script that prints `{port, token}`: parses the first line, times out with a clear error, passes the key only through the environment (assert the command line has no key), stops the process on dispose, restarts on settings change
- [ ] T034 [US2] Implement `extractor/SwReview.AddIn/Review/BackendProcess.cs` (locate `uv`/python from settings or PATH, start `swreview chat serve --port 0`, job object kill-on-close, health poll)

**Checkpoint**: Settings save and restore across restarts; the backend starts with the key in its environment only.

---

## Phase 4: User Story 1 - Review Chat (Priority: P1)

**Goal**: Press Review, watch the investigation, act on findings, answer evidence requests, ask follow-ups.

**Independent Test**: quickstart Scenario 1.

- [ ] T035 [P] [US1] Write `reviewer/tests/unit/test_chat_sessions.py`: `ChatSession` state machine transitions from data-model section 3; `events.jsonl` writer with monotonic `seq`; replay from a given `seq`
- [ ] T036 [P] [US1] Write `reviewer/tests/unit/test_chat_server.py` with Starlette's test client: 401 without token; `POST /sessions` starts a fake-provider run and returns ids; `GET /events` streams replayed then live events with `id`; `POST /messages` 409 while running then 202; evidence answer 404/409/202; disposition 200/409 and `report.md` re-rendered; `/stop` writes `session.ended`; `/models` proxies and maps provider errors to 502; error bodies redacted
- [ ] T037 [US1] Implement `reviewer/src/swreview/chat/sessions.py` and `reviewer/src/swreview/chat/server.py` (Starlette app, SSE via `sse-starlette`, one worker thread per chat, credentials from environment only)
- [ ] T038 [US1] Implement `reviewer/src/swreview/chat/__main__.py` (`--port 0`, prints `{port, token}` once, binds 127.0.0.1, `--fail-bridge N` test hook) and wire `swreview chat serve` in `cli.py`
- [ ] T039 [P] [US1] Write `extractor/SwReview.AddIn.Tests/ReviewHostTests.cs`: `review.start` refuses without an open document; with a fake session and fake backend client it creates the run folder, runs the dump, posts the session, and replies `review.started`; `entity.show` resolves through a fake resolver and reports the state code on failure; `report.open`/`folder.open`/`log.open` shell out through an injectable opener
- [ ] T040 [US1] Implement `extractor/SwReview.AddIn/Review/ReviewHost.cs` review flow: run folder naming (`<run_root>/<yyyyMMdd-HHmmss>-<doc>`), in-process `PackageWriter` dump with progress `status` messages, backend `POST /sessions`, `entity.show` via `PersistRefService.Resolve` + `SelectByID2` + `ViewZoomToSelection` on the application thread, `document.changed` notifications
- [ ] T041 [US1] Implement the Review page chat view in `Review/ReviewPage/app.js`: SSE client with `Last-Event-ID` reconnect; transcript of text, tool cards (name, summary, status, elapsed), finding cards (status, severity, title, components, expand for full fields, Show in SOLIDWORKS, Accept/Reject/Defer with note), evidence request cards with an answer box, coverage summary, error cards with Retry/Open Settings/View log, follow-up input disabled while a turn runs; keep the last 500 events in memory
- [ ] T042 [US1] Write `extractor/SwReview.AddIn.Tests/ReviewPageContractTests.cs`: load `app.js` in a headless check that every message type it sends and handles is in `contracts/pane-host-messages.md` (string scan against the contract table) and that it never references a key field after `init`
- [ ] T043 [US1] Replace `extractor/SwReview.AddIn/DumpIrPanel.cs` with `TaskPaneControl.cs`: tabs Review (WebView2 hosting the page from a virtual host), Terminal (placeholder until US3), Actions (the three existing buttons); `SwReviewAddIn.cs` hosts it, starts the backend after settings load, and stops it on disconnect
- [ ] T044 [US1] Run quickstart Scenario 1 with the fake provider on the bracket fixture; record results in `benchmarks/native/bracket-assy/notes.md`

**Checkpoint**: A full review runs from the pane with the fake provider; findings can be shown, dispositioned, and followed up.

---

## Phase 5: User Story 4 - In-Process Tool Service (Priority: P4)

**Goal**: Captures, measurements, interference, and Show in SOLIDWORKS served by the add-in on the application thread, with a per-launch secret.

**Independent Test**: quickstart Scenario 4.

- [ ] T045 [US4] Move `SwBridgeDispatcher`, `BridgeProtocol`, `BridgeServices`, and the command result types from `extractor/SwReview.Extractor.Console/Serve/` to `extractor/SwReview.Extractor/Bridge/`; keep `PipeServer` in the console; update namespaces and tests; add the `secret` field to `BridgeRequest` (optional; the console host ignores it, the in-process host requires it) and document it in `PROTOCOL.md`
- [ ] T046 [P] [US4] Write `extractor/SwReview.AddIn.Tests/InProcPipeServerTests.cs`: requests read on a background thread are executed through an injectable `Invoke` that records the calling thread; concurrent requests serialize in arrival order; wrong or missing secret returns `unauthorized` and is logged without the secret; circuit-open propagates; dispose stops the listener and pending requests get `error`
- [ ] T047 [US4] Implement `extractor/SwReview.AddIn/ToolService/InProcPipeServer.cs` (pipe reader thread, `Control.BeginInvoke` marshalling to the Task Pane control, one-at-a-time execution) and `ToolService/ToolServiceHost.cs` (`SwScope.Open` on the application thread, `SwBridgeDispatcher`, pipe `swreview-<guid>`, secret, log under `%LOCALAPPDATA%\SwReview\logs`)
- [ ] T048 [US4] Wire the tool service into `SwReviewAddIn.cs`: start on connect after the first document is available, pass `{pipe, secret}` to the backend `POST /sessions` `bridge` field and to the MCP profile writer, stop on disconnect; `entity.show` uses the same scope
- [ ] T049 [P] [US4] Update `reviewer/src/swreview/bridge/client.py` and `tools/bridge.py` to send `secret` and to accept it from the session's `bridge` config; tests in `tests/unit/test_bridge_client.py`
- [ ] T050 [US4] Write `extractor/SwReview.AddIn.Tests/ProcessLifetimeTests.cs`: backend and CLI child processes are assigned to a job object with kill-on-close; disposing the host ends them; two hosts in one process get distinct pipe names and ports
- [ ] T051 [US4] Run quickstart Scenario 4 on the workstation; record in `benchmarks/native/bracket-assy/notes.md`

**Checkpoint**: No console `serve` needed for the pane; requests are served in-process with a secret.

---

## Phase 6: User Story 3 - General Chat Terminal (Priority: P3)

**Goal**: Codex or Gemini running inside the pane with our read-only tools and a regenerated restriction profile.

**Independent Test**: quickstart Scenario 3.

- [ ] T052 [P] [US3] Write `extractor/SwReview.AddIn.Tests/ConPtyTests.cs`: start `cmd.exe /c echo hello` under a pseudo-console and receive `hello`; resize changes `COLUMNS`/`LINES` as observed by a child `mode con`; closing the console ends the child; output chunks arrive as bytes without translation
- [ ] T053 [US3] Implement `extractor/SwReview.AddIn/Terminal/ConPty.cs` (P/Invoke `CreatePseudoConsole`, `ResizePseudoConsole`, `ClosePseudoConsole`, `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`, pipes) and `Terminal/TerminalSession.cs` (start with cwd and environment, async read loop to `terminal.output` base64, `terminal.input`, resize, stop with exit command then process-tree termination, exit notification)
- [ ] T054 [P] [US3] Write `extractor/SwReview.AddIn.Tests/CliLocatorTests.cs`: finds `codex`/`gemini` on PATH including `.cmd`/`.ps1` npm shims, parses `--version`, compares to minimums, reports not-found with install steps and the Node requirement for Gemini
- [ ] T055 [US3] Implement `extractor/SwReview.AddIn/Terminal/CliLocator.cs`
- [ ] T056 [P] [US3] Write `extractor/SwReview.AddIn.Tests/CliProfileWriterTests.cs`: generated Codex profile TOML and `-c` overrides, Gemini `settings.json` and policy TOML match `contracts/cli-profiles.md` byte-for-byte after placeholder substitution; the secret appears only in the `env` block; a previous file with a missing restriction key produces a warning; regeneration overwrites edits; the Codex launch arguments include `--profile swreview`, every `-c` override, and `-C <run_dir>`; the Gemini launch sets the settings directory override and `--approval-mode plan`
- [ ] T057 [US3] Implement `extractor/SwReview.AddIn/Terminal/CliProfileWriter.cs` plus the persona texts `Terminal/Profiles/codex-instructions.md` and `Terminal/Profiles/GEMINI.md` (read-only rule, tool list, run folder layout; no numbers from memory)
- [ ] T058 [P] [US3] Write `reviewer/tests/unit/test_mcp_server.py` with the `mcp` client over in-memory streams: the tool list equals `contracts/mcp-toolset.md` exactly (no check tools, no `record_drawing_finding`, no `bridge_interference`); schemas are the canonical schemas; a call is appended to `chat-log.jsonl`; missing `package.json` makes every query return an error result; `bridge_*` tools appear only with `--bridge-pipe`; resources `swreview://package/summary` and `swreview://report`
- [ ] T059 [US3] Implement `reviewer/src/swreview/mcp/server.py` and `mcp/chat_log.py`; wire `swreview mcp` in `cli.py`
- [ ] T060 [US3] Implement the Terminal page `extractor/SwReview.AddIn/Terminal/TerminalPage/{index.html,term.js,term.css}` (xterm.js + fit addon, base64 output decode, input and resize messages, CLI dropdown, Start/Stop, install-steps view, chat-log count) and the terminal tab in `TaskPaneControl.cs`
- [ ] T061 [US3] Write `extractor/SwReview.AddIn.Tests/TerminalPageContractTests.cs`: message types match `contracts/pane-host-messages.md`
- [ ] T062 [US3] Implement the first-launch tool listing check in `TerminalSession` (Codex startup tool list parse; Gemini `/mcp` output parse) with a warning on the tab when the allowlist and the listed tools differ
- [ ] T063 [US3] Run quickstart Scenario 3 with Codex and with Gemini (install Gemini CLI with `npm i -g @google/gemini-cli` if absent); record in `benchmarks/native/bracket-assy/notes.md`

**Checkpoint**: General chat answers through our tools; writes are refused; no orphan processes.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T064 [P] Update `specs/001-agentic-design-review/contracts/cli.md` (new `chat serve`, `mcp`, `audit-secrets`, `--provider`/`--model`) and `contracts/agent-tools.md` (note that tool schemas are generated by `providers/schema.py` and are provider-neutral)
- [ ] T065 [P] Update `README.md`, `reviewer/README.md`, `extractor/README.md`, and `NOTICE.md` (xterm.js, ConPTY sample, openai, google-genai, mcp, starlette licenses; SwpilotCLI reimplemented, not copied)
- [ ] T066 [P] Add an `.github/workflows/reviewer.yml` step running `swreview audit-secrets` over the test output directory with a dummy key set
- [ ] T067 Run every quickstart scenario end to end; fix discrepancies between quickstart, contracts, and behavior
- [ ] T068 DRY and constitution review across `providers/`, `chat/`, `mcp/`, and `SwReview.AddIn/`; remove duplicated event or message shaping; confirm no Anthropic references remain in code, config, or docs for this feature

---

## Dependencies & Execution Order

- **Setup (Phase 1)** → **Foundational (Phase 2)** → **US2 (Phase 3)** → **US1 (Phase 4)** → **US4 (Phase 5)** → **US3 (Phase 6)** → **Polish**
- US1's Show in SOLIDWORKS works in-process from Phase 4 without US4; US4 adds the shared tool service that US3's MCP server needs for captures and measurements
- US3's Python MCP server (T058, T059) can be built in parallel with Phase 5

### Parallel Opportunities

- Phase 1: T002 through T005 after T001
- Phase 2: T006/T007, T008/T009, T010/T011 in parallel; T017/T018 and T019/T020 in parallel after T013
- Phase 3: T026, T027, T029 in parallel
- Phase 4: T035, T036, T039 in parallel
- Phase 6: T052, T054, T056, T058 in parallel

---

## Implementation Strategy

1. Finish Phase 2 and prove `swreview review --provider fake` and both recorded adapters (this alone removes the Anthropic dependency and unblocks the org's constraint).
2. Deliver US2 then US1 with the fake provider so the pane is demonstrable without keys.
3. Deliver US4 to make live actions in-process, then US3 for general chat.
4. Workstation scenarios T044, T051, T063 are the only steps needing SOLIDWORKS or the CLIs.

## Notes

- Never pass a key on a command line; environment blocks only.
- Regenerate CLI profiles on every launch; never trust the engineer's global CLI config for restrictions.
- Feature 001 golden baselines must remain unchanged through the provider port.
