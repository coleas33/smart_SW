# Quickstart: Validating the Task Pane Assistant

**Feature**: `002-task-pane-assistant` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

## Prerequisites

| Need | For | Notes |
|------|-----|-------|
| Everything in feature 001's quickstart | all | Extractor built, reviewer synced, add-in registered. |
| WebView2 runtime | Review and Terminal tabs | Present on the development machine (152.x). |
| `OPENAI_API_KEY` or a key entered in Settings | Scenario 2 | Gemini needs `GEMINI_API_KEY`. |
| Codex CLI on PATH (ChatGPT sign-in) and/or Gemini CLI (Node 22) | Scenario 3 | `codex --version`, `gemini --version`. |
| One assembly open in SOLIDWORKS | Scenarios 1, 3, 4 | The bracket fixture from feature 001. |

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

1. In Settings choose provider `fake` (development builds only), save.
2. Open the bracket assembly, press Review.

Expected: status shows extracting, then backend starting, then the event stream; at least
one finding card; an evidence request that you answer in the chat and that resumes the
turn; Accept on a finding writes the disposition into `<run>/session.json` and re-renders
`<run>/report.md`; Show in SOLIDWORKS selects the component; a follow-up question appends
steps to the same session. `events.jsonl` validates against `contracts/chat-events.schema.json`.

## Scenario 2 (US2): OpenAI and Gemini

1. Settings: provider OpenAI, pick a model from the list, paste the key, save. Press Review.
2. Repeat with Gemini.

Expected: both runs produce `session.json` files that validate against the feature 001
contract and differ only in `provider_info`; the key is absent from every file under the run
folder and the log folder (`uv run swreview audit-secrets <run> <logs>` reports none); an
invalid key produces an authentication error card with an Open Settings action.

## Scenario 3 (US3): General chat in the terminal

1. Terminal tab, choose Codex, Start. Then ask: "List the components of the open assembly and
   capture the first screw."
2. Ask it to create a file in the run folder.

Expected: the CLI starts in the run folder with `swreview` tools listed; the answer comes
through our tools (the chat log count on the tab increments, `<run>/chat-log.jsonl` records
the calls); the write attempt is refused by the sandbox; resizing the pane reflows the
terminal; Stop ends the process with no orphan. Repeat with Gemini.

## Scenario 4 (US4): In-process tool service

1. With the pane open and no console `serve` running, press Show in SOLIDWORKS on a finding,
   then ask the terminal CLI for a measurement between two persistent references.

Expected: both are served by the add-in (its log under `%LOCALAPPDATA%\SwReview\logs` shows
the requests with elapsed times); the result names the on-screen document and configuration;
after three forced failures (test hook `--fail-bridge 3` on the backend) the fourth request
is refused with circuit-open; closing SOLIDWORKS leaves no `python` or CLI process behind.

## Regression gate (every change)

```powershell
cd reviewer && uv run pytest -q && uv run ruff check src tests
cd ..\extractor && dotnet test SwReview.sln -c Release
```

Feature 001 golden baselines must not change; `test_schema_sync` and the review-session
contract tests must pass with `provider_info` present.
