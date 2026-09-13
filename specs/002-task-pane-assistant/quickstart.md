# Quickstart: Validating the Task Pane Assistant

**Feature**: `002-task-pane-assistant` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

## Prerequisites

| Need | For | Notes |
|------|-----|-------|
| Everything in feature 001's quickstart | all | Extractor built, reviewer synced, add-in registered. |
| WebView2 runtime | Review and Terminal tabs | Present on the development machine (152.x). |
| `OPENAI_API_KEY` or a key entered in Settings | Scenario 2 | Gemini needs `GEMINI_API_KEY`. |
| Codex CLI on PATH (ChatGPT sign-in) and/or Gemini CLI (Node 22) | Scenario 3 | `codex --version`, `gemini --version`. |
| One assembly open in SOLIDWORKS | Scenarios 1, 3, 4 | The bracket fixture `benchmarks/native/bracket-assy/`, prepared on the workstation by **feature 001 task T061** (SOLIDWORKS files are not committed). Do that task first if the folder is empty. |
| A development build of the add-in | Scenario 1 | The `fake` provider is offered in the Settings provider list only in a development build (FR-027). |

Setup:

```powershell
cd reviewer
uv sync --all-extras
uv run pytest                      # provider adapters, chat server, MCP server, schema tests
cd ..
dotnet build extractor\SwReview.sln -c Release
dotnet test  extractor\SwReview.sln -c Release
# register the add-in as in feature 001 (elevated regasm); restart SOLIDWORKS
```

## Scenario 1 (US1): Review from the pane with the fake provider

1. In Settings choose provider `fake` (offered by development builds only), save.
2. Open the bracket assembly, press Review. **Start a stopwatch when you press Review.**

Expected: status shows extracting, then backend starting, then the event stream; at least
one finding card; an evidence request that you answer in the chat and that resumes the
turn, after which any finding that was unresolved only because of that request shows a
single re-evaluated verdict, not two; Accept on a finding writes the disposition into
`<run>/session.json` and re-renders `<run>/report.md`; Show in SOLIDWORKS selects the
component; a follow-up question on the already-ended session appends steps to the same
session. `events.jsonl` validates against `contracts/chat-events.schema.json`.

Record in the metric table in `benchmarks/native/bracket-assy/notes.md`: component count,
seconds from pressing Review to extraction complete (SC-001, under 60), seconds to the first
finding card (SC-001, under 180), seconds from the first `text.delta` in `events.jsonl` to
the text appearing in the pane (SC-002, under 2), and the count of findings whose Show in
SOLIDWORKS selected the right entity out of those whose persistent references resolve
(SC-007, expect all of them) with the state code and full path shown for any that do not.

## Scenario 2 (US2): OpenAI and Gemini

1. Settings: provider OpenAI, pick a model from the list, paste the key, save. Press Review.
2. Repeat with Gemini.
3. While a turn is running, press Save in Settings once.

Expected: both runs produce `session.json` files that validate against the feature 001
contract and differ only in `provider_info`; the key is absent from every file under the run
folder and the log folder (`uv run swreview audit-secrets <run> <logs>` reports none - this
shell holds no key, so the check is carried by the provider-shaped detectors, and the command
exits non-zero if it has neither a key nor detectors to work with); an invalid key produces
an authentication error card with an Open Settings action and the failed session still has a
non-null `ended_at`; the save attempted during a running turn is refused with a clear message
instead of restarting the backend and killing the session.

## Scenario 3 (US3): General chat in the terminal

1. Open the Terminal tab **before** running a review, choose Codex, Start.
2. Ask: "List the components of the open assembly and capture the first screw."
3. Refusal probe: ask it to create a file in the run folder, then to run a shell command.
4. Gemini: deferred (decision 2026-09-13); repeat 1 to 3 with Gemini only after T055a.

Expected: a terminal run folder `<run_root>/<timestamp>-terminal` is created and is the CLI's
working directory; the CLI starts with exactly the `swreview` allowlist listed (a missing or
extra tool stops the session rather than warning); the Codex sign-in still works from the
generated `CODEX_HOME`; the answer comes through our tools (the chat log count on the tab
increments, `<run>/chat-log.jsonl` records the calls, including any call that failed, with
`status: "error"`); both probe attempts are refused because no shell or write tool is offered, and the
refusal text is pasted into the notes file; resizing the pane reflows the terminal and typing feels immediate; Stop ends the
process with no orphan.

Record in the notes metric table: seconds from opening the Terminal tab to an answer that
used one of our tools (SC-008, under 120).

## Scenario 4 (US4): In-process tool service

1. With the pane open and no console `serve` running, press Show in SOLIDWORKS on a finding,
   then ask the terminal CLI for a measurement between two persistent references.

Expected: both are served by the add-in (its log under `%LOCALAPPDATA%\SwReview\logs` shows
the requests with elapsed times); the result names the on-screen document and configuration;
after three forced failures (test hook `--fail-bridge 3` on the backend) the fourth request
is refused with circuit-open; closing SOLIDWORKS leaves no `python` or CLI process behind.

SC-004 audit, at the end of a full review plus a 30-minute general chat session: the
tool-service log contains no `MutatingCallError` refusal and no gated interop member outside
the reader set, and every tool call appears in `session.json` steps or `chat-log.jsonl`
(SC-003). Ask the terminal CLI for an interference run: it is refused `unauthorized`, because
the general-chat secret is not scoped for it. Record both results in the notes file.

## Regression gate (every change)

```powershell
cd reviewer && uv run pytest -q && uv run ruff check src tests
cd ..\extractor && dotnet test SwReview.sln -c Release
```

Feature 001 golden baselines must not change; `test_schema_sync` and the review-session
contract tests must pass with `provider_info` present.
