# smart_SW: SOLIDWORKS agentic design review pilot

An assistant that investigates SOLIDWORKS assemblies and drawings, gathers engineering
evidence through a curated tool set, runs deterministic checks, and writes a findings
report an engineer can verify and disposition. Numbers come from checked code; the language
model decides what to investigate and explains, never computes a verdict.

The design documents live in `specs/001-agentic-design-review/` (spec, plan, research,
data model, contracts, quickstart, tasks), the Task Pane assistant that runs the reviewer
from inside SOLIDWORKS in `specs/002-task-pane-assistant/`, the Resilient Modeling checks
and the Model check tab in `specs/003-resilient-modeling/`, the Standards check tab in
`specs/006-standards-check/`, and the governing rules in
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
`check`, `rms`, `benchmark`, plus `chat serve` for the Task Pane backend, `mcp` for the
read-only toolset an external CLI connects to, and `audit-secrets`) and `swreview-extract`
(C# console: `dump`, `interference`, `capture`, `resolve`, `serve`, `probe rms`,
`suppress-test`).

The review loop runs on OpenAI by default, or on Gemini with `--provider gemini`. It needs
`OPENAI_API_KEY`, or `GOOGLE_API_KEY` (`GEMINI_API_KEY` is read second) for Gemini. Inside SOLIDWORKS the key comes from the pane's settings instead,
DPAPI-protected under `%APPDATA%\SwReview\settings.json`, and reaches the backend only
through its environment block: it is never a command-line argument, and `swreview
audit-secrets <run> <logs>` is the check that it never reached a file.

Command-line contracts: `specs/001-agentic-design-review/contracts/cli.md`.

Installing, updating and checking the add-in on the pilot workstation, including where the
per-machine files live and how findings come back: `docs/workstation-runbook.md`.

## Resilient Modeling checks

A second family of findings, deterministic like the first and with no language model
anywhere in it: does the part's feature tree follow the Resilient Modeling convention -
the six ordered group folders `1-Ref`, `2-Construction`, `3-Core`, `4-Detail`,
`5-Modify`, `6-Quarantine` - and are the references between features the ones that survive
an edit? The rules grade what the extractor read (`features[]`, `equations[]`, mates,
component instances); a rule with no evidence to read is reported as unresolved coverage,
never as a pass. The catalogue is `specs/003-resilient-modeling/contracts/rules.md` and
the feature type tables are `reviewer/src/swreview/checks/rms_types.yaml`.

```powershell
swreview-extract dump --out <package dir>            # --features tree --equations on
swreview check rms --package <package dir> --out <run dir>   # findings, coverage; session.json, report.md, check.json into <run dir>
swreview rms types --package <package dir>           # type names the tables do not classify
```

One rule cannot be answered from a static dump: whether a Detail feature can be suppressed
on its own without breaking the rebuild. `swreview rms suppress-plan` writes the plan -
which features, in which order, in which configuration - and the engineer runs
`swreview-extract suppress-test` against the open document to carry it out. That command is
the only mutation path in this product: it is acknowledged on the command line, guarded,
restores the tree, never saves, and is not reachable from the pane, the bridge or the MCP
toolset. `benchmarks/README.md` has the workflow end to end.

The **Model check tab** is the same checks from inside SOLIDWORKS: it dumps the active
document with `--profile model-check` (features and equations only, so it is seconds rather
than a full extract), runs the same `run_rms_check` the command line runs, and shows the
grade, the findings and an Accept control for a demonstrated failure. It registers no tool
and adds no mutation - the model is not in this loop at all, and no API key is needed to
use it.

## Standards check

The Task Pane has six tabs - **Review**, **Ask**, **Extract**, **Model check**, **Remodel**
and **Standards** - and the sixth is the release gate. Press Standards on a part, an
assembly or a drawing and it dumps the active document with `--profile standards`
(the model check phases plus cut lists, and the drawing sheets when the document is a
drawing), grades it against sixteen checks, and shows a release verdict with every check
accounted for as checked, skipped, unresolved or out of scope. Like the Model check tab it
**needs no language model and no API key**: no provider is constructed and no key is read
on any standards path, and the only host it reaches is the loopback backend. What it grades
against is a **profile** - the library folders, part-number pattern and property names of
one company - which lives on the workstation at `%LOCALAPPDATA%\SwReview\standards.yaml`
and is never in this repository; `config/standards.example.yaml` is a fictional example of
its shape. The checks read the documents as they stand: nothing is opened, rebuilt,
activated or saved. The catalogue is `specs/006-standards-check/contracts/rules.md`.

```powershell
swreview-extract dump --out <package dir> --profile standards
swreview check standards --package <package dir> --out <run dir> --profile <standards.yaml>
swreview exceptions accept-standards <run dir> --package <package dir> --file <waivers.json>
```

## Spec Kit

This repository was initialized with GitHub Spec Kit. The workflow skills are
`/speckit-constitution`, `/speckit-specify`, `/speckit-plan`, `/speckit-tasks`,
`/speckit-implement`, `/speckit-converge`, plus `/speckit-clarify`, `/speckit-analyze`,
and `/speckit-checklist`.

## License

AGPL-3.0-or-later; see `LICENSE`. Third-party notices are in `NOTICE.md`. The reviewer
depends on PyMuPDF (AGPL-3.0-or-later), which is why this project carries the same license.
