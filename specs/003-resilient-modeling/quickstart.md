# Quickstart: Validating the Resilient Modeling Checks

**Feature**: `003-resilient-modeling` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

## Prerequisites

Everything from features 001 and 002. Workstation scenarios need SOLIDWORKS 2024 and the
two fixture parts built by hand from `benchmarks/native/rms-part/RECIPE.md` (one with the
six groups in order and one seeded violation per reachable rule; one with a missing group
and two groups transposed).

## Scenario 1 (US1): Part rules on a fixture package (no SOLIDWORKS)

```powershell
cd reviewer
uv run swreview check rms --package tests/golden/fixtures/rms-part --scope part
```

Expected: one finding per seeded violation with the rule id, feature name, and observed
condition; one aggregated checked-coverage item per passing rule naming the documents; the
four Quarantine rules skipped for the part without a Quarantine group; the reference rules
and `rms.sketches.one_sketch_per_feature` unresolved for the part whose dependents are null;
`rms.types.unknown` unresolved naming the unlisted type; `rms.detail.individually_suppressible`
resolved from the seeded run on the part it names (the `rebuild_errors` row as a finding with
its count and messages, the `ok` rows as checked coverage, the `already_suppressed` row
skipped, the untested Detail feature unresolved with reason `not tested`) and unresolved with
reason `no suppress-test run` for the other two parts, with the coverage reason naming
`<tested>/<present>`; the `modeling.resilience` summary item in `unresolved` with the counts.

## Scenario 2 (US2, US3): Assembly and equation rules

```powershell
uv run swreview check rms --package tests/golden/fixtures/rms-assembly --scope assembly
uv run swreview check rms --package tests/golden/fixtures/rms-equations --scope equations
```

Expected: the face-mate finding, the first-component finding (unfixed and under
constrained while a later component is fixed), and the deep-chain finding from that fixed
root; the four data-gap rules unresolved once, with `rms.assembly.subassemblies` naming the
fixture's subassembly document; a global-variables finding on the part with no equations and
unresolved on the part whose equations are a gap.

## Scenario 3 (US1 to US3, workstation): Probe, dump, check on a real part

1. Open the first fixture part in SOLIDWORKS 2024.
2. `swreview-extract probe rms --doc <part>`: read every line; record in
   `benchmarks/native/rms-part/notes.md` the traversal shape, which of `GetChildren`,
   `GetParents`, sketch status, description, equations, and fillet radii returned values,
   and every type name the probe marks unknown to the tables.
3. Time `swreview-extract dump --out ..\benchmarks\packages\rms-part\native` once with the
   defaults and once with `--features none --equations off`; record both timings.
4. `uv run swreview validate benchmarks/packages/rms-part/native`, then
   `uv run swreview check rms --package benchmarks/packages/rms-part/native` and compare with
   `benchmarks/answer_keys/rms-part.json`.

Expected: the seeded violations are found; anything the probe showed unavailable appears as
unresolved coverage, never as pass or fail; the two timings differ by well under 20 s on the
fixture and are re-measured on a 200-component assembly in T062.

## Scenario 4 (US4, workstation): Suppressibility test

```powershell
uv run swreview rms suppress-plan --package benchmarks/packages/rms-part/native --document <doc id>
swreview-extract suppress-test --doc <part> --plan ..\benchmarks\packages\rms-part\native\suppress-plan.json --acknowledge-rebuild --out ..\benchmarks\packages\rms-part\native
uv run swreview check rms --package benchmarks/packages/rms-part/native --scope part
```

Expected: the plan lists the Detail content features; the command refuses without the flag,
on an unsaved document, on a rolled-back document, on a part with pre-existing rebuild
errors, in another configuration, and against a package from an older dump; with a saved
part it reports `<tested>/<present>` rows, `restore_verified: true`, writes the distinct
interop member names to `suppress-test.log`, prints that the document is modified in memory
and must be closed without saving, and the file on disk is unchanged; the review shows the
seeded fragile Detail feature as a finding with its rebuild errors, the others as checked
coverage, and the pre-suppressed one as skipped.

## Scenario 5 (US5): Exceptions and advisory coverage

```powershell
uv run swreview check rms --package tests/golden/fixtures/rms-exceptions --scope part
```

The fixture carries an active exception for `rms.core.shell_last` on one part and a
`needs_review` exception for another rule.

Expected: the shell result is checked within scope with `exception:EX-001` in its coverage
limits; the other finding stands and names its exception as needing re-review; the six
out-of-scope rules appear once under `out_of_scope` with their reasons.

Then, on a run directory from Scenario 1:

```powershell
uv run swreview exceptions accept-rms <run_dir> --package tests/golden/fixtures/rms-part --file rms_exceptions.json
```

with a file naming `rms.core.shell_last`, `rms.detail.holes_last`, and `rms.bogus.rule`.

Expected: exit 1, nothing written, and the three reported as `would accept 1`,
`invalid (warn rule)`, and `invalid (unknown rule)`; with only the first id the command
reports `accepted 1` and writes `exceptions.json`.

## Regression gate

Feature 001 and 002 goldens unchanged; `test_schema_sync` passes on 1.1.0; the C# serializer
test validates a package with features, equations, the constrained-status field, and a
suppress-test run; the guard tests show `SetSuppression2` and `ForceRebuild3` refused
everywhere but the suppress-test gate.
