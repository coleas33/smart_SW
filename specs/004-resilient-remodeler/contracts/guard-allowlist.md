# The Write Guard: stage-1 allowlist, assertions, and target verification

Two layers, because one cannot do the job. `SwGate.Call("GetChildren", () => component.GetChildren())`
guards on the **member name only**; the document is captured inside the lambda and the guard never
sees it. So "document-scoped" cannot be a property of `ICallGuard` alone. This mirrors the shape
`ReadOnlyGuard.Assert` plus `ReadOnlyGuard.AssertSaveAs` already has.

- **Layer 1**, `Guard/RemodelGuard.cs`, an `ICallGuard`: *which member may be called at all.*
- **Layer 2**, `Rms/RemodelScope.cs`: *which document it may be called on.*

## Why an allowlist here and a denylist there

`ReadOnlyGuard` is a denylist because the reviewer's **read** surface is unbounded and grows every
phase. The re-modeler is the inverse: its write surface is a closed set of about twenty members
this file enumerates. It is also exactly the workload that finds a denylist's gaps:
`ReadOnlyGuard` blocks `InsertFeatureChamfer`, `InsertFeatureShell` **and**
`InsertFeatureTreeFolder2` through its `InsertFeature` prefix, while leaving `FeatureFillet3`,
`FeatureRevolve2`, `InsertMirrorFeature2`, `InsertPart3`, `SetSuppression2` and `IModelDoc2.Save`
wide open.

**004 adds nothing to `ReadOnlyGuard`.** The four narrowing denials
(`IFeature.SetSuppression2` exempted under `SuppressTestGuard`,
`ISldWorks.SetUserPreferenceToggle`, `IModelDoc2.EditUndo2`, `IModelDoc2.SetSaveFlag`) are feature
003's, and narrowing is not widening.

### Denials added after stage 1

This file's set assertions read `ReadOnlyGuard`'s denied surface as data, so a denial another
feature adds lands here rather than in a silent drift. Recorded, so that a reader can check the
table against `RemodelGuardTests.ExpectedDeniedMembers` and against the guard itself.

**Feature 006 (the Standards check tab)** adds the members below with its cut-list and drawing
phases - the mutating and view-changing members that sit beside the reads those phases perform.
`006-standards-check/research.md` R8 is the table that fixes the membership, and therefore the
count; this list is that table's bare names, `SetText` counted once because
`ReadOnlyGuard.DeniedMemberSet` stores unqualified names.

| Members | The family they guard |
|---|---|
| `ActivateSheet`, `ActivateView` | sheet and view activation |
| `ShowExploded`, `ShowExploded2`, `CreateExplodedView`, `AutoExplode` | exploded-state writes |
| `SetVisibility`, `SetVisibilityInAsmDisplayStates`, `set_Visible` | visibility writes |
| `SetMaterialPropertyValues2`, `RemoveMaterialProperty`, `RemoveMaterialProperty2` | appearance writes |
| `set_Text`, `set_Text2` | table-cell writes |
| `AddRevision`, `DeleteRevision` | revision writes |
| `InsertRevisionTable`, `InsertRevisionTable2` | revision-table creation |
| `SetAutomaticCutList`, `UpdateCutList`, `SortCutList`, `SetAutomaticUpdate` | cut-list writes |
| `set_OverrideMass`, `SetOverrideMassValue` | mass-override writes |
| `SetOverride`, `SetText` | display-dimension writes (`SetText` also covers `INote.SetText`) |
| `SetSystemValue3`, `set_SystemValue`, `set_Value` | dimension-value writes |
| `SetName` | annotation-identity writes |
| `set_ExcludeFromCutList` | cut-list exclusion writes |

**None of them widens this allowlist.** No stage-1 key's bare name is on the list, so
`Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive` still finds the same five
(`IFeature.set_Name` and `SetName` are different names, and `ISldWorks.SetUserPreferenceToggle`
is untouched), and no member of `RemodelGuard.ExcludedMembers` became redundant. A denial is a
narrowing, so none of this is a constitution exception.

**Feature 010 (automatic mechanical checks)** adds the members below with its Hole Wizard and
`tolerance` reads (`010-mechanical-checks/contracts/tolerances.md` section 2): the setters beside
each value those reads take - the dimension tolerance, the GTol frames, the datum label, the
annotation's attachment and the Hole Wizard data. Every name was reflected on the 2024 SP5
interop (32.5.0.48); the numbered siblings of a listed setter (`SetFrameValues2`,
`SetFrameSymbols2`, `SetValues2`) are there because the same family writes the same value
through them. `set_*Diameter`, `set_*Depth` and `set_*Angle` are every such setter
`IWizardHoleFeatureData2` declares, not only the ones beside a read: `ModifyDefinition`, already
denied, is the only way a wizard edit takes effect, and these close the family by name as well.
This table is the membership: `MechanicalChecksDenylistTests` (in `GuardTests.cs`) parses it,
and `RemodelGuardTests.ExpectedDeniedMembers` lists the same bare names.

| Member (feature 010) | The read it sits beside |
|---|---|
| `IDimension.SetToleranceType`, `IDimension.SetToleranceValues`, `IDimension.SetToleranceFitValues` | `IDimension.Tolerance`; the three are the obsolete writers of the same tolerance |
| `IDimensionTolerance.set_Type`, `IDimensionTolerance.set_FitType` | `IDimensionTolerance.Type` |
| `IDimensionTolerance.SetValues`, `IDimensionTolerance.SetValues2` | `IDimensionTolerance.GetMinValue2`, `GetMaxValue2` |
| `IDimensionTolerance.SetFitValues` | `IDimensionTolerance.GetHoleFitValue`, `GetShaftFitValue` |
| `IGtol.SetFrameValues`, `IGtol.SetFrameValues2` | `IGtol.GetFrameValues` |
| `IGtol.SetFrameSymbols`, `IGtol.SetFrameSymbols2` | `IGtol.GetFrameSymbols3` |
| `IGtol.AddFrame`, `IGtol.DeleteFrame` | `IGtol.GetFrameCount`, `IGtol.GetFrame` |
| `IGtol.SetDatumIdentifier` | `IGtol.GetDatumIdentifier` |
| `IGtolFrame.SetSymbolXml`, `IGtolFrame.SetIndicator`, `IGtolFrame.AddIndicator`, `IGtolFrame.DeleteIndicator`, `IGtolFrame.SetFrameToleranceType` | `IGtolFrame.GetSymbolXml` |
| `IDatumTag.SetLabel` | `IDatumTag.GetLabel` |
| `IAnnotation.SetAttachedEntities`, `IAnnotation.ISetAttachedEntities` | `IAnnotation.GetAttachedEntities3` |
| `IWizardHoleFeatureData2.set_HoleFit` | `IWizardHoleFeatureData2.HoleFit` |
| `IWizardHoleFeatureData2.set_ThreadClass` | `IWizardHoleFeatureData2.ThreadClass` |
| `IWizardHoleFeatureData2.set_HeadClearance` | `IWizardHoleFeatureData2.HeadClearance` |
| `IWizardHoleFeatureData2.set_Diameter`, `.set_CounterBoreDiameter`, `.set_CounterDrillDiameter`, `.set_CounterSinkDiameter`, `.set_MinorDiameter`, `.set_MajorDiameter`, `.set_HoleDiameter`, `.set_ThruHoleDiameter`, `.set_TapDrillDiameter`, `.set_ThruTapDrillDiameter`, `.set_NearCounterSinkDiameter`, `.set_MidCounterSinkDiameter`, `.set_FarCounterSinkDiameter`, `.set_ThreadDiameter` | the diameter reads (`Diameter`, `ThruHoleDiameter`, `TapDrillDiameter`, `CounterBoreDiameter`, `CounterSinkDiameter`) |
| `IWizardHoleFeatureData2.set_Depth`, `.set_CounterBoreDepth`, `.set_CounterDrillDepth`, `.set_HoleDepth`, `.set_ThruHoleDepth`, `.set_TapDrillDepth`, `.set_ThruTapDrillDepth`, `.set_ThreadDepth` | the depth reads (`HoleDepth`, `ThreadDepth`, `CounterBoreDepth`) |
| `IWizardHoleFeatureData2.set_CounterDrillAngle`, `.set_CounterSinkAngle`, `.set_DrillAngle`, `.set_NearCounterSinkAngle`, `.set_MidCounterSinkAngle`, `.set_FarCounterSinkAngle`, `.set_ThreadAngle` | the angle read (`CounterSinkAngle`) |

**None of them widens this allowlist either.** No stage-1 key's bare name is among them - in
particular `set_Name` and `set_Description` are not - so the five overriding keys and
`RemodelGuard.ExcludedMembers` answer exactly as before. The reads beside them stay allowed.

004 makes exactly one **visibility-only** change to that file: `DeniedMembers` and
`DeniedPrefixes` become `public static readonly IReadOnlyCollection<string>` instead of
`private static readonly`, with no member added, removed or reworded. The tests below read the
denied surface as data, and nothing exposes `SwReview.Extractor`'s internals (the only
`InternalsVisibleTo` in the tree is `SwReview.Extractor.Console`'s, `Program.cs:25`), so without
this the set assertions cannot be written at all. Exposing a denylist for reading widens no call
surface.

## Keys are interface-qualified

Allowlist keys are `Interface.Member`. Bare names collide, and both halves of the collision are
real on 2024 SP5:

- `ICustomPropertyManager.Delete2(String)` (the session-tag delete) is refused today because
  `ReadOnlyGuard` denies the bare name `Delete2`, which was meant for `IEntity.Delete2`.
- An allowlist entry for `IEquationMgr.Add3` written as `"Add3"` would silently also permit
  `ICustomPropertyManager.Add3`.

`RemodelGuard.Assert(qualifiedKey)` returns if the qualified key is on the allowlist below; else it
delegates to `ReadOnlyGuard.Assert(BareName(qualifiedKey))`, so the read-only rules still apply
unchanged to everything off the list. Only the remodel call sites use qualified keys; the
reviewer's existing `SwGate.Call("GetChildren", ...)` sites keep bare names and are untouched.

Within the remodel family the rule is **qualified keys at write call sites, bare names at read call
sites**. The probe and the remodel handlers' own reads (`GetObjectByPersistReference3`,
`IFeature.get_Name`, `GetWhatsWrongCount`, `Get4` and the scope-signal reads) use bare names exactly
as the reviewer's read sites do, so the allowlist is consulted only where a write is attempted. This
is pinned here because the gated log records strings, and a test that has to tell a read from a
write in that log needs the key style to be a decision rather than an accident.

## The stage-1 allowlist

Exactly this list. Every member below is VERIFIED present with the signature the interop manifest
records (`interop-manifest.md`); VERIFIED never means the call behaves.

| Qualified key | Used for |
|---------------|----------|
| `IModelDocExtension.ReorderFeature` | the only move operation; `location` is `Before = 2` or `After = 3` |
| `IFeatureManager.InsertFeatureTreeFolder2` | create a folder around the current contiguous selection, `Containing = 2` |
| `IFeatureManager.EditRollback` | roll the bar to the end at open, `ToEnd = 1` |
| `IFeature.set_Name` | folder naming and duplicate-feature-name repair, and nothing else |
| `IFeature.set_Description` | the description pass |
| `IFeature.Select2` | build the contiguous selection a folder wraps |
| `IEquationMgr.Add3` | the verified equation helper's first attempt |
| `IEquationMgr.Add2` | the verified equation helper's fallback |
| `IEquationMgr.Delete` | the inverse of an add, in reverse order |
| `IEquationMgr.set_Equation` | `SetEquationVerified`'s first attempt: repair an existing global in place (FR-029, `remodel.equation` `op: "set"`) |
| `IEquationMgr.SetEquationAndConfigurationOption` | `SetEquationVerified`'s fallback for the same job |
| `IModelDoc2.ForceRebuild3` | the one rebuild call |
| `IModelDoc2.ClearSelection2` | before and after every selection-based operation |
| `IModelDoc2.Save3` | the single save, no filename, behind `AssertSaveTarget` |
| `IModelDocExtension.SelectByID2` | selection where `Select2` is not enough |
| `ICustomPropertyManager.Add3` | write the session tag |
| `ICustomPropertyManager.Delete2` | remove the session tag at close |
| `ISldWorks.SetUserPreferenceToggle` | the three user-preference toggles (10, 77, 329), restored in a `finally` |
| `ISldWorks.set_CommandInProgress` | the modal-suppression flag set for the run and restored in the same `finally` (PROBE-1). It is a property, not a `swUserPreferenceToggle_e` value, so it needs its own key |
| `ISldWorks.CloseDoc` | close the tagged copy |

**`remodel.probe_scope` adds nothing to this list.** The preflight probe that reads the scope
signals off the engineer's open source (`bridge-remodel.md`) calls read members only, every one of
which `ReadOnlyGuard` already permits, so it takes `RemodelGuard`'s delegation branch and touches
no allowlist entry. It does **not** follow that the probe's `gated=` set is empty: `SwGate.Guard`
calls `observer.Gated(interopMember)` for every member *before* the guard judges it
(`extractor/SwReview.Extractor/Sw/SwGate.cs`), so reads are recorded too, and the probe's gated set
holds roughly nine read members. One test asserts instead that the probe's `refused=` set is empty,
that its `gated=` set is a subset of a named, checked-in read-only probe surface - the members of
`bridge-remodel.md`'s `scope_signals` table plus `GetOpenDocumentByName`, `GetType`, `GetSaveFlag`
and `ListExternalFileReferencesCount2` - and that no stage-1 allowlist key appears in it. That is
the machine-checkable form of "the source is only ever read".

## Explicitly not allowlisted in stage 1

Listed so that stage 1's surface cannot silently come to include them, and so that a reader can
check the list against the code.

| Not allowlisted | Why |
|-----------------|-----|
| `IModelDoc2.EditDelete` | the one call that deletes real features on a mis-selection. **Owner decision: v1 refuses a part whose tree already carries an RMS-named folder holding the wrong members**, rather than dissolving and re-wrapping it. This removes the single highest-risk allowance from the guard entirely, at the cost of refusing some legacy parts by name |
| `IModelDoc2.SaveAs3`, `IModelDocExtension.SaveAs3` | any path at all. A silent `SaveAs` renames the open document in place, and `swSaveAsOptions_Copy` was observed opening a modal Save As dialog after the file was already written; a modal on the add-in's STA thread is a hang, not an error |
| `IModelDoc2.SetSaveFlag` | forging the dirty state defeats the source-dirty preflight |
| `IModelDoc2.EditRebuild3` | one rebuild call, one meaning |
| `IModelDoc2.EditUndo2`, `EditRedo2` | returns **void** (VERIFIED), so it cannot be verified, and it shares the engineer's UI undo stack |
| `IModelDocExtension.StartRecordingUndoObject`, `FinishRecordingUndoObject2` | a UI-undo-stack mechanism this design has decided not to rely on; an unused allowlist entry is exactly the accidental widening the allowlist exists to prevent |
| `IDimension.set_Name` | v1 addresses no dimension: the IR carries none, so the planner cannot name one, and FR-030 forbids driving one. The rename-before-equations ordering rule this member existed for is kept in research.md R3.5 for the later dimensions feature. An allowlist entry with no call path is exactly the accidental widening this list exists to prevent, which is the same reason `StartRecordingUndoObject` is excluded below |
| `IFeature.SetSuppression2`, `IPartDoc.EditSuppress`, `EditUnsuppress` | suppression is feature 003's exception under its own guard, not this one's |
| `IFeature.ModifyDefinition` | redefining a feature is stage 2 |
| `Delete2` on anything but a custom property | the interface-qualified key is the whole point |
| `IModelDoc2.SetSystemValue*`, `IModelDocExtension.SetUserPreference*` | document and user preference writes beyond the four named toggles |
| the whole `FeatureCut*`, `FeatureExtrusion*`, `FeatureRevolve*`, `FeatureFillet*`, `InsertFeature*`, `InsertMirrorFeature*`, `FeatureLinearPattern*`, `FeatureCircularPattern*`, `InsertRefPlane`, `InsertPart3`, `CreateFeatureFromBody3`, `ISketchManager.*` creation family | stage 1 creates no geometry. `IFeatureManager.InsertFeatureTreeFolder2` is the single exception and is listed above by name |

Stage 2 gets a **second additive allowlist, reviewed on its own**. Stage 1's list is never widened
to accommodate it.

## `AssertSaveTarget(path)`

Called before `IModelDoc2.Save3` even though `Save3` takes no filename, because the assertion is
what the test suite pins and what the report cites.

Refuses, each with its own test: a path outside this run's folder; a path containing `..` before
canonicalization; a path equal to the source; another run's copy; a path that is not `.SLDPRT`; a
path with no extension; a `.sldasm` or `.slddrw`. Only this run's copy path passes.

## `AssertFolderSelection()`

`GetSelectedObjectCount2(-1) == 1` **and** `((IFeature)GetSelectedObject6(1, -1)).GetTypeName2()
== "FtrFolder"` (all VERIFIED). One wrong selection under a delete removes real features, so this
is a named, tested helper and is never inlined at a call site.

**In v1 it is a refusal helper, not a precondition to a write.** `IModelDoc2.EditDelete` is not on
the allowlist, so v1 has no dissolve path and nothing calls this before a delete. It has exactly
two v1 uses:

1. It is the predicate the planner's refusal is written against. A part carrying an RMS-named
   folder whose members differ from the plan is refused with `rms_named_folder_wrong_members`
   (the one token, data-model.md section 4.2), and the
   refusal names the folder using the same "one selected object and it is a `FtrFolder`" reading.
2. It is the stated precondition any future dissolve **must** pass, so stage 2 inherits a tested
   assertion rather than writing one under time pressure beside a delete.

One test asserts `IModelDoc2.EditDelete` is absent from the stage-1 allowlist, so the helper cannot
be needed in v1 by any path.

## `VerifyTarget()`

`Rms/RemodelScope.cs` is the only object that holds the copy's `IModelDoc2`. Every write method is
`VerifyTarget()` and then `gate.Call(qualifiedKey, ...)`. `VerifyTarget` is four cheap checks on
the application thread, re-run **before every single write**:

| # | Check | Catches |
|---|-------|---------|
| 1 | `document.GetPathName()` equals the copy path this run created | a different document became the handle |
| 2 | `document.Extension.CustomPropertyManager("").Get4("SwReviewRemodelRun", ...)` equals this run's id | a different copy, or the tag stripped (PROBE-12, blocking) |
| 3 | `swApp.GetOpenDocumentByName(copyPath)` returns the **same** COM identity (`Marshal.GetIUnknownForObject`) | a close-and-reopen underneath the run |
| 4 | the copy path is a canonicalized descendant of this run's folder, with `..` resolved | a path that escapes the run folder |

Any failure throws `RemodelTargetError` naming which check failed; the run aborts with the change
log intact and the copy left on disk for inspection.

**The strongest property here is structural, not procedural.** No command exposed to the model, and
no command in the bridge protocol at all, takes a document. The scope's copy is the only target
reachable. That is stronger than validating a path the caller supplied, and it is what the
constitution's exception rests on.

## Option composition, asserted as exact integers

| Call | Required | Forbidden |
|------|----------|-----------|
| `OpenDoc7` on the copy | `Silent(1) \| LoadModel(16) = 17` | `ReadOnly(2)`, `ViewOnly(4)` |
| `Save3` | `swSaveAsOptions_Silent = 1` | `Copy(2)`, `SaveReferenced(4)`, `AvoidRebuildOnSave(8)` |
| `InsertFeatureTreeFolder2` | `swFeatureTreeFolder_Containing = 2` | every other value |
| `EditRollback` | `swMoveRollbackBarToEnd = 1` | every other value |
| `ReorderFeature` | `Before = 2` or `After = 3` | `ToEnd = 1`, `ToTop = 4`, `ToFolder = 5` |

The planner's `Move.location` set is closed at `before` and `after` for the same reason
(data-model.md section 1.3), so `test_remodel_order.py` and `RemodelGuardTests` assert the same two
values from the two ends and a `to_end` move cannot be planned in the first place.

All values VERIFIED. Each row is one unit test asserting the integer the code composes, not the
name it used.

## What the tests pin without SOLIDWORKS

- `RemodelGuard` is a pure `ICallGuard`: xUnit over the allow and deny table above, including the
  `Delete2` and `Add3` interface collisions, asserted as a **set equality** against
  `ReadOnlyGuard.DeniedMembers` union `DeniedPrefixes` (readable as data after the visibility-only
  change named above), so a denial added upstream cannot silently
  widen the remodel surface, and a member added to the allowlist without a row here fails the test.
- `AssertSaveTarget`: every refusal case above, and only this run's copy passes.
- `RemodelScope` over an `IRemodelTarget` fake: tag changed mid-run refuses; path changed refuses;
  COM identity changed refuses; run-folder escape refuses; happy path asserts the exact member
  sequence, in order.
- `ToolServiceRequestLogger.Format` already records `gated=`, and it records **reads as well as
  writes**, because `SwGate.Guard` gates every member before judging it. So the assertion is not
  "the gated set contains only allowlisted keys": a mutating remodel request also gates
  `GetObjectByPersistReference3`, `IFeature.get_Name` and `GetWhatsWrongCount`, none of which are on
  the stage-1 list. One test asserts instead that a remodel request's `refused=` set is empty and
  that every gated key on `ReadOnlyGuard`'s denied surface - every key that needed the allowlist to
  pass - is on the stage-1 allowlist:
  `gated ∩ (ReadOnlyGuard.DeniedMembers ∪ DeniedPrefixes) ⊆ stage-1 allowlist`. This is
  stronger than a claim about "write keys", which the log has no way to identify. It is the same
  SC-004 audit artifact, extended rather than replaced.
- Secret policy: the general-chat secret is refused for every `remodel.*` command; the remodel
  secret is refused for `interference`.
- The frozen interop-surface manifest and its two tests (`interop-manifest.md`).
