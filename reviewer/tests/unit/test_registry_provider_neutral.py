"""Unit tests for the provider-neutral tool registry (T012).

`tools/registry.py` is the one choke point every tool call goes through, whichever
provider is driving and whether the run is a review session or a general chat. Four
guarantees are asserted here, in the order `RecordedTool.call` applies them:

1. **validate** - arguments are checked against the tool's signature by
   `pydantic.validate_call` before the function sees them, so a hallucinated argument is
   a result the model can read rather than a `TypeError` up the stack;
2. **record** - every call, successful or not, is written through an *injectable* sink.
   A review run gets the session sink (an `InvestigationStep`, plus a `failed` coverage
   item when the call failed); the general-chat MCP server in T059 passes its chat-log
   sink to the same wrapper instead of reimplementing any of this;
3. **convert** - an error is `ToolCallResult(is_error=True)` with an `{"error": ...}`
   payload, whether the tool returned one itself or raised;
4. **never raise** - including for a tool name that is not registered at all, which is
   routine provider behaviour and which feature 001 never had to handle because the
   vendor SDK did the dispatching.

The last three tests are the guard for FR-026: no module under `reviewer/src/` imports the
retired SDK, and no source file so much as spells its name - an import scan alone would
miss a string constant such as a default model id.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.checklist import load_checklist
from swreview.agent.providers import ProviderTool, ToolCallResult
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import EvidencePackage
from swreview.tools.context import ToolContext, context_for
from swreview.tools.registry import (
    REGISTRATIONS,
    RecordedTool,
    ToolCallRecord,
    ToolRegistry,
    build_tools,
)

MakePackage = Callable[..., EvidencePackage]
COMPONENT = "cmp:0001"
TOP_LEVEL = ["cmp:0001", "cmp:0002"]


@pytest.fixture
def context(make_package: MakePackage) -> ToolContext:
    """A review context over the minimal package: the session sink is the default."""
    return context_for(make_package())


def sessionless(package: EvidencePackage) -> ToolContext:
    """A context with no review session - what the general-chat MCP server will build."""
    return ToolContext(
        package=LoadedPackage(package=package, base_dir=Path(".")),
        session=None,
        checklist=load_checklist(),
    )


@dataclass
class ListSink:
    """A recording sink that keeps the records in a list. Stands in for the chat log."""

    records: list[ToolCallRecord] = field(default_factory=list)

    def record(self, record: ToolCallRecord) -> None:
        self.records.append(record)


def tool_named(context: ToolContext, name: str, **kwargs: Any) -> RecordedTool:
    tools = {tool.name: tool for tool in ToolRegistry().build(context, **kwargs)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


# --- what `build` hands a provider --------------------------------------------------


def test_every_built_tool_is_a_provider_tool_over_a_tool_spec(context: ToolContext) -> None:
    tools = ToolRegistry().build(context)

    assert tools, "the registry built no tools"
    for tool in tools:
        assert isinstance(tool, ProviderTool)
        assert tool.name and tool.description
        assert tool.schema["type"] == "object"
        assert "$defs" not in tool.schema


def test_the_built_names_are_the_registered_groups_in_order(context: ToolContext) -> None:
    expected = [fn.__name__ for registration in REGISTRATIONS for fn in registration()]

    assert [tool.name for tool in build_tools(context)] == expected


# --- 1. validate --------------------------------------------------------------------


def test_an_argument_the_tool_does_not_take_is_an_error_result(context: ToolContext) -> None:
    tool = tool_named(context, "get_component")

    result = tool.call({"component_id": COMPONENT, "depth": 3}, "call_1")

    assert result.is_error is True
    assert "depth" in result.payload["error"]
    assert context.session.steps[0].status == "error"


def test_an_argument_of_the_wrong_type_is_an_error_result(context: ToolContext) -> None:
    tool = tool_named(context, "get_component")

    result = tool.call({"component_id": 40.0}, "call_1")

    assert result.is_error is True
    assert "error" in result.payload


def test_a_null_for_a_parameter_that_cannot_be_null_means_use_the_default(
    context: ToolContext,
) -> None:
    """Strict mode has no "omitted": every property is required, so optional is nullable.

    `include_suppressed: bool = True` is not a nullable parameter, so a null for it means
    the model did not care - the default, not a validation error.
    """
    tool = tool_named(context, "list_components")

    result = tool.call({"parent_id": None, "include_suppressed": None}, "call_1")

    assert result.is_error is False
    assert [item["id"] for item in result.payload["result"]] == TOP_LEVEL


# --- 2. record ----------------------------------------------------------------------


def test_a_successful_call_records_a_step_and_carries_the_call_id(
    context: ToolContext,
) -> None:
    tool = tool_named(context, "get_component")

    result = tool.call({"component_id": COMPONENT}, "call_7")

    assert isinstance(result, ToolCallResult)
    assert result.call_id == "call_7"
    assert result.is_error is False
    assert result.payload["component"]["id"] == COMPONENT
    (step,) = context.session.steps
    assert step.index == 0
    assert step.tool == "get_component"
    assert step.arguments == {"component_id": COMPONENT}
    assert step.status == "ok"
    assert step.error is None
    assert step.elapsed_s >= 0.0
    assert len(step.result_summary) <= 200
    assert context.session.coverage.failed == []


def test_a_call_id_is_optional_because_the_caller_is_not_always_a_provider(
    context: ToolContext,
) -> None:
    result = tool_named(context, "get_package_summary").call({})

    assert result.is_error is False
    assert result.call_id == ""


def test_the_recording_sink_is_injectable(make_package: MakePackage) -> None:
    context = sessionless(make_package())
    sink = ListSink()

    result = tool_named(context, "get_component", sink=sink).call({"component_id": COMPONENT})

    assert result.is_error is False
    assert [record.tool for record in sink.records] == ["get_component"]
    assert sink.records[0].status == "ok"
    assert sink.records[0].arguments == {"component_id": COMPONENT}
    assert sink.records[0].error is None
    assert sink.records[0].elapsed_s >= 0.0


def test_a_context_with_no_session_and_no_sink_is_a_caller_mistake(
    make_package: MakePackage,
) -> None:
    with pytest.raises(ValueError, match="recording sink"):
        ToolRegistry().build(sessionless(make_package()))


# --- 3. convert, 4. never raise ------------------------------------------------------


def test_an_error_result_from_the_tool_is_an_error_result_and_failed_coverage(
    context: ToolContext,
) -> None:
    tool = tool_named(context, "get_component")

    result = tool.call({"component_id": "cmp:9999"}, "call_1")

    assert result.is_error is True
    assert result.payload["error"] == "unknown component id 'cmp:9999'"
    assert context.session.steps[0].status == "error"
    assert [item.check for item in context.session.coverage.failed] == ["tool.get_component"]
    assert context.session.coverage.failed[0].error == result.payload["error"]


def test_a_raised_exception_becomes_an_error_payload_and_never_propagates(
    context: ToolContext,
) -> None:
    tool = tool_named(context, "get_component", fail_tool=["get_component"])

    result = tool.call({"component_id": COMPONENT}, "call_1")

    assert result.is_error is True
    assert "--fail-tool" in result.payload["error"]
    assert [item.check for item in context.session.coverage.failed] == ["tool.get_component"]


def test_fail_tool_rejects_a_name_that_is_not_a_tool(context: ToolContext) -> None:
    with pytest.raises(ValueError, match="no such tool"):
        ToolRegistry().build(context, fail_tool=["nope"])


def test_a_list_payload_is_wrapped_so_a_tool_result_is_always_an_object(
    context: ToolContext,
) -> None:
    result = tool_named(context, "list_components").call({}, "call_1")

    assert result.is_error is False
    assert [item["id"] for item in result.payload["result"]] == TOP_LEVEL


# --- dispatch by name ----------------------------------------------------------------


def test_dispatch_calls_the_named_tool(context: ToolContext) -> None:
    dispatch = ToolRegistry().dispatch(context)

    result = dispatch.call("get_component", {"component_id": COMPONENT}, "call_1")

    assert result.is_error is False
    assert dispatch.get("get_component") is not None
    assert dispatch.get("no_such_tool") is None
    assert [tool.name for tool in dispatch.tools] == [tool.name for tool in build_tools(context)]


def test_a_tool_name_that_is_not_registered_is_an_error_result_not_a_raise(
    context: ToolContext,
) -> None:
    """A hallucinated tool name is routine: the model gets a result naming what it asked
    for, and the session records the call as failed coverage like any other failure."""
    dispatch = ToolRegistry().dispatch(context)

    result = dispatch.call("check_everything", {"scope": "all"}, "call_4")

    assert result.is_error is True
    assert result.call_id == "call_4"
    assert "check_everything" in result.payload["error"]
    (step,) = context.session.steps
    assert step.tool == "check_everything"
    assert step.status == "error"
    assert step.arguments == {"scope": "all"}
    assert [item.check for item in context.session.coverage.failed] == ["tool.check_everything"]


def test_dispatch_records_an_unknown_tool_through_the_injected_sink(
    make_package: MakePackage,
) -> None:
    sink = ListSink()
    dispatch = ToolRegistry().dispatch(sessionless(make_package()), sink=sink)

    result = dispatch.call("check_everything", {}, "call_1")

    assert result.is_error is True
    assert [record.tool for record in sink.records] == ["check_everything"]
    assert sink.records[0].status == "error"


# --- FR-026: the retired SDK is gone from the source tree ----------------------------

SRC = Path(__file__).resolve().parents[2] / "src" / "swreview"

PENDING: frozenset[str] = frozenset()
"""Modules that still name the retired vendor and are rewritten by a later Phase 2 task.

It was a countdown, not a permanent exemption: `agent/runner.py` (T015), then `cli.py`
and `tools/context.py`'s `DEFAULT_MODEL` (T023). It is empty, so the scan below is strict
over every single `*.py` under `reviewer/src/`, with no exemptions at all (FR-026).

There is deliberately no carve-out for `agent/providers/__init__.py`: `ProviderName` does
not have the retired names, so `providers.get` rejects them through the same
`UnknownProviderError` as any other unsupported name and never has to spell them.
`tests/unit/test_provider_protocol.py` is where they are still written down, and a test
tree is not `reviewer/src/`.
"""

RETIRED = re.compile(r"(?i)anthropic|claude")


def source_files() -> list[tuple[str, Path]]:
    return [(path.relative_to(SRC).as_posix(), path) for path in sorted(SRC.rglob("*.py"))]


def test_no_module_under_src_imports_the_retired_sdk() -> None:
    offenders = []
    for name, path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            if "anthropic" in roots and name not in PENDING:
                offenders.append(f"{name}:{node.lineno}")

    assert offenders == []


def test_no_source_file_names_the_retired_vendor() -> None:
    offenders = {
        name
        for name, path in source_files()
        if RETIRED.search(path.read_text(encoding="utf-8"))
    }

    assert offenders <= PENDING, (
        f"{sorted(offenders - PENDING)} name the retired vendor; "
        "FR-026 leaves no import, dependency, string constant or model id behind"
    )
