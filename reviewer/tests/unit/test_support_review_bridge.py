"""The scripted review bridge (008 T011, research R2.50).

`tests/support/review_bridge.ScriptedReviewBridge` stands in for the live SOLIDWORKS bridge
wherever a review needs one without a seat: the fixture generator answers a recording's live
`bridge_interference` call with it, and the checks-first tests (T041) and the serial-dispatch
test (T080) drive live interference and parallel calls through it. These tests pin what those
callers rely on: it plugs into `start_review` through `bridge_factory`, answers in order,
raises what it is told to, records every call, can lack a command the way an old host does,
and refuses to be entered twice at once - SOLIDWORKS answers on one thread.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.bridge.client import BridgeError, BridgeOpenError
from swreview.ir.loader import save_package
from swreview.ir.models import Gap, Interference
from tests.support.prerun import prerun_package
from tests.support.review_bridge import (
    RECORDED_INTERFERENCE_SETTINGS,
    VOLUME_UNIT_GAP,
    ScriptedReviewBridge,
    interference_row,
)

ROWS = [interference_row("int:0101", ("cmp:0002", "cmp:0003"), "cmp:0002|cmp:0003", 42.0)]


def interference_call(bridge: ScriptedReviewBridge, configuration: str = "Default") -> Any:
    return bridge.interference([], configuration, dict(RECORDED_INTERFERENCE_SETTINGS))


# --- answers, failures, records --------------------------------------------------------


def test_it_returns_scripted_results_in_order() -> None:
    first = {"interferences": ROWS, "gaps": [VOLUME_UNIT_GAP]}
    second = {"interferences": [], "gaps": []}
    bridge = ScriptedReviewBridge(results={"interference": [first, second]})

    assert interference_call(bridge) == first
    assert interference_call(bridge, "Other") == second


def test_running_out_of_scripted_results_is_a_scripting_mistake() -> None:
    bridge = ScriptedReviewBridge(results={"interference": [{"interferences": [], "gaps": []}]})
    interference_call(bridge)

    with pytest.raises(AssertionError, match="interference"):
        interference_call(bridge)


def test_it_raises_a_scripted_bridge_error_on_every_call() -> None:
    bridge = ScriptedReviewBridge(raises={"interference": BridgeError("the host said no")})

    for _ in range(2):
        with pytest.raises(BridgeError, match="the host said no"):
            interference_call(bridge)
    assert len(bridge.calls) == 2


def test_an_exception_among_the_results_is_raised_in_its_turn() -> None:
    bridge = ScriptedReviewBridge(
        results={"interference": [BridgeOpenError("circuit open"), {"interferences": []}]}
    )

    with pytest.raises(BridgeOpenError):
        interference_call(bridge)
    assert interference_call(bridge) == {"interferences": []}


def test_it_records_every_calls_arguments_by_name() -> None:
    bridge = ScriptedReviewBridge(
        results={"interference": [{"interferences": []}], "capture": [{"capture": None}]}
    )

    interference_call(bridge)
    bridge.capture("YWJj", "iso")

    assert bridge.calls == [
        (
            "interference",
            {
                "component_ids": [],
                "configuration": "Default",
                "settings": dict(RECORDED_INTERFERENCE_SETTINGS),
                "truncate_after": None,
            },
        ),
        ("capture", {"persist_ref": "YWJj", "view": "iso", "scope_document": None, "note": ""}),
    ]


def test_a_callable_answer_is_called_with_the_arguments() -> None:
    bridge = ScriptedReviewBridge(
        results={"interference": [lambda args: {"configuration": args["configuration"]}]}
    )

    assert interference_call(bridge, "Assembled") == {"configuration": "Assembled"}


def test_without_interference_in_supports_it_has_no_interference_attribute() -> None:
    bridge = ScriptedReviewBridge(supports=("capture", "measure"))

    assert not hasattr(bridge, "interference")
    assert hasattr(bridge, "capture")


def test_a_call_that_starts_while_another_is_in_progress_is_refused() -> None:
    bridge = ScriptedReviewBridge(
        results={
            "interference": [lambda args: bridge.measure("YWJj", "Y2Rl")],
            "measure": [{"distance": None}],
        }
    )

    with pytest.raises(AssertionError, match="while"):
        interference_call(bridge)


def test_after_a_refused_reentry_the_bridge_is_free_again() -> None:
    bridge = ScriptedReviewBridge(
        results={
            "interference": [lambda args: bridge.measure("YWJj", "Y2Rl"), {"interferences": []}],
            "measure": [{"distance": None}],
        }
    )
    with pytest.raises(AssertionError):
        interference_call(bridge)

    assert interference_call(bridge) == {"interferences": []}


def test_it_behaves_like_a_client_for_the_runner() -> None:
    bridge = ScriptedReviewBridge()

    assert bridge.circuit_open is False
    assert bridge.last_error is None
    bridge.close()
    assert bridge.closed is True


# --- the rows it answers with ------------------------------------------------------------


def test_interference_row_validates_as_the_irs_interference_row() -> None:
    row = interference_row("int:0101", ("cmp:0002", "cmp:0003"), "cmp:0002|cmp:0003")

    parsed = Interference.model_validate(row)

    assert parsed.volume is None
    assert parsed.status == "computed"
    assert parsed.configuration == "Default"
    assert parsed.is_possible is False
    assert parsed.settings.model_dump() == RECORDED_INTERFERENCE_SETTINGS


def test_interference_row_carries_a_volume_and_its_options() -> None:
    row = interference_row(
        "int:0102",
        ("cmp:0004", "cmp:0005"),
        "cmp:0004|cmp:0005",
        volume_mm3=42.0,
        is_possible=True,
        status="truncated",
        configuration="Assembled",
    )

    parsed = Interference.model_validate(row)

    assert parsed.volume is not None and parsed.volume.value == 42.0
    assert parsed.volume.unit == "mm3"
    assert (parsed.is_possible, parsed.status, parsed.configuration) == (
        True,
        "truncated",
        "Assembled",
    )


def test_interference_row_can_carry_a_volume_in_cubic_metres() -> None:
    row = interference_row("int:0103", ("cmp:0004", "cmp:0005"), "g", volume_m3=2.5e-07)

    parsed = Interference.model_validate(row)

    assert parsed.volume is not None and parsed.volume.unit == "m3"


def test_interference_row_refuses_two_volumes() -> None:
    with pytest.raises(ValueError, match="one volume"):
        interference_row("int:0104", ("cmp:0004", "cmp:0005"), "g", 1.0, volume_m3=1e-9)


def test_the_volume_unit_gap_validates_as_the_irs_gap() -> None:
    gap = Gap.model_validate(VOLUME_UNIT_GAP)

    assert gap.entity_kind == "interference_volume_unit"


# --- through start_review ----------------------------------------------------------------


def test_start_review_accepts_it_through_the_bridge_factory(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    bridge = ScriptedReviewBridge(
        results={"interference": [{"interferences": ROWS, "gaps": [VOLUME_UNIT_GAP]}]}
    )
    arguments = {
        "component_ids": [],
        "configuration": "Default",
        "settings": dict(RECORDED_INTERFERENCE_SETTINGS),
    }
    provider = FakeProvider(
        script=[
            ScriptedTurn(
                text="done", tool_calls=(ScriptedToolCall("bridge_interference", arguments),)
            )
        ],
        model="fake-scripted",
    )

    run = start_review(
        package_dir,
        tmp_path / "out",
        provider=provider,
        bridge=True,
        bridge_factory=lambda pipe, secret: bridge,
    )
    session = run.start()
    run.close()

    [step] = session.steps
    assert (step.tool, step.status) == ("bridge_interference", "ok")
    assert [command for command, _ in bridge.calls] == ["interference"]
    assert bridge.closed is True
