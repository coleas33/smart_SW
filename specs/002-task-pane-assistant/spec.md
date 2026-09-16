# Feature Specification: Task Pane Assistant

**Feature Branch**: `002-task-pane-assistant`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "Task Pane assistant: a SOLIDWORKS Task Pane with a review chat driving the curated design reviewer on OpenAI or Gemini, plus an embedded Codex or Gemini CLI terminal for read-only general chat." Design approved in conversation on 2026-09-13 (reviewer first, general chat read-only, chat panel plus terminal tab, OpenAI default with Gemini, no Claude in the product).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review the Open Assembly from the Task Pane (Priority: P1)

An engineer with an assembly open in SOLIDWORKS opens the SwReview Task Pane, chooses the Review tab, and presses Review. The pane extracts the evidence package from the open document, starts a review session, and shows the investigation as it happens: the assistant's explanations, each tool call with a one-line result, and every finding as a card with status, severity, and the evidence behind it. When the assistant needs an input only the engineer has, the question appears in the chat and the engineer's typed answer lets the review continue. Each finding card has a Show in SOLIDWORKS action that selects and zooms to the affected entity, and Accept, Reject, and Defer actions that record the disposition. The engineer can type follow-up questions about any finding in the same session. The session file and the Markdown report are written to a run folder the pane names.

**Why this priority**: It is the product. Everything in feature 001 exists to feed this screen, and it is the only path that gives an engineer findings without leaving SOLIDWORKS.

**Independent Test**: With the bracket fixture from feature 001 open (`benchmarks/native/bracket-assy/`, prepared by feature 001 task T061; `cover-blind-tap` is a package fixture with no SOLIDWORKS model and cannot be opened as an assembly), press Review with a fake provider selected in a development build. Confirm the pane shows streamed text, tool cards, at least one finding card, an evidence request that the engineer answers in chat, a disposition that appears in the re-rendered report, and that Show in SOLIDWORKS selects the named component.

**Acceptance Scenarios**:

1. **Given** an assembly is open and a provider is configured, **When** the engineer presses Review, **Then** the pane shows extraction progress, then the session's events in order, and the run folder contains `package.json`, `session.json`, and `report.md` when the session ends.
2. **Given** a finding card is displayed, **When** the engineer presses Show in SOLIDWORKS, **Then** the affected component (or the first drawing location's document) is selected and the view zooms to it, and a failure to resolve the reference is shown on the card rather than ignored.
3. **Given** a finding card, **When** the engineer presses Accept, Reject, or Defer and enters a note, **Then** `session.json` records the disposition with the engineer's identity and time, `report.md` is re-rendered, and the card shows the disposition.
4. **Given** the assistant issued an evidence request, **When** the engineer types an answer, **Then** the request is marked answered with the text, the session resumes with that answer visible to the assistant, and any finding that was unresolved only because of that request is re-evaluated in the same session.
5. **Given** a completed session, **When** the engineer types a follow-up question, **Then** the assistant answers within the same session using the same tools, and the new steps are appended to `session.json`.
6. **Given** no document is open, **When** the engineer presses Review, **Then** the pane says so and nothing is extracted or started.

---

### User Story 2 - Choose and Configure the Model Provider (Priority: P2)

The engineer opens the Settings section of the Review tab, chooses OpenAI (the default) or Gemini, picks a model from the provider's list, enters an API key, and saves. The key is stored for that Windows user only and never appears in logs, session files, or reports. The same provider choice is available to the command line and the benchmark runner so a review run on the workstation and a benchmark run on another machine use the same loop.

**Why this priority**: Without a working provider the review cannot run, and this build targets OpenAI and Gemini only, and that has to be enforced by construction, not by convention.

**Independent Test**: Save OpenAI settings with a key, run a review against a recorded OpenAI exchange, then switch to Gemini with a recorded Gemini exchange, and confirm both produce the same session structure. Confirm the key is absent from every file the run writes and from the pane's log.

**Acceptance Scenarios**:

1. **Given** no settings exist, **When** the engineer presses Review, **Then** the Settings section opens with OpenAI preselected and Review does not start until a key is saved.
2. **Given** settings are saved, **When** the pane restarts, **Then** the provider, model, and key are restored for the same Windows user and are unreadable by other users.
3. **Given** an invalid or revoked key, **When** a review starts, **Then** the pane shows an authentication error naming the provider and offers to open Settings; no partial session is left without an ended time.
4. **Given** the command line, **When** the engineer runs a review with `--provider gemini`, **Then** the same tools, checklist, and session format are used as in the pane.

---

### User Story 3 - General Chat in an Embedded Terminal (Priority: P3)

The engineer switches to the Terminal tab, picks Codex or Gemini, and gets that CLI running inside the Task Pane in the current run folder. The CLI can inspect the open assembly through the same read-only tools the reviewer uses (queries over the extracted package, measurements, captures), and cannot run shell commands, modify the SOLIDWORKS model, save documents, or write files. The Codex CLI ships first; the Gemini CLI terminal is deferred to a later verification on the workstation (Gemini remains a review-mode provider). The engineer can ask anything: "what is the heaviest part", "show me the mates on the cover", "screenshot the screw pattern".

**Why this priority**: It is the second half of the request and the fastest way for an engineer to ask ad hoc questions, but it depends on the tool server and the bridge from the first two stories.

**Independent Test**: Launch Codex in the Terminal tab with the generated profile, ask it to list the components of the open assembly and capture the first one; confirm the answer came through our tool (the tool call is visible in the CLI and recorded in the run folder), and that an attempt to run a write command is refused by the CLI's sandbox.

**Acceptance Scenarios**:

1. **Given** Codex or Gemini is installed, **When** the engineer chooses it and presses Start, **Then** the CLI appears in the pane with our tool server connected and the run folder as its working directory.
2. **Given** the CLI is running, **When** the engineer asks a question that needs the model, **Then** the CLI answers through our read-only tools, and every tool call is recorded in the run folder's chat log.
3. **Given** the CLI is running, **When** the model attempts a file write or a shell command, **Then** the CLI refuses it under the generated profile (the tools are not offered) and the engineer sees the refusal.
4. **Given** the chosen CLI is not installed, **When** the engineer presses Start, **Then** the pane shows the install steps and the version requirement instead of an empty terminal.
5. **Given** the pane is resized, **When** the terminal is visible, **Then** the terminal reflows to the new size without losing scrollback.

---

### User Story 4 - Live SOLIDWORKS Actions from Both Modes Without a Second Attach (Priority: P4)

Captures, measurements, interference runs, and Show in SOLIDWORKS requested by the review chat or by the terminal CLI execute inside the running SOLIDWORKS session that hosts the pane. No separate console process, no second SOLIDWORKS attach, and no possibility of the pane driving a different session than the one on screen.

**Why this priority**: It removes the biggest test-day failure mode in feature 001 (a bridge attached to the wrong session) and makes captures appear inline, but the first three stories can be demonstrated with the existing console bridge.

**Independent Test**: With the pane open, request a capture from the review chat and a measurement from the terminal CLI; confirm both files land in the run folder, both were served by the add-in's own dispatcher (its log shows them), and closing the pane stops the service.

**Acceptance Scenarios**:

1. **Given** the pane is open, **When** either mode requests a capture, measurement, or interference run, **Then** it is served by the add-in in the SOLIDWORKS process on the application thread and the result names the document and configuration on screen.
2. **Given** a request arrives while another is running, **When** the second is queued, **Then** it runs after the first completes and neither corrupts the other's result.
3. **Given** three consecutive failures on SOLIDWORKS calls, **When** a fourth request arrives, **Then** it is refused with a circuit-open error and appears as failed coverage, as in feature 001.
4. **Given** the add-in unloads, **When** SOLIDWORKS closes, **Then** the tool service and any backend process it started are stopped and no orphan process remains.

---

### Edge Cases

- Provider returns a tool call for a tool that does not exist or with arguments that fail validation: the error is returned to the model as a tool error, recorded as failed coverage, and shown in the chat; the session continues.
- Provider rate limit or network failure mid-session: the pane shows the error class, keeps the partial session on disk with an ended time (the runner finalizes on the failure path, not only on the success path), and offers Retry, which starts a new session in a new run folder carrying `retry_of` = the failed session's id (FR-028).
- The engineer closes the document while a review runs: the review continues on the extracted package; any live action fails with a clear "document no longer open" error and becomes failed coverage.
- Two Task Pane instances (two SOLIDWORKS windows): each add-in instance owns its own tool service and backend on distinct ports and pipes.
- API key present in environment variables and in settings: settings win, and the pane says which source it used.
- Model id no longer offered by the provider: the pane shows the provider's error and the model list is refreshed from the provider.
- The CLI is installed but its version is older than the minimum: the pane shows the installed and required versions.
- The CLI's generated profile is edited by the engineer: the pane regenerates it on every launch and shows a warning if a restriction key was missing or changed.
- WebView2 runtime missing: the pane shows the download link and a plain-text fallback with the run folder path; nothing else breaks.
- Gemini's tool naming limits: tool names are kept under the length limit and the server name has no underscores so every tool is reachable.
- A finding references a component whose persistent reference no longer resolves after a rebuild: Show in SOLIDWORKS reports the resolution state code and offers the component's full path instead.
- Very long sessions: the transcript view keeps the last 500 events in memory and the full stream on disk.
- Model- or document-authored text containing markup (a finding title with `<img src=x onerror=...>`, a drawing note read as `</script>`): both pages insert every untrusted string as text, never as markup, and the strict Content-Security-Policy and navigation blocking in `contracts/pane-host-messages.md` make an injected element inert. The pane holds the backend token and can invoke `settings.save` and the shell openers, so this is a first-class boundary, not a cosmetic concern.
- A turn that ends on the provider's output ceiling (reasoning plus text exceeding `max_output_tokens`): the turn ends with reason `truncated`, the partial answer stays visible, and the unfinished work is recorded as unresolved coverage rather than reported as a completed check.
- The engineer saves Settings while a turn is running: the save is refused with a clear message rather than restarting the backend and killing the live session; it is offered again when the turn ends.
- The Terminal tab is opened before any review: the host creates a terminal run folder under the run root so the CLI, its generated profile, and `chat-log.jsonl` have a home.

## Requirements *(mandatory)*

### Functional Requirements

**Task Pane**

- **FR-001**: The add-in MUST present a Task Pane with a Review tab, an Ask tab (the CLI terminal) and an Extract tab, each carrying a one-line statement of what it is for; MUST show, above the tabs and at all times, the three steps (open a document, extract evidence, review or ask) with each one marked done or pending and the reason it is pending; and MUST keep the existing extract-evidence, Interference, and Capture selection actions available on the Extract tab.
- **FR-002**: The Review tab MUST show, as they occur, the assistant's text, each tool call with its recorded step summary and status, each finding, each evidence request, and coverage changes.
- **FR-003**: Each finding MUST be shown with its status, severity, title, affected components or drawing locations, and a Show in SOLIDWORKS action; expanding the card MUST reveal the full finding fields defined in feature 001.
- **FR-004**: The pane MUST let the engineer record a disposition (accepted, rejected, deferred) with a note on any finding, and MUST persist it to the session file and re-render the report.
- **FR-005**: The pane MUST let the engineer answer an open evidence request in the chat and MUST resume the session with that answer.
- **FR-006**: The pane MUST accept follow-up messages in an existing session and MUST append the resulting steps and findings to the same session file.
- **FR-007**: The pane MUST extract the open document into the run folder before starting a review and MUST refuse to start when no document is open.
- **FR-008**: The pane MUST show every error with its class and a next action (retry, open settings, view log) and MUST never leave a session without an ended time.

**Provider layer**

- **FR-009**: The review loop MUST run on OpenAI or Google Gemini through one provider interface; no other model provider MAY be used in product code, and the Anthropic SDK MUST NOT be a dependency.
- **FR-010**: OpenAI MUST be the default provider; the engineer MUST be able to select Gemini.
- **FR-011**: Tool definitions MUST be generated from the existing tool functions' signatures and docstrings, MUST be strict for OpenAI (no additional properties, all properties required, optional expressed as nullable), and MUST be adapted for Gemini's schema subset without loss of validation on our side.
- **FR-012**: Every tool call from either provider MUST pass through the same argument validation, step recording, and error-to-result conversion as in feature 001.
- **FR-013**: The provider layer MUST emit a uniform event stream (text delta, tool call started, tool call finished, finding recorded, evidence request opened, coverage changed, session ended, error) that both the pane and the command line consume.
- **FR-014**: Reasoning effort MUST be mapped to each provider's own control, and the mapping MUST be recorded in the session.
- **FR-015**: API keys MUST be stored per Windows user with operating-system protection, MUST never be written to session files, reports, logs, or the run folder, and MUST be redacted from any error text.
- **FR-016**: The command line and the benchmark runner MUST accept `--provider` and `--model` and MUST produce the same session format as the pane.

**Tool service and bridge**

- **FR-017**: The add-in MUST host the capture, measure, and interference dispatcher in the SOLIDWORKS process and MUST execute every SOLIDWORKS call on the application thread, serializing concurrent requests.
- **FR-018**: The dispatcher MUST keep the read-only guard and the circuit breaker from feature 001; no request MAY invoke a mutating SOLIDWORKS member.
- **FR-019**: The pane MUST start the Python backend and the tool service with per-instance addresses and a per-launch secret, MUST bind to loopback only, and MUST stop both when the add-in unloads.

**General chat**

- **FR-020**: The Terminal tab MUST run the chosen CLI (Codex or Gemini) inside the pane with the run folder as its working directory and MUST reflow on resize.
- **FR-021**: The pane MUST generate the CLI's profile on every launch such that our tool server is registered, file writes are refused, the CLI's shell and file-editing tools are disabled, and SOLIDWORKS and the run folder are reachable only through our tools; the profile MUST be regenerated even if the engineer edited it.
- **FR-022**: The tool server exposed to the CLI MUST offer exactly the read-only subset of the feature 001 contract (package query tools, measurement tools, `request_capture`, and the bridge capture and measure tools) and MUST record every call in a chat log in the run folder.
- **FR-023**: The pane MUST detect a missing or too-old CLI before launch and MUST show the install steps and versions.

- **FR-030**: The pane MUST let the engineer stop a running turn; the turn ends at the next tool boundary and the session records `turn.ended` with reason `stopped`.

**Boundaries**

- **FR-024**: Neither mode MAY modify, rebuild, or save any SOLIDWORKS document.
- **FR-025**: The general chat MUST NOT be able to create findings or dispositions; those come only from the review session's tools and the engineer's actions.
- **FR-026**: No Claude or Anthropic path MAY exist in product code, configuration, or documentation for this feature. In particular no module-level default model id naming a Claude model MAY remain in the Python package; defaults come from the provider settings module.
- **FR-027**: The scripted `fake` provider MUST be selectable and persistable as a provider in a development build so the pane is demonstrable without keys, and a release build MUST refuse to load a settings file that names it, falling back to the default provider with a visible error, so a shipped configuration can never produce fabricated findings.
- **FR-028**: When a session fails, the pane MUST offer Retry, and the session Retry starts MUST record the failed session's id so the two are linked in the run artifacts.
- **FR-029**: Both WebView2 pages MUST insert model- and document-authored text as text rather than markup, MUST run under a restrictive Content-Security-Policy, and MUST refuse navigation outside the add-in's virtual host.

### Key Entities

- **Chat Session**: One conversation in the Review tab bound to one run folder and one feature 001 review session; holds the ordered event stream, the provider and model used, and the run folder path.
- **Chat Event**: A typed, timestamped item in the stream: text delta, tool call started, tool call finished, finding, evidence request, evidence answered, disposition, coverage, error, ended.
- **Provider Settings**: Provider name, model id, effort, key reference, and the source the key came from; stored per Windows user.
- **Tool Service**: The in-process dispatcher endpoint (pipe name, secret, log path) that both modes use for live SOLIDWORKS actions.
- **Backend Process**: The Python process the pane starts; its port, token, log path, and health.
- **Terminal Session**: The embedded CLI process: which CLI, version, profile path, working directory, pseudo-console size.
- **Tool Server Profile**: The generated CLI configuration that registers our tool server and applies the read-only restrictions; regenerated per launch.
- **Chat Log**: The run folder record of every tool call the general chat made, with arguments, result summary, and status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From pressing Review on a 200-component assembly to the first finding card is under 3 minutes on the pilot workstation, with extraction itself under 1 minute.
- **SC-002**: Streamed text appears in the pane within 2 seconds of the provider producing it, measured with the fake provider.
- **SC-003**: 100% of tool calls made in either mode are recorded in the run folder (session steps for review, chat log for general chat); an audit finds none missing.
- **SC-004**: Zero mutating SOLIDWORKS calls occur across a full review session and a 30-minute general chat session, verified against artifacts that exist: no `MutatingCallError` refusal appears in the tool-service request log under `%LOCALAPPDATA%\SwReview\logs`, every interop member that log records for those requests is in the reader set, and every tool call appears in `session.json` steps or `chat-log.jsonl`.
- **SC-005**: Switching provider between OpenAI and Gemini produces session files that validate against the same contract and differ only in provider, model, and effort mapping fields.
- **SC-006**: API keys never appear in any file under the run folder or the log folder across the test suite and the manual scenarios; an automated scan confirms it.
- **SC-007**: Show in SOLIDWORKS selects the correct entity for 100% of findings on the bracket fixture whose persistent references resolve, and reports the resolution state for those that do not.
- **SC-008**: An engineer can start general chat, ask one question, and receive an answer that used one of our tools in under 2 minutes from opening the tab.
- **SC-009**: The existing feature 001 test suite passes unchanged in behavior after the provider port, with the Anthropic dependency removed.

SC-001, SC-002, SC-007 and SC-008 are wall-clock or per-finding measurements: each is timed
during the quickstart scenario named beside it and written into the metric table in
`benchmarks/native/bracket-assy/notes.md` by tasks T044, T051 and T063. A criterion with no
recorded number is not met.

## Assumptions

- The workstation runs Windows 11 with the WebView2 runtime installed (it is present on the development machine) and SOLIDWORKS 2024 SP5.
- The operator supplies OpenAI and Gemini API keys for review mode, and Codex CLI (and later Gemini CLI) signed in with their own accounts for general chat; the pane never performs a sign-in flow itself.
- Model lists are read from each provider at settings time; the defaults ship with the current OpenAI general model and Gemini's current flash model, and are overridable.
- Codex's `apply_patch` cannot be disabled by configuration; its writes are blocked by the read-only sandbox, which is accepted for v1.
- Gemini's core-tool allowlist semantics are uncertain; the policy engine's deny-all rule with an allow for our server is the enforced restriction, and the allowlist is belt and braces.
- The terminal embedding reimplements the public ConPTY and xterm.js mechanism; no code is copied from SwpilotCLI, whose license forbids redistribution.
- Session resume for the CLIs (Codex `resume`, Gemini `--resume`) is available to the engineer inside the terminal but not surfaced in the pane in v1.
- Gemini via the enterprise platform (Vertex) is supported through the same SDK flag but is not tested in v1.
- The chat transport is loopback HTTP with server-sent events; a WebSocket is not needed for a single-user pane. The pages read the event stream with `fetch` plus a stream reader, because `EventSource` cannot send the `Authorization` header and the token may never appear in a URL.
- The bracket fixture (`benchmarks/native/bracket-assy/`) is prepared on the workstation by feature 001 task T061 and is not committed to the repository; the workstation scenarios depend on that task being done first.
- The Gemini CLI settings-home override is not yet verified on the workstation; `contracts/cli-profiles.md` marks the Gemini launch mechanism as unverified until the spike task confirms it, and the terminal fails closed rather than starting an unrestricted CLI.
- The general-chat CLI can read its own generated profile, so it can read the bridge secret in that profile's environment block. This is accepted because that secret is scoped to `ping`, `capture` and `measure` at the dispatcher, all of which the CLI already reaches through the MCP toolset; a leak grants nothing beyond the published read-only subset.
- Codex's read-only shell remains enabled for reading the run folder; the exception to the constitution's curated-toolset rule is recorded in the plan's Complexity Tracking table.
