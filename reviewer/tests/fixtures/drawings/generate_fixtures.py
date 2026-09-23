"""Generate the synthetic packages feature 011's acceptance tests read (T012).

Run from `reviewer/` and commit what it writes:

    uv run python tests/fixtures/drawings/generate_fixtures.py

`tests/unit/test_support_drawings.py` re-runs `render_all()` and compares every byte with the
tree, so a fixture is changed here, regenerated and committed - never edited by hand.

**Nothing here comes from a recorded package, and no string in it was recorded.** Every
fixture is built from `tests/support/drawings.py` on top of feature 010's builders
(`tests/support/mechanical.py`) or feature 006's (`tests/support/standards.py`), from fictional
strings; `test_drawing_fixtures_are_fictional.py` holds the output to that. The three packages
are IR 1.6.0 (`contracts/fixtures.md` section 2).

## plate-drawing

Feature 010's `tolerances` assembly, read from its own generator and never regenerated here:
the plate `doc:0002` (`cmp:0001`: dowel hole `hol:0001` on `fac:0001` Ø3.0, counterbore
`hol:0002` on `fac:0002` Ø4.5 and `fac:0003` Ø8.0), the block `doc:0003`, the 3.0 mm dowel
`doc:0004` and one M4 socket head screw `doc:0005`, with its five model dimensions
(`mdm:0001` the plate's dowel diameter, a class-only H7 fit) and its position GTol. Beside it:

- **Drawing A**, `FICT-TULMKALO-3001.SLDDRW` (`doc:0006`): not in detailing mode, millimetres
  (unit 0), default precision 2, tolerance precision 3, drafting standard `FICTIONAL-STANDARD`;
  one sheet, format `FICTIONAL-FORMAT-A`, third angle, 1:1. Its sheet-format view carries three
  notes (one a general tolerance note, verbatim) and three tables - a title block (type 5), a
  general tolerance table (9) and a hole table (1) - and one revision table. Its one model view
  shows the plate in `Default`, up to date and loaded, and carries:
  - `KALOMIR11`: Ø3.00 +0.010/0.000 bilateral, attached to the dowel face `fac:0001` (the
    `attached_face` route);
  - `KALOMIR1@FICT-HOLE-0001@fict-tulmkalo-3001.sldprt`: the plate's dowel diameter as a model
    item, its name `mdm:0001`'s before a document suffix spelled differently, the model's
    class-only H7 fit (type 8) (the `model_dimension` route);
  - `KALOMIR13`: Ø4.50 untoleranced (type `NONE`) at the document's precision, attached to the
    counterbore's through bore `fac:0002` - the plate's only other hole in a joint, which the
    case table calls "the pin hole";
  - `KALOMIR14`: Ø8.0 `BLOCK` (type 10) on `fac:0003`; `KALOMIR15`: a 20.00 linear `GENERAL`
    (type 11) dimension;
  - `KALOMIR16`: the counterbore hole callout, its three variables verbatim, on `fac:0002`;
  - `KALOMIR17`: a 4.40 reference dimension attached to the bore-to-counterbore edge, so its
    two faces `fac:0002` and `fac:0003`, each `via: edge`;
  - `KALOMIR18`: a scalar (type 13) with no unit: no value and a `dimension_unit` gap;
  - `KALOMIR19`: Ø3.00 attached to `fac:0001` with its displayed value overridden to 3.05;
  - a position GTol (`<GTOL-POSI>`, value `0.05` with no unit) on `fac:0001`, datum tags A and
    B, and a surface-finish symbol with its texts on `fac:0002`.
- **Drawing B**, `FICT-TULMKALO-3001-B.SLDDRW` (`doc:0007`), a second drawing of the plate:
  one view of configuration `FICT-VENTA` carrying Ø3.00 +0.020/+0.005 on `fac:0001`, and one
  `Default` view left out of date carrying Ø4.500 untoleranced at its own precision 3 on
  `fac:0002` - neither usable.
- **Candidate**: `FICT-TULMSORN-3002.SLDDRW` beside the block `doc:0003`, not open.

## drawing-root

A drawing root shaped like feature 006's drawing fixtures, built by feature 006's standards
builder and rebuilt whole with every 1.6.0 member: `FICT-OKTAPELIN-4000.SLDDRW` referencing the
part `FICT-OKTAPELIN-4001` and the assembly `FICT-OKTAQUILL-4002` (of one part,
`FICT-OKTASORN-4003`). Three sheets: `Sheet1` active, with the sheet-format view (the export
control phrase of profile A), both model views, an overridden dimension, a GTol, a datum tag and
a surface finish; `Sheet2` not active and enumerated, with a view and a bill of materials whose
rows resolve both parts; `Sheet3` not active, listing no views, with its `drawing_sheet_views`
gap. The drawing binds no configuration (`contracts/attach.md` section 2): the design, its
document row and manifest entry and the forest's root node carry `""`, the models `Default`.

## assembly-drawings

A small assembly `FICT-OKTAVEN-5000` of three parts, with an assembly drawing
(`FICT-OKTAVEN-5000.SLDDRW`) whose bill of materials resolves the three parts and keeps one
unresolved library path, and whose second view shows a document outside the design (its
`drawing_referenced_document` gap); and the part `FICT-OKTAKALO-5001` shown by three attached
drawings (`FICT-OKTAKALO-5001.SLDDRW`, `-B`, `-C`). No candidate.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[2]))

from tests.support.drawings import Attach, DrawingBuilder  # noqa: E402
from tests.support.mechanical import (  # noqa: E402
    FICTIONAL_ROOT,
    HYGIENE_PROPERTIES,
    Built,
    PackageBuilder,
    load_generator,
)
from tests.support.packages import persist_ref  # noqa: E402
from tests.support.standards import (  # noqa: E402
    AssemblySpec,
    ComponentSpec,
    DrawingSpec,
    PartSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

from swreview.ir.models import AttachedFace, BomRow, EvidencePackage, GtolFrame  # noqa: E402

MECHANICAL = FIXTURE_DIR.parent / "mechanical" / "generate_fixtures.py"

PLATE_ID = UUID("01100000-0000-4000-8000-000000000011")
ROOT_ID = UUID("01100000-0000-4000-8000-000000000012")
ASSEMBLY_ID = UUID("01100000-0000-4000-8000-000000000013")

PART_NUMBER, SUMMARY, REVISION = HYGIENE_PROPERTIES

POSITION = GtolFrame(
    number=1,
    symbols_raw=["<GTOL-POSI>", "<MOD-DIAM>", "", "", "", ""],
    values_raw=["0.05", "", "A", "B", ""],
)
GENERAL_TOLERANCE_NOTE = "GENERAL TOLERANCE FICTIONAL: .X 0.4 .XX 0.15 .XXX 0.04"


def title_properties(stem: str) -> dict[str, str]:
    return {PART_NUMBER: stem, SUMMARY: "TULM KALO DRAWING", REVISION: "A"}


# --- plate-drawing --------------------------------------------------------------------------


def build_plate_drawing() -> Built:
    tolerances = load_generator(MECHANICAL).build_tolerances_assembly()
    builder = DrawingBuilder(tolerances.package, package_id=PLATE_ID)
    plate = "doc:0002"

    drawing_a = builder.drawing(
        builder.drawing_document(
            "FICT-TULMKALO-3001", properties=title_properties("FICT-TULMKALO-3001")
        )
    )
    sheet = builder.sheet(drawing_a, "Sheet1")
    frame = builder.view(
        sheet,
        "Sheet Format1",
        view_type_raw=1,
        configuration=None,
        out_of_date=None,
        loaded=None,
        scale_decimal=None,
        orientation=None,
    )
    builder.note(frame, "FICTIONAL NOTE 1")
    builder.note(frame, GENERAL_TOLERANCE_NOTE)
    builder.note(frame, "BREAK SHARP EDGES FICTIONAL")
    builder.table(
        sheet,
        frame,
        type_raw=5,
        title="TITLE BLOCK",
        rows=[["TITLE", "FICT-TULMKALO-3001"], ["REV", "A"]],
    )
    builder.table(
        sheet,
        frame,
        type_raw=9,
        title="GENERAL TOLERANCE",
        rows=[["DECIMALS", "TOLERANCE"], ["X", "0.4"], ["XX", "0.15"]],
    )
    builder.table(
        sheet,
        frame,
        type_raw=1,
        title="HOLE TABLE",
        rows=[["TAG", "X LOC", "Y LOC", "SIZE"], ["1", "0", "0", "3.00"], ["2", "20", "0", "4.50"]],
    )
    builder.revision_table(
        sheet,
        rows=[["REV", "DESCRIPTION", "DATE"], ["A", "FICTIONAL RELEASE", "2026-09-23"]],
        current_revision="A",
    )

    view = builder.view(sheet, "Drawing View1", references=plate)
    builder.dimension(
        view,
        "KALOMIR11@FICT-TULMKALO-3001",
        value_mm=3.0,
        tolerance=("bilateral", 0.010, 0.0),
        tolerance_type_raw=2,
        attached=[Attach("fac:0001")],
    )
    builder.dimension(
        view,
        "KALOMIR1@FICT-HOLE-0001@fict-tulmkalo-3001.sldprt",
        value_mm=3.0,
        tolerance_type_raw=8,
        fit_hole_class="H7",
    )
    builder.dimension(
        view,
        "KALOMIR13@FICT-TULMKALO-3001",
        value_mm=4.5,
        precision=2,
        uses_document_precision=True,
        attached=[Attach("fac:0002")],
    )
    builder.dimension(
        view,
        "KALOMIR14@FICT-TULMKALO-3001",
        value_mm=8.0,
        precision=1,
        tolerance_type_raw=10,
        attached=[Attach("fac:0003")],
    )
    builder.dimension(
        view,
        "KALOMIR15@FICT-TULMKALO-3001",
        value_mm=20.0,
        type_raw=2,
        tolerance_type_raw=11,
        prefix="",
    )
    builder.dimension(
        view,
        "KALOMIR16@FICT-TULMKALO-3001",
        value_mm=4.5,
        hole_callout=True,
        callout_variables=["<MOD-DIAM>4.50 THRU", "<HOLE-CB-DIAM>8.00", "<HOLE-DEPTH>4.40"],
        attached=[Attach("fac:0002")],
    )
    builder.dimension(
        view,
        "KALOMIR17@FICT-TULMKALO-3001",
        value_mm=4.4,
        type_raw=2,
        prefix="",
        is_reference=True,
        driven_state_raw=2,
        attached=[Attach("fac:0002", via="edge"), Attach("fac:0003", via="edge")],
    )
    builder.dimension(view, "KALOMIR18@FICT-TULMKALO-3001", value_mm=2.0, type_raw=13, prefix="")
    builder.dimension(
        view,
        "KALOMIR19@FICT-TULMKALO-3001",
        value_mm=3.0,
        overridden=True,
        override_mm=3.05,
        attached=[Attach("fac:0001")],
    )
    builder.annotation(
        view, type_raw=5, name="GTOL1", gtol_frames=[POSITION], attached=[Attach("fac:0001")]
    )
    builder.annotation(view, type_raw=2, name="DATUMTAG1", datum_label="A")
    builder.annotation(view, type_raw=2, name="DATUMTAG2", datum_label="B")
    builder.annotation(
        view,
        type_raw=7,
        name="SFSYMBOL1",
        surface_finish_symbol=1,
        surface_finish_texts=["1.6", ""],
        attached=[Attach("fac:0002")],
    )

    drawing_b = builder.drawing(
        builder.drawing_document(
            "FICT-TULMKALO-3001-B", properties=title_properties("FICT-TULMKALO-3001-B")
        )
    )
    sheet_b = builder.sheet(drawing_b, "Sheet1")
    other = builder.view(sheet_b, "Drawing View1", references=plate, configuration="FICT-VENTA")
    builder.dimension(
        other,
        "KALOMIR21@FICT-TULMKALO-3001",
        value_mm=3.0,
        tolerance=("bilateral", 0.020, 0.005),
        tolerance_type_raw=2,
        attached=[Attach("fac:0001")],
    )
    stale = builder.view(
        sheet_b, "Drawing View2", references=plate, out_of_date=True, orientation="*Top"
    )
    builder.dimension(
        stale,
        "KALOMIR22@FICT-TULMKALO-3001",
        value_mm=4.5,
        precision=3,
        attached=[Attach("fac:0002")],
    )

    builder.candidate("doc:0003")
    return Built(package=builder.build(), meshes=tolerances.meshes)


# --- drawing-root ---------------------------------------------------------------------------

ROOT = "FICT-OKTAPELIN-4000"
PART = "FICT-OKTAPELIN-4001"
SUB = "FICT-OKTAQUILL-4002"
INNER = "FICT-OKTASORN-4003"


def without_configuration(package: EvidencePackage, root: str) -> EvidencePackage:
    """`package` as a drawing root's dump writes it: the drawing binds no configuration
    (`contracts/attach.md` section 2), so the design, the drawing's document row and manifest
    entry, and the forest's root node carry the empty string, where feature 006's builder -
    written before a drawing could be attached - gave them the models' `Default`."""
    return package.model_copy(
        update={
            "design": package.design.model_copy(update={"active_configuration": ""}),
            "documents": [
                document.model_copy(update={"configurations": [], "active_configuration": ""})
                if document.document_id == root
                else document
                for document in package.documents
            ],
            "manifest": package.manifest.model_copy(
                update={
                    "entries": [
                        entry.model_copy(update={"configuration": ""})
                        if entry.document_id == root
                        else entry
                        for entry in package.manifest.entries
                    ]
                }
            ),
            "components": [
                component.model_copy(update={"referenced_configuration": ""})
                if component.document_id == root and component.parent_id is None
                else component
                for component in package.components
            ],
        }
    )


def build_drawing_root() -> Built:
    # Feature 006's builder lays out the documents, the synthesized forest and the extractor
    # block exactly as a standards dump of a drawing root writes them; the views below name the
    # two referenced models so that forest is the one the record's views imply.
    base = standards_package(
        documents=[
            DrawingSpec(
                name=ROOT,
                active_sheet="Sheet1",
                sheets=(
                    SheetSpec(
                        "Sheet1",
                        views=(
                            ViewSpec("Drawing View1", references=PART),
                            ViewSpec("Drawing View2", references=SUB),
                        ),
                    ),
                ),
            ),
            PartSpec(name=PART, material="Alloy Steel"),
            AssemblySpec(name=SUB, components=(ComponentSpec(name=f"{INNER}-1", document=INNER),)),
            PartSpec(name=INNER, material="6061-T6"),
        ],
        vault_root=f"{FICTIONAL_ROOT}Vault",
    )
    base = without_configuration(base, base.design.root_assembly_document_id)
    builder = DrawingBuilder(base, package_id=ROOT_ID)
    ids = {
        document.file_name.rsplit(".", 1)[0]: document.document_id for document in base.documents
    }
    face = AttachedFace(persist_ref=persist_ref("fac:0001"), scope=ids[PART], via="face")

    record = builder.drawing(ids[ROOT])
    first = builder.sheet(record, "Sheet1")
    frame = builder.view(
        first,
        "Sheet Format1",
        view_type_raw=1,
        configuration=None,
        out_of_date=None,
        loaded=None,
        scale_decimal=None,
        orientation=None,
    )
    builder.note(frame, "MERIDIAN-EMBARGO")
    builder.revision_table(
        first,
        rows=[["REV", "DESCRIPTION", "DATE"], ["AA", "FICTIONAL RELEASE", "2026-09-23"]],
        current_revision="AA",
    )
    part_view = builder.view(first, "Drawing View1", references=ids[PART])
    builder.dimension(
        part_view,
        "KALOMIR31@FICT-OKTAPELIN-4001",
        value_mm=10.0,
        tolerance=("symmetric", 0.05, None),
        tolerance_type_raw=4,
        fit_hole_class=None,
        attached=[face],
    )
    builder.dimension(
        part_view,
        "KALOMIR32@FICT-OKTAPELIN-4001",
        value_mm=6.0,
        tolerance_type_raw=7,
        fit_hole_class="H7",
        fit_shaft_class="g6",
        hole_callout=True,
        callout_variables=["<MOD-DIAM>6.00 THRU"],
        below="THRU",
        attached=[face],
    )
    builder.dimension(
        part_view,
        "KALOMIR33@FICT-OKTAPELIN-4001",
        value_mm=12.0,
        overridden=True,
        override_mm=12.5,
        is_reference=True,
        driven_state_raw=2,
    )
    builder.annotation(
        part_view,
        type_raw=5,
        name="GTOL1",
        gtol_frames=[POSITION],
        datum_identifier="C",
        attached=[face],
    )
    builder.annotation(part_view, type_raw=2, name="DATUMTAG1", datum_label="C")
    builder.annotation(
        part_view,
        type_raw=7,
        name="SFSYMBOL1",
        surface_finish_symbol=2,
        surface_finish_texts=["3.2"],
    )
    builder.view(first, "Drawing View2", references=ids[SUB], orientation="*Top")

    second = builder.sheet(record, "Sheet2", first_angle=True, scale=(1.0, 2.0))
    detail = builder.view(
        second, "Drawing View3", references=ids[PART], orientation="*Right", scale_decimal=0.5
    )
    builder.table(
        second,
        detail,
        type_raw=2,
        title="FICTIONAL PARTS LIST",
        rows=[["ITEM", "QTY"], ["1", "1"], ["2", "1"]],
        bom_rows=[
            BomRow(index=1, document_ids=[ids[PART]]),
            BomRow(index=2, document_ids=[ids[INNER]]),
        ],
    )

    third = builder.sheet(record, "Sheet3")
    builder.gap(
        kind="not_extracted",
        entity_kind="drawing_sheet_views",
        entity_id=third.id,
        reason=(
            "Sheet 'Sheet3' was not the active sheet and listed no views, so nothing on it "
            "could be read. The sheet was not activated to look again."
        ),
        error=None,
    )
    return Built(package=builder.build(profile="standards"), meshes={})


# --- assembly-drawings ----------------------------------------------------------------------


def build_assembly_drawings() -> Built:
    base = PackageBuilder(design_stem="FICT-OKTAVEN-5000", schema_version="1.6.0")
    kalo = base.document("FICT-OKTAKALO-5001", "part", material="6061-T6")
    sorn = base.document("FICT-OKTASORN-5002", "part", material="Alloy Steel")
    mir = base.document("FICT-OKTAMIR-5003", "part", material="Alloy Steel")
    for document in (kalo, sorn, mir):
        base.component(document)
    built = base.build()

    builder = DrawingBuilder(built.package, package_id=ASSEMBLY_ID)
    root = built.package.design.root_assembly_document_id

    assembly_drawing = builder.drawing(builder.drawing_document("FICT-OKTAVEN-5000"))
    sheet = builder.sheet(assembly_drawing, "Sheet1")
    iso = builder.view(sheet, "Drawing View1", references=root, orientation="*Top")
    builder.table(
        sheet,
        iso,
        type_raw=2,
        title="FICTIONAL PARTS LIST",
        rows=[["ITEM", "QTY"], ["1", "1"], ["2", "1"], ["3", "1"], ["4", "2"]],
        bom_rows=[
            BomRow(index=1, document_ids=[kalo]),
            BomRow(index=2, document_ids=[sorn]),
            BomRow(index=3, document_ids=[mir]),
            BomRow(index=4, unresolved_paths=[f"{FICTIONAL_ROOT}Kalo\\FICT-NIXA-5009.SLDPRT"]),
        ],
    )
    outside = builder.view(
        sheet,
        "Drawing View2",
        referenced_model_path=f"{FICTIONAL_ROOT}Other\\FICT-ZEPH-5999.SLDPRT",
        configuration="Default",
    )
    builder.gap(
        kind="not_extracted",
        entity_kind="drawing_referenced_document",
        entity_id=outside.id,
        reason=(
            f"references '{FICTIONAL_ROOT}Other\\FICT-ZEPH-5999.SLDPRT', which is not part of "
            "this review"
        ),
        error=None,
    )

    for number, stem in enumerate(
        ("FICT-OKTAKALO-5001", "FICT-OKTAKALO-5001-B", "FICT-OKTAKALO-5001-C"), start=51
    ):
        record = builder.drawing(builder.drawing_document(stem))
        view = builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=kalo)
        builder.dimension(view, f"KALOMIR{number}@FICT-OKTAKALO-5001", value_mm=5.0)

    return Built(package=builder.build(), meshes=built.meshes)


FIXTURES = {
    "plate-drawing": build_plate_drawing,
    "drawing-root": build_drawing_root,
    "assembly-drawings": build_assembly_drawings,
}


def render_all() -> dict[str, bytes]:
    """`{<fixture>/<relative path>: bytes}` for every file this script writes."""
    return {
        f"{name}/{relative}": content
        for name, build in FIXTURES.items()
        for relative, content in build().render().items()
    }


def main() -> None:
    for relative, content in render_all().items():
        path = FIXTURE_DIR / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        print(f"wrote {path.relative_to(FIXTURE_DIR)}")


if __name__ == "__main__":
    main()
