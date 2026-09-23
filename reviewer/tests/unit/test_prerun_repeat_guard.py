"""A model that asks for a check the pre-run already ran is answered, never re-run
(feature 008 T043, FR-012, `contracts/checks-first.md` section 5).

The digest tells the model which checks already ran; a model may still ask. A second
`check_rms_part` over a graded document appends a second finding per condition, so a
repeat must be caught - including one narrowed to a `document_id` - and answered with the
recorded outcome: one real step (the pane's tool card and `tool.started.step_index` stay
aligned with the session), no finding, no coverage, and for a folded family counts only.
A call the pre-run did not make - other settings, a component subset, another
configuration, or a call whose pre-run attempt failed - runs as it always did.

Feature 010's three argument-free checks (`check_joints`, `check_mass_material`,
`check_hygiene`) are guarded the same way (010 T092, its `contracts/code-first.md` section
5): each records findings - a joint's alignment, a part's density, an unresolved component -
so a repeat would record every one of them a second time. They are keyed by name alone,
through `CODE_FIRST_CHECKS`, the one registration point, and never through a second list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.ir.loader import load_package, save_package
from swreview.prerun import (
    ALREADY_RUN,
    LIVE_INTERFERENCE_TOOL,
    PRERUN_INTERFERENCE_SETTINGS,
    REPEAT_NOTE,
    PrerunCall,
    PrerunGuard,
    PrerunResult,
    repeat_key,
)
from swreview.tools import checks_mechanical
from swreview.tools.context import build_context
from swreview.tools.model_view import check_digest
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME, ToolDispatch, ToolRegistry
from tests.support.prerun import (
    CHECKS_FIRST,
    GROUP_KEY,
    LIVE_OVERLAP_KEY,
    LIVE_ROWS,
    PART_DOCUMENT,
    live_prerun_package,
    prerun_package,
)
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge

FINDING_ID = re.compile(r"\bF-\d+\b")


def played(
    tmp_path: Path,
    calls: tuple[ScriptedToolCall, ...],
    *,
    package: Any = None,
    bridge: Any = None,
    events: list[tuple[str, dict[str, Any]]] | None = None,
    **options: Any,
) -> ReviewRun:
    folder = tmp_path / "run"
    save_package(package if package is not None else prerun_package(), folder)
    collected = events if events is not None else []
    if bridge is not None:
        options.update(bridge=True, bridge_factory=lambda pipe, secret: bridge)
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[ScriptedTurn(text="done", tool_calls=calls)], model="fake-scripted"
        ),
        callbacks=[lambda event: collected.append((event.type, dict(event.body)))],
        **options,
    )
    run.start()
    return run


def prerun_step(run: ReviewRun, tool: str) -> int:
    return next(step.index for step in run.session.steps if step.tool == tool)


def model_steps(run: ReviewRun, count: int) -> list[Any]:
    return run.session.steps[-count:]


# --- RMS: counts only, whatever the document ----------------------------------------------


def test_a_repeated_rms_part_call_is_answered_with_counts_and_records_one_step(
    tmp_path: Path,
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    run = played(
        tmp_path,
        (
            ScriptedToolCall("check_rms_part"),
            ScriptedToolCall("check_rms_part", {"document_id": PART_DOCUMENT}),
        ),
        efficiency=CHECKS_FIRST,
        events=events,
    )
    session = run.session
    ran_at = prerun_step(run, "check_rms_part")
    findings_after_prerun = len(session.findings)

    first, second = model_steps(run, 2)
    for step in (first, second):
        assert step.tool == "check_rms_part"
        assert step.status == "ok"
        assert '"status":"already_run"' in step.result_summary
        assert f'"ran_at_step":{ran_at}' in step.result_summary
    guarded = [
        body
        for kind, body in events
        if kind == "tool.finished" and body["step_index"] in (first.index, second.index)
    ]
    assert len(guarded) == 2
    assert len(session.findings) == findings_after_prerun
    finding_events = [body for kind, body in events if kind == "finding"]
    assert len(finding_events) == findings_after_prerun


def test_the_rms_answer_names_the_step_and_carries_no_finding_id(tmp_path: Path) -> None:
    run = played(tmp_path, (), efficiency=CHECKS_FIRST)
    guard = run.tools
    assert isinstance(guard, PrerunGuard)

    result = guard.call("check_rms_part", {"document_id": PART_DOCUMENT})

    assert result.is_error is False
    assert result.payload["status"] == ALREADY_RUN
    assert result.payload["ran_at_step"] == prerun_step(run, "check_rms_part")
    assert result.payload["note"] == REPEAT_NOTE
    outcome = result.payload["outcome"]
    assert outcome["findings"] >= 1
    assert "rows" not in outcome and "finding_ids" not in outcome
    assert not FINDING_ID.search(str(result.payload))


# --- interference: the finding named ------------------------------------------------------


def test_a_repeated_group_call_is_answered_with_that_calls_finding(tmp_path: Path) -> None:
    run = played(tmp_path, (), efficiency=CHECKS_FIRST)
    [finding] = [f for f in run.session.findings if f.check == "interference.static"]
    before = len(run.session.findings)

    result = run.tools.call("check_interference_group", {"group_key": GROUP_KEY})

    assert result.payload["status"] == ALREADY_RUN
    assert result.payload["outcome"]["finding_ids"] == [finding.id]
    assert len(run.session.findings) == before


def test_another_group_key_is_not_caught(tmp_path: Path) -> None:
    run = played(tmp_path, (), efficiency=CHECKS_FIRST)

    result = run.tools.call("check_interference_group", {"group_key": "not-a-group"})

    assert result.is_error
    assert "already_run" not in str(result.payload)


# --- the live call ------------------------------------------------------------------------


def live_bridge(answers: int) -> ScriptedReviewBridge:
    answer = {"interferences": [dict(row) for row in LIVE_ROWS], "gaps": [dict(VOLUME_UNIT_GAP)]}
    return ScriptedReviewBridge(results={"interference": [answer] * answers})


def test_the_live_call_repeated_exactly_makes_no_second_bridge_call(tmp_path: Path) -> None:
    bridge = live_bridge(1)
    run = played(
        tmp_path, (), package=live_prerun_package(), bridge=bridge, efficiency=CHECKS_FIRST
    )

    result = run.tools.call(
        LIVE_INTERFERENCE_TOOL,
        {
            "component_ids": [],
            "configuration": "Default",
            "settings": dict(reversed(list(PRERUN_INTERFERENCE_SETTINGS.items()))),
        },
    )

    assert result.payload["status"] == ALREADY_RUN
    assert result.payload["outcome"] == {
        "groups": 2,
        "rows": 2,
        "configuration": "Default",
        "settings": PRERUN_INTERFERENCE_SETTINGS,
    }
    assert sum(1 for name, _ in bridge.calls if name == "interference") == 1


def test_other_settings_or_a_subset_reach_the_bridge(tmp_path: Path) -> None:
    bridge = live_bridge(3)
    run = played(
        tmp_path, (), package=live_prerun_package(), bridge=bridge, efficiency=CHECKS_FIRST
    )
    other = {**PRERUN_INTERFERENCE_SETTINGS, "ignore_hidden": True}
    component = load_package(tmp_path / "run").package.components[0].id

    run.tools.call(
        LIVE_INTERFERENCE_TOOL,
        {"component_ids": [], "configuration": "Default", "settings": other},
    )
    run.tools.call(
        LIVE_INTERFERENCE_TOOL,
        {
            "component_ids": [component],
            "configuration": "Default",
            "settings": PRERUN_INTERFERENCE_SETTINGS,
        },
    )

    assert sum(1 for name, _ in bridge.calls if name == "interference") == 3


# --- a pre-run call that failed is not in the ledger --------------------------------------


def test_a_forced_failure_in_the_pre_run_is_not_answered_from_the_ledger(tmp_path: Path) -> None:
    run = played(
        tmp_path,
        (ScriptedToolCall("check_rms_part"),),
        efficiency=CHECKS_FIRST,
        fail_tool=["check_rms_part"],
    )

    model_step = run.session.steps[-1]
    assert model_step.tool == "check_rms_part"
    assert model_step.status == "error"
    assert "already_run" not in model_step.result_summary


def test_a_call_whose_pre_run_attempt_failed_runs_and_records_findings(tmp_path: Path) -> None:
    """The guard's own rule, without a forced failure on the tool: a ledger built from a
    pre-run whose `check_rms_part` failed lets the model's call through to the tool."""
    folder = tmp_path / "package"
    save_package(prerun_package(), folder)
    context = build_context(load_package(folder))
    dispatch = ToolRegistry().dispatch(context)
    failed = PrerunCall(
        tool="check_rms_part", arguments={}, step_index=0, findings=(), error="it broke"
    )
    guard = PrerunGuard(dispatch, PrerunResult(calls=(failed,), not_evaluated=()), folded=())

    result = guard.call("check_rms_part", {})

    assert result.payload["status"] == "recorded"
    assert context.session is not None and context.session.findings


# --- the steps line up, and the guard exists only under checks first -----------------------


def test_every_guarded_steps_started_index_is_its_session_index(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    run = played(
        tmp_path,
        (
            ScriptedToolCall("check_rms_assembly"),
            ScriptedToolCall("check_interference_group", {"group_key": GROUP_KEY}),
            ScriptedToolCall("get_package_summary"),
        ),
        efficiency=CHECKS_FIRST,
        events=events,
    )

    started = [body for kind, body in events if kind == "tool.started"]
    finished = [body for kind, body in events if kind == "tool.finished"]
    for body in started:
        step = run.session.steps[body["step_index"]]
        assert step.tool == body["tool"]
    assert [body["step_index"] for body in finished] == [s.index for s in run.session.steps]


def test_with_checks_first_off_the_run_hands_over_the_dispatch_itself(tmp_path: Path) -> None:
    run = played(tmp_path, ())

    assert isinstance(run.tools, ToolDispatch)


def test_repeat_key_catches_a_document_subset_and_nothing_else() -> None:
    assert repeat_key("check_rms_part", {}) == repeat_key(
        "check_rms_part", {"document_id": "doc:3"}
    )
    assert repeat_key("check_rms_equations", {"document_id": "doc:3"}) == (
        "check_rms_equations",
    )
    assert repeat_key("check_interference_group", {"group_key": "a"}) != repeat_key(
        "check_interference_group", {"group_key": "b"}
    )
    assert repeat_key(LIVE_INTERFERENCE_TOOL, {"component_ids": ["cmp:0002"]}) is None
    assert repeat_key("get_package_summary", {}) is None
    assert repeat_key("check_interference_group", {}) is None
    assert repeat_key(LIVE_OVERLAP_KEY, {}) is None


# --- feature 010: the three argument-free checks (010 T092) ------------------------------

MECHANICAL_CHECKS = ("check_joints", "check_mass_material", "check_hygiene")
"""Named here rather than read from `CODE_FIRST_CHECKS`: the test says which three tools
the guard must catch, and the tuple-driven test below says how it catches them."""

MECHANICAL_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "mechanical" / "small-assembly"
)
"""Feature 010's small fixture, on which each of the three records at least one finding in
the pre-run (a pin joint's alignment, two densities, an unresolved component), so "the
repeat recorded no finding" says something."""


def mechanical_package() -> Any:
    return load_package(MECHANICAL_FIXTURE).package


def stored_payload(run: ReviewRun, step: int) -> dict[str, Any]:
    """A step's full result as the run stored it (`tool-results/step-<n>.json`, 008 SC-008)."""
    path = Path(run.session_path).parent / TOOL_RESULTS_DIR_NAME / f"step-{step}.json"
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


@pytest.mark.parametrize("tool", MECHANICAL_CHECKS)
def test_repeat_key_keys_each_mechanical_check_by_its_name_alone(tool: str) -> None:
    """They take no argument, so any argument a model adds is noise: the same question."""
    assert repeat_key(tool, {}) == (tool,)
    assert repeat_key(tool, {"document_id": PART_DOCUMENT}) == (tool,)


def test_the_guard_keys_whatever_code_first_checks_names_when_it_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One mechanism (010 notes): a check joins the guard by joining `CODE_FIRST_CHECKS`,
    and leaves it by leaving the tuple - no per-tool list to keep in step with it."""
    monkeypatch.setattr(checks_mechanical, "CODE_FIRST_CHECKS", ("check_joints", "check_later"))

    assert repeat_key("check_later", {}) == ("check_later",)
    assert repeat_key("check_joints", {}) == ("check_joints",)
    assert repeat_key("check_mass_material", {}) is None
    assert repeat_key("check_hygiene", {}) is None


@pytest.mark.parametrize("tool", MECHANICAL_CHECKS)
def test_a_repeated_mechanical_check_records_one_step_each_and_no_finding(
    tmp_path: Path, tool: str
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    run = played(
        tmp_path,
        (ScriptedToolCall(tool), ScriptedToolCall(tool)),
        package=mechanical_package(),
        efficiency=CHECKS_FIRST,
        events=events,
    )
    session = run.session
    ran_at = prerun_step(run, tool)
    recorded = [finding for finding in session.findings if ran_at in finding.tool_result_ids]
    assert recorded, f"the fixture gives {tool} nothing to record, so the test proves nothing"

    first, second = model_steps(run, 2)
    for step in (first, second):
        assert (step.tool, step.status) == (tool, "ok")
        assert '"status":"already_run"' in step.result_summary
        assert f'"ran_at_step":{ran_at}' in step.result_summary
        assert not [f for f in session.findings if step.index in f.tool_result_ids]
    finished = [
        body["step_index"]
        for kind, body in events
        if kind == "tool.finished" and body["step_index"] in (first.index, second.index)
    ]
    assert finished == [first.index, second.index]
    finding_events = [body for kind, body in events if kind == "finding"]
    assert len(finding_events) == len(session.findings)


@pytest.mark.parametrize("tool", MECHANICAL_CHECKS)
def test_the_mechanical_answer_is_the_digest_of_the_recorded_result(
    tmp_path: Path, tool: str
) -> None:
    """`outcome` is `check_digest` of the pre-run call's own payload, unfolded: these three
    return counts and ids, and no family of theirs is folded (008 FR-014)."""
    run = played(tmp_path, (), package=mechanical_package(), efficiency=CHECKS_FIRST)
    session = run.session
    ran_at = prerun_step(run, tool)
    recorded = stored_payload(run, ran_at)
    before = (len(session.findings), len(session.contacts), session.coverage.model_dump())

    result = run.tools.call(tool, {})

    assert result.is_error is False
    assert result.payload["status"] == ALREADY_RUN
    assert result.payload["ran_at_step"] == ran_at
    assert result.payload["note"] == REPEAT_NOTE
    assert result.payload["outcome"] == check_digest(recorded)
    assert result.payload["outcome"]["finding_ids"] == [
        finding.id for finding in session.findings if ran_at in finding.tool_result_ids
    ]
    assert (len(session.findings), len(session.contacts), session.coverage.model_dump()) == (
        before
    )
    assert session.steps[-1].tool == tool


@pytest.mark.parametrize("tool", MECHANICAL_CHECKS)
def test_a_mechanical_check_whose_pre_run_call_was_forced_to_fail_is_not_answered(
    tmp_path: Path, tool: str
) -> None:
    run = played(
        tmp_path,
        (ScriptedToolCall(tool),),
        package=mechanical_package(),
        efficiency=CHECKS_FIRST,
        fail_tool=[tool],
    )

    model_step = run.session.steps[-1]
    assert (model_step.tool, model_step.status) == (tool, "error")
    assert "already_run" not in model_step.result_summary


@pytest.mark.parametrize("tool", MECHANICAL_CHECKS)
def test_a_mechanical_check_whose_pre_run_attempt_failed_runs_and_records_findings(
    tmp_path: Path, tool: str
) -> None:
    """The guard's own rule without a forced failure on the tool: a failed ledger entry
    lets the model's call through to the tool, which records what it finds."""
    folder = tmp_path / "package"
    save_package(mechanical_package(), folder)
    context = build_context(load_package(folder))
    dispatch = ToolRegistry().dispatch(context)
    failed = PrerunCall(tool=tool, arguments={}, step_index=0, findings=(), error="it broke")
    guard = PrerunGuard(dispatch, PrerunResult(calls=(failed,), not_evaluated=()), folded=())

    result = guard.call(tool, {})

    assert result.payload["status"] == "recorded"
    assert result.payload["findings"] >= 1
    assert context.session is not None and context.session.findings
