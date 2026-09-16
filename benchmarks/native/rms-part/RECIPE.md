# `rms-part`: hand-built SOLIDWORKS fixture for the Resilient Modeling checks

Two parts and one assembly, built by hand in SOLIDWORKS 2024 SP5, that seed one violation of
every RMS rule the checks can reach from extracted data. They are the workstation fixture for
quickstart Scenarios 3 (probe, dump, check) and 4 (suppressibility test); the expected result
is `benchmarks/answer_keys/rms-part.json`, which is never passed to the reviewer.

Rule ids below are the ids in `specs/003-resilient-modeling/contracts/rules.md`. Group names,
type names, and the end-tag convention are the ones in
`reviewer/src/swreview/checks/rms_types.yaml`; the six group folders are named exactly
`1-Ref`, `2-Construction`, `3-Core`, `4-Detail`, `5-Modify`, `6-Quarantine`.

## Files

Build in this folder (`benchmarks/native/rms-part/`), which is source, not output:

| File | Contents |
|------|----------|
| `RMS-A.SLDPRT` | Part A: the six groups present and in order, one seeded violation per rule reachable with correct folders, and the two US4 Detail features. |
| `RMS-B.SLDPRT` | Part B: `5-Modify` missing and `3-Core` after `4-Detail`; otherwise clean. |
| `RMS-Fixture.SLDASM` | Both parts as components, so the dump has a component tree to walk. |

The dumped package goes to `benchmarks/packages/rms-part/native/` (quickstart Scenario 3);
what the probe reported and which interop members answered goes in `notes.md` next to this
file (T062).

**Why an assembly wrapper.** `swreview-extract dump` walks the active configuration's
component tree (`ComponentTreeDumper`), so a part opened on its own yields no
`ComponentInstance` rows and nothing carries a `cmp:` id. Opening `RMS-Fixture.SLDASM` gives
the root assembly `cmp:0001` and the two parts the ids the answer key uses. Insert Part A
**before** Part B so the ids land as `cmp:0002` = Part A and `cmp:0003` = Part B; ids are
allocated in traversal order.

## Conventions for both parts

- New part from the default millimetre template: MMGS, three decimals.
- Sketch dimensions are round numbers; nothing is driven by a design table.
- Every content feature gets a description (right-click the feature, **Feature Properties**,
  **Description**) stating intent, e.g. `CORE outer block`. The single feature left without
  one is the seed for `rms.intent.every_feature_described`, listed below.
- Groups use the nested shape: select the contiguous features of a group in the
  FeatureManager, right-click, **Add to New Folder**, rename the folder to the exact group
  name. No `___EndTag___` markers are created by hand; the flat shape is not used here.
- Save each part and rebuild clean (`Ctrl+Q`) before inserting it into the assembly. Part A
  must rebuild with **no errors** or the suppress test (US4) refuses to run.

## Part A - `RMS-A.SLDPRT`

Feature tree, top to bottom. Indentation is folder membership; `D-n` are the answer-key ids.

```text
RMS-A
+- Front/Top/Right Plane, Origin        (default, excluded from content)
+- Axis1                    RefAxis     loose, above the first group folder   D-1
+- 1-Ref
|  +- Plane1                RefPlane    offset 20 mm above Top Plane
+- 2-Construction
|  +- Sketch2               ProfileFeature  under defined                     D-12
|  +- Surface-Extrude1      SurfaceExtrude  from Sketch2
|  +- Boss-Extrude1         Extrusion   "CON stray pad"                       D-2
+- 3-Core
|  +- Sketch3               ProfileFeature  two closed contours, fully defined
|  +- Boss-Extrude2         Extrusion   "CORE block", contour 1 of Sketch3    D-14
|  +- Boss-Extrude3         Extrusion   "CORE pad",   contour 2 of Sketch3    D-14
|  +- Shell1                Shell       "CORE wall thickness"
|  +- Boss-Extrude4         Extrusion   "CORE rib", after the shell           D-3
+- 4-Detail
|  +- Cut-Extrude2          Cut         "DET pocket", sketch on a CORE face   D-10, D-15
|  +- Cut-Extrude3          Cut         "DET slot", sketch on the pocket floor
|  +- Cut-Extrude4          Cut         "DET vent", SUPPRESSED when saved     (US4)
|  +- Hole1                 HoleWzd     "DET M6 tapped", placed on a CORE face
|  +- Cut-Extrude5          Cut         "DET relief", over-defined sketch     D-4, D-13
+- 5-Modify
|  +- LPattern1             LPattern    "MOD hole row", pattern of Hole1      D-5
|  +- Draft1                Draft       no description                        D-11
+- 6-Quarantine
   +- Fillet1               Fillet      R2                                    D-6, D-9
   +- Chamfer1              Chamfer     1 mm
   +- Fillet2               Fillet      R5                                    D-7
   +- Fillet3               Fillet      R1, on an edge created by Fillet1
   +- Draft2                Draft       "QUAR draft"                          D-8
```

### Seeded violations in Part A

| # | Rule id | Severity | Seed feature | What makes it a violation |
|---|---------|----------|--------------|---------------------------|
| D-1 | `rms.grouping.all_features_in_a_group` | fail | `Axis1` | A content feature (`RefAxis` is not a tolerated loose type) sits above the `1-Ref` folder, so it belongs to no group. |
| D-2 | `rms.groups.no_solids_in_ref_or_construction` | fail | `Boss-Extrude1` | A solid (`Extrusion`) inside `2-Construction`. |
| D-3 | `rms.core.shell_last` | fail | `Boss-Extrude4` | A feature follows `Shell1` inside `3-Core`. |
| D-4 | `rms.detail.holes_last` | warn | `Cut-Extrude5` | A non-hole, non-sketch feature follows `Hole1` inside `4-Detail`. |
| D-5 | `rms.modify.transform_before_replicate` | warn | `LPattern1` | The pattern precedes `Draft1` inside `5-Modify`. |
| D-6 | `rms.quarantine.chamfers_before_fillets` | fail | `Fillet1` | `Fillet1` precedes `Chamfer1` inside `6-Quarantine`. |
| D-7 | `rms.quarantine.largest_fillet_first` | fail | `Fillet2` | Quarantine radii run 2, 5, 1: the 2 to 5 step increases. |
| D-8 | `rms.quarantine.only_fillets_and_chamfers` | fail | `Draft2` | A `Draft` inside `6-Quarantine`. |
| D-9 | `rms.refs.quarantine_has_no_children` | fail | `Fillet1` | `Fillet3` rounds an edge created by `Fillet1`, so a Quarantine feature has a dependent. |
| D-10 | `rms.detail.no_internal_references` | fail | `Cut-Extrude3` | Its sketch sits on the floor created by `Cut-Extrude2`: one Detail feature depends on another, and the pair is neither the single-consumer sketch exception nor a coupled pair in one derived subfolder. |
| D-11 | `rms.intent.every_feature_described` | fail | `Draft1` | Its description is left empty; every other content feature has one. |
| D-12 | `rms.sketches.fully_defined` | fail | `Sketch2` | The construction profile is left under defined (one free endpoint, no dimension or relation to the origin). |
| D-13 | `rms.sketches.not_over_defined` | fail | the sketch of `Cut-Extrude5` | A second driving dimension duplicates one already there; answer **Leave this dimension driving** when SOLIDWORKS offers to make it driven. Use a *consistent* value so the sketch still solves. |
| D-14 | `rms.sketches.one_sketch_per_feature` | fail | `Sketch3` | Shared by `Boss-Extrude2` and `Boss-Extrude3` through contour selection, so it has two consumers. |
| D-15 | `rms.detail.individually_suppressible` | fail | `Cut-Extrude2` | Suppressing the pocket alone leaves `Cut-Extrude3` without its sketch plane, so the rebuild errors. Reported only after the US4 run. |
| D-16 | `rms.params.global_variables_present` | fail | the part's equations | Part A has no equations at all: **Tools, Equations** is empty. |
| D-17 | `rms.params.dimensions_driven_by_equations` | warn | the part's equations | The same absence: no dimension is driven by an equation. |

`Cut-Extrude4` ("DET vent") seeds no rule. It is saved **suppressed** so the US4 run reports
it `already_suppressed` (skipped coverage), per quickstart Scenario 4. Its sketch is on
`Plane1`, not on a Detail face, so suppressing it breaks nothing.

Rules that pass on Part A, and are its `correct_conditions` in the answer key:
`rms.folders.present`, `rms.folders.ordered`, `rms.refs.direction`.

### Build steps for Part A

1. New part from the millimetre template. Save as `RMS-A.SLDPRT` in this folder.
2. **Axis1**: Insert, Reference Geometry, Axis, from Front Plane and Right Plane. Give it a
   description (`REF long axis`) so it seeds only D-1.
3. **Plane1**: Reference Geometry, Plane, offset 20 mm above Top Plane. Describe it.
4. **Sketch2** on Plane1: a three-segment open profile. Dimension the segment lengths but
   leave one endpoint with no dimension or relation to the origin, so the sketch stays under
   defined (the status bar reads *Under Defined*).
5. **Surface-Extrude1**: Insert, Surface, Extrude from Sketch2, 30 mm. Describe it.
6. **Boss-Extrude1** ("CON stray pad"): sketch a 20 x 20 rectangle on Top Plane centred on the
   origin, extrude 10 mm. This is the first solid body; the Core features below merge into it.
7. **Sketch3** on Top Plane: two separate closed contours - a 100 x 60 rectangle centred on
   the origin, and a 20 x 20 square 60 mm to the right of it. Fully define both.
8. **Boss-Extrude2** ("CORE block"): extrude Sketch3 40 mm with **Selected Contours** = the
   100 x 60 rectangle only.
9. **Boss-Extrude3** ("CORE pad"): extrude **the same Sketch3 again** (select it in the tree)
   15 mm, Selected Contours = the 20 x 20 square. Sketch3 now has two consumers (D-14).
10. **Shell1** ("CORE wall thickness"): shell 3 mm, removing the top face of the block.
11. **Boss-Extrude4** ("CORE rib"): sketch a 60 x 6 rectangle on a side face of the block and
    extrude 8 mm. It follows the shell (D-3).
12. **Cut-Extrude2** ("DET pocket"): sketch a 40 x 30 rectangle on the large flat Core face,
    cut 6 mm deep.
13. **Cut-Extrude3** ("DET slot"): sketch a 30 x 8 rectangle **on the floor of the pocket**,
    cut 4 mm deep. That face reference is what makes D-10 and D-15.
14. **Cut-Extrude4** ("DET vent"): sketch a 10 mm circle on Plane1, cut Through All. Describe
    it; it is suppressed in step 21.
15. **Hole1** ("DET M6 tapped"): Hole Wizard, M6x1.0 tapped, 12 mm deep, placed **on a Core
    face**, not on a Detail-cut face, so the hole depends on Core only.
16. **Cut-Extrude5** ("DET relief"): sketch a 25 x 10 rectangle on a Core face and cut 5 mm.
    Then add a second driving dimension that duplicates one already there, with the same
    value, and choose **Leave this dimension driving**: the sketch reads *Over Defined* and
    still solves (D-13). It follows Hole1, which is D-4.
17. **LPattern1** ("MOD hole row"): linear pattern of Hole1, 3 instances, 20 mm spacing.
18. **Draft1**: 3 degree neutral-plane draft on two faces of the Core rib. **Leave the
    description empty** (D-11).
19. **Fillet1** R2, **Chamfer1** 1 mm, **Fillet2** R5, **Fillet3** R1 on an edge that
    `Fillet1` created, **Draft2** 2 degrees on an outer face - created in that order and all
    described.
20. Group the features: select each contiguous block and **Add to New Folder**, renaming to
    `1-Ref`, `2-Construction`, `3-Core`, `4-Detail`, `5-Modify`, `6-Quarantine`. Leave `Axis1`
    outside every folder. Check the folder order against the tree above.
21. Right-click `Cut-Extrude4`, **Suppress**.
22. Leave **Tools, Equations** empty (D-16, D-17).
23. `Ctrl+Q`. The part must rebuild with **no error** - an over-defined sketch is expected to
    raise at most a warning. If step 16 leaves a rebuild error on the part, the US4
    suppress-test refuses to run: replace the duplicate dimension with a consistent one, or
    move the over-defined sketch to Part B and record the change here. Save.

## Part B - `RMS-B.SLDPRT`

```text
RMS-B
+- 1-Ref
|  +- Plane1                RefPlane    offset 15 mm from Right Plane
+- 2-Construction
|  +- Surface-Extrude1      SurfaceExtrude  fully defined sketch
+- 4-Detail
|  +- Boss-Extrude1         Extrusion   "DET base plate"
|  +- Cut-Extrude1          Cut         "DET window", sketch on Plane1
+- 3-Core                               out of order                          D-19
|  +- Boss-Extrude2         Extrusion   "CORE rib", sketch on the base-plate face   D-20
+- 6-Quarantine
   +- Chamfer1              Chamfer     1 mm
   +- Fillet1               Fillet      R6
   +- Fillet2               Fillet      R3

(no 5-Modify folder)                                                          D-18
```

### Seeded violations in Part B

| # | Rule id | Severity | Seed feature | What makes it a violation |
|---|---------|----------|--------------|---------------------------|
| D-18 | `rms.folders.present` | warn | the tree | No `5-Modify` folder exists. |
| D-19 | `rms.folders.ordered` | fail | the `3-Core` folder | `3-Core` appears after `4-Detail` in tree order. |
| D-20 | `rms.refs.direction` | fail | `Boss-Extrude2` | The Core rib is sketched on a face of `Boss-Extrude1`, which the transposed folders put in the later `4-Detail` group: a dependent lives in an earlier group than what it depends on. |

**Why `rms.refs.direction` is not seeded in Part A.** SOLIDWORKS refuses to reorder a feature
above its own parent, so in a part whose six groups appear once each and in order, every
dependent is in the same or a later group than what it depends on and the rule cannot fail.
Transposed folders (Part B) are the only way to reach it by hand; a duplicated group folder
would reach it too, but that is already a `rms.folders.ordered` failure.

Rules that pass on Part B, and are its `correct_conditions` in the answer key:
`rms.grouping.all_features_in_a_group`, `rms.groups.no_solids_in_ref_or_construction`,
`rms.intent.every_feature_described`, `rms.sketches.fully_defined`,
`rms.sketches.not_over_defined`, `rms.sketches.one_sketch_per_feature`,
`rms.quarantine.chamfers_before_fillets`, `rms.quarantine.largest_fillet_first`,
`rms.quarantine.only_fillets_and_chamfers`, `rms.refs.quarantine_has_no_children`,
`rms.params.global_variables_present`, `rms.params.dimensions_driven_by_equations`.

`rms.core.shell_last` (no shell), `rms.detail.holes_last` (no hole), and
`rms.modify.transform_before_replicate` (no Modify group) are expected as *skipped* coverage
on Part B, not passes, so they are not in the answer key.
`rms.detail.no_internal_references` is expected to pass on Part B, but it is left out of the
answer key until T062 records whether `GetChildren` reports the base boss as a parent of the
cut that removes material from it.

### Build steps for Part B

1. New part from the millimetre template. Save as `RMS-B.SLDPRT` in this folder.
2. **Tools, Equations**: add two global variables, `"Width" = 60` and `"Thickness" = 6`, and
   drive the base plate's width and thickness from them (`"D1@Sketch1" = "Width"`,
   `"D1@Boss-Extrude1" = "Thickness"`). Both equation rules then pass.
3. **Plane1**: offset 15 mm from Right Plane. Describe it.
4. **Surface-Extrude1**: a fully defined rectangular profile on Top Plane, surface-extruded
   20 mm. Describe it.
5. **Boss-Extrude1** ("DET base plate"): fully defined rectangle on Top Plane, extruded
   `"Thickness"`.
6. **Cut-Extrude1** ("DET window"): fully defined 20 mm circle **on Plane1**, cut Through All,
   so it takes no reference from the base plate's faces.
7. **Boss-Extrude2** ("CORE rib"): sketch a 40 x 6 rectangle **on the top face of the base
   plate** and extrude 10 mm (D-20).
8. **Chamfer1** 1 mm, then **Fillet1** R6, then **Fillet2** R3, each on a different edge and
   none of them on an edge another created. All described.
9. Folder the tree as `1-Ref`, `2-Construction`, `4-Detail`, `3-Core`, `6-Quarantine` - in
   that tree order - and create **no** `5-Modify` folder.
10. Every content feature has a description and every sketch reads *Fully Defined*. `Ctrl+Q`,
    then save.

## Assembly - `RMS-Fixture.SLDASM`

1. New assembly from the millimetre template. Save as `RMS-Fixture.SLDASM` in this folder.
2. Insert `RMS-A.SLDPRT` first, at the origin, and leave it **fixed** (the default for the
   first component). It becomes `cmp:0002`.
3. Insert `RMS-B.SLDPRT` (`cmp:0003`) and constrain it with three mates **between reference
   geometry only** - plane to plane, or plane to plane plus axis to axis. Do not mate to a
   face, an edge, or a vertex.
4. Rebuild, save, and keep the assembly as the document to open for the dump.

The assembly is deliberately clean, so `rms.assembly.mates_to_reference_geometry`,
`rms.assembly.first_component_fixed`, and `rms.assembly.mate_chain_depth` are correct
conditions. No Toolbox component is inserted, so
`rms.assembly.toolbox_parts_not_configurations` is expected as skipped coverage, and the four
data-gap assembly rules stay unresolved.

## Using the fixture

```powershell
# Scenario 3: open RMS-Fixture.SLDASM in SOLIDWORKS 2024, then
swreview-extract probe rms --doc RMS-A
swreview-extract dump --out ..\benchmarks\packages\rms-part\native
uv run swreview validate benchmarks/packages/rms-part/native
uv run swreview check rms --package benchmarks/packages/rms-part/native

# Scenario 4: suppressibility test on Part A's document
uv run swreview rms suppress-plan --package benchmarks/packages/rms-part/native --document <RMS-A doc id>
swreview-extract suppress-test --doc RMS-A --plan ..\benchmarks\packages\rms-part\native\suppress-plan.json --acknowledge-rebuild --out ..\benchmarks\packages\rms-part\native
uv run swreview check rms --package benchmarks/packages/rms-part/native --scope part
```

Compare the run with `benchmarks/answer_keys/rms-part.json`. After a suppress-test run the
document is modified in memory: **close it without saving**, or the next run refuses because
the part has unsaved changes.

Rules with no seed here, by design: the four data-gap assembly rules, the drawing rule, and
the five advisory rules are reported as unresolved or out-of-scope coverage on every review
and cannot be seeded in a model; `rms.types.unknown` is coverage, not a finding, and every
type name this fixture uses is already in `rms_types.yaml`.
