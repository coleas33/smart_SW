"""The wall-clock budgets of the joint map and `check_joints` (feature 010 plan, T101).

The plan's performance goals: `build_joint_map` alone under 200 ms, and `check_joints` -
the map, every joint and fastener check, and the mesh loads engagement and tool access
need - under 2 s on the development machine, both on the big fixture shaped like the
recorded 830 assembly (132 hole instances, about 8,700 candidate pairs). The pairing is
quadratic in instances and is measured here rather than optimized until a package makes it
matter; the printed seconds are the trend that says when.

Not collected unless the run asks for the `perf` marker (`tests/conftest.py`), for the
reason `test_rms_perf.py` gives: a timing assertion is a statement about the machine as
much as about the code. Run with `uv run pytest -m perf tests/perf -s`. Loading the package
is outside the timer: nobody waits for `load_package` inside a check.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from swreview.checks.joints import build_joint_map
from swreview.ir.loader import load_package
from swreview.tools.context import build_context
from swreview.tools.registry import ToolRegistry

pytestmark = pytest.mark.perf

BIG = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical" / "big-assembly"

MAP_BUDGET_SECONDS = 0.2
"""`build_joint_map` alone on the big fixture (plan, Performance Goals)."""

CHECK_BUDGET_SECONDS = 2.0
"""`check_joints` end to end through the dispatch, mesh loads included (plan, SC-006's
code-first pass)."""


def test_the_joint_map_of_the_big_fixture_is_built_inside_its_budget() -> None:
    package = load_package(BIG).package

    start = time.perf_counter()
    joint_map = build_joint_map(package)
    elapsed = time.perf_counter() - start

    # The workload is the contract's (`contracts/joint-map.md` section 9), not a smaller one.
    assert len(joint_map.instances) == 132
    assert len(joint_map.joints) == 50
    print(f"\nbuild_joint_map over 132 instances: {elapsed:.3f} s, budget {MAP_BUDGET_SECONDS} s")
    assert elapsed < MAP_BUDGET_SECONDS


def test_check_joints_on_the_big_fixture_is_inside_its_budget() -> None:
    context = build_context(load_package(BIG))
    dispatch = ToolRegistry().dispatch(context)

    start = time.perf_counter()
    result = dispatch.call("check_joints", {})
    elapsed = time.perf_counter() - start

    assert not result.is_error, result.payload
    assert context.require_session().findings, "the timed run judged something"
    print(f"\ncheck_joints on the big fixture: {elapsed:.3f} s, budget {CHECK_BUDGET_SECONDS} s")
    assert elapsed < CHECK_BUDGET_SECONDS
