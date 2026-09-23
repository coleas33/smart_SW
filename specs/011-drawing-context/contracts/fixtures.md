# Contract: The Synthetic Drawing Fixtures

Normative for the committed packages every acceptance test in this feature reads. No recorded
package carries a drawing, and the repository is public: the fixtures are built by code from
fictional strings, on top of feature 010's builders and its `tolerances` assembly, whose joints,
faces, persistent references and model dimensions have known answers.

## 1. What is committed

```text
reviewer/tests/support/drawings.py                 # builders: drawing records, sheets, views, display
                                                   # dimensions with tolerances, precision, text parts and
                                                   # attached faces, typed annotations, notes, tables, BOM
                                                   # rows, candidates - on top of tests/support/mechanical.py
reviewer/tests/fixtures/drawings/
├── generate_fixtures.py                           # run from reviewer/; reads nothing but the builders
├── plate-drawing/package.json, meshes/            # IR 1.6.0
├── drawing-root/package.json                      # IR 1.6.0
└── assembly-drawings/package.json, meshes/        # IR 1.6.0
```

Re-running the generator reproduces every committed byte; `test_support_drawings.py` asserts it.
Feature 010's `tests/fixtures/mechanical/` is read by the builders and never regenerated here.

## 2. The case table

| Fixture | Shape | Cases |
|---|---|---|
| `plate-drawing` | feature 010's `tolerances` assembly (plate, block, 3.0 mm dowel, M4 socket head screw) with two attached drawings of the plate and a candidate beside the block | **Drawing A** (configuration as reviewed, up to date, mm, default precision 2, drafting standard `FICTIONAL-STANDARD`, third angle, one sheet with format `FICTIONAL-FORMAT-A`): the plate's dowel hole Ø3.10 with bilateral limits attached to its cylinder face (route `attached_face`); the plate's other dowel dimension as a model item whose name matches the model dimension (route `model_dimension`); an untoleranced two-decimal diameter on the pin hole's face with `uses_document_precision`; a `BLOCK` dimension; a `GENERAL` dimension; a counterbore hole callout with its variables; a position GTol on the dowel face with a unitless value `0.05`; datum tags A and B; a surface-finish symbol; three notes (one a general tolerance note, verbatim); a title-block table, a general-tolerance table and a hole table; one reference dimension attached to an edge (two faces, `via: edge`); one dimension with no readable unit (a `dimension_unit` gap); one diameter attached to a face whose displayed value is overridden (binds nothing). **Drawing B** (a second drawing of the plate: one sheet whose view shows another configuration, and one view left out of date): a diameter on the same hole with different limits in the other-configuration view, and an untoleranced diameter written to three decimals in the out-of-date view - neither usable. **Candidate**: the block document's same-name `.SLDDRW` path under `C:\Fictional\`, beside it and not open |
| `drawing-root` | a drawing root shaped like feature 006's drawing fixtures, at 1.6.0, three sheets (one not active and enumerated, one whose views could not be enumerated - a `drawing_sheet_views` gap), two referenced models | feature 006's four drawing checks grade it exactly as they grade the 1.4.0 fixtures; every new field present on at least one record |
| `assembly-drawings` | a small assembly with an assembly drawing (bill of materials whose rows resolve to three package documents and one unresolved path) and one part shown by three attached drawings | the governing question with three options plus `They all apply`; the candidate question absent; a view referencing a document outside the design (a `drawing_referenced_document` gap) |

The pathological package for the brief's bound (500 notes, 300 dimensions, 60 joints) is built in
`test_drawing_brief.py` from the builders and never committed.

*Landed as (T012, 2026-09-23)*: the generator's module docstring is the case table with every id.
Three readings the table above leaves open were decided there: the plate's dowel hole is the
tolerances assembly's Ø3.0 (`fac:0001`), so drawing A's bilateral dimension is Ø3.00 +0.010/0.000;
"the pin hole" is the plate's only other hole in a joint, the counterbore's Ø4.5 through bore
(`fac:0002`), whose two equal 4.5 mm model dimensions leave feature 010's screw stack unresolved;
and "the plate's other dowel dimension" is the model item of `mdm:0001` on the same dowel hole,
named with a document suffix spelled differently. A drawing dimension's value is in metres, as
`DrawingDumper` writes it. The drawing root is built with feature 006's standards builder and its
record rebuilt whole with every 1.6.0 member; `opened_by_review` appears on no fixture, since only
the confirmed read-only open writes it. The drawing vocabulary reads a word and the number run into
it apart (`Sheet1`), and the denylist scan leaves out the published head codes, as feature 010's
does (`tests/support/fixture_denylist.PUBLISHED_HEAD_CODES`, moved there from 010's test).

## 3. Fictional strings only

Every path is under `C:\Fictional\`; file names, sheet names, view names, notes, table cells and
format names come from the builders' fictional vocabulary (feature 010's, extended with drawing
words); materials are the library names already used by committed goldens. The general tolerance
note and the title-block cells use invented wording that matches no company's.
`reviewer/tests/unit/test_drawing_fixtures_are_fictional.py` asserts, over the fixture tree: every
path starts with the fictional root; every string is from the vocabulary or is a number or an id;
and, when `%LOCALAPPDATA%\SwReview\fixture-denylist.txt` exists, no token from it appears (skipped
naming the file otherwise), through the existing `tests/support/fixture_denylist.py`.
`test_standards_no_company_values.py` stays green.
