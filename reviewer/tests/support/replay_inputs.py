"""Seed only runtime producer inputs when verifying unchanged replay fixture bytes.

The unchanged generator still builds packages, payloads and records and runs its self-checks.
Nothing here reads or rewrites generated output. Counts are exact for each of its two passes;
a changed event/step/finalization structure is a failure, never a new baseline.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

from swreview.agent import events, runner
from swreview.tools import context, registry
from tests.support import replay


@dataclass(frozen=True)
class ReplayBaseline:
    """Runtime inputs captured before the generator replaces its fixture folder."""

    session_id: UUID
    started_at: datetime
    event_times: tuple[datetime, ...]
    ended_at: tuple[datetime, ...]
    perf_times: tuple[float, ...]

    @classmethod
    def from_folder(cls, folder: Path) -> ReplayBaseline:
        session = json.loads((folder / "session.json").read_bytes())
        stream = [json.loads(line) for line in (folder / "events.jsonl").read_bytes().splitlines()]
        return cls(
            session_id=UUID(session["session_id"]),
            started_at=datetime.fromisoformat(session["started_at"]),
            event_times=tuple(datetime.fromisoformat(row["at"]) for row in stream),
            ended_at=tuple(
                datetime.fromisoformat(row["body"]["ended_at"])
                for row in stream
                if row["type"] == "session.ended"
            ),
            perf_times=tuple(
                value for step in session["steps"] for value in (0.0, step["elapsed_s"])
            ),
        )


class _Values:
    def __init__(self, kind: str, values: Sequence[Any]) -> None:
        self.kind = kind
        self.values = values
        self.used = 0
        self.overflow = False

    def next(self) -> Any:
        if self.used >= len(self.values):
            self.overflow = True
            raise AssertionError(f"unexpected extra {self.kind} runtime input")
        value = self.values[self.used]
        self.used += 1
        return value

    def exhausted(self) -> None:
        if self.overflow:
            raise AssertionError(
                f"unexpected extra {self.kind} runtime input was caught by a producer"
            )
        if self.used != len(self.values):
            raise AssertionError(
                f"missing {self.kind} runtime input: used {self.used}, expected {len(self.values)}"
            )


@contextmanager
def seed_replay_inputs(baseline: ReplayBaseline) -> Iterator[None]:
    """Wrap the unchanged generator's two plays, resetting the seams for each one."""
    original_play = replay.play_review
    passes: list[bool] = []

    def seeded_play(*args: Any, **kwargs: Any) -> Any:
        writing = kwargs.get("usages") is not None
        passes.append(writing)
        main_rounds = sum(len(plan.rounds) + 1 for plan in args[2])
        learning_count = len(baseline.event_times) - main_rounds
        if learning_count < 0:
            raise AssertionError("the learning pass has more main rounds than recorded events")
        event_values = baseline.event_times if writing else (baseline.started_at,) * learning_count
        uuid = _Values("uuid", (baseline.session_id,))
        start = _Values("start", (baseline.started_at,))
        event = _Values("event", event_values)
        end = _Values("end", baseline.ended_at)
        perf = _Values("perf", baseline.perf_times)

        class ContextDatetime(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                value = start.next()
                return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

        class RunnerDatetime(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                value = end.next()
                return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

        with ExitStack() as stack:
            stack.enter_context(patch.object(context, "uuid4", uuid.next))
            stack.enter_context(patch.object(context, "datetime", ContextDatetime))
            stack.enter_context(patch.object(events, "utc_now", event.next))
            stack.enter_context(patch.object(runner, "datetime", RunnerDatetime))
            stack.enter_context(patch.object(registry, "perf_counter", perf.next))
            result = original_play(*args, **kwargs)
        for values in (uuid, start, event, end, perf):
            values.exhausted()
        return result

    with patch.object(replay, "play_review", seeded_play):
        yield
    if passes != [False, True]:
        raise AssertionError(
            "generator passes changed: expected one learning then one writing pass"
        )
