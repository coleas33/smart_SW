"""Generate the `standards-compliant` golden: parts, sub-assemblies and drawings (T054).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-compliant/generate_package.py

SC-002's first half. Every one of the sixteen checks has something to say about this
package and **none of them has a finding to report**, which is the only way to tell a check
that passed from a check that never ran. What it costs to get there is the point of the
fixture: two of the rows are *unresolved* and they are unresolved by design.

- `standards.assembly.mate_references` and the mate-count branch of
  `standards.assembly.fully_mated` are unresolved on the **sub-assembly** `MR-21002`,
  because a native dump walks only the root assembly's mate group (difference h). Nothing
  here can close that gap; the fixture states it instead of hiding it;
- `standards.assembly.not_transparent` is unresolved on every assembly while
  `TRANSPARENCY_POLARITY` is `unsettled` (SC-014);
- the four drawing checks are unresolved until their evaluators land (T066). T069a
  completes SC-002's drawing half over this fixture and `standards-compliant-flat`.

The verdict is therefore `ready_coverage_incomplete` and not `ready`:
`standards-compliant-flat` is the fixture that reaches `ready`, and it is deliberately the
narrowest one in the suite.

**The root is the drawing**, so that the drawing is graded at all (FR-003), and each sheet
records a **type-1 sheet-format view**: without one, `standards.drawing.no_itar_statement`
is unresolved per sheet and `ready` is unreachable (`contracts/rules.md`).
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

DRAWING = "MR-91001"
ROOT_ASSEMBLY = "MR-21001"
SUB_ASSEMBLY = "MR-21002"
CUT_LIST_PART = "MR-11001"
PLAIN_PART = "MR-11002"
LIBRARY_PART = "MR-11003"
SUB_PART = "MR-11004"

JOB_FOLDER = "jobs/flight"
LIBRARY_FOLDER = "catalog/screws"
"""A two-mate library prefix. The component under it is under-constrained, which is what
makes `fully_mated`'s mate-count branch reach the sub-assembly's missing mate data."""

MATERIAL = "Fictional Alloy 2"
CONFIGURATION = PROFILE.material.configuration
REVISION = PROFILE.revision.initial
"""Every document carries the profile's initial revision, so the revision table, the
drawing's property and the referenced model all agree (graded from T066)."""

DEFINED = 3
UNDER_DEFINED = 2


def sheet(name: str, was_active: bool) -> SheetSpec:
    """One compliant sheet: a sheet-format view, a view of the assembly, a revision table."""
    return SheetSpec(
        name=name,
        was_active=was_active,
        views=(
            ViewSpec(
                name=f"Sheet Format {name}",
                view_type_raw=1,
                notes=(NoteSpec("UNLESS OTHERWISE SPECIFIED, DIMENSIONS ARE IN MILLIMETRES"),),
            ),
            ViewSpec(
                name=f"Drawing View {name}",
                references=ROOT_ASSEMBLY,
                dimensions=(DimensionSpec(name=f"D1@{name}", value_mm=25.0),),
                annotations=(AnnotationSpec(name=f"Balloon1@{name}"),),
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
    )


def drawing() -> DrawingSpec:
    return DrawingSpec(
        name=DRAWING,
        folder=JOB_FOLDER,
        properties=card(PROFILE, revision=REVISION),
        active_sheet="Sheet1",
        sheets=(sheet("Sheet1", was_active=True), sheet("Sheet2", was_active=False)),
    )


def part(name: str, folder: str, *, cut_list: bool = False) -> PartSpec:
    """A part that passes or is skipped on every part check."""
    return PartSpec(
        name=name,
        folder=folder,
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
        cut_list=(
            (CutListSpec(name="Plate 200 x 100 x 6"),) if cut_list else ()
        ),
    )


def build() -> EvidencePackage:
    return standards_package(
        profile=PROFILE,
        documents=(
            drawing(),
            AssemblySpec(
                name=ROOT_ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=REVISION),
                components=(
                    ComponentSpec(
                        name=f"{SUB_ASSEMBLY}-1",
                        document=SUB_ASSEMBLY,
                        is_fixed=True,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{CUT_LIST_PART}-1",
                        document=CUT_LIST_PART,
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
                            MateEntitySpec(f"{SUB_ASSEMBLY}-1", "swSelDATUMPLANES"),
                            MateEntitySpec(f"{CUT_LIST_PART}-1", "swSelDATUMPLANES"),
                        )
                    ),
                ),
            ),
            AssemblySpec(
                name=SUB_ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE, revision=REVISION),
                components=(
                    ComponentSpec(
                        name=f"{SUB_PART}-1",
                        document=SUB_PART,
                        parent=f"{SUB_ASSEMBLY}-1",
                        is_fixed=True,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{LIBRARY_PART}-1",
                        document=LIBRARY_PART,
                        parent=f"{SUB_ASSEMBLY}-1",
                        constrained_status_raw=UNDER_DEFINED,
                    ),
                ),
            ),
            part(CUT_LIST_PART, JOB_FOLDER, cut_list=True),
            part(PLAIN_PART, JOB_FOLDER),
            part(LIBRARY_PART, LIBRARY_FOLDER),
            part(SUB_PART, JOB_FOLDER),
        ),
    )


def main() -> None:
    write_fixture(FIXTURE_DIR, build())


if __name__ == "__main__":
    main()
