"""The one stored-result reader, `tools.registry.read_stored_result` (T014, for T015).

Every recorded step of a review keeps its full result in `tool-results/step-<index>.json`,
written by `SessionSink._store` (feature 008, FR-021); this is the one reader beside that one
writer (plan decision RF-30), which the replay, the questions reader and the report call. What
it promises is pinned here, as `questions.md` 9 lists it for this file:

1. **A file `_store` wrote reads back** as `StoredResult`: its payload, its status and the
   file's raw text, written through a real registry call with `tool_results_dir` set.
2. **Anything else is `Unstored`, naming why**: `missing`; `unreadable` (not JSON, nested too
   deep to parse, not an object, a payload that is not an object, a status that is not a
   string); `other_session` (another `session_id`, a stale file from an earlier review in a
   reused folder); `other_call` (another step; another tool or other arguments, when given).
3. **The replay's classification is unchanged**: `benchmark/replay._stored_result` calls the
   reader once per call it classifies, with the recorded session's id and the call's step, tool
   and arguments, and a call is `stored` exactly when the reader found its result and
   `estimated` on any `Unstored`, for every spoil the replay's own tests make
   (`test_replay_accounting.py`), another step, a deleted file, and a recording made before
   feature 008.

The questions reader's spy and the structural "no other reader of `tool-results/` under
`benchmark/`" land with the questions reader (T081), the report's spy with the report (T165).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from swreview.benchmark import replay as replay_module
from swreview.benchmark.recording import RecordedCall, read_recording
from swreview.benchmark.replay import TurnPlan, replay
from swreview.ir.loader import save_package
from swreview.report.session import InvestigationStep
from swreview.tools import registry
from swreview.tools.context import ToolContext, context_for
from swreview.tools.registry import (
    TOOL_RESULTS_DIR_NAME,
    StoredResult,
    ToolRegistry,
    Unstored,
    read_stored_result,
)
from tests.support.prerun import FIRST_INSTANCE, SECOND_INSTANCE, prerun_package
from tests.support.replay import ALL_OFF, record_scripted_review, without_stored_results
from tests.unit.test_replay_accounting import COMPONENTS, LIVE, stored_file, with_bridge

Envelope = dict[str, Any]


def storing_context(run_dir: Path) -> ToolContext:
    """A review context whose every call `_store` writes under `run_dir`, as `start_review` sets
    it (`agent/runner.py:1607`)."""
    context = context_for(prerun_package())
    context.tool_results_dir = run_dir / TOOL_RESULTS_DIR_NAME
    return context


def called(context: ToolContext, tool: str, arguments: Mapping[str, Any]) -> InvestigationStep:
    """Call `tool` through the real dispatch and return the step it recorded."""
    ToolRegistry().dispatch(context).call(tool, arguments)
    return context.require_session().steps[-1]


def rewrite_envelope(path: Path, change: Callable[[Envelope], None]) -> None:
    """Rewrite the envelope in `path` through `change`, which mutates the parsed JSON."""
    envelope = json.loads(path.read_text(encoding="utf-8"))
    change(envelope)
    path.write_text(json.dumps(envelope), encoding="utf-8")


@pytest.fixture
def component_step(tmp_path: Path) -> tuple[UUID, InvestigationStep]:
    """One ok `get_component` call stored in `tmp_path`, and the session that recorded it."""
    context = storing_context(tmp_path)
    step = called(context, "get_component", {"component_id": FIRST_INSTANCE})
    return context.require_session().session_id, step


# --- 1. a file `_store` wrote reads back --------------------------------------------------


def test_a_result_store_wrote_reads_back_with_its_payload_status_and_raw_text(
    tmp_path: Path,
) -> None:
    context = storing_context(tmp_path)
    result = ToolRegistry().dispatch(context).call(
        "get_component", {"component_id": FIRST_INSTANCE}
    )
    session = context.require_session()
    [step] = session.steps
    path = stored_file(tmp_path, step.index)

    stored = read_stored_result(
        tmp_path, session.session_id, step.index, tool=step.tool, arguments=step.arguments
    )

    assert stored == StoredResult(
        payload=result.payload, status="ok", text=path.read_bytes().decode("utf-8")
    )
    assert read_stored_result(tmp_path, session.session_id, step.index) == stored, (
        "without a tool and arguments (the report's call) only the session and step are checked"
    )


def test_an_error_result_reads_back_with_its_error_status(tmp_path: Path) -> None:
    context = storing_context(tmp_path)
    step = called(context, "get_component", {"component_id": "cmp:9999"})

    stored = read_stored_result(
        tmp_path,
        context.require_session().session_id,
        step.index,
        tool=step.tool,
        arguments=step.arguments,
    )

    assert isinstance(stored, StoredResult)
    assert stored.status == "error"
    assert "cmp:9999" in stored.payload["error"]


# --- 2. anything else is `Unstored`, naming why ---------------------------------------------


def test_a_step_with_no_stored_file_is_missing(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep]
) -> None:
    session_id, step = component_step

    assert read_stored_result(tmp_path, session_id, step.index + 1) == Unstored("missing")
    assert read_stored_result(tmp_path / "before-008", session_id, 0) == Unstored("missing"), (
        "a session recorded before feature 008 has no tool-results folder at all"
    )


@pytest.mark.parametrize(
    "damage",
    [
        "not JSON",
        "not UTF-8",
        "not an object",
        "a payload that is not an object",
        "no payload",
        "no status",
        "a status that is not a string",
        "a folder in the file's place",
    ],
)
def test_a_stored_file_that_is_no_envelope_is_unreadable(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep], damage: str
) -> None:
    session_id, step = component_step
    path = stored_file(tmp_path, step.index)
    if damage == "not JSON":
        path.write_text("{not json", encoding="utf-8")
    elif damage == "not UTF-8":
        path.write_bytes(b'{"step": "\xff"}')
    elif damage == "not an object":
        envelope = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps([envelope]), encoding="utf-8")
    elif damage == "a payload that is not an object":
        rewrite_envelope(path, lambda envelope: envelope.update(payload=["not", "an", "object"]))
    elif damage == "no payload":
        rewrite_envelope(path, lambda envelope: envelope.pop("payload"))
    elif damage == "no status":
        rewrite_envelope(path, lambda envelope: envelope.pop("status"))
    elif damage == "a status that is not a string":
        rewrite_envelope(path, lambda envelope: envelope.update(status=["ok"]))
    else:
        path.unlink()
        path.mkdir()

    assert read_stored_result(
        tmp_path, session_id, step.index, tool=step.tool, arguments=step.arguments
    ) == Unstored("unreadable")


def test_a_stored_file_nested_too_deep_to_parse_is_unreadable(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep]
) -> None:
    """`json.loads` raises `RecursionError`, not a `ValueError`, past the interpreter's nesting
    limit. The file is this call's envelope in every other respect, its payload nested that
    deep, so only the parse refuses it."""
    session_id, step = component_step
    path = stored_file(tmp_path, step.index)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"] = {"deep": None}
    nested = "[" * 100_000 + "]" * 100_000
    text = json.dumps(envelope).replace('{"deep": null}', '{"deep": ' + nested + "}")
    assert nested in text
    with pytest.raises(RecursionError):
        json.loads(text)
    path.write_text(text, encoding="utf-8")

    assert read_stored_result(
        tmp_path, session_id, step.index, tool=step.tool, arguments=step.arguments
    ) == Unstored("unreadable")


def test_a_stored_file_from_another_session_is_other_session(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep]
) -> None:
    session_id, step = component_step
    rewrite_envelope(stored_file(tmp_path, step.index), lambda e: e.update(session_id=str(uuid4())))

    assert read_stored_result(
        tmp_path, session_id, step.index, tool=step.tool, arguments=step.arguments
    ) == Unstored("other_session")
    assert read_stored_result(tmp_path, session_id, step.index) == Unstored("other_session")


def test_a_stale_file_names_the_other_session_whatever_call_it_was(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep]
) -> None:
    """A stale file from an earlier review is usually another call at the same index too; what
    it is, first, is another session's (the report says "a stale result from another session")."""
    session_id, step = component_step
    rewrite_envelope(
        stored_file(tmp_path, step.index),
        lambda e: e.update(session_id=str(uuid4()), tool="list_components", arguments={}),
    )

    assert read_stored_result(
        tmp_path, session_id, step.index, tool=step.tool, arguments=step.arguments
    ) == Unstored("other_session")


def test_a_stored_file_naming_another_step_is_other_call(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep]
) -> None:
    session_id, step = component_step
    rewrite_envelope(stored_file(tmp_path, step.index), lambda e: e.update(step=step.index + 1))

    assert read_stored_result(
        tmp_path, session_id, step.index, tool=step.tool, arguments=step.arguments
    ) == Unstored("other_call")
    assert read_stored_result(tmp_path, session_id, step.index) == Unstored("other_call"), (
        "the step is checked whether or not a tool and arguments are given"
    )


def test_a_stored_file_naming_another_tool_is_other_call_when_a_tool_is_given(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep]
) -> None:
    session_id, step = component_step
    rewrite_envelope(stored_file(tmp_path, step.index), lambda e: e.update(tool="list_components"))

    assert read_stored_result(
        tmp_path, session_id, step.index, tool=step.tool, arguments=step.arguments
    ) == Unstored("other_call")
    assert isinstance(
        read_stored_result(tmp_path, session_id, step.index, arguments=step.arguments),
        StoredResult,
    ), "with no tool given, the tool is not checked"


def test_a_stored_file_with_other_arguments_is_other_call_when_arguments_are_given(
    tmp_path: Path, component_step: tuple[UUID, InvestigationStep]
) -> None:
    session_id, step = component_step
    rewrite_envelope(
        stored_file(tmp_path, step.index),
        lambda e: e.update(arguments={"component_id": SECOND_INSTANCE}),
    )

    assert read_stored_result(
        tmp_path, session_id, step.index, tool=step.tool, arguments=step.arguments
    ) == Unstored("other_call")
    assert isinstance(
        read_stored_result(tmp_path, session_id, step.index, tool=step.tool), StoredResult
    ), "with no arguments given, the arguments are not checked"


# --- 3. the replay's classification, through the reader -------------------------------------


@dataclass(frozen=True)
class Seen:
    """One call the replay made to the reader, and what the real reader answered."""

    run_dir: Path
    session_id: UUID
    step: int
    tool: str | None
    arguments: Mapping[str, Any] | None
    answer: StoredResult | Unstored


def spied(monkeypatch: pytest.MonkeyPatch) -> list[Seen]:
    """Every call `benchmark/replay` makes to the reader, which still answers."""
    seen: list[Seen] = []

    def spy(
        run_dir: Path,
        session_id: UUID,
        step: int,
        *,
        tool: str | None = None,
        arguments: Mapping[str, Any] | None = None,
    ) -> StoredResult | Unstored:
        answer = registry.read_stored_result(
            run_dir, session_id, step, tool=tool, arguments=arguments
        )
        seen.append(Seen(run_dir, session_id, step, tool, arguments, answer))
        return answer

    monkeypatch.setattr(replay_module, "read_stored_result", spy)
    return seen


def two_live_calls(tmp_path: Path) -> tuple[Path, list[RecordedCall]]:
    """A recorded review with two bridge calls the replay cannot run, then one it can."""
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((LIVE,), (LIVE,), (COMPONENTS,)))],
        **with_bridge(answers=2),
    )
    calls = [
        call
        for turn in read_recording(run).turns
        for recorded_round in turn.rounds
        for call in recorded_round.calls
    ]
    return run, calls


def spoil_file(path: Path, spoil: str) -> None:
    """The replay's own spoils (`test_replay_accounting.py`), another step, and a deletion."""
    if spoil == "another session":
        rewrite_envelope(path, lambda envelope: envelope.update(session_id=str(uuid4())))
    elif spoil == "another step":
        rewrite_envelope(path, lambda envelope: envelope.update(step=envelope["step"] + 1))
    elif spoil == "another tool":
        rewrite_envelope(path, lambda envelope: envelope.update(tool="list_components"))
    elif spoil == "other arguments":
        rewrite_envelope(
            path,
            lambda envelope: envelope.update(
                arguments={**envelope["arguments"], "configuration": "Other"}
            ),
        )
    elif spoil == "no payload":
        rewrite_envelope(path, lambda envelope: envelope.pop("payload"))
    elif spoil == "not json":
        path.write_text("{not json", encoding="utf-8")
    elif spoil == "deleted":
        path.unlink()
    else:
        assert spoil == "as stored", spoil


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize(
    ("spoil", "reason"),
    [
        ("as stored", None),
        ("another session", "other_session"),
        ("another step", "other_call"),
        ("another tool", "other_call"),
        ("other arguments", "other_call"),
        ("no payload", "unreadable"),
        ("not json", "unreadable"),
        ("deleted", "missing"),
    ],
)
def test_the_replay_classes_each_call_it_cannot_run_by_what_the_reader_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spoil: str, reason: str | None
) -> None:
    """The first bridge call's file is spoiled, the second's left as `_store` wrote it."""
    run, (first, second, components) = two_live_calls(tmp_path)
    spoil_file(stored_file(run, first.step), spoil)
    seen = spied(monkeypatch)

    report = replay(run, requested=ALL_OFF)

    classes = {call.step: call.class_ for row in report.rounds for call in row.calls}
    assert classes == {
        first.step: "stored" if reason is None else "estimated",
        second.step: "stored",
        components.step: "reproduced",
    }
    session_id = read_recording(run).session.session_id
    assert [(s.run_dir, s.session_id, s.step, s.tool, s.arguments) for s in seen] == [
        (run, session_id, call.step, call.tool, call.arguments) for call in (first, second)
    ], "once per call the replay could not run, with the recorded session, step, tool, arguments"
    if reason is None:
        assert isinstance(seen[0].answer, StoredResult)
    else:
        assert seen[0].answer == Unstored(reason)
    assert isinstance(seen[1].answer, StoredResult)


@pytest.mark.usefixtures("vocabulary")
def test_a_recording_made_before_feature_008_reads_every_call_missing_and_estimated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, (first, second, components) = two_live_calls(tmp_path)
    without_stored_results(run)
    seen = spied(monkeypatch)

    report = replay(run, requested=ALL_OFF)

    classes = {call.step: call.class_ for row in report.rounds for call in row.calls}
    assert classes == {
        first.step: "estimated",
        second.step: "estimated",
        components.step: "reproduced",
    }
    assert [(s.step, s.answer) for s in seen] == [
        (first.step, Unstored("missing")),
        (second.step, Unstored("missing")),
    ]
