"""A recorded review, read back from its run folder (feature 008, `contracts/replay.md` §2).

`read_recording(run_dir)` is the replay's only view of a review that already happened. It
reads `session.json` through `report/rerender.run_folder_session` - so a folder with no session
and a benchmark run root are refused in that function's own sentences - and rebuilds the
review's turns and rounds from `events.jsonl`, using only the markers the log carries:

- a **round** is a `usage` event and the `tool.started` events after it: every adapter emits a
  round's usage before it dispatches that round's calls;
- a `usage` after the turn's `text.done` and before its `turn.ended` is the **presentation**
  request, told apart by position alone (its `round_index` follows on from the main rounds);
  a turn that ends with no text therefore has that round counted as a main round;
- a turn preceded by `evidence.answered` events is an **answer** turn carrying them; any other
  turn after the first is a **follow-up**, whose words are sized from the recorded growth
  because no event records the text;
- a `tool.started` with no `tool.finished` - the call a Stop interrupted - is dropped;
- steps written before the first `usage` (a recorded pre-run) are `setup_steps`, never
  scripted;
- each finding belongs to the call whose `tool.started`/`tool.finished` bracket its first
  `finding` event falls in; `tool_result_ids` cannot tie them, because live-bridge findings
  carry none.

A folder that is not a review is refused with one sentence naming what is missing. Reading
writes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from swreview.agent.events import EVENTS_FILE_NAME
from swreview.agent.providers import TokenUsage, usage_from_body
from swreview.findings import Finding
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.report.rerender import run_folder_session
from swreview.report.session import ReviewSession, load_session

__all__ = [
    "RecordedCall",
    "RecordedFinding",
    "RecordedRound",
    "RecordedTurn",
    "Recording",
    "RecordingRefused",
    "read_recording",
]

UNCOMMITTED_ENDS = frozenset({"stopped", "error"})
"""Turn ends the runner keeps no history for: the turn raised instead of returning, so the next
turn's request does not carry it."""


class RecordingRefused(ValueError):
    """The folder is not a recorded review; the message is one sentence naming what is missing."""


@dataclass(frozen=True)
class RecordedCall:
    """One call the recorded model made, as the trace recorded it."""

    step: int
    tool: str
    arguments: dict[str, Any]
    status: Literal["ok", "error"]
    summary: str
    """The recorded 200-character `result_summary`."""


@dataclass(frozen=True)
class RecordedRound:
    """One billed model round and the calls it asked for."""

    turn: int
    index: int
    """Counts the turn's main rounds; a presentation round takes the next number."""
    kind: Literal["main", "presentation"]
    usage: TokenUsage
    calls: tuple[RecordedCall, ...]


@dataclass(frozen=True)
class RecordedTurn:
    """One engineering turn: how it began, its rounds, how it ended."""

    index: int
    kind: Literal["opening", "follow_up", "answer"]
    answers: tuple[tuple[str, str], ...]
    rounds: tuple[RecordedRound, ...]
    end_reason: str
    user_tokens: int | None
    """The engineer's message, in tokens, as the recorded growth shows it: the turn's first
    input minus the previous committed turn's last main round and its output. `None` for the
    opening turn (its message is inside the first round) and when that growth is not
    observable - the previous round asked for calls whose sizes the log does not carry."""

    @property
    def main_rounds(self) -> tuple[RecordedRound, ...]:
        return tuple(r for r in self.rounds if r.kind == "main")


@dataclass(frozen=True)
class RecordedFinding:
    """A recorded finding and the step whose event bracket produced it (`None` if none did)."""

    finding: Finding
    step: int | None


@dataclass(frozen=True)
class Recording:
    """A recorded review: its session, its package and its turns, as the log records them."""

    run_dir: Path
    session: ReviewSession
    package_path: Path
    provider: str
    turns: tuple[RecordedTurn, ...]
    findings: tuple[RecordedFinding, ...]
    setup_steps: tuple[int, ...]

    def growth_after(self, recorded: RecordedRound) -> int | None:
        """The input the round's own output and results added, as the next round shows it.

        The next main round of the same turn, minus this round's input and output. `None` -
        not observable - for a presentation round, for the last main round of a turn (the next
        request carries a new user message too, or never came) and for a negative difference,
        which a pruned or compacted history can produce.
        """
        if recorded.kind != "main":
            return None
        turn = self.turns[recorded.turn]
        following = [r for r in turn.main_rounds if r.index == recorded.index + 1]
        if not following:
            return None
        before, after = recorded.usage, following[0].usage
        if before.input_tokens is None or before.output_tokens is None:
            return None
        if after.input_tokens is None:
            return None
        growth = after.input_tokens - before.input_tokens - before.output_tokens
        return growth if growth >= 0 else None


def read_recording(run_dir: Path | str) -> Recording:
    """Read a review run folder into a `Recording`, or refuse it in one sentence."""
    directory = Path(run_dir)
    try:
        session_file = run_folder_session(directory)
    except (FileNotFoundError, ValueError) as exc:
        raise RecordingRefused(str(exc)) from exc
    events_file = directory / EVENTS_FILE_NAME
    if not events_file.is_file():
        raise RecordingRefused(
            f"{directory} holds no {EVENTS_FILE_NAME}: it is a check folder or was written "
            "before the event log, and a check has no provider rounds to replay"
        )
    events = _events(events_file)
    if not any(event.get("type") == "usage" for event in events):
        raise RecordingRefused(
            f"{events_file} records no usage event: no provider round was recorded, so there "
            "is nothing to price"
        )
    package_path = directory / PACKAGE_FILE_NAME
    if not package_path.is_file():
        raise RecordingRefused(
            f"{directory} holds no {PACKAGE_FILE_NAME}: the replay re-runs the recorded calls "
            "against the package and cannot without it"
        )
    session = load_session(session_file)
    reader = _EventReader()
    for event in events:
        reader.read(event)
    turns = _with_user_tokens(reader.finish())
    provider = session.provider_info.provider if session.provider_info is not None else "unknown"
    return Recording(
        run_dir=directory,
        session=session,
        package_path=package_path,
        provider=provider,
        turns=turns,
        findings=tuple(
            RecordedFinding(finding=finding, step=reader.finding_steps.get(finding.id))
            for finding in session.findings
        ),
        setup_steps=tuple(reader.setup_steps),
    )


def _events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RecordingRefused(
                f"{path} line {number} is not a JSON event ({exc.msg}), so the recorded rounds "
                "cannot be read"
            ) from exc
        if not isinstance(event, dict) or not isinstance(event.get("body"), dict):
            raise RecordingRefused(
                f"{path} line {number} is not an event object with a body, so the recorded "
                "rounds cannot be read"
            )
        events.append(event)
    return events


@dataclass
class _OpenTurn:
    answers: list[tuple[str, str]]
    rounds: list[dict[str, Any]]
    text_done: bool = False


class _EventReader:
    """One pass over the event log, keeping the rebuild's state explicit."""

    def __init__(self) -> None:
        self.turns: list[tuple[_OpenTurn, str]] = []
        self.setup_steps: list[int] = []
        self.finding_steps: dict[str, int] = {}
        self._turn: _OpenTurn | None = None
        self._answers: list[tuple[str, str]] = []
        self._open_calls: dict[int, dict[str, Any]] = {}
        self._seen_usage = False

    def read(self, event: dict[str, Any]) -> None:
        kind, body = event.get("type"), event["body"]
        if kind == "usage":
            self._usage(body)
        elif kind == "tool.started":
            self._started(body)
        elif kind == "tool.finished":
            self._finished(body)
        elif kind == "finding":
            self._finding(body)
        elif kind == "text.done" and self._turn is not None:
            self._turn.text_done = True
        elif kind == "evidence.answered":
            self._answers.append((str(body.get("request_id")), str(body.get("answer"))))
        elif kind == "turn.ended":
            self._ended(str(body.get("reason")))

    def _usage(self, body: dict[str, Any]) -> None:
        self._seen_usage = True
        if self._turn is None:
            self._turn = _OpenTurn(answers=self._answers, rounds=[])
            self._answers = []
        main = [r for r in self._turn.rounds if r["kind"] == "main"]
        presentation = self._turn.text_done
        self._turn.rounds.append(
            {
                "kind": "presentation" if presentation else "main",
                "index": len(main),
                "usage": usage_from_body(body),
                "calls": [],
            }
        )

    def _started(self, body: dict[str, Any]) -> None:
        step = int(body["step_index"])
        call = {"step": step, "tool": str(body["tool"]), "arguments": body.get("arguments") or {}}
        self._open_calls[step] = call
        if not self._seen_usage:
            self.setup_steps.append(step)
        elif self._turn is not None and self._turn.rounds:
            self._turn.rounds[-1]["calls"].append(call)

    def _finished(self, body: dict[str, Any]) -> None:
        call = self._open_calls.pop(int(body["step_index"]), None)
        if call is not None:
            call["status"] = "error" if body.get("status") == "error" else "ok"
            call["summary"] = str(body.get("result_summary", ""))

    def _finding(self, body: dict[str, Any]) -> None:
        finding_id = body.get("id")
        if not isinstance(finding_id, str) or finding_id in self.finding_steps:
            return
        if len(self._open_calls) == 1:
            [step] = self._open_calls
            self.finding_steps[finding_id] = step

    def _ended(self, reason: str) -> None:
        if self._turn is None:
            self._turn = _OpenTurn(answers=self._answers, rounds=[])
            self._answers = []
        self.turns.append((self._turn, reason))
        self._turn = None
        # A call a Stop interrupted never finishes; it is not part of the recorded review.
        self._open_calls.clear()

    def finish(self) -> list[RecordedTurn]:
        if self._turn is not None:
            self.turns.append((self._turn, "open"))
            self._turn = None
        built: list[RecordedTurn] = []
        for index, (turn, reason) in enumerate(self.turns):
            kind: Literal["opening", "follow_up", "answer"] = (
                "opening" if index == 0 else "answer" if turn.answers else "follow_up"
            )
            built.append(
                RecordedTurn(
                    index=index,
                    kind=kind,
                    answers=tuple(turn.answers),
                    rounds=tuple(
                        RecordedRound(
                            turn=index,
                            index=r["index"],
                            kind=r["kind"],
                            usage=r["usage"],
                            calls=tuple(
                                RecordedCall(
                                    step=c["step"],
                                    tool=c["tool"],
                                    arguments=dict(c["arguments"]),
                                    status=c["status"],
                                    summary=c["summary"],
                                )
                                for c in r["calls"]
                                if "status" in c
                            ),
                        )
                        for r in turn.rounds
                    ),
                    end_reason=reason,
                    user_tokens=None,
                )
            )
        return built


def _with_user_tokens(turns: list[RecordedTurn]) -> tuple[RecordedTurn, ...]:
    """Size each later turn's engineer message from the recorded growth (see `user_tokens`)."""
    sized: list[RecordedTurn] = []
    baseline: RecordedRound | None = None
    for turn in turns:
        tokens: int | None = None
        first = turn.main_rounds[0] if turn.main_rounds else None
        if turn.index > 0 and first is not None and baseline is not None and not baseline.calls:
            before, now = baseline.usage, first.usage
            if None not in (before.input_tokens, before.output_tokens, now.input_tokens):
                growth = now.input_tokens - before.input_tokens - before.output_tokens  # type: ignore[operator]
                tokens = growth if growth >= 0 else None
        sized.append(
            RecordedTurn(
                index=turn.index,
                kind=turn.kind,
                answers=turn.answers,
                rounds=turn.rounds,
                end_reason=turn.end_reason,
                user_tokens=tokens,
            )
        )
        if turn.end_reason not in UNCOMMITTED_ENDS and turn.main_rounds:
            baseline = turn.main_rounds[-1]
    return tuple(sized)
