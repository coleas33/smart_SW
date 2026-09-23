"""The one hook every feature 010 check joins the pre-run through (T013, contracts/code-first.md).

`tools/checks_mechanical.CODE_FIRST_CHECKS` names argument-free check tools in the order the
pre-run calls them; `prerun.planned_calls` reads it and plans `(name, {})` for each one that
is not withheld, after the interference groups and before `check_standards`. The tuple is
the only hook (research R2.20): a check that needed its own pre-run branch would be a second
copy of something feature 008 owns. With the tuple empty the pre-run is exactly what it was
before this feature, byte for byte.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import pytest
from pytest_regressions.file_regression import FileRegressionFixture

from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import CHECK_TOOL
from swreview.checks.standards.traversal import graded_documents
from swreview.prerun import planned_calls, prerun_checks, prerun_tools
from swreview.tools import checks_mechanical
from swreview.tools.context import context_for
from swreview.tools.registry import TOOL_FUNCTIONS, ToolRegistry, WithheldTool, check_tools
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
from tests.support.prerun import (
    GROUP_KEY,
    ON,
    STANDARDS_PROFILE,
    prerun_package,
    standards_prerun_package,
)
from tests.unit.test_prerun_digest import opening_of, started

FAKE = "fake_code_first_check"
LEGACY_PLAN: tuple[tuple[str, dict[str, Any]], ...] = (
    ("check_rms_part", {}),
    ("check_rms_equations", {}),
    ("check_rms_assembly", {}),
    ("check_interference_group", {"group_key": GROUP_KEY}),
)
"""What the pre-run planned for `prerun_package()` before feature 010 existed."""


def fake_code_first_check() -> dict[str, Any]:
    """Counts nothing and records nothing; stands in for a feature 010 check tool.

    Notes:
        Takes no argument, like every tool `CODE_FIRST_CHECKS` names.
    """
    return {"status": "recorded", "findings": 0}


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> ToolRegistry:
    """The fake tool registered and named in the tuple, the real registry otherwise."""
    monkeypatch.setattr(checks_mechanical, "CODE_FIRST_CHECKS", (FAKE,))
    return ToolRegistry(functions=(*TOOL_FUNCTIONS, fake_code_first_check))


def with_a_standards_run() -> Any:
    context = context_for(standards_prerun_package())
    profile = load_profile(STANDARDS_PROFILE)
    attach_standards_run(
        context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
    )
    return context


def test_a_registered_name_is_planned_with_no_arguments_after_the_interference_groups(
    registered: ToolRegistry,
) -> None:
    context = context_for(prerun_package())
    dispatch = registered.dispatch(context)

    assert planned_calls(context, dispatch) == (*LEGACY_PLAN, (FAKE, {}))


def test_a_registered_name_is_planned_before_check_standards(registered: ToolRegistry) -> None:
    context = with_a_standards_run()
    dispatch = registered.dispatch(context)

    plan = planned_calls(context, dispatch)

    assert [name for name, _ in plan][-2:] == [FAKE, CHECK_TOOL]
    assert plan[-2] == (FAKE, {})


def test_a_registered_name_is_called_as_a_real_step(registered: ToolRegistry) -> None:
    context = context_for(prerun_package())
    dispatch = registered.dispatch(context)

    result = prerun_checks(context, dispatch, efficiency=ON)

    assert result is not None
    assert [call.tool for call in result.calls][-1] == FAKE
    assert [step.tool for step in context.require_session().steps][-1] == FAKE


def test_a_withheld_name_is_not_planned_and_its_tier_sentence_reaches_the_digest(
    registered: ToolRegistry,
) -> None:
    context = context_for(prerun_package())
    built = registered.dispatch(context)
    reason = "the fake tier withheld this check for the test"
    dispatch = dataclasses.replace(
        built,
        tools=tuple(tool for tool in built.tools if tool.name != FAKE),
        withheld=(
            WithheldTool(
                name=FAKE, reason=reason, checklist_item=None, context=context, sink=built.sink
            ),
        ),
    )

    assert FAKE not in [name for name, _ in planned_calls(context, dispatch)]
    assert FAKE in prerun_tools()
    result = prerun_checks(context, dispatch, efficiency=ON)
    assert result is not None
    assert f"  {FAKE}: {reason}" in result.digest()


def test_every_name_in_the_real_tuple_is_an_argument_free_check_tool() -> None:
    tools = {function.__name__: function for function in check_tools()}

    for name in checks_mechanical.CODE_FIRST_CHECKS:
        assert name in tools, f"{name} is in CODE_FIRST_CHECKS but is not a check tool"
        assert inspect.signature(tools[name]).parameters == {}, f"{name} takes an argument"


def test_the_pre_run_tools_are_the_four_legacy_ones_and_the_tuple_in_order() -> None:
    assert prerun_tools() == (
        "check_rms_part",
        "check_rms_equations",
        "check_rms_assembly",
        "check_interference_group",
        *checks_mechanical.CODE_FIRST_CHECKS,
    )


def test_with_the_tuple_empty_the_plan_is_the_legacy_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checks_mechanical, "CODE_FIRST_CHECKS", ())
    context = context_for(prerun_package())

    assert planned_calls(context, ToolRegistry().dispatch(context)) == LEGACY_PLAN


def test_with_the_tuple_empty_the_opening_message_is_byte_identical_to_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, file_regression: FileRegressionFixture
) -> None:
    """The baseline was written from the tree before feature 010 touched `prerun.py`.

    Regenerated once, deliberately, by T037: that task retires `coaxial_hole_pairs`, so the
    legacy "hole alignment: 1 coaxial hole pair" line has nothing left to count it. With
    `check_joints` out of the tuple no joint map runs, and the hole-alignment family says
    nothing rather than claim what a map that never ran could not reach. Every other byte is
    the pre-010 message.

    Regenerated a second time, deliberately, by feature 008 T038: lever 5 is checks first,
    so the four RMS id lines are one counts-only "modelling practice" line (FR-014) and the
    standards family is reported with its reason when no profile was given (US2 scenario 3).
    Nothing feature 010 added moved.
    """
    monkeypatch.setattr(checks_mechanical, "CODE_FIRST_CHECKS", ())

    run, _ = started(tmp_path, "empty-tuple", efficiency=ON)

    file_regression.check(opening_of(run), extension=".txt", encoding="utf-8", newline="\n")
