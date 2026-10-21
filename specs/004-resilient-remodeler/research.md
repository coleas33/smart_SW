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
*Added 2026-09-26:* the defaults taken on 2026-09-26, when the owner asked to proceed without
questions unless blocked, are recorded in R13. They are not owner decisions: each is a default
the owner may revise, and none is written as the owner's words. *Added 2026-09-27:* so are the
defaults the review of the seat adapter's integration took, in R14, and those of T181 and T179,
in R15.

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

*Amended 2026-09-28 (U27; default taken 2026-09-28, the owner may revise; R16.2, `tasks.md` T185):*
`CommandInProgress` is set with the toggles and put back as `remodel.open`'s last step; only the
three dialog toggles hold for the session.

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

*Amended 2026-09-25 on review (T169): the named creators the list missed.* A review of the
implementation found members of the four interfaces whose API help says they create something
passing a read-only gate bare, because the grammar does not reach them and the named list did not
name them, and `CreationFamilyCompletenessTests` checks only the grammar's matches and that each
named creator is real. Reading the installed help again over every public method of the four that
is neither a reader nor a grammar match and that the guard allowed (533 names) gives ten:
`IFeatureManager.FilletXpertMakeCorner` (a fillet corner feature); `IModelDoc2.Scale` (scales the
part, as the refused `InsertScale` does), `NameView` (a named view), `SkToolsAutoConstr` (relations
added to the active sketch) and the obsolete `SplitOpenSegment` and `SplitClosedSegment` (split
sketch segments); `IModelDocExtension.GeodesicSketchOffset` (the sibling of the refused
`SketchOffsetOnSurface`), `SaveSelection` (a selection set), `Capture3DView` (a 3D View) and
`BreakAllExternalFileReferences2` (the original parts' features, inserted when asked). They join
the named creators; none is a stage-1 key's bare name, a `RemodelGuard` refusal or already denied.
The scan of product literals finds one new collision, the JSON property name `scale` of
`Ir/DrawingSheet.cs`, which matches `Scale` by case only and is named in the audit as feature
011's `dimensions` is; `Scale`'s other bare-name holders, `IMathPoint` and `IMathVector`, are math
the product does not call. The same review found the grammar reaching two members that create
nothing, `IModelDocExtension.SketchBoxSelect` (a box selection) and `IModelDoc2.AddIns` (the
Add-In Manager); they stay refused, since a denial fails closed and allowing them would widen the
guard, which is the owner's call, and the contract says so beside rule 1.

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
then, and the copy carried the original's wrong `redact=` keyword, so the Gemini fix of `287d4c3`
had to be made twice; one body cannot disagree with itself.

**Not MCP tools.** The `propose_*` tools are registered on the remodel run's registry only. They
do not appear in the MCP function list and they are not in the terminal profile's
`enabled_tools`; a test asserts both.

---

## R8. Artifacts and undo tiers

### R8.1 The run folder

Created by the existing `RunFolders` helper so the naming convention stays in one place:
`<run_root>/<yyyyMMdd-HHmmss>-<doc>-remodel/`. *Amended 2026-10-20 (feature 011, owner decision
148A; its research R12.3):* in its full form, named under `Path.GetFullPath` of the run root, so a
run root spelled with a `..` segment, which the backend's rule for a run folder and the one rule for
the copy's path refuse, plans.

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
| `remodel.plan` | `{}` | probe the active document's scope signals (`remodel.probe_scope`, read members only) and refuse (`error`) if there is no document, it is not a part, it is dirty (`GetSaveFlag()`), it is read-only (*amended 2026-09-28, U26: read-only sources are allowed; a read-only source whose save flag cannot be believed is refused instead, R16.3*), it has external references, or it fails the scope gate, **all before anything is copied**. Otherwise create the run folder, `File.Copy`, open and tag, roll and rebuild (a non-zero error count refuses and deletes the copy), dump, plan. Reply `remodel.planned {run_dir, plan_summary}` |
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

Two operational rules, and a third added by the owner's decision 22A (2026-09-25):

- **One remodel run per host.** A second is refused with `error {error_class: "RunInProgress"}`,
  the same shape `settings.save` already uses for `TurnRunning`. `ToolServiceGate` already
  enforces one tool service per add-in instance (RK-10).
- **A run never auto-resumes.** If SOLIDWORKS dies mid-run, the existing `CircuitBreaker` trips
  to `circuit_open`, and the copy and `changes.jsonl` survive on disk. Resuming onto a tree that
  was not re-verified is exactly the wrong risk, so resume is refused and there is a test that
  says so; recovery is manual and documented in the quickstart (RK-12).
- **A plan does not survive a tool-service re-attach (decision 22A, 004 T160).** `remodel.open`
  leaves the run's `RemodelSession` on the dispatcher of the tool service that answered it, and
  `ToolServiceGate.FollowDocument` replaces that service - a new pipe, new secrets, a new
  dispatcher with no session - whenever SOLIDWORKS switches documents and nothing holds the
  bridge. A plan waiting for Start holds nothing: `RemodelHost.RunInProgress` drops when planning
  ends. The two ways out were to carry the session across the re-attach (it belongs to the run,
  not to the document) or to refuse Start by name; the owner chose the refusal. The host records
  on each run the attachment its plan was made on (the pipe name, minted fresh per start) and
  `remodel.start` refuses a run whose attachment is not the one listening now with
  `SessionLost`, before `remodel.started` and before any call that could change anything; the
  engineer plans again. Comparing the attachment rather than the document is what makes a
  re-attach back to the same document refused and a configuration switch, which re-attaches
  nothing, not. The bridge's own `target_mismatch` on a dispatcher with no session stays the
  backstop for the race between the pane's check and the backend's first call. For the same
  reason a discard of such a run sends no `remodel.close` through the new attachment, whose
  session, if it holds one, is another plan's (004 T168, found while implementing T160). What the
  discarded session leaves on the seat - the toggles `remodel.open` set and the copy still open -
  is 004 T167, not decided. *Amended 2026-09-25 (owner, decision 24A; 004 T170):* the engineer is
  told as soon as the plan is lost rather than at the next Start. The host hears of every
  tool-service attach and detach, so it posts `remodel.plan_lost` for the plan on screen once
  that plan's attachment is gone, and the page disables Start and offers Plan again; `SessionLost`
  stays the backstop. *Amended 2026-09-26 (defaults taken 2026-09-26, the owner may revise;
  R13.1, R13.4):* T167 is decided - a re-attach or an unload ends the session on the application
  thread before the pipe closes, the copy closed unsaved and the settings restored - and planning
  again while a plan waits closes the earlier plan's session first and marks that plan lost
  (004 T173). *Amended 2026-10-20 (owner decision 152A; 002 `research.md`, 152A):* a switch the
  tool service skipped while a turn or a plan or a run held the bridge is no longer left until the
  next switch: the gate looks again every second while one is owed and, once nothing holds the
  bridge, follows the document active then, by its path - a re-attach, which loses a plan made on
  the old attachment as any re-attach does, told as 24A tells it. The planned copy's own attachment
  (T180) is kept by that look exactly as by a switch: the plan holds the bridge while it opens and
  activates its copy, so that switch is owed, and the look once the plan ends finds the held copy
  active and keeps the plan's attachment. With Start switched off a plan's session is closed at the
  plan (T176), so the look follows whatever the plan's close left active - the original, normally,
  or the copy if the close left it open and active, which tells the plan lost; put to the owner.
  *Settled 2026-10-21 by owner decision 159A (R19.5; T212, T213):* the look still follows the copy,
  and tells nothing: a plan closed at the plan holds no session for a re-attach to take, so it is
  not lost. A
  configuration switch re-attaches nothing, at the switch or in a look; a review that finds the
  bridge on another configuration asks the gate to follow the active document, which re-attaches
  it, and a plan on the old attachment is then lost like any other. *Amended 2026-10-20 (owner
  decision 152A, on the Codex review; 002 `research.md`, 152A):* a look's busy question is a round
  trip, and a plan could begin while it was out - too late for the question, its copy made active,
  not yet the planned plan whose held copy keeps the attachment - and the look took the bridge down
  under it; so could a Start. A plan and a run now hold the attachment through the gate from just
  after the host is marked busy until it is free again, and a follow takes the bridge down only if no
  hold was taken while its question was out. With none listening to hold, a plan is refused as while
  the tool service attaches and a Start as a lost session (`contracts/pane-remodel-messages.md`).
  *Noted 2026-10-21 (002 `research.md`, 152A, the merge of `main` and its final reviews, N5):* since
  the merge with 154A a plan and a Start hold from just after the run root is judged again, which
  follows the gate, so a press refused for its run root holds nothing.

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

---

## R13. Defaults taken 2026-09-26: the sitting's remodel items

**Sources.** The 2026-09-26 sitting on the pilot workstation, the first on the checks-first
build, and its debrief, which is held outside this repository because it carries company data
(nothing is copied from it here); and two of the six analysts' reports on that sitting: "remodel
scope" (this feature's seat adapter, T152 to T159 and T161, and the then-undecided T167) and
"logs, runs and U24" (the probe 1 race). The owner asked on 2026-09-26 to proceed without
questions unless blocked, so each question those analysts put is settled below by a default.
**Each is a default taken 2026-09-26, the owner may revise; none is the owner's own words, and
none is an R12 decision.** The review-side items of the same sitting are feature 013's
(`specs/013-engineer-first-review/`), which leaves this feature's documents to this section.

**What the analysts found (VERIFIED by reading; SOLIDWORKS was not started).** The production
seat was never built: `ToolServiceHost.Attach` never sets `BridgeServices.RemodelSeat`, so the
Remodel tab shows its designed refusal (T157). The per-run folder handoff has no writer in the
product (T158). The in-process dump reads whatever document is active (T159). Nothing ends a
remodel session when the tool service goes away: a re-attach disposes only the pipe server, and
the dispatcher has no teardown (T167). `remodel.close` runs its verification, untag and close
outside any `try`, so one throw leaves the settings flipped and the session stuck, and no test
covers it. The sitting's tool-service logs show three attachments across three documents in
sixteen minutes, so a plan waiting for Start will routinely meet a re-attach: T167 is not a rare
edge case.

### R13.1 T167: the teardown ends the session

**Decision**: on a re-attach or an add-in unload, on the application thread and before the pipe
closes, one routine shared with `remodel.close` ends the session: verify the target; when it
passes, remove the tag and close the copy unsaved, each write judged by the guard and logged but
not counted against the circuit breaker; restore all four settings in a `finally`,
`CommandInProgress` last; clear the session and the run root. The copy file stays in `copy/`, the
run folder stays whole with `plan.json` untouched, and one teardown line goes to the tool-service
log and to `remodel.log`. The pane is quiet on success and shows one plain-words status error on a
failure. (004 T167; `contracts/bridge-remodel.md`, "Ending a session".)

**Default taken 2026-09-26, the owner may revise.**

**Why**: FR-005 and FR-031 ask for the settings restored in every case, and nothing restores them
on a re-attach today. The three toggles are system options SOLIDWORKS keeps across sessions
(INFERRED), so an unrestored plan could leave them off for good, and `CommandInProgress` left true
suppresses modal boxes for the rest of the session. Once T157 gives the add-in a seat, the
"Nothing was changed" of `SessionLostMessage` and `PlanLostMessage` would be false without it.
Closing unsaved keeps the constitution's exception exactly as it is - the copy is saved only by
`remodel.save` - and closing is what lets a later Discard delete `copy/`. Running inline at
unload avoids a self-deadlock (`DisconnectFromSW` is already on the application thread); a
re-attach, which comes from the thread pool, posts with a bounded wait. One routine for both
paths also mends `remodel.close`'s unprotected failure path.

**Alternatives weighed**: the pane only reports what was left behind and how to put it right
(not taken: it leaves the engineer to restore four settings by hand after every document switch
while a plan waits); delete the copy at teardown (not taken: a teardown deletes nothing, and
Discard stays the one delete).

### R13.2 T157 and T167 land together; T167 is a prerequisite of T135

**Decision**: T157 (the seat) and T167 (the teardown) land in the same build, with T172 (R13.3),
and T167 joins T152 to T160 as a prerequisite of T135. The pass line of test-plan step 5.3, the
"not in this build" sentence today, becomes Plan, then Discard, with the engineer's file
unchanged and the settings as they were.

**Default taken 2026-09-26, the owner may revise.**

**Why**: a seated build without the teardown is a build in which a document switch leaves the
seat's settings changed; landing the two together means main never holds one.

### R13.3 Start is switched off until the blocking probes pass

**Decision**: a switch like `DrawingOpenScope.SeatValidated` - `RemodelStart.SeatValidated`,
false as shipped - lets Plan run and refuses Start in plain words (`StartNotValidated`, before
any call and with nothing written) until PROBE-1, 2, 3, 4 and 12 have verdicts from a seat. It is
set true in a commit of its own that cites the capabilities ledger. While it is false the bridge
refuses the six change commands as a backstop. (004 T172.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: with T157, Start is reachable before step 5.6's verdicts, and PROBE-1 is exactly whether
an illegal reorder's "Cannot reorder" box hangs the application thread; FR-005 says stage 1 must
not run unattended if it does. Plan makes no reorder, so meanwhile it can exercise T153 to T159
and the teardown on the seat. The cost is one more sitting before T135. The backstop follows
`remodel.save`'s rule that a clause checked only by the caller is one the caller can skip.

**Alternatives weighed**: a per-seat opt-in setting (not taken: a setting the engineer can turn
on is a way past the probes, where the build switch needs a commit citing their verdicts); an
instruction in the test plan only (not taken: nothing in the product would stop a Start).

### R13.4 Planning again while an earlier plan waits; a copy is never a source

**Decision**: when Plan is pressed while an earlier plan waits for Start, the host answers the
refusals that need no bridge call first, then closes the earlier plan's session - unsaved, the
folder kept, through `remodel.close` and so through R13.1's routine, and only when that plan's
attachment is still the one listening - marks that plan lost (`remodel.plan_lost` for it, and
`SessionLost` for a Start naming it), then plans. A source that lies in a run folder's `copy/`
under `run_root` is refused (`SourceIsRemodelCopy`) before any bridge call. (004 T173.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: the path is reachable and unhandled. The page keeps Plan enabled while a plan is held,
the host makes the new run folder first, and the dispatcher refuses the second `remodel.open` as
`run_in_progress`, because the earlier session is still open. After T159 the active document is
the copy, so pressing Plan again without switching documents would probe the copy itself - dirty
after the rollback and rebuild - and send the engineer to save it. Answering the no-call refusals
first is a choice of this amendment (R13.8, D4).

**Alternatives weighed**: refuse the new Plan with "Discard the earlier plan first" (not taken:
one more press, for a plan the engineer has already chosen to replace).

### R13.5 `GetVault` answers null, "not read by this build"

**Decision**: the seat's `GetVault` answers null until T139 adds a vault read, and data-model
sections 4.1 and 5 say that a null vault means "not read by this build", not "not in a vault".
T139 decides how the two are told apart once a read exists.

**Default taken 2026-09-26, the owner may revise.**

**Why**: no PDM API is referenced anywhere in the product, and the code defines null as "not in a
vault" (`Rms/RemodelCopy.cs`, `Rms/RemodelScopeProbe.cs`), so a null for a vault part would
record something false in `plan.json`. The report already omits a null vault line
(`remodel/report.py`), so it claims nothing either way. A vault part is still copied out and never
refused for vault reasons (FR-006).

**Alternatives weighed**: a late-bound PDM read now (not taken: unverified, and it needs a seat
with the PDM client, which is T139's sitting).

### R13.6 T135 on Part A: the refusal is an expected pass of FR-007

**Decision**: T135 on benchmark Part A expects the scope refusal `rms_named_folder_wrong_members`,
before anything is copied, and records it as an expected pass of FR-007. The compliant case runs
on a variant of Part A with no group-named folders, judged against the development machine's dry
run over the variant's package rather than against "a near-empty change list and a zero delta".

**Default taken 2026-09-26, the owner may revise.**

**Why**: T135 as written cannot pass on Part A. Its recipe has the six groups present and in
order (`benchmarks/native/rms-part/RECIPE.md`), and the scope gate refuses any part that already
carries a group-named folder, before the copy (`reviewer/src/swreview/remodel/scope.py`), because
this version can neither verify nor repair their membership before the copy exists and has no
dissolve path (R12, OQ-3). Phase 0's offline dry run refused the `rms-part` golden packages, which
carry group folders, the same way (`phase0-decision.md`, rows 14 to 16). A variant with its
folders dissolved is planned, and its folder creations make its change list and its grade delta
non-trivial, which is why the dry run, not a fixed expectation, is the yardstick.

### R13.7 Probe 1's watchdog is decided by signals, and runs flag-set first (U24)

**Decision**: the probe 1 watchdog runs the call on a thread of its own and starts its deadline
only once the call has begun; the deadline is a seam the tests control; a host's own exception
reaches the ledger; and probe 1 runs its flag-set attempt first. The code is the change feature
013 lists as 013 T135 to T137 (that package's research R2.41 records the same default); this
feature records it as T171 and amends T033, because the probe is this feature's, and the change is
built once.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the verdict came from a wall-clock race: `Rms/RemodelProbeWatchdog.cs:65-72` counts
thread-pool queueing as blocking, which a loaded test suite can turn into a false `Refuted`. On
the seat, if the flag-clear attempt blocks as expected, its message box is still up when the
flag-set attempt runs, which could read as blocked and give a false `Refuted` too; flag-set first
gives the reading that matters a clean seat. `RemodelProbe1Logic.Decide` is unchanged.

### R13.8 Design choices of this amendment

Choices the defaults leave open, made here and changeable in review. They are neither owner
decisions nor the defaults above:

| # | Choice | Reason |
|---|---|---|
| D1 | The seat adapter is built in lanes A to F, plus U for the probe watchdog (`tasks.md`, "Build order") | The analysts' split: each lane owns its files, so lanes can be built side by side; the probe host's wrappers are split first because lane B builds on them |
| D2 | `StartNotValidated` comes after `ResumeRefused` and before `SessionLost` in Start's refusal order | A Start this build can never honour says so before anything about the plan's session, so the engineer is not sent to plan again for nothing |
| D3 | While Start is switched off the bridge refuses the change commands (`start_not_validated`, a `RemodelContractError`) | Defence in depth, as `remodel.save`'s `gate_not_passed` is; the pane refuses first, so reaching it is a bug in the caller |
| D4 | Planning again answers the refusals that need no bridge call before it closes the earlier plan | A Plan refused on the spot costs the earlier plan nothing |
| D5 | The run root is used up at `remodel.open` and bound per run through `IToolService.BindRemodelRun` (T158) | Stricter than "cleared at close": a second run gets a fresh root by construction |
| D6 | Both dumps activate the copy first, activate only, and refuse rather than open it (T159) | `package-after.json` has the same gap as `package-before.json`, and a dump that opened a document would be a second way to open one |
| D7 | Open step 12 compares each folder's name and member count, not its members' persist-ref strings (T174) | Feature 001's research R12: the bytes for one entity may differ, so string equality could refuse plain folders once the reader returns real refs (INFERRED; checked on the seat) |
| D8 | The teardown's failure words name the settings by their Tools > Options labels and say whether the copy is still open, with no path | The engineer can put right only what the words name; the labels themselves are checked on the seat |

**What only a seat can show** (the analysts' list, kept for the sittings): whether `OpenDoc7`
with `Silent | LoadModel` activates the copy; the path's spelling after the open; the COM identity
check; the tag round trip (PROBE-12); rollback, rebuild and error counts on real parts;
`GetFeatures(true)` order against the dump's; persist-ref round trips, and whether member refs
compare equal between source and copy; folder membership and end tags; `GetUnits`; the material
name with the active configuration; mass properties (PROBE-8); reorders, folders and modal
suppression (PROBE-1, 3, 4, 5 and 20); the equation manager (PROBE-2, 6, 7 and 21); `CloseDoc`
closing a dirty copy with no prompt and releasing the file; the teardown on a real re-attach, an
unload from Tools > Add-ins and a SOLIDWORKS exit; whether unrestored toggles persist across
sessions; activating the copy before a dump; the vault read (T139, PROBE-13); the Tools > Options
labels; and what happens when the engineer saves or closes the copy by hand while a plan waits.

## R14. Defaults taken 2026-09-27: the review of the seat adapter's integration

**Sources.** The review of 2026-09-27 of lanes D, E and F integrated (`tasks.md`, "Build order",
the commits up to the one that closed T152), by a safety lens and an invariants lens: eleven
findings, nine of them this feature's. The owner asked on 2026-09-26 to proceed without questions
unless blocked, so each item below is settled by a default. **Each is a default taken 2026-09-27,
the owner may revise; none is the owner's own words, and none is an R12 decision.** SOLIDWORKS was
not started: what each item says a seat does is read from the code and stays a seat item until a
sitting checks it. The two findings that are not this feature's - feature 013's T150 count and its
lever 14 fallback - are answered in that package.

### R14.1 A plan that fails after the open was asked for ends the session it may have left (T175, widened)

**Decision**: *the host* - once `RemodelHost.Plan` has asked the pipeline for the open, a plan that
ends without recording a run (the open refused or failed, or the plan step after it failed: T159's
`CopyNotActive`, the dump's profile check or post-check, `POST /remodel/plan`) closes through the
pipeline's close before the page is answered: `POST /remodel/close` with `discard_copy: false`, so
R13.1's routine, unsaved, deleting nothing - the copy and the run folder stay as the evidence. The
page gets the plan's own refusal unchanged, and a close that fails is swallowed. The
`PreexistingRebuildErrors` paths keep their own close-and-delete, once. *The backend* - `POST
/remodel/open` closes the session the bridge's open made (`remodel.close`, `discard_copy: false`)
when anything after that open answered fails - the source attestation, its write, `remodel.geometry`
or its reading, the open record - before its own error goes back; the close's failure is logged,
the key redacted, and never replaces it.

**Why**: the review found that a Plan failing after the bridge's open left the session running:
the copy open and tagged, all four settings changed, no run for Discard to reach, and every later
`remodel.open` on that attachment refused `run_in_progress`, while the page said to press Remodel a
copy again. Once the open was asked for, the host cannot tell a refused open from one whose backend
steps failed after it or whose reply was lost to the client's 30-second timeout (R14.5, T182); any
session the bridge holds then is one nothing else the host sends will end - planning again closed the
waiting plan's first (R13.4), and in this build no run has started; and a close with no session is
answered `target_mismatch` with no SOLIDWORKS call.
So the host closes on every such failure, and a bridge left holding a session by an earlier failure
is healed the same way. The backend's half keeps its own route whole for any caller: it knows the
bridge's open succeeded.

**Alternatives weighed**: close only after the plan step (T175 as first proposed; not taken: the
backend's own failures after the open and a timed-out open leave the same stuck bridge); delete the
copy, as `PreexistingRebuildErrors` does (not taken: `CopyNotActive`'s words say the copy was not
changed and the run folder is the evidence; a refused plan keeps its folder).

### R14.2 While Start is switched off, a plan holds no session (T176)

**Decision**: while `RemodelStart.SeatValidated` is false, the host ends a plan's session as soon
as the plan is recorded - after the plan step and before the `ready` status and the
`remodel.planned` reply - through the same close: the copy closed unsaved and left in `copy/`,
`plan.json` still `planned`, the folder whole. The plan stays on screen, readable and not lost;
Start is refused `StartNotValidated` as before; Discard deletes `copy/` and sends no close; planning
again sends none for it; and a re-attach or an unload finds no session. A close the bridge answered,
with or without something left, marks the plan so (`RemodelRun.SessionClosedAtPlan`), and what it
left is T167's one status error, through `ToolServiceOptions.RemodelSessionEnded`; a close it could
not answer (`BridgeUnavailable`, or no named refusal) leaves the plan holding its session, so
Discard, planning again, a re-attach or an unload still end it. With Start switched on, a plan keeps
its session for Start, as today.

**Why**: every successful plan left the engineer's four application-wide settings changed for as
long as the plan waited - `CommandInProgress` set, which suppresses SOLIDWORKS' modal boxes, and
"Warn before saving documents with update errors" off, so the engineer could save their own part
with rebuild errors and no warning - while they worked on their own part, since a switch back to
the source re-attaches nothing. No Start can use the session in this build, so holding it bought
nothing. It also takes the copy out of SOLIDWORKS as soon as the plan is made, so the review's two
other findings about a waiting plan cannot happen in this build: the copy becoming the active
document (Open copy, or the copy's window T159 left in front) re-attaches the tool service and
closes the copy under the engineer; and decision 24A's "Nothing was changed" notice posted before a
teardown's failure words.

**Alternatives weighed**: put the settings back at the end of the open and set them again for
Start (not taken now: a contract change for a Start the switch keeps off; it is T180's question);
leave it until the switch is set (not taken: the next sitting runs Plan on real parts with the
switch off, and step 5.3 checks the settings right after it).

**What it leaves open**: with Start switched on a plan must hold its session for Start, and the
three findings return. T180 decides them before T172's switch is set.

### R14.3 A failed open cleans up by the routine's rules and tells the ending (T177)

**Decision**: `remodel.open`'s failure path, once the settings were changed at step 6: the copy
closed unsaved by the routine's clean-up write (the guard asked and the observer told, not counted
by the breaker, so a circuit the failing open opened cannot stop it), the copy deleted whatever the
close did, and all four settings put back - each step attempted whatever the others did, and none of
their failures replaces the refusal the open answers. Then the ending is told to
`BridgeServices.RemodelSessionEnded`, with a new reason, `remodel.open`
(`RemodelSessionEnd.ReasonOpenFailed`), so an unwind that left the copy open or a setting changed
reaches the pane as T167's one status error, and a clean one keeps the pane quiet. `CopyClosed` is
true when no document was opened; `Verified` and `TagRemoved` are false. The routine and the unwind
share one close helper and one put-back helper.

**Why**: the review found the unwind was its own code: a `CloseDoc` that threw skipped the copy's
delete and replaced the refusal, a restore that threw replaced it, `gate.Call` counted the close
against the breaker (and an open circuit refused it outright), and nothing told the pane, so a copy
could be left open and tagged with no session left to close it.

**Alternatives weighed**: run the unwind through `EndRemodelSession` itself (not taken: its
verification needs a scope, which may not exist yet, and the routine never deletes, where a failed
open deletes its copy).

### R14.4 The bridge gates the equation manager (T178)

**Decision**: `remodel.snapshot` and `remodel.equation` reach `IRemodelDocument.Equations` through
the remodel gate under `GetEquationMgr`, the bare key the manifest row names for those two commands
and the probe host gates it under. It is a read, so `RemodelGuard` delegates it; it now appears on
the request's `gated=` line and counts toward the breaker, and `SwRemodelCopyDocument`'s remark that
`VerifyTarget`'s reads are the one ungated path is true.

### R14.5 Recorded and deferred

- **T179 - the teardown reads the seat's own answers.** `tag_removed` is true when `Delete2`
  returned, whatever it answered, and `copy_closed` when `CloseDoc` returned (it returns nothing),
  with no read that the copy is gone. Judging `Delete2`'s answer needs the
  `swCustomInfoDeleteResult_e` values in the manifest's enums, which are regenerated, never typed
  (T181), and confirming the close needs a seat member that asks whether the copy is still open.
  Until then `CopyClosed` means "`CloseDoc` returned", as its own remark says, and the sitting checks
  that `CloseDoc` closes a dirty copy (R13.8).
- **T180 - the held session once Start is switched on**: the settings held while a plan waits, the
  copy becoming the active document tearing the plan down, and 24A's notice posted before the
  teardown's words; and, found while writing T175, a run that saved keeps its session, so the next
  plan's open is refused `run_in_progress` until R14.1's close ends it. Decided before T172's switch
  is set; it blocks that commit.
- **T181 - the manifest's regeneration command and the pane seat's members.** The contract's
  `swreview-extract probe interop --emit-manifest` was never built: the rows are checked field for
  field against the installed assembly by `InstalledAssemblyMatchesManifest`, and `used_by` and
  `note` are written by hand. The pane's own seat (`SwRemodelSeat`: `remodel.open_copy` and T159's
  activation) calls `GetOpenDocumentByName`, `ActivateDoc3`, `get_ActiveDoc`, `GetTitle`,
  `GetPathName` and `OpenDoc7` directly, outside the bridge, by design (`IRemodelSeat`'s remarks: a
  UI action of the add-in, which the bridge's vocabulary deliberately lacks, and which the read-only
  guard would refuse, since `ActivateDoc3` is on its denylist); its members join the manifest, and
  `SwRemodelSeat` the audit, when the command exists. Before T140.
- **T182 - the open route's client timeout.** The add-in's backend client waits 30 seconds on every
  route, `POST /remodel/open` included, while the backend's bridge client waits 60 and the pipe's
  application-thread call 120; a real part's copy, open, rollback, rebuild and signal re-read may
  take longer than 30 seconds. A timed-out open is a failed plan, so R14.1's close follows it, but
  the close waits behind the open on the application thread. The sitting records how long Plan
  takes on a real part (the test plan's step 5.3); the timeout is set from that.

### R14.6 Refuted

- **The pane seat's direct COM calls are not a defect** (the review said so itself): the pane's UI
  actions are the add-in's and have no bridge command by design; what is owed is their record in the
  manifest and the audit, T181.
  *Amended 2026-10-19 (owner decision 144A; feature 011's research R10.4 item 6 and R11.1):* the
  seat stays outside the bridge, but its calls no longer bypass every gate: each action calls
  SOLIDWORKS through a gate of its own, whose guard allows `ISldWorks.ActivateDoc3` and
  `ISldWorks.OpenDoc7` by those keys, refuses every other qualified key and hands every bare name
  to the read-only guard; the seat takes only the run's copy and writes its gate log to the run's
  `remodel.log` (`contracts/guard-allowlist.md`, "The re-modeler's pane seat").
  *Amended 2026-10-20 (owner decision 148A; feature 011's research R12):* the seat's guard is a closed
  allowlist - its two keys and its five reads, nothing else; `remodel.open` and `probe remodel`'s
  reopen call `OpenDoc7` by its qualified key too, the stage-1 allowlist and the probe's guard allowing
  it, and the read-only guard refuses the bare name; both seats take the run's copy by one rule,
  `RemodelCopy.CopyOf`; and Open copy is refused while a remodel run is in progress.

## R15. Defaults taken 2026-09-27: the manifest's regeneration and the teardown's answers (T181, T179)

**Sources.** `tasks.md` T181 and T179, deferred by the review of 2026-09-27 (R14.5). The owner asked
on 2026-09-26 to proceed without questions unless blocked, so each item below is settled by a
default. **Each is a default taken 2026-09-27, the owner may revise; none is the owner's own words,
and none is an R12 decision.** SOLIDWORKS was not started: the reflection below is metadata-only,
over the interop assemblies installed on the development machine (32.5.0.48), and what the
teardown's reads answer on a seat stays a seat item until a sitting checks it.

### R15.1 The rows are regenerated from committed code (T181)

**Decision**: the manifest's *selection* is committed code, in `Rms/RemodelInteropSurface.cs`:
which members, in order, and each one's `used_by`, `allowlisted` and `note` (`Calls`, each call
carrying its `UsedBy` and `Note`); which enum constants, in order (`Constants`); and the absences
with their consequences (`Absences`). `swreview-extract probe interop --emit-manifest <path>
[--force]` reflects the installed `SolidWorks.Interop.sldworks` and `SolidWorks.Interop.swconst`
from the seat's `api\redist` folder - metadata only: types and methods are read, no COM object is
created, and SOLIDWORKS is neither attached to nor started - and writes, beside the selection,
every field reflection answers: each row's `kind` (a `get_` or `set_` special name is a property's
accessor, anything else a method), `arity`, ordered `parameters` with `by_ref`, and `returns`; each
constant's integer; and the two assembly versions. `product` is read from the assembly version,
`SOLIDWORKS {1992 + major} SP{minor}` (32.5 is 2024 SP5; the interop assemblies carry no product
name); `generated_at` is the UTC second the command ran; `generated_by` is the command. The file is
written in the fixture's existing format - two-space indentation, the existing key order, `by_ref`
only when true, a note only when there is one, UTF-8 without a byte-order mark, LF line ends and a
final newline - so a regeneration's diff is only what moved.

It **writes nothing and exits 1**, naming every problem at once, when a selected interface or
member is missing from the installed assembly, a member has more than one overload (the row's one
signature would no longer identify it), a recorded absence is present, an enum or a constant is
missing, or a row has no `used_by`; and when the path exists and `--force` was not given, the path
is a folder, or no redist folder holds both assemblies. It takes no `--doc` and no `--allow-start`,
because it addresses no document and no session. On success it prints the path, the member,
constant and absence counts, and the assembly version and folder it read.

Two tests hold the fixture to the command: `TheFixtureIsWhatTheCommandWrites` (pure, always run)
regenerates from the interop the product is built against with the committed selection and compares
the text with the fixture, `generated_at` aside - so a row typed into the fixture by hand, or a
selection changed without regenerating, fails; and `InstalledAssemblyMatchesManifest` (test B)
still compares every row and constant with the installed interop, now through the command's own
reflection, so the two cannot spell a signature differently. The first regeneration is to leave the
fixture unchanged but for its header; the one row the builder table holds out of the fixture's
order, `IFeatureFolder.GetFeatureCount` (added last at lane B's integration), moves in the table to
the fixture's place.

**Why**: test B could compare every row with reflection but could not produce one, and `used_by`
and `note` were read against nothing; with the selection in code, "regenerated, never typed" is a
test rather than a practice, and a new row is one line of the builder table and one run of the
command. **Alternatives weighed**: regenerate in place from the fixture's own selection (not
taken: a new row would still be typed into the file by hand before the command filled it); a
second committed selection file (not taken: a second list of the keys the builder table already
holds); derive `product` from `SLDWORKS.exe`'s version information (not taken: the command reads
the interop assemblies and nothing else).

### R15.2 The pane seat's rows, and the audit's receivers (T181)

**Decision**:

- **Rows.** `ISldWorks.ActivateDoc3`, `ISldWorks.get_ActiveDoc` and `IModelDoc2.GetTitle` join, none
  allowlisted: the pane's own seat (`SwRemodelSeat`) calls them outside the bridge and its guard, by
  design (R14.6), and a row records a member, it never permits one - `ActivateDoc3` stays on the
  read-only guard's denylist. `used_by` names the pane's commands: `remodel.open_copy` for the
  activation or the reopen, and `remodel.plan` and `remodel.start` for T159's activation before each
  dump. `OpenDoc7` gains `remodel.open_copy`, and its note, cut short at a `|` when it was first
  typed, is completed; `GetOpenDocumentByName` and `GetPathName` gain `remodel.open_copy`,
  `remodel.plan` and `remodel.start`.
  *Amended 2026-10-19 (owner decision 144A):* the seat calls these through a gate of its own now
  (R14.6's amendment); "none allowlisted" stays true of the stage-1 allowlist the manifest's
  column records, and the rows are unchanged.
- **Constants.** `swCustomInfoDeleteResult_e`, all three (`OK = 0`, `NotPresent = 1`,
  `LinkedProp = 2`), because the teardown names each answer (R15.3); and
  `swRebuildOnActivation_e.swDontRebuildActiveDoc = 1`, the constant the pane seat composes, since
  the block carries the constants the code composes.
- **The audit reads the pane seat.** `SwReview.AddIn/Remodel/SwRemodelSeat.cs` joins the files the
  seat adapter audit reads, and `SwRemodelSeat` the classes whose declaring file it must read. A new
  case holds every `sw*_e.member` those files name outside comments to an enum row.
- **The audit checks the interface where the source says it.** A member access's receiver is read
  back from the dot, and its interop interface is known when the receiver is: an identifier every
  declaration of which in the file names the same interop interface (a field, a parameter, a local,
  a pattern or `out` variable, or `var x = ... as T` and `var x = (T)...`); a call to a method the
  file declares with an interop return type; a chain through interop members, each link typed by
  the member's declared return type; or a parenthesized cast, `(T)x` or `x as T`. Its row must then
  be on that interface or one it inherits (the coclass interfaces, `Feature` and the like, inherit
  their `I` interface), and a missing one is reported as `Interface.member`. A receiver it cannot
  read - an identifier declared with two types or none, `var` from anything else, an indexer, a
  generic call - keeps the name-only rule, and an indexed property set is still read as a get.

**Why**: the review recorded the pane seat's members as owed (R14.5, R14.6), and the audit's
blind spot, a name recorded on one interface passing when called on another, is closed wherever the
file itself says the type, which in the seat's own files is nearly everywhere. **Alternatives
weighed**: a C# parser (not taken: the product references none, and the audit's scanner is the one
`DrawingFamilyReadAuditTests` shares); reject any receiver the scan cannot type (not taken: it
would fail on `List<T>.Add` and the adapter's own helpers, which the named exceptions already
answer for).

### R15.3 The teardown judges the tag and the close by what SOLIDWORKS answered (T179)

**Decision**:

- **The tag.** `tag_removed` is true only when `ICustomPropertyManager.Delete2` answered
  `swCustomInfoDeleteResult_OK` (0). `NotPresent`, `LinkedProp` or any other integer leaves it false
  and adds one failure sentence naming the answer by its swconst name, or as not a
  `swCustomInfoDeleteResult_e` value. So such an answer makes `remodel.close` answer
  `close_incomplete`; the page still does not word the tag, since the unsaved close takes it with a
  closed copy and a copy not closed is already said.
- **The close.** `copy_closed` is true only when `CloseDoc` returned **and** a read that follows it
  says SOLIDWORKS has no document open at the copy's path: a new seat member,
  `IRemodelSeat.IsDocumentOpen(copyPath)` (`ISldWorks.GetOpenDocumentByName` answered a document),
  asked only about a copy's path, by `RemodelCopy.RunDirectoryOf`'s rule, as the open and the close
  are. *Amended 2026-10-20 (feature 011, owner decision 148A's review; its research R12.8)*: by
  `RemodelCopy.CopyOf`, the one rule both seats take the run's copy by, for the read, the open and the
  close alike, where the copy folder's name alone took a `..` segment and a device path. The read is a
  clean-up read: the guard asked under the bare key `GetOpenDocumentByName` and
  the observer told, not counted against the breaker, as the clean-up's writes are, so an open
  circuit cannot make every teardown report the copy open. A copy still open is false with a
  sentence that SOLIDWORKS still has it open; a read that throws is unknown, and unknown is not
  closed, with a sentence that it could not be read.
- **The failed open's unwind** (T177) shares the close helper, so its `copy_closed` is confirmed the
  same way, and is still true when no document was opened.
- **The words.** The outcome's fields are unchanged: the teardown line and `remodel.close`'s
  `detail` carry `tag_removed` and `copy_closed` as judged, and the failure sentences carry the
  answers. `remodel.close`'s message says "The copy may still be open" where it said "The copy was
  not closed", which a copy nobody could read might not be. The page's words for a copy not closed
  ("may still be open ... close it without saving") are true of a copy still open and of one nobody
  could read, and are unchanged.

**Why**: a `Delete2` that answered `NotPresent` and a `CloseDoc` that did nothing were reported as
done, and the page stayed quiet about a copy that was still open (R14.5). **Alternatives weighed**:
a new three-valued field for the close (not taken: `remodel.close`'s `detail` and the page's
three-fact seam read a boolean, and unknown is not closed); confirm the close through the copy's own
`GetOpenDocumentIdentity` (not taken: it is `VerifyTarget`'s ungated read on a document that has
just been closed, where the seat's read is gated and asks the application).

### R15.4 A failed open's unwind asks SOLIDWORKS when no document came back (review of 2026-09-27, T183)

**Decision**: the unwind of a `remodel.open` that failed after it changed the settings (T177) no
longer reports the copy closed without asking whenever it holds no document handle. What it does
depends on how far the open got:

- **The copy was never made** (`RemodelCopy.CreateCopy` refused or threw): `OpenDoc7` was never
  called, so nothing was opened; `copy_closed` is true and nothing is asked. A file the byte copy
  refused to overwrite is not the run's, and neither is a document open at its path.
- **The copy exists but no handle came back** - `OpenDoc7` answered null, it or the document's
  wrapper (`SwRemodelCopyDocument`, built after `OpenDoc7` returns) threw, or the gate refused the
  call: SOLIDWORKS may have opened the file anyway. The unwind asks the seat
  (`IRemodelSeat.IsDocumentOpen(copy)`, the clean-up read under `GetOpenDocumentByName`, guarded and
  observed but not counted, as R15.3's confirmation is) whether a document is open at the copy's
  path. None is `copy_closed` true. One is closed unsaved by the same close helper - `CloseDoc`, then
  the confirmation - so its `copy_closed` is judged as every other close is. A read that throws is
  unknown, and unknown is not closed: false, with a sentence that whether SOLIDWORKS opened the copy
  could not be read.
- **A handle came back**: unchanged, the close helper as before.

The copy is deleted after this, as before, whatever it found; the reason the open stopped is still
what is thrown.

**Default taken 2026-09-27, the owner may revise.**

**Why**: `copy_closed = document == null || CloseCopyUnsaved(...)` reported a copy closed with no
`GetOpenDocumentByName` read whenever no handle came back, although everywhere else the teardown is
judged by SOLIDWORKS's answers (R15.3), and a copy left open after a failed open would also make the
delete that follows fail. The copy's path is the run's own folder, just made by a byte copy that
refuses to overwrite, so a document open there can only be the one this open made.

**Alternatives weighed**: close by path without asking (not taken: a `CloseDoc` of nothing is a write
the guard and the log would show for no document, and it still needs the confirmation); ask even
when the copy was never made (not taken: the open was never called, and a document at a path the run
did not create is not the run's to close).

### R15.5 The untag's failure sentence says what is true after a save (review of 2026-09-27, T183)

**Decision**: when `Delete2` does not answer `swCustomInfoDeleteResult_OK`, the failure sentence reads
"untag: Delete2 answered {answer}, so the session tag was not removed from the open copy; the ending
never saves, so the copy on disk carries the tag only if remodel.save saved it there". The fields,
the close attempted whatever the untag answered, and the page's words (which do not word the tag)
are unchanged; the page's reason is restated: the untag reaches only the open document, an unsaved
close discards the tag there, and a copy `remodel.save` saved keeps on disk the tag it was saved
with, whatever the untag answered.

**Default taken 2026-09-27, the owner may revise.**

**Why**: the sentence ended "the copy's close is unsaved, so a closed copy does not keep it", which is
false once `remodel.save` has run - the copy on disk keeps the tag it was saved with
(`contracts/bridge-remodel.md`, `remodel.close`) - and says nothing true when the close then fails.
The new words are true whether or not the run saved and whether or not the close succeeded.

**Alternatives weighed**: record on the session whether `remodel.save` ran and word two sentences
(not taken: new state for one sentence, and the one sentence true in every case says as much);
drop the clause (not taken: an engineer reading "the tag was not removed" should know whether the
file on disk carries it).

## R16. Defaults taken 2026-09-28: the seat packet's U26 and U27, and the review of the follow-up

**Sources.** The sitting of 2026-09-28 (the handoff packet's findings U26 and U27), the follow-up
on `codex/testing-feedback-2026-09-28` (commits `f421225` and `228762c`), and the four reviews of
that follow-up the same day: a read-only-source lens, a crash hunt over the packet's logs and the
2024 API help installed on the development machine, and a general gates lens (the fourth, the
drawing lens, is feature 011's and 013's). The engineer asked for the follow-up to be checked, and
the workflow that checked it settles each finding by a default. **Each item below is a default
taken 2026-09-28, the owner may revise; none is the owner's own words, and none is an R12
decision.** SOLIDWORKS was not started: the API help was read from the installed help files and the
interop metadata was reflected, and what each item says a seat does stays a seat item until the
next sitting checks it (the retest in `docs/history/testing-feedback-2026-09-28.md`).

### R16.1 The copy is measured as a whole part, the proven way (U27, T185)

**Decision**: `remodel.geometry` reads the copy the way the review dump's `PropertyDumper` reads
every part: the copy's selection cleared (`IModelDoc2.ClearSelection2(true)`, allowlisted, behind
`VerifyTarget`), `GetBodies2` for both body counts, the material, the face and edge counts,
`CreateMassProperty2()`, `UseSystemUnits = true`, `Recalculate()` and the getters - and no
`set_AccuracyLevel` and no `set_SelectedItems`. Three guards fail closed: other than one solid body
is counted and not measured (`UnknownError`, `recalculated` false); a volume that is not positive
and finite ends the reading (`UnknownError`, nothing recorded); `Recalculate()` false is unchanged.
`accuracy_level` is `null`. PROBE-8, which still sets both on its throwaway part, hands
`set_SelectedItems` a `DispatchWrapper` array. The phase stamp counts usable readings (status `OK`
and `Recalculate()` true), and `POST /remodel/open` refuses a baseline that is not usable, so a run
never goes on from one.

**Why**: SOLIDWORKS exited after `remodel.open` answered ok and while the backend waited on the
baseline `remodel.geometry` (the packet's logs; the crash hunt's timeline). Of the calls that
reading makes, the whole-part sequence had run on this seat the same sitting (the Model check and
Standards dumps carry the plate's mass and volume), and two had never run on any seat:
`set_AccuracyLevel`, and `set_SelectedItems` - handed a plain `object[]`, which .NET marshals as a
SAFEARRAY of VARIANT (VT 0x200C, measured) where the SOLIDWORKS programming guide ("IDispatch Object
Arrays as Input in .NET") requires `DispatchWrapper`, a SAFEARRAY of IDispatch (0x2009). The cause is
not proven; removing the two unproven calls from the path under investigation, and wrapping the one
that stays, is what the evidence supports. The scope gate already refuses a part with more than one
solid body and the geometry compare already requires a one-body baseline, so the whole part is that
body; the guards keep a whole-part reading from ever standing for anything else. `CreateMassProperty2`'s
remarks say pre-selected bodies are included, and a folder change leaves a selection, hence the
clear. A failed baseline accepted at open would only have surfaced at the end of a run as a subject
mismatch, so it is refused where it happens.

**Alternatives weighed**: keep the selected-body design and only wrap `SelectedItems` (not taken as
the whole answer: the wrapped call is still unproven on a seat, and the whole-part read is proven);
read the selection count and refuse a non-empty one instead of clearing it (not taken: a folder
change legitimately leaves a selection, and clearing is the allowlisted, proven call); split the
reading counter into attempts and usable readings (not needed once open refuses an unusable baseline;
the subject contract is amended instead).

### R16.2 `CommandInProgress` is put back at the end of `remodel.open` (U27, T185; R5.6 amended)

**Decision**: `CommandInProgress` is set with the three dialog toggles at step 6 and put back to its
original value as `remodel.open`'s last step, before the session exists; the three toggles hold for
the session as before. A put-back that fails fails the open, whose unwind tries it again and names
it; the session's end writes it no second time. A change command that needs the flag once PROBE-1
has answered sets it around itself (T180).

**Why**: the API help for `ISldWorks::CommandInProgress`: set it true before a sequence of API calls
and false after, and it affects only out-of-process applications. It was held true for the whole
session - between commands, while SOLIDWORKS processed the copy it had just opened, and through the
baseline reading - and its one stated purpose, PROBE-1's reorder modal, belongs to the change
commands, which Start keeps switched off. T180 already proposed putting settings back at the end of
the open.

**Alternatives weighed**: keep R5.6's session-wide flag (not taken: against the help, and in the
crash window); drop the flag from the open altogether (not taken: the open's own sequence is the
documented use, and dropping it would change the four-setting record every ending reports).

### R16.3 A read-only source's save flag is believed only when SOLIDWORKS can report its edits (U26, T186)

**Decision**: the probe returns `save_flag_dirty: false` only for a source open for writing from a
writable file, or one whose "Don't prompt to save read-only referenced documents" option
(`swExtRefNoPromptOrSave = 15`) reads off; otherwise `null`, and the host refuses before any copy
with `ScopeRefused`, naming the option and the two ways past it (turn it off, or check the part
out). The probe reads `IModelDoc2.IsOpenedReadOnly()` and, when needed,
`ISldWorks.GetUserPreferenceToggle(15)`; a read SOLIDWORKS will not answer is unknown. `remodel.open`
re-checks the same rule with the save flag and refuses `scope_changed` when the flag stopped being
believable. `true` is believed as before.

**Why**: the API help's remark on `IModelDoc2::GetSaveFlag`: it returns true for a model opened
read-only only when that option is not selected (and the model is dirty and visible). Removing the
`DocumentReadOnly` refusal (U26) left `GetSaveFlag` as the only check that the file on disk is the
model on screen (spec.md's edge case), so a checked-in part with unsaved edits could be copied from
disk while that option is on. The seat's setting is not in the packet.

**Alternatives weighed**: restore the `DocumentReadOnly` refusal (not taken: it refuses the seat's
normal case, which is what U26 reported); write the limitation down and allow it (not taken: a
silent copy of the wrong model is the class of wrong answer this feature exists to prevent); a new
error class with its own label (not taken for now: `ScopeRefused` already carries a sentence per
refusal, and the sentence names the fix).

### R16.4 The attestation is re-checked when the copy is closed; the writable copy has its own failure (U26, T186)

**Decision**: `POST /remodel/close`, unless a run is in flight for the folder, and the end of a
failed open re-check a source attestation nothing has re-checked yet and file the verdict; phase D's
verdict is never overwritten. Separately, clearing the copy's read-only attribute is a step of its
own after `File.Copy`: its failure is `copy_failed` ("was made but could not be made writable"), and
the copy is deleted (its attribute cleared first) or the sentence says where it was left.

**Why**: the re-check lived only in phase D, which Start keeps switched off, so every run's
`rechecked_at` and `matches` stayed null - including the crashed run's - and U26's "the source is
unchanged" was never checked at run time. And the attribute clear sat inside the copy's
`IOException` handler, so its failure answered `copy_exists` with a read-only copy left where no
clean-up could delete it; unreachable from the add-in until U26 let read-only sources through.

**Alternatives weighed**: record the source's read-only attribute in the attestation (deferred,
T188: a change to the record both artifacts carry; the seat plan's step 5.3 and the retest read the
attribute before and after instead); re-check at plan time (not taken: the close is the last moment
the run touches the seat, and a plan that waits would re-check too early).

### R16.5 The open's steps, every request, and the document-change fan-out are marked (U27, T185)

**Decision**: every step of `remodel.open` that calls SOLIDWORKS or does file work, and the unwind's
close, delete and put-back, is marked before it starts and after it returns in the bound run folder's
`remodel.log`, through the one helper `remodel.geometry` uses (`RemodelStageMarkers`); every request
gets a begin line before it runs, in the tool-service log and, for a remodel command with a run, in
`remodel.log`; while a remodel plan or run is in flight the add-in's document-change fan-out is
bracketed in `addin.log`. A pipe thread answers anything that escapes a request's answer with an
error line, and a request line the codec cannot even transcode is answered as a line that is not a
request. Each marker is one file append, written before the call it names.

**Why**: the packet could place the exit only between two request boundaries: the build wrote a
request's line after it completed, marked only the geometry calls, and wrote nothing for the fan-out
that ran inside `OpenDoc7`. The tests prove each marker is on disk before its call by reading the
file from inside the fake call. The catch-all closes the one path the crash hunt found where a
managed exception could reach the top of a thread in the SOLIDWORKS process.

### R16.6 Recorded and deferred

- **T187 - overrides and accuracy after PROBE-8.** A whole-part reading honours a mass,
  centre-of-mass or moment override (inferred from the help), which would make those deltas
  meaningless; detecting one adds `GetOverrideOptions` and its casts - never run on a seat in this
  path - to the path under investigation, so it waits for PROBE-8 on a throwaway part with and
  without an override. When PROBE-8 has run, either the reading sets
  `swMassPropertyAccuracyLevel_Higher` again or PROBE-8 calibrates at the default.
- **T188 - smaller follow-ups.** The source's read-only attribute in the attestation (R16.4); the
  fan-out deferring `ActiveConfigurationWatch.Follow` onto a remodel copy while a plan opens it (the
  fan-out finished cleanly in the packet, and it is now logged); a read deadline in the Python named
  pipe transport, which records its 60 s and does not enforce it (documented; the add-in's 120 s
  `InvokeTimeout` is the bound a stuck call meets).
- **T180** gains R16.2's other half: set `CommandInProgress` around the change commands once
  PROBE-1 has answered.

### R16.7 Refuted

- None of the three lenses' findings is refuted. One recommendation is not taken as written: the
  general lens's option A, splitting the reading counter, is not needed once `POST /remodel/open`
  refuses an unusable baseline (R16.1).

### T180 extractor implementation preparation (2026-10-13)

The scoped-settings portion of T180 uses the already proposed default: all four application
settings are restored before Plan becomes idle; validated change/rebuild/save commands capture
and restore the engineer's current values around each sequence. This supersedes the held-dialog
part of R5.6 and R16.2, without claiming a result for native PROBE-1. It adds no allowlist key,
source write, reopening of the source, or change to the geometry profile.

The fake-seat acceptance cases observe the suppressed values inside each actual guarded command,
then the restored idle values, including an idle change after Plan. They cover body failure,
invalid target, invalid Save verdict, unfinished restoration retry/refusal, and suppression failure
reported before any copy exists. The old Open marker/setting sequence expectations change only for
the added idle restore; clean teardown expectations make no redundant writes. Existing teardown
failure cases now first cause a real command restoration to fail, so they still require the same
outstanding-setting names, copy/verification outcomes, failure order, breaker bypass and retry.
The setter begins its pending tracking inside the guarded native call, so a guard refusal never
creates a spurious cleanup failure. A setter that throws is conservatively treated as attempted.

This is implementation preparation on a fake seat. T180's add-in lifecycle half, actual Plan with
source attestation, native blocking-probe verdicts, and the Start enablement decision remain to be
integrated and verified; no enabling flag or task completion is asserted here.

### R17.1 T187 preparation: matching calibration and override protection (2026-10-13)

The whole-part/default reading introduced for U27 is retained. PROBE-8 now uses the same fresh
`CreateMassProperty2` path, clearing selection and setting system units before recalculation,
without accuracy or body-selection setters. Plain readings require readable false override
flags and finite usable quantities before recording attained errors. Mass, centre-of-mass and
principal-moment overrides are then applied independently to each throwaway analytic part; their
known SI values and all setter booleans are checked, and detection/honouring is recorded from a
fresh whole-part reading. The overridden readings never calibrate a tolerance. A complete probe
records a finite differing value as not honoured; unknown flags, values or failed native calls
leave it unresolved. Every analytic part is closed and deleted even on failure, with no save
after fixture overrides.

`remodel.geometry` now checks `GetOverrideOptions` and its three typed Boolean getters before
recalculation or measured getters. Any set flag or unreadable options produce an unusable
reading, and a throwing read remains an error. The probe is the only writer of these overrides;
its seven qualified fixture exemptions do not enter the stage-1 allowlist, and the newly
encountered writers are denied by the read-only guard. The installed interop signatures are
reflected and the frozen manifest regenerated. These are code and fake-test preparations, not
native behavior evidence. T187/T039/T138 and publishing calibration remain pending until the seat
ledger exists and its attained errors meet the gate's bounds. This preparation changes neither
production switch.

## R18. Decision 155A: the Remodel tab's words and its defects before Start is switched on (owner, 2026-10-20)

**Source.** Owner decision 155A ("4A", the register's row 155A), on feature 002 research 149A's owner
question 3 and feature 011 research R12.9 items 4, 8 and 9: "The Remodel tab's words and its defects
before Start is switched on (002 `research.md` 149A's owner question 3; 011 `research.md` R12.9, items 4,
8 and 9), test first: the refusals that show a full path on the tab -
`DocumentDirty`, `ExternalReferences`, `RunNotFound` and the stop when the copy is gone - say it in
plain words with no path; the run report does not count the calls that name no document as writes to
another one; a page that loads again during a run knows the run is in flight and can stop it; and the
copy actions are offered again only once the host is free. The scope gate's signal names stay as they
are." The tasks are T189 to T197 (Phase 10). Everything here is fake-tested on the development machine;
SOLIDWORKS was not started, and only the real `remodel.open` request line (R18.2) was read off the
production chain, over its stand-ins. Three of the four items are reachable only once Start is switched
on (T172); the first is met by every unsaved or referenced part today.

### R18.1 The refusals that named a path, in plain words (T189, T190)

**Where each sentence came from.**

- `DocumentDirty` and `ExternalReferences`: the bridge's. Its probe refuses at its steps 3 and 4
  (`RemodelScopeProbe.Probe`: "'{path}' has unsaved changes. ...", "'{path}' has {n} external file
  reference(s). ..."), on every plan of an unsaved or referenced part, and `remodel.open` refuses the same
  two codes as it reads the part again before the copy (`BridgeDispatcher.RecheckSource`: "'{source}' has
  been edited since the probe and has unsaved changes.", "'{source}' has {n} external file reference(s)
  now."). The backend maps the codes onto the classes with the bridge's sentence (`chat/remodel.py`,
  `BRIDGE_REFUSALS`, `_refusal`), the pipeline carries it through unchanged
  (`BackendRemodelPipeline.Refusal`), and the host posted it twice: in the run line's
  `status {stage: "error"}` (`Plan`'s catch) and in the refusal (`SendRefusal`).
- **Why the add-in's own sentences were never reached.** `RemodelHost.ScopeAllowsARun` refuses the two
  classes from the probe's reply - `save_flag_dirty: true`, a reference count above zero - and the
  bridge's probe never answers either: steps 3 and 4 are protocol conditions, checked and refused before
  step 5 reads the signals and mints a probe (`contracts/bridge-remodel.md`), so a reply that reached the
  host always carried a clean save flag and no references.
- `RunNotFound`: the host's own, in two places - the shared rows' lookup (`PaneRunLookup`'s sentence,
  for `report.open`, `folder.open` and `entity.show`) and `SendRunNotFound` (Start, the result, Open
  copy, Discard copy and Show change) - each naming the run folder the page sent. `remodel.stop`'s own
  ("no remodel run is in flight, so there is nothing to stop.") names none and is unchanged.
- The stop when the copy is gone: the host's own (`RemodelHost.DocumentChanged`), naming the copy's full
  path; a Start's run only.

**Decision: the tab's own sentence for the class, whoever refused.** `RemodelHost.TabWords` maps the two
classes to the host's sentences, and `PageWords` is the one place a failure becomes the page's words -
`SendRefusal`, and the run line's status of a failed probe, open and plan step (and, R18.4, the
executor's). `ScopeAllowsARun` sends the same two constants. Two designs were weighed:

- *Plain words in the backend's mapping*, as decision 149A gave `ScopeRefused`'s two codes
  (`SCOPE_REFUSAL_WORDS`): one mapping where the bridge's codes become the page's classes. But the
  add-in's own sentences for the two classes, which its scope check sends, would stay unreached, and the
  class would have two sentences - or one written twice, in two languages, kept equal by a test. 149A
  needed the backend because `ScopeRefused` carries two codes with two sentences, and only the backend
  sees the code.
- *The host's sentence for the class* - **chosen**, as the instruction asked: prefer reaching the add-in's
  own sentences. One sentence per class serves every refusal under it, and the host can say it from the
  class alone, through any pipeline; the host is already the page's words source for every refusal of
  its own. 149A's `SCOPE_REFUSAL_WORDS` is untouched, and so is the backend: its body keeps the bridge's
  sentence (149A's pins of that stand), which the page never prints. Whoever debugs reads the bridge's
  sentence where it is already written - the tool-service log's line for the refused request
  (`ToolServiceRequestLogger`, `error="..."`), the open's as the probe's: a refused open holds no
  session, and the run's `remodel.log` is written only while a session holds the run's folder
  (`BridgeDispatcher.RemodelRunDirectory`), so the open's line goes to the tool-service log alone
  (corrected on the decision's review, R18.8). No line was added: the host has no log of its own a test
  would not write into the engineer's (`AddInLog`), and the backend's `WARNING` line stays 149A's, for
  the two scope codes. The pipeline's own rule, "the class and the sentence are carried through
  unchanged", still holds: the host words the class, as it words its own refusals.

**The words**, each naming no path, saying what was not done, vouching for the engineer's part alone (the
tab's other refusals of a plan do, `PartNotChanged`), and naming the way on by the button's label where
there is one:

- `DocumentDirtyMessage`: "Your part has unsaved changes, and the re-modeler copies the part as it is
  saved on disk, so nothing was copied and no new plan was made. Your part was not changed. Save it, or
  close it without saving and open it again, then press Remodel a copy again." True of the probe's
  refusal and the open's, both before any copy, and of a read-only part, which can be closed unsaved
  where it cannot be saved.
- `ExternalReferencesMessage`: "This part references other files, which this remodel cannot copy with
  it, so nothing was copied and no new plan was made. Your part was not changed. This version remodels
  only parts that reference no other files." No button: pressing again changes nothing, and breaking the
  references would be a change to the engineer's own part. The count the host's old sentence carried is
  gone; the bridge's refusal carries it in its sentence alone.
- `RunNotFoundMessage`: "This tab no longer has that run, so nothing was done with it. Press Remodel a
  copy to plan again." One sentence for both places; `SendRunNotFound` no longer takes the folder, whose
  one use was the sentence. A host keeps its runs for as long as it lives, so a page naming one it does
  not have shows a run from before it.
- `CopyGoneMessage`: "The copy is gone, so the run is stopping: the change in flight is finished first,
  and the change log stays in the run folder. Your part was not changed. Once the run has ended, press
  Remodel a copy to plan again." Its stage is R18.4's.

The retryable flags are unchanged: the backend's `DocumentDirty` says false and the host's true, and the
Remodel page reads no flag (149A).

**What else the tab can print with a path**, checked, and not changed - the decision names four; each is
for the owner (R18.7): the bridge's `not_a_part` on the probe or the open (a part not on disk, or open as
another type) and `source_not_open`, which has no row and reaches the page as `RunFolderFailed`; the
copy's own refusals inside `remodel.open` (`copy_exists`, `copy_failed`, `open_failed`, the save
target's); the backend's `RunFolderFailed` and `PackageMissing` naming the run folder, and
`copy_path_for`'s; the host's `RunFolderFailed` naming the run root; a pipeline failure's own message in
the run line; `DiscardFailed` and `OpenFailed` carrying an exception's message; the restart gate's
`BackendUnavailable` carrying a restart's failure, which can end in the log's path (150A); and, once
Start is switched on, `POST /remodel/runs`' refusals naming the run folder, and Show change's
`entity.shown {ok: false, message}`, which carries a failure's own message when showing throws
(`PaneActions.ShowPersistRef`) - among them the attach's refusal while a drawing is the active
document, naming the drawing's full path (`SwSession`: "'{path}' is a drawing, which has no
configuration to bind a session to; ...") - added on the decision's review (R18.8).

### R18.2 The run report and calls that name no document (T191, T192)

**What the log holds.** The completed `remodel.open` line, read off the production chain
(`RemodelPlanEndToEndTests`' world: the real dispatcher, gate and recorder over stand-ins), ends
`target=(none)` and nothing else. A mutating call's target is the session's copy
(`BridgeDispatcher.RemodelTargetPath`, the session's scope), and `remodel.open` sets its session only as
it returns, so every allowlisted call it makes records `(none)`: the three toggles and `CommandInProgress`,
`ISldWorks.OpenDoc7`, the copy's tag (`ICustomPropertyManager.Add3`), its rollback
(`IFeatureManager.EditRollback`) and rebuild (`IModelDoc2.ForceRebuild3`), and the settings put back
before it answers. Feature 011's R12.9 item 8 named the toggles and `OpenDoc7`; the tag, the rollback and
the rebuild are writes to the copy that the log cannot attribute. The report read `(none)` as another
target, so it said it "cannot claim" that every write went to the copy on every run.

**Decision: count them apart, as calls naming no document** - R12.9 item 8's second option. The reader
keeps the entry as the log holds it (`read_log_targets`, unchanged), and `_where_the_writes_went` counts
a `NO_TARGET` entry neither as another target (it no longer withdraws the claim) nor as a write on the
copy (the claim's counts are of entries that name a document), and says so after the claim, whenever the
log holds one: "`remodel.log` also records {n} request(s) whose calls name no document (`(none)`): calls
made before the run held its copy, among them the application settings a run changes and the open of the
copy. They are counted apart, as naming no document, and not as writes to another one." The first option,
skipping `(none)` in the reader, would have dropped evidence the report exists to show; the module's rule
is that it never claims from intent and never quietly omits. The words stay true: the settings are the
application's, opening the copy is not a write (the draft constitution amendment, pull request #4), none
of the calls is called a write, and "among them" holds of the tag, rollback and rebuild too. While the
log holds such an entry, the claim's three sentences speak only of the writes, and the mutating
requests, that name a document ("Every write of this run that names a document went to ...", "No write
that names a document was recorded ...", "N of M mutating request(s) in `remodel.log` that name a
document"): the entry's calls include writes - the copy's tag, rollback and rebuild - and the open's
line is a mutating request. With none they read as they did before the decision, so the golden report,
whose log names the copy alone, is unchanged byte for byte (corrected on the decision's review, R18.8,
where T192 had qualified `NO_WRITE_RECORD`'s last clause alone, on every run).

The token is `NO_TARGET`, pinned to `RemodelGateRecorder.NoTarget` read from `ToolServiceHost.cs`, and the
test's line is the real one: `RemodelPlanEndToEndTests.TheOpensRequestLineInTheRunsLogNamesNoDocument`
pins that the open's line still ends `target=(none)`, gating the six allowlisted keys it makes before the
session is held. Only a run writes the report, so this waited for Start.

### R18.3 A page that loads again during a run (T193, T194)

`init.latest_run.running` is true while that run is in flight in this host - from `remodel.started` until
the host is freed from it (R18.4) - which `state`, the plan's, does not say. A page that loads again
starts from `init` alone; `applyInit` now shows such a run running before it renders, as the page that
pressed Start did: the run line says `Running...`, Stop is pressable, and Remodel a copy, Start, Open copy
and Discard copy are not offered, since the host refuses each while the run holds it. The run's terminal
`status` or the answer to Stop ends it, as for any run; an `init` saying no run is in flight never ends a
run the page shows running, so an `init` that crosses the run's end cannot end it early.

- The run in flight is the latest run in this build: a plan cannot be made while a run holds the host,
  and a page sends Start for the run it shows.
- A plan in flight never meets an `init`: a plan holds the host's one message thread, so `ready` waits.
- The flag is the host's `_active`, the run the executor is inside, read under the lock that frees the
  host (R18.4).

### R18.4 A run's ending reaches the page once the host is free (T195, T196)

**What reached the page before the host was free.** The page ends its running state, and offers Open copy
and Discard copy again, on a `status` of `ready` or `error` (`remodel.js`, `showStatus`). While a run held
the host, four things posted one: `Execute`'s two catches, before its `finally` closed the session and
freed the host; the pipeline's own `error` before it answered (`BackendRemodelPipeline`: the backend not
answering a poll, a failed job's error, a job that wrote no state); the words of "When a re-attach or an
unload ends the session" for a close made under the run - `Execute`'s own close, or the run's discard of
its copy on failure - told through `ToolServiceOptions.RemodelSessionEnded` before the close answers; and
the stop when the copy is gone, mid-run. A press in that window was refused `RunInProgress`, and on the
copy-gone stop the page also disabled Stop while the run still finished the change in flight.

**Decision: post the terminal status once the host is free** - the first of the two options the
instruction named - rather than make the page offer the actions only on some new word that the host is
free. The page's rule is the contract's already ("the host posts one of them once phases B to D have
finished"), so holding the host to it keeps the protocol, the page and every page test of a run's end as
they were; a new marker would have to be posted on every ending, the failed hand-over of a Start's run
included, and a run the host forgot to mark would never end on the page.

- `HoldUntilTheHostIsFree` holds a post while a run holds the host (`_active`), in `_heldForTheEnd`, and
  posts at once otherwise. `Execute`'s catches hold their status and their unsolicited `error`;
  `RunReporter.Status` holds the two stages; `PostWhatWasLeft` holds T167's words.
- `Execute` closes the session as before, then frees the host (`FreeTheHostFromTheRun`: the run
  `Finished`, `_active` and `_busy` cleared, and what was held taken, in one step), then tells what was
  held, in the order it was made, then the run's last word, then the answer to Stop. The order of the
  page's messages is the one they had; the freeing moves ahead of them.
- The copy-gone stop is told in `applying`, the stage of the engineer's own Stop ("Stopping: ..."): it is
  a stop, the run goes on to its end, and its terminal status follows once the host is free.
- Start's own failed hand-over posts its status before it frees the host, as before: it is on the host's
  message thread, so a press waits behind it and meets a free host. A plan's statuses are unchanged: no
  run holds the host then, so nothing is held (T176's words still precede `remodel.planned`).

**The lock, and the deadlock it must not cause.** With R18.3, an `init` answered on the message thread
could read the run in flight, the run end on its own thread and tell its ending, and the `init` then be
posted - a page loaded again would show a run that had ended, Stop the only button offered and answered
"no remodel run is in flight". So `SendInit` reads `running`, and posts, under `_endingLock`, the lock the
freeing takes: an `init` that read the run in flight is posted before the ending, or it read that no run
is. Only that is under the lock: `SendInit` reads everything else first, since the active document is
read on SOLIDWORKS' application thread (`SwReviewAddIn.CurrentDocument`, `Invoke`), and that thread takes
the lock when a session's ending is told during a run - a read on it under the lock would hang
SOLIDWORKS. The lock is held to read and write the run's fields, to take the held list, and to post,
which queues the message to the pane and returns.

### R18.5 Tests changed on purpose

- `RemodelHostTests.ARefusalRaisedWhileCopyingIsAnsweredWithItsOwnClass` (T189): its refusal is
  `RunFolderFailed`, a class that keeps its own words, where it was `DocumentDirty`, whose words on the tab
  are now the host's. What it pins - the class passed through, the message as sent, the run folder kept -
  is unchanged.
- `RemodelHostTests.ADocumentChangedWhoseCopyWentAwayAbortsTheRun` (T195): it looks for the stop's own
  status, `CopyGoneMessage` in `applying`, where it looked for an `error` status, which the stop no longer
  posts. The abort it pins is unchanged.
- Three of T191's own cases of `test_remodel_report.py`'s `TestCallsThatNameNoDocument` (T198, on the
  decision's review): `test_a_run_whose_writes_all_went_to_the_copy_still_claims_it`,
  `test_a_write_to_another_path_still_withdraws_the_claim_and_none_is_not_named_as_one` and
  `test_a_log_that_names_no_document_at_all_records_no_write` read the claim's qualified words (R18.2),
  each assertion as strict as it was or stricter. What they pin - the claim made, withdrawn or not
  made, the counts, the sentence on calls that name no document - is unchanged.

No test was loosened. The harness gained two hooks used by the new cases only: `RemodelWorld.WhenPosted`,
run after a message is collected, and `RemodelWorld.Channel`, a channel of a case's own
(`PausingChannel`, which collects under a lock from two threads).

### R18.6 The mutations

Each fix taken out once, by one exact replacement in one file (M22, M23 and M25 by two in one file), in
this worktree: the solution built (or, for the report, nothing to build), the named class run, and the
file restored byte for byte, checked by its sha256. Every mutation is red. M22 to M28 are the review's
(R18.8).

| Id | Taken out | Red |
|---|---|---|
| M1 | `PageWords`: every failure keeps its own message, the tab's words not consulted | 4 cases of 1 test: the probe's and the open's refusals of both classes (`APartRefusalReachesThePageInTheTabsOwnWordsWhoeverRefusedItAndNamesNoPath`) |
| M2 | `DocumentDirty` dropped from `TabWords` | 2 cases of 1 test: the probe's and the open's `DocumentDirty` |
| M3 | `ExternalReferences` dropped from `TabWords` | 2 cases of 1 test: the probe's and the open's `ExternalReferences` |
| M4 | the run line's status of a failed probe back to the failure's own message | 2 cases of 1 test: the probe's, of both classes |
| M5 | the run line's status of a failed open back to the failure's own message | 2 cases of 1 test: the open's, of both classes |
| M6 | `SendRefusal` back to the refusal's own message | 4 cases of 1 test: as M1 |
| M7 | the host's own `DocumentDirty` back to its old sentence | 1 case of 1 test: the host's own reading of the probe |
| M8 | the host's own `ExternalReferences` back to its old sentence | 1 case of 1 test: as M7 |
| M9 | the shared rows' `RunNotFound` back to the sentence naming the folder | 3 cases of 1 test: `report.open`, `folder.open` and `entity.show` (`ARunThisHostDoesNotHaveIsRefusedInPlainWordsThatNameNoPath`) |
| M10 | the host's own `RunNotFound` back to its old words | 5 cases of 1 test: Start, the result, Open copy, Discard copy and Show change |
| M11 | the copy-gone stop back to the sentence naming the copy's path | 3 cases of 3 tests: `TheStopWhenTheCopyIsGoneIsToldInPlainWordsThatNameNoPath`, `TheStopWhenTheCopyIsGoneLeavesThePageRunningUntilTheRunEnds` and `ADocumentChangedWhoseCopyWentAwayAbortsTheRun` |
| P1 | the report counting a `(none)` entry as another target | 4 cases of 4 tests: the class `TestCallsThatNameNoDocument` |
| P2 | the sentence on calls that name no document left out | 4 cases of 4 tests: as P1 |
| P3 | `NO_WRITE_RECORD` back to its old words | 1 case of 1 test: `test_a_log_that_names_no_document_at_all_records_no_write` |
| M12 | `init.latest_run.running` always false | 1 case of 1 test: `AnInitAnsweredWhileTheRunIsInFlightSaysTheLatestRunIsRunning` |
| M13 | the page not reading `running` | 2 cases of 2 tests: `APageLoadedAgainWhileItsRunRunsShowsItRunningAndCanStopIt` and `ARunShownRunningAfterAReloadEndsAtItsTerminalStatus` |
| M14 | the run line left empty for a run shown running after a reload | 1 case of 1 test: `APageLoadedAgainWhileItsRunRunsShowsItRunningAndCanStopIt` |
| M15 | the executor's refusal told at once, before the host is free | 4 cases of 3 tests: the refused ending (`EveryStatusThatEndsTheRunOnThePageIsPostedOnceTheHostIsFree`), `TheExecutorsRefusalIsToldAfterTheHostIsFreeBetweenItsStatusAndTheRunsLastWord` and both presses of `ACopyActionPressedAsSoonAsAFailedRunsEndIsOfferedIsAnswered` |
| M16 | the executor's failure with no named refusal told at once | 1 case of 1 test: the failed ending |
| M17 | the pipeline's own error told at once | 1 case of 1 test: the pipeline's ending |
| M18 | T167's words of a close made under the run told at once | 1 case of 1 test: the close that left something |
| M19 | the copy-gone stop told in `error` again | 2 cases of 2 tests: `TheStopWhenTheCopyIsGoneLeavesThePageRunningUntilTheRunEnds` and `ADocumentChangedWhoseCopyWentAwayAbortsTheRun` |
| M20 | `init`'s reading of a run in flight, and its post, out of the lock | 1 case of 1 test: `AnInitAnsweredAsTheRunEndsIsNeverToldAfterTheEndingThatTheRunIsInFlight` |
| M21 | the freeing handing back nothing of what the ending held | 7 cases of 4 tests: the four endings that hold something, the order of the executor's refusal, and two older cases that read the ending's refusal, `ARefusalRaisedByTheExecutorIsAnsweredWithItsOwnClassAndEndsTheRun` and `AnAfterReadingOfACopyThatCouldNotBeMadeTheActiveDocumentEndsTheRunInTheHostsWords` |
| M22 | the claim never qualified, a `(none)` entry in the log or not | 6 cases of 4 tests: the three of `TestCallsThatNameNoDocument` changed on purpose (R18.5) and the three of `test_no_sentence_speaks_of_every_write_while_the_log_holds_one_that_names_no_document` |
| M23 | the claim always qualified, with no `(none)` entry too | 2 cases of 2 tests: `test_without_one_the_sentences_are_as_they_were` and the golden report, `test_the_whole_report` |
| M24 | a target read past ` failures=`, as before the review | 1 case of 1 test: `test_a_teardown_lines_target_is_read_to_its_failures` |
| M25 | `init`'s active document read under the ending's lock (the review's probe A) | 1 case of 1 test: `AnInitNeverWaitsOnSolidworksThreadWhileItHoldsTheEndingsLock`, failed within its bound rather than hung |
| M26 | what an ending held left in the list once told | 1 case of 1 test: `WhatARunsEndingHeldIsToldOnceAndNotAgainAtTheNextRunsEnd` |
| M27 | every stage of a run held until its end, not only those that end the page's running state | 1 case of 1 test: `TheRunsOtherStagesReachThePageAsTheyArePostedWhileTheRunHoldsTheHost` |
| M28 | `TaskPaneControl.PostToPage` waiting on the pane's thread (`Invoke` for `BeginInvoke`) | 1 case of 1 test: `TaskPaneControlTests.APostFromAnotherThreadIsQueuedAndNeverWaitsOnThePanesThread` |

31 mutations, 72 red results: 24 and 59 before the review, 7 and 13 on it.

The case `AnInitAnsweredAsTheRunEndsIsNeverToldAfterTheEndingThatTheRunIsInFlight` was first written to
look for the run's terminal status from the start of the log, where the plan's own `ready` stood, so its
first red was for that; corrected to look after `remodel.started`, it is red against the host as it was
before T196 (the ten cases of T195) and under M20, which takes the lock out.

### R18.7 Left for the owner

1. **The other messages the tab can print with a path** (R18.1's list): give them plain words too, in the
   backend's mapping or the host's, or leave them - most are failures of the add-in, the backend or the
   disk, whose path is the evidence for whoever reads the message?
   *Settled 2026-10-21 by owner decision 159A ("3A"; R19.3; T208, T209):* every one reaches the tab in plain
   words with no path - the tab's own for each class the review backend answers, and for each failure of the
   host's own - and its own sentence, the evidence, goes to the add-in's log, which View log opens. The
   backend's bodies keep their sentences.
2. **One class, two flags**: `DocumentDirty` is retryable from the host's own check and not from the
   backend's mapping. The page reads no flag; align them, or leave them?
   *Settled 2026-10-21 by owner decision 159A (R19.4; T210, T211):* retryable on every route, the backend's
   mapping made the host's: saving the part makes the same press succeed.
3. **Decision 152A beside this one** (corrected on the decision's review, R18.8, where this item said
   152A's follow at a run's end touched `RemodelHost.Execute`'s `finally`): it does not touch
   `RemodelHost.cs`. 152A's branch (`bridgedoc-152a`) follows the document a hold leaves active through
   the tool-service gate's own poll (`ToolServiceGate.FollowPoll`), so it meets none of this decision's
   changes to `Execute`; the review's trial merge of the two branches was clean, built at zero warnings
   and passed the 672 tests it ran. Nothing waits on it.
4. **A Stop that crosses the run's end** (the review's; older than this decision, whose freeing keeps the
   window as it was). `Stop` reads `_active` and only then stores its id in `_pendingStopId`, while
   `Execute` frees the host and then takes that id to answer it. A Stop that reads the run in flight
   just before the host is freed, and stores its id just after `Execute` has taken it, is not answered at
   that run's end: its "Stopping: ..." status is posted after the run's last word, its id lingers, and
   the next run's end answers it with `remodel.stopped`, carrying that run's count, though no one stopped
   it. Read `_active` and store the id under `_endingLock`, and take the id as the host is freed, so a
   Stop either reaches the run or is refused as having nothing to stop; or leave it - on Stop's side the
   window is a few instructions wide, and only a run opens it?
   *Settled 2026-10-21 by owner decision 159A (R19.1; T204, T205):* a Stop reads the run, stores its id and
   posts its word under `_endingLock`, and the ids are taken as the host is freed, so a Stop reaches its run
   or finds the host free and is answered at once; every Stop that reached the run is answered at its end,
   and the stop when the copy is gone is decided under the same lock.
5. **The run line after a Stop** (the review's; older than this decision). The host answers
   `remodel.stop` with `remodel.stopped` once the executor has finalized, after the run's terminal
   `status`, and the page writes its answer into the run line last ("Stopping. N change(s) applied; the
   change in flight is finished and the artifacts are finalized first."), so a stopped run's line ends on
   "Stopping" over the terminal status's "The run ended 'truncated'. ...". T193's page case
   (`APageLoadedAgainWhileItsRunRunsShowsItRunningAndCanStopIt`) has its stand-in answer Stop at once,
   before any terminal status, an order the host never produces; what it pins - Stop pressable and its
   answer ending the run on the page - holds in either order. Word the answer as the end of the run, or
   leave the line as it is?
   *Settled 2026-10-21 by owner decision 159A (R19.2; T206, T207):* the page lets the run's terminal status
   win - the answer to Stop writes the run line only while no terminal status has ended the run, and an
   `error` that ends a run clears the line - and the page cases' stub answers Stop in the host's order.

**Evidence** (2026-10-20; before at `bd07f29`, after on the branch): the C# build, `--no-incremental`,
at zero warnings both times; `SwReview.Extractor.Tests` 10,059 passed before and after, and
`SwReview.AddIn.Tests` 3,003 before and 3,038 after - the 35 new cases of T189 (17), T191 (1), T193 (7)
and T195 (10) - with the remodel host, page and end-to-end classes, the restart classes and the
stub-children collection, 666 cases, green five times in a row. Python, not live, with
`SWREVIEW_REQUIRE_TOKENIZER=1`: 18,089 passed and 5 skipped before, and 18,095 passed and 5 skipped
after - the six new cases of T191 - on 3.12 (3.12.3) and on 3.11 (3.11.16, `--isolated`) alike.
`ruff check` clean, and no broken link.

### R18.8 The decision's review (T198 to T203)

An independent adversarial review of T189 to T197 found no must-fix: four should-fixes, one older
defect in the report's path, and six nits. Each change was made test first, and each fix, and each
property the new cases pin, was taken out once and was red (R18.6, M22 to M28); the teardown line's
guard pins the log's format, which has no fix of its own to take out.

- **S1, the claim beside calls that name no document** (T198, T199). The code calls a `(none)` entry's
  calls writes - the settings a run changes, and the copy's tag, rollback and rebuild before the run
  holds it - and the open's line is a mutating request, so "No write was recorded", "Every write of this
  run went to" and "N of M mutating request(s)" were untrue beside one: on every run, and most plainly
  on one that ended before its first change. While the log holds such an entry the three sentences
  speak of the writes, and the mutating requests, that name a document (R18.2); with none they read as
  they did, and the golden report is unchanged. 7 cases red before T199, three of them T191's own,
  changed on purpose (R18.5).
- **F11, a teardown line's target** (T200, T201; older than the decision, in the path it changed). The
  report read a line's target up to ` refused=` or ` error=`, the fields a request line writes after
  it, but a teardown line - which a re-attach or an unload writes into the run's `remodel.log`, mid-run
  too - writes ` failures="..."` there, quoted and holding commas. A teardown with failures was read as
  targets of junk, the copy's path run into the failures and split at their commas, and the claim was
  withdrawn on them. `_TARGET` now ends a target at ` failures=` too. The test's line is a real teardown
  line, captured from `ToolServiceWiringTests`' seated world: 1 case red before T201; the guard
  `ToolServiceWiringTests.ATeardownLinePutsOnlyRefusedAndFailuresAfterItsTarget` pins that a teardown
  line writes only those two fields after its target.
- **S2, the ending lock's deadlock** (T202). No test held R18.4's reason for reading the active
  document before taking the lock (the review's probe A).
  `AnInitNeverWaitsOnSolidworksThreadWhileItHoldsTheEndingsLock` plays SOLIDWORKS' application thread
  (`FakeAppThread`): the `init` reads the active document on it and waits, a session's ending is told
  on it once the `init` has asked, and each wait is bounded, so a regression fails rather than hangs.
- **S3, a held ending told once** (T202). `WhatARunsEndingHeldIsToldOnceAndNotAgainAtTheNextRunsEnd`:
  two runs in one host, the first refused by its executor, whose words reach the page once.
- **S4, the run's other stages** (T202).
  `TheRunsOtherStagesReachThePageAsTheyArePostedWhileTheRunHoldsTheHost`: `applying`, `verifying` and
  `saving` reach the page while the run holds the host, ahead of the progress posted after them; only
  `ready` and `error` wait for its end.
- **N5, a post never waits on the pane's thread** (T202). The ending's lock is held while posting,
  which is safe only because a post is queued: `IPageChannel` now says a post never waits on the
  pane's thread, SOLIDWORKS' application thread, and `TaskPaneControl.PostToPage`'s `BeginInvoke`
  says why. `TaskPaneControlTests.APostFromAnotherThreadIsQueuedAndNeverWaitsOnThePanesThread` posts
  to every channel from another thread while the pane's thread waits for it.
- **N6** (T203). The `status` row of `contracts/pane-remodel-messages.md` and feature 011 research R12.9
  item 4's note said no `ready` or `error` is posted while a run holds the host; one is, as R18.4 said:
  Start's failed hand-over posts its `error` before it frees the host, on the host's message thread,
  where a press waits behind it and meets a free host. Both now name it.
- **N7** (T203). R18.1 said the open's refusal is kept in the run's `remodel.log`; a refused open holds
  no session, so its line goes to the tool-service log alone. Corrected.
- **N8** (T203). R18.7 item 3 said decision 152A's follow touched `Execute`'s `finally`; 152A does not
  touch `RemodelHost.cs`. Corrected.
- **N9** (T203). R18.1's list of what else the tab can print with a path missed Show change's
  `entity.shown {ok: false, message}`. Added.
- **N10** (T202). `RemodelHostTests`' section header for decision 145A's cases, lost when this
  decision's cases went in above it, is restored.
- **For the owner, no change**: two defects older than the decision, R18.7 items 4 and 5.

**Evidence** (2026-10-20, on the branch): the C# build, `--no-incremental`, at zero warnings after every
mutation was restored; `SwReview.Extractor.Tests` 10,059 passed, and `SwReview.AddIn.Tests` 3,043,
where it was 3,038 before the review - the five new cases of T200 (1) and T202 (4) - with the remodel
host, page and end-to-end classes, the restart classes, the stub-children collection,
`TaskPaneControlTests` and `ToolServiceWiringTests`, 778 cases, green five times in a row.
Python, not live, with `SWREVIEW_REQUIRE_TOKENIZER=1`, the files the review touched or that read what
it touched - `test_remodel_report.py` (with T198's 4 new cases and T200's 1),
`test_remodel_apply_log.py`, `test_chat_remodel_routes.py`, `test_workstation_test_plan.py`,
`test_workstation_handover.py`, `test_committable_paths.py` and `test_remodel_flow.py`: 526 passed on
3.12 (3.12.3) and on 3.11 (3.11.16, `--isolated`) alike. `ruff check` clean, and no broken link.

## R19. Decision 159A: the Remodel tab's remaining defects before Start is switched on (owner, 2026-10-21)

**Source.** Owner decision 159A ("3A", the register's row 159A), on R18.7 and feature 002 research 152A's owner
question 3: "The Remodel tab's remaining defects before Start is switched on (004 `research.md` R18.7; 002
`research.md` 152A's question 3), test first, with adversarial reviews: the Stop id race, the run line after
Stop, the other messages that can carry a path, `DocumentDirty`'s retry flag differing by route, and the look
after a plan following into the copy its close left open - so switching Start on (004 T172) waits on no known
defect." The tasks are T204 to T214 (Phase 11). Everything here is fake-tested on the development machine;
SOLIDWORKS was not started. R18.7 item 3, decision 152A beside 155A, asked for nothing.

### R19.1 A Stop and the run's end, decided under one lock (T204, T205)

**What was wrong** (R18.7 item 4). `Stop` read `_active` and only then stored its id in `_pendingStopId`,
while `Execute` freed the host and then took that id to answer it. A Stop that read the run in flight just
before the host was freed, and stored its id just after `Execute` had taken it, was not answered at that run's
end: its "Stopping: ..." was posted after the run's last word, and its id lingered for the next run's end to
answer with `remodel.stopped` and that run's count. Two more were found writing T204: a second Stop during one
run replaced the first's id, so the first was never answered and the page kept waiting on it; and the stop when
the copy goes away (RK-14) was decided and told outside any lock, so it too could be told after the run's last
word.

**Decision: a Stop is decided under the lock that frees the host** - the first of the two fixes the instruction
named. `Stop` reads `_active`, adds its id to `_pendingStops` and posts its word under `_endingLock` (R18.4);
`FreeTheHostFromTheRun` takes the ids in the step that frees the host; and `Execute` answers each at the run's
end, after its last word, as before. So a Stop either reaches the run - its word told before the run's end, its
id answered at that end - or finds the host free and is answered at once, `RunNotFound` ("no remodel run is in
flight, so there is nothing to stop."), storing nothing. The copy-gone stop is decided and told under the same
lock, the copy looked for there too.

- *Keyed to the run instead*, the other fix named: a Stop that stored its id on a run that had just ended would
  never be answered unless it then asked whether the run had ended - a second reading of the fact the lock
  decides once, and the lock is the one the freeing already takes.
- *Every Stop answered.* Stop stays pressable until the run ends (`remodel.js`, `renderControls`), and each
  `remodel.stop` the page sends waits for its own answer. A run stopped only because its copy went away is
  answered unasked, `remodel.stopped` with no id, as before.
- *The ids taken as the host is freed*, where they were taken after the run's last word: once a Stop is decided
  under the lock the two are the same - a Stop after the freeing finds the host free - so this is one step for
  the reader, not a fix, and has no mutation of its own.
- *What waits under the lock.* A post queues the message and returns (R18.8, N5); the masking reads the keys and
  the remodel secret (`KeysToMask`, a DPAPI decryption, and the gate's record under its own lock, which is never
  held while anything is waited for); and `File.Exists` reads the copy in the run folder, under a local run root
  (owner decision 154A). Nothing waits on SOLIDWORKS' application thread, which takes the lock to tell a
  session's ending (R18.4) and now to decide the copy-gone stop.

**Tests** (T204). The run on a thread of its own, and the stop's word held in its post - on the page's thread,
or SOLIDWORKS' for the copy-gone stop - while the run reaches its end: before T205 the run's end was told first
and the stop's word after it; with the lock the end waits for the word. A double Stop, both answered at the
run's end and neither at the next run's. And a guard: a Stop pressed the moment the run's last word reaches the
page is answered at once and stores nothing, before and after. The old `Stop`'s gap between its read and its
store has no seam a test can hold open; T204 holds the stop's post instead, which the same lock orders against
the freeing, and the mutation that takes the lock out is red under it (R19.7, S1).

### R19.2 The run line after a Stop (T206, T207)

**What was wrong** (R18.7 item 5). The host answers `remodel.stop` with `remodel.stopped` once the executor has
finalized, after the run's terminal `status` (R18.4), and the page wrote that answer into the run line last:
"Stopping. N change(s) applied; the change in flight is finished and the artifacts are finalized first." over
the run's last word, "The run ended 'truncated'. ...". A stopped run that ended in `error` kept a "Stopping"
line either way: the page's `error` branch shows the banner and leaves the run line alone, so the line kept the
answer's words, or the host's own "Stopping: ..." posted as the Stop reached the run.

**Decision: the page lets the terminal status win** - the second of the two options - rather than the host
posting the answer ahead of the run's last word.

- The host's order is the contract's: the answer once the executor has finalized, the terminal `status` once
  the host is free (R18.4), and every host test of a run's end pins it (R18.6, M21). The page ends its running
  state on `ready` and `error`; an answer ordered first would end it instead.
- Ordering the host alone would not have done: a run that ends in `error` would still have left the Stop's
  "Stopping: ..." in the line, since the page's `error` branch did not touch it. The page had to change either
  way, so the change is made there alone, and the protocol is as it was.
- So the answer to Stop writes the run line, and ends the run, only while no terminal status has ended it -
  which this host never leaves to it, and on which the page does not depend - and an `error` that ends a run
  clears the run line, the banner saying how it ended, as a refused plan or Start leaves it. A `ready` that ends
  a run writes its words, as before; an `error` while no run is running - a plan's, a teardown's, the add-in's
  word on the backend - leaves the line as it was.

**Tests** (T206). The real page over the real transport, the stub posting in the order the host uses - the
Stop's word, the run's last word, then the answer - for a run that ends `ready` and one that ends `error`: before
T207 the line ended "Stopping. 2 change(s) applied ...". The stub answered Stop at once before 159A, an order the
host never produces (R18.7 item 5); it now answers in the host's order for every page case (R19.6).

### R19.3 The other messages that can carry a path (T208, T209)

**Where each came from** (R18.1's list, R18.7 item 1), checked again by route:

- *The review backend's refusals*, which the pipeline hands on with their class and sentence
  (`BackendRemodelPipeline.Refusal`) and the host printed as they came: the bridge's `not_a_part` (`NotAPart`)
  and `source_not_open` (no row, so `RunFolderFailed`), naming the part's full path; the copy's own refusals
  inside `remodel.open` (`copy_exists`, `copy_failed`, `tag_failed`, `open_failed` and the save target's, all
  `RunFolderFailed`), naming the copy's; `RunFolderFailed` and `PackageMissing` naming the run folder (the open
  record, the dump, the waivers' carry-forward, `copy_path_for`); `POST /remodel/runs`' `RunNotPlanned`,
  `ResumeRefused` and `RunInProgress`, naming the run folder; `PackageAfterRefused` and `InvalidRunDir`, naming
  both of their paths; and `BridgeUnavailable`, whose detail is the reviewer's bridge client's, naming the
  bridge's pipe (`the bridge on \\.\pipe\... could not be reached`).
- *The run's failure in the run line*: the pipeline's `status {stage: "error"}` with a poll's failure or a failed
  job's error (`RemodelJob.fail`, the text of whatever the run raised).
- *The host's own*: `RunFolderFailed` naming the run root and carrying the disk's refusal; `HostError` with any
  exception's message - the pipeline's refusal of a dump that read another document names the package's path,
  and `SwSession` refuses to attach to a drawing naming it; `OpenFailed` with the seat's sentence, naming the
  copy; `DiscardFailed` with the disk's refusal, naming the copy's file or `plan.json`'s full path; and the
  unanswered closes of an earlier plan and of a run, each ending with the failure's message.
- *The restart gate's* `BackendUnavailable` with a restart's failure, which can end in the backend's log's path
  (decision 150A), and the add-in's word that the backend did not start, `status {stage: "error", lifecycle:
  true}`, with the same failure.
- *The shared rows*: Show change's `entity.shown {ok: false, message}` with whatever showing threw
  (`PaneActions.ShowPersistRef`), `SwSession`'s refusal of a drawing among it; and the `OpenFailed` of View log,
  Open report and Open run folder with the failure's message - the log folder's own path when it cannot be made.

**Decision: the host words every one; the backend is unchanged.** The host is the page's words source (R18.1):
every failure the page can print passes through it, so one rule there covers every route, the add-in's own
failures and the backend's alike, and a sentence written anywhere upstream later cannot reach the page unworded.

- *A refusal the review backend answered* - the pipeline keeps the backend's answer as the refusal's cause,
  which T208 pins - is told in the tab's words for its class (`PageWords`): `NotAPart`, `BridgeUnavailable` and
  `BackendUnavailable` have their own, since their ways on differ (save the part as a part; wait a moment; wait
  for the backend); `ScopeRefused` keeps the backend's own, which name no path (owner decision 149A); 155A's two
  keep theirs; and every other class - the rest of `contracts/backend-remodel.md`'s error table, `InvalidRunDir`,
  `InvalidRequest`, and the client's `HttpError` and `BadResponse` - shares one sentence, true of every step it
  can stop, before any change to a copy or during a run, whose last word follows. A refusal the add-in raised
  itself keeps its own words, which name no path; any other failure is told in `UnexpectedFailureMessage`, its
  class `HostError` as before.
- *The host's own sites* each have a sentence of their own: the run folder not made, the unanswered closes of an
  earlier plan and of a run, Open copy, the two Discard failures, the gate's restart, the backend that did not
  start, the run's failure in the run line, Show, and Windows not opening a file or the log folder.
- *What a failure said goes to a log, never the tab*: `RemodelHostOptions.Log`, which the add-in wires to
  `AddInLog.Write` (`addin.log`, in the folder View log opens), each line masked as the page's messages are
  (FR-015) and naming what was asked and the refusal's class and sentence, or the whole of an exception. R18.1
  found the host had no log a test would not write into the engineer's; the option is nowhere by default, so no
  test does. The tab's words send whoever needs the sentence there by the button's label: "Press View log to
  see why."
- *Plain words in the backend's mapping*, 149A's way, were weighed. The backend sees the bridge's code and could
  word each, but its remodel routes raise some twenty sentences that can name a path, the add-in's own failures
  would still need the host's words, and the tab's words would live in two places and two languages. The class
  is enough for the engineer's way on; the code reaches the log with the sentence. The backend's bodies keep
  their sentences, for the log.
- *The gate's* `BackendUnavailable`: the review host answers the gate's refusals in words for this tab, and the
  one that can name a path, a restart's failure, is a retryable `BackendUnavailable`, as is the one for a backend
  that does not answer whether a turn runs. Both leave the backend not restarted with the saved settings, so the
  host words every retryable `BackendUnavailable` from the gate as that (`BackendNotRestartedMessage`) and keeps
  the gate's other refusals - a turn, a remodel run in flight, the add-in unloading - as the review host words
  them. Telling the restart's failure apart would have meant changing the review host's gate, which decision 157A
  changes in parallel, or carrying the raw failure across as the refusal's cause, an unmasked text that can
  quote the key.
- *The shared rows*: `PaneActionsOptions.FailureWords`, given the row and the failure; its message by default,
  so every other tab is as it was (`PaneActionsTests`), and the Remodel host's words, which log the failure.
- *Not changed, by design*: the run's data the page shows as recorded - the active document and the run folder
  in its header, the attestation's source path, a change record's `target_path` and `error` - and `init`,
  `document.changed` and `remodel.planned` naming them. They are not a failure's sentence, and the page names them
  on purpose (R18.1's `AssertNoPathWasPosted` leaves them out too).

**The words** (`RemodelHost`), each naming no path, no command and none of the build's plumbing, saying what was
not done, that the engineer's part was not changed where a plan, a run or a copy action was asked for, and the
way on, by the button's label where there is one:

- `UnexpectedFailureMessage`: "The add-in met a failure it did not expect, so what was asked was not done. Your
  part was not changed. Press View log to see why."
- `NotAPartOnDiskMessage`: "The active document is not a part file the re-modeler can find where SOLIDWORKS
  opened it from - it may have been moved, renamed or deleted since - so nothing was copied and no new plan was
  made. Your part was not changed. Save it as a part, then press Remodel a copy again." The bridge refuses
  `not_a_part` at the probe and as it reads the part again before the copy, so "nothing was copied" holds; this
  host's own `NotAPart`, for an assembly or a drawing, keeps its words.
- `BridgeNotAnsweringMessage`: "SOLIDWORKS did not answer the re-modeler, so it stopped. Your part was not
  changed. Wait a moment, then press Remodel a copy again."
- `BackendNotAnsweringMessage`: "The review backend did not answer, so the re-modeler stopped. Your part was not
  changed. Wait for the backend to be ready, then press Remodel a copy again."
- `BackendFailedMessage`: "The review backend could not do a step of this remodel, so it stopped. Your part was
  not changed. Press View log to see why, then press Remodel a copy to plan again." Also the run line's word for
  the run's own failure, which the run's last word follows.
- `RunFolderNotMadeMessage`: "The run folder could not be made under the run root, so nothing was copied and no
  new plan was made. Your part was not changed. Press View log to see why; if the run root cannot be written to,
  choose a local folder for runs in Settings on the Review tab, then press Remodel a copy again."
- `EarlierPlanNotClosedMessage`: "SOLIDWORKS did not answer the close of the earlier plan, so that plan is left as
  it was and no new plan was made. Your part was not changed. Wait a moment, then press Remodel a copy again."
- `RunCloseNotAnsweredMessage`: "The run ended, but SOLIDWORKS did not answer its close, so the copy may still be
  open; the report and the saved artifacts are kept. Your part was not changed. Press View log to see why."
  *Reworded 2026-10-21 on the decision's review (R19.9, M6), with the one above:* a close that never reached the
  bridge is not answered either, so neither says who did not answer: "Closing the earlier plan's copy was not
  confirmed, so that plan is left as it was ..." and "The run ended, but closing its copy was not confirmed, so the
  copy may still be open in SOLIDWORKS; ...", the rest as it was.
- `OpenCopyFailedMessage`: "SOLIDWORKS did not open the copy, so nothing was opened. Your part was not changed.
  Press View log to see why, then press Open copy again."
- `DiscardCopyFailedMessage`: "The copy could not be deleted, so it is still in the run folder; SOLIDWORKS may
  still have it open. Your part was not changed. Close the copy in SOLIDWORKS without saving, then press Discard
  copy again. Press View log to see why."
- `DiscardStateNotWrittenMessage`: "The copy was deleted, but 'discarded' could not be written to plan.json, so
  this tab would go on reporting the state the run ended in. Your part was not changed. Press View log to see
  why."
- `BackendNotRestartedMessage`: "The review backend has not restarted with the saved settings, so nothing was
  done. Your part was not changed. Save the settings again on the Review tab to restart it, then try again. Press
  View log to see why." "Try again", since a plan and a Start both meet it.
- `BackendDidNotStartMessage`: "The review backend did not start, so this tab cannot plan or run. The Review tab
  says why. Save Settings on the Review tab to start it again." - the way on is 150A's
  (`ReviewHost.StartItAgainOnTheReviewTab`), and the Review tab shows the failure whole.
- `ShowFailedMessage`: "SOLIDWORKS could not show this, so nothing was selected. Press View log to see why."
- `NotOpenedMessage`: "Windows could not open it, so nothing was opened. Press View log to see why."
- `LogFolderNotOpenedMessage`: "Windows could not open the log folder, so nothing was opened." No View log: it is
  the log's own folder that could not be made, and nothing could be written there either.

**Tests** (T208). The theory `AFailureThatCanNameAPathReachesTheTabInItsOwnWordsAndItsSentenceGoesToTheLog`
drives 23 routes, each failure's sentence carrying a fictional drive-letter path, run folder, pipe or log, and
asserts the tab's words where the page shows them, that no sentence the page can print names a path - a drive
letter's root, or the two separators a share or a pipe begins with - and that the sentence is in the host's
log. `EveryClassTheBackendAnswersReachesTheTabInWordsThatNameNoPath` sweeps every class of
`contracts/backend-remodel.md`'s error table, read from the contract, and the five more the routes and the
client raise. The 22 routes first written were red before T209, and every class of the sweep but `ScopeRefused`,
whose words were the backend's own and plain. The sentences are pinned word for word and plain, and name their
buttons by the labels read from the page; the pipeline's keeping the backend's answer as the cause is pinned on
its three routes (a guard); and the add-in hands the host its log. Three tests were written while planning the
mutations (R19.7), each where what it pins had no test: the log is masked (red under W22); the 23rd route, View
log when Windows does not open the log folder, whose refusal can name it (red under W18, W24, W26 and W30); and
the guard `AGateRefusalThatIsNotTheRestartsKeepsTheReviewHostsWords`, the restart gate's refusals but its
retryable `BackendUnavailable` - a remodel run in flight, the add-in unloading - in the review host's words, a
turn's being pinned already (red under W28 and W29). On net48, `Directory.Delete`'s refusal names the file and not
its folder, so the Discard route's sentence names the copy's file.

### R19.4 One class, one flag (T210, T211)

R18.7 item 2: `DocumentDirty` was retryable from the host's own check of the probe's signals and not from the
backend's mapping of the bridge's `source_dirty`. **Retryable is the true value**: saving the part, or closing it
unsaved and opening it again, makes the same press succeed. The backend's `DocumentDirty` is now retryable
(`chat/remodel.py`); the host's own already was. `test_chat_remodel_routes.py` pins it on the probe and the open,
red before T211, and keeps `ExternalReferences` not retryable on both - pressing again changes nothing - as a
guard; on the add-in's side a guard pins its own route and the backend's flag passed on as it is given. The page
reads no flag today.

### R19.5 The look after a plan that follows into the copy its close left open (T212, T213)

**What was asked** (002 research 152A's owner question 3, from its review's R5). With Start switched off, the
shipped build, a plan closes its session before it answers (T176), so no held copy keeps the tool service's
attachment (T180), and the look once the plan ends (152A) follows whatever the plan's close left active: the
engineer's part, normally, which is the document attached to; or the copy, when the close left it open and
active - the close's words then say so (T167: "The copy may still be open in SOLIDWORKS ... close it without
saving") - which the tool service follows, a re-attach, and the re-attach told the plan lost, in words that say
SOLIDWORKS switched documents. Should the look follow into the copy, and should such a plan be told lost?

**Weighed**:

- *The plan's close restores the source as active.* The re-modeler would take a handle to the engineer's part to
  activate it, where the source leaves the host once, as the source of a filesystem copy, and is unreachable
  rather than untargeted - the property the constitution's re-modeler exception rests on - and the guard would
  need a call on the source that no allowlist has. And the copy would stay open behind it. Not safe.
- *The follow skips the copy.* The tool service would stay on the engineer's part while the copy is active: the
  bridge left on another document, the state 152A exists to end. A review of the copy would be refused
  `BridgeOnAnotherDocument` for as long as the copy is active, in words that say to wait a moment (152A's N6,
  reachable in the shipped build for the first time); and T180 and 152A's V12 pin that a plan closed at the plan
  keeps no attachment, since preserving one is for a session a Start can use. Skipping every re-modeler copy
  (`IsRemodelCopy`) would be wider still: Show change resolves through the tool service's session, so after Open
  copy it would resolve a run's changes against the engineer's part.
- *The follow kept, and the plan not told lost* - **chosen**. The tool service follows the document SOLIDWORKS has
  active, the copy included, by 152A's one rule; nothing of the source is reached; a review of the copy is the
  engineer's to make, and Remodel a copy refuses the copy as a source (`SourceIsRemodelCopy`). And a re-attach
  loses a plan by taking the session it holds: a plan the host closed at the plan holds none, so neither a
  re-attach nor a teardown takes anything from it, and no Start can use it in this build either way - Start
  answers `StartNotValidated` before `SessionLost`. The notice's words, that the plan was made before SOLIDWORKS
  switched documents and so can no longer be started, gave a cause that is not one. `RemodelRun`'s own record
  already said a plan closed at the plan "is not lost, since nothing it needs went away"; `IsLostPlan` now agrees
  for a re-attach too.

**What changes**: `IsLostPlan` - the notice's and `init.latest_run.plan_lost`'s one rule - no longer counts a
re-attach or a teardown against a plan closed at the plan. Planning again, which sets a plan aside, still tells it
(T173), and so does a re-attach for a plan whose close the bridge could not answer, which keeps its session
(T176). With Start switched on no plan is closed at the plan, so nothing changes there. After a plan whose close
left the copy active, the page shows the close's words in its banner and the plan as planned; the tool service
follows the copy, and follows the engineer's part again once the copy is closed, telling nothing either time.

**Tests** (T212): through the real gate, the look into the copy the close left active, and an ordinary switch to
another part, both telling nothing and `init` saying nothing is lost - red before T213 - and a guard of a plan
whose close was not answered, still told lost. 152A's R5 theory now pins the follow as well (R19.6).

### R19.6 Tests changed on purpose

Each still pins what it pinned; where it pinned a failure's own sentence, it pins the tab's words and that the
sentence is in the host's log.

- `RemodelPageContractTests.HostStub` answers `remodel.stop` in the host's order - the Stop's word, the run's last
  word (`StopEndsWith`), then the answer - where it answered at once, an order the host never produces (R18.7
  item 5); `APageLoadedAgainWhileItsRunRunsShowsItRunningAndCanStopIt`'s summary says so, and it is green in both.
- `RemodelHostTests.EveryStatusThatEndsTheRunOnThePageIsPostedOnceTheHostIsFree`: its "failed" and "pipeline"
  endings look for `UnexpectedFailureMessage` and `BackendFailedMessage` where they looked for the failure's own
  sentence; the order and the moment it pins are unchanged.
- `RemodelHostTests.APlanWhoseStepFailsAfterTheCopyExistsClosesItsSessionOnceAndAnswersItsOwnRefusal`: its
  `HostError` case, a dump that names no document, looks for `UnexpectedFailureMessage`.
- `RemodelHostTests.ACloseThatFailedWithoutANamedRefusalCountsAsUnanswered`: `EarlierPlanNotClosedMessage`, where
  it looked for the close's own message in the refusal.
- `RemodelHostTests.AStartThatFailsAfterTheGateLeavesTheHostFree`: its scheduler case looks for
  `UnexpectedFailureMessage` in the run line's `error`.
- `RemodelHostTests.AStartTheRestartGateRefusesIsAnsweredWithItsRefusalAndTheRunNeverStarts`: the gate's
  retryable `BackendUnavailable` in `BackendNotRestartedMessage`, and its flag pinned too.
- `OtherTabsBackendRestartTests.EachOtherTabsHostMarksTheBackendsOwnWordAndNothingElse`: for the Remodel tab the
  message is `BackendDidNotStartMessage`; the mark, and the other tabs' words, are unchanged.
- `RemodelHostTests.ThroughTheGateWithStartSwitchedOffTheLookFollowsWhatThePlansCloseLeftActive` (152A's R5):
  no plan lost where the copy was left active, where it pinned one, and the document the tool service follows,
  which it did not pin.
- `RemodelPlanEndToEndTests.AToolServiceThatStopsWhileAPlanWaitsFindsNoSessionAndThePageHearsOnlyThatThePlanIsLost`
  is renamed `...AndThePageHearsNothingOfIt`: no plan lost, where it pinned one; the teardown's finding no
  session, no SOLIDWORKS call and no failure told are unchanged.

No test was loosened. The harness gained what the new cases use: `RemodelWorld.Logged` (the host's log),
`RemodelWorld.Root`, a settable `LogFolder`, `FakeResolver.Failure`, `RecordingOpener.Failure`, and
`HostStub.StopEndsWith`.

### R19.7 The mutations

Each fix taken out once, by one exact replacement in one file, in this worktree: the solution built (for P1,
nothing to build), the named classes run - `RemodelHostTests`, `RemodelPlanEndToEndTests`, `RemodelWiringTests`,
`BackendRemodelPipelineTests`, `OtherTabsBackendRestartTests` and `PaneActionsTests`; `RemodelPageContractTests`
(52 cases) for L1 and L2; `test_chat_remodel_routes.py` (100) for P1 - and the file restored byte for byte, checked
by its sha256. Every mutation is red. S1 to S3, L1, L2, W1 to W23, F1 and P1 ran twice, the same each time, with
578 cases in the host's classes, `WhatTheLogKeepsIsMasked` among them. Reading every changed line against them
then found fixes no mutation had taken out, and two properties no test pinned (R19.3): S4 and W24 to W30 ran once
the three cases pinning those were in, with 581, and so did W18 and W21 again, whose red the new route adds to (4
and 44 cases before it).

| Id | Taken out | Red |
|---|---|---|
| S1 | `Stop` deciding and telling outside `_endingLock` | 1 case of 1 test: `AStopTheRunsEndMeetsIsToldBeforeThatEndAndAnsweredAtIt` |
| S2 | a second Stop replacing the first's id (`_pendingStops` cleared before the add) | 1 case of 1 test: `EveryStopThatReachesARunIsAnsweredOnceAtItsEndAndNotAtTheNextRunsEnd` |
| S3 | the copy-gone stop decided and told outside the lock | 1 case of 1 test: `TheStopWhenTheCopyIsGoneThatTheRunsEndMeetsIsToldBeforeThatEnd` |
| S4 | a run stopped by a press answered unasked as well | 2 cases of 2 tests: S1's and S2's |
| L1 | the answer to Stop writing the run line whether or not the run has ended | 2 cases of 1 test: `AStoppedRunsLineEndsOnTheRunsEndAndNotOnTheAnswerToStop`, ending `ready` and `error` |
| L2 | an `error` that ends a run leaving the run line as it was | 1 case of 1 test: the same, ending `error` |
| W1 | `TheBackendAnswered` always false: a refusal the backend answered keeping its own sentence | 23 cases of 3 tests: the seven routes of a refusal the backend answered (`AFailureThatCanNameAPathReachesTheTabInItsOwnWordsAndItsSentenceGoesToTheLog`), the fifteen classes with no words of 155A's or 149A's (`EveryClassTheBackendAnswersReachesTheTabInWordsThatNameNoPath`) and `WhatTheLogKeepsIsMasked` |
| W2 | `NotAPart` dropped from `BackendWords` | 2 cases of 2 tests: the bridge's `not_a_part` route and the class |
| W3 | `BridgeUnavailable` dropped from `BackendWords` | 2 cases of 2 tests: SOLIDWORKS not answering the probe, and the class |
| W4 | `BackendUnavailable` dropped from `BackendWords` | 2 cases of 2 tests: the backend not answering the open, and the class |
| W5 | `ScopeRefused` dropped from `ClassesTheBackendWordsPlainly` | 1 case of 1 test: the class |
| W6 | `PageWords`: a failure that is no refusal keeping its own message | 2 cases of 2 tests: the plan's failure of the add-in's own, and the scheduler's case of `AStartThatFailsAfterTheGateLeavesTheHostFree` |
| W7 | `Receive`'s `HostError` back to the failure's message | 2 cases of 2 tests: the plan's failure of the add-in's own, and T175's `HostError` case |
| W8 | the run folder's failure back to the run root and the disk's refusal | 1 case of 1 test: its route |
| W9 | the earlier plan's unanswered close ending with the close's message again | 2 cases of 2 tests: its route, and `ACloseThatFailedWithoutANamedRefusalCountsAsUnanswered` |
| W10 | the run's failure with no named refusal back to its message | 2 cases of 2 tests: its route, and the "failed" ending of `EveryStatusThatEndsTheRunOnThePageIsPostedOnceTheHostIsFree` |
| W11 | the run's unanswered close ending with the close's message again | 1 case of 1 test: its route |
| W12 | Open copy's `OpenFailed` back to the seat's sentence | 1 case of 1 test: its route |
| W13 | Discard copy's `DiscardFailed` back to the disk's refusal | 1 case of 1 test: its route |
| W14 | the unwritten "discarded" ending with the disk's refusal again | 1 case of 1 test: its route |
| W15 | the gate's retryable `BackendUnavailable` kept as the gate gave it | 2 cases of 2 tests: its route, and `AStartTheRestartGateRefusesIsAnsweredWithItsRefusalAndTheRunNeverStarts` |
| W16 | the add-in's word that the backend did not start kept as it gave it | 2 cases of 2 tests: its route, and the Remodel case of `OtherTabsBackendRestartTests.EachOtherTabsHostMarksTheBackendsOwnWordAndNothingElse` |
| W17 | the pipeline's `error` in the run line kept as it gave it | 2 cases of 2 tests: its route, and the "pipeline" ending |
| W18 | the Remodel host's words not handed to `PaneActions` (`FailureWords`) | 5 cases of 1 test: Open report, Open run folder, Show change and View log's two routes |
| W19 | `PaneActions`' Show not asking for the words | 1 case of 1 test: Show change's route |
| W20 | a refusal told in the tab's words not logged (`SendRefusal`) | 25 cases of 3 tests: W1's seven routes, the seventeen classes but `ScopeRefused`, and `WhatTheLogKeepsIsMasked` |
| W21 | nothing written to the log | 45 cases of 7 tests: the 23 routes, the seventeen classes, `WhatTheLogKeepsIsMasked`, and the four tests changed on purpose that look in the log (R19.6) |
| W22 | the log not masked | 1 case of 1 test: `WhatTheLogKeepsIsMasked` |
| W23 | the add-in not handing the host its log | 1 case of 1 test: `RemodelWiringTests.TheAddInHandsTheRemodelHostItsLog` |
| W24 | `PaneActions`' Open not asking for the words | 3 cases of 1 test: Open report, Open run folder, and View log's folder not opened |
| W25 | `PaneActions`' log folder not made, not asking for the words | 1 case of 1 test: its route |
| W26 | every shared row told in one sentence, a file not opened (`SharedRowWords`) | 3 cases of 1 test: Show change and View log's two routes |
| W27 | Start's failure once started back to its message | 1 case of 1 test: the scheduler's case of `AStartThatFailsAfterTheGateLeavesTheHostFree` |
| W28 | every refusal of the gate that can be pressed again told as a backend not restarted | 2 cases of 2 tests: a turn's (`APlanTheRestartGateRefusesIsAnsweredWithItsRefusalAndNothingHappens`) and a remodel run's (`AGateRefusalThatIsNotTheRestartsKeepsTheReviewHostsWords`) |
| W29 | the add-in unloading told as a backend not restarted | 1 case of 1 test: the guard's `BackendUnavailable` that cannot be pressed again |
| W30 | View log's failure to open asking for Open report's words | 1 case of 1 test: View log's folder not opened |
| F1 | `IsLostPlan` as it was: a re-attach losing a plan closed at the plan | 4 cases of 4 tests: the two of T212 that tell nothing, 152A's R5 case where the copy is left active, and the end-to-end teardown (R19.6) |
| P1 | the backend's `DocumentDirty` not retryable | 2 cases of 1 test: `test_an_unsaved_part_is_retryable_on_every_route`, the probe and the open |

38 mutations, 153 red results. Two parts of the fixes have no mutation of their own: the Stops taken in the step
that frees the host, which is one step for the reader once a Stop is decided under the lock (R19.1); and each
site's call to the log, which W21 takes out together - every route asserts its own sentence in the log, so each
site's call is pinned by its route. The race S1 brings back is the old `Stop`'s, held open by T204's post rather
than by its gap between the read and the store, which has no seam (R19.1).

### R19.8 Left for the owner

1. **The answer to Stop's own line.** The page still writes "Stopping. N change(s) applied ..." and ends the
   run on the answer to Stop when no terminal status has ended the run - which this host never leaves it to do
   (R19.2). Its words would then say the run is stopping when it has ended. Word that line as the run's end, or
   drop the second way out of the running state?
   *2026-10-21, on the decision's review (R19.12):* still the owner's, and it does not block T172: this host never
   leaves the page to end a run on that answer, and the second way out is now pinned on its own side (T229).
2. **A backend that does not answer whether a turn runs**, at a plan or a Start, is told on this tab as a
   backend not restarted with the saved settings (`BackendNotRestartedMessage`) - true, but less than the
   review host's own sentence, which goes to the log. Telling it apart from a restart's failure needs the gate
   to say which it is, in the review host's `BeginRemodelRun`, which decision 157A changes. Leave it, or ask for
   the distinction once 157A has landed?
   *2026-10-21, on the decision's review (R19.12):* still the owner's, and it does not block T172: both words are
   true, plain and name no path.
3. **The other tabs.** The Model check and Standards tabs still print a restart's failure ending in the
   backend's log's path, and the shared rows' failures as they come; the Review tab prints a failure whole by
   design (decision 150A). 159A was the Remodel tab's. The same words for the Model check and Standards tabs?
   *2026-10-21, on the decision's review (R19.12):* still the owner's, and it does not block T172: Start is the
   Remodel tab's alone.
4. **The run's own records.** A change record's `error`, the executor's text for a change that failed, is shown
   in the change list as the run recorded it, and can name a path, as the attestation's source path and the
   header's run folder do on purpose. They are the run's data, not a failure's sentence (R19.3). Leave them as
   recorded?
   *Settled 2026-10-21 on the decision's review (R19.9; T227, T228), as the owner's coordinator asked, since only a
   run reaches it:* a change that did not hold is shown in plain words with no path - its code, and where to read
   why - and its sentence stays in the change's record and the report in the run folder.

Recorded, not changed:

- View log's own failure: the log folder could not be made, so its reason can be logged nowhere. The tab says
  Windows could not open the log folder, and the Review tab's View log prints the failure whole.
- The host's own `ResumeRefused` quotes the state `plan.json` records - a token the run writes - as the page's
  run header shows a state it does not know as it was recorded (`remodel.js`, `RUN_STATES`).
- The backend's bodies keep their sentences, paths included; the add-in is their only reader, and logs them.
- Show change's log line names `entity.show` as what was asked: the shared row's hook is given the row.

**Evidence** (2026-10-21; before at `5a58988`, after on the branch): the C# build, `--no-incremental`, at zero
warnings once every mutation was restored; `SwReview.Extractor.Tests` 10,086 passed before and after, and
`SwReview.AddIn.Tests` 3,540 before and 3,603 after - the 63 new cases of T204 (4), T206 (2), T208 (51), T210 (3)
and T212 (3) - with the remodel host, page, end-to-end, pipeline and wiring classes, the shared rows, and the
restart and tool-service classes, 2,798 cases, green five times in a row. Python, not live, with
`SWREVIEW_REQUIRE_TOKENIZER=1`: 18,111 passed and 5 skipped before, on 3.12, and 18,115 passed and 5 skipped
after - the four new cases of T210 - on 3.12 (3.12.3) and on 3.11 (3.11.16, `--isolated`) alike. `ruff check`
clean, and no broken link.

### R19.9 The decision's review (T215 to T234)

Two independent reviews of T204 to T214 found no must-fix: one of the races, which brought five tests (four red, one
green that shows its first finding), and one of the mutations, which ran its own beside the 38 of R19.7. The owner's
coordinator asked for one more round, test first, in this worktree: fix what switching Start on (T172) would meet, one
defect older than 159A and R19.8 item 4 included, so that the switch waits on no known defect, and pin what the
mutations left alive. Each test was shown red before its fix, or under its mutation (R19.11). SOLIDWORKS was not
started.

- **A page that loads again reused its request ids** (T215, T216; the race review's R1). `remodel.js` numbered its
  requests from `m1` at every load, and the host answers a request of an earlier load under that load's id after the
  page has loaded again - its Stop, which 159A answers at the run's end. That answer was taken for the request of the
  load after it with the same id: the result view emptied ("No run yet."), and a Show waiting said it could not be
  shown. Each load now numbers its requests after a prefix of its own - the time and a random number - and a reply to
  a request this load did not send is dropped: the host's own messages carry no id, so an earlier load's `error`
  reply is not put in this load's banner either. The host's half is a guard: every Stop that reached the run is
  answered under its own id, to whichever load the pane shows (`EveryStopIsAnsweredUnderItsOwnIdThoughThePageLoadedAgain`).
- **`addin.log` lost lines** (T217, T218; the race review's R2). `AddInLog.Write` appended with
  `File.AppendAllText` - the file shared for reading only, under no lock, a failure swallowed - and the add-in appends
  there from several threads at once; the review's stress run lost 501 of 4,000 lines. The tab now sends the engineer
  there for a failure's reason. The appends of this process are made one at a time (a lock); the file is shared with
  any other reader or writer; a holder that shares it with neither is waited out briefly - 300 ms in all, and only
  while no line waits already, so a file held for long costs each later line one try; and a line that still cannot be
  written is kept, at most 1,000 to a file, the oldest going first, and written ahead of the next. The review's test
  held the file through the whole write, which no wait outlasts: hence the keeping. The tests write through
  `AddInLog.Append`, the append `Write` makes, each to a file of its own, since `AddInLog.Folder` is the whole
  process's and other classes move it while they run.
- **A failed hand-over let go of its run outside the lock** (T219, T220; the race review's R3). A Start whose run its
  scheduler would not take posted its `error` - the run's last word on the page - and only then, in its `finally`,
  cleared `_active`, outside `_endingLock`. The copy-gone stop, decided under that lock on SOLIDWORKS' thread, could
  land between: told after the last word, its flag left on the plan, which stays startable, so the next Start's run
  was stopped before it began and answered `remodel.stopped` unasked. The run is now let go of under the lock before
  that last word, and a stop asked for meanwhile - the copy going away as `remodel.started` was posted, the test's
  second case, written once the fix was in and red under R3b - is taken back (`RemodelRun.WithdrawStop`). R18.8's
  exception stands: the host is freed, `_busy` cleared, in the `finally`, after the `error`.
- **A Stop that crossed the run's end replaced the banner** (T221, T222; the race review's R4). A Stop the page sent
  as the run ended finds the host free and is answered `RunNotFound` (159A), and `stopRun` put that answer in the
  banner over the one the run's `error` put there, saying how the run ended. Every way a run is freed posts its
  terminal `status`, so the page ignores that answer.
- **A close that never reached the bridge was taken for done** (T223, T224; the mutation review's M6, older than
  159A). `CloseSession` counted every named refusal but the bridge's `BridgeUnavailable` as the end-of-session
  routine's answer with what it left. The add-in's client gives up after 30 seconds while the backend waits 60 for the
  bridge, so a close that timed out - or never reached the bridge - was recorded as done: with Start on, the run ended
  "The run ended 'saved'. ..." with the copy perhaps still open and the engineer's four settings changed, and nothing
  would end the session. A close refused `BackendUnavailable`, `HttpError`, `BadResponse`, `InvalidRunDir` or
  `InvalidRequest` is now not answered too (`CloseNotAnsweredClasses`): the session is kept for Discard, planning
  again, a re-attach or an unload to end, and the run ends in `RunCloseNotAnsweredMessage`. Found fixing it, by the
  same door: the pipeline's close was a quiet no-op when no backend ran, and a backend that stops after the open
  leaves the session held, so it is refused `BackendUnavailable`, sending nothing; the delete path deletes whatever
  the close answers, as before (`BackendRemodelPipelineTests`, R19.10). `UnansweredCloses` keeps its two rows and
  gains the client's real answers and that refusal (`ClosesThatNeverReachedTheBridge`). The two words of a close
  that was not answered said SOLIDWORKS did not answer; they now say what is known - "The run ended, but closing its
  copy was not confirmed, so the copy may still be open in SOLIDWORKS; ..." and "Closing the earlier plan's copy was
  not confirmed, so that plan is left as it was ...", the rest as it was (R19.3).
- **The earlier plan's close refused by the backend** (T225, T226; the mutation review's M3). Its `BridgeUnavailable`,
  whose sentence names the bridge's pipe, reached the tab as any refusal the backend answered - in
  `BridgeNotAnsweringMessage`, which says nothing of the earlier plan - where its twin with no named refusal says the
  earlier plan was left as it was. Every close of that plan that was not answered is now told in
  `EarlierPlanNotClosedMessage`, its class kept (`BridgeUnavailable` for a failure with no named refusal), retryable,
  and what it said logged: the 24th route of the path theory, and `AnEarlierPlansCloseThatNeverReachedTheBridgeLeavesItAsItWas`.
- **A change that did not hold** (T227, T228; R19.8 item 4). Its row printed the executor's own sentence
  (`remodel/apply.py`, `str(exc)`), which can name the copy's full path. It now says the change's code - when it is a
  code: never a sentence or a path - and "Press Open report to see why."; the sentence stays in the change's record
  and the report in the run folder.
- **The add-in's word that the backend did not start, logged twice** (T230, T231). `SwReviewAddIn.StartBackend`
  reports a first start that failed to `addin.log`, and the Remodel host logged the same failure again. Kept: the
  add-in's line. The tab's words send the engineer to the Review tab, which shows the failure whole, so the host logs
  nothing of it. A settings restart that failed has no line in `addin.log`, before 159A or after; the Review tab shows
  it.
- **A request with a body that could not reach the backend** (T232, T233; found on this round, older than 159A).
  `RemodelBackendClient.Call` sent a request's body before its `try`, so a backend that no longer listened - the
  connection refused as the body went - left as the transport's own `WebException`, not `BackendUnavailable`; the
  probe, the open, the plan, a Start, a Stop and the close all send one. The tab told it as a failure the add-in did
  not expect, and the pipeline's close let it through unnamed, which `CloseSession` already read as not answered.
  The body is sent inside the `try`, as a request with none was.
- **Pins** (T229), each where a mutation of the review survived: in the real chain, a Start-off plan's own close
  marks its session ended, so only `IsLostPlan`'s rule that an ended session loses no plan closed at the plan keeps it
  from being told lost (M1, RF3; `AStartOffPlansOwnCloseInTheRealChainNeverTellsItLost`); the add-in's other words on
  the backend, `backend_starting` and `ready`, reach the page as given (M2, RW6); the second way out of the
  `remodel.stop` row, and an `error` while no run runs leaving the run line (M4, RP1, RP2); a run stopped by its copy
  going away answered unasked, the copy-gone stop told once, and a plan planning again set aside told lost by `init`
  while it is the latest run (RS8, RS10, RF1); the log line's shape (RW2 to RW4) and a log that throws costing nothing
  but its line (RW5); the add-in's log wiring read from the code alone (RW7); and the other tabs' failure words
  exactly (RW8, RW9). `AnUnsavedPartIsRefusedRetryableOnEveryRoute`'s summary had been put between U26's summary and
  its test; each is back with its own.

### R19.10 Tests changed on purpose, on review

Each still pins what it pinned, or more.

- `RemodelPageContractTests.HostStub`: `StopEndsWith` may be null - the answer to Stop with no terminal `status`
  before it, for the second way out - and `StopCrossesTheRunsEnd` answers a Stop after the run's end `RunNotFound`.
- `RemodelPageContractTests.EveryChangeIsARowWithItsOutcomeAndAShowButton`: the failed change names its code and
  where to read why, where it named the executor's sentence (T227).
- `RemodelHostTests.AFailureThatCanNameAPathReachesTheTabInItsOwnWordsAndItsSentenceGoesToTheLog`: two routes more
  (the earlier plan's close refused by the backend; the run's close the backend did not answer), and the add-in's
  word that the backend did not start is not in the host's log (T230).
- `RemodelHostTests.TheTabsWordsForAFailureThatCanNameAPathArePlain`: the two words of a close that was not answered
  (T223).
- `RemodelHostTests.T180FinishedCloseFailureIsTruthfulAndOnlyAnAnsweredCloseReleasesSession`: those words exactly,
  where it looked for "did not answer" in them.
- `RemodelHostTests.UnansweredCloses`: its rows kept, with the client's real answers and the pipeline's refusal added
  (the review asked that it model the client's `BackendUnavailable`; its raw failure is a real one too - a request
  whose body could not be sent, T232).
- `BackendRemodelPipelineTests.CloseCopyWithNoBackendOrNoBridgeIsAQuietNoOp`, renamed `CloseCopyWithNoBridgeIsAQuietNoOp`:
  its no-backend half is now `CloseCopyWithNoBackendRunningIsRefusedAsNotSent`, refused, where it was a quiet no-op.
- `RemodelWiringTests.StartRemodelHost` reads the method's code alone, so `TheAddInHandsTheRemodelHostItsLog` - and
  `TheAddInsOnePipelineIsHandedItsBind` with it - is not met by a line commented out.
- `PaneActionsTests.AResolverThatThrowsIsAnsweredAsANotShownReplyRatherThanAsACrash` and
  `AnOpenerThatFailsIsReportedRedactedRatherThanThrownIntoWebView2`: the other tabs' message exactly, where a contains
  let a prefix or the whole exception through.

No test was loosened.

### R19.11 The mutations, on review

Each fix of the review taken out once, and each mutation the review left alive put back, by one exact replacement in
one file, in this worktree, as R19.7's were: the solution built, the named classes run - the host's (R19.7's six and
`AddInLogTests`, 621 cases), `RemodelPageContractTests` (58), `RemodelBackendClientTests` with the pipeline's (104), or
`test_chat_remodel_routes.py` (100) - and the file restored byte for byte, checked by its sha256. Every one is red. The
names beginning RS, RW, RF and RP are the review's own, put back as it wrote them where the code still reads so.

| Id | Taken out | Red |
|---|---|---|
| R1a | each load's requests numbered from `m1` | 1 case: `AnEarlierLoadsAnswerToStopIsNeverTakenForTheResultOfThePageThatLoadedAgain` |
| R1b | a reply to a request this load never sent taken as the host's own word | 1 case: `AReplyToARequestThisLoadNeverSentLeavesTheBannerAsItWas` |
| R2a | the appends neither one at a time nor kept, each straight to the file | 3 cases of 3 tests: `LinesAppendedFromSeveralThreadsAtOnceAreAllKeptOnce`, `ALineAppendedWhileAnotherHoldsTheFileIsWrittenWithTheNextOne` and `AFailuresSentenceReachesTheAddInsLogThoughAnotherAppendHoldsTheFile` |
| R2b | the file shared for reading only | 1 case: `ALineIsWrittenAtOnceBesideAnotherWriterThatSharesTheFile` |
| R2c | a holder not waited out | 1 case: `ALineWaitsOutABriefHolderAndIsInTheFileWhenTheAppendReturns` |
| R2d | a line that could not be written dropped | 2 cases of 2 tests: the held file, and the host's sentence through it |
| R3a | a failed hand-over letting go of its run after its last word | 1 case: the copy going away as that word is posted |
| R3b | a stop asked for during a failed hand-over left on the plan | 1 case: the copy going away as `remodel.started` is posted |
| R4 | the answer to a Stop that crossed the run's end put in the banner | 1 case: `AStopThatCrossesARunsErrorEndLeavesTheBannerSayingHowTheRunEnded` |
| M6a | only the bridge's own `BridgeUnavailable` a close not answered | 22 cases of 4 tests: the seven of `ClosesThatNeverReachedTheBridge` for a run's close, an earlier plan's and a Start-off plan's, and the route of a run's close the backend did not answer |
| M6b | a close with no backend running a quiet no-op | 1 case: `CloseCopyWithNoBackendRunningIsRefusedAsNotSent` |
| M6c | a run's unanswered close back to saying SOLIDWORKS did not answer it | 1 case: `TheTabsWordsForAFailureThatCanNameAPathArePlain` |
| M3 | the earlier plan's close the backend refused answered as that refusal | 8 cases of 2 tests: its route, and the seven of `AnEarlierPlansCloseThatNeverReachedTheBridgeLeavesItAsItWas` |
| RW16b | the earlier plan's close told in the close's own sentence | 10 cases of 4 tests: `ACloseThatFailedWithoutANamedRefusalCountsAsUnanswered`, the two routes of the earlier plan's close, and the seven above |
| I4a | a change that did not hold shown in the executor's sentence | 2 cases of 2 tests: `AChangeThatDidNotHoldIsShownInPlainWordsThatNameNoPath` and `EveryChangeIsARowWithItsOutcomeAndAShowButton` |
| I4b | any code shown, a path included | 1 case: `AChangeThatDidNotHoldIsShownInPlainWordsThatNameNoPath` |
| L1 | the add-in's word that the backend did not start logged by the host again | 1 case: its route |
| C1 | a request's body sent outside the call's `try` | 2 cases of 1 test: `ARequestWithABodyToABackendThatDiedIsBackendUnavailableRatherThanAnUnhandledWebException`, a plan and a close |
| RS8 | a run stopped by its copy going away not answered unasked | 1 case: `ARunStoppedOnlyBecauseItsCopyWentAwayIsAnsweredUnaskedAtItsEnd` |
| RS10 | the copy-gone stop told again at every later document change | 1 case: `TheStopWhenTheCopyIsGoneIsToldOnceHoweverOftenTheDocumentChanges` |
| RF1 | a plan closed at the plan never lost, planning again's set-aside included | 1 case: `WithStartSwitchedOffAPlanPlanningAgainSetAsideIsToldLostByInitWhileItIsTheLatestRun` |
| RF3 | an ended session losing a plan closed at the plan (M1) | 1 case: `AStartOffPlansOwnCloseInTheRealChainNeverTellsItLost` |
| RW2 | an exception logged by its message alone | 1 case: `TheLogKeepsWhatWasAskedAndWhatTheFailureSaid` |
| RW3 | a refusal logged without its class | 1 case: as RW2 |
| RW4 | the log line not saying what was asked | 1 case: as RW2 |
| RW5 | a log that throws not caught | 1 case: `ALogThatThrowsCostsNothingButItsLine` |
| RW6 | every lifecycle `status` reworded (M2) | 2 cases of 1 test: `TheAddInsOtherWordsOnTheBackendReachTheTabAsTheyAre`, `backend_starting` and `ready` |
| RW7 | the add-in's log wiring commented out | 1 case: `TheAddInHandsTheRemodelHostItsLog` |
| RW8 | the other tabs' failure words the whole exception | 6 cases of 2 tests: Show and the opener, on the Review, Model check and Standards tabs |
| RW9 | the other tabs' failure words with a prefix | 6 cases: as RW8 |
| RP1 | the answer to Stop never writing the line or ending the run (M4) | 1 case: `AnAnswerToStopThatNoTerminalStatusPrecededEndsTheRunOnItsWords` |
| RP2 | every `error` clearing the run line, a run ended or not (M4) | 1 case: `AnErrorWhileNoRunIsRunningLeavesTheRunLineAsItWas` |
| RPY1 | `ExternalReferences` made retryable | 2 cases of 1 test: `test_a_part_that_references_other_files_stays_not_retryable`, the probe and the open - the review's run of it had not run the Python suite |

33 mutations, 87 red results.

### R19.12 What is left, and Start

T172's switch waits on no known defect of the tab. What is open is the owner's, and none of it blocks the switch:

1. **The answer to Stop's own line** (R19.8 item 1): unreachable with this host, which posts every run's terminal
   `status` before it answers Stop; the second way out is pinned as the contract row describes it.
2. **A backend that does not answer whether a turn runs** (R19.8 item 2): told as a backend not restarted with the
   saved settings - true and plain; telling the two apart waits on 157A's gate.
3. **The other tabs** (R19.8 item 3): Start is the Remodel tab's alone.

Recorded, not changed:

- The race review's RS3 and RS4 survive: a Stop, or the copy-gone stop, that reads `_active` outside the lock and
  acts under it. Between the read and the lock there is no seam a test can hold open, as R19.1 found for the old
  `Stop`; both read under the lock, which S1 and S3 pin by the post the lock orders.
- A settings restart that failed has no line in `addin.log`; the Review tab shows it whole (T231).
- The Python suites were not run again on this round: no Python file changed.

**Evidence** (2026-10-21, on the branch after `b720e67`): the C# build, `--no-incremental`, at zero warnings once
every mutation was restored; `SwReview.Extractor.Tests` 10,086 passed, and `SwReview.AddIn.Tests` 3,651, from 3,603 -
the 48 new cases of T215 (3), T217 (5), T219 (2), T221 (1), T223 (23), T225 (1), T227 (1), T229 (10) and T232 (2) -
with the remodel host, page, end-to-end, pipeline, client and wiring classes, the shared rows, `AddInLogTests`, and
the restart and tool-service classes, 2,846 cases, green five times in a row. No Python file changed, so the Python
suites were not run again; RPY1 ran `test_chat_remodel_routes.py`, which only its mutation turned red. No broken link.
