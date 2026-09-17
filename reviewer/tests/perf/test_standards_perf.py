"""The wall-clock budget for a standards check over a pilot-sized design (T092).

SC-011 says that evaluating all sixteen checks over a package representing a
**200-component assembly with three drawings** completes in **under 2 seconds**, and the
run that measures it is this one: it is executed explicitly with `-m perf` on the
continuous-integration machine during Polish, and the measured number is recorded on T092.

**Why four packages and not one.** A standards run grades the document that was *opened*
and no other: the graded set is the root, what a root drawing's views reference, and what
hangs below those (`checks/standards/traversal.py`, FR-003). A design with three drawings
is therefore three drawing roots plus the assembly root - four runs - which is exactly the
reading `tests/golden/fixtures/standards-drawings/generate_package.py` already takes for
its five cases. The budget covers **all four**, because that is the whole design and so the
whole wait; measuring one root and calling it the design would quietly under-report by the
three drawings SC-011 names. Every one of the four is built from the same specs, so the
`COMPONENT_COUNT` components are walked four times over, which is the pessimistic side of
the reading and the safe side of a budget claim.

Why it is not in the default run - the same reason `test_rms_perf.py` gives, and the rule
lives in `tests/conftest.py::pytest_ignore_collect`: a timing assertion is a statement
about the machine as much as about the code, so `tests/perf/` is *not collected* unless the
run asks for the `perf` marker. Run them with:

    uv run pytest -m perf -s

`-s` because the measured seconds are printed: an assertion that only says "under 2 s"
hides the trend that says the budget is about to be missed.

The budget covers what `run_standards_check` does - profile load and validation, package
load, traversal, all sixteen checks, the carry-forward, coverage, and writing
`session.json`, `report.md` and `check.json` - because that is what an engineer waits for
after pressing the button. Fixture construction and `save_package` are outside the timer
for the reason the model-check budget gives: nobody waits for them in the product.

No company value is written here. Every data-card property name, the part-number
convention, the revision property and the export-control phrase come off the fictional
fixture profile, exactly as the goldens' generators take them (FR-001).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from swreview.checks.standards.registry import RULES
from swreview.checks.standards.run import run_standards_check
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from tests.checks.golden_standards import PROFILE_DIR
from tests.checks.standards_fixtures import card, fixture_profile
from tests.support.features import FeatureSpec, SketchSpec
from tests.support.standards import (
    AnnotationSpec,
    AssemblySpec,
    ComponentSpec,
    DimensionSpec,
    DocumentSpec,
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

pytestmark = pytest.mark.perf

PROFILE = fixture_profile()
PROFILE_PATH = PROFILE_DIR / "profile-a.yaml"

BUDGET_SECONDS = 2.0
"""What the whole design must stay under: the assembly root and all three drawing roots."""

SUB_ASSEMBLY_COUNT = 20
PARTS_PER_SUB_ASSEMBLY = 9
COMPONENT_COUNT = SUB_ASSEMBLY_COUNT * (1 + PARTS_PER_SUB_ASSEMBLY)
"""200 component instances under one root assembly - SC-011's workload, and SC-002's
statement of the pilot assembly's order of magnitude."""

DRAWING_COUNT = 3
SHEETS_PER_DRAWING = 3
"""Three sheets each, because every drawing check reads **every** sheet and not only the
active one (difference q): a single-sheet drawing would time a third of that walk."""

VIOLATION_EVERY = 10
"""One part in ten seeds data-card and material failures, and every drawing seeds an
overridden dimension and a dangling annotation, so the finding path - fingerprint,
exception refresh, subject rendering - is inside the timer too and the budget is not a
measurement of the clean path alone."""

FOLDER = "jobs/perf"
"""Vault-relative, and under no library prefix of the profile, so no part is skipped."""

MATERIAL = "Fictional Alloy 7"
CONFIGURATION = PROFILE.material.configuration
REVISION = PROFILE.revision.initial
DEFINED = 3
"""`swConstrainedStatus_e` 3: fully constrained, so the assembly checks pass."""

BENIGN_NOTE = "UNLESS OTHERWISE SPECIFIED, BREAK ALL SHARP EDGES"

GRADED_FROM_ASSEMBLY = 1 + SUB_ASSEMBLY_COUNT + SUB_ASSEMBLY_COUNT * PARTS_PER_SUB_ASSEMBLY
"""The root assembly, its sub-assemblies and its parts: one document each, once each."""

GRADED_FROM_DRAWING = 1 + GRADED_FROM_ASSEMBLY
"""The drawing itself, plus everything its one referenced model reaches."""


# --- the design every run grades ------------------------------------------------------------


def _part_name(sub_index: int, index: int) -> str:
    return f"MR-1{sub_index:02d}{index:02d}"


def _sub_assembly_name(index: int) -> str:
    return f"MR-20{index:03d}"


TOP_ASSEMBLY = "MR-30001"


def _part(sub_index: int, index: int) -> PartSpec:
    """One part. Every tenth is seeded, so the finding path is timed as well."""
    seeded = (sub_index * PARTS_PER_SUB_ASSEMBLY + index) % VIOLATION_EVERY == 0
    return PartSpec(
        name=_part_name(sub_index, index),
        folder=FOLDER,
        configuration=CONFIGURATION,
        properties=card(PROFILE, revision=REVISION, blank=(1,) if seeded else ()),
        material=None if seeded else MATERIAL,
        material_configuration=CONFIGURATION,
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


def _assembly(name: str, children: tuple[str, ...]) -> AssemblySpec:
    """A compliant assembly of `children`: one fixed child, every child constrained."""
    return AssemblySpec(
        name=name,
        folder=FOLDER,
        properties=card(PROFILE, revision=REVISION),
        components=tuple(
            ComponentSpec(
                name=f"{child}-1",
                document=child,
                is_fixed=index == 0,
                constrained_status_raw=DEFINED,
            )
            for index, child in enumerate(children)
        ),
        mates=(
            MateSpec(
                entities=tuple(
                    MateEntitySpec(f"{child}-1", "swSelDATUMPLANES") for child in children
                )
            ),
        ),
    )


def _model_documents() -> list[DocumentSpec]:
    """The 200-component assembly: the root, its sub-assemblies, then their parts."""
    parts: list[DocumentSpec] = []
    sub_assemblies: list[DocumentSpec] = []
    for sub_index in range(SUB_ASSEMBLY_COUNT):
        children = tuple(
            _part_name(sub_index, index) for index in range(PARTS_PER_SUB_ASSEMBLY)
        )
        sub_assemblies.append(_assembly(_sub_assembly_name(sub_index), children))
        parts += [_part(sub_index, index) for index in range(PARTS_PER_SUB_ASSEMBLY)]
    tops = tuple(_sub_assembly_name(index) for index in range(SUB_ASSEMBLY_COUNT))
    return [_assembly(TOP_ASSEMBLY, tops), *sub_assemblies, *parts]


def _sheet(drawing_index: int, sheet_index: int) -> SheetSpec:
    """One sheet: the type-1 sheet-format view notes live in, and one view on the model.

    The first sheet of every drawing carries the seeded overridden dimension and the
    seeded dangling annotation; the revision table sits on it too and agrees with the
    drawing's own property, so `revision_matches` is checked rather than warned.
    """
    seeded = sheet_index == 0
    return SheetSpec(
        name=f"Sheet{sheet_index + 1}",
        was_active=sheet_index == 0,
        views=(
            ViewSpec(
                name=f"Sheet Format Sheet{sheet_index + 1}",
                view_type_raw=1,
                notes=(NoteSpec(BENIGN_NOTE),),
            ),
            ViewSpec(
                name=f"Drawing View{sheet_index + 1}",
                references=TOP_ASSEMBLY,
                dimensions=(
                    DimensionSpec(
                        name=f"D1@Drawing View{sheet_index + 1}",
                        is_overridden=seeded,
                        value_mm=12.5,
                        override_mm=99.5 if seeded else None,
                    ),
                    DimensionSpec(name=f"D2@Drawing View{sheet_index + 1}", value_mm=30.0),
                ),
                annotations=(
                    AnnotationSpec(name=f"Datum{drawing_index}", type_raw=5, is_dangling=seeded),
                    AnnotationSpec(name=f"Balloon{sheet_index + 1}"),
                ),
            ),
        ),
        revision_tables=(
            (
                RevisionTableSpec(
                    rows=(
                        (PROFILE.revision.header_text, "REV", "DESCRIPTION"),
                        ("A1", REVISION, "Initial release"),
                    ),
                    current_revision_raw=REVISION,
                ),
            )
            if seeded
            else ()
        ),
    )


def _drawing(index: int) -> DrawingSpec:
    return DrawingSpec(
        name=f"MR-9000{index + 1}",
        folder=FOLDER,
        properties=card(PROFILE, revision=REVISION),
        active_sheet="Sheet1",
        sheets=tuple(_sheet(index, sheet) for sheet in range(SHEETS_PER_DRAWING)),
    )


def _packages() -> list[EvidencePackage]:
    """One package per root: the assembly, then one per drawing (`DRAWING_COUNT`)."""
    model = _model_documents()
    return [
        standards_package(profile=PROFILE, documents=model),
        *(
            standards_package(profile=PROFILE, documents=[_drawing(index), *model])
            for index in range(DRAWING_COUNT)
        ),
    ]


@pytest.fixture
def design_dirs(tmp_path: Path) -> list[Path]:
    """The four written packages, in the order the runs grade them."""
    directories = []
    for index, package in enumerate(_packages()):
        directory = tmp_path / "packages" / f"root-{index}"
        save_package(package, directory)
        directories.append(directory)
    return directories


def test_the_sixteen_checks_grade_a_pilot_sized_design_within_the_budget(
    design_dirs: list[Path], tmp_path: Path
) -> None:
    run_root = tmp_path / "runs"

    started = time.perf_counter()
    runs = [
        run_standards_check(
            directory, PROFILE_PATH, run_root / f"perf-{index}", run_root=run_root
        )
        for index, directory in enumerate(design_dirs)
    ]
    elapsed = time.perf_counter() - started

    # The budget means nothing without the workload: a run that graded nothing, or that
    # reached none of the sixteen checks, would come in under two seconds as well.
    assembly_run, *drawing_runs = runs
    assert len(assembly_run.documents) == GRADED_FROM_ASSEMBLY
    assert len(drawing_runs) == DRAWING_COUNT
    for run in drawing_runs:
        assert len(run.documents) == GRADED_FROM_DRAWING
        assert {row["check"] for row in run.checks} == set(RULES)
    assert all(run.findings for run in runs)

    print()
    print(
        f"check standards over {COMPONENT_COUNT} components and {DRAWING_COUNT} drawings "
        f"({len(runs)} roots): {elapsed:.3f} s, budget {BUDGET_SECONDS} s"
    )
    assert elapsed < BUDGET_SECONDS, (
        f"grading {COMPONENT_COUNT} components and {DRAWING_COUNT} drawings took "
        f"{elapsed:.3f} s, over the {BUDGET_SECONDS} s budget"
    )
