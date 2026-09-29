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
  (004 T173).

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
  are. The read is a clean-up read: the guard asked under the bare key `GetOpenDocumentByName` and
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
on `codex/testing-feedback-2026-09-28` (commits `63fc360` and `2aed3d5`), and the four reviews of
that follow-up the same day: a read-only-source lens, a crash hunt over the packet's logs and the
2024 API help installed on the development machine, and a general gates lens (the fourth, the
drawing lens, is feature 011's and 013's). The engineer asked for the follow-up to be checked, and
the workflow that checked it settles each finding by a default. **Each item below is a default
taken 2026-09-28, the owner may revise; none is the owner's own words, and none is an R12
decision.** SOLIDWORKS was not started: the API help was read from the installed help files and the
interop metadata was reflected, and what each item says a seat does stays a seat item until the
next sitting checks it (the retest in `docs/testing-feedback-2026-09-28.md`).

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
