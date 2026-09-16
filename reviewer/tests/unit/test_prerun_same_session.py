"""The pre-run is the same checks, not a second implementation of them (T075, lever 5).

The strongest statement this feature can make about lever 5 is that a review whose
deterministic checks ran before the first turn is **the same session** a review whose
model asked for those same checks produces. Everything else about the lever - the round
trips saved, the digest - is worth nothing if the two sessions differ, because then the
pre-run is a second copy of the check logic and the report has started lying about what
was evaluated.

The comparison is on `_verdict_key`, the runner's own answer to "are these two findings
two verdicts on the same thing", rather than on serialized finding lists: ids, timestamps
and step numbers are allowed to differ, verdicts are not.

The correctness point underneath it is that the pre-run calls the same tool functions
through the same `ToolDispatch`, so every pre-run check produces a real
`InvestigationStep`, real findings through `ToolContext.record_finding`, real coverage and
real `tool.started` / `tool.finished` events. A pre-run that bypassed the dispatch would
have to synthesize all four, and `Finding.tool_result_ids` would point at nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swreview.agent.providers.fake import ScriptedToolCall
from swreview.agent.runner import _verdict_key
from swreview.benchmark.scorecard import seconds_to_first_finding
from swreview.prerun import PRERUN_CHECK_PREFIX, planned_calls
from swreview.report.session import ReviewSession
from swreview.tools.context import context_for
from swreview.tools.registry import ToolRegistry
from tests.support.prerun import MODEL_DRIVEN_CALLS, OFF, ON, prerun_package, review


def verdicts(session: ReviewSession) -> list[str]:
    """Every finding as the runner's own verdict key, ordered so two runs compare."""
    return sorted(repr(_verdict_key(finding)) for finding in session.findings)


def checks_in(session: ReviewSession, bucket: str) -> list[str]:
    return sorted(item.check for item in getattr(session.coverage, bucket))


def events_path(tmp_path: Any, out: str) -> Path:
    return Path(tmp_path) / out / "events.jsonl"


def events_of(tmp_path: Any, out: str) -> list[dict[str, Any]]:
    lines = events_path(tmp_path, out).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def first_at(tmp_path: Any, out: str, event_type: str) -> int:
    """Where the first `event_type` sits in the stream; raises if the run never wrote one."""
    return next(
        index
        for index, event in enumerate(events_of(tmp_path, out))
        if event["type"] == event_type
    )


# --- the same session -------------------------------------------------------------------


def test_the_pre_run_produces_the_same_verdicts_as_a_model_driven_run(tmp_path: Any) -> None:
    pre = review(tmp_path, "prerun", efficiency=ON)
    driven = review(tmp_path, "driven", efficiency=OFF, calls=MODEL_DRIVEN_CALLS)

    assert verdicts(pre) == verdicts(driven)
    # Two empty lists are equal and prove nothing; this fixture must produce verdicts.
    assert pre.findings


def test_the_pre_run_closes_the_same_coverage_a_model_driven_run_closes(
    tmp_path: Any,
) -> None:
    """Including the `unresolved` bucket, which finalization rebuilds from the open
    checklist items: closing an item before the first turn closes it exactly as closing it
    during the turn does."""
    pre = review(tmp_path, "prerun", efficiency=ON)
    driven = review(tmp_path, "driven", efficiency=OFF, calls=MODEL_DRIVEN_CALLS)

    for bucket in ("checked", "unresolved", "failed", "out_of_scope"):
        assert checks_in(pre, bucket) == checks_in(driven, bucket), bucket

    digest_items = [
        check for check in checks_in(pre, "skipped") if check.startswith(PRERUN_CHECK_PREFIX)
    ]
    rest = [
        check
        for check in checks_in(pre, "skipped")
        if not check.startswith(PRERUN_CHECK_PREFIX)
    ]
    assert digest_items, "the digest's not-evaluated lines are written as coverage"
    assert rest == checks_in(driven, "skipped")


# --- real steps, real events, real provenance -------------------------------------------


def test_the_pre_run_records_one_real_investigation_step_per_call(tmp_path: Any) -> None:
    pre = review(tmp_path, "prerun", efficiency=ON)

    assert [step.tool for step in pre.steps] == [call.name for call in MODEL_DRIVEN_CALLS]
    assert [step.index for step in pre.steps] == list(range(len(MODEL_DRIVEN_CALLS)))
    assert all(step.status == "ok" for step in pre.steps)


def test_every_pre_run_finding_cites_a_step_of_this_session(tmp_path: Any) -> None:
    """`Finding.tool_result_ids` is the only evidence a check has when its verdict rests on
    what was shown rather than on arithmetic; a synthesized pre-run would cite nothing."""
    pre = review(tmp_path, "prerun", efficiency=ON)

    cited = [step_id for finding in pre.findings for step_id in finding.tool_result_ids]
    assert cited
    assert all(0 <= step_id < len(pre.steps) for step_id in cited)


def test_the_pane_sees_the_pre_run_happening(tmp_path: Any) -> None:
    review(tmp_path, "prerun", efficiency=ON)
    events = events_of(tmp_path, "prerun")

    started = [event for event in events if event["type"] == "tool.started"]
    finished = [event for event in events if event["type"] == "tool.finished"]
    assert [event["body"]["tool"] for event in started] == [
        call.name for call in MODEL_DRIVEN_CALLS
    ]
    assert [event["body"]["step_index"] for event in started] == list(
        range(len(MODEL_DRIVEN_CALLS))
    )
    assert len(finished) == len(MODEL_DRIVEN_CALLS)
    assert all(event["body"]["status"] == "ok" for event in finished)


def test_every_tool_started_step_index_identifies_the_step_it_produced(
    tmp_path: Any,
) -> None:
    """The pre-run's steps and the model's are one numbering, not two starting at 0.

    `tool.started.step_index` has identified an `InvestigationStep` in every run before
    this lever, and two readers join on it: the pane keys its tool cards on the number
    (`app.js`, `state.tools['s' + body.step_index]`) and `Finding.tool_result_ids` carries
    real session indices that the pane and `report/markdown.py` render against those
    cards. An adapter counter that restarted at 0 after the pre-run wrote four steps would
    point the model's first call at the pre-run's card and silently overwrite it.
    """
    pre = review(
        tmp_path,
        "prerun",
        efficiency=ON,
        calls=(ScriptedToolCall("get_review_checklist"),),
    )
    events = events_of(tmp_path, "prerun")
    started = [event["body"] for event in events if event["type"] == "tool.started"]
    finished = [event["body"] for event in events if event["type"] == "tool.finished"]

    # The scripted call is the model's, after the four the pre-run made.
    assert [step.tool for step in pre.steps] == [
        *(call.name for call in MODEL_DRIVEN_CALLS),
        "get_review_checklist",
    ]
    assert [body["step_index"] for body in started] == [step.index for step in pre.steps]
    assert [body["tool"] for body in started] == [step.tool for step in pre.steps]
    assert [body["step_index"] for body in finished] == [step.index for step in pre.steps]


# --- where the pre-run sits in the stream -----------------------------------------------


def test_the_stream_still_opens_with_session_started(tmp_path: Any) -> None:
    """The one implicit ordering rule `events.jsonl` has ever had.

    The pane's `app.js` opens a session on `case 'session.started'` and
    `benchmark/scorecard.py` times the first finding from its stamp; the pre-run runs
    during setup, so setup is what has to emit it.
    """
    review(tmp_path, "prerun", efficiency=ON)

    assert events_of(tmp_path, "prerun")[0]["type"] == "session.started"


def test_the_pre_run_moves_the_first_finding_ahead_of_the_first_round_trip(
    tmp_path: Any,
) -> None:
    """Lever 5's headline metric is wall clock to first finding (T078).

    `seconds_to_first_finding` counts a `finding` only after it has seen `session.started`,
    so a pre-run whose findings landed before that event would score `None`: the lever
    would turn its own headline column into `unknown` and the A/B row could not be read at
    all. Both arms must therefore be scorable.

    The saving itself is asserted as **ordering**, not as a duration: a scripted provider
    answers instantly, so two fake runs differ by Python import warm-up rather than by the
    round trips this lever removes, and a comparison of the two numbers would measure this
    machine. `usage` is emitted once per model round trip, so "the first finding arrives
    before the first round trip" says what lever 5 buys in a form a fake can prove.
    """
    review(tmp_path, "prerun", efficiency=ON)
    review(tmp_path, "driven", efficiency=OFF, calls=MODEL_DRIVEN_CALLS)

    assert seconds_to_first_finding(events_path(tmp_path, "prerun")) is not None
    assert seconds_to_first_finding(events_path(tmp_path, "driven")) is not None
    assert first_at(tmp_path, "prerun", "finding") < first_at(tmp_path, "prerun", "usage")
    assert first_at(tmp_path, "driven", "usage") < first_at(tmp_path, "driven", "finding")


def test_the_pre_run_asks_for_exactly_what_a_model_would_have_asked_for(
    tmp_path: Any,
) -> None:
    """The plan and the script are one list read twice: if they drift, the same-session
    comparison above would be comparing two different sets of calls and still pass."""
    context = context_for(prerun_package())
    dispatch = ToolRegistry().dispatch(context)

    assert planned_calls(context, dispatch) == tuple(
        (call.name, dict(call.arguments)) for call in MODEL_DRIVEN_CALLS
    )


# --- the flag off -----------------------------------------------------------------------


def test_the_flag_off_runs_nothing_at_all(tmp_path: Any) -> None:
    off = review(tmp_path, "off", efficiency=OFF)

    assert off.steps == []
    assert off.findings == []
    assert not [
        item
        for item in off.coverage.skipped
        if item.check.startswith(PRERUN_CHECK_PREFIX)
    ]
