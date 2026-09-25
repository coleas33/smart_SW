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
coverage row would move one. `test_the_golden_tree_holds_only_this_feature_s_new_goldens` is that
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
from tests.golden.test_golden import (
    FIXTURES_DIR,
    PRE_1_4_0_FIXTURE_DIRS,
    WRITTEN_AT_1_4_0,
)
from tests.unit.test_cli import REPO_ROOT, git_status_of

GOLDEN_DIR = FIXTURES_DIR.parent
"""`reviewer/tests/golden/` - the fixtures and the pytest-regressions baselines both."""

GOLDEN_PACKAGES: list[Path] = [
    directory / PACKAGE_FILE_NAME
    for directory in PRE_1_4_0_FIXTURE_DIRS
    if (directory / PACKAGE_FILE_NAME).is_file()
]
"""Every golden package written **before** the bump, through `test_golden.py`'s case walk.

Discovered rather than listed, so a golden added by a later feature is gated the day it
lands; through the golden module's walk rather than a glob of this module's own, so the
nested group directories (`fixtures/remodel-plan/<case>/`) are covered by the same rule
that collects them for grading.

Feature 006's own `standards-*` goldens are excluded, and that is the gate's subject rather
than a hole in it: they are written *at* 1.4.0 by `tests/support/standards.py` and carry
this feature's cut-list items and drawing records deliberately, so asking whether they
predate the bump has no answer. What SC-004 measures is that no golden that **did** predate
it moved, and `test_the_golden_tree_holds_only_this_feature_s_new_goldens` is where the new
ones are accounted for by name.
"""

NEW_GOLDEN_PREFIX = WRITTEN_AT_1_4_0
"""The name prefix of this feature's own golden fixtures and baselines."""

NEW_GOLDEN_CASES: tuple[str, ...] = (
    "standards-compliant",
    "standards-compliant-flat",
    "standards-multiplicity",
    "standards-seeded",
    "standards-unknown",
)
"""The five goldens this feature adds (T053 to T056), named one by one rather than matched.

A `standards` substring filter would keep exempting them for ever: the day they are
committed it would go on excusing a **modified** `test_golden/standards-seeded.yml`, which
is drift in this feature's own byte-compared baseline and exactly what a golden exists to
catch. Naming the five costs one line each and expires on its own - once they are
committed the tree is clean and the gate is the absolute one again.
"""

DRAWING_GOLDEN_GROUP = "standards-drawings"
"""The case **group** T069 adds: `fixtures/standards-drawings/` holds one case directory
per root drawing, the way `fixtures/remodel-plan/` holds feature 004's.

A group and not a single case because a standards run grades the drawing that was opened
and no other (`checks/standards/traversal.py`), so the five relationships T069 enumerates
are five root drawings and therefore five packages.
"""

DRAWING_GOLDEN_CASES: tuple[str, ...] = (
    "standards-drawings-seeded",
    "standards-drawings-compliant",
    "standards-drawings-ingested",
    "standards-drawings-two-models",
    "standards-drawings-no-views",
)
"""The five cases inside that group, named one by one for the same reason the five above
are: a `standards-drawings` substring filter would go on excusing a **modified** baseline
of this feature's own for ever."""

REWRITTEN_BY_THE_DRAWING_CHECKS: frozenset[str] = frozenset(
    {
        "fixtures/standards-unknown/package.json",
        "fixtures/standards-unknown/generate_package.py",
    }
    | {f"test_golden/{case}.yml" for case in NEW_GOLDEN_CASES}
)
"""The goldens of this feature's own that T069a, T070 and T070a rewrite, named one by one.

Round B committed the five `standards-*` goldens while the four drawing checks were still
unbound, so every one of their baselines carries `unavailable_checks` naming those four -
and the two compliant fixtures, the seeded one and the unknown one carry their four
`unresolved` drawing rows. Binding the evaluators (T066) moves all five baselines, and
T070a additionally rewrites `standards-unknown`'s package to carry the drawing whose note
could not be read.

This is the **same** allowance the `??` rule above is, said for a golden that is now
tracked rather than new: every path is one of this feature's own, each is named rather than
matched, and the list expires on its own the moment the round is committed. Nothing outside
`standards-*` may move, which is what SC-004 measures.
"""

WAIVER_GOLDEN_CASE = "standards-seeded-second-subject"
"""The golden T090 adds: `standards-seeded` with one more subject of one check on one
document, which is the re-review case of `contracts/standards-check.md` section 5.

Named on its own line rather than added to `NEW_GOLDEN_CASES` above, because those five
are also the baselines `REWRITTEN_BY_THE_DRAWING_CHECKS` allows to have moved; this one is
new and has never been committed, so the gate holds it to `??` and nothing else.
"""

MATCHED_PAIR_CASES: tuple[str, ...] = (
    "standards-profile-a",
    "standards-profile-b",
)
"""The two goldens T098 adds: SC-005's matched pair, one package per fictional profile.

Named one by one for the reason the lists above are - a `standards-profile` substring filter
would go on excusing a **modified** baseline of this feature's own for ever - and on their
own line rather than inside `NEW_GOLDEN_CASES`, because those five are also the baselines
`REWRITTEN_BY_THE_DRAWING_CHECKS` allows to have moved. These two are new and have never
been committed, so the gate holds them to `??` and nothing else.
"""

NEW_GOLDEN_PATHS: frozenset[str] = frozenset(
    [f"fixtures/{case}/" for case in NEW_GOLDEN_CASES]
    + [f"test_golden/{case}.yml" for case in NEW_GOLDEN_CASES]
    + [f"fixtures/{WAIVER_GOLDEN_CASE}/", f"test_golden/{WAIVER_GOLDEN_CASE}.yml"]
    + [f"fixtures/{case}/" for case in MATCHED_PAIR_CASES]
    + [f"test_golden/{case}.yml" for case in MATCHED_PAIR_CASES]
    + [f"fixtures/{DRAWING_GOLDEN_GROUP}/"]
    + [f"test_golden/{case}.yml" for case in DRAWING_GOLDEN_CASES]
)
"""The paths under `tests/golden/` this feature adds, as `git status --short` prints them
while they are new: the five round-B fixture directories and their baselines, plus T069's
one case-group directory - git collapses a wholly untracked directory to a single line -
the five baselines its cases write, and T098's matched pair with its own two baselines.

They are allowed **only** as untracked (`??`), unless they are named in
`REWRITTEN_BY_THE_DRAWING_CHECKS` above. A line naming one of them in any other state is a
golden of this feature's own that moved after it was written, and fails.
"""

REMODEL_PLAN_CASES: tuple[str, ...] = (
    "remodel-cycle",
    "remodel-duplicate-names",
    "remodel-ordered",
    "remodel-pinned",
    "remodel-refusal-3d-interconnect",
    "remodel-refusal-mesh-body",
    "remodel-refusal-multibody",
    "remodel-refusal-rms-folder",
    "remodel-refusal-sheet-metal",
    "remodel-refusal-two-signals",
    "remodel-refusal-weldment",
    "remodel-reversed",
    "remodel-unplaceable",
)
"""Feature 004's thirteen remodel-plan goldens as T030 committed them, named one by one."""

DECISION_17A_NEW_CASES: tuple[str, ...] = (
    "remodel-absorbed-sketches",
    "remodel-refusal-derived-part",
)
"""The remodel-plan goldens feature 004 adds under the owner's decision 17A (2026-09-25):
T143's real-shape fixture and T147's derived-part refusal. Held to `??` exactly as this
feature's own new goldens are, until committed."""

REWRITTEN_BY_DECISION_17A: frozenset[str] = frozenset(
    {"fixtures/remodel-plan/generate_packages.py"}
    | {f"test_golden/{case}.yml" for case in REMODEL_PLAN_CASES}
    | {
        f"fixtures/remodel-plan/{case}/package.json"
        for case in DECISION_17A_NEW_CASES
    }
    | {f"test_golden/{case}.yml" for case in DECISION_17A_NEW_CASES}
)
"""The committed remodel-plan goldens decision 17A rewrites, named one by one.

Every plan carries the `second listings` (T143) and `carried sub-features` (T163) coverage
items, which are the only lines each of the thirteen baselines gains, and the generator
gains the cases and the layouts it writes; their packages are static inputs and do not move.
T163 extends this round's own `remodel-absorbed-sketches` package with the hole's carried
sketch after T143 committed it, which moves that package and that baseline. The same
allowance `REWRITTEN_BY_THE_DRAWING_CHECKS` is, for another feature's round: it names
nothing outside `remodel-plan`, and it expires the moment the round is committed.
"""

DECISION_17A_NEW_PATHS: frozenset[str] = frozenset(
    [f"fixtures/remodel-plan/{case}/" for case in DECISION_17A_NEW_CASES]
    + [f"test_golden/{case}.yml" for case in DECISION_17A_NEW_CASES]
)

GOLDEN_HARNESS: frozenset[str] = frozenset({"test_golden.py", "test_standards_goldens.py"})
"""The two modules in that tree that are code rather than artefact, named so that they are
accounted for rather than dropped by a directory filter.

A golden is an artefact nobody edits by hand, which is why a change to one is a finding; a
harness module is reviewed as code, so a change to one of these two is not. A *third* file
appearing beside them is neither, and fails.
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
    without_a_package = sorted(
        {directory.name for directory in PRE_1_4_0_FIXTURE_DIRS}
        - {package.parent.name for package in GOLDEN_PACKAGES}
    )

    assert without_a_package == [], (
        f"a golden case directory holds no package.json: {without_a_package}"
    )
    assert not [name for name in PACKAGE_IDS if name.startswith(NEW_GOLDEN_PREFIX)]


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


def golden_tree_status() -> list[tuple[str, str]]:
    """Every `git status --short` line for `tests/golden/`, as `(status, path)`.

    The path is relative to that tree and slash-separated, so the expectations below can
    be written as the ten paths they are rather than as substrings of a status line.
    """
    prefix = f"{GOLDEN_DIR.relative_to(REPO_ROOT).as_posix()}/"
    rows: list[tuple[str, str]] = []
    for line in git_status_of(GOLDEN_DIR).splitlines():
        status, path = line[:2].strip(), line[2:].strip().strip('"').replace("\\", "/")
        rows.append((status, path.removeprefix(prefix)))
    return rows


def test_the_golden_tree_holds_only_this_feature_s_new_goldens() -> None:
    """Gate 2's artefact: `git status --porcelain reviewer/tests/golden` names nothing else.

    The pytest-regressions baselines under `tests/golden/test_golden/` are regenerated
    from callable output, so this is only a real measurement in a run that has just
    regenerated them - `uv run pytest tests/golden` alongside this module, which is what
    quickstart Scenario 0 runs.

    The gate is absolute over the **whole** of that tree: every line it prints must be a
    golden this feature adds (T053 to T056, T069) and still untracked, one of this
    feature's own goldens that T069a, T070 and T070a rewrite and that
    `REWRITTEN_BY_THE_DRAWING_CHECKS` names, or one of the two harness modules named above.
    A feature 001, 002 or 003 baseline that drifted prints a line that is none of those, and
    so does a `standards-*` baseline of this feature's own that stopped being new and is not
    named - which is SC-004 measured rather than asserted by inspection.
    """
    changed = golden_tree_status()

    new = NEW_GOLDEN_PATHS | DECISION_17A_NEW_PATHS
    rewritten = REWRITTEN_BY_THE_DRAWING_CHECKS | REWRITTEN_BY_DECISION_17A
    allowed = new | GOLDEN_HARNESS | rewritten
    stray = [f"{status} {path}" for status, path in changed if path not in allowed]
    drifted = [
        f"{status} {path}"
        for status, path in changed
        if path in new and status != "??" and path not in rewritten
    ]

    assert stray == [], f"the golden tree moved outside this feature: {stray}"
    assert drifted == [], f"a golden this feature wrote moved after it was written: {drifted}"
