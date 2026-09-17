"""Generate the `standards-compliant-flat` golden: the narrowest fixture there is (T054).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-compliant-flat/generate_package.py

SC-002's second half, and the **only** fixture in the suite that can reach `ready`. A
single-level root assembly `MR-22001` with no sub-assembly, its two parts, and one drawing -
which is the root, so that the drawing is graded at all (FR-003).

No sub-assembly is what removes difference h's two unresolved rows: the root assembly's
mate group is the one a native dump walks, so `standards.assembly.mate_references` and the
mate-count branch of `standards.assembly.fully_mated` both have their evidence here. What
is left unresolved is only what this build cannot answer yet:
`standards.assembly.not_transparent` until SC-014 settles the polarity, and the four
drawing checks until T066 binds their evaluators. When both land this run is `ready` with
zero unresolved checks (T069a).

The single sheet records a **type-1 sheet-format view**, without which
`standards.drawing.no_itar_statement` is unresolved per sheet and `ready` is unreachable
(`contracts/rules.md`). The fixture carries a drawing, so the headline must **not** carry
the "no drawing graded" note - which is the other thing a narrow fixture is easy to get
wrong.
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
    CutListSpec,
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

from swreview.ir.models import EvidencePackage  # noqa: E402

PROFILE = fixture_profile()

DRAWING = "MR-92001"
ASSEMBLY = "MR-22001"
CUT_LIST_PART = "MR-12001"
PLAIN_PART = "MR-12002"

JOB_FOLDER = "jobs/lite"
MATERIAL = "Fictional Alloy 3"
CONFIGURATION = PROFILE.material.configuration
REVISION = PROFILE.revision.initial

DEFINED = 3


def drawing() -> DrawingSpec:
    return DrawingSpec(
        name=DRAWING,
        folder=JOB_FOLDER,
        properties=card(PROFILE, revision=REVISION),
        active_sheet="Sheet1",
        sheets=(
            SheetSpec(
                name="Sheet1",
                was_active=True,
                views=(
                    ViewSpec(
                        name="Sheet Format",
                        view_type_raw=1,
                        notes=(NoteSpec("TOLERANCES UNLESS OTHERWISE STATED: +/- 0.2"),),
                    ),
                    ViewSpec(
                        name="Drawing View1",
                        references=ASSEMBLY,
                        dimensions=(DimensionSpec(name="D1@Drawing View1", value_mm=18.0),),
                        annotations=(AnnotationSpec(name="Balloon1"),),
                    ),
                ),
                revision_tables=(
                    RevisionTableSpec(
                        rows=(
                            ("ZONE", "REV", "DESCRIPTION"),
                            ("A1", REVISION, "Initial release"),
                        ),
                        current_revision_raw=REVISION,
                    ),
                ),
            ),
        ),
    )


def part(name: str, *, cut_list: bool = False) -> PartSpec:
    return PartSpec(
        name=name,
        folder=JOB_FOLDER,
        configuration=CONFIGURATION,
        properties=card(PROFILE, revision=REVISION),
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
        cut_list=((CutListSpec(name="Angle 30 x 30 x 3"),) if cut_list else ()),
    )


def build() -> EvidencePackage:
    return standards_package(
        profile=PROFILE,
        documents=(
            drawing(),
            AssemblySpec(
                name=ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=REVISION),
                components=(
                    ComponentSpec(
                        name=f"{CUT_LIST_PART}-1",
                        document=CUT_LIST_PART,
                        is_fixed=True,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{PLAIN_PART}-1",
                        document=PLAIN_PART,
                        constrained_status_raw=DEFINED,
                    ),
                ),
                mates=(
                    MateSpec(
                        entities=(
                            MateEntitySpec(f"{CUT_LIST_PART}-1", "swSelDATUMPLANES"),
                            MateEntitySpec(f"{PLAIN_PART}-1", "swSelDATUMPLANES"),
                        )
                    ),
                ),
            ),
            part(CUT_LIST_PART, cut_list=True),
            part(PLAIN_PART),
        ),
    )


def main() -> None:
    write_fixture(FIXTURE_DIR, build())


if __name__ == "__main__":
    main()
