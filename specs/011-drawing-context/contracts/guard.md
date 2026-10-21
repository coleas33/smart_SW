# Contract: The Guard, Hardened First

Normative for FR-005 to FR-007 and SC-009. Lands before any new drawing read (Phase 2).

## 1. The families

**The 28 drawing families**, every writer of which is refused: `IDrawingDoc`, `ISheet`, `IView`,
`IDisplayDimension`, `IDimension`, `IDimensionTolerance`, `IAnnotation`, `INote`, `IGtol`,
`IGtolFrame`, `IDatumTag`, `ISFSymbol`, `ITableAnnotation`, `IBomTableAnnotation`, `IBomFeature`,
`IRevisionTableAnnotation`, `IGeneralTableFeature`, `ITitleBlockTableFeature`, `ITitleBlock`,
`IDatumTargetSym`, `ICenterMark`, `IWeldSymbol`, `IDowelSymbol`, `IMultiJogLeader`,
`ICalloutVariable`, `ICalloutLengthVariable`, `ICalloutAngleVariable`, `ICalloutStringVariable`.

*Corrected 2026-09-23 on review*: the last four, the hole callout's variables, joined the list.
T026's `SwDrawingReader.HoleCalloutVariables` reads them, and they were the only interop
interfaces the feature's reads touch outside the first 24, so twelve of their writers
(`set_ToleranceMax`, `set_ToleranceMin`, `set_ToleranceType`, `set_Precision`,
`set_TolerancePrecision`, `set_TextHeight`, `set_TextScale`, `set_UseTextScale`,
`set_FitTextHeight`, `set_FitTextScale`, `set_FitUseTextScale`, `set_ShaftFit`) had been left
callable. `ICalloutAngleVariable` and `ICalloutStringVariable` have getters only; they are listed so
a later interop that adds a writer is caught. A family any drawing read touches is a family of this
list.

**The shared families**, named members only:

| Interface | Members refused | Beside the read |
|---|---|---|
| `ISldWorks` | `ActivateDoc`, `ActivateDoc2`, `ActivateDoc3`, `DocumentVisible`, `CloseAllDocuments`, `CloseAndReopen`, `CloseAndReopen2`, `QuitDoc`, `NewDocument`, `NewDrawing`, `NewDrawing2`, `NewPart`, `NewAssembly`, `OpenDoc`, `OpenDoc2`, `OpenDoc3`, `OpenDoc4`, `OpenDoc7`, `OpenDocSilent`, `OpenModelConfiguration`, `LoadFile2`, `LoadFile3`, `LoadFile4`, `RunMacro`, `RunMacro2`, `RunCommand`, `RunAttachedMacro`, `RunJournalCmd` | `GetDocuments`, `GetDocumentCount` (discovery) |
| `IModelDocExtension` | `SetUserPreferenceInteger`, `SetUserPreferenceString`, `SetUserPreferenceDouble`, `SetUserPreferenceTextFormat` | `GetUserPreferenceInteger`, `GetUserPreferenceString` (the drawing's settings) |

*Amended 2026-10-19 (owner decision 136A).* The rows named members by hand, and other spellings
of the same members on the same interop went unrefused: the COM twins `IOpenDoc` to `IOpenDoc5`,
`IOpenDocSilent`, `IActivateDoc` to `IActivateDoc3`, `INewDocument`, `INewDocument2`,
`INewDrawing`, `INewDrawing2`, `INewPart` and `INewAssembly`, and bare `LoadFile`, `LoadAddIn` and
`LoadAdminSettingsFile`. The shared rows now name every member of the **open, activate, new, load,
close and quit families** of `ISldWorks`, `IModelDoc2` (a third shared row) and
`IModelDocExtension`, and `DocumentLifecycleFamilyTests` (section 5) reflects the interop to prove
them complete. A name belongs to the families when one of its words is `Open`, `Reopen`,
`Activate`, `Deactivate`, `New`, `Load`, `Reload`, `Unload`, `Close`, `Quit` or `Exit` - the verb
with its capital, starting the name, following a COM twin's `I` or starting a later word, and
ending where the name or the word does - so `ExitApp` is of the quit family and `FileReload` of the
load family, and `ClosestDistance`, a measurement, and `IsOpenedReadOnly` are of none. Each member
is a reader by section 2's prefixes, which stays allowed, an exclusion of section 3, or refused bare
and qualified with its interface by every gate the product builds; a member a later interop adds
fails the test until someone decides which. Beyond the spellings above the grammar found, and the
rows now refuse: on `ISldWorks` `UnloadAddIn`, `ExitApp`, `ActivateTaskPane`,
`CloseUserNotification`, `CreateNewWindow`, `PresetNewDrawingParameters`, `SetNewFilename`,
`AddFileOpenItem` to `AddFileOpenItem3`, `RemoveFileOpenItem` and `RemoveFileOpenItem2`; on
`IModelDoc2` `Quit`, `FileReload`, `ReloadOrReplace`, `CloseFamilyTable`, `ClosePrintPreview`,
`ActivateSelectedFeature`, `ActivateFeatureMgrView` and `DeActivateFeatureMgrView`; on
`IModelDocExtension` `LoadDraftingStandard`, `ReloadOrReplace`, `CloseMessageBar` and
`CloseUserNotification`. The product calls none of them (section 5's audit). `IModelDoc2.Close`
stays allowed, for the reason section 3 gives.

*Amended 2026-10-19 (owner decision 140A).* `IModelDoc2.Close` is refused now, and the rows also
name `IModelDoc2.Save` and `Rebuild` and `IModelDocExtension.Rebuild`: the bridge judges a
command against its own fixed set and no longer hands its name to `ReadOnlyGuard`, which had
judged `remodel.close`, `remodel.save` and `remodel.rebuild` by the part after the dot, so the
three members could not be denied while those commands existed (research R10.1). No product path
calls any of them; the re-modeler's rebuild, save and close are the qualified keys
`IModelDoc2.ForceRebuild3`, `IModelDoc2.Save3` and `ISldWorks.CloseDoc` of its own allowlist.

*Amended 2026-10-19 (owner decision 140A), the families.* The rows also name every member of the
**save, rename, move and copy, replace, release and lock, read-only and rebuild families** of the
three interfaces and of `IPartDoc` and `IAssemblyDoc` - two more shared rows: a model document is
also one of them, and their saves, replaces and rebuilds act on that same document - and, on the
decision's review, of `IFeatureManager`, a third, that the guard did not refuse yet; the drawing
families' are writers of their family rows already. `DocumentWriteFamilyTests` (section 5)
reflects the 34 interfaces the generated tables are written against - those six, decision 21A's
creation interfaces and the 28 drawing families of this section - to prove the rows complete for
them; no test reads the interop's other interfaces, where research R10.4 counts what the families
hold. A
name belongs when one of its words, read as above, is `Save`, `Rename`, `Move`, `Copy`,
`Replace`, `Release`, `Lock`, `Unlock`, `ReadOnly` or `Rebuild`: `Copy` because
`ISldWorks.CopyDocument` is `MoveDocument`'s twin, `Release`, `Lock` and `Unlock` for the locks
and storage SOLIDWORKS holds in the file and the locks on the document's references, `ReadOnly`
for `SetReadOnlyState`, which would undo behind the engineer what decision 136A's check reads; so
`HasRenamedDocuments`, a read, and `IsLightLockedToModel` are of none. The rows refuse 55 more
names: on `ISldWorks` `AddFileSaveAsItem`, `AddFileSaveAsItem2`, `RemoveFileSaveAsItem`,
`RemoveFileSaveAsItem2`, `RunBatchSaveProcess`, `SaveSettings`, `ShowBatchSaveTo3DExperienceDlg`,
`MoveDocument`, `IMoveDocument`, `CopyDocument`, `ICopyDocument`, `CopyAppearance` and
`ReplaceReferencedDocument`; on `IModelDoc2` `Save2`, `SaveAs`, `SaveAs2`, `SaveAs4`,
`SaveAsSilent`, `SaveSilent`, `SetSaveAsFileName`, `EditCopy`, `ForceReleaseLocks`,
`IRelease3rdPartyStorage`, `Lock`, `UnLock`, `LockAllExternalReferences`,
`UnlockAllExternalReferences`, `LockFramePoint`, `UnlockFramePoint`, `LockLightToModel` and
`SetReadOnlyState` (which `RemodelGuard` had refused itself, and still refuses in both spellings);
on `IModelDocExtension` `SaveAs`, `SaveAs2`, `SaveDeFeaturedFile`, `SaveDraftingStandard`,
`SavePackAndGo`, `SaveTo3DExperience`, `SaveViewToSolidworks`, `RenameDocument`,
`RenameDraftingStandard`, `MoveDecal`, `CopyDraftingStandard`, `IRelease3rdPartyStorageStore`,
`ReleaseStream`, `EditRebuildAll` and `set_ShowPartRebuildIndicators`; on `IPartDoc`
`SaveToFile`, `SaveToFile2` and `SaveToFile3`; on `IAssemblyDoc` `SaveIsolate`, `CopyWithMates`,
`CopyWithMates2`, `ReplaceComponents`, `ReplaceComponents2`, `ReplacePLMComponents`,
`ForceRebuild2` and `set_EnableAssemblyRebuild`; and on the review, on `IFeatureManager`,
`MoveRotateLiveSectionPlane` and `set_MoveSizeFeatures`. The product calls none of them (section
5's audit). Of the families only `SaveBMP` and `MoveToFolder` stay allowed, for the reasons
section 3 gives, and only the exceptions' own guards let any of the rest through:
`SuppressTestGuard` and `RemodelProbeGuard` the bare `ForceRebuild3`, `RemodelProbeGuard` the bare
`SaveAs3`, and `RemodelGuard` `IModelDoc2.ForceRebuild3` and `IModelDoc2.Save3`.

*Amended 2026-10-19 (owner decision 144A; research R11).* Three of the gaps decision 140A's
reviews found (research R10.4, items 1, 2 and 5) are closed. `MoveToFolder` and `NewDocument` are
refused now: only `probe remodel` calls them, so they left section 3's exclusions, the
`IFeatureManager` and `ISldWorks` rows refuse them, and `RemodelProbeGuard`'s run-scoped members
exempt the bare names its host gates, as they exempt `ForceRebuild3` and `SaveAs3`; of the families
only `SaveBMP` stays allowed. The open, activate, new, load, close and quit families are read on
`IAssemblyDoc` as a fourth interface, and its row refuses the fifteen members they hold there:
`OpenCompFile`, `SelectiveOpen`, `ComponentReload`, `ComponentReload2`, `IComponentReload2`,
`IComponentReload3`, `InsertNewPart`, `InsertNewPart2`, `InsertNewAssembly`,
`InsertNewVirtualPart`, `InsertNewVirtualAssembly`, `InsertLoadReference`, `ActivateGroundPlane`,
`ExitIsolate` and `TemporaryFixGroupExit`. The row also names `Isolate`, the mode `ExitIsolate`
leaves, which section 2's reader prefix `Is` had taken for a reader by its letters and which no
grammar of these interfaces reads. The product calls none of them (section 5's audit). Only the
exceptions' own guards let any member of the families through: those above, `RemodelProbeGuard`
the bare `NewDocument` and `MoveToFolder` as well, and the re-modeler's pane seat's guard
`ISldWorks.ActivateDoc3` (section 8).

*Amended 2026-10-20 (owner decision 148A; research R12).* `OpenDoc7`, a writable open, is refused
now. Its two callers that gated it by the bare name - the bridge's `remodel.open` and `probe
remodel`'s reopen of its throwaway part - name it by its qualified key, as the pane seat already did,
so it left section 3's exclusions and the `ISldWorks` row refuses it, and no gate the product builds
lets the bare name through. Its key, `ISldWorks.OpenDoc7`, is let through by exactly the guards of
its three callers: `RemodelGuard`'s stage-1 allowlist, where it is the sixth key that overrides a
read-only denial, `RemodelProbeGuard`'s run-scoped members and the pane seat's guard, which is a
closed allowlist now (section 8). The product calls no other member of the families.

**Every spelling.** `ReadOnlyGuard.Assert` judges an interface-qualified key
(`IDrawingDoc.ActivateSheet`) by its member half as well as by the whole key, so a read-only gate
refuses every spelling of a denied member, and `DrawingFamilyDenylistTests` asserts each table
member refused qualified with its interface too. *Corrected 2026-09-23 on review*: a qualified key
had passed a read-only gate whatever it named, and the read audit compared literals whole; it now
judges a qualified literal by its member half unless it is a key of `RemodelGuard` or
`DrawingOpenGuard`, the two allowlist guards, which judge their own keys first and are unchanged.
The deliberate exclusions of section 3 (`OpenDoc6`, `CloseDoc`, ...) stay allowed in either
spelling; what keeps a read path from closing a document is that no read call site names one, and
the confirmed drawing's close goes through `DrawingOpenGuard`'s allowlist. *Amended 2026-10-19
(owner decision 144A)*: the re-modeler's pane seat's guard, `RemodelSeatGuard` (section 8), is a
third allowlist guard; the read audit judges its two keys whole only in the seat's own file
(`DrawingFamilyReadAuditTests.IsTheSeatsOwnKey`, on the decision's review), so either key written in
any other product file is judged by its member half, as before. *Amended 2026-10-20 (owner decision
148A)*: `ISldWorks.OpenDoc7` is a key of `RemodelGuard` too, which the audit judges whole in every
file, so `TheSeatsKeysAreLiteralsOfTheFilesWhoseGuardsLetThemThroughAlone` holds it to the three files
whose guards let it through - the seat's, the bridge's dispatcher and the probe host - and
`ActivateDoc3`'s key to the seat's alone. *Amended 2026-10-20 (owner decision 151A; research
R13.1)*: the audit reads every allowlist guard's keys through their shared rule (section 9) and
judges a key whole only in a file that builds that guard, by its member half anywhere else: the
seat's keys as before - but that decision 21A's and 17A's audits, which never had the seat's
exemption, judge its `ISldWorks.ActivateDoc3` in the seat's file whole where they judged it as
`ActivateDoc3`, which neither table holds (noted on the review, research R13.6) - and the other two
guards' more narrowly - `ISldWorks.OpenDoc7` whole in the
dispatcher, the add-in's tool service host and the seat, and by its member half in the probe host,
where it is the probe's own call; of the confirmed drawing's keys only `ISldWorks.CloseDoc` stands in
a product file outside the `Guard` folder, the dispatcher, as the stage-1 guard's key.

## 2. The writer grammar

A public method of a drawing family is a **writer** when its name does not start with `get_`,
`Get`, `IGet` or `Is` as a whole word - the prefix followed by the end of the name or by anything
but a lowercase letter (`get_` ends a word itself) - and matches:

```text
^(set_|I?(Set|Add|Insert|Delete|Remove|Edit|Modify|Change|Reset|Activate|Attach|Detach|Update|
  Replace|Break|Hide|Show|Isolate|Move|Align|Suppress|Unsuppress|Rebuild|Convert|Create|Make|
  Lock|Unlock|Sort|Split|Merge|Rotate|Scale|Flip|Link|Unlink|Import|Explode|Clear|Apply|Restore|
  Save|Dissolve|Expand|Collapse|Reload|Rename|New|Paste|Copy|Cut|Drag|Close|Quit|Open|Load|
  Unload|Regenerate|Reorder|Auto|Dimension|Reverse|Swap|Toggle|Enable|Disable|Select|Purge|
  Relink|Resolve|Crop|Unbreak|Force|Hatch|Offset|Position|Freeze|Unfreeze))
```

*Amended 2026-10-19 (owner decision 144A; research R10.4 item 2, R11.4)*: the grammar gave the
COM twin's `I` to four verbs only, `^(set_|Set|ISet|Add|IAdd|Insert|IInsert|...|Create|ICreate|...)`,
so five twins of other verbs passed on the drawing families - `IDrawingDoc.IEditSelectedGtol`,
`IMakeCustomSymbol2`, `INewGtol` and `IReorderSheets`, and `IView.ISelectEntity` - and it read the
reader prefixes by their letters, so `Is` took in two writers, `IDrawingDoc.IsolateChangedDimensions`
and `IAssemblyDoc.Isolate`. The twin's `I` may come before every verb now; `Isolate`, the display
writer beside `Hide` and `Show`, is a verb; and the prefixes are whole words. The reader rule is
the one both generators share (`extractor/tools/guard-table-helpers.ps1`), so decision 21A's
creation grammar applies it first too, and its table regenerates unchanged. `IAssemblyDoc` is no
drawing family, so its shared row names `Isolate` (section 1), and `DrawingFamilyCompletenessTests`
holds every name of the 34 interfaces that a prefix takes only by its letters to a refusal (section
5).

On the 2024 SP5 interop (32.5.0.48) it matches 621 distinct names (reflected 2026-09-23, research
R2.2). *Landed as (T004, 2026-09-23)*: the generator, applying this grammar ordinally with the
reader prefixes checked first, finds **633** distinct matches on the 24 families - 40 already
denied, 2 excluded, 591 new - and the shared rows add 30, so the table denies **621** new names.
*Regenerated 2026-09-23 on review* with the 28 families of section 1: **646** distinct matches -
41 already denied, 2 excluded, 603 new - and the shared rows' 30, so the table denies **633** new
names. The generated table is the count, never this paragraph. A false positive costs nothing: the
extractor never calls a writer, and section 5's audit proves no read is refused. *Regenerated
2026-10-19 (owner decision 136A)*: the shared rows' new names are 70, so the table denies **673**
new names; the 28 families' 646 matches are unchanged. *Regenerated 2026-10-19 (owner decision
140A)*: `Close`, `Save` and `Rebuild` join them, so the table denies **676** new names, then the
55 names of section 1's last amendment, so it denies **731**, and on the decision's review
`IFeatureManager`'s two, so it denies **733**; the 28 families' 646 matches are unchanged.
*Regenerated 2026-10-19 (owner decision 144A)*: the 28 families' matches are **652** - the five
twins and `IsolateChangedDimensions` - and the table denies **757** new names: those six,
`NewDocument` and `MoveToFolder` on the `ISldWorks` and `IFeatureManager` rows, and the
`IAssemblyDoc` row's sixteen. *Regenerated 2026-10-20 (owner decision 148A)*: `OpenDoc7` on the
`ISldWorks` row, so the table denies **758** new names; the 28 families' 652 matches are unchanged.

*Measured 2026-10-20 (owner decision 151A; research R13.2), and not changed*: the verbs are read as
prefixes. Read as whole words - a verb followed by an uppercase letter, a digit or the end of the
name, the twin's `I` before it as now - the regenerated table would lose seven writers of
`IDrawingDoc` and gain none: `Dimensions` (the verb `Dimension` followed by `s`) and `SetupSheet` to
`SetupSheet6` (`Set` followed by `up`), its matches falling to 645 and its new names to 751. The
decision made the change conditional on the table losing no name, so this grammar, its copy in the
tests and both tables stand as they are; decision 21A's table regenerated unchanged either way.

## 3. Exclusions, each with its reason

| Bare name | Why it is not denied |
|---|---|
| `set_Name`, `Select2` (drawing families), `CloseDoc`, `SetUserPreferenceToggle` (shared) | Feature 004's stage-1 allowlist has a key with this bare name (`IFeature.set_Name`, `IFeature.Select2`, `ISldWorks.CloseDoc`, `ISldWorks.SetUserPreferenceToggle`); denying the bare name would make that key override a read-only denial and move `Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredOnes` (*named `...DeclaredFive` until owner decision 148A, 2026-10-20, which made the keys six; the name amended here on its review, research R12.8*) |
| `OpenDoc6` | The console attach's read-only open of a model (`SwSession.OpenReadOnly`), for parts and assemblies only (`attach.md` section 4), checked with `IsOpenedReadOnly` after it (decision 136A). *Corrected 2026-10-19 (owner decision 137A)*: this row called it the extractor's one sanctioned read-only open; the confirmed drawing's open below is another, and feature 004's `OpenDoc7` opens (next row) are file-opening calls too. The read-only open of a confirmed drawing does not ride on this exclusion: it calls the qualified key `ISldWorks.OpenDoc6` through its own allowlist guard (section 7) |
| `OpenDoc7`, `NewDocument` (shared) | *Withdrawn 2026-10-20 (owner decision 148A): `OpenDoc7` is refused now too - `remodel.open` names it by its key on `RemodelGuard`'s stage-1 allowlist and `probe remodel`'s reopen by the same key among `RemodelProbeGuard`'s run-scoped members, as the pane seat does under its own guard (section 1) - so the row holds no name. It stays as the record of why they were exclusions.* *Added 2026-09-23 by T003's read audit*: feature 004 calls them by their bare names on sanctioned paths - `OpenDoc7` opens the re-modeler's own copy (`remodel.open`, under `RemodelGuard`) and reopens `probe remodel`'s throwaway part, and `NewDocument` creates that part (under `RemodelProbeGuard`, which exempts only what `ReadOnlyGuard` refused when it was written). Denying them would break both; the research's collision check had read only literal call-site names, and these two are named through constants. *Amended 2026-10-19 (owner decision 144A)*: `NewDocument` is refused now - only `probe remodel` calls it, and `RemodelProbeGuard`'s run-scoped members exempt the bare name its host gates (section 1) - and this row holds `OpenDoc7` alone, which the re-modeler's pane seat also calls, by the qualified key its own guard allows (section 8) |
| a member `RemodelGuard` refuses itself (`ExcludedMembers`) | `RemodelExclusions_AreOnlyMembersTheReadOnlyGuardDoesNotAlreadyRefuse` forbids `ReadOnlyGuard` to refuse them; none matched on 32.5.0.48, and the generator excludes them should a later interop add one. *Amended 2026-10-19 (owner decision 140A)*: `SetReadOnlyState`, one of them, is named on the `IModelDoc2` row now, so it left `RemodelGuard.ExcludedMembers` rather than be refused in two places, as that test asks; `RemodelGuard` still refuses it, qualified by its rule for a key off the allowlist and bare by `ReadOnlyGuard`'s answer |
| `Close` (`IModelDoc2`, shared) | *Withdrawn 2026-10-19 (owner decision 140A): `Close` is refused now, since the bridge judges its commands against its own fixed set and hands no command name to `ReadOnlyGuard` (section 1). The row stays as the record of why it was an exclusion.* *Added 2026-10-19 (owner decision 136A)*: the member half of the bridge command `remodel.close`. `BridgeDispatcher.Dispatch` hands every command name to `ReadOnlyGuard`, which judges a qualified name by its member half, so denying the bare name refused `remodel.close` (the remodel tests went red when it was tried). No product path calls `IModelDoc2.Close`; its qualified spelling is refused by the allowlist guards, `RemodelGuard` and `DrawingOpenGuard`, and `DocumentLifecycleFamilyTests.NoCommandTheBridgeAnswersIsRefusedByTheReadOnlyGuard` keeps every command name off the denials |
| `MoveToFolder` (`IFeatureManager`, shared) | *Withdrawn 2026-10-19 (owner decision 144A): `MoveToFolder` is refused now, and `RemodelProbeGuard`'s run-scoped members exempt the bare name its host gates (section 1); `RemodelGuardTests`' example of a bare writer the denylist misses is `IModelDoc2.DeleteConfiguration2` (research R10.4 item 3). The row stays as the record of why it was an exclusion.* *Added 2026-10-19 (owner decision 140A, on its review)*: `probe remodel`'s PROBE-5 moves a feature of its throwaway part into a folder; `SwRemodelProbeHost` gates the bare name under `RemodelProbeGuard`, which hands it to `ReadOnlyGuard`, as it does `NewDocument`. Never the engineer's document: `probe remodel` refuses to run while one is open. `RemodelGuardTests` keeps it as its example of a bare writer the denylist misses, the reason the re-modeler's writes are interface-qualified |
| `SaveBMP` (`IModelDoc2`, shared) | *Added 2026-10-19 (owner decision 140A)*: the capture's image of a view. `SwCaptureView` gates the bare name on the session's read-only gate and has it write a bitmap of the graphics window beside the capture's PNG, at the PNG's name with `.bmp`, which the capture then turns into the PNG. `SaveBMP` writes to whatever path it is handed, a document's included, and a guard judges names, never paths: what keeps this path an image is the capture's own code, which names the PNG under the `captures` folder of the directory the host chose and checks its extension with `ReadOnlyGuard.AssertSaveAs` first. `SaveAs3` stays refused, and so does the rest of the save family (section 1). *Corrected on the decision's review (2026-10-19)*: this said `SaveBMP` cannot write a document |

Names already denied (41 of the 646 grammar matches, from features 001, 006 and 010, or by a
denied prefix; the generated table is the count) are listed in the table's "already denied" column
and are not added twice. *Corrected 2026-09-23 on review*: this paragraph had kept the pre-landing
research figure, "39 of the 621", which the generator never produced. `CloseDoc`,
`SetUserPreferenceToggle` and `OpenDoc6` are on no row of section 1 and match no grammar on the 28
families, so the generated exclusion table names only what a row or the grammar reached:
`set_Name`, `Select2`, `OpenDoc7` and `NewDocument`. *Amended 2026-10-19 (owner decision 136A)*:
`OpenDoc6` and `CloseDoc` are now on the `ISldWorks` row and `Close` on the `IModelDoc2` row, so the
generated exclusion table names them too, each with its reason. *Amended 2026-10-19 (owner decision
140A)*: `Close` is refused, so the generated exclusion table no longer names it, and `SaveBMP`,
now on the `IModelDoc2` row, and `MoveToFolder`, on the `IFeatureManager` row, join it. *Amended
2026-10-19 (owner decision 144A)*: `NewDocument` and `MoveToFolder` are refused, so the generated
exclusion table no longer names them. *Amended 2026-10-20 (owner decision 148A)*: neither does it
name `OpenDoc7`, which is refused - the first bare name of a stage-1 allowlist key the table refuses,
on purpose: the first row's reason, that denying it would make the key override a read-only denial,
is the decision's intent for `ISldWorks.OpenDoc7`, the sixth key that does. The generator withdraws
both its named exclusion and the structural one, and the structural reason names the overriding-keys
test by its new name, `Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredOnes`.

## 4. The table, generated

`extractor/tools/list-writer-members.ps1` loads the interop from `$SwRedist` (the path
`Directory.Build.props` names) as metadata, applies sections 1 to 3, and prints the "Feature 011"
section of `specs/004-resilient-remodeler/contracts/guard-allowlist.md`: one row per interface,
`| Interface | Members refused | Already denied |`, members in ordinal order, then the shared rows,
then the exclusion rows. *Landed as (T004)*: two columns, `| Members refused (feature 011) |
Interface; already denied |`, because `DenylistTable.Parse` reads the members from the first cell
and requires two; a row only for an interface with at least one new name (the one whose writers
were all denied already, `IGtolFrame`, and the three with no writer are named in a sentence under
the table); then a `| Not denied (feature 011) | Why |` table. The "already denied" set and the
exclusions are read from `Guard/ReadOnlyGuard.cs` and `Guard/RemodelGuard.cs` themselves.
`ReadOnlyGuard.Drawing.cs` holds one `string[]` merged into the denied set by a static
constructor in `ReadOnlyGuard.cs`, which runs after both files' field initializers. **The table is regenerated, never transcribed**; the script's output is
pasted whole, and `ReadOnlyGuard`'s feature 011 block (`Guard/ReadOnlyGuard.Drawing.cs`, a
`partial` of the static class holding one `string[]`) is generated from the same run. Both land in
one commit with the tests of section 5.

*Noted 2026-09-25 (feature 004, the owner's decision 21A)*: the script's metadata-only loader, its
reading of the guard sources, section 3's two structural exclusions and its name formatting now live
in `extractor/tools/guard-table-helpers.ps1`, shared with `extractor/tools/list-creation-members.ps1`,
which generates 004's separate creation-family table ("Decision 21A" in `guard-allowlist.md`,
`Guard/ReadOnlyGuard.Creation.cs`). This contract's table is not shared: the script's output, and so
the "Feature 011" section and `ReadOnlyGuard.Drawing.cs`, were checked byte-identical after the move.

## 5. The tests

In `extractor/SwReview.Extractor.Tests/GuardTests.cs`:

| Test class | Asserts |
|---|---|
| `DrawingFamilyDenylistTests` | parses the "Feature 011" table (`DenylistTable.Parse`, as `MechanicalChecksDenylistTests` does); every member is refused by `ReadOnlyGuard.Assert` and `ReadOnlyCallGuard.Instance.Assert` |
| `DrawingFamilyCompletenessTests` | reflects the 28 interfaces at test time and applies the grammar: every match is refused, or is an excluded name of section 3; the shared rows are refused. *Amended 2026-10-19 (owner decision 144A)*: the grammar it applies is section 2's as amended - every verb's twin, `Isolate`, the reader prefixes as whole words - which a theory pins case by case, and `EveryNameTheReaderPrefixesTookOnlyByTheirLettersIsRefusedByEveryGate` reflects the 34 interfaces the generated tables are written against and holds every name a reader prefix starts by its letters but not as a word (on 32.5.0.48 `IAssemblyDoc.Isolate` and `IDrawingDoc.IsolateChangedDimensions`) to a refusal, bare and qualified, by every gate the product builds |
| `DrawingFamilyReadAuditTests` | no bare name the extractor gates (every `SwGate.Call`/`CallOptional` literal in `extractor/SwReview.Extractor`, collected by a source scan) is refused, except the write-refusal tests' own names and the re-modeler's write sites. *Landed as (T003)*: every string literal of the product source - `SwReview.Extractor`, `SwReview.AddIn` and `SwReview.Extractor.Console`, the `Guard` folder's own tables excepted - that the table refuses must be one of four named literals that are not gated calls (two members `probe standards` asserts it never calls, a JSON property name, a remodel operation name); a superset that also reaches names passed through constants and read helpers. *Amended 2026-09-27 by feature 004 T156 (default taken 2026-09-27, the owner may revise)*: six named literals - the frozen interop manifest's builder table (`Rms/RemodelInteropSurface.cs`) now records the re-modeler's open request, whose `IDocumentSpecification.set_ReadOnly` (set false, never gated: a property of a throwaway request, as 004's `guard-allowlist.md` leaves `Silent` and `LoadModel`) and the parameter name of `set_LoadModel` match the refused `IDimension`/`INote.set_ReadOnly` and `IView.LoadModel` by name only. *Amended 2026-10-19 (owner decision 140A)*: a line that is a comment and nothing else is not read (a word quoted in a comment is no string the program holds; `<see cref="Close"/>` names a C# method), the named literals are matched exactly rather than in any case (so a lower-case word the product uses for something else cannot exempt the member's own spelling), and refusing `Close`, `Save` and `Rebuild` named eight more: the bridge commands `remodel.close`, `remodel.save` and `remodel.rebuild`, judged by the part after the dot; the clean-up label `close`; the plan's JSON member `rebuild`; and the Review page's message types `events.close`, `send_when_checked.save` and `settings.save`. *Amended on the decision's second review (research R10.5)*: each named literal is keyed by the literal and the file it stands in, so it exempts its spelling there and nowhere else (decision 21A's `CreationFamilyReadAuditTests` keys its `scale` the same way); the keying found `ActivateDoc3` in `Rms/RemodelInteropSurface.cs` too, the frozen interop manifest's row for the pane seat's direct call, named now with its own reason. *And on its second pass*: a file is named by its path under the extractor folder (`SwReview.Extractor/Capture/SwCaptureView.cs`), so a file of the same name elsewhere is another file; it was named by its name, with a check that no two product files shared one, which failed for any two that did. *Amended 2026-10-19 (owner decision 144A)*: the pane seat's guard is a third allowlist guard, whose two keys the audit judges whole in the seat's own file alone, and `TheSeatsOwnKeysAreLiteralsOfItsOwnFileAlone` pins that no other product file names either (section 1); and a literal of `probe remodel`'s host that `RemodelProbeGuard` lets through is the probe's own call, judged by its own gate, as decision 21A's audit judges the probe's creation calls - `TheProbesOwnCallsAreExactlyItsTwoWritersAndOnlyItsGuardLetsThemThrough` pins them, `NewDocument` and `MoveToFolder`, so a later literal of the probe host the table refuses fails until someone decides what it is. *Amended 2026-10-20 (owner decision 148A)*: the two literals of the bare `OpenDoc7` that are no gated call - `probe standards`' absent list in `Program.cs` and the frozen manifest's row - are named literals, each by its file; `TheSeatsOwnKeysAreLiteralsOfItsOwnFileAlone` is now `TheSeatsKeysAreLiteralsOfTheFilesWhoseGuardsLetThemThroughAlone` (section 1); and `TheOpensTwoOtherCallersNameItByItsQualifiedKeyAndNeverBare` holds the dispatcher and the probe host to the key. *Amended on the decision's review (research R12.8)*: `TheProbesOwnCallsAreExactlyItsTwoWritersAndOnlyItsGuardLetsThemThrough`, now `TheProbesOwnCallsAreExactlyTheDeclaredWritersAndOnlyTheirCallersGuardsLetThemThrough`, reads the probe host's literals by their member half, where `Judged` reads a key of `RemodelGuard` whole, so it sees the probe's third writer, its reopen by `ISldWorks.OpenDoc7`, and pins it let through by exactly the guards of its three callers. *Amended 2026-10-20 (owner decision 151A)*: `Judged` reads every allowlist guard's keys through their shared rule (section 9), each keyed by the files that build it (`BuildersOf`), as the seat's were since decision 144A's review, so `IsTheSeatsOwnKey` is its own case and is gone; `AnAllowlistGuardsKeyIsJudgedWholeOnlyInAFileThatBuildsThatGuard` pins the rule, case by case. *Amended on the decision's review (research R13.6)*: `NoProductFileButAnAllowlistGuardsBuildersNamesItButForTheNamedLines` holds `BuildersOf` to the source, every allowlist guard's construction-site test - no product file but a guard's builders names it, on a line that is not a comment, but for two lines held exactly that build nothing (`NamingsThatBuildNothing`), and each builder builds it; it replaces `EachAllowlistGuardIsBuiltInExactlyTheFilesTheAuditReadsItsKeysWholeIn`, which read `new X(` and `X x = new()` alone and was no construction-site test |
| `DocumentLifecycleFamilyTests` | *Added 2026-10-19 (owner decision 136A)*: reflects `ISldWorks`, `IModelDoc2` and `IModelDocExtension` and applies section 1's family grammar; every member is a reader, which stays allowed in both spellings, one of the explicit exclusions it names with its reason (`OpenDoc6`, `OpenDoc7`, `CloseDoc`, `NewDocument`, `IModelDoc2.Close`, each also on the generated "Not denied" table), or refused bare and qualified by `ReadOnlyGuard` and by every gate the product builds; a floor and the spellings decision 136A names; and no bridge command's name is refused. *Amended 2026-10-19 (owner decision 140A)*: `IModelDoc2.Close` left the exclusions, and the last pin gave way to `CloseSaveAndRebuildAreRefusedInEverySpellingByEveryGate` - `Close`, `Save` and `Rebuild`, bare and qualified with each of the three interfaces that declares them, refused by every gate the product builds. The bridge's own rule is `BridgeDispatcherTests`' ("the bridge's own commands"): it answers exactly its eighteen commands and refuses every other name as unknown before anything runs, and `RemodelFinishHandlerTests` shows `remodel.rebuild`, `remodel.save` and `remodel.close` answering, their writes judged by `RemodelGuard`. *Amended 2026-10-19 (owner decision 144A)*: it reads `IAssemblyDoc` as a fourth interface and pins the fifteen members it finds there; `NewDocument` left its exclusions; and every gate the product builds lets through exactly the exceptions it names, each with its reason and still a literal of the file whose call needs it - `RemodelProbeGuard` the bare `NewDocument` and `RemodelSeatGuard` `ISldWorks.ActivateDoc3` - the two checks `DocumentWriteFamilyTests` makes, which the classes share (`GuardSweep`). *Amended 2026-10-20 (owner decision 148A)*: `OpenDoc7` left its exclusions, and its key is three exceptions - `RemodelGuard`, `RemodelProbeGuard` and `RemodelSeatGuard` `ISldWorks.OpenDoc7`, each with the file whose call needs it; `DrawingFamilyDenylistTests.TheBareOpenDoc7IsRefusedByEveryGateAndOnlyTheGuardsOfItsCallersLetItsKeyThrough` sweeps both spellings over every gate the product builds |
| `DocumentWriteFamilyTests` | *Added 2026-10-19 (owner decision 140A)*: reflects the 34 interfaces the generated tables are written against - `ISldWorks`, `IModelDoc2`, `IModelDocExtension`, `IPartDoc`, `IAssemblyDoc`, decision 21A's `IFeatureManager` and the 28 drawing families of section 1, widened to the last two on the decision's review - and applies section 1's second family grammar (`Save`, `Rename`, `Move`, `Copy`, `Replace`, `Release`, `Lock`, `Unlock`, `ReadOnly`, `Rebuild`, as whole words): the grammar reads whole words; a floor, and the members research R8.5 and 004's `guard-allowlist.md` named are found; every member is a reader, which stays allowed in both spellings, the exclusions it names with their reasons (`SaveBMP` and `MoveToFolder`, each on the generated "Not denied" table and still a literal of the file whose call needs it, the capture's and `probe remodel`'s), or refused bare and qualified by `ReadOnlyGuard`; and every gate the product builds lets through exactly the exceptions it names, each with its reason and still a literal of the file whose call needs it - `SuppressTestGuard` the bare `ForceRebuild3`, `RemodelProbeGuard` the bare `ForceRebuild3` and `SaveAs3`, `RemodelGuard` `IModelDoc2.ForceRebuild3` and `IModelDoc2.Save3` - so a guard that comes to let another member through, or no longer needs one of these, fails it. *Amended 2026-10-19 (owner decision 144A)*: `MoveToFolder` left the members left allowed for the exceptions, `RemodelProbeGuard` letting the bare name through; `SaveBMP` alone is left allowed |
| `GuardSweepTests` | *Added 2026-10-19 (owner decision 144A)*: `GuardSweep.ProductGates`, the guards every sweep of this section and of decision 21A's tests reads, holds one of every `ICallGuard` the extractor's and the console's assemblies define, and no source file of the three projects outside the extractor's `Guard` folder declares one - a class, a struct or a record - while the add-in suite's `TheAddInDefinesNoGuardOfItsOwn` reads the add-in's assembly; so a guard added later - the pane seat's was the sixth - cannot be left out of the sweeps. *Amended 2026-10-20 (owner decision 151A)*: the declaration it looks for names `AllowlistGuard` as well as `ICallGuard`, since a guard built on the shared rule (section 9) names only the base; and `GuardSweep.AllowlistGuards` is those of the product's gates built on it, which the sweeps read each guard's keys and policy through |
| `AllowlistGuardAnswersTests`, `AllowlistGuardTests` | *Added 2026-10-20 (owner decision 151A; research R13.1; on its review, R13.6, the rule's invariant as a guard is built)*: section 9's rule. The first holds every allowlist guard's answer - allowed, refused naming the same member in the same words, or the same argument error - to its answer before the decision, each guard's own `Assert` at `5685def` kept verbatim as the oracle, for every name the generated tables and the product use and, where the interop is installed, every member of the 34 interfaces, bare and qualified, each in four spellings; written before the code moved. The second: the product's allowlist guards are exactly the three; each answers through the one shared `Assert`, which none overrides or implements again; each one's keys and bare-name policy, read through the base, are its own; the shared rule for each, through its keys and policy; and `RemodelGuard`'s fourth answer, its own refusal by name, before the rest of the rule |
| `RemodelSeatGuardTests`; the add-in's `SwRemodelSeatTests` | *Added 2026-10-19 (owner decision 144A)*: section 8's allowlist, its refusals, its bare reads, and that no product file but the seat names the guard or its gate; and the seat's every call, placed under the gate entry it is made under, its open options, its scope and its gate log. *Amended 2026-10-20 (owner decision 148A)*: the closed allowlist - its five reads exactly, each a bare name the read-only guard allows, every other name refused, bare or qualified, and the members the seat's gate is asked about, way by way, exactly the list's seven; and the seat held to the one rule for the copy's path by the forms the bridge's tests read (`RemodelCopyPathForms`) |

`RemodelGuardTests.ExpectedDeniedMembers` gains the table's names (it lists the guard's denials
from both ends); the five overriding keys and `RemodelGuard.ExcludedMembers` are unchanged and
their tests pass unedited. *Amended 2026-10-19 (owner decision 140A)*: `SetReadOnlyState` left
`RemodelGuard.ExcludedMembers` when the table came to refuse it, and
`RemodelGuardTests.ExpectedRemodelExclusions` was edited deliberately to match, as
`RemodelExclusions_AreOnlyMembersTheReadOnlyGuardDoesNotAlreadyRefuse` asks; the five overriding
keys are unchanged and their test passes unedited. *Amended 2026-10-20 (owner decision 148A)*: the
table refuses the bare `OpenDoc7`, and its key joined the stage-1 allowlist, so the keys that
override a read-only denial are six: `KeysThatOverrideAReadOnlyDenial` and the allowlist's table were
edited deliberately, the test renamed `Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredOnes`,
and `NoMemberOfTheTableIsTheBareNameOfAStage1AllowlistKey`, renamed
`OnlyTheNamedMembersOfTheTableAreBareNamesOfStage1AllowlistKeys` on the decision's review (research
R12.8), names that one.

## 6. What an extraction's gate log shows (FR-007)

For every extraction that reads a drawing: no member of this contract's denials, no
`ActivateSheet`, `ActivateView` or `ActivateDoc*`, and no `OpenDoc*`. `PackageWriterTests` asserts
it with the recording observer over the fake drawing reader; T062 records it at the seat. The read
of a confirmed drawing (section 7) shows exactly `ISldWorks.DocumentVisible`, `ISldWorks.OpenDoc6`
and `ISldWorks.CloseDoc` under their qualified keys when it opened the drawing, none of them when
the drawing was already open, and nothing else from the denials. *Amended 2026-10-19 (owner
decision 136A)*: when it opened the drawing it also shows the bare read `IsOpenedReadOnly`, the
check of section 7, after the open.

## 7. The confirmed drawing's read-only open: an allowlist of its own (owner, 2026-09-23)

The owner's answer to research R5 Q2 lets the product open a candidate the engineer confirms,
read-only, "through the guarded seam, with its own allowlist entry". `Guard/DrawingOpenGuard.cs`
is that entry: an `ICallGuard` allowing exactly `ISldWorks.DocumentVisible`, `ISldWorks.OpenDoc6`
and `ISldWorks.CloseDoc` (ordinal), refusing every other qualified key, and handing every bare
name to `ReadOnlyGuard` unchanged - the shape of feature 004's `RemodelGuard`, built only by
`Sw/DrawingOpenScope.cs` (`confirmed-open.md` section 3). Of the three keys, only
`DocumentVisible` overrides a read-only denial (section 1's shared row); a test pins that set.
The entry is recorded in `specs/004-resilient-remodeler/contracts/guard-allowlist.md` beside the
stage-1 list, and it widens neither `RemodelGuard` nor `ReadOnlyGuard`. *Amended 2026-10-20 (owner
decision 151A)*: its three answers are the shared rule's (section 9), its bare names the read-only
guard's answer; the guard keeps its three keys, its words for a refusal and its one construction
site, and answers every name as it did.

*Amended 2026-10-19 (owner decision 136A): the runtime check.* After the open the seam asks the
drawing `IModelDoc2.IsOpenedReadOnly()` under its bare name - a read, which this guard hands to
`ReadOnlyGuard` unchanged, so the allowlist stays the three keys - and refuses and closes, unread, a
drawing SOLIDWORKS did not open read-only or will not say (`confirmed-open.md` section 3). The
console attach makes the same check after its own `OpenDoc6` (`attach.md` section 4). Neither
asks, or ever closes, a document the open says SOLIDWORKS already had open (on the decision's
review, the same day): that open did not open it.
`DrawingOpenGuardTests.TheReadOnlyCheckIsABareReadEveryGuardAllows` pins that every gate the product
builds allows the bare name, and that this guard refuses the qualified `IModelDoc2.IsOpenedReadOnly`,
which is why the seam names it bare. *Amended 2026-10-20 (owner decision 148A and its review, research
R12.1 and R12.8)*: every gate but the pane seat's, whose guard is a closed allowlist since that
decision and refuses a read the seat never makes; the test, renamed
`TheReadOnlyCheckIsABareReadEveryGuardButThePaneSeatsAllows`, asserts that refusal.

## 8. The re-modeler's pane seat: an allowlist of its own (owner decision 144A, 2026-10-19)

Research R10.4 item 6 found that the re-modeler's pane seat - the add-in's
`Remodel/SwRemodelSeat.cs`: `remodel.open_copy`, and the activation of the run's copy before each
dump (feature 004 T159) - called the interop directly, on the application thread, through no gate:
`GetOpenDocumentByName`, `GetTitle`, `ActivateDoc3` (which section 1's shared row has refused since
T004), a writable `OpenDoc7` of the run's copy, `ActiveDoc` and `GetPathName`. The owner's decision
144A puts it behind a gate (research R11.1).

`Guard/RemodelSeatGuard.cs` is the seat's guard: an `ICallGuard` in the shape of section 7's
`DrawingOpenGuard`, allowing exactly `ISldWorks.ActivateDoc3` and `ISldWorks.OpenDoc7` (ordinal),
refusing every other qualified key, and handing every bare name to `ReadOnlyGuard` unchanged.
*Amended 2026-10-20 (owner decision 148A; research R12.1)*: a closed allowlist - the two keys and the
five reads the seat makes, by their bare names, each matched ordinally, and every other name, bare or
qualified, refused, naming it; the bare `CloseDoc`, `OpenDoc6` and `OpenDoc7` that passed it are
refused. No read is handed to `ReadOnlyGuard` at run time: a test holds each read on the list to a
bare name that guard allows. Each
action of the seat builds its own gate on it, with a breaker of its own, and makes every interop call
through it: the reads under their bare names (`GetOpenDocumentByName`, `GetPathName`, `GetTitle`,
`ActiveDoc`, `GetOpenDocSpec`), the activation and the open under the two keys. The open request's
property sets are made inside the `GetOpenDocSpec` gate entry, and its load bits read back inside the
open's, as the bridge makes them inside its own open: they set a throwaway request, not a document.
Of the two keys only `ActivateDoc3` overrides a read-only denial; `OpenDoc7` is an exclusion of
section 3. *Amended 2026-10-20 (owner decision 148A)*: both do now - the bare `OpenDoc7` is refused,
and `ISldWorks.OpenDoc7` is `RemodelGuard`'s and `RemodelProbeGuard`'s key too, for `remodel.open` and
`probe remodel`'s reopen (section 1). The seat is the guard's one construction site. The entry is recorded in
`specs/004-resilient-remodeler/contracts/guard-allowlist.md` beside the confirmed drawing's, and it
widens neither `RemodelGuard`, `DrawingOpenGuard` nor `ReadOnlyGuard`. *Amended 2026-10-20 (owner
decision 151A)*: its answers are the shared rule's (section 9), its bare names its five reads alone;
the guard keeps its two keys, its reads, its one sentence for any name off its list and its one
construction site, and answers every name as it did.

**Only the run's copy.** The constitution's exception lets the re-modeler create and modify one
document, its run's copy, and every other exception the product builds is scoped to its own
documents (research R11.1), so the seat's is too. A guard sees names, never documents, so the scope
is the seat's own second layer, as `RemodelScope` is `RemodelGuard`'s. Before any call, a path that
is not the run's copy is refused (`Remodel/RemodelSeatCopyPath.cs`): it must be a full path, a
drive's or a share's - never one relative to a drive's folder or to the current drive's root, nor a
device path - with no `..`, to a part (`.SLDPRT`) inside a run folder's `copy/`
(`RemodelCopy.RunDirectoryOf`'s rule), the run folder not the root of a drive or a share; from then on
the seat uses the canonical form it checked, for every call and comparison. A document the lookup
answers is asked its title and activated only if its own path is the copy's; for `remodel.open_copy`
the document the activation answers must be the copy too, since `ActivateDoc3` activates by title;
and a document the open answers is taken as the copy only if its own path is the copy's. A document
that is not is refused and left as it is - never activated, closed or named. Which run's copy it is,
the seat cannot tell: the pipeline resolves it from a run this host made. *Amended 2026-10-20 (owner
decision 148A; research R12.3 to R12.5)*: the path rule is `RemodelCopy.CopyOf` in the extractor, the
one rule both seats take the copy by - the bridge's `remodel.open` too, at its step 4 - and
`RemodelSeatCopyPath` is the seat's door to it; every run folder is made in its full form, so the
copy the seat is handed carries no `..`. Open copy is refused while a remodel run is in progress
(`RunInProgress`), and the page offers it no more than Discard copy during a run - nor, with Discard
copy, while a plan is made (*on the decision's second review, research R12.8a*). Whether activating
or opening the run's copy is a write - the constitution's 2(b) - is answered by the draft constitution
amendment (pull request #4): it is not, the copy's path check being its scope.

**The gate log.** Each action writes two lines to the run folder's `remodel.log`, on the application
thread: `seat=open_copy begin` or `seat=activate_before_dump begin` before its first call, so an action
SOLIDWORKS never returns from still leaves a line, as every bridge request's begin line does; and
after its last, `status=ok` with `outcome=` how it ended (`activated` or `opened`, and for the
activation before a dump, which answers rather than refuses, `not_open`, `not_the_copy` or
`not_activated`), or `status=error`; then `gated=` the distinct members its gate was asked about in
the order first seen, and `refused=` and `error=<exception type>` when they apply. A line never
carries `target=`, the field the report counts writes by, and never a path. With the seat working,
the closing lines read:

```text
seat=activate_before_dump status=ok outcome=activated gated=GetOpenDocumentByName,GetPathName,GetTitle,ISldWorks.ActivateDoc3,ActiveDoc
seat=open_copy status=ok outcome=activated gated=GetOpenDocumentByName,GetPathName,GetTitle,ISldWorks.ActivateDoc3
seat=open_copy status=ok outcome=opened gated=GetOpenDocumentByName,GetOpenDocSpec,ISldWorks.OpenDoc7,GetPathName
```

(the second when SOLIDWORKS has the copy open - its path asked once of the copy found and once of
the copy activated - the third when it opens it again). `RemodelSeatGuardTests` pins the allowlist
and that no product file but the seat names the guard or its gate, and the add-in's
`SwRemodelSeatTests` the seat's every call, placed under the gate entry it is made under, its open
options (`Silent | LoadModel = 17`, never `ReadOnly` or `ViewOnly`), its scope and its log; section 5
says how the sweeps read the guard, and the read audit exempts the seat's two keys in the seat's own
file alone. *Amended 2026-10-20 (decision 144A's second review, T178)*: the scope both ways - the
fourteen paths the seat refuses, and six it takes, the run-root forms a pilot most likely has (a
share's path with either separator, a run folder directly under a share's or a mapped drive's root,
spaces, the copy folder and extension in another case) - and a copy whose path SOLIDWORKS answers in
another letter case. Task T171 runs it at the next sitting, amended for decision 148A to read
`remodel.open`'s request line and PROBE-12's reopen too (research R12.6).

## 9. The allowlist guards' one rule (owner decision 151A, 2026-10-20)

The product's three allowlist guards - the confirmed drawing's (section 7), the pane seat's (section
8) and feature 004's stage-1 `RemodelGuard` - each wrote the same rule in its own code, and the tests
named each by its type (research R11.8 item 6). `Guard/AllowlistGuard.cs` holds it once, and the three
answer through it. In order:

1. a missing name is an argument error, and any other is judged trimmed;
2. one of the guard's own interface-qualified keys, matched **ordinally**, passes;
3. a name the guard refuses by name itself is refused, however it is spelled - only `RemodelGuard`
   refuses any, its `ExcludedMembers`, the fourth answer it keeps as its own (`RefuseByName`);
4. any other interface-qualified key is refused, naming it, in the guard's own words; and
5. a bare name is answered by the guard's policy: the read-only guard's answer, unchanged, for the
   confirmed drawing's guard and the stage-1 guard (`ReadOnlyGuardsAnswer`); the seat's five reads
   alone, every other bare name refused naming it, for the pane seat's (`OwnReadsOnly`).

Each guard keeps its own list, its words, its matching - exact and ordinal - and its construction
sites. The rule's `Assert` cannot be overridden, and its one hook, step 3, can refuse and never allow.
*Amended on the decision's review (research R13.6)*: the rule holds its own invariant as a guard is
built - every key interface-qualified, every read a bare member name, not blank and with no separator -
and a guard built otherwise fails then, before it is asked anything; and each guard is named only in
the product files that build it but for two named lines that build nothing
(`NoProductFileButAnAllowlistGuardsBuildersNamesItButForTheNamedLines`), so the files the read audit
reads a guard's keys whole in are the files its gate is built in.
`RemodelProbeGuard` and `SuppressTestGuard` are exemptions over the read-only guard, not allowlists -
they pass a name on their lists matched ignoring case and hand every other, qualified or bare, to the
read-only guard - so they are not built on it: it would answer otherwise for them. *Amended 2026-10-21
(owner decision 160A; research R14.1):* the probe's run-scoped members are matched ordinally, and a case
variant of one is refused before the read-only guard is asked, which allows the two system-setting
members by name; the probe's creation exemption and `SuppressTestGuard`'s list are matched ignoring case,
as before.

*Added 2026-10-21 (owner decision 160A; research R14.2):* every list a guard publishes - the six statics
(`DrawingOpenGuard.AllowedKeys`, `RemodelSeatGuard.AllowedKeys` and `AllowedReads`,
`RemodelGuard.AllowedKeys` and `ExcludedMembers`, `RemodelProbeGuard.ThrowawayPartCreationMembers`) and
the base's `Keys` and `Reads` - is a read-only view over the guard's own set (`ReadOnlySet`), which
implements no `ICollection<string>` or `ISet<string>`: it counts and enumerates as before, and no cast
reaches the set a guard matches, the one `RemodelGuard.IsAllowlisted` reads among them.

The tests read each guard's keys and bare-name policy through the rule (`Keys`, `BareNames`,
`Reads`): the read audit's `Judged`, which judges a key of an allowlist guard whole only in a file
that builds that guard (section 1); the creation tests' `AllowlistsByName`; and the confirmed open's
read check (section 7). No guard answers any name otherwise than before the decision:
`AllowlistGuardAnswersTests` holds each to its own code as it stood, for every name the generated
tables and the product use (section 5), and each guard's whole answer to 48,560 names was the same,
byte for byte, before and after (research R13.1).
