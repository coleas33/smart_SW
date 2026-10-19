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
three members could not be denied while those commands existed (research R9.1). No product path
calls any of them; the re-modeler's rebuild, save and close are the qualified keys
`IModelDoc2.ForceRebuild3`, `IModelDoc2.Save3` and `ISldWorks.CloseDoc` of its own allowlist.

**Every spelling.** `ReadOnlyGuard.Assert` judges an interface-qualified key
(`IDrawingDoc.ActivateSheet`) by its member half as well as by the whole key, so a read-only gate
refuses every spelling of a denied member, and `DrawingFamilyDenylistTests` asserts each table
member refused qualified with its interface too. *Corrected 2026-09-23 on review*: a qualified key
had passed a read-only gate whatever it named, and the read audit compared literals whole; it now
judges a qualified literal by its member half unless it is a key of `RemodelGuard` or
`DrawingOpenGuard`, the two allowlist guards, which judge their own keys first and are unchanged.
The deliberate exclusions of section 3 (`OpenDoc6`, `CloseDoc`, ...) stay allowed in either
spelling; what keeps a read path from closing a document is that no read call site names one, and
the confirmed drawing's close goes through `DrawingOpenGuard`'s allowlist.

## 2. The writer grammar

A public method of a drawing family is a **writer** when its name does not start with `get_`,
`Get`, `IGet` or `Is`, and matches:

```text
^(set_|Set|ISet|Add|IAdd|Insert|IInsert|Delete|Remove|Edit|Modify|Change|Reset|Activate|Attach|
  Detach|Update|Replace|Break|Hide|Show|Move|Align|Suppress|Unsuppress|Rebuild|Convert|Create|
  ICreate|Make|Lock|Unlock|Sort|Split|Merge|Rotate|Scale|Flip|Link|Unlink|Import|Explode|Clear|
  Apply|Restore|Save|Dissolve|Expand|Collapse|Reload|Rename|New|Paste|Copy|Cut|Drag|Close|Quit|
  Open|Load|Unload|Regenerate|Reorder|Auto|Dimension|Reverse|Swap|Toggle|Enable|Disable|Select|
  Purge|Relink|Resolve|Crop|Unbreak|Force|Hatch|Offset|Position|Freeze|Unfreeze)
```

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
140A)*: `Close`, `Save` and `Rebuild` join them, so the table denies **676** new names; the 28
families' 646 matches are unchanged.

## 3. Exclusions, each with its reason

| Bare name | Why it is not denied |
|---|---|
| `set_Name`, `Select2` (drawing families), `CloseDoc`, `SetUserPreferenceToggle` (shared) | Feature 004's stage-1 allowlist has a key with this bare name (`IFeature.set_Name`, `IFeature.Select2`, `ISldWorks.CloseDoc`, `ISldWorks.SetUserPreferenceToggle`); denying the bare name would make that key override a read-only denial and move `Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive` |
| `OpenDoc6` | The console attach's read-only open of a model (`SwSession.OpenReadOnly`), for parts and assemblies only (`attach.md` section 4), checked with `IsOpenedReadOnly` after it (decision 136A). *Corrected 2026-10-19 (owner decision 137A)*: this row called it the extractor's one sanctioned read-only open; the confirmed drawing's open below is another, and feature 004's `OpenDoc7` opens (next row) are file-opening calls too. The read-only open of a confirmed drawing does not ride on this exclusion: it calls the qualified key `ISldWorks.OpenDoc6` through its own allowlist guard (section 7) |
| `OpenDoc7`, `NewDocument` (shared) | *Added 2026-09-23 by T003's read audit*: feature 004 calls them by their bare names on sanctioned paths - `OpenDoc7` opens the re-modeler's own copy (`remodel.open`, under `RemodelGuard`) and reopens `probe remodel`'s throwaway part, and `NewDocument` creates that part (under `RemodelProbeGuard`, which exempts only what `ReadOnlyGuard` refused when it was written). Denying them would break both; the research's collision check had read only literal call-site names, and these two are named through constants |
| a member `RemodelGuard` refuses itself (`ExcludedMembers`) | `RemodelExclusions_AreOnlyMembersTheReadOnlyGuardDoesNotAlreadyRefuse` forbids `ReadOnlyGuard` to refuse them; none matched on 32.5.0.48, and the generator excludes them should a later interop add one |
| `Close` (`IModelDoc2`, shared) | *Withdrawn 2026-10-19 (owner decision 140A): `Close` is refused now, since the bridge judges its commands against its own fixed set and hands no command name to `ReadOnlyGuard` (section 1). The row stays as the record of why it was an exclusion.* *Added 2026-10-19 (owner decision 136A)*: the member half of the bridge command `remodel.close`. `BridgeDispatcher.Dispatch` hands every command name to `ReadOnlyGuard`, which judges a qualified name by its member half, so denying the bare name refused `remodel.close` (the remodel tests went red when it was tried). No product path calls `IModelDoc2.Close`; its qualified spelling is refused by the allowlist guards, `RemodelGuard` and `DrawingOpenGuard`, and `DocumentLifecycleFamilyTests.NoCommandTheBridgeAnswersIsRefusedByTheReadOnlyGuard` keeps every command name off the denials |

Names already denied (41 of the 646 grammar matches, from features 001, 006 and 010, or by a
denied prefix; the generated table is the count) are listed in the table's "already denied" column
and are not added twice. *Corrected 2026-09-23 on review*: this paragraph had kept the pre-landing
research figure, "39 of the 621", which the generator never produced. `CloseDoc`,
`SetUserPreferenceToggle` and `OpenDoc6` are on no row of section 1 and match no grammar on the 28
families, so the generated exclusion table names only what a row or the grammar reached:
`set_Name`, `Select2`, `OpenDoc7` and `NewDocument`. *Amended 2026-10-19 (owner decision 136A)*:
`OpenDoc6` and `CloseDoc` are now on the `ISldWorks` row and `Close` on the `IModelDoc2` row, so the
generated exclusion table names them too, each with its reason. *Amended 2026-10-19 (owner decision
140A)*: `Close` is refused, so the generated exclusion table no longer names it.

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
| `DrawingFamilyCompletenessTests` | reflects the 28 interfaces at test time and applies the grammar: every match is refused, or is an excluded name of section 3; the shared rows are refused |
| `DrawingFamilyReadAuditTests` | no bare name the extractor gates (every `SwGate.Call`/`CallOptional` literal in `extractor/SwReview.Extractor`, collected by a source scan) is refused, except the write-refusal tests' own names and the re-modeler's write sites. *Landed as (T003)*: every string literal of the product source - `SwReview.Extractor`, `SwReview.AddIn` and `SwReview.Extractor.Console`, the `Guard` folder's own tables excepted - that the table refuses must be one of four named literals that are not gated calls (two members `probe standards` asserts it never calls, a JSON property name, a remodel operation name); a superset that also reaches names passed through constants and read helpers. *Amended 2026-09-27 by feature 004 T156 (default taken 2026-09-27, the owner may revise)*: six named literals - the frozen interop manifest's builder table (`Rms/RemodelInteropSurface.cs`) now records the re-modeler's open request, whose `IDocumentSpecification.set_ReadOnly` (set false, never gated: a property of a throwaway request, as 004's `guard-allowlist.md` leaves `Silent` and `LoadModel`) and the parameter name of `set_LoadModel` match the refused `IDimension`/`INote.set_ReadOnly` and `IView.LoadModel` by name only. *Amended 2026-10-19 (owner decision 140A)*: a line that is a comment and nothing else is not read (a word quoted in a comment is no string the program holds; `<see cref="Close"/>` names a C# method), the named literals are matched exactly rather than in any case (so a lower-case word the product uses for something else cannot exempt the member's own spelling), and refusing `Close`, `Save` and `Rebuild` named eight more: the bridge commands `remodel.close`, `remodel.save` and `remodel.rebuild`, judged by the part after the dot; the clean-up label `close`; the plan's JSON member `rebuild`; and the Review page's message types `events.close`, `send_when_checked.save` and `settings.save` |
| `DocumentLifecycleFamilyTests` | *Added 2026-10-19 (owner decision 136A)*: reflects `ISldWorks`, `IModelDoc2` and `IModelDocExtension` and applies section 1's family grammar; every member is a reader, which stays allowed in both spellings, one of the explicit exclusions it names with its reason (`OpenDoc6`, `OpenDoc7`, `CloseDoc`, `NewDocument`, `IModelDoc2.Close`, each also on the generated "Not denied" table), or refused bare and qualified by `ReadOnlyGuard` and by every gate the product builds; a floor and the spellings decision 136A names; and no bridge command's name is refused. *Amended 2026-10-19 (owner decision 140A)*: `IModelDoc2.Close` left the exclusions, and the last pin gave way to `CloseSaveAndRebuildAreRefusedInEverySpellingByEveryGate` - `Close`, `Save` and `Rebuild`, bare and qualified with each of the three interfaces that declares them, refused by every gate the product builds. The bridge's own rule is `BridgeDispatcherTests`' ("the bridge's own commands"): it answers exactly its eighteen commands and refuses every other name as unknown before anything runs, and `RemodelFinishHandlerTests` shows `remodel.rebuild`, `remodel.save` and `remodel.close` answering, their writes judged by `RemodelGuard` |

`RemodelGuardTests.ExpectedDeniedMembers` gains the table's names (it lists the guard's denials
from both ends); the five overriding keys and `RemodelGuard.ExcludedMembers` are unchanged and
their tests pass unedited.

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
stage-1 list, and it widens neither `RemodelGuard` nor `ReadOnlyGuard`.

*Amended 2026-10-19 (owner decision 136A): the runtime check.* After the open the seam asks the
drawing `IModelDoc2.IsOpenedReadOnly()` under its bare name - a read, which this guard hands to
`ReadOnlyGuard` unchanged, so the allowlist stays the three keys - and refuses and closes, unread, a
drawing SOLIDWORKS did not open read-only or will not say (`confirmed-open.md` section 3). The
console attach makes the same check after its own `OpenDoc6` (`attach.md` section 4). Neither
asks, or ever closes, a document the open says SOLIDWORKS already had open (on the decision's
review, the same day): that open did not open it.
`DrawingOpenGuardTests.TheReadOnlyCheckIsABareReadEveryGuardAllows` pins that every gate the product
builds allows the bare name, and that this guard refuses the qualified `IModelDoc2.IsOpenedReadOnly`,
which is why the seam names it bare.
