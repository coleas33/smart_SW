# Quickstart: Validating the Agentic Design Review Pilot

**Feature**: `001-agentic-design-review` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

This guide lists the runnable scenarios that prove each user story works end to end. It
does not contain implementation code. Paths are relative to the repository root.

## Prerequisites

| Need | For | Notes |
|------|-----|-------|
| Windows 11 workstation with SOLIDWORKS 2024 and EPDM working copy | US2, US3 (native) | Only the extractor and interference need a SolidWorks seat. |
| .NET Framework 4.8 developer pack, Visual Studio 2022 | `extractor/` (C#) | SolidWorks 2024 interop targets .NET Framework. |
| Python 3.11+ and `uv` | `reviewer/` (Python) | `uv` already installed at `~/.local/bin/uv`. |
| `ANTHROPIC_API_KEY` or `ant auth login` | US1 agent loop | Reviewer calls Claude through the Anthropic SDK. |
| One real design package plus 5 to 10 benchmark packages | US1, US6 | See `benchmarks/README.md` once created. |

Setup:

```powershell
# Python side
cd reviewer
uv sync --all-extras
uv run pytest            # unit + golden tests; must pass before any scenario below

# C# side (on the SolidWorks workstation)
cd extractor
dotnet build SwReview.sln -c Release
```

## Scenario 1 (US1): Evidence-linked review of an exported package

Inputs: `benchmarks/packages/<name>/` containing `manifest.json`, `bom.csv`, `drawings/*.pdf`, optional `geometry/*.step`.

```powershell
cd reviewer
uv run swreview review benchmarks/packages/cover-blind-tap --out runs/cover-blind-tap
```

Expected:

- `runs/cover-blind-tap/session.json` validates against `contracts/review-session.schema.json`.
- `runs/cover-blind-tap/report.md` exists; every finding shows component or drawing location, provenance, requirement, inputs with units, calculation or tool result, status, and recommended action.
- The seeded blind tapped hole with drill depth only produces an `unresolved` finding and an open evidence request for usable thread depth; no finding is `checked_within_scope` on that joint.
- The `Coverage` section lists the drawing PDF whose text layer is missing (seeded) under `unresolved` with reason `no_text`.
- Forcing a tool error (`--fail-tool measure_distance`) yields a `failed` coverage item with the error text and the run still completes.

Disposition:

```powershell
uv run swreview disposition runs/cover-blind-tap F-001 --decision accepted --note "reviewed, ok"
```

Expected: `session.json` finding `F-001` gains a `disposition`; the report re-renders with it.

## Scenario 2 (US2): Native extraction on the workstation

Open `benchmarks/native/bracket-assy/bracket-assy.SLDASM` in SOLIDWORKS 2024, then:

```powershell
# in-process add-in command (Task Pane button "Dump IR") or console host:
extractor\bin\Release\SwReview.Extractor.Console.exe dump --out ..\benchmarks\packages\bracket-assy\native
```

Expected:

- `native/package.json` validates against `contracts/ir.schema.json` with `schema_version` major `1`.
- Component count, instance names, hole thread designation and depth for `housing-1`, and screw size and length for `M6x20-3` match `benchmarks/native/bracket-assy/answer-key.json` exactly (SC-007).
- Every component, hole, fastener and face has a non-empty `persist_ref`.
- Close and reopen the assembly; run `SwReview.Extractor.Console.exe resolve --ref <persist_ref>`: the same entity name is returned.
- Suppress one component and re-run: it appears with `suppression: "suppressed"` and any check needing it appears under unresolved coverage in a subsequent review.
- Edit `manifest.json` to claim a different vault version for one part: the next review lists a `version_mismatch` discrepancy at the top of the report.

## Scenario 3 (US3): Interference and clearance

```powershell
extractor\bin\Release\SwReview.Extractor.Console.exe interference --config Default --pairs all --out ..\benchmarks\packages\bracket-assy\native
cd reviewer
uv run swreview review benchmarks/packages/bracket-assy --out runs/bracket-assy
```

Expected:

- Three seeded interferences reported with both component ids, volume in mm³, configuration, and settings.
- The six-instance pattern interference appears as one grouped finding with six members.
- The previously accepted exception (`benchmarks/packages/bracket-assy/exceptions.json`) is shown as `excepted`; after modifying the excepted boss diameter and re-extracting, it is shown as `needs_review`.
- Simulating a truncated result (`--truncate-after 2` on the console host) produces `unresolved` pairs and no overall pass.
- Reviewing a mechanism at positions A and B produces a coverage statement naming A and B and stating motion-path clearance was not established.

## Scenario 4 (US4): Fit and tolerance checks

```powershell
uv run swreview check fit --package benchmarks/packages/shaft-bore --shaft P-101 --bore P-102
uv run swreview check stack --package benchmarks/packages/plate-stack --stack stack-A
```

Expected:

- Shaft/bore: min and max clearance match `answer-key.json` to 0.001 mm; the calculation block names model `fit.size_only` and lists excluded effects.
- Plate stack with one untoleranced dimension and no general note: result `unresolved`, missing tolerance named, no default substituted.
- Mixed-unit fixture (inch drawing, mm model): report shows both source and converted values.
- Golden test `tests/golden/fixtures/angle-not-length/` fails the run if an angle is ever consumed as a length.

## Scenario 5 (US5): Fastener and hole compatibility

```powershell
uv run swreview check fastener --package benchmarks/packages/bracket-assy --joint J-1
uv run swreview check fastener --package benchmarks/packages/bracket-assy --joint J-2
```

Expected:

- J-1 (screw 2 mm too long): `demonstrated` bottoming finding with the computed margin and the engagement rule applied.
- J-2 (correct): `checked_within_scope` with engagement ratio.
- A joint of unsupported type (`J-3`, rivet): listed under `out_of_scope`.
- Thread mismatch fixture (M6 screw in M5 hole): `demonstrated` with both designations.

## Scenario 6 (US6): Benchmark scorecard

```powershell
uv run swreview benchmark run --set benchmarks/sets/pilot.json --out runs/benchmark-<date>
uv run swreview benchmark score runs/benchmark-<date> --answer-keys benchmarks/answer_keys
```

Expected:

- `scorecard.json` validates against `contracts/scorecard.schema.json` and has per-package and aggregate counts, median net minutes saved, and the distribution.
- The reviewer process, started with the benchmark runner, cannot read `benchmarks/answer_keys/` (the loader refuses that prefix and the test `tests/integration/test_answer_key_isolation.py` proves it).
- Baseline and assisted times entered with `swreview benchmark time ...` appear in the scorecard, with unattended runtime shown separately.

## Regression gate (every change)

```powershell
cd reviewer
uv run pytest -q                       # unit tests + golden fixtures under tests/golden/fixtures/*
uv run pytest -q -m integration        # requires a saved native package; skipped if absent
```

A change to the IR schema or to any check must add or update a golden fixture, or the
golden test for that check fails.
