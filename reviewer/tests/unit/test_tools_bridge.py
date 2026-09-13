"""Unit tests for the live-bridge tools (T073).

`bridge_capture`, `bridge_measure` and `bridge_interference` exist only when the reviewer
was started with `--bridge`, so these tests cover both halves of that:

- with no bridge wired, the three tools are not in the registry at all and
  `request_capture` says `unresolved` instead of inventing a view;
- with a fake bridge client wired, each tool sends the coarse call, writes what came back
  into the session's copy of the package - captures, interferences and the host's gaps -
  and turns a `BridgeError` (including an open circuit) into an error result, which the
  registry records as `failed` coverage.

The result shapes the fake replays are the ones in
`extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md` version 1.0.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from anthropic.lib.tools import ToolError

from swreview.bridge.client import BridgeError, BridgeOpenError
from swreview.ir.models import EvidencePackage
from swreview.tools import bridge as bridge_tools
from swreview.tools import session as session_tools
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.registry import RecordedTool, ToolRegistry

MakePackage = Callable[..., EvidencePackage]

CAPTURE_ROW = {
    "id": "cap:0001",
    "persist_ref": "YWJj",
    "component_ids": ["cmp:0001"],
    "file": "captures/cap-0001.png",
    "view": "iso",
    "note": "iso view of the boss",
}

INTERFERENCE = {
    "id": "int:live-1",
    "configuration": "Default",
    "component_ids": ["cmp:0001", "cmp:0002"],
    "volume": {"value": 3.5, "unit": "m3"},
    "settings": {
        "treat_coincident_as_interference": False,
        "treat_subassemblies_as_components": True,
        "include_multibody": False,
        "ignore_hidden": True,
        "fastener_folder_treatment": "include",
    },
    "status": "computed",
    "error": None,
    "group_key": "boss/screws",
    "is_fastener": False,
    "is_possible": False,
}

VOLUME_UNIT_GAP = {
    "kind": "unsupported",
    "entity_kind": "interference_volume_unit",
    "entity_id": None,
    "reason": "IInterference.Volume unit assumed m3; verify on workstation",
    "error": None,
}


class FakeBridge:
    """A bridge client that answers from a script and records what it was asked."""

    def __init__(self, results: dict[str, Any] | None = None, raises: Exception | None = None):
        self.results = results or {}
        self.raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.circuit_open = isinstance(raises, BridgeOpenError)
        self.last_error = None if raises is None else str(raises)

    def _answer(self, command: str, args: dict[str, Any]) -> Any:
        self.calls.append((command, args))
        if self.raises is not None:
            raise self.raises
        return self.results[command]

    def capture(self, persist_ref: str, view: str = "fit", **kwargs: Any) -> Any:
        return self._answer("capture", {"persist_ref": persist_ref, "view": view, **kwargs})

    def measure(self, persist_ref_a: str, persist_ref_b: str, **kwargs: Any) -> Any:
        return self._answer(
            "measure",
            {"persist_ref_a": persist_ref_a, "persist_ref_b": persist_ref_b, **kwargs},
        )

    def interference(
        self,
        component_ids: list[str],
        configuration: str | None = None,
        settings: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._answer(
            "interference",
            {
                "component_ids": component_ids,
                "configuration": configuration,
                "settings": settings,
                **kwargs,
            },
        )


def bridged(make_package: MakePackage, bridge: Any) -> ToolContext:
    context = context_for(make_package())
    context.bridge = bridge
    return context


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge(
        {
            "capture": {
                "capture": dict(CAPTURE_ROW),
                "path": r"C:\host\pkg\captures\cap-0001.png",
                "gap": None,
            },
            "measure": {
                "distance": {"value": 0.0125, "unit": "m"},
                "delta_x": {"value": 0.0125, "unit": "m"},
            },
            "interference": {"interferences": [INTERFERENCE], "gaps": [VOLUME_UNIT_GAP]},
        }
    )


@pytest.fixture
def context(make_package: MakePackage, bridge: FakeBridge) -> Iterator[ToolContext]:
    tool_context = bridged(make_package, bridge)
    with use_context(tool_context):
        yield tool_context


def tools_of(context: ToolContext) -> dict[str, RecordedTool]:
    return {tool.name: tool for tool in ToolRegistry().build(context)}


# --- registration ------------------------------------------------------------------


def test_the_bridge_tools_are_absent_without_a_bridge(make_package: MakePackage) -> None:
    names = set(tools_of(context_for(make_package())))

    assert not names & {"bridge_capture", "bridge_measure", "bridge_interference"}


def test_the_bridge_tools_appear_when_a_bridge_is_wired(context: ToolContext) -> None:
    names = set(tools_of(context))

    assert {"bridge_capture", "bridge_measure", "bridge_interference"} <= names


def test_fail_tool_accepts_a_bridge_tool_name_when_the_bridge_is_wired(
    context: ToolContext,
) -> None:
    tools = {
        tool.name: tool for tool in ToolRegistry().build(context, fail_tool=["bridge_capture"])
    }

    with pytest.raises(ToolError):
        tools["bridge_capture"].call({"persist_ref": "YWJj", "view": "iso"})


# --- bridge_capture ----------------------------------------------------------------


def test_bridge_capture_appends_a_capture_and_returns_its_path(
    context: ToolContext, bridge: FakeBridge
) -> None:
    result = bridge_tools.bridge_capture("YWJj", "iso")

    assert result["status"] == "captured"
    assert result["file"] == "captures/cap-0001.png"
    assert result["host_path"].endswith("cap-0001.png")
    assert bridge.calls[0][0] == "capture"
    assert bridge.calls[0][1]["view"] == "iso"
    capture = context.ir.captures[-1]
    assert capture.id == "cap:0001"
    assert capture.file == "captures/cap-0001.png"
    assert capture.component_ids == ["cmp:0001"]


def test_two_captures_get_different_ids(context: ToolContext) -> None:
    bridge_tools.bridge_capture("YWJj", "iso")
    bridge_tools.bridge_capture("YWJj", "front")

    ids = [capture.id for capture in context.ir.captures]
    assert len(ids) == len(set(ids)) == 2


def test_bridge_capture_refuses_a_view_the_host_cannot_frame(context: ToolContext) -> None:
    result = bridge_tools.bridge_capture("YWJj", "back")

    assert "back" in result["error"]
    assert "iso" in result["error"]


def test_bridge_capture_refuses_a_file_outside_the_package(make_package: MakePackage) -> None:
    row = {**CAPTURE_ROW, "file": "../../elsewhere/cap.png"}
    bridge = FakeBridge({"capture": {"capture": row, "path": None, "gap": None}})
    with use_context(bridged(make_package, bridge)) as context:
        result = bridge_tools.bridge_capture("YWJj", "iso")

    assert "outside the package" in result["error"]
    assert context.ir.captures == []


def test_bridge_capture_refuses_a_result_that_names_no_file(make_package: MakePackage) -> None:
    bridge = FakeBridge({"capture": {"capture": None, "path": None, "gap": None}})
    with use_context(bridged(make_package, bridge)):
        result = bridge_tools.bridge_capture("YWJj", "iso")

    assert "no file" in result["error"]


def test_a_failed_capture_records_the_hosts_gap(make_package: MakePackage) -> None:
    gap = {
        "kind": "not_extracted",
        "entity_kind": "capture",
        "entity_id": None,
        "reason": "select the entity to capture (iso view)",
        "error": "The reference did not resolve: deleted",
    }
    bridge = FakeBridge(
        raises=BridgeError("could not select", {"capture": None, "path": None, "gap": gap})
    )
    context = bridged(make_package, bridge)
    with use_context(context):
        result = bridge_tools.bridge_capture("YWJj", "iso")

    assert "recorded as a gap" in result["error"]
    assert context.ir.gaps[-1].entity_kind == "capture"


def test_a_malformed_host_gap_is_recorded_rather_than_dropped(make_package: MakePackage) -> None:
    malformed = {"kind": "no_such_kind", "reason": "select failed"}
    bridge = FakeBridge(
        raises=BridgeError("could not select", {"capture": None, "path": None, "gap": malformed})
    )
    context = bridged(make_package, bridge)
    before = len(context.ir.gaps)
    with use_context(context):
        result = bridge_tools.bridge_capture("YWJj", "iso")

    assert "recorded as a gap" in result["error"]
    assert len(context.ir.gaps) == before + 1
    recorded = context.ir.gaps[-1]
    assert recorded.kind == "tool_error"
    assert recorded.entity_kind == "bridge_gap"
    assert "no_such_kind" in recorded.reason
    assert recorded.error


# --- bridge_measure ----------------------------------------------------------------


def test_bridge_measure_returns_the_measurement_in_the_hosts_units(
    context: ToolContext, bridge: FakeBridge
) -> None:
    result = bridge_tools.bridge_measure("YWJj", "ZGVm")

    assert result["measurement"]["distance"] == {"value": 0.0125, "unit": "m"}
    assert "metres" in result["source"]
    assert bridge.calls[0][0] == "measure"


# --- bridge_interference -----------------------------------------------------------


def test_bridge_interference_returns_stores_and_records_the_gaps(
    context: ToolContext, bridge: FakeBridge
) -> None:
    result = bridge_tools.bridge_interference(["cmp:0001", "cmp:0002"], "Default", {})

    assert [item["id"] for item in result["interferences"]] == ["int:live-1"]
    assert [item.id for item in context.ir.interferences] == ["int:live-1"]
    assert bridge.calls[0][1]["configuration"] == "Default"
    assert result["gaps"] == [VOLUME_UNIT_GAP["reason"]]
    assert context.ir.gaps[-1].entity_kind == "interference_volume_unit"


def test_bridge_interference_does_not_add_a_result_twice(context: ToolContext) -> None:
    bridge_tools.bridge_interference(["cmp:0001"], "Default", {})
    second = bridge_tools.bridge_interference(["cmp:0001"], "Default", {})

    assert second["added_to_package"] == 0
    assert len(context.ir.interferences) == 1


def test_bridge_interference_rejects_an_unknown_component(context: ToolContext) -> None:
    result = bridge_tools.bridge_interference(["cmp:9999"], "Default", {})

    assert "cmp:9999" in result["error"]


def test_bridge_interference_refuses_a_malformed_result(make_package: MakePackage) -> None:
    bridge = FakeBridge({"interference": {"interferences": [{"id": "int:1"}], "gaps": []}})
    with use_context(bridged(make_package, bridge)):
        result = bridge_tools.bridge_interference(["cmp:0001"], "Default", {})

    assert "error" in result
    assert "interference" in result["error"]


# --- failures ----------------------------------------------------------------------


def test_a_bridge_error_is_an_error_result(make_package: MakePackage) -> None:
    bridge = FakeBridge(raises=BridgeError("SelectByID2 returned false"))
    with use_context(bridged(make_package, bridge)):
        result = bridge_tools.bridge_capture("YWJj", "iso")

    assert "SelectByID2" in result["error"]


def test_an_open_circuit_is_an_error_result_and_failed_coverage(
    make_package: MakePackage,
) -> None:
    bridge = FakeBridge(raises=BridgeOpenError("the bridge circuit is open"))
    context = bridged(make_package, bridge)
    with use_context(context):
        tool = tools_of(context)["bridge_measure"]
        with pytest.raises(ToolError) as caught:
            tool.call({"persist_ref_a": "YWJj", "persist_ref_b": "ZGVm"})

    assert "circuit is open" in json.loads(caught.value.content)["error"]
    assert [item.check for item in context.session.coverage.failed] == ["tool.bridge_measure"]


def test_every_further_call_after_the_circuit_opens_is_failed_coverage(
    make_package: MakePackage,
) -> None:
    bridge = FakeBridge(raises=BridgeOpenError("the bridge circuit is open"))
    context = bridged(make_package, bridge)
    with use_context(context):
        tools = tools_of(context)
        for name, arguments in (
            ("bridge_capture", {"persist_ref": "YWJj", "view": "iso"}),
            ("bridge_measure", {"persist_ref_a": "YWJj", "persist_ref_b": "ZGVm"}),
        ):
            with pytest.raises(ToolError):
                tools[name].call(arguments)

    assert [item.check for item in context.session.coverage.failed] == [
        "tool.bridge_capture",
        "tool.bridge_measure",
    ]


# --- request_capture through the bridge --------------------------------------------


def test_request_capture_uses_the_bridge_when_one_is_wired(
    context: ToolContext, bridge: FakeBridge
) -> None:
    result = session_tools.request_capture("cmp:0001", "iso")

    assert result["status"] == "captured"
    assert result["capture"]["file"] == "captures/cap-0001.png"
    assert bridge.calls[0][1]["persist_ref"] == context.component("cmp:0001").persist_ref
    assert context.ir.captures[-1].component_ids == ["cmp:0001"]


def test_request_capture_stays_unresolved_for_a_view_the_bridge_cannot_frame(
    context: ToolContext, bridge: FakeBridge
) -> None:
    result = session_tools.request_capture("cmp:0001", "bottom")

    assert result["status"] == "unresolved"
    assert "iso" in result["reason"]
    assert bridge.calls == []


def test_request_capture_without_a_bridge_stays_unresolved(make_package: MakePackage) -> None:
    with use_context(context_for(make_package())):
        result = session_tools.request_capture("cmp:0001", "iso")

    assert result == {"status": "unresolved", "reason": "no capture and no bridge"}


def test_request_capture_reports_a_bridge_failure(make_package: MakePackage) -> None:
    bridge = FakeBridge(raises=BridgeError("the pipe has been ended"))
    with use_context(bridged(make_package, bridge)):
        result = session_tools.request_capture("cmp:0001", "iso")

    assert "the pipe has been ended" in result["error"]
