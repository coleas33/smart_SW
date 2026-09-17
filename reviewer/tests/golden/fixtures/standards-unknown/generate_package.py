"""Generate the `standards-unknown` golden: unknown stays unknown (T055, model half).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-unknown/generate_package.py

SC-003's model half. The package is **otherwise compliant** - its error count is zero - so
that every row this fixture produces is about a signal that could not be read rather than
about a defect. What it seeds, and what each one must produce:

- **`MR-13002-1` is suppressed** and **`MR-13003-1` is lightweight**: each is skipped, with
  its own state as the reason, on the four instance-signal checks, and the document each of
  them names is unresolved on every check that would have read it. Neither is ever a hidden
  finding (difference c) and neither is a pass;
- **the sub-assembly `MR-30002`**: `mate_references` is unresolved for it, and
  `fully_mated` is unresolved for its under-constrained library-prefix component only,
  because a native dump walks the root assembly's mate group alone (difference h);
- **`MR-13005`'s sketch status is unreadable**: `sketches_fully_defined` is unresolved for
  that part and it is **not** also checked;
- **`MR-13004`'s mass-override flag is unreadable**: `material_assigned` is unresolved for
  that part and it is **not** also checked, because pass and fail differ only by that flag.

The two documents reached **only** through an unresolved instance are the sharp case: a
suppressed or lightweight instance was never opened, so what the package records about the
document it names is not a reading of that document, and every check says so instead of
grading it (FR-005, `results.document_evidence_unresolved`).

**The fixture carries no drawing.** The drawing half - a note whose text could not be read -
arrives with T070a, for the same reason T056 is split: the drawing checks and the drawing
dump do not exist until US2, and the golden is byte-compared, so a drawing added here would
have its coverage rows rewritten at US2 anyway. So the four drawing checks are
`out_of_scope` rows here and the headline carries the "no drawing graded" note.

The verdict is `ready_coverage_incomplete`: zero errors, and coverage that is not complete.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.checks.standards_fixtures import card, fixture_profile, write_fixture  # noqa: E402
from tests.support.features import FeatureSpec, SketchSpec  # noqa: E402
from tests.support.standards import (  # noqa: E402
    AssemblySpec,
    ComponentSpec,
    MateEntitySpec,
    MateSpec,
    PartSpec,
    standards_package,
)

from swreview.ir.models import EvidencePackage  # noqa: E402

PROFILE = fixture_profile()

ROOT_ASSEMBLY = "MR-30001"
SUB_ASSEMBLY = "MR-30002"
PLAIN_PART = "MR-13001"
SUPPRESSED_PART = "MR-13002"
LIGHTWEIGHT_PART = "MR-13003"
UNREADABLE_MASS_PART = "MR-13004"
UNREADABLE_SKETCH_PART = "MR-13005"
LIBRARY_PART = "MR-13006"
SUB_PART = "MR-13007"

JOB_FOLDER = "jobs/probe"
LIBRARY_FOLDER = "catalog/screws"
MATERIAL = "Fictional Alloy 4"
CONFIGURATION = PROFILE.material.configuration

DEFINED = 3
UNDER_DEFINED = 2


def part(
    name: str,
    folder: str = JOB_FOLDER,
    *,
    mass_overridden: bool | None = False,
    sketch_status: int | None = DEFINED,
) -> PartSpec:
    """A compliant part unless one of the two readings is deliberately unreadable."""
    return PartSpec(
        name=name,
        folder=folder,
        configuration=CONFIGURATION,
        properties=card(PROFILE),
        material=MATERIAL,
        mass_overridden=mass_overridden,
        features=(
            FeatureSpec(
                "Boss-Extrude1",
                "Extrude",
                contents=(
                    FeatureSpec(
                        "Sketch1",
                        "ProfileFeature",
                        sketch=SketchSpec(raw_status=sketch_status, text_segments=0),
                    ),
                ),
            ),
        ),
    )


def build() -> EvidencePackage:
    return standards_package(
        profile=PROFILE,
        documents=(
            AssemblySpec(
                name=ROOT_ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE),
                components=(
                    ComponentSpec(
                        name=f"{SUB_ASSEMBLY}-1",
                        document=SUB_ASSEMBLY,
                        is_fixed=True,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{PLAIN_PART}-1",
                        document=PLAIN_PART,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{SUPPRESSED_PART}-1",
                        document=SUPPRESSED_PART,
                        suppression="suppressed",
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{LIGHTWEIGHT_PART}-1",
                        document=LIGHTWEIGHT_PART,
                        suppression="lightweight",
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{UNREADABLE_MASS_PART}-1",
                        document=UNREADABLE_MASS_PART,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{UNREADABLE_SKETCH_PART}-1",
                        document=UNREADABLE_SKETCH_PART,
                        constrained_status_raw=DEFINED,
                    ),
                ),
                mates=(
                    MateSpec(
                        entities=(
                            MateEntitySpec(f"{SUB_ASSEMBLY}-1", "swSelDATUMPLANES"),
                            MateEntitySpec(f"{PLAIN_PART}-1", "swSelDATUMPLANES"),
                        )
                    ),
                ),
            ),
            AssemblySpec(
                name=SUB_ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE),
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
            part(PLAIN_PART),
            part(SUPPRESSED_PART),
            part(LIGHTWEIGHT_PART),
            part(UNREADABLE_MASS_PART, mass_overridden=None),
            part(UNREADABLE_SKETCH_PART, sketch_status=None),
            part(LIBRARY_PART, LIBRARY_FOLDER),
            part(SUB_PART),
        ),
    )


def main() -> None:
    write_fixture(FIXTURE_DIR, build())


if __name__ == "__main__":
    main()
