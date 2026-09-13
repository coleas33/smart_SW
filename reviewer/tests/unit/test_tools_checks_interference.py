"""Unit tests for the interference tools (T068).

`list_interferences` and `get_exceptions` are query tools and are covered in
`test_tools_query.py`; what this file pins is `check_interference_group`, the tool that
turns a group of detection results into one finding, and the two rules US3 hangs on it:

- an `active` exception bound to this geometry and configuration clears the group, a
  `needs_review` one does not, and either way the exception id is on the finding;
- a `truncated` or `failed` pair is unresolved coverage as well as an unresolved finding,
  so a session holding one cannot be summarized as a pass (FR-019).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator

import pytest
from anthropic.lib.tools import ToolError

from swreview.exceptions import ExceptionStore
from swreview.ir.models import (
    EvidencePackage,
    Interference,
    InterferenceSettings,
    Volume,
)
from swreview.tools import checks_interference, query
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.registry import RecordedTool, ToolRegistry

MakePackage = Callable[..., EvidencePackage]

SETTINGS = InterferenceSettings(
    treat_coincident_as_interference=False,
    treat_subassemblies_as_components=True,
    include_multibody=False,
    ignore_hidden=True,
    fastener_folder_treatment="include",
)


def interference(
    interference_id: str,
    group_key: str,
    status: str = "computed",
    volume_mm3: float | None = 4.0,
    configuration: str = "Default",
    error: str | None = None,
) -> Interference:
    return Interference(
        id=interference_id,
        configuration=configuration,
        component_ids=["cmp:0001", "cmp:0002"],
        volume=None if volume_mm3 is None else Volume(value=volume_mm3, unit="mm3"),
        settings=SETTINGS,
        status=status,  # type: ignore[arg-type]
        error=error,
        group_key=group_key,
        is_fastener=False,
        is_possible=volume_mm3 is None,
    )


def interference_package(make_package: MakePackage) -> EvidencePackage:
    return make_package(
        interferences=[
            interference("int:1", "boss/screws"),
            interference("int:2", "boss/screws", volume_mm3=6.0),
            interference(
                "int:3",
                "flange/cover",
                status="truncated",
                volume_mm3=None,
                error="result list truncated at 100 pairs",
            ),
            interference("int:4", "other/config", configuration="Machining"),
        ]
    )


@pytest.fixture
def context(make_package: MakePackage) -> Iterator[ToolContext]:
    tool_context = context_for(interference_package(make_package))
    with use_context(tool_context):
        yield tool_context


def accepted_store(context: ToolContext, status: str = "active") -> ExceptionStore:
    """A store holding one exception bound to the boss/screws group as it stands now."""
    store = ExceptionStore()
    groups = {
        group.group_key: group
        for group in checks_interference.groups_of(context.ir)
    }
    exception = store.accept(
        groups["boss/screws"], context.ir, by="cole", note="press fit, intended"
    )
    exception.status = status  # type: ignore[assignment]
    return store


def recorded(context: ToolContext, name: str) -> RecordedTool:
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


# --- check_interference_group -----------------------------------------------------


def test_a_measured_group_is_one_demonstrated_finding(context: ToolContext) -> None:
    result = checks_interference.check_interference_group("boss/screws")

    finding = result["finding"]
    assert finding["check"] == "interference.static"
    assert finding["status"] == "demonstrated"
    assert finding["calculation"]["result"]["member_count"] == 2
    assert finding["calculation"]["result"]["max_volume_mm3"] == 6.0
    assert sorted(finding["component_ids"]) == ["cmp:0001", "cmp:0002"]
    assert result["group_key"] == "boss/screws"
    assert result["members"] == 2


def test_an_active_exception_clears_the_group_and_is_cited(context: ToolContext) -> None:
    context.exceptions = accepted_store(context)

    result = checks_interference.check_interference_group("boss/screws")

    finding = result["finding"]
    assert finding["status"] == "checked_within_scope"
    assert any("exception:EX-001" in limit for limit in finding["coverage_limits"])
    assert finding["exception_id"] == "EX-001"
    assert result["exception"]["id"] == "EX-001"


def test_an_exception_needing_review_does_not_clear_the_group(context: ToolContext) -> None:
    context.exceptions = accepted_store(context, status="needs_review")

    result = checks_interference.check_interference_group("boss/screws")

    finding = result["finding"]
    assert finding["status"] == "suspected"
    assert finding["exception_id"] == "EX-001"
    assert any("needs_review" in limit for limit in finding["coverage_limits"])


def test_a_truncated_group_is_unresolved_and_adds_run_coverage(context: ToolContext) -> None:
    result = checks_interference.check_interference_group("flange/cover")

    finding = result["finding"]
    assert finding["status"] == "unresolved"
    assert finding["coverage_limits"]
    unresolved = context.session.coverage.unresolved
    assert [item.check for item in unresolved] == ["interference.static"]
    assert unresolved[0].error == "result list truncated at 100 pairs"
    assert unresolved[0].scope.pairs == [["cmp:0001", "cmp:0002"]]
    assert result["coverage"] == 1


def test_a_computed_group_adds_no_run_coverage(context: ToolContext) -> None:
    checks_interference.check_interference_group("boss/screws")

    assert context.session.coverage.unresolved == []


def test_an_unknown_group_key_lists_the_ones_that_exist(context: ToolContext) -> None:
    result = checks_interference.check_interference_group("nope")

    assert "nope" in result["error"]
    assert "boss/screws" in result["error"]
    assert context.session.findings == []


def test_a_group_in_another_configuration_is_still_addressable(context: ToolContext) -> None:
    result = checks_interference.check_interference_group("other/config")

    assert result["finding"]["check"] == "interference.static"
    assert result["configuration"] == "Machining"


def test_check_interference_group_is_registered_and_records_a_step(
    context: ToolContext,
) -> None:
    tool = recorded(context, "check_interference_group")

    payload = json.loads(tool.call({"group_key": "boss/screws"}))

    assert payload["finding"]["status"] == "demonstrated"
    assert [step.tool for step in context.session.steps] == ["check_interference_group"]


def test_an_unknown_group_through_the_registry_is_failed_coverage(
    context: ToolContext,
) -> None:
    tool = recorded(context, "check_interference_group")

    with pytest.raises(ToolError):
        tool.call({"group_key": "nope"})

    assert [item.check for item in context.session.coverage.failed] == [
        "tool.check_interference_group"
    ]


# --- the query tools this check works with ----------------------------------------


def test_list_interferences_groups_the_members(context: ToolContext) -> None:
    groups = {group["group_key"]: group for group in query.list_interferences()}

    assert set(groups) == {"boss/screws", "flange/cover", "other/config"}
    assert groups["boss/screws"]["count"] == 2
    assert groups["flange/cover"]["statuses"] == ["truncated"]


def test_get_exceptions_reads_an_exception_store(context: ToolContext) -> None:
    context.exceptions = accepted_store(context)

    entries = query.get_exceptions()

    assert [entry["id"] for entry in entries] == ["EX-001"]
    assert query.get_exceptions(check="interference.static")
    assert query.get_exceptions(check="fit.size_only") == []


def test_a_retired_exception_is_not_returned(context: ToolContext) -> None:
    store = accepted_store(context)
    store.retire("EX-001")
    context.exceptions = store

    assert query.get_exceptions() == []
