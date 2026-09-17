"""The goldens gate for the IR 1.3.0 -> 1.4.0 bump (006 T018, quickstart Scenario 0, gate 2).

The bump adds thirteen members and nine models. Every one is additive by the rule
`specs/006-standards-check/contracts/ir-additions.md` states: optional, defaulted, and
left out of the JSON entirely when it is null (when it is empty, for the two arrays). If
that rule holds, a package written before 1.4.0 existed reads back under the 1.4.0 models
and serializes to the bytes the older build wrote, and the feature 001, 002 and 003
goldens do not move (SC-004).

Nothing rewrites `tests/golden/fixtures/*/package.json`; they are static input files. So
what proves they still **load** is this module, which parses every one of them under the
1.4.0 models and measures what the round-trip does to each:

- it **drops** nothing, so no evidence any golden carries has become unreadable;
- it **adds** no 1.4.0 member anywhere, which is the additivity rule measured rather than
  asserted by inspection;
- the only keys it adds at all are the eight that earlier minors default in, named below,
  so "the round-trip added something" cannot pass unnoticed as "it always did".

The baselines under `tests/golden/test_golden/` are the artefact actually at risk - they
are regenerated from callable output, so a new IR field that reached a summary or a
coverage row would move one. `test_the_golden_tree_has_no_uncommitted_change` is that
gate, and `tests/golden/test_golden.py` regenerating them is what makes it meaningful.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from swreview.ir.loader import PACKAGE_FILE_NAME, load_package
from swreview.ir.models import (
    ComponentInstance,
    Document,
    DrawingSheet,
    EvidencePackage,
    MateEntity,
    SketchInfo,
)
from tests.golden.test_golden import FIXTURE_DIRS, FIXTURES_DIR
from tests.unit.test_cli import git_status_of

GOLDEN_DIR = FIXTURES_DIR.parent
"""`reviewer/tests/golden/` - the fixtures and the pytest-regressions baselines both."""

GOLDEN_PACKAGES: list[Path] = [
    directory / PACKAGE_FILE_NAME
    for directory in FIXTURE_DIRS
    if (directory / PACKAGE_FILE_NAME).is_file()
]
"""Every existing golden package, discovered through `test_golden.py`'s own case walk.

Discovered rather than listed, so a golden added by a later feature is gated the day it
lands; through the golden module's walk rather than a glob of this module's own, so the
nested group directories (`fixtures/remodel-plan/<case>/`) are covered by the same rule
that collects them for grading.
"""

PACKAGE_IDS: list[str] = [
    package.parent.relative_to(FIXTURES_DIR).as_posix() for package in GOLDEN_PACKAGES
]

ADDED_AT_1_4_0: dict[type[BaseModel], tuple[str, ...]] = {
    Document: (
        "is_exploded",
        "rebuild_error_count",
        "mass_overridden",
        "material_configuration",
    ),
    ComponentInstance: (
        "transparency_raw",
        "has_appearance_override",
        "visibility_raw",
        "is_pattern_instance",
    ),
    MateEntity: ("resolution_status",),
    SketchInfo: ("text_segment_count",),
    DrawingSheet: ("source",),
    EvidencePackage: ("drawing_records", "cut_list_items"),
}
"""The thirteen members 1.4.0 adds to models that already existed.

`ExtractorInfo.profile` is deliberately absent: 1.4.0 widens its enumeration with
`"standards"`, which is a new *value* of a 1.2.0 member, not a new key, and no golden
carries that value. The nine models 1.4.0 adds whole (`CutListItem` and the eight drawing
records) reach a package only through `drawing_records`, `cut_list_items` and
`DrawingSheet.source`, all three of which are listed here, so gating those three gates
every field of all nine.
"""

NEW_MEMBER_NAMES: frozenset[str] = frozenset(
    name for names in ADDED_AT_1_4_0.values() for name in names
)

FILLED_IN_BY_EARLIER_MINORS: frozenset[str] = frozenset(
    {
        ".components[].constrained_status_raw",
        ".equations",
        ".extractor.profile",
        ".features",
        ".reuse_key",
        ".reused_at",
        ".reused_from",
        ".rms_suppress_test",
    }
)
"""The only keys a round-trip of the existing goldens adds, all of them pre-1.4.0.

These are members that earlier minors gave a non-null default and that the oldest goldens
predate - a 1.0.0 package has no `features` array and no reuse fields, and the models
default them in. They are named rather than counted so that "the round-trip adds a key"
can never be read as normal: every entry here is a key some golden was written before,
and nothing 1.4.0 adds may ever join them.
"""

PRE_1_4_0_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0.0", "1.1.0", "1.2.0", "1.3.0"})
"""What the goldens on disk are allowed to declare: the bump rewrites none of them."""


def json_paths(node: Any, prefix: str = "") -> Iterator[str]:
    """Every key in `node`, as a dotted path with list indices elided to `[]`.

    Indices are elided on purpose: the question is which *members* a round-trip adds or
    drops, and a member absent from one row of an array and present in another is the
    same question asked twice.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}"
            yield path
            yield from json_paths(value, path)
    elif isinstance(node, list):
        for item in node:
            yield from json_paths(item, f"{prefix}[]")


def round_trip(package_file: Path) -> tuple[set[str], set[str]]:
    """`(added, dropped)`: the key paths the 1.4.0 round-trip of `package_file` gains and loses."""
    on_disk = set(json_paths(json.loads(package_file.read_bytes())))
    loaded = load_package(package_file.parent).package
    reserialized = set(json_paths(json.loads(loaded.model_dump_json())))
    return reserialized - on_disk, on_disk - reserialized


def test_every_golden_package_is_discovered() -> None:
    """The walk finds goldens at both layouts, so an empty gate cannot pass silently."""
    assert GOLDEN_PACKAGES, f"no golden package.json under {FIXTURES_DIR}"
    assert "rms-part" in PACKAGE_IDS
    assert "remodel-plan/remodel-ordered" in PACKAGE_IDS
    assert len(GOLDEN_PACKAGES) == len(FIXTURE_DIRS), (
        "a golden case directory holds no package.json: "
        f"{sorted({d.name for d in FIXTURE_DIRS} - {p.parent.name for p in GOLDEN_PACKAGES})}"
    )


def test_every_member_the_gate_names_is_a_real_1_4_0_field() -> None:
    """The named member list is tied to the models, so a rename fails here loudly.

    Without this, a member renamed in `ir/models.py` would quietly stop being gated and
    every assertion below would keep passing while measuring nothing.
    """
    for model, names in ADDED_AT_1_4_0.items():
        for name in names:
            assert name in model.model_fields, f"{model.__name__}.{name} no longer exists"
            field = model.model_fields[name]
            assert not field.is_required(), f"{model.__name__}.{name} is not optional"
            assert "1.4.0" in (field.description or ""), (
                f"{model.__name__}.{name} no longer says which schema added it"
            )


@pytest.mark.parametrize("package_file", GOLDEN_PACKAGES, ids=PACKAGE_IDS)
def test_every_golden_package_parses_under_the_1_4_0_models(package_file: Path) -> None:
    """Gate 2's first half: every existing golden still loads, unchanged, at 1.4.0."""
    loaded = load_package(package_file.parent)

    assert isinstance(loaded.package, EvidencePackage)
    assert loaded.package.schema_version in PRE_1_4_0_SCHEMA_VERSIONS, (
        f"{package_file} declares {loaded.package.schema_version}; the bump rewrites no golden"
    )


@pytest.mark.parametrize("package_file", GOLDEN_PACKAGES, ids=PACKAGE_IDS)
def test_the_round_trip_adds_no_1_4_0_member_and_drops_nothing(package_file: Path) -> None:
    """Gate 2's second half, per golden: additivity measured on the files themselves.

    A 1.4.0 member appearing here would mean the field is serialized when null - the one
    failure mode that moves every golden at once.
    """
    added, dropped = round_trip(package_file)

    assert not dropped, f"{package_file} lost {sorted(dropped)} on the round-trip"
    leaked = {path for path in added if path.rsplit(".", 1)[-1] in NEW_MEMBER_NAMES}
    assert not leaked, f"{package_file} gained 1.4.0 members {sorted(leaked)}"


def test_the_round_trip_adds_only_the_defaults_earlier_minors_named() -> None:
    """Corpus-wide: the round-trip adds those eight pre-1.4.0 keys and nothing else.

    Stricter than the per-file test above and for a different reason: that one asks
    whether 1.4.0 leaked, this one asks whether *anything* new started being written, so
    a future additive field that forgets its omit-when-null rule is caught even before it
    has a name here.
    """
    added: set[str] = set()
    for package_file in GOLDEN_PACKAGES:
        added |= round_trip(package_file)[0]

    assert added == FILLED_IN_BY_EARLIER_MINORS


def test_the_golden_tree_has_no_uncommitted_change() -> None:
    """Gate 2's artefact: `git status --porcelain reviewer/tests/golden` prints nothing.

    The pytest-regressions baselines under `tests/golden/test_golden/` are regenerated
    from callable output, so this is only a real measurement in a run that has just
    regenerated them - `uv run pytest tests/golden` alongside this module, which is what
    quickstart Scenario 0 runs.
    """
    assert git_status_of(GOLDEN_DIR) == ""
