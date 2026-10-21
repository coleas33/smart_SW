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
    *Changed 2026-10-21 by owner decision 157A:* a check is a turn to the restart now - while a backend is
    up, a Model check or a Standards check holds a settings restart back from its gate until the page's
    evaluation of it has been answered, and one started while a restart waits makes the restart first, as
    a remodel run does;
    its later calls, an Accept or a re-read, are still not held (see
    [157A](#157a-a-model-check-or-a-standards-check-holds-a-settings-restart-back-until-its-evaluation-is-answered-2026-10-21)).
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
     *Settled by decision 152A (2026-10-20, "1A"):* every review session's start asks which
     document and configuration the bridge it would hand over serves - the tool service's record
     of its attach, which its `ping` answers - and refuses one that is not the review's,
     `BridgeOnAnotherDocument`, retryable, in plain words, before anything is made where it can
     be; and the tool service, which skipped a switch made while a turn or a remodel run held it,
     follows the active document once that hold ends (152A, below).
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

### 152A. A review never runs on a bridge left on another document (2026-10-20)

*Renumbered 2026-10-21:* this decision's tasks were numbered T166 to T183 provisionally, as
153A's and 154A's were, and are T207 to T224 since 153A's, T166 to T188, and 154A's, T189 to
T206, landed on `main` first; the commits that made them carry their first numbers (`cafd8d0` to
`88e8f7e`, T166 to T183).

- **Question**: 149A's owner question 5. A review's session is given whatever bridge the tool
  service is attached to when the session is made (`ReviewHost.CreateReviewSession`,
  `_options.Bridge`, which `SwReviewAddIn` publishes from the gate), and nothing compared it with
  the review's document - not the add-in, and not the backend, whose bridge answers `ping` with its
  document and is not asked for it. The tool service follows a document switch on a thread of its
  own, so for a moment after a switch it is still attached to the document left; and it skips a
  switch made while a review turn or a remodel run holds it (`ToolServiceGate.FollowCore` asked
  `busy`, logged "not re-attaching to ... a turn is running against ..." and returned), and nothing
  caught up until the next switch. So: switch documents during a turn, then press Review once it
  ends, and the new review's live interference check - the first of its pre-run checks - ran over
  the other document and wrote that document's rows into this review's package, with no restart
  at all. 149A closed only the restart's window.
- **Decision** (owner decision 152A, "1A", 2026-10-20): "A review never runs on a bridge left on
  another document (002 `research.md`, 149A's owner question), test first, with an adversarial
  review: the tool service, which skips a document switch made while a turn or a remodel run holds
  it, follows the active document once that hold ends; and every review session's start asks the
  bridge which document it serves and refuses in plain words, retryable, when it is not the
  review's."

**1. The tool service follows the active document once the hold ends.**

- **How**: a follow skipped while work holds the bridge is owed (`ToolServiceGate._owed`), and the
  gate looks again a poll later (`FollowPoll`, a second, as the settings restart's watcher polls,
  143A) through `later` - by default a delay on the thread pool, injected in the cases - one look
  waiting at a time (`_asking`). A look claims `_starting` as a switch's follow does, asks the busy
  question again, and while work still holds the bridge is owed again; once nothing holds it, it
  reads the active document at that moment and follows it (`FollowNow`): another part or assembly
  is attached to; the document already attached to, a drawing, or none, re-attaches nothing; the
  exact held copy of a waiting plan keeps its attachment (004 T180). Either way nothing more is
  owed, and no look is asked for again.
- **What the busy question reads** (the 152A review's R1): the add-in's answer is the remodel run
  first, which costs nothing, and then whether a turn may be running (`ReviewHost.TurnMayBeRunning`):
  one seen running, or a chat the backend gives no usable answer about - not knowing whether a turn
  runs is not knowing that none does, as the settings restart reads it (143A) - and none with no
  backend process at all, which runs no turn. It was `AnyTurnRunning`, which reads no answer as
  none, so a follow made as one request timed out tore the bridge down under a running turn; a
  look asked every second for the length of a turn would meet that moment far more often than a
  switch did. A save still asks `AnyTurnRunning`, so a backend that does not answer still lets the
  engineer save. While the backend is up and does not answer, a follow now waits for its answer;
  with no backend process the tool service follows the engineer as before.
- **The trigger, weighed**:
  - *an explicit call from the hosts when a hold ends*: the Remodel host knows when a plan or a
    run ends (`FreeTheHost`, `Execute`'s `finally`), but the review host does not know when a turn
    ends. A turn begins at `POST /sessions` or at a page call the proxy passes on - a follow-up, an
    answer, a Send - and ends on the backend; the add-in learns that it has ended only by asking
    (`IBackendClient.IsTurnRunning`, `GET /sessions/{chat_id}`), which is why the settings
    restart's watcher polls (143A, `DeferredRestart`). The event stream the host reads for the page
    is not parsed, and is read only for the chat on screen. An explicit call would cover remodel
    holds alone, and a poll would still be needed for turns: two mechanisms for one rule.
  - *a deferred follow, asked again until nothing holds the bridge* - **chosen**: one mechanism
    for both holds, inside the gate that already asks the busy question. It is as testable as an
    explicit call: the cases hand the gate a `later` that keeps each look until the case runs it,
    so every case decides by order, not by time; one case pins the gate's own `later`, a poll late
    and on the pool. Its cost is the restart watcher's: the busy question - the remodel run, then
    one `GET` per review the host tracks until one does not rule a turn out - once a second, off
    the application thread, and only while a follow is owed. A remodel's end is followed within a
    poll.
- **No race with a switch** (the decision's own words): a follow reads the active document only
  once it has its busy answer, and a start reads it again as it attaches, so a switch made while
  either asks is followed by it. A switch that lands while a start or a follow is in flight - after
  the start read the active document and before it is listening - was dropped until the next switch
  (`docs/review-backlog.md`'s finding against `FollowDocument`'s early return while a start is in
  flight); it is owed now, and looked at as soon as that work is over (`Settle`, and `StartCore`
  once the new service is published). What is owed is taken by a follow as it asks the busy
  question and again as it reads the active document, and by a start as it reads it, so a switch
  after any of these is owed afresh: one that lands just after a look's reading is looked at once
  the look is over, and one made while the busy question is out is followed by that follow - or,
  when the question throws, looked at once it has (the 152A review's R4 and N2).
- **No second service**: a look never runs beside a start or a follow - it returns when
  `_starting` is held, and the work in flight looks again itself when it ends - and every entry
  claims `_starting` under the lock before anything that can start a service is scheduled, as
  `FollowDocument` and `EnsureStarted` always have.
- **The preserved attachment**, exactly as before: `_preserveAttachment` is asked with the document
  active when the follow is made, as `FollowCore` asked it since T180, and only when nothing holds
  the bridge. A plan holds the bridge while it opens and activates its copy, so that switch is
  skipped and owed; the look once the plan ends finds the exact held copy active, keeps the plan's
  attachment, writes the T180 line, and asks no more. A switch to any other document is followed
  and loses the plan, as an ordinary switch does (22A).
- **What is said**: the tool-service log's line for a skipped switch is written by the switch's own
  follow when it finds the bridge held, as before; a look writes nothing, since a line a second for
  the length of a turn would bury the one the engineer is sent to read, and a switch that lands while
  a look or a follow is in flight is owed without a line and followed with the rest (the review's
  N7). A busy question that throws is reported and counts as busy, as before, and owes nothing of
  its own - not a look at once, nor one a poll later - since nothing says the next answer would come:
  the next switch, or a review's request (below), asks again. A switch made while it was out is
  still owed.
- **The configuration**: a switch's follow - at the switch, owed while a start or a follow was in
  flight, or made once a hold ends - is made as at the switch, by the path (`SameDocument`,
  canonically and ignoring case, as the gate has always compared paths), so a configuration switch
  re-attaches nothing wherever it lands, as 004 decision 22A records. It first did when it landed
  while work was in flight, which the review found (N3). A review's request is made by the review's
  own rule, the path ignoring case and the configuration exactly (`Serves` with `Owed.Configuration`,
  through `PageDocument.IsSameDocument`), so that what the review refuses the gate follows: a
  document the attach spelled otherwise - opened through `..`, say - was refused by the review and
  called the same by the gate, and the refusal never cleared (the review's R3). A start attaches to
  the document as it is. Why the configuration matters to a review: the scope is walked in the
  configuration the attach found active (`SwScope.Open`, `ComponentTreeDumper.Traverse` over
  `session.ConfigurationName()`), and its component table is what the live interference check maps
  its rows through; ids are allocated by that traversal, so another configuration's rows can name
  other components.

**2. Every review session's start asks the bridge which document it serves.**

- **What answers**: `ToolServiceGate.DocumentServedBy(bridge)` - the document and configuration
  of the service listening on that bridge's pipe, or none when no service listening now has it
  (before the first start, another attachment's, one a re-attach is taking down, any after the
  add-in unloads). It is the service's record of its attach, `IToolService.DocumentPath` and
  `Configuration`, which `ToolServiceHost` takes from the one attach that also sets
  `BridgeServices.DocumentPath` and `Configuration` (`ToolServiceHost.Attach`), and those are what
  the bridge's `ping` answers (`SwBridgeDispatcher.Ping`). A case asks the bridge's `ping` over its
  own pipe with the review secret and pins that the two answers agree.
- **Why the record, not a `ping` over the pipe**: the add-in has no bridge client of its own - the
  backend's is the bridge's only client - and a request over the pipe is served one at a time on
  the application thread (`InProcPipeServer.Answer` queues it), so a review start would wait behind
  every command ahead of it - minutes behind a turn's interference check or a remodel command - or,
  with a timeout, refuse a review because the bridge was busy, which is the false refusal the
  decision's adversarial review was asked to look for. A pipe name is minted for every start, so it
  names one attachment for its whole life: a session handed a bridge that served the review's
  document when it was asked reaches that document or nothing - in whatever configuration is active
  when it calls, since a configuration switch after the session's start re-attaches nothing (the
  review's R2; What is left).
- **What is compared**: `PageDocument.IsSameDocument`, the pane's one rule (the path ignoring case,
  the configuration exactly), since `ping` gives both. Both paths are `GetPathName` of one open
  document (the attach's and `SwReviewAddIn.CurrentDocument`), and both configurations
  `IConfiguration.Name` of its active configuration. The configuration matters for the reason above.
- **Where**: a new review - and a Retry of one, which is a new review - is asked before its run
  folder is made (`StartReview`, after 149A's second reading), so a bridge left on another document
  costs no extraction and leaves no folder. Every start is asked again at its session
  (`CreateReviewSession`, before `POST /sessions`), with the bridge read there once, and the session
  is given that very bridge: one published between the question and the session is closing, and is
  not handed over unasked. The extraction takes minutes, in which the tool service can follow
  another document.
- **The refusal**: `error {error_class: "BridgeOnAnotherDocument", retryable: true}`, in words that
  name no path; nothing is made by the start and no status of an extraction or a check is posted -
  a Recheck says it checks only once its bridge is asked, and a settings restart the start made or
  waited for first has said so, as 143A has it - and the tool service is asked to follow the
  active document (`ReviewHostOptions.FollowActiveDocument`, the gate's `FollowActiveDocument`),
  which every start has checked is the review's. Two messages, each true where it is raised:
  - before anything is made: "the SOLIDWORKS bridge this review would be given is not attached to
    the review's document and configuration, so nothing was extracted and no run folder was made.
    It follows the active document once no review turn or remodel holds it: wait a moment, then
    press Review again.";
  - at the session: "... so no review session was started and no check ran. It follows the active
    document once no review turn or remodel holds it: wait a moment, then try again.". What is made
    by then: nothing, but for a new review whose bridge the tool service moved to another document
    while it extracted, whose run folder keeps the package just extracted - of the review's own
    document, by the second reading and the dump's attach - as one whose extraction fails keeps its
    folder; the next press makes a new one. Deleting it would be a delete in the run root the add-in
    makes nowhere else.
- **Asking the tool service to follow** - an extension of the decision's words, by the
  implementer's choice, not the owner's decision, and put to the owner: without it a refusal after a
  configuration switch would never clear, since a configuration switch re-attaches nothing at the
  switch (22A), and neither would one after a busy question that threw, or one for a document the
  attach spelled otherwise. Asked, the gate follows the active document as the review compares it -
  at once, or once the hold ends - keeping the planned copy's attachment as any follow does. So
  "retryable" is true: pressed again once the bridge is on the review's document, every start goes
  ahead with it (pinned for each). One refusal it does not clear: a review of a waiting plan's copy,
  whose attachment the plan keeps (What is left). *Settled by decision 158A (2026-10-21, "2A"):* the
  owner confirms the extension, the implementer's, put to the owner here: a start refused
  `BridgeOnAnotherDocument` asks the tool service to follow, having first let go of any hold it took.
  Pinned, unchanged, by `DeferredRestartTests.AStartEndedAtItsSessionLetsGoOfItsHold` (its bridge
  moved: the follow asked once, with no hold held) and by section 15's refusal cases, each of which
  asks it once (158A, below).
- **The class and its label**: the Review page shows a class's label first and the message in a
  fold, and every class the host sends has one (`ErrorLabelsCoverTheHostTests`). Weighed:
  - `NotAttached` ("The add-in is not attached to SOLIDWORKS yet. Wait a moment, then try
    again."): the way on fits, but the add-in is attached, and the engineer would look for an
    add-in that failed to load;
  - `DocumentChanged`: the active document did not change - the bridge is elsewhere - and its label
    says nothing was extracted, untrue at the session after an extraction;
  - `ReviewNotActive`: the review's document is the active one; `BridgeUnavailable` ("SOLIDWORKS
    could not be reached ..."): it can be;
  - a class of its own, `BridgeOnAnotherDocument` - **chosen** - with its label, true of every start
    that carries it: "The SOLIDWORKS bridge is not attached to this review's document yet, so the
    review did not start. It follows the active document once no review turn or remodel holds it.
    Wait a moment, then try again." "Try again", since the button is Review, Retry, Recheck or the
    context review's. The pane fixtures that carry the words file's labels are regenerated with
    their generators (`generate_pane_fixture.py --write`: `review-big-assembly.json`;
    `generate_waiting_fixtures.py --write`: `review-waiting.json`,
    `review-waiting-big-assembly.json` and `review-waiting-restored.json`, each differing in the one
    added line, `review-not-sent-session.json` back byte for byte), and
    `review-send-failure-events.json`'s pin of `review-waiting.json` moves to its sha256 as written
    on Windows (CRLF). `review-waiting-apply-failure.json`, a capture with no generator, keeps the
    labels it was captured with, as 146A to 150A left it.
- **The starts**, each pinned: a new review, one through a preparation (the add-in's path), a Retry
  of one (`review.start` with `retry_of`), a context review (`context.review`), its Retry, and a
  Recheck (`review.recheck`). A Recheck's own checks ask the seat nothing (149A): it carries the
  first run's live detection over. But its session holds the bridge for the model's turns after
  Send - a waiting run closes the live transport and keeps its client for a later request
  (`ReviewRun.release_bridge`; `send_review` then runs the model on the same run) - and those turns
  can call the live tools over it, so its start is asked as every other is. Excluded, each making no
  review session: `context.prepare` (a dump into a folder, attached to the active document, which
  `context.review` then checks); the Extract, Model check and Standards tabs, which hand the backend
  no bridge; the Remodel tab, whose remodel bridge's open is bound to the path its own probe was
  minted for (`RemodelScopeProbe.Require`); and the Terminal tab, hidden, whose CLI holds the
  general-chat bridge and makes no review session.
- **No bridge at all** - no tool service listening yet, or one being replaced - is no refusal: the
  session is given none and the backend runs no live check and says so in the review's coverage, as
  before 152A. Nothing of another document can reach such a session.
- **A host that cannot be told**: `ReviewHostOptions.BridgeDocument` answers none by default, so a
  host given a bridge and nothing to ask about it refuses every start rather than hand over a bridge
  it cannot vouch for; an answer that throws is none too.
- **Contracts**: 002 [`contracts/pane-host-messages.md`](contracts/pane-host-messages.md) (a dated
  152A paragraph after the Review page's table, for `review.start`, `context.review` and
  `review.recheck`) and [`contracts/chat-api.md`](contracts/chat-api.md) (the `bridge` of
  `POST /sessions`, and the class); 004
  [`contracts/pane-remodel-messages.md`](../004-resilient-remodeler/contracts/pane-remodel-messages.md)
  and [`contracts/bridge-remodel.md`](../004-resilient-remodeler/contracts/bridge-remodel.md) (how the
  tool service follows) and 004 [`research.md`](../004-resilient-remodeler/research.md) (22A's
  paragraph), each with a dated 152A note.
- **What is left** (recorded, not changed):
  - A turn that starts between a follow's busy answer and its teardown meets a pipe that is closing:
    its live calls fail and are recorded as failed coverage. Older than 152A - every follow since the
    tool service follows switches has had it - and it reaches no other document. The follow now runs
    at a hold's end too, so it can meet a follow-up typed at once. *Settled 2026-10-20 by the Codex
    review's X2 (below): the turn's call holds the bridge, and the follow waits for it.*
  - A remodel Start pressed in the moment between a look's busy answer and its reading of the active
    document: the look finds the plan's copy no longer planned, so T180 does not keep its attachment,
    and the bridge is taken down under the run that is starting (the review's N1). 145A recorded the
    moment; since 152A a look comes due within a second of a plan's end, when Start is often pressed.
    The run's next bridge call meets a closing pipe, or a dispatcher with no session, answered
    `target_mismatch` before any write (004 `contracts/bridge-remodel.md`), so the copy is not
    changed: the run fails, and is pressed again. *Settled 2026-10-20 by the Codex review's X2
    (below), which found the same race with a plan still being planned: a plan and a run hold the
    bridge, and the look waits for them.*
  - A session made while the tool service is between two attachments is given no bridge, and its
    live checks are recorded as not run: a review pressed in the seconds a follow takes, now also at
    a hold's end. Older than 152A; no evidence of another document.
  - A configuration switch is followed only when a review asks, or once a document switch
    re-attaches, so the general-chat tools and Show in SOLIDWORKS (`entity.show`, through the tool
    service's scope) keep the configuration attached to until then. And a session started before
    such a switch keeps a live pipe bound to the configuration it was asked about: its later live
    calls - the model's after Send, a follow-up's or an answer's, and its pre-run checks in the
    seconds after `POST /sessions` - run in the configuration now active through the other's
    component table (the review's R2). A Send, a follow-up and an answer reach the backend from the
    page through the proxy, not through the host, so no session's start is asked again for them.
    Older than 152A (004, decision 22A); owner question 1. *Narrowed 2026-10-20 by the Codex review's
    X1 (below): a new review whose configuration was switched during its extraction is refused at its
    session, and the bridge refuses every live command while its document's active configuration is
    not the one it attached in, so none of those calls runs through the other's table. What is left:
    those commands, the general-chat tools' included, are refused until the configuration is switched
    back or a review re-attaches the tool service, and Show keeps the configuration attached to.*
  - A review of a waiting plan's copy, while the plan keeps its original's attachment (T180), is
    refused until the plan is started or its copy discarded, or another document is made active: a
    review's request keeps that attachment as any follow does, and the label's "wait a moment" does
    not say so (the review's N6).
  - With Start switched off (004 T172) - the shipped build - a plan closes its session before it
    answers (004 T176), so no held copy keeps the attachment, and the look once the plan ends follows
    whatever the plan's close left active: the original part, normally, which is the document
    attached to and changes nothing; or the copy, when the close left it open and active, which the
    tool service then follows, telling the plan lost (24A) in words that say SOLIDWORKS switched
    documents (the review's R5). Before 152A that switch was skipped for good, and the next switch
    told the plan lost. Both pinned (`RemodelHostTests`); owner question 3.
  - The same document closed and opened again leaves the attachment on the closed one, by path;
    its commands fail with their own errors, since the presence check finds the reopened file by its
    name (this record first said "document no longer open", which the review's N4 corrected). Older
    than 152A; no other document's evidence.
  - `LookAgain`'s guard lets go of `_starting` whatever escaped it. Nothing inside it throws - every
    call catches its own failures - and a claim left held would stop the gate following for good,
    the worse of the two (the review's N8).
- **Owner questions** (recorded 2026-10-20, behaviour unchanged):
  1. Follow a configuration switch at the switch, as a document switch is followed? The general
     tools and Show would follow it too, and a session started before the switch would have its pipe
     closed, so its later live calls fail rather than run through the other configuration's table
     (the review's R2); and a plan made on the attachment would be lost on a configuration switch of
     its original part, which 22A keeps. Or keep it followed only when a review asks, as now?
     *Changed 2026-10-20 by the Codex review's X1 (below):* a session's later live calls no longer
     run through the other configuration's table - the bridge refuses them while the configuration
     differs, and answers again once it is switched back - so following at the switch would no
     longer be what protects a review. What remains for the owner: whether the tool service should
     follow a configuration switch at the switch, so that the live commands it refuses meanwhile - a
     waiting review's after Send, the general-chat tools' - and Show in SOLIDWORKS (`entity.show`,
     through the tool service's scope, walked in the configuration attached to) answer about the
     configuration now active, at the cost of a session's pipe closed under it and a plan made on its
     original part's attachment lost on such a switch (22A); or keep the attached configuration until
     a review asks or a document switch re-attaches, as now. *Settled by decision 158A (2026-10-21,
     "2A"):* kept as now - a configuration switch is followed only when a review asks, or once a
     document switch re-attaches; the add-in's one fan-out of a document or configuration change asks
     the gate to follow by the path alone, and only the review host asks it to follow the active
     configuration (158A, below).
  2. A review pressed while the tool service is between two attachments runs with no live checks,
     which its coverage says. Refuse it as `BridgeOnAnotherDocument` while a follow is in flight -
     the gate knows - or leave it?
  3. With Start switched off, should the look once a plan ends follow into the re-modeler's copy its
     close left open, and should a plan whose session was closed at the plan be told lost when the
     tool service re-attaches?
- **Review**: an independent adversarial review of the branch at `cf67b69` found no must-fix - a
  session is handed only a bridge that served its document when asked, and that pipe then serves
  that document or nothing - and five should-fixes and nine nits, settled test first by T212 to T214:
  - R1 (should-fix): a look's busy question read a chat the backend did not answer about as no turn,
    and took the bridge down under a running turn - one timed-out request in a turn's polls was
    enough (the reviewer's probe). Fixed: the gate asks `ReviewHost.TurnMayBeRunning`, the remodel
    run first (What the busy question reads, above).
  - R2 (should-fix, records): the configuration holds only at a session's start. The record said a
    session's bridge reaches its document or nothing; it reaches it in whatever configuration is
    active when it calls. Corrected above, What is left, and owner question 1.
  - R3 (should-fix): two rules for "the same document" - the review's raw path and the gate's
    canonical one - left a refusal that never cleared for a document the attach spelled otherwise.
    Fixed: a review's request is made by the review's rule (The configuration, above).
  - R4 (should-fix, tests): `Settle`'s look, a review's request made while work was in flight, and
    "a busy question that throws owes nothing" had no failing case, and a follow's reading that left
    what was owed crashed the test host. Five cases now - a switch just after a look's reading, a
    request during a start, a throwing question at a switch and in a look, and a switch back while
    the question is out - and a follow takes what is owed before it asks, so that mutation fails
    cleanly.
  - R5 (should-fix, records and tests): with Start switched off, the look follows what the plan's
    close left active. Pinned both ways, recorded (What is left), owner question 3, and 004's notes.
  - N1: a Start pressed between a look's busy answer and its reading - recorded (What is left).
  - N2: a switch made while a busy question that then threw was out was dropped. Fixed: the follow
    takes what is owed before it asks, and a throw settles, looking at what came meanwhile.
  - N3: a configuration switch that landed while a start or a follow was in flight re-attached.
    Fixed: a switch's follow is made by the path wherever it lands; pinned during a start and once a
    hold ends.
  - N4: a reopened document's commands do not answer "document no longer open" - corrected.
  - N5: "making nothing" overstated a refusal at the session, after which a new review's run folder
    stays - corrected in the dated note on 149A's question 5 and in Phase 16's purpose and checkpoint.
  - N6: a review's request does not clear a refusal for a waiting plan's copy - corrected above, and
    recorded.
  - N7: the busy question's cost and the log's line. The add-in now reads the remodel run first; the
    cost and the line are said truly above.
  - N8: `LookAgain`'s guard - recorded (What is left).
  - N9: the dated note's form - now "*Settled by decision 152A (2026-10-20, ...)*", as the file's
    others.
  - Existing cases changed deliberately: `TheAddInsGateRefreshesTheRemodelHostOnEveryPublishAndARunHoldsIt`
    also pins the busy question's new reading (tightened). The reviewer's own probes stood in a
    scratch copy and were not committed; T212's cases are their counterparts.
- **Mutations**: each fix taken out once, by one exact replacement, the tree rebuilt, the named
  classes run - `ToolServiceWiringTests`, `RemodelHostTests`, `DeferredRestartTests`,
  `ErrorLabelsCoverTheHostTests` and `ReviewHostTests`, 728 cases; `ReviewPageSendGateTests` for
  the pin; and for the words file the C# scan and the Python words and fixture tests - and the file
  restored byte for byte (checked by its sha256): 33 mutations, 225 red results, every one red;
  and for the review's fixes, 12 more (V1 to V12) over the same classes, 742 cases then, 20 red
  results, every one red.

  | Id | Taken out | Red |
  |---|---|---|
  | G1 | `FollowCore`: a follow skipped while work holds the bridge lets go and owes nothing | 9: the skipped switch followed, one look at a time, the look to another model, the copy kept and another document followed, the request through a hold, the gate's own look, and both Remodel cases |
  | G2 | `Defer`: the owed follow is never asked again | 9: as G1 |
  | G3 | `LookAgain`: a look runs beside a follow in flight | 1: the look due during a follow's busy question |
  | G4 | `FollowDocument`: a switch during a start or a follow is dropped, as before | 1: the switch that lands during a start |
  | G5 | `StartCore`: no look once the new service is published | 1: as G4 |
  | G6 | `Serves`: the path alone | 2: the two requests' cases |
  | G7 | `FollowNow`: re-attaches to the document already attached to | 2: the request with nothing changed, and the look back on the attached document |
  | G8 | `FollowNow`: the planned copy not asked after | 4: T180's two cases through a switch, the look's copy kept, and the Remodel plan case |
  | G9 | `FollowCore`: a look writes the busy line too | 2: one look at a time (one line per switch), and the request through a hold (none) |
  | G10 | `FollowActiveDocument`: asks no look | 2: the two requests' cases |
  | G11 | `DocumentServedBy`: answers for any pipe | 1: its case |
  | G12 | `DocumentServedBy`: answers no configuration | 4: its case, the `ping` case, and the two requests' cases, which read it |
  | G13 | the gate's own `later`: never looks | 1: the gate's own look |
  | G14 | the gate's own `later`: looks at once | 1: as G13 - it looked within the poll |
  | H1 | `ToolServiceHost.Configuration`: none recorded | 1: the `ping` case |
  | R1 | `StartReview`: a new review not asked before anything is made | 8: the refusal's six new-review cases, which then extract and are refused at the session, and the two cases of a bridge that cannot be told |
  | R2 | `CreateReviewSession`: no start asked at its session | 12: the refusal's eight context, context Retry and Recheck cases, pressed again for those three, and the bridge moved during the extraction |
  | R3 | the session given the bridge published now, not the one asked about | 1: the bridge asked about |
  | R4 | the configuration not compared | 11: the refusal's five cases of another configuration, and pressed again for all six starts |
  | R5 | the path compared with its case | 9: the six cases of a path spelled otherwise, and `ReviewHostTests`' Recheck theory, three cases |
  | R6 | not retryable | 15: the refusal's fourteen cases and the moved bridge |
  | R7 | the tool service not asked to follow | 21: the refusal's fourteen, pressed again six, and the moved bridge |
  | R8 | the class `DocumentChanged` | 24: as R7, the two that cannot be told, and the scan's list |
  | R9 | the words: the document's path added | 17: the refusal's fourteen, the moved bridge, and the two that cannot be told |
  | R10 | no bridge refused too | 42: every start with no bridge, in `DeferredRestartTests` and `ReviewHostTests` |
  | R11 | an answer that throws not caught | 1: the answer that throws |
  | R12 | a Recheck says it checks before its bridge is asked | 8: the refusal's three Recheck cases, and the five Recheck cases that count its statuses |
  | R13 | the options' default vouches for a bridge | 2: the two that cannot be told, which read it first |
  | A1 | the add-in does not wire `BridgeDocument` | 1: the add-in's source case |
  | A2 | the add-in does not wire `FollowActiveDocument` | 1: as A1 |
  | W1 | the label taken out of the words file | 8: `ErrorLabelsCoverTheHostTests`' words-file case; the sentence's pin; and the six pane fixture tests, the committed fixtures no longer a fresh generation |
  | W2 | the pin left on the old `review-waiting.json` | 3: `ReviewPageSendGateTests`' cases that read it |
  | V1 | `TurnMayBeRunning`: no answer read as no turn | 1: the no-answer case |
  | V2 | `TurnMayBeRunning`: asks with no backend process | 1: the no-backend case |
  | V3 | the add-in's busy question: `AnyTurnRunning` again | 1: the add-in's source case |
  | V4 | a review's request: the path compared canonically | 1: the attach's other spelling |
  | V5 | a switch's follow: the configuration compared too | 2: a configuration switch during a start and once a hold ends |
  | V6 | `FollowCore`: a throwing question drops what was owed meanwhile | 1: the switch made while the question was out |
  | V7 | `FollowCore`: a throwing question owed and asked again a poll later | 3: the two "owes nothing" cases and the switch meanwhile |
  | V8 | `Settle`: never looks | 2: the switch just after a look's reading, and the switch while a throwing question was out |
  | V9 | `FollowActiveDocument`: owed only when it can be looked at at once | 1: the request during a start |
  | V10 | `FollowNow`: its reading leaves what was asked meanwhile owed | 1: the switch back while the question is out |
  | V11 | `FollowCore`: takes nothing before it asks | 1: the look whose question throws |
  | V12 | `KeepCopyAttachment`: a plan closed at the plan keeps its copy's attachment | 5: four of T180's - a plan closed at the plan, another attachment or none, and the cleanup's - and the Start-off look that follows the copy |
- **Evidence** (2026-10-20; before at `bd07f29`, after on the branch with the review's fixes): the C#
  build, `--no-incremental`, at zero warnings both times; `SwReview.Extractor.Tests` 10,059 passed
  before and after, and `SwReview.AddIn.Tests` 3,003 before and 3,071 after - the 68 cases of T207,
  T209 and T212 - with the restart and tool-service classes and the stub-children collection, 853
  cases, green five times in a row. One full run made while both Python suites ran beside it failed
  `ReviewPageNarrowLayoutTests`' two cases, a page's layout timed under load, which 152A does not
  touch; they passed alone and in the full run after. Python, not live, with
  `SWREVIEW_REQUIRE_TOKENIZER=1`: 18,089 passed and 5 skipped before, and 18,090 passed and 5
  skipped after - the label's pin - on 3.12 (3.12.3) and on 3.11 (3.11.16, `--isolated`) alike.
  `ruff check` clean, and no broken link.
- **Tests**: T207 and T209 in [tasks.md](tasks.md), each written first; and the review's, T212.

**3. The Codex review (a second opinion, 2026-10-20).**

- **What it was**: an adversarial review of the branch at `22bdd6b` by Codex, a second opinion
  beside the review above. It answered "needs attention" with two high findings, settled test first
  by T215 to T219.
- **X1 (high): a configuration switched before the session passed the bridge's check.** Extract A in
  Default and switch A to Machined during the extraction or just after it - the extraction runs in
  one call on the application thread (`SwReviewDump.Run`), so a switch made during it lands as it
  ends - and the follow, which a same-path switch re-attaches nothing for (22A), left the bridge's
  record on Default, so `DocumentServedBy` answered Default and the session was made; its live
  interference check, which `SwInterferenceSource` runs on the document's active configuration, then
  mapped Machined's rows through Default's component table into Default's review. The same reached
  any live command a session sends after a switch (the R2 above, What is left).
- **The combination chosen, and why**: both of the review's suggestions, since each covers what the
  other cannot.
  - *At the session, the active document read again* (`ReviewHost.StartReview`, once the evidence is
    extracted and before `CreateReviewSession`), as 149A reads it again after a restart: the one
    reading that can refuse before anything runs, in plain words, while the evidence extracted is
    still the review's. Refused `DocumentChanged`, retryable: "the active document or its
    configuration changed while the evidence was extracted, so no review session was started and no
    check ran. Make the part or assembly and the configuration you want reviewed active again, then
    press Review again." No path. The run folder keeps what was extracted, as one whose extraction
    fails keeps its own, and as the bridge's refusal at the session keeps it. The tool service is
    not asked to follow: the words send the engineer back to the review's configuration, where the
    bridge still is, and a follow would move it away. And nothing is left half made: the status
    line, which said it was extracting, is told the extraction is over - `status {stage: "ready",
    message: "Evidence extracted, but no review was started; no review tokens used."}` - after this
    refusal and after `BridgeOnAnotherDocument` at a new review's session alike, where it used to be
    left saying it was extracting.
  - *At the bridge, a live command refused while the active configuration is not the one it attached
    in* (`SwBridgeDispatcher`, over `BridgeServices.ActiveConfiguration`, which the in-process host
    reads through its session's gate, `SwSessionConfiguration.ActiveConfigurationName`): `capture`,
    `measure`, `interference` and `tessellate` each ask after the secret and the name and before
    they run - so nothing is run or written on another configuration, a mesh or a capture file above
    all - and answer `configuration changed: this bridge answers about configuration 'Default' of
    <the document>, and 'Machined' is active now, so a live command would answer about another
    configuration than the one extracted. Make 'Default' active again in SOLIDWORKS.` (its way on
    reworded on review, N5, below); `ping`, `drawing.read` and the remodel family are not asked. The
    name is compared exactly, and a reading that answers none is refused too. Each command asks, so
    a switch back lets the next one through. It covers what no start can see: a switch after the
    session's start, in its own checks' seconds or before a Send, a follow-up or an answer much
    later. The add-in's host serves each request in one call on the application thread, where the
    engineer's switch is made too, so none lands between the reading and the command's end.
  - *Why both*: the session's reading alone leaves every later live command open; the bridge's alone
    would make the session and run its checks with every live check refused - a review run half,
    with the engineer told only in its coverage.
  - *Not chosen*: following a configuration switch at the switch (owner question 1, changed above),
    which would close a session's pipe and lose a plan made on its original part's attachment (22A);
    and invalidating the bridge for good once its configuration changed, which would refuse it after
    a switch back too, when its answers are the review's again.
- **Where the reading is not added**: a Recheck runs no live check at its start (149A, pinned by
  `ARecheckRunsOnItsSavedEvidenceWhateverIsActiveAfterTheRestart`), and its later live calls are the
  bridge's to refuse; a context review reads its document after its restart, just before its session
  (`CurrentContext`), and a context review's Retry after its gate (149A); a switch in the moment
  after either is the bridge's to refuse too.
- **The label**: `DocumentChanged`'s said "... so nothing was extracted. Make the part or assembly
  you want reviewed the active document, then press Review again.", untrue at the session. Now "The
  active document or its configuration changed while the review was starting, so the review did not
  start. Make the part or assembly and the configuration you want reviewed active, then press Review
  again.", true of both refusals; 149A's pin of it in `test_review_words.py` changed deliberately.
  The pane fixtures are regenerated with their generators - `review-big-assembly.json`,
  `review-waiting.json`, `review-waiting-big-assembly.json` and `review-waiting-restored.json`, one
  line each, `review-not-sent-session.json` unchanged - and `review-send-failure-events.json`'s pin
  of `review-waiting.json` moved to its sha256 as written on Windows (CRLF).
- **Two existing cases changed deliberately**: `ReviewHostTests`' two cases that a review names, and
  tracks, the document it extracted, not the one active when it answers, made their switch to
  another document during the dump, which is now refused at the session; each switches while `POST
  /sessions` is out instead, where a switch still lands unrefused, and what each pins is unchanged.
  The first is renamed
  `ReviewStartedNamesTheExtractedDocumentEvenIfTheActiveOneChangedWhileItsSessionWasMade`.
- **X2 (high): a follow's teardown could take down work just begun.** A look's busy question reads
  the remodel run, then whether a turn may be running - a round trip per chat - and a Remodel plan
  could begin while the round trip was out: it marked the host busy too late for the question, made
  its copy active, and was not yet tracked, so `KeepCopyAttachment` could not keep it (T180 keeps a
  planned plan only); the look then took the bridge down, though `RunInProgress` was true. The same
  race stood with Start (the N1 above), with a turn started through the proxy (What is left, first
  item), and with a review session being made, whose checks run over the bridge while `POST
  /sessions` is out and whose turn the busy question cannot see until it is tracked.
- **The fix: work holds the bridge through the gate.** `ToolServiceGate.HoldAttachment` holds the
  service listening now, under the gate's lock, or answers null when none is listening - none
  started, a follow taking one down and the next not listening yet, or disposed. A follow notes the
  holds taken before it asks its question - one held then makes it busy without the round trip, and
  the switch's line is written as for any busy follow - and takes the bridge down, under the same
  lock, only if none was taken since; otherwise it is owed and asked again a poll later, afresh. A
  hold and a teardown cannot pass each other: work that asks once the teardown is decided finds no
  service to hold. Another busy check alone would not do: the plan's flag was set, and read too
  late. Nothing waits: a hold is taken and let go under the gate's lock alone, which is never held
  while anything is waited for, and no hold is taken on the application thread (155A's lesson).
- **Who holds, and for how long**:
  - a Remodel plan, from just after 145A's gate marks the host busy and before it reads its
    attachment, until it ends - planned, refused or failed (`FreeTheHost`) - and a run until its
    session is closed (`Execute`'s `finally`). A plan given no hold is refused `RemodelUnavailable`,
    in the words while the tool service attaches; a Start `SessionLost`, since its plan's session
    goes with the attachment; neither waits for the next service.
    *Noted 2026-10-21 (the merge of `main` and the final reviews, N5):* since the merge with 154A a
    plan and a Start hold from just after the run root is judged again, which follows the gate, so a
    press refused for its run root holds nothing.
  - every start that makes a review session, from before it reads the bridge it hands over until the
    session is tracked (`CreateReviewSession`): from then the busy question sees the session's turn.
    With no hold to be had the session is given what is published, as before - none, or a bridge no
    service listening has, which is refused. A start refused for its bridge lets go before it asks
    the tool service to follow, which a hold still held would put off a poll (found reviewing this
    fix). *Corrected 2026-10-21 (the review of these fixes, N7):* or until `POST /sessions` gives up
    after the backend client's 30 seconds, when the hold is let go while the backend may still run
    the review's checks over the bridge, and that session is never tracked (015 RK-10's orphan
    path).
  - a page call that would start a turn (the proxy's `StartsATurn`), while it is out: the backend
    marks the turn running before it answers. A call the host refuses (143A) holds nothing; one with
    no hold to be had goes on, since its chat's bridge, given when the chat was made, serves the
    attachment going away or none, and waiting would change nothing it reaches; a hold that cannot
    be asked for is answered `ProxyFailed`, unsent, as a host that throws instead of answering is.
- **The preserved attachment keeps working**, a plan still being planned included: while it plans,
  its hold keeps the bridge; once planned, the next look finds its copy active and keeps the
  attachment (T180), and Start runs on its session.
- **What remains** (recorded, not changed): a chat whose bridge was taken down while nothing held it
  - the engineer moved on and the turn had ended - meets a closed pipe on its next turn; older than
    152A, failed coverage, and no other document. A turn's end is still learnt only by asking. And
    owner question 2 stands as asked: a hold the gate cannot give is the gate saying no service is
    listening - a follow in flight among the reasons - and the session is given what is published.
- **Owner questions** (recorded 2026-10-20, behaviour unchanged), besides question 1 as changed
  above:
  4. The console host's bridge (`swreview-extract serve`) compares no configuration: it runs out of
     process, where a switch can land between any two of its calls, so a check there would narrow
     the window and not close it. Add it all the same, or leave the console host as it is?
  5. The reviewer's client takes a `configuration changed` refusal as any bridge failure - failed
     coverage carrying the sentence, counted toward its breaker, which opens after three for the
     rest of the run. Treat it as it treats a closed document instead, a definite answer that leaves
     the count where it was, so live checks go on once the configuration is switched back? *Settled
     2026-10-21, decided on review for the owner, who may revert (The review of the Codex fixes,
     below):* treated as a closed document is - not counted.
- **Contracts**: 002 [`contracts/pane-host-messages.md`](contracts/pane-host-messages.md) and
  [`contracts/chat-api.md`](contracts/chat-api.md); the bridge's
  `extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md` (Errors that are not command failures);
  004
  [`contracts/pane-remodel-messages.md`](../004-resilient-remodeler/contracts/pane-remodel-messages.md),
  [`contracts/bridge-remodel.md`](../004-resilient-remodeler/contracts/bridge-remodel.md) and
  [`research.md`](../004-resilient-remodeler/research.md) (22A's paragraph), each with a dated note.
- **Mutations**: each fix taken out once, by one exact replacement, the tree rebuilt, the named
  classes run - the dispatcher's own suites (`BridgeDispatcherTests`, `BridgeTessellateTests` and
  `BridgeSecretPolicyTests`, 191 cases) for its mutations; `ToolServiceWiringTests`,
  `RemodelHostTests`, `DeferredRestartTests`, `ErrorLabelsCoverTheHostTests`, `ReviewHostTests`,
  `BackendProxyHandlerTests` and `InProcPipeServerTests`, 933 cases, for the add-in's;
  `ReviewPageSendGateTests` for the pin; and for the words file the C# scan and the Python words and
  fixture tests - and the file restored byte for byte (checked by its sha256): 19 mutations for X1,
  97 red results, and 22 for X2, 114 red results, every one red.

  | Id | Taken out | Red |
  |---|---|---|
  | XA1 | `capture` asks no configuration | 6: its refused, run-as-before and throwing-reading cases, and the three refused readings of the exact name |
  | XA2 | `measure` asks no configuration | 3: its refused, run-as-before and throwing-reading cases |
  | XA3 | `interference` asks no configuration | 3: as XA2 |
  | XA4 | `tessellate` asks no configuration | 3: as XA2 |
  | XA5 | the name compared ignoring case | 1: another case of the name |
  | XA6 | a host that reads no configuration refuses every live command | 31: its four cases, and every earlier `capture`, `measure`, `interference` and `tessellate` case of the dispatcher's suites, whose hosts read none |
  | XA7 | no configuration read as active taken for the bound one | 1: the reading of none |
  | XA8 | the configuration asked before the secret | 8: the three commands that are not live, the refused secret, and the four run as before, asked twice |
  | XA9 | the in-process host reads no active configuration | 1: the host's source case |
  | XA10 | the in-process host reads the bound configuration as the active one | 1: as XA9 |
  | XB1 | `StartReview`: a new review not read again at its session | 7: the four changes, pressed again, the status after the change, and the hold's case of a changed document |
  | XB2 | the refusal at the session in 149A's words | 4: the four changes |
  | XB3 | the refusal at the session leaves the extraction's status | 5: the four changes, and the status after the change |
  | XB4 | a refusal inside the session leaves the extraction's status | 1: the status after the bridge moved |
  | XB5 | the refusal at the session not retryable | 4: the four changes |
  | XB6 | the refusal at the session asks the tool service to follow | 4: the four changes |
  | XB7 | the session's reading compares the path alone | 4: another configuration's case, pressed again, and its status and hold cases |
  | XP1 | the pin left on the old `review-waiting.json` | 3: `ReviewPageSendGateTests`' cases that read it |
  | XL1 | `DocumentChanged`'s old label put back | 7: its pin, and the six pane fixture tests, the committed fixtures no longer a fresh generation |
  | YG1 | `HoldAttachment`: a hold counts nothing | 8: the gate's four hold cases, and the four races - a review session, a turn, a plan, a run |
  | YG2 | `HoldAttachment`: a hold given with no service listening | 2: no hold while none listens, and the plan pressed during a teardown |
  | YG3 | `FollowNow`: holds taken meanwhile ignored | 5: the hold taken while the question was out, and the four races |
  | YG4 | `FollowCore`: a hold held when a follow begins not busy | 3: busy without the question, let go twice, and the next service held |
  | YG5 | `LetGo`: a hold let go still held | 16: every case that follows once a hold is let go - the gate's three, the four races, T180's four (five cases), and four more through the gate |
  | YG6 | a hold let go twice lets go twice | 1: let go twice |
  | YG7 | `FollowCore`: the holds noted after the question | 5: as YG3 |
  | YR1 | `Plan`: holds nothing | 8: the plan's holds (five cases), the plan given none, the plan race, and the plan pressed during a teardown |
  | YR2 | `Start`: holds nothing | 3: the run's hold, the Start given none, and the run race |
  | YR3 | `FreeTheHost`: lets go of nothing | 14: the plan's holds, and every case that follows once a plan has ended |
  | YR4 | `Execute`: a run's end lets go of nothing | 3: the run's hold, the run race, and the run that holds the service across a switch |
  | YR5 | `Plan`: a plan given no hold goes on | 2: the plan given none, and the plan pressed during a teardown |
  | YV1 | `CreateReviewSession`: a session holds nothing | 9: the review session race, the six starts' holds, and the two ends at the session |
  | YV2 | `CreateReviewSession`: lets go before the session is tracked | 6: the six starts' holds |
  | YV3 | `CreateReviewSession`: a start refused for its bridge asks the follow while it holds | 1: the bridge moved |
  | YP1 | `TryServe`: a turn call holds nothing | 12: the six turn calls, the four endings, the hold that throws, and the turn race |
  | YP2 | `TryServe`: a turn call never lets go | 11: the six turn calls, the four endings, and the turn race |
  | YP3 | `TryServe`: a hold that throws lets the call through | 1: the hold that throws |
  | YT1 | `TaskPaneControl`: the proxy given no hold | 1: the add-in's source case |
  | YW1 | the add-in: the pane's turn calls hold nothing | 1: as YT1 |
  | YW2 | the add-in: the review host's sessions hold nothing | 1: as YT1 |
  | YW3 | the add-in: the Remodel host's plans and runs hold nothing | 1: as YT1 |
- **Evidence** (2026-10-21, at `a6ab107`): the C# build, `--no-incremental`, at zero warnings;
  `SwReview.Extractor.Tests` 10,085 passed, from 10,059 - T215's 26 dispatcher cases - and
  `SwReview.AddIn.Tests` 3,126, from 3,071 - T215's 9 cases and T217's 46; the restart and
  tool-service classes with the stub-children collection, 890 cases, from 853, green five times in a
  row, the plan race on a thread of its own among them. Python, not live, with
  `SWREVIEW_REQUIRE_TOKENIZER=1`: 18,090 passed and 5 skipped on 3.12 (3.12.3), as before - the
  label's pin changed and no case was added - and 18,089 passed and 6 skipped on 3.11 (3.11.16,
  `--isolated`): one geometry case's optional `embreex` import (`importorskip`) was not installed in
  the isolated environment this time. A first 3.11 run failed one case, `test_benchmark_failures`,
  whose benchmark run records the commit it began at and refuses its resume at another: the code was
  committed while it ran. It passed alone, and in the run after. `ruff check` clean, and no broken
  link.
- **Tests**: T215 and T217 in [tasks.md](tasks.md), each written first.

**4. The review of the Codex fixes (2026-10-21).**

- **What it was**: an independent adversarial review of the branch at `aac63df`, by Opus. It found
  no must-fix, and confirmed that the bridge check's two reads go through the gate under names the
  guard allows, that every hold is let go on every path with nothing waited for under the lock, that
  the preserved attachment survives, and that the cases changed deliberately still pin what they
  pinned. It found two should-fixes and four nits, settled test first by T220 to T224, and the
  coordinator decided owner question 5 on it, for the owner, who may revert.
- **S1 (should-fix): the read behind the bridge check had no test.**
  `SwSessionConfiguration.ActiveConfigurationName` was pinned only by the host's source case: the
  reviewer made it read the bound configuration, which would turn X1's bridge half off at the pilot,
  and every related case stayed green; one that answered none would refuse every live command,
  unseen too. A case on the interop stand-ins (`SwSessionActiveConfigurationTests`) attaches in
  Default and switches the manager's active configuration: the active name follows the switch, the
  bound one (`ConfigurationName`) still answers Default, both reads pass the gate's observer, and a
  document that reports no active configuration answers none. Green on the code, red under both
  mutations.
- **S2 (should-fix): the reading after the extraction compared the document with the earlier
  reading, not with what was extracted.** The dump attaches to whatever is active as it begins
  (`SwReviewDump.Run`), and said nothing of it: switched after 149A's second reading - while the run
  folder is made and the extracting status posted - and back during the extraction, it extracted the
  other document, the reading once it ended saw the review's own again, and so did the bridge check,
  so the session ran the review's live checks into the other document's package, under a review
  recorded as the review's. Now the dump says what it attached to (`DumpSummary.Extracted`: the
  document's path and the configuration the attach was bound to), and a new review is refused
  `DocumentChanged` when that is not the review's, by the pane's one rule, in the same words and
  leaving nothing half made; a dump that says nothing is not taken for the review's - the add-in's
  always says. The double switch is pinned. The other consumers of a dump read nothing new and are
  unchanged: the Model check and Standards tabs, the Terminal tab's extraction, and the context
  preparation, which its own generation count already guards - every `document.changed` while it
  runs expires it. The test doubles of a dump in the Review host's three suites now say what they
  attached to, as the real one does.
- **Q5 (decided on review for the owner, who may revert): a `configuration changed` refusal no
  longer counts toward the reviewer's breaker.** Counted, three such refusals opened the circuit for
  the rest of a review run, or of the general-chat terminal's session (`swreview.mcp.server`), even
  after the configuration was switched back. The client now names the refusal
  (`BridgeConfigurationChangedError`, matched at the start of the host's text, as `unauthorized` is)
  and takes it as it takes a closed document: a definite answer from a healthy host, failed coverage
  carrying the sentence, the count left where it was, so live calls go on once the configuration is
  the review's again. Its marker is pinned against the host's `ConfigurationChangedPrefix`. Owner
  question 5, settled; the client's `PROTOCOL.md` (N6) and `contracts/chat-api.md` say so.
- **N4: a finishing run could let go of the next plan's hold.** A run ends on a thread of its own
  and freed the host before it let go of its hold, so a plan pressed in between took a hold of its
  own (the field's exchange let go of the run's), and the run's thread then let go of the plan's,
  leaving the plan unheld. A plan or a run now lets go before it frees the host (`Execute`,
  `FreeTheHost`), and letting go never throws, since it comes first: a hold that failed as it was
  let go would otherwise keep the host busy, holding back every plan and every settings restart, or
  reach a run's own thread, which no one waits on. The gate's own holds never fail.
- **N5: the bridge's way on was impossible after a rename.** The bound configuration is copied once,
  at the attach, and compared by name, so a configuration renamed since makes every live command
  refused with "Make 'Default' active again", which can no longer be done. The way on now holds
  either way: "Make the configuration you started with active again, or press Review to start a new
  review." A renamed configuration still answers nothing until a new review re-attaches the bridge,
  recorded.
- **N6: the client's `PROTOCOL.md` named three refusals.** It names four, the new one with how the
  breaker takes it.
- **N7 (records): a hold is bounded only by its holder.** A review session's start holds the bridge
  until its session is tracked - or until `POST /sessions` gives up after the backend client's 30
  seconds, when the hold is let go while the backend may still be running the review's checks over
  the bridge, and that session is never tracked (015 RK-10's orphan path), so a follow can take the
  bridge down under those checks. Corrected above (Who holds). And nothing in the gate bounds a
  hold: a plan's calls are bounded by the re-modeler's client (30 seconds each), a run by its twenty
  minutes (`RemodelLimits`), a session start by those 30 seconds and a turn call by the proxy's 120;
  a holder that never let go would keep the tool service on its document for good. Owner question 6.
- **What remains** (recorded, not changed): the Model check and Standards tabs name the document
  they read before their dumps, so a switch in the moment before a dump attaches labels a package of
  another document; they hand the backend no bridge and run no live check, and their reply could
  name what the dump says it extracted. Older than 152A.
- **Owner questions** (recorded 2026-10-21, behaviour unchanged): 6. Bound a hold in the gate - let
  go after a time whatever its holder does - or keep each holder's own bound, as now? *Settled by
  decision 158A (2026-10-21, "2A"):* bounded in the gate - a hold held longer than an hour
  (`ToolServiceGate.HoldLimit`) no longer holds back a follow, and is said once in the tool-service log
  by its holder's kind and how long it held; its work goes on, and its holder letting it go later lets
  go of nothing more (158A, below).
- **Mutations**: each fix taken out once, by one exact replacement, the tree rebuilt for the C#
  ones, the named cases run - `SwSessionActiveConfigurationTests`, `SwSessionReadOnlyOpenTests`,
  `BridgeDispatcherTests` and `BridgeTessellateTests`, 161 cases, for the extractor's;
  `DeferredRestartTests`, `ReviewHostTests`, `RemodelHostTests`, `EngineeringContextHostTests` and
  `ToolServiceWiringTests`, 810 cases, for the add-in's; `test_bridge_client.py` and
  `test_tools_bridge.py`, 108 cases, for the reviewer's - and the file restored byte for byte
  (checked by its sha256): 11 mutations, 21 red results, every one red.

  | Id | Taken out | Red |
  |---|---|---|
  | ZS1a | `ActiveConfigurationName`: reads the bound configuration | 1: S1's case |
  | ZS1b | `ActiveConfigurationName`: never answers a configuration | 1: as ZS1a |
  | ZS2a | `StartReview`: what the dump extracted not compared | 3: the double switch's two cases, and the dump that says nothing |
  | ZS2b | `StartReview`: a dump that says nothing taken for the review's | 1: the dump that says nothing |
  | ZN4a | `Execute`: the host freed before the hold is let go | 1: the order of letting go |
  | ZN4b | `FreeTheHost`: the host freed before the hold is let go | 1: as ZN4a |
  | ZN4c | `LetGoOfTheToolService`: a hold that fails as it is let go let through | 2: the failing hold, for a plan and for a run |
  | ZN5 | the way on names the bound configuration again | 4: the refusal word for word, for each live command |
  | ZQ5a | the client: the refusal not named | 3: the named failure, the circuit kept, and the count kept |
  | ZQ5b | the client: the refusal counted toward the breaker | 2: the circuit kept, and the count kept |
  | ZQ5c | the client: the marker matched anywhere in the text | 2: the two sentences that merely mention a change |
- **Evidence** (2026-10-21, before main was merged): the C# build, `--no-incremental`, at zero
  warnings; `SwReview.Extractor.Tests` 10,086 passed, from 10,085 - S1's case - and
  `SwReview.AddIn.Tests` 3,133, from 3,126 - T220's seven. The reviewer's client and tool tests,
  the records' readers and the words, fixture and pin tests, 1,090 cases, passed on 3.12 and on
  3.11 (`--isolated`). `ruff check` clean, and no broken link.
- **Tests**: T220 and T222 in [tasks.md](tasks.md), each written first.

#### The merge of `main`: 154A's run root beside 152A's bridge (2026-10-21)

- **Question**: 154A landed on `main` (pull request #30) after 153A, with a run root in force that
  every run start judges - again once the backend is ready or its gate is passed - and a run folder
  that must lie under it. The coordinator asked, for the owner: 152A's tasks renumbered after 153A's
  and 154A's first, in a commit of its own; `main` merged in, never rebased, each conflict resolved
  keeping both sides' intent; 152A's hold, bridge check and post-extraction reading placed beside
  154A's run-root reads and 153A's start under way, so a session is given exactly the bridge
  checked, the settings in force and a folder under the run root in force; and the order of the
  refusals decided so each says what is true, and pinned.
- **The renumbering** (`caccf04`): T166 to T183 became T207 to T224 (the note under this entry's
  heading), the commits keeping their first numbers. 152A's section of `DeferredRestartTests.cs`,
  numbered 13 beside 153A's, became 15, since 154A's is 14, and moved after 153A's, so the file
  reads 13, 14, 15 once merged; T209, T215 and `ReviewHostTests.cs` name it.
- **Decision** (the coordinator, for the owner, 2026-10-21): the order the two decisions leave
  (*corrected on the final reviews, N1:* first given as the one whose way on the other cannot mend
  answered first - Why, below). At a review session (`CreateReviewSession`): a start of the backend
  under way (153A); the run root judged again, then the run folder under the run root in force
  (154A); then the hold and the bridge (152A); then a Recheck's `checking` status and the settings
  in force. Before a new review's extraction: the run root judged again, then the bridge. In a plan
  and a Start: the run root judged again, and a Start's folder under it, then the hold. After a new
  review's extraction, its document read again (152A, on the Codex review) still comes before the
  session.
- **Why** (*corrected on the final reviews, N1*): the order is forced by the decisions it merges.
  153A reads a start under way before anything of the settings in force, the run root among them, as
  154A kept; and 154A judges the run root, and the run folder under it, before anything is asked or
  made under it - and the hold and the bridge question ask the tool service, and a bridge refused
  asks it to follow. Each refusal is true whichever comes first, and so is its way on: a start under
  way ends in seconds - 153A refuses it retryable for that reason - and a new review whose run root
  moved while it extracted is answered by pressing Review again, which makes a new run under the run
  root in force, as `DocumentChanged` is; that same reason keeps the document read after the
  extraction first. First given here as the bridge's and the hold's ways on being no way past a
  start under way or a moved run root, which pressing again would only meet - untrue of both those
  combinations. A start refused before its bridge is asked about takes no hold and asks the tool
  service to follow nothing.
- **Changed with it**: a new review refused at its session after its extraction - for a start under
  way or a run root that moved, as for its bridge - now ends the extraction's statuses with a
  `ready` status (T215's rule). On `main` those two left the status line saying that it was
  extracting.
- **The conflicts** (`d1ac5bb`), each resolved keeping both sides:
  - `ReviewHost.cs`, two hunks in `StartReview` - before the extraction, the run root judged again
    and 152A's bridge, in that order; after it, 152A's document read again and the session asked for
    with 154A's run-root arguments. `CreateReviewSession` merged without a conflict, in an order
    that asked the bridge first, and was reordered as decided.
  - `RemodelHost.cs`, three hunks: both options kept; in `Plan` and `Start`, the run root before the
    hold.
  - `DeferredRestartTests.cs`: 154A's section 14 and 152A's section 15, both added after 153A's 13,
    interleaved by git - each taken whole, 14 then 15, and checked against its side's own blob.
  - `ErrorLabelsCoverTheHostTests.cs` and `test_review_words.py`: both sides' classes and pins.
  - `review-send-failure-events.json`: the pin is the sha256 of `review-waiting.json` as
    regenerated, with CRLF (`ad7f1681...`). Both generators wrote the four pane fixtures, which
    match git's merge of the labels byte for byte; `review-waiting-apply-failure.json`, captured, is
    as it was.
  - The 002 records merged without a conflict, in id order: 152A's entry and Phase 16, then 153A's,
    154A's and 156A's.
- **Not changed**: a session reads 153A's record twice, as on `main` - the run root in
  `RunRootToUse`, the provider, model and effort just before `POST /sessions` - and now asks about
  the bridge between the two readings; only the add-in's first start, begun after the start under
  way was read, could move the record there, which 153A's fourth review found practically
  unreachable (N4 there).
- **What remains** (*added on the final reviews, N1*): a refusal ahead of the bridge asks the tool
  service to follow nothing, so a bridge on another document or configuration takes one press more
  to clear - the press that meets the bridge's refusal asks for the follow.
- **Tests**: T225 in [tasks.md](tasks.md), written on the merge and run against each order it could
  have taken - git's own at the session, and 152A's side of each conflict first - in which each case
  of its kind is red (Mutations, below): at the session, a folder under a run root a save has since
  moved is refused `RunRootChanged` (a new review, a Recheck, a context review and its Retry), a
  start asked for while a start of the backend is under way `BackendUnavailable` (a Recheck and a
  context review), and a run root a waiting restart brings in that the rule refuses `RunRootRefused`
  (a new review before its extraction, a Recheck at its session), each though the bridge is on
  another document too, with no hold taken and no follow asked; a plan and a Start refused for their
  run root take no hold, whether or not one is to be had; and a new review whose document and run
  root both changed while it extracted is refused for its document (a guard of the order kept).
- **Mutations**: as before - each resolution taken out once, by the order git or one side alone
  would have left or by one exact replacement, the tree rebuilt, `DeferredRestartTests`,
  `ReviewHostTests`, `RemodelHostTests`, `EngineeringContextHostTests` and `ToolServiceWiringTests`
  run (980 cases), and the file restored byte for byte (checked by its sha256): 9 mutations, 37 red
  results, every one red. The orders are red only in T225's cases, which no earlier case pinned.

  | Id | Where | Taken out | Red |
  |---|---|---|---|
  | ZM6 | `CreateReviewSession` | git's order: the hold and the bridge before the start under way and the run root | 7: T225's at the session - the run root moved (four), the start under way (two), the refused run root at a Recheck |
  | ZM7 | `CreateReviewSession` | the bridge between the start under way and the run root | 5: the run root moved (four), the refused run root at a Recheck |
  | ZM8 | `StartReview` | the bridge before the run root judged again, before the extraction (152A's side first) | 1: the refused run root before a new review's extraction |
  | ZM9 | `RemodelHost.Plan` | the hold before the run root judged again (152A's side first) | 2: the plan, a hold to be had and none |
  | ZM10 | `RemodelHost.Start` | the hold before the run root judged again and the folder checked (152A's side first) | 2: the Start, a hold to be had and none |
  | ZM11 | `StartReview` | `main`'s side alone: no `ready` after a refusal at the session | 2: the new review whose run root moved while it extracted, and T215's whose bridge moved |
  | ZM12 | `CreateReviewSession` | the session given the bridge published now, not the one checked | 1: the bridge asked about and no other (T209) |
  | ZM13 | `CreateReviewSession` | the session given the saved settings, not those in force | 8: 153A's eight sessions after a failed restart |
  | ZM14 | `CreateReviewSession` | a folder not under the run root in force let through | 9: 154A's five of a moved run root and T225's four |
- **Evidence** (2026-10-21, on the merge with T225): the C# build, `--no-incremental`, at zero
  warnings; `SwReview.Extractor.Tests` 10,086 passed and `SwReview.AddIn.Tests` 3,535, from 3,522 on
  the merge - T225's 13; the restart classes, the stub-children collection and the tool-service
  classes, 1,055 cases, five times in a row. Python - the words, fixture, pin and labels tests,
  every reader of `tasks.md` and `research.md`, `test_every_tasks_list_defines_each_task_id_once`
  among them, the client and tool tests, and the rest the merge touched, 2,250 cases - passed on
  3.12 and on 3.11 (`--isolated`). `ruff check` clean, no broken link, and every changed file
  `i/lf`.

#### The final reviews of the merged state (2026-10-21)

- **What they were**: Opus's review of `41f2a88`, which found nothing to fix - the merge lost no
  behaviour or test, the renumbering is clean, the holds behave as recorded, and ZM6 and ZM11
  matched when run again - and five nits; Codex's, with one medium finding; and the coordinator's
  own gate, which passed.
- **C1 (Codex, medium): a session's start could hand over a bridge published after its hold was
  refused.** During a re-attach the gate answers no hold, since no service is listening, and the
  re-attach could then publish the new service's bridge before the start read the bridge: the start
  handed that bridge to `POST /sessions` with nothing held and its session not yet tracked, so a
  switch while the call was out let a follow take it down under the review's first checks -
  avoidable failed coverage, not wrong evidence. 152A's case with no hold to be had covered only a
  publication that held still. Fixed by asking for the hold again (`ReviewHost.HoldForTheBridge`):
  with no hold to be had and a bridge published, the hold is asked for once more and the bridge read
  again under it; with still none, the start is refused `BridgeOnAnotherDocument`, retryable, rather
  than given a bridge nothing holds; with nothing published, the session is given none, as before.
- **Why this fix, of the two the coordinator offered**: it is the explicit one here. A bridge read
  under a hold is already vouched for by the bridge check, which asks the gate whether the service
  listening now - the one held - has its pipe; the one gap was a hold the gate could not give, and
  the fix closes it where it opens, in a few lines that say so, with the gate's contract and every
  host's wiring left as they were. The other - the gate handing out the bridge it published with the
  hold, under its lock - would have changed the gate's contract, the review host's options and the
  add-in's wiring, and still needed a rule for a hold it cannot give with a bridge published.
- **N1 (Opus, for the owner): the stated reason for the order was untrue of two combinations.**
  Corrected in the merge's entry (above), `ReviewHost.cs`, `RemodelHost.cs`, two test comments and
  both contracts: the order is the one 153A's reading order and 154A's rule leave, and each refusal
  is true whichever comes first. A refusal ahead of the bridge asks no follow: What remains, in the
  merge's entry.
- **N2: 153A's MR1 is pinnable since the merge.** Its "Not changed" says nothing is called between
  the start under way and the settings in force; since the merge the run root, the hold, the bridge
  question and the follow request are. A dated note there, and a case: a start that ends while the
  bridge is asked about meets a session already refused for the start under way (red under ZF4).
- **N3: the start under way before the run root was unpinned** - the reviewer's P1 moved it after
  them and 498 cases stayed green. A case: a Recheck under a run root not in force, asked for while
  a start of the backend is under way, is refused for the start, not its run root (red under ZF5).
- **N4: the full suite.** T226's Python evidence was a subset; this round's is the full suite,
  `pytest -m "not live"`, on 3.12 and on 3.11 (Evidence, below).
- **N5**: the Codex review's "a plan holds from just after the host is marked busy", in this entry
  and in 004's research, has a dated note: since the merge the hold comes after the run root is
  judged again, so a press refused for its run root holds nothing.
- **N6**: the class doc of `DeferredRestartTests` names 154A's section 14.
- **What remains** (recorded, not changed): a hold had in the instant between the gate's making a
  new service its own and its publishing it reads no bridge, and the session is given none, as
  before - no bridge goes out unheld; closing that would take the other fix.
- **Tests**: T227 in [tasks.md](tasks.md). Written first, against the code at `41f2a88`: C1's
  regression, in the review's order - the hold refused, the new bridge published, the session asked
  for, a follow while `POST /sessions` is out - failed with the follow taking the session's bridge
  down while the call was out, and the bridge no hold can be had on was handed over; the two order
  pins passed, as guards, and are red under ZF4 and ZF5. The case of a bridge read as its service is
  taken down, read again under the second hold, was written with the fix, and is red without its
  reading again (ZF3) and without the fix (ZF0). The fake backend runs a hook while `POST /sessions`
  is out (`DuringCreate`).
- **Mutations**: as before - each taken out once, by one exact replacement or the move named, the
  tree rebuilt, `DeferredRestartTests`, `ReviewHostTests`, `RemodelHostTests`,
  `EngineeringContextHostTests` and `ToolServiceWiringTests` run (985 cases), and the file restored
  byte for byte (checked by its sha256): 6 mutations, 14 red results, every one red.

  | Id | Where | Taken out | Red |
  |---|---|---|---|
  | ZF0 | `CreateReviewSession` | C1's fix whole: the hold and the bridge as at `41f2a88` | 3: C1's three cases |
  | ZF1 | `HoldForTheBridge` | the hold not asked for again when a bridge is published | 3: the session refused rather than held, the bridge read as its service went down refused, and the hold asked for once |
  | ZF2 | `CreateReviewSession` | a bridge published with still no hold handed over | 1: the bridge no hold can be had on |
  | ZF3 | `HoldForTheBridge` | the bridge not read again under the second hold | 1: the bridge read as its service is taken down |
  | ZF4 | `CreateReviewSession` | MR1: the settings in force read where the start under way is, and it where they are | 5: the MR1 pin, N3's, T225's two of a start under way, and 153A's Recheck posting no `checking` |
  | ZF5 | `CreateReviewSession` | P1: the start under way read after the run root and the folder under it | 1: N3's |
- **Evidence** (2026-10-21, at `fdfa378`): the C# build, `--no-incremental`, at zero warnings once
  every mutation was restored; `SwReview.Extractor.Tests` 10,086 passed and `SwReview.AddIn.Tests`
  3,540, from 3,535 - T227's five; the restart and tool-service classes, 1,060 cases, five times in
  a row. One full run met `ConPtyTests.ACmdChildsOutputReachesThePage` with only the console's
  opening codes read before the child's output - a Terminal-tab case nothing here touches, a timing
  of the pseudo-console - which passed when run five times again and in a full run after. The full
  `pytest -m "not live"` suite: 18,111 passed and 5 skipped on 3.12, and 18,111 passed and 5 skipped
  on 3.11 (`--isolated`, every extra). No broken link, and every changed file `i/lf`.

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
    the moment is over long before an extraction is. `KeysToMask` added the key of a start under way -
    only while it was under way, the fourth review found (S1, below).
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
    that waited, and the mark covered that only while the restart was under way: its failure, told
    once it was over, named its key unmasked (the fourth review, S1). Two guards pin the `init` read
    during either restart; they passed before the change.
  - The page is unchanged: the word it held is no longer said.
  - Existing cases changed deliberately: none. `MakeASession`'s first three asks moved into
    `AskForASession`, which the new cases use to expect a refusal, and the test world's backend can
    hold a start once it has published the backend's endpoint (`Published`).
- **Fourth review** (2026-10-21): a focused review of the third fix at `2ca804a` found no must-fix -
  the fix closes R1 for every start under way - and the items below, settled test first by T186 to
  T188:
  - A start's failure was told with the key it was made with unmasked, once a save made while it was
    under way had replaced the saved key (S1, a leak older than 153A, which the third review's words
    overstated). `StartWith` took the mark off before anyone told the failure: a restart that waited
    tells it in its `status` and its word to every other tab, and the add-in tells the first start's in
    its `status` and in `addin.log` (`SwReviewAddIn.StartBackend`, `Report`), each masked with the saved
    key - by then the save's - and the one recorded, neither of them the failed start's. The reviewer's
    probes showed it for a restart that waited (P1) and for the first start after a failed save (P2),
    at `2ca804a` and at `4c604e2`. Every key a start has been made with is now kept, each once, from
    just before the start (`ReviewHost._keysStarted`, an array replaced whole under the restart lock and
    never changed), and `KeysToMask` masks every one besides the saved key and the one recorded;
    `_starting` serves the `init` and the session alone. One place for the last start's key would not
    do: the save that waits for the first start makes its own restart as soon as the first start lets
    the lock go, which can be before the add-in, on the first start's thread, tells the failure - a
    case lets that restart begin first (mutation F3). A key no backend holds any more stays masked for
    the life of the host, which hides nothing a page needs.
  - Nothing pinned the restart's half of the mark (S2): the reviewer's mutant, marking the first start
    alone (MF), passed every case. A guard now holds a restart that waited under way while a save
    replaces the key, and asks that the restart's key be among the keys masked; with S1 that reads the
    keys kept, and MF (mutation F4) is red there and in the case of that restart's failure.
  - A recheck refused while a start was under way had posted `checking` first, and nothing after the
    refusal took that word off the badge (N5). The start under way is read before a recheck's
    `checking` status now - and, for every session, still before the settings in force.
  - The contracts said no session is made "between publishing the endpoint and recording" (N6); the
    host refuses one for the whole of the start, and they say "while a start of the backend is under
    way".
  - The reading orders the review named (N3): MR3, whether the saved settings are in force read with
    the start under way before the endpoint, is pinned - a case begins the first start, and has it
    publish its endpoint, inside the `init`'s reading of that endpoint, through the test world's
    backend (`EndpointRead`), and mutation F6 is red there. MR1 and MR2 are recorded under Not changed.
  - Existing cases changed deliberately: the check the first-start cases end with,
    `AssertTheBackendAndTheSettingsInForceAgree`, asked that the keys masked be the backend's key
    alone; they are that key and every key a start was made with now (S1), and it asks for exactly
    those, from the keys the test world's backend was asked to start with (`KeysAsked`), without
    printing them. Three cases went red against `2ca804a` for that check alone.
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
  - Two more reading orders no case pins (the fourth review, N3): `CreateReviewSession` reads the start
    under way before the settings in force (MR1), and nothing is called between the two readings, so
    no case can hold a start there; and `KeysToMask` read the mark after the record (MR2), which S1
    made moot, since the keys masked now read the keys kept, which only grow. MR3 is pinned (Fourth
    review, above).
    *Noted 2026-10-21 (152A, the merge of `main`, Not changed, and its final reviews, N2):* since
    the merge with 154A and 152A, the run root, the hold, the bridge question and the follow request
    are asked between the start under way and the settings in force, so a start can end there; MR1
    is pinned (152A's T227).
  - A start that begins after a session's check (the fourth review, N4): `CreateSession` reads the
    endpoint after `CreateReviewSession` has read the start under way and the settings in force, so a
    start that began between them would pair the settings recorded before it with the backend it
    started. In production only the first start can begin then, delayed, and only after a save started
    a backend that then died, followed by a later save whose restart failed before it stopped
    anything: practically unreachable. Two fixes are open to the owner: take the restart lock across
    that reading and `POST /sessions`, so that no start overlaps a session's making, at the cost of the
    page pump waiting through a start under way; or read the endpoint with the settings in force and
    have `CreateSession` post to that endpoint, refusing the session when it has changed - an
    `IBackendClient` change, which ten implementations would follow.
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

  For the fourth review: 7 mutations, the same way - the host's classes, 480 cases - 20 red results
  in all, every mutation red. F3 is the one place for the last start's key the review warned of, red
  where the waiting save's restart begins before the add-in tells the first start's failure; F4 is the
  reviewer's MF.

  | id | where | taken out | red |
  |---|---|---|---|
  | F1 | `ReviewHost.KeysToMask` | the keys masked leave out the keys starts were made with | 6 |
  | F2 | `ReviewHost.StartWith` | a start's key kept only once the start has succeeded | 5 |
  | F3 | `ReviewHost.StartWith` | one place for the last start's key, not every key | 4 |
  | F4 | `ReviewHost.StartWith`, `FirstStart` | only the first start keeps its key and is marked under way (MF) | 2 |
  | F5 | `ReviewHost.CreateReviewSession` | a recheck's `checking` posted before the start under way is read | 1 |
  | F6 | `ReviewHost.SettingsNotInForce` | the start under way read before the endpoint (MR3) | 1 |
  | F7 | `ReviewHost.KeysToMask` | the keys masked not each once | 1 |

- **Tests**: T166 and T168 in [tasks.md](tasks.md), each written first; the review's, T171, T173
  and T175; the second review's, T178 and T180; the third's, T183; and the fourth's, T186. 153A's
  tasks are T166 to T188: it lands first among this round's 002 decisions, so its numbers stand.

### 154A. A run root on a share or reached through a link is refused before anything is made (2026-10-20)

*Renumbered 2026-10-21:* this decision's tasks were numbered T166 to T177 provisionally, as 153A's were,
and are T189 to T200 since 153A's, T166 to T188, landed on `main` first; the commits that made them carry
their first numbers (`b722e0c` to `718061d`, T166 to T177).

- **Question**: decision 148A left two things about the run root for the owner (011
  [research.md](../011-drawing-context/research.md) R12.9, items 1 and 2). The backend's rule for a
  run folder (`resolve_run_dir`, `reviewer/src/swreview/chat/server.py`) refuses a UNC or device
  path on every route, by design - it writes only into a local folder - so under a run root on a
  share nothing could review, check or plan, and the refusal came deep in a run: after the run
  folder was made and the model extracted, as `InvalidRunDir` (146A's words). That includes the
  default run root, `Documents\SwReview\runs`, when Documents is redirected to a share. And the
  backend resolves the run folder it is sent (`Path.resolve()`), following a junction, a symbolic
  link, a substituted drive or a mapped network drive, while the host binds its own spelling of the
  folder, so under a run root reached through a link `remodel.open` refused the copy at step 4's
  comparison of run folders. The pilot's run root is neither.
- **Decision** (owner decision 154A, "3A", test first): "Run roots on a network share or reached
  through a link (011 `research.md` R12.9, items 1 and 2), test first: the settings and every run
  start refuse such a run root in plain words that name the way on, a local folder, instead of a
  refusal deep in a run; the backend's rule that it writes only into a local folder stays."

**1. One rule** (`Review/RunRootRule.cs`, which reads Windows through `Native/WindowsRunRootProbe.cs`).

- A run root is acceptable only when it is a local folder reached by its own path. The rule judges
  the root in its full form - `RunFolders.FullFormOf`, the form every run folder is made under
  (148A), made `internal` so that the root judged and the root used cannot differ - and answers
  `Accepted`, `Share`, `Link` or `DevicePath`, reading in this order, so that nothing is opened
  over the network or through a link:
  1. a full form written as a UNC path (`\\server\share`, `//server/share`, `\\?\UNC\...`) is
     `Share`, and one written as any other device path (`\\?\C:\...`, `\\.\...`) is `DevicePath`,
     on sight, as the backend refuses both; a root with no full form - a device path under the
     legacy path handling a host process may run with, a UNC path naming no share - is read as it
     is written;
  2. a mapped network drive is `Share`, by `GetDriveType` of its letter, which makes no connection;
  3. a substituted drive (`subst`) is `Link` - `Share` when it stands for a share - by
     `QueryDosDevice` of its letter, which answers `\??\` and the folder for one;
  4. each part of the path from the top, opened as itself (`FILE_FLAG_OPEN_REPARSE_POINT`) and
     never through it: a name-surrogate reparse point - a junction, a symbolic link, or a volume's
     mount point, which shares the junction's tag - is `Link`, and the walk stops at the first part
     that is not a folder;
  5. the final path of the deepest folder the walk reached (`GetFinalPathNameByHandle`, normalized,
     with its drive letter): one that differs from that folder's full path other than by letter
     case is `Link`, or `Share` when it is on a share.
- **The detection, and why.** The last step is the general rule. It is the reading the backend's
  own resolution makes: on Windows `Path.resolve()` is `ntpath.realpath`, which reads
  `GetFinalPathNameByHandle` of the path, or of its longest existing part and joins the rest - so
  the rule refuses exactly the roots the backend would spell otherwise than the host. It cannot
  stand alone: reading a final path opens the folder, which on a mapped network drive, or through a
  symbolic link to a share, goes over the network and can wait on a server that does not answer.
  So the drive's kind, its substitution and each part's own kind are read first, from Windows'
  record of the letter or the name, and a final path is read only of a local folder none of whose
  parts is a link. Only name surrogates are links: a OneDrive folder - Known Folder Move puts
  Documents, and with it the default run root, in one - can carry a cloud-file reparse point that
  names no other path, and refusing every reparse point would refuse it. Every path is opened in its
  `\\?\` form, which reaches past MAX_PATH whatever path handling SOLIDWORKS runs the add-in with.
  *Corrected on the reviews (N9; below):* the rule's own full form came from `Path.GetFullPath`,
  which under the legacy path handling refuses a root past MAX_PATH before anything is opened; the
  rule now makes its full path with `GetFullPathNameW` and judges such a root, but its run folders
  are still made through `Path.GetFullPath`, so under that handling the run folder is refused.
- **A root that does not exist yet** - the settings may name a folder the first run makes - is
  judged by its nearest existing folder: the walk stops at the first part that is not there, and
  that folder's final path is read, as the backend's resolution reads the longest existing part. A
  root not made yet below a junction is refused for the junction.
- **What the rule cannot read, it does not refuse**: a blank root, one with no full form, one on a
  drive letter that names no drive, a part that is a file or cannot be opened, a final path that
  cannot be read. The run folder is made under such a root, or reports why not, as before
  (`RunFolderFailed`); refusing them would answer a root that is wrong in some other way with words
  about shares and links. *Changed on the reviews (F2; below):* a part that cannot be opened, and a
  final path or a long-name form that cannot be read, leave the root unverified, refused in words that
  say it could not be checked, since such a part can hide a link; only a root no folder can be made
  under is left to the run folder.
- **The seam**: `IRunRootProbe`, four questions - the drive's kind, its substitution, a part's
  kind, a folder's final path - so the tests fake a share, a mapped drive and a substituted drive,
  which this machine cannot make without rights or side effects (a `subst` or `net use` letter is
  the whole logon session's, Explorer's included). A junction needs no rights, and the real tests
  make one under the temp folder with `mklink /J`; so are a long path, another letter case, an 8.3
  short name, and a reparse point that names no other path, set with a third-party tag.
- **Edge cases**, each decided and tested (`RunRootRuleTests`):

  | Case | Decided |
  |---|---|
  | Forward slashes, mixed separators, `.` and `..` segments | judged in the full form, the one the run folders are made under; `//server/share` is a share |
  | A drive's root (`C:\`) | judged as the drive: accepted on a local drive, `Link` on a substituted one, `Share` on a mapped one. The backend takes a run folder directly under a drive's root |
  | Another letter case | the same folder: the final path is compared ignoring case, and a real folder spelled upper and lower case is accepted |
  | A long path | judged past MAX_PATH through the `\\?\` form: a real local root longer than MAX_PATH is accepted, and a real junction past MAX_PATH is found. A root whose full form cannot be made - legacy path handling refuses a long one - is not judged, and the run folder reports it as before. *Corrected on the reviews (N9):* the full path is now made by `GetFullPathNameW`, so a long root is judged under either handling; under the legacy one its run folder is refused when made |
  | A root that does not exist | judged by its nearest existing folder |
  | One whose parent is a junction | refused for the junction, faked and real |
  | 8.3 short names | not a link: the full form expands them - `Path.GetFullPath` does under either path handling, measured with a probe program - so the final path matches, and a real folder spelled by the short name Windows gave it is accepted. *Corrected on the reviews (F3):* under the newer handling `Path.GetFullPath` leaves a short name followed by a folder not made yet as written, and such a root was refused as a link; the rule now reads each part as written and compares the final path with the long-name form, under either handling |
  | The default run root | judged as any root in force: on a mapped home drive it is `Share`, and with Documents redirected to a share it is written as one |
  | A device path (`\\?\C:\...`, `\\.\...`) | `DevicePath`, on sight: the backend refuses it on every route with a UNC path |
  | A drive letter that names no drive, a blank root, one with no full form, a part that is a file | not judged: left to the run folder |

**2. Where it refuses.**

- **The settings.** *Replaced the same day, before it landed, by the owner's follow-up (below): a
  field for runs in Settings, and no save refused for the run root.* `settings.save` carries no run
  root - the Settings panel has no field for one
  (`index.html:46` to `:100`, `saveSettings` at `app.js:2983`) - and a save writes a clone of the
  settings in force (`ReviewHost.cs:1171`, and `:1253` for the send box), run root included, which
  the add-in read from the settings file when it loaded (`ReviewHost.cs:431`, `SwReviewAddIn.cs:390`).
  So "a run root the rule refuses is not saved" is decided as: the one persist step both writers
  share, `PersistSettings` (015's 73A) - the Settings Save and the send box - refuses a save whose
  run root the rule refuses, whole: nothing is written, the backend is not restarted, the settings
  in force stand. The add-in never writes a refused root, so it never writes into the file a
  default the file never named - a Documents on a share - nor writes a refused root back over a
  local folder set by hand since it loaded. Weighed and not chosen: saving the page's fields and
  reporting the root beside them, which would write the refused root; and adding a run-root field
  to Settings, a feature the decision does not name, which would move the run root under every
  review, check and plan this session tracks. Both are put to the owner below.
- **Every run start, first** - before the document, the backend, a waiting settings restart, the
  gate, an earlier plan's session, the probe or anything else it asks:
  - on the Review tab (`ReviewHost`): `review.prepare`, which the add-in starts every review with;
    `review.start` - a review, a Retry, which reviews into a new run folder, and a context review's
    Retry; `review.recheck`, a restored waiting review's Send, which re-runs its checks in its own
    folder; `context.prepare`, which extracts into a run folder of its own; and `context.review`;
  - the Model check tab's `check.start`, the Standards tab's `standards.start`, and the Remodel
    tab's `remodel.plan` and `remodel.start`.
  - Each hands the backend a run folder under the run root - a new one, or one made under it
    before - so each is refused as a start is. The run root in force is read once per load, so a
    Recheck, `context.review` and Start meet a refused root only when the rule's answer changed
    since the folder was made - a folder of the root replaced by a link, a drive mapped - which the
    tests fake. (*Since the owner's follow-up* the run root in force also moves with a restart that
    brings in a folder chosen in Settings, which the rule accepted.)
  - Written once: `PaneActions.RefusedRunRoot` judges the root, sends the one refusal and says
    whether it did; each host calls it once per start, with its own words.
- **Not a run start, and not refused**: `context.selection`, which reads a selection against a
  package already made; Open copy, Discard copy and Stop, which act on a run already planned; and
  the searches of the run root - `init`'s newest check on the check tabs, `sessions.list`'s waiting
  review. The Extract tab makes no run folder and asks no backend: it writes into the folder its box
  names, the session's run folder - made under a root the rule accepted - or one the engineer
  chose. The Terminal tab, which would make a folder under the root, is hidden (151A) and its host
  not attached; recorded below.

**3. The words.** *Their way on, and the save's row, replaced the same day by the owner's follow-up
(below), before they landed: the way on is now the decision's example.*

- One class, `RunRootRefused`, not retryable: pressing again cannot help until the settings file
  names a local folder and SOLIDWORKS is restarted. The Review page shows a class's sentence first,
  and the class and the message behind the fold (feature 009 FR-026); the words file's sentence
  (`review_words_v1.yaml`) is true of every refusal that carries the class - the save, the send box
  and every start, whichever of the three the root is: "Runs are made only in a local folder reached
  by its own path, not on a network share or through a link, so nothing was saved or started. Set
  the run root in the add-in's settings file to a local folder, then restart SOLIDWORKS." It states
  the rule, not which of the three the root is; the message says which.
- The message (`RunRootRule.Refusal`), which the Model check, Standards and Remodel pages print
  whole: what the root is, the rule, what was not done, and the way on, ending with what to press.
  It opens "The run root is on a network share or a mapped network drive" (`Share`), "The run root
  is reached through a link, such as a junction, a symbolic link or a substituted drive" (`Link`) or
  "The run root is written as a Windows device path" (`DevicePath`), then ", and runs are made only
  in a local folder reached by its own path, so {not done}. Set the run root in the add-in's
  settings file to a local folder, then restart SOLIDWORKS and {way on}.":

  | Where | Not done | Way on |
  |---|---|---|
  | The Review tab's starts | nothing was started | try again |
  | The settings save and the send box | the settings were not saved | try again |
  | Model check | nothing was checked | press Model check again |
  | Standards | nothing was checked | press Standards check again |
  | A plan | nothing was copied | press Remodel a copy again |
  | A Start | the plan was not applied | press Remodel a copy again |

- No path: the run root can name a server, a share or a user, and the engineer knows where it is.
- The way on, decided against the decision's example ("Choose a local folder for runs in Settings,
  then try again"): the Settings panel has no run-root field, so "in Settings" would send the
  engineer to a panel with nothing to change, and "try again" with no restart meets the same
  refusal, since the add-in reads the settings file once, when it loads. So the words name the file
  and a restart. With a field in Settings (owner question 1) they would be the example's.
- The pane fixtures that carry the labels were regenerated by their generators, never by hand -
  `review-big-assembly.json`, `review-waiting.json`, `review-waiting-big-assembly.json` and
  `review-waiting-restored.json`, each differing in the one line, and `review-not-sent-session.json`
  unchanged - and `review-send-failure-events.json`'s pin of `review-waiting.json` (its bytes as
  written on Windows, CRLF) moved. `review-waiting-apply-failure.json`, a capture with no generator,
  keeps its labels as captured, as 147A left it.
- The Review page is unchanged: its error card, its Save line and the send box's line show the
  class's sentence; with no labels - an older backend - the Save line prints "RunRootRefused: " and
  the message, as it prints every class but `TurnRunning` and `BackendNotRestarted`.

**4. The backend's rule stays.** `resolve_run_dir` and `InvalidRunDir` are unchanged; the add-in
refuses such a root before any request carries one. The backend reads a run folder's text alone for
a UNC path, so a run folder on a mapped network drive passed its rule and was written over the
network; the add-in now refuses that root.

- **Evidence** (at `bd07f29`):
  - The backend's rule: `server.py:529` refuses a UNC or device path's text, `:533` and `:534`
    resolve the run folder and the run root; `remodel.py:369` builds the copy's path from the
    resolved folder; the bridge compares its folder with the host's at `BridgeDispatcher.cs:1047`.
  - The run starts made their folder after the document, the backend and a waiting restart:
    `ReviewHost.cs:2203` (`BackendReady`) before `:2224` (`CreateForDocument`); `:1985` for context
    evidence; `ModelCheckHost.cs:238`, `StandardsHost.cs:276`; and `RemodelHost.cs:1116` (the gate),
    `:1145` (an earlier plan's session ended), `:1153` (the probe) before `:1169`.
  - The settings: `UserSettings.cs:163` and `:401` (the default, under Documents); one load per
    add-in load (`ReviewHost.cs:431`, `SwReviewAddIn.cs:390`); a save writes the clone
    (`ReviewHost.cs:1171`, `:1253`, `:1265`).
  - Measured with a probe program on this machine, under both path handlings: `Path.GetFullPath`
    expands an 8.3 name, with or without a missing tail (*corrected on the reviews, F3:* not under
    the newer handling for a short name followed by a folder not made yet - `...\LONGFO~1\new` kept
    as written three times out of three, measured 2026-10-20 - and not the same way on every call);
    keeps `\\?\` and `\\.\` paths under the
    new path handling and refuses them under the legacy one; makes the full form of a long path
    only under the new; a junction's tag is `0xA0000003`; `GetDriveType` answers 3 for a local disk
    and 1 for a missing letter; `QueryDosDevice` answers `\Device\HarddiskVolume4` for `C:`.
- **Tests**: T189 and T191 in [tasks.md](tasks.md), each written first. Against the API alone - the
  rule answering `Accepted` and its words empty, the probe answering local folders reached by their
  own paths - 43 of the rule's 58 cases failed; the other 15 are guards, which pass before and after
  (a final path differing only by letter case or a trailing separator, three; one that cannot be
  read; a root the rule cannot read, five; the temp folder and a folder not made yet; a real root in
  other letter case or by its 8.3 name; and four `QueryDosDevice` answers that name no
  substitution). A 59th, a real reparse point with and without the surrogate bit, was added when
  mutation P5 survived the first pass (Mutations, below), and fails with it. Against
  `PaneActions.RefusedRunRoot` answering `false`, 25 of the hosts' 26 new
  and changed cases failed; `ASaveOfSettingsWhoseRunRootTheRuleAcceptsIsSavedAsBefore` is a guard.
  `ErrorLabelsCoverTheHostTests.TheScanFindsTheClassesTheHostAndThePageMake`'s expected list gains
  `RunRootRefused`, changed deliberately: the host now makes it; and
  `EveryClassTheReviewTabCanShowHasASentenceInTheWordsFile`, unchanged, was red while the class had
  no sentence. `test_review_words.py` pins the sentence, red against the old words file; the six
  pane fixture tests red once the words file changed passed once the fixtures were regenerated, and
  the three `ReviewPageSendGateTests` cases that read the pin failed with it left on the old file.
- **Gates**: 2026-10-20, at `70b38d8`: C# 0 warnings on a `--no-incremental` build, `SwReview.Extractor.Tests`
  10,059 and `SwReview.AddIn.Tests` 3,087 passed, from 10,059 and 3,003 at `bd07f29`; Python 3.12
  18,090 passed and 5 skipped, from 18,089 and 5; Python 3.11 (`uv run --isolated --python 3.11`)
  18,090 passed and 5 skipped, from 18,089 and 5, measured on a local clone of `bd07f29` - an
  export of it, which is not a repository, fails the tests that read the repository's history;
  `ruff check` clean; no broken link. `b722e0c` builds alone with zero warnings, and its rule and
  run-folder tests pass.
- **Not changed**, put to the owner (the first answer's items on a run-root field, on the save refused
  whole, on `InvalidRunDir`'s and `RunFolderFailed`'s "the run root in Settings" and on the words not
  naming the settings file are settled by the owner's follow-up, below, and dropped):
  1. A volume's mount point among the root's parts is refused, though the backend spells a folder on
     a volume with no drive letter the same: the walk reads the tag, which a mount point shares with
     a junction. Telling them apart reads the reparse point's target.
  2. The searches of a refused root - the check tabs' newest check, at every `init`, and the waiting
     review, at every `sessions.list` - still enumerate it, and on a share whose server does not
     answer they wait on the network as before.
  3. The Terminal tab, hidden, makes its run folder under the root unjudged; were it shown again,
     its start would want the rule.
  4. What the rule cannot read, it does not refuse: a part that cannot be opened, a final path that
     cannot be read, a drive letter naming no drive - a mapped drive not connected may read so.
     *Settled on the reviews (F2)* but for the drive letter naming no drive, still left to the run folder.
  5. The add-in reads the settings file once, when it loads, and a save writes the settings in force
     over a hand edit made since; older than 154A.
  6. The rule judges the root when a start begins. A root that becomes a share or a link between
     that and the backend's reading - a drive mapped, a folder replaced by a junction, in seconds -
     meets the backend's rule, and the refusal deep in a run, as before.
- **Mutations**: each fix taken out once with one exact replacement - two for the order mutants - the
  tree rebuilt, the named cases run and the file restored byte for byte (checked by sha256).
  36 of 38 mutations of the add-in's own code turned at least one case red, 167 red results in all;
  the two that did not are below the table. Of the words file, two mutations, 14 Python red results
  and 1 C#; and of the pin, one, 3 red:

  | id | where | taken out | red |
  |---|---|---|---|
  | R1 | `RunRootRule` | the share or device naming | 12 |
  | R2 | `RunRootRule` | a mapped network drive refused | 4 |
  | R3 | `RunRootRule` | a substituted drive refused | 7 |
  | R4 | `RunRootRule` | a link among the parts refused | 5 |
  | R5 | `RunRootRule` | the final path read | 10 |
  | R6 | `RunRootRule` | the final path compared ignoring case | 3 |
  | R7 | `RunRootRule` | the walk stopped at the first part not there | 2 |
  | R8 | `RunRootRule` | a final path on a share read as a share | 1 |
  | R9 | `RunRootRule` | a device path read as one, not as a share | 4 |
  | R10 | `RunRootRule` | the root judged in its full form | 9 |
  | R11 | `RunRootRule` | a drive substituted for a share read as a share | 1 |
  | R12 | `RunRootRule.Refusal` | the share's words | 1 |
  | R13 | `RunRootRule.Refusal` | the way on | 3 |
  | P1 | `WindowsRunRootProbe` | the device prefix taken off a final path | 5 |
  | P2 | `WindowsRunRootProbe` | a part opened as itself, not through its link | 2 |
  | P3 | `WindowsRunRootProbe` | every path opened in its `\\?\` form | 0, below |
  | P4 | `WindowsRunRootProbe` | a share's substitution read as a share | 1 |
  | P5 | `WindowsRunRootProbe` | only a name surrogate a link | 1 |
  | P6 | `WindowsRunRootProbe` | a network drive read as one | 0, below |
  | P7 | `WindowsRunRootProbe` | a missing drive read as one | 1 |
  | P8 | `WindowsRunRootProbe` | the substitution in force read, not one after it | 3 |
  | H1 | `ReviewHost.StartReview` | a review's and a Retry's judgement | 6 |
  | H2 | `ReviewHost.PrepareReview` | the preparation's judgement | 4 |
  | H3 | `ReviewHost.RecheckReview` | a Recheck's judgement | 3 |
  | H4 | `ReviewHost.PrepareContext` | context evidence's judgement | 1 |
  | H5 | `ReviewHost.ReviewContext` | a context review's judgement | 1 |
  | H6 | `ReviewHost.PersistSettings` | the save's judgement | 4 |
  | H7 | `ModelCheckHost.StartCheck` | a Model check's judgement | 3 |
  | H8 | `StandardsHost.Start` | a Standards check's judgement | 3 |
  | H9 | `RemodelHost.Plan` | a plan's judgement | 3 |
  | H10 | `RemodelHost.Start` | a Start's judgement | 1 |
  | H11 | `PaneActions.RefusedRunRoot` | not retryable | 17 |
  | H12 | `ReviewHost.StartReview` | the judgement first, not once the backend is readied | 6 |
  | H13 | `RemodelHost.Plan` | the judgement first, not once the plan holds the gate | 3 |
  | H14 | `ReviewHost` | the Review tab's words, "nothing was started" | 8 |
  | H15 | `ReviewHost.PersistSettings` | the save's words, "the settings were not saved" | 3 |
  | H16 | `RemodelHost.Start` | a Start's words, "the plan was not applied" | 1 |
  | H17 | `PaneActions.RefusedRunRoot` | the class, `RunRootRefused` | 25 |
  | W1 | `review_words_v1.yaml` | the class's sentence | 7 Python, 1 C# |
  | W2 | `review_words_v1.yaml` | the sentence's way on | 7 Python |
  | F1 | `review-send-failure-events.json` | the pin moved to the regenerated fixture | 3 |

  H6 and H15 took out the first answer's save refusal and its words, which the owner's follow-up
  removed; they are kept as they were run. P3 and P6 are equivalent here, and recorded rather than
  dropped. *Corrected on the reviews (F4):* P6 was not equivalent but untestable through the real API;
  the reading is now a table of its own, pinned answer by answer, and its successor, P9, is red. P3: the test host,
  `testhost.net48.exe`, declares itself long-path aware and this machine has long paths enabled
  (`LongPathsEnabled` is 1), so here `CreateFileW` reaches past MAX_PATH with or without the `\\?\`
  form, and the real long-path case passes either way. `SLDWORKS.exe` declares no such thing, so in
  SOLIDWORKS the form is what reaches past it; no test in this host can tell the two apart. P6: no
  test here can map a network drive without rights, or without a letter the whole logon session
  sees; the faked mapped drive covers the rule's answer to one, and the real probe's reading of a
  local drive and of a missing letter is pinned. P5 survived the first pass, and the real reparse
  point case (`AReparsePointIsALinkOnlyWhenItNamesAnotherPath`, a third-party tag with and without
  the surrogate bit, which needs no rights) was added for it; the rule's and the probe's mutations
  were run again with it.

#### The owner's follow-up: a field for runs in Settings, and no save refused for the run root (2026-10-20)

- **Question**: the settings' part of item 2 refused a save whole while the run root was refused, so no
  key, model or provider could be saved until the settings file was edited by hand and SOLIDWORKS
  restarted, which the first answer put to the owner.
- **Decision** (the owner's answer, 2026-10-20, "A Field + don't block"): "Add a run-root field to the
  Settings panel, checked by the same rule, so the way on becomes "choose a local folder in Settings".
  Save never refuses other settings because of the root. Every run start still refuses up front, as you
  built." It replaces the settings' part of item 2 and the way on in item 3, before either landed; the
  rule (item 1), the run starts (item 2) and the backend's rule (item 4) stand.

**What a change of run root meets** - read at `6861284`, before anything was built:

- The backend is bound to its run root when it starts: `swreview chat serve --run-root`, from the
  settings the add-in starts or restarts it with (`BackendClient.cs:237`, `BackendProcess.cs:548`).
  `resolve_run_dir` (`server.py:516` to `:537`) refuses a run folder outside it, and
  `GET /reviews/{run_id}` and `GET /checks/{check_id}` find a review or a check by name under it. So a
  running backend needs a restart for a new run root - which a save makes already: at once, or, through
  `DeferredRestart` (143A, 145A), once no turn or remodel run holds it back.
- Every tab read the run root from the settings saved: the Review host from `_settings`, and the Model
  check, Standards and Remodel hosts through `(_reviewHost?.Settings ?? UserSettings.Defaults()).RunRoot`
  (`SwReviewAddIn.cs:571`, `:685`, `:806`). A save replaces `_settings` before its restart, so between
  the two - a restart a turn or a remodel run holds back, or one that failed - `RunFolders` would make a
  check's or a review's folder under the new root, which the backend still running refuses
  (`InvalidRunDir`); and the check tabs' newest check (`CheckPaneHost`'s latest-run lookup), the waiting
  review (`RunFolders.FindNotSentReview`) and `PaneActions`' containment of `report.open` and
  `folder.open` would look under a root the backend does not.
- So the run root is now held twice, each named: the run root **saved**, `UserSettings.RunRoot`, which
  the field shows and a save writes; and the run root **in force**, `ReviewHost.RunRoot`, the one the
  backend was last started with - the settings' at the add-in's load, which the backend is started with,
  moved only when a restart the host makes succeeds (`ReviewHost.RestartBackend`, the one call every
  restart goes through, at once or deferred). Every tab makes its run folders, judges its starts, looks
  for its newest run and contains its paths under the run root in force: the Review host itself
  (`PaneActions`' root, `init.run_root`, the waiting review, `context.prepare`'s and `review.start`'s
  folders, every start's judgement), and the other three tabs through `SwReviewAddIn.RunRootInForce`,
  one named reading in place of three copies. A restart that waits, or fails, leaves the two apart, and
  the run root in force stands until one is made.

**1. The field.** "Folder for runs (run root)", in the Review tab's Settings under the Gemini Enterprise
fields, with a line saying it is a local folder on this computer, not a network share or a link, and that
blank is `Documents\SwReview\runs`. A plain text field, not a folder picker: the page cannot read the
file system - a WebView2 page under its own CSP, and no browser hands a page a folder's path - so a picker
would be a new page-to-host message and a folder dialog the host opens on the SOLIDWORKS UI thread,
plumbing the decision does not need. The field shows the run root saved, as every field shows what is
saved: showing the one in force while a restart waits would have the next save write it back over the
folder chosen. "(run root)" ties the field to the words that say run root - `InvalidRunDir`'s and
`RunFolderFailed`'s "Check the run root in Settings", which are true now, and were checked and kept.

**2. The save** (`ReviewHost.ChooseRunRoot`, after the payload's own refusals, before the write):

- `settings.save` carries `run_root`, the field trimmed. Absent, null or not text, the run root saved
  stays, as a page older than the field sends none. Trimmed, as every text field is; empty, it chooses
  the default, as a blank `run_root` in the file does (`UserSettings.cs:467`).
- A folder that differs from the run root saved - compared as written, ordinally - is judged by the
  rule. Accepted, it is written with the rest, and the save's restart brings it into force. Refused, it
  is the one field not written: every other field is, the backend is restarted with them, the run root
  stands, and the answer says so. The field then shows the run root saved, which the save did not change.
- Otherwise the run root saved is kept - the file's, or the default when it names none - and judged:
  when the rule refuses it the save still goes through, and its answer says every run is refused until
  the run root is changed. The whole-save refusal is gone, and `PersistSettings` is as it was before
  154A, so the send box saves as it always did.
- The answer: `settings.saved` carries `run_root_refusal {error_class: "RunRootRefused", message,
  retryable: false}` when there is anything to say, and nothing otherwise. A save whose restart fails is
  still a save (150A), answered `BackendNotRestarted`, and that error carries the same `run_root_refusal`,
  so what the save says of the run root is not lost with the restart. Both are built by
  `PaneActions.ErrorPayload`, which `SendError` now sends: one shape and one masking for an error and a
  note.
- The page shows it under the field, as the send box shows its error: the class's sentence, with the
  class and the message in a fold, or with no labels the message. The next save written takes it down
  when its answer carries none; a save refused before anything was written - a turn running, a setting
  refused - says nothing of the run root, and leaves the note as it was.

**3. The words.** Every run start's way on is now the decision's: "Choose a local folder for runs in
Settings, then" what to do there (`RunRootRule.Refusal`; "try again" on the Review tab, "press Model check
again" and the rest as before). The words file's sentence is "Runs are made only in a local folder
reached by its own path, not on a network share or through a link. Choose a local folder for runs in
Settings." - true of every start and of the note under the field alike, so it no longer says what was not
done; the message does. A save's two messages, with no path:

| Case | Message, for a root on a share (`Link` and `DevicePath` say what the root is as a run start's words do) |
|---|---|
| A folder chosen and refused (`RunRootRule.ChosenRefusal`) | "The folder chosen for runs is on a network share or a mapped network drive, and runs are made only in a local folder reached by its own path, so the run root was not changed; the other settings were saved. Choose a local folder for runs, then save again." |
| The run root kept and refused (`RunRootRule.KeptRefusal`) | "The run root is on a network share or a mapped network drive, and runs are made only in a local folder reached by its own path, so every run is refused until it is changed; the settings were saved. Choose a local folder for runs, then save again." |

The fixtures were regenerated by their generators again - the same four files, each in the one line,
`review-not-sent-session.json` unchanged - and `review-send-failure-events.json`'s pin moved to the new
`review-waiting.json` (`f3237bad...`, its bytes as written on Windows, CRLF);
`review-waiting-apply-failure.json`, captured, keeps its labels as captured.

- **Tests**: T194 in [tasks.md](tasks.md), written first and run against stubs - `ReviewHost.RunRoot`
  reading the settings saved, `ChosenRefusal` and `KeptRefusal` empty, the save ignoring `run_root`, no
  field on the page, the add-in's tabs reading the settings saved: 30 of the first 32 cases failed, and
  the 4 written next for a save whose restart fails, and for a save refused before anything was written,
  failed too. The two that passed are a guard, `ASaveOfSettingsWhoseRunRootTheRuleAcceptsIsSavedAsBefore`,
  and `AReviewIsMadeUnderTheRunRootInForceNotUnderOneChosenWhoseRestartFailed`, which the stub's save
  passed by ignoring the folder chosen, and which mutations H7, H9 and H10 turn red. `RunRootWiringTests`
  was rewritten, after it was seen red, to the one named reading the implementation chose
  (`TheRunRootInForceIsTheReviewHosts` is red under A2). A 38th case,
  `WhileAFolderChosenWaitsAReviewStartJudgesTheRunRootInForceAndInitNamesIt`, was added when mutations H16
  and H17 survived the first pass (Mutations, below), and fails with each. Changed deliberately: T191's
  two save tests, `ASaveOfSettingsWhoseRunRootTheRuleRefusesIsNotSaved` and
  `ADefaultRunRootTheRuleRefusesIsNotWrittenIntoAFileThatNamesNone`, replaced by
  `ASaveUnderARefusedRunRootSavesEverySettingAndSaysTheRunRootIsRefused` and
  `ASaveUnderARefusedDefaultRunRootGoesThroughAndSaysSo`, since a save no longer refuses; the rule's
  words case, to the new way on; `ASaveOfSettingsWhoseRunRootTheRuleAcceptsIsSavedAsBefore`, which now
  also says its answer carries no note; `test_review_words.py`'s pin, to the new sentence; and
  `ErrorLabelsCoverTheHostTests`' scan, which reads an `ErrorPayload("<class>"` literal as it reads a
  `SendError(id, "<class>"` one - `BackendNotRestarted` is built that way now, and the scan, which lost
  it, failed until it read the new form: stronger, not looser.
- **Gates**: 2026-10-20, on the follow-up's tree: C# 0 warnings on a `--no-incremental` build,
  `SwReview.Extractor.Tests` 10,059 and `SwReview.AddIn.Tests` 3,116 passed, from 10,059 and 3,087 at
  `6861284` (38 cases new or changed, 4 of the first answer's replaced); Python, the touched files and
  the words, fixture and pin tests (`test_review_words.py`, `test_pane_fixture.py`,
  `test_pane_waiting_fixtures.py`, `test_replay_fixture_hygiene.py`, `test_support_mechanical.py`,
  `test_chat_server.py`), 443 passed on 3.12 and 443 on 3.11 (`uv run --isolated --python 3.11`);
  `ruff check` clean; no broken link. The full Python suites are run by the coordinator.
- **Not changed**, put to the owner:
  1. *Settled on the reviews (F6), but for the backend's lookups by name:* runs made under an earlier run
     root open still, and a run that would go on under one is refused up front. As first recorded:
     Runs made under the old run root stay where they are, and the pane reaches them no more by name:
     the backend finds a review or a check by name under the run root it was started with, so a review
     of this session made before the change cannot be restored (`UnknownReview`), and a Recheck of one
     sends the backend a folder outside its run root (`InvalidRunDir`); the check tabs' newest check
     and the waiting review are looked for under the new root; and `report.open` and `folder.open`
     refuse a folder outside it (`PathRefused`). The folders open by hand.
  2. *Settled on the reviews (F7):* the field refuses a relative folder; one in the settings file keeps
     working. As first recorded: A relative run root typed in the field is accepted, as one in the settings file was: the add-in
     makes its run folders under it resolved against SOLIDWORKS's working folder at each run, and the
     backend against the one it inherited when it started, so once SOLIDWORKS moves its own the backend
     refuses the run's folder (`InvalidRunDir`, whose sentence sends the engineer to the run root in
     Settings). Refusing a relative root is a rule the decision does not name.
  3. The field shows the run root saved, and `init.run_root` the one in force; they differ only while a
     save's restart waits, or after one failed, and the page shows no sign of it.
  4. The hidden Terminal tab makes its run folder under the run root read when the add-in loaded
     (`TaskPaneOptions.RunRoot`), neither saved nor in force, and unjudged (the first answer's item 3).
- **Mutations**: as for the first answer - each fix taken out once with one exact replacement, the tree
  rebuilt, the named cases run (the rule's, the page's, the wiring's, `PageMessageTests`, the follow-up's
  and the first answer's run-start cases: 153, and 154 once a case was added) and the file restored byte
  for byte (checked by sha256). All 32 mutations of the add-in's code and its page turned at least one case
  red, 94 red results in all - H16 and H17 only once the case for them was added. Of the words file, two
  mutations, 7 Python red results each and 1 C# for the first; and of the pin, one, 3 red:

  | id | where | taken out | red |
  |---|---|---|---|
  | M1 | `RunRootRule.Refusal` | the way on, a local folder chosen in Settings (the settings file and a restart put back) | 3 |
  | M2 | `RunRootRule.ChosenRefusal` | the folder chosen named as such, not as the run root | 3 |
  | M3 | `RunRootRule.ChosenRefusal` | the other settings said to be saved | 3 |
  | M4 | `RunRootRule.KeptRefusal` | the settings said to be saved | 3 |
  | H1 | `ReviewHost.ChooseRunRoot` | a folder chosen and accepted written | 4 |
  | H2 | `ReviewHost.ChooseRunRoot` | a folder chosen and refused not written | 4 |
  | H3 | `ReviewHost.ChooseRunRoot` | the run root kept judged | 5 |
  | H4 | `ReviewHost.ChooseRunRoot` | the run root sent back unchanged judged as kept, not as chosen | 3 |
  | H5 | `ReviewHost.ChosenRunRoot` | an empty field the default | 1 |
  | H6 | `ReviewHost.ChosenRunRoot` | the folder chosen trimmed | 2 |
  | H7 | `ReviewHost.RestartBackend` | the run root in force moved only once the restart is made | 4 |
  | H8 | `ReviewHost.RestartBackend` | the run root in force moved by a restart | 4 |
  | H9 | `ReviewHost.RunRoot` | the run root in force, not the one saved | 4 |
  | H10 | `ReviewHost.StartReview` | a review's folder made under the run root in force | 1 |
  | H11 | `ReviewHost.SendSettings` | `run_root_refusal` on `settings.saved` | 7 |
  | H12 | `ReviewHost.Save` | `run_root_refusal` on `BackendNotRestarted` | 2 |
  | H13 | `ReviewHost.AddRunRootRefusal` | the note's class, `RunRootRefused` | 8 |
  | H14 | `ReviewHost.AddRunRootRefusal` | the note not retryable | 8 |
  | H15 | `ReviewHost.PersistSettings` | the whole-save refusal's removal (the refusal put back) | 8 |
  | H16 | `ReviewHost.RunRootRefused` | a Review-tab start judging the run root in force, not the one saved | 1 |
  | H17 | `ReviewHost` `init` | `run_root` the run root in force, not the one saved | 1 |
  | A1 | `SwReviewAddIn` | the Model check tab on the run root in force | 2 |
  | A2 | `SwReviewAddIn.RunRootInForce` | the review host's run root in force, not its settings' | 1 |
  | G1 | `app.js` `saveSettings` | the folder sent as `run_root` | 1 |
  | G2 | `app.js` `saveSettings` | the folder sent trimmed | 1 |
  | G3 | `app.js` `renderSettings` | the field filled from the settings | 1 |
  | G4 | `app.js` `saveSettings` | a saved answer's note shown | 4 |
  | G5 | `app.js` `saveSettings` | a `BackendNotRestarted` answer's note shown | 1 |
  | G6 | `app.js` `asError` | an error's `run_root_refusal` kept | 1 |
  | G7 | `app.js` `showRunRootRefusal` | the note taken down by a save that carries none | 1 |
  | G8 | `app.js` `saveSettings` | the note left by a save refused before anything was written (taken down at every save) | 1 |
  | G9 | `app.js` `showRunRootRefusal` | the class's sentence first, not the message alone | 1 |
  | W1 | `review_words_v1.yaml` | the class's sentence | 7 Python, 1 C# |
  | W2 | `review_words_v1.yaml` | the way on, a local folder chosen in Settings (the settings file and a restart put back) | 7 Python |
  | F1 | `review-send-failure-events.json` | the pin moved to the regenerated fixture | 3 |

  H16 and H17 survived the first pass: no case started a review, or asked for `init`, while a folder
  chosen waited for its restart, so judging or naming the run root saved there went unseen.
  `WhileAFolderChosenWaitsAReviewStartJudgesTheRunRootInForceAndInitNamesIt` was added for them, and H7
  to H10, H16 and H17 were run again with it; their counts above are the second pass's, and H7's and H9's
  first were 3.

#### The reviews of 154A at `9f20e8e` (2026-10-20)

- **Question**: two independent reviews of the branch at `9f20e8e` - one by Opus, one by Codex - found no
  must-fix for the pilot, and seven findings and four nits to fix now (the coordinator's list, F1 to F7 and
  N8 to N11). One measured fact shapes several: the test host runs .NET's newer path handling (net48,
  `UseLegacyPathHandling=False`), while SOLIDWORKS almost certainly runs the add-in with the legacy one -
  there is no `SLDWORKS.exe.config` and no override - and `Path.GetFullPath` behaves differently in the two.
- **Decision** (the coordinator, for the owner, 2026-10-20): fix each, test first; for F6 and F7 the fix is
  decided (below); a Model check or Standards run whose extraction spans a save is left to the owner.

**F1. Nothing is read before the rule's checks.** `Path.GetFullPath` expands an 8.3 short name by reading
each folder of the path (`GetLongPathNameW`) under either handling, and the rule made its full form first:
`\\offline-server\share\RUNS~1` went over SMB before it was refused, and `C:\link\RUNS~1` was read through
the junction before the walk found it. The rule now reads, in order: the root's text - a UNC or device path
refused on sight; then its full path made from the text alone (`IRunRootProbe.FullPathOf`,
`GetFullPathNameW`, which reads nothing and leaves a short name as written - and names a share when a
relative root lies under a current folder on one); then the drive by its letter; then each part as itself;
and only then, when the final path is not the spelling, the long-name form (finding F3). A root written with
a character no folder can have is left to the run folder before any of it, as before. The guard is in two
halves: the fake probe records every question that reads the disk or the network and, apart, every full
path asked for, so a share with a short name is refused with nothing asked or made of it and a link above a
short name with nothing asked below it; and the rule's source is read for any reading of its own -
`System.IO`, `Path.Get`, `Directory.`, `File.`, `RunFolders.`, `GetLongPathName`, `GetFullPathName`,
`DllImport`, `CreateFile` - since what a call reads below the probe's questions cannot be seen in the
probe's record. `RunFolders.FullFormOf`, made `internal` for the rule, is `private` again.

**F2. A part that cannot be read leaves the root unverified.** `EntryOf` read a part whose open failed for
any reason but absence as `Other`, which ended the walk and accepted the folder above it; Windows lets every
user pass through a folder whose attributes are denied, so `C:\Restricted\link\runs` could hide a link to a
share below an unreadable `Restricted`. Now a missing part (`ERROR_FILE_NOT_FOUND`, `ERROR_PATH_NOT_FOUND`)
is told from one that cannot be read (`RunRootEntry.Unreadable`), and the rule answers
`RunRootVerdict.Unverified` for it - and for a final path or a needed long-name form that cannot be read -
and every start refuses it, `RunRootRefused`, in words that say so: "The run root could not be checked,
since a part of its path cannot be read, and runs are made only in a local folder reached by its own path,
so ..." with the way on. A save still saves every other setting, and the note under the field says so
(`ChosenRefusal`, `KeptRefusal`). Made for real without rights: a folder denied its own attributes and the
listing of the folder above it, with a junction below it - the probe reads it as unreadable, the junction
below as a link, and the root as unverified, where the first answer accepted it; the denials come off first
on dispose. A cloud file's folder whose filter does not answer - the third-party tag the tests set - is now
unverified too, since nothing through it opens; a OneDrive folder's filter answers.

**F3. An 8.3 short name followed by a folder not made yet is accepted.** Under the newer handling
`Path.GetFullPath` leaves such a short name as written (`...\LONGFO~1\new`, measured three times out of three
here; the reviewer saw another expand on a first call and not after), so its final path, in long names,
differed from its spelling and the root was refused as a link; the first answer's test passed only because
its short segment was not the immediate parent of the missing one. The probe now reads a folder's long-name
form (`LongPathOf`, `GetLongPathNameW` on the `\\?\` form), asked only once the walk has found no link and
only when the final path is not the spelling, and the final path is compared with it. The exact shape is
tested for real, three readings and one deeper, and the verdict no longer depends on the path handling: the
rule makes no full path through .NET at all. A long-name form that cannot be read - a folder above denies
its listing - leaves the root unverified.

**F4. The mapped-drive reading is pinned.** The `GetDriveType` mapping is a table of its own
(`WindowsRunRootProbe.DriveKindOf`), tested answer by answer: 4 a network drive, 1 no drive, every other a
local drive - `DRIVE_UNKNOWN` (0) among them, decided and recorded. The first answer called its mutant P6
"equivalent"; it was not, only untestable through the real API, and its successor P9 is red. The part's
reading became a table of its own too (`EntryKindOf`: what the open answered, and the attributes and
reparse tag when it opened), once mutation P12 showed that its attribute-failure branch, which no test can
make happen, was untested.

**F5. The three tabs' way on names the Review tab.** The Model check, Standards and Remodel pages print the
message whole and have no Settings, so their words say "Choose a local folder for runs in Settings on the
Review tab, then ..." (`RunRootRule.InSettingsOnTheReviewTab`, after 150A's `StartItAgainOnTheReviewTab`),
and the Review tab's own say "in Settings" (`RunRootRule.InSettings`); `RunRootRule.Refusal` and
`PaneActions.RefusedRunRoot` take where the Settings are.

**F6. A run root moved inside a session.** Opus showed that once a save moved the run root and its restart
succeeded, an earlier review's report and folder answered `PathRefused`, a Recheck sent the backend a folder
under the old root (`InvalidRunDir`), and `IsRemodelCopy` no longer knew a copy under the old root, so a plan
of one went on - 004's T173 guard broken. Decided and done:

- The review host keeps every run root in force this session (`ReviewHost.RunRootsInForce`: the one at the
  add-in's load and each a successful restart brings in, each once, replaced whole by the one restart made
  at a time), and the add-in hands it to the other three tabs (`SwReviewAddIn.RunRootsInForce`). The shared
  containment of `report.open` and `folder.open` (`PaneActions`, through `RunFolders.IsUnder`, now the one
  containment rule) and `RemodelHost.IsRemodelCopy` read every one of them.
- A run that would go on in a folder not under the run root in force is refused before the backend is
  asked, `RunRootChanged`, not retryable, with words that say so and the way on: a Recheck ("... so its
  checks were not run again. Press Review to review the model again."), a review with saved context
  ("... Extract the context evidence again."), a context review's Retry ("... so it was not retried."), a
  review whose run root moved while its evidence was extracted - a save made then restarts at once, no turn
  holding it back (*corrected on the reviews of the merge, N5:* no save is made then, the page's messages being
  handled one at a time; the add-in's first start, under way when the review began, can end then) ("the run
  root changed while the evidence was extracted ... Press Review again."), and a
  Start of a plan made under the old root ("... so the plan was not applied. Press Remodel a copy again.").
  The words file's sentence: "This run's folder is under a run root that is no longer in force, and runs go
  on only under the one in force. Start the run again."
- Left to the owner, recorded below: a Model check or a Standards run whose extraction spans the save.
  *Settled 2026-10-21 by owner decision 157A:* while a backend is up, a check holds the save's restart back until its
  evaluation has been answered (157A, below).

**F7. A relative folder typed in the field is not saved.** A folder chosen for runs must be written as a full
path - a drive letter and a separator, or two separators, which the rule then refuses as a share or a device
path (`RunRootRule.IsFullPath`); one that is not - relative, rooted on the current drive, or a drive letter
with no separator - is the one field not saved, with the note `RunRootNotFullPath`: "The folder chosen for
runs is not written as a full path, starting with its drive letter, so the run root was not changed; the
other settings were saved. Type the folder's full path, then save again." No path is echoed, and the rule is
not asked. A relative run root the settings file names keeps working as before. The words file's sentence:
"The folder for runs must be written as a full path, starting with its drive letter. Type the folder's full
path in Settings."

**N8. A start judges again a run root its gate moved.** A start judged the run root in force before a
waiting restart its gate could make, then made its folder under whatever was in force after it. Now each
start that can meet a restart judges again when the run root moved (`RunRootToUse`): a review and context
evidence once the backend is ready, before the folder is made; every review session before it is asked for -
a Recheck, a review with saved context, a context Retry, and a new review whose extraction spanned a save;
and a plan and a Start once the gate is passed.

**N9.** The probe's words, and the research's, no longer claim the rule reads past MAX_PATH "whatever path
handling" through its own reach alone: it does now, through `GetFullPathNameW`, but a run folder is made
through `Path.GetFullPath`, which under the legacy handling refuses a root past MAX_PATH first
(`RunFolderFailed`).

**N10, N11.** The four test summaries that still described the settings file and a restart describe the
Settings on the Review tab; the test worlds that did not inject a probe now default to one that answers every
folder as local (`FakeRunRootProbe.Local()`), so a temp folder below a junction fails no test that is not
about the rule. The worlds changed: the review host's, the settings page's, the deferred restart's, the
engineering context's, the Model check's, the Standards', the Remodel host's and the end-to-end plan's.

- **Tests**: T197 in [tasks.md](tasks.md), written first against stubs - the rule's new API answering as
  the first answer did, the probe's new readings wrong on purpose (`FullPathOf` through `Path.GetFullPath`,
  no long-name form, every drive local), the hosts' new properties present and unread: 55 of the 238 cases
  then run failed. The guards that passed - a share with a short name refused with nothing asked, a link
  above a short name, a mapped drive with a short name, a final path that is not the long name either, the
  Review tab's own way on, and the drive table's local answers - pass before and after; the source guard
  catches what the fake's record cannot. The three tabs' word cases went red once the rule took where the
  Settings are, before the hosts did. Added once the implementation was in, each shown red by its mutation:
  the Remodel tab's open of an earlier run (H27), a Recheck judged again (H29), a run recorded in another
  letter case (RF1), a sibling whose name begins with the run root's (RF2), and the part-reading table, 10
  of its 12 cases red against a stub (P12). Changed deliberately: the
  final path that cannot be read, and the cloud file's folder, now unverified (F2); the way-on cases of the
  three tabs and the Review tab (F5); `RefusedKinds`, which gains "could not be checked", so every host's
  refusal case runs a fourth time; the summary that a moved run root refuses an open (F6); the reflection
  test of `CreateReviewSession`, which passes the run root judged and the words; the expected classes of the
  label scan, `RunRootChanged` and `RunRootNotFullPath`; and the words pins in `test_review_words.py`.
- **Gates**: 2026-10-20, on the reviews' tree: C# 0 warnings on a `--no-incremental` build,
  `SwReview.Extractor.Tests` 10,059 and `SwReview.AddIn.Tests` 3,204 passed, from 10,059 and 3,116 at
  `9f20e8e`; Python, the touched files and the words, fixture and pin tests (`test_review_words.py`,
  `test_pane_fixture.py`, `test_pane_waiting_fixtures.py`, `test_replay_fixture_hygiene.py`,
  `test_support_mechanical.py`, `test_chat_server.py`), 445 passed on 3.12 and 445 on 3.11
  (`uv run --isolated --python 3.11`); `ruff check` clean; no broken link. The full Python suites are run
  by the coordinator.
- **Mutations**: as for the first answer - each fix taken out once with one exact replacement, the tree
  rebuilt, the named cases run (the rule's, the probe's, the settings page's, the shared actions', the
  wiring's, the label scan's, the engineering context's, and every host's run-root cases: 324, and 336 once
  the part-reading table was added) and the file restored byte for byte (checked by sha256). 45 of the 46
  mutations of the add-in's code turned at least one case red, 131 red results in all; the one that did not
  is below the table. Of the words file, three mutations, 7 Python red results each and 1 C# for each of the
  two new sentences; and of the pin, one, 3 red:

  | id | where | taken out | red |
  |---|---|---|---|
  | Q1 | `RunRootRule.Judge` | a share or device path refused on its text, before its full path is made | 15 |
  | Q2 | `RunRootRule.Judge` | a full path on a share refused | 1 |
  | Q3 | `RunRootRule.Judge` | a root with a character no folder can have left to the run folder | 2 |
  | Q4 | `RunRootRule.Judge` | a part that cannot be read leaves the root unverified | 9 |
  | Q5 | `RunRootRule.Judge` | a final path that cannot be read leaves the root unverified | 1 |
  | Q6 | `RunRootRule.Judge` | the long-name form read | 4 |
  | Q7 | `RunRootRule.Judge` | a long-name form that cannot be read leaves the root unverified | 1 |
  | Q8 | `RunRootRule.Judge` | the long-name form read only when the final path is not the spelling | 8 |
  | Q9 | `RunRootRule.Judge` | a final path on a share read as a share before the long name | 1 |
  | Q10 | `RunRootRule.Kind` | the words for a root that could not be checked | 3 |
  | Q11 | `RunRootRule.Refusal` | the way on from where the page is | 4 |
  | Q12 | `RunRootRule.IsFullPath` | a drive letter followed by a separator | 3 |
  | Q13 | `RunRootRule.IsFullPath` | two separators, not one | 3 |
  | Q14 | `RunRootRule.NotFullPathRefusal` | the words for a folder not written in full | 1 |
  | P9 | `WindowsRunRootProbe.DriveKindOf` | a remote drive's answer, 4 | 2 |
  | P10 | `WindowsRunRootProbe.DriveKindOf` | a missing root's answer, 1 | 3 |
  | P11 | `WindowsRunRootProbe.EntryKindOf` | an open failing but for absence read as unreadable | 4 |
  | P12 | `WindowsRunRootProbe.EntryKindOf` | attributes that cannot be read read as unreadable | 1 |
  | P13 | `WindowsRunRootProbe.FullPathOf` | the full path made from the text alone | 1 |
  | P14 | `WindowsRunRootProbe.LongPathOf` | the long-name form read in its `\\?\` form | 0, below |
  | P15 | `WindowsRunRootProbe.LongPathOf` | the device prefix taken off the long-name form | 3 |
  | H18 | `ModelCheckHost.StartCheck` | the way on names the Review tab's Settings | 4 |
  | H19 | `StandardsHost.Start` | the way on names the Review tab's Settings | 4 |
  | H20 | `RemodelHost.RunRootRefused` | the way on names the Review tab's Settings | 7 |
  | H21 | `ReviewHost.RestartBackend` | a run root a restart brings in joins those in force | 1 |
  | H22 | `PaneActions` | every run root in force contains a run that opens | 5 |
  | H23 | `CheckPaneHost` | the check tabs' run roots handed to their actions | 2 |
  | H24 | `ModelCheckHost` | the run roots handed to the check pane | 1 |
  | H25 | `StandardsHost` | the run roots handed to the check pane | 1 |
  | H26 | `RemodelHost.IsRemodelCopy` | every run root in force read for a copy | 1 |
  | H27 | `RemodelHost` | the run roots handed to its actions | 1 |
  | H28 | `ReviewHost.CreateReviewSession` | the run's folder held to the run root in force | 4 |
  | H29 | `ReviewHost.CreateReviewSession` | a moved run root judged again before the session | 1 |
  | H30 | `ReviewHost.StartReview` | a moved run root judged again before the folder | 1 |
  | H31 | `ReviewHost.PrepareContext` | a moved run root judged again before the folder | 1 |
  | H32 | `RemodelHost.Plan` | a moved run root judged again after the gate | 1 |
  | H33 | `RemodelHost.Start` | a moved run root judged again after the gate | 1 |
  | H34 | `RemodelHost.Start` | the plan's folder held to the run root in force | 1 |
  | H35 | `ReviewHost.ChooseRunRoot` | a folder chosen written as a full path | 4 |
  | H36 | `ReviewHost.ChooseRunRoot` | the note's class, `RunRootNotFullPath` | 5 |
  | H37 | `ReviewHost.CreateReviewSession` | the class, `RunRootChanged` | 5 |
  | H38 | `ReviewHost.CreateReviewSession` | not retryable | 2 |
  | A3 | `SwReviewAddIn` | the Model check tab handed every run root in force | 1 |
  | A4 | `SwReviewAddIn.RunRootsInForce` | the review host's run roots in force | 1 |
  | RF1 | `RunFolders.IsUnder` | letter case ignored | 3 |
  | RF2 | `RunFolders.IsUnder` | a separator after the run root | 3 |
  | W3 | `review_words_v1.yaml` | `RunRootRefused`'s sentence true of a root that could not be checked | 7 Python |
  | W4 | `review_words_v1.yaml` | `RunRootChanged`'s sentence | 7 Python, 1 C# |
  | W5 | `review_words_v1.yaml` | `RunRootNotFullPath`'s sentence | 7 Python, 1 C# |
  | F2 | `review-send-failure-events.json` | the pin moved to the regenerated fixture | 3 |

  P14 is equivalent here, as P3 is: the test host declares itself long-path aware and long paths are
  enabled on this machine, so `GetLongPathNameW` reaches past MAX_PATH with or without the `\\?\` form, and
  no test in this host can tell the two apart; in SOLIDWORKS, which declares no such thing, the form is what
  reaches past it. P12 survived its first pass - the attributes failing to read on a handle opened to read
  them is one no test can make happen - and, as F4 did for the drive, the part's reading became a table of
  its own (`EntryKindOf`), pinned answer by answer; P11 and P12 were run again against it, and their counts
  above are the second pass's (P11's first was 1).
- **Not changed**, put to the owner:
  1. A Model check or a Standards run whose extraction spans a save: its folder is under the old run root,
     and the page's `POST /checks/...` reaches the restarted backend and is refused after minutes of
     extraction. Whether a check run holds the restart back, as decision 145A made a remodel run, is the
     owner's to say. *Settled 2026-10-21 by owner decision 157A* ("1A"): it does while a backend is up, from its
     gate until the page's evaluation of it has been answered, so a save made during the extraction restarts the
     backend only once the evaluation is over; the reading of the run root after the extraction now guards only the
     starts that bring a backend up where there was none - a save's made with no backend up, or the add-in's first
     start - which nothing holds back (157A, below).
  2. A prepared context, and a plan waiting for Start, across a run-root change: each is refused when it is
     used - `context.review` and `remodel.start` answer `RunRootChanged` - and the engineer extracts or plans
     again; the plan's bridge session is ended by the next plan, as before.
  3. A run root spelled with an 8.3 short name is accepted now, but its run folders are made through
     `Path.GetFullPath`, which under the newer handling can keep the short name, while the backend's
     resolution spells them in long names: the re-modeler's comparison of run folders at the copy's open
     (step 4) can refuse such a copy, as it did a root through a link (011 [research.md](../011-drawing-context/research.md)
     R12.9 item 2, corrected). Making `RunFolders` spell a run folder in long names would close it.
  4. `GetDriveType`'s "cannot be determined" (0) is read as a local drive, whose parts are then read one by
     one.
  5. A run root past MAX_PATH is judged, but under the legacy path handling its run folder is refused when
     made (N9).
  6. Every run root in force this session stays the pane's to open until SOLIDWORKS closes, the rule not
     asked of it again.
- **Later**, once 153A is on `main`: the run root in force is to become 153A's record of the settings the
  running backend was started with (`_inForce.RunRoot`), `RestartBackend` and this branch's own record to
  go, the run root to join 153A's `SameBackendSettings`, and the delayed first start that could replace a
  newer root (Codex's third finding) to be shown closed by 153A's `FirstStart`, with a test - and these tasks
  renumbered after 153A's T188. Done on 2026-10-21: the renumbering, T189 to T200, and the rest below (the merge
  of `main`, T201 to T203).

#### The merge of `main`, and the run root in force as 153A's record's (2026-10-21)

- **Question**: 153A landed on `main` first (pull request #28, with 155A's #29 and 156A's #27), and its record of
  the settings the backend that is up was started with is what this decision's run root in force had been kept
  apart from until then (the "Later" item above). The coordinator asked, for the owner: `main` merged into this
  branch, never rebased; the run root in force folded into 153A's record, its own record and `RestartBackend`
  gone, the run root among 153A's `SameBackendSettings` with a sentence true of it, every reader kept on the
  merged record; Codex's third finding shown closed by 153A's `FirstStart`, with a test; a start under way
  checked for a run start that could mix run roots, and pinned if one could; and these tasks renumbered after
  153A's, each in a commit of its own.
- **Decision** (the coordinator, for the owner, 2026-10-21): as asked, the unification test first. One order
  changed: merged first, `tasks.md` defined T166 to T177 twice - 153A's and these - which
  `test_every_tasks_list_defines_each_task_id_once` refuses, so the merge was undone, the renumbering committed
  (`c179f42`) and `main` merged after it (`6d7cb0a`): no commit on the branch defines an id twice.

**The merge** (`6d7cb0a`): six files in conflict, each resolved keeping both sides' intent.

1. `ReviewHost.cs`: the fields and properties, this branch's run root in force and run roots in force beside
   153A's record, start under way, keys started with and readings' numbers; the save's restart, this branch's
   `RestartBackend` made through 153A's `RestartWith`, with 153A's comment on a failed restart and this branch's
   line on the run root's note; 153A's `FirstStart`, `RestartWith` and `StartWith` whole; and
   `CreateReviewSession`, 153A's refusal while a start is under way first, then this branch's run root judged again
   and the run's folder held to it - moved above a Recheck's `checking` status, as 153A moved its refusal, since
   nothing would take that status off after the refusal - then 153A's settings in force for the session.
2. `RemodelHostTests.cs`: 155A's channel for the test world beside this branch's run root spelling.
3. `contracts/pane-host-messages.md`: the `ready` and `settings.save` rows, 153A's amendments first and this
   branch's after them; `settings.save`'s payload `{..., gemini_enterprise, run_root?}`.
4. 004 `contracts/pane-remodel-messages.md`: `ready` from 155A, `remodel.plan` and `remodel.start` from this branch.
5. `research.md`: 153A's entry, then this one, then 156A's.
6. `tasks.md`: 153A's Phase 17, then this decision's Phase 18.

The words file merged clean: 153A changed no labels. Both pane fixture generators, run again, changed nothing, so
`review-send-failure-events.json`'s pin of `review-waiting.json` (`2f31946...`) stands, and
`review-waiting-apply-failure.json`, captured, is `main`'s.

**The unification** (T201 to T203).

- **The run root in force is 153A's record's** (`ReviewHost.RunRoot => _inForce.RunRoot`). The record of its own
  and `RestartBackend` are gone - a save's restart and one that waited are 153A's `RestartWith` again - so the run
  root in force moves exactly when the settings in force do, in `StartWith`: at the add-in's first start and at
  every restart that succeeds, and at nothing else. The merge showed what that changes: the first start was the
  one start that did not move it. A save whose restart failed with no backend up left the folder chosen saved, and
  the first start, made then with the settings saved by then (153A), started the backend under it, while every tab
  went on making its runs under the run root loaded, which that backend refuses.
- **The run roots in force**: the run root loaded, then each one a start brings in, appended by `StartWith` just
  before it records the settings in force, so the run root in force is always among them.
- **One rule for the same run root** (`ReviewHost.SameRunRoot`): as written, ignoring letter case, as Windows names
  a folder - for the run roots in force, for whether the run root saved is in force, and for whether a start under
  way moves it. Another spelling of one folder (a trailing separator, an 8.3 short name) counts as another run
  root: telling them apart would read the disk, which the restart's lock must not wait on.
- **The run root joins `SameBackendSettings`**, whose comment said it could not differ - no longer true since the
  follow-up's field. **The sentence: the run root's own words.** 153A's sentence speaks of reviews, while a run root
  not in force moves every tab's runs - the backend makes them only under the one it was started with - and the
  Settings panel's field shows the one saved; and a clause about the folder said when the folder saved is the one
  in force would be false. So no one sentence is true of both. While the run root saved is not the one in force,
  alone or with other settings, `init` and the status of a restart that waited and failed say 153A's sentence with
  where runs are made: "The saved settings are not in force yet: the review backend did not restart with them, so
  reviews run with the settings it was started with, and every tab makes its runs in the folder for runs it was
  started with, not the one saved. Save the settings again to retry the restart." Otherwise 153A's, word for word;
  both are built from one beginning (`NotInForceAsReviewsRun`). The page shows the host's sentence as it is.
- **Codex's third finding against 154A** - a delayed first start for the run root loaded, released after a save
  had restarted the backend with a folder chosen, would start a second backend under the old run root - is closed
  by 153A's `FirstStart`: it holds the restart's lock, reads the settings saved under it, and starts nothing when a
  restart has started the backend; and a save's restart waits for a first start under way, then brings its folder
  in. Pinned both ways, each start held by the fake backend while the other is asked for: the backend and the run
  root in force agree, on the folder chosen, whichever comes first.
- **A start under way** (`_starting`) publishes the backend's endpoint before it records its settings, and can
  still fail and leave the backend it would replace: while one that would bring another run root into force is
  under way, neither run root is the one the backend up makes runs under. `ReviewHost.RunRootForANewRun` answers
  none then, and the run root in force otherwise, the start under way read before the record, as 153A reads it. It
  can happen, and it was checked tab by tab:
  - The Review tab: no change. A review and context evidence take the run root once the backend is ready, which
    makes or waits for any settings restart, so the one start that can be under way then is the add-in's first; and
    a review session is refused while a start is under way (153A) and when its folder is not under the run root in
    force (F6). Pinned: a review whose folder was made while the first start brought another run root in is
    refused before any session - while the start is still under way, and once it has ended during the extraction,
    `RunRootChanged`, which before the unification went on in a folder that backend refuses.
  - The Model check and Standards tabs, which no restart waits for: the run root for a new run, read once. While it
    is none the start is refused first, `BackendUnavailable`, retryable, in the tab's words - "The review backend
    is being started with another folder for runs, so nothing was checked. Press Model check again in a moment."
    (`RunRootRule.MovingRefusal`, sent by `PaneActions.SendRunRootMoving`) - and the run root judged is the one the
    folder is made under and the one a failure names: it was read three times, so a restart ending between the
    readings could make a check's folder under a run root it never judged.
  - The Remodel tab: its gate holds back every settings restart but not the add-in's first start, so a plan and a
    Start take the run root for a new run once the gate is passed, read once, and are refused while it is none -
    "... so nothing was copied." and "... so the plan was not applied. Press Remodel a copy again in a moment." -
    the host left free and the plan startable.
- **Every reader on the merged record**: `init.run_root` on all four tabs and the other tabs' newest runs
  (`RunRoot`, `SwReviewAddIn.RunRootInForce`); the Review tab's starts, its re-judging once the backend is ready and
  its sessions' `RunRootChanged` refusals (`RunRoot` through `RunRootToUse`); the Model check, Standards and Remodel
  tabs' starts and the Remodel tab's re-judging after its gate (`RunRootForANewRun`, through
  `SwReviewAddIn.RunRootForANewRun`, one reading of the review host); and the containment of `report.open` and
  `folder.open` on every tab and `IsRemodelCopy` (`RunRootsInForce`).
- **Not changed**, put to the owner with the reviews' first item: a start begun just after a run start has read the
  run root is not seen, as one begun while the run is made is not (a Model check or Standards run whose extraction
  spans a save). And the run roots in force are appended before the record, an order no test can observe.
  *Narrowed 2026-10-21 by owner decision 157A:* no settings restart begins while a check holds it, so of the starts
  that can begin then only those that bring a backend up where there was none remain - a save's made with no backend
  up, or the add-in's first start (157A, below).

- **Tests**: T201, written first against stubs on the merged code - `RunRootForANewRun` answering the run root in
  force, `MovingRefusal` empty, the three hosts' option present and unread - 21 of the 26 new cases failed. The 5
  that passed pin what already held, each red under a mutation: Codex's third finding both ways (U2), the run root
  saved in another letter case twice (U3, U4), and a start under way that keeps the run root (U9). No existing case
  was changed; the Model check and Standards test worlds gained a moving run root and the run root for a new run.
- **Gates**: 2026-10-21: on the merge (`6d7cb0a`), no broken link, C# 0 warnings on a `--no-incremental` build,
  10,059 and 3,317 passed, and Python, the words, fixture, pin and tasks tests, 753 passed on 3.12 and on 3.11; on
  the unification, no broken link; C# 0 warnings on a `--no-incremental` build, 10,059 and 3,343 passed, from 10,059
  and 3,317; the restart classes (`DeferredRestartTests`, `OtherTabsBackendRestartTests`,
  `ReviewPageBackendRestartTests`, `TabPagesBackendRestartTests`, 335 cases) passed five times in a row; Python, the
  words, fixture, pin and labels tests and those that read `tasks.md`, 1,036 passed on 3.12 and 1,036 on 3.11
  (`--isolated`); `ruff check` clean; the pane fixtures regenerated by both generators unchanged, the pin standing;
  the full Python suites the coordinator's.
- **Mutations**: as before - each change taken out once with one exact replacement, the tree rebuilt, the named
  cases run (154A's run root cases, 153A's settings in force and first start, and the unification's: 457) and the
  file restored byte for byte (checked by sha256). Each of the 23 mutations turned at least one case red, 128
  red results in all.

  | id | where | taken out | red |
  |---|---|---|---|
  | U1 | `ReviewHost.RunRoot` | the run root in force read from 153A's record, not the settings saved | 20 |
  | U2 | `ReviewHost.StartWith` | the run root a start brings in joins those in force | 5 |
  | U3 | `ReviewHost`'s constructor | the run root loaded among those in force | 13 |
  | U4 | `ReviewHost.SameRunRoot` | letter case ignored | 2 |
  | U5 | `ReviewHost.SameBackendSettings` | the run root among the settings in force | 2 |
  | U6 | `ReviewHost.SettingsNotInForce` | the run root's sentence when the run root differs | 4 |
  | U7 | `ReviewHost.NotInForceWithTheRunRoot` | where every tab makes its runs, not the folder saved | 4 |
  | U8 | `ReviewHost.RunRootForANewRun` | none while a start under way would bring another run root in | 4 |
  | U9 | `ReviewHost.RunRootForANewRun` | a start under way that keeps the run root moves nothing | 1 |
  | U10 | `ReviewHost.RunRootForANewRun` | none, not the run root the start under way is made with | 4 |
  | U11 | `ModelCheckHost.StartCheck` | the run root for a new run, not the run root in force | 1 |
  | U12 | `ModelCheckHost.StartCheck` | the folder made under the run root judged, one reading | 1 |
  | U13 | `ModelCheckHostOptions` | the run root for a new run the run root in force by default | 18 |
  | U14 | `StandardsHost.Start` | the run root for a new run, not the run root in force | 1 |
  | U15 | `StandardsHost.Start` | the folder made under the run root judged, one reading | 1 |
  | U16 | `StandardsHostOptions` | the run root for a new run the run root in force by default | 27 |
  | U17 | `RemodelHost.RunRootToUse` | the run root for a new run, not the run root in force | 2 |
  | U18 | `RemodelHostOptions` | the run root for a new run the run root in force by default | 6 |
  | U19 | `PaneActions.SendRunRootMoving` | the class, `BackendUnavailable` | 4 |
  | U20 | `PaneActions.SendRunRootMoving` | retryable | 4 |
  | U21 | `RunRootRule.MovingRefusal` | the way on, the same press in a moment | 2 |
  | U22 | `SwReviewAddIn` | the Remodel tab handed the run root for a new run | 1 |
  | U23 | `SwReviewAddIn.RunRootForANewRun` | one reading of the host, its none never taken for its absence | 1 |

#### The reviews of the merge (2026-10-21)

- **Question**: two independent reviews of the branch at `046a428` - Opus and Codex - found no must-fix (Opus) or only the
  item already left to the owner (Codex); Opus confirmed the merge and the unification: every run start, Recheck, context
  review and session takes the backend's run root, the run roots in force are complete, and the read order is right. Two
  should-fix findings (F1, F2) and five more to fix (N3 to N6, N8), the coordinator's list.
- **Decision** (the coordinator, for the owner, 2026-10-21): fix each, test first; for F1, decide whether the rule refuses
  such a root already in force at a run start, and say why. Tasks T204 to T206, numbered after T203, which stand: 154A
  lands next.

**F1. A folder name ending in a space or a period.** `C:\Work \runs` and `C:\Work..\runs` were accepted, saved, and the
backend started with them - and under SOLIDWORKS' path handling every run then failed inside the backend. Measured here
with `GetFullPathNameW`, the rule's full path: it keeps `Work `, `Work..` and `Work...` as written, and trims only a
single period (`Work.`) and the last name's trailing spaces and periods; the backend's own resolution keeps them too. The
reviewer measured .NET's legacy `Path.GetFullPath` - SOLIDWORKS' most likely handling - trimming `Work `, so every run
folder was made under `C:\Work\runs\...`, `IsUnder` passed, and the backend refused the folder, `InvalidRunDir`, naming
paths, after the whole extraction on the Review tab; the test host runs the newer handling, so no test there met it.
Fixed in the rule, read on the text before anything else is: a fifth verdict, `RunRootVerdict.NameEndsInSpaceOrPeriod`,
for any name of the root - its folders' and its last, but `.` and `..`, which are no names - that ends in a space or a
period, either separator counted. A folder chosen so is the one field a save does not write (`ChosenRefusal`), a run
root kept so is noted (`KeptRefusal`), and every run start refuses it (`Refusal`): "The run root has a folder whose name
ends in a space or a period, which Windows reads both with and without it, and runs are made only in a local folder
reached by its own path, so ...". **Decided: the rule refuses such a root already in force too**, at every start. The
settings file can name one - written by hand, or saved before this round - and under it every run is refused inside the
backend, after the extraction, for the reason the rule refuses a link: the add-in and the backend spell the run root as
two folders. Refused up front, it costs nothing and names the way on. The words file's `RunRootRefused` sentence names it
("- not on a network share, not through a link, and with no folder name ending in a space or a period -"), and every
host's refusal cases run a fifth time (`FakeRunRootProbe.RefusedKinds`, "a name ending in a period").

**F2. A path copied with Explorer's "Copy as path".** Ctrl+Shift+C copies a path in double quotes, which the field's
save called not a full path. The save now takes one pair of quotes around the whole off, after the field is trimmed, and
trims what they held again (`ReviewHost.ChosenRunRoot`); a pair around nothing chooses the default, as an empty field
does, and a quote before the folder alone stays, and is no full path.

**N3. Two orders.** That a failed start adds nothing to the run roots in force is now pinned: the two T201 theories that
fail a start - a save's at once and after waiting, and a start under way that fails before the old backend stops - assert
the run roots in force afterwards, and moving the append ahead of the start (V11, as 153A deliberately does for the keys
started with) turns them red. Two orders stay unobservable without a hook, and are recorded: the start under way read
before the record in `RunRootForANewRun` (a start that ends between the two readings is the only thing that tells the
orders apart, and nothing in the test worlds runs between them), and the run roots appended before the record, not
after it.

**N4. A refused run root in force while another is chosen.** The run root loaded on a share refuses every start; the
engineer chooses a local folder in Settings, and its save's restart fails before the old backend stops. Every start was
then refused saying to choose a local folder, which the engineer had just done, and `init` said every tab makes its runs
in the folder the backend was started with, where none is made. Now, while another folder is saved than the run root in
force (`RunRootRule.SameRunRoot`), a start refused for the run root in force is `RunRootChosenNotInForce`, not retryable:
"The run root in force is ..., so nothing was started. The folder chosen for runs in Settings is not in force until the
review backend restarts with it: save the settings again to retry the restart, then try again." (the other tabs: "in
Settings on the Review tab", and their own way on). Its sentence in the words file: "The folder for runs in force is
refused, and the one chosen in Settings is not in force until the review backend restarts with it. Save the settings
again to retry the restart." Every refusal reads the run root saved: the review host its own settings', and the other
tabs the review host's, handed down (`SwReviewAddIn.RunRootSaved`, each host's `RunRootSaved`, `CheckPaneHost`,
`PaneActionsOptions.RunRootSaved`). And `init`, and the status of a restart that waited and failed, say "The saved
settings are not in force yet: the review backend did not restart with them, and no run can start until it does, since
the folder for runs it was started with is refused. Save the settings again to retry the restart." whenever the run root
in force is one the rule refuses (`NotInForceWhileTheRunRootIsRefused`): the rule is asked there, under the restart's
lock when a restart that waited fails, and reads nothing over the network or through a link before it refuses. Left: a
refused run root in force with a folder chosen whose restart waits for a turn - a turn running under a run root the rule
now refuses - says to save again, which waits for the turn as the first save did.

**N5.** `RunRootToUse`'s comment named a save made while a review's evidence was extracted, which cannot happen - the
Review page's messages are handled one at a time, on one thread - and left out the case that can: the add-in's first
start, under way when the review began, ending during the extraction (pinned in T201). Corrected there, and in the F6
test's summary, whose save made from the dump stands in for that first start. *Corrected in F6 above too:* "a save made
then restarts at once" is that first start.

**N6. A check run whose extraction spans a restart.** Codex rated the recorded item "do not ship yet": a Model check or a
Standards run reads the run root, extracts for minutes, and hands its folder on, while a settings save's restart on the
Review tab, which no check holds back, can bring another run root in, and the backend refuses the folder at the page's
first call. Narrowed: once the extraction is over the run root is read again (`PaneActions.AnsweredForAMovedRunRoot`),
and a run whose folder it no longer holds is answered `RunRootChanged`, not retryable - "The run root changed while the
feature tree was read (the document was read), and the backend makes runs only under the one in force, so nothing was
checked. Press Model check (Standards check) again." - and one while a start that would bring another in is under way,
`BackendUnavailable`, retryable, as a start is then; either way the folder is left as the evidence and neither
registered nor handed to the page. **Left, put to the owner as before:** a restart after that reading, before the
backend reads the folder - one round trip, the page's first call - and one during the backend's grading, which ends that
backend as any restart ends work in flight on it. Whether a check run holds a restart back, as decision 145A made a
remodel run, is the owner's to say. *Settled 2026-10-21 by owner decision 157A:* a check holds every settings restart
back until the page's evaluation of it has been answered while a backend is up, so neither of the two can be a save's
restart then; the reading after the extraction, and `RunRootChanged` there, stay for the starts that bring a backend up
where there was none, which nothing holds back (157A, below).

**N8. A folder name longer than 255 characters** was reported as a root that could not be checked: Windows answers the
open of such a name as an invalid name (`ERROR_INVALID_NAME`, 123; measured here, where a missing 255-character name
answers "not found"), which the probe reads as a part that cannot be read. Its own true words, and small: the rule leaves
such a root to the run folder, as a character no folder can have, before anything is read, and the run folder says so in
Windows' own words (`RunFolderFailed`). The probe's reading is unchanged and true of the probe.

- **Not changed**, put to the owner: a save writes a folder chosen that no folder can be made under - a character no
  folder can have, a trailing quote alone among them, or a name longer than 255 characters - as it did before, and every
  run is then answered `RunFolderFailed`; refusing it at the save, as a folder not written in full is, would be one more
  note.
- **Tests**: T204, written first against stubs - the new verdict, the two new sentences and the hosts' run root saved
  present and unread - 45 of the 63 new and changed cases failed. The 18 that passed: the dot segments and names with a
  space or a period inside (5) and a saved run root in another letter case (2), guards; N3's pins (9), red under V11; a
  quote before the folder alone (1), a guard; and the words file's coverage of the classes the host sends, red once the
  host sends `RunRootChosenNotInForce` with no sentence for it. Changed deliberately, each with its reason: the rule's
  three word theories, a fifth row each, and `ThereAreNoWordsForARootTheRuleAccepts`, the new sentence among them (F1,
  N4); `FakeRunRootProbe.RefusedKinds`, a fifth kind, so every host's refusal case runs a fifth time (F1); T201's two
  theories (N3); the check tabs' one-reading cases, the run root now read again after the extraction, so the move is
  answered `RunRootChanged` where the run was handed on (N6); `WhileAFolderChosenWaitsAReviewStartJudgesTheRunRootInForceAndInitNamesIt`,
  whose refusal is now `RunRootChosenNotInForce` (N4; red against the implementation until changed); the label scan's
  expected classes; `LabelsSample.RunRootRefused` and `test_review_words.py`'s pins, the sentence; and the F6 test's
  summary (N5, words only).
- **Gates**: 2026-10-21: no broken link; C# 0 warnings on a `--no-incremental` build, 10,059 and 3,392 passed, from
  10,059 and 3,343; the restart classes (`DeferredRestartTests`, `OtherTabsBackendRestartTests`,
  `ReviewPageBackendRestartTests`, `TabPagesBackendRestartTests`, 337 cases) passed five times in a row; Python, the
  words, fixture, pin and labels tests and those that read `tasks.md`, 1,037 passed on 3.12 and 1,037 on 3.11
  (`--isolated`); `ruff check` clean; the pane fixtures regenerated by both generators, the same four in two lines
  each, and the pin moved; the full Python suites the coordinator's.
- **Mutations**: as before - each change taken out once with one exact replacement (V11 with two, the append moved
  ahead of the start), the tree rebuilt, the named cases run (154A's run root cases, 153A's settings in force and first start,
  the unification's and this round's: 506) and the file restored byte for byte (checked by sha256): each of the 30
  mutations of the add-in's code turned at least one case red, 105 red results in all. Of the words file and the
  pin, 3 more, below the first table's rows.

  | id | where | taken out | red |
  |---|---|---|---|
  | V1 | `RunRootRule.Judge` | a name ending in a space or a period refused | 19 |
  | V2 | `RunRootRule.HasANameEndingInASpaceOrAPeriod` | `.` and `..` no names | 4 |
  | V3 | `RunRootRule.HasANameEndingInASpaceOrAPeriod` | a name ending in a period | 14 |
  | V4 | `RunRootRule.HasANameEndingInASpaceOrAPeriod` | a name ending in a space | 5 |
  | V5 | `RunRootRule.Names` | either separator counted | 1 |
  | V6 | `RunRootRule.Kind` | the words for a name ending in a space or a period | 3 |
  | V7 | `RunRootRule.NamesNoFolderCanHave` | a name longer than 255 characters left to the run folder | 2 |
  | V8 | `RunRootRule.LongestName` | 255, the longest name a folder can have | 1 |
  | V9 | `ReviewHost.ChosenRunRoot` | one pair of quotes taken off | 4 |
  | V10 | `ReviewHost.ChosenRunRoot` | what the quotes held trimmed again | 1 |
  | V11 | `ReviewHost.StartWith` | the run root appended only once the start has succeeded | 5 |
  | V12 | `PaneActions.RefusedRunRoot` | `RunRootChosenNotInForce` while another folder is saved | 6 |
  | V13 | `PaneActions.RefusedRunRoot` | the folder saved told apart by the one rule, ignoring letter case | 2 |
  | V14 | `PaneActions.RefusedRunRoot` | the class, `RunRootChosenNotInForce` | 7 |
  | V15 | `RunRootRule.ChosenNotInForceRefusal` | the way on, the restart retried | 2 |
  | V16 | `ReviewHost` | the run root saved handed to the Review tab's refusals | 3 |
  | V17 | `CheckPaneHost` | the run root saved handed to the check tabs' refusals | 2 |
  | V18 | `ModelCheckHost` | the run root saved handed to the check pane | 1 |
  | V19 | `StandardsHost` | the run root saved handed to the check pane | 1 |
  | V20 | `RemodelHost` | the run root saved handed to its actions | 1 |
  | V21 | `SwReviewAddIn` | the Standards tab handed the run root saved | 1 |
  | V22 | `SwReviewAddIn.RunRootSaved` | the run root saved, not the one in force | 1 |
  | V23 | `ReviewHost.SettingsNotInForce` | the sentence while the run root in force is refused | 2 |
  | V24 | `ReviewHost.NotInForceWhileTheRunRootIsRefused` | no run can start until the restart | 2 |
  | V25 | `ModelCheckHost.StartCheck` | the run root read again once the extraction is over | 3 |
  | V26 | `StandardsHost.Start` | the run root read again once the extraction is over | 3 |
  | V27 | `PaneActions.AnsweredForAMovedRunRoot` | a run root no longer holding the folder answered | 4 |
  | V28 | `PaneActions.AnsweredForAMovedRunRoot` | a start under way answered as at a start | 2 |
  | V29 | `PaneActions.AnsweredForAMovedRunRoot` | `RunRootChanged` not retryable | 2 |
  | V30 | `RunRootRule.ChangedRefusal` | the words for a run root changed while the model was read | 1 |
  | W6 | `review_words_v1.yaml` | `RunRootChosenNotInForce`'s sentence | 7 Python, 1 C# |
  | W7 | `review_words_v1.yaml` | `RunRootRefused`'s sentence true of a name ending in a space or a period | 7 Python |
  | F3 | `review-send-failure-events.json` | the pin moved to the regenerated fixture | 3 |

### 156A. 002's other words for the hidden Terminal tab, and an invalid escape in a test (2026-10-20)

- **Question**: Other words in 002 still describe the hidden Terminal tab as shown, and a test's fictional Windows path has an invalid escape.
- **Decision**: Add dated notes wherever the spec describes that tab, built and hidden since 2026-09-19, and fix invalid Python escapes without changing values or product behaviour.
- **Change**: Annotated `spec.md` and settled 011's research R13.5 item 2; audited `reviewer/tests/` and `reviewer/src/` and made the affected test literal raw with the same value.

### 157A. A Model check or a Standards check holds a settings restart back until its evaluation is answered (2026-10-21)

- **Question**: 154A's reviews left one thing for the owner (154A, the reviews of the merge, N6, and the reviews' Not
  changed item 1): a Model check or a Standards run reads the run root, extracts for minutes, and hands its run folder
  to the page, which calls `POST /checks/rms` or `/checks/standards` itself - and a settings save's restart on the
  Review tab, which no check held back, could land in between. 145A had recorded that a check is not a turn to the
  restart: "its call in flight when the backend restarts fails as any call to a backend that stopped does" (145A, Not
  changed). N6 narrowed the run root's half - the run root is read again once the extraction is over - and left the
  rest: a restart after that reading, before the backend reads the folder, and one during the backend's grading. Beyond
  the run root, an evaluation made with the old token after a restart is refused by the new backend, and one in flight
  when the backend stops fails; either way the minutes of extraction are wasted.
- **Decision** (owner decision 157A, "1A", 2026-10-21): "A Model check or Standards run holds back a settings restart,
  as a remodel run does since 145A (154A's owner question), test first, with adversarial reviews: a save made during a
  check waits for it, and a check started while a restart waits makes the restart first, so no check's extraction is
  wasted on a backend that restarted under it."

**1. Where the hold starts and ends.**

- The span the decision preferred is the whole: from the press until the page's last call for that check has answered.
  It cannot be bounded. After the evaluation the page's calls for a check are the engineer's to make - an Accept
  (`POST /checks/{check_id}/exceptions/{finding_id}`) and its re-read (`GET /checks/{check_id}`), and the latest check
  read again by a later `init` - at any time, or never, and the page never says it is done with a check. A restart held
  on that would keep the saved settings out of force, and every new review, turn call and remodel run refused, for as
  long as a result stays on screen.
- So the span chosen is the one that removes the wasted extraction and the failed call: from the check's gate - once
  every refusal that needs no call is behind it - through the extraction and the reply that hands the run to the page
  (`check.extracted`, `standards.extracted`), until the page's evaluation of that run has been answered. The extraction
  and the evaluation are the check; they are the calls a restart wastes it by cutting.
- The page's half is held by the pane's proxy, which sees the evaluation: `POST /checks/rms` and `/checks/standards`
  name the run folder in their body (`run_dir`, as the host's reply gave it), and the proxy asks the check hosts for
  that run's hold while the call is out (`TaskPaneOptions.HoldCheckEvaluation`, `ModelCheckHost.HoldEvaluation`,
  `StandardsHost.HoldEvaluation`, `CheckPaneHost.HoldEvaluation`) and lets it go once the call is answered, however it
  is - answered, refused by the backend, unreachable, refused by this side, or with no backend. Nothing on the page
  changed: the host sees its own reply's folder come back. The routes held are exactly the backend's two that grade a
  run, read from `chat/server.py` by a case, as 143A's turn routes are.
- The gap between the reply and the call is bounded: the hold, handed over with the run (`CheckPaneHost.HandOver`),
  waits for that evaluation a minute at most (`CheckPaneHostOptions.HandOverLimit`, on a clock no change of the wall
  clock moves). A page that has gone - loaded again, or closed, after the reply - never calls, and the restart waits no
  longer than that for it. A page that is there calls as soon as it reads the reply, once any `init` on its way is
  answered on the tab's own pump, which is free once the reply is sent: milliseconds. Once the proxy has taken the hold
  over, the evaluation's own timeouts bound it: the proxy gives the backend two minutes to answer, and each read of its
  answer two more.
- Accepts and re-reads are not held: each is one short call, made when the engineer chooses; one that a restart cuts is
  answered as any failed call is, and pressed again on the new backend. An Accept whose exception was written before the
  cut is refused `AlreadyAccepted` when pressed again, so nothing doubles; and none of them wastes an extraction.

**2. How a check holds the restart.**

- Through 145A's mechanism. `DeferredRestart`'s busy reading says which work is in progress (`DeferredRestart.Work`: a
  remodel run, a Model check, a Standards check, or work of a kind not known): the review host reads `BackendBusy`, as
  before, and two new readings, `ReviewHostOptions.ModelCheckInProgress` and `StandardsCheckInProgress`, which the
  add-in answers through each host's `CheckInProgress`, read through the field. 145A's `Hold.RemodelRun` and
  `Outcome.RemodelRunning` are `Hold.Work` and `Outcome.WorkInProgress`, and `Now`, `Apply` and `Begin` carry the work
  they found out, so every sentence and refusal names it.
- A save made during a check: `Now` reads the work under the restart's lock before it asks the backend anything, and
  defers. The save is kept, answered `settings.saved`, and its status says what the restart waits for (section 3). The
  watcher makes the restart once no work and no turn holds it back.
- A check started while a restart waits: after every refusal that needs no call, `CheckPaneHost.BeginCheck` asks the
  review host's gate (`ReviewHost.BeginCheck`, through `CheckPaneHostOptions.BeginCheck` and `SwReviewAddIn.BeginCheck`,
  read through the field per call as `BeginRemodelRun` is): a waiting restart is made first, or the one being made is
  waited for, and the check takes its hold under the restart's own lock (`TakeTheHold`); or the press is refused saying
  what holds the restart back, or with the failure of the restart it made or waited for, and nothing is made.
  `BeginRemodelRun` and `BeginCheck` are one gate (`ReviewHost.BeginWork`), each answering in its tab's words.
- What the gate's wait can move is read again once it is passed: the run root (`PaneActions.RunRootToUse`, which the
  Remodel host's N8 reading now goes through too), judged again when it moved; and the active document - a check whose
  document changed while the gate waited is refused `DocumentChanged`, retryable, in words with no path, as 145A's
  second review made a plan read its document again.
- The page is told first when a restart stands before the press: `status {stage: "backend_starting"}`, "Waiting for the
  review backend to restart with the saved settings, then reading the feature tree..." on the Model check tab and
  "...then reading the document..." on the Standards tab - 145A's Remodel tab words, their beginning now written once
  (`PaneActions.WaitingForTheRestart`). The check page writes any status but `error` in its check line, and its catch
  empties that line when the press is refused.
- Every way out of the start once the gate is passed, but the hand-over, lets the hold go (`EndCheck`, in a `finally`):
  a run root moved and refused, a document changed, the run folder not made, the extraction failed, the run root moved
  while the model was read, a throw. A gate that throws leaves nothing held, whether or not it ran its step, and so does
  one that refuses after running it, which the review host's never does.
- A check refused on the spot - its run root, no document, not attached, not a part, a document never saved, a kind not
  graded, no profile - asks no gate, and so makes no restart.
- A check holds the restart back only while a backend is up (`ReviewHost.WorkInProgress` reads the checks only then).
  With none - the first start failed, or the backend stopped - there is no backend to restart under the check, and the
  restart is what brings back the backend its evaluation needs: 143A's rule for the look, "no backend process at all
  holds nothing". 145A kept a remodel run holding the restart even then, because every call a run makes fails with no
  backend, so "it cannot last". A check's extraction asks no backend and lasts minutes, and its page, holding no
  backend, never even makes the evaluation the hand-over waits for: holding the restart would waste the very extraction
  the check holds it for, and keep the backend the save asked for down a minute longer. So a save made during a check
  with no backend up starts the backend at once, and a restart that waits for a check is made once its backend has
  stopped; the check's page is told the backend restarted, and its evaluation, made after its `init`, goes to the new
  backend.

**3. What a restart waits for, said.**

- The promise is composed from what holds the restart, in one order - a turn that started during the save, the remodel
  run, the checks - with "and" before the last and the verb agreeing: "the settings are saved; the backend restarts when
  the running check ends.", "...when the running checks end." for a check on each check tab, and so on up to "...when
  the running turn, the remodel run and the running checks end.". 145A's three are the rows with no check, word for
  word. `backend.restarted` carries all twelve sentences - eleven promises and the watcher's word - and the Review page,
  which takes whichever is on its banner off it, needed nothing new.
- A refusal names the work as well: "the backend restarts with the saved settings when the running check ends, and
  nothing new starts before then. Wait for the check to end, then try again.", "the running checks" and "the checks" for
  one on each check tab, and "them" for a remodel run and a check together. Its class is `CheckRunning` for checks
  alone - new, with a sentence of its own in the words file: "A Model check or Standards check is in progress. Wait for
  it to finish, then try again." - and `RemodelRunning` whenever a remodel run is among the work, since one is then in
  progress, as that class's sentence says. The proxy answers `CheckRunning` 409, as `TurnRunning` and `RemodelRunning`.
- A check tab's refusals for a turn and for a backend that does not answer are 145A's Remodel tab's, naming a check:
  "the backend restarts with the saved settings when the running review turn ends, and no check starts before then. Wait
  for the turn to end, or press Stop on the Review tab, then try again."; written once for both tabs
  (`TurnHoldsTheWork`, `NoAnswerHoldsTheWork`).
- The watcher's word for a backend that does not answer names a check among what makes the restart first: "the review
  backend is not answering, so it has not been restarted with the saved settings yet. It will be before the next review,
  follow-up, remodel run or check, once it answers; to restart it now, save the settings again."

**4. The other tabs.** A check holds back only restarts. With no restart waiting, two checks, a check and a remodel run,
and a check and a turn overlap as before: `Begin` reads no work when nothing waits. While a restart waits for a check,
nothing new starts on the old backend - a check on the other tab, a remodel run, a new review, a turn call - each
refused saying what holds the restart back, as while it waits for a turn or a remodel run: this is what the restart
logic needs, since work begun then would put the restart off again, the saved settings out of force meanwhile. A page
loaded again can press again while its predecessor's evaluation is out: the tab keeps both holds, and lets each go on
its own.

**5. Work read before the look.** 145A's look read a remodel run before the turns, so a restart a run held back asked
the backend nothing, and the watcher counted no backend that does not answer meanwhile. With the checks among the work,
that reading moved from the review host's look into `DeferredRestart.Apply`, which reads the work before it looks and
again under its lock, as it did; the look asks only about the turns, and a look that still names work is work of a kind
not known. 145A's cases - a remodel run named before a backend that does not answer, a run with no backend at all - pass
as they were.

**6. 154A's reading after the extraction.** While a backend is up no restart can move the run root during a check's
extraction, nor before its evaluation is answered, so the `RunRootChanged` answer after an extraction is unreachable
then. It is kept for the starts that bring a backend up where there was none, which nothing holds back, since there is
no backend for them to restart under the check: a save that chose another folder for runs, made with no backend up,
starts the backend with it at once; and the add-in's first start, after a save that chose one and whose restart failed,
starts it with the settings saved. Either way that folder comes into force during the extraction, and the check, made
under the run root loaded, would meet the backend's refusal at its evaluation. Cases pin both, through the real review
host. The reading before the gate (`RunRootForANewRun` none while a start under way would bring another run root in)
stays for the same reason.

**7. No deadlock.** The gate's step takes the tab's own hold lock and sets a field, nothing more; the restart reads
`CheckInProgress` under its lock, and the hold lock is a leaf - nothing is called, waited on or asked of SOLIDWORKS
while it is held, and nothing holding it takes another lock. 145A's order stands: the restart's lock, then its state
lock or a tab's hold lock. The extraction and the document's readings, which go through SOLIDWORKS' application thread
(004 R18.4's lesson), run on the tab's pump under no lock. A restart a check's gate makes runs on that pump and posts
`backend.restarted` to every tab, which never blocks; the tab's own page then asks `ready` again, answered behind the
start on the same pump, and its evaluation waits for that `init` (`call`, `initSettled`) and carries the new token.

- **Edge cases**, each decided and tested (T230, T232, T235):
  - End to end, on each tab, through the real review host, the real check host and the real proxy: a save while the
    model is read waits until the evaluation is answered, by the backend the check began on, and then the backend
    restarts once; so does one made between the reply and the evaluation, however long the evaluation is out; a check
    started while a restart waits makes it first, is told so before the gate in its tab's words, is told the backend
    restarted before its reply, and is evaluated on the restarted backend; one started while a turn holds the restart is
    refused in its tab's words, making nothing, and a press refused on the spot makes no restart; one whose gate's
    restart fails, before the old backend stopped or once it had, is refused with the failure, masked, and holds
    nothing - the next save restarts at once; a restart that waited for a check and failed is told, the check's answer
    standing; a page that never evaluates holds the restart a moment short of the limit, and not at it; and a start that
    brings a backend up during an extraction - a save's with no backend up, or the first start - is still answered
    `RunRootChanged`.
  - Through the review host: a save's sentence for every combination of a turn, a remodel run and one or two checks; a
    new review and a turn call refused `CheckRunning`, plural for two checks, and the proxy's 409; a remodel run refused
    while a check holds the restart, and begun once it is over; a remodel run and a check named together, under
    `RemodelRunning`; a check begun at once beside other work with nothing waiting; begun the moment the turn ends on
    the restarted backend; refused while a turn, a backend that does not answer, a remodel run or the other tab's check
    holds the restart; waiting for a restart being made, the watcher's or a save's; refused with a restart's failure,
    its own or a save's; refused once the host is disposed; a check named before a backend that does not answer, the
    watcher asking nothing; and with no backend at all a check holding nothing - a save starts the backend at once, and
    a restart that waits for a check is made once its backend has stopped.
  - In the restart itself: the work a save defers by, and that a waiting restart and work that would begin are held back
    by, carried out whole for six combinations; work read before the look, which is then never asked; work only the
    reading under the lock found named by that reading; work a look names, or a reading that throws, of a kind not
    known; and work begun beside work in progress with nothing waiting, nothing read.
  - In the check hosts, on each tab: one gate, before anything is made, after every refusal that needs no call; the
    gate's refusal answered and nothing made; a gate that throws, or refuses after its step, holding nothing; the page
    told before the gate only with a restart ahead; the run root read again once the gate is passed and a move judged
    again; a document changed while the gate waited refused, the same document spelled otherwise checked; the hold from
    the gate through the extraction, the reply and the evaluation out, past the limit; every other way out letting it
    go; only the evaluation of the run handed over held, once, however its folder is spelled; the limit, its own option,
    measured from the hand-over; two checks of one tab each let go on its own; and every hold let go with the host.
  - In the proxy: the evaluation held while it is out, by the folder its body names, the body sent on as received; let
    go however the call ends; nothing else held - a re-read, an Accept, a turn call, a `GET`, a body naming no folder or
    not JSON, a route that only looks like an evaluation's; with no hold to be had, or a host that throws, the
    evaluation sent unheld; and the routes held exactly the backend's two that grade a run.
- **Evidence** (at `5a58988`):
  - A check held nothing: `ModelCheckHost.StartCheck` read the run root (`ModelCheckHost.cs:241`), dumped (`:315`), read
    the run root again (`:337`) and replied (`:351`) with no gate; `StandardsHost.Start` likewise
    (`StandardsHost.cs:252`, `:353`, `:377`, `:391`). The page then called the route itself (`check.js:100`), once any
    `init` on its way was answered (`check-page.js:292`, `:299`).
  - The restart's busy reading was the remodel run alone: `ReviewHostOptions.BackendBusy`, set to
    `_remodelHost?.RunInProgress` (`SwReviewAddIn.cs:474`), read by `ReviewHost.RemodelRunInProgress`
    (`ReviewHost.cs:1858`) for `DeferredRestart`'s `busy` (`DeferredRestart.cs:599`) and by the look
    (`ReviewHost.cs:1880`); a save deferred only for it (`ReviewHost.cs:1404`). The only gate was `BeginRemodelRun`
    (`ReviewHost.cs:2180`).
  - The proxy held nothing but a turn's bridge (`BackendProxyHandler.cs:132`, `:262`), with a call timeout of two
    minutes (`:84`).
  - The backend's evaluation routes grade synchronously, with no chat (`chat/server.py:1661`, `:1687`); an Accept writes
    its exception, then grades again (`:1729`), and refuses a rule already covered (`AlreadyAccepted`, `:2093`).
- **Not changed**, put to the owner:
  1. An Accept and a re-read are not held (section 1); one a restart cuts is answered as any failed call is.
  2. A page whose evaluation reaches the proxy after the hand-over's limit - a page held up for a minute, such as by
     another tab's extraction holding SOLIDWORKS' application thread, through which the page's requests are served - is
     sent unheld, as before 157A. A longer limit would hold a gone page's restart back longer; a minute is the choice.
  3. A restart's refusals still name what was found first: work is read before the turns, so while a check and a turn
     both hold the restart a new review is told of the check alone - as 145A's refusals named a remodel run before a
     turn. The save's promise names both.
  4. With no backend up a check holds nothing, where 145A has a remodel run hold the restart even then: decided, for the
     reasons in section 2; a remodel run's rule is unchanged.
  5. A start that brings a backend up where there was none - a save's with no backend up, or the add-in's first - can
     still land between the reading after the extraction and the evaluation, and move the run root; nothing holds it
     back, and with no backend the check could not be evaluated without it.
  6. 154A's run root read before the gate refuses a start under way at the press; one that begins after the gate is
     passed is caught by the reading after the extraction, as before.
  7. While a hand-over waits for a page that has gone, the tab's next `check.start` - from the page loaded again - takes
     a hold of its own beside it when no restart waits; when a save's restart waits for the check that was handed over,
     the press is refused `CheckRunning`, as any work is then, for at most the rest of that check's minute.
- **Existing cases changed deliberately**, each with its reason: `DeferredRestartTests` - the renames `Hold.Work` and
  `Outcome.WorkInProgress` in six cases, the helper's remodel-run reading taken as the work reading's `RemodelRun`, the
  watcher's not-answering word naming a check (eight cases read it), and `backend.restarted`'s twelve sentences (three
  cases); `ReviewPageBackendRestartTests` - the same two constants, as data, the page unchanged; `ModelCheckHostTests`
  and `StandardsHostTests` - the four cases that count the run root's readings, since it is read once more, after the
  gate, the move they stage now at the third reading; `ToolServiceWiringTests` - the pin of the proxy's construction,
  which gains the check hosts' holds after the bridge's; `ErrorLabelsCoverTheHostTests` - the classes the host makes
  gain `CheckRunning`; `BackendProxyHandlerTests` - a `CheckRunning` row; `test_review_words.py` - `CheckRunning`'s
  sentence among the restart holds. None was loosened.
- **Tests**: T230 and T232, written first against stubs - `DeferredRestart`'s work reading present and answering none,
  the review host's two readings unread and `BeginCheck` running its step, the check hosts' options unread and their
  hold answering nothing, the proxy's and the pane's option unread: 110 of the 145 new cases in the six classes the hold
  touches failed. The 35 that passed are guards, pinning what held already: a press refused on the spot asks no gate
  (11), work begins beside work with nothing waiting (9), 145A's three sentences (3), a document spelled otherwise (2),
  calls that are not evaluations (8), and an evaluation with no hold to be had (2). The Review page's two new cases, the
  check sentences taken off its banner, pass as written: the page takes off whichever sentence `backend.restarted`
  lists. Eighteen existing cases went red with them, the deliberate changes above. T234's `test_review_words.py` row was
  red against the words file before its sentence. T235, once the implementation was in: the rule for no backend up was
  first written the other way, mirroring 145A's remodel run - a check holding the restart with no backend at all, pinned
  by one case - and a second reading of the design, during the first pass of the mutations, reversed it (section 2). The
  cases of the rule as decided - a save made during a check starting the backend at once, on each tab, and a restart
  that waited for a check made once its backend stopped - were red against the code as it was, 3 of 3, and took the
  first rule's case's place; T232's case for 154A's reading after the extraction gained the save's two rows beside the
  first start's. Added with them, each red under its mutation: work found only under the lock (D4), a check named before
  a backend that does not answer (D2, H1, H2), a gate that refuses after its step (C4), a folder spelled otherwise (C9,
  C10), the limit measured from a hand-over made at a later clock (C7), three routes that only look like an evaluation's
  (X3, X4, X5), and the proxy's answer to `CheckRunning` (X8), 503 until it was given its class's 409. The add-in's
  suite grew from 3,540 cases to 3,704: 147 from T230 and T232, and 17 from T235.
- **Gates**: 2026-10-21, on the records' tree: no broken link; C# 0 warnings on a `--no-incremental` build, 10,086 and
  3,704 passed, from 10,086 and 3,540; the restart classes (`DeferredRestartTests`, `OtherTabsBackendRestartTests`,
  `ReviewPageBackendRestartTests`, `TabPagesBackendRestartTests`, 499 cases) and `CheckHoldTests` (57) passed five times
  in a row; Python, the full suites, 18,111 passed and 5 skipped on 3.12 and on 3.11 (`--isolated`), as at `5a58988`,
  since the words test's new row is in a case that was there; `ruff check` clean; the pane fixtures as both generators
  write them (T234).
- **Mutations**: as before - each fix taken out once with one exact replacement, the tree rebuilt, the named classes run
  (`DeferredRestartTests`, `CheckHoldTests`, `BackendProxyHandlerTests`, `ModelCheckHostTests`, `StandardsHostTests`,
  `ErrorLabelsCoverTheHostTests` and `ToolServiceWiringTests`: 758 cases; with `RemodelHostTests` for P1 to P3 and R1,
  1,108, and with `ReviewPageBackendRestartTests` for H18, 785) and the file restored byte for byte (checked by sha256):
  each of the 76 mutations of the add-in's code turned at least one case red, 620 red results in all. Of the words file,
  the fixture and the pin, 3 more, below the first table's rows: W1 and F2 ran the words and fixture tests
  (`test_review_words.py`, `test_pane_waiting_fixtures.py`, 139 cases), W1 the label scan, and F1 and F2
  `ReviewPageSendGateTests` (57).

  | id | where | taken out | red |
  |---|---|---|---|
  | D1 | `DeferredRestart.Now` | the work a save deferred by carried out | 28 |
  | D2 | `DeferredRestart.Apply` | work read before the look | 6 |
  | D3 | `DeferredRestart.Apply` | the work read before the look carried out | 21 |
  | D4 | `DeferredRestart.Apply` | the work read under the lock carried out | 1 |
  | D5 | `DeferredRestart.Apply` | a look that names work: work of a kind not known | 1 |
  | D6 | `DeferredRestart.Busy` | a reading that throws: work of a kind not known, not none | 2 |
  | D7 | `DeferredRestart.Begin` | the work its `Apply` found carried out | 10 |
  | H1 | `ReviewHost.WorkInProgress` | a Model check read | 19 |
  | H2 | `ReviewHost.WorkInProgress` | a Standards check read | 17 |
  | H3 | `ReviewHost.InProgress` | a reading that throws: work in progress | 1 |
  | H4 | `ReviewHost.Promise` | the work the save deferred by named | 18 |
  | H5 | `ReviewHost.Promise` | a turn that started during the save named with the work | 7 |
  | H6 | `ReviewHost.EndsOf` | "and" before the last | 14 |
  | H7 | `ReviewHost.EndsOf` | the verb agreeing with "the running checks" | 7 |
  | H8 | `ReviewHost.WhatHoldsTheRestart` | a check on each check tab named as two | 10 |
  | H9 | `ReviewHost.EveryRestartSentence` | the promises that name a check among `backend.restarted`'s sentences | 4 |
  | H10 | `ReviewHost.WorkHoldsIt` | the class, `CheckRunning` | 10 |
  | H11 | `ReviewHost.WorkHoldsTheRestart` | "them" for work held together | 1 |
  | H12 | `ReviewHost.RestartedForNewReview` | the work that holds a new review back named | 7 |
  | H13 | `ReviewHost.PageTurnRefusal` | the work that holds a turn call back named | 3 |
  | H14 | `ReviewHost.BeginWork` | the work that holds work back named | 4 |
  | H15 | `ReviewHost.BeginCheck` | a check tab's words, "no check starts" | 4 |
  | H16 | `ReviewHost.BeginCheck` | a check begins through the restart gate | 16 |
  | H17 | `ReviewHost.Save` | the work the save deferred by handed to its sentence | 18 |
  | H18 | `ReviewHost.RestartNotAnswered` | a check among what makes the restart first | 11 |
  | H19 | `ReviewHost.WorkInProgress` | the checks read only while a backend is up | 7 |
  | C1 | `CheckPaneHost.BeginCheck` | the page told first when a restart stands before the press | 4 |
  | C2 | `CheckPaneHost.BeginCheck` | the gate's step takes the hold | 37 |
  | C3 | `CheckPaneHost.BeginCheck` | a gate that throws lets the hold go | 1 |
  | C4 | `CheckPaneHost.BeginCheck` | a refusal lets the hold go | 2 |
  | C5 | `CheckPaneHost.Holds` | the hand-over's limit | 6 |
  | C6 | `CheckPaneHost.Holds` | an evaluation out holds past the limit | 2 |
  | C7 | `CheckPaneHost.HandOver` | the limit measured from the hand-over | 2 |
  | C8 | `CheckPaneHost.HoldEvaluation` | only the folder handed over held | 2 |
  | C9 | `CheckPaneHost.SameFolder` | letter case ignored | 3 |
  | C10 | `CheckPaneHost.SameFolder` | a trailing separator ignored | 2 |
  | C11 | `CheckPaneHost.HoldEvaluation` | an evaluation held once | 2 |
  | C12 | `CheckPaneHost.HoldEvaluation` | a hand-over past its limit not taken over | 2 |
  | C13 | `CheckPaneHost.LetGo` | only its own check let go | 2 |
  | C14 | `CheckPaneHost.Dispose` | every hold let go with the host | 2 |
  | C15 | `CheckPaneHost.EndCheck` | the start's hold let go | 25 |
  | C16 | `CheckPaneHost.HandOver` | the run handed over with its folder | 23 |
  | M1 | `ModelCheckHost.StartCheck` | begun through the gate | 30 |
  | M2 | `ModelCheckHost.StartCheck` | the run root read again once the gate is passed | 7 |
  | M3 | `ModelCheckHost.StartCheck` | the document read again once the gate is passed | 2 |
  | M4 | `ModelCheckHost.StartCheck` | the run handed over with its folder | 12 |
  | M5 | `ModelCheckHost.StartCheck` | every other way out lets the hold go | 11 |
  | M6 | `ModelCheckHost.StartCheck` | the gate after every refusal that needs no call | 27 |
  | S1 | `StandardsHost.Start` | begun through the gate | 28 |
  | S2 | `StandardsHost.Start` | the run root read again once the gate is passed | 7 |
  | S3 | `StandardsHost.Start` | the document read again once the gate is passed | 2 |
  | S4 | `StandardsHost.Start` | the run handed over with its folder | 11 |
  | S5 | `StandardsHost.Start` | every other way out lets the hold go | 11 |
  | S6 | `StandardsHost.Start` | the gate after every refusal that needs no call | 27 |
  | P1 | `PaneActions.RunRootToUse` | a moved run root judged again | 6 |
  | P2 | `PaneActions.RunRootToUse` | a start under way answered | 4 |
  | P3 | `PaneActions.WaitingForTheRestart` | the words written once | 6 |
  | X1 | `BackendProxyHandler.ForwardHoldingTheCheck` | the check's hold taken while its evaluation is out | 14 |
  | X2 | `BackendProxyHandler.ForwardHoldingTheCheck` | the hold let go once answered | 13 |
  | X3 | `BackendProxyHandler.EvaluatesACheck` | two segments exactly | 1 |
  | X4 | `BackendProxyHandler.EvaluatesACheck` | the two evaluation routes by name | 1 |
  | X5 | `BackendProxyHandler.EvaluatesACheck` | under `/checks` | 1 |
  | X6 | `BackendProxyHandler.RunDirectoryOf` | the body's `run_dir` read | 14 |
  | X7 | `BackendProxyHandler.HoldTheCheck` | a host that throws leaves the evaluation sent | 1 |
  | X8 | `BackendProxyHandler.RefuseTurn` | `CheckRunning` answered 409, as a turn's | 2 |
  | A1 | `SwReviewAddIn` | the review host told whether a Model check is in progress | 1 |
  | A2 | `SwReviewAddIn` | the review host told whether a Standards check is in progress | 1 |
  | A3 | `SwReviewAddIn` | the Model check host handed the review host's gate | 1 |
  | A4 | `SwReviewAddIn` | the Standards host handed the review host's gate | 1 |
  | A5 | `SwReviewAddIn` | the Model check host handed the word on a restart ahead | 1 |
  | A6 | `SwReviewAddIn` | the pane handed the check hosts' holds of an evaluation | 1 |
  | A7 | `SwReviewAddIn.BeginCheck` | the review host's gate asked | 2 |
  | A8 | `TaskPaneControl` | the proxy handed the pane's option | 2 |
  | A9 | `SwReviewAddIn` | the Standards host handed the word on a restart ahead | 1 |
  | A10 | `SwReviewAddIn` | the pane handed the Standards host's hold of an evaluation | 1 |
  | R1 | `RemodelHost.RunRootToUse` | the run root for a new run read once the gate is passed, through the shared reading | 6 |
  | W1 | `review_words_v1.yaml` | `CheckRunning`'s sentence | 5 Python, 1 C# |
  | F1 | `review-send-failure-events.json` | the pin moved to the regenerated fixture | 3 |
  | F2 | `review-waiting.json` | the fixture regenerated with `CheckRunning`'s sentence | 1 Python, 3 C# |

### 158A. A hold on the tool service's attachment holds back a follow for an hour at most, and 152A's two follow rules stand (2026-10-21)

- **Question**: 152A left three things with the owner (152A, above): the extension it made to its
  decision's words, that a start refused for its bridge asks the tool service to follow (Asking the
  tool service to follow, the implementer's extension, put to the owner unnumbered); whether to bound
  a hold in the gate, since nothing did and a holder that never let go would keep the tool service on
  its document for good (owner question 6, from the review of the Codex fixes, N7); and whether to
  follow a configuration switch at the switch (owner question 1).
- **Decision** (owner decision 158A, "2A", 2026-10-21): "152A's bridge questions, test first, with
  adversarial reviews: a start refused for its bridge asking the tool service to follow is
  confirmed; a hold on the attachment gets a generous time limit, logged, so a holder that never lets
  go cannot stop the follow for ever; and a configuration switch is still followed only when a review
  asks."

**1. A start refused for its bridge asks the tool service to follow: confirmed.**

- **What stands**: 152A's extension, now the owner's (the dated note on Asking the tool service to
  follow, above). A start refused `BridgeOnAnotherDocument` - a new review before its run folder is
  made, or any start at its session - asks the gate to follow the active document
  (`ReviewHostOptions.FollowActiveDocument`, the gate's `FollowActiveDocument`); at its session it
  first lets go of the hold it took, which a hold still held would put off a poll.
- **Pinned, unchanged**: `DeferredRestartTests.AStartEndedAtItsSessionLetsGoOfItsHold`, its case "its
  bridge moved", asks the follow once with no hold held (152A's YV3), and section 15's refusal cases
  each ask it once (152A's R7). Both mutations were run again on this branch (E1 and E2, below), red.
- **Nothing changed**, in code or in words.

**2. A hold holds back a follow for an hour at most.**

- **How**: every hold carries its holder's kind and when it was taken, on the gate's clock
  (`ToolServiceGate.HoldAttachment(ToolServiceHolder)`, and `_held`, a list of the holds, in place of
  their count). A follow, as it notes the holds before its busy question, takes out every hold held
  longer than `ToolServiceGate.HoldLimit` (`TakeHoldsPastTheLimit`), says each in the tool-service log
  once its lock is let go, and decides by the holds left, as before: with none it asks the busy
  question, and with one it is busy without asking. A follow owed while a hold holds is looked at
  every second (152A), so a stuck hold is let past within a poll of the limit; with no follow owed
  nothing reads the holds, and a stuck hold holds nothing back until a switch or a review's request
  makes a follow.
- **The limit, and why an hour** (*corrected on the reviews, S1:* first given as three times the
  longest hold, a remodel run's twenty minutes, which bound only its changes): the limit is for the
  holds the busy question cannot see while they hold, and must be well past their own bounds; a
  remodel plan or run is bounded by no time, and the busy question covers it instead.

  | Holder | What bounds its hold | What else keeps the bridge while it holds |
  |---|---|---|
  | A review session's start | `POST /sessions` giving up, the backend client's 30 seconds | nothing, until its session is tracked |
  | A page call that starts a turn | the proxy's 120 seconds | nothing, until the backend has marked its turn running |
  | A remodel plan | no time: its probe, its copy, its dump of the copy, and its plan call, the re-modeler's client's 30 seconds | the busy question, which reads it in progress |
  | A remodel run | no time: the model's judgement turn first, bounded by its steps alone (200 by default), each model call by the provider SDK's 600-second read; then its changes, twenty minutes of wall clock from their start (004, `RemodelLimits.MaxMinutes`), read before each one; the after-dump, which the backend waits up to 600 seconds for and the add-in's dump bounds no further; the verification, the save and the close | the busy question, which reads it in progress |

  An hour is thirty times a turn call's bound and a hundred and twenty times a session start's:
  neither meets it working, and one that never lets go holds the follow back an hour and a poll, not
  for ever. A healthy remodel run can outlast it - a long judgement turn is enough - and its hold is
  then said, which changes nothing, since the Remodel host is busy whenever it holds (A real remodel
  run, below). Shorter - ten minutes would still be five times a turn call - would say the hold of
  every remodel run whose changes alone take that long, burying the line that matters. Longer, a day
  say, would keep the tool service on the old document that long behind a session's start or a turn
  call that will never let go, every review of another document refused `BridgeOnAnotherDocument`
  meanwhile. `TheHoldLimitIsAnHourFarPastTheHoldsTheBusyQuestionCannotSee` reads both bounds from
  their own constants, the clients' `CallTimeout`s, so one raised past a tenth of the limit fails
  there, for the limit to be weighed again.
- **What expiry does not do**: it ends nothing. The gate has no handle on a holder's work and stops
  none, and the hold stays its holder's to let go. It only stops the hold holding back a follow by
  itself, and the follow then asks the busy question as for no hold - so a turn the backend has
  marked running, or a remodel plan or run in progress, still keeps the bridge (*corrected on the
  reviews, R1:* first given as "a turn running", which the busy question sees only once the backend
  has marked it; What is left).
- **A holder that lets go later**: its hold was taken out of the holds when it was ignored, so
  letting it go lets go of nothing - of no other hold, which a count of holds would have let go of in
  its place, the reason the count became a list - and says nothing, its line written when it was
  ignored. Letting it go twice does nothing either, as before. A hold let go past the limit before any
  follow found it was never ignored, and is said nowhere.
- **A real remodel run: not exempt, and needs no exemption** (*corrected on the reviews, S1 and S3:*
  first given as covered by the margin, which it is not, and an exemption as leaving one holder that
  could hold the follow back for ever, which the busy question already does). A run holds through
  `RemodelHostOptions.HoldToolService` from its Start until its session is closed, and the host is
  busy for longer - from before the hold is taken until after it is let go
  (`RemodelHost.RunInProgress`, marked through `RemodelHostOptions.BeginRun`;
  `RemodelHostTests.APlanOrARunTakesItsHoldOnlyOnceTheHostIsBusy`, and 152A's
  `APlanOrARunLetsGoOfItsHoldBeforeItFreesTheHost`) - which the add-in's busy question reads first.
  So whenever a plan or a run holds, the busy question answers busy: past the limit, the hold is
  ignored and said, and the look still finds the run in progress - the bridge is not taken down
  under it, and the switch is followed once it ends
  (`RemodelHostTests.ThroughTheGateARunHeldPastTheHoldLimitIsStillNotTakenDownUnder`). A healthy
  run can outlast the hour (the table above), so its line can be written while it is still going,
  and it says only what is true: the hold no longer holds back the follow by itself. The hold exists
  for the moment the busy question cannot see - a plan or a run that began while it was out (152A's
  X2) - long past by then. An exemption would change only the line. And the limit does not bound a
  plan or a run: one that never ended would hold the follow back through the busy question (What is
  left; owner question 3). A plan is the same: busy through `BeginRun` until the host is free.
- **No race with a new hold**: the limit is each hold's own, from when it was taken, so a hold taken
  the moment another passes the limit holds the bridge - one taken before the follow notes the holds
  is held then, and one taken while its busy question is out is a hold taken since it noted them,
  which keeps the bridge (152A's X2, `FollowNow`, unchanged). Ignoring a hold changes neither the
  count of holds taken nor that check.
- **The clock**: a stopwatch of the gate's own, a clock that only goes forward, so a change of the
  system's time neither ages a hold nor keeps one young; read under the gate's lock, where it waits
  for nothing (145A's and 153A's lock rules, and 155A's lesson in 004 research R18: never wait on
  the SOLIDWORKS application thread while holding a lock). Injectable (`clock`), as the poll's
  `later` is, so the cases decide by the clock they move; and so is the limit (`holdLimit`), so that
  one case can see the gate's own clock age a hold in a quarter of a second. The add-in passes
  neither (pinned from its source).
- **The line**: written to the tool-service log of the attachment the hold was on - the service the
  follow is looking at, which no follow can have replaced while the hold held - beside the line a
  skipped switch writes, since it is a fact about that attachment: `ignoring a hold by a review
  session's start: held for 1:01:01, longer than the 1:00:00 limit, so it no longer holds back
  following the active document by itself; its work is not stopped` (*"by itself" added on the
  reviews:* the busy question still keeps the bridge under a turn the backend has marked running, or
  a remodel plan or run in progress, so the first words were untrue of a Remodel holder). The kind is
  one of three fixed phrases and the times are the gate's own, so no path or document name can reach
  it; the hours run on past a day, and each part is cut, not rounded. Once per hold, outside the lock,
  as the gate's other lines are (pinned on the reviews, S4). Not to the add-in log: nothing failed, and
  the pane has nothing to show the engineer.
- **The holder's kind**: three, one per host the add-in hands the hold to (`ToolServiceHolder`): a
  review session's start (`ReviewSession`), a page call that starts a turn (`TurnCall`), and a Remodel
  plan or run (`Remodel`) - the Remodel host takes its one hold, through one option, for either, and
  the Remodel tab's own records say which was in flight. The add-in names each; the hosts are
  unchanged.
- **What is left** (recorded, not changed):
  - The busy question is not bounded by this decision: a turn the backend says runs, or gives no
    usable answer about (152A's R1), and a remodel plan or run in progress keep a follow owed for as
    long as they do. Each is bounded where it runs, if at all - a turn by the backend; a remodel run's
    changes by the executor's twenty minutes, but not its judgement turn or its after-dump - and the
    Remodel host is busy whenever it holds, so a plan or a run that never ended would hold the follow
    back through the busy question, whatever its hold's limit (*corrected on the reviews, S1 and
    S3*). The decision's words are about holds.
  - A review session's start whose hold is ignored - possible only if `POST /sessions` outlived its
    30 seconds by an hour - has its bridge taken down under its checks if the active document has
    moved on, since its session is not yet tracked for the busy question to see: failed coverage, as
    for any closed pipe, and no other document's evidence. That is the decision's trade: a session's
    start or a turn call that never lets go does not keep the bridge for ever.
  - So can a page call that starts a turn whose hold is ignored - possible only if the call stayed out
    an hour past the proxy's 120 seconds - since it takes its hold before it sends the call
    (`BackendProxyHandler.TryServe`), and the busy question sees its turn only once the backend has
    marked it running: the turn's live calls meet a closed pipe, failed coverage again, and no other
    document's evidence (added on the reviews, R1).
  - While a stuck session start's or turn call's hold holds - an hour at most - a review of another
    document is refused `BridgeOnAnotherDocument` and its request to follow waits; reloading the
    add-in clears it sooner.
- **Owner questions** (recorded 2026-10-21, behaviour as decided):
  1. The hour: kept, or another time? *Asked again on the reviews (S1), with what each holder holds
     for:* the hour bounds the holds the busy question cannot see - a session's start, 30 seconds of
     its own, and a turn call, 120 - far past either. A remodel plan or run holds for no time the
     add-in or the backend bounds - the model's judgement turn, its steps alone, then twenty minutes of
     changes, the after-dump the backend waits ten minutes for, the verification, the save and the
     close - so a healthy run can outlast any limit, and its hold is then said, while the busy question
     keeps the bridge under it whatever the limit. Shorter brings a stuck session start or turn call to
     an end sooner and says more healthy runs' holds; longer, the reverse. Or a limit for those two
     alone, a Remodel plan's or run's hold never said? Kept at an hour meanwhile: the facts move no
     holder the limit protects.
  2. Name a remodel plan and a remodel run apart in the line? The Remodel host takes its one hold
     through one option for either, so the add-in names both "a Remodel plan or run"; telling them
     apart would give the host's hold option the kind, a change to the Remodel host.
  3. Bound the busy question too - a turn the backend says runs, or a remodel run in progress, for
     longer than some time - or leave each to its own bound, as now?
  4. Say an ignored hold somewhere besides the tool-service log - the add-in log, or the pane?
- **Existing cases changed deliberately**: every hold names its holder, so 152A's X2 cases in
  `ToolServiceWiringTests`, `DeferredRestartTests`' three real-gate holds and the Remodel world's hold
  name one, and `TheAddInsReviewSessionsRemodelRunsAndTurnCallsHoldTheBridgeThroughTheGate` pins the
  kind each of the add-in's three wirings names (tightened). What each pinned is unchanged. 152A's
  YG6 - a hold let go twice lets go twice - is an equivalent mutation now (below): a hold is taken
  out of the holds by itself, which lets go once however often it is asked. The guard that makes a
  second letting go do nothing (`Interlocked.Exchange` in `Hold.Dispose`) stays. *Corrected on the
  reviews, S2:* this said `LettingAHoldGoTwiceLetsItGoOnce` still pinned what it pinned, which was
  untrue - its first edit gave the second of its two holds another kind, so a hold let go that let go
  of every hold of its kind passed every case. Its two holds are of one kind again, two turn calls as
  two chats hold, and so are `AHoldLetGoAfterItWasIgnoredLetsGoOfNoOtherHold`'s; that mutation (RS2)
  is red in both.

**3. A configuration switch is followed only when a review asks: confirmed.**

- **What stands**: today's behaviour (152A's owner question 1, settled above). The add-in's one
  fan-out of a document or a configuration change asks the gate to follow by the active document's
  path (`FollowDocument`), and a configuration switch, the same path, re-attaches nothing - at the
  switch, during a start or once a hold ends; the gate follows the active configuration only on a
  review's request (`FollowActiveDocument`), which the review host makes when a start finds its bridge
  on another document or configuration.
- **Pinned**: the gate's half by 152A's `ToolServiceWiringTests.AReviewsRequestFollowsTheActiveConfigurationWhichASwitchAloneDoesNot`
  and `AConfigurationSwitchReattachesNothingWhereverItLands`, and by
  `RemodelHostTests.ThroughTheGateAConfigurationSwitchReattachesNothingAndTellsNothing`. The add-in's
  half had none - a fan-out that asked the gate to follow the active configuration left every case
  green - and has one now, read from its source:
  `ToolServiceWiringTests.TheAddInFollowsAConfigurationSwitchOnlyWhenAReviewAsks`.

**Tests**: T250 and T252 in [tasks.md](tasks.md), written first - but T250's case of every hold past
the limit said at one look, written after and red under HB18 - and T253's named pins.

**Mutations**: each taken out once, by one exact replacement, the tree rebuilt, the tool-service,
restart, review, remodel, context and proxy classes run - `ToolServiceWiringTests`,
`RemodelHostTests`, `DeferredRestartTests`, `ReviewHostTests`, `EngineeringContextHostTests` and
`BackendProxyHandlerTests`, 1,051 cases, 1,052 once the case written after was added - and the file
restored byte for byte (checked by its sha256): the fix's 18 (HB1 to HB18), 74 red results; the
configuration rule's three (C1 to C3), 4; the extension's two, run again (E1, E2), 25; and four of
152A's holds, run again on the list that replaced their count (YG1r, YG4r, YG5r and YG6r) - every
one red but YG6r, equivalent now (above). One full pass under HB6 also failed a case of
`DeferredRestartTests.ARestartThatWaitedAndFailedSaysSavingAgainRetriesIt`, which HB6 cannot reach - it
changes a branch taken only when a hold was ignored, and no hold ages in that class - while other
work loaded the machine; HB6 run again was red in its own five cases alone, and that case passed
then and in every run after, the five below among them. *Corrected on the reviews:* HB1's count is 11
as first run, before the case written after was added; 12 with it, as the reviews counted.

| Id | Taken out | Red |
|---|---|---|
| HB1 | `TakeHoldsPastTheLimit`: no hold is ever past the limit | 11: the stuck hold, the hold at the limit, the line's three kinds, said once, let go after, the two races, the gate's own clock, and the run held past the limit |
| HB2 | a hold that has held the limit exactly is past it too | 1: the hold at the limit |
| HB3 | a hold's age read from the clock's zero, not from when it was taken | 4: the hold at the limit, let go after, and the two races - a hold taken late read as old |
| HB4 | every hold taken out once one is past the limit | 2: let go after, and the race as the follow looks |
| HB5 | an ignored hold left among the holds | 9: the stuck hold, the hold at the limit, the line's three kinds, said once, the two races, and the gate's own clock |
| HB6 | past the limit, the follow made free without the busy question | 5: the stuck hold, the hold at the limit, said once, the race while the question is out, and the run held past the limit |
| HB7 | the line not written | 8: the line's three kinds, said once, let go after, the two races, and the run held past the limit |
| HB8 | the line names the document attached to | 3: the line's three kinds |
| HB9 | the hours wrapped at a day | 1: said once, after 26 hours |
| HB10 | letting go of an ignored hold lets go of another | 1: let go after |
| HB11 | the gate's own clock stands still | 1: the gate's own clock |
| HB12 | the gate's own limit not the hour | 9: the stuck hold, the hold at the limit, the line's three kinds, let go after, the two races, and the run held past the limit |
| HB13 | the hour lowered to thirty minutes | 7: the stuck hold, the line's three kinds, let go after, the limit's value, and the run held past the limit |
| HB14 | the add-in passes a limit of its own | 1: the add-in's gate |
| HB15 | the add-in names a review session's hold as the Remodel host's | 1: the add-in's wiring |
| HB16 | every hold taken at the clock's zero, not when it was taken | 4: the hold at the limit, let go after, and the two races |
| HB17 | every hold named a review session's start, whatever holds | 5: the line's two other kinds, said once, let go after, and the run held past the limit |
| HB18 | the hold after one taken out skipped, left for a later look | 1: every hold past the limit said at one look, written after |
| C1 | the fan-out of a document or configuration change asks the gate to follow the active configuration | 1: the add-in's configuration case |
| C2 | a configuration change also asks the gate to follow the active configuration | 1: as C1 |
| C3 | a switch's follow compares the configuration too (152A's V5, again) | 2: a configuration switch during a start and once a hold ends |
| E1 | a start refused for its bridge asks the follow while it holds (152A's YV3, again) | 1: its bridge moved, the follow asked with no hold held |
| E2 | a start refused for its bridge asks the tool service to follow nothing (152A's R7, again) | 24: section 15's refusal cases and the same starts pressed again, the bridge moved during the extraction, the bridge no hold can be had on, the hold let go before the follow, and the add-in's configuration case, its one other caller gone |
| YG1r | `HoldAttachment`: a hold taken is not among the holds (152A's YG1) | 16: 152A's held-follow cases, the session asked for as a re-attach ends, and 158A's |
| YG4r | `FollowCore`: a hold held when a follow begins is not busy (YG4) | 15: as YG1r, but for the run held past the limit, whose run the busy question still reads |
| YG5r | `LetGo`: a hold let go is still held (YG5) | 23: every case that follows once a hold is let go - 152A's gate cases, the two sessions, T180's four, the plan and run races and the Remodel looks - and 158A's |
| YG6r | `Hold.Dispose`: a hold let go twice lets go twice (YG6) | none: equivalent now |

**Evidence** (2026-10-21, on the branch from `5a58988`): the C# build, `--no-incremental`, at zero
warnings before, after, and once every mutation was restored; `SwReview.Extractor.Tests` 10,086
passed before and after, and `SwReview.AddIn.Tests` 3,540 before and 3,556 after - T250's fifteen
cases and T252's one - `RemodelPageContractTests`, which reads 004's `pane-remodel-messages.md`,
among them; the restart and tool-service classes with the stub-children collection and
`RemodelHostTests` (`DeferredRestartTests`, `OtherTabsBackendRestartTests`,
`ReviewPageBackendRestartTests`, `TabPagesBackendRestartTests`, `ToolServiceWiringTests`,
`InProcPipeServerTests`, `BackendClientSessionBodyTests`, `BackendProcessTests`,
`ProcessLifetimeTests` and `RemodelHostTests`), 1,071 cases, five times in a row. Python, the tests
that read the changed records - `test_workstation_test_plan.py`, which reads every `tasks.md`, and
`test_remodel_client.py`, which reads `bridge-remodel.md` - 308 passed on 3.12 (3.12.3) and on 3.11
(3.11.16, `--isolated`, every extra), with `SWREVIEW_TOKENIZER_DIR` set; no Python changed, and
`ruff check` clean. No broken link, and every changed file `i/lf`.

**4. The reviews (2026-10-21).**

- **What they were**: two independent reviews of the branch at `cdd6749`, by Opus - one led by
  mutation, which ran 39 of its own, and one on races, standing in for Codex, which was at its usage
  limit. Neither found a must-fix, and the race review found no concurrency defect. Their findings,
  settled test first by T255 to T257, are below; what they corrected above is marked where it stands.
- **S1: the hour's margin was wrong for a remodel run.** A run holds from its Start until its session
  is closed (`RemodelHost.Start`, `Execute`'s `finally`), which is the whole backend job: the model's
  judgement turn first, with no time bound of its own - 200 steps by default
  (`swreview.agent.events.DEFAULT_MAX_STEPS`; the remodel route sets no lower cap), each model call on
  the provider SDK's 600-second read - and only then the changes, whose twenty minutes start at
  `apply_changes` and are read before each change; then the after-dump, which the backend waits up to
  600 seconds for (`DEFAULT_PACKAGE_AFTER_TIMEOUT_S`) and the add-in's dump bounds no further, and its
  poll loop none at all; then the verification, the save and the close. `RemodelLimits.MaxMinutes`
  bounds the changes alone, whatever this record said, so a healthy run with a long judgement turn
  can pass the hour and have its hold said. Safety held - the busy question reads the run in
  progress, which the run held past the limit pins. Corrected: the gate's comments, The limit (its
  table now what each holder holds for), A real remodel run, What is left, 004's two notes and T250's
  note; and the limit's case, rewritten to what is true -
  `TheHoldLimitIsAnHourFarPastTheHoldsTheBusyQuestionCannotSee`: a session's start's 30 seconds and a
  turn call's 120, each read from its own constant, a tenth of the limit at most, red when either is
  raised to ten minutes (RS1a, RS1b). Owner question 1 is asked again with what a run holds for. The
  hour is kept: it bounds the holds the busy question cannot see, far past their own bounds, and the
  facts moved none of those.
- **S2: letting go by identity was unpinned for two holds of one kind.** A hold let go that let go of
  every hold of its kind survived every case: the first edit of `LettingAHoldGoTwiceLetsItGoOnce` gave
  its second hold another kind, and this record said the case still pinned what it pinned. Two chats
  can each hold a turn call, and the first let go must not let go of the second (152A's X2). Its two
  holds are of one kind again, and so are `AHoldLetGoAfterItWasIgnoredLetsGoOfNoOtherHold`'s; that
  mutation (RS2) is red in both.
- **S3: the overclaim that no holder can keep the bridge for ever.** The Remodel host is busy from
  before it takes its hold until after it lets it go, so whenever it holds, the busy question answers
  busy: a plan or a run that never ended would hold the follow back through it, and the limit only
  says its hold. "What is left" and owner question 3 said so; the gate's comments, The limit, A real
  remodel run and the checkpoint now agree. The take side was unpinned, the letting go pinned by
  152A's N4 case: `RemodelHostTests.APlanOrARunTakesItsHoldOnlyOnceTheHostIsBusy`, red when the host
  takes it before it is busy (RS3).
- **S4: "written once the lock is let go" was unpinned.** The ignored holds' lines moved under the
  gate's lock passed every case, which would put a tool-service log's write - its own lock and a file
  append - under the lock the SOLIDWORKS application thread takes on every document change (155A's
  lesson, 004 research R18). `AnIgnoredHoldsLineIsWrittenWithTheGatesLockLetGo`: while the line is
  written (`FakeToolService.DuringWriteLog`), a hold asked for on a thread of its own is had at once,
  waited for fifteen seconds at most, and keeps the bridge, a hold taken since the follow noted them;
  red under the lock (RS4).
- **S5: 002's `contracts/pane-host-messages.md` describes the holds** and had no 158A note: it has
  one now, dated; T254's claim that no 002 contract changed is corrected.
- **R1 (race review): a turn call's hold can be ignored before its turn is marked running.** The
  proxy takes its hold before it sends the call (`BackendProxyHandler.TryServe`), and the busy
  question sees a turn only once the backend has marked it running; a call out an hour past its 120
  seconds would lose its bridge. Recorded beside the session's start (What is left), and "a turn
  running" made "a turn the backend has marked running" in the gate's remarks and What expiry does not
  do.
- **R2 (race review): the limit's seam took no time or less.** Refused now when the gate is built,
  `ArgumentOutOfRangeException`, as `DeferredRestart` refuses a poll: none, a tick less, and an hour
  less; a tick's is taken. Red without the refusal (RR2a), with no time let through (RR2b), and with a
  tick's refused (RR2c).
- **Nits**: the extension's ordinal is dropped - 152A numbers its owner questions 1 to 6, and the
  extension went to the owner unnumbered (here, 152A's note and T254); the gate's own clock is pinned
  as a stopwatch from its source, since any clock that moves passed the real-time case, the system's
  time among them (`TheGatesOwnClockIsAStopwatchOfItsOwn`, RE4); the hours are said cut, not rounded,
  1:59:59 (`HowLongAHoldHeldIsSaidCutNotRounded`, RC6a for the hours and RC6b for the seconds); the
  add-in's configuration case reads a method group of `FollowActiveDocument` as well as a call, and no
  comment line (RG2: under it the scan as first written still counts one caller in the add-in, the
  widened one two); the first round's mutation records - HB1's count, the four YG reruns named, the
  flaky restart case named; and the line says the hold no longer holds back the follow "by itself",
  true of every holder, where for a Remodel holder it was not (RW).

- **Tests**: T255 in [tasks.md](tasks.md). Against `cdd6749`, the line's three kinds and the three
  refusals failed; the rest are guards, each red under its mutation below.
- **Mutations**: as before - each taken out once, by one exact replacement, the tree rebuilt, the same
  classes run (1,060 cases), and the file restored byte for byte (checked by its sha256): 14 mutations,
  33 red results, every one red.

  | Id | Taken out | Red |
  |---|---|---|
  | HB1 | no hold is ever past the limit, run again with every case | 15: as before, with the case written after, a tick's limit, the line written with the lock let go, and the hours cut |
  | RS1a | a turn call's own bound raised to ten minutes | 1: the limit's case |
  | RS1b | `POST /sessions`' own bound raised to ten minutes | 1: as RS1a |
  | RS2 | a hold let go lets go of every hold of its kind | 2: let go twice, and let go after it was ignored |
  | RS3 | a plan or a run takes its hold before the host is busy | 1: the take side's case |
  | RS4 | the ignored holds' lines written under the gate's lock | 1: the line written with the lock let go |
  | RR2a | a limit of no time or less taken | 3: the three refusals |
  | RR2b | a limit of no time taken | 1: the refusal of no time |
  | RR2c | a limit of a tick refused too | 1: a tick's limit taken |
  | RE4 | the gate's own clock the system's time | 1: the stopwatch's case - the real-time case passes under it, as the review found |
  | RC6a | the hours rounded | 1: the hours cut |
  | RC6b | the seconds rounded | 1: as RC6a |
  | RW | the line's first words, untrue of a Remodel holder | 3: the line's three kinds |
  | RG2 | the fan-out also hands `FollowActiveDocument` on as a method group | 1: the add-in's configuration case |

- **Evidence** (2026-10-21, on the branch from `cdd6749`): the C# build, `--no-incremental`, at zero
  warnings once every mutation was restored; `SwReview.Extractor.Tests` 10,086 passed, and
  `SwReview.AddIn.Tests` 3,564, from 3,556 - T255's eight new cases, the limit's case rewritten in
  place of its first; the restart and tool-service classes with the stub-children collection and
  `RemodelHostTests`, 1,079 cases, five times in a row. Python, the tests that read the changed
  records - `test_workstation_test_plan.py` and `test_remodel_client.py` - 308 passed on 3.12 (3.12.3)
  and on 3.11 (3.11.16, `--isolated`, every extra); no Python changed. The C# cases that read 002's
  `pane-host-messages.md` and 004's `pane-remodel-messages.md` ran in the full suite. No broken link,
  and every changed file `i/lf`.
