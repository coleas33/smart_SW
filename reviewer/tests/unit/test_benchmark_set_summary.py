"""The set summary's family rule (T112, for T113); T118 adds the summary's own rows.

`benchmark/families.py` is the one family rule (`cases.md` 8; `generator.md` 9): the generator's
spec check row 3, the committed-set test and `swreview benchmark set-summary` all read it, and
none restates it.

1. **`family_of(check)`** reads an exact id or an `x.*` family by its first segment: `fastener`
   and `hole` are `fastener`, `fit` and `stack` are `fit_and_stack`, `interference` and
   `drawing` are their own, and every other check is `other` (modelling practice, hygiene,
   standards, provenance). A first segment that merely starts with the same letters
   (`fasteners.x`) and a judgement word in a later segment (`standards.drawing.*`) are `other`.
2. **`part_role` is a `Family` value no check reaches.** The summary counts the part-roles
   question's count rule there, a rule that names no check; the part-roles coverage row
   (`checks/part_roles.PART_ROLES_CHECK`) is `other`.
3. **`ANCHOR_FAMILY`** maps exactly the anchors R-1 to R-8 and the analyst-found AF-1 to AF-3,
   in that order, each to its family; **`FAMILY_LABELS`** gives every family's printed label
   once, in the summary's row order.
4. **The module is data only**, the standard library alone, so the generator imports it without
   loading the runner, the agent or a check (`generator.md` 9; RF-48).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import get_args

import pytest

from swreview.benchmark import families
from swreview.checks.part_roles import PART_ROLES_CHECK

# --- family_of: an exact id or an x.* family, by its first segment -------------------------


@pytest.mark.parametrize(
    ("check", "family"),
    [
        ("fastener.bottoming", "fastener"),
        ("fastener.head.fit", "fastener"),
        ("fastener.*", "fastener"),
        ("fastener.head.*", "fastener"),
        ("hole.nominal_alignment", "fastener"),
        ("hole.*", "fastener"),
        ("fit.size_only", "fit_and_stack"),
        ("fit.*", "fit_and_stack"),
        ("stack.worst_case", "fit_and_stack"),
        ("stack.*", "fit_and_stack"),
        ("interference.static", "interference"),
        ("interference.*", "interference"),
        ("drawing.manufacturing_inputs", "drawing"),
        ("drawing.*", "drawing"),
        ("drawing", "drawing"),
    ],
)
def test_a_judgement_check_or_family_maps_to_its_family_by_its_first_segment(
    check: str, family: str
) -> None:
    assert families.family_of(check) == family


@pytest.mark.parametrize(
    "check",
    [
        "rms.*",
        "rms.sketches.fully_defined",
        "hygiene.revision_present",
        "standards.part.sketches_fully_defined",
        "provenance.x",
    ],
)
def test_modelling_practice_hygiene_standards_and_provenance_are_other(check: str) -> None:
    assert families.family_of(check) == "other"


@pytest.mark.parametrize(
    "check",
    ["fasteners.x", "holes.x", "fits.x", "stacks.x", "interferences.x", "drawings.x"],
)
def test_a_first_segment_that_merely_starts_with_a_judgement_word_is_other(check: str) -> None:
    """The first segment is compared whole, as `answer_key_model.pattern_covers` compares a
    family: `fastener.*` never covers `fasteners.x`, and `fasteners.x` is no fastener check."""
    assert families.family_of(check) == "other"


@pytest.mark.parametrize(
    "check",
    ["standards.drawing.revision_matches", "standards.drawing.*", "coverage.prerun.interference"],
)
def test_a_judgement_word_in_a_later_segment_is_other(check: str) -> None:
    """Only the first segment decides: a standards check about a drawing is a standards check."""
    assert families.family_of(check) == "other"


# --- part_role: a family no check reaches ----------------------------------------------------


def test_part_role_is_a_family_value() -> None:
    assert "part_role" in get_args(families.Family)


def test_the_part_roles_coverage_row_is_other_since_no_check_reaches_part_role() -> None:
    """The summary counts only the part-roles question's count rule on `part role` (T118); the
    part-roles coverage row is a check like any other, on the `other` row."""
    assert families.family_of(PART_ROLES_CHECK) == "other"


def test_the_families_are_the_six_in_the_summary_s_row_order() -> None:
    assert get_args(families.Family) == (
        "fastener",
        "fit_and_stack",
        "interference",
        "drawing",
        "part_role",
        "other",
    )


# --- ANCHOR_FAMILY and FAMILY_LABELS ---------------------------------------------------------


def test_anchor_family_maps_exactly_the_anchors_and_the_analyst_found_ids() -> None:
    """`cases.md` 8's anchors column: R-1 part role; R-2 drawing; R-3 fit and axial stack; R-4
    and R-5 interference; R-6, AF-1 and AF-2 fastener; R-7 and R-8 other; AF-3 interference."""
    assert families.ANCHOR_FAMILY == {
        "R-1": "part_role",
        "R-2": "drawing",
        "R-3": "fit_and_stack",
        "R-4": "interference",
        "R-5": "interference",
        "R-6": "fastener",
        "R-7": "other",
        "R-8": "other",
        "AF-1": "fastener",
        "AF-2": "fastener",
        "AF-3": "interference",
    }


def test_anchor_family_lists_r_1_to_r_8_then_af_1_to_af_3() -> None:
    assert list(families.ANCHOR_FAMILY) == [
        *(f"R-{n}" for n in range(1, 9)),
        *(f"AF-{n}" for n in range(1, 4)),
    ]


def test_family_labels_are_the_printed_labels_in_order() -> None:
    assert list(families.FAMILY_LABELS.values()) == [
        "fastener",
        "fit and axial stack",
        "interference",
        "drawing",
        "part role",
        "other",
    ]


def test_family_labels_label_every_family_once_in_the_family_order() -> None:
    assert list(families.FAMILY_LABELS) == list(get_args(families.Family))


# --- the module: data only, the standard library alone ---------------------------------------


def test_the_families_module_imports_the_standard_library_only() -> None:
    path = Path(families.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))

    outside = {module for module in modules if module.split(".")[0] not in sys.stdlib_module_names}
    assert outside == set()
