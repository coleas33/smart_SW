# Implementation Plan: Task Pane Assistant

**Branch**: `002-task-pane-assistant` | **Date**: 2026-09-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-task-pane-assistant/spec.md`

## Summary

Add a two-tab Task Pane to the existing SOLIDWORKS add-in. The Review tab is a WebView2
chat page fed by the Python reviewer over loopback HTTP with server-sent events; the
reviewer's loop moves from the Anthropic SDK to a provider layer with OpenAI (default) and
Gemini adapters. The Terminal tab embeds the engineer's Codex or Gemini CLI through a ConPTY
pseudo-console and xterm.js, with our read-only tools registered as a stdio MCP server and
the CLI locked to a read-only profile. Live SOLIDWORKS actions for both modes are served by
the add-in itself on the application thread.

## Technical Context

**Language/Version**: Python 3.11+ (provider layer, chat backend, MCP server) and C# on
.NET Framework 4.8 x64 (add-in, Task Pane, ConPTY host, in-process tool service).

**Primary Dependencies**: Python: `openai` (Responses API), `google-genai`, `mcp` (stdio
server), `pydantic` (schema generation via `TypeAdapter`), `starlette`+`uvicorn` or
`aiohttp` for the loopback server with SSE (decide in Phase 1: `starlette` with `sse-starlette`
is the default choice), `httpx` (already transitively present; test client), `respx` (dev).
Removed: `anthropic`. C#: `Microsoft.Web.WebView2` (NuGet, WebView2Loader.dll shipped next
to the add-in; the add-in creates one `CoreWebView2Environment` for the process with an
explicit user data folder `%LOCALAPPDATA%\SwReview\WebView2\<add-in instance>`, shared by
both tabs, because the default folder is derived from `SLDWORKS.exe`, is shared with
SOLIDWORKS' own WebView2 usage and every other add-in in the process, and sits under a
Program Files directory that is not writable; environment creation failure degrades to the
documented runtime-missing fallback rather than an unhandled exception), Win32 ConPTY P/Invoke (`CreatePseudoConsole`, `ResizePseudoConsole`,
`ClosePseudoConsole`), `System.Security.Cryptography.ProtectedData` (DPAPI), `System.Text.Json`.
Vendored, MIT: xterm.js and its fit addon (pinned versions, no CDN).

**Storage**: Files. Run folder per session (`package.json`, `session.json`, `report.md`,
`captures/`, `chat-log.jsonl`, `events.jsonl`); per-user settings at
`%APPDATA%\SwReview\settings.json` (DPAPI-protected key); logs at `%LOCALAPPDATA%\SwReview\logs`;
generated CLI profiles under the run folder.

**Testing**: `pytest` (adapters with `respx`/stubs, fake provider, HTTP and SSE with an
in-process client, MCP with in-memory streams, schema strictifier, the chat backend's process
contract driven as a real subprocess), xUnit (message contract, ConPTY against `cmd.exe` and a
`.cmd` shim, dispatcher marshalling with fakes, DPAPI round trip, WebView2 runtime-missing
fallback), quickstart Scenarios 1 through 4 on the workstation.

**Target Platform**: Windows 11 workstation with SOLIDWORKS 2024, WebView2 runtime, Codex CLI
and/or Gemini CLI on PATH (Node 22 for Gemini).

**Project Type**: Extends the two-language monorepo: `extractor/SwReview.AddIn` (UI, ConPTY,
tool service host), `extractor/SwReview.Extractor` (dispatcher reuse), `reviewer/` (provider
layer, chat backend, MCP server).

**Performance Goals**: first finding card within 3 minutes on a 200-component assembly;
text delta to screen under 2 seconds; extraction under 1 minute (SC-001 and SC-002, timed and
written into the metric table in `benchmarks/native/bracket-assy/notes.md` by T044).
Terminal keystroke echo under 50 ms is a design target, not a success criterion: it is judged
qualitatively in Scenario 3 and bounded by the `terminal.output` coalescing rule whose
message count T052 asserts.

**Constraints**: OpenAI and Gemini only, no Anthropic dependency; every SOLIDWORKS call on
the application thread; read-only guard and circuit breaker unchanged; keys never on disk
unprotected, in logs, or in run folders; loopback-only endpoints with per-launch secrets;
no code copied from SwpilotCLI; general chat cannot create findings.

**Scale/Scope**: single engineer per pane, one session at a time per pane, two SOLIDWORKS
windows at most per workstation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | How this plan meets it | Status |
|-----------|------|------------------------|--------|
| I. Evidence before conclusions | Findings keep every field; unknown stays unknown | Findings are still produced only by feature 001 check tools; the pane renders them, never edits them; evidence answers become `EvidenceRequest.answer`, not inferred values | PASS |
| II. Deterministic numerics | The LLM never computes verdicts | Provider swap does not touch checks; the MCP toolset for general chat excludes check tools; measurements return tool results | PASS |
| III. Test-first with golden fixtures | Tests before code; goldens unchanged | Adapters, strictifier, server, MCP, ConPTY, and marshalling each get tests first; existing goldens must remain byte-identical | PASS |
| IV. Semantic fidelity and traceability | Persistent references drive navigation | Show in SOLIDWORKS resolves `persist_ref` with its scope through the in-process dispatcher and reports the state code on failure | PASS |
| V. Engineered enough | No speculative abstraction | One provider protocol with two adapters and one fake; one event schema shared by pane and CLI; no plugin system; SSE not WebSocket | PASS |
| VI. Inspectable findings, coverage tracked | Coverage and dispositions persist | Dispositions and evidence answers write through the existing session module; general chat writes a chat log | PASS |
| Technical constraints | STA COM, no exec tool, licenses | In-process dispatcher on the application thread; our own tool surface stays curated (no exec tool of ours; the MCP toolset for general chat is the read-only subset); CLI profiles deny writes through a read-only sandbox; SwpilotCLI reimplemented, not copied; xterm.js and MiniTerm are MIT | **PASS with a documented exception**: the generated Codex profile enables that CLI's own read-only shell, which is generic command execution. See Complexity Tracking. |
| Development workflow | Spec Kit cycle | This document; tasks.md follows | PASS |

Post-design re-check: one documented exception (Codex's read-only shell), recorded in
Complexity Tracking below. No other violations.

## Project Structure

### Documentation (this feature)

```text
specs/002-task-pane-assistant/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── README.md
│   ├── chat-api.md                 # loopback HTTP + SSE
│   ├── chat-events.schema.json     # uniform event stream
│   ├── pane-host-messages.md       # WebView2 page <-> add-in
│   ├── cli-profiles.md             # generated Codex/Gemini restriction profiles
│   ├── mcp-toolset.md              # read-only toolset for general chat
│   └── settings.schema.json        # per-user settings file
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
reviewer/src/swreview/
├── agent/
│   ├── providers/
│   │   ├── __init__.py             # AgentProvider protocol, AgentEvent, ToolSpec, registry
│   │   ├── schema.py               # TypeAdapter + docstring -> JSON schema; strictify(); gemini_adapt()
│   │   ├── openai_provider.py
│   │   ├── gemini_provider.py
│   │   └── fake.py
│   ├── runner.py                   # drives AgentProvider; multi-turn; evidence answers
│   └── settings.py                 # provider settings model + env precedence + redaction
├── tools/registry.py               # RecordedTool without anthropic; (payload, is_error)
├── chat/
│   ├── server.py                   # starlette app: sessions, messages, events (SSE), dispositions
│   ├── sessions.py                 # ChatSession state, events.jsonl writer
│   └── __main__.py                 # `swreview chat serve --port 0` prints {port, token}
├── mcp/
│   ├── server.py                   # stdio MCP server over the read-only toolset
│   └── chat_log.py
└── cli.py                          # --provider/--model; chat serve; mcp

extractor/SwReview.AddIn/
├── SwReviewAddIn.cs                # hosts TaskPaneControl; starts/stops backend + tool service
├── TaskPaneControl.cs              # tabs: Review (WebView2), Terminal (WebView2 + ConPTY), Actions
├── Review/
│   ├── ReviewPage/                 # vendored HTML/JS/CSS for the chat page (no framework)
│   ├── ReviewHost.cs               # page<->host messages; backend client; Show in SOLIDWORKS
│   └── BackendProcess.cs           # start python backend, read {port, token}, health, stop
├── Terminal/
│   ├── ConPty.cs                   # P/Invoke pseudo-console
│   ├── TerminalSession.cs          # process + pipes + resize
│   ├── TerminalPage/               # xterm.js vendored + glue
│   ├── CliLocator.cs               # find codex/gemini, version check
│   └── CliProfileWriter.cs         # generate restriction profiles per launch
├── ToolService/
│   ├── InProcPipeServer.cs         # pipe reader thread -> BeginInvoke onto app thread
│   └── ToolServiceHost.cs          # SwScope + SwBridgeDispatcher wiring, secret, log
└── Settings/
    ├── UserSettings.cs             # %APPDATA%\SwReview\settings.json, DPAPI
    └── Redaction.cs

extractor/SwReview.Extractor.Console/Serve/   # unchanged; dispatcher moves to Extractor? no:
                                              # SwBridgeDispatcher, BridgeProtocol move to
                                              # SwReview.Extractor/Bridge/ so the add-in can
                                              # reference them without the console project
```

**Structure Decision**: The dispatcher and protocol classes move from the console project
to the extractor library so both hosts share them (the console keeps `PipeServer` and its
STA worker; the add-in adds `InProcPipeServer` that marshals to the application thread).
The chat page and terminal page are plain vendored HTML/JS with no build step, embedded as
content files next to the add-in DLL.

## Phase 0: Research

Completed in [research.md](research.md): SwpilotCLI mechanism (R1), two runtimes (R2),
provider layer (R3), CLI restriction (R4), terminal embedding (R5), in-process tool service
(R6), chat transport (R7), secrets (R8), MCP toolset (R9), testing (R10), open risks.

## Phase 1: Design

Completed: [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md).

Key design points tasks must honor:

1. **One provider protocol.** `AgentProvider.run(...)` is the only way the runner talks to
   a model. Adapters own history format, tool encoding, effort mapping, streaming, and
   error mapping. The runner owns step budget, recording, evidence requests, session
   finalization, and multi-turn.
2. **Schema generation without the SDK.** `providers/schema.py` produces one canonical JSON
   schema per tool from the function signature and docstring; `strictify()` (OpenAI) and
   `gemini_adapt()` derive provider forms. A test compares every tool's canonical schema with
   the feature 001 contract table.
3. **Uniform events.** `chat-events.schema.json` is produced by the runner and consumed by
   the pane, the CLI's verbose output, and `events.jsonl`. No provider-specific event leaks
   past the adapter.
4. **In-process tool service.** The add-in hosts the dispatcher; every SOLIDWORKS call runs
   through `BeginInvoke` on the Task Pane control, then through `SwGate` as today. The
   console `serve` command is unchanged and remains the headless path.
5. **Profiles regenerated every launch.** `CliProfileWriter` writes a complete Codex config
   home and the Gemini settings and policy files under the run folder and points the CLI at
   them through its config-home environment variable (`CODEX_HOME` for Codex; the equivalent
   for Gemini is still to be verified), never relying on the engineer's global files.
   `--profile swreview` on its own cannot work, because Codex resolves profiles out of its
   own config home and fails outright when the named profile is absent; the engineer's Codex
   sign-in is preserved by copying `auth.json` into the generated home.
   `contracts/cli-profiles.md` is normative for the exact keys and arguments.
6. **Secrets never leave the process boundary in the clear.** Keys travel to the backend as
   environment variables of the child process; redaction applies to every log line and error
   text; the run folder never contains a key.
7. **General chat cannot create findings.** The MCP server registers only the read-only
   subset; the check tools and `record_drawing_finding` are absent from it.

## Delivery order (maps to user stories)

| Order | Story | Deliverable | Needs SOLIDWORKS |
|-------|-------|-------------|------------------|
| 1 | Foundational | Provider protocol, schema generation, OpenAI and Gemini adapters, fake provider, runner port, `--provider`, anthropic removed | No |
| 2 | US2 | Settings model, DPAPI store, settings section, env precedence, redaction | No |
| 3 | US1 | Chat backend (HTTP + SSE), events, Review tab page and host, extraction on Review, findings cards, dispositions, evidence answers, follow-ups | Show in SOLIDWORKS needs it |
| 4 | US4 | Dispatcher moved to the library, in-process pipe server, tool service host, backend lifecycle | Yes |
| 5 | US3 | ConPTY, terminal page, CLI locator, profile writer, MCP server, chat log | CLIs installed |

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| OpenAI strict schema rejects a generated tool schema | T006 asserts the strict-mode rules locally for every registered tool, including that no object is left with `additionalProperties: true` or with zero properties; T018a makes one real, key-gated call per tool group early in Phase 2. A recorded `respx` exchange replays a body we authored ourselves and can never show that the API accepts a schema, so it is not the evidence for this risk. Fall back to non-strict with server-side validation only if a specific tool cannot be expressed |
| Gemini renames or truncates tool names | Server name `swreview`, names kept under 60 characters, and the startup listing check: T061a tests the parser against fixtures, T062 implements it as a gate that refuses to start the terminal on a mismatch |
| ConPTY under the SOLIDWORKS message pump misbehaves | ConPTY tests against `cmd.exe` in xUnit, including a `.cmd` shim (the Gemini CLI ships as `gemini.cmd` and `CreateProcess`, which ConPTY requires, cannot execute one directly) and an output-coalescing bound; early workstation check in quickstart Scenario 3; SetParent never used |
| Codex profile ignored, or the named profile is absent from the engineer's config | Own the whole config home: `CODEX_HOME=<run_dir>/.swreview-cli/codex-home` with the generated `config.toml` and a copied `auth.json`, plus `-c` overrides for the five scalar restriction keys; never rely on the user or project config (contracts/cli-profiles.md) |
| Backend process orphaned on SOLIDWORKS crash | Job object with kill-on-close for the backend and the CLI processes |
| Two SOLIDWORKS windows collide on ports or pipes | Port 0 and a GUID-suffixed pipe name per add-in instance |
| Keys leak through exception messages from SDKs | Redaction filter applied at the logging sink and before any error reaches the page; `audit-secrets` carries provider-shaped detectors so it is not vacuous when run from a shell that holds no key |
| Model- or document-authored text injected into the Review page, which holds the backend token and the whole host message surface | Untrusted strings inserted as text only, a strict CSP on both pages, navigation blocked outside the virtual host, and a test that feeds hostile strings through a finding title, a recommended action and a tool summary (T042a) |
| A settings save or a backend restart destroys a live chat | `settings.save` is refused while a turn is running, and any backend shutdown finalizes every live chat with an ended time before exiting (chat-api.md) |

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why needed | Simpler alternative rejected because |
|-----------|------------|--------------------------------------|
| `[features] shell_tool = true` in the generated Codex profile, against the constitution's Technical Constraints ("Generic code execution tools ... MUST NOT be exposed to the agent. Expose a curated set of inspection operations") | FR-021 and US3 acceptance scenario 3 are written around a shell that the sandbox confines; Codex's agent loop is built around its shell tool, and research R4 records that `apply_patch` has no off switch and is blocked by the sandbox rather than by configuration. Disabling the shell is unverified and risks a Terminal tab that cannot work at all. | The simpler alternative - MCP resources (`swreview://package/summary`, `swreview://report`) plus a narrow read-only run-folder file tool - does not reach `captures/`, `chat-log.jsonl`, `events.jsonl` or `session.json`, and would mean reimplementing file reading the CLI already has. The exception is bounded: read-only sandbox, `approval_policy = "never"`, `web_search = "disabled"`, unelevated Windows sandbox, run folder as working directory, and it grants the model no privilege the engineer lacks on their own workstation. The Codex/Gemini asymmetry is deliberate: the Gemini policy denies `run_shell_command` outright because that loop does not need it. |
