# Data Model: Automatic Mechanical Checks

**Feature**: `010-mechanical-checks` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

Four things change shape, each additively: the evidence package gains three optional members
(IR schema 1.5.0, US8); the review session gains one optional list (`contacts`, US1); the
standards profile gains a version 2 with two sections (US7, US8); and seven data files are added
or edited. `Finding`, `CoverageItem`, `InvestigationStep` and every event keep their shapes.
Everything else below is an in-memory Python type, pure and recomputable from `package.json`
(and the profile, when one is attached), so nothing here needs a store of its own. The contracts
in [contracts/](contracts/) are normative; this is the model.

---

## 1. The joint map (`checks/joints.py`, pure)

### `HoleInstance`

One instance of a Hole Wizard feature: a group of the feature's cylinder faces sharing an axis
(research R2.1).

| Field | Type | Rules |
|---|---|---|
| `id` | str | `<hole id>#<n>`, `n` from 1 in order of the group's smallest face id |
| `hole_id`, `component_id`, `hole_type` | as on `Hole` | |
| `face_ids` | tuple[str, ...] | the group's faces, sorted |
| `axis` | `Axis` | the first face's cylinder axis, in the assembly frame |
| `diameters_mm` | tuple[float, ...] | every distinct face diameter, ascending; a counterbore instance holds two |
| `bore_mm` | float | the smallest; `H` unless a native size exists |
| `size_mm`, `size_source` | float, Literal["hole_wizard", "face"] | `Hole.diameter` or the US8 `wizard` size when present, else `bore_mm` labelled `face` |
| `axis_aligned` | bool | the axis within `axis_aligned_deg` of a coordinate axis, so a bounding-box extent along it is exact to `r sin θ` (recorded) |

### `CylinderMember`

| Field | Type | Rules |
|---|---|---|
| `face_id`, `component_id` | str | a free cylinder face: in no `Hole.face_ids`, on a component with no `Hole` row |
| `diameter_mm` | float | measured |
| `role` | Literal["in_bore", "in_counterbore"] | research R2.3 |
| `offset_mm`, `overlap_mm` | float | against the instance it joined |

### `Joint`

| Field | Type | Rules |
|---|---|---|
| `id` | str | `jnt:0001` onward, in order of the smallest member instance id |
| `kind` | Literal["screw", "pin", "through_bolt", "unclassified"] | research R2.4, first rule that matches |
| `instances` | tuple[HoleInstance, ...] | at least one |
| `cylinders` | tuple[CylinderMember, ...] | possibly empty |
| `fastener` | `RecognisedFastener` \| None | set from US4 when a recognised fastener is placed in the joint |
| `reference` | str | the instance id whose axis the joint is measured along: the tapped instance, else the first |
| `offset_mm` | float | the largest lateral offset between any member axis and the reference axis |
| `component_ids` | tuple[str, ...] | sorted union |
| `pattern_key` | str | kind plus the sorted `(hole id or "cylinder", component id)` of its members; joints sharing it are one pattern group (R2.21) |
| `axis_aligned` | bool | every member instance axis-aligned |

### `Candidate` and `JointMapGap`

| Type | Fields | Rules |
|---|---|---|
| `Candidate` | `members` (two ids), `reason` (Literal["angle_near", "overlap_near", "gap_near", "assigned_elsewhere"]), `values` (angle, offset, radius sum, gap) | a pair within `candidate_margin` of exactly one failed gate, or one that lost the partner assignment; never a finding |
| `JointMapGap` | `subject` (a hole id, instance id or component id), `reason` | a hole row with no cylinder face; a zero-length axis; a component that is not resolved; the hole phase not run |

### `JointMap` and `JointRules`

`JointMap(joints, candidates, gaps, unplaced, rules)`, from `build_joint_map(package, rules=None,
fasteners=None)`: the whole result, deterministic for a
package (shuffling any array of the package yields byte-identical JSON). `unplaced` holds the
recognised fasteners no rule placed (from US4). `JointRules` is `checks/joint_rules.yaml` (section
13), loaded once, with `version`.

`build_joint_map` never raises on a valid package.

## 2. Fastener identity (`checks/fastener_names.py`, `checks/fastener_identity.py`)

### `ParsedName`

| Field | Type | Rules |
|---|---|---|
| `text`, `source` | str, Literal["file_name", "description", "configuration"] | what was parsed and where it came from |
| `kind` | Literal["screw", "bolt", "nut", "washer", "pin", "other"] \| None | |
| `head_code`, `head_type`, `drive` | str \| None | from `fastener_names.yaml`; a null drive stays null |
| `thread` | `ThreadSpec` \| None | `checks/fastener.py parse_thread` of the normalized designation |
| `length_mm` | float \| None | |

`parse_fastener_name(text, source) -> ParsedName | None` returns `None` for text that names no
size; an unreadable part of a readable name is a null field, never a guess.

### `RecognisedFastener`

| Field | Type | Rules |
|---|---|---|
| `component_id`, `document_id` | str | |
| `identity_source` | Literal["toolbox", "custom_property", "name_parse"] | a `Fastener` row wins; `name_parse` otherwise |
| `name` | `ParsedName` \| None | the first source that parsed; the others cross-check |
| `fastener` | `Fastener` | the IR row, or one built in memory for a name-parsed screw: `id = "fst:name:<component id>"`, the component's persist ref and scope, the axis from its placement |
| `shank_mm`, `shank_source` | float \| None, Literal["face", "mesh"] \| None | the measured shank |
| `agreement` | Literal["agrees", "disagrees", "unmeasured"] | the ISO 68-1 band (research R2.12) |
| `placement` | Literal["face", "origin"] \| None | research R2.3; `None` is unplaced |
| `extent_mm`, `extent_source` | tuple[float, float] \| None, Literal["face", "mesh"] \| None | along the joint's reference axis, once placed |

## 3. The placed screw (`checks/fastener.py`)

`check_placed_screw(fastener, hole, placement, hole_material=None, rules=None, envelope=None) ->
list[CheckResult]` returns the same four results as `check_fastener_joint`.

| Type | Fields | Rules |
|---|---|---|
| `Placement` | `protrusion_mm` (float \| None), `protrusion_source` (str), `usable_thread` (`UsableThread` \| None), `missing` (list[str]) | protrusion is the tip's depth below the thread entry along the tapped axis; `missing` names what could not be measured, in the unresolved results' words |
| `UsableThread` | `length_mm`, `source` | `Hole.thread_depth` for a blind hole; `derived: through-tapped length from the tapped face` for a through-tapped hole; never `hole_depth`, never a blind face's extent |

`CHECK_IDENTITY = "fastener.identity"` lives in `checks/fastener_identity.py` with the check that
emits it.

## 4. Alignment and stack-up (`checks/joint_alignment.py`, pure)

| Type | Fields | Rules |
|---|---|---|
| `ClearanceTerm` | `instance_id`, `h_mm`, `h_source`, `f_mm`, `f_source`, `term_mm` | `(H - F) / 2`; 0 for a tapped or line-to-line instance; negative is demonstrated |
| `NominalAlignment` | `joint_id`, `fixture` (Literal["fixed", "floating"]), `offset_mm`, `terms`, `allowed_mm`, `budget_mm`, `callout` | research R2.6 |
| `StackModel` | Literal["size_and_position", "size_only"] | the richest model whose contributors all resolve (R2.7) |
| `ToleranceLookup` | Protocol: `resolve(subject) -> ResolvedTolerance \| UnresolvedTolerance` | US3 ships `NoSources`, whose every answer is unresolved with "no tolerance source is read yet"; US8 replaces it with the resolver |

## 5. Tolerances (`checks/tolerances.py`, pure)

The module is created by US3 (T035) with the types below and `NoSources`, so the stack-up lands
before any tolerance is read; US8 (T083) adds `resolve_tolerance` and the resolver that replaces
`NoSources` as the default lookup.

| Type | Fields | Rules |
|---|---|---|
| `ToleranceSubject` | `kind` (Literal["hole_size", "pin_size", "hole_position"]), `instance_id` or `component_id`, `face_ids`, `nominal_mm`, `document_id` | what a contributor is |
| `SourceKind` | Literal["drawing", "annotation", "model_dimension", "hole_wizard", "general"] | in precedence order |
| `ResolvedTolerance` | `subject`, `source_kind`, `cited` (str: document, entity, persist ref or profile section), `dimension` (`Dimension` whose `tolerance.source` names the source), `also_found` (list of lower-precedence sources that carried one), `conflict` (str \| None) | `checks/result.py limits_mm` reads it, so there is one reading of a tolerance |
| `UnresolvedTolerance` | `subject`, `searched` (list of `(SourceKind, why it did not bind)`) | never carries a number |

`resolve_tolerance(package, profile, subject) -> ResolvedTolerance | UnresolvedTolerance`.

## 6. Tool access (`checks/tool_access.py`, pure but for the mesh load)

| Type | Fields | Rules |
|---|---|---|
| `HeadGeometry` | `joint_id`, `head_plane_origin` (Vec3), `outward` (Vec3), `source` (Literal["mesh", "face_plus_k"]) | research R2.15; unresolved when neither source exists |
| `ToolChoice` | `tool` (str), `reason` (Literal["drive", "head_type"]), `radius_mm`, `reach_mm`, `sources` | from `fastener_names.yaml`, `tool_envelopes.yaml`; a tool the table lacks is unresolved |
| `HeadFit` | `joint_id`, `recess` (Literal["counterbore", "countersink"]), `recess_diameter_mm`, `recess_depth_mm` \| None, `dk_mm`, `k_mm`, `table_row` | against `head_dimensions.yaml` |

## 7. Mass and material (`checks/mass.py`, pure)

No new type beyond the `CheckResult`s. It reads `Document.material`, `.mass`, `.mass_overridden`,
the component tree for an assembly's children, and `package.gaps` of kinds `document`, `body` and
`mass_override`. `MaterialClass(name, matches, density_kg_m3: tuple[float, float], source)` is
the row of `material_classes.yaml`, loaded by `checks/material_classes.py`, whose `for_material`
replaces `EngagementRules.for_material`'s matching (one classifier, research R2.16).

## 8. Hygiene (`checks/hygiene.py`, pure)

No new type. Reads `Document.file_name`, `.custom_properties`, `.config_properties`,
`ComponentInstance.suppression`, and the profile's `hygiene` and `revision.property` when a
standards run is attached.

## 9. The contact (`report/session.py`)

### `Contact`

| Field | Type | Rules |
|---|---|---|
| `id` | str | `C-001` onward, allocated like finding ids |
| `kind` | Literal["zero_volume", "possible_only", "thread_model"] | research R2.9, R2.10 |
| `group_key`, `configuration` | str | |
| `interference_ids` | list[str] | the group's members |
| `component_ids` | list[str] | sorted, at least two |
| `volume_mm3` | float \| None | the largest member volume in mm3, `None` for possible-only |
| `joint_id` | str \| None | when the joint map has a joint over these components |
| `reason` | str | one sentence naming both parts and why it is a contact |
| `tool_result_ids` | list[int] | the step that judged the group |

### `ReviewSession.contacts`

`list[Contact] = []`, in `properties` of `review-session.schema.json` and never in `required`,
omitted from `session.json` when empty so a session written before this feature round-trips to
its own bytes.

## 10. IR schema 1.5.0 (`ir/models.py`, `extractor/SwReview.Extractor/Ir/`)

### `HoleWizardData` (`Hole.wizard`, optional, omitted when null)

| Field | Type | Interop read (seat-validated) |
|---|---|---|
| `fit_class_raw` | str \| None | `IWizardHoleFeatureData2.HoleFit`, verbatim |
| `thread_class_raw` | str \| None | `.ThreadClass`, verbatim |
| `thru_hole_diameter`, `tap_drill_diameter` | Quantity \| None | `.ThruHoleDiameter`, `.TapDrillDiameter` |
| `counterbore_diameter`, `counterbore_depth` | Quantity \| None | `.CounterBoreDiameter`, `.CounterBoreDepth` |
| `countersink_diameter` | Quantity \| None | `.CounterSinkDiameter` |
| `countersink_angle` | Angle \| None | `.CounterSinkAngle` |
| `head_clearance` | Quantity \| None | `.HeadClearance` |

Each field is null plus a `hole_wizard` gap naming it when the read fails. Nothing is derived.

### `ModelDimension` (`EvidencePackage.model_dimensions`, omitted when empty)

| Field | Type | Rules |
|---|---|---|
| `id` | str | `^mdm:[0-9]{4,}$` |
| `document_id`, `feature_name`, `name` | str | `name` as `IDimension.FullName` reads |
| `dimension_type` | Literal["linear", "diameter", "radius", "angular", "other"] | |
| `nominal` | Quantity \| Angle | |
| `tolerance` | `Tolerance` | `kind` from `GetToleranceType`, limits from `GetToleranceValues`; `source.document_id` the part and `source.persist_ref` the dimension's |
| `fit_hole_class`, `fit_shaft_class` | str \| None | `GetToleranceFitValues` |
| `persist_ref`, `persist_ref_scope` | PersistRef \| None, str \| None | |

### `ModelAnnotation` (`EvidencePackage.model_annotations`, omitted when empty)

| Field | Type | Rules |
|---|---|---|
| `id` | str | `^man:[0-9]{4,}$` |
| `document_id` | str | |
| `kind` | Literal["gtol", "datum"] | `IGtol` or `IDatumTag` |
| `symbol_raw`, `values_raw`, `datums_raw` | list[str] | `GetFrameSymbols3`, `GetFrameValues`, `GetDatumIdentifier`, verbatim |
| `label` | str \| None | `IDatumTag.GetLabel` |
| `attached_persist_refs` | list[PersistRef] | the faces the annotation is attached to, the binding key (research R2.18) |
| `persist_ref`, `persist_ref_scope` | PersistRef \| None, str \| None | |

`SCHEMA_VERSION = "1.5.0"`; a 1.4.0 package loads and serializes to its own bytes.

## 11. Standards profile version 2 (`checks/standards/profile.py`)

| Section | Fields | Rules |
|---|---|---|
| `general_tolerance` | `linear: list[LinearBand]`, `angular_deg: float \| None` | `LinearBand(over_mm, up_to_mm, plus_minus_mm)`, bands contiguous and non-overlapping, `over < up_to`, `plus_minus > 0`; an empty list means the company declares none |
| `hygiene` | `part_number_property: str`, `description_property: str` | an empty string skips the checks that need it |

`PROFILE_VERSION = 2`; version 1 loads with both sections absent (research R2.19). No value of
either section appears in the source; the example, both fixtures and 006's contract block carry
fictional values that differ everywhere.

## 12. The registration point (`tools/checks_mechanical.py`)

`CODE_FIRST_CHECKS: tuple[str, ...]` - `()` until US2, then `("check_joints",)`, then with
`"check_mass_material"` and `"check_hygiene"` as US6 and US7 land. Read by
`prerun.planned_calls`; the three tools take no argument.

## 13. Data files

| File | New or changed | Shape | Loader |
|---|---|---|---|
| `checks/joint_rules.yaml` | new | `version`, `parallel_deg`, `adjacency_gap_mm`, `member_coaxial_mm`, `member_diameter_allowance_mm`, `origin_on_axis_mm`, `axis_aligned_deg`, `candidate_margin: {angle_deg, overlap_mm, gap_mm}`, each with a `source` note | `checks/joints.py load_joint_rules` |
| `checks/fastener_names.yaml` | new | `version`, `head_codes: {<code>: {kind, head_type, drive}}` (drive may be null), `kinds`, `heads` vocabularies | `checks/fastener_names.py` |
| `checks/head_dimensions.yaml` | new | `version`, rows `{standard, head_type, size, dk_max_mm, k_max_mm, countersink_angle_deg?}` with a `source` per standard | `checks/tool_access.py` |
| `checks/tool_envelopes.yaml` | changed | each tool gains `reach_diameter_ratio`; a `head_tools: {<head type>: <tool>}` map | `checks/tool_envelopes.py` |
| `checks/material_classes.yaml` | new | `version`, `default_class`, `classes: {<name>: {matches, density_kg_m3: [lo, hi] \| null, source}}`, `no_material_density_kg_m3: 1000` with its source | `checks/material_classes.py` |
| `checks/engagement_rules.yaml` | changed | `material_classes` keeps `min_engagement_ratio` and `source` per class name; `matches` moves out; steel 1.5 | `checks/engagement_rules.py` |
| `checks/iso286.yaml` | new | `version`, `it_grades_um: {<grade>: [{over_mm, up_to_mm, um}]}` for IT5 to IT11 up to 120 mm, the `H` and `h` classes (zero fundamental deviation) | `checks/tolerances.py` |

## 14. New finding ids

| Id | Module | Class (policy v1) | Status it can take |
|---|---|---|---|
| `hole.nominal_alignment` | `joint_alignment.py` | interface | demonstrated, unresolved, checked within scope |
| `hole.position_stack` | `joint_alignment.py` | interface | demonstrated, suspected, unresolved, checked within scope |
| `fastener.identity` | `fastener_identity.py` | interface | suspected |
| `fastener.head_fit` | `tool_access.py` | interface | demonstrated, unresolved, checked within scope |
| `mass.material_assigned` | `mass.py` | manufacturing | demonstrated, unresolved (passes counted in one `checked` item) |
| `mass.density` | `mass.py` | manufacturing | demonstrated, checked within scope |
| `mass.assembly_override` | `mass.py` | manufacturing | suspected |
| `hygiene.part_number_matches_file` | `hygiene.py` | hygiene | demonstrated (passes counted in one `checked` item, as for every `hygiene.` id) |
| `hygiene.duplicate_description` | `hygiene.py` | hygiene | demonstrated |
| `hygiene.duplicate_part_number` | `hygiene.py` | hygiene | demonstrated |
| `hygiene.revision_present` | `hygiene.py` | hygiene | demonstrated |
| `hygiene.component_not_resolved` | `hygiene.py` | hygiene | demonstrated |

`fastener.bottoming`, `.engagement`, `.thread_match` and `.head_clearance` are reused by the
joint checks unchanged.

## 15. Relationships

```
package.json ──build_joint_map──▶ JointMap ──▶ coverage: checked per pattern group, skipped per candidate/gap/unplaced
     │                              │
     │   recognise_fasteners ───────┤ (US4: placement by face or origin)
     │                              ├──▶ joint_alignment: hole.nominal_alignment, hole.position_stack ◀── resolve_tolerance (US8)
     │                              ├──▶ check_placed_screw: fastener.thread_match/.engagement/.bottoming, fastener.identity
     │                              └──▶ tool_access: fastener.head_clearance (envelope_raycast), fastener.head_fit
     ├──check_interference_group──▶ Finding | Contact (thread_model contacts read the JointMap)
     ├──mass checks──▶ mass.*          profile v2 ──▶ general tolerance (US8), hygiene names (US7)
     └──hygiene checks──▶ hygiene.*
CODE_FIRST_CHECKS ──▶ prerun.planned_calls ──▶ the same ToolDispatch the model uses (lever 5/11 today; 008's pane default later)
```
