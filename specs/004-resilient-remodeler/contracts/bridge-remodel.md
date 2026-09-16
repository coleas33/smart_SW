# Bridge commands: `remodel.*`

The authoritative envelope is `extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md`. This file
adds a command family to it and changes nothing else. Protocol version goes 1.0 to **1.1**,
additively.

**This file is normative for the request and response shapes of every `remodel.*` command**, and
`data-model.md` defers to it for those (`data-model.md` section 8 lists the command names and the
protocol rules and restates no shape). The reverse holds for the records those shapes carry:
`data-model.md` is normative for every field name on a record it defines, and where a JSON block
here differs from that file, the data model is right and the block is a defect. The blocks on this
page are **abridged examples**, not field lists.

These are **commands, not tools**. The bridge already carries a secret policy, a call guard, a
circuit breaker, a per-request log of gated members, and a `DocumentPresenceDispatcher`; the
re-modeler needs every one of them, and none of that exists on the tool side.

## Envelope

Request, one JSON object per line over the named pipe:

```json
{"id": "17", "command": "remodel.reorder", "params": {}, "secret": "<per-launch>"}
```

Response:

```json
{"id": "17", "status": "ok|error|circuit_open", "result": {}, "error": null, "elapsed_ms": 0}
```

One addition to 1.0: on `status: "error"` a `remodel.*` response carries
`result: {"error_code": "<stable token>", "detail": {}}` instead of `null`, so the Python client
maps a refusal to a class without matching on prose. `error` still carries the sentence an
engineer reads. This uses the same "except where noted" allowance 1.0 grants `capture`, which
returns its `Gap` on an error.

## Authorization

`ScopedSecretPolicy` gains a third scope. `ToolServiceHost` mints `RemodelSecret` alongside
`ReviewSecret` and `GeneralChatSecret` and hands it only to the remodel backend session.

| Secret | May call |
|--------|----------|
| `RemodelSecret` | `ping`, `remodel.*`, and nothing else (not `capture`, not `measure`, not `interference`) |
| `ReviewSecret` | unchanged; no `remodel.*` |
| `GeneralChatSecret` | unchanged; no `remodel.*` |

A wrong, missing or out-of-scope secret answers `status: "error"`, `error: "unauthorized"`,
`result: null`, exactly as today, and opens the circuit at once on the Python side
(`BridgeUnauthorizedError`).

Two tests pin the boundary. The existing test that asserts the MCP function names and the
terminal profile's `enabled_tools` are the same list gains a sibling asserting that every
`remodel.*` command is in **neither** list. A secret-policy test asserts the general-chat secret
is refused for every `remodel.*` command and that `RemodelSecret` is refused for `interference`.

## The commands

**No command that writes takes a document parameter.** `RemodelScope` holds the only `IModelDoc2`
the run can reach, and every write goes to it. Exactly two commands name a path at all, both
before the scope exists: `remodel.probe_scope`, which reads an already-open source and returns no
handle, and `remodel.open`, which names the source to copy from and the copy to create. After
`remodel.open` returns, no command in this family accepts a path or a document again. Everything
below is addressed by persistent reference, never by name and never by index, because names change
and indices change on every reorder.

| Command | Params | Result on `ok` |
|---------|--------|----------------|
| `remodel.probe_scope` | `{source_path}` | `{probe_id, source_path, scope_signals}` |
| `remodel.open` | `{source_path, copy_path, run_id, probe_id}` | `{document_path, tag, feature_count, scope_signals, configurations[], document_length_unit, source_attestation}` |
| `remodel.snapshot` | `{}` | `{order[], names{}, descriptions{}, equations[], rebuild_errors, feature_count}` |
| `remodel.rename` | `{persist_ref, new_name}` | `{previous_name, new_name}` |
| `remodel.reorder` | `{feature_persist_ref, anchor_persist_ref, location}` | `{previous_anchor_persist_ref, previous_location, previous_index, new_index}` |
| `remodel.folder` | `{op, name, member_persist_refs[], folder_persist_ref}` | `{folder_persist_ref, name, member_persist_refs[]}` |
| `remodel.describe` | `{persist_ref, text}` | `{previous_text}` |
| `remodel.equation` | `{op, index, text, which_configs}` | `{index, count_before, count_after, previous_text, round_trip_text, helper_path}` |
| `remodel.rebuild` | `{force}` | `{rebuild_errors, whats_wrong[], elapsed_ms, feature_errors[]}` |
| `remodel.geometry` | `{}` | `GeometryReading` |
| `remodel.save` | `{}` | `{path, errors, warnings, save_flag_after}` |
| `remodel.close` | `{discard_copy}` | `{closed, copy_deleted}` |

### `remodel.probe_scope`

**Read-only, and it runs before anything is copied.** FR-001 refuses a run "before any copy is
made and before any SOLIDWORKS document handle to the source exists" when any scope signal fails,
so the signals cannot be read at the end of `remodel.open`: by then the copy is on disk and a
document is open. This command is where they are read instead.

It reaches the engineer's **already-open** source through
`ISldWorks.GetOpenDocumentByName(source_path)` (VERIFIED). It never opens a document, never
returns or retains an `IModelDoc2`, and calls read members only, so it passes through
`RemodelGuard`'s delegation branch to `ReadOnlyGuard` and touches no allowlist entry. A source
that is not open is `source_not_open`: the pane only offers Remodel for the active document, so
this is a protocol error rather than a condition, and opening the source to answer it would give
away the one property the constitution exception rests on.

Sequence:

1. `source_path` ends in `.SLDPRT` (case-insensitive) and exists. Otherwise `not_a_part`.
2. `GetOpenDocumentByName` returns a document and its `GetType()` is `swDocPART = 1` (VERIFIED
   value). Otherwise `source_not_open` or `not_a_part`.
3. `IModelDoc2.GetSaveFlag()` (VERIFIED) is false. Otherwise `source_dirty`.
4. `IModelDoc2.ListExternalFileReferencesCount2()` (VERIFIED) is 0. Otherwise `external_refs`.
5. Read the scope signals, one VERIFIED call per row of the table below, and return them with a
   `probe_id` this bridge session mints and keeps beside the canonicalized `source_path`.

**The verdict is not made here.** The pure `remodel/scope.py` decides it in Python from the
signals, so the refusal table is table-testable with no seat, and the host refuses the run without
ever calling `remodel.open`. The v1 RMS-named-folder refusal (`rms_named_folder_wrong_members`) is
decided from the `rms_named_folders[]` signal in the same pass, which is what makes FR-007's
"before the copy is made" true.

`scope_signals` carries one field per row, each read with one VERIFIED call:

| Signal | Call | Field |
|--------|------|-------|
| solid body count | `IPartDoc.GetBodies2(swSolidBody = 0, false)` | `solid_body_count` |
| weldment | `IPartDoc.IsWeldment()` | `is_weldment` |
| sheet metal | `IFeatureManager.GetSheetMetalFolder()` non-null | `sheet_metal_folder_present` |
| mesh or graphics body | `IBody2.IsMeshBody()`, `IsGraphicsBody` | `mesh_body_present`, `graphics_body_present` |
| 3D Interconnect | `IFeature.Is3DInterconnectFeature` on any feature | `is_3d_interconnect` |
| imported dumb solid | `IFeature.GetImportedFileName` non-null | `imported_file_names[]` |
| surface bodies | `GetBodies2(swSheetBody = 1, false)` | `sheet_body_count` |
| configurations | `IModelDoc2.GetConfigurationNames` | `configuration_names` |
| RMS-named folders | `GetTypeName2() == "FtrFolder"` plus the folder's members | `rms_named_folders[]` with `{name, member_persist_refs[]}` |

**Pre-existing rebuild errors are not in this table and cannot be.** Reading them needs
`EditRollback` to the end of the tree and a `ForceRebuild3`, both writes, and neither may touch
the source. That one refusal is therefore taken on the copy, at step 11 of `remodel.open`, and its
refusal path deletes the copy and closes the document (FR-004). It is the only refusal in the
feature that happens after a copy exists, and the spec says so in those words.

### `remodel.open`

The only command that creates a document handle, and it does so only after the copy exists on
disk. It names two paths: the source to copy **from** and the copy to create. It runs only after
`remodel.probe_scope` has answered and the pure `remodel/scope.py` has returned `ok` on those
signals, which is what keeps every scope refusal ahead of the copy (FR-001).

Sequence, in order, with the call that performs each step:

1. `probe_id` names a `remodel.probe_scope` this bridge session performed, and that probe's
   canonicalized source path equals this request's. Otherwise `scope_not_probed`. The bridge
   cannot check a verdict Python reached, and does not try to; it checks that a probe **happened**,
   which is the part a caller could otherwise skip.
2. `source_path` ends in `.SLDPRT` (case-insensitive) and exists. Otherwise `not_a_part`.
3. `IModelDoc2.GetSaveFlag()` (VERIFIED) is false and
   `ListExternalFileReferencesCount2()` (VERIFIED) is 0, re-read on the still-open source, because
   the engineer may have edited it between the probe and the run. Otherwise `source_dirty` or
   `external_refs`.
4. `copy_path` passes `AssertSaveTarget` (`guard-allowlist.md`): inside this run's folder,
   canonicalized, `.SLDPRT`, not the source, not another run's copy.
5. Record the source attestation: absolute path, length, `LastWriteTimeUtc`, SHA-256, and, when
   the path is inside an EPDM vault, the vault path and the revision as read from the vault. An
   EPDM part is **copied out, never refused for vault reasons**.
6. Set the three system toggles through `ISldWorks.SetUserPreferenceToggle` -
   `swInputDimValOnCreate = 10`, `swShowErrorsEveryRebuild = 77`,
   `swWarnSaveUpdateErrors = 329` (all VERIFIED values) - plus the separately allowlisted
   `ISldWorks.set_CommandInProgress` flag set to `true`
   (**UNVERIFIED that it suppresses the "Cannot reorder" message box; PROBE-1, blocking**),
   recording each previous value for the `finally` restore. Four writes, two allowlist keys
   (`guard-allowlist.md`): `CommandInProgress` is a property and is not covered by the toggle
   member.
7. `File.Copy(source, copy_path, overwrite: false)`. On a sharing violation, fall back to
   `new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)` copied into a
   destination opened `FileMode.CreateNew`, so refuse-to-overwrite survives the fallback
   (PROBE-13). Failure is `copy_failed`; an existing destination is `copy_exists`.
8. `OpenDoc7` with `Silent | LoadModel = 17` exactly, and **never** `ReadOnly(2)` or
   `ViewOnly(4)` (VERIFIED values; asserted as an integer in a unit test). Then assert
   `GetPathName()` equals `copy_path` and does not equal `source_path`.
9. Tag: `ICustomPropertyManager.Add3("SwReviewRemodelRun", 30, run_id, 2)` and read back with
   `Get4` (both VERIFIED; **UNVERIFIED that the round trip works on 2024, PROBE-12, blocking**,
   because it is one of `VerifyTarget`'s four checks). Failure is `tag_failed`.
10. `IFeatureManager.EditRollback(swMoveRollbackBarToEnd = 1, "")` (VERIFIED), then assert no
    feature reports `IFeature.IsRolledBack()` (VERIFIED).
11. `IModelDoc2.ForceRebuild3(false)` (VERIFIED). If `GetWhatsWrongCount()` is non-zero, **stop**
    with `preexisting_rebuild_errors`, **delete the copy and close the document**: the part was
    already broken and nothing after this point could be attributed to the run. This is the one
    refusal in the feature that happens after a copy exists, which is why it is the one refusal
    that has to clean up after itself.
12. Re-read the same scope signals, this time **on the copy**, and compare them field for field
    with the probe's. A difference is `scope_changed`: the document being changed is not the one
    the verdict was reached on, and the run stops with the copy deleted. This costs one pass over
    the tree and closes the only gap the two-step ordering opens.

The returned `scope_signals` are the copy's, measured at step 12, and are what the plan records:
the plan should describe the document the run actually changed. The probe's signals are what the
verdict was made from, and `plan.scope.signals_probe` keeps them so a reader can see both.

The `rms_named_folders[]` row is what makes the v1 refusal decidable in Python: a folder already
carrying one of the six RMS names but holding the wrong members is refused by `scope.py` with
reason `rms_named_folder_wrong_members`, because `IModelDoc2.EditDelete` is not on the stage-1
allowlist and there is therefore no dissolve path. That verdict is reached from the **probe**, so
the part is refused before anything is copied (FR-007).

### `remodel.snapshot`

Read-only, and the same shape before and after every change, so the executor can diff without a
second vocabulary. `order[]` is the tree order as persist refs; `names{}` and `descriptions{}` are
keyed by persist ref (a description read as `null` means **unreadable**, which is not the same as
`""`, which means absent); `equations[]` mirrors the IR `Equation` shape; `rebuild_errors` is
`GetWhatsWrongCount()`.

### `remodel.rename`

`IFeature.set_Name` (VERIFIED). Used for two things and no others: repairing a duplicate feature
name before any reorder, and naming a folder the run just created. `previous_name` in the result
is what `derive_undo` records; the command never guesses it.

### `remodel.reorder`

`IModelDocExtension.ReorderFeature(String FeatureToMove, String TargetFeature, Int32 Location)`
(VERIFIED). `location` is `before` or `after`, mapped to `swMoveLocation_e.Before = 2` or
`After = 3` (VERIFIED values). `swMoveToFolder = 5` is **not** used in v1: folders are created by
wrapping a contiguous run, so there is no move-into-an-existing-folder operation in the plan
(PROBE-5 could turn this into an optimisation later, and the probe is where that is decided).

Both refs are resolved to `IFeature` through `GetObjectByPersistReference3` (VERIFIED, ByRef error
code read on every resolve), their names read with `get_Name`, and the name-based call made in one
breath. An unresolvable ref is `persist_ref_unresolved` and the run stops.

**A `false` return is a contract violation, not a retry.** Legality was decided from the
dependency graph before the call, so `false` means the model of the tree is wrong. The command
answers `reorder_refused`, the executor stops the run, and the copy is discarded. Never retry,
never search for a legal position. This is also why `CommandInProgress` matters: a refusal that
raises the "Cannot reorder" modal on the STA thread is a hang rather than an error (PROBE-1).

### `remodel.folder`

| `op` | v1 behavior |
|------|-------------|
| `create` | Select the contiguous member run with `IFeature.Select2(append, mark)` (VERIFIED), then `IFeatureManager.InsertFeatureTreeFolder2(swFeatureTreeFolder_Containing = 2)` (VERIFIED value), then `set_Name`, then verify membership with `IFeatureManager.FeatureFolderLocation(Feature)` (VERIFIED) for every member |
| `rename` | `set_Name` on a folder resolved from `folder_persist_ref`; the `___EndTag___` marker is matched on its **suffix**, never on the folder's name, because the marker keeps the folder's default name after a rename (PROBE-10) |
| `dissolve` | **Refused in v1** with `not_in_v1`. Reserved for stage 2. `IModelDoc2.EditDelete` is not on the stage-1 allowlist, and a part needing a dissolve is refused by the scope gate before anything is copied |

Members must be contiguous in the current tree order before `create` is called; the planner proves
it, and a non-contiguous request is `folder_members_not_contiguous` rather than an attempt.
Whether 2024 requires contiguity at all is PROBE-4 (blocking); the plan assumes it does, which is
the conservative direction.

### `remodel.describe`

`IFeature.set_Description` (VERIFIED). `previous_text` is returned for the inverse. A feature
whose current description reads back as `null` (unreadable) is **refused up front** by the
planner, because an inverse that writes `""` over something unreadable is a silent edit.

### `remodel.equation`

`op` is `add`, `set` or `delete`.

`set` is how FR-029 is satisfied: an existing global whose equation is broken or whose text must
change is **edited in place**, never deleted and re-added. It is its own operation rather than a
composition because the composition is the failure mode: while a referenced global is missing,
every dependent equation enters an error state that does not clear when the global returns
(research.md R3.5). `set` is also the inverse of itself, which is what gives `equation.edit` a
real per-change undo where `equation.add`'s is a delete.

Every `add` goes through **one** helper, `AddEquationVerified(text, whichConfigs)`, and the
assertion is never inlined at a call site:

1. `IEquationMgr.Add3(index, text, solve, whichConfigs, configNames)` (VERIFIED).
2. Assert `GetCount()` incremented **and** `get_Equation(i)` round-trips to `text`.
3. On failure, `Add2(index, text, solve)` (VERIFIED) and assert again.
4. On a second failure the change fails with `equation_unverified`.

`helper_path` in the result records which of `add3` or `add2` succeeded, so the run report can say
what the seat actually did (PROBE-6 observed `Add3` returning `-1` and adding nothing, silently,
on 2026).

A global variable is created by **syntax**: `"name" = expr`, a quoted left-hand side with no `@`.
`IEquationMgr.set_GlobalVariable` is a VERIFIED ABSENCE, so nothing may treat it as a flag.

`set` goes through **one** helper, `SetEquationVerified(index, text, whichConfigs)`, with the same
shape and the same never-inlined rule as the add helper:

1. Read and return `get_Equation(index)` (VERIFIED) as `previous_text` **before** writing. This is
   what `derive_undo` records; the command never guesses it, and an unreadable previous text fails
   the change with `equation_unverified` rather than writing over something with no inverse.
2. `IEquationMgr.set_Equation(index, text)` (VERIFIED).
3. Assert `GetCount()` is **unchanged** and `get_Equation(index)` round-trips to `text`.
4. On failure, `SetEquationAndConfigurationOption(index, text, whichConfigs, configNames)`
   (VERIFIED) and assert again.
5. On a second failure the change fails with `equation_unverified`. `helper_path` records which of
   `set_equation` or `set_equation_and_configuration_option` succeeded.

Delete-and-re-add is **not** a third fallback and is not reachable from `set`: if neither member
can be proven to have written, the change fails and is inverted. Trading a failed edit for a
missing global is exactly the upstream failure R3.5 records.

`delete` uses `IEquationMgr.Delete(index)` (VERIFIED), is issued in reverse order of addition, and
is only ever the inverse of an `add` this run made. It never deletes a global the part already
had, and never one that any equation still references.

`which_configs` comes from the configuration count `remodel.open` recorded. A single-configuration
assumption is checked, never assumed.

**The number in an equation text is in the document's length unit, not metres.** The document's
unit is returned by `remodel.open` as `document_length_unit` and the executor converts the value
the package carries (metres, as every length in the IR is) into that unit before composing the
text. Whether `get_Value(i)` returns document units or metres is **UNVERIFIED and blocking
(PROBE-2)**. `IDimension` is not read here and `IDimension.set_Name` is not on the allowlist: v1
addresses no dimension at all (FR-030).

### `remodel.rebuild`

`IModelDoc2.ForceRebuild3(force)` (VERIFIED), then the error reading. `feature_errors[]` is the
**primary** reading: one `IFeature.GetErrorCode2(out bool)` (VERIFIED) per feature, and
`swFeatureError_e.swFeatureErrorNone = 0` (VERIFIED value) is the only acceptable value at verify
time. `whats_wrong[]` comes from `GetWhatsWrongCount()` and `GetWhatsWrong` and is **corroborating
only**, because its out-array element type is UNVERIFIED (PROBE-9) and re-joining by name is
fragile where two features inside different folders share a name.

`IModelDoc2.EditRebuild3` is **not** allowlisted: one rebuild call, one meaning.

A rebuild that exceeds `max_rebuild_seconds` is reported as `rebuild_timeout` and the executor
treats it as a limit hit, so the run finalizes as `truncated` rather than hanging.

### `remodel.geometry`

**It takes no parameters because there is nothing to name.** The only document this run can reach
is the scope's copy, and the gate compares that copy against itself: `subject: "copy_at_open"` is
the reading taken immediately after `remodel.open` returns and before the first change,
`subject: "copy_at_end"` the one taken after the last change. The C# side stamps the `subject`
from the run's own phase, so the caller cannot ask for a reading of anything else.

FR-037 says the source is never opened for this comparison, in any mode, and that no reference
body is inserted into any tree, so `IPartDoc.InsertPart3` appears nowhere in stage 1. The baseline
reading stands in for the source because the copy is a byte-for-byte `File.Copy` whose SHA-256 was
recorded before any document handle existed; `GeometryReading.source_sha256` carries that hash on
both readings, so the artifact names the file it speaks for. A read-only handle to the source would
have been the alternative, and it was rejected: it puts a second command that names a document into
a protocol whose central property is that no command names one.

Measured in C# because the measurement calls take ByRef out-parameters that the Python bridge
cannot marshal; **decided in Python**, because the verdict must be table-testable with no seat.
`remodel/geometry.py::evaluate(before, after, tolerances) -> GateResult` has **no COM in its
signature**.

The reading uses the typed interface, not the raw `Object` from `GetMassProperties2`, whose flat
`double[]` index layout is not discoverable by reflection and has changed across API generations:
`IModelDocExtension.CreateMassProperty2()` (VERIFIED), `AccuracyLevel =
swMassPropertyAccuracyLevel_Higher = 2` (VERIFIED value), `SelectedItems` set to the body, then
`Recalculate()` with **its Boolean checked before anything is read**.

`GeometryReading`:

```jsonc
{
  "status": 0,                         // swMassPropertiesStatus_e; anything but OK(0) makes the gate unresolved
  "volume_m3": 0.00123456789,
  "surface_area_m2": 0.0456,
  "center_of_mass_m": [0.01, 0.02, 0.03],
  "principal_moments": [1.1e-5, 2.2e-5, 3.3e-5],   // sorted ascending by the C# side
  "solid_body_count": 1,
  "sheet_body_count": 0,
  "face_count": 214,
  "edge_count": 642,
  "mass_kg": 3.21,                     // recorded and compared SEPARATELY, never as geometry
  "material_name": "1060 Alloy",       // IPartDoc.GetMaterialPropertyName2 (VERIFIED)
  "accuracy_level": 2
  // abridged: `at`, `source_sha256`, `subject`, `recalculated`, `density` and `residual` are
  // part of the record too; data-model.md section 3.1 is the field list.
}
```

Rules this shape encodes, each with a test:

- `principal_moments` is sorted ascending **before** comparison, because two bodies differing by a
  symmetry-degenerate rotation return the same three numbers permuted.
- `mass_kg` and `material_name` are compared separately from geometry. `Mass = Volume x Density`,
  and density comes from the material, which is not geometry. A mass-only delta reports
  `material_changed`, never `geometry_changed`.
- `status` other than `swMassPropertiesStatus_e.OK = 0` makes the verdict `unresolved`, never
  `fail` and never `pass`. The reason for an `unresolved` verdict lives on `GateResult.tier_1.reason`,
  not on the reading; `GeometryReading` carries no `reason` field.
- Every length is metres and every angle is radians. One unit test asserts that no tolerance
  constant is in any other unit and that no comparison mixes an absolute with a relative bound.

Tolerance profiles, in one pure function, neither of which ships until **PROBE-8** has measured
the attained error against a part of exactly known analytic volume (a box and a cylinder) at
`swMassPropertyAccuracyLevel_Higher` and recorded it: a tolerance that has never been compared
against a known answer does not ship.

| Profile | volume_rel | area_rel | com_rel | moment_rel | face_count | body_count | Used by |
|---------|-----------|----------|---------|------------|------------|------------|---------|
| `IDENTITY` | 1e-9 | 1e-9 | 1e-9 | 1e-9 | exact | exact | stage 1, where nothing geometric is supposed to change |
| `EQUIVALENCE` | 1e-6 | 1e-5 | 1e-6 | 1e-5 | warn | exact | stage 2 only, **not shipped in v1** |

Tier 2 (the boolean symmetric difference, the only thing that can detect a **reflection**, since
volume, area and all three principal moments are invariant under any isometry including a mirror)
is **stage 2 only and is not built in v1**. Stage 1 creates no geometry, so it cannot mirror
anything, and running an untested `IBody2.Operations2` (VERIFIED present, behavior UNVERIFIED,
PROBE-18 and PROBE-19) on every stage-1 run would buy nothing and add a failure mode.
`GateResult` is tri-state from day one so stage 2 adds a tier rather than changing a type.

### `remodel.save`

`IModelDoc2.Save3(swSaveAsOptions_Silent = 1, out errors, out warnings)` (VERIFIED, and it takes
**no filename**, which is the structural reason it cannot reach the source). `AssertSaveTarget`
runs first anyway. Options are asserted as exact integers in a unit test: `Silent = 1` and never
`Copy(2)`, `SaveReferenced(4)` or `AvoidRebuildOnSave(8)`.

- `errors != 0` is `save_failed`: a failed run.
- `warnings & swFileSaveWarning_RebuildError (1)` is a failed run **with a saved artifact**, and
  the report says exactly that rather than reporting success.
- Then assert `GetSaveFlag()` is false.

`SaveAs3` on any path and `SetSaveFlag` are not allowlisted, so neither is reachable.

The command refuses with `gate_not_passed` unless the geometry gate has already returned `pass`
for this run. The copy is saved **once**, at the end.

### `remodel.close`

`ISldWorks.CloseDoc` (VERIFIED) on the tagged copy only. With `discard_copy: true` it also deletes
`copy/` and nothing else: **Discard keeps every other artifact**, because deleting the run folder
would lose the evidence Principle VI asks for and "what did it propose" must stay answerable after
the engineer says no. The system toggles are restored in the `finally` that wraps the run,
including on recovery from a previous run that died.

## Error codes

`result.error_code` on `status: "error"`. Each maps to one Python class in
`bridge/remodel_client.py`, which subclasses the existing `BridgeError` so a caller that catches
the base type cannot crash on any of them and every one becomes failed coverage the same way.

| `error_code` | Meaning | Python class | Run effect |
|--------------|---------|--------------|------------|
| `not_a_part` | Source is not an existing `.SLDPRT` | `RemodelPreflightError` | Refused before the copy |
| `source_not_open` | `remodel.probe_scope` was asked about a source SOLIDWORKS does not have open | `RemodelPreflightError` | Refused before the copy; the source is never opened to answer |
| `scope_not_probed` | `remodel.open` was called with a `probe_id` this session did not mint, or one minted for a different source path | `RemodelContractError` | Refused before the copy; this is a bug in the caller, not a condition |
| `scope_changed` | The copy's scope signals differ from the probe's | `RemodelTargetError` | Run aborts; the copy is deleted |
| `source_dirty` | The open source has unsaved changes | `RemodelPreflightError` | Refused before the copy |
| `external_refs` | `ListExternalFileReferencesCount2() != 0` | `RemodelPreflightError` | Refused before the copy |
| `copy_exists` | The destination already exists | `RemodelPreflightError` | Refused; the run never overwrites |
| `copy_failed` | Both the copy and the stream fallback failed | `RemodelPreflightError` | Refused |
| `open_failed` | `OpenDoc7` returned no document or the wrong path | `RemodelTargetError` | Run aborts; the copy is deleted |
| `tag_failed` | The session tag did not write or did not read back | `RemodelTargetError` | Run aborts; the copy is deleted |
| `preexisting_rebuild_errors` | The part was already broken at baseline | `RemodelPreflightError` | Refused **after** the copy exists, because the reading needs a rollback and a rebuild; the handler deletes the copy and closes the document before it answers |
| `target_mismatch` | One of `VerifyTarget`'s four checks failed | `RemodelTargetError` | Run aborts with the change log intact |
| `guard_refused` | The member is not on the stage-1 allowlist | `RemodelGuardError` | Run aborts; this is a bug, not a condition |
| `persist_ref_unresolved` | `GetObjectByPersistReference3` returned an error code | `RemodelAddressError` | The change fails and the run stops |
| `reorder_refused` | `ReorderFeature` returned `false` | `RemodelContractError` | Contract violation: stop, discard the copy |
| `folder_members_not_contiguous` | The requested members are not a contiguous run | `RemodelContractError` | Contract violation: stop |
| `equation_unverified` | Neither `Add3` nor `Add2` could be proven to have landed | `RemodelChangeError` | The change fails and is inverted |
| `rebuild_regressed` | The rebuild-error count rose above the run's baseline | `RemodelChangeError` | The change is inverted, confirmed, and the run continues |
| `rebuild_timeout` | A rebuild exceeded `max_rebuild_seconds` | `RemodelLimitError` | The run finalizes as `truncated` |
| `gate_not_passed` | `remodel.save` called before a `pass` verdict | `RemodelContractError` | Nothing is saved |
| `save_failed` | `Save3` returned a non-zero error | `RemodelSaveError` | Failed run |
| `not_in_v1` | A reserved stage-2 operation was requested | `RemodelNotInV1Error` | Refused |
| `run_in_progress` | A second run was started on the same host | `RemodelRunInProgress` | Refused |

`unauthorized`, `no longer open` and `circuit_open` keep their existing meanings and their
existing Python classes (`BridgeUnauthorizedError`, `BridgeDocumentClosedError`,
`BridgeOpenError`); the circuit breaker's three-consecutive-failures rule is unchanged, and an
open circuit leaves the copy and `changes.jsonl` on disk. **The run never auto-resumes.**

## Logging

`remodel.log` gets one line per request: the command, the elapsed time, the gated members the
`ISwGateObserver` recorded, and the **target path** of every mutating call. The target path is
what lets the run report state, from the log rather than from intent, that every write went to
`<copyPath>`. `gated=` records **reads as well as writes**, because `SwGate.Guard` gates every
member before the guard judges it, so the test is not "the gated set contains only allowlisted
keys". One test asserts that a remodel request's `refused=` set is empty and that every gated key
on `ReadOnlyGuard`'s denied surface - every key that needed the allowlist to pass - is on the
stage-1 allowlist (`guard-allowlist.md`).
