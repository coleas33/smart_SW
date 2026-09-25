# Research: Resilient Re-modeler

**Feature**: `004-resilient-remodeler` | **Date**: 2026-09-16 | **Plan**: [plan.md](plan.md)

Phase 0 output. Condensed from the design brief that synthesized four Opus research passes
(`solidworks-api-reorganize.md`, `solidworks-api-rebuild-and-geometry-gate.md`,
`architecture.md`, `model-check-tab.md`), plus a reflection pass over the SOLIDWORKS 2024 SP5
interop assemblies installed on the pilot machine
(`SolidWorks.Interop.sldworks, Version=32.5.0.48`) done for the brief itself rather than taken
on trust from the researchers.

**What VERIFIED means in this document.** VERIFIED means exactly this: *the member exists with
that signature, or the enum constant has that integer value, on 2024 SP5*. It never means the
call behaves. UNVERIFIED means behavior that needs the workstation; every UNVERIFIED item is a
numbered probe in R10 and is not trusted until that probe runs.

**Owner decisions are binding and are recorded in R12.** Where a decision narrows the brief
(the `EditDelete` allowlist entry, stage 2 not shipping in v1), the narrowing is applied
everywhere in this document, not only in R12, and its consequences are named where they fall.

---

## R1. What the source method and the prior features give us

The Resilient Modeling Strategy (RMS, Richard Gebhard, 2013) supplies the vocabulary: six
ordered groups (`1-Ref`, `2-Construction`, `3-Core`, `4-Detail`, `5-Modify`, `6-Quarantine`),
the intra-group ordering rules, and the intent requirements (every content feature described,
dimensions driven by named global variables). Feature 003 already encodes all of it as 34
deterministic rules plus the normative type table
`reviewer/src/swreview/checks/rms_types.yaml`. Feature 004 grades nothing of its own: it
*plans* against the same table and *re-runs* the same rules before and after.

### R1.1 Feature 003 US6 is a hard prerequisite, not a scheduling preference

`ComponentTreeDumper.Traverse`
(`extractor/SwReview.Extractor/Dump/ComponentTreeDumper.cs:95-111`) gets the tree from
`IConfiguration.GetRootComponent3(false)`. On a **part opened alone** that is expected to
return null, so the tree has no nodes, `scope.Components` is empty, and `FeatureDumper.Dump`
(`Dump/FeatureDumper.cs:139-142`) iterates nothing. `features[]` comes out empty and all 34
RMS rules come back unresolved.

The re-modeler's entire subject is a part opened alone: the copy it just made. Every dump 004
takes (`package-before.json`, `package-after.json`, every re-grade) hits that path. Without
003 US6's part-root fix the planner has no input at all.

### R1.2 The DRY contract with feature 003

Each row is built in 003 and **consumed** by 004, never re-created in 004. This table is the
first thing to check in a 004 code review.

| Shared artifact | Built in | Consumed by 004 |
|---|---|---|
| `ComponentTreeDumper` part-root node | 003 T064 | every dump of the copy |
| `DumpProfile.ModelCheck` (features + equations; no faces, holes, fasteners, meshes) | 003 T064 | `remodel` dumps, `package-before.json`, `package-after.json` |
| `checks/rms/run.py::run_rms_check` (one no-LLM evaluation entry point) | 003 T067 | `rms-before.json`, `rms-after.json` |
| `checks/rms/grade.py::RmsGrade` | 003 (US6) | before and after grade in `grades.json` and in the report |
| `AddIn/Review/PaneActions.cs` (`entity.show`, `report.open`, `folder.open`, `log.open`, run-root containment, redaction) | 003 T075 | the Remodel host delegates to it |
| `AddIn/Review/FeatureSelection.cs` (pure selection strategy) | 003 T079 | `remodel.show_change` |
| `AddIn/web/shared/dom.js` (`el`, `write`, `clear`, `append`, `button`, `field`, `list`, `scalar`, `compact`, `seconds`) | 003 T080 | the Remodel page loads it |

Two more reuses are extractions rather than consumptions, and they are flagged here because
they are the DRY violations that will otherwise appear during implementation:

- `EventSink` (currently private to `reviewer/src/swreview/agent/runner.py:232`) stamps
  `seq`/`at`, appends to `events.jsonl` and fans out to listeners. It must be **extracted** to
  `agent/events.py` and shared, not copied. The per-turn step budget, `TurnEndReason` handling,
  `build_system_prompt` and the redactor hand-off (`no_redaction`) go with it.
- `ReviewRun` itself must **not** be reused. `agent/runner.py` is review-shaped (checklist,
  findings, evidence requests, coverage buckets, finalization) and none of that fits a remodel
  run.

### R1.3 Pane numbering

003 ships first. The task pane's tabs are **Review, Ask, Extract, Model check, Remodel**, with
a step strip above them. **Model check is tab 4; Remodel is tab 5.** Five tabs share one
`CoreWebView2Environment` (`TaskPaneControl.cs:220`) and cost four renderer processes inside
the SOLIDWORKS process, so the Remodel WebView is created **lazily on first tab activation**,
not at add-in load (RK-11).

### R1.4 What 004 adds

The copy and its attestation (R2); the write guard and the document-scoped target (R5); the
pure planner (R6); the bounded LLM judgement phase (R7); the deterministic executor, the
change log and the undo tiers (R8); the geometry gate (R4); the pane (R9). Stage 2 (rebuild)
is out of scope for v1 by owner decision (R12, OQ-8).

---

## R2. The copy strategy, and why `File.Copy` beats `SaveAs3`

### R2.1 The decision

The working file is created by `File.Copy(source, runDir/copy/<name>-RMS.SLDPRT,
overwrite:false)` **before any SOLIDWORKS document handle to the copy exists**, and the source
file is never opened for writing. The copy is then opened at its own path and every write goes
to it.

`IModelDoc2.Save3(Int32, Int32&, Int32&)` (VERIFIED, and VERIFIED to take **no filename**) can
therefore only write to the path the document was opened at. Nothing in stage 1 requires any
`SaveAs*` call. That is a structural guarantee, not a convention: the reachable write target is
the copy, because there is no API in the stage-1 allowlist that can name another file.

### R2.2 Why not `SaveAs3`

| Route | Observed or verified behavior | Verdict |
|---|---|---|
| `SaveAs3(path, version, options)` silent, no `Copy` flag | **Renames the open document in place**: SOLIDWORKS retargets the open document to the new path, so the engineer's window title changes under them and their original is left behind unopened | rejected |
| `SaveAs3` with `swSaveAsOptions_Copy = 2` | Opened a modal Save As dialog *after* the file was already written. A modal on the add-in's STA thread is a hang, not an error | rejected |
| `ISldWorks.CopyDocument(String, String, Object, Object, Int32)` (VERIFIED present) | A reference-rewriting document copy, designed for assemblies with children; more surface than a single part needs and it is not a bytewise copy | not used in v1 |
| `File.Copy(..., overwrite:false)` | Bytewise; refuses to overwrite; happens before any handle exists; needs no SOLIDWORKS call at all | **taken** |

Fallback when SOLIDWORKS holds the source open and `File.Copy` is refused (RK-9):
`new FileStream(src, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)` plus a stream copy.
Whether the plain `File.Copy` succeeds against an open `.SLDPRT` at all is PROBE-13.

### R2.3 Preflight, in order, with no document handle to the source

| # | Check | Call | On failure |
|---|---|---|---|
| 1 | source is a `.SLDPRT` | path and `swDocumentTypes_e.swDocPART = 1` | refuse |
| 2 | the source is open in SOLIDWORKS | `ISldWorks.GetOpenDocumentByName(path)` returns a document | refuse (`source_not_open`); the source is **never opened** to answer any of these |
| 3 | not dirty | `IModelDoc2.GetSaveFlag()` is false | refuse |
| 4 | no external references | `IModelDoc2.ListExternalFileReferencesCount2() == 0` | refuse |
| 5 | scope gate (R4.1) | one call per signal | refuse, with every failing reason named |
| 6 | attestation recorded | `LastWriteTimeUtc`, length, content hash | n/a |
| 7 | three system toggles plus the command-in-progress flag recorded and set | `ISldWorks.SetUserPreferenceToggle` for the three, `ISldWorks.set_CommandInProgress` for the flag (R5.6) | restore both in `finally` |

Rows 1 to 5 are the `remodel.probe_scope` command (`contracts/bridge-remodel.md`). They are read
members only, they return no `IModelDoc2`, and they run **before** the copy is made, which is what
FR-001's "before any copy is made" requires: reading the scope signals at the end of the open
sequence would leave a refused sheet-metal part with a copy on disk and a document open, the exact
state this whole preflight exists to prevent. `remodel.open` refuses with `scope_not_probed` unless
it is handed the `probe_id` of a probe this session performed on this path, so the ordering is
structural rather than conventional.

Then: copy; `OpenDoc7` the copy with `Silent | LoadModel = 17`; assert `GetPathName()` equals
the copy path and differs from the source path; tag with
`ICustomPropertyManager.Add3("SwReviewRemodelRun", 30, runId, 2)` and read it back with `Get4`;
`EditRollback(swMoveRollbackBarToEnd = 1, "")` and assert no feature reports `IsRolledBack()`;
`ForceRebuild3(false)` and **stop if `GetWhatsWrongCount() != 0`** (the part was already broken,
so nothing after this point could be attributed), deleting the copy and closing the document on
that one refusal, because it is the only refusal in the feature that can happen after a copy
exists: reading it needs a rollback and a rebuild, both writes, and neither may touch the source.
Then re-read the scope signals on the copy and compare them field for field with the probe's, a
difference being `scope_changed`; then take the baseline `GeometryReading`, `package-before.json`
and `rms-before.json`.

### R2.4 Option composition, asserted as exact integers in a test

- Open: `swOpenDocOptions_Silent(1) | swOpenDocOptions_LoadModel(16) = 17`, and **never**
  `ReadOnly(2)` or `ViewOnly(4)`. VERIFIED enum values.
- Save: `swSaveAsOptions_Silent = 1`, and **never** `Copy(2)`, `SaveReferenced(4)` or
  `AvoidRebuildOnSave(8)`. VERIFIED enum values.

### R2.5 Where the copy lives, and EPDM

The copy lives **only** in the run folder (OQ-10). Writing `<name>-RMS.SLDPRT` beside the
source is friendlier and much riskier: one bad path join writes into the engineer's working
directory, possibly into a vault. The copy leaves through the pane's "Open copy" plus a Save As
the engineer performs themselves.

EPDM vault parts are **copied out** into the run folder and are never refused for vault reasons
(OQ-11). The vault path and the revision are recorded in `plan.json` and in
`source-attestation.json`. A checked-in, read-only vault file is a legitimate source because
nothing in the run opens it for writing.

### R2.6 The attestation

`source-attestation.json` records the source path, length, `LastWriteTimeUtc` and content hash
at plan time and re-checks all three at report time. **A difference is a hard failure of the
run**, reported as such, regardless of how well the copy came out: it means something wrote to
the engineer's file during the run and the run can no longer claim it did not.

---

## R3. Reorganize API: the VERIFIED / UNVERIFIED ledger for stage 1

Stage-1 members only. Stage-2 creators (`FeatureExtrusion3`, `FeatureCut4`, `FeatureRevolve2`,
`FeatureFillet3`, `InsertFeatureChamfer`, `InsertMirrorFeature2`, the pattern creators,
`InsertPart3`, `ISketchManager.*`) are deliberately absent here; they belong to the stage-2
re-specification and to a second, additive allowlist.

### R3.1 VERIFIED members (present with this signature on 2024 SP5, 32.5.0.48)

| Area | Members |
|---|---|
| Copy and open | `ISldWorks.GetOpenDocSpec(String)`, `OpenDoc7(Object)`, `GetOpenDocumentByName(String)`, `CloseDoc(String)`, `IDocumentSpecification{FileName, DocumentType, Silent, ReadOnly, ViewOnly, LoadModel, ConfigurationName, AddToRecentDocumentList, Error, Warning}` |
| Session tag | `ICustomPropertyManager.Add3(String, Int32, String, Int32) -> Int32`, `Get4(String, Boolean, out String, out String)`, `Delete2(String) -> Int32` |
| Folders | `IFeatureManager.InsertFeatureTreeFolder2(Int32) -> Feature`, `FeatureFolderLocation(Feature) -> Feature`, `IFeature.GetFirstSubFeature`, `GetNextSubFeature`, `IFeatureFolder.GetFeatures`, `GetFeatureCount` |
| Reorder | `IModelDocExtension.ReorderFeature(String FeatureToMove, String TargetFeature, Int32 Location) -> Boolean` |
| Rollback | `IFeatureManager.EditRollback(Int32, String)`, `IFeature.IsRolledBack()` |
| Names and text | `IFeature.get_Name` / `set_Name`, `get_Description` / `set_Description`, `GetTypeName2()`, `GetNameForSelection(String& Type) -> String`, `IDimension.get_Name` / `set_Name`, `get_FullName`, `get_ReadOnly`, `get_DrivenState`, `get_SystemValue`, `GetSystemValue3` |
| Selection | `IFeature.Select2(Boolean, Int32) -> Boolean`, `IModelDoc2.ClearSelection2(Boolean)`, `IModelDocExtension.SelectByID2` (9 args), `ISelectionMgr.GetSelectedObjectCount2(Int32)`, `GetSelectedObject6(Int32, Int32)`, `IComponent2.GetSelectByIDString()` |
| Equations | `IModelDoc2.GetEquationMgr()`, `IEquationMgr.Add3(Int32, String, Boolean, Int32, Object) -> Int32`, `Add2(Int32, String, Boolean) -> Int32`, `Delete(Int32)`, `GetCount()`, `EvaluateAll()`, `get_Equation` / `set_Equation`, `get_Value`, `get_Status`, `get_GlobalVariable`, `SetEquationAndConfigurationOption`, `get_AngularEquationUnits` / `set_AngularEquationUnits` |
| Rebuild and errors | `IModelDoc2.ForceRebuild3(Boolean)`, `IModelDocExtension.GetWhatsWrongCount()`, `GetWhatsWrong(Object&, Object&, Object&)`, `get_NeedsRebuild2()`, `IFeature.GetErrorCode2(Boolean&)` |
| Save | `IModelDoc2.Save3(Int32, Int32& Errors, Int32& Warnings) -> Boolean` (**no filename**), `GetSaveFlag()` |
| Persist refs | `IModelDocExtension.GetPersistReference3(Object)`, `GetObjectByPersistReference3(Object, Int32& ErrorCode) -> Object`, `IsSamePersistentID` |
| Graph | `IFeature.GetParents()`, `GetChildren()`, `GetSpecificFeature2()`, `IModelDoc2.FirstFeature()`, `IFeature.GetNextFeature()` |
| Mass properties | `IModelDocExtension.CreateMassProperty2()`, `IMassProperty2{Volume, SurfaceArea, CenterOfMass, PrincipalMomentsOfInertia, SelectedItems, AccuracyLevel, Recalculate()}`, `IBody2.GetFaceCount()`, `GetEdgeCount()`, `IPartDoc.GetMaterialPropertyName2` |
| Scope signals | `IPartDoc.GetBodies2(Int32, Boolean)`, `IsWeldment()`, `IFeatureManager.GetSheetMetalFolder()`, `IBody2.IsMeshBody()`, `IsGraphicsBody`, `IFeature.Is3DInterconnectFeature`, `GetImportedFileName`, `IModelDoc2.GetConfigurationNames`, `ListExternalFileReferencesCount2()` |
| Toggles | `ISldWorks.SetUserPreferenceToggle`, `GetUserPreferenceToggle` |

**Enum values, VERIFIED on 2024 SP5:** `swMoveLocation_e {ToEnd=1, Before=2, After=3, ToTop=4,
ToFolder=5}`; `swFeatureTreeFolderType_e {EmptyBefore=1, Containing=2, Mold=3}`;
`swMoveRollbackBarTo_e {ToEnd=1, ToPrevious=2, ToBeforeFeature=3, ToAfterFeature=4}`;
`swOpenDocOptions_e {Silent=1, ReadOnly=2, ViewOnly=4, LoadModel=16}`;
`swSaveAsOptions_e {Silent=1, Copy=2, SaveReferenced=4, AvoidRebuildOnSave=8}`;
`swFileSaveWarning_e {RebuildError=1, NeedsRebuild=2}`; `swFeatureError_e.swFeatureErrorNone=0`;
`swInConfigurationOpts_e {SuppressFeatures=0, ThisConfiguration=1, AllConfiguration=2,
SpecifyConfiguration=3}`; `swAngularEquationUnits_e {Unrecognized=0, Degrees=1, Radians=2}`;
`swUserPreferenceToggle_e {InputDimValOnCreate=10, ShowErrorsEveryRebuild=77,
WarnSaveUpdateErrors=329}`; `swMassPropertyAccuracyLevel_e {Lower=0, Medium=1, Higher=2}`;
`swMassPropertiesStatus_e {OK=0, UnknownError=1, NoBody=2}`; `swBodyType_e {Solid=0, Sheet=1,
Mesh=6, Graphics=7}`.

### R3.2 VERIFIED ABSENCES

Each one closes off a design that would otherwise look available.

| Absent member | Consequence for this feature |
|---|---|
| `IEquationMgr.set_GlobalVariable` | A global is created by equation **syntax** (`"name" = expr`, quoted left side with no `@`), never by a flag. Confirmed: the only setters on `IEquationMgr` are `Suppression, Equation, AngularEquationUnits, LinkToFile, FilePath, AutomaticSolveOrder, Disabled, AutomaticRebuild` |
| `ISketchRelation.Name` | Sketch relations cannot be named. "Add relations with names" becomes "record the intent in the parent feature's Description". Full surface: `GetRelationType, GetEntities, GetEntitiesCount, GetEntitiesType, GetDefinitionEntities(2), GetDisplayDimension, ReplaceEntity, Suppressed` |
| Any `*Shell*` creator on `IFeatureManager` | Only `GetPlasticsShellType` exists; shell creation is `IModelDoc2.InsertFeatureShell(Double, Boolean)` returning **Void**, from the current face selection. Stage 2 only, and it is the weakest call in that surface |
| `IFeature.set_ShowFeatureDescription` | `IFeatureManager.get_ShowFeatureDescription()` can *detect* that descriptions are hidden in the tree, so the report can tell the engineer to turn them on; it cannot turn them on |

### R3.3 Members that are present but whose behavior stage 1 does not rely on

`IFeatureManager.MoveToFolder(String, String, Boolean)` and `IFeature.MakeSubFeature(Feature)`
are both VERIFIED present, and both are **unused in v1**. The folder design (R6.6) creates
every folder once by selecting a proven-contiguous run and calling
`InsertFeatureTreeFolder2(swFeatureTreeFolder_Containing = 2)`, so there is no "move into an
existing folder" operation in the plan at all. `ReorderFeature(..., swMoveToFolder = 5)` is in
the same category. All three survive only as the probe decision tree (PROBE-5): if they work on
2024 they become an optimization, and the probe is where that is found out, not the product.

### R3.4 The four behaviors stage 1 does depend on and cannot verify by reflection

| What | Why it matters | Probe |
|---|---|---|
| `ReorderFeature` actually moves a feature on 2024, and returns `false` rather than corrupting the tree when asked to move past a dependency | the whole reorganize-in-place premise | PROBE-3, blocking |
| A refused reorder does not raise a modal "Cannot reorder" box on the STA thread | a modal in an add-in is a hang, not an error | PROBE-1, blocking |
| Folders require contiguous members on 2024 (upstream says yes on 2026) | the contiguity precondition the whole folder plan is built on | PROBE-4, blocking |
| The equation number is in the document's length unit | R3.6 | PROBE-2, blocking |

### R3.5 Two ordering rules that are easy to get wrong and are unrecoverable

1. **Rename dimensions before any equation exists.** Renaming a dimension breaks every equation
   that referenced the old name. Order: rename duplicates, rename dimensions, then descriptions,
   then reorders, then folders, then globals, then dimension equations.

   **This rule is recorded here and implemented by nothing in v1.** FR-030 keeps dimensions out
   of this version: the IR carries none, so the planner cannot name one and cannot prove what an
   equation on one would drive, and `IDimension.set_Name` is therefore off the stage-1 allowlist
   (R5.4). The v1 apply order is the same list with both dimension steps removed: duplicates,
   descriptions, reorders, folders, in-place global repairs, new globals (data-model.md section
   1.11). The rule stands unchanged for the later feature that extracts dimensions into the IR,
   which is why it is kept rather than deleted.
2. **Never delete a global that dimensions reference in order to change it.** Confirmed
   upstream failure: while the global is missing, the dependent equations enter an error state
   that does not clear when it returns, and SOLIDWORKS then rejects any non-constant equation
   for that name. Preference order: `set_Equation(i, text)` (VERIFIED on 2024; the upstream
   "silently no-ops" observation is a pywin32 indexed-property-put artifact and is suspect in
   C#), then `SetEquationAndConfigurationOption` (VERIFIED, never tried by anyone). In v1 there
   is no third fallback: delete-and-re-add is unreachable from the repair path, and a repair that
   neither member can be proven to have written fails the change and is inverted. The repair is
   its own change kind (`equation.edit`, `remodel.equation` `op: "set"`), which is what gives
   FR-029 a call path and gives `set_Equation` and `SetEquationAndConfigurationOption` their only
   reason to be on the allowlist. New globals are added in `order_index` order, each after every
   global its expression names, and removed in reverse order.

`AddEquationVerified(text, whichConfigs)` is the one helper every equation write goes through:
call `Add3`; assert `GetCount()` incremented **and** `get_Equation(i)` round-trips; on failure
call `Add2` and assert again; on a second failure the change fails. The assertion is never
inlined at a call site, because the assertion is the only evidence the add happened (upstream
observed `Add3` returning `-1` and adding nothing, silently, on 2026; PROBE-6).

### R3.6 The units trap: the highest-risk single question in stage 1

**The number in an equation text is in the DOCUMENT's length unit, not meters.** A part in mm
takes `"plate_width" = 120` for 120 mm. This is the exact opposite of `IDimension.SystemValue`,
which is always meters. Getting it backwards builds a 120-**meter** part that rebuilds cleanly
and passes every non-geometric check. Whether `IEquationMgr.get_Value(i)` returns document
units or meters is UNVERIFIED (PROBE-2, blocking).

Required sequence per global that v1 adds (steps 1, 2, 3, 5 and 6 of the brief's dimension
sequence; step 4 is the one FR-030 removes):

1. read the justifying value from the package's feature data (meters, as every length in the IR
   is), recorded as `GlobalEvidence.value_m`;
2. convert to the document's length unit and seed the global's literal with that **exact** value,
   recorded as `GlobalEvidence.value_document_units`;
3. add the global through `AddEquationVerified`; assert it landed and evaluated;
4. **not in v1.** The brief added the dimension equation here. FR-030 forbids it, because the
   planner never saw the dimension, so a v1 global names a value and drives nothing;
5. `ForceRebuild3(false)`, re-read the equation and assert its text and value round-trip at the
   document's stored precision, not at a loose epsilon;
6. compare the geometry snapshot against the pre-change one, which must be **identical**: a global
   that drives nothing cannot move geometry, so any delta here is a defect, not a tolerance
   question.

A document whose length unit cannot be read refuses the change rather than assuming meters. A pure
regression test, needing no seat, pins the conversion: a 120 mm value never produces
`"w" = 0.12`.

### R3.7 Duplicate feature names

`IModelDocExtension.ReorderFeature` is **name-addressed** (`String FeatureToMove, String
TargetFeature`, VERIFIED). SOLIDWORKS permits two features in the tree to share a name inside
different folders. A name-addressed reorder is then ambiguous, and there is no error code to
say so: the call returns a bare `false`, or moves the wrong feature.

Mitigation, and it is a planner precondition: assert feature-name uniqueness across the whole
tree. A duplicate is either renamed first (a recorded, reversible `rename` change applied before
any reorder) or both features go on the rebuild list with reason `ambiguous_name`. One pass over
`features[]`, fully testable.

The general rule that follows: **everything is addressed by persistent reference, never by name
and never by index.** Names change and indices change on every reorder. The C# side resolves a
persist ref to an `IFeature` through `GetObjectByPersistReference3` (reading its ByRef error
code every time), reads `IFeature.get_Name`, and *then* calls the name-based API in one breath.

---

## R4. The geometry gate

### R4.1 The scope gate runs first, before anything is copied

Measured in C# at `remodel.open` (one call each, all VERIFIED present), decided by the pure
`remodel/scope.py`, whose signature contains no COM.

| Signal | Call | Verdict |
|---|---|---|
| multibody | `IPartDoc.GetBodies2(swSolidBody = 0, false)` length > 1 | **refuse**: the gate cannot pair bodies unambiguously |
| weldment | `IPartDoc.IsWeldment()` | refuse |
| sheet metal | `IFeatureManager.GetSheetMetalFolder()` non-null | refuse: RMS's six groups do not model bends, K-factor or flat pattern |
| mesh or graphics body | `IBody2.IsMeshBody()`, `IsGraphicsBody` | refuse: no B-rep, so no gate |
| 3D Interconnect | `IFeature.Is3DInterconnectFeature` | refuse: editing fights the live link |
| imported dumb solid | `IFeature.GetImportedFileName` | allow, and report the reorganize stage as a no-op |
| surface bodies present | `GetBodies2(swSheetBody = 1, false)` | allow, and report the gate's surface coverage as **uncovered**, never as passed |
| configurations | `IModelDoc2.GetConfigurationNames` | record the count; drives `which_configs` on every equation add |

A refusal costs nothing; a half-rebuilt sheet-metal part costs the engineer their afternoon.
Per Principle VI a refusal is a reported coverage gap, never a silent skip, and when two signals
fail the message names both.

### R4.2 Measure in C#, decide in Python

The disagreement between the researchers (pure Python over two IR dumps, versus C# because of
ByRef out-parameters) dissolves once measurement and decision are separated. Five of the
measurement calls (`Operations2`, `GetMassProperties2`, `GetWhatsWrong`, `GetErrorCode2`,
`CreateBodiesFromSheets2`) take ByRef out-parameters that pywin32 cannot marshal. The verdict,
by contrast, must be table-testable without a seat.

- `remodel.geometry` (a bridge command) returns a plain `GeometryReading` record.
- `reviewer/src/swreview/remodel/geometry.py::evaluate(before, after, tolerances) -> GateResult`
  has **no COM in its signature** and is table-tested.

The same split is applied to the scope gate (R4.1).

### R4.3 Tier 1, mass properties: the stage-1 gate

Measured in C# with `doc.Extension.CreateMassProperty2()`, `AccuracyLevel =
swMassPropertyAccuracyLevel_Higher (2)`, `SelectedItems` set to the body, `Recalculate()`, and
**its Boolean checked before anything is read**. The typed `IMassProperty2` interface is used,
**not** `GetMassProperties2`'s raw `Object`: that call's flat `double[]` index layout is not
discoverable by reflection and has changed across API generations, so it would be guessed.

Compared: `Volume`, `SurfaceArea`, `CenterOfMass`, `PrincipalMomentsOfInertia` **sorted
ascending** before comparison (two bodies differing by a symmetry-degenerate rotation return the
same three numbers permuted), solid body count (exact), face count and edge count.

`Mass` is recorded and compared **separately**. `Mass = Volume x Density`, and density comes
from the material, which is not geometry. A mass-only delta reports `material_changed`, never
`geometry_changed`. Material equality is checked on its own with
`IPartDoc.GetMaterialPropertyName2` (VERIFIED present).

### R4.4 Two tolerance profiles, split by stage

In stage 1 nothing geometric is supposed to change: the same B-rep is re-evaluated after a
reorder, so any delta at all is a defect. In stage 2 a feature is genuinely recreated, so a
NURBS re-evaluation legitimately moves the last few digits. One pure function, two named
profiles:

| Profile | volume_rel | area_rel | com_rel | moment_rel | face_count | body_count | Used by |
|---|---|---|---|---|---|---|---|
| `IDENTITY` | 1e-9 | 1e-9 | 1e-9 | 1e-9 | exact | exact | stage 1 (v1) |
| `EQUIVALENCE` | 1e-6 | 1e-5 | 1e-6 | 1e-5 | warn | exact | stage 2 (declared, not selected by any v1 code path) |

**A tolerance that has never been compared against a known answer does not ship.** PROBE-8 is a
gating task: measure the attained relative error on a part of exactly known analytic volume (a
box and a cylinder) at `swMassPropertyAccuracyLevel_Higher`, and record it in a
`capabilities.yaml`-style ledger. `IDENTITY` is not shipped until that number exists.

### R4.5 What tier 1 cannot detect

Stated in the report's coverage section on every run, because Principle VI requires it:

- a **reflection**: volume, surface area and all three principal moments are invariant under any
  isometry including a mirror, and the center of mass is equivariant, so a left-hand part and its
  mirror are mass-properties-identical;
- a rigid rotation about a symmetry axis;
- compensating add/remove pairs;
- any difference occupying no volume: split faces, cosmetic threads, material, custom properties,
  configuration data;
- surface-body and wire-body differences.

### R4.6 Tier 2, boolean symmetric difference, and why it is stage 2

The reflection hole above is real and the boolean is the only closer:

```csharp
IBody2 rA = (IBody2)R.Copy();  IBody2 pA = (IBody2)P.Copy();   // Operations2 consumes BOTH
object[] leftOver  = (object[])rA.Operations2((int)SWBODYCUT /*15902*/, pA, out int err1);
IBody2 rB = (IBody2)R.Copy();  IBody2 pB = (IBody2)P.Copy();   // fresh copies; the first pair is gone
object[] rightOver = (object[])pB.Operations2((int)SWBODYCUT, rB, out int err2);
```

The gate's whole vocabulary is four VERIFIED error codes: `swBodyOperationEmptyBody = 6` on
`A - B` means A lies entirely inside B, a pass signal; `swBodyOperationNoIntersect = 1067` is
read *together with* the residual volume, never alone; `swBodyOperationPartialCoincidence = 1040`
is the classic sliver, meaning "inspect the residual", not "fail";
`swBodyOperationBooleanFail = 1058` and `swBodyOperationUnknownError = -1` mean **the gate did
not run**, which is `unresolved`, never `pass`.

Three residual signals, not one scalar: total residual volume at or below
`max(1e-12 m3, 1e-6 x V)`; residual body count **recorded, not gated** (many tiny lumps is the
sliver signature, one big lump is a real difference); the largest residual's bounding-box
**minimum** dimension at or above 1e-5 m to count as real.

**Why it is not in v1.** Stage 1 does not create geometry, so it cannot mirror anything.
`Operations2` behavior is UNVERIFIED on 2024 and the upstream source never exercised body
booleans at all (its `capabilities.yaml` lists no boolean capability). Running an untested
boolean on every stage-1 run buys nothing and adds a failure mode. Tier 2 is built and tested in
stage 2, where it is mandatory (PROBE-18, PROBE-19).

**What v1 keeps so that stage 2 adds a tier and not a type change:** `GateResult` is tri-state
(`pass` / `fail` / `unresolved`) from day one, and it carries `tier_2: TierResult | null`, null
in v1.

### R4.7 The decision function and the case table that decides whether the product is trustworthy

`evaluate(...) -> GateResult` returns `pass | fail | unresolved`, never a Boolean. Tier 1
passing with tier 2 failing **is** the mirrored-part case and must be reported as a failure with
that diagnosis spelled out. Tier 1 failing with tier 2 passing is a bug in the tolerances and is
`unresolved`, not silently resolved either way.

Table-driven cases, all of which must be written (the tier-2 rows are written in stage 2 against
the same types):

identical; delta-V just inside tolerance; delta-V just outside; **mirrored** (mass properties
identical, residual equal to the full volume); translated 0.1 mm; uniformly scaled 1.0001; one
sliver residual (10 mm x 10 mm x 0.2 um); many slivers summing over the volume threshold; a
residual body with a null bounding box (upstream saw `GetBodyBox` return null on a cut body);
`errorCode = 1058` gives unresolved; `= 6` gives pass; `= 1067` read with volume; `= 1`
(non-API body) gives unresolved; mass-properties `Status != OK` gives unresolved; a baseline
reading with body count 2 gives unresolved; principal moments permuted gives pass after sorting;
**a zero-volume baseline reading gives unresolved, not a divide-by-zero**.

Plus one unit test asserting that every tolerance constant is in meters, every angle in radians,
and no comparison mixes an absolute with a relative bound.

### R4.8 What the gate compares against

**The copy is compared against itself: the baseline reading taken at open, and the final reading
taken after the last change** (`subject: "copy_at_open"` and `"copy_at_end"`, data-model.md
section 3.1). The source file is **never opened for the comparison, in any mode**, and no
reference body is put in any tree.

Two alternatives were considered and rejected.

`IPartDoc.InsertPart3` (VERIFIED) is not used in v1: the copy already is the source geometry
feature for feature, so bringing the source in as a derived body would add a live external
reference, an RMS violation in `1-Ref` (a solid body in the reference group), and a body that must
be deleted before save. It stays documented as the fallback for one stage-2 case only, if
`Operations2` turns out not to work across two documents' bodies.

Opening the source read-only as a second document to measure it was the brief's wording, and it is
rejected too. It buys nothing the baseline reading does not already give: the copy is a byte-for-
byte `File.Copy` whose SHA-256 was recorded before any document handle existed, so the baseline
reading **is** a reading of the source's geometry, and `GeometryReading.source_sha256` says which
file it speaks for. It costs a second command that names a document, in a protocol whose central
property is that none does, plus a second open handle to the engineer's file that the constitution
exception was written to avoid having at all. The one thing it would have covered is a geometry
difference introduced by the baseline rollback and rebuild themselves, which sits inside the
baseline either way and is printed as a named coverage limit on every run (data-model.md section
3.4).

---

## R5. The write guard

### R5.1 Why two layers

`SwGate.Call("GetChildren", () => component.GetChildren())` guards on the **member name only**:
the document is captured inside the lambda and the guard never sees it. So "document-scoped"
cannot be a property of `ICallGuard` alone. Two layers, mirroring the shape
`ReadOnlyGuard.Assert` plus `ReadOnlyGuard.AssertSaveAs` already has:

1. `Guard/RemodelGuard.cs`, an `ICallGuard`, an **allowlist** of interface-qualified members;
2. `Rms/RemodelScope.cs`, the only object that holds the copy's `IModelDoc2`, which re-verifies
   the target before every single write.

### R5.2 Layer 1: an allowlist, and why it is not a denylist

`ReadOnlyGuard` is a denylist because the reviewer's *read* surface is unbounded and grows every
phase. The re-modeler is the inverse: its write surface is a closed set of about twenty members
the spec can enumerate. The re-modeler is also exactly the workload that finds a denylist's
gaps: `ReadOnlyGuard` blocks `InsertFeatureChamfer`, `InsertFeatureShell` **and**
`InsertFeatureTreeFolder2` through its `InsertFeature` prefix, while leaving `FeatureFillet3`,
`FeatureRevolve2`, `InsertMirrorFeature2`, `InsertPart3`, `SetSuppression2` and `IModelDoc2.Save`
wide open. *Amended 2026-09-25 (the owner's decision 21A, R5.11)*: the creation members among them
are closed now; `IModelDoc2.Save` is not, and the case for an allowlist is unchanged.

### R5.3 Interface-qualified keys, and the collision that proves they are needed

Bare member names collide, and both halves of the collision are VERIFIED on 2024 SP5:

- `ICustomPropertyManager.Delete2(String)` (the session-tag delete) is refused today because
  `ReadOnlyGuard` denies the bare name `Delete2`, meaning `IEntity.Delete2`;
- an allowlist entry for `IEquationMgr.Add3` written as `"Add3"` would silently also permit
  `ICustomPropertyManager.Add3`.

So `RemodelGuard`'s allowlist keys are `Interface.Member`. `RemodelGuard.Assert(qualified)`
returns if the qualified key is allowlisted, and otherwise delegates to
`ReadOnlyGuard.Assert(BareName(qualified))`, so the read-only rules still apply unchanged. Only
the remodel call sites use qualified keys; the reviewer's existing
`SwGate.Call("GetChildren", ...)` sites are untouched.

### R5.4 The stage-1 allowlist

```
IModelDocExtension.ReorderFeature
IFeatureManager.InsertFeatureTreeFolder2
IFeatureManager.EditRollback
IFeature.set_Name                     (folders and duplicate-name repair only)
IFeature.set_Description
IFeature.Select2
IEquationMgr.Add2  /  Add3  /  Delete  /  set_Equation  /  SetEquationAndConfigurationOption
IModelDoc2.ForceRebuild3
IModelDoc2.ClearSelection2
IModelDoc2.Save3                      (no filename; see AssertSaveTarget)
IModelDocExtension.SelectByID2
ICustomPropertyManager.Add3           (the session tag)
ICustomPropertyManager.Delete2        (the session tag)
ISldWorks.SetUserPreferenceToggle     (the three system toggles of R5.6, restored in finally)
ISldWorks.set_CommandInProgress       (the run-scoped modal-suppression flag, restored in finally)
ISldWorks.CloseDoc                    (the tagged copy only)
```

**`IModelDoc2.EditDelete` is not on this list** (owner decision, R12 OQ-3). The brief carried it
for exactly one case: an existing folder already carrying one of the six RMS names but holding
the wrong members, which would be dissolved and re-wrapped. In v1 such a part is **refused**
instead, which removes the single highest-risk allowance from the guard entirely. Three
consequences follow and are applied throughout this package:

1. The folder plan has no `dissolve` action in v1 (R6.6).
2. The per-change inverse of `folder.create` does not exist in v1, so a failed folder creation
   escalates to the tier-2 catastrophic replay rather than being undone in place (R8.3).
3. `AssertFolderSelection` (the mandatory pre-`EditDelete` assertion:
   `GetSelectedObjectCount2(-1) == 1` **and**
   `((IFeature)GetSelectedObject6(1, -1)).GetTypeName2() == "FtrFolder"`) has **no write call
   site** in v1, because there is no dissolve to guard. It is nonetheless built and unit-tested
   now, in Phase 3, as a pure refusal predicate: it is the reading the planner's
   `rms_named_folder_wrong_members` refusal is written against, and it is the stated precondition
   any stage-2 dissolve must pass, so stage 2 inherits a tested assertion rather than writing one
   under time pressure beside a delete. It is **never** called before a folder creation: creation
   selects a contiguous run of N content features, which this predicate refuses by construction.
   An unused allowlist *entry* is accidental widening and is excluded (`IModelDoc2.EditDelete`,
   `IDimension.set_Name`, `StartRecordingUndoObject`); a tested predicate that widens nothing is
   not. RK-4 is therefore not a v1 risk.

### R5.5 Explicitly not allowlisted in stage 1

`EditRebuild3`; `SaveAs3` on any path; `SetSaveFlag`; `Delete2` on anything but a custom
property; `ModifyDefinition`; `EditSuppress2` / `EditUnsuppress2` / `SetSuppression2`;
`EditUndo2` / `EditRedo2`; `StartRecordingUndoObject` / `FinishRecordingUndoObject2`;
`SetReadOnlyState`; `IModelDoc2.SetSystemValue*`; `IModelDoc2.EditDelete`; `IDimension.set_Name`
(v1 addresses no dimension, FR-030); and the whole
`FeatureCut* / FeatureExtrusion* / InsertFeature*` creation family. Stage 2 gets a **second,
additive allowlist**, reviewed on its own.

`StartRecordingUndoObject` / `FinishRecordingUndoObject2` are rejected on purpose: they are a
UI-undo-stack mechanism this design has decided not to rely on (R8.3), and their interaction
with `ForceRebuild3` is itself UNVERIFIED.

### R5.6 Three system toggles plus one application flag

The first three rows are `swUserPreferenceToggle_e` constants, all VERIFIED values, all **system**
(not document) settings. The fourth is not one of them: `ISldWorks.CommandInProgress` is a plain
property, which is why its Value column reads `n/a` and why it carries its own allowlist key,
`ISldWorks.set_CommandInProgress` (`contracts/guard-allowlist.md`), rather than riding on
`SetUserPreferenceToggle`. All four are read, set, and restored in a `finally`, including during
crash recovery of a previous run.

| Toggle | Value | Why |
|---|---|---|
| `swInputDimValOnCreate` | 10 | upstream calls leaving it on "the single most expensive failure in this repo's history": every dimension call opens a modal and the script appears to hang |
| `swShowErrorsEveryRebuild` | 77 | a rebuild with errors raises the What's Wrong dialog; in an add-in a dialog is a hang |
| `swWarnSaveUpdateErrors` | 329 | the "save anyway?" dialog |
| `ISldWorks.CommandInProgress = true` | n/a | **UNVERIFIED that it suppresses the "Cannot reorder" message box, and that is blocking (PROBE-1)** |

### R5.7 Layer 2: `RemodelScope` and `VerifyTarget`

Every write method is `VerifyTarget()` then `gate.Call(qualifiedKey, ...)`. `VerifyTarget()` is
four cheap checks on the application thread, re-run **before every single write**:

1. `document.GetPathName()` equals the copy path this run created;
2. `document.Extension.CustomPropertyManager("").Get4("SwReviewRemodelRun", ...)` equals this
   run's id;
3. `swApp.GetOpenDocumentByName(copyPath)` returns the *same* COM identity
   (`Marshal.GetIUnknownForObject`), which catches a close-and-reopen underneath the run;
4. the copy path is a canonicalized descendant of this run's folder, with `..` resolved.

Any failure throws `RemodelTargetError` naming which check failed, and the run aborts with the
change log intact. `AssertSaveTarget(path)` refuses any path that is not this run's copy, refuses
`..`, refuses the source, refuses another run's copy, and refuses a non-`.SLDPRT`.

**The strongest property is structural, not procedural:** no command exposed to the model, and no
command in the bridge protocol at all, takes a document. The scope's copy is the only reachable
target. That is stronger than validating a path the caller supplied.

`ISwGateObserver` already records gated and refused members per request
(`ToolService/ToolServiceHost.cs`). The remodel observer additionally records the **target path**
per mutating call, so the run report can state, from the log rather than from intent, that every
write went to `<copyPath>`.

### R5.8 Secret scope

`ToolServiceHost` mints two secrets today (`ReviewSecret`, `GeneralChatSecret`) bounded by
`ScopedSecretPolicy`. A third, `RemodelSecret`, authorizes `ping | remodel.*` and nothing else,
and is handed only to the remodel backend session. The general-chat secret authorizes **no**
`remodel.*`. The existing test asserting that the MCP function names and the terminal profile's
`enabled_tools` are the same list gains a sibling asserting that the remodel commands are in
**neither**.

### R5.9 What a test pins without SOLIDWORKS

- `RemodelGuard` is a pure `ICallGuard`: xUnit over the allow/deny table, including the
  `Delete2` and `Add3` interface collisions, asserted as a **set equality** against
  `ReadOnlyGuard.DeniedMembers` union `DeniedPrefixes` (both made publicly readable by a
  visibility-only change; `contracts/guard-allowlist.md`), so a denial added upstream cannot
  silently widen the remodel surface.
- `AssertSaveTarget`: outside the run folder, containing `..`, equal to the source, another
  run's copy, a `.sldasm`, no extension: all refused; only this run's copy passes.
- `RemodelScope` over an `IRemodelTarget` fake: tag changed mid-run refuses; path changed
  refuses; COM identity changed refuses; the happy path asserts the exact member sequence, in
  order.
- `ToolServiceRequestLogger.Format` already records `gated=`, and it records reads as well as
  writes (`SwGate.Guard` gates every member before judging it). So a new test asserts a remodel
  request's `refused=` set is empty and that every gated key on `ReadOnlyGuard`'s denied surface
  is on the stage-1 allowlist, rather than that the whole gated set is allowlisted. That is the
  SC-004 audit artifact, extended, not replaced.
- Secret policy: the general-chat secret is refused for every `remodel.*`; the remodel secret is
  refused for `interference`.
- **Option composition** as exact integers (R2.4).
- **A frozen interop-surface manifest**: a checked-in JSON fixture of
  `{interface, member, arity, ordered parameter names, return type}` for every member the
  re-modeler calls, generated by the same reflection dump used for this ledger. Two tests:
  (a) pure, asserting the code's argument builders match the fixture; (b) workstation-only,
  skipped when the interop DLL is absent, regenerating from the installed DLL and diffing.
  **(b) turns a SOLIDWORKS upgrade from a runtime surprise into a red build.**

### R5.10 `ReadOnlyGuard` is narrowed by 003, and 004 adds nothing to it

SC-004 is audited against `ReadOnlyGuard`, so it must not be **widened**. Both researchers
independently found real **gaps**, members that mutate and are not denied:
`IFeature.SetSuppression2`, `ISldWorks.SetUserPreferenceToggle`, `IModelDoc2.EditUndo2`, and
`IModelDoc2.SetSaveFlag`. Feature 003 adds those four denials (with `SetSuppression2` exempted
only under 003's `SuppressTestGuard`). **Feature 004 adds nothing to `ReadOnlyGuard` at all**;
it introduces a separate guard whose allowlist is delegated back to it. *Amended 2026-09-25*: the
owner's decisions 17A (FeatureWorks and import repair) and 21A (the creation family, R5.11) narrow
`ReadOnlyGuard` for 004; both only add denials, so SC-004's "never widened" holds.

### R5.11 Decision 21A: the creation family is closed in `ReadOnlyGuard` (owner, 2026-09-25)

**Decision.** Close the wider feature-creation family decision 17A left open - `FeatureFillet*`,
`FeatureRevolve*`, `InsertMirrorFeature*`, `InsertPart*`, `MirrorPart*`, `InsertSheetMetal*`,
`InsertConvertToSheetMetal*`, the pattern creators and the like - in `ReadOnlyGuard`, with a table
generated from the installed interop the way feature 011 generated its drawing writer list.

**Why a grammar over four interfaces, not a longer prefix list.** A prefix is a bare-name rule that
reaches every interface, and the creation verbs are also read verbs elsewhere: `Create` names the
mass-property and measure calculators the product reads through, and `Feature` names the lookups
`FeatureById` and `FeatureFolderLocation`. So the denial is exact names, reflected from
`IFeatureManager`, `IModelDoc2`, `IPartDoc` and `IModelDocExtension` (the interfaces feature
creation is reached through) with a creation grammar - `Feature`, `Insert`, `Create`, `Add`,
`Mirror`, `Make`, `Sketch` and the hole builders, each with its optional COM `I` - plus a short list
of named creators the grammar cannot reach (the `Pre`/`Post` split, trim and intersect features, the
builders' last calls, the Delete Face feature, the body move and copy features, `DeriveSketch`,
`Paste`). The existing three prefixes stay; nothing is removed.

**Collisions, checked by name.** A bare-name denial reaches every interface, so every generated name
is checked against (1) feature 004's stage-1 allowlist - no generated name is the bare name of a
stage-1 key or of a `RemodelGuard` refusal, so the five keys that override a read-only denial are
unchanged; (2) the reads the grammar reaches, which are excluded by name with their reasons
(`FeatureById`, `FeatureByName`, `FeatureByPositionReverse`, their `I` twins, `FeatureFolderLocation`,
`CreateMassProperty`, `CreateMassProperty2`, `CreateMeasure`); and (3) every string literal of the
product source, by the scan feature 011's read audit runs. The scan finds exactly three literals the
new table refuses, all in `Rms/SwRemodelProbeHost.cs`, the throwaway-part probe: `FeatureFillet3`,
`InsertSketch` and `CreateCircleByRadius` (the last two are `ISketchManager` calls whose bare names
`IModelDoc2` also declares).

**The probe's exemption.** Those three join the members `RemodelProbeGuard` already exempted for the
same part (`FeatureExtrusion3`, `FeatureCut4`, `InsertFeatureChamfer`, `InsertFeatureShell`,
`InsertFeatureTreeFolder2`) in one named set, the throwaway part's creation members. The guard is
built only by `probe remodel`'s gate, which refuses to run while a document is open and addresses
only the part it creates, so that is the exemption's scope; a test pins the set to the probe host's
own literals and asserts that no other gate exempts any of them.

**Not in scope, recorded for the owner.** The other writers of the four interfaces are not creation
and are not closed by this decision; the reflection run found saves (`IModelDoc2.Save`, `SaveAs`,
`SaveSilent` and their siblings, `IPartDoc.SaveToFile*`) and rebuilds (`IModelDoc2.Rebuild`,
`IModelDocExtension.Rebuild` and `EditRebuildAll`) that pass a read-only gate as bare names, and creation on other interfaces (`ISketchManager`,
`IAssemblyDoc`) is outside the four. `contracts/guard-allowlist.md` names them.

---

## R6. The planner: algorithms, and what is pure

Everything in `reviewer/src/swreview/remodel/` except `apply.py` and `runner.py` is pure Python:
no SOLIDWORKS, no LLM, no I/O, fully testable with builder fixtures over an IR package.

| Module | Responsibility | Test shape |
|---|---|---|
| `target.py` | `target_group(row, tree, table) -> Resolved(group, basis) \| NeedsJudgement(reason, candidates) \| NotContent()` | one case per class, sketch-follows-consumer, unconsumed sketch, two-consumer sketch, `unknown`, `ICE` |
| `rank.py` | `(group_index, intra_rank, original_index)` | one per intra-rank rule; an unrankable fillet is blocked, never given an arbitrary position |
| `order.py` | Kahn's algorithm with a priority queue keyed by desired rank, then LIS for the minimal edit script | already-ordered gives 0 moves; reversed with no dependencies gives a full reorder; LIS minimality; a cycle refuses with the cycle named, never loops |
| `feasibility.py` | pins, non-contiguous groups, the rebuild list | one fixture per reason in R6.5 |
| `folders.py` | create and rename plan; correct folder is a no-op; derived subfolder preserved | membership equality; mis-membered RMS-named folder is a refusal (v1) |
| `intent.py` | description **gap** list (`None` unreadable is not `""` absent); which equations exist, are globals, or are broken | |
| `names.py` | duplicate-feature-name detection and the rename plan (R3.7) | |
| `scope.py` | `ScopeGate.evaluate(signals) -> Ok \| Refusal(reasons[])`, no COM in the signature | one per signal, plus two signals at once, where the message must name both |
| `geometry.py` | `evaluate(before, after, t) -> GateResult`, no COM in the signature | R4.7's table |
| `apply_log.py` | `ChangeRecord` plus `derive_undo(change)`, a pure inverse per change kind | one test per kind |
| `plan.py` | `RemodelPlan` (pydantic, `plan_schema: "1.0"`), `plan_reorganize()` composes the above | four golden plans |
| `apply.py` | the deterministic executor | fake bridge that scripts a failure at change N |
| `runner.py` | phases A to D; the one entry point to a provider, which delegates to `cli.provider_factory` (decision 4A, 2026-09-23) | `FakeProvider` scripts, including one that proposes garbage |

### R6.1 Targets

`target.py` reads `default_group_by_class`, **one new key in the existing
`checks/rms_types.yaml`**, so the checker and the planner cannot disagree about what "should"
means. The table stays the single normative type table; adding this key is the only edit feature
004 makes to a feature 003 artifact.

Rules that are not table lookups:

- a **sketch follows its single consumer** into that consumer's group; a sketch with more than
  one consumer is a rebuild-list entry (`shared_sketch`); an unconsumed sketch targets
  `2-Construction`;
- a feature whose `GetTypeName2` is not in the table is `unresolved` and is **never** moved
  (Principle I); it appears on the rebuild list as `unclassified`;
- `ambiguous` (`ICE`) goes to the model through `classify_unknown`, and is `unresolved` if the
  model declines;
- a **fillet defaults to `3-Core`** and is listed in the report as "reviewed as structural; move
  to Quarantine if cosmetic" (owner decision, R12 OQ-4). The model may move a cosmetic one to
  `6-Quarantine` through `decide_fillet`;
- a fillet or chamfer that has dependents can never target `6-Quarantine`, because that would
  guarantee an `rms.quarantine.has_no_children` failure. It targets `3-Core` and the choice is
  recorded as a deviation. This rule is enforced in the pure planner and again inside the
  `decide_fillet` tool's validation, so a model proposal cannot bypass it.

### R6.2 Ranks

`(group_index, intra_rank, original_index)`. The intra-ranks come straight from the rules
`checks/rms/part.py` already grades, so the planner cannot aim at an order the checker will mark
down: `shell_last`, `holes_last`, `transform_before_replicate`, `chamfers_before_fillets`,
`largest_fillet_first`. `original_index` is the tie-break, which makes the plan stable and makes
"minimum movement" the default.

A fillet whose `FilletInfo.default_radius` is `None` (a variable-radius fillet, or an unreadable
radius) cannot be ranked by `largest_fillet_first`. It is **blocked**, with reason
`radius_unreadable`, and never given an arbitrary position.

### R6.3 The achievable order

Kahn's algorithm over the feature dependency graph (`parent_ids` / `child_ids` from the IR), with
a priority queue keyed by the desired rank. The result is the legal topological order closest to
the RMS order: it never violates a dependency, and among legal choices it always takes the one
RMS would prefer.

Then the **longest increasing subsequence** of current positions under that order gives the set
of features that can stay put, and the complement is the minimal edit script. On a 200-feature
part this is typically 20 to 40 moves instead of 200, which matters because every move is a
guarded write with a rebuild after it.

A cycle in the condensed group graph is a **refusal** that names the cycle, never a loop and
never an arbitrary break.

### R6.4 Feasibility

`feasibility.py` produces the honest output of stage 1: pins (which feature could not reach its
target group, and **which dependency edge** holds it), non-contiguous groups (which interloper
splits the run), and the rebuild list.

### R6.5 The rebuild-list reason taxonomy: the product of stage 1

| Reason | Detection (pure) | Example |
|---|---|---|
| `backward_reference` | some parent `p` with `group(p) > group(f)` | a `4-Detail` cut sketched on a face created by a `6-Quarantine` fillet |
| `shared_sketch` | a sketch with more than one consumer | one sketch driving two cuts: it can only be contiguous with one |
| `splits_group` | the feature sits inside another group's `[first, last]` span in the achievable order | a Detail feature pinned in the middle of Core |
| `cycle` | the condensed group graph has a cycle | mutually referencing Detail features |
| `radius_unreadable` | fillet with `default_radius is None` | variable-radius fillet |
| `ambiguous_name` | two features share a name (R3.7) | |
| `unclassified` | `GetTypeName2()` not in `rms_types.yaml` | reported `unresolved`, never "movable" (Principle I) |
| `graph_unreadable` | `child_ids` **and** `parent_ids` both `None` | never move on an unknown graph |

### R6.6 Folders

Every folder is created once, by `Select2`-ing a run of features whose contiguity has already
been **proven in the plan**, and calling
`InsertFeatureTreeFolder2(swFeatureTreeFolder_Containing = 2)` then `set_Name`, verified
afterwards with `FeatureFolderLocation`. There is no "move into an existing folder" operation in
the plan at all, which removes three UNVERIFIED calls from the critical path (R3.3).

- an existing folder with the correct name and exactly the right members is a **no-op**;
- a derived subfolder (the coupled-pair exception 003 already models) is **preserved**, never
  dissolved;
- an existing folder carrying one of the six RMS names but holding the wrong members is a **v1
  refusal**, reported as "this part already has a folder named `3-Core` with unexpected contents;
  fix it by hand, or wait for the rebuild stage" (owner decision, R12 OQ-3).

### R6.7 Phase 0: the dry run comes before any write code

Both researchers challenged the staged v1 with the same upstream sentence: *"SolidWorks folders
must hold contiguous features and will not reorder past a dependency, so there is no
sort-the-tree-afterwards path on a part of any realistic complexity."* The planner is precisely
the machinery that measures how much of a given part is sortable, but the honest expectation is
that on a part built without RMS discipline the reorganizable fraction may be small.

So two things are adopted, and both are spec requirements rather than aspirations:

1. **Stage 1's output is a partition with reasons**, and success is measured on the quality of
   the partition, not on the size of the reorganized fraction. A run that moves 3 of 200
   features says "this part needs rebuilding" in the report's first line, not "success".
2. **The planner ships and runs first.** `swreview remodel plan <package.json> --json` is built
   in Phase 1 and run over the benchmark packages and 3 to 5 real parts **before any C# write
   code exists** (owner decision, R12 OQ-1). It prints, per part: how many features reach their
   target group, how many are pinned and by which edge, how many groups come out non-contiguous,
   and the rebuild list. It is a deliverable in its own right, a "how re-modelable is this part"
   report an engineer would use even if the modeler never shipped, and it converts RK-1 into a
   number before the expensive half starts.

---

## R7. The LLM phase and its tools

Phase B sits between the pure plan (rev 1) and the deterministic apply. It is bounded, it makes
no SOLIDWORKS call, and it writes only to the plan (rev 2).

`reviewer/src/swreview/tools/remodel_plan.py`, registered through a `Registration` in
`tools/registry.py` added **only when `ToolContext.remodel` is set**, exactly the way
`bridge_tools()` is added only when the context carries a bridge.

| Tool | Writes | Pure validation inside the tool |
|---|---|---|
| `propose_description(feature_id, text)` | `plan.descriptions[]` | feature exists, is content, 1 to 200 chars, not equal to `name` or `type_name`, no newline |
| `propose_global(name, expression, rationale, evidence)` | `plan.globals[]`, or `plan.rejected_proposals[]` on a rejection | `^[a-z][a-z0-9_]{1,31}$`, unique, not an existing global, expression parses over the declared globals and the documented function set (`sin cos tan atn arcsin sqr`, **degrees**) |
| `decide_fillet(feature_id, group, rationale)` | `plan.targets[]` | classifies as a fillet; `group` in `{3-Core, 6-Quarantine}`; `6-Quarantine` refused if the feature has dependents |
| `classify_unknown(feature_id, group, rationale)` | `plan.targets[]` and `plan.deviations[]` | classifies as `unknown` or `ambiguous`; group is one of the six |
| `get_remodel_plan(section)` | nothing | read-back |

A rejected proposal returns `{"error": ...}`, which `RecordedTool.call` already turns into
`is_error=True` with no exception. Reuse, not a new error path.

**Nothing on that list decides an order, a move, a rollback, or a verdict.** That is Principle II
held exactly, and it is what lets the apply loop run with no model in it. If the model declines,
times out, or proposes only garbage, the run continues: descriptions stay as they are, fillets
stay at `3-Core` as deviations, and the report says the judgement phase contributed nothing.

**Providers.** OpenAI is the default and Gemini is the alternative, both through the existing
`agent/providers` layer. Claude is not a provider in this product. The prompt is
`agent/prompts/remodel_v1.md`, built through the shared `build_system_prompt`.

*Amended 2026-09-23 (owner, decision 4A):* the remodel run's adapter is built by the same body
as the review's. `remodel/runner.py::build_provider` stays the run's one entry point, refuses the
scripted provider, and delegates to `cli.provider_factory` with no efficiency levers
(`contracts/tools.md`, "Providers"). The run had its own copy of the construction body until
then, and the copy carried the original's wrong `redact=` keyword, so the Gemini fix of `d47a91f`
had to be made twice; one body cannot disagree with itself.

**Not MCP tools.** The `propose_*` tools are registered on the remodel run's registry only. They
do not appear in the MCP function list and they are not in the terminal profile's
`enabled_tools`; a test asserts both.

---

## R8. Artifacts and undo tiers

### R8.1 The run folder

Created by the existing `RunFolders` helper so the naming convention stays in one place:
`<run_root>/<yyyyMMdd-HHmmss>-<doc>-remodel/`.

```
copy/<doc>-RMS.SLDPRT     the working copy; the ONLY file SOLIDWORKS may write
plan.json                 RemodelPlan, plan_schema 1.0
changes.jsonl             one ChangeRecord per attempted change, append-only
package-before.json       ModelCheck-profile dump of the copy at open (equals the source's tree)
package-after.json        same, after the last change
rms-before.json           run_rms_check over package-before
rms-after.json            same over package-after
grades.json               RmsGrade before, after, per-rule delta
geometry.json             the GeometryReadings and the GateResult
source-attestation.json   source path, size, LastWriteTimeUtc, hash; recorded at plan time,
                          re-checked at report time; a difference is a HARD FAILURE of the run
report.md                 the engineer-facing summary
events.jsonl, session.json   the agent run (same shape as a review; reuse)
remodel.log               one line per bridge request: command, elapsed, gated members, target path
```

### R8.2 `changes.jsonl` is both the undo record and the change list the pane shows

One line is written **before** the call (`status: "attempting"`) and a second after
(`applied | failed | rolled_back`), so a hard crash mid-change leaves an `attempting` line naming
exactly what was in flight.

```jsonc
{"seq":17,"at":"...","kind":"reorder",
 "subject":{"feature_id":"feat:0042","name":"Fillet3","persist_ref":"<b64>"},
 "before":{"index":42,"anchor":"Cut-Extrude2"},
 "after":{"index":61,"anchor":"Chamfer1"},
 "undo":{"command":"remodel.reorder","params":{"feature_persist_ref":"<b64>",
         "anchor_persist_ref":"<b64 of Cut-Extrude2>","location":"after"}},
 "rebuild_errors_before":0,"rebuild_errors_after":0,"status":"applied","elapsed_ms":310}
```

### R8.3 Three undo tiers, ranked

`IModelDoc2.EditUndo2(Int32)` returns **void** (VERIFIED). The caller cannot tell whether it did
anything, and it shares the UI undo stack the engineer can also touch. It is rejected as the
mechanism.

1. **Per-change forward inverse (primary).** Every change kind has an exact inverse that is
   itself a guarded write, derived by the pure `apply_log.derive_undo(change)`. This is primary
   because it lets the run continue past one bad change.
2. **Catastrophic fallback.** Delete the copy, re-`File.Copy` the source, replay `changes.jsonl`
   up to the last `applied` line. Deterministic, because every change is persist-ref addressed.
3. **`EditUndo2`: never.** Not in the allowlist (R5.5).

| Change kind | Inverse in v1 |
|---|---|
| `rename` | rename back to the recorded previous name |
| `reorder` | reorder back to the recorded anchor |
| `folder.create` | **none in v1**: the inverse is a folder dissolve, which needs `IModelDoc2.EditDelete`, which the owner decision removed from the allowlist. A failed folder creation escalates to tier 2 |
| `folder.rename` | rename to the recorded previous name |
| `describe` | write the recorded previous text (`""` when there was none; **refused up front** when `before` was `null`, which means unreadable) |
| `equation.add` | `IEquationMgr.Delete(index)`, in reverse order, subject to R3.5's rule |
| `equation.edit` | write back the recorded previous equation text through the same `set` path. An in-place edit is its own inverse, which is why the repair is a distinct kind rather than a delete plus an add |
| `save` | none: the copy is saved once, at the end, only after the gate passes |
| `folder.dissolve` | not a v1 operation (R5.4, R6.6) |

Because folder creation is the one change with no in-place inverse in v1, the executor orders
**all** folder creations after every reorder and description change, and a folder creation
failure ends the run: the run finalizes, reports, and does not save. This is stated as a design
consequence rather than discovered during implementation.

### R8.4 Limits

Enforced by the executor and never by the model: `max_changes` 250, `max_minutes` 20 wall clock,
`max_rebuild_seconds` 120. Hitting one is `truncated`: stop, finalize, and report how many of
the planned changes were applied and which were not. **Never a silent partial success.**

### R8.5 Verify, save, attest, report

Verify is pure over readings the bridge returns: `GetWhatsWrongCount() == 0` **and** every
`IFeature.GetErrorCode2 == swFeatureErrorNone` **and** the geometry gate at the `IDENTITY`
profile returns `pass`. Any failure discards the copy, reports, and does not save.

Save is `Save3(swSaveAsOptions_Silent = 1, out errors, out warnings)`. `errors != 0` is a failed
run. `warnings & swFileSaveWarning_RebuildError` is a failed run **with a saved artifact**, and
the report says exactly that rather than quietly counting it as a success. Then assert
`GetSaveFlag() == false`.

Attest: re-check the source's `LastWriteTimeUtc`, length and hash; restore the four system
toggles.

Report: the change list, the before-and-after RMS grade, the geometry comparison, and the rebuild
list with a reason for every entry. There is no approve-each-change mode: the run goes to
completion and then presents all three (owner decision, R12).

### R8.6 Discard

Discard closes the copy without saving and deletes `copy/`, and **keeps every other artifact**
(owner decision, R12 OQ-5). Deleting the whole run folder would lose the evidence Principle VI
asks for, and "what did it propose?" must stay answerable after the engineer says no.

---

## R9. The pane: tab 5, "Remodel"

`AddIn/Remodel/RemodelPage/{index.html, remodel.js, remodel.css}` on the shared
`CoreWebView2Environment`, the same virtual host, the same CSP, the same `textContent`-only
rendering rule, and the same `NavigationStarting` / `NewWindowRequested` cancellation as the
existing pages. `RemodelHost` owns only `ready` and `remodel.*`; everything else delegates to
003's `PaneActions`. The WebView is created lazily on first activation of the tab (RK-11).

**Page to host**

| type | payload | host action |
|---|---|---|
| `ready` | `{}` | reply `init` `{backend:{port,origin}, token, run_root, document:{path,configuration,kind}\|null, limits}` |
| `remodel.plan` | `{}` | probe the active document's scope signals (`remodel.probe_scope`, read members only) and refuse (`error`) if there is no document, it is not a part, it is dirty (`GetSaveFlag()`), it is read-only, it has external references, or it fails the scope gate, **all before anything is copied**. Otherwise create the run folder, `File.Copy`, open and tag, roll and rebuild (a non-zero error count refuses and deletes the copy), dump, plan. Reply `remodel.planned {run_dir, plan_summary}` |
| `remodel.start` | `{run_dir}` | run phases B to D to completion; progress through `status`; reply `remodel.started {chat_id}` |
| `remodel.stop` | `{}` | set the stop flag; the executor finishes the change in flight, rolls it back if it failed, finalizes; reply `remodel.stopped {changes_applied}` |
| `remodel.result` | `{run_dir}` | reply `{changes[], grade_before, grade_after, geometry, rebuild_list[]}` read from the run folder |
| `remodel.open_copy` | `{run_dir}` | activate, or re-open, the copy; reply `ok` |
| `remodel.discard_copy` | `{run_dir}` | `CloseDoc` without saving, delete `copy/`, keep every other artifact; reply `ok` |
| `remodel.show_change` | `{run_dir, change_seq}` | resolve the change's persist ref through 003's `FeatureSelection` and the existing `SwEntityResolver`; reply `entity.shown {ok, state_code, message}`, deliberately the identical payload `entity.show` already returns, so one resolver serves three tabs |
| `report.open` / `folder.open` / `log.open` | `{run_dir}` | delegated to `PaneActions`; path canonicalized and required to be a descendant of `run_root` |

**Host to page (unsolicited)**

| type | payload |
|---|---|
| `status` | `{stage: copying\|dumping\|planning\|judging\|applying\|verifying\|ready\|error, message}` |
| `remodel.progress` | `{applied, total, current:{seq, kind, subject_name}}` |
| `remodel.change` | one `ChangeRecord` as it is written, so the list grows live |
| `document.changed` | `{path, configuration} \| null`; if the **copy** goes away mid-run, the run aborts |

Two operational rules:

- **One remodel run per host.** A second is refused with `error {error_class: "RunInProgress"}`,
  the same shape `settings.save` already uses for `TurnRunning`. `ToolServiceGate` already
  enforces one tool service per add-in instance (RK-10).
- **A run never auto-resumes.** If SOLIDWORKS dies mid-run, the existing `CircuitBreaker` trips
  to `circuit_open`, and the copy and `changes.jsonl` survive on disk. Resuming onto a tree that
  was not re-verified is exactly the wrong risk, so resume is refused and there is a test that
  says so; recovery is manual and documented in the quickstart (RK-12).

---

## R10. The probe backlog

Reproduced from the design brief's ledger, with its blocking flags. A blocking probe gates the
code that depends on it; the phase order in the plan exists to run these before the write code is
trusted.

| # | Question | Blocking? |
|---|---|---|
| PROBE-1 | Does `ISldWorks.CommandInProgress = true` suppress the "Cannot reorder" message box? | **Blocking**: if not, an illegal reorder hangs the add-in's STA thread and stage 1 cannot run unattended |
| PROBE-2 | Equation units: does `"w" = 120` in a mm part produce 120 mm, and what unit does `EquationMgr.get_Value(i)` return? | **Blocking**: a wrong answer silently builds a 120-meter part |
| PROBE-3 | Does `ReorderFeature(f, anchor, swMoveAfter = 3)` move a feature on 2024, and return `false` rather than corrupting the tree when asked to move past a dependency? | **Blocking**: this is the whole reorganize-in-place premise |
| PROBE-4 | Do folders require **contiguous** members on 2024? (Upstream says yes on 2026.) | **Blocking** |
| PROBE-5 | Does `ReorderFeature(f, folderName, swMoveToFolder = 5)` move a feature into an existing folder? Does `MoveToFolder` work, or silently no-op as on 2026? Does `IFeature.MakeSubFeature` work? | No: an optimization; the folder plan does not need any of them |
| PROBE-6 | Does `EquationMgr.Add3` work on 2024, or silently return `-1` as on 2026? | No: the verified helper handles both |
| PROBE-7 | Does `set_Equation(i, text)` edit in place from C#? | No: fallbacks documented |
| PROBE-8 | **Calibrate the tolerances**: attained relative error on volume, area, center of mass and moments at `swMassPropertyAccuracyLevel_Higher` against a part of exactly known analytic volume (box, cylinder). Record in a `capabilities.yaml`-style ledger. | **Blocking for shipping the gate** |
| PROBE-9 | `GetWhatsWrong` out-array element type on 2024: feature **names** or `Feature` objects? | No: `GetErrorCode2` is primary |
| PROBE-10 | Does the `___EndTag___` marker appear on 2024, and does it keep the folder's **default** name after a rename? | No: 003 already handles both shapes |
| PROBE-11 | `GetTypeName2` values on 2024 versus the 2026-calibrated `rms_types.yaml` (`ICE` covering both cuts and some bosses; `CommentsFolder` / `SelectionSetFolder` / `InkMarkupFolder`). | No: unknown gives `unresolved` |
| PROBE-12 | Does `ICustomPropertyManager.Add3(key, 30, value, 2)` tag, and does `Get4` read it back, on 2024? | **Blocking**: it is one of `VerifyTarget`'s four checks |
| PROBE-13 | Does `File.Copy` succeed on a `.SLDPRT` SOLIDWORKS currently has open? | No: `FileShare.ReadWrite` stream fallback |
| PROBE-14 | Time the ModelCheck-profile dump: a 150-feature RMS part (target under 2 s) and the 200-component pilot assembly (target under 20 s, SC-002's budget). | No, but it sets the tab's honest claim |
| PROBE-15 | Does `IConfiguration.GetRootComponent3(false)` return a component for a **part** configuration on 2024? | **Blocking for 003 US6 and therefore for 004** |
| PROBE-16 | Show in context: does `SelectByID2(featureSelectName + "@" + IComponent2.GetSelectByIDString(), <GetNameForSelection type>)` select a part feature inside an active assembly? Record the exact strings. Does `GetNameForSelection` on a feature from the part document already return a qualified name? | No: the component-only fallback already works |
| PROBE-17 | `SelectByID2` type strings on 2024 (`"FTRFOLDER"`, `"BODYFEATURE"`, `"SKETCH"`, `"PLANE"`, `"AXIS"`), or confirm `IFeature.Select2` makes the table unnecessary. | No |
| PROBE-18 | Does `IMassProperty.AddBodies` accept a **temporary** (non-document) body? | Blocking **for stage 2's tier-2 gate only**: the whole boolean gate depends on measuring a temp body's volume. Fallback: `CreateFeatureFromBody3` into a scratch document |
| PROBE-19 | Does `Operations2` work across **two different documents'** temp bodies? Does `Copy()` on a document body yield `IsTemporaryBody() == true`? | Stage 2 only. Good failure behavior either way: `swBodyOperationNonApiBody(1)` is a clear, actionable error rather than a wrong answer |
| PROBE-20 | Does `IFeature.Description` survive a reorder and a folder wrap? Is it per-configuration? | No |
| PROBE-21 | `IEquationMgr` on a part with no equations: count 0, or a throw? | No |
| PROBE-22 | Selection **marks** for `FeatureRevolve2` (profile versus axis) and `InsertMirrorFeature2` (plane versus features). | Stage 2 only |

Stage-1 probes, run on a throwaway part the probe builds itself: PROBE-1, 2, 3, 4, 5, 6, 7, 10,
12, 13, 20, 21, plus PROBE-8's tolerance calibration on a box and a cylinder. PROBE-15 belongs to
003 US6 and gates this feature's start. PROBE-18, 19 and 22 are stage-2 only.

---

## R11. Constitution amendment

The read-only rule currently lives implicitly in Principle II ("SolidWorks does what only
SolidWorks can do (read ...)") and explicitly only as a *gate* in each plan's Constitution Check
table. Feature 003 already needs one documented exception (the suppressibility test), carried in
its Complexity Tracking table rather than in the constitution. Adding a second, larger exception
the same way would leave the governing rule unwritten while two features carve at it.

So: write the rule down, and write both exceptions under it. New subsection in **Technical
Constraints**, after the "SolidWorks-side code" bullet. New section, materially expanded
guidance, no principle removed or redefined, therefore **MINOR: 1.0.0 to 1.1.0**.

Rejected alternative: a new Principle VII, "Proposals, Not Edits". The rule is a constraint on
where code may write, not a principle about what evidence means, and Principle I already covers
how a proposal is judged. Six principles that each say something distinct beats seven where one
is a misplaced constraint.

### R11.1 Text to insert

> - **Documents are read, not written.** The reviewer, every check, every tool exposed to a
>   model, and every add-in command MUST treat every document SOLIDWORKS has open as read-only.
>   `ReadOnlyGuard` is the enforcement point, and its denylist grows the moment a phase touches
>   an API family that can write. There are exactly two exceptions, both bounded below; a third
>   requires an amendment to this file.
>
>   1. **The suppressibility test** (feature 003): console-only, behind an explicit flag, driven
>      by a reviewer-written plan, under a guard that exempts exactly `IFeature.SetSuppression2`
>      and `IModelDoc2.ForceRebuild3`, over a saved and not-rolled-back document with no
>      pre-existing rebuild errors, with a whole-tree snapshot and a verified restore. It never
>      saves.
>
>   2. **The re-modeler** (feature 004): the re-modeler MAY create and modify exactly one
>      document, a copy it created during this session, and no other.
>      - The copy is made by a filesystem copy that refuses to overwrite, into the run folder,
>        before any SOLIDWORKS document handle exists. The engineer's file is never opened for
>        writing, never saved, never renamed and never deleted. The run records the source file's
>        size, last-write time and content hash before it starts and re-checks all three before
>        it reports; a difference is a hard failure of the run.
>      - **The re-modeler MUST NOT save over a file that already existed.** Only
>        `IModelDoc2.Save3` is permitted, which takes no filename and therefore writes only to
>        the copy's own path, and only after the geometry comparison has passed. `SaveAs3` to any
>        path, and any write to any document that is not this run's copy, are refused by the
>        guard, not by convention.
>      - Writes go through a document-scoped guard that (a) **allowlists** the specific
>        interface-qualified interop members the run needs and refuses every other write, and
>        (b) re-verifies the target document's path, its session tag, and its COM identity
>        immediately before each write. No command in the bridge protocol, and no tool exposed to
>        the language model, names a document.
>      - Every applied change is recorded with its before state, its after state, and the inverse
>        operation that undoes it. A change that raises the rebuild-error count above the run's
>        baseline is undone and recorded as undone. The run is bounded by a change count and a
>        wall-clock limit, and a truncated run says so.
>      - The language model does not perform the mutation. It proposes intent (descriptions,
>        global-variable names, and the judgement calls the modeling method itself says to ask
>        about) into a plan; a deterministic executor applies the plan. Where a stage genuinely
>        requires generative modeling, the model's tools are the same guarded, document-scoped
>        commands, and each change is created, verified and rolled back individually.
>      - Geometric equivalence is reported as `pass`, `fail` or `unresolved`, never as a Boolean,
>        and never inferred from a successful rebuild.
>
>   A mutation exception is not an engineering result. A copy that rebuilds cleanly, has the same
>   volume, and grades better against the Resilient Modeling Strategy is a **proposal** the
>   engineer accepts or discards; Principle I applies to it unchanged.

### R11.2 Sync Impact Report comment

```
- Version change: 1.0.0 → 1.1.0
- Modified principles: none
- Added sections: Technical Constraints → "Documents are read, not written" (the read-only rule,
  previously implicit in Principle II and enforced only in per-plan Constitution Checks, plus the
  two bounded exceptions: 003 suppress-test, 004 re-modeler copy)
- Removed sections: none
- Templates: no edits required
- Migration: specs/003-resilient-modeling/plan.md's Complexity Tracking row for `suppress-test`
  now cites this section rather than standing alone.
```

---

## R12. Open questions, resolved

Every row is an owner decision and is binding on this package. The consequences column names
where the decision is already applied in this document.

| # | Question | Decision | Applied in |
|---|---|---|---|
| OQ-1 | Dry run before write code? | **Yes.** The planner is built first and `swreview remodel plan --json` is run over the benchmark packages and 3 to 5 real parts before any C# write code exists (Phase 0 and Phase 1) | R6.7 |
| OQ-2 | Dimensions in the IR | **v1 ships without them and says so.** Globals that already exist are named and repaired; new globals are added only where feature data justifies them (hole diameter, shell thickness, fillet radius). Turning a literal sketch dimension into a global is a **separate later feature** that extends the extractor | R7, and a non-goal in the spec |
| OQ-3 | Is `EditDelete` in the stage-1 allowlist? | **No.** A legacy part with an RMS-named folder holding the wrong members is **refused** in v1 | R5.4, R6.6, R8.3 |
| OQ-4 | Structural versus cosmetic fillets | **Default to `3-Core`**, and list every one in the report as "reviewed as structural; move to Quarantine if cosmetic" | R6.1 |
| OQ-5 | Discard semantics | **Keep everything but the `.SLDPRT`** | R8.6 |
| OQ-6 | Model Check transport fallback | **Route only** (a feature 003 decision, recorded here because 004's pane inherits the same transport rule: the page talks to the backend directly, the host does not proxy results) | R9 |
| OQ-7 | Exceptions storage | **(a) Copy forward.** Exceptions are copied into each new run folder for the same design; there is no per-design store. A run folder stays the whole story | R8.1, and the carry-forward helper is 003's |
| OQ-8 | Does stage 2 ship in v1? | **No.** Stage 1 ships, runs on real parts, and stage 2 is re-specified with those numbers in hand. The tri-state `GateResult`, the `tier_2` slot and the profile table stay, so stage 2 adds a tier and a second additive allowlist, not a type change | R4.4, R4.6, R5.5 |
| OQ-9 | Assembly scope in the Model Check tab | **Part-only first** (a feature 003 decision). 004 is **parts only** in v1 regardless | R4.1 |
| OQ-10 | Where the copy lives | **Run folder only.** The copy leaves through "Open copy" plus a Save As the engineer performs | R2.5 |
| OQ-11 | EPDM | **Copy out.** Nothing is refused for vault reasons; the vault path and revision are recorded in `plan.json` and the attestation | R2.5, R2.6 |

Four further owner decisions that are not numbered open questions but bind this package equally:

1. **The reviewer and the Model check stay read-only.** The constitution exception in R11 covers
   the re-modeler's copy and nothing else. No reviewer code path and no check gains a write.
2. **v1 depth is staged, and only stage 1 ships.** Stage 1 is reorganize: groups, folders,
   descriptions, global variables, with geometry proven unchanged. Stage 2 is rebuild what blocks
   the rules, and it is named as out of scope in the spec.
3. **The run goes to completion, then presents.** No approve-each-change mode. The three things
   presented are the change list, the before-and-after RMS grade, and the geometry comparison.
4. **Providers are OpenAI (default) and Gemini, through the existing provider layer. Never
   Claude.**
