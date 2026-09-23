# smart_SW: SOLIDWORKS agentic design review pilot

An assistant that investigates SOLIDWORKS assemblies and drawings, gathers engineering
evidence through a curated tool set, runs deterministic checks, and writes a findings
report an engineer can verify and disposition. Numbers come from checked code; the language
model decides what to investigate and explains, never computes a verdict.

The design documents live in `specs/001-agentic-design-review/` (spec, plan, research,
data model, contracts, quickstart, tasks), the Task Pane assistant that runs the reviewer
from inside SOLIDWORKS in `specs/002-task-pane-assistant/`, the Resilient Modeling checks
and the Model check tab in `specs/003-resilient-modeling/`, the Standards check tab in
`specs/006-standards-check/`, the ranking and the procedural gate in
`specs/007-attention-policy-gate/`, checks first and the token budget in
`specs/008-checks-first-review/`, the Review tab's summary, questions and kept reviews in
`specs/009-engineer-workspace/`, the mechanical checks in `specs/010-mechanical-checks/`, and
the governing rules in `.specify/memory/constitution.md`. `README-complete.md` is the original
pilot proposal and `sw-review-architecture-proposal.md` the architecture decision record.

## Current status and next steps

See [the September 20 project status](docs/project-status-2026-09-20.md) for the
current baseline, pilot findings, and prioritized next steps. The imported
[handoff overview](README-START-HERE.md) and
[detailed findings](docs/pane-findings-2026-09-20.md) preserve the pilot report.

The [pre-test readiness plan](docs/pretest-readiness-plan-2026-09-20.md) records the
implemented batch; [the testing handoff](docs/testing-handoff-2026-09-20.md) covers
installation, live checks, and comparable efficiency experiments. A local test run can be collected with
`swreview handoff <run-dir> --out <new-archive.zip>`; the archive includes a manifest of
missing artifacts and retains design paths, so inspect it before sharing.

## Layout

```text
extractor/    C# (.NET Framework 4.8, x64): SOLIDWORKS 2024 add-in, Task Pane (Review,
              Extract, Model check, Remodel and Standards tabs), console host, IR dump,
              interference, captures. Only this tree touches the SOLIDWORKS API.
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
`timing`, `attention`, `check`, `rms`, `benchmark`, plus `chat serve` for the Task Pane
backend, `mcp` for the read-only toolset an external CLI connects to, and `audit-secrets`)
and `swreview-extract`
(C# console: `dump`, `interference`, `capture`, `resolve`, `serve`, `probe rms`,
`suppress-test`).

The review loop runs on OpenAI by default, or on Gemini with `--provider gemini`. It needs
`OPENAI_API_KEY`, or `GOOGLE_API_KEY` (`GEMINI_API_KEY` is read second) for Gemini. Inside SOLIDWORKS the key comes from the pane's settings instead,
DPAPI-protected under `%APPDATA%\SwReview\settings.json`, and reaches the backend only
through its environment block: it is never a command-line argument, and `swreview
audit-secrets <run> <logs>` is the check that it never reached a file.

Command-line contracts: `specs/001-agentic-design-review/contracts/cli.md`.

**What to read first.** Every `report.md` opens its findings with a **Start here** section:
the five findings a fixed rule put first (checks that need engineering judgement, then
rebuild breakers, then interface, manufacturing, discipline and hygiene classes; waived and
decided findings last; a total order with no weights), a line accounting for what was not
amplified, and a block saying what the run could not reach. The rule is
`reviewer/src/swreview/report/attention.py` with its table in `attention_policy_v1.yaml`;
`attention.json` beside `session.json` records the order the engineer was shown, and
`swreview attention <run dir>` prints it with the key values behind every row without
writing anything. The same rows appear above the chips on the Model check and Standards
tabs and in a panel above the Review transcript when a session ends; no page computes
them. `swreview timing <run dir>` records the engineer's minutes (baseline, assisted
supervision, verification and false-alarm handling) against any run folder, and the report's
Timing section prints the net figure. `swreview review --lever procedural_gate`, off by
default, runs the deterministic checks first and opens the model's first user message with
their ranked brief; `specs/007-attention-policy-gate/` has the contracts.

**Checks first.** A pane review runs the deterministic checks whose scope the package already
decides before the model's first turn (feature 008): the three RMS checks, every interference
group (after live detection when SOLIDWORKS is attached, whose rows and gaps are then written into
the run folder's `package.json`, replacing that configuration's rows, so a Retry does not add them
twice), `check_joints`, `check_mass_material`, `check_hygiene`, and `check_standards` when a
profile is attached. Each is a real recorded step with its findings, and the first user message
opens with a digest of what ran and what could not; a model that asks for one again is answered
`already_run` from the recorded result, and the tools that ran to completion leave the tool array
for the rest of the session. The RMS findings fold into one collapsed "Modelling practice" group
in `report.md` and one row in the ranking. Every step of a review, the pre-run's included, keeps
its full result in the run folder as `tool-results/step-<n>.json`, and the report lists the five
largest. What the model reads of each result is a view - references out, check digests, compact
JSON - and results older than two rounds reach it as short stubs it can re-fetch; the session, the
package, the report and every stored result keep the full payload.

On the command line every change is **off** unless asked. `swreview review --pane-defaults` runs
with exactly the pane's settings for the provider (checks first and lever 13, parallel tool calls
on OpenAI, payload slimming, history pruning after two rounds), and the explicit switches add to
it or turn one change on alone: `--payload-slimming`, `--history-pruning` and `--prune-after N` (N
at least 1, and only with pruning on). `session.json` records what ran (`efficiency`,
`model_view`). The contracts are `specs/008-checks-first-review/contracts/`.

**The mechanical checks** (feature 010) take no argument and run in checks first. `check_joints`
finds every joint from the geometry - cross-part hole-to-hole and cylinder-to-hole pairs - and
checks each for alignment, the tolerance stack-up (unresolved, naming the missing contributor,
whenever a tolerance is not in the evidence: none is inferred), fastener identity from file names
and the measured shank, thread match, engagement, bottoming, tool access above the head and head
fit in a counterbore. Engagement follows the owner's rule: at least 1.5 times the nominal diameter
into steel and aluminium alike, and a screw through-tapped into sheet thinner than that is a
finding at low severity carrying the sheet thickness. `check_mass_material` gives every part with
a mass and a volume a verdict on its material and density, and reports an assembly mass override
for confirmation; `check_hygiene` compares the part-number property with the file name, finds
shared descriptions and part numbers and missing revisions, and flags suppressed and lightweight
components. A zero-volume interference row is a **contact**, kept in its own list beside the
findings and never in "Start here". The part-number and description properties the hygiene checks
read, and the general tolerance by decimal places, come from standards profile **version 2**
(`config/standards.example.yaml`); a version 1 profile still loads, with the two property checks
skipped naming the setting and no general tolerance applied, so the owner's real profile has to be
regenerated at version 2 before they grade a real run.

**The Review tab** (feature 009) opens its Results with a summary the backend computes and the
page prints as supplied: how many findings in how many issues; the findings to **Decide**, **Fix**
and **Verify**; the open questions; the parts not loaded; and one line per check goal saying
whether it was checked, found issues or was not reached, and why. Every word it prints - the
summary's templates and the status, severity, bucket and error labels - is in
`reviewer/src/swreview/report/review_words_v1.yaml`, and the page reads the labels from
`GET /labels`. **Questions for you** appear above Start here one at a time, with the answers the
review offered or a text box and "Skip for now"; the answers go together in one submission that
resumes the review once, and the pane states the approximate cost of resuming before it sends. A
two-way switch chooses **Results** (no tool calls, arguments or token counts) or **Transcript**
(every prose block and tool call in order). Every finished review of the SOLIDWORKS session is
kept as a chip naming its document, configuration and time; choosing one restores its results
without a new review, and a review whose conversation is gone - a settings save restarts the
backend - is restored **read-only** from its run folder, with the reason shown and the follow-up
and dispositions disabled. The contracts are `specs/009-engineer-workspace/contracts/`.

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

The Task Pane shows five tabs - **Review**, **Extract**, **Model check**, **Remodel** and
**Standards** - and the last is the release gate. A sixth, **Ask** (the CLI terminal), is
built but hidden until the terminal is part of the pilot (`TaskPaneControl.AskTabShown`).
Press Standards on a part, an assembly or a drawing and it dumps the active document with
`--profile standards`
(the model check phases plus cut lists, and the drawing sheets when the document is a
drawing), grades it against sixteen checks, and shows a release verdict with every check
accounted for as checked, skipped, unresolved or out of scope. Like the Model check tab it
**needs no language model and no API key**: no provider is constructed and no key is read
on any standards path, and the only host it reaches is the loopback backend. What it grades
against is a **profile** - the library folders, part-number pattern and property names of
one company - which lives on the workstation at `%LOCALAPPDATA%\SwReview\standards.yaml`
and is never in this repository; `config/standards.example.yaml` is a fictional example of
its shape. The checks read the documents as they stand: nothing is opened, rebuilt,
activated or saved. The catalogue is `specs/006-standards-check/contracts/rules.md`. On
both check tabs the rows above the bucket chips are the report's "Start here" section, sent
by the backend in the check body's `attention` block and rendered in the order supplied.

```powershell
swreview-extract dump --out <package dir> --profile standards
swreview check standards --package <package dir> --out <run dir> --profile <standards.yaml>
swreview exceptions accept-standards <run dir> --package <package dir> --file <waivers.json>
```

## Benchmarks

`swreview benchmark run`, `score`, `time` and `compare` run the benchmark set and render the
results ledger in `docs/llm-efficiency-options.md` (`specs/005-llm-efficiency/`).
`swreview benchmark replay <run dir>` prices a recorded review through the current code offline -
no key, no network, no SOLIDWORKS, nothing written into the folder: it replays the recorded calls
in their recorded rounds once as recorded and once with the requested settings, prints every
round's recorded, as-recorded and requested input with the totals counted with o200k_base, and
compares the findings by subject. It exits 1 when a recorded finding is lost. The request is the
pane's for the recorded provider unless `--no-pane-defaults`, plus any `--lever`,
`--payload-slimming`, `--history-pruning` or `--prune-after N` named, resolved as
`swreview review` resolves them; `--standards-profile` grades the standards checks in both passes
and `--json` prints the report as JSON. With checks first or parallel calls requested it also
prints a regrouped estimate with its assumption beside it. Three fictional fixtures shaped like
the recorded reviews are committed under `reviewer/tests/fixtures/replay/`, and the tokenizer's
vocabulary is fetched once into a per-user cache. The contract is
`specs/008-checks-first-review/contracts/replay.md`.

```powershell
cd reviewer
uv run swreview benchmark replay tests/fixtures/replay/big-assembly --standards-profile ../config/standards.example.yaml
uv run swreview benchmark replay tests/fixtures/replay/big-assembly --no-pane-defaults --lever prerun_checks --json
```

## Spec Kit

This repository was initialized with GitHub Spec Kit. The workflow skills are
`/speckit-constitution`, `/speckit-specify`, `/speckit-plan`, `/speckit-tasks`,
`/speckit-implement`, `/speckit-converge`, plus `/speckit-clarify`, `/speckit-analyze`,
and `/speckit-checklist`.

## License

AGPL-3.0-or-later; see `LICENSE`. Third-party notices are in `NOTICE.md`. The reviewer
depends on PyMuPDF (AGPL-3.0-or-later), which is why this project carries the same license.
