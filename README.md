# smart_SW: SOLIDWORKS agentic design review pilot

An assistant that investigates SOLIDWORKS assemblies and drawings, gathers engineering
evidence through a curated tool set, runs deterministic checks, and writes a findings
report an engineer can verify and disposition. Numbers come from checked code; the language
model decides what to investigate and explains, never computes a verdict.

The design documents live in `specs/001-agentic-design-review/` (spec, plan, research,
data model, contracts, quickstart, tasks), the Task Pane assistant that runs the reviewer
from inside SOLIDWORKS in `specs/002-task-pane-assistant/`, and the governing rules in
`.specify/memory/constitution.md`. `README-complete.md` is the original pilot proposal and
`sw-review-architecture-proposal.md` the architecture decision record.

## Layout

```text
extractor/    C# (.NET Framework 4.8, x64): SOLIDWORKS 2024 add-in, Task Pane (Review and
              Terminal tabs), console host, IR dump, interference, captures. Only this
              tree touches the SOLIDWORKS API.
reviewer/     Python 3.11+ (uv): IR models, units, ingest of exported files, deterministic
              checks, curated agent tools, a provider-neutral tool-runner loop (OpenAI or
              Gemini), the Task Pane chat backend, the read-only MCP toolset, report,
              benchmarks.
benchmarks/   Review packages, native CAD inputs, answer keys (never readable by the
              reviewer), benchmark sets.
specs/        Spec Kit artifacts for each feature.
```

## Build and test

Python reviewer (any OS):

```powershell
cd reviewer
uv sync --all-extras          # add --reinstall-package swreview if "No module named swreview"
uv run pytest                 # unit + golden tests; integration tests skip without a native package
uv run ruff check src tests
```

C# extractor (Windows with SOLIDWORKS 2024 installed; interop DLLs are read from
`C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist`, override with `-p:SwRedist=...`):

```powershell
dotnet build extractor\SwReview.sln -c Release
dotnet test  extractor\SwReview.sln -c Release
```

## Run

See `specs/001-agentic-design-review/quickstart.md` for the validation scenarios and
`specs/002-task-pane-assistant/quickstart.md` for the Task Pane ones. The main entry points
are `swreview` (Python CLI: `validate`, `ingest`, `review`, `report`, `disposition`,
`check`, `benchmark`, plus `chat serve` for the Task Pane backend, `mcp` for the read-only
toolset an external CLI connects to, and `audit-secrets`) and `swreview-extract` (C#
console: `dump`, `interference`, `capture`, `resolve`, `serve`).

The review loop runs on OpenAI by default, or on Gemini with `--provider gemini`. It needs
`OPENAI_API_KEY`, or `GOOGLE_API_KEY` (`GEMINI_API_KEY` is read second) for Gemini. Inside SOLIDWORKS the key comes from the pane's settings instead,
DPAPI-protected under `%APPDATA%\SwReview\settings.json`, and reaches the backend only
through its environment block: it is never a command-line argument, and `swreview
audit-secrets <run> <logs>` is the check that it never reached a file.

Command-line contracts: `specs/001-agentic-design-review/contracts/cli.md`.

## Spec Kit

This repository was initialized with GitHub Spec Kit. The workflow skills are
`/speckit-constitution`, `/speckit-specify`, `/speckit-plan`, `/speckit-tasks`,
`/speckit-implement`, `/speckit-converge`, plus `/speckit-clarify`, `/speckit-analyze`,
and `/speckit-checklist`.
