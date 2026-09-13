# smart_SW: SOLIDWORKS agentic design review pilot

An assistant that investigates SOLIDWORKS assemblies and drawings, gathers engineering
evidence through a curated tool set, runs deterministic checks, and writes a findings
report an engineer can verify and disposition. Numbers come from checked code; the language
model decides what to investigate and explains, never computes a verdict.

The design documents live in `specs/001-agentic-design-review/` (spec, plan, research,
data model, contracts, quickstart, tasks) and the governing rules in
`.specify/memory/constitution.md`. `README-complete.md` is the original pilot proposal and
`sw-review-architecture-proposal.md` the architecture decision record.

## Layout

```text
extractor/    C# (.NET Framework 4.8, x64): SOLIDWORKS 2024 add-in, console host, IR dump,
              interference, captures. Only this tree touches the SOLIDWORKS API.
reviewer/     Python 3.11+ (uv): IR models, units, ingest of exported files, deterministic
              checks, curated agent tools, Claude tool-runner loop, report, benchmarks.
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

See `specs/001-agentic-design-review/quickstart.md` for the validation scenarios. The main
entry points are `swreview` (Python CLI: `validate`, `ingest`, `review`, `report`,
`disposition`, `check`, `benchmark`) and `swreview-extract` (C# console: `dump`,
`interference`, `capture`, `resolve`, `serve`). The review loop needs `ANTHROPIC_API_KEY`
or an `ant auth login` profile.

## Spec Kit

This repository was initialized with GitHub Spec Kit. In Claude Code, the workflow skills
are `/speckit-constitution`, `/speckit-specify`, `/speckit-plan`, `/speckit-tasks`,
`/speckit-implement`, `/speckit-converge`, plus `/speckit-clarify`, `/speckit-analyze`,
and `/speckit-checklist`.
