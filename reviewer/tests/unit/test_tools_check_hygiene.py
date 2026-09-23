"""`check_hygiene`, the argument-free house-rules tool (feature 010 T074).

`contracts/hygiene.md` sections 3 and 5: the tool takes no argument, reads the property names
from the standards run attached to the context - never loading a profile itself - and with
no run attached still runs the component check while the property checks are skipped naming
their settings. It is a check tool and the third name in `CODE_FIRST_CHECKS` (T075), so the
pre-run calls it after `check_mass_material` at no model round.
"""

from __future__ import annotations

import inspect
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.loader import load_package
from swreview.tools import checks_mechanical
from swreview.tools.checks_mechanical import check_hygiene
from swreview.tools.context import ToolContext, build_context, use_context
from swreview.tools.registry import ToolRegistry, check_tools
from swreview.tools.standards_checks import StandardsRun, attach_standards_run

REVIEWER = Path(__file__).resolve().parents[1].parent
FIXTURES = REVIEWER / "tests" / "fixtures" / "mechanical"
PROFILE_A = REVIEWER / "tests" / "fixtures" / "standards" / "profile-a.yaml"


def run(profile: StandardsProfile | None) -> tuple[ToolContext, dict[str, Any]]:
    context = build_context(load_package(FIXTURES / "big-assembly"))
    if profile is not None:
        attach_standards_run(
            context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
        )
    with use_context(context):
        return context, check_hygiene()


def by_check(context: ToolContext) -> Counter[str]:
    return Counter(finding.check for finding in context.require_session().findings)


@pytest.fixture(scope="module")
def attached() -> tuple[ToolContext, dict[str, Any]]:
    return run(load_profile(PROFILE_A))


def test_the_tool_takes_no_argument() -> None:
    assert inspect.signature(check_hygiene).parameters == {}


def test_it_is_a_check_tool_and_the_third_code_first_check() -> None:
    assert check_hygiene in check_tools()
    assert checks_mechanical.CODE_FIRST_CHECKS.index("check_hygiene") == 2


def test_through_the_registry_it_is_one_real_step_and_refuses_an_argument() -> None:
    context = build_context(load_package(FIXTURES / "small-assembly"))
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}

    assert tools["check_hygiene"].call({}).payload["profile"] == "absent"
    assert [step.tool for step in context.require_session().steps] == ["check_hygiene"]
    assert tools["check_hygiene"].call({"profile": "profile-a"}).is_error is True


def test_the_tool_never_loads_a_profile_itself() -> None:
    source = inspect.getsource(check_hygiene)

    assert "load_profile" not in source
    assert "load_profile" not in inspect.getsource(checks_mechanical)


def test_with_the_profile_attached_the_section_5_rows_hold(attached) -> None:
    context, result = attached

    assert result["profile"] == "attached"
    assert result["documents"] == 26  # every part and assembly reached, the 3 unread among them
    assert by_check(context) == {
        "hygiene.part_number_matches_file": 1,
        "hygiene.duplicate_description": 1,
        "hygiene.revision_present": 1,
        "hygiene.component_not_resolved": 3,
    }
    assert all(finding.status == "demonstrated" for finding in context.require_session().findings)


def test_passes_are_one_checked_item_per_check(attached) -> None:
    """Plus, since T108, the family's summary row under the checklist item's id, `hygiene`,
    which the result does not count (`test_mechanical_family_summaries.py`)."""
    context, result = attached

    checked = {item.check: item.reason for item in context.require_session().coverage.checked}

    assert set(checked) == {
        "hygiene.part_number_matches_file",
        "hygiene.duplicate_description",
        "hygiene.duplicate_part_number",
        "hygiene.revision_present",
        "hygiene",
    }
    assert checked["hygiene.part_number_matches_file"].startswith("22 documents: ")
    assert result["coverage"]["checked"] == 4


def test_the_unread_documents_are_one_coverage_item(attached) -> None:
    context, _ = attached

    [item] = context.require_session().coverage.skipped
    assert item.check == "hygiene.coverage"
    assert item.reason.startswith("3 documents' properties were not read")


def test_with_no_profile_the_property_checks_are_skipped_and_components_still_run() -> None:
    context, result = run(None)

    assert result["profile"] == "absent"
    assert by_check(context) == {"hygiene.component_not_resolved": 3}
    skipped = {item.check for item in context.require_session().coverage.skipped}
    assert skipped == {
        "hygiene.part_number_matches_file",
        "hygiene.duplicate_description",
        "hygiene.duplicate_part_number",
        "hygiene.revision_present",
        "hygiene.coverage",
    }


def test_with_a_version_1_profile_the_two_property_settings_are_skipped() -> None:
    profile = load_profile(PROFILE_A)
    version_1 = profile.model_copy(
        update={"version": 1, "hygiene": None, "general_tolerance": None}
    )

    context, _ = run(version_1)

    assert by_check(context) == {
        "hygiene.revision_present": 1,
        "hygiene.component_not_resolved": 3,
    }
