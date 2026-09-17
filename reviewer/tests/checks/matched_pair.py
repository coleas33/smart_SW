"""The matched pair SC-005's third measurement is made over (T098, quickstart Scenario 6).

One design, built twice: `matched_package(profile)` writes a package whose vault root,
folder prefixes, file names, data-card property names, material configuration, revision
property, revision-table shape and export-control phrase are all read off the profile it is
handed. Graded against its own profile, the two packages must produce **the same sixteen
coverage rows and the same findings by check id** - and the two fictional profiles differ in
every value-bearing field, so a company value compiled into the source fails that even if it
was spelled differently and slipped past T001's grep (FR-001, RK-1).

Written once here rather than twice in the two fixture directories because the two packages
are one design instantiated twice; a second hand-maintained copy of it would drift from this
one the first time either was edited (constitution Principle V). The two
`generate_package.py` scripts under `tests/golden/fixtures/standards-profile-{a,b}/` say
which profile they are for and nothing else.

**Every placement is derived, and then checked.** The job folder must match no list, the
one-mate folder must ask for one mate and the two-mate folder for two, the skip folder must
skip and the sketch-exempt folder must exempt without skipping - in *both* profiles, whose
lists overlap in opposite directions (`contracts/profile.md` prefix semantics rule 6: profile
A's one-mate prefix is the longer of its overlapping pair, profile B's two-mate prefix is).
`_checked_folders` asserts all five, so a fixture that quietly stopped exercising a list
fails here rather than passing as an equality between two packages that test nothing.

**The two mate-library parts carry features but no sketches**, which is the one asymmetry the
two profiles make unavoidable: profile A's one-mate prefix sits under its sketch-exempt
prefix and profile B's does not, so a sketch on those parts would be exempt in A and graded
in B. With no sketch the check is skipped coverage in both, for reasons that differ and
buckets that do not - which is what the comparison is written over.
"""

from __future__ import annotations

from swreview.checks.standards.library import PrefixMatcher
from swreview.checks.standards.profile import StandardsProfile
from swreview.checks.standards.traversal import part_number_matches
from swreview.ir.models import EvidencePackage
from tests.checks.standards_fixtures import card
from tests.support.features import FeatureSpec, SketchSpec
from tests.support.standards import (
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

__all__ = ["JOB_FOLDER", "document_name", "matched_package"]

JOB_FOLDER = "release/pair"
"""Where the documents that are nobody's library live: a folder neither profile's four
lists name, so the parts in it are graded on every check."""

EXTENSION_PATTERN = ".SLD???"
"""The tail every part-number pattern in this suite ends in: three literal characters for
the file type. The builder appends the real extension, so the name is the pattern with this
tail removed and its placeholders filled."""

PLACEHOLDER_LETTER = "X"
"""What fills a `?` of the pattern's stem. `#` takes a digit; every other character is
literal, so the two profiles' patterns yield `MR-90001` and `XX90001-KS` from `"90001"`."""

DRAWING_NUMBER = "90001"
ASSEMBLY_NUMBER = "20001"
JOB_PART_NUMBER = "10001"
EXEMPT_PART_NUMBER = "10002"
SKIPPED_PART_NUMBER = "10003"
ONE_MATE_PART_NUMBER = "10004"
TWO_MATE_PART_NUMBER = "10005"

UNNUMBERED_PART = "loose-bracket"
"""A file name that follows **neither** profile's part-number convention, so the data-card
check is skipped coverage for it under both - the other half of what `part_number.pattern`
decides, and the half a fixture of conforming names alone would never exercise."""

MATERIAL = "Fictional Alloy 7"
"""A material name, not a profile value: no check reads it, only whether one is assigned."""

WRONG_REVISION = "ZZ"
"""What the revision table states in the cell the profile names, and the drawing's revision
property does not - the one seeded disagreement `standards.drawing.revision_matches` reports.
Asserted to differ from the profile's `revision.initial`, which is what the drawing states."""

REVISION_ROWS = 4
"""Rows in the seeded revision table, the header counted.

`revision.cell.row_from_end` is counted from the end over **every** row, and the two
profiles select rows 0 and 2 from the end, so four rows is the smallest table in which both
selectors land on a data row rather than outside the table or on its header."""

DEFINED = 3
UNDER_DEFINED = 2
"""`swConstrainedStatus_e`: 3 is fully constrained, 2 under-constrained."""


def document_name(profile: StandardsProfile, digits: str) -> str:
    """A document name (no extension) that follows `profile.part_number.pattern`.

    The name is the pattern itself with the file-type tail removed, its `#` placeholders
    filled with `digits` in order and its `?` placeholders filled with a letter. Built from
    the profile rather than written out, because a name written out is a second statement of
    the convention, free to disagree with the one the check reads.
    """
    pattern = profile.part_number.pattern
    if not pattern.endswith(EXTENSION_PATTERN):
        raise ValueError(
            f"{pattern!r} does not end in {EXTENSION_PATTERN!r}, so this fixture cannot say "
            "which part of it is the file type"
        )
    stem = pattern[: -len(EXTENSION_PATTERN)]
    if stem.count("#") != len(digits):
        raise ValueError(f"{pattern!r} takes {stem.count('#')} digit(s), not {len(digits)}")
    remaining = list(digits)
    return "".join(
        remaining.pop(0)
        if character == "#"
        else PLACEHOLDER_LETTER
        if character == "?"
        else character
        for character in stem
    )


def _first(prefixes: list[str], list_name: str) -> str:
    """The first entry of one of the profile's four lists, as a folder to write under."""
    if not prefixes:
        raise ValueError(
            f"the profile's library.{list_name} is empty, so this fixture cannot "
            "write a document under it"
        )
    return prefixes[0].rstrip("/")


def _checked_folders(profile: StandardsProfile) -> dict[str, str]:
    """The five folders this fixture writes under, each proved to play its intended part.

    Derived from the profile's own lists and then matched back through `PrefixMatcher`, the
    matcher the checks themselves use, so the fixture cannot claim to exercise a list it no
    longer reaches. The two mate folders are the first entry of their own list: for profile A
    that is the longer of the overlapping pair and for profile B the shorter, and each still
    yields the requirement named here, which is prefix rule 6 exercised in both directions.
    """
    library = profile.library
    folders = {
        "job": JOB_FOLDER,
        "skip": _first(library.skip_prefixes, "skip_prefixes"),
        "sketch_exempt": _first(library.sketch_exempt_prefixes, "sketch_exempt_prefixes"),
        "one_mate": _first(library.one_mate_prefixes, "one_mate_prefixes"),
        "two_mate": _first(library.two_mate_prefixes, "two_mate_prefixes"),
    }
    matcher = PrefixMatcher.from_profile(profile)
    expected: dict[str, tuple[bool, bool | None, int]] = {
        # role: (is skipped, is sketch-exempt - None where either answer is fine, mates)
        "job": (False, False, 0),
        "skip": (True, None, 0),
        "sketch_exempt": (False, True, 0),
        "one_mate": (False, None, 1),
        "two_mate": (False, None, 2),
    }
    for role, folder in folders.items():
        match = matcher.match(f"{folder}/{document_name(profile, JOB_PART_NUMBER)}.SLDPRT")
        skipped, exempt, requirement = expected[role]
        actual = (match.skip is not None, match.sketch_exempt is not None, match.mate_requirement)
        wanted = (skipped, actual[1] if exempt is None else exempt, requirement)
        if actual != wanted:
            raise ValueError(
                f"the {role} folder {folder!r} matches (skipped, sketch-exempt, mates) "
                f"{actual}, not {wanted}"
            )
    return folders


def _revision_table(profile: StandardsProfile) -> RevisionTableSpec:
    """A table whose cell the profile selects disagrees with the drawing's revision property.

    The header row is written with `revision.header_text` in its first cell, because a
    selected row whose first cell is that text is read as `revision.initial` and would agree;
    the seeded disagreement has to sit on a data row, whichever row the profile selects.
    """
    if WRONG_REVISION.casefold() == profile.revision.initial.casefold():
        raise ValueError(
            f"the seeded revision {WRONG_REVISION!r} is the profile's own initial revision, "
            "so the table would agree with the drawing and nothing would be reported"
        )
    cell = profile.revision.cell
    index = REVISION_ROWS - 1 - cell.row_from_end
    if not 1 <= index < REVISION_ROWS:
        raise ValueError(
            f"revision.cell.row_from_end {cell.row_from_end} selects row {index} of "
            f"{REVISION_ROWS}, which is not one of this table's data rows"
        )
    width = max(cell.column + 1, 3)
    rows = [
        [profile.revision.header_text, *(f"COLUMN {number}" for number in range(1, width))],
        *(
            [f"row {number} cell {column}" for column in range(width)]
            for number in range(1, REVISION_ROWS)
        ),
    ]
    rows[index][cell.column] = WRONG_REVISION
    return RevisionTableSpec(
        rows=tuple(tuple(row) for row in rows),
        current_revision_raw=WRONG_REVISION,
    )


def _drawing(profile: StandardsProfile, names: dict[str, str]) -> DrawingSpec:
    """The root drawing: two sheets, one seeded export-control note and one seeded revision."""
    return DrawingSpec(
        name=names["drawing"],
        folder=JOB_FOLDER,
        properties=card(profile, revision=profile.revision.initial),
        active_sheet="Sheet1",
        sheets=(
            SheetSpec(
                name="Sheet1",
                was_active=True,
                views=(
                    ViewSpec(
                        name="Sheet Format",
                        view_type_raw=1,
                        notes=(NoteSpec("BREAK ALL SHARP EDGES"),),
                    ),
                    ViewSpec(
                        name="Drawing View1",
                        references=names["assembly"],
                        dimensions=(DimensionSpec(name="D1@Drawing View1", value_mm=24.0),),
                        annotations=(AnnotationSpec(name="Balloon1"),),
                    ),
                ),
            ),
            SheetSpec(
                name="Sheet2",
                sheet_format_name="Sheet Format Sheet2",
                views=(
                    ViewSpec(
                        name="Sheet Format Sheet2",
                        view_type_raw=1,
                        notes=(
                            NoteSpec(f"THIS DRAWING CARRIES {profile.export_control.phrase} DATA"),
                        ),
                    ),
                ),
                revision_tables=(_revision_table(profile),),
            ),
        ),
    )


def _assembly(profile: StandardsProfile, names: dict[str, str]) -> AssemblySpec:
    """One assembly, whose only seeded violation is the two-mate component's mate count."""
    return AssemblySpec(
        name=names["assembly"],
        folder=JOB_FOLDER,
        properties=card(profile, revision=profile.revision.initial),
        components=(
            ComponentSpec(
                name=f"{names['job_part']}-1",
                document=names["job_part"],
                is_fixed=True,
                constrained_status_raw=DEFINED,
            ),
            ComponentSpec(
                name=f"{names['exempt_part']}-1",
                document=names["exempt_part"],
                constrained_status_raw=DEFINED,
            ),
            ComponentSpec(
                name=f"{names['skipped_part']}-1",
                document=names["skipped_part"],
                constrained_status_raw=DEFINED,
            ),
            ComponentSpec(
                name=f"{names['one_mate_part']}-1",
                document=names["one_mate_part"],
                constrained_status_raw=UNDER_DEFINED,
            ),
            ComponentSpec(
                name=f"{names['two_mate_part']}-1",
                document=names["two_mate_part"],
                constrained_status_raw=UNDER_DEFINED,
            ),
            ComponentSpec(
                name=f"{UNNUMBERED_PART}-1",
                document=UNNUMBERED_PART,
                constrained_status_raw=DEFINED,
            ),
        ),
        mates=(
            MateSpec(
                entities=(
                    MateEntitySpec(f"{names['one_mate_part']}-1", "swSelDATUMPLANES"),
                    MateEntitySpec(f"{names['job_part']}-1", "swSelDATUMPLANES"),
                )
            ),
            MateSpec(
                entities=(
                    MateEntitySpec(f"{names['two_mate_part']}-1", "swSelDATUMPLANES"),
                    MateEntitySpec(f"{names['job_part']}-1", "swSelDATUMPLANES"),
                )
            ),
        ),
    )


def _part(
    profile: StandardsProfile,
    name: str,
    folder: str,
    *,
    properties: dict[str, str] | None = None,
    material: str | None = MATERIAL,
    sketch_status: int | None = DEFINED,
    cut_list: bool = False,
) -> PartSpec:
    """One part, in the configuration the profile names its material one.

    `sketch_status` of `None` writes a part with features and **no sketch**, which is what
    the two mate-library parts carry.
    """
    contents = (
        ()
        if sketch_status is None
        else (
            FeatureSpec(
                "Sketch1",
                "ProfileFeature",
                sketch=SketchSpec(raw_status=sketch_status, text_segments=0),
            ),
        )
    )
    return PartSpec(
        name=name,
        folder=folder,
        configuration=profile.material.configuration,
        properties=card(profile) if properties is None else properties,
        material=material,
        mass_overridden=False,
        features=(FeatureSpec("Boss-Extrude1", "Extrude", contents=contents),),
        cut_list=(
            (CutListSpec(name="Tube 25 x 25 x 2", excluded_from_cut_list=False),)
            if cut_list
            else ()
        ),
    )


def matched_package(profile: StandardsProfile) -> EvidencePackage:
    """The one design, written for `profile`.

    Eight documents: a root drawing of two sheets, the assembly one of its views references,
    and the six parts that assembly holds - one in nobody's library, one under the profile's
    sketch-exempt prefix, one under its skip prefix, one under each mate-count prefix, and
    one whose file name follows no part-number convention.
    """
    folders = _checked_folders(profile)
    names = {
        "drawing": document_name(profile, DRAWING_NUMBER),
        "assembly": document_name(profile, ASSEMBLY_NUMBER),
        "job_part": document_name(profile, JOB_PART_NUMBER),
        "exempt_part": document_name(profile, EXEMPT_PART_NUMBER),
        "skipped_part": document_name(profile, SKIPPED_PART_NUMBER),
        "one_mate_part": document_name(profile, ONE_MATE_PART_NUMBER),
        "two_mate_part": document_name(profile, TWO_MATE_PART_NUMBER),
    }
    _check_names(profile, names)
    return standards_package(
        profile=profile,
        documents=(
            _drawing(profile, names),
            _assembly(profile, names),
            _part(
                profile,
                names["job_part"],
                folders["job"],
                properties=card(profile, blank=(1,), absent=(3,)),
                material=None,
                sketch_status=UNDER_DEFINED,
                cut_list=True,
            ),
            _part(
                profile,
                names["exempt_part"],
                folders["sketch_exempt"],
                sketch_status=UNDER_DEFINED,
            ),
            _part(
                profile,
                names["skipped_part"],
                folders["skip"],
                sketch_status=UNDER_DEFINED,
            ),
            _part(profile, names["one_mate_part"], folders["one_mate"], sketch_status=None),
            _part(profile, names["two_mate_part"], folders["two_mate"], sketch_status=None),
            _part(profile, UNNUMBERED_PART, folders["job"]),
        ),
    )


def _check_names(profile: StandardsProfile, names: dict[str, str]) -> None:
    """Every generated name follows the convention, and the one exception does not.

    The data-card check grades a document only when its file name matches, so a generated
    name that stopped matching would turn six findings into six skipped rows - identically in
    both packages, and therefore invisibly to the comparison this fixture exists for.
    """
    pattern = profile.part_number.pattern
    extensions = {"drawing": "SLDDRW", "assembly": "SLDASM"}
    for role, name in names.items():
        file_name = f"{name}.{extensions.get(role, 'SLDPRT')}"
        if not part_number_matches(pattern, file_name):
            raise ValueError(f"{file_name!r} does not follow the pattern {pattern!r}")
    if part_number_matches(pattern, f"{UNNUMBERED_PART}.SLDPRT"):
        raise ValueError(
            f"{UNNUMBERED_PART!r} follows the pattern {pattern!r}, so the data-card check "
            "would grade it and this fixture would no longer carry a skipped row"
        )
