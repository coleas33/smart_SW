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
