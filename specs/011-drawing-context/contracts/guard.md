# Contract: The Guard, Hardened First

Normative for FR-005 to FR-007 and SC-009. Lands before any new drawing read (Phase 2).

## 1. The families

**The 24 drawing families**, every writer of which is refused: `IDrawingDoc`, `ISheet`, `IView`,
`IDisplayDimension`, `IDimension`, `IDimensionTolerance`, `IAnnotation`, `INote`, `IGtol`,
`IGtolFrame`, `IDatumTag`, `ISFSymbol`, `ITableAnnotation`, `IBomTableAnnotation`, `IBomFeature`,
`IRevisionTableAnnotation`, `IGeneralTableFeature`, `ITitleBlockTableFeature`, `ITitleBlock`,
`IDatumTargetSym`, `ICenterMark`, `IWeldSymbol`, `IDowelSymbol`, `IMultiJogLeader`.

**The shared families**, named members only:

| Interface | Members refused | Beside the read |
|---|---|---|
| `ISldWorks` | `ActivateDoc`, `ActivateDoc2`, `ActivateDoc3`, `DocumentVisible`, `CloseAllDocuments`, `CloseAndReopen`, `CloseAndReopen2`, `QuitDoc`, `NewDocument`, `NewDrawing`, `NewDrawing2`, `NewPart`, `NewAssembly`, `OpenDoc`, `OpenDoc2`, `OpenDoc3`, `OpenDoc4`, `OpenDoc7`, `OpenDocSilent`, `OpenModelConfiguration`, `LoadFile2`, `LoadFile3`, `LoadFile4`, `RunMacro`, `RunMacro2`, `RunCommand`, `RunAttachedMacro`, `RunJournalCmd` | `GetDocuments`, `GetDocumentCount` (discovery) |
| `IModelDocExtension` | `SetUserPreferenceInteger`, `SetUserPreferenceString`, `SetUserPreferenceDouble`, `SetUserPreferenceTextFormat` | `GetUserPreferenceInteger`, `GetUserPreferenceString` (the drawing's settings) |

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
denied, 2 excluded, 591 new - and the shared rows add 30, so the table denies **621** new names;
the generated table is the count, never this paragraph. A false positive costs nothing: the
extractor never calls a writer, and section 5's audit proves no read is refused.

## 3. Exclusions, each with its reason

| Bare name | Why it is not denied |
|---|---|
| `set_Name`, `Select2` (drawing families), `CloseDoc`, `SetUserPreferenceToggle` (shared) | Feature 004's stage-1 allowlist has a key with this bare name (`IFeature.set_Name`, `IFeature.Select2`, `ISldWorks.CloseDoc`, `ISldWorks.SetUserPreferenceToggle`); denying the bare name would make that key override a read-only denial and move `Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive` |
| `OpenDoc6` | The extractor's one sanctioned read-only open (`SwSession.OpenReadOnly`), for models only (`attach.md` section 4). The read-only open of a confirmed drawing does not ride on this exclusion: it calls the qualified key `ISldWorks.OpenDoc6` through its own allowlist guard (section 7) |
| `OpenDoc7`, `NewDocument` (shared) | *Added 2026-09-23 by T003's read audit*: feature 004 calls them by their bare names on sanctioned paths - `OpenDoc7` opens the re-modeler's own copy (`remodel.open`, under `RemodelGuard`) and reopens `probe remodel`'s throwaway part, and `NewDocument` creates that part (under `RemodelProbeGuard`, which exempts only what `ReadOnlyGuard` refused when it was written). Denying them would break both; the research's collision check had read only literal call-site names, and these two are named through constants |
| a member `RemodelGuard` refuses itself (`ExcludedMembers`) | `RemodelExclusions_AreOnlyMembersTheReadOnlyGuardDoesNotAlreadyRefuse` forbids `ReadOnlyGuard` to refuse them; none matched on 32.5.0.48, and the generator excludes them should a later interop add one |

Names already denied (39 of the 621, from features 001, 006 and 010, or by a denied prefix) are
listed in the table with the feature that denied them and are not added twice. `CloseDoc`,
`SetUserPreferenceToggle` and `OpenDoc6` are on no row of section 1 and match no grammar on the 24
families, so the generated exclusion table names only what a row or the grammar reached:
`set_Name`, `Select2`, `OpenDoc7` and `NewDocument`.

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

## 5. The tests

In `extractor/SwReview.Extractor.Tests/GuardTests.cs`:

| Test class | Asserts |
|---|---|
| `DrawingFamilyDenylistTests` | parses the "Feature 011" table (`DenylistTable.Parse`, as `MechanicalChecksDenylistTests` does); every member is refused by `ReadOnlyGuard.Assert` and `ReadOnlyCallGuard.Instance.Assert` |
| `DrawingFamilyCompletenessTests` | reflects the 24 interfaces at test time and applies the grammar: every match is refused, or is an excluded name of section 3; the shared rows are refused |
| `DrawingFamilyReadAuditTests` | no bare name the extractor gates (every `SwGate.Call`/`CallOptional` literal in `extractor/SwReview.Extractor`, collected by a source scan) is refused, except the write-refusal tests' own names and the re-modeler's write sites. *Landed as (T003)*: every string literal of the product source - `SwReview.Extractor`, `SwReview.AddIn` and `SwReview.Extractor.Console`, the `Guard` folder's own tables excepted - that the table refuses must be one of four named literals that are not gated calls (two members `probe standards` asserts it never calls, a JSON property name, a remodel operation name); a superset that also reaches names passed through constants and read helpers |

`RemodelGuardTests.ExpectedDeniedMembers` gains the table's names (it lists the guard's denials
from both ends); the five overriding keys and `RemodelGuard.ExcludedMembers` are unchanged and
their tests pass unedited.

## 6. What an extraction's gate log shows (FR-007)

For every extraction that reads a drawing: no member of this contract's denials, no
`ActivateSheet`, `ActivateView` or `ActivateDoc*`, and no `OpenDoc*`. `PackageWriterTests` asserts
it with the recording observer over the fake drawing reader; T062 records it at the seat. The read
of a confirmed drawing (section 7) shows exactly `ISldWorks.DocumentVisible`, `ISldWorks.OpenDoc6`
and `ISldWorks.CloseDoc` under their qualified keys when it opened the drawing, none of them when
the drawing was already open, and nothing else from the denials.

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
