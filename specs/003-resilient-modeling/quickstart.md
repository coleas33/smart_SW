# Quickstart: Validating the Resilient Modeling Checks

**Feature**: `003-resilient-modeling` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

## Prerequisites

Everything from features 001 and 002. Workstation scenarios need SOLIDWORKS 2024 and the
two fixture parts built by hand from `benchmarks/native/rms-part/RECIPE.md` (one with the
six groups in order and one seeded violation per reachable rule; one with a missing group
and two groups transposed).

### Working copies of the fixtures

`swreview check rms` writes `session.json` and `report.md` into the package directory and,
before the rules run, carries the newest same-`design_id` `exceptions.json` under the run
root - the package directory's parent - into it (FR-029). Every `tests/golden/fixtures`
package carries the placeholder `design_id` `dsn:1`, so running these scenarios against the
fixture directories in place would leave untracked files in the repository and copy one
fixture's waivers into another. Copy each fixture into its own run root first; every path
below is one of those copies.

```powershell
cd reviewer
$runs = "$env:TEMP\swreview-quickstart"
Remove-Item -Recurse -Force $runs -ErrorAction Ignore
foreach ($name in 'rms-part', 'rms-assembly', 'rms-equations', 'rms-exceptions') {
  $dir = New-Item -ItemType Directory -Force "$runs\$name\run"
  Copy-Item "tests\golden\fixtures\$name\package.json" $dir
  Copy-Item "tests\golden\fixtures\$name\exceptions.json" $dir -ErrorAction Ignore
}
```

## Scenario 1 (US1): Part rules on a fixture package (no SOLIDWORKS)

```powershell
uv run swreview check rms --package $runs\rms-part\run --scope part
```

Expected: one finding per seeded violation on the seeded part `doc:2`, with the rule id,
feature name, and observed condition; one aggregated checked-coverage item per passing rule
naming the documents; on the unknown-data part `doc:4`, `rms.core.shell_last` skipped (no
shell in Core), `rms.modify.transform_before_replicate` skipped (no Modify group),
`rms.quarantine.largest_fillet_first` skipped (fewer than two readable fillet radii), and
`rms.refs.direction` unresolved for the one feature whose `child_ids` the dumper could not
read - the other Quarantine and reference rules are checked for it, because its Quarantine
features carry readable children; `rms.groups.no_solids_in_ref_or_construction` and
`rms.quarantine.only_fillets_and_chamfers` unresolved on the same part naming the
unclassified `NoSuchType` and `rms.detail.holes_last` unresolved naming the ambiguous `ICE`;
`rms.types.unknown` unresolved naming `NoSuchType x2`; `rms.detail.individually_suppressible`
resolved from the seeded run on the part it names (the `rebuild_errors` row as a finding with
its count and messages, the `ok` rows as checked coverage, the `already_suppressed` row
skipped, the untested Detail feature unresolved with reason `not tested`) and unresolved with
reason `no suppress-test run` for the other two parts, with the coverage reason naming
`<tested>/<present>`; the four assembly data-gap rules unresolved and the six out-of-scope
rules once each, which a `--scope part` run writes too because they are the session's
never-dispatched rules; and the `modeling.resilience` summary item in `unresolved` with the
counts. The closing line reads
`coverage: checked: 18, skipped: 4, unresolved: 11, failed: 0, out_of_scope: 6`.

## Scenario 2 (US2, US3): Assembly and equation rules

```powershell
uv run swreview check rms --package $runs\rms-assembly\run --scope assembly
uv run swreview check rms --package $runs\rms-equations\run --scope equations
```

Expected from the assembly run: the face-mate finding, the first-component finding (unfixed
and under constrained while a later component is fixed), the deep-chain finding from that
fixed root, and the Toolbox finding naming the one document inserted as two configurations;
`rms.assembly.mate_chain_depth` and `rms.assembly.toolbox_parts_not_configurations` also
unresolved for the components the mate graph and the Toolbox flag could not answer for; the
four data-gap rules unresolved once, with `rms.assembly.subassemblies` naming the fixture's
subassembly document `doc:2`. The closing line reads
`coverage: checked: 0, skipped: 0, unresolved: 7, failed: 0, out_of_scope: 6`.

Expected from the equations run: both equation rules fail on the part with no equations at
all - `rms.params.global_variables_present` demonstrated and
`rms.params.dimensions_driven_by_equations` suspected - and both are unresolved on two other
parts for two different reasons: the part whose equation manager was a gap, and the part
whose `is_global` flag could not be read. The closing line reads
`coverage: checked: 2, skipped: 0, unresolved: 7, failed: 0, out_of_scope: 6`.

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
uv run swreview check rms --package $runs\rms-exceptions\run --scope part
```

The fixture carries an active exception for `rms.core.shell_last` on one part and a
`needs_review` exception for another rule.

Expected: the shell result is checked within scope with `exception:EX-001` in its coverage
limits; the other finding stands and names its exception as needing re-review; the six
out-of-scope rules appear once under `out_of_scope` with their reasons.

Then, on the run directory Scenario 1 produced - which is its package directory, because
`run_rms_check` writes `session.json` and `report.md` beside the package it graded:

```powershell
uv run swreview exceptions accept-rms $runs\rms-part\run --package $runs\rms-part\run --file rms_exceptions.json
```

with a file naming `rms.core.shell_last`, `rms.detail.holes_last`, and `rms.bogus.rule`.
Write it as UTF-8 without a byte-order mark: the waiver file is read as plain `utf-8`, and
Windows PowerShell 5.1's `Out-File -Encoding utf8` prepends a BOM the reader rejects.

Expected: exit 1, nothing written, and the three reported as `would accept 1`,
`invalid (warn rule)`, and `invalid (unknown rule)`; with only the first id the command
reports `accepted 1` and writes `exceptions.json`.

## Regression gate

Feature 001 and 002 goldens unchanged; `test_schema_sync` passes on 1.1.0; the C# serializer
test validates a package with features, equations, the constrained-status field, and a
suppress-test run; the guard tests show `SetSuppression2` and `ForceRebuild3` refused
everywhere but the suppress-test gate.
