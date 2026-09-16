"""The event stream, extracted from the review run so a remodel run can share it (T106).

`EventSink` stamps `seq` and `at`, appends one JSON line to `events.jsonl` and fans the
event out to its listeners. Feature 004's judgement phase needs exactly that and none of
`ReviewRun`'s review vocabulary (checklist, findings, evidence requests, coverage
buckets), so the sink **moves** to `swreview/agent/events.py` and both runs import it from
there. Copying it would give the two runs two stamping rules and, the first time one
changed, two `events.jsonl` dialects (plan.md Phase 1 point 8, research.md R1.2).

Three things are asserted here and nothing else is:

1. **Where the shared pieces live.** `EventSink`, its `EventListener` alias, the
   `UsageLedger` that rides on it, the `events.jsonl` file name, the per-turn step budget
   and the redactor hand-off are defined in `agent/events.py` - checked by `__module__` and
   by parsing `agent/runner.py`'s source, because an import alias left behind in the
   runner would satisfy a name check while the definition stayed put.

2. **That `agent/runner.py` re-exports the same objects.** Every existing importer -
   `chat/sessions.py`, `benchmark/scorecard.py`, `tests/unit/test_usage_ledger.py` -
   imports from `swreview.agent.runner` today and stays **unedited**, which is the whole
   regression proof. Identity, not equality: two classes with the same name would pass an
   equality check and fail every `isinstance` the chat server does.

3. **That the behavior did not change.** The stamping, the append and the fan-out are
   pinned here against the bytes the sink writes. The feature 001 and 002 goldens are the
   other half of that proof and are not touched by this feature.

`events.py` must not import `agent/runner.py`: the dependency runs one way, from the runs
to the shared stream, and a cycle would be the first sign that something review-shaped
followed the sink across.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.agent import events, runner
from swreview.agent.providers import AgentEvent, TokenUsage, usage_body
from swreview.report.session import (
    MAX_STEPS_CLOSEOUT,
    TRUNCATED_CLOSEOUT,
    cut_short_reason,
)

AT = datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
AT_JSON = "2025-03-04T05:06:07Z"
"""How the stamp is serialized on the wire: UTC with a `Z`, per the event contract."""

ROUND = TokenUsage(
    input_tokens=1_009,
    cached_input_tokens=101,
    cache_write_tokens=None,
    output_tokens=53,
    reasoning_tokens=11,
    tool_result_input_tokens=None,
    total_tokens=1_062,
    latency_s=0.5,
)
"""One round trip's cost, so the ledger has something to accumulate."""

SHARED = (
    "EventSink",
    "EventListener",
    "UsageLedger",
    "EVENTS_FILE_NAME",
    "no_redaction",
    "DEFAULT_MAX_STEPS",
    "emit_turn_failed",
)
"""What moves. Everything else in `agent/runner.py` is review-shaped and stays there."""

REVIEW_SHAPED = (
    "swreview.agent.checklist",
    "swreview.findings",
    "swreview.ir.models",
    "swreview.ir.loader",
    "swreview.tools.context",
)
"""Modules whose presence in `events.py` would mean a review concept came across with it.

`swreview.report.session` is deliberately not on this list and is deliberately not a blanket
allowance either: `UsageLedger` imports `SessionUsage` from it, because that class holds the
one summing rule for token counts and is not review-shaped despite its address. The test
below pins exactly which names may come from there, so `ReviewSession` or `CoverageItem`
following them across is a failure and not a judgement call.
"""

ALLOWED_FROM_SESSION = {"SessionUsage"}
"""The only names `events.py` may take from `report/session.py`. See `REVIEW_SHAPED`."""


def clock_of(*stamps: datetime):
    """A clock handing out `stamps` in order, so `at` is asserted and not merely typed."""
    remaining = list(stamps)
    return lambda: remaining.pop(0)


def source_of(module: ModuleType) -> str:
    assert module.__file__ is not None
    return Path(module.__file__).read_text(encoding="utf-8")


def defined_names(module: ModuleType) -> set[str]:
    """Every class, function and module-level assignment *defined* in a module's source.

    Parsed rather than read off the module object, because `from ... import X` puts `X` on
    the module object too and the question here is where the definition lives.
    """
    names: set[str] = set()
    for node in ast.parse(source_of(module)).body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def imported_modules(module: ModuleType) -> set[str]:
    return {
        node.module
        for node in ast.walk(ast.parse(source_of(module)))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


# --- 1. the extraction ------------------------------------------------------------------


@pytest.mark.parametrize("name", SHARED)
def test_the_shared_pieces_are_defined_in_agent_events(name: str) -> None:
    assert name in defined_names(events), f"{name} is not defined in agent/events.py"


@pytest.mark.parametrize("name", SHARED)
def test_the_runner_no_longer_defines_them(name: str) -> None:
    assert name not in defined_names(runner), (
        f"{name} is still defined in agent/runner.py; it was copied, not extracted"
    )


@pytest.mark.parametrize("name", SHARED)
def test_the_runner_re_exports_the_same_object(name: str) -> None:
    """Identity, so every unedited `from swreview.agent.runner import ...` still works."""
    assert getattr(runner, name) is getattr(events, name)


def test_the_sink_and_the_ledger_report_agent_events_as_their_home() -> None:
    assert events.EventSink.__module__ == "swreview.agent.events"
    assert events.UsageLedger.__module__ == "swreview.agent.events"


def test_events_does_not_import_the_review_runner() -> None:
    """One direction only: the runs depend on the stream, never the stream on a run."""
    assert "swreview.agent.runner" not in imported_modules(events)


@pytest.mark.parametrize("module", REVIEW_SHAPED)
def test_events_imports_nothing_review_shaped(module: str) -> None:
    """Checklist, findings, IR and the tool layer stay behind with `ReviewRun`."""
    assert module not in imported_modules(events)


def test_only_the_summing_rule_crosses_over_from_report_session() -> None:
    """`SessionUsage` is shared arithmetic; `ReviewSession` is a review and must not be."""
    taken = {
        alias.name
        for node in ast.walk(ast.parse(source_of(events)))
        if isinstance(node, ast.ImportFrom) and node.module == "swreview.report.session"
        for alias in node.names
    }
    assert taken <= ALLOWED_FROM_SESSION, f"review-shaped names followed the sink: {taken}"


# --- 2. the stamping, the append and the fan-out ----------------------------------------


def test_seq_starts_at_one_and_is_monotonic_per_session(tmp_path: Path) -> None:
    sink = events.EventSink(tmp_path / "events.jsonl")
    assert sink.seq == 0
    first = sink.emit("session.started", {"a": 1})
    second = sink.emit("turn.ended", {"reason": "end"})
    assert (first.seq, second.seq) == (1, 2)
    assert sink.seq == 2


def test_at_comes_from_the_injected_clock(tmp_path: Path) -> None:
    later = datetime(2025, 3, 4, 5, 6, 8, tzinfo=UTC)
    sink = events.EventSink(tmp_path / "events.jsonl", clock=clock_of(AT, later))
    assert sink.emit("session.started", {}).at == AT
    assert sink.emit("turn.ended", {"reason": "end"}).at == later


def test_every_event_is_one_appended_json_line(tmp_path: Path) -> None:
    path = tmp_path / "nested" / events.EVENTS_FILE_NAME
    sink = events.EventSink(path, clock=clock_of(AT, AT))
    sink.emit("session.started", {"package": "p"})
    sink.emit("turn.ended", {"reason": "end"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {
            "seq": 1,
            "at": AT_JSON,
            "type": "session.started",
            "body": {"package": "p"},
        },
        {
            "seq": 2,
            "at": AT_JSON,
            "type": "turn.ended",
            "body": {"reason": "end"},
        },
    ]


def test_a_second_sink_on_the_same_file_appends_rather_than_truncates(tmp_path: Path) -> None:
    """The pane's resumed chat opens its own sink on a run folder that already has one."""
    path = tmp_path / events.EVENTS_FILE_NAME
    events.EventSink(path).emit("session.started", {})
    events.EventSink(path).emit("turn.ended", {"reason": "end"})
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_a_sink_with_no_path_writes_nothing_and_still_fans_out(tmp_path: Path) -> None:
    seen: list[AgentEvent] = []
    sink = events.EventSink(None, listeners=[seen.append])
    sink.emit("session.started", {})
    assert [event.seq for event in seen] == [1]
    assert list(tmp_path.iterdir()) == []


def test_listeners_are_called_in_order_with_the_stamped_event(tmp_path: Path) -> None:
    order: list[str] = []
    sink = events.EventSink(
        tmp_path / "events.jsonl",
        listeners=[
            lambda event: order.append(f"a{event.seq}"),
            lambda event: order.append(f"b{event.seq}"),
        ],
    )
    sink.emit("session.started", {})
    assert order == ["a1", "b1"]


def test_add_listener_attaches_after_construction(tmp_path: Path) -> None:
    """`ReviewRun` puts its ledger on a sink `start_review` built; so will a remodel run."""
    seen: list[AgentEvent] = []
    sink = events.EventSink(tmp_path / "events.jsonl")
    sink.emit("session.started", {})
    sink.add_listener(seen.append)
    sink.emit("turn.ended", {"reason": "end"})
    assert [event.seq for event in seen] == [2]


def test_the_body_is_copied_so_a_later_mutation_cannot_rewrite_the_stream(
    tmp_path: Path,
) -> None:
    body: dict[str, Any] = {"reason": "end"}
    sink = events.EventSink(tmp_path / "events.jsonl")
    event = sink.emit("turn.ended", body)
    body["reason"] = "error"
    assert event.body == {"reason": "end"}


# --- 3. the pieces that ride with it ----------------------------------------------------


def test_no_redaction_is_the_identity_hand_off() -> None:
    """A keyless run takes the same code path as a real one, not a branch nobody runs."""
    assert events.no_redaction("sk-live-0000 in the message") == "sk-live-0000 in the message"


def test_the_per_turn_step_budget_is_the_shared_default() -> None:
    assert events.DEFAULT_MAX_STEPS == 200


def test_emit_error_reports_one_failure_in_the_contract_s_shape(tmp_path: Path) -> None:
    """The `error_body` shape, the redactor, and no `turn.ended`: nothing ended here.

    A failure that happens *before* a turn exists - a provider that could not be built -
    has no turn to close, and announcing one would put a turn on the stream that never
    ran.
    """
    seen: list[AgentEvent] = []
    sink = events.EventSink(tmp_path / "events.jsonl", listeners=[seen.append], clock=clock_of(AT))
    message = events.emit_error(
        sink,
        RuntimeError("sk-live-0000 was refused"),
        lambda text: text.replace("sk-live-0000", "***"),
    )
    assert message == "*** was refused"
    assert [event.type for event in seen] == ["error"]
    assert seen[0].body == {
        "error_class": "RuntimeError",
        "message": "*** was refused",
        "retryable": True,
    }


def test_emit_turn_failed_reports_the_error_then_ends_the_turn(tmp_path: Path) -> None:
    """The two events both runs emit when a turn raises, in the one order they emit them."""
    seen: list[AgentEvent] = []
    sink = events.EventSink(
        tmp_path / "events.jsonl", listeners=[seen.append], clock=clock_of(AT, AT)
    )
    message = events.emit_turn_failed(sink, ValueError("the provider fell over"))
    assert message == "the provider fell over"
    assert [event.type for event in seen] == ["error", "turn.ended"]
    assert seen[0].body["error_class"] == "ValueError"
    assert seen[1].body == {"reason": "error"}


def test_the_cut_short_sentences_are_one_mapping_both_runs_read() -> None:
    """T106: the `TurnEndReason` handling is shared, not restated once per run.

    It lives beside its two constants in `report/session.py` rather than here, because
    `was_cut_short` reads the same sentences back and `events.py` may take nothing but the
    summing rule from that module (see `ALLOWED_FROM_SESSION`).
    """
    assert cut_short_reason("max_steps", 200) == MAX_STEPS_CLOSEOUT.format(max_steps=200)
    assert cut_short_reason("truncated", 200) == TRUNCATED_CLOSEOUT
    assert cut_short_reason("end", 200) is None
    assert cut_short_reason("error", 200) is None
    assert cut_short_reason("stopped", 200) is None


@pytest.mark.parametrize("module", ("swreview.agent.runner", "swreview.remodel.runner"))
def test_neither_run_restates_the_cut_short_sentences(module: str) -> None:
    """Both call the mapping; neither spells `max_steps` into a sentence of its own."""
    source = source_of(import_module(module))
    assert "cut_short_reason" in source
    assert "MAX_STEPS_CLOSEOUT" not in source
    assert "TRUNCATED_CLOSEOUT" not in source


def test_the_ledger_is_an_event_sink_listener(tmp_path: Path) -> None:
    """Wiring only; the arithmetic is pinned in `test_usage_ledger.py`, which is unedited."""
    ledger = events.UsageLedger()
    assert ledger.usage() is None
    sink = events.EventSink(tmp_path / "events.jsonl", listeners=[ledger])
    sink.emit("usage", usage_body(ROUND, round_index=0, provider="fake", model="fake-1"))
    sink.emit("turn.ended", {"reason": "end"})
    usage = ledger.usage()
    assert usage is not None
    assert usage.rounds == 1
