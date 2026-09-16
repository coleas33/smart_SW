# Quickstart: Validating the Resilient Re-modeler

**Feature**: `004-resilient-remodeler` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

## Prerequisites

Everything from features 001, 002 and 003, and in particular **feature 003 User Story 6 must
have landed before any scenario here can run**. Four of its deliverables are consumed rather
than re-created by this feature: the part-root node in `ComponentTreeDumper`, the
`DumpProfile.ModelCheck` dump, `checks/rms/run.py::run_rms_check` with
`checks/rms/grade.py::RmsGrade`, and the add-in's `PaneActions`, `FeatureSelection` and
`web/shared/dom.js`. Without the part-root node a part opened alone dumps zero features, so
`package-before.json` would be empty and the planner would have no input at all; that is a hard
stop, not a degraded run.

Scenarios 1, 2 and 3 run with no SOLIDWORKS and no API key, on any machine that can run the
Python test suite. Scenario 4 and Scenario 5 need the pilot workstation: SOLIDWORKS 2024 SP5
with the interop assemblies at 32.5.0.48, the add-in registered, and a **throwaway prototype
part**, meaning a copy of a real part made by hand into a scratch folder, never the original and
never a vault working copy the engineer still needs. Scenario 4 additionally needs the two
analytic solids PROBE-8 measures; the probe builds them itself so their volume is known exactly
rather than trusted.

Nothing in Scenarios 1 to 3 writes a `.SLDPRT`. Scenario 5 is the first moment any write code
touches a document, and it touches only the copy the run made.

## Scenario 1 (Phase 1, the dry-run planner): plan a part with no SOLIDWORKS

The planner is built and run before any C# write code exists, so the answer to "how much of a
real part can stage 1 actually reorganize" arrives before the expensive half of the feature is
built (plan Phase 0).

```powershell
cd reviewer
uv run swreview remodel plan --package tests/golden/fixtures/rms-part --document <doc id> --json
```

Expected: a `RemodelPlan` with `plan_schema: "1.0"`, no LLM section filled (`descriptions`,
`globals` and the judged `targets` are empty at revision 1), and the whole output readable as
**a partition with reasons**: every content feature is either assigned a target group with the
basis that assigned it, or named on the rebuild list with exactly one reason. The achievable
order is a legal topological order under the dependency graph, ranked toward the RMS order, and
the edit script is the longest-increasing-subsequence minimum, so an already-ordered part
yields zero moves and a reversed part with no dependencies yields a full reorder. Nothing under
the package directory is modified: assert it by hashing the directory before and after.

The four golden plans and the fixtures for the refusal categories:

| Golden fixture | What the plan must show |
|---|---|
| `remodel-ordered` | zero moves, six folders already correct, empty rebuild list, no geometry section (nothing has been compared yet) |
| `remodel-reversed` | full reorder, an edit script no longer than the feature count, each folder created once |
| `remodel-pinned` | a Detail cut sketched on a Quarantine fillet face pinned with reason `backward_reference` naming the blocking edge, and every group it splits named with the interloper |
| `remodel-duplicate-names` | two features sharing a name either renamed first as a recorded, reversible `rename` change, or both on the rebuild list with reason `ambiguous_name` |
| refusal fixtures | one each for multibody, weldment, sheet metal, mesh or graphics body, 3D Interconnect, and an existing folder carrying an RMS name with the wrong members; each refused with every triggering signal named, and a part that trips two signals names both |

Rebuild-list reasons must appear verbatim as `backward_reference`, `shared_sketch`,
`splits_group`, `cycle`, `radius_unreadable`, `ambiguous_name`, `unclassified`,
`graph_unreadable`. A feature whose type name is not in `rms_types.yaml` is `unclassified` and
therefore unresolved, never "movable"; a feature whose `child_ids` and `parent_ids` are both
null is `graph_unreadable` for the same reason. A dependency cycle is refused with the cycle
named, never looped over.

Then the Phase 0 measurement, which is the deliverable this scenario exists for: run the same
command over the benchmark packages and over packages dumped from three to five real parts, and
record per part, in `benchmarks/native/remodel/notes.md`, the feature count, how many features
reach their target group, how many are pinned and by which edge, how many groups come out
non-contiguous, and the rebuild-list size. A part where 3 of 200 features move is a part that
needs rebuilding, and the report says that in its first line rather than calling the run a
success.

## Scenario 2 (Phase 5, the executor over the fake bridge): a scripted failure at change N

```powershell
uv run pytest tests/unit/test_remodel_apply.py tests/unit/test_remodel_apply_log.py -q
```

The fake bridge answers every `remodel.*` command from a script, so every rollback path is
exercised with no SOLIDWORKS and no COM. Each row below is a case the suite must contain.

| Scripted condition at change N | Expected executor behaviour |
|---|---|
| the command returns an error | `changes.jsonl` holds the `attempting` line then a `failed` line, no inverse is needed, and the run continues |
| the command succeeds but `remodel.rebuild` reports errors above the baseline | the recorded inverse from `derive_undo` is applied, confirmed by a second rebuild back at the baseline, the line becomes `rolled_back`, and the run continues |
| the inverse itself fails | the run stops, the copy is not saved, and the report names the change that could not be undone |
| `remodel.reorder` returns `false` | a contract violation, because legality was decided from the graph before the call: log, discard the copy, stop; never retry and never search |
| a persist ref stops resolving after change N-1 | the change fails with "could not be addressed after change N-1" and the run stops with the log intact |
| the target check fails (tag, path, or COM identity changed) | `RemodelTargetError` naming which of the four checks failed; the run aborts with `changes.jsonl` intact |
| three consecutive bridge failures | the existing circuit breaker trips, the run ends `circuit_open`, the copy and `changes.jsonl` survive on disk, and a resume attempt is refused |
| change 251 is reached, or 20 minutes elapse, or one rebuild exceeds 120 seconds | the run stops, finalizes, and reports `truncated` with how many planned changes were applied and which were not; never a silent partial success |
| the verify phase finds a rebuild error or a non-zero feature error code | the copy is discarded, the report is written, nothing is saved |
| `remodel.save` returns `errors != 0` | failed run, no artefact claimed |
| `remodel.save` returns `warnings & swFileSaveWarning_RebuildError` (VERIFIED, value 1) | failed run **with** a saved artefact, and the report says exactly that |
| a hard stop between the two `changes.jsonl` lines | the file ends on an `attempting` line naming exactly what was in flight |

Also asserted here, with no seat: the catastrophic fallback (delete the copy, re-copy the
source, replay `changes.jsonl` up to the last `applied` line) reproduces the same tree, because
every change is persist-ref addressed; one `derive_undo` test per change kind (`rename`,
`reorder`, `folder.create`, `folder.dissolve`, `folder.rename`, `describe`, `equation.add`); a
`describe` whose recorded `before` is `null` is refused up front, because null means the
previous text was unreadable and `""` would be a fabricated restore; and the units regression,
that a 120 mm dimension never produces `"w" = 0.12`.

## Scenario 3 (Phase 6, the geometry gate): the case table

```powershell
uv run pytest tests/unit/test_remodel_geometry.py -q
```

`remodel/geometry.py::evaluate(before, after, tolerances) -> GateResult` has no COM in its
signature, so every case below is a table row built from two `GeometryReading` records.
`GateResult` is tri-state (`pass`, `fail`, `unresolved`) from day one, so stage 2 adds a tier
rather than changing the type. Tier 1 is mass properties and is the stage-1 gate under the
`IDENTITY` profile; tier 2 is the boolean symmetric difference and belongs to stage 2, where it
is mandatory. Stage 2 does not ship in v1, so the tier-2 rows are written and tested against
readings rather than run against SOLIDWORKS.

| Case | Tier 1 | Tier 2 | Verdict | What the report says |
|---|---|---|---|---|
| identical readings | equal | empty both ways | `pass` | geometry unchanged |
| volume delta just inside the profile | within | empty | `pass` | the delta and the bound it met |
| volume delta just outside the profile | outside | not run in stage 1 | `fail` | which quantity moved and by how much |
| mirrored body | identical | residual equals the full volume | `fail` | reflection named explicitly; this is the case tier 1 cannot see |
| translated 0.1 mm | centre of mass moves | residual non-empty | `fail` | the centre-of-mass delta over the diagonal |
| uniformly scaled 1.0001 | volume and area move | residual non-empty | `fail` | the scale named |
| one sliver residual, 10 mm by 10 mm by 0.2 micrometre | equal | `swBodyOperationPartialCoincidence` (VERIFIED, 1040) | `pass` with the residual recorded | a sliver, inspected rather than ignored |
| many slivers summing over the volume threshold | equal | residual volume above `max(1e-12 m3, 1e-6 x V)` | `fail` | total residual volume and residual body count |
| a residual body whose bounding box is null | equal | box unreadable | `unresolved` | the gate did not run on that residual |
| tier-2 error `swBodyOperationBooleanFail` (VERIFIED, 1058) or `Unknown` (-1) | any | did not run | `unresolved` | never `pass` |
| tier-2 error `swBodyOperationEmptyBody` (VERIFIED, 6) | equal | A lies entirely inside B | `pass` | the pass signal, read together with the other direction |
| tier-2 error `swBodyOperationNoIntersect` (VERIFIED, 1067) | any | read with the residual volume, never alone | per volume | stated with the volume that decided it |
| tier-2 error `swBodyOperationNonApiBody` (VERIFIED, 1) | any | did not run | `unresolved` | the input was not an API body |
| mass-properties status not OK (`swMassPropertiesStatus_e`, VERIFIED) | not readable | not run | `unresolved` | measurement failed; this is not "geometry changed" |
| prototype solid body count 2 | bodies cannot be paired | not run | `unresolved` | the scope gate should have refused this part earlier |
| principal moments permuted | equal after sorting ascending | empty | `pass` | sorting is part of the comparison, not a fix-up |
| zero-volume prototype | guarded | not run | `unresolved` | no divide by zero |
| mass differs, volume identical | volume equal | empty | `pass` with `material_changed` | material, not geometry (`IPartDoc.GetMaterialPropertyName2`, VERIFIED present) |
| tier 1 passes, tier 2 fails | pass | fail | `fail` | the mirrored-part diagnosis, spelled out |
| tier 1 fails, tier 2 passes | fail | pass | `unresolved` | the tolerances are wrong; never silently resolved either way |

Plus the unit test that every tolerance constant is in metres, every angle in radians, and no
comparison mixes an absolute bound with a relative one. Neither tolerance profile ships until
PROBE-8 has been run (Scenario 4): a tolerance that has never been compared against a known
answer does not ship.

The gate's coverage statement is part of the report, not a footnote, because the report must
say what it cannot see: a reflection, a rigid rotation about a symmetry axis, compensating add
and remove pairs, anything occupying no volume (split faces, cosmetic threads, material, custom
properties, configuration data), and surface or wire bodies. A part carrying surface bodies is
allowed through the scope gate and its surface coverage is reported **uncovered**, never as
passed.

## Scenario 4 (Phase 2, workstation): the blocking probes

```powershell
swreview-extract probe remodel --out ..\benchmarks\native\remodel
```

The probe builds its own throwaway part and never touches an engineer's file. Read every line
of the output and record the observations in `benchmarks/native/remodel/notes.md`; record the
PROBE-8 numbers in `benchmarks/native/remodel/tolerance-calibration.md`, which the tolerance
constants cite by name. A probe whose answer is not recorded counts as not run.

| Probe | Question | Observation to record | If the answer is bad |
|---|---|---|---|
| PROBE-1 | Does `ISldWorks.CommandInProgress = true` suppress the "Cannot reorder" message box? | whether an illegal `ReorderFeature` returned `false` silently or raised a dialog, and how long the call took | stage 1 cannot run unattended; stop and re-plan before any executor code is written |
| PROBE-2 | Equation units: does `"w" = 120` in a millimetre part produce 120 mm, and what unit does `IEquationMgr.get_Value(i)` return? | the text written, the resulting `IDimension.SystemValue` in metres, and the value the manager reported | the units sequence in the plan is inverted; globals do not ship until it is right |
| PROBE-3 | Does `IModelDocExtension.ReorderFeature(f, anchor, swMoveAfter=3)` (VERIFIED signature, VERIFIED enum value 3) move a feature on 2024, and return `false` rather than corrupting the tree when asked to move past a dependency? | the return value in the legal and the illegal case, and the tree order after each | the reorganize-in-place premise fails; Phase 0's numbers decide what replaces it |
| PROBE-4 | Do folders require contiguous members on 2024? | what `IFeatureManager.InsertFeatureTreeFolder2(swFeatureTreeFolder_Containing=2)` (both VERIFIED) did with a contiguous run, and what it did with a non-contiguous selection | the contiguity precondition is wrong in one direction or the other; re-plan `folders.py` before executor work |
| PROBE-8 | Attained relative error on volume, surface area, centre of mass and principal moments at `swMassPropertyAccuracyLevel_Higher` (VERIFIED, 2), against a box and a cylinder of exactly known analytic volume | measured value, analytic value and relative error for each quantity on each solid | the `IDENTITY` profile's 1e-9 bounds are not attainable and must be raised to the measured floor before the gate ships |
| PROBE-12 | Does `ICustomPropertyManager.Add3(key, 30, value, 2)` tag the copy, and does `Get4` read it back on 2024? | the return code of `Add3`, the value `Get4` returned, and whether it survived a save and reopen | the tag cannot be one of `VerifyTarget`'s four checks; the guard needs a different second identity signal before any write code ships |
| PROBE-15 | Does `IConfiguration.GetRootComponent3(false)` return a component for a part configuration on 2024? | the exact return (a component or null), and, with the 003 US6 part-root node in place, the feature count of a part dumped alone | this is feature 003 US6's blocker and therefore 004's; nothing downstream is trustworthy until it is answered |

The non-blocking probes (5, 6, 7, 9, 10, 11, 13, 14, 16, 17, 20, 21) run in the same pass and
are recorded the same way; each has a documented fallback, so a bad answer costs an
optimisation, not the feature. PROBE-18 and PROBE-19 concern the tier-2 boolean and are
recorded for the stage-2 re-spec, not gated on here.

## Scenario 5 (Phase 9, workstation): stage 1 end to end from the pane

1. Copy a real part into a scratch folder by hand and open **the copy** in SOLIDWORKS 2024.
   This is the prototype for the run; the run makes its own second copy in the run folder.
2. Record the prototype's size, last-write time and SHA-256 with `Get-FileHash` before anything
   else, in the notes file. This is the independent check on the run's own attestation, and it
   is the point of the scenario.
3. Open the task pane, go to the **Model check** tab (tab 4), press Model check, and record the
   grade: counts per bucket, the fraction, and the unresolved rule ids by name.
4. Go to the **Remodel** tab (tab 5) and press Plan. Expected: the tab reports the run folder
   `<run_root>/<yyyyMMdd-HHmmss>-<doc>-remodel`, and `plan.json` exists beside
   `source-attestation.json`, `package-before.json` and `rms-before.json`. A part that is
   dirty, read-only, not a part, carrying external references, failing the scope gate, or
   already carrying rebuild errors is refused here, before anything is copied, with every
   reason named. A part on an EPDM vault path is not refused for vault reasons: it is copied
   out into the run folder, and the vault path and revision are recorded in `plan.json`.
5. Read the plan summary in the pane before pressing Run: how many features move, how many are
   pinned and by which edge, which groups are non-contiguous, and the rebuild list with one
   reason per entry. Stage 2 does not ship in v1, so the rebuild list is the run's statement
   about what it will not attempt, and it is read here rather than after the fact.
6. Press Run. The run goes to completion unattended; there is no approve-each-change mode. The
   change list grows live and the status line names the stage.
7. When it finishes, read the report region: the change list, the before and after `RmsGrade`
   with the per-rule delta, and the geometry comparison with its verdict and its coverage
   statement. Fillets the planner sent to `3-Core` by default appear in the report as "reviewed
   as structural; move to Quarantine if cosmetic"; that list is read, not skipped.
8. **The source attestation check.** Re-run `Get-FileHash` on the prototype and compare all
   three values with step 2 and with `source-attestation.json`. They must be identical. Then
   open `remodel.log` and confirm that every mutating call recorded a target path equal to the
   copy's path under the run folder, that the gated member set contains only allowlisted
   interface-qualified keys, and that the refused set is empty. The claim "no write reached
   your file" is made from this log, not from intent.
9. Press **Open copy**: the copy opens from the run folder. Confirm the title bar shows the run
   folder's path and not the prototype's, and that the prototype's own window, if it is still
   open, is untouched and unmodified.
10. Select a change in the list and confirm Show selects that feature in the copy, through the
    same `FeatureSelection` strategy the Model check tab uses.
11. Press **Discard**. Expected: the copy is closed without saving and `copy/` is deleted, while
    `plan.json`, `changes.jsonl`, `package-before.json`, `package-after.json`, `rms-before.json`,
    `rms-after.json`, `grades.json`, `geometry.json`, `source-attestation.json`, `report.md`,
    `events.jsonl`, `session.json` and `remodel.log` all remain. "What did it propose" stays
    answerable after the engineer says no.
12. Record in `benchmarks/native/remodel/notes.md`: the feature count, the applied and the
    planned change counts, wall-clock time, the grade delta, the geometry verdict, every type
    name the run could not classify, and every place where `default_group_by_class` disagreed
    with what an engineer would have chosen. The last two feed the type-table calibration.

Repeat steps 1 to 12 on a second part chosen to be awkward: many features, at least one shared
sketch, and at least one duplicate feature name. A run that refuses, or that applies three
changes out of two hundred, is a valid outcome of this scenario and is recorded as a number,
not as a failure of the scenario.

## Regression gate

Feature 001, 002 and 003 goldens byte-identical; `test_schema_sync` green. `ReadOnlyGuard` is
unchanged by this feature: the four narrowing denials belong to feature 003, and 004 adds
nothing to it, asserted by the set-equality test that pins `RemodelGuard`'s allowlist against
`ReadOnlyGuard.DeniedMembers` union `DeniedPrefixes`, so a denial added upstream cannot
silently widen the remodel surface. The MCP function list and the terminal profile's
`enabled_tools` are unchanged, and a sibling test asserts every `remodel.*` command is in
neither. The general-chat secret is refused for every `remodel.*` and the remodel secret is
refused for `interference`. Option composition is asserted as exact integers: the copy opens
with `Silent|LoadModel = 17` and never carries `ReadOnly(2)` or `ViewOnly(4)`; the save is
`Silent = 1` and never carries `Copy(2)`, `SaveReferenced(4)` or `AvoidRebuildOnSave(8)`. The
frozen interop-surface manifest matches the code's argument builders (pure test, always run)
and matches the installed interop DLL (workstation test, skipped when the DLL is absent), so a
SOLIDWORKS upgrade becomes a red build rather than a runtime surprise. `ReviewHostTests` and
the feature 003 Model check tests stay green with no edits.
