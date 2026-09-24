# Contract: The Synthetic Fixtures

Normative for the committed fixtures every acceptance test in this feature reads. The recorded
packages never enter the repository (the repository is public); the fixtures are built by code
from fictional strings and the geometry numbers research R3 verified.

## 1. What is committed

```text
reviewer/tests/support/mechanical.py              # builders: documents, components, hole features with
                                                  # N instances, free cylinder faces, screws in the vendor
                                                  # naming shape, interference rows, tiny STL meshes
reviewer/tests/fixtures/mechanical/
├── generate_fixtures.py                          # run from reviewer/; reads nothing but the builders
├── big-assembly/package.json, meshes/*.stl       # shaped like the big assembly
├── small-assembly/package.json, meshes/*.stl     # shaped like the small assembly
└── tolerances/package.json, meshes/*.glb         # IR 1.5.0 (US8, T084)
specs/010-mechanical-checks/contracts/fastener-name-vectors.json   # the parser vectors (T039)
```

Re-running the generator reproduces every committed byte; `test_support_mechanical.py` asserts
it, so a drifted fixture is a failure and not a rewrite.

## 2. The case table

| Fixture | Shape | Cases |
|---|---|---|
| big-assembly | 26 documents (23 parts, 3 assemblies), 89 components (86 resolved, 2 lightweight, 1 suppressed), 27 hole rows with 132 instances (two rows with no cylinder face), 68 screws over 9 documents in the vendor naming shape (32 `SHC`, 35 `FHT`, 1 `BHT`), 2 pin components with no face, 113 interference groups | the joint numbers of `joint-map.md` section 9; the fastener cases of `fasteners.md` section 6 (both M4-in-M5 screws, the M10, M2 and M3 engagements, the passes, one screw named M5 with a 3.3 mm shank); an overhanging part over one screw head and a clear head; a 12.0 mm counterbore under an M8 socket head; parts at 2700, 7850 and 1000 kg/m3; a 2.000 kg sub-assembly with unread children; one surface-only part; one document whose part-number property differs from its stem; two documents sharing a description; one model with no revision; 8 positive-volume groups (one mixed with a zero-volume member) and 105 zero-volume or possible-only groups |
| small-assembly | 3 documents, 4 components, 4 hole rows with 16 instances, no hole pair | a 3.0 mm pin in a 3.0 mm hole at 0.000 mm with 8.475 mm of overlap; two zero-volume interference rows between the pin and the plate; an assembly whose mass is its part plus two pins |
| tolerances | IR 1.5.0, a small screw and dowel assembly: a plate and a block pinned by a 3.0 mm dowel (3 documents, 4 components with the screw), one M4 socket head through the plate's counterbore into the block's tapped hole | the dowel joint's three sizes each bound by a model dimension: the plate hole's by a class-only `H7` fit on its diameter dimension, the block hole's and the pin's by bilateral limits (a size-only stack, least clearance 0.001 mm); the counterbore's `wizard` data with the clearance fit `swScrewClearanceNormal` and its sizes; one ambiguous pair of equal 4.5 mm dimensions (the screw joint's stack unresolved, naming every source); one position `gtol` on the plate's dowel face bound by face persist ref, whose value states no unit and so binds nothing; used with a version 2 profile carrying a general block, a version 1 profile without one, and no profile |

**Where a hole's ISO class arrives (T084, from the C# lane's finding).** The table above first
put the dowel hole's `H7` on its Hole Wizard data. The Hole Wizard's own fit (`HoleFit`) is a
screw clearance fit - close, normal or loose - and never an ISO 286 class, so a hole's `H7`
arrives on its model dimension as a fit tolerance (`fit_hole_class`); the fixture carries it
there, and the counterbore's Hole Wizard fit is the clearance fit the resolver reads and
declines.

## 3. Fictional strings only

Every document path is under `C:\Fictional\`; file names and descriptions come from a syllable
vocabulary in the builders, with the vendor shape `<HEAD>_M<d>-<p>X<L>_FICT-<nnnn>` and
`<KIND>, <abbr> M<d>-<p> X <L> MM, FICTIONAL`; property names are the test profiles' fictional
ones; materials are SOLIDWORKS library names already used by committed goldens (`6061-T6`,
`Alloy Steel`).

`reviewer/tests/unit/test_mechanical_fixtures_are_fictional.py` asserts, over the fixture tree and
the vector table: every path starts with the fictional root; every file name and description is
built from the vocabulary; and, when `%LOCALAPPDATA%\SwReview\fixture-denylist.txt` exists on the
machine running the tests, no token from it appears (skipped with that reason where it does not,
which is every CI machine). The denylist reader is `reviewer/tests/support/fixture_denylist.py` over the same
`fixture-denylist.txt` feature 008's generator refreshes (008 T018); if 008's T010 or T017 already
reads that file, this feature imports that reader instead of writing a second one. `test_standards_no_company_values.py` stays green.
