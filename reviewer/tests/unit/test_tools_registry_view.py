"""The view is computed once, beside the payload (feature 008 T064, research R2.24).

`RecordedTool._finish` is the one choke point where every call becomes a `ToolCallResult`,
so that is where the model's view is computed when payload slimming is on - and nowhere
else. `payload` stays the tool's full return, which the step summary, the `tool.finished`
event, MCP and the goldens read; `view` is what `model_payload` hands the adapters. With
slimming off there is no view, and every byte is what it was.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from swreview.agent.checklist import load_checklist
from swreview.agent.providers import ToolCallRequest, call_tool, model_payload
from swreview.agent.runner import COVERAGE_STOP_KEY, COVERAGE_STOP_SENTENCE, CoverageStopTools
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE, EfficiencySettings
from swreview.ir.loader import load_package, save_package
from swreview.tools.context import build_context
from swreview.tools.model_view import model_view
from swreview.tools.registry import ToolRegistry
from tests.support.prerun import prerun_package
from tests.unit.test_tool_payload import encoding_digests, gemini_objects, openai_objects


def context_in(tmp_path: Path, name: str = "run") -> Any:
    folder = tmp_path / name
    save_package(prerun_package(), folder)
    return build_context(load_package(folder))


CALLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("check_rms_part", {}),
    ("list_components", {"parent_id": None, "include_suppressed": True}),
    ("list_gaps", {}),
    ("get_component", {"component_id": "cmp:0002"}),
)


def test_with_slimming_the_payload_is_the_return_and_the_view_is_the_model_view(
    tmp_path: Path,
) -> None:
    plain = ToolRegistry().dispatch(context_in(tmp_path, "plain"))
    slim = ToolRegistry().dispatch(context_in(tmp_path, "slim"), model_view=MODEL_VIEW_PANE)

    for name, arguments in CALLS:
        off = plain.call(name, arguments)
        on = slim.call(name, arguments)
        assert on.payload == off.payload, name
        assert on.view == model_view(name, on.payload), name
        assert off.view is None, name
        assert model_payload(off) == off.payload
        assert model_payload(on) == on.view


def test_the_summaries_are_byte_identical_with_slimming_on_and_off(tmp_path: Path) -> None:
    summaries: dict[str, list[tuple[str, str]]] = {}
    for label, settings in (("off", MODEL_VIEW_OFF), ("on", MODEL_VIEW_PANE)):
        context = context_in(tmp_path, label)
        dispatch = ToolRegistry().dispatch(context, model_view=settings)
        events: list[tuple[str, dict[str, Any]]] = []

        def collect(kind: str, body: Any, into: list[Any] = events) -> None:
            into.append((kind, dict(body)))

        for index, (name, arguments) in enumerate(CALLS):
            call_tool(
                request=ToolCallRequest(call_id=f"c{index}", name=name, arguments=arguments),
                tools=dispatch,
                on_event=collect,
                step_index=index,
                clock=lambda: 0.0,
            )
        finished = [body["result_summary"] for kind, body in events if kind == "tool.finished"]
        steps = [step.result_summary for step in context.session.steps]
        summaries[label] = list(zip(finished, steps, strict=True))

    assert summaries["on"] == summaries["off"]


def test_withheld_and_unknown_results_have_no_view(tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    empty = prerun_package().model_copy(update={"features": []})
    save_package(empty, folder)
    context = build_context(load_package(folder))
    dispatch = ToolRegistry().dispatch(
        context, efficiency=EfficiencySettings(tool_tiers=True), model_view=MODEL_VIEW_PANE
    )

    withheld = dispatch.call("check_rms_part", {})
    unknown = dispatch.call("no_such_tool", {})

    assert withheld.is_error and withheld.view is None
    assert unknown.is_error and unknown.view is None


def test_get_finding_is_offered_exactly_when_slimming_is_on(tmp_path: Path) -> None:
    context = context_in(tmp_path)

    assert "get_finding" in ToolRegistry().dispatch(context, model_view=MODEL_VIEW_PANE).by_name
    assert "get_finding" not in ToolRegistry().dispatch(context, model_view=MODEL_VIEW_OFF).by_name
    assert "get_finding" not in ToolRegistry().dispatch(context).by_name


def encoded_hashes(dispatch: Any) -> dict[str, str]:
    specs = [tool.spec for tool in dispatch]
    compact = {"separators": (",", ":")}
    return {
        "gemini": hashlib.sha256(
            json.dumps(gemini_objects(specs), **compact).encode("utf-8")
        ).hexdigest(),
        "openai": hashlib.sha256(
            json.dumps(openai_objects(specs), **compact).encode("utf-8")
        ).hexdigest(),
    }


def test_with_no_view_the_array_is_todays_array(tmp_path: Path) -> None:
    dispatch = ToolRegistry().dispatch(context_in(tmp_path))

    assert encoded_hashes(dispatch) == encoding_digests()


def test_the_slim_array_is_the_same_on_every_round(tmp_path: Path) -> None:
    context = context_in(tmp_path)
    first = ToolRegistry().dispatch(context, model_view=MODEL_VIEW_PANE)
    second = ToolRegistry().dispatch(context, model_view=MODEL_VIEW_PANE)

    assert encoded_hashes(first) == encoded_hashes(second)
    assert [tool.name for tool in first] == [tool.name for tool in second]


def test_the_coverage_stop_sentence_reaches_the_view(tmp_path: Path) -> None:
    """Lever 7 under slimming (research R2.35): the sentence rides on what the model reads."""
    context = context_in(tmp_path)
    dispatch = ToolRegistry().dispatch(context, model_view=MODEL_VIEW_PANE)
    tools = CoverageStopTools(dispatch, load_checklist(), context.session)
    tools.checklist = type(
        "Closed", (), {"items": [], "bucket_of": lambda self, item, session: "checked"}
    )()

    result = tools.call("check_rms_part", {})

    assert result.view is not None
    assert model_payload(result)[COVERAGE_STOP_KEY] == COVERAGE_STOP_SENTENCE
    assert result.payload[COVERAGE_STOP_KEY] == COVERAGE_STOP_SENTENCE
