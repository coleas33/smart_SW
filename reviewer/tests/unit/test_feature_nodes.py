"""One tree reading, now a check's (feature 013 T130).

`specs/013-engineer-first-review/contracts/readings.md` section 3 is normative. The reading the
planner learnt on the real packages - an absorbed sketch listed twice with one persist ref is one
node, the Hole Wizard's profile sketch is its hole's - moves to `checks/feature_nodes.py` so the
grading checks read the tree the way the planner does. `remodel/nodes.py` re-exports its names,
so every planner import keeps working and the planner's output is byte-identical: the planner's
own tests (`test_remodel_nodes.py`, `test_tools_remodel_plan.py`) and the remodel goldens run
unedited against the moved code.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from swreview.checks import feature_nodes
from swreview.checks.rms_types import load_table
from swreview.ir.loader import load_package
from swreview.remodel import nodes as remodel_nodes

NAMES = ("CarriedRow", "MergedRow", "TreeNodes", "tree_nodes")
GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "remodel-plan"


def test_the_reading_lives_in_checks() -> None:
    assert tuple(sorted(feature_nodes.__all__)) == NAMES
    for name in NAMES:
        assert getattr(feature_nodes, name).__module__ == "swreview.checks.feature_nodes"


def test_the_planners_module_re_exports_the_same_objects() -> None:
    assert tuple(sorted(remodel_nodes.__all__)) == NAMES
    for name in NAMES:
        assert getattr(remodel_nodes, name) is getattr(feature_nodes, name), name


def test_the_planners_module_defines_nothing_of_its_own() -> None:
    """A second copy of the rules would be free to drift from the first."""
    defined = [
        name
        for name, value in vars(remodel_nodes).items()
        if (inspect.isfunction(value) or inspect.isclass(value))
        and value.__module__ == remodel_nodes.__name__
    ]

    assert defined == []


def test_the_planner_imports_the_reading_through_its_own_module() -> None:
    from swreview.remodel import plan

    assert plan.tree_nodes is feature_nodes.tree_nodes


def test_every_remodel_fixture_reads_the_same_through_either_name() -> None:
    table = load_table()
    packages = sorted(path.parent for path in GOLDEN.rglob("package.json"))
    assert packages, "the remodel golden fixtures are where the planner's shapes live"

    for directory in packages:
        package = load_package(directory).package
        for document in {row.document_id for row in package.features}:
            rows = [row for row in package.features if row.document_id == document]
            assert feature_nodes.tree_nodes(rows, table) == remodel_nodes.tree_nodes(rows, table)
