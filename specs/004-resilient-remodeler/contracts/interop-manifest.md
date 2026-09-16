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

## Generation

`swreview-extract probe interop --emit-manifest <path>` writes the file from the installed
assembly. It is the same reflection dump used to establish the VERIFIED column throughout these
contracts, so the manifest and the contracts cannot disagree about what was checked. The probe
prints the member count and the assembly version it read, and refuses to write over an existing
file without `--force`, for the same reason the re-modeler's copy refuses to overwrite.
