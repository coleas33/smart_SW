"""Generate the `standards-seeded` golden: one violation of each of the sixteen checks (T053).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-seeded/generate_package.py

A script rather than a hand-built JSON, for the reason every other golden is one: the shape
of a standards package - the synthesized forest root of a drawing-rooted dump, one
`ComponentInstance` per occurrence with its `parent_id` and `full_path`, mate entities
resolved to instance ids, `feat:` ids allocated in traversal order, `cut:`/`dsh:`/`dvw:`
ids across the package - is what `tests/support/standards.py` already lays out, and a
second hand-maintained copy of that knowledge would drift from the builder the unit tests
use. The *intent* - which check each document, component, feature and dimension seeds -
lives here and is readable without reading the JSON.

**The root is the drawing** (`MR-90001`), because a standards run grades the drawing only
when it is the document that was opened (FR-003, `checks/standards/traversal.py`): a
drawing-rooted dump hangs one subtree per referenced model under a synthesized forest root,
so the assembly its views reference and every part below it are graded in the same run.

**The package holds exactly one assembly document** (SC-001, quickstart Scenario 1). A
second assembly would force difference h's rows - `mate_references` unresolved once per
sub-assembly and the mate-count branch of `fully_mated` - which the finding count excludes.

What each of the sixteen checks is seeded by, one violation in one document each:

| check | seeded by |
| --- | --- |
| `assembly.not_exploded` | `MR-20001` is left exploded |
| `assembly.rebuild_errors` | `MR-20001` records three document-level rebuild errors |
| `assembly.mate_references` | the second mate has one entity that did not resolve |
| `assembly.one_fixed` | three of the twenty `MR-10001` instances are fixed |
| `assembly.fully_mated` | `MR-10002-2` is under-constrained and under no library prefix |
| `assembly.not_transparent` | `MR-10002-3` carries a component-level appearance override |
| `assembly.not_hidden` | `MR-10002-4` is hidden |
| `part.sketches_fully_defined` | `Sketch2`, under-defined, **inside** a derived feature |
| `part.rebuild_errors` | `Rib1`, error code 1, **inside** a folder, plus `MR-10001`'s count |
| `part.material_assigned` | `MR-10001` has neither a material nor a mass override |
| `part.cut_list_excluded` | one `MR-10001` cut-list item is not excluded |
| `document.data_card_complete` | `MR-10002` has one blank field and one absent field |
| `drawing.dimensions_not_overridden` | six overridden dimensions on one view |
| `drawing.annotations_not_dangling` | one dangling annotation |
| `drawing.revision_matches` | the table's last data row says `AC`; the drawing says `AB` |
| `drawing.no_itar_statement` | a sheet-format note carries the profile's phrase |

`assembly.not_transparent` is **one unresolved row and no finding** while
`assembly.TRANSPARENCY_POLARITY` is `unsettled` (SC-014), and the four drawing checks are
unresolved over `MR-90001` until their evaluators land (T066), so this fixture produces
eleven findings today and fifteen after US2 (T070).

**Both halves of SC-006 that belong here**: the failing part `MR-10001` is reached through
**twenty** component instances, and the overridden-dimension violation is **six dimensions
on one drawing** - one finding each, whatever the multiplicity.
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

DRAWING = "MR-90001"
ASSEMBLY = "MR-20001"
FAILING_PART = "MR-10001"
CARD_PART = "MR-10002"
LIBRARY_PART = "MR-10003"

JOB_FOLDER = "jobs/main"
LIBRARY_FOLDER = "catalog/screws/hex"
"""Under the profile's **one**-mate prefix, which is longer than the two-mate prefix that
also matches it - so the library component below needs one unsuppressed mate, not two."""

MATERIAL = "Fictional Alloy 1"
CONFIGURATION = PROFILE.material.configuration
"""Every part is read in the configuration the profile names its material one, so
`part.material_assigned` grades the material rather than reporting the configuration
mismatch that is its own unresolved row."""

INSTANCES = 20
"""SC-006: the failing part is reached through twenty instances and still yields one
finding per failing check, naming all twenty."""

FIXED = 3
"""`assembly.one_fixed` fails at two; three makes it unambiguous that the count is read and
not the presence of a fixed component."""

OVERRIDDEN_DIMENSIONS = 6
"""SC-006's drawing half: six subjects inside one finding, not six findings."""

DEFINED = 3
UNDER_DEFINED = 2
"""`swConstrainedStatus_e`: 3 is fully constrained, 2 under-constrained."""

HIDDEN = 0


def drawing() -> DrawingSpec:
    """The root drawing: one sheet, a sheet-format view and one view of the assembly."""
    return DrawingSpec(
        name=DRAWING,
        folder=JOB_FOLDER,
        properties=card(PROFILE, revision="AB"),
        active_sheet="Sheet1",
        sheets=(
            SheetSpec(
                name="Sheet1",
                was_active=True,
                views=(
                    ViewSpec(
                        name="Sheet Format",
                        view_type_raw=1,
                        notes=(
                            NoteSpec(f"THIS DRAWING CARRIES {PROFILE.export_control.phrase} DATA"),
                            NoteSpec("UNLESS OTHERWISE SPECIFIED, BREAK ALL SHARP EDGES"),
                        ),
                    ),
                    ViewSpec(
                        name="Drawing View1",
                        references=ASSEMBLY,
                        dimensions=(
                            *(
                                DimensionSpec(
                                    name=f"D{number}@Drawing View1",
                                    is_overridden=True,
                                    value_mm=10.0 + number,
                                    override_mm=99.0 + number,
                                )
                                for number in range(1, OVERRIDDEN_DIMENSIONS + 1)
                            ),
                            DimensionSpec(name="D7@Drawing View1", value_mm=42.0),
                        ),
                        annotations=(
                            AnnotationSpec(name="Note1", is_dangling=False),
                            AnnotationSpec(name="Datum1", type_raw=5, is_dangling=True),
                        ),
                    ),
                ),
                revision_tables=(
                    RevisionTableSpec(
                        rows=(
                            ("ZONE", "REV", "DESCRIPTION"),
                            ("A1", "AC", "Released for manufacture"),
                        ),
                        current_revision_raw="AC",
                    ),
                ),
            ),
        ),
    )


def components() -> tuple[ComponentSpec, ...]:
    """Twenty instances of the failing part, plus the five the assembly checks read."""
    return (
        *(
            ComponentSpec(
                name=f"{FAILING_PART}-{number}",
                document=FAILING_PART,
                is_fixed=number <= FIXED,
                constrained_status_raw=DEFINED,
            )
            for number in range(1, INSTANCES + 1)
        ),
        ComponentSpec(name=f"{CARD_PART}-1", document=CARD_PART, constrained_status_raw=DEFINED),
        ComponentSpec(
            name=f"{CARD_PART}-2", document=CARD_PART, constrained_status_raw=UNDER_DEFINED
        ),
        ComponentSpec(
            name=f"{CARD_PART}-3",
            document=CARD_PART,
            constrained_status_raw=DEFINED,
            has_appearance_override=True,
            transparency_raw=0.6,
        ),
        ComponentSpec(
            name=f"{CARD_PART}-4",
            document=CARD_PART,
            constrained_status_raw=DEFINED,
            visibility_raw=HIDDEN,
        ),
        ComponentSpec(
            name=f"{LIBRARY_PART}-1",
            document=LIBRARY_PART,
            constrained_status_raw=UNDER_DEFINED,
        ),
    )


def mates() -> tuple[MateSpec, ...]:
    """One mate that resolves - and satisfies the library component's one-mate minimum -
    and one that has lost an entity."""
    return (
        MateSpec(
            entities=(
                MateEntitySpec(f"{LIBRARY_PART}-1", "swSelDATUMPLANES"),
                MateEntitySpec(f"{FAILING_PART}-4", "swSelDATUMPLANES"),
            )
        ),
        MateSpec(
            type="CONCENTRIC",
            entities=(
                MateEntitySpec(f"{CARD_PART}-1", "swSelFACES", resolution_status="unresolved"),
                MateEntitySpec(f"{FAILING_PART}-5", "swSelFACES"),
            ),
        ),
    )


def failing_part() -> PartSpec:
    """Every part-scope violation, two of them at depth (difference z)."""
    return PartSpec(
        name=FAILING_PART,
        folder=JOB_FOLDER,
        configuration=CONFIGURATION,
        properties=card(PROFILE),
        rebuild_error_count=2,
        material=None,
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
            FeatureSpec(
                "Derived-Pocket",
                "IndentFeature",
                contents=(
                    FeatureSpec(
                        "Sketch2",
                        "ProfileFeature",
                        sketch=SketchSpec(raw_status=UNDER_DEFINED, text_segments=0),
                    ),
                ),
            ),
            FeatureSpec(
                "Stiffeners",
                "FtrFolder",
                contents=(FeatureSpec("Rib1", "Rib", error_code=1),),
            ),
            FeatureSpec(
                "Sketch-Label",
                "ProfileFeature",
                sketch=SketchSpec(raw_status=UNDER_DEFINED, text_segments=2),
            ),
        ),
        cut_list=(CutListSpec(name="Tube 40 x 40 x 3", excluded_from_cut_list=False),),
    )


def compliant_part(name: str, folder: str, properties: dict[str, str]) -> PartSpec:
    """A part that passes or is skipped on every part check, whatever its folder."""
    return PartSpec(
        name=name,
        folder=folder,
        configuration=CONFIGURATION,
        properties=properties,
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


def build() -> EvidencePackage:
    return standards_package(
        profile=PROFILE,
        documents=(
            drawing(),
            AssemblySpec(
                name=ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE),
                is_exploded=True,
                rebuild_error_count=3,
                components=components(),
                mates=mates(),
            ),
            failing_part(),
            compliant_part(CARD_PART, JOB_FOLDER, card(PROFILE, blank=(1,), absent=(3,))),
            compliant_part(LIBRARY_PART, LIBRARY_FOLDER, card(PROFILE)),
        ),
    )


def main() -> None:
    write_fixture(FIXTURE_DIR, build())


if __name__ == "__main__":
    main()
