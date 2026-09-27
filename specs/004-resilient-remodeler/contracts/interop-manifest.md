# The Frozen Interop-Surface Manifest

A checked-in JSON fixture describing every interop member the re-modeler calls, plus two tests.
The pure test keeps the code honest about the surface it was written against; the workstation test
**turns a SOLIDWORKS upgrade from a runtime surprise into a red build**.

File: `extractor/SwReview.Extractor.Tests/Fixtures/InteropSurface/remodel-interop-manifest.json`

## Why this exists

Every member on the stage-1 allowlist is VERIFIED: it exists with that signature on SOLIDWORKS
2024 SP5 interop `32.5.0.48`, confirmed by reflection on the pilot machine. Nothing keeps that
true. An interop upgrade can change an arity, reorder parameters, change a ByRef out-parameter to
a return value, or remove a member, and the failure mode is a `COMException` or, worse, a silently
wrong argument at the one moment the code is writing to a document.

The manifest makes that a build failure instead. It also records the **absences** the design
depends on, which is the half a signature dump normally loses: `IEquationMgr.set_GlobalVariable`
is absent, so a global is created by equation syntax; `ISketchRelation.Name` is absent, so sketch
relations cannot be named; there is no `*Shell*` creator on `IFeatureManager`. A design that
assumes any of those three would look reasonable and be wrong.

## Format

```jsonc
{
  "manifest_schema": "1.0",
  "assembly": "SolidWorks.Interop.sldworks",
  "assembly_version": "32.5.0.48",
  "swconst_version": "32.5.0.48",
  "product": "SOLIDWORKS 2024 SP5",
  "generated_at": "2026-09-16T00:58:00Z",
  "generated_by": "swreview-extract probe interop --emit-manifest",
  "members": [
    {
      "interface": "IModelDocExtension",
      "member": "ReorderFeature",
      "kind": "method",
      "arity": 3,
      "parameters": [
        {"name": "FeatureToMove", "type": "System.String"},
        {"name": "TargetFeature", "type": "System.String"},
        {"name": "Location", "type": "System.Int32"}
      ],
      "returns": "System.Boolean",
      "used_by": ["remodel.reorder"],
      "allowlisted": true
    },
    {
      "interface": "IModelDoc2",
      "member": "Save3",
      "kind": "method",
      "arity": 3,
      "parameters": [
        {"name": "Options", "type": "System.Int32"},
        {"name": "Errors", "type": "System.Int32&", "by_ref": true},
        {"name": "Warnings", "type": "System.Int32&", "by_ref": true}
      ],
      "returns": "System.Boolean",
      "used_by": ["remodel.save"],
      "allowlisted": true,
      "note": "takes no filename; this is the structural reason it cannot reach the source"
    },
    {
      "interface": "ISldWorks",
      "member": "set_CommandInProgress",
      "kind": "property-set",
      "arity": 1,
      "parameters": [
        {"name": "Value", "type": "System.Boolean"}
      ],
      "returns": "System.Void",
      "used_by": ["remodel.open"],
      "allowlisted": true,
      "note": "a property, not a swUserPreferenceToggle_e value; it is deliberately absent from the enums block below"
    }
  ],
  "enums": [
    {"enum": "swMoveLocation_e", "values": {"ToEnd": 1, "Before": 2, "After": 3,
                                            "ToTop": 4, "ToFolder": 5}},
    {"enum": "swFeatureTreeFolderType_e", "values": {"EmptyBefore": 1, "Containing": 2,
                                                     "Mold": 3}},
    {"enum": "swOpenDocOptions_e", "values": {"Silent": 1, "ReadOnly": 2, "ViewOnly": 4,
                                              "LoadModel": 16}},
    {"enum": "swSaveAsOptions_e", "values": {"Silent": 1, "Copy": 2, "SaveReferenced": 4,
                                             "AvoidRebuildOnSave": 8}},
    {"enum": "swUserPreferenceToggle_e", "values": {"InputDimValOnCreate": 10,
                                                    "ShowErrorsEveryRebuild": 77,
                                                    "WarnSaveUpdateErrors": 329}},
    {"enum": "swMassPropertyAccuracyLevel_e", "values": {"Lower": 0, "Medium": 1, "Higher": 2}},
    {"enum": "swMassPropertiesStatus_e", "values": {"OK": 0, "UnknownError": 1, "NoBody": 2}},
    {"enum": "swFeatureError_e", "values": {"swFeatureErrorNone": 0}},
    {"enum": "swMoveRollbackBarTo_e", "values": {"ToEnd": 1, "ToPrevious": 2,
                                                 "ToBeforeFeature": 3, "ToAfterFeature": 4}},
    {"enum": "swFileSaveWarning_e", "values": {"RebuildError": 1, "NeedsRebuild": 2}},
    {"enum": "swBodyType_e", "values": {"Solid": 0, "Sheet": 1, "Mesh": 6, "Graphics": 7}}
  ],
  "absences": [
    {"interface": "IEquationMgr", "member": "set_GlobalVariable",
     "consequence": "a global is created by equation syntax, \"name\" = expr, not by a flag"},
    {"interface": "IFeatureManager", "member_pattern": "*Shell*",
     "consequence": "shell is IModelDoc2.InsertFeatureShell(Double, Boolean) returning Void, from the current face selection"},
    {"interface": "ISketchRelation", "member": "Name",
     "consequence": "sketch relations cannot be named; intent is recorded in the parent feature's Description"},
    {"interface": "IFeature", "member": "set_ShowFeatureDescription",
     "consequence": "descriptions hidden in the tree can be DETECTED via IFeatureManager.get_ShowFeatureDescription but not turned on"}
  ]
}
```

Field rules:

- `interface` is the interop interface name as reflection reports it, not the dispatch name.
- `parameters` is **ordered**, and the order is load-bearing: this is what catches a reordered
  signature, which is the failure a name-only check misses.
- `by_ref: true` marks an out-parameter. Every ByRef member in this manifest is a reason a call
  lives in C# rather than Python: `Operations2`, `GetMassProperties2`, `GetWhatsWrong`,
  `GetErrorCode2`, `GetObjectByPersistReference3` and `Save3` all take ByRef out-parameters that
  the Python bridge cannot marshal.
- `allowlisted` mirrors `guard-allowlist.md` exactly. A member with `allowlisted: true` that is
  absent from the guard's list, or the reverse, fails test A.
- `used_by` names the `remodel.*` commands (or `probe`) that call the member, so a reader can go
  from a red diff to the affected command in one step.
- `absences` carries members the design depends on **not** existing. Test B checks each one is
  still absent; a member that appears is as much a design change as one that disappears.
- `enums` carries only the constants the code composes. Every one is asserted as an integer, never
  by name, because the name is what the code already writes.

## Test A: pure, runs everywhere, no SOLIDWORKS

`RemodelInteropManifestTests.CodeMatchesManifest`

The argument builders in `RemodelScope` and the bridge command handlers expose, for each member
they call, the qualified key, the ordered argument names, and the composed option integers. The
test asserts:

1. every member a builder calls has a manifest row, and every row with `allowlisted: true` has a
   builder or an explicit probe-only marker;
2. the arity and the ordered parameter names the builder uses equal the row's;
3. the option integers the builders compose equal the manifest's enum values (the same integers
   `guard-allowlist.md` pins, asserted from one source rather than two);
4. `allowlisted` agrees with `RemodelGuard`'s list, as a set equality in both directions.

This test fails when someone adds a call without recording it, or changes an argument order, or
writes an option as a name whose value drifted.

## Test B: workstation-only, skipped when the interop assembly is absent

`RemodelInteropManifestTests.InstalledAssemblyMatchesManifest`

Skipped (not failed, and reported as a skip with its reason) when
`SolidWorks.Interop.sldworks.dll` is not present, so CI stays green on a machine with no
SOLIDWORKS. On the pilot workstation it regenerates the manifest from the installed assembly by
the same reflection dump that produced it and diffs:

- a member whose signature changed fails, naming the interface, the member, and both signatures;
- a member that disappeared fails;
- a member that appeared in `absences` fails, because a design decision was made on its absence;
- an enum whose integer changed fails;
- `assembly_version` differing from the manifest's is reported in the failure message, so the
  first line of the diff says which SOLIDWORKS is installed.

Regenerating the manifest is a deliberate, reviewed commit: the new file, the version bump, and a
note in the quickstart saying which members moved. It is never a test that updates its own fixture.
*Amended 2026-09-27 (T181):* the regeneration is the manifest command's own reflection
(`RemodelInteropManifest`, "Generation" below), read for the fixture's rows, constants and
absences, and the kind of each row is compared too.

## The seat adapter's additions (T156, 2026-09-27)

The production seat adapter (T153 to T155, the 004 build order's lane B) calls members the first
generation did not record: the routes to members already recorded, the reads the bridge's seams
leave to the adapter, and the copy's open request. Twenty rows were added, none allowlisted,
each read by the same metadata-only reflection over the installed `SolidWorks.Interop.sldworks`
32.5.0.48 on the development machine (SOLIDWORKS not started) and checked there by test B. Nothing
that was recorded moved, so `generated_at` stays the first generation's and `generated_by` names
the additions. `RemodelInteropManifestTests.EveryMemberTheSeatAdapterAddsHasARowAndIsNotAllowlisted`
pins the list by value. Nineteen were derived ahead of lane B; the twentieth,
`IFeatureFolder.GetFeatureCount`, was found by the cross-check of lane B's calls, interface by
interface, when its files merged, and lane B calls all twenty.

| Member | Why the adapter calls it | `used_by` |
|---|---|---|
| `IModelDoc2.get_Extension` | the route to every `IModelDocExtension` member (persist refs, the tag's property manager, `ReorderFeature`, What's Wrong, `CreateMassProperty2`) | every copy command, `remodel.probe_scope`, `VerifyTarget` |
| `IModelDoc2.get_FeatureManager` | the route to `GetFeatures`, `GetSheetMetalFolder`, `EditRollback`, `InsertFeatureTreeFolder2`, `FeatureFolderLocation` | the tree walks |
| `IModelDoc2.GetEquationMgr` | `IRemodelDocument.Equations`, handed to the shared `SwEquationManager` | `remodel.snapshot`, `remodel.equation` |
| `IModelDoc2.GetUnits` | `IRemodelDocument.GetLengthUnit`: element 0 is a `swLengthUnit_e` value; unreadable is null, never metres | `remodel.open` |
| `IModelDocExtension.GetPersistReference3` | `IRemodelDocument.GetPersistReference` and a folder's member refs, encoded by `PersistRefCodec` | the tree walks |
| `IFeatureManager.GetFeatures` | `GetFeatures(true)`: `IRemodelDocument.GetFeaturesInOrder` and the scope-signal reader's walk | the tree walks |
| `IModelDoc2.get_ConfigurationManager`, `IConfigurationManager.get_ActiveConfiguration`, `IConfiguration.get_Name` | the active configuration `IGeometrySource.GetMaterialName` reads the material for, by the path `Dump/PropertyDumper.cs` reads it | `remodel.geometry` |
| `IFeature.GetSpecificFeature2`, `IFeatureFolder.GetFeatures`, `IFeatureFolder.GetFeatureCount` | an `FtrFolder`'s members for the `rms_named_folders` signal (research R3.1), read only when their number equals the folder's count, else the whole listing is null | `remodel.probe_scope`, `remodel.open` |
| `ISldWorks.GetOpenDocSpec`; `IDocumentSpecification.set_DocumentType`, `set_Silent`, `set_LoadModel`, `set_ReadOnly`, `set_ViewOnly`, `get_Error`, `get_Warning` | the copy's open request, built by the one open-options helper the add-in's `remodel.open_copy` shares: `OpenDoc7` takes the request, so `Silent \| LoadModel = 17` is written as its members, `ReadOnly` and `ViewOnly` always false; property sets on a throwaway request, never gated and not allowlisted (`guard-allowlist.md`, decision 17A's "Left open" row) | `remodel.open`, `remodel.open_copy` |

"The tree walks" are `remodel.probe_scope`, `remodel.open`, `remodel.snapshot`, `remodel.reorder`,
`remodel.folder` and `remodel.rebuild`. Three of the rows name members the bridge already gated
under bare keys with no row: `GetFeatures`, `GetPersistReference3` and `GetUnits`. Where T153 to
T155 leave the path open (the active configuration, a folder's members, the open request's error
bits), the rows follow the repository's existing reads (*default taken 2026-09-27, the owner may
revise*); a row lane B does not call is removed when its files merge, and when they merged there
was none. `set_ReadOnly` and the parameter name `LoadModel` match feature 011's refused
`IDimension`/`INote.set_ReadOnly` and `IView.LoadModel` by name only, so they are two of
`DrawingFamilyReadAuditTests`' named literals.

The enums block gained the constants the adapter writes by their swconst names, each read by the
same metadata-only reflection over the installed `SolidWorks.Interop.swconst` 32.5.0.48 (*default
taken 2026-09-27, the owner may revise*): `swBodyType_e.swAllBodies = -1`, the body type the mesh
and graphics rows ask `GetBodies2` for; the new `swPersistReferencedObjectStates_e` with
`swPersistReferencedObject_Invalid = 1`, what a persist ref that does not decode answers without
asking SOLIDWORKS; and the new `swLengthUnit_e` with all eleven members, `swMM = 0` to `swUIN = 10`,
the keys of `RemodelLengthUnits`' table. A constant written by name is what the block pins as an
integer; `EveryConstantTheSeatAdapterComposesHasAnEnumRow` pins the three by value and reads the
length-unit table through the manifest's integers, and test B holds each to the installed swconst.

## The seat adapter audit (T152): pure, runs everywhere

Test A compares the fixture with a hand-written table, so a member the adapter called directly and
nobody added to the table would pass it. The audit reads the adapter's source instead:
`RemodelInteropManifestTests.EveryInteropMemberTheSeatAdapterSourceNamesHasARow`, over the files
under `extractor/SwReview.AddIn/Remodel/Seat/`, lane A's shared `Rms/SwEquationManager.cs` and
`Rms/SwMassProperty.cs`, and lane B's extractor-side `Rms/SwRemodelToggleHost.cs`,
`Rms/RemodelWhatsWrong.cs` and `Rms/RemodelLengthUnits.cs` (*default taken 2026-09-27, the owner
may revise*: the pure table included, so an interop call added to it later is audited too), found
by the product-source scan `DrawingFamilyReadAuditTests` runs.

- It takes every member access outside comments (strings are kept, since an interpolated string
  holds code): a read is the member or its `get_` accessor, an assignment its `set_` accessor, a
  compound assignment both.
- It fails on a name that some public interface of the interop the product is built against
  declares and that no row records, on any interface.
- It cannot see which interface a name is called on, so a name recorded on one interface passes on
  another, and an indexed property set (`x.Member[i] = v`) is read as a get. A name that is not a
  SOLIDWORKS call but matches one is a named exception with its reason, and a staleness case
  fails an exception that is no longer needed. There are five: `Length` (`Array.Length`), and
  lane B's four, found when its files merged (*defaults taken 2026-09-27, the owner may revise*):
  `Add` (`List<T>.Add`), `Features` (the adapter's own `SwRemodelReads.Features`), `GetBodyCount`
  (the product's `IScopeSignalSource.GetBodyCount`) and `Message` (`Exception.Message`).
- A floor keeps it from passing on nothing: the shared classes are read and their interop calls
  found, and a product file declaring one of the build order's adapter classes (`SwScopeSignalReader`,
  `SwRemodelCopyDocument`, `SwRemodelProbeSource`, `SwRemodelBridgeSeat`, `CopyOpenSpecification`)
  outside those paths fails it.

*Recorded 2026-09-27 on review (T181):* the pane's own seat, `SwRemodelSeat` (`remodel.open_copy`
and T159's activation before each dump), is outside the audit and outside the bridge by design - a
UI action of the add-in, which the bridge's vocabulary deliberately lacks (`IRemodelSeat`'s
remarks), and which the read-only guard would refuse, since `ActivateDoc3` is on its denylist. It
calls `GetOpenDocumentByName`, `ActivateDoc3`, `get_ActiveDoc`, `IModelDoc2.GetTitle`,
`GetPathName` and `OpenDoc7` directly; `ActivateDoc3`, `get_ActiveDoc` and `GetTitle` have no row,
and `OpenDoc7`'s `used_by` does not name `remodel.open_copy`. They join the manifest, and the file
the audit, with T181's regeneration.

`EveryMemberTheScopeProbeGatesHasARow` pins, beside it, that every member
`RemodelScopeProbe.ProbeSurface` gates (T154's reads) and `RemodelSession`'s resolve pair has a row.

## Generation

*Amended 2026-09-27 on review (`tasks.md` T181, research R14.5):* the command this section
describes has **not been built**. The fixture was generated by metadata-only reflection run by hand
(T055, and the T156 additions), and what backs "regenerated, not typed" is test B,
`InstalledAssemblyMatchesManifest`, which compares every row's signature and every enum value with
reflection over the installed assembly, field for field; the `used_by` and `note` fields are written
by hand and no test reads them against the code. T181 builds the command before T140, whose
regeneration it is, and until then no row is added or changed. As specified:

`swreview-extract probe interop --emit-manifest <path>` writes the file from the installed
assembly. It is the same reflection dump used to establish the VERIFIED column throughout these
contracts, so the manifest and the contracts cannot disagree about what was checked. The probe
prints the member count and the assembly version it read, and refuses to write over an existing
file without `--force`, for the same reason the re-modeler's copy refuses to overwrite.

*Built 2026-09-27 (`tasks.md` T181; defaults taken 2026-09-27, the owner may revise; research
R15.1).* The command exists and writes the fixture. The **selection** is committed code in
`Rms/RemodelInteropSurface.cs`: the rows, in order, each with its `used_by`, `allowlisted` and
`note` (`Calls`, each call's `UsedBy` and `Note`); the enum constants, in order (`Constants`); and
the absences with their consequences (`Absences`). **Reflection** over the installed
`SolidWorks.Interop.sldworks` and `SolidWorks.Interop.swconst` in the seat's `api\redist` folder -
metadata only: types and methods are read, no COM object is created, and SOLIDWORKS is neither
attached to nor started (`Rms/RemodelInteropManifest.cs`) - writes every other field: each row's
`kind` (a `get_` or `set_` special name is a property's accessor, anything else a method), `arity`,
ordered `parameters` with `by_ref`, and `returns`; each constant's integer; the two versions; and
`product`, read from the members' version as `SOLIDWORKS {1992 + major} SP{minor}`, since the
interop assemblies carry no product name. `generated_at` is the UTC second the command ran and
`generated_by` is the command. The file keeps this format exactly - two-space indentation, the key
order above, `by_ref` only when true, a note only when there is one, UTF-8 without a byte-order
mark, LF line ends and a final newline - so a regeneration's diff is only what moved.

It **writes nothing and exits 1**, naming every problem, when a selected interface or member is
missing, a member has more than one overload, a recorded absence is present, an enum or a constant
is missing, or a row has no `used_by`; and when the path exists without `--force`, is a folder, or
no redist folder holds both assemblies. It takes no `--doc` and no `--allow-start`: it addresses no
document and no session. `RemodelInteropManifestTests.TheFixtureIsWhatTheCommandWrites` (pure,
always run) regenerates from the interop the product is built against and compares the text with
the fixture, `generated_at` aside, so a row typed into the fixture by hand, or a selection changed
without regenerating, fails; test B reads the fixture's own rows through the command's reflection,
so the two cannot spell a signature differently. The first regeneration changed `generated_at` and
`generated_by` and nothing else. Adding a row is now its builder row in `RemodelInteropSurface`,
with its `used_by` and note, then:

```
swreview-extract probe interop --emit-manifest extractor/SwReview.Extractor.Tests/Fixtures/InteropSurface/remodel-interop-manifest.json --force
```
