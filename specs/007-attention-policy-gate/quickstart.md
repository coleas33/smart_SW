# Quickstart: Validating the Attention Policy and the Gate

**Feature**: `007-attention-policy-gate` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

Scenarios 0 to 9 run **offline**, with no SOLIDWORKS licence and no key. Scenarios 10 to 13
are marked **[W]** and need the pilot workstation, the copied 2026-09-18 run folders, or a
provider key.

## Prerequisites

Everything from features 001 to 006 plus the two pane fixes on main (`b3cb948`, `7e700e4`).
Offline: the two committed fixture sessions `reviewer/tests/fixtures/attention/
session-20260918-review.json` and `session-20260918-check.json` (shaped like the workstation
runs: eight findings with two interference rows; three RMS findings), the ranked golden under
`tests/unit/test_report_start_here/`, and the pre-run fixture package from
`tests/support/prerun.py` extended with a `cutlist` phase row and a fictional standards profile.

```powershell
cd reviewer
$runs = "$env:TEMP\swreview-attention-quickstart"
Remove-Item -Recurse -Force $runs -ErrorAction Ignore
New-Item -ItemType Directory $runs | Out-Null
```

## Scenario 0 (Foundational): what must not move

```powershell
uv run pytest tests/unit/test_report_tokens.py tests/unit/test_remodel_report.py -q
```

Expected: both goldens byte-identical with no ranking. Then
`uv run pytest tests/unit/test_report_start_here.py -q`: the ranked golden matches, and the
call-site enumeration finds exactly the eight production sites named in research R3.

## Scenario 1 (US1): timing on a fixture folder

```powershell
Copy-Item -Recurse tests/fixtures/attention/review-folder "$runs\review"
uv run swreview timing "$runs\review" --baseline 45 --supervision 6 --verification 9 --false-alarms 2 --json
uv run swreview timing "$runs\review" --baseline -1
```

Expected: the first prints `net saved: 28.0` and `report.md`'s Timing section reads `Net saved
minutes: 28.0`; the second exits 1 with `baseline_minutes` in the message and the session
unchanged. `uv run pytest tests/unit/test_timing.py -q` proves `benchmark time` still passes
its six tests through the wrapper, and `tests/unit/test_chat_timing_route.py` proves the route
writes the live session, survives the next turn, and refuses `net_saved_minutes` by name.

## Scenario 2 (US2): the 2026-09-18 order

```powershell
uv run swreview attention tests/fixtures/attention/review-folder
uv run swreview attention tests/fixtures/attention/check-folder
```

Expected, review: rows 1 and 2 are the two `interference.static` findings, then
`rms.assembly.mates_to_reference_geometry`, `rms.sketches.fully_defined`,
`rms.grouping.all_features_in_a_group`; `rms.folders.present` last of eight; no `%` anywhere.
Check: `rms.sketches.fully_defined` first. The folder hashes are identical before and after.

## Scenario 3 (US2): total order and the catalogue

```powershell
uv run pytest tests/unit/test_attention.py tests/unit/test_attention_catalogue.py tests/unit/test_attention_fold.py -q
```

Expected: the shuffled session ranks byte-identically; the 4 x 4 x 6 status, severity and
disposition cross product lands where the contract says; every emittable check id, including
the fastener family's five constants, has a class; the fold never touches
`session.findings`; the policy module imports no provider, settings or network module.

## Scenario 4 (US2): the record

```powershell
uv run pytest tests/unit/test_attention_record.py -q
```

Expected: `attention.json` round-trips; `rank(load_session(...))` reproduces it; a check folder
is still a check folder with the record present; a review claiming an RMS check folder rotates
`attention.json` beside `session.json`.

## Scenario 5 (US3): every render carries the section

```powershell
uv run pytest tests/unit/test_report.py -k "start_here or disposition" tests/unit/test_chat_server.py -k "report" -q
```

Expected: after a disposition, a waiver, a turn and a stop, the re-rendered report still opens
its Findings with "Start here" above; `swreview disposition` on a standards folder keeps the
verdict header.

## Scenario 6 (US3): the keyless tabs stay keyless

```powershell
uv run pytest tests/unit/test_chat_checks_routes.py tests/unit/test_chat_standards_routes.py tests/unit/test_standards_no_llm.py -q
```

Expected: both result bodies carry `attention`, byte-equal on the POST and the GET; the
provider factories raising changes nothing; no key variable is read.

## Scenario 7 (US3): the pages own no rule

```powershell
cd ..\extractor
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~Attention|FullyQualifiedName~SharedCheckPage" --nologo
```

Expected: the rows render in the supplied order on both check tabs above the chips; the Review
panel appears on `session.ended` from a stubbed route, says "Nothing to start with" for an
empty ranking, and is cleared by a second Review press; no page script sorts or compares
severities; the Standards body carries no `%`.

## Scenario 8 (US4): the gate, off and on

```powershell
cd ..\reviewer
uv run pytest tests/unit/test_prerun_digest.py tests/unit/test_gate_brief.py tests/unit/test_gate_same_session.py tests/unit/test_gate_standards_in_review.py -q
```

Expected: with the gate off the opening message is byte-identical to lever 5's; with it on,
the brief's "Start here" ids equal the report's; the standards call is a real step; without a
profile, and with a package missing the cutlist row, the not-evaluated line and its skipped
item both appear; both families' summary items stay disjoint.

## Scenario 9 (US4): the number guard and the lever

```powershell
uv run pytest tests/unit/test_drawing_finding_number_guard.py tests/unit/test_efficiency_settings.py tests/unit/test_no_lever_in_pane_settings.py tests/unit/test_usage_contracts.py -q
```

Expected: `0.05 mm` refused when no cited sheet carries it and accepted when one does;
`F-003`, `cmp:0002` and a date accepted; eleven levers, none in the pane schema; a session
carrying the eleventh lever validates against the amended contract.

## Scenario 10 [W] (US2): the read-through with the owner

Copy the four 2026-09-18 folders off the workstation into `$runs`, then:

```powershell
foreach ($folder in Get-ChildItem $runs -Directory) { uv run swreview attention $folder.FullName }
```

Read each ranking with the owner. A disagreement is an edit to `attention_policy_v1.yaml`'s
`classes` or `needs_judgement` and a change to the fixture's expected order; nothing else.

## Scenario 11 [W] (US3): the pane

Start a review on the 810-11249 assembly; when it ends, the pinned panel's rows are identical
to `report.md`'s "Start here". Press Model check and Standards: the rows sit above the chips.

## Scenario 12 [W] (US4): the gate's wall clock

With `--lever procedural_gate --standards-profile <real profile>` on the pilot assembly, record
the seconds between `session.started` and the first `text.delta`. That number decides whether
the gate belongs in the pane.

## Scenario 13 [W] (US4): six alternated runs

Per `specs/005-llm-efficiency/contracts/ab-harness.md`: three off, three on, alternated, each
scored, then `benchmark compare`. Expected: the row's lever counter names no run in
`fell_in_runs`; the median net saved minutes column carries `n=` runs. The compare exits 1 on
the one-package set by design; read `ledger.md`, not the exit code.

## Regression gate

```powershell
cd reviewer; uv run pytest -q; uv run ruff check src tests
cd ..\extractor; dotnet build SwReview.sln -c Release; dotnet test SwReview.sln -c Release
```
