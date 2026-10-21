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

### 142A. A Retry replaces only the session its folder holds, and never a check's (2026-10-19)

- **Question**: `POST /sessions` refuses a run folder that already holds a session
  (`events.jsonl` or `session.json`) "unless this request is the Retry that replaces it", and
  lets a start claim the folder a Model check wrote (feature 003 User Story 6 scenario 11;
  feature 007 FR-021). Fixing 139A found three gaps in that rule (`chat/server.py`,
  `_claim_run_dir`): it looked at the folder only when `retry_of` was absent, so any `retry_of`
  claimed any folder under the run root, rotating the session there aside and writing a review
  in its place, a check's included; `retry_of` was never compared with the session the folder
  held, so a Retry could name any chat, or an id no chat ever had; and `is_check_folder` read a
  folder through the rms record, so a Standards check's folder was no check to it. Before the
  change (verified by running it at `ca7a720`):

  | Folder | A start, without `retry_of` | A Retry, any `retry_of` |
  |---|---|---|
  | A Model check's (rms) | claimed: the check's session rotated aside | claimed |
  | The re-modeler's grade, `rms-before/` or `rms-after/` (the rms record `run_rms_check` writes) | claimed, as a Model check's | claimed |
  | A Standards check's | `400 InvalidRunDir`, "already holds a review session; retry it with 'retry_of'" | claimed |
  | A review's | `400 InvalidRunDir` | claimed, whatever chat it named |

- **Chosen** (the owner's option "Fix, test first"):
  1. **A Retry is refused on a check's folder of every family, and so is a start on a
     Standards check's folder**, with one `400 InvalidRunDir` and one wording from both
     routes: "`<run_dir>` holds the `<family>` check that ran in it and no review session: a
     Retry replaces only a review's session, and only a Model check's folder is handed to a new
     review; review into a new run folder". A start still claims an rms check's folder, which
     features 003 and 007 require. `is_check_folder` moves to `checks/rules/run.py`, the
     run-folder machinery every family shares, and asks only whether `check.json` names the
     `session.json` beside it; `checks/rms/run.py` re-exports it. The family comes off the
     record, as `GET /checks/{check_id}` reads it, so a start's exception is the rms family's
     by name rather than by which family's record `is_check_folder` happened to read.
  2. **A Retry claims a folder that holds a session only for the chat that wrote it**
     (`_require_retried`). `retry_of` is a `chat_id` (`contracts/chat-api.md`), which no file
     in the folder records, so the chat must be one this backend holds: none by that id is
     `404 UnknownChat`; one that reviewed another folder, or whose review session a session
     file in the folder does not belong to (`session.json`'s record, the session
     `events.jsonl` opens with), is `409 RunDirInUse`, naming each such file. A folder with no
     session file is claimed by any start, as before.

  After it:

  | Folder | A start, without `retry_of` | A Retry |
  |---|---|---|
  | A Model check's | claimed (unchanged) | `400 InvalidRunDir`, the check's wording |
  | The re-modeler's grade | claimed (unchanged) | `400 InvalidRunDir`, the check's wording |
  | A Standards check's | `400 InvalidRunDir`, the check's wording | the same body |
  | A review's | `400 InvalidRunDir` (unchanged) | claimed for the chat that wrote it; `404 UnknownChat` for a chat this backend does not hold; `409 RunDirInUse` for any other |
  | One that holds no session file | claimed (unchanged) | claimed (unchanged) |

- **Why**: a Retry exists to replace one failed session (FR-028). A check's folder holds no
  review session, and a review's folder holds one, its own chat's, which is the only one a
  Retry may move aside. "As any start is", in the decision's words, holds for a Standards
  check's folder only: a start claims an rms check's folder on purpose, so there a Retry is
  refused and a start is not.
- **Why these errors**: the decision named a start's 400 for a check's folder. For the second
  item `contracts/chat-api.md` named no error, and is amended. Two existing classes were taken
  rather than a new one: every error class needs a next-step sentence in
  `report/review_words_v1.yaml` (`test_review_words.py`), whose labels the add-in's pane
  fixtures carry byte for byte (`test_pane_fixture.py`), and nothing under `extractor/` is
  changed here. `UnknownChat`'s sentence ("This review is no longer held by the backend. Press
  Review to start a new one.") is the engineer's next step after a restart, and `RunDirInUse`
  already says that a folder is another chat's, its sentence ending "or press Review for a new
  one".
- **Edge cases**, each decided and tested in `tests/unit/test_chat_server.py`:
  - a folder holding only `events.jsonl` (its record never written, or removed) or only
    `session.json` (its stream removed): the file it holds decides, and a Retry of its chat
    claims it;
  - a session file that cannot be read, or that belongs to another session: `409
    RunDirInUse` naming the file; nothing is guessed through and nothing moves;
  - a folder already rotated, a Retry of a Retry: only the latest attempt's chat can be
    retried. Naming the attempt it replaced, whose session is `session.1.json` by then, is
    `409`; the latest still rotates its own to index 2;
  - a Model check's folder a review claimed keeps its `check.json`, but the session beside it
    is the review's, so it is no check's folder: the review's own chat retries it there, and
    the check's session stays at index 1;
  - concurrent Retries of one chat: the claim runs on the event loop with no await before the
    folder is reserved, so the second meets the first's reservation or its live chat (`409
    RunDirInUse`, unchanged), and once that one ends, a folder that holds its session (`409`):
    the folder rotates once;
  - case and format of `retry_of`: it is read as a uuid (`_uuid`), so upper case, braces, a
    `urn:uuid:` prefix or no hyphens name the same chat; a value that is no uuid (blank,
    padded, a number, a boolean) is `400 InvalidRequest` before the folder is looked at, and an
    empty string is no Retry, which meets a start's refusal. The ids in the folder's files are
    compared as this backend writes them, as `_rotate_kept` compares them;
  - a start that failed after writing its stream (feature 015's cache or finalization
    failure) registered no chat, so a Retry naming it is `404 UnknownChat` and its stream stays
    where it is;
  - a Retry into a folder holding no session file, naming a chat this backend does not hold -
    the pane's own Retry after a restart - is claimed as before and records no `retry_of`.
- **What it costs**: chats live only in the backend's memory, so a restarted backend (a
  settings save restarts it) cannot tie any folder to a chat, and a Retry that reuses its
  failed chat's folder - a context review's, owner decision 108A - is `404 UnknownChat` after
  one, with nothing moved; the engineer starts a new review. The pane's own Retry extracts into
  a new folder and is not affected. Keeping 108A's Retry across a restart needs the folder to
  record which chat wrote it, or `retry_of` to accept the review session id the folder records,
  which the add-in would then send; both are left to the owner.
- **The command line is not changed.** `swreview review --out` has no Retry and no claim rule
  at all: it writes `session.json` and `report.md` into the directory it is given, and appends
  to its `events.jsonl`, whether that holds a check's session, a review's or nothing. A refusal
  for one kind of folder would be a new rule in a command that protects none, so the decision's
  rule does not plainly belong there; 139A records that the command writes over a standards
  folder's session (001 `contracts/cli.md`).
- **Noticed, not changed**: `InvalidRunDir`'s sentence in the words file ("The run folder is not
  inside the run root. Check the run root in Settings.") fits the path rule and not a folder
  that holds a session; changing it regenerates the add-in's pane fixtures. A start still claims
  the re-modeler's grade folders, as rms records: the grade's session rotates aside, its
  `report.md` is written over by the review's, and the run's `rms-before.json` or
  `rms-after.json` then names the review's files. `GET /reviews/{run_id}` refuses any folder
  holding `check.json`, so a review that claimed a Model check's folder is not restored
  read-only.
- **Tests**: T074 and T076 in [tasks.md](tasks.md), each written first.

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
    before it stops anything. What holds it back (`ReviewHost.RestartHeldBack`) is read in the
    order the add-in can know it: no backend process at all holds nothing - the restart brings
    one back; then a remodel run in progress (`ReviewHostOptions.BackendBusy`), which the
    restart would end, known without asking the backend; then the turns, asked of the backend
    as the save's check asks them (`LookAtTheTurns`), but read strictly: only a readable state, a
    404 `UnknownChat` or a 400 `InvalidRequest` rules a turn out (`ReviewHost.RulesOutATurn`, on
    the status `BackendRequestException.Status` keeps); anything else - no HTTP answer at all, a
    5xx, a body that is not the backend's, any other refusal - leaves the turn unknown and holds
    the restart back. After three such looks in a row (`DeferredRestart.UnansweredLooks`) the
    watcher stops looking and posts `status {stage: "error"}`: "the review backend is not
    answering, so it has not been restarted with the settings saved during the turn yet. It will
    be before the next review or follow-up, once it answers; to restart it now, save the settings
    again." It posts that under the restart's own lock, so a later save's promise always comes
    after it. The restart still waits: each review and each turn call then looks once more, and
    makes it if the backend has answered that nothing holds it back. A save refused again starts
    a new watcher; one refused while the watcher is deciding to stop starts the count again. The
    restart reads the settings and resolves the key only when it is made. One lock is held for
    the whole of any restart the host makes, and whoever takes it asks again whether a restart
    is still waiting, so however many ask the backend restarts once. `settings.save`'s own
    restart, when no turn runs, goes through the same lock and is the restart for the settings
    in force, so a restart still waiting is dropped.
  - A new review makes the restart first: `BackendReady` and `ContextReady` make it or wait for
    the one being made, and are refused, before anything is read, with what holds it back -
    `TurnRunning` for a turn, `RemodelRunning` for a remodel run, `BackendUnavailable` for a
    backend that does not answer, each with words that name it - or `BackendUnavailable`, with
    the failure, when it fails. Every review's session is created after one of the two
    (`review.start`, `review.recheck`, a Retry with saved context, `context.review`), and the
    engineering context requests that check the backend go through `ContextReady`
    (`context.prepare`, `context.selection`).
  - A page call that would start a turn - `POST /sessions/{chat_id}/messages`, `/send`,
    `/evidence` or `/evidence/{request_id}` - is for a chat of the backend about to be replaced,
    so while a restart waits the pane's proxy asks the review host
    (`TaskPaneOptions.PageTurnRefusal`, `ReviewHost.PageTurnRefusal`) and never sends it: while
    something holds the restart back it is refused with what, as a new review is; otherwise the
    restart is made, or waited for, and the call is answered `UnknownChat` once one has been
    made - or `BackendUnavailable`, with the failure, when the restart it made or waited for
    failed. A refusal goes out with the status and the `retryable` flag the backend gives its
    class - `TurnRunning` 409, not retryable, and `UnknownChat` 404, as `chat/server.py` answers
    them - and the host's own words, which say why. Stop, dispositions and the timing are never
    held: Stop must reach the backend while a turn holds the restart back, and a disposition
    sent before the restart is recorded, where one held until after it would only be refused.
  - The page is told with `backend.restarted {sentences}`, takes whichever of the host's
    sentences about the wait - the promise, or that the backend is not answering - is on its
    banner off it, and nothing else there, and asks `ready` again for the new port and token, as
    it does after a save that restarted at once - once more after an `init` already on its way,
    which the host may have read while there was no backend, or before the restart began. It
    believes the restart until an `init` names a token other than the one it held when the
    message arrived, so a live waiting review on screen is restored from its folder with the new
    backend's token (feature 015 FR-042); and it closes the old chat's stream and any reconnect
    its close left waiting, since the new backend does not hold that chat. A failed restart is
    reported as a failed start is - `status {stage: "error"}` with its message - and not
    retried: the next save is the retry, as after any failed start. A review or turn call that
    waited for a restart someone else was making - the watcher, another call, a save - is told
    what became of it: made, or failed with that same failure (`DeferredRestart`, a count of the
    restarts that ended and the last one's failure, read against the count seen before waiting).
  - A page that asks `ready` again while it reads a stream on the same backend asks for that
    stream again, from the last event it showed. The host's `ready` closes the reader it holds
    for the page, as a reload needs; and the save a turn started during re-inits the page while
    that turn runs, so without this the page never saw the turn end and stayed "running", with
    Review disabled.
  - The add-in unloading: `BackendClient.Dispose` cancels a token it hands every start
    (`BackendStartOptions.Cancellation`) before it waits for the gate a start in flight holds.
    That start stops waiting for the handshake, or for `/health` between probes, stops its child
    and fails; and a start or restart asked for after that starts nothing. So the unload waits
    for a restart in flight to stop its child, not for the new backend to start.
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
  - Only an answer that rules a turn out releases the restart. A readable state says whether a
    turn runs; 404 `UnknownChat` says the backend does not hold the chat, and 400
    `InvalidRequest` that it could not. A 5xx, or a body that is not the backend's, says nothing
    of the turn - a backend answering 500 to `GET /sessions/{chat_id}` may be mid-turn - and the
    backend's own check, as lenient as the save's, reads such an answer as no turn, so it must
    not be the one to decide; nor may no answer at all. Watching such a backend is bounded
    because a wedged one keeps its process, and so its endpoint, and its watcher would ask for
    good. The bound stops only the watcher: the restart still waits, so no review and no turn
    call runs on the old backend - each looks once more, and makes the restart once the backend
    answers - and no caller is told the backend restarted when it has not. Saving the settings
    again is the way on meanwhile because the save's own check, and the backend's, read a
    missing answer as no turn (`AnyTurnRunning`, `TryListModels` swallowing its failure, and
    `BackendSupervisor`'s delegate being the same `AnyTurnRunning`): the save restarts the
    backend once each of those round trips has timed out - up to 30 seconds a tracked chat for
    each of the two checks, and 30 for the model list, on a backend that accepts connections and
    never answers.
  - A refusal says what holds the restart back because the page shows the label of its class
    first: `TurnRunning`'s says to wait or press Stop, which is untrue of a remodel run - and Stop
    is disabled then - and of a backend that does not answer. A turn keeps `TurnRunning`; a
    backend that does not answer takes `BackendUnavailable`, whose sentence ("Save Settings to
    start it again") is the way on, and which the add-in already gives every call the backend
    did not answer; a remodel run had no class whose sentence is true of it, so it has its own,
    `RemodelRunning`, with a sentence in `review_words_v1.yaml`. The remodel run is read before
    the turns because the add-in knows it without a round trip, and because the way on from a
    backend that does not answer - saving again - would end the run.
  - A new review must not run on the old backend, or the save is in force in the host and not
    in the backend: the case 143A exists to end. Making the restart from the request rather
    than waiting for the watcher closes the second in which the turn has ended and the watcher
    has not looked yet; and none of these callers waits for a turn - only for a restart already
    being made, which the backend's own start timeouts bound. `CreateReviewSession` asks nothing
    itself: a restart can only start waiting in `settings.save`, which runs on the same page pump
    as every review request (`SwReviewAddIn.StartPageMessagePump`; no other page, pump or host
    calls `Save` or `IBackendClient.Restart`), and every caller of `CreateReviewSession` has
    passed `BackendReady` or `ContextReady` on that pump just before, so a check there could
    never find one waiting.
  - The proxy's question covers the calls the host never sees. The page enables a follow-up the
    moment it reads `turn.ended`, before the backend has settled the chat and so before the
    watcher can see the turn has ended, so a quick follow-up or a Send could otherwise start a
    turn on the old backend and put the restart off for another turn. The restart ends that
    chat in any case, as every settings restart does, so the call is answered `UnknownChat`
    rather than sent where it would run with the settings the engineer replaced. Its refusals
    carry the backend's own status and flag for their class, so the page treats them as it
    treats the backend's; the words differ, and say why.
  - Unloading must not wait for a start nobody wants: `DisconnectFromSW` runs on the SOLIDWORKS
    thread, and the start it would wait for takes up to the handshake's 60 seconds and the
    health check's 30. A token handed to the start, cancelled before the gate is waited for, is
    the one way to reach a start already under way without stopping a process the start has not
    finished handing over.
  - The sentence needs no change: it is now what happens, unless a remodel run outlasts the
    turn (owner question 1, below). The up-front refusal's old sentence made the kind of promise
    143A removes, in a smaller place, so it is corrected with the behaviour.
- **Edge cases**, each pinned by a test (T079, T081, T083, T085, T087, T089, T092, T095):
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
  - A backend that gives no usable answer holds the restart back; after three looks of the
    watcher's in a row without one - fewer, and an answer that rules a turn out releases it as
    usual - the watcher stops looking, restarts nothing, and says so and how to go on, before any
    later save's promise. The restart still waits: the next review or follow-up looks once more,
    is refused while the backend still gives no usable answer, and once it answers makes the
    restart first - the review runs on the restarted backend, and a follow-up is answered
    `UnknownChat` only after a restart has really been made. A save meanwhile restarts the
    backend once its round trips have timed out. An answer between the looks starts the count
    again, and so does a save refused again, even while the watcher is deciding to stop. A 404
    `UnknownChat` or a 400 `InvalidRequest` does not hold the restart back; a 5xx, an unreadable
    body or any other refusal holds it as no answer does, and a backend answering 500 during a
    turn is never asked to restart under it. With no backend process the restart is made, to
    bring one back.
  - A remodel run in progress holds the restart back as a turn does, and so holds a new review
    back with it; it is named before a backend that does not answer, and the watcher does not
    stop waiting for want of an answer while the run lasts.
  - A new review the moment the turn ends restarts the backend first and runs on it with the
    new settings; one made while the restart is being made waits for it; one made while
    something holds the restart back is refused before anything is extracted, saying what, and
    the restart still comes when that ends; one whose restart fails is refused with that
    failure. Preparing engineering context, or reading the selection against it, the moment the
    turn ends restarts the backend before the dump or the read, and is refused as a review is
    while something holds the restart back. None is dropped: each is answered.
  - A follow-up, an answer or a Send the moment the turn ends makes the restart and is answered
    `UnknownChat`; one while something holds the restart back is refused saying what, with the
    backend's status and flag for that class; with nothing waiting, every call goes on as
    before and nothing is asked.
  - A restart that fails is reported, whatever it threw, with the key masked, and is not tried
    again, and every review or turn call that waited for it is told the same failure - never
    that the backend restarted, and never let through to the backend there is. One that fails
    before it stops anything - the configured launcher has gone, so its start options cannot be
    built - leaves the old backend up, with the environment it was started with and its chats;
    one that fails after stopping it leaves no backend. Either way the next save is the retry,
    as after any failed start, and a save's own failed restart is told to those that waited for
    it the same way.
  - Disposing the host - the add-in unloading - while a restart waits stops the watcher without
    waiting a poll out, and nothing asks or restarts afterwards. A restart already under way
    when the host is disposed - past the lock's check that one still waits - is not stopped or
    waited for by the host: `BackendClient.Dispose`, which the add-in calls next, tells its
    start to stop before waiting for the gate the start holds, and the start stops its child.
    A page that reloads leaves the restart waiting and is told when it is made, and a post to
    a page that has gone is dropped (`TaskPaneControl.PostToPage`), so a pane that closes holds
    nothing open.
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
  - After any settings restart, made at once or afterwards, the review that was on screen keeps
    its transcript although the backend no longer holds its chat: a follow-up, an answer or a
    disposition is answered `UnknownChat`. Only a review waiting for Send is restored from its
    folder (FR-042).
  - A review refused because the backend does not answer is refused `BackendUnavailable`, whose
    label reads "The review backend is not running. Save Settings to start it again, then
    retry." The way on is right; "not running" is not quite - the backend is running and not
    answering. The label is unchanged, since every pane fixture that carries it would be
    regenerated; it goes to the owner's wording round.
- **Owner questions** (recorded 2026-10-19, behaviour unchanged). *Answered 2026-10-19 by owner
  decision 145A, which settles all three: see
  [145A](#145a-what-a-settings-restart-leaves-behind-every-tab-follows-it-and-a-remodel-run-waits-for-it-as-a-turn-does-2026-10-19),
  "The answers to 143A's owner questions".*
  1. The sentence says the backend restarts "when the running turn ends". A remodel run in
     progress holds the restart back too, so when one outlasts the turn the restart comes when
     the run ends. Keep the sentence, since a run that outlasts the turn is rare and a new
     review is told `RemodelRunning` meanwhile, or name the run in it ("...when the running
     turn, and any remodel run, ends")?
  2. A save made when no turn runs restarts the backend at once and so ends a remodel run in
     progress, as before 143A; and a remodel run started while a restart waits runs on the old
     backend, with its key. Should a save wait for a remodel run as the restart for a save made
     during a turn does, and should a remodel run be refused, or made to restart the backend
     first, while a restart waits? Both are feature 004's.
  3. The other tabs - Model check, Standards and Remodel - keep the port and token of their
     `init` after any settings restart, made at once or afterwards, so their next backend call
     is refused 401; 143A makes such a restart happen without the engineer pressing anything.
     Each page has an init path to reuse (`check-page.js` and `remodel.js`, `requestInit`), so
     the fix is the Review page's: the add-in posts `backend.restarted` to every pane host after
     either restart, and each page asks `ready` again - once more after an `init` already on its
     way, which neither page does yet. It would take the add-in's fan-out to the three hosts,
     the two page scripts, a row in three more features' contracts (003 `model-check.md`, 006
     `standards-check.md`, 004 `pane-remodel-messages.md`), and page tests for both scripts,
     the Remodel page's being new; and a decision on what the Remodel page re-renders on that
     `init`, which re-reads its latest run. Not small, so not made here.
- **Review**: an independent adversarial review of T079 to T084 found that a page re-init
  closed the stream of the very turn that holds the restart back, leaving the page "running";
  that an `init` read while there was no backend hid the restart from the page; that a question
  the backend did not answer could release the restart under a turn; that the restart could end
  a remodel run; and that a call could be told the backend restarted when the restart had
  failed. T087 and T088 fix each, test first. A second independent review, of T079 to T088 on
  `4c4f0ce`, found no deadlock and no exception that can escape a background thread, and these,
  which T089 and T090 settle test first: the two
  restart calls before a review hid each other from the tests, and the engineering context
  requests' was pinned by none (now pinned; `CreateReviewSession`'s, which no caller could
  reach, removed); the strict look could hold the restart back for ever, and its refusals named
  a turn whatever held it (bounded, and named); the unload waited for a restart in flight to
  finish, and "nothing is restarted after it" was not strictly true (the start is now stopped,
  and the claim says what is true); the page kept the old chat's reconnect, could take an `init`
  read before the restart for the new backend, and cleared any banner (each fixed); the proxy's
  refusal was `retryable` where the backend's is not, while the docs said the two could not be
  told apart (now the backend's flag, pinned against `chat/server.py`, and the docs say what is
  true); and a sub-millisecond poll would spin the watcher (refused). The other tabs' stale
  token is owner question 3. A second pass of that review, on `18a0823`, found seven more, which
  T092 and T093 settle test first: after the bound the restart stopped waiting, so once the
  backend answered again a review ran on the old backend with the new settings, and a turn call
  racing the last look could be told the backend had restarted when it had not (the bound now
  stops only the watcher); a 5xx was read as no turn, so a backend answering 500 during a turn
  could be restarted under it by its own lenient check (only a readable state, 404
  `UnknownChat` or 400 `InvalidRequest` rule a turn out); the watcher's guard against stopping
  on a newer save's account was pinned by nothing (pinned); its word that it stopped could land
  after a newer save's promise, and the restart did not take it off the banner (posted under
  the restart's lock, and carried back with the promise); these records said more than the code
  (corrected); a stop test failed once under a loaded run (read from the code as two test
  classes changing the runner's one console at once - the add-in makes every stop under one
  gate - so the classes that start stub children now run one at a time; not seen again); and the
  label for a backend that does not answer says "not running" (Not changed, above). A third
  pass, on `50db9fa`, found two more, which T095 and T096 settle test first: nothing pinned
  the watcher's stop taking itself off the books, without which a save refused later starts
  no new watcher and is never restarted (pinned: a save refused after the watcher stopped is
  restarted by a new one); and a caller that waited for a restart which failed before it
  stopped anything was told the backend had restarted, or let through to the old backend
  with the new settings, while the caller that made the attempt was refused (a waiter is now
  told what became of the restart it waited for - made, or that failure - for a turn call, a
  review and a save's restart alike). Each fix is pinned: 26 mutations for the first pass, 9
  for the second and 5 for the third, each taking one fix out, turn 66, 21 and 21 cases red
  (T089, T092, T095).
- **Tests**: T079, T081, T083, T085, T087, T089, T092 and T095 in [tasks.md](tasks.md), each
  written first.

### 145A. What a settings restart leaves behind: every tab follows it, and a remodel run waits for it as a turn does (2026-10-19)

- **Question**: 143A left three owner questions about what a settings restart leaves behind
  (143A, Owner questions 1 to 3). The pane's sentence said the restart comes "when the running
  turn ends", while a remodel run held it back too. A save made when no turn ran restarted the
  backend at once, and so ended a remodel run in progress with its copy half changed, and a
  remodel run started while a restart waited ran on the old backend, with its key. And the Model
  check, Standards and Remodel tabs kept the port and token of their `init` after any settings
  restart, so their next backend call was refused 401.
- **Decision** (owner decision 145A, "test first"): every tab of the Task Pane, not only Review,
  is told the backend restarted and asks for its new port and token; a remodel run is treated as a
  turn: a save made during one restarts the backend when the run ends, a remodel run started
  while a restart waits makes the restart first, as a new review does, and the pane's sentence
  names what the restart waits for.
- **The answers to 143A's owner questions**:
  1. The sentence names what the restart waits for: "the settings are saved; the backend
     restarts when the running turn ends." for a turn, as before; "...when the remodel run ends."
     for a remodel run; and "...when the running turn and the remodel run end." for both.
  2. A save made during a remodel run is kept, and its restart waits for the run, through the
     same `DeferredRestart`; a remodel run started while a restart waits makes it first, or waits
     for the one being made, or is refused saying what holds it back.
  3. The add-in tells the Model check, Standards and Remodel tabs `backend.restarted` after every
     restart the review host makes, made at once or after waiting, and each page asks `ready`
     again - once more after an `init` already on its way - and takes the new port and token.
     The Remodel page no longer reads its latest run again on that `init` (below).
- **How: every tab follows a restart**:
  - The review host calls `ReviewHostOptions.BackendRestarted` after every restart it makes: a
    save's made at once (`Save`, once `DeferredRestart.Now` has made it), and one made after
    waiting (the restart's `restarted` report, after `backend.restarted` to the Review page). Never
    after one that failed - no backend was started for the tabs to ask about, and the failure is
    the Review tab's to report, as a failed start is - and never while one waits. The call is
    guarded (`ReviewHost.TellTheOtherTabs`): a tab that cannot be told does not turn a restart that
    was made into a save answered with an error.
  - The add-in sets it to `SwReviewAddIn.TellTheOtherTabsTheBackendRestarted`, which calls
    `BackendRestarted()` on the Model check, Standards and Remodel hosts, each read through its
    field: all three are built after the review host's options, and one that has gone tells
    nothing. The Terminal tab holds no backend and is not told.
  - One message, one shape, from one place: `PaneActions.PostBackendRestarted(sentences)` posts
    `backend.restarted {sentences}` for every host. The Review host's carries its sentences about
    a restart that waited; the other three carry none, since those sentences are posted to the
    Review page alone and no other page shows them. The Review page is told as before: by the
    save's reply for a restart made at once, and by `backend.restarted` for one that waited.
  - The two page scripts that hold a backend besides `app.js` - `web/shared/check-page.js`, which
    the Model check and Standards pages share, and `Remodel/RemodelPage/remodel.js` - answer it as
    `app.js` does: `requestInit(false)`, or, while an `init` is already on its way, once more after
    it (`initAgain`), since the host may have read that `init` before the new backend was up.
- **What each page does on that `init`**: the rules were to replace the port and token, to lose
  nothing the engineer is looking at, and not to reconnect to the old backend a stream or a call
  in flight was made to. Each page takes the least it can:
  - The Review page: unchanged (143A) - the new backend's token, a live waiting review restored
    from its folder, and the old chat's stream and reconnect closed.
  - The Model check and Standards pages: `applyInit(payload, false)` - the backend, the token,
    the run root, the document and `latest_check`, kept as state, and the page's own `onInit` (the
    profile path the page relays). The check on screen stays and is not read again: the restart
    changed the backend, not the check, and a re-read would race whatever the page shows - the
    reason the page already gives for not reading it again when the backend starts late. Its
    stale-result rule is applied to the document the `init` names, which is the one open. These
    pages hold no stream, and retry no call: a check's `POST`, an Accept or a re-read already
    made with the old token is refused by the new backend, or fails with the old one, and is
    answered as any failed call is; the engineer presses again, on the new backend. *Second
    review (T121, T122):* a call the page makes while that `init` is on its way waits for it,
    and for the one more ask after it, and carries the token they leave: the host answers
    `ready` on the tab's own pump, behind an extraction already running there, so a check
    pressed as the backend restarted got its extraction's reply first and called its route
    with the old token. And a latest check the page could not read - a tab opened during a
    restart reads it with the token of an `init` the host gave before - is read again by the
    next `init` until it is read, or until a check is pressed; a read still out when a check
    is pressed is neither shown nor remembered, and one the page did read is not read again
    (third review, T134, T135).
  - The Remodel page: `applyInit(payload, false)` - the backend, the token, the run root, the
    document, the limits and the seat capability - and it does not read `latest_run` again.
    Decision: its `init` used to re-read its latest run (`renderRun`, the `plan_lost` notice,
    `remodel.result`) every time, which is right for a page that loads again and not after a
    restart. Nothing about the run changed: its record is the run folder, which the restart does
    not touch, and the host reads `remodel.result` out of that folder, not the backend. A backend
    restart loses no plan either - the plan's bridge session lives on the tool service - so
    `plan_lost` would only repeat what the page already shows. And the restart's message can reach
    the page while it is busy with a run: a plan or a Start makes a waiting restart first (below),
    and the watcher can restart in the moment between a run's end and its terminal `status`; a
    re-read there would re-render the run and clear the run's status line (`showPlanLost` empties
    it). The page makes no backend call of its own, so nothing is in flight to the old backend. A
    page that loads again still starts from `init.latest_run`, unchanged, and so does one whose
    backend finished starting after its `init` (`status {stage: "ready"}` while it holds none).
- **How: a remodel run is treated as a turn**:
  - A remodel run here is what `RemodelHost.RunInProgress` covers and what 143A's
    `ReviewHostOptions.BackendBusy` reads: a plan (`remodel.plan`) or a Start's run
    (`remodel.start`). Both hold the backend for their whole length - the plan its probe, open and
    plan routes, the run its job - and a restart ends either.
  - `DeferredRestart` takes a second reading, `busy` - `ReviewHost.RemodelRunInProgress`, which
    reads `BackendBusy`, a throw read as busy, as 143A's look already read it - and every restart
    reads it under the restart's own lock. `Now`, a save's restart, reads it before it asks the
    backend anything: a run in progress defers the restart (`Hold.RemodelRun`), exactly as a turn
    the backend's own check finds does (`Hold.Turn`), and the watcher makes it once nothing holds
    it back. `Apply` - the watcher's, a review's, a turn call's - reads it again under the lock,
    after its look, because the look can answer that nothing holds the restart back without
    reading the run: the review host's does so when no backend process is up at all, since the
    restart is what brings one back, and a look that cannot be made is read as that answer. A run
    in progress then still holds the restart back (`Outcome.RemodelRunning`; the restart still
    waits). No run begins between the look and the lock while a restart waits: a run begins
    through `Begin`, below.
  - A run begins through `DeferredRestart.Begin(begin)`. A restart that waits is made first, as
    a new review makes it (`Apply`), or the one being made is waited for, on the restart's lock -
    a save's made at once included, which `Apply` never waited for, since it is never waiting. A
    restart made or tried while the call waited is its answer, from the count 143A keeps: made,
    and the run begins on the restarted backend; failed, and the run is refused with that failure.
    A newer save's restart that started to wait meanwhile is looked at again from the top. Only
    then, under the lock, `begin` runs: the step that marks the Remodel host busy. Every restart
    reads that mark under the same lock, so a run and a restart never overlap.
  - `ReviewHost.BeginRemodelRun(begin)` answers the outcome: nothing waited, or the restart was
    made, and the step ran - null; a turn holds it back - `TurnRunning`; the backend does not
    answer whether a turn runs - `BackendUnavailable`; a remodel run - `RemodelRunning`, which only
    a reading that throws can give, since the Remodel host refuses a second run itself; the
    restart failed - `BackendUnavailable`, with the failure, masked; the host disposed -
    `BackendUnavailable`, "the review backend is stopping with the add-in.". The words are the
    Remodel tab's: that tab's own Stop stops the run, so the turn's refusal sends the engineer to
    "Stop on the Review tab", and the one for a backend that does not answer to "Save the settings
    again on the Review tab". The Remodel page reads no words file and prints the message as it is.
  - How the Remodel host reaches it: `RemodelHostOptions.BeginRun`, which the add-in sets to
    `SwReviewAddIn.BeginRemodelRun`, which calls `_reviewHost.BeginRemodelRun` read through the
    field; with no review host there is no settings restart to wait for, and the step runs. The
    Remodel host calls it (`RemodelHost.BeganRun`) where it used to set `_busy = true` - in `Plan`
    and in `Start` - after every refusal that needs no call and before the first pipeline call, or
    `remodel.started`, so a press refused on the spot makes no restart. A refusal is answered with
    the gate's class, words and flag, and nothing else happens; a gate that throws leaves the host
    free, so one failure cannot hold every later plan, and the restart that waits on the run, back
    for good.
  - Threading and the lock order: the gate runs on the Remodel page's own pump, while the
    restart is made from the watcher's thread, the review page's pump or a proxied request's
    thread. `DeferredRestart` keeps the order it documents, its restart lock and then its state
    lock, and `Begin` takes the restart lock and reads the state under it, as `Apply` does; the step it
    runs there writes a volatile flag and nothing more: no lock, no call back into the restart,
    nothing that blocks. A restart the gate makes posts `backend.restarted` and tells the other
    tabs from the Remodel pump, under the lock, as 143A's restarts post from the other callers'
    threads; a post never blocks (`TaskPaneControl.PostToPage`). The page's `ready` that the
    message prompts waits on the Remodel pump behind the plan, or behind Start's reply, so it is
    answered after it.
  - The sentence: `Save` reads what `Now` says holds the restart back. A turn: 143A's sentence,
    unchanged. A remodel run: the run's sentence - or, when a turn also started during the save,
    which the look made then finds (`LookAtTheTurns`, stopping at the first chat the backend gives
    no answer about), the sentence for both. `backend.restarted {sentences}` carries all four of
    the host's sentences about a restart that waits - the three promises, and the watcher's word
    that the backend is not answering - so the page takes whichever is on its banner off it, and
    nothing else.
  - The not-answering sentence said the backend "has not been restarted with the settings saved
    during the turn yet", untrue of a save made during a remodel run, and named only "the next
    review or follow-up" as what makes the restart first. It now reads "the review backend is not
    answering, so it has not been restarted with the saved settings yet. It will be before the
    next review, follow-up or remodel run, once it answers; to restart it now, save the settings
    again." Saving again is still the way on: the watcher reads the remodel run before the turns,
    so it says this only once no run holds the restart, and a run cannot begin while the backend
    gives no answer.
- **Why**:
  - A remodel run holds the backend as a turn does: its plan calls the backend's remodel routes,
    and its run is a job inside the backend's process, which a restart kills; the add-in's poll
    then finds no job and ends the run `failed`, the copy half changed (FR-031 keeps the change
    log and refuses a resume, but the run is lost). The promise the pane makes for a save during a
    turn holds for a save during a run.
  - A run makes the restart first rather than running on the old backend: the run's judge phase
    asks the model with the backend's environment - the provider and key the engineer replaced,
    the session of another provider 138A records for the Remodel route - and a restart that waited
    for the run would wait the length of it with the settings saved but not in force.
  - The mark is set under the restart's lock because nothing else closes the two gaps: a save's
    restart made at once is never waiting, so a run that began during it was never held, and ran
    on a backend about to go; and a save whose restart began to wait between a run's look at the
    restart and its mark would leave the run on the old backend, with the restart waiting on it.
    Every restart, and every save's deferral, already holds that lock, so the two become exclusive
    there, and a step that only writes a flag cannot slow it.
  - The other tabs are told by the host rather than left to meet a 401: the page cannot tell a
    refused token from a refused call, and only the host knows the restart happened. A message
    the pages already understand - `backend.restarted`, the Review page's since 143A - keeps one
    meaning for one word on every tab.
- **Edge cases**, each decided and tested (T113, T115, T118):
  - A save's restart made at once tells every other tab once; a restart that waited tells them
    once it is made and not before; one a new review, a turn call or a remodel run makes tells
    them too; a failed restart, at once or after waiting, never tells them it restarted - one
    that failed once the old backend had stopped tells them the failure, masked, as a failed
    first start is told (T129), and one that failed before it stopped anything tells them
    nothing; a tab that cannot be told, of either, leaves the save answered `settings.saved`
    and the Review page told.
  - A page told while an `init` is on its way asks once more after it, and only once, however
    many messages arrive meanwhile; its next call carries the new token, and none the old.
  - A save during a remodel run is kept and says the run's sentence; the watcher asks nothing of
    the backend while the run lasts, since it reads the run first - the save itself asks about
    the turns before it writes, as every save does, and once more for its sentence; the backend
    restarts once, with the saved settings, when the run ends.
    A save a turn also started during says the sentence for both and waits for both, whichever
    ends first.
  - A run started with nothing waiting begins at once and asks nothing; the moment the turn ends
    it makes the restart first and begins on the restarted backend, the pages told before it
    begins; while a turn, or a backend that gives no answer, holds the restart back it is refused,
    saying so, and the next press makes the restart once nothing does; started while the watcher's
    restart or a save's own is being made, it waits for it and begins on the new backend; when the
    restart fails - its own, or a save's that failed before it stopped anything, which left the old
    backend up - it is refused with the failure, masked, and never begins; once the host is
    disposed it never begins.
  - A restart whose look did not read the run - no backend process at all, or a look that cannot
    be made - never ends a run in progress: it waits, and is made once, with the saved settings,
    when the run ends; a save's restart asked for while a run's step runs waits for it, and then
    waits for the run.
  - A plan or a Start refused on the spot asks no gate; one the gate refuses calls nothing, makes
    no folder and records no run, leaving the plan startable; a gate that throws leaves the host
    free.
  - A Start whose plan's session went while its gate waited - the tool service re-attached, or a
    teardown ended the session - is refused `SessionLost` in decision 22A's words, before
    `remodel.started` and before any call, and the host is left free; a loss that came after
    the gate marked the host busy is announced `remodel.plan_lost` as Start frees it (T125).
  - A plan whose document - another part, another configuration, or none - changed while its
    gate waited is refused `DocumentChanged` before any call, in words that name no path, the
    earlier plan left as it was; the same part spelled otherwise still plans (T123).
  - Anything that throws after Start's gate and before its run is handed on frees the host,
    puts the plan back and leaves nothing for Stop; a page told `remodel.started` is told the
    run is over (T125). A press that makes a restart first, or waits for one being made, says
    so first, and a refused Start leaves the run status line empty (T131).
- **Evidence** (at `ef6d1ce`):
  - A save restarted the backend under a remodel run: `ReviewHost.Save` checks only the turns
    before it writes (`ReviewHost.cs:1049`) and restarts through `DeferredRestart.Now` (`:1168`),
    which asked nothing of a run; the backend's own check is `AnyTurnRunning` alone
    (`SwReviewAddIn.cs:449`). 143A's `BackendBusy` held only a restart that waited
    (`ReviewHost.cs:1301`), read before the restart's lock.
  - How the Remodel host talks to the backend: `BackendRemodelPipeline` calls the loopback
    routes through `RemodelBackendClient`, which reads the endpoint per call
    (`RemodelBackendClient.cs:275`). A plan calls `/remodel/probe`, `/remodel/open` and
    `/remodel/plan` (`BackendRemodelPipeline.cs:163`, `:200`, `:256`); a run starts a job in the
    backend (`POST /remodel/runs`, `:277`) and polls it (`:312`), and a poll the backend does not
    answer ends the run `failed` (`:314` to `:320`).
  - Where a run begins: `RemodelHost.Plan` set `_busy = true` at `RemodelHost.cs:1028`, `Start`
    at `:1545`; `RunInProgress` is `_busy` (`:414`). The Remodel host runs on a pump of its own
    (`SwReviewAddIn.cs:892`), the review host on another (`:1273`).
  - The other tabs' stale token: `CheckPaneHost.SendInit` (`CheckPaneHost.cs:274`) and
    `RemodelHost.SendInit` (`RemodelHost.cs:859`) read the endpoint when asked;
    `check-page.js` calls with the token of its last `init` (`:229` to `:241`) and asked `ready`
    again only on `status {stage: "ready"}` while it held no backend (`:1194`), and `remodel.js`
    likewise (`:961`); the review host posted `backend.restarted` to the Review page alone
    (`ReviewHost.cs:447`), and the add-in posts to every page only the first start's status
    (`SwReviewAddIn.cs:1038`).
- **Review**: an independent review of T113 to T117 found two things, settled test first by T118
  and T119:
  - Start read its plan's session before the gate only, and the gate can wait through a restart:
    seconds in which the host is not yet busy, so the tool service is free to re-attach - its
    re-attach asks whether the host is busy before it moves (`ToolServiceGate.FollowCore`) - and
    a teardown to end the session. A Start could then begin on a session that went while it
    waited, which decision 22A refuses. Start now reads the session again once the gate has
    marked the host busy (`RemodelHost.LostSessionWords`, one reading for both checks), and
    refuses `SessionLost` in the same words, clearing the mark.
  - `Apply`'s reading of the run under the lock was said to guard a run begun between the look
    and the lock, which the gate rules out while a restart waits. What it guards is a look that
    answers without reading the run; the comment, `Outcome.RemodelRunning`, the class summary and
    the unit case's name now say so, and a case through the host pins it: no backend process, a
    run in progress, and the restart made only when the run ends.
- **Second review**: an independent adversarial review of the branch at `020fec8` found no
  must-fix - no lock inversion, `Begin`'s loop sound, 36 of its 40 mutations caught - and the
  items below, settled test first by T121 to T132:
  - A check pressed as the backend restarted called its route with the old token (S1), and a
    check tab opened during a restart could come up blank (N5): `check-page.js`'s calls wait
    for the `init` on its way, and a latest check that could not be read is read again (above).
  - Plan read the active document before its gate and its probe read whatever was active after
    (S2). The bridge's `scope_not_probed` caught the switch, but its words name both full paths
    and reach the page as `ScopeRefused`, and an assembly made active got a refusal about a
    document the engineer never pressed for. Plan reads the document again once the gate has
    marked the host busy, by `PageDocument.IsSameDocument`, and refuses `DocumentChanged`.
  - "A throw is read as busy" was written down and tested nowhere (S3): two cases pin it, one
    per layer (T127), and the review's mutations D8, R9 and R13 now go red.
  - A failed restart told the other tabs nothing (N4). Decision: they are told as a failed first
    start is told to every page, `status {stage: "error"}` with the failure, masked - only when
    no backend is up after it, since one that failed before it stopped anything left their
    tokens working. Not `backend.stopped`: its payload names a process's exit code, and every
    page's sentence for it sends the engineer to reopen the pane, which starts no backend.
  - While a press waited in the gate the Remodel page said only "Reading the part..." or
    "Running..." (N6). Telling it is cheap - the existing `status` message, the
    `backend_starting` stage the page already writes into its run line, and one reading
    (`ReviewHost.RestartAhead`: a restart that waits, which stays pending until it ends, or a
    save's being made at once) - so it is told, before the gate. A refused Start now empties the
    run line, as a refused plan already did, since the restart's sentence would otherwise stay
    under the refusal.
  - Repetition (N7): `ReviewHost`'s refusals for an unloading add-in and for a failed restart
    are written once each (T128). The pages' restart handling is not consolidated (below).
  - Start had no `try`/`finally` after the gate (N8), and its refusal after the gate did not
    announce the lost plan (N9): both settled in one `finally` (T126). Two throwing seams test
    it - the attachment read after the gate, and the scheduler.
  - This entry said nothing was asked of the backend while a run lasts, true of the watcher and
    not of the save (N10); the edge cases above now say which.
  - `BeganRun`'s busy reset on a refusal never mattered (N11, the review's equivalent mutant
    H7): 145A added it (`e732436`), and it is removed (T126).
- **Third review**: a third independent review of the fixes at `c9d34aa` found no must-fix -
  `DeferredRestart` sound, the removal of `Apply`'s own mark right, about 34,000 restarts in a
  stress probe with no violation - and proved the items below with probes; settled test first
  by T134 to T141:
  - `latestUnread` was never cleared (F1): on the Standards tab a latest verdict read again on a
    restart's `init`, then cleared on purpose by a check that failed before anything was graded,
    came back on the next restart under the failure. The flag is now cleared when the latest
    check is read and when a check is pressed, and the `init` reads again on the flag alone. A
    count of checks pressed, taken when a read is made, keeps a read still out when a check is
    pressed from being shown or remembered.
  - A save's restart that failed other than with `BackendStartException` told the other tabs
    nothing (F2): the old backend can stop and the new one's log fail to open, outside the
    wrapper. Save now tells them of any failure, still only when no backend is up, and throws it
    on: how the save is answered is not changed (below).
  - Nothing pinned that a refused `init` lets the calls waiting for it go (F3); a case does, the
    driver refusing a held `ready`.
  - A failed start's or restart's banner outlived the restart that worked (F4). A page cannot
    tell that `error` from a check's or a run's by its stage, and taking those down would hide
    what the engineer must read - a teardown's word on what it left, say - so the add-in marks
    its own word: `status {stage, message, lifecycle: true}` through
    `PostStatusToTheOtherPages`, from `PaneActions.PostStatus`'s marked form, beside the
    two-argument form tests bind to. `check-page.js` and `remodel.js` remember whether the last
    banner they put up was that word and take it down when an `init` names a backend; any other
    banner since clears the mark. The Review page is not changed: its own Save clears its banner
    before it saves, and every restart after a failed one starts from that Save.
  - The restart-first sentence said the backend was restarting even while a turn or a backend
    that does not answer held the restart back (F5): "Waiting for the review backend to restart
    with the saved settings, then ...", true either way, its beginning written once.
  - `DocumentChangedMessage` (F6) says "The active document or its configuration changed ... so
    nothing was copied and no new plan was made": true of a configuration switched alone, and
    not read as if the earlier plan waiting for Start were gone.
  - Repetition (F7): `RestartedForNewReview` uses `RestartFailed`, so the failed-restart refusal
    is written once; Plan's and Start's `finally` share `FreeTheHost`.
  - An Accept and a check let go together could show the Accept's re-read of the older check
    over the newer one (F8). `refreshResult` shows a re-read only while its caller still wants
    it - the Accept's while its check is the one on screen - and answers whether it did; the
    accepted row is marked only then. Nothing the engineer can click changed.
- **Not changed**:
  - Discard copy's close is one backend round trip that holds nothing back: a restart that lands
    during it fails the close, and Discard deletes `copy/` anyway, as it does when the bridge does
    not answer. A check (Model check, Standards) is not a turn to the restart either: its call in
    flight when the backend restarts fails as any call to a backend that stopped does.
  - No host posts `backend.stopped`, which every page's contract names and every page handles: a
    failed restart is told as a failed first start is (above). Its sentence on every page, "The
    backend stopped. Reopen the pane to start it again.", names a way that starts no backend -
    the add-in starts it when it loads - and is left for the owner with the message.
  - After a failed restart a check page's backend strip still says "Backend ready", the
    banner carrying the failure, as after a failed first start it says "Backend starting": the
    strip follows `init`, not `status`. Left for the owner.
  - The supervisor's own check (`BackendSupervisor`'s delegate) still asks only about turns: every
    restart reaches it through the review host's lock, which now reads the run first.
  - The Review page's script: it takes whichever of the host's sentences is on its banner off it,
    so the two new promises needed nothing of it; its tests pin them coming off.
  - The labels: the refusals keep their classes - `TurnRunning`, `RemodelRunning`,
    `BackendUnavailable` - and the Remodel page prints a refusal's message, not a label, so
    `review_words_v1.yaml` and the pane fixtures are untouched.
  - The moment between a re-attach's question whether the host is busy and its taking the
    service down, in which a Start that has read its session just after its mark can still lose
    it: Start's reading and its mark had that moment before 145A, and the gate's wait no longer
    widens it.
  - `scope_not_probed`'s words name both full paths, and reach the page as `ScopeRefused`
    (`chat/remodel.py`), on a tab whose words name no path. Since T124 only a part switched in the
    moment between a plan's second reading of the document and its probe meets them. Older than
    145A; put to the owner. *Settled by decision 149A (2026-10-20)*: both of the codes
    `ScopeRefused` carries from the bridge reach the page in plain words, with no path (149A,
    below).
  - The restart and re-`init` handling is still written in three page scripts - `app.js`,
    `check-page.js`, `remodel.js`. The one script all three load is `web/shared/dom.js`, whose
    charter keeps it to building nodes, with no page state, host bridge or network, so the
    injection tests can call it inside the real page; a fourth shared script would be a new
    include on three pages. What the three share is about a dozen lines - the
    `initPending`/`initAgain` pair and the `backend.restarted` case - around halves that differ:
    the Review page's `replacedToken` and stream close, a check page's waiting calls and its
    latest check, the Remodel page's `latest_run`. Left for the owner.
  - The review host's catch in `RemodelRunInProgress` is redundant with `DeferredRestart`'s own,
    which reads a look that throws as no hold and then reads the run again under the lock. It is
    kept, since the look is documented never to throw; the mutant that removes it is equivalent.
  - The Remodel page's restart sentence is read before the gate: a restart that begins to wait
    between that reading and the gate is made without it, and only the words are missed.
  - A save whose restart failed other than with `BackendStartException` is answered with the
    failure, `HostError`, although the settings were written: older than 145A, kept by T139 and
    pinned by its case so a change to it is deliberate; put to the owner.
  - An Accept whose re-read is dropped for a newer check says nothing of the exception it wrote:
    the newer check on screen is the answer, and it shows the rule as accepted when the backend
    wrote the exception before it graded. Left for the owner.
  - Seen while reviewing, in 143A's area and left for the owner: a new review reads the active
    document before it makes a waiting restart first (`ReviewHost.StartReview`, `BackendReady`),
    and its dump attaches to whatever is active after (`SwReviewDump.Run`). A restart takes
    seconds, in which the engineer can switch documents, so the run folder named for one document
    could hold another's evidence; nothing like `scope_not_probed` stands between the two.
    *Settled by decision 149A (2026-10-20)*: a new review reads its document again once the backend
    is ready, and refuses one that changed, in plain words, making nothing (149A, below).
- **Mutations**: each fix is pinned by a case that turns red when it is taken out: 14 mutations
  for the tabs (T114), 38 red results in all; 21 for a remodel run (T116), 75 red results in
  all; and 4 for the review's findings (T119), 10 red results in all; and for the second review
  45 - 7 for the check pages (T122), 26 red results; 6 for a plan's document (T124), 13; 6 for
  Start after its gate (T126), 16; 7 for a throwing run reading and the refusals written once
  (T127, T128), 9, the one that removes the review host's own catch surviving as an equivalent
  mutant; 8 for a failed restart (T130), 15; and 11 for the restart-first sentence (T132), 14 -
  93 red results in all; and for the third review 25 - 9 for the check page's latest check, a
  refused `init` and a stale re-read (T135), 26 red results; 9 for the backend's own error
  banner (T137), 18; 2 for a save's other failure (T139), 3; and 5 for the words and the two
  things written once (T141), 145 - 192 red results in all - each taking one fix out, the tree
  rebuilt and restored after each.
- **Tests**: T113, T115, T118, T121, T123, T125, T127, T129, T131, T134, T136, T138 and T140 in
  [tasks.md](tasks.md), each written first except T127, which pins what T116 built.

### 146A. Three run-folder fixes left by 142A (2026-10-19)

- **Question**: 142A recorded three things it noticed and did not change (above, "Noticed, not
  changed"). It refused a folder for what the folder holds with the path rule's class,
  `InvalidRunDir`, whose sentence in the words file reads "The run folder is not inside the run
  root. Check the run root in Settings."; the Review page shows a class's sentence first and its
  message only in a fold (`render.js`, `plainError`), so an engineer refused for a folder holding
  a check, or another review, was sent to a run root that was right. A start still claimed the re-modeler's
  grade folders as Model check folders: the grade's session went aside, the review wrote over its
  `report.md`, and the run's `rms-before.json` or `rms-after.json` then named the review's files.
  And `GET /reviews/{run_id}` refused any folder holding `check.json`, so a review that claimed a
  Model check's folder - as feature 003 User Story 6 scenario 11 and feature 007 FR-021 intend -
  could not be restored read-only after a restart.
- **Decision** (owner decision 146A): fix the three, test first. A context review's Retry after a
  backend restart (108A) and the command line's `--out` stay as they are (Not changed, below).

**1. A class of its own for a folder another run holds.**

- Two designs were weighed:
  - *one class, with a sentence true of every refusal and the reason in the message* - say, "The
    review cannot use this run folder. Press Review to review into a new run folder; if it is
    refused again, check the run root in Settings." Nothing changes on the wire and one sentence
    changes; but the sentence is vaguer than either case, an engineer whose run root is wrong is
    refused a second time before being told to look at it, and what is true of the folder stays
    in the fold, in the words FR-026 (feature 009) keeps out of the engineer's way;
  - *a class for each way on, each with its own sentence* - **chosen**. The cases differ in what
    is true and in the way on: a path the rule refuses is fixed in Settings, a folder another run
    holds by reviewing into a new one. The sentence is the first thing the page shows, so it must
    be true of every refusal that carries its class. This is 143A's precedent: `TurnRunning`'s
    sentence was untrue of a remodel run, so a remodel run got a class of its own,
    `RemodelRunning`, rather than a vaguer sentence for both.
- `InvalidRunDir` is the path rule's alone (`resolve_run_dir`, on every route that takes a
  `run_dir`), and its sentence states the rule rather than that the folder is outside the run
  root, which is untrue of a network path under a network run root and of a path spelled with
  `..` that lands inside: "The backend refused the run folder's path: it writes only into a local
  folder inside the run root. Check the run root in Settings."
- Every refusal `_claim_run_dir` makes for what a folder holds is the new `400 RunDirTaken`, not
  retryable: "This run folder already holds another run's files, which a new review must not
  write over. Press Review to start the review in a new run folder." One class, not one per kind
  of folder: what the folder holds changes the message and not the way on, and the one sentence
  is true of each. The messages:

  | Refused | Message |
  |---|---|
  | A start or a Retry on a re-modeler grade's folder (item 2) | "`<run_dir>` is the folder of the `<side>` grade of the remodel run in `<parent>`: a review never claims a grade's folder, which only the remodel run writes; review into a new run folder" |
  | A Retry on a Model check's or a Standards check's folder, a start on a Standards check's | "`<run_dir>` holds the `<family>` check that ran in it and no review session: a Retry replaces only a review's session, and only a Model check's folder is handed to a new review; review into a new run folder" (142A's, unchanged) |
  | A start on any other folder that holds a session | "`<run_dir>` already holds a session that a start does not write over: review into a new run folder, or retry the chat that wrote it with 'retry_of'" |

  The last said "already holds a review session; retry it with 'retry_of' ...": untrue of a
  remodel run's own folder, whose session is the re-modeler's, and of a check's folder whose
  record cannot be read, which `is_check_folder` cannot tell from a review's; and since 142A
  only the chat that wrote a session may replace it.
- Unchanged: `RunDirInUse` (409: a chat on the folder is live or being set up),
  `_require_retried`'s `UnknownChat` and `RunDirInUse` (142A), every status, and the add-in,
  which makes neither class: it passes the backend's refusal on (`CreateReviewSession`) and the
  page prints the class's sentence. `test_review_words.py` asserts every `ChatError` subclass has a sentence,
  `RunDirTaken` included, and pins both; `ErrorLabelsCoverTheHostTests` scans the classes the
  add-in and the page make, which this does not add to, and passes unchanged.
- The pane fixtures that carry the words file's labels are regenerated with their generators in
  the commit that changes the words (015 R2.25): `review-big-assembly.json`
  (`generate_pane_fixture.py`), and `review-waiting.json`, `review-waiting-big-assembly.json` and
  `review-waiting-restored.json` (`generate_waiting_fixtures.py`, whose
  `review-not-sent-session.json` came back byte for byte). Each diff is the one sentence changed
  and the one added. `review-send-failure-events.json`'s pin of `review-waiting.json`
  (`source_fixture_sha256`, over the bytes `ReviewPageSendGateTests` reads) moved with it, as
  143A moved it.
- The two captured fixtures have no generator. `review-waiting-apply.json` carries no labels.
  `review-waiting-apply-failure.json` carries the `labels` block it was captured with, before
  015's T100: 58 error classes against the words file's 67 - none of 016's seven, nor
  `RemodelRunning`, nor `RunDirTaken` - and the old `InvalidRunDir` sentence. Nothing reads that
  block: its cases read its `before_save` and `after_save` captures, and the page under test takes
  its labels from `review-waiting.json` (`WaitingReviewFixture`). It is left as captured, as 015's
  review and 143A left it: a hand edit would break the capture and the hashes 015 recorded for it
  (R2.25), and regenerating it needs a generator, which is code. If the owner wants its labels
  current, that is a small generator task.

**2. A grade's folder, told by the remodel run's layout and not by its record.**

- A grade's folder and a Model check's both hold a `check.json` naming the `session.json` beside
  it, written by `run_rms_check`, family `rms`. The records differ only in prose - a grade's
  carry-forward `reason` is `SUPPLIED_STORE`'s sentence, because the re-modeler hands its store
  in - which a refusal should not rest on. What tells them apart is where a grade is:
  `grade_remodel_run` grades each side in a folder of its own, `rms-before/` or `rms-after/`,
  inside the remodel run's folder, and files that side's dump beside it as `package-before.json`
  or `package-after.json` (`write_package`) before it grades anything. `remodel/artifacts.py`,
  which writes that layout, answers the question (`grade_side_of`): the folder is one of the two,
  and its side's dump is beside it.
- Not by the name alone: a Model check's folder called `rms-before` in the run root has no dump
  beside it, and is claimed as a Model check's. Not by `rms-before.json` or `rms-after.json`,
  which name the grade's files but are written only after both grades: a run cut off between a
  grade and its artifact would leave a grade's folder nothing names, which a start would claim.
- The grade is asked about before the folder's files, so a grade's folder is refused whatever it
  holds - before its grade is written too, when it holds only its `package.json`: a start claimed
  that as a folder holding no session, and the grade would then have written its session and
  report over the review's. A Retry meets the same refusal; 142A refused it as a check's, with
  the check's words. A re-run (`recheck: true`) is not refused here: it re-runs a waiting review
  in its own folder, and `_waiting_record` refuses a grade's, which waits for nothing
  (`409 NotWaiting`, nothing moved).
- Records: of every spec and contract, only 002 `contracts/chat-api.md` said a start claims a
  grade's folder (142A's paragraph), and it is amended. 004 described a grade's artifacts and not
  its folders; `contracts/run-artifacts.md` gains the two folders, the layout that tells them
  apart and the rule, and `data-model.md` section 7 a row pointing there. 003 describes its own
  `-check` folder and no grade's (`contracts/model-check.md` section 4); its User Story 6 scenario
  11, and 007's FR-021, are about a Model check's folder, which a start still claims, so neither
  conflicts and neither is amended.

**3. A review beside a check, restored.**

- `GET /reviews/{run_id}` restores a folder that holds `check.json` when the record can be read,
  names a session, and that session is not the one `session.json` holds: a review claimed the
  folder and moved the check's session aside. `checks/rules/run.py` says so in one place:
  `recorded_session` raises `SessionReplacedError`, a `NotACheckError`, for exactly that case,
  and `session_replaced` asks it. The snapshot is `session.json`'s, the review's; the check's
  session at `session.N.json` is never read. A check's own folder - its record names
  `session.json`'s session - stays `404 UnknownReview`, and `GET /checks/{check_id}` is its route;
  the claimed folder stays `404 UnknownCheck` there. The rule is every family's.
- It is the rule the claim reads (`is_check_folder`: a folder is its check's while its record
  names the session beside it) and the one 132A gave a report (015 `contracts/records.md`
  section 4), so the three cannot disagree about whose a session is.
- A record that cannot be read, or that names no session, cannot show whose `session.json` is,
  and nothing is guessed through: `404`, as before 146A. A record naming no session read, until
  now, as one naming another ("the record describes session None"); `recorded_session` now
  refuses it as a record it cannot read, the same `NotACheckError` to every caller, so
  `GET /checks`, the claim and the command line's check readers answer as before.
- **Edge cases**, each decided and tested (`test_chat_review_routes.py`, `test_chat_server.py`):
  - the review's own chat retried it there: `session.1.json` is the check's, `session.2.json` the
    attempt replaced, and `session.json`, the latest, is restored;
  - a `session.json` that cannot be read: no review to restore, `404`;
  - a `check.json` that cannot be read, is no JSON object, or names no session: `404`;
  - the review's `session.json` gone, the check's still at `session.1.json`: `404`, and the
    check's session is not restored in its place;
  - a folder holding both records as the check wrote them: `GET /checks` answers it and
    `GET /reviews` does not; a claimed one the other way round;
  - every family: any family's own session is not replaced, and another session in its place is.
- **What it leaves**: a check run cut off after it saved its session and before it wrote its
  record (`run_rms_check` writes `session.json`, then `report.md` and `attention.json`, then
  `check.json`, and an Accept re-runs the check that way) leaves a check's session its record does
  not name. `GET /checks` already reads that folder as no longer the check; `GET /reviews` now
  restores that session read-only as a review's. Owner question 1, below.

- **Not changed**:
  - a context review's Retry after a backend restart (108A) stays `404 UnknownChat`, with nothing
    moved: 142A's cost, above. Keeping it needs the folder to record which chat wrote it, or
    `retry_of` to accept the review session id the folder records, both left to the owner as 142A
    left them;
  - `swreview review --out` keeps writing into any folder it is given - a check's, a grade's or a
    review's - with no claim rule (142A, "The command line is not changed");
  - the path rule and every route's use of it: `InvalidRunDir` keeps its status, and only its
    sentence changes;
  - `report/rerender.py` asks whether a session is its check's in its own words (`check_run`,
    the record's `session_id` against the session's, 132A), a second statement of the rule
    `recorded_session` holds. The two agree on every record this backend writes, and on one
    naming no session, so it is noticed and not touched.
- **Owner questions** (recorded 2026-10-19, behaviour unchanged):
  1. A check run cut off between its session and its record is restored by `GET /reviews` as a
     review (What it leaves, above). Leave it - it takes a kill inside one synchronous request,
     and what is restored is read-only and true of the folder - or restore a folder holding
     `check.json` only when its session also opens a stream there? A review always writes
     `events.jsonl`, rotated with its session on a Retry, and a check never does; but that test
     would also refuse a review whose stream was removed by hand. *Kept recorded by decision 149A
     (2026-10-20)*: unchanged - such a folder is still restored read-only as a review's - and the
     question stands here as recorded (149A, below).
- **Review**: each fix is pinned by taking it out once - 13 mutations of the reviewer's code, 74
  red results in all, and 1 of the pin, 3 red C# cases. The claim's refusals back to
  `InvalidRunDir` (15 red), the session's words back to "a review session" (4), each sentence in
  the words file (7 and 8), the grade's refusal (5), the grade without its dump beside it (3) or
  without its name (4), the grade asked only of a folder holding a session (1), `GET /reviews`
  refusing any `check.json` (2), `recorded_session` raising no `SessionReplacedError` (11), a
  record naming no session taken for another (2), a folder that cannot be read guessed through
  (8), a check's own folder restored (4), and `review-send-failure-events.json`'s pin left on
  the old `review-waiting.json` (3, in `ReviewPageSendGateTests`).
- **Tests**: T106, T108 and T110 in [tasks.md](tasks.md), each written first.

### 147A. Four sentences say what is true (2026-10-19)

**Decision** (owner decision 147A): four wording fixes, test first where a test pins the words.
Feature 011's refusal once the limit of ten is spent names a new Review as the way on;
`suppress-test`'s refusal no longer calls the extractor's read-only open its only open path;
FR-001 names the tabs the pane shows; and `BackendUnavailable`'s label covers a backend that
does not answer as well as one that is not running.

1. **Feature 011's refusal once the limit of ten is spent** (`ConfirmedDrawingRead.LimitReached`,
   the one helper both limit sentences share; 011 `contracts/confirmed-open.md` section 2 item 5,
   amended, and the `drawing.read` bullet of `extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md`).
   - Old end: "; a drawing already open in SOLIDWORKS is still read, since reading it opens
     nothing, and a new review session (Retry or Recheck) starts its own count".
   - New end: "; a new review (press Review) starts its own count, and a drawing already open in
     SOLIDWORKS is still read, since reading it opens nothing".
   - Why: 011 research R9.5's first question. A Recheck starts its own count, but carries an
     earlier confirmed answer onto the same candidate question with no new read (015
     `contracts/recheck.md` section 4), so after a read refused for every candidate it reads
     nothing again; and Retry is offered only on an error card, which this refusal does not
     raise - the backend records it as the candidate's coverage reason. Review starts a review in
     a run folder of its own (`ReviewHost.StartReview`, `RunFolders.CreateForDocument`), so a
     session whose count starts at nothing, which reads natively the open drawings that show its
     design and asks the candidate question afresh: the surest way on, now named first. The
     second way on is kept word for word, with the two limits R9.5 item 4 records, and the
     sentence is still said only while the package holds fewer than ten drawings, so both ways
     are true whenever they are named. A Recheck, or a context review's Retry, still starts its
     own count (011 research R9.1); the sentence no longer names either. The ten-records sentence
     is unchanged. 011 research R9.5 item 1 carries a dated note.
   - Left open: whether a Recheck should ask a refused candidate question again, R9.5's other
     question, is not part of 147A and is still the owner's.
2. **`suppress-test`'s refusal** (`SuppressTest.DocumentNotOpenMessage`).
   - Old: "'{path}' is not open in SOLIDWORKS. Open it with write access first: suppress-test
     never opens a document, because the extractor's only open path is read-only and a read-only
     document cannot be suppressed."
   - New: "'{path}' is not open in SOLIDWORKS. Open it with write access first: suppress-test
     never opens a document, because the extractor opens your documents only read-only, and a
     read-only document cannot be suppressed."
   - Why: the extractor has more than one file-opening call (decision 137A; 011 research R8.4),
     so "its only open path" was untrue - and "every open is read-only" would be untrue too.
     Every call that opens a document of the engineer's opens it read-only: the console attach's
     `SwSession.OpenReadOnly` and feature 011's `DrawingOpenScope` (probe D14's as well), each
     `ISldWorks.OpenDoc6` with ReadOnly and Silent. The only calls that open a file for writing
     are feature 004's `OpenDoc7` opens, with Silent and LoadModel and never ReadOnly, of the
     re-modeler's own copy, which its run made in the run folder, and of `probe remodel`'s own
     throwaway part: files the extractor made, never the engineer's (the constitution's second
     exception: "The engineer's file is never opened for writing"). So the sentence says what
     holds of every open the extractor makes, that it opens the engineer's documents only
     read-only; the comment above it says why.
   - Where the old words were recorded: 011 research R8.5 item 6 left them to the owner. Feature
     003's records do not quote the message: the `suppress-test` row of its `contracts/cli.md`
     lists the refusals made before anything is touched, and this one is not among them. Nothing
     in 003 changes.
3. **FR-001** ([spec.md](spec.md)).
   - Old: "a Task Pane with a Review tab, an Ask tab (the CLI terminal) and an Extract tab", and
     "the three steps (open a document, extract evidence, review or ask)".
   - New: "a Task Pane with a Review tab, an Extract tab, a Model check tab, a Remodel tab and a
     Standards tab", and "the three steps (open a document, extract evidence, review)", with a
     dated note.
   - Why: the pane's tab list (`TaskPaneControl`'s constructor) is Review, then Ask only while
     `AskTabShown`, false since 2026-09-19, then Extract, Model check (feature 003), Remodel
     (feature 004) and Standards (feature 006), each built with its purpose sentence as banner and
     tooltip; and the step strip names the tabs step 3 is done on as the pane shows them, so it
     reads `3 Review` (139A). 139A left FR-001 as it was. User Story 3 and FR-020 still describe
     the Terminal tab, which is built and hidden; they are not changed. *Amended 2026-10-20 (owner
     decision 151A; its record is feature 011's research R13.3, its task 011's T204)*: each carries a
     dated note now, saying what the pane shows - the tab, captioned Ask, built and hidden since
     2026-09-19 (`TaskPaneControl.AskTabShown` false), its page not loaded and its host not attached
     - and that it holds as written were the tab shown again; no requirement's meaning changed.
4. **`BackendUnavailable`'s label** (`reviewer/src/swreview/report/review_words_v1.yaml`).
   - Old: "The review backend is not running. Save Settings to start it again, then retry."
   - New: "The review backend is not running or not answering. Save Settings to start it again,
     then retry."
   - Why: 143A gives the class to a backend that does not answer as well as to one with no
     process, and left the label to the owner's wording round (143A, Not changed). The way on is
     kept: a save starts the backend in both cases - when it does not answer, once the save's
     round trips have timed out.
   - The fixtures: every pane fixture that carries the label was regenerated with its generator,
     never by hand - `generate_pane_fixture.py --write` (`review-big-assembly.json`) and
     `generate_waiting_fixtures.py --write` (`review-waiting.json`, `review-waiting-restored.json`
     and `review-waiting-big-assembly.json`; `review-not-sent-session.json`, which carries no
     labels, came out byte for byte the same) - each differing in the label's line alone; and
     `review-send-failure-events.json`'s pin of `review-waiting.json`'s sha256 moved, as 143A
     moved it. The two captured fixtures have no generator and are left as captured (015
     `contracts/pane.md`, "A captured fixture"): `review-waiting-apply.json` carries no labels,
     and `review-waiting-apply-failure.json`'s captured labels block keeps the old words, beside
     the eight labels added since its capture that it already lacks, `RemodelRunning` among
     them. No test reads that block: its cases read only `before_save` and `after_save`, and the
     label the page shows in them comes from `review-waiting.json`.

**Tests**, T098, T100 and T102 in [tasks.md](tasks.md), each changed to the new words first and
run red against the old ones:

- The limit (T098): `ConfirmedDrawingReadTests.HowToGoOn`, which `TheLimitsRefusalSaysHowToGoOn`
  (three cases) and `AReviewWhoseFailedOpensAloneReachTheLimitIsRefusedBeforeItsPackageIsLoaded`
  assert exactly, and the full sentence in
  `ToolServiceWiringTests.ANewReviewSessionInTheSameRunFolderStartsItsOwnCountThroughTheReviewHostsRecords`:
  those five cases red, the other 53 and 97 cases of the two classes green; then all green.
  Changed because the words they pin change; nothing else they assert moved.
  `test_confirmed_drawing_read.py` passes unedited: the backend records the sentence as each
  candidate's reason and recognises none of it.
- `suppress-test` (T100): `SuppressTestTests.DocumentNotOpenMessage_NamesThePartAndWhyTheCommandWillNotOpenIt`
  keeps its three checks - the path, "write access", "read-only" - which the old words passed
  too, and now asserts the sentence exactly: red, then green. Tightened, so that untrue words
  cannot pass again.
- The label (T102): `RESTART_HOLDS` in `test_review_words.py`, which
  `test_each_thing_that_holds_a_restart_back_has_a_true_sentence` asserts exactly: red, then
  green. With the words file changed and the fixtures not yet regenerated, six fixture tests of
  `test_pane_fixture.py` and `test_pane_waiting_fixtures.py` were red, and once
  `review-waiting.json` was regenerated three `ReviewPageSendGateTests` cases were red on the
  pin until it moved; all green after. `ErrorLabelsCoverTheHostTests` reads the keys, not the
  words, and passed before and after.
- FR-001 is docs only: no test reads it.

**Evidence** (2026-10-19; before at `ef6d1ce`, after on the branch): the C# build,
`--no-incremental`, at zero warnings both times, and `SwReview.Extractor.Tests` 9,732 and
`SwReview.AddIn.Tests` 2,608 passed before and after - tests changed, none added. Python, not
live, with `SWREVIEW_REQUIRE_TOKENIZER=1`: before, on 3.11, 18,053 passed, 5 skipped and 1 failed,
`test_prices.py::test_run_spend_includes_failed_attempts[failed]`, which 147A does not touch and
which passed alone, and in its whole module three times in a row; after, 18,054 passed and 5
skipped on 3.12 and on 3.11 (`--isolated`), that case among the passed. `ruff check` clean, and
no broken link.

### 149A. Evidence from the wrong document: a new review reads its document again, and `ScopeRefused` speaks plainly (2026-10-20)

- **Question**: 145A's reviews left two things to the owner (145A, Not changed). A new review read
  the active document before the waiting settings restart it makes first (`BackendReady`), and its
  dump attaches to whatever is active after it (`SwReviewDump.Run`): a restart takes seconds, in
  which the engineer can make another document active, so the run folder named for one document
  could hold another's evidence. And the bridge's `scope_not_probed` reached the Remodel tab as
  `ScopeRefused` in the bridge's own words, which name both full paths, on a tab whose words name
  no path. The same decision answers two questions recorded earlier: 146A's, a check run cut off
  between its session and its record, which `GET /reviews` restores read-only as a review's; and
  011 R9.5's, a Recheck that does not read a refused drawing again.
- **Decision** (owner decision 149A, "2A", 2026-10-20): "Evidence from the wrong document, test
  first: a new review reads the active document again once it has made a waiting restart, and
  refuses in plain words if it changed, as Plan and Start do since 145A; and `ScopeRefused` reaches
  the Remodel tab in plain words, with no path. A check run cut off between its session and its
  record (146A's question) and a Recheck that does not read a refused drawing again (011
  `research.md` R9.5) stay recorded."

**1. A new review reads its document again once the backend is ready.**

- **How**: `ReviewHost.StartReview` reads the active document again once `BackendReady` has
  answered - after any settings restart the start made or waited for - and compares it with the one
  it read first by `PageDocument.IsSameDocument`, the rule Plan uses since 145A (T124): the path
  ignoring case, the configuration exactly. Another document, another configuration of it, none at
  all, or a drawing is refused `DocumentChanged`, retryable, before the run folder is made: nothing
  is extracted, no run folder is made, no session is created and no extraction is announced. The
  restart the start made stands and nothing is left held: the next press, its document active,
  runs on the restarted backend, which is not restarted again. The message names no path: "the
  active document or its configuration changed after the review was asked for, so nothing was
  extracted and no run folder was made. Make the part or assembly you want reviewed the active
  document, then press Review again."
- **Always, not only after a restart** (decided here; the decision's words name the restart):
  - *read again always, once the backend is ready* - **chosen**. One rule, Plan's: Plan reads its
    document again after its gate whatever the gate did. It is explicit: `BackendReady` stays a
    yes or no, the review's question about its evidence is not tied to what `DeferredRestart`
    answered, and a wait added to the gate later is covered without anyone remembering to report
    it. It is true of any change between the two readings, whatever took the time. It costs one
    more `CurrentDocument` - a few reads on the application thread, which the add-in makes several
    times per document switch - before minutes of extraction. With nothing waiting the two readings
    are a moment apart, so a refusal there is rare, and right: the dump would read the other
    document;
  - *read again only when a restart was made or waited for*: `BackendReady` would have to say
    which (`Outcome.Restarted` or `RestartedMeanwhile`, against `NotPending`) and the review branch
    on it - one more branch, with its own tests - and the moment before the gate would be left
    uncovered.
  - Both branches are pinned (T143): the restart the review makes (four kinds of change), the
    restart it waits for (the watcher's), and no restart waiting at all; and on the path the
    add-in takes, through a preparation (`review.prepare`, then `review.start` with its
    `preparation_id`), which T148 adds.
- **The class and its label**: the Review page shows a class's label first and the message in a
  fold (`render.plainError`; 009 `contracts/plain-words.md` section 5), and every class the host
  sends has a label (`ErrorLabelsCoverTheHostTests`). Three were weighed:
  - `PreparationExpired` ("The preparation is out of date. Press Review again."): the add-in always
    prepares a review, and the class's message is the nearest case - the document changed between
    the preparation and the start - but the label speaks of a preparation, which a host without one
    (`ReviewHostOptions.PrepareReview` null) never made, and which was still current when the start
    read the document;
  - `ReviewNotActive` ("This review is of another document. Open that document in SOLIDWORKS, then
    try again."): a Recheck's and a context Retry's, about a review that exists; a refused new
    review is no review yet, and its way on is either document;
  - `DocumentChanged` - **chosen**: the Remodel tab's class for the same event since 145A, so one
    word means one thing on every tab, with a label of its own, true of every refusal that carries
    it on the Review page: "The active document or its configuration changed while the review was
    starting, so nothing was extracted. Make the part or assembly you want reviewed the active
    document, then press Review again." The Remodel page reads no words file, so the label is the
    Review page's alone.
  - The pane fixtures that carry the words file's labels are regenerated with their generators
    (`generate_pane_fixture.py --write`: `review-big-assembly.json`; `generate_waiting_fixtures.py
    --write`: `review-waiting.json`, `review-waiting-big-assembly.json` and
    `review-waiting-restored.json`, `review-not-sent-session.json` coming back byte for byte), each
    differing in the one added line, and `review-send-failure-events.json`'s pin of
    `review-waiting.json` moves to its sha256 as written on Windows. `review-waiting-apply.json`
    carries no labels, and `review-waiting-apply-failure.json` keeps the labels it was captured
    with, as 146A and 147A left it.
- **The other starts**, checked: the rule applies where a waiting restart can come between a
  reading of the document and a dump.
  - A Retry of a review started without saved context is `review.start` with `retry_of`: a new run
    folder and a new dump, through the same code, so it is read again (pinned by its own case).
  - A Recheck (015) reads the document, checks it is the review's, and makes the restart first -
    and extracts nothing and asks SOLIDWORKS nothing: it re-runs the checks on the evidence saved
    in its own run folder and carries the first run's live detection over rather than detecting
    again (015 `contracts/recheck.md` section 3). A document made active during the restart cannot
    put another document's evidence in its folder, so it is not read again. Its check that the
    review's document is active is the page's binding (`recheck.md` section 1, check 3), and a
    switch after it reaches the page as `document.changed`, as for any review. A guard case pins
    it, so that a dump, a live call or a reading after the gate is a deliberate change.
  - A context review's Retry (108A) extracts nothing either, and this record first said the same
    of it; the review of 149A found it untrue (Review, below). Every pane review runs its checks
    first (`agent/settings.py`, the pane's efficiency defaults), a Retry carries none of them over
    (`agent/runner.py`, `prerun_checks` with no `carried_live`), and the first of them, the live
    interference check, runs over the whole assembly the session's bridge is attached to and
    writes its rows into the review's package (`prerun.py`, `_live_interference` and
    `_persist_rows`). The bridge is the tool service's (`ReviewHostOptions.Bridge`, which
    `SwReviewAddIn` sets from the gate), and the tool service follows the active document unless a
    turn or a remodel run holds it - and a restarting backend answers no question about a turn,
    which `AnyTurnRunning` reads as none. So a document made active during the restart had its
    interference rows written into this review's package and judged as its findings. The Retry now
    reads its document again once the backend is ready, and refuses a change as it refuses a Retry
    pressed on another document: `ReviewNotActive`, retryable, in the same words, written once
    (`SendContextRetryNotActive`). Not `DocumentChanged`: its label sends the engineer to Review,
    which would start a new review and lose the saved context, where the way on is the review's
    own document and Retry - which is what `ReviewNotActive`'s label says ("This review is of
    another document. Open that document in SOLIDWORKS, then try again."), true here as before the
    gate. The guard case that pinned the old behaviour became a refusal case (T148).
  - A context review (016): `context.prepare` reads the document only after `ContextReady`, which
    makes the restart first, and again after its dump; `context.selection` and `context.review`
    compare the prepared document with the active one after `ContextReady`. Read after the gate
    already; unchanged.
  - The Extract tab: no backend and no restart. It runs on the SOLIDWORKS thread, where the engineer
    cannot switch documents while it runs; it reads the document only at its dump's attach
    (`SwReviewAddIn.OnDumpRequested`); and it writes to the folder the engineer chose, named for no
    document. Unchanged.
  - The Model check and Standards tabs, and the Terminal tab's Extract evidence: no restart gate - a
    check is not a turn to the restart (145A) - so no waiting restart comes between their reading
    and their dump. Unchanged.
  - The Remodel tab: Plan reads its document again after its gate since 145A (T124); Start reads its
    plan's session again (T119) and no document.
- **What is left**:
  - The moment between the second reading and the dump's attach, one call on the application
    thread apart with nothing slow between them, as Plan has between its second reading and its
    probe. Closing it would take the dump to check the document it attaches to, within the same
    application-thread call; `SwReviewDump.Run` attaches to whatever is active by design (011
    `contracts/attach.md`), and `IReviewDump` is every tab's. Not done: owner question 1, below.
  - The bridge a session is given is whatever the tool service is attached to when the session is
    made, and nothing compares it with the review's document: not the add-in, and not the backend,
    whose bridge `ping` names the document it is attached to and is not asked for this. A second
    reading shows only what is active. The tool service follows a switch on a thread of its own, so
    for a moment after a switch back it is still attached to the document left; and it does not
    follow a switch made while a turn or a remodel run holds it, nor afterwards until the next
    switch - with no restart at all. Found while checking the review's finding, older than 149A,
    and not changed: owner question 5, below.

**2. `ScopeRefused` in plain words.**

- **Where `ScopeRefused` comes from**: two places, and only one names a path.
  - The bridge's refusals of `remodel.open`, which `chat/remodel.py` maps by `error_code`
    (`BRIDGE_REFUSALS`). `scope_not_probed`, at the open's first step, before anything is copied:
    the open names a file no probe of this bridge session was minted for - "'{probe_id}' is not a
    probe this bridge session performed. ..." or "probe '{probe_id}' was minted for '{path}' and
    this request names '{path}'. ..." (`RemodelScopeProbe.Require`). The probe reads the document
    active when it runs (`BackendRemodelPipeline.ProbeScope`) and the open names the one the host
    read (`OpenCopy`), so since T124 this is a part made active in the moment between the plan's
    second reading and its probe. `scope_changed` in the open's re-reading of the source, before
    the copy - the source open read-only, and "Don't prompt to save read-only referenced documents"
    turned on since the probe: "'{source}' is open read-only and SOLIDWORKS now discards changes
    ..." (`BridgeDispatcher.RecheckSource`) - or at its twelfth step, after the copy, which is then
    deleted: "the copy's scope signals differ from the probe's in {signals}. ..."
    (`BridgeDispatcher.OpenIn`). Two of the four sentences name a full path, one of them both, and
    two name the probe.
  - The add-in's own, once the probe has answered: `RemodelHost.ScopeAllowsARun` sends the scope
    gate's refusals (`ScopeGate.evaluate`, through `POST /remodel/probe`) and its own unread
    signals, "the re-modeler will not run on this part: ...". These name signals and their values -
    folder and feature-type names - and no path: the signals the gate refuses on hold none.
    Unchanged.
- **How**: `_refusal`, the one mapping from a bridge refusal to the page's class, gives the two
  codes plain words (`SCOPE_REFUSAL_WORDS`), one sentence per code true of every refusal under it,
  and logs the bridge's sentence on the module's logger at `WARNING`, which reaches the backend's
  log. That line duplicates one already written: the tool-service log, in the same logs folder,
  records every failed bridge request with the bridge's sentence (`ToolServiceHost`'s request
  line, `error="..."`; `BridgeDispatcher`: a failed open's request line goes there). It is there
  for whoever reads the backend's log, beside the request that was refused. This record first
  called it the one record left of which files disagreed, which the review of 149A found untrue
  (Review, below). Every other code keeps the bridge's sentence.
  - `scope_not_probed`: "The part to be copied is not one this remodel checked, so nothing was
    copied and no new plan was made. Your part was not changed. Make your part the active document
    and press Remodel a copy again."
  - `scope_changed`: "The part, or the copy made of it, no longer reads as it did when this remodel
    checked it, so the remodel stopped and no new plan was made. Your part was not changed. Press
    Remodel a copy again to check it afresh; if the same happens again, the copy reads differently
    from your part once SOLIDWORKS opens it, and this part cannot be remodeled as it stands." True
    at both points it is raised. Before the copy, no copy was made; after it, the bridge's unwind
    deletes the copy only when it can (`BridgeDispatcher.DeleteCopy` leaves one that will not
    delete), so the words say nothing of the copy's fate and vouch for the engineer's part alone,
    as the tab's own refusals do (`RemodelHost`: the copy may have been changed, or never existed).
    Its first words, "no copy was kept ... Press Remodel a copy again to check it afresh.", promised
    both a deleted copy and a press that names the reason; the review of 149A found neither true
    after the copy (Review, below).
  - The words follow the tab's own refusals of a plan (`RemodelHost.DocumentChangedMessage`): what
    was not done, that the engineer's part was not changed (`PartNotChanged`), and the button by its
    label - a case reads both from the add-in's sources. Pressing again probes afresh: a reason the
    gate reads is then named by it, in its own words, the read-only option among them (U26), which
    covers the refusal before the copy. A copy that reads differently from the part after it does so
    on every press, and the gate passes the part each time, so `scope_changed`'s words say what a
    second refusal means.
- **Why in the backend**: the page prints the message it is given, which comes from the backend
  through the add-in unchanged (`RemodelBackendClient`, `RemodelHost.SendRefusal`); the add-in also
  posts it as the run line's `status {stage: "error"}` (`RemodelHost.Plan`). One mapping, where the
  bridge's codes already become the page's classes, reaches both, on every route that maps a bridge
  refusal. The bridge's sentences are unchanged: they are the bridge's contract (004
  `contracts/bridge-remodel.md`).
- **The other refusals the Remodel tab prints with a path**, checked; recorded, not changed - the
  decision names `ScopeRefused`, and each of these is a wording of 004's to decide:
  - On every plan, the bridge's refusals of `remodel.probe_scope`, its sentence passed on:
    `source_dirty` (`DocumentDirty`, "'{path}' has unsaved changes. ...") and `external_refs`
    (`ExternalReferences`, "'{path}' has {n} external file reference(s). ..."), which every part
    with unsaved changes or with references meets; `not_a_part` (`NotAPart`), for a part the bridge
    cannot find on disk or that is open as another type; and `source_not_open`, which has no row
    and so reaches the page as `RunFolderFailed`. The add-in's own plain sentences for the first two
    (`RemodelHost.ScopeAllowsARun`: "the part has unsaved changes. ..." and "the part carries {n}
    external file references, ...") are never reached with the bridge as it is: its probe refuses
    before it would answer `save_flag_dirty: true` or a count other than zero
    (`RemodelScopeProbe.Probe`).
  - From `remodel.open`: the same refusals on the source's re-reading (`RecheckSource`), and the
    copy's own (`copy_exists`, `copy_failed`, `open_failed`, the save target's), which name the
    copy.
  - The backend's own: the run folder's path in `PackageMissing` ("package-before.json is not in
    {run_dir}; ..."), in `POST /remodel/plan`'s `RunFolderFailed` ("open.json is not in {run_dir}",
    the carry-forward's "could not be carried into {run_dir}") and in `copy_path_for`'s.
  - The add-in's own `RunFolderFailed` ("the run folder could not be created under '{run_root}':
    ..."), and the run line's `status {stage: "error"}` with the message of a pipeline call that
    failed.
  - The add-in's own `RunNotFound` ("this pane did not start a remodel run in '{run_dir}', ..."),
    for a run folder the page names that this host did not start, from the shared run lookup and
    from Start, Discard and the other run requests (`RemodelHost`, its `PaneRunLookup` and
    `SendRunNotFound`) - added on review.
  - The add-in's `status {stage: "error"}` when the copy goes while a run is in progress ("the copy
    '{copy}' is no longer there, so the run is stopping. ..."), which only a Start's run meets, and
    so not while Start is switched off - added on review.
  - `POST /remodel/runs` and the routes after it (`RunInProgress`, `RunNotPlanned`,
    `ResumeRefused`) name the run folder too, and are not reached while Start is switched off in
    this build (`StartNotValidated`).
  - *Settled in part 2026-10-20 by owner decision 155A (owner question 3, below; 004 research
    R18.1):* `DocumentDirty` and `ExternalReferences` - the add-in's own sentences now, whoever
    refused - the add-in's `RunNotFound` and its word on a copy gone during a run speak plain words
    and name no path. The rest of this list stands, recorded again in 004 research R18.7.

**3. Kept recorded.** Both questions stand as recorded, behaviour unchanged, each with a dated
note where it is recorded: 146A's owner question 1, above, and 011 `research.md` R9.5 item 1's
second question.

- **Contracts**: 002 [`contracts/pane-host-messages.md`](contracts/pane-host-messages.md)
  (`review.start`); 004 `contracts/pane-remodel-messages.md` (`ScopeRefused`, and the restart
  section's sentence on `scope_not_probed`) and `contracts/backend-remodel.md` (`ScopeRefused`),
  each with a dated 149A note.
- **Not changed**:
  - The scope gate's own refusals, which name signals by their tokens ("solid_body_count is 2:
    ...") and no path; they are 004's report lines too (`ScopeGateResult.coverage`). Owner question
    4, below.
  - A scope refusal stays not retryable: the Remodel page reads no flag, and the gate's refusal of
    a part, a weldment say, is not one a press can change.
  - The bridge's sentences, and every refusal in the list above.
- **Owner questions** (recorded 2026-10-20, behaviour unchanged):
  1. The moment between a new review's second reading and its dump's attach (What is left, above):
     close it by having the dump check, within its own application-thread call, that the document
     it attaches to is the one the review read - a change to `IReviewDump`, which every tab shares -
     or leave it, since nothing slow runs in it?
  2. A Recheck checks that the review's document is active before its gate and not after it. It
     asks SOLIDWORKS nothing and cannot put evidence in the wrong folder, but it can run while
     another document is active. Check its binding again after the gate too, with its own
     `ReviewNotActive` - one small change, no new class - or leave it as pinned? (A context
     review's Retry, first asked about here, is now read again: R1 of the review, below.)
  3. On the Remodel tab, `DocumentDirty` and `ExternalReferences` carry the bridge's sentence and the
     part's full path, and every part with unsaved changes or with references meets them, while the
     add-in's own plain sentences for the two classes are never reached. Give them plain words in the
     backend's mapping, as the scope codes now have, and the rest of the list above with them -
     the add-in's own `RunNotFound` and its word on a copy gone during a run among them?
     *Settled 2026-10-20 by owner decision 155A ("4A"; 004 research R18.1; 004 T189, T190):* the four
     the decision names - `DocumentDirty`, `ExternalReferences`, `RunNotFound` and the stop when the
     copy is gone - say it in plain words with no path. For the first two the tab prints the add-in's
     own sentences, reached at last, whoever refused - in the refusal and in the run line's status -
     rather than plain words in the backend's mapping: one sentence per class serves every refusal
     under it, which the host can say from the class alone, where `ScopeRefused`'s two codes need
     the backend's two sentences. The backend's body keeps the bridge's sentence, which the
     tool-service log records on the refused request's line. The rest of the list above stays as it
     is, recorded again for the owner in 004 research R18.7.
  4. The scope gate's own refusals, which name signals by their tokens: reword them for the tab,
     which would change the reports' coverage lines too, or leave them? And `scope_changed` after
     the copy: the bridge's sentence named the signals that differed ("the copy's scope signals
     differ from the probe's in solid_body_count ..."), with no path, and it was the engineer's
     only clue; the plain words name none. Naming them in plain words needs the bridge to send
     them in the refusal's `detail`, since the code is shared with the refusal before the copy.
  5. The bridge a review's session is given is whatever the tool service is attached to when the
     session is made (What is left, above), so a review can run its live checks over another
     document than its own, and write that document's interference rows into its package, with no
     restart at all: started after a switch the tool service did not follow because a turn or a
     remodel run held it, or a moment after a switch back. Check, before the first live call, that
     the bridge is attached to the package's document - its `ping` names the document - and run no
     live check otherwise, recording why; or have the add-in make the tool service follow the
     review's document before the session is created, and wait for it; or leave it?
- **Review**: an independent adversarial review of the branch at `1f87be6` confirmed the second
  reading itself - on the right thread, nothing left half made, no false refusal, the fixtures and
  the pin right - and found one must-fix, two should-fixes and three nits, settled test first by
  T148 to T152:
  - R1 (must-fix): a context review's Retry could put another document's evidence in this
    review's run folder, and this record said it could not - its live interference check runs over
    the bridge, which follows the active document. The reviewer's throwaway probe showed it. Fixed
    by a second reading after its gate, refused `ReviewNotActive` as before the gate (The other
    starts, above). The guard case that pinned the old behaviour, `DeferredRestartTests`' theory
    over a Recheck and a context Retry, changes deliberately: the Recheck keeps its guard, as its
    own case, and the context Retry's becomes a refusal case. Checking the finding found the wider
    gap of What is left, owner question 5.
  - R2: `scope_changed`'s words promised a copy that was not kept and a press that names the
    reason, and after the copy the first can fail and the second does not hold. New words, true
    at both points it is raised, and the docstring's and this record's claims corrected (How,
    above); its pin changes deliberately, and a case pins that the words promise nothing of the
    copy. The clue the bridge's sentence gave is owner question 4.
  - R3: the reason given for the `WARNING` line was false. The line is kept, unchanged, and the
    reason corrected (How, above). The reviewer's checks are recorded here: a key in it is masked
    twice, by the backend's record factory and again by the add-in as it writes the backend's
    stderr to the log (`BackendProcess`); the line is in no report, fixture or handoff, since the
    handoff takes an allowlist of run-folder files (`handoff.py`) and the backend log is not one;
    and the backend log already carries design names, through the run ids in its access log's
    URLs.
  - N1: "the bridge's sentences name the probe and the part's full path" - two of the four name a
    path and the twelfth step's names neither, so they now "can name" it (`chat/remodel.py`, 004
    `contracts/backend-remodel.md` and `contracts/pane-remodel-messages.md`).
  - N2: the list of the Remodel tab's other refusals that carry a path left out the add-in's
    `RunNotFound` and its word on a copy gone during a run; both added, and to owner question 3.
  - N3: section 4b never went through a preparation, the add-in's path; a case now does (T148).
- **Mutations**: each fix is taken out once, by one exact replacement, the named tests run, and the
  file restored byte for byte (checked by its sha256): 16 mutations, 76 red results. M1 to M6 were
  run again with T148's cases, M7 and M8 are as first run - nothing they touch has changed since -
  and P1 to P5 were run again with T150's.

  | Id | Taken out | Red |
  |---|---|---|
  | M1 | A new review's second reading: the first compared with itself | 8: the four changes, the restart waited for, no restart waiting, the Retry, and the prepared start |
  | M2 | The configuration: the path compared alone | 1: another configuration |
  | M3 | The pane's rule: the path compared with its case | 1: the same document spelled otherwise |
  | M4 | The refusal's flag: not retryable | 8: as M1 |
  | M5 | The class: `PreparationExpired`, the nearest existing one | 9: as M1, and the label scan's list |
  | M6 | The words: the document's path added to them | 8: as M1 |
  | M7 | The label: `DocumentChanged`'s line taken out of the words file | 8: `ErrorLabelsCoverTheHostTests`' words-file case; the label's pin; and the six pane fixture tests, the committed fixtures no longer a fresh generation |
  | M8 | The pin's move: `review-send-failure-events.json` left on the old `review-waiting.json` | 3: `ReviewPageSendGateTests`' cases that read it |
  | M9 | A context Retry's second reading: the first compared with itself | 1: the context Retry's refusal |
  | M10 | A context Retry's refusal after the gate: `DocumentChanged`, a new review's | 1: as M9 |
  | P1 | The plain words: every scope refusal carries the bridge's sentence | 6: the four sentences and the two mapping cases |
  | P2 | The log of the bridge's sentence | 4: the four sentences |
  | P3 | `scope_changed`'s words | 4: its two sentences, its mapping case, and the case that it promises nothing of the copy |
  | P4 | `scope_not_probed`'s words | 3: its two sentences and its mapping case |
  | P5 | The plain words kept to the two codes: every code given them | 7: the other seven codes' mapping cases |
  | P6 | `scope_changed`'s new words: its first words back | 4: as P3 |

- **Tests**: T143, T145, T148 and T150 in [tasks.md](tasks.md), each written first.

**Evidence** (2026-10-20; before at `35d6ff7`, after on the branch): the C# build,
`--no-incremental`, at zero warnings both times; `SwReview.Extractor.Tests` 9,913 passed before and
after, and `SwReview.AddIn.Tests` 2,817 before and 2,827 after - the ten new cases of section 4b -
with the restart classes and the stub-children collection, 540 cases, green five times in a row.
Python, not live, with `SWREVIEW_REQUIRE_TOKENIZER=1`: 18,081 passed and 5 skipped before, and
18,087 passed and 5 skipped after - the label's pin and the five new route cases - on 3.12 (3.12.3)
and on 3.11 (3.11.16, `--isolated`) alike. `ruff check` clean, and no broken link. After the
review's fixes (T148 to T152): the C# build at zero warnings, `SwReview.Extractor.Tests` 9,913 and
`SwReview.AddIn.Tests` 2,828 passed - the old guard theory's two cases gone, three cases added -
and the restart classes with the stub-children collection, 541 cases, green five times in a row;
on Python 3.12 and 3.11, the files touched, the words, fixture and labels tests, the other remodel
tests and the tests that read `tasks.md`, 590 passed each, the full suites left to the run after;
`ruff check` clean, and no broken link.

### 150A. What a failed or stopped backend leaves on the pane (2026-10-20)

- **Question**: 145A left four things the pane said untruly once the backend failed to restart or
  stopped (145A, "Not changed"). A save whose restart failed other than with
  `BackendStartException` was answered `HostError`, not retryable, as if nothing had been saved,
  though the settings were written and in force in the host; one that failed with it was answered
  `settings.saved`, the failure alone in a `status`, which said neither that the backend did not
  restart nor how to go on. Every page's sentence for `backend.stopped`, "The backend stopped.
  Reopen the pane to start it again.", named a way that starts no backend. A check page's backend
  strip followed `init` alone, so under the banner that said the backend did not start it said
  "Backend ready" after a failed restart, and "Backend starting" after a failed first start. And
  an Accept whose re-read was dropped for a newer check said nothing of the exception it wrote.
- **Decision** (owner decision 150A, "3A", test first): "a save whose restart fails says the
  settings were saved and the backend did not restart, with the reason, retryable;
  `backend.stopped`'s sentence names saving the settings as the way to start the backend again; a
  check page's backend strip follows a failed restart; and an Accept whose re-read is dropped says
  its exception was saved. The three pages' restart handling stays as written."

**1. A save whose restart fails.**

- `ReviewHost.Save` writes the settings and puts them in force (`PersistSettings`) before it
  restarts the backend, so a restart that fails is a save that was kept and a backend that was not
  restarted. Whatever the restart throws - a `BackendStartException`, or anything outside that
  wrapper, such as the new backend's log not opened - the save is now answered
  `error {error_class: "BackendNotRestarted", retryable: true}` with "the settings are saved, but
  the review backend did not restart with them. Save the settings again to retry the restart. The
  restart failed: " and the failure, masked as every error is (`SendError`). Nothing is posted
  beside it: no `settings.saved`, and no `status` carrying the failure a second time. The other
  tabs are told as 145A tells them, only when no backend is up. The reason goes last because a
  restart's failure need not end in a full stop (`"... (log: <path>)"`).
- Three designs were weighed:
  - *`settings.saved`, and the new words in the `status`* - the shape a start failure already had.
    Nothing new on the wire, but nothing in it is retryable, and the Save line says "Saved." while
    the banner says the backend did not restart.
  - *`settings.saved` with a field for the failed restart* - one reply in two shapes, which the
    page and every reader of the contract would have to tell apart.
  - *an `error` of a class of its own, retryable* - chosen. "Retryable" is this channel's flag on
    an `error`, and the Review page shows a save's `error` on its Save line by the class's sentence,
    the class and the message behind a fold (FR-026), so the sentence says it in plain words and
    the message says it whole for a page that has no labels. `HostError`'s sentence ("The add-in
    hit a problem it did not expect") was not true of it, nor `BackendUnavailable`'s, which says
    nothing of the settings, and "not running" of a backend a restart that failed before it
    stopped anything left up.
- The class's sentence (`review_words_v1.yaml`): "The settings are saved, but the review backend
  did not restart with them. Save Settings again to retry the restart." The pane fixtures that
  carry the labels were regenerated by their generators, never by hand - `review-big-assembly.json`,
  `review-waiting.json`, `review-waiting-big-assembly.json` and `review-waiting-restored.json`,
  each differing in that line alone, and `review-not-sent-session.json` unchanged - and
  `review-send-failure-events.json`'s pin of `review-waiting.json` (CRLF, as written on Windows)
  moved. `review-waiting-apply-failure.json`, a capture with no generator, keeps its labels as
  captured, as 147A left it.
- The Review page (`app.js`) on that class: the sentence on the Save line; the message whole when
  it has no labels, as `TurnRunning`'s is, rather than "class: message"; and it asks `ready` again,
  as after a save that restarted the backend, so the key typed leaves the box, the key source says
  it is stored, and the page holds the backend there is now - the old one, or none.
- The Review page's strip: an extension of the decision's words, by the implementer's choice, not
  the owner's decision - item 3 names a check page's strip - made for the same defect, and put to
  the owner. On the Review page the `init` that followed a failed save restart named no backend
  and the strip said "Backend starting" under a Save line saying the backend did not restart - the
  same untruth, on the page item 1 changes. It now says "Backend not running" while an `init`
  names none, and "Backend ready" once one names one; an `init` naming none after that says
  "Backend starting" again, as during a restart. Its mark (`notRunning`) is its own and set by this
  class alone: the Review page has no lifecycle-banner mark to reuse, and 145A left its `status`
  handling as it is.

**2. `backend.stopped`'s sentence.**

- The Review page: "The backend stopped. Save Settings to start it again." The Model check,
  Standards and Remodel pages: "The backend stopped. Save Settings on the Review tab to start it
  again." The add-in starts the backend once, when it loads (`SwReviewAddIn.StartBackend`), and a
  settings save restarts it - `BackendSupervisor.Start` stops whatever runs and starts a backend,
  with none running too - so saving the settings is the way on, and the settings are saved on the
  Review tab. Reopening the pane starts nothing. The message type and its payload stay as the four
  contracts name them, and no host posts it.

**3. A page's backend strip follows a failed start or restart.**

- `check-page.js`, which the Model check and Standards pages share, now says "Backend not running"
  from `status {stage: "error", lifecycle: true}`, the add-in's own word that the backend did not
  start (145A), until an `init` names a backend: through an `init` that names none, "Backend ready"
  at the one that names one, which is where 145A takes the banner down, and "Backend starting" for
  an `init` naming none after that. An `error` that is not the add-in's word leaves the strip as it
  was.
- `remodel.js` does the same: an extension of the decision's words, by the implementer's choice,
  not the owner's decision - the Remodel page is not a check page - made because its strip had the
  same defect, following `init` alone; put to the owner.
- Decision: a mark of its own (`notRunning`), set and cleared where 145A sets and clears the
  banner's, rather than the banner's mark itself, which the instruction suggested reusing. The
  banner's mark is cleared by any banner put up since - 145A's rule, which
  `ABannerThatIsNotTheBackendsWordStaysThroughARestartsInit` pins - and the backend is still not
  running then. With that mark alone, a tab holding no backend, opened while the backend started,
  whose check then failed for want of one (a banner) said "Backend starting" at the next check's
  `init`, which the extraction's `status {stage: "ready"}` asks for while the tab holds none,
  though nothing was starting. `ABannerPutUpSinceTheLifecycleErrorLeavesTheStripSayingTheBackendIsNotRunning`
  pins it, and mutations C4 and M4, which put the banner's mark in its place, turn it red.

**4. An Accept whose re-read is dropped.**

- `acceptRule` shows its re-read only while its check is on screen (145A, third review). When it
  is not, the banner now says so, as it says of a re-read that failed: "Accepted as
  {exception_id}, and the exception is saved; a newer check was pressed before this check was
  re-read. Press the check again to see where it stands." "Pressed", not "shown": on the Standards
  page a newer check that fails before anything is graded clears the verdict, and the re-read is
  then dropped with no newer check on screen. The two notices are written once
  (`acceptedWithoutReRead`), and the failed re-read's words, which nothing pinned, are pinned by a
  guard that passes before and after.

**5. The three pages' restart handling** (`app.js`, `check-page.js`, `remodel.js`) stays as
written - the owner's answer to 145A's "Not changed". Each page keeps its own mark and its own
words for the strip.

- **Evidence** (at `35d6ff7`):
  - The save: `PersistSettings` puts the settings in force (`_settings = next`,
    `ReviewHost.cs:1273`) before the restart (`:1208`); a `BackendStartException` was answered
    `settings.saved` (`:1238`) and posted as a `status` (`:1242`), and any other failure thrown on
    (`:1235`) to `Receive`'s catch-all, `HostError`, not retryable (`:859`).
  - `backend.stopped`'s sentence: `app.js:284`, `check-page.js:243`, `remodel.js:190`. The add-in
    starts the backend when it loads (`SwReviewAddIn.cs:546`, `StartBackend` at `:1033`), and a save
    restarts it through `BackendSupervisor.Start` (`BackendProcess.cs:766`).
  - The strips: `check-page.js:1480` and `remodel.js:1166` render from `init` alone, and so does
    `app.js:3067`, whose `init` after a failed save restart came after the failure's `status`.
  - The Accept: `check-page.js:427` to `:433` shows its re-read only while wanted, and says nothing
    otherwise.
- **Review**: an independent adversarial review of the branch at `8b75949` found no must-fix, and
  these, settled test first by T160 to T164:
  - After a save whose restart failed once the old backend had stopped, the Review page stopped
    noticing that the backend was later replaced (S1). The `init` that followed named no backend,
    so the next one, naming the restarted backend, had no token to compare with, and the page asked
    the new backend for the old chat's stream - a 404 and a reconnect loop, which 143A's
    `AReInitOnARestartedBackendAsksNothingOfTheOldChatsStream` exists to prevent - and left a live
    waiting review live, its Send going to a backend that does not hold its chat (FR-042). Older
    than 150A for a start that failed and was answered `settings.saved`; 150A routed every failed
    save restart through it. On `BackendNotRestarted` the page now marks its backend replaced, as
    `backend.restarted` marks it: a fix in the page's restart detection, not the consolidation the
    decision rules out. The reviewer's two probes are T160's cases.
  - Nothing pinned that the dropped re-read's notice stays off an Accept whose re-read is shown
    (S2): a mutation that put it up then too survived every check page case. The Model check
    page's Accept case now asserts the banner stays hidden, and the Standards page has the Accept
    case it lacked, its twin.
  - The two strips the decision does not name were recorded under "Decision:", which reads as the
    owner's (O1, the owner's point): they are recorded above as the implementer's extension.
  - The way on was where no message goes (O2, the owner's point). `backend.stopped` names it, but no
    host posts it; a stopped backend reaches the pages as the add-in's `status {stage: "error"}`,
    whose banner carried the bare failure. That failure is now followed by the way on - on the Model
    check, Standards and Remodel tabs, after a first start that failed or a restart that failed once
    the old backend had stopped, "Save Settings on the Review tab to start it again."; on the Review
    tab, after a first start that failed, "Save Settings to start it again.", and after a restart
    that waited and failed, whether or not it stopped the old backend, "Save the settings again to
    retry the restart.". The three sentences are written once (`ReviewHost.StartItAgain`,
    `StartItAgainOnTheReviewTab` and `RetryTheRestart`, which the save's own answer shares), and
    `ReviewHost.WithTheWayOn` puts a full stop after a failure that has none (`"... (log: <path>)"`).
    The add-in's call for the other tabs is renamed `TellTheOtherTabsTheBackendDidNotStart`, since
    a failed first start makes it now too.
  - Recorded, not changed (O3, the owner's point): a restart that fails before the old backend
    stops leaves reviews running on it with mixed settings (Not changed, below).
  - Nits: a save made while the add-in unloads (N1: recorded below, since answering it otherwise is
    not small); three comments that said less than the code (N2: `RestartedForNewReview`,
    `PaneActions.PostStatus`'s `lifecycle`, the add-in's fan-out); this entry's account of the
    first start's strip (N3: corrected above); and the Review page's strip word, now the constant
    `NOT_RUNNING` the other pages name it by (N4).
  - Existing cases changed deliberately: the Model check page's Accept case asserts the banner
    stays hidden (tightened); `TheAddInTellsEachOtherTabARestartFailedAsAFailedStartIsTold` reads
    the renamed call and its way on; and the four cases that pinned a waited restart's `status`
    word for word - `ANewReviewWhoseRestartFailsIsRefusedWithThatFailure`,
    `ARestartThatFailsIsReportedAsAFailedStartIsAndNotTriedAgain`,
    `ACallThatWaitedForARestartThatFailedBeforeStoppingAnythingIsToldThatFailure` and the "after
    waiting" half of `ARestartThatFailsBeforeTheOldBackendStoppedTellsTheOtherTabsNothing` - expect
    the way on after the failure; nothing else they assert moves.
- **Not changed**:
  - A review, a turn call or a remodel run refused because a restart failed keeps
    `BackendUnavailable` with the failure (143A, 145A). The Review page shows the class's sentence,
    which names the way on; the Remodel page prints the message as it is (145A), so there the
    refusal names none.
  - A restart that fails before it stops the old backend - the launcher cannot be resolved, say -
    ends what waited (`End(caught)` in `DeferredRestart.Now` and `Apply`, `DeferredRestart.cs:313`
    to `:319` at `8b75949`; a save's, `ReviewHost.cs:1223` to `:1234`), so nothing waits any more.
    The next review or remodel run goes to the old backend, which keeps its environment - the key,
    `OPENAI_BASE_URL`, Gemini Enterprise - while the session takes the new provider, model and
    effort from the settings in force (`ReviewHost.cs:2311` to `:2313`), and the strip says
    "Backend ready". 143A's and 145A's rule is that nothing runs on the old backend with settings
    replaced since; this breaks it. Older than 150A (143A's edge case: one that fails before it
    stops anything leaves the old backend up); closing it is a design choice left to the owner.
    *Settled by decision 153A (2026-10-20)*: until a restart succeeds, every session takes the
    provider, model and effort the backend was started with, and the pane says the saved
    settings are not in force yet and that saving again retries (153A, below).
  - A save made while the add-in unloads - its restart refused because the backend client is
    unloading (`BackendClient.cs:212` to `:218`), or its start told to stop - is answered
    `BackendNotRestarted`, whose sentence says to save again. Answering it as the add-in stopping,
    in 143A's words, would not change what the page shows: the Review page shows a class's
    sentence, not its message, and those words go out as `BackendUnavailable`, whose sentence says
    to save too. It needs a class of its own, so it is not small; and the pane goes with the add-in,
    so the answer is seldom seen.
  - No host posts `backend.stopped`, and its handlers keep no mark for the strip: a page told it
    and then given an `init` naming no backend says "Backend starting".
  - A page that loads, or loads again, while no backend is up after a failed start or restart says
    "Backend starting": its `init` names no backend and nothing tells it why. Whether `init` should
    say why is the owner's.
  - The Review page's strip after a failed first start says "Error", from its `status` handling,
    which 145A left as it is; its new mark is set by a save's `BackendNotRestarted` alone.
  - A check tab keeps the port and token of a backend that stopped with a failed restart, and its
    calls fail as calls to a stopped backend do (145A).
  - On the Standards page a check that fails and an Accept's notice share one banner, and whichever
    lands last stays, as the failed re-read's notice and a check's failure did before 150A.
- **Mutations**: each fix taken out once with one exact replacement, the tree rebuilt, the named
  cases run and the file restored byte for byte (checked by sha256) - 28 mutations, 96 red
  results in all, and every mutation turned at least one case red; and for the review, 10
  mutations, 33 red results, every one red but S1b, an equivalent mutant (below):

  | id | where | taken out | red |
  |---|---|---|---|
  | H1 | `ReviewHost.Save` | every failure thrown on, answered `HostError` | 10 |
  | H2 | `ReviewHost.Save` | a start failure answered `settings.saved` and a `status` again | 8 |
  | H3 | `ReviewHost.Save` | not retryable | 4 |
  | H4 | `ReviewHost.Save` | no reason | 8 |
  | H5 | `ReviewHost.Save` | the reason alone, nothing of the settings being saved | 8 |
  | H6 | `ReviewHost.Save` | `settings.saved` sent after the answer as well | 4 |
  | H7 | `ReviewHost.Save` | the other tabs not told (145A's, kept) | 6 |
  | W1 | `review_words_v1.yaml` | no sentence for the class | 1 C#, 7 Python |
  | R1 | `app.js` | no `init` asked after the failed restart | 2 |
  | R2 | `app.js` | "class: message" with no labels | 1 |
  | R3 | `app.js` | the strip's mark never set | 1 |
  | R4 | `app.js` | the strip's mark never cleared | 1 |
  | R5 | `app.js` | the `init` ignores the mark | 1 |
  | R6 | `app.js` | `backend.stopped`'s old sentence | 1 |
  | C1 | `check-page.js` | a lifecycle `error` leaves the strip | 4 |
  | C2 | `check-page.js` | the `init` ignores the mark | 4 |
  | C3 | `check-page.js` | the mark never cleared | 2 |
  | C4 | `check-page.js` | the banner's mark in the strip's own place | 4 |
  | C5 | `check-page.js` | any `error` marks it | 2 |
  | C6 | `check-page.js` | `backend.stopped`'s old sentence | 2 |
  | C7 | `check-page.js` | a dropped re-read says nothing | 2 |
  | C8 | `check-page.js` | the Accept's notices without the way on | 4 |
  | M1 | `remodel.js` | a lifecycle `error` leaves the strip | 2 |
  | M2 | `remodel.js` | the `init` ignores the mark | 2 |
  | M3 | `remodel.js` | the mark never cleared | 1 |
  | M4 | `remodel.js` | the banner's mark in the strip's own place | 2 |
  | M5 | `remodel.js` | any `error` marks it | 1 |
  | M6 | `remodel.js` | `backend.stopped`'s old sentence | 1 |
  | S1a | `app.js` | a failed save restart does not mark the backend replaced | 2 |
  | S1b | `app.js` | the mark overwrites one `backend.restarted` made | 0, equivalent |
  | S2 | `check-page.js` | the dropped re-read's notice on a re-read that was shown too | 2 |
  | O2a | `ReviewHost.WithTheWayOn` | the way on dropped | 10 |
  | O2b | `ReviewHost.WithTheWayOn` | no full stop before the way on | 6 |
  | O2c | `ReviewHost` | a waited restart's failure told the Review page bare | 7 |
  | O2d | `SwReviewAddIn` | the other tabs told the failure bare | 3 |
  | O2e | `SwReviewAddIn.StartBackend` | a failed first start told the Review page bare | 1 |
  | O2f | `SwReviewAddIn.StartBackend` | the other tabs told past the call that adds their way on | 1 |
  | O2g | `SwReviewAddIn.StartBackend` | the Review page sent to the Review tab | 1 |

  S1b keeps the mark but drops its guard, so a failed save restart overwrites the token an earlier
  mark kept. The two differ only once an `init` naming no backend has emptied the page's token, and
  every `init` after that can only name a new backend's token, which either one believes: no case
  can tell them apart. The guard is kept, as it says what the mark is - the token of the first
  backend said to be replaced.

- **Tests**: T153, T155 and T157 in [tasks.md](tasks.md), each written first; and the review's,
  T160, T162 and T163. 150A's tasks landed as T143 to T155, the numbers the commits that made
  them name, and were renumbered T153 to T165 when 150A was merged after 149A, whose Phase 14
  holds T143 to T152.

### 153A. Until a restart succeeds, the settings the backend was started with are in force (2026-10-20)

- **Question**: 150A left one mixed state on record (150A, "Not changed", second item). A settings
  restart can fail before it stops the old backend - the configured launcher cannot be resolved,
  say - and it then ends what waited (`End(caught)` in `DeferredRestart.Now` and `Apply`; a save's
  in `ReviewHost.Save`), so nothing waits any more. The next review went to the old backend, which
  keeps the environment it was started with - the key, `OPENAI_BASE_URL`, Gemini Enterprise -
  while its session took the new provider, model and effort from the saved settings, and the strip
  said "Backend ready". A switch from OpenAI to Gemini so ran Gemini sessions on a backend holding
  the OpenAI key, with whatever Gemini key the workstation exports, or none. That broke 143A's and
  145A's rule that nothing runs with settings replaced since the backend started.
- **Decision** (owner decision 153A, "2A", test first): "until a restart succeeds, sessions take the
  settings the running backend was started with - provider, model and effort - and the pane says
  the saved settings are not in force yet and that saving again retries."

**1. The settings in force.**

- `ReviewHost._inForce` holds the settings the backend that is up was started with. Every start of
  the backend goes through the host and one transition, `StartWith`, which records the settings the
  start was made with once it has returned, and never when it throws - a turn the backend's own
  check found, which changed nothing, or a failure, before the old backend stopped or after: every
  restart, a save's at once or one made after waiting (143A, 145A), through `RestartWith`; and,
  since the second review (C1), the add-in's first start, through `ReviewHost.FirstStart`, under
  the same restart lock. The host takes the settings it loads when it is built, which the first
  start is made with unless a save comes first. With no backend up nothing is in force, whatever
  the record holds: every reader asks for the endpoint first, or is refused for want of one.
- Recorded in the host, beside the saved settings it is compared with, rather than in
  `BackendClient`, which starts every process under its gate: `IBackendClient` has ten
  implementations, nine of them test fakes, which would each grow a member, and every start passes
  through the host's restart lock - the first too, since the second review - under which the
  record is written.
- "In force" now means what the backend runs with. 150A's records and the comments said a save's
  settings were "written and in force in the host" before its restart; the comments now say
  "saved" (`ReviewHost.Settings`, `Save`, `SavedNotRestarted`, and `DeferredRestart`'s summary,
  `Outcome.Restarted`, its `restart` parameter and `Now`'s failure), `RestartWithSettingsInForce`
  is `RestartWithSavedSettings`, and the contracts carry a dated note.
- The decision names the model and the effort with the provider, though the backend's environment
  holds neither: a session takes the three that the backend was started with together, so a save
  that changed only the model, whose restart failed, leaves the old model in force until a restart
  succeeds.

**2. Every consumer of the saved settings, and which take the settings in force.**

- Taking them now, each pinned by cases that failed before (T166): every session. `review.start` -
  a review, and an ordinary Retry - `review.recheck`, which a restored waiting review's Send makes
  before its `/send` (feature 015), `context.review`, and a context review's Retry (`review.start`
  with `retry_of`, owner decision 108A) all go through `CreateReviewSession`, which creates the
  session with `_inForce`'s provider, model and effort.
- Taking none of the provider settings, and why:
  - A turn call - a follow-up (`POST /sessions/{chat_id}/messages`) or the answers (`/evidence`,
    `/evidence/{request_id}`) - carries no provider, model or effort: the backend continues the
    chat's own run, built when its session was.
  - A live waiting review's Send (`POST /sessions/{chat_id}/send`, feature 015) has an empty body,
    and the backend sends with the chat's own provider, model and effort, those of its session,
    which is now created with the settings in force. A restored review's Send is a recheck first
    (above).
  - The remodel run's backend calls carry none: `POST /remodel/runs` sends `run_dir` and `bridge`,
    and the backend builds the run's judge with its default provider from its own environment, so
    it runs with the environment in force whatever is saved - the Remodel route's case 138A left
    open, which this does not change. The probe, the open and the plan take no provider at all.
  - The check runs - `POST /checks/rms` and `/checks/standards` - use no provider, no key and no
    network.
  - `models.list`, and a save's own check of its model, ask the backend for the provider the
    Settings form shows, which is the saved one the engineer edits; they run nothing.
  - `context.prepare` and `context.selection` create no session: they check the backend is ready
    (143A) and read saved evidence.
  - The Terminal tab takes the saved settings for a CLI of its own, which is not the backend, and
    is hidden (FR-020).
  - The other tabs - Model check, Standards and Remodel, which 145A tells of restarts - take the run
    root, the endpoint and, the two check tabs, the Standards profile path; and the saved key only to
    mask it (Not changed, below). Nothing they run takes a provider setting.
  - The run root, the Python launcher and the Standards profile path go into the backend's start or
    a session, but no `settings.save` writes them (`Save` clones them from the settings the add-in
    loaded), so they cannot differ from the ones in force; the Send box is saved without a restart
    and is no part of the backend's environment.

**3. The pane says the saved settings are not in force yet.**

- `init` carries `settings_not_in_force`: the host's sentence "The saved settings are not in force
  yet: the review backend did not restart with them, so reviews run with the settings it was
  started with. Save the settings again to retry the restart." while it is true, or null. It is
  true while a backend is up, no restart waits or is being made, and the saved settings differ from
  the ones in force in a provider, model, effort, key, base URL, or Gemini Enterprise project or
  location (`ReviewHost.SettingsNotInForce`, `SameBackendSettings`) - each, since the review (N5),
  as the backend's start reads it for the provider: the base URL for openai alone, trimmed, a blank
  one none, and Gemini Enterprise for gemini alone. The key is compared as it
  resolves, by its value and by where it comes from, which 138A's marker follows - not as stored,
  since DPAPI stores the same key anew each time it is typed.
- The Review page holds the sentence from every `init` (`state.notInForce`, `holdNotInForce`), and
  its banner says it whenever it says nothing else (`showBanner`): a status that clears the banner
  leaves the sentence on it; another word takes the banner, and the sentence comes back once that
  word goes. An `init` carrying null takes it off, and so does `backend.stopped`. Every `init`
  carries it, so a page that loads or loads again is told.
- A restart that waited and failed before it stopped the old backend, leaving the saved settings
  not in force, says so in its `status`: the failure, then the sentence, which ends with 150A's way
  on, where it ended with the way on alone. One that failed once the old backend had stopped keeps
  150A's words. Since the review (S1) that `status` carries `settings_not_in_force` as `init` does,
  and the page holds the sentence from it, since no `init` follows it.
- The save's own answer is unchanged: `BackendNotRestarted`'s sentence already says the settings
  are saved, that the backend did not restart with them, and that saving again retries, and the
  page asks for its `init` after it (150A), which now carries the sentence.
- No label changes: the sentence is the host's, carried by `init` and a `status`, and no error
  class is new, so `review_words_v1.yaml` and the pane fixtures are untouched.
- Designs weighed:
  - *The strip*: "Backend ready" is true - a backend is up, and reviews run on it - a badge has no
    room for the way on, and every status rewrites it.
  - *The banner from `init`, as any other banner*: the first status of the next review takes it off
    while that review runs with the settings in force, when it matters most.
  - *The banner's resting text*, chosen: a holder and one line in `showBanner`, and the sentence is
    on screen whenever nothing more urgent is.
  - *A flag in `init` and the words in the page*: the restart's `status` says the same sentence, so
    it would be written twice, in C# and in the page; the host composes every other sentence about
    a restart (143A, 145A, 150A).
  - *A field on every `status`, or on the review's reply*: a field on several messages for one
    state; not small.
- Null while a restart waits or is being made: 143A's and 145A's promise is the true sentence then,
  nothing new runs on the old backend before the restart is made, and saving again is not the way
  on while a turn runs, since the save is refused.

**4. Edge cases**, each decided and tested (T166, T168):

- A restart that fails once the old backend stopped: no backend, so nothing is in force; `init`
  carries null, the strip says the backend is not running (150A), and a restart that waited keeps
  150A's way on word for word.
- Two saves, the first failing before the old backend stopped and the second restarting it, at once
  or once the turn it met has ended: the second's settings are in force from then on, the next
  review takes them on the restarted backend, and `init` carries null.
- A save of the settings in force - the same settings saved again, or a return to them after a
  failed switch, the key typed again and so stored anew - whose restart fails before the old
  backend stops: the saved settings are the ones in force, so `init` carries null and sessions take
  them. The save is still answered `BackendNotRestarted` (150A): the restart did fail, and saving
  again retries it.
- Each setting a save writes that the backend needs, changed alone - the provider, the model, the
  effort, the key, where the key comes from, the base URL, Gemini Enterprise's project or its
  location: not in force until a restart succeeds.
- The add-in loads with saved settings whose first start fails: no backend and nothing in force,
  `init` carries null, and a review is refused as with no backend; a save that starts the backend
  puts its settings in force, and the next review takes them; a save whose start fails too leaves no
  backend, and `init` still carries null.
- The Send box's save leaves the settings in force as they were: `init` goes on saying the saved
  settings are not in force while they are not, and says nothing while they are.
- A restart that waits or is being made: `init` carries null meanwhile.
- The other tabs: nothing there takes a provider setting (item 2). A restart that failed before it
  stopped the old backend tells them nothing, as 145A decided, and their tokens still work.

- **Evidence** (at `bd07f29`):
  - The session: `CreateReviewSession` built `POST /sessions` from `_settings.Provider`, `.Model` and
    `.Effort` (`ReviewHost.cs:2393` to `:2395`), and a save puts its settings in `_settings`
    (`PersistSettings`, `:1272`) before its restart (`:1209`).
  - The failure that leaves the old backend up: `BackendClient.Restart` builds its start options
    (`BackendLocator.Resolve`, `BackendClient.cs:235`) before `BackendSupervisor.Restart` stops
    anything (`BackendProcess.cs:777`, through `Start` at `:766`, which stops at `:769`); `Now` and
    `Apply` then end what waited (`DeferredRestart.cs:318`, `:414`).
  - The backend's environment: `BackendClient.StartOptions` (`:228`) writes the key under the
    provider's variables, names the provider whose key the pane saved (138A), and writes
    `OPENAI_BASE_URL` and Gemini Enterprise; the server builds each session from the request's
    provider, model and effort and the key in its environment (`chat/server.py:2146`,
    `ChatServer._settings`).
  - The first start: `SwReviewAddIn.cs:544` to `:546` reads `_reviewHost.Settings` after the host is
    built and queues the start (`:1043`).
  - The consumers that take no provider setting: `chat/server.py` `send_review` (`:1482`, the
    chat's own provider, model and effort at `:1490`), `post_message` (`:1499`), `answer_evidence`
    (`:1513`), `run_check` (`:1661`) and `run_standards` (`:1687`); `chat/remodel.py` `start_run`
    (`:694`, `self.settings(body)` with no provider at `:702`); `RemodelBackendClient.StartRun`
    (`RemodelBackendClient.cs:115`); the Review page's restored Send, `recheckThenSend`
    (`app.js:1390`).
- **Review**: an independent adversarial review of the branch at `5e36305` found no must-fix - the
  record stays true through every restart and is read after the restart gate by every session
  path, and the consumers left alone are right, checked in the backend - and the items below,
  settled test first by T171 to T177:
  - After a restart that waited and failed before it stopped the old backend, the Review page never
    held the sentence (S1). Its `status` said it, but no `init` followed, so the next ready status -
    a review's preparation, say - took it off the banner, and the review ran with the settings in
    force with nothing on screen (the reviewer's probe D: the failure, then two ready statuses). That
    `status` now carries `settings_not_in_force` from the reading its way on is made from
    (`ReviewHost.PostRestartFailed`, its payload built where every `status`'s is,
    `PaneActions.StatusPayload`), and the page holds it as it holds `init`'s (`showStatus`). The Not
    changed item that said a later status could take it off understated this, and is gone.
  - The hosts masked the saved key alone (S2). After a switch whose restart failed before the old
    backend stopped, a session's failure quoting the key that backend runs with reached the page
    unmasked, in the `status` and in the refusal (the reviewer's probe B). The backend masks the keys
    in its own environment, so this lost a second layer rather than opening a leak, but 153A makes
    the state last. Every host now masks the saved key and the key the backend was started with:
    `ReviewHost.KeysToMask`, which the review host masks and the add-in hands the Model check,
    Standards and Remodel hosts (`SwReviewAddIn.KeysToMask`). The Not changed item that left this
    to the owner is gone.
  - The branch of that `status` for the settings in force was pinned by nothing (N4): the reviewer's
    mutation, saying the sentence whenever a backend was up, left every case green. A waited restart
    of the settings in force that fails before the old backend stops keeps 150A's way on, and a case
    pins it.
  - Each setting was compared for every provider (N5), while the backend's start reads the base URL
    for openai alone and Gemini Enterprise for gemini alone, so a settings file edited by hand could
    have the pane say the saved settings were not in force when nothing the backend reads differed.
    The start and the comparison read one rule now (`BackendClient.BaseUrlFor`,
    `ReadsGeminiEnterprise`), which `BackendProcessTests` pins on the start's side.
  - Words that still called the saved settings "in force" (N6): `ReviewHost`'s promise, eight
    comments of `DeferredRestartTests`, `chat-api.md`'s settings bullet, and the 143A and 150A words
    of the `settings.save` row, whose 153A note now says they were changed.
  - A second ordering of the first-start race (O2): recorded under Not changed, with
    `BackendSupervisor`'s summary saying a restart added there must go through the review host's
    restart, or the record drifts; settled by the second review (C1, below), which made the first
    start the host's.
  - Existing cases changed deliberately: none. The comments of eight cases change their words
    alone, and the test world's backend can now fail `POST /sessions` (`SessionFailure`).
- **Second review**: a Codex adversarial review of the branch at `d41ae2c` said it needed
  attention, with two findings, settled test first by T178 to T182:
  - The add-in's first start was made outside the host (C1, high). `SwReviewAddIn.StartBackend`
    called `BackendClient.Start` with the settings read as the add-in loaded, while the host took
    those as in force when it was built. Codex's ordering needs no failure: the first start's
    thread-pool item comes late; a save on the page pump restarts the backend with its settings and
    records them; the first start then replaces that backend with one started with the settings
    loaded, recording nothing, so sessions took the saved provider, model and effort on a backend
    started with the loaded settings' environment, and the keys masked left its key out. O2, the
    ordering recorded under Not changed - a save whose restart failed, then the first start - came
    from the same cause. The first start is the host's now (`ReviewHost.FirstStart`): made under the
    lock every restart holds for its whole length (`DeferredRestart.First`), with the settings saved
    when it is made and the key resolved from them then, and recorded by the transition every
    restart records by (`StartWith`, which `RestartWith` goes through). One that comes after a
    restart has started the backend finds it up and starts nothing: a second start with the settings
    loaded would replace it under the record, and one with the saved settings would end any review
    already running on it. One after a save whose restart failed, with no backend, starts the backend
    with the settings saved then. Once the host is disposed it starts nothing and is thrown, so the
    add-in logs that the backend did not start, as a start the unloading client refused was. The
    add-in queues it with nothing read beforehand and says what it said: `backend_starting` before,
    `ready` after, and on a failure the way on to every page (150A). Both Not changed items on the
    first start are gone, and `BackendSupervisor`'s summary says every start is the host's.
  - An `init` read while a restart waited could reach the page after that restart's failure word
    and take its sentence off (C2, medium): `init` is read on the page pump and the failure's word
    posted from the restart's thread, and the page took whichever came last. Of the two ways Codex
    named - one lock for each reading and its post, or a number the page checks - the number holds
    in whatever order the posts arrive, the status path included: each reading of whether the saved
    settings are in force is taken together with its number, one past the last, under one lock
    (`ReviewHost.ReadSettingsNotInForce`); `init` and the failure's word carry it
    (`settings_not_in_force_revision`); and the Review page takes a reading only when its number is
    above the last it took (`holdNotInForce`), and one with no number - its own, at
    `backend.stopped` - as before. A case holds an `init` inside its reading while a save puts the
    settings in force, and the reading taken after it is numbered above it; with the number taken
    apart from the reading, the older reading took the higher one (mutation C2d).
  - Existing cases changed deliberately: `AFailedFirstStartTellsEveryPageTheWayOn` reads
    `StartBackend()`, which takes nothing now, where it read `StartBackend(UserSettings settings,
    ResolvedApiKey key)` - an anchor; nothing it asserts moves. The Review page driver's `init`
    carries `settings_not_in_force_revision`, null unless a case sets it.
- **Third review**: a Codex adversarial review of the fixes at `4c604e2` found one more race (R1,
  medium), settled test first by T183 to T185:
  - Every start publishes the backend's endpoint before it records the settings it was made with:
    `BackendSupervisor.Start` sets `Current` inside the backend client's start, and `StartWith`
    records the settings once that has returned. After a save that switched the provider and failed
    with no backend up, the first start - made, since C1, with the saved settings - left a moment in
    which the backend was up with the saved settings while the record still held the settings
    loaded. An `init` read then said the saved settings were not in force, numbered above the
    failure's word, and the page held it: the add-in's `ready` asks for no `init` on a page that has
    the backend, and one it asks for while another is pending is dropped (`showStatus`,
    `requestInit`). `DeferredRestart.First` marks nothing, so `init` could not tell that moment from
    a failed restart's.
  - The same moment had two more readers. A session made then - a review, a recheck, a context
    review, their Retries - took its provider, model and effort from the record, the settings
    loaded, on the backend started with the saved ones' environment: the pairing 153A ended. And the
    keys masked - the saved key and the recorded one - left out the key that backend was started
    with once a save made meanwhile had replaced the saved settings.
  - Fixed where the moment is made. `StartWith`, the one transition every start goes through, marks
    the start under way from just before it starts the backend until it has recorded the settings,
    or thrown (`ReviewHost._starting`, the settings it was made with), and records them before it
    takes the mark off. `SettingsNotInForce` says nothing while a start is under way, as while a
    restart waits or is being made, and reads the endpoint first, so a start whose endpoint it read
    is still under way, or has recorded its settings. `CreateReviewSession` makes no session while
    one is: just before it reads the settings in force it refuses the session as a review asked for
    before the backend is up is refused - `BackendUnavailable`, retryable, in the same words
    (`BackendNotRunningYet`, which `BackendReady` now shares). A review extracts first, so its
    evidence stays in its run folder, as for a backend that stops during an extraction; in practice
    the moment is over long before an extraction is. `KeysToMask` adds the key of a start under way.
  - Marking `_making` in `DeferredRestart.First`, as a save's restart is marked, was weighed and
    left. `Ahead` is what the Remodel tab reads to tell its page that a press waits "for the review
    backend to restart with the saved settings" (145A, whose third review took out words that said
    the backend was restarting when it might not be), and a first start is no restart. Nor does
    `Ahead` reach the other two readers: a review's gate reads only whether a restart waits, and the
    keys masked read no restart at all. A mark made in `StartWith` covers every start by
    construction, as the record itself does.
  - The same window in the restarts, checked as the review asked. `RestartWith` goes through
    `StartWith`, so a restart, too, publishes the new backend's endpoint before it records the
    settings. `init` was never wrong there: a save's restart made at once holds `_making` from before
    it starts the backend until after the record (`DeferredRestart.Now`, its `finally`), and one that
    waited stays pending until `End`, after the record, so `Ahead` covered the moment. Sessions never
    met it: a save's restart is made on the page pump that makes sessions, and a review waits under
    the restart lock for one that waited. The keys masked did, when a save was made during a restart
    that waited, and the mark covers that now. Two guards pin the `init` read during either restart;
    they passed before the change.
  - The page is unchanged: the word it held is no longer said.
  - Existing cases changed deliberately: none. `MakeASession`'s first three asks moved into
    `AskForASession`, which the new cases use to expect a refusal, and the test world's backend can
    hold a start once it has published the backend's endpoint (`Published`).
- **Not changed**:
  - A backend that dies while the saved settings are not in force: no host posts `backend.stopped`
    (150A), so the Review page goes on saying reviews run with the settings it was started with until
    its next `init`, while a review is refused for want of a backend.
  - A page that reloads while a restart waits is told nothing of the promise: `init` carries no word
    of a restart that waits (143A), and `settings_not_in_force` is null then, by decision.
  - A save of the settings in force whose restart failed is answered `BackendNotRestarted`, as any
    save whose restart failed (edge cases, above).
  - `models.list`, and a save's check of its model, ask the backend that is up for the provider the
    Settings form shows; a backend started for another provider may not list it, and the model is
    then saved unchecked, as on any provider switch.
  - The mark of a start under way (`_starting`) and the record of the settings in force
    (`_inForce`) are two references, written in an order no case can pin (mutation W7): the mark
    comes off only once the record is written, as a comment in `StartWith` says. One reference
    holding both, written once, would make that order a single write, at the cost of changing every
    reader of the record; left as it is (third review).
- **Existing cases changed deliberately**: three cases pinned word for word the `status` a restart
  that waited posts when it failed before it stopped the old backend - the "old backend still up"
  half of `ARestartThatWaitedAndFailedSaysSavingAgainRetriesIt`, the "after waiting" half of
  `ARestartThatFailsBeforeTheOldBackendStoppedTellsTheOtherTabsNothing`, and both halves of
  `ACallThatWaitedForARestartThatFailedBeforeStoppingAnythingIsToldThatFailure` - and now expect the
  failure followed by the 153A sentence, which ends with the same way on, since the saved settings
  in each differ from the ones in force; nothing else they assert moves. The test world's `Save`
  helper takes a base URL and Gemini Enterprise, and its environment can be set
  (`WorkstationEnvironment`); the Review page driver's `init` carries `settings_not_in_force`, null
  unless a case sets it, and null with no backend, as the host's.
- **Mutations**: each fix taken out once with one exact replacement, the tree rebuilt, the classes
  run - for the host's, `DeferredRestartTests`, `ReviewPageBackendRestartTests`,
  `OtherTabsBackendRestartTests`, `ReviewHostTests` and `PageMessageTests`, 399 cases; for the
  page's, `ReviewPageBackendRestartTests`, 22 - and the file restored byte for byte (checked by
  sha256): 22 mutations, 107 red results in all - 90 for the host's 17, 17 for the page's 5 - and
  every mutation turned at least one case red. Existing cases went red as well: four of 143A's
  that read a session made after a restart that waited (H2); three that pin the words of a waited
  restart's failure once the old backend had stopped (H4); four runs of two `ReviewHostTests`
  cases that read a session's settings (H17); and 143A's case that a restart takes only its own
  sentence off the banner (P3).

  | id | where | taken out | red |
  |---|---|---|---|
  | H1 | `ReviewHost.CreateReviewSession` | a session takes the saved settings | 8 |
  | H2 | `ReviewHost.RestartWith` | a restart that succeeds records nothing | 8 |
  | H3 | `ReviewHost.RestartWith` | recorded before the restart, so one that fails is recorded too | 23 |
  | H4 | `ReviewHost.SettingsNotInForce` | said with no backend up | 5 |
  | H5 | `ReviewHost.SettingsNotInForce` | said while a restart waits or is being made | 1 |
  | H6 | `ReviewHost.SameBackendSettings` | the provider not compared | 1 |
  | H7 | `ReviewHost.SameBackendSettings` | the model not compared | 1 |
  | H8 | `ReviewHost.SameBackendSettings` | the effort not compared | 5 |
  | H9 | `ReviewHost.SameBackendSettings` | the key's value not compared | 1 |
  | H10 | `ReviewHost.SameBackendSettings` | where the key comes from not compared | 1 |
  | H11 | `ReviewHost.SameBackendSettings` | the key compared as stored, not as it resolves | 1 |
  | H12 | `ReviewHost.SameBackendSettings` | the base URL not compared | 1 |
  | H13 | `ReviewHost.SameBackendSettings` | Gemini Enterprise's project not compared | 1 |
  | H14 | `ReviewHost.SameBackendSettings` | Gemini Enterprise's location not compared | 1 |
  | H15 | `ReviewHost` | a restart that waited and failed keeps the bare way on | 5 |
  | H16 | `ReviewHost.SendInit` | `init` says nothing | 11 |
  | H17 | `ReviewHost` | the settings loaded not recorded for the first start | 16 |
  | P1 | `app.js` | `init`'s sentence ignored | 6 |
  | P2 | `app.js`, `showBanner` | the banner does not fall back to the sentence | 6 |
  | P3 | `app.js`, `holdNotInForce` | any banner taken for the sentence's | 2 |
  | P4 | `app.js`, `holdNotInForce` | the sentence held until now left on the banner | 2 |
  | P5 | `app.js` | `backend.stopped` leaves the sentence | 1 |

  For the review: 14 mutations, the same way, the host's classes with `BackendProcessTests` as well,
  456 cases, and the page's, 24 - 22 red results in all, and every mutation turned at least one case
  red; `BackendProcessTests`' case that the base URL is written only for the provider that reads it
  went red with R12 besides.

  | id | where | taken out | red |
  |---|---|---|---|
  | R1 | `ReviewHost.PostRestartFailed` | the failure's `status` carries no `settings_not_in_force` | 3 |
  | R2 | `ReviewHost.PostRestartFailed` | its way on says the sentence whenever a backend is up (the reviewer's M1) | 1 |
  | R3 | `app.js`, `showStatus` | the field ignored | 2 |
  | R4 | `app.js`, `showStatus` | every `status` read for the field, carried or not | 2 |
  | R5 | `ReviewHost.KeysToMask` | without the key the backend was started with | 2 |
  | R6 | `ReviewHost` | the host masks the saved key alone | 1 |
  | R7 | `SwReviewAddIn` | the Model check tab masks the saved key alone | 1 |
  | R8 | `SwReviewAddIn` | the Standards tab masks the saved key alone | 1 |
  | R9 | `SwReviewAddIn` | the Remodel tab masks the saved key alone | 1 |
  | R10 | `ReviewHost.SameBackendSettings` | the base URL compared as stored, for every provider | 3 |
  | R11 | `ReviewHost.SameBackendSettings` | Gemini Enterprise compared for every provider | 1 |
  | R12 | `BackendClient.BaseUrlFor` | the base URL read for every provider | 2 |
  | R13 | `BackendClient.BaseUrlFor` | the base URL not trimmed | 1 |
  | R14 | `BackendClient.ReadsGeminiEnterprise` | Gemini Enterprise read for every provider | 1 |

  For the second review: 14 mutations, the same way - the host's classes, 467 cases (468 once
  C2d's case was written), and the page's, 25 - 41 red results in all, every mutation red. C2d, the
  lock that takes a reading and its number together, survived until a case held an `init` inside its
  reading; C2a and C2c were run again once that case was written.

  | id | where | taken out | red |
  |---|---|---|---|
  | C1a | `DeferredRestart.First` | the first start not under the restart lock | 2 |
  | C1b | `ReviewHost.FirstStart` | the first start made though a backend is up | 2 |
  | C1c | `ReviewHost.FirstStart` | the first start records nothing | 2 |
  | C1d | `ReviewHost.FirstStart` | made with the settings recorded, not the saved ones | 2 |
  | C1e | `ReviewHost.StartWith` | no start records the settings it was made with | 15 |
  | C1f | `DeferredRestart.First` | a first start made once disposed | 1 |
  | C1g | `SwReviewAddIn.StartBackend` | the add-in starts the backend itself, with the settings read at load | 1 |
  | C2a | `ReviewHost.SendInit` | `init` carries no number | 2 |
  | C2b | `ReviewHost.PostRestartFailed` | the failure's word carries no number | 1 |
  | C2c | `ReviewHost.ReadSettingsNotInForce` | every reading numbered alike | 2 |
  | C2d | `ReviewHost.ReadSettingsNotInForce` | a reading and its number taken apart | 1 |
  | C2e | `app.js`, `holdNotInForce` | every reading taken, whatever its number | 1 |
  | C2f | `app.js`, `holdNotInForce` | the number of a reading taken never kept | 1 |
  | C2g | `app.js`, `holdNotInForce` | a word with no number not taken | 8 |

  For the third review: 7 mutations, the same way - the host's classes, 475 cases - 43 red results in
  all, six of the seven turning at least one case red. W5, the mark left on a start that threw, turned
  28 existing cases red - the sessions, `init`'s sentence, the failure's word and the keys masked after
  a restart that threw - and none of the new ones, whose starts all succeed. W7 survived: it takes the
  mark off before the settings are recorded, a moment no case can hold, since nothing is called
  between the two (Not changed, below).

  | id | where | taken out | red |
  |---|---|---|---|
  | W1 | `ReviewHost.StartWith` | no start marked under way | 5 |
  | W2 | `ReviewHost.SettingsNotInForce` | read while a start is under way | 1 |
  | W3 | `ReviewHost.CreateReviewSession` | a session made while a start is under way | 3 |
  | W4 | `ReviewHost.KeysToMask` | the key of a start under way not masked | 1 |
  | W5 | `ReviewHost.StartWith` | the mark left on a start that threw | 28 |
  | W6 | `ReviewHost.StartWith` | the mark set once the start has returned | 5 |
  | W7 | `ReviewHost.StartWith` | the mark taken off before the settings are recorded | 0 |

- **Tests**: T166 and T168 in [tasks.md](tasks.md), each written first; the review's, T171, T173
  and T175; the second review's, T178 and T180; and the third's, T183. 153A's tasks are T166 to
  T185: it lands first among this round's 002 decisions, so its numbers stand.

### 156A. 002's other words for the hidden Terminal tab, and an invalid escape in a test (2026-10-20)

- **Question**: Other words in 002 still describe the hidden Terminal tab as shown, and a test's fictional Windows path has an invalid escape.
- **Decision**: Add dated notes wherever the spec describes that tab, built and hidden since 2026-09-19, and fix invalid Python escapes without changing values or product behaviour.
- **Change**: Annotated `spec.md` and settled 011's research R13.5 item 2; audited `reviewer/tests/` and `reviewer/src/` and made the affected test literal raw with the same value.
