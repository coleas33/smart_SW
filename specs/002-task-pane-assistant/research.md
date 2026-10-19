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
