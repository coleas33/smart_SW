# Reviewer guide: what a review does and how to run it

This guide holds the detail that used to be on the front page ([`README.md`](../README.md)): the
command-line entry points, what a review reads first, the checks it runs and the tabs of the Task
Pane. It describes `main`; each section names the feature's contracts, which are authoritative
where the two differ. Paths in backticks are from the repository root. For how the parts fit
together see [`architecture.md`](architecture.md), and for each feature's status see
[`specs/README.md`](../specs/README.md).

## Entry points

See `specs/001-agentic-design-review/quickstart.md` for the validation scenarios and
`specs/002-task-pane-assistant/quickstart.md` for the Task Pane ones. The main entry points
are `swreview` (Python CLI: `validate`, `ingest`, `review`, `report`, `disposition`,
`timing`, `attention`, `check`, `rms`, `drawing brief`, `benchmark`, plus `chat serve` for the
Task Pane backend, `mcp` for the read-only toolset an external CLI connects to, and
`audit-secrets`) and `swreview-extract`
(C# console: `dump`, `interference`, `capture`, `resolve`, `serve`, `probe rms`,
`probe standards`, `probe drawings`, `suppress-test`). `swreview --help` lists every command,
including `handoff`, `exceptions`, `remodel`, `tokenizer`, `profile` and `context`.

Command-line contracts: `specs/001-agentic-design-review/contracts/cli.md`.

If a command in `reviewer/` fails with "No module named swreview" after a pull or a branch
switch, sync again with the package reinstalled: `uv sync --all-extras --reinstall-package
swreview`.

## Providers and keys

The review loop runs on OpenAI by default, or on Gemini with `--provider gemini`. It needs
`OPENAI_API_KEY`, or `GOOGLE_API_KEY` (`GEMINI_API_KEY` is read second) for Gemini. Inside
SOLIDWORKS the key comes from the pane's settings instead, DPAPI-protected under
`%APPDATA%\SwReview\settings.json`, and reaches the backend only through its environment block:
it is never a command-line argument, and `swreview audit-secrets <run> <logs>` is the check that
it never reached a file.

OpenAI is the only provider in use: owner decision 94A (2026-10-15,
`specs/014-design-review-eval/research.md`) defers the Gemini work. The Gemini adapter is still
in the code. `reviewer/README.md` ("Providers and keys") has the model and effort options.

## What to read first

Every `report.md` opens its findings with a **Start here** section:
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

## Checks first

A pane review runs the deterministic checks whose scope the package already
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
on OpenAI, lever 14 `drop_prior_reasoning` leaving earlier turns' reasoning out of the request,
payload slimming, history pruning after two rounds; `pane_efficiency()` in
`reviewer/src/swreview/agent/settings.py`), and the explicit switches add to
it or turn one change on alone: `--payload-slimming`, `--history-pruning` and `--prune-after N` (N
at least 1, and only with pruning on). `session.json` records what ran (`efficiency`,
`model_view`). The contracts are `specs/008-checks-first-review/contracts/`.

## The mechanical checks

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
read, and the general tolerance by decimal places, come from standards profile **version 2** or
later (`config/standards.example.yaml` is version 4); a version 1 profile still loads, with the two
property checks skipped naming the setting and no general tolerance applied, so a real standards
profile, kept outside the repository, has to be regenerated at version 2 or later before it
grades a real run.

## Drawings in a review

**Drawings in a review** (feature 011). A review extraction of a part or assembly reads, with it,
the drawings **already open** in SOLIDWORKS whose views show the design - at most ten, matched by
full path - into the same package; the extraction opens nothing, and the Standards and Model check
extractions still read no drawing but the one they were pressed on. A same-name drawing beside a
reviewed part that is not open is recorded as a **candidate**, never opened by the extraction.
Every dimension's value, tolerance, written precision and unit, the callouts (geometric
tolerances, datums, surface finish, hole callouts), the notes and every table are read, and the
model's `find_dimensions` and `get_drawing_sheet` show them. `check_drawings`, argument-free and
offered only when the package carries drawing evidence, runs in checks first: one coverage line per
reviewed document saying which drawings show it and which views could not be used and why; each
drawing compared with the profile's drawing section (profile **version 3**: sheet formats, drafting
standard, projection, the dimension unit), a difference being one manufacturing-class finding naming
the drawing's values and never a release-verdict failure; and at most four **questions** for the
pane - whether a candidate is the part's drawing, and which drawing governs a document two or more
show. Answering "Yes, open it read-only and read it" has the product open the candidate itself,
read-only and hidden through its own three-key allowlist, read it into the run's package and close
it again - only what it opened - before the review resumes; this ships **off** until a seat probe
validates the open (probe D14), and until then the candidate is refused with that sentence, while a
candidate the engineer has since opened is still read. The drawing is the first tolerance source
for the stack-up, and an untoleranced dimension hands its written precision to the profile's
general tolerance in the profile's declared unit (a radius's band doubled for the diameter); that
binding also ships **off** until the seat confirms callouts tie to the right holes
(`DRAWING_BINDING_VALIDATED`), and until then every answer names the seat validation. A per-part
**brief** of at most 6,000 bytes - the part, its joints, the interfaces needing a callout, what its
drawings cover, the engineer's answers and the drawing standard - comes from `get_drawing_brief`
and from `swreview drawing brief --package <dir> --document <id> [--run <run dir>] [--profile
<yaml>]`, the input a drawing creator (feature 012) will read. Every writer of the drawing API is
refused by the read-only guard, generated from the interop. The contracts are
`specs/011-drawing-context/contracts/`.

## The engineer-first review

**The engineer-first review** (feature 013). Bought parts are out of the grading: standards
profile **version 4** adds a `part_roles` section (`swreview profile upgrade` proposes one from a
version 3 file and decides nothing), and one classifier calls each part custom, bought or unclear
by votes of its signals - Toolbox, a bought-parts folder, the make-or-buy property, vendor and
distributor properties, catalogue numbers, part-number ranges, sparse properties, a same-name
drawing. Modelling-practice and hygiene checks grade custom and unclear parts only, the bought
ones are named once in a bought-parts line, the reviewed document is always graded (and says so
when it looks bought), and one question with buttons and a text box asks about the unclear parts;
its answer regrades the review before it resumes and withdraws what no longer holds
(`finding.withdrawn`). Every finding is shown, grouped by type in a fixed order - Interference and
fit, Fasteners, Drawings, Standards, Modelling practice, Hygiene, Mass and material - with passes
in one "Checked, no issue" fold and no surface amplifying a pass; `report.md` carries the same
"Findings by type". The review never asks what it can know or has been told: provenance is closed
by code, a question repeating an answered one comes back to the model as already answered, and a
drawing request is answered from the drawings code found. The drawing offer follows the seat:
while the read-only open of a closed drawing is not validated (probe D14), no drawing question is
asked and the summary says to open the drawing and press Review again. Every finding, question and
coverage row says who wrote it - "Checked by code" or "AI guidance" - every model answer opens
with a basis line computed from what its turn read, and no fallback stands in for a missing
explanation. Answer turns carry no bookkeeping rounds, and lever 14 leaves earlier turns'
reasoning out of the OpenAI request. The contracts are `specs/013-engineer-first-review/contracts/`.

## The Review tab

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

## Engineering context

Feature 016 provides [engineering context](../specs/016-engineering-context/quickstart.md):
requirements and applied forces, immutable revisions, explicit confirmation and bounded
read-only context for reviews. The Review pane prepares saved evidence, accepts inputs
and attaches an exact context revision; a read-only selection adapter can prefill saved
targets. Native selection calibration, freshness/rebinding and automated drawing writers
remain pending workstation/later roadmap gates.

## Collecting a run

A local test run can be collected with
`swreview handoff <run-dir> --out <new-archive.zip>`; the archive includes a manifest of
missing artifacts and retains design paths, so inspect it before sharing. Its bundle is a bounded
allowlist that leaves `tool-results\` out; for a workstation sitting, hand findings back as
[`workstation-runbook.md`](workstation-runbook.md) section 8 describes instead.

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
`swreview-extract suppress-test` against the open document to carry it out. The constitution
names exactly two bounded exceptions to the read-only rule
([Technical Constraints](../.specify/memory/constitution.md#technical-constraints), "Documents
are read, not written"; [ADR 0003](adr/0003-documents-read-not-written.md)): this
suppressibility test, which is acknowledged on the command line, guarded, restores the tree,
never saves, and is not reachable from the pane, the bridge or the MCP toolset; and feature
004's re-modeler, which may create and modify one document only, a copy it made itself during
the session ([ADR 0004](adr/0004-remodeler-works-on-a-copy.md)). `benchmarks/README.md` has the
suppress-test workflow end to end.

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
drawing - a drawing attaches with no configuration, feature 011, so a drawing open on its own is
graded live; the drawings attached to a part's review are not), grades it against sixteen checks,
and shows a release verdict with every check
accounted for as checked, skipped, unresolved or out of scope. Like the Model check tab it
**needs no language model and no API key**: no provider is constructed and no key is read
on any standards path, and nothing leaves the machine
([`architecture.md`](architecture.md#4-trust-and-security-boundaries), "What leaves the
machine"). What it grades
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

The design-review evaluation's cases, answer keys and sets (feature 014) are described in
[`benchmarks/README.md`](../benchmarks/README.md).
