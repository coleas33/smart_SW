"""Every step says how big its result was (feature 008 T088 to T090, FR-026, contracts/cost.md).

An `InvestigationStep` carries `result_bytes`, the UTF-8 length of the full payload in the one
serialization (`tool_result_text`, the pre-008 form, so sizes compare across settings and with
the recorded runs), and `result_tokens`, `count_tokens` of the same text, estimated with
o200k_base. Both are optional in the review-session contract, landed there before the model
writes them, and omitted from `session.json` when null, so every older session and committed
fixture keeps its bytes.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError as PydanticError

from swreview import tokens
from swreview.agent.providers import tool_result_text
from swreview.agent.settings import MODEL_VIEW_PANE, EfficiencySettings
from swreview.ir.loader import load_package, save_package
from swreview.mcp.chat_log import ChatLogSink
from swreview.report.session import InvestigationStep, load_session
from swreview.tokens import TokenizerUnavailable, count_tokens
from swreview.tools.context import build_context
from swreview.tools.registry import ToolRegistry, record_call
from tests.support.contracts import contract_validator, load_contract
from tests.support.prerun import prerun_package
from tests.unit.test_mcp_server import CHAT_LOG_FIELDS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ATTENTION_SESSION = FIXTURES / "attention" / "session-20260918-review.json"
"""A committed session written before feature 008: no step carries a size."""


def committed_session() -> dict[str, Any]:
    return json.loads(ATTENTION_SESSION.read_text(encoding="utf-8"))


def with_step_sizes(**sizes: Any) -> dict[str, Any]:
    """The committed session with every step carrying `sizes`."""
    session = copy.deepcopy(committed_session())
    for step in session["steps"]:
        step.update(sizes)
    return session


# --- the contract, before the model (T088) -------------------------------------------------


def test_a_session_whose_steps_carry_both_sizes_validates() -> None:
    contract_validator("review-session.schema.json").validate(
        with_step_sizes(result_bytes=612_418, result_tokens=204_857)
    )


def test_a_session_whose_steps_carry_neither_size_validates() -> None:
    session = committed_session()
    assert all("result_bytes" not in step for step in session["steps"])

    contract_validator("review-session.schema.json").validate(session)


def test_a_step_may_carry_its_bytes_without_its_tokens() -> None:
    """The tokenizer can be unavailable; the bytes are still known (contracts/cost.md)."""
    contract_validator("review-session.schema.json").validate(with_step_sizes(result_bytes=10))


@pytest.mark.parametrize(
    "sizes",
    [
        {"result_bytes": -1, "result_tokens": 0},
        {"result_bytes": 0, "result_tokens": -1},
        {"result_bytes": 1.5},
        {"result_tokens": "12"},
    ],
    ids=["negative-bytes", "negative-tokens", "fractional-bytes", "tokens-as-text"],
)
def test_a_size_that_is_not_a_count_is_refused(sizes: dict[str, Any]) -> None:
    with pytest.raises(SchemaError):
        contract_validator("review-session.schema.json").validate(with_step_sizes(**sizes))


def test_both_sizes_are_optional_properties_of_a_closed_step() -> None:
    step = load_contract("review-session.schema.json")["$defs"]["InvestigationStep"]

    assert step["additionalProperties"] is False
    assert step["properties"]["result_bytes"] == {"type": "integer", "minimum": 0}
    assert step["properties"]["result_tokens"]["type"] == "integer"
    assert step["properties"]["result_tokens"]["minimum"] == 0
    assert "o200k_base" in step["properties"]["result_tokens"]["description"]
    assert not {"result_bytes", "result_tokens"} & set(step["required"])


# --- the measurement, at the one recording funnel (T089) ------------------------------------


def dispatch_in(tmp_path: Path, name: str, **options: Any) -> tuple[Any, Any]:
    """A session context over the pre-run package, and its dispatch built with `options`."""
    folder = tmp_path / name
    save_package(options.pop("package", prerun_package()), folder)
    context = build_context(load_package(folder))
    return context, ToolRegistry().dispatch(context, **options)


def measured(payload: Mapping[str, Any]) -> tuple[int, int]:
    """What the step must say: the full payload's bytes and tokens in the one serialization."""
    text = tool_result_text(payload)
    return len(text.encode("utf-8")), count_tokens(text)


def sizes_of(step: InvestigationStep) -> tuple[int | None, int | None]:
    return step.result_bytes, step.result_tokens


@pytest.mark.usefixtures("vocabulary")
def test_an_ok_an_error_and_an_unknown_call_carry_their_payloads_sizes(tmp_path: Path) -> None:
    context, dispatch = dispatch_in(tmp_path, "run")

    ok = dispatch.call("list_components", {"parent_id": None, "include_suppressed": True})
    error = dispatch.call("get_component", {"component_id": "cmp:9999"})
    unknown = dispatch.call("no_such_tool", {})

    assert not ok.is_error and error.is_error and unknown.is_error
    steps = context.session.steps
    assert [sizes_of(step) for step in steps] == [
        measured(ok.payload),
        measured(error.payload),
        measured(unknown.payload),
    ]
    assert all((step.result_bytes or 0) > 0 and (step.result_tokens or 0) > 0 for step in steps)


@pytest.mark.usefixtures("vocabulary")
def test_a_withheld_call_carries_its_refusals_size(tmp_path: Path) -> None:
    context, dispatch = dispatch_in(
        tmp_path,
        "empty",
        package=prerun_package().model_copy(update={"features": []}),
        efficiency=EfficiencySettings(tool_tiers=True),
    )

    withheld = dispatch.call("check_rms_part", {})

    assert withheld.is_error
    [step] = context.session.steps
    assert sizes_of(step) == measured(withheld.payload)


@pytest.mark.usefixtures("vocabulary")
def test_a_slimmed_call_is_measured_on_its_full_payload_never_its_view(tmp_path: Path) -> None:
    context, dispatch = dispatch_in(tmp_path, "slim", model_view=MODEL_VIEW_PANE)

    result = dispatch.call("check_rms_part", {})

    assert result.view is not None and result.view != result.payload
    [step] = context.session.steps
    assert sizes_of(step) == measured(result.payload)
    assert step.result_tokens != count_tokens(tool_result_text(result.view, compact=True))


def test_an_unavailable_tokenizer_leaves_the_tokens_unknown_and_the_call_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> Any:
        raise TokenizerUnavailable("the vocabulary is not on this machine")

    monkeypatch.setattr(tokens, "encoding", unavailable)
    context, dispatch = dispatch_in(tmp_path, "run")

    result = dispatch.call("get_package_summary", {})

    assert not result.is_error
    [step] = context.session.steps
    assert step.result_tokens is None
    assert step.result_bytes == len(tool_result_text(result.payload).encode("utf-8"))
    dumped = step.model_dump(mode="json")
    assert "result_tokens" not in dumped
    assert dumped["result_bytes"] == step.result_bytes


def plain_step(**sizes: Any) -> InvestigationStep:
    return InvestigationStep(
        index=0,
        tool="list_gaps",
        arguments={},
        result_summary="list_gaps returned 0 rows",
        status="ok",
        error=None,
        elapsed_s=0.0,
        **sizes,
    )


def test_a_step_without_sizes_serializes_without_the_keys() -> None:
    step = plain_step()

    assert sizes_of(step) == (None, None)
    assert "result_bytes" not in step.model_dump(mode="json")
    assert not {"result_bytes", "result_tokens"} & set(json.loads(step.model_dump_json()))


def test_a_step_with_sizes_round_trips() -> None:
    step = plain_step(result_bytes=612_418, result_tokens=204_857)

    assert InvestigationStep.model_validate_json(step.model_dump_json()) == step


@pytest.mark.parametrize("field", ["result_bytes", "result_tokens"])
def test_the_model_refuses_a_negative_size(field: str) -> None:
    with pytest.raises(PydanticError):
        plain_step(**{field: -1})


def test_a_committed_session_loads_and_re_dumps_with_no_size_keys() -> None:
    session = load_session(ATTENTION_SESSION)

    dumped = json.loads(session.model_dump_json())

    assert session.steps
    assert all(sizes_of(step) == (None, None) for step in session.steps)
    assert all(not {"result_bytes", "result_tokens"} & set(step) for step in dumped["steps"])


@pytest.mark.usefixtures("vocabulary")
def test_a_chat_log_line_keeps_exactly_its_fields(tmp_path: Path) -> None:
    """The record carries the sizes; the chat log's line is its contract's, field for field."""
    sink = ChatLogSink(path=tmp_path / "chat-log.jsonl")

    record_call(
        sink,
        tool="list_gaps",
        arguments={},
        payload={"gaps": [], "count": 0},
        elapsed_s=0.01,
        error=None,
    )

    [line] = (tmp_path / "chat-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert list(json.loads(line)) == list(CHAT_LOG_FIELDS)
