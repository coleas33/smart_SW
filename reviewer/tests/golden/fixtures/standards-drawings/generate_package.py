"""Generate the `standards-drawings` golden case group: every sheet, every relationship (T069).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-drawings/generate_package.py

**Five packages, not one.** A standards run grades the drawing that was *opened* and no
other (`checks/standards/traversal.py`: the graded set is the root, what a root drawing's
views reference, and what hangs below those). So the five drawings T069 enumerates are five
roots, and therefore five packages, held together as one case group the way
`fixtures/remodel-plan/` holds feature 004's - `tests/golden/test_golden.py` reads a
directory with no `case.json` as a group and grades its subdirectories.

One generator for all five, because everything they share - the fictional profile, the data
card, a compliant part, a compliant assembly - would otherwise be written five times and be
free to drift five ways (constitution Principle V).

- **`standards-drawings-seeded`** - the three-sheet drawing: one overridden dimension on
  sheet 1, one dangling annotation on sheet 2, a revision table **on sheet 2** whose last
  data row disagrees with the drawing's revision property, and the profile's export-control
  phrase in a note on **sheet 3**;
- **`standards-drawings-compliant`** - the drawing that passes: its file name follows the
  part-number pattern, its table agrees with its property and its referenced model carries
  the same revision, so it yields five checked rows and no finding;
- **`standards-drawings-ingested`** - a drawing whose only sheet evidence is PDF-ingested:
  all four drawing checks unresolved naming the evidence source (FR-024);
- **`standards-drawings-two-models`** - a drawing whose views reference **two** models, both
  graded and both disagreements named in the one revision warning; the second of them is
  also a component of the first, so it is reached twice and graded **once** (FR-003);
- **`standards-drawings-no-views`** - a drawing with no views at all: its own checks still
  run and the model comparison is unresolved naming that it references no document
  (difference f).

The violations are deliberately spread **across** the three sheets of the seeded drawing:
a drawing dumper that read only the active sheet would find the overridden dimension and
miss the other three, and that is the failure difference q exists to catch.

Nothing here spells out a company value: the revision property, its initial value, the
part-number pattern and the export-control phrase are all read off the fictional profile
(FR-001, T002).
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.checks.standards_fixtures import card, fixture_profile, write_fixture  # noqa: E402
from tests.support.features import FeatureSpec, SketchSpec  # noqa: E402
from tests.support.standards import (  # noqa: E402
    AnnotationSpec,
    AssemblySpec,
    ComponentSpec,
    DimensionSpec,
    DrawingSpec,
    MateEntitySpec,
    MateSpec,
    NoteSpec,
    PartSpec,
    RevisionTableSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

from swreview.ir.models import DrawingSheet, EvidencePackage  # noqa: E402

PROFILE = fixture_profile()

JOB_FOLDER = "jobs/drawings"
MATERIAL = "Fictional Alloy 5"
CONFIGURATION = PROFILE.material.configuration
DEFINED = 3
"""`swConstrainedStatus_e` 3: fully constrained, so no assembly check has anything to say."""

RELEASED = PROFILE.revision.initial
"""What a compliant document's revision property holds."""

SEEDED_REVISION = "AB"
SEEDED_TABLE_REVISION = "AC"
"""The seeded disagreement: the drawing's property says one thing, its table another."""

STALE_MODEL_REVISION = "AB"
"""What the two referenced models of the two-model case say, against the drawing's
`RELEASED` - one warning naming both."""

OVERRIDE_MM = 99.5
MODELLED_MM = 12.5
"""Rendered with the unit the package recorded, never as a bare number (difference p)."""

BENIGN_NOTE = "UNLESS OTHERWISE SPECIFIED, BREAK ALL SHARP EDGES"


# --- the pieces every case is built from --------------------------------------------------


def part(name: str, revision: str = RELEASED) -> PartSpec:
    """A part that passes or is skipped on every part check."""
    return PartSpec(
        name=name,
        folder=JOB_FOLDER,
        configuration=CONFIGURATION,
        properties=card(PROFILE, revision=revision),
        material=MATERIAL,
        mass_overridden=False,
        features=(
            FeatureSpec(
                "Boss-Extrude1",
                "Extrude",
                contents=(
                    FeatureSpec(
                        "Sketch1",
                        "ProfileFeature",
                        sketch=SketchSpec(raw_status=DEFINED, text_segments=0),
                    ),
                ),
            ),
        ),
    )


def assembly(name: str, parts: tuple[str, ...], revision: str = RELEASED) -> AssemblySpec:
    """A flat, compliant assembly of `parts`: one fixed child, every child constrained.

    Flat on purpose: a sub-assembly would add difference h's two unresolved rows to every
    case here, and what these fixtures are about is the drawing.
    """
    return AssemblySpec(
        name=name,
        folder=JOB_FOLDER,
        properties=card(PROFILE, revision=revision),
        components=tuple(
            ComponentSpec(
                name=f"{child}-1",
                document=child,
                is_fixed=index == 0,
                constrained_status_raw=DEFINED,
            )
            for index, child in enumerate(parts)
        ),
        mates=(
            MateSpec(
                entities=tuple(
                    MateEntitySpec(f"{child}-1", "swSelDATUMPLANES") for child in parts
                )
            ),
        ),
    )


def sheet_format_view(sheet_name: str, *notes: str) -> ViewSpec:
    """The type-1 sheet-format pseudo-view, which is where notes live.

    Every sheet of every drawing here records one: without it
    `standards.drawing.no_itar_statement` is unresolved for that sheet, and a fixture that
    left it out would report that gap instead of whatever it was written to show
    (`contracts/rules.md`).
    """
    return ViewSpec(
        name=f"Sheet Format {sheet_name}",
        view_type_raw=1,
        notes=tuple(NoteSpec(text) for text in notes),
    )


def agreeing_table(revision: str) -> RevisionTableSpec:
    """A revision table whose last data row states `revision` in the cell the profile names."""
    return RevisionTableSpec(
        rows=(
            ("ZONE", "REV", "DESCRIPTION"),
            ("A1", revision, "Initial release"),
        ),
        current_revision_raw=revision,
    )


# --- standards-drawings-seeded ------------------------------------------------------------


def seeded_drawing(name: str, model: str) -> DrawingSpec:
    """Three sheets, one seeded violation each, and the table off the first sheet."""
    return DrawingSpec(
        name=name,
        folder=JOB_FOLDER,
        properties=card(PROFILE, revision=SEEDED_REVISION),
        active_sheet="Sheet1",
        sheets=(
            SheetSpec(
                name="Sheet1",
                was_active=True,
                views=(
                    sheet_format_view("Sheet1", BENIGN_NOTE),
                    ViewSpec(
                        name="Drawing View1",
                        references=model,
                        dimensions=(
                            DimensionSpec(
                                name="D1@Drawing View1",
                                is_overridden=True,
                                value_mm=MODELLED_MM,
                                override_mm=OVERRIDE_MM,
                            ),
                            DimensionSpec(name="D2@Drawing View1", value_mm=30.0),
                        ),
                        annotations=(AnnotationSpec(name="Balloon1"),),
                    ),
                ),
            ),
            SheetSpec(
                name="Sheet2",
                views=(
                    sheet_format_view("Sheet2", BENIGN_NOTE),
                    ViewSpec(
                        name="Drawing View2",
                        references=model,
                        dimensions=(DimensionSpec(name="D3@Drawing View2", value_mm=8.0),),
                        annotations=(
                            AnnotationSpec(name="Datum1", type_raw=5, is_dangling=True),
                            AnnotationSpec(name="Balloon2"),
                        ),
                    ),
                ),
                revision_tables=(
                    RevisionTableSpec(
                        rows=(
                            ("ZONE", "REV", "DESCRIPTION"),
                            ("A1", SEEDED_TABLE_REVISION, "Released for manufacture"),
                        ),
                        current_revision_raw=SEEDED_TABLE_REVISION,
                    ),
                ),
            ),
            SheetSpec(
                name="Sheet3",
                views=(
                    sheet_format_view(
                        "Sheet3",
                        f"THIS DRAWING CARRIES {PROFILE.export_control.phrase} DATA",
                        BENIGN_NOTE,
                    ),
                    ViewSpec(
                        name="Drawing View3",
                        references=model,
                        dimensions=(DimensionSpec(name="D4@Drawing View3", value_mm=5.0),),
                        annotations=(AnnotationSpec(name="Balloon3"),),
                    ),
                ),
            ),
        ),
    )


def build_seeded() -> EvidencePackage:
    drawing, model, first, second = "MR-90101", "MR-20101", "MR-10101", "MR-10102"
    return standards_package(
        profile=PROFILE,
        documents=(
            seeded_drawing(drawing, model),
            assembly(model, (first, second), revision=SEEDED_REVISION),
            part(first),
            part(second),
        ),
    )


# --- standards-drawings-compliant ---------------------------------------------------------


def build_compliant() -> EvidencePackage:
    """The drawing that passes all five of its checks, on two sheets rather than one."""
    drawing, model, first, second = "MR-90201", "MR-20201", "MR-10201", "MR-10202"
    return standards_package(
        profile=PROFILE,
        documents=(
            DrawingSpec(
                name=drawing,
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=RELEASED),
                active_sheet="Sheet1",
                sheets=tuple(
                    SheetSpec(
                        name=sheet_name,
                        was_active=sheet_name == "Sheet1",
                        views=(
                            sheet_format_view(sheet_name, BENIGN_NOTE),
                            ViewSpec(
                                name=f"Drawing View {sheet_name}",
                                references=model,
                                dimensions=(
                                    DimensionSpec(
                                        name=f"D1@{sheet_name}", value_mm=18.0
                                    ),
                                ),
                                annotations=(AnnotationSpec(name=f"Balloon1@{sheet_name}"),),
                            ),
                        ),
                        revision_tables=(agreeing_table(RELEASED),),
                    )
                    for sheet_name in ("Sheet1", "Sheet2")
                ),
            ),
            assembly(model, (first, second)),
            part(first),
            part(second),
        ),
    )


# --- standards-drawings-ingested ----------------------------------------------------------


def build_ingested() -> EvidencePackage:
    """A drawing whose only sheet evidence came from the PDF ingest (FR-024).

    The native record exists and carries **no sheet**, which is what a dump that could not
    read the drawing natively leaves behind; the sheet evidence in `drawings[]` is the
    ingest's, stamped `pdf_ingest` (T068). The four drawing checks may not grade it: a
    parser with known limits must not produce a demonstrated finding.
    """
    drawing = "MR-90301"
    package = standards_package(
        profile=PROFILE,
        documents=(
            DrawingSpec(
                name=drawing,
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=RELEASED),
                active_sheet=None,
                sheets=(),
            ),
        ),
    )
    document_id = next(
        row.document_id for row in package.documents if row.kind == "drawing"
    )
    return package.model_copy(
        update={
            "drawings": [
                DrawingSheet(
                    document_id=document_id,
                    sheet_name="Sheet1",
                    page=1,
                    scale=None,
                    units="mm",
                    general_notes=[],
                    dimensions=[],
                    views=[],
                    parse_status="text",
                    parser="pdf-text",
                    source="pdf_ingest",
                )
            ]
        }
    )


# --- standards-drawings-two-models --------------------------------------------------------


def build_two_models() -> EvidencePackage:
    """Two referenced models, one of which the other's tree also reaches (FR-003).

    The drawing states the released revision and both models state a different one, so the
    one revision warning names **both** disagreements; and the part is reached once from a
    view and once through the assembly's component tree, and is graded once.
    """
    drawing, model, shared, other = "MR-90401", "MR-20401", "MR-10401", "MR-10402"
    return standards_package(
        profile=PROFILE,
        documents=(
            DrawingSpec(
                name=drawing,
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=RELEASED),
                active_sheet="Sheet1",
                sheets=(
                    SheetSpec(
                        name="Sheet1",
                        was_active=True,
                        views=(
                            sheet_format_view("Sheet1", BENIGN_NOTE),
                            ViewSpec(
                                name="Drawing View1",
                                references=model,
                                dimensions=(DimensionSpec(name="D1@Sheet1", value_mm=40.0),),
                            ),
                            ViewSpec(
                                name="Detail View A",
                                references=shared,
                                dimensions=(DimensionSpec(name="D2@Sheet1", value_mm=6.0),),
                            ),
                        ),
                        revision_tables=(agreeing_table(RELEASED),),
                    ),
                ),
            ),
            AssemblySpec(
                name=model,
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=STALE_MODEL_REVISION),
                components=(
                    ComponentSpec(
                        name=f"{shared}-1",
                        document=shared,
                        is_fixed=True,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{other}-1",
                        document=other,
                        constrained_status_raw=DEFINED,
                    ),
                ),
                mates=(
                    MateSpec(
                        entities=(
                            MateEntitySpec(f"{shared}-1", "swSelDATUMPLANES"),
                            MateEntitySpec(f"{other}-1", "swSelDATUMPLANES"),
                        )
                    ),
                ),
            ),
            part(shared, revision=STALE_MODEL_REVISION),
            part(other),
        ),
    )


# --- standards-drawings-no-views ----------------------------------------------------------


def build_no_views() -> EvidencePackage:
    """A drawing whose sheets record no view at all (difference f).

    Nothing crashes: the dimension and annotation checks are skipped because there is
    nothing to grade, the revision table is still compared against the drawing's property,
    and the **model** comparison is unresolved because there is no referenced document to
    make it against.
    """
    return standards_package(
        profile=PROFILE,
        documents=(
            DrawingSpec(
                name="MR-90501",
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=RELEASED),
                active_sheet="Sheet1",
                sheets=(
                    SheetSpec(
                        name="Sheet1",
                        was_active=True,
                        views=(),
                        revision_tables=(agreeing_table(RELEASED),),
                    ),
                ),
            ),
        ),
    )


BUILDERS = {
    "standards-drawings-seeded": build_seeded,
    "standards-drawings-compliant": build_compliant,
    "standards-drawings-ingested": build_ingested,
    "standards-drawings-two-models": build_two_models,
    "standards-drawings-no-views": build_no_views,
}


def main() -> None:
    for case, builder in BUILDERS.items():
        directory = FIXTURE_DIR / case
        directory.mkdir(exist_ok=True)
        write_fixture(directory, builder())


if __name__ == "__main__":
    main()
