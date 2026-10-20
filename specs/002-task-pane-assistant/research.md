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
- **Owner questions** (recorded 2026-10-19, behaviour unchanged):
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
     would also refuse a review whose stream was removed by hand.
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
