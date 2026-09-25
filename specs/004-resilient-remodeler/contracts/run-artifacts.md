# Run Artifacts

**[data-model.md](../data-model.md) is normative for every field name on this page.** What follows
is the file layout plus **examples** of the models that file defines; where an example and the data
model ever differ, the data model is right and the example is a defect. One test loads every
example below into the pydantic model named beside it, so an example cannot drift silently while
the Phase 5 and Phase 6 artifact tests are written against it.

One run, one folder, created by the existing `RunFolders` helper so the naming convention stays in
one place:

```text
<run_root>/<yyyyMMdd-HHmmss>-<doc>-remodel/
```

The `-remodel` suffix sorts beside feature 003's `-check` and feature 001's review folders and
makes the folder obviously disposable. **The copy lives only here.** It never sits beside the
source: one bad path join beside a source inside an EPDM vault writes into the vault.

## Files

| File | Written by | Schema | Notes |
|------|-----------|--------|-------|
| `copy/<doc>-RMS.SLDPRT` | `RemodelCopy`, then SOLIDWORKS | n/a | The working copy and **the only file SOLIDWORKS may write**. Created by a filesystem copy with `overwrite: false` before any document handle exists |
| `plan.json` | `remodel/plan.py` | `RemodelPlan`, `plan_schema: "1.0"` | One file, rewritten in place: `plan_revision` is 1 after the planner and 2 after the judgement phase, and `state` is rewritten at every transition so the run's state is readable from disk after a crash (data-model.md section 11) |
| `changes.jsonl` | `remodel/apply.py` | one `ChangeRecord` per line, append-only | Both the undo record and the change list the pane shows |
| `package-before.json` | `SwReviewDump` with 003's `DumpProfile.ModelCheck` | feature 001 `contracts/ir.schema.json` 1.2.0, `extractor.profile: "model_check"` | The copy at open, which is the source's tree |
| `package-after.json` | the same dumper | the same schema | After the last change |
| `rms-before.json` | `checks/rms/run.py::run_rms_check` | 003's `RmsCheckRun` | Over `package-before.json` |
| `rms-after.json` | the same entry point | the same schema | Over `package-after.json` |
| `grades.json` | `remodel/report.py` | below | 003's `RmsGrade` before and after, plus the per-rule delta |
| `geometry.json` | `remodel/report.py` | below | Both `GeometryReading`s and the `GateResult` |
| `source-attestation.json` | `RemodelCopy`, re-checked by `remodel/report.py` | below | A difference between plan time and report time is a **hard failure of the run** |
| `exceptions.json` | carried forward before the plan is written | feature 001 `ExceptionStore` | See "Exceptions carry-forward" below |
| `report.md` | `remodel/report.py` | prose | The engineer-facing summary |
| `events.jsonl` | `agent/events.py` | feature 002 `contracts/chat-events.schema.json` | The agent run, same shape as a review, through the **extracted** sink |
| `session.json` | the recorded `ToolRegistry` steps | feature 001 session schema | So `tool_result_ids` reference steps that exist |
| `remodel.log` | `BridgeDispatcher` | one line per request | Command, elapsed, gated members, and the **target path** of every mutating call |

`report.md` is the product, and its section order is fixed, because Principle VI fixes the first
three and FR-056 fixes the last:

| # | Section | Content |
|---|---------|---------|
| 1 | Headline | One sentence. A run that moved 3 of 200 features says "this part needs rebuilding", not "success". A `truncated` run says so here. A changed source attestation says so here, ahead of everything else |
| 2 | Change list | Every attempted change with its outcome, and the copy path, with the statement that every write of the run went to that path, cited from `remodel.log`'s per-request target and from each `ChangeRecord.target_path` (FR-041) |
| 3 | Grade | Before and after as counts per bucket, the fraction secondary, **the unresolved rule ids named alongside**, then the per-rule delta |
| 4 | Geometry | The compared quantities, the profile and its calibration reference, the verdict, and the coverage statement of what the gate cannot detect |
| 5 | Rebuild list | One reason per entry from the closed taxonomy, with the blocking edge, interloper, span or cycle |
| 6 | Deviations | Every fillet defaulted to `3-Core` as "reviewed as structural; move to Quarantine if cosmetic", and every group the model assigned |
| 7 | Judgement | Per accepted proposal, the provider and the model that produced it; then `rejected_proposals` with the rule that refused each one, listed rather than omitted (FR-016, US4 scenario 7); then the sentence that the added globals drive nothing yet (FR-030) |
| 8 | Attestation | The recorded and re-checked path, length, last-write time and hash, and the verdict |
| 9 | Credit and status | The Resilient Modeling Strategy credited as the source of the rules and the group vocabulary, and the sentence that **this copy is a proposal the engineer accepts or discards, not an engineering acceptance result** (FR-056) |

Section 9 is not a footer that may be dropped when the report is long. It is the sentence that
keeps a clean rebuild from reading as an approval, which is the same reason there is no letter
grade.

## `changes.jsonl`

One line is written **before** the call with `status: "attempting"` and a second after it with
`applied`, `failed`, `rolled_back` or `rollback_failed`, so a hard crash mid-change leaves an
`attempting` line naming exactly what was in flight. The file is append-only; a later line never
rewrites an earlier one.

```jsonc
{"seq":17,"at":"2026-09-16T14:22:31.481Z","kind":"reorder",
 "subject":{"feature_id":"feat:0042","name":"Fillet3","persist_ref":"<b64>"},
 "before":{"index":42,"anchor":"Cut-Extrude2","anchor_persist_ref":"<b64>","location":"after"},
 "after":{"index":61,"anchor":"Chamfer1","anchor_persist_ref":"<b64>","location":"after"},
 "undo":{"command":"remodel.reorder","params":{"feature_persist_ref":"<b64>",
         "anchor_persist_ref":"<b64 of Cut-Extrude2>","location":"after"}},
 "rebuild_errors_before":0,"rebuild_errors_after":0,
 "status":"applied","error_code":null,"error":null,
 "target_path":"C:\\runs\\20260916-142201-bracket-remodel\\copy\\bracket-RMS.SLDPRT",
 "elapsed_ms":310}
```

The field table below is `data-model.md` section 2 restated; that section is normative and
`tasks.md` T074 asserts exactly this list.

| Field | Meaning |
|-------|---------|
| `seq` | Monotonic from 1 within the run; the pane's `remodel.show_change` addresses a change by it |
| `at` | ISO 8601 |
| `kind` | `rename`, `describe`, `reorder`, `folder.create`, `folder.rename`, `equation.add`, `equation.edit`, `save`. `folder.dissolve` is reserved and never written in v1 |
| `subject` | The feature the change acts on, addressed by **persistent reference**; `name` is recorded for the report and is never used to address anything |
| `before` / `after` | The recorded state, read from the seat, never assumed |
| `undo` | The exact inverse command and parameters, derived by the pure `apply_log.derive_undo(change)`; `null` means no in-place inverse exists and is a deliberate value |
| `rebuild_errors_before` / `_after` | From `remodel.rebuild` on each side of the change |
| `status` | `attempting`, `applied`, `failed`, `rolled_back`, `rollback_failed`. The fifth is not a dressed-up `failed`: `failed` means the change never landed, `rollback_failed` means it landed, raised the rebuild-error count and could not be undone. Only `rollback_failed` ends the run |
| `error_code` | The bridge `error_code` when the change failed, else `null` |
| `error` | The prose sentence beside the code, else `null`. Never parsed |
| `target_path` | The path `VerifyTarget` confirmed for this write. With `remodel.log`'s per-request target this is what makes FR-041 checkable per change; one test asserts the two agree |
| `elapsed_ms` | Wall clock for the bridge call, or `null` on the `attempting` line |

After every change: `ForceRebuild3(false)` and the error reading. A count **above the run's
baseline** means the change is inverted, the inversion is confirmed by a second rebuild, the pair
is recorded, and the run continues. A count at or below baseline is left alone: a part that
already had errors at baseline is refused before the run starts, so the baseline is normally 0.

### The inverse per kind

All derived by the pure `apply_log.derive_undo`, one test each.

| kind | inverse |
|------|---------|
| `rename` | rename back to the recorded previous name |
| `reorder` | reorder back to the recorded anchor and location |
| `folder.create` | **none in v1.** See below |
| `folder.rename` | rename to the recorded previous name |
| `describe` | write the recorded previous text (`""` when there was none). A feature whose description read back as `null`, meaning unreadable, is refused by the planner up front and never described |
| `equation.add` | `IEquationMgr.Delete(index)`, in reverse order of addition, subject to the never-delete-a-referenced-global rule |
| `equation.edit` | `remodel.equation` with `op: "set"` and the recorded `before.equation_text`. An in-place edit is its own inverse, which is why FR-029's repair is a distinct kind and not a delete plus an add |
| `save` | none. The copy is saved once, at the end, only after the gate passes |

**`folder.create` has no per-change inverse in v1, and that is a deliberate consequence of the
allowlist.** Dissolving a folder needs `IModelDoc2.EditDelete`, which is not on the stage-1
allowlist, so a failed folder creation cannot be undone in place. It escalates straight to the
catastrophic fallback below. This is acceptable because folders are created last among the
structural changes, from runs the planner has already proven contiguous, and because the
alternative (allowlisting the one call that can delete real features on a mis-selection) is the
single highest-risk allowance the guard exists to prevent.

### The three undo tiers, in order

1. **Per-change forward inverse.** Every change kind above that has one. This is the primary
   mechanism because it lets the run continue past one bad change.
2. **Catastrophic fallback.** Delete the copy, re-copy the source, and replay `changes.jsonl` up
   to the last `applied` line. Deterministic, because every change is persist-ref addressed. This
   is what a failed `folder.create` triggers.
3. **`IModelDoc2.EditUndo2`: never.** It returns **void** (VERIFIED), so there is no way to tell
   whether it did anything, and it shares the UI undo stack the engineer can also touch. It is not
   on the allowlist.

### Limits

Enforced by the executor and never by the model: `max_changes` 250, `max_minutes` 20 wall clock,
`max_rebuild_seconds` 120. Hitting one is `truncated`: stop, finalize every artifact, and report
how many of the planned changes were applied and which were not. **Never a silent partial
success.**

## `plan.json`

An example of `RemodelPlan` (data-model.md section 1), abbreviated but with every field name as
that section defines it:

```jsonc
{
  "plan_schema": "1.0",
  "plan_revision": 2,
  "run_id": "20260916-142201-bracket-remodel",
  "created_at": "2026-09-16T14:22:01Z",
  "updated_at": "2026-09-16T14:41:55Z",
  "state": "saved",
  "source": { },                                 // SourceAttestation, section 5
  "copy_path": "C:\\runs\\20260916-142201-bracket-remodel\\copy\\bracket-RMS.SLDPRT",
  "document_id": "...", "configuration": "Default", "configuration_names": ["Default"],
  "package_before": "package-before.json",
  "type_table_version": "1.0.0", "type_table_calibrated_version": "1.0.0",
  "scope": {"verdict": "ok", "signals": { }, "signals_probe": { },
            "refusals": [], "notes": []},
  "targets": [{"feature_id": "feat:0007", "name": "Cut-Extrude1", "type_name": "ICE",
               "feature_class": "cut", "current_group": null, "target_group": "4-Detail",
               "basis": "type_table", "decided_by": "planner", "state": "resolved",
               "candidates": [], "rationale": null, "provider": null, "model": null}],
  "ranks": [{"feature_id": "feat:0007", "group_index": 4, "intra_rank": 2,
             "intra_rule_id": "rms.detail.holes_last", "original_index": 7, "rankable": true}],
  "order": {"achievable": ["feat:0001"], "kept": ["feat:0001"],
            "edit_script": [{"feature_id": "feat:0042", "anchor_feature_id": "feat:0031",
                             "location": "after"}],
            "move_count": 1, "cycle": null},
  "pins": [{"feature_id": "feat:0031", "desired_index": 4, "achievable_index": 12,
            "blocking_edge": {"parent_id": "feat:0012", "child_id": "feat:0031"},
            "reason": "held below its parent feat:0012"}],
  "rebuild": [{"feature_id": "feat:0044", "name": "Fillet7", "reason": "backward_reference",
               "detail": "parent feat:0061 is in 6-Quarantine",
               "blocking_edge": {"parent_id": "feat:0061", "child_id": "feat:0044"}}],
  "folders": {"actions": [{"op": "create", "name": "3-Core",
                           "member_feature_ids": ["feat:0003", "feat:0004"],
                           "contiguous": true, "existing_folder_id": null,
                           "status": "planned"}],
              "refusals": []},
  "renames": [{"feature_id": "feat:0019", "before_name": "Fillet1", "after_name": "Fillet1_2",
               "reason": "duplicate_name"}],
  "descriptions": [{"feature_id": "feat:0007", "before": "", "text": "Mounting slot",
                    "source": "model", "rationale": "...",
                    "provider": "openai", "model": "<model id>", "validation": "accepted"}],
  "globals": [{"name": "shell_thickness", "expression": "3", "rationale": "...",
               "evidence": [{"feature_id": "feat:0019", "parameter": "shell_thickness",
                             "value_m": 0.003, "document_length_unit": "mm",
                             "value_document_units": 3.0,
                             "equation_text": "\"shell_thickness\" = 3"}],
               "provider": "openai", "model": "<model id>", "validation": "accepted",
               "order_index": 1}],
  "rejected_proposals": [{"at": "2026-09-16T14:31:02Z", "tool": "propose_global",
                          "arguments": {"name": "PlateWidth", "expression": "50",
                                        "rationale": "...", "evidence": []},
                          "reason": "global name must be lower_snake_case, 2 to 32 characters",
                          "rule": "global.name_pattern",
                          "provider": "openai", "model": "<model id>"}],
  "deviations": [{"kind": "fillet_default_core", "feature_id": "feat:0052",
                  "chosen": "3-Core", "rationale": "...",
                  "report_line": "reviewed as structural; move to Quarantine if cosmetic"}],
  "changes": [ ],                                // PlannedChange, section 1.11
  "limits": {"max_changes": 250, "max_minutes": 20, "max_rebuild_seconds": 120},
  "coverage": [{"item": "sketch dimensions", "reason": "not carried by IR 1.2.0",
                "feature_ids": []}]
}
```

There is no `revisions[]` array and no `stage` field. The plan is one object rewritten in place:
`plan_revision` says whether the judgement phase has run, and `state` says where the run is
(data-model.md section 11). Keeping two revisions inside one file would mean the pane could read a
state that is no longer true, which is the one thing this artifact exists to prevent.

`rebuild[].reason` is a closed set of exactly eight, and this is the product of stage 1. The v1
RMS-named-folder refusal is **not** a ninth reason: it is a scope refusal
(`rms_named_folder_wrong_members`, data-model.md section 4.2) that refuses the whole part before
anything is copied, and it appears in `scope.refusals` and in `folders.refusals`, never here.

| Reason | Detection (pure) |
|--------|------------------|
| `backward_reference` | some parent `p` has `group(p) > group(f)` |
| `shared_sketch` | a sketch with more than one consumer, so it can be contiguous with only one |
| `splits_group` | the feature sits inside another group's `[first, last]` span in the achievable order |
| `cycle` | the condensed group graph has a cycle; the cycle is named, never looped over |
| `radius_unreadable` | a fillet whose `default_radius` is `None`, such as a variable-radius fillet |
| `ambiguous_name` | two features share a name, so the name-addressed reorder is ambiguous |
| `unclassified` | `GetTypeName2()` is not in `rms_types.yaml`; reported `unresolved`, never "movable" |
| `graph_unreadable` | `child_ids` **and** `parent_ids` are both `None`; never move on an unknown graph |

### How the planner reads the tree

*Added 2026-09-25 (owner, decision 17A; T142, T143).* The planner plans **features**, not
rows, and a package can list one feature on two rows. The extractor walks the tree with
`FirstFeature`/`GetNextFeature` and, under every feature, with
`GetFirstSubFeature`/`GetNextSubFeature`; SOLIDWORKS lists an absorbed sketch in both walks, at
depth 0 just before the feature that consumes it and again at depth 1 under that feature, with
one `persist_ref`. The real packages carry this shape for every absorbed sketch. The rule:

> **A row at depth 1 or deeper whose enclosing row (`folder_id`) is a feature and not a folder,
> and whose `persist_ref` and `type_name` equal those of exactly one depth-0 row of the same
> document, is that depth-0 row listed a second time.** The planner keeps the depth-0 row, drops
> the second listing, and rewrites every `parent_ids`, `child_ids`, `sketch.consumer_ids` and
> `folder_id` that names the dropped id to name the kept one, once.

- The depth-0 row is kept because its position is the feature's place in the flat order
  `ReorderFeature` works on; its readings stand, and the second listing contributes only its
  id, which is the id the other rows' edges name (the dumper's handle index keeps the last id
  it gave a feature).
- A depth-1 row under a **folder** is folder membership in the nested traversal shape and is
  never merged; nothing on the real packages shows a folder member listed twice.
- A second listing whose `persist_ref` names two depth-0 rows is not merged: the real packages
  carry seven system folders of seven types that share one reference, and a reference that
  names two rows cannot say which one a second listing is.
- `plan.json` therefore carries **one `targets[]` entry per feature**, and the coverage item
  `second listings` names every dropped row on every plan ("none" included), so a reader
  counting the package's rows against the plan's targets has the difference in writing.
- The plan type refuses a persist ref that is the subject of more than one `rename` or more
  than one `reorder`: the edit script moves a feature once and the rename plan renames a
  duplicate once, so a repeat is one feature read as two.

*Added 2026-09-25 (decision 17A; T162, T163), found on the same packages.* The sub-feature walk
also lists rows that hold **no** place in the flat order: the Hole Wizard's own profile sketch
is listed only under its hole, after it, and is that hole's parent; the annotation folders and
the lights of the real packages are listed only under their system containers; a derived part's
body and reference folders only under its base feature. The second rule:

> **A row at depth 1 or deeper whose enclosing row is a feature and not a folder, and whose
> `persist_ref` no depth-0 row carries, is carried by the nearest kept feature above it.** It
> is not planned on its own - no target, never the subject or the anchor of a move, never a
> folder member - every edge naming it names the owner instead (an edge from the owner to
> itself is dropped), and its own parents and children become the owner's; an unreadable list
> on either side leaves the owner's list unread.

- A row whose `persist_ref` some depth-0 row carries but that is not a second listing by the
  first rule - two depth-0 rows share the reference, or the one that has it is of another
  type - is **neither** merged nor carried: it is kept as the dump gave it, because it names a
  top-level feature nobody can pick, and the plan type's refusal above is its backstop.
- The coverage item `carried sub-features` names every carried row, and its owner, on every
  plan, "none" included.

## `grades.json`

```jsonc
{"before": {"checked": 24, "failed": 7, "warned": 3, "skipped": 0, "unresolved": 2,
            "out_of_scope": 6, "fraction": 0.706, "unresolved_rule_ids": ["rms.params.units"]},
 "after":  {"checked": 30, "failed": 1, "warned": 3, "skipped": 0, "unresolved": 2,
            "out_of_scope": 6, "fraction": 0.882, "unresolved_rule_ids": ["rms.params.units"]},
 "per_rule": [{"rule_id": "rms.core.shell_last", "before_outcome": "fail",
               "after_outcome": "pass",
               "subjects_before": ["feat:0031"], "subjects_after": []}]}
```

The `RmsGrade` model is feature 003's (`checks/rms/grade.py`), used unchanged so the tab and the
re-modeler report the same number. Counts per bucket are the headline, the fraction is secondary,
and the unresolved rule ids are always named alongside. There is no letter grade: a letter is
precisely the confident-but-unsupported artifact Principle I exists to prevent.

## `geometry.json`

Two `GeometryReading`s (data-model.md section 3.1) and one `GateResult` (section 3.3):

```jsonc
{"before": {"at": "...", "source_sha256": "…", "subject": "copy_at_open",
            "status": 0, "accuracy_level": 2, "recalculated": true,
            "volume_m3": 0.00123456789, "surface_area_m2": 0.0456,
            "center_of_mass_m": [0.01, 0.02, 0.03],
            "principal_moments": [1.1e-5, 2.2e-5, 3.3e-5],
            "mass_kg": 3.21, "density": 2600.0, "material_name": "1060 Alloy",
            "solid_body_count": 1, "sheet_body_count": 0,
            "face_count": 214, "edge_count": 642, "residual": null},
 "after":  { },                                  // the same shape, subject "copy_at_end"
 "gate": {"verdict": "pass", "profile": "IDENTITY",
          "tier_1": {"ran": true, "verdict": "pass", "reason": null},
          "tier_2": null,
          "deltas": [{"quantity": "volume_m3", "before": 0.00123456789,
                      "after": 0.00123456789, "absolute": 0.0, "relative": 0.0,
                      "bound": 1e-9, "within": true}],
          "material_changed": false,
          "coverage_limits": ["a reflection", "a rigid rotation about a symmetry axis",
                              "compensating add and remove pairs",
                              "any difference occupying no volume",
                              "surface- and wire-body differences",
                              "a difference produced by the baseline rebuild itself"],
          "diagnosis": null},
 "tolerances": {"volume_rel": 1e-9, "area_rel": 1e-9, "com_rel": 1e-9, "moment_rel": 1e-9,
                "face_count": "exact", "body_count": "exact",
                "calibrated": true, "calibration_ref": "PROBE-8 2026-09-16"}}
```

`verdict` is `pass`, `fail` or `unresolved`, never a boolean and never inferred from a successful
rebuild. `coverage_limits` is written on **every** run, including a passing one, because Principle
VI requires the report to say what was not checked. `profile` is `IDENTITY` in v1; `EQUIVALENCE` is
reserved for stage 2 and is not selectable.

**Both readings are of the copy** (FR-037): `copy_at_open` after the baseline rollback and rebuild,
`copy_at_end` after the last change. The source is never opened for the comparison in any mode, and
`source_sha256` is the attested hash that makes the baseline stand for the source. There is no
`prototype` reading and no reference body in any tree, so `IPartDoc.InsertPart3` appears nowhere in
stage 1.

## `source-attestation.json`

```jsonc
{"path": "C:\\work\\bracket.SLDPRT", "length_bytes": 482913,
 "last_write_utc": "2026-09-14T09:11:03Z", "sha256": "…",
 "source_design_id": "dsn:4f2a91c0d3b7",
 "vault_path": "…", "vault_revision": "B",
 "recorded_at": "2026-09-16T14:22:01Z",
 "rechecked_at": "2026-09-16T14:41:55Z",
 "matches": true,
 "copy_path": "C:\\runs\\20260916-142201-bracket-remodel\\copy\\bracket-RMS.SLDPRT",
 "copy_sha256_after_save": "…"}
```

`matches` is `true`, `false`, or `null` when the re-check has not run yet. `false` is a **hard
failure of the run**: the report says
so in its first line, and the run is recorded as failed regardless of how well everything else
went. This is the artifact that makes "the engineer's file was never touched" a checked claim
rather than a promise.

## Exceptions carry-forward

Before the plan is written, the newest `exceptions.json` under `run_root` whose run resolves to the
**same source `design_id`** is copied into this run folder, byte-identical. The before and after
grades are then measured against the same waivers the engineer already granted, which is the only
way a grade delta means anything. There is no per-design store in v1.

**The match is on the source's id, never on this run's own.** `DocumentIds.DesignId` is derived
from the document path (`extractor/SwReview.Extractor/Ids/DocumentIds.cs`), and this run's packages
are dumps of the **copy**, whose path is `<run_root>/<ts>-<doc>-remodel/copy/<doc>-RMS.SLDPRT` and
therefore unique to the run. Matching on the package's own `design_id` would select no candidate,
ever - not a Model check run's, and not a previous remodel run's. The two candidate kinds are read
differently, and a candidate carrying neither field is skipped rather than guessed at:

| Candidate | Where its source `design_id` is read |
|---|---|
| a feature 003 `-check` run folder | `package.json`, `design.design_id` - that package is a dump of the source itself |
| a prior `-remodel` run folder | `source-attestation.json`, `source_design_id` - its `package-before.json` carries that run's **copy** id |

**Rebind, then freeze.** `ReviewException.bindings` are `(persist_ref, persist_ref_scope)` pairs and
`persist_ref_scope` is a `document_id` (`reviewer/src/swreview/ir/models.py`), which is path-derived
too, so a carried exception whose scope still names the source resolves to nothing and
`ExceptionStore.refresh` (`reviewer/src/swreview/exceptions.py`) sets it `needs_review` - leaving an
effectively empty store, which is the failure this section exists to prevent. Two rules follow, and
both are recorded steps in the run log rather than silent ones:

1. The copied exceptions' `persist_ref_scope` values are rewritten from the source `document_id` to
   the copy's **before the rules run**. The `persist_ref` bytes come across unchanged with
   `File.Copy`; only the scope changes.
2. `ExceptionStore.refresh` runs **at most once**, against `package-before.json`, and the resulting
   store is applied unchanged to both the before and the after grade. The after grade is never
   re-fingerprinted against `package-after.json`: `fingerprint_kind_for` makes every `rms.*`
   exception a `feature_tree` fingerprint whose digest covers every feature row in index order, so
   a rename or a reorder - this run's whole purpose - would re-open every waiver and move the delta
   for exactly the reason a grade delta is supposed to be readable.

Six cases, each tested: a different source `design_id` is **not** copied; the copied file is
byte-identical; no candidate is not an error, the run proceeds with an empty store; an unreadable
candidate is a **refusal of the run**, never a silent empty store, because a silently empty store
turns a waived finding back into a failure and moves the grade for the wrong reason; a candidate
whose source `design_id` matches is selected across **both** candidate kinds, and one whose copy
`design_id` coincidentally differs is still selected; and after the rebind, `ExceptionStore.match`
over `package-before.json` returns the carried exception `active`, and that same store waives the
same rule over `package-after.json` after a rename plus a reorder of the waived feature.

## Discard

`remodel.discard_copy` closes the document without saving and deletes `copy/`. **Every other file
in this list stays.** Deleting the run folder would lose the evidence Principle VI asks for, and
"what did it propose" must stay answerable after the engineer says no. The run state becomes
`discarded` and `remodel.result` keeps answering from disk.
