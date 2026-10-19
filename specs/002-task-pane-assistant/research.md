# Research: Task Pane Assistant

**Feature**: `002-task-pane-assistant` | **Date**: 2026-09-13 | **Plan**: [plan.md](plan.md)

Phase 0 output. Research was performed by three Opus subagents (SwpilotCLI mechanism; Codex
and Gemini CLI embedding, MCP, and restriction; OpenAI and Gemini SDK tool calling) plus
probes of the development machine. All web sources are as of 2026-09-13; none carried a
version stamp.

## R1. What SwpilotCLI's Task Pane actually is

**Finding**: At commit `5824b367` the Task Pane is a WinForms `UserControl` shown through
`CreateTaskpaneView3` and `DisplayWindowFromHandlex64`. For the plain shell it hosts
WebView2 with xterm.js over a ConPTY pseudo-console (`CreatePseudoConsole`, bytes to the
page as base64, keystrokes back through `postMessage`). For `claude` and `codex` it spawns
a real console window and reparents it with `SetParent`, a hack that races on `FindWindow`
and needs `taskkill /T /F` on shutdown. The add-in exposes no tools; the CLI runs 36
`net8.0-windows` console EXEs through Bash, each re-attaching to SOLIDWORKS through the
running object table. There is no chat transcript widget, no API call, no approval gate,
and the README recommends disabling the CLI's sandbox.

**Decision**: Reimplement the ConPTY plus xterm.js mechanism (Microsoft's MiniTerm sample
and xterm.js are MIT) and run the CLI through the pseudo-console instead of reparenting a
window. Copy no files: the SwpilotCLI license permits internal use but forbids
redistribution and derivative shipping.

## R2. Two runtimes in one pane

**Decision**: The Review tab is our own WebView2 chat page fed by the Python runner; the
Terminal tab embeds the engineer's Codex or Gemini CLI. Review needs curated tools, step
recording, findings, and dispositions, which a terminal cannot render; general chat wants
the CLI's own features and sign-in, which we should not rebuild.

**Alternatives considered**: terminal only (findings as text; no cards, no dispositions);
chat panel only driving general chat through the API (loses CLI sign-in, browsing, files);
driving the CLIs in JSON mode from the chat panel for review (`codex exec --json`,
`gemini -p -o stream-json`; rejected because curation would depend on per-seat CLI config
and the system prompt is replaced wholesale, though it remains a viable later backend).

## R3. Provider layer for the review loop

**Decision**: `AgentProvider` protocol with `run(system, messages, tools, effort, max_steps,
on_event)`; adapters `OpenAIProvider` and `GeminiProvider`; `FakeProvider` for tests. Tool
schemas come from `pydantic.TypeAdapter(fn).json_schema()` merged with a Google-style
docstring parser for parameter descriptions, so the tool modules keep their current shape.
`RecordedTool.call` returns `(payload, is_error)` and each adapter encodes it.

**Correction found while reviewing the plan**: two tool parameters are free-form maps -
`mark_coverage(scope: dict[str, Any])` and `bridge_interference(settings: dict[str, Any])`.
Generated with the repo's pydantic they yield `{"type": "object", "additionalProperties":
true}` with no `properties`. `strictify()` as specified would turn each into an object that
admits no keys at all, and `CoverageScope.model_validate({})` succeeds because every field
defaults to empty, so every coverage item the model recorded would come back with an empty
scope and no error anywhere - silent loss of exactly the information constitution VI requires
the report to carry. Strict mode has no representation for an arbitrary-key object, so the
fix is upstream of the strictifier: both parameters get explicit models (`CoverageScope`,
a new `InterferenceSettings`) before the port, and T006 asserts that no generated tool schema
contains an object with `additionalProperties: true` or an object with zero properties.

**OpenAI** (Responses API, `openai` SDK): tools are flat `{type: "function", name,
description, parameters, strict: true}`; strict requires `additionalProperties: false` on
every object, every property in `required`, optional as `["T", "null"]`. Loop keeps the
full `input` list and appends `response.output` verbatim (reasoning items must be echoed
back with tool outputs), then `function_call_output` items with `call_id`. Prompt goes in
`instructions`. Effort in `reasoning={"effort": ...}` (levels vary by model). Streaming
events `response.output_text.delta`, `response.function_call_arguments.delta`,
`response.output_item.done`, `response.completed`. No auto-run helper in `openai-python`;
the Agents SDK is pre-1.0 and not used. Errors: `AuthenticationError`, `RateLimitError`,
`APIStatusError`, `APIConnectionError`, `APITimeoutError`.

**Gemini** (`google-genai`): `types.FunctionDeclaration(parameters_json_schema=...)` accepts
standard JSON Schema (strip `additionalProperties` and `$defs`); `automatic_function_calling
=AutomaticFunctionCallingConfig(disable=True)` is mandatory so our recording loop owns each
call; function responses are `Part.from_function_response` in a `role="tool"` content and
must carry the call `id` on 3.5+ models; thinking through `thinking_config.thinking_level`
(2.5 models use `thinking_budget`); `system_instruction` in the config; streaming via
`generate_content_stream` with events synthesized by the adapter. The newer
`client.interactions` API mirrors the Responses shape and is kept as a possible second
adapter. Errors: `google.genai.errors.ClientError`, `ServerError`, `APIError`.

**Auth**: `OPENAI_API_KEY` and `OPENAI_BASE_URL`; `GEMINI_API_KEY` or `GOOGLE_API_KEY`
(`GOOGLE_API_KEY` wins if both set); Gemini enterprise via `genai.Client(enterprise=True,
project=..., location=...)` with `vertexai=True` as the legacy alias. Settings from the pane
take precedence over environment variables and the source is reported.

**Models**: defaults `gpt-5.6` and `gemini-3.5-flash`, verified against each provider's
model list at settings time; the research listed `gemini-3.8-flash` through `gemini-2.5`
and OpenAI reference examples on `gpt-5.6` and `gpt-5.5`.

## R4. Restricting the CLIs for general chat

**Codex** (`$CODEX_HOME/config.toml`, default `~/.codex/config.toml`, profile selected with
`--profile`): `sandbox_mode = "read-only"`, `approval_policy = "never"`, `web_search = "disabled"`,
`[features] shell_tool = true` (read-only shell allowed for reading the run folder),
`[mcp_servers.swreview] command/args`, `enabled_tools` allowlist, `startup_timeout_sec`,
`tool_timeout_sec`. `apply_patch` has no documented off switch; the read-only sandbox
blocks its writes. Project-scoped `.codex/config.toml` loads only for trusted projects.
Tools are exposed as `mcp__<server>__<tool>` (unverified in docs; from issue reports).
Windows sandbox is native (`[windows] sandbox = "elevated" | "unelevated"`); the development
machine's config currently routes Codex through WSL, which the generated profile must
override for the pane.

**Verified on the workstation (Codex CLI 0.115.0), after the plan review**: `--profile` names
a profile inside the config home and there is no flag that points Codex at an arbitrary
config file, so a TOML file written into the run folder is never read; `codex exec --profile
swreview` on a machine whose config has no such profile fails with `config profile 'swreview'
not found`, and `-c key=value` cannot express a `[mcp_servers.*]` table. `CODEX_HOME` pointed
at a generated home does resolve the profile and start - but it also relocates `auth.json`, so
the same run fails `401 Unauthorized` unless the engineer's credential is copied into that
home. The generated-config-home approach with auth passthrough is therefore what
`contracts/cli-profiles.md` specifies.

**Gemini** (`~/.gemini/settings.json` and `~/.gemini/policies/*.toml`): `mcpServers.swreview`
with `command`, `args`, `cwd`, `env`, `timeout` (default 600000 ms), `includeTools`; tools
are named `mcp_{server}_{tool}` truncated at 63 characters, so the server name must not
contain underscores. Policy engine: a deny-all rule at low priority plus an allow rule for
`mcpName = "swreview"` at high priority; run in `--approval-mode plan`. The semantics of
`tools.core: []` are unverified, so the policy rule is the enforced half. **No
settings-directory override was established by this research**: `GEMINI_CLI_HOME` in
`contracts/cli-profiles.md` is an unverified placeholder, and neither `mcp.allowed`,
`security.disableYoloMode`, `general.defaultApprovalMode`, `context.fileName`, the per-server
`trust` key nor a `toolName = "*"` wildcard deny rule came from a verified source. The Gemini
CLI is not installed on the development machine, so all of it must be confirmed by the spike
task before the byte-for-byte profile test asserts any of it.

**Claude Code** is documented for completeness only (`--disallowedTools`,
`--append-system-prompt`, `-p --output-format stream-json`) and is not used.

## R5. Terminal embedding

**Decision**: ConPTY pseudo-console (`CreatePseudoConsole`, `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`)
hosted by the add-in, output forwarded to xterm.js in WebView2 as base64 chunks, input and
resize sent back through `postMessage`. Both CLIs are ordinary console applications and run
under ConPTY; Windows 10 1809 or later is required and Windows 11 is the baseline. Gemini
needs Node 20 or later (22 recommended). Known open issues: Codex TUI ANSI leaks and no
mouse scroll in some terminals; Gemini's Ink renderer reflows imperfectly on width changes.
No minimum terminal size is documented; the pane enforces a sensible minimum.

## R6. In-process tool service

**Decision**: Host `SwBridgeDispatcher` inside the add-in. Requests arrive on a pipe reader
thread and are marshalled to the SOLIDWORKS application thread with `Control.BeginInvoke`
on the pane control, serialized through the existing queue. The console `serve` command
stays for headless use. Rationale: the add-in already owns the `ISldWorks` pointer on the
application thread; a second STA worker would cross apartments on every call.

Two bounds the marshalling needs, because the application thread is the same thread that runs
modal dialogs and rebuilds: (a) the wait on the marshalled call is bounded, and on expiry the
request answers `{"status": "error", "error": "the SOLIDWORKS thread did not answer within
Ns - a dialog may be open"}` while the queued delegate is prevented from writing a stale
response later; the bound is generous (a live interference run legitimately takes seconds) and
longer than any client-side timeout, so the two sides cannot disagree about whether a call is
still running. (b) `Control.BeginInvoke` throws when the handle is not created or has been
destroyed during unload, so `IsHandleCreated` / `IsDisposed` are checked first and answer a
clean `error` rather than letting the throw land on the pipe reader thread.

The pipe is created with an explicit `PipeSecurity` granting `ReadWrite` to the current user's
SID only: .NET Framework 4.8 has no `PipeOptions.CurrentUserOnly`, and a default security
descriptor leaves a named pipe readable by any local process.

## R7. Chat transport

**Decision**: The add-in starts the Python backend (`swreview chat serve --port 0`) and reads
`{port, token}` from its first stdout line. The page calls loopback HTTP with the token in a
header; events stream over server-sent events. Rationale: single user, one direction of
streaming, trivially testable with an in-process HTTP client; WebSocket adds nothing here.

Three consequences the contract now spells out. uvicorn's default logging configuration sends
the **access** log to stdout, which would corrupt the handshake line and can block the child
once the parent stops draining the pipe, so both handlers are configured onto stderr. The
page and the backend are different origins (virtual host vs `http://127.0.0.1:<port>`), so the
server answers unauthenticated `OPTIONS` preflights and echoes the exact page origin; it never
uses `*`, because the loopback port is reachable from any browser on the workstation.
`EventSource` cannot set `Authorization` or `Last-Event-ID`, so the page reads the stream with
`fetch` plus a `ReadableStream` reader and the token never appears in a URL.

## R8. Secrets

**Decision**: Keys are stored with Windows DPAPI (`ProtectedData`, current-user scope) in
`%APPDATA%\SwReview\settings.json`; the add-in passes the key to the backend process through
its environment, never through arguments or files; logs redact any value that matches a
configured key. Rationale: FR-015 and the constitution's evidence rules.

## R9. Tool server for the CLIs

**Decision**: `swreview mcp` runs a stdio server with the `mcp` Python SDK exposing the
read-only subset (package query tools, measurement tools, `request_capture`, bridge capture
and measure). Names stay under 60 characters; the server name is `swreview`. Each call is
appended to `chat-log.jsonl` in the run folder. The check tools that create findings are not
exposed to general chat (FR-025).

## R10. Testing

- Python: adapter tests with `respx` for OpenAI and a stubbed client for Gemini; runner tests
  on `FakeProvider`; chat server tests with an in-process HTTP client; MCP server tests with
  the `mcp` client over in-memory streams; schema generation tests comparing the generated
  strict schema with the current contract per tool.
- C#: page-to-host message contract tests (JSON), ConPTY session tests against `cmd.exe`
  (echo, resize), in-process dispatcher tests with the existing fakes, settings encryption
  round trip.
- Manual: quickstart Scenario 7 on the workstation.

## Open questions carried as risks

1. Codex `mcp__server__tool` naming and the `enabled_tools` allowlist are documented only
   partially; verify on first launch by listing tools in the CLI.
2. Gemini policy engine precedence with `--approval-mode plan`; verify that a write is
   refused and an MCP call is allowed.
3. ConPTY inside a Task Pane hosted by SOLIDWORKS (message pump owned by SOLIDWORKS): verify
   input latency and resize behavior early.
4. OpenAI strict schema for tools whose parameters include `SourceRef` objects with nullable
   fields; the strictifier must produce a schema the API accepts. A recorded `respx` exchange
   cannot show this - it replays a body we wrote ourselves. The evidence is T006 (the strict
   rules asserted locally for every tool) plus T018a, one real key-gated call per tool group,
   run early in Phase 2 rather than at Polish time.
5. The Gemini settings-directory override, and every Gemini settings key not listed in R4
   above, are unverified; the spike task (T055a) confirms them on the installed CLI and
   records the version, before T056 asserts any of them byte-for-byte. Until then the terminal
   fails closed.
6. Free-form `dict[str, Any]` tool parameters cannot be expressed in OpenAI strict mode at
   all (see the correction in R3); they are replaced with explicit models before the port.

## Owner decisions after the build

### 138A. The session records the key saved in the pane as `settings` (2026-10-19)

- **Question**: a review started from the Task Pane recorded `key_source: env` in
  `session.json` even when its key was the one the engineer saved in the pane's settings. The
  pane itself showed `settings` (`ReviewHost.SendInit` and `SendSettings`), and
  `ResolvedApiKey.Source` (`UserSettings.cs`), the comment on `BackendClient.KeyVariablesFor`,
  001 `contracts/cli.md` and the docstring of `reviewer/tests/unit/test_provider_settings.py`
  all said the session records `settings`. The field is there so that whoever reads a run
  knows which credential to revoke (FR-015, R8). The cause: only the add-in reads
  `%APPDATA%\SwReview\settings.json`. `UserSettings.ResolveApiKey` takes the saved key first
  and `BackendClient.StartOptions` copies it into the backend's environment under its
  provider's variables; the reviewer reads no settings file, so `ProviderSettings.from_env`
  found the key in the environment, and since no caller passes it an `api_key` (`cli.py` and
  `benchmark/runner.py` twice each, `chat/server.py` twice), every key it found was `env`.
- **Options** for the marker the add-in passes, which is not a secret: A: a `chat serve`
  start argument. B: an environment variable in the child's block, beside the key.
- **Chosen**: A, `--settings-key-provider <provider>`. `BackendClient.StartOptions` sets it
  when the key it copied is the saved one; `chat/server.py` `_settings` hands it to
  `ProviderSettings.from_env(settings_key_provider=...)`, which records that provider's
  environment key as `settings`. Why:
  - It matches how `BackendClient` passes the backend's own options. `--run-root` and
    `--allow-origin` are `BackendStartOptions` properties that `BackendProcess.Arguments`
    renders; the variables it writes into the environment (`OPENAI_BASE_URL`,
    `GOOGLE_GENAI_USE_ENTERPRISE`, the Gemini project and location) configure the provider
    SDKs, which `from_env` reads on every path, the command line included. The marker
    belongs to the server alone.
  - Only `chat serve` defines it, so the command line cannot be told it: `review`,
    `benchmark run` and any later command record `env` or `none`. An environment variable
    would be inherited from SLDWORKS.exe or a developer's shell, and by anything the backend
    starts, and would claim `settings` wherever it leaked unless the add-in overwrote it on
    every start. Typing the argument by hand makes the claim, as typing `--allow-origin`
    does; it is the add-in's statement to make.
  - It names a provider, not a source. The add-in writes the saved key under its own
    provider's variables only, so another provider's key in the same environment is the
    workstation's. A session for another provider happens when a provider change is saved as
    a turn starts (the restart meets `TurnRunning` after the new settings are written, and
    the backend keeps the environment it was started with), and on the Remodel route, which
    resolves the default provider. Those sessions record `env`.
  - The key stays in the environment; the argument carries none (AGENTS.md rule 3).
- **Edge cases**: a saved key and an environment key both present: the saved key wins
  (`ResolveApiKey`), is copied over the inherited one and its provider is named, so
  `settings`. No saved key: nothing is named, so `env`. A stored key this Windows account
  cannot decrypt falls back to the environment's key, and nothing is named. The scripted
  provider reads no key, so none is copied or named. The marker with no key in the
  environment: `none`, and the existing refusals are unchanged (the OpenAI adapter's
  `ValueError` on a ticked start, `409 NoCredential` on Send). `key_source` keeps its three
  values in the model and in the contract.
- **An unknown value is refused, not read as `env` with a warning.** It means the add-in and
  the backend disagree about what the marker says (two versions, or a hand-typed command
  line), so the backend cannot tell where its key came from, and `env` would be a guess that
  names the wrong credential exactly when the key was the saved one: the defect this
  decision removes. The refusal is a usage error (exit 2) before the handshake. It costs
  nothing on a matched install, comes before any session exists, and reaches the engineer as
  a backend that would not start, whose log names the values the option takes. It holds the
  other way round too: an older reviewer started by this add-in with a saved key refuses the
  option it does not know rather than silently recording `env`. The add-in and the reviewer
  ship from one repository and are updated together; a mismatched pair fails at start
  instead of writing a record that names the wrong credential.
- **Tests**: T069 (reviewer) and T071 (add-in) in [tasks.md](tasks.md), each written first.

### 139A. The pane's strings name the tabs it shows (2026-10-19)

**Decision**: every user-facing string in the add-in that names the pane's tabs names the tabs
the pane shows, and follows `TaskPaneControl.AskTabShown` if it is turned on again.

- Step 3 of the step strip reads `3 Review` while the Ask tab is hidden and `3 Review or Ask`
  when it is shown. The strip is told the captions (`StepStrip(IReadOnlyList<string>)`): the
  pane passes those of the Review and Ask tabs that its tab list holds.
- The runtime-missing fallback panel opens with a sentence built from the tab list: every tab
  the pane shows except Extract, which is WinForms and still works. Today it reads "The
  Microsoft Edge WebView2 runtime is not available, so the Review, Model check, Remodel and
  Standards tabs cannot be shown. The Extract tab still works."
- The Extract evidence tooltip ends "The reviewer reads this file instead of the live model."
  while the Ask tab is hidden, and with its earlier sentence, "The reviewer and the Ask tab
  read this file instead of the live model.", when it is shown. This one is an explicit
  choice on the switch (`ActionsPanel.DumpToolTipFor`) rather than built from captions,
  because "the reviewer" is not a tab and the verb follows the count; both sentences are
  pinned by a test.

**Why**: the pane has shown five tabs since 2026-09-19 (`a35f457`): Review, then Ask only if
`AskTabShown`, which is false, then Extract, Model check, Remodel and Standards. Three strings
still named Ask, and the fallback sentence, written out by hand when the pane had three WebView2
tabs, named the hidden Ask and left out Remodel and Standards, although both render that same
panel when their page cannot load. A string that sends an engineer to a tab that is not there
is the question these strings exist to answer (FR-001). Built from the tab list, the step and
the sentence cannot drift from it again.

**Evidence** (at `304092c`):

- The three strings: `TaskPaneControl.cs:1182` (the fallback sentence, "the Review, Ask and
  Model check tabs cannot be shown"), `:1469` (the step, "3 Review or Ask"), `:1603` (the
  tooltip, "The reviewer and the Ask tab read this file"). The first two are the ones the
  decision names; the third was found by the search below and is held by the sweep it adds.
- Every other string literal in the add-in's C# that names a tab names a tab the pane shows,
  and the pages' scripts and HTML name tabs only in comments. The Ask tab's own Codex
  instructions (`Terminal/Profiles/codex-instructions.md`) name it, and reach an engineer only
  through that tab.
- `docs/review-backlog.md` recorded the fallback sentence three times (feature 004 offline part
  3, twice; feature 006 round D); those entries are marked resolved.
- At the pane's minimum width (236 px of label, Microsoft Sans Serif 8.25 pt) the new sentence
  wraps to the same four lines as the old one (`TextRenderer.MeasureText`), so the fallback note
  is no taller than before.

Tests, written first and run against the old strings (the new members stubbed to return them):
16 failed - in `TaskPaneGuidanceTests`, the six step-strip literals, the Extract evidence
tooltip, and the new `TheThirdStepNamesTheAskTabOnlyWhenThePaneShowsIt`,
`AStepStripToldNoTabForTheThirdStepIsRefused`, `TheExtractTooltipNamesTheAskTabOnlyWhileThePaneShowsIt`
and `NothingThePaneShowsNamesTheHiddenAskTab`; in `WebViewFallbackTests`, the four fallback
tests and the new `TheFallbackSentenceNamesTheTabsItIsGivenInTheirOrder` - and all pass after
it. `contracts/pane-host-messages.md` ("The step strip") carries the dated amendment. FR-001
still names an Ask tab and the step "review or ask"; it predates the 2026-09-19 decision that
hid the tab and is not amended here.

### 143A. The add-in restarts the backend when the turn ends, as the pane says (2026-10-19)

- **Question**: `settings.save` asks whether a turn is running before it writes anything, and
  the add-in's backend supervisor asks again before it stops the old process. A turn that
  starts in between - a follow-up, an answer or a Send, which the page posts to the backend
  directly - leaves the settings written and in force in the host and the restart refused, and
  the Review tab says
  "the settings are saved; the backend restarts when the running turn ends." No code restarted
  it. The backend kept the environment it was started with, and every review started afterwards
  ran on it: with the new provider, model and effort, which `POST /sessions` carries from the
  host, and the old key and endpoint, which come from the backend's environment - the session
  for another provider that 138A records as `env`.
- **Decision** (owner decision 143A, "Make it restart"): the add-in makes that restart once no
  turn is running, with the settings in force then, and starts no turn on the old backend in
  between.
- **How**:
  - `Review/DeferredRestart.cs` holds the restart a turn refused. A watcher looks every second
    (`ReviewHostOptions.RestartPoll`) and restarts as soon as nothing holds the restart back,
    through `IBackendClient.Restart` and so through `BackendSupervisor.Restart`, which asks again
    before it stops anything. What holds it back (`ReviewHost.RestartHeldBack`) is a turn - the
    question the save's check asks, `AnyTurnRunning`, read strictly: a question the backend does
    not answer counts as a turn, and only an answer, a `state` or `UnknownChat`, says a chat has
    none - or a remodel run in progress (`ReviewHostOptions.BackendBusy`), which the restart
    would end. With no backend process at all nothing holds it back, and the restart brings one
    back. The restart reads the settings and resolves the key only when it is made. One lock is
    held for the whole of any restart the host makes, and whoever takes it asks again whether a
    restart is still waiting, so however many ask the backend restarts once. `settings.save`'s
    own restart, when no turn runs, goes through the same lock and is the restart for the
    settings in force, so a restart still waiting is dropped.
  - A new review makes the restart first: `BackendReady`, `ContextReady` and
    `CreateReviewSession` - the one place every review's session is created - make it or wait
    for the one being made, and are refused `TurnRunning` while what holds it back still runs or
    `BackendUnavailable`, with the failure, when it fails. The engineering context requests that
    check the backend through `ContextReady` (`context.prepare`, `context.selection`) do the
    same.
  - A page call that would start a turn - `POST /sessions/{chat_id}/messages`, `/send`,
    `/evidence` or `/evidence/{request_id}` - is for a chat of the backend about to be replaced,
    so while a restart waits the pane's proxy asks the review host
    (`TaskPaneOptions.PageTurnRefusal`, `ReviewHost.PageTurnRefusal`) and never sends it: while
    what holds the restart back runs it is refused `TurnRunning`; otherwise the restart is made,
    or waited for, and the call is answered `UnknownChat`, as the restarted backend would answer
    it - or `BackendUnavailable` when that restart failed and there is no backend. Stop,
    dispositions and the timing are never held: Stop must reach the backend while a turn holds
    the restart back, and a disposition sent before the restart is recorded, where one held
    until after it would only be refused.
  - The page is told with `backend.restarted {}`, clears the banner that carried the sentence,
    and asks `ready` again for the new port and token, as it does after a save that restarted
    at once - once more after an `init` already on its way, which the host may have read while
    there was no backend, and the restart is believed then too, so a live waiting review on
    screen is restored from its folder (feature 015 FR-042). A failed restart is reported as a
    failed start is - `status {stage: "error"}` with its message - and not retried: the next
    save is the retry, as after any failed start.
  - A page that asks `ready` again while it reads a stream asks for that stream again, from the
    last event it showed, on the same backend. The host's `ready` closes the reader it holds for
    the page, as a reload needs; and the save a turn started during re-inits the page while
    that turn runs, so without this the page never saw the turn end and stayed "running", with
    Review disabled.
  - The words: the sentence is kept, true now, and pinned word for word. The refusal a save
    meets when the turn is seen before anything is written (`TurnRunningException`) said
    "settings are saved once it finishes", which no code did; it now says the settings were not
    saved, and still tells the engineer to press Save again.
- **Why**:
  - The sentence is the pane's promise, and a promise no code keeps is the defect: a key the
    engineer replaced or removed stays in use, and a provider switch runs with the other
    provider's environment, until the next save that happens to see no turn.
  - The watcher asks the backend rather than reading the event stream. The host reads only the
    stream of the chat on screen and parses nothing of it (`EventStreamPump`, and
    `contracts/pane-host-messages.md`, "nothing is parsed"), the page may be closed or showing
    another review, and `turn.ended` is written before the backend settles the chat, which is
    what the restart's own check reads. Asking is the one source that covers every chat however
    the turn ended, and it costs one `GET /sessions/{chat_id}` per review per second, and only
    while a restart waits.
  - A new review must not run on the old backend, or the save is in force in the host and not
    in the backend: the case 143A exists to end. Making the restart from the request rather
    than waiting for the watcher closes the second in which the turn has ended and the watcher
    has not looked yet; and none of these callers waits for a turn - only for a restart already
    being made, which the backend's own start timeouts bound.
  - The proxy's question covers the calls the host never sees. The page enables a follow-up the
    moment it reads `turn.ended`, before the backend has settled the chat and so before the
    watcher can see the turn has ended, so a quick follow-up or a Send could otherwise start a
    turn on the old backend and put the restart off for another turn. The restart ends that
    chat in any case, as every settings restart does, so the call is answered as the restarted
    backend would answer it rather than sent where it would run with the settings the engineer
    replaced.
  - The sentence needs no change: it is now what happens. The up-front refusal's old sentence
    made the kind of promise 143A removes, in a smaller place, so it is corrected with the
    behaviour.
- **Edge cases**, each pinned by a test (T074, T076, T078, T080, T082):
  - However the turn ends - normally or stopped (`ended`), in an error (`failed`), asking the
    engineer (`waiting_engineer`), or a Send that failed back to waiting (`awaiting_send`) - the
    chat leaves `running`, and the restart is made. The contract names none of them as a reason
    to keep the old settings; `waiting_engineer` is "no turn is running" in data-model section 3,
    as it is to the save's own check, and its questions go with the chat, as they do after a
    save made at that moment.
  - Several saves during one turn - a second gets past the save's check only when that check
    cannot see the turn - restart the backend once, with the last of them.
  - A save when no turn runs is the restart it always was, made at once and announced by its
    reply. One made after the turn has ended is that restart, with its own settings, and drops
    the one that waited; if the watcher gets there first, during that save, the backend is
    restarted twice and the second time with the newer settings. The settings in force are
    always the last saved.
  - A question the backend does not answer never releases the restart; a chat the backend does
    not hold (`UnknownChat`) does not hold it back; with no backend process the restart is made,
    to bring one back.
  - A remodel run in progress holds the restart back as a turn does, and so holds a new review
    back with it.
  - A new review the moment the turn ends restarts the backend first and runs on it with the
    new settings; one made while the restart is being made waits for it; one made while a turn
    still runs is refused `TurnRunning` before anything is extracted, and the restart still
    comes when the turn ends; one whose restart fails is refused with that failure. None is
    dropped: each is answered.
  - A follow-up, an answer or a Send the moment the turn ends makes the restart and is answered
    `UnknownChat`; one while a turn runs is refused `TurnRunning`; with nothing waiting, every
    call goes on as before and nothing is asked.
  - A restart that fails is reported, whatever it threw, with the key masked, and is not tried
    again; the backend is then down, as after any failed start, until the next save.
  - Disposing the host - the add-in unloading - while a restart waits stops the watcher without
    waiting a poll out, and nothing asks or restarts afterwards. The host does not wait for a
    restart being made; `BackendClient.Dispose`, which the add-in calls next, waits for it on
    the same gate - as it already waits for a save's restart or the first start - for at most
    the start's own timeouts, then stops what it started, so nothing outlives the add-in. A page
    that reloads leaves the restart waiting and is told when it is made, and a post to a page
    that has gone is dropped (`TaskPaneControl.PostToPage`), so a pane that closes holds nothing
    open.
  - The 138A marker follows the new settings: the restart is built from the settings in force
    when it is made, so a switch to Gemini saved with a Gemini key starts the backend with that
    key under Gemini's variables and names Gemini as the saved key's provider, and one saved
    without a key, which retires the stored one, names nothing. This ends the first of the two
    cases 138A names for a session of another provider; the Remodel route's remains.
- **Evidence** (at `ca7a720`):
  - The sentence: `extractor/SwReview.AddIn/Review/ReviewHost.cs:1041`, set when
    `IBackendClient.Restart` throws `TurnRunningException` (`:1037`) and posted as
    `status {stage: "error"}` (`:1052`). The check before the save writes anything is `:916`; the
    model-list round trip (`:980`) and the write (`:1026`) come between it and the restart
    (`:1035`).
  - The refusal: `BackendSupervisor.Restart` (`BackendProcess.cs:739`) throws at `:744` when its
    delegate, the review host's `AnyTurnRunning` (`SwReviewAddIn.cs:443`), says a turn runs.
  - Nothing restarted it: the only caller of `IBackendClient.Restart` in the add-in was
    `ReviewHost.cs:1035`, and the only caller of `BackendSupervisor.Restart` was
    `BackendClient.cs:89`.
  - How the host learns a turn has ended: only by asking. `EventStreamPump` passes frames on
    unparsed (`EventStreamPump.cs:22`), and `AnyTurnRunning` (`ReviewHost.cs:610`) reads
    `GET /sessions/{chat_id}` through `BackendClient.IsTurnRunning` (`BackendClient.cs:118`),
    which is `state == "running"` (`:121`). The backend settles a turn as `ended`, `failed`,
    `waiting_engineer` or `awaiting_send` (`reviewer/src/swreview/chat/server.py:2479`,
    `:2483`, `:2485`), after it has rendered the report (`:2505`).
  - The turns the host never sees: `app.js:2283` (a follow-up), `:1297` (Send) and `:2696`
    (the answers), each a `fetch` through the proxy; the follow-up box is enabled again as soon
    as the page reads `turn.ended` (`:2071`).
  - A review after such a save ran with the host's provider, model and effort
    (`ReviewHost.cs:1746`, `:1748`) on the backend started with the old environment, as 138A's
    research noted (`research.md:259` to `:262` at `ca7a720`).
  - The up-front refusal's sentence, `TurnRunningException` (`BackendProcess.cs:697`), says
    "settings are saved once it finishes" while nothing is saved, then or later.
- **Not changed**:
  - For the save's check, and every other caller, `AnyTurnRunning` still reads a question the
    backend does not answer as "no turn" (`docs/review-backlog.md`, the entry on
    `ReviewHost.cs:201`), and the backend's own check reads it so too: a save made while the
    backend does not answer can still restart it under a turn, as before. Only the restart that
    waits reads it strictly.
  - A save made at once while a remodel run is in progress restarts the backend and ends the
    run, as before 143A; and a remodel run started while a restart waits runs with the old
    backend's key. Both are feature 004's to decide.
  - After any settings restart, made at once or afterwards, the review that was on screen keeps
    its live view although the backend no longer holds its chat: a follow-up, an answer or a
    disposition is answered `UnknownChat`. Only a review waiting for Send is restored from its
    folder (FR-042).
  - The other tabs (Model check, Standards, Remodel) keep the port and token of their `init`
    after any settings restart, made at once or afterwards; that is as it was before 143A.
- **Review**: an independent adversarial review of T074 to T079 found that a page re-init
  closed the stream of the very turn that holds the restart back, leaving the page "running";
  that an `init` read while there was no backend hid the restart from the page; that a question
  the backend did not answer could release the restart under a turn; that the restart could end
  a remodel run; and that a call could be told the backend restarted when the restart had
  failed. T082 and T083 fix each, test first.
- **Tests**: T074, T076, T078, T080 and T082 in [tasks.md](tasks.md), each written first.
