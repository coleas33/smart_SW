# Data Model: Resilient Re-modeler

**Feature**: `004-resilient-remodeler` | **Date**: 2026-09-16 | **Spec**: [spec.md](spec.md)

**This feature adds no IR fields.** It reads the evidence package feature 003 produces
(`schema_version` 1.2.0, `extractor.profile == "model_check"` or `"full"`) and rejects a package
whose major version it does not support, per Principle IV. Every type below is either a new
pydantic model under `reviewer/src/swreview/remodel/`, a new C# DTO on the bridge, or an existing
003 or 001 type reused unchanged.

Conventions carried over from features 001 and 003 and used everywhere here:

- **Absence is not emptiness.** `null` means "not readable" and carries a reason; `""` and `[]`
  mean "read, and empty". The two are never collapsed. A description whose `before` value is
  `null` is refused as a change target up front, because it has no recoverable inverse.
- **Lengths are meters** in every stored reading and every tolerance. Angles are radians.
  Equation **text** is the one exception and carries the document's length unit, which is why
  `GlobalEvidence` records both numbers (section 1.9).
- **This document is normative for every field name.** `contracts/run-artifacts.md` and the JSON
  blocks in `contracts/bridge-remodel.md` carry examples of the same models and nothing else; where
  one of them and this file ever differ, this file is right and the example is a defect. One test
  loads every example in `run-artifacts.md` into the pydantic model named beside it, so the
  examples cannot drift silently. The one thing this file does **not** own is the request and
  response shape of a `remodel.*` command: `contracts/bridge-remodel.md` is normative for those,
  and section 8 below lists the command names and the protocol rules without restating a shape.
- **Entities are addressed by persistent reference**, never by name and never by index. Names
  and indices both change on every reorder.
- **Every verdict is tri-state or richer.** No Boolean gate, no letter grade.

---

## 1. `RemodelPlan` (`plan.json`)

`reviewer/src/swreview/remodel/plan.py`. Written twice: revision 1 by the pure planner (phase A),
revision 2 after the judgement phase (phase B). Rewritten in place on every state transition so
that `state` is always readable from disk.

| Field | Type | Rules |
|---|---|---|
| `plan_schema` | `Literal["1.0"]` | Rejected by a reader that does not know the version |
| `plan_revision` | int, 1 or 2 | 1 is pure; 2 includes model proposals |
| `run_id` | str | The value written into the copy's `SwReviewRemodelRun` custom property |
| `created_at`, `updated_at` | ISO 8601 | |
| `state` | `RunState` | Section 11 |
| `source` | `SourceAttestation` | Section 5 |
| `copy_path` | str | Absolute; always under `<run_dir>/copy/` |
| `document_id`, `configuration` | str | From the package; the configuration the tree was read in |
| `configuration_names` | list[str] | Drives `which_configs` on every equation add |
| `package_before` | str | Relative path, `package-before.json` |
| `type_table_version`, `type_table_calibrated_version` | str | From `rms_types.yaml`, recorded so a re-grade on another machine is comparable |
| `scope` | `ScopeReport` | Section 4 |
| `targets` | list[`PlanTarget`] | One per feature in the tree, including the ones that are not content |
| `ranks` | list[`FeatureRank`] | One per content feature with a resolved target |
| `order` | `OrderPlan` | |
| `pins` | list[`Pin`] | |
| `rebuild` | list[`RebuildEntry`] | The product of stage 1 |
| `folders` | `FolderPlan` | |
| `renames` | list[`RenamePlan`] | Duplicate-name repair, applied before any reorder |
| `descriptions` | list[`DescriptionProposal`] | Accepted description proposals only |
| `globals` | list[`GlobalProposal`] | Accepted global proposals only |
| `rejected_proposals` | list[`RejectedProposal`] | Every proposal the tool layer refused, with the rule that refused it. Written by the tool itself, not only returned to the model, so the report can list it (FR-016, FR-056) |
| `deviations` | list[`Deviation`] | Every choice the report must call out, including every fillet defaulted to `3-Core` |
| `changes` | list[`PlannedChange`] | The executor's ordered input; the only list `apply.py` walks |
| `limits` | `Limits` | |
| `coverage` | list[`PlanCoverage`] | What the plan could not decide, with a reason each. Never empty by convention: a plan with nothing unresolved says so explicitly |

### 1.1 `PlanTarget`

| Field | Type | Rules |
|---|---|---|
| `feature_id` | `feat:NNNN` | From the package |
| `name`, `type_name` | str | As read; `type_name` may be one the table does not know |
| `feature_class` | str | `RmsTypeTable.classify` result, or `"unknown"` |
| `current_group` | str \| null | From 003's `GroupAssignment`; null when the feature is loose |
| `target_group` | str \| null | One of the six; null when `state` is not `resolved` |
| `basis` | `"type_table" \| "sketch_follows_consumer" \| "unconsumed_sketch" \| "model_judgement" \| "quarantine_has_children"` | Why this group |
| `decided_by` | `"planner" \| "model"` | |
| `state` | `"resolved" \| "needs_judgement" \| "not_content" \| "unresolved"` | `unresolved` is terminal: the feature is never moved |
| `candidates` | list[str] | Populated only for `needs_judgement`; what the model is offered |
| `rationale` | str \| null | Required when `decided_by == "model"` |
| `provider`, `model` | str \| null | Required when `decided_by == "model"`, null otherwise. A group that came from the type table names no provider, and the report keeps the two apart (FR-020, FR-056) |

### 1.2 `FeatureRank`

| Field | Type | Rules |
|---|---|---|
| `feature_id` | str | |
| `group_index` | int 1..6 | Position of `target_group` in the six |
| `intra_rank` | int \| null | From the intra-group rules; null when unrankable |
| `intra_rule_id` | str \| null | Which 003 rule produced the rank (`rms.core.shell_last`, `rms.detail.holes_last`, `rms.modify.transform_before_replicate`, `rms.quarantine.chamfers_before_fillets`, `rms.quarantine.largest_fillet_first`) |
| `original_index` | int | The tie-break, so the plan is stable and minimal movement is the default |
| `rankable` | bool | False sends the feature to `rebuild` with `radius_unreadable` rather than to an arbitrary position |

### 1.3 `OrderPlan`

| Field | Type | Rules |
|---|---|---|
| `achievable` | list[`feat:NNNN`] | Kahn output: the legal topological order closest to the RMS order |
| `kept` | list[str] | The longest increasing subsequence of current positions under `achievable`; these features are not moved |
| `edit_script` | list[`Move`] | The complement, in application order |
| `move_count` | int | `len(edit_script)`; the headline number of the dry run |
| `cycle` | list[str] \| null | Non-null means the plan is a refusal and names the cycle |

`Move`: `feature_id`, `anchor_feature_id`, `location: "before" | "after"`
(`swMoveLocation_e.Before = 2`, `After = 3`, VERIFIED values). Both ends are carried as persist
refs in the corresponding `PlannedChange`.

**The location set is closed at two, and matches the guard.** `swMoveLocation_e.ToEnd = 1`,
`ToTop = 4` and `ToFolder = 5` are all forbidden by the option-composition test in
`contracts/guard-allowlist.md`, so a planner that emitted them would produce a change the guard's
own test says must never be composed. Kahn plus LIS never needs them: a move to the end of the
tree is `after` the last feature, and a move into an existing folder is not a v1 operation at all.
`test_remodel_order.py` asserts the emitted set is exactly `{"before", "after"}`.

### 1.4 `Pin`

| Field | Type | Rules |
|---|---|---|
| `feature_id` | str | |
| `desired_index`, `achievable_index` | int | |
| `blocking_edge` | `{parent_id, child_id}` | **Which edge** holds it; a pin with no named edge is a bug, not a pin |
| `reason` | str | Prose for the report, derived from the edge |

### 1.5 `RebuildEntry`

| Field | Type | Rules |
|---|---|---|
| `feature_id`, `name` | str | |
| `reason` | enum, 8 values | `backward_reference`, `shared_sketch`, `splits_group`, `cycle`, `radius_unreadable`, `ambiguous_name`, `unclassified`, `graph_unreadable` |
| `detail` | str | Names the interloper, the second consumer, the unknown type name, or the cycle |
| `blocking_edge` | `{parent_id, child_id}` \| null | Present for `backward_reference` and `splits_group` |

The set of reasons is closed. A feature that cannot be placed and matches none of the eight is a
planner defect, and the plan fails rather than inventing a ninth reason at runtime.

### 1.6 `FolderPlan`

| Field | Type | Rules |
|---|---|---|
| `actions` | list[`FolderAction`] | In application order; every creation comes after every reorder (section 2.3) |
| `refusals` | list[`FolderRefusal`] | A non-empty list makes the whole run a refusal in v1 |

`FolderAction`: `op: "create" | "rename"`, `name` (one of the six group names, or a preserved
subfolder name), `member_feature_ids` in tree order, `contiguous: bool` (**must** be true before
the action is emitted), `existing_folder_id: str | null`, `status: "planned" | "no_op"`.

`FolderRefusal`: `existing_folder_id`, `name`, `expected_member_ids`, `actual_member_ids`,
`reason: "rms_named_folder_wrong_members"`. In v1 this is a refusal because dissolving a folder
needs `IModelDoc2.EditDelete`, which is not in the stage-1 allowlist (research.md R5.4). The
field `op` deliberately keeps the name space of the bridge command, which also knows
`"dissolve"`, so stage 2 adds an allowlist entry rather than a protocol change.

### 1.7 `RenamePlan`

`feature_id`, `before_name`, `after_name`, `reason: "duplicate_name"`. Applied before any
reorder, because `IModelDocExtension.ReorderFeature` is name-addressed and a duplicate name makes
it ambiguous with no error code.

### 1.8 `DescriptionProposal`

| Field | Type | Rules |
|---|---|---|
| `feature_id` | str | |
| `before` | str \| null | `null` means the description was unreadable. Such a feature is **refused as a change target** up front: there is no recoverable inverse |
| `text` | str | 1 to 200 characters, no newline, not equal to the feature's `name` or `type_name` |
| `source` | `"model"` | The planner never invents description prose |
| `rationale` | str | |
| `provider`, `model` | str | The provider id (`openai` or `gemini`) and the exact model id that produced it. Required by FR-056, which makes the report name them per judgement item. Never `claude`: Claude is not a provider in this product |
| `validation` | `"accepted"` | Only accepted proposals reach this list; the refused ones are in `rejected_proposals` (section 1.9.1) |

### 1.9 `GlobalProposal` and `GlobalEvidence`

| Field | Type | Rules |
|---|---|---|
| `name` | str | `^[a-z][a-z0-9_]{1,31}$`, unique, not an existing global |
| `expression` | str | Parses over the declared globals and the documented function set (`sin cos tan atn arcsin sqr`), angles in **degrees** as SOLIDWORKS equations expect |
| `rationale` | str | |
| `evidence` | list[`GlobalEvidence`] | The feature data that justifies the value. May be empty only for an expression over globals declared earlier in the same plan; a literal with no evidence is rejected |
| `provider`, `model` | str | As for `DescriptionProposal`; FR-056 |
| `validation` | `"accepted"` | Refused proposals are in `rejected_proposals` |
| `order_index` | int | Application order within the globals step; a global is added after every global its expression names, and removed in reverse order |

`GlobalEvidence`: `feature_id`, `parameter` (the feature-data field that justifies the value, for
example `hole_diameter`, `shell_thickness`, `default_radius`), `value_m: float` (as the package
carries it, always meters), `document_length_unit: str`, `value_document_units: float`,
`equation_text: str`. Both numbers are stored because the equation text carries document units
while the package carries meters, and the unit inversion is the highest-risk single error in
stage 1 (research.md R3.6). A pure test asserts that a 120 mm value never produces `"w" = 0.12`.

**A v1 global names a value and drives nothing.** FR-030 forbids creating an equation that drives
a sketch dimension, because the IR carries no dimensions (owner decision OQ-2), and v1 renames no
dimension either. So `evidence` records **why** the number is what it is; it is not a dependency
and nothing in the copy is rewired to the new global. The report says so in those words, so that a
part with three added globals is never read as parameterized. Wiring a dimension to a global
arrives with the later feature that extracts dimensions into the IR.

### 1.9.1 `RejectedProposal`

| Field | Type | Rules |
|---|---|---|
| `at` | ISO 8601 | |
| `tool` | `"propose_description" \| "propose_global" \| "decide_fillet" \| "classify_unknown"` | |
| `arguments` | object | Exactly what the model sent, recorded verbatim; every string in it is untrusted and reaches the report through the `textContent` path only |
| `reason` | str | The rejection sentence the tool returned, from the closed rule tables in `contracts/tools.md` |
| `rule` | str | The identifier of the validation rule that refused it, so the report groups rejections by rule rather than by prose |
| `provider`, `model` | str | FR-056 |

The tool writes this list **and** returns `{"error": ...}` to the model. Returning the error alone
would leave FR-016 and US4 scenario 7 unsatisfiable, because nothing the report reads would carry
the rejection.

### 1.10 `Deviation`, `PlanCoverage`, `Limits`

`Deviation`: `kind` (`"fillet_default_core" | "unknown_classified_by_model" |
"description_skipped" | "global_declined"`), `feature_id | null`, `chosen`, `rationale`,
`report_line` (the exact sentence the report prints, for example "reviewed as structural; move to
Quarantine if cosmetic").

`PlanCoverage`: `item` (what was not decided), `reason`, `feature_ids`. These become coverage
items in the report so a gap is visible rather than absent (Principle VI).

`Limits`: `max_changes: int = 250`, `max_minutes: int = 20`,
`max_rebuild_seconds: int = 120`. Enforced by the executor, never by the model.

### 1.11 `PlannedChange`

The executor's input. One per intended write, in the only order stage 1 permits.

| Field | Type | Rules |
|---|---|---|
| `seq` | int, from 1 | Matches the `ChangeRecord.seq` written for it |
| `kind` | `"rename" \| "describe" \| "reorder" \| "folder.create" \| "folder.rename" \| "equation.add" \| "equation.edit"` | |
| `subject_kind` | `"feature" \| "folder" \| "equation"` | There is no `"dimension"`: v1 addresses no dimension, renames none, and drives none (FR-030) |
| `subject` | `{feature_id, name, persist_ref}` | Resolved to a live object by the C# side at call time |
| `params` | object | Kind-specific; mirrors the bridge command's payload exactly, so the executor is a translator and not a second model of the operation |
| `expect` | object | What must be true afterwards (`rebuild_errors_delta: 0`, `folder_location: <name>`, `equation_count_delta: 1`); asserted by the executor, never assumed |

**The fixed order of operations, and why each step is where it is:**

| Step | Kind | Why here |
|---|---|---|
| C1 | `rename` (feature) | Duplicate names make the name-addressed reorder ambiguous |
| C2 | `describe` | Independent of order; done before anything moves so a failure is cheap |
| C3 | `reorder` | The minimal LIS edit script |
| C4 | `folder.create`, `folder.rename` | Contiguity is only true once the order is achieved. Folder creation is also the one change with no in-place inverse in v1, so it is last among structural changes |
| C5 | `equation.edit` | Repairing an existing global's equation in place (FR-029), before any new global is added, so a repair never competes with an add for the same name |
| C6 | `equation.add` | New globals, in `order_index` order, each added after every global its expression names, each literal seeded from `GlobalEvidence.value_document_units` |

**There is no dimension step.** The brief's apply order carried a dimension-rename step between C1
and C2 and a dimension-equation step after the globals. FR-030 removes both: the IR carries no
dimensions in v1, so the planner can neither name a dimension nor prove what an equation on it
would drive. The rename-before-equations ordering rule is preserved in research.md R3.5 for the
later dimensions feature and is implemented by nothing here.

---

## 2. `ChangeRecord` (`changes.jsonl`) and the inverse table

`reviewer/src/swreview/remodel/apply_log.py`. Append-only, one JSON object per line, two lines
per change: `attempting` before the bridge call and a terminal status after it. A hard crash
mid-change therefore leaves an `attempting` line naming exactly what was in flight.

**This table is the one `ChangeRecord` shape.** `contracts/run-artifacts.md` restates it verbatim
and `tasks.md` T074 asserts exactly these fields; a field in one and not the others is a defect.

| Field | Type | Rules |
|---|---|---|
| `seq` | int | Matches the `PlannedChange`; a `save` record uses the next free seq |
| `at` | ISO 8601 | |
| `kind` | `"rename" \| "describe" \| "reorder" \| "folder.create" \| "folder.rename" \| "equation.add" \| "equation.edit" \| "save"` | `folder.dissolve` is reserved and never written in v1 |
| `subject` | `{feature_id, name, persist_ref}` | `name` is recorded for the report and never used to address anything |
| `before`, `after` | object | Whatever the inverse needs, and nothing else |
| `undo` | `{command, params}` \| null | Derived by the pure `derive_undo(change)`; null means "no in-place inverse exists" and is a deliberate value, not a missing field |
| `rebuild_errors_before`, `rebuild_errors_after` | int | `GetWhatsWrongCount()` around the change |
| `status` | `"attempting" \| "applied" \| "failed" \| "rolled_back" \| "rollback_failed"` | Five, and the fifth is not covered by `failed`: `failed` means the change did not land and the tree is where it was, while `rollback_failed` means a change landed, raised the error count, and could **not** be undone. Only the second ends the run (T080) |
| `error_code` | str \| null | The bridge `error_code` when the change failed, from the closed table in `contracts/bridge-remodel.md`. Null on `applied` |
| `error` | str \| null | The prose sentence beside the code. Never parsed |
| `target_path` | str | The path `VerifyTarget` confirmed for this write. This is what makes FR-041 checkable per change, alongside `remodel.log`'s per-request target; the report cites both and one test asserts they agree |
| `elapsed_ms` | int \| null | |

### 2.1 Inverses, one pure test each

| Kind | Inverse in v1 |
|---|---|
| `rename` | rename back to the recorded previous name |
| `reorder` | reorder back to the recorded anchor and location |
| `folder.rename` | rename to the recorded previous name |
| `describe` | write the recorded previous text (`""` when there was none). Refused up front when `before` was `null` |
| `equation.add` | `IEquationMgr.Delete(index)`, in reverse order of addition, never by deleting a global other equations still reference |
| `equation.edit` | `remodel.equation` with `op: "set"` and the recorded `before.equation_text`, written back through the same preference ladder. The inverse of an in-place edit is another in-place edit, which is why `equation.edit` exists as its own kind instead of being a delete plus an add: a delete would remove a referenced global and put every dependent equation into an error state that does not clear when it returns (research.md R3.5) |
| `folder.create` | **none.** The inverse is a dissolve, which needs `IModelDoc2.EditDelete`, which is not allowlisted in v1. `undo` is `null` and a failure escalates to the tier-2 replay |
| `save` | none. The copy is saved once, at the end, only after the gate passes |
| `folder.dissolve` | not a v1 operation |

### 2.2 The three undo tiers

1. **Per-change forward inverse**, the primary, because it lets the run continue past one bad
   change. A change that raises `rebuild_errors_after` above the run's baseline is undone, the
   undo is confirmed, and the record is written as `rolled_back`.
2. **Catastrophic replay**: delete the copy, re-`File.Copy` the source, replay `changes.jsonl` up
   to the last `applied` line. Deterministic because every change is persist-ref addressed.
3. **`IModelDoc2.EditUndo2`: never.** It returns void, so the caller cannot tell whether it did
   anything, and it shares the UI undo stack the engineer can also touch. It is not in the
   allowlist.

### 2.3 Consequence of the missing `folder.create` inverse

Because folder creation has no in-place inverse in v1, the executor orders every folder creation
after every reorder and description, and a failed folder creation ends the run: finalize, report,
do not save. This is a stated design consequence of the owner's `EditDelete` decision, not an
implementation discovery.

---

## 3. Geometry types

### 3.1 `GeometryReading`

Measured in C# (the ByRef out-parameters cannot be marshalled from Python), returned as a plain
record, and never interpreted there.

| Field | Type | Rules |
|---|---|---|
| `at` | ISO 8601 | |
| `source_sha256` | str | The attested hash of the source the copy was made from; identical on both readings |
| `subject` | `"copy_at_open" \| "copy_at_end"` | Both readings are of the run's own copy. `copy_at_open` is taken after the baseline rollback and rebuild and before the first change; `copy_at_end` after the last one. **The source is never opened, in any mode** (FR-037): the copy is a byte-for-byte filesystem copy whose SHA-256 is recorded before any document handle exists, so `copy_at_open` is a reading of the source's geometry with no handle to the source and no reference body inserted into any tree. `GeometryReading` carries `source_sha256` so the artifact says on its face which file the baseline stands for |
| `status` | int | `swMassPropertiesStatus_e`; anything but `OK(0)` makes the gate `unresolved`, never `fail` |
| `accuracy_level` | int | `swMassPropertyAccuracyLevel_Higher = 2` on every reading |
| `recalculated` | bool | `IMassProperty2.Recalculate()`'s return, checked **before** anything is read |
| `volume_m3` | float \| null | |
| `surface_area_m2` | float \| null | |
| `center_of_mass_m` | [float, float, float] \| null | |
| `principal_moments` | [float, float, float] \| null | **Sorted ascending** by the producer, because a symmetry-degenerate rotation returns the same three numbers permuted |
| `mass_kg`, `density`, `material_name` | float \| null, float \| null, str \| null | Compared **separately** from geometry (section 3.3) |
| `solid_body_count`, `sheet_body_count` | int | |
| `face_count`, `edge_count` | int \| null | |
| `residual` | `ResidualReading` \| null | Tier 2 only; **always null in v1** |

`ResidualReading` (stage 2): `error_code` (`swBodyOperationError_e`), `body_count`,
`total_volume_m3`, `per_body_bbox` (list of `[dx, dy, dz]`, any of which may be null when
`GetBodyBox` returns null).

### 3.2 `Tolerances`

Two named profiles, one pure function. Declared as frozen constants, never assembled at a call
site.

| Name | `volume_rel` | `area_rel` | `com_rel` | `moment_rel` | `face_count` | `body_count` | Ships in |
|---|---|---|---|---|---|---|---|
| `IDENTITY` | 1e-9 | 1e-9 | 1e-9 | 1e-9 | `exact` | `exact` | v1, stage 1 |
| `EQUIVALENCE` | 1e-6 | 1e-5 | 1e-6 | 1e-5 | `warn` | `exact` | stage 2; declared here, selected by no v1 code path |

Each profile also carries `calibrated: bool` and `calibration_ref: str | null`. **A profile with
`calibrated == False` cannot be used by a shipping run**: PROBE-8 measures the attained error on
a part of exactly known analytic volume and fills in the reference. A unit test asserts every
constant is relative, dimensionless, and never mixed with an absolute bound.

### 3.3 `GateResult`

| Field | Type | Rules |
|---|---|---|
| `verdict` | `"pass" \| "fail" \| "unresolved"` | Tri-state from day one, so stage 2 adds a tier and not a type change. Never a Boolean, and never inferred from a successful rebuild |
| `profile` | `"IDENTITY" \| "EQUIVALENCE"` | |
| `tier_1` | `TierResult` | Mass properties |
| `tier_2` | `TierResult` \| null | Boolean symmetric difference; null in v1 |
| `deltas` | list[`Delta`] | One per compared quantity |
| `material_changed` | bool | A mass-only difference reports this and **never** `geometry_changed` |
| `coverage_limits` | list[str] | What this gate cannot detect, printed on every run (section 3.4) |
| `diagnosis` | str \| null | Required when `verdict != "pass"`. Tier 1 passing with tier 2 failing is the mirrored-part case and says so in words |

`TierResult`: `ran: bool`, `verdict`, `reason: str | null`.
`Delta`: `quantity`, `before`, `after`, `absolute`, `relative | null`, `bound`,
`within: bool | null` (null when either side is null, which makes the gate `unresolved`).

Tier 1 failing while tier 2 passes is a tolerance bug and is reported `unresolved`, never
silently resolved either way.

### 3.4 `coverage_limits`, printed every run

A reflection; a rigid rotation about a symmetry axis; compensating add and remove pairs; any
difference occupying no volume (split faces, cosmetic threads, material, custom properties,
configuration data); surface-body and wire-body differences. When the scope gate allowed the part
with surface bodies present, the surface coverage is reported **uncovered**, never as passed.

One more limit follows from FR-037's baseline and is printed with the rest: the baseline reading is
taken **after** the copy has been rolled to the end of its tree and rebuilt (FR-004), so a geometry
difference produced by that first rebuild alone sits inside the baseline and cannot be seen by this
gate. It is bounded, not ignored: a first rebuild that reports any error refuses the run outright,
and the run's stated claim is "the changes this run made did not move the geometry", never "opening
this part in this SOLIDWORKS build did not move the geometry".

---

## 4. Scope types

### 4.1 `ScopeSignals`, measured in C# at `remodel.probe_scope`, then again at `remodel.open`

Every row below except `rebuild_error_count` is a **read** and is taken by
`remodel.probe_scope` on the source the engineer already has open, before any copy exists, which is
what FR-001 requires. `remodel.open` step 12 re-reads the same rows on the copy and a field-for-
field difference is `scope_changed`, so the verdict and the document it was reached on cannot come
apart. `rebuild_error_count` is the one exception: reading it needs a rollback and a rebuild, both
writes, so it is taken on the copy only, and its refusal (code `preexisting_rebuild_errors`)
deletes the copy (FR-004). The field is named for the call that produces it, `GetWhatsWrongCount()`,
rather than for the code that refuses on it, so that the `code` and the `signal` a reader holds side
by side on a `Refusal` (section 4.2) cannot be mistaken for each other.

| Field | Type | Source |
|---|---|---|
| `document_type` | int | `swDocumentTypes_e`; not `swDocPART(1)` is a refusal |
| `solid_body_count`, `sheet_body_count` | int | `IPartDoc.GetBodies2(0, false)`, `GetBodies2(1, false)` |
| `is_weldment` | bool \| null | `IPartDoc.IsWeldment()` |
| `sheet_metal_folder_present` | bool \| null | `IFeatureManager.GetSheetMetalFolder()` non-null |
| `mesh_body_present`, `graphics_body_present` | bool \| null | `IBody2.IsMeshBody()`, `IsGraphicsBody` |
| `is_3d_interconnect` | bool \| null | any `IFeature.Is3DInterconnectFeature` |
| `imported_file_names` | list[str] | `IFeature.GetImportedFileName` |
| `configuration_names` | list[str] | `IModelDoc2.GetConfigurationNames` |
| `rms_named_folders` | list[{`name`: str, `member_persist_refs`: list[str]}] \| null | folders where `GetTypeName2() == "FtrFolder"`, with each folder's members. This row is what makes `rms_named_folder_wrong_members` decidable in `scope.py` from `ScopeSignals` alone, which is what puts FR-007's refusal ahead of the copy |
| `external_reference_count` | int | `ListExternalFileReferencesCount2()` |
| `save_flag_dirty` | bool | `GetSaveFlag()` on the source, when it is open |
| `read_only` | bool | |
| `rebuild_error_count` | int | `GetWhatsWrongCount()` after the baseline rollback and rebuild |
| `vault` | `{path, revision}` \| null | EPDM; recorded, never a refusal reason |

A `null` signal is **not** treated as a pass. It produces an `unresolved` scope item naming the
signal, and a run may not proceed on an unresolved multibody, weldment, sheet-metal, mesh, 3D
Interconnect **or `rms_named_folders`** signal. An unreadable folder listing is `signal_unresolved`
for the same reason every other unreadable signal is; otherwise the new row reopens the FR-007 hole
from the other side.

### 4.2 `ScopeReport`

`verdict: "ok" | "refused" | "unresolved"`, `signals_probe: ScopeSignals` (read from the open
source by `remodel.probe_scope`, and **the only signals the verdict is made from**, because the
verdict has to be reached before the copy exists), `signals: ScopeSignals | null` (re-read on the
copy at `remodel.open` step 12; null on a refused run, which never got that far), `probe_id: str`,
`refusals: list[Refusal]`, `notes: list[str]` (for example "imported dumb solid: the reorganize
stage is a no-op", "surface bodies present: gate coverage is partial").

`Refusal`: `code`, `message`, `signal`. Closed set of codes: `not_a_part`, `source_dirty`,
`external_refs`, `multibody`, `weldment`, `sheet_metal`, `mesh_or_graphics_body`,
`three_d_interconnect`, `preexisting_rebuild_errors`, `rms_named_folder_wrong_members`,
`signal_unresolved`. **Every failing signal is reported**, not just the first: a message that
names one of two reasons sends the engineer back twice.

`Refusal.code` and the bridge's `result.error_code` for preflight conditions are **one
vocabulary**, not two that happen to agree on three tokens. `contracts/bridge-remodel.md`'s
"Error codes" table is authoritative for every token the bridge raises (`not_a_part`,
`source_dirty`, `external_refs`, `preexisting_rebuild_errors`,
`rms_named_folder_wrong_members`); this section is authoritative for the gate-only tokens the
bridge never raises (`multibody`, `weldment`, `sheet_metal`, `mesh_or_graphics_body`,
`three_d_interconnect`, `signal_unresolved`). The bridge's spelling wins in both halves, because a
token that differs by an underscore is a refusal that maps to no Python class in
`bridge/remodel_client.py`. Note also that the bridge refuses `not_a_part`, `source_dirty` and
`external_refs` **before** any signals are returned, so the pure `ScopeGate.evaluate(signals)`
never reaches those three verdicts from `ScopeSignals` alone even though
`external_reference_count` is in the table; they enter `scope.refusals` only when the host records
the bridge's refusal, which is precisely why the tokens have to be identical.

---

## 5. `SourceAttestation` (`source-attestation.json`)

| Field | Type | Rules |
|---|---|---|
| `path` | str | The engineer's file. Never opened for writing, never saved, never renamed, never deleted |
| `length_bytes` | int | |
| `last_write_utc` | ISO 8601 | |
| `sha256` | str | |
| `source_design_id` | str | `DocumentIds.DesignId(path)` under the same normalization `DocumentIds` uses (trim, `/` to `\\`, lowercase), computed at copy time. **This is what the exceptions carry-forward matches on** (`contracts/run-artifacts.md`). The plan's `document_id` and this run's package `design_id` stay the **copy's** and are not overloaded; the copy's path is unique to the run, so they can never match a prior run's |
| `recorded_at` | ISO 8601 | Before the copy is made |
| `rechecked_at` | ISO 8601 \| null | At report time |
| `matches` | bool \| null | All three re-checked values equal. **`False` is a hard failure of the run**, whatever the copy looks like |
| `vault_path`, `vault_revision` | str \| null | EPDM source; the copy is taken out of the vault into the run folder |
| `copy_path`, `copy_sha256_after_save` | str, str \| null | Recorded so the artifact in the run folder is identifiable later |

---

## 6. Grades: reused from feature 003

`RmsGrade` is feature 003's model (`reviewer/src/swreview/checks/rms/grade.py`) and is **not**
redefined here. Its headline is counts per bucket (failed, warned, checked, skipped, unresolved,
out of scope); the fraction `checked / (checked + failed + warned)` is secondary; the unresolved
rule ids are always named alongside. There is no letter grade: a letter is precisely the
confident-but-unsupported artifact Principle I exists to prevent.

`grades.json` is `{before: RmsGrade, after: RmsGrade, per_rule: list[RuleDelta]}` where
`RuleDelta` is `{rule_id, before_outcome, after_outcome, subjects_before, subjects_after}`. Both
grades come from `run_rms_check` over `package-before.json` and `package-after.json`, with no
provider constructed in either call.

---

## 7. Run folder layout

Created by the existing `RunFolders` helper (`extractor/SwReview.AddIn/Review/RunFolders.cs`), so
the naming convention stays in one place: `<run_root>/<yyyyMMdd-HHmmss>-<doc>-remodel/`.

| Path | Written by | Contains |
|---|---|---|
| `copy/<doc>-RMS.SLDPRT` | `File.Copy`, then SOLIDWORKS | The working copy; the only file SOLIDWORKS may write |
| `plan.json` | `remodel/plan.py` | `RemodelPlan`, rev 1 then rev 2, then state updates |
| `changes.jsonl` | `remodel/apply.py` | Two `ChangeRecord` lines per change |
| `package-before.json`, `package-after.json` | the extractor, ModelCheck profile | The copy's tree at open and after the last change |
| `rms-before.json`, `rms-after.json` | `checks/rms/run.py` | Rule results, no LLM |
| `grades.json` | `checks/rms/grade.py` | Section 6 |
| `geometry.json` | `remodel/geometry.py` | The `GeometryReading`s and the `GateResult` |
| `source-attestation.json` | `remodel/runner.py` | Section 5 |
| `report.md` | `remodel/runner.py` | Change list, grade delta, geometry comparison, rebuild list with a reason each |
| `events.jsonl`, `session.json` | the shared `EventSink` and `SessionSink` | Section 10 |
| `remodel.log` | the bridge host | One line per request: command, elapsed, gated members, target path |

**Discard** closes the copy without saving and deletes `copy/` only. Every other file stays:
deleting the folder would lose the evidence Principle VI asks for, and "what did it propose?"
must stay answerable after the engineer says no.

---

## 8. Bridge commands and the `RemodelSecret` scope

Commands, not tools, because the bridge already has a secret policy, a guard, a circuit breaker,
a per-request log of gated members, and a `DocumentPresenceDispatcher`. **No `remodel.*` command
takes a document parameter.** The target is not validated; it is unreachable.

**`contracts/bridge-remodel.md` is the single source for every `remodel.*` request and response
shape.** This section restates none of them on purpose: a second copy of twelve row shapes is
exactly the drift this package has already paid for once, and `contracts/README.md` already assigns
those shapes to that page. What follows is the command list; the shapes, the error codes and the
per-command sequences live there.

| Command |
|---|
| `remodel.probe_scope` |
| `remodel.open` |
| `remodel.snapshot` |
| `remodel.rename` |
| `remodel.reorder` |
| `remodel.folder` |
| `remodel.describe` |
| `remodel.equation` |
| `remodel.rebuild` |
| `remodel.geometry` |
| `remodel.save` |
| `remodel.close` |

Three rules that hold across the whole protocol:

1. **Persist refs only.** `IModelDocExtension.GetObjectByPersistReference3(Object, Int32&)`
   (VERIFIED, with a ByRef error code that is read on every resolve) plus `IsSamePersistentID`.
   The C# side resolves the ref, reads `IFeature.get_Name`, and then calls the name-based API in
   one breath.
2. **`remodel.folder` with `op: "dissolve"` is refused in v1** by the guard, because
   `IModelDoc2.EditDelete` is not allowlisted. The value stays in the protocol so that stage 2
   adds an allowlist entry and a handler branch, not a new command.
3. **`remodel.rename` takes a feature persist ref and nothing else.** There is no dimension form,
   because v1 addresses no dimension (FR-030). The command has exactly two uses: repairing a
   duplicate feature name before any reorder, and naming a folder the run just created.
4. **`remodel.probe_scope` is the only command that touches the source, and it only reads it.**
   It reaches the engineer's already-open document through `ISldWorks.GetOpenDocumentByName`
   (VERIFIED), calls read members only, never passes through `RemodelGuard`'s allowlist branch
   (every member it uses is a read that `ReadOnlyGuard` already permits), and never returns or
   retains an `IModelDoc2`. `remodel.open` refuses with `scope_not_probed` unless it is handed the
   `probe_id` of a probe this bridge session performed on this exact canonicalized source path.
   That is what makes FR-001's "before any copy is made" structurally true rather than a
   convention (`contracts/bridge-remodel.md`).

**Secret scope.** `ToolServiceHost` mints `ReviewSecret` and `GeneralChatSecret` today, bounded
by `ScopedSecretPolicy`. `RemodelSecret` is a third, authorizing `ping | remodel.*` and nothing
else, handed only to the remodel backend session.

| Secret | Authorizes | Refused |
|---|---|---|
| `ReviewSecret` | the review command set | every `remodel.*` |
| `GeneralChatSecret` | the general chat command set | every `remodel.*` |
| `RemodelSecret` | `ping`, `remodel.*` | everything else, including `interference` |

The existing test asserting that the MCP function names and the terminal profile's
`enabled_tools` are the same list gains a sibling asserting the remodel commands are in
**neither**.

---

## 9. `rms_types.yaml`: one new key

The single normative RMS type table
(`reviewer/src/swreview/checks/rms_types.yaml`, owned by feature 003) gains exactly one key,
`default_group_by_class`, so that the checker and the planner cannot disagree about what "should"
means. This is the only edit feature 004 makes to a feature 003 artifact.

```yaml
# The planner's target group per feature class (feature 004). The checker grades what is;
# this says what should be. One table, so the two cannot drift.
default_group_by_class:
  sketch: follows_consumer        # the single consumer's group; unconsumed -> 2-Construction
  reference: 1-Ref
  construction: 2-Construction
  solid: 3-Core
  shell: 3-Core                   # intra-rank rms.core.shell_last puts it last inside Core
  cut: 4-Detail
  hole: 4-Detail
  draft: 5-Modify
  pattern: 5-Modify
  fillet: 3-Core                  # the safe default; decide_fillet may move a cosmetic one
  chamfer: 3-Core                 # same reasoning; no judgement tool in v1
  ambiguous: needs_judgement      # ICE; classify_unknown, else unresolved
  unknown: unresolved             # never moved (Principle I)
judgement_classes: [fillet, ambiguous]
```

Three rules that are code, not table, and are tested as such:

1. **A fillet or chamfer with dependents can never target `6-Quarantine`**, because that
   guarantees an `rms.quarantine.has_no_children` failure. It stays at `3-Core` and the choice is
   recorded as a `Deviation`. Enforced in the planner and again inside `decide_fillet`'s
   validation, so a model proposal cannot bypass it.
2. **Every fillet left at `3-Core` is listed in the report** as "reviewed as structural; move to
   Quarantine if cosmetic" (owner decision OQ-4).
3. **`unresolved` is terminal.** An unknown `GetTypeName2` is never guessed into a group and never
   reported as movable.

---

## 10. Events and session: reuse, not re-creation

A remodel run writes `events.jsonl` and `session.json` in the same shapes a review does.

- `EventSink` (today private to `agent/runner.py:232`) is **extracted** to `agent/events.py` and
  shared. It remains the only place an event gets its `seq` and its timestamp, and the only
  writer of `events.jsonl`.
- `AgentEvent` is unchanged: `{seq >= 1, at, type, body}`, with `chat-events.schema.json`
  authoritative for every body.
- The `EventType` literal set is **unchanged**. A remodel run uses `session.started`,
  `text.delta`, `text.done`, `tool.started`, `tool.finished`, `coverage`, `turn.ended`,
  `session.ended` and `error`. It emits no `finding`, `evidence.requested`,
  `evidence.answered` or `disposition` events, because it produces a plan, not findings. Adding
  remodel-specific event types is explicitly rejected: the pane's existing stream reader, the
  redactor and the SSE fan-out all stay unchanged.
- Progress that is not an agent event (`remodel.progress`, `remodel.change`) travels on the
  host-to-page channel, not on `events.jsonl`, because it belongs to the deterministic executor
  and not to the model's turn.
- `session.json` is written through `ToolRegistry.build(context, sink=SessionSink(context))`, so
  `tool_result_ids` point at steps that exist. That is the same fix feature 003 US6 makes for the
  Model check tab, and 004 depends on it rather than repeating it.
- `ReviewRun` is **not** reused. Its checklist, findings, evidence requests, coverage buckets and
  finalization are review-shaped and none of them fit a remodel run.

---

## 11. Run state

`RunState` is a single field on `RemodelPlan`, rewritten to `plan.json` at every transition, so
the state survives a crash and the pane can read it from disk.

| State | Entered when | Artifacts complete at this point | Copy present |
|---|---|---|---|
| `planned` | `plan.json` rev 1 is written | `package-before.json`, `rms-before.json`, `geometry.json` baseline, `source-attestation.json` (recorded half), `plan.json` | yes |
| `judging` | `remodel.start` is accepted | plus `events.jsonl`, `session.json` growing | yes |
| `applying` | `plan.json` rev 2 is written | plus `changes.jsonl` growing | yes |
| `verifying` | the last planned change reaches a terminal status, or a limit is hit | `changes.jsonl` complete, `package-after.json`, `rms-after.json`, `grades.json` | yes |
| `saved` | verification passed and `Save3` returned no errors | plus `geometry.json` final, `report.md` | yes |
| `truncated` | as `saved`, but a limit stopped the run before every planned change was applied | same, and the report names how many of the planned changes were applied and which were not | yes |
| `failed` | any abort: scope refusal, target verification failure, contract violation, gate `fail` or `unresolved`, save error, save warning `swFileSaveWarning_RebuildError`, or a source attestation mismatch | every artifact produced so far, plus `report.md` | **no**: the copy is discarded on a verification failure; `report.md` says why |
| `discarded` | the engineer presses Discard on a run that reached `saved` or `truncated` | everything except `copy/` | no |

Rules the transitions obey:

- The only path into `saved` or `truncated` runs through `verifying`, and `verifying` requires
  `GetWhatsWrongCount() == 0`, every `IFeature.GetErrorCode2 == swFeatureErrorNone`, and
  `GateResult.verdict == "pass"` at the `IDENTITY` profile. An `unresolved` gate does **not**
  save.
- `judging` is skippable. If no provider is configured or the model declines, the run goes
  `planned -> applying` and records a `PlanCoverage` item saying the judgement phase contributed
  nothing.
- A save that returns `errors != 0` is `failed`. A save that returns
  `warnings & swFileSaveWarning_RebuildError` is **`failed` with a saved artifact**, and the
  report says exactly that rather than counting it as a success.
- `truncated` is never silent. It is a distinct state, a distinct report headline, and a distinct
  test.
- **A run never auto-resumes.** After a crash the state on disk is whatever transition last
  completed; recovery is manual. A resumed run over a tree that was not re-verified is exactly
  the wrong risk, and a test asserts that resume is refused.

Crash recovery reads the state from artifacts rather than trusting the last written `state`:

| Observed on disk | Inferred |
|---|---|
| no `plan.json` | the run never reached `planned`; delete or keep the folder, nothing was written to any document |
| `plan.json` present, `changes.jsonl` absent | `planned` or `judging`; the copy is untouched |
| last `changes.jsonl` line is `attempting` | the process died inside that change; it names exactly what was in flight |
| last line terminal, no `report.md` | `applying` or `verifying` was interrupted |
| `report.md` present | the state it records is authoritative |

---

## 12. Relationships

```text
RemodelRun 1 -- 1 RemodelPlan -- 1 SourceAttestation
RemodelPlan 1 -- * PlanTarget -> Feature (feature 003 IR)
RemodelPlan 1 -- * FeatureRank -> PlanTarget ; 1 -- 1 OrderPlan -- * Move
RemodelPlan 1 -- * Pin ; 1 -- * RebuildEntry ; 1 -- 1 FolderPlan -- * FolderAction | FolderRefusal
RemodelPlan 1 -- * DescriptionProposal | GlobalProposal | RenamePlan | Deviation | PlanCoverage
RemodelPlan 1 -- * RejectedProposal ; GlobalProposal 1 -- * GlobalEvidence
RemodelPlan 1 -- * PlannedChange 1 -- 2 ChangeRecord (attempting, then terminal)
ChangeRecord 0..1 -- 1 undo command (null for folder.create and save in v1)
RemodelRun 1 -- 2 GeometryReading (copy_at_open, copy_at_end) 1 -- 1 GateResult
RemodelRun 1 -- 2 EvidencePackage (before, after) 1 -- 2 RmsGrade -> grades.json
RemodelRun 1 -- 1 ScopeReport -- 1 ScopeSignals -- * Refusal
RemodelRun 1 -- 1 session.json + events.jsonl (shared EventSink and SessionSink)
```
