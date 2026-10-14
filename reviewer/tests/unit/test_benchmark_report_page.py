"""The report page and the reader it shares with the replay (feature 014 `contracts/report.md`).

`report.md` 9's rows, each named where it is pinned. R-17 (T159): `read_recording`, the
replay's view of a recorded review, reads its event log through the product's one event-line
reader, `agent/events.replay_events` (plan decision RF-29), which is stricter than the line
reader it replaces: a line that is JSON with a body but not an `AgentEvent` is now refused too.
Its other refusals keep their sentences (`benchmark/recording.py:163-173` at `be01974`), and
every committed replay fixture reads with no unreadable line.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import events
from swreview.agent.events import EVENTS_FILE_NAME
from swreview.agent.providers import AgentEvent
from swreview.benchmark import recording
from swreview.benchmark.recording import RecordingRefused, read_recording
from swreview.benchmark.replay import TurnPlan
from swreview.ir.loader import PACKAGE_FILE_NAME, save_package
from tests.support.prerun import prerun_package
from tests.support.replay import record_scripted_review
from tests.unit.test_replay_recording import SUMMARY

TESTS = Path(__file__).resolve().parents[1]
REPLAY_FIXTURES = sorted(
    path.parent for path in (TESTS / "fixtures" / "replay").glob("*/events.jsonl")
)


def recorded_run(tmp_path: Path) -> Path:
    """A scripted recorded review of one round, as `test_replay_recording.py` records one."""
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    return record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])


class ReaderSpy:
    """Wraps `replay_events` as `recording` calls it: each path it is given, and each number
    the reader reports to the hook `read_recording` passed."""

    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.reported: list[int] = []

    def __call__(self, path: Path | str, after: int = 0, **hooks: Any) -> Iterator[AgentEvent]:
        self.paths.append(Path(path))
        hook: Callable[[int], None] | None = hooks.get("on_unreadable")
        assert hook is not None, "read_recording passed no on_unreadable hook"

        def reported(number: int) -> None:
            self.reported.append(number)
            hook(number)

        return events.replay_events(path, after, on_unreadable=reported)


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> ReaderSpy:
    spy = ReaderSpy()
    monkeypatch.setattr(recording, "replay_events", spy)
    return spy


def refusal(folder: Path) -> str:
    with pytest.raises(RecordingRefused) as raised:
        read_recording(folder)
    message = str(raised.value)
    assert "\n" not in message
    return message


def _lines(folder: Path) -> int:
    """How many lines the folder's event log holds, its last line ended."""
    return len((folder / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines())


def _unreadable_sentence(folder: Path, number: int) -> str:
    return (
        f"{folder / EVENTS_FILE_NAME} line {number} is not a readable event (not JSON, or not an "
        "event of the chat-events schema), so the recorded rounds cannot be read"
    )


# --- R-17: read_recording on the one reader (T159) ------------------------------------------


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize(
    "line",
    ["{not json", '{"type": "usage", "body": {}}'],
    ids=["not-json", "not-an-agent-event"],
)
def test_r17_a_line_the_reader_cannot_read_is_refused_naming_the_log_and_its_line(
    tmp_path: Path, reader: ReaderSpy, line: str
) -> None:
    """The second line is JSON with a body object, which the old line reader accepted; it has no
    `seq` and no `at`, so it is no `AgentEvent`, and the stricter reader refuses it (`report.md`
    5). The number is the offending line's, 1-based, as the hook reports it."""
    folder = tmp_path / "broken"
    shutil.copytree(recorded_run(tmp_path), folder)
    number = _lines(folder) + 1
    with (folder / EVENTS_FILE_NAME).open("a", encoding="utf-8") as log:
        log.write(line + "\n")

    message = refusal(folder)

    assert message == _unreadable_sentence(folder, number)
    assert re.search(rf"\bline {number}\b", message)
    assert reader.paths == [folder / EVENTS_FILE_NAME]
    assert reader.reported == [number]


@pytest.mark.usefixtures("vocabulary")
def test_r17_a_log_with_no_usage_event_is_refused_in_its_sentence(
    tmp_path: Path, reader: ReaderSpy
) -> None:
    folder = tmp_path / "quiet"
    shutil.copytree(recorded_run(tmp_path), folder)
    log = folder / EVENTS_FILE_NAME
    kept = [
        line
        for line in log.read_text(encoding="utf-8").splitlines()
        if AgentEvent.model_validate_json(line).type != "usage"
    ]
    log.write_text("\n".join(kept) + "\n", encoding="utf-8")

    message = refusal(folder)

    assert message == (
        f"{log} records no usage event: no provider round was recorded, so there is nothing "
        "to price"
    )
    assert reader.paths == [log]
    assert reader.reported == []


@pytest.mark.usefixtures("vocabulary")
def test_r17_a_folder_with_no_package_is_refused_in_its_sentence(
    tmp_path: Path, reader: ReaderSpy
) -> None:
    folder = tmp_path / "nopackage"
    shutil.copytree(recorded_run(tmp_path), folder)
    (folder / PACKAGE_FILE_NAME).unlink()

    message = refusal(folder)

    assert message == (
        f"{folder} holds no {PACKAGE_FILE_NAME}: the replay re-runs the recorded calls against "
        "the package and cannot without it"
    )
    assert reader.paths == [folder / EVENTS_FILE_NAME]
    assert reader.reported == []


def test_there_are_committed_replay_fixtures_to_read() -> None:
    assert REPLAY_FIXTURES, "no tests/fixtures/replay/*/events.jsonl was found"


@pytest.mark.parametrize("folder", REPLAY_FIXTURES, ids=lambda folder: folder.name)
def test_r17_every_committed_replay_fixture_reads_through_the_one_reader_whole(
    folder: Path, reader: ReaderSpy
) -> None:
    read = read_recording(folder)

    assert reader.paths == [folder / EVENTS_FILE_NAME]
    assert reader.reported == []
    assert read.turns
