"""The one event-line reader, `agent.events.replay_events` (T012, for T013).

Every reader of `events.jsonl` reads it through the product's own typed, tolerant reader,
moved beside `EVENTS_FILE_NAME` in `agent/events.py` from `chat/sessions.py` and re-exported
there (plan decision RF-29), and a run's stream is found, plain or packed, through
`event_stream` beside it (owner decision 28A; plan decision RF-83). What it promises is
pinned here, as `scoring.md` 11's `test_event_lines.py` numbers it:

1. **Where it stops, and that it says so.** It yields every event of a well-formed log and
   stops at the first line that is not JSON, not UTF-8 (a write cut inside a multibyte
   character, in either form, section 5) or not an `AgentEvent`, calling `on_unreadable`
   with that line's 1-based number in the file, blank lines counted. A line ends at `\\n`,
   `\\r\\n` or a lone `\\r`, as text mode ends it at `be01974` (owner decision 38A, section
   5). Without the hook it behaves as at `be01974`: a missing file is an empty stream,
   `after` filters by `seq`, and the pane's reconnect and remodel tests
   (`test_chat_sessions.py`, the chat-server reconnect tests,
   `tests/integration/test_remodel_flow.py`) pass unchanged.
2. **One reader.** `chat.sessions.replay_events` is the object `agent/events.py` defines,
   not a copy.
3. **Every committed replay fixture reads whole**, with an `on_unreadable` that fails.
5. **A packed stream reads as its plain form**, and a damaged one (truncated mid-archive, a
   header that is not gzip, a CRC that does not match, deflate data that does not inflate)
   yields what precedes the damage, stops at the line being read and names it, never
   raising.
6. **`event_stream(folder)`** names the plain stream, else the packed one, else the plain
   path; a folder holding both is an unfinished pack and is refused.

4. **One call per reader's unit.** A spy on it sees exactly one call per package from
   `score_run` (T086), one per `read_recording` (T159) and one per transcript page the report
   writes (T166); `attempt_facts`' row lands with its caller (T187). The structural half
   (T159): no other reader of `events.jsonl` under `benchmark/`, and no module there
   decompresses a stream itself; a module-level sentence the owner named may name the files
   (owner decision 81A).

6's `score_run` spy (T086): `score_run` finds each package's stream through `event_stream`.
"""

from __future__ import annotations

import ast
import gzip
import re
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import events
from swreview.agent.events import (
    EVENTS_FILE_NAME,
    PACKED_EVENTS_FILE_NAME,
    event_stream,
    replay_events,
)
from swreview.agent.providers import AgentEvent
from swreview.benchmark import recording, report_page, runner
from swreview.benchmark.scorecard import score_run
from swreview.benchmark.sets import BenchmarkSet
from swreview.chat import sessions
from swreview.report.session import SessionUsage
from tests.support.studies import PackageSpec, RunSpec, write_run
from tests.unit.test_benchmark_attempts import write_attempt
from tests.unit.test_benchmark_report_page import recorded_run
from tests.unit.test_scorecard_usage import make_usage
from tests.unit.test_scorecard_usage import write_package as write_scored_package

TESTS = Path(__file__).resolve().parents[1]
REPLAY_FIXTURES = sorted((TESTS / "fixtures" / "replay").glob("*/events.jsonl"))

AT = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _event(seq: int, text: str = "") -> AgentEvent:
    return AgentEvent(seq=seq, at=AT, type="text.delta", body={"text": text or f"line {seq}"})


def _line(event: AgentEvent) -> str:
    """One line of `events.jsonl` as `EventSink.emit` writes it."""
    return event.model_dump_json() + "\n"


def _log(count: int, text: str = "") -> tuple[list[AgentEvent], bytes]:
    """`count` events and the bytes of the well-formed log that holds them."""
    written = [_event(seq, text) for seq in range(1, count + 1)]
    return written, "".join(_line(event) for event in written).encode()


class Unreadable:
    """An `on_unreadable` hook that keeps every number it was called with."""

    def __init__(self) -> None:
        self.numbers: list[int] = []

    def __call__(self, number: int) -> None:
        self.numbers.append(number)


def _replay(path: Path, after: int = 0) -> tuple[list[AgentEvent], list[int]]:
    """Every event the reader yields, and every number it reported, never raising."""
    hook = Unreadable()
    return list(replay_events(path, after, on_unreadable=hook)), hook.numbers


# --- 1. where it stops, and that it says so ----------------------------------------


def test_it_yields_every_event_of_a_well_formed_log_and_reports_nothing(
    tmp_path: Path,
) -> None:
    written, data = _log(5)
    path = tmp_path / EVENTS_FILE_NAME
    path.write_bytes(data)

    assert _replay(path) == (written, [])


def test_it_stops_at_a_line_that_is_not_json_and_names_its_number(tmp_path: Path) -> None:
    """The replay ends there: the event after the bad line is not read."""
    written, data = _log(3)
    path = tmp_path / EVENTS_FILE_NAME
    path.write_bytes(data + b"not json at all\n" + _line(_event(4)).encode())

    assert _replay(path) == (written, [4])


def test_it_stops_at_a_json_line_that_is_not_an_agent_event(tmp_path: Path) -> None:
    written, data = _log(3)
    path = tmp_path / EVENTS_FILE_NAME
    path.write_bytes(data + b'{"seq": 4, "body": {}}\n' + _line(_event(5)).encode())

    assert _replay(path) == (written, [4])


def test_it_stops_at_a_half_written_last_line_and_names_it(tmp_path: Path) -> None:
    """What a backend killed mid-write leaves: no newline, the line cut in half."""
    written, data = _log(2)
    path = tmp_path / EVENTS_FILE_NAME
    path.write_bytes(data + b'{"seq": 3, "at": "2026-09-27T12:00:00Z", "type": "text.d')

    assert _replay(path) == (written, [3])


def test_blank_lines_are_skipped_and_counted_in_the_number(tmp_path: Path) -> None:
    first, second = _event(1), _event(2)
    path = tmp_path / EVENTS_FILE_NAME
    lines = [_line(first), "\n", "   \n", _line(second), "{broken\n"]
    path.write_bytes("".join(lines).encode())

    assert _replay(path) == ([first, second], [5])


def test_after_filters_by_seq_and_the_number_still_counts_every_line(
    tmp_path: Path,
) -> None:
    written, data = _log(3)
    path = tmp_path / EVENTS_FILE_NAME
    path.write_bytes(data + b"{broken\n")

    assert _replay(path, after=2) == (written[2:], [4])


def test_a_file_that_does_not_exist_is_an_empty_stream_and_is_not_unreadable(
    tmp_path: Path,
) -> None:
    assert _replay(tmp_path / "nothing" / EVENTS_FILE_NAME) == ([], [])


def test_an_empty_file_is_an_empty_stream_and_is_not_unreadable(tmp_path: Path) -> None:
    path = tmp_path / EVENTS_FILE_NAME
    path.write_bytes(b"")

    assert _replay(path) == ([], [])


def test_without_the_hook_it_behaves_as_before(tmp_path: Path) -> None:
    """As at `be01974`: `after` filters by `seq`, a bad line ends the replay quietly, a
    missing file is empty, and the path may be a string."""
    written, data = _log(4)
    path = tmp_path / EVENTS_FILE_NAME
    path.write_bytes(data + b"{broken\n" + _line(_event(5)).encode())

    assert list(replay_events(path)) == written
    assert list(replay_events(str(path), after=2)) == written[2:]
    assert list(replay_events(path, after=written[-1].seq)) == []
    assert list(replay_events(tmp_path / "nothing" / EVENTS_FILE_NAME)) == []


# --- 2. one reader -----------------------------------------------------------------


def test_chat_sessions_re_exports_the_reader_agent_events_defines() -> None:
    """Identity, and the definition's module: a copy in `chat/sessions.py`, or the reader
    left there and imported back into `agent/events.py`, fails one of the two."""
    assert sessions.replay_events is events.replay_events
    assert events.replay_events.__module__ == "swreview.agent.events"
    assert "replay_events" in sessions.__all__


# --- 3. every committed replay fixture reads whole ---------------------------------


def test_there_are_committed_replay_fixtures_to_read() -> None:
    assert REPLAY_FIXTURES, "no tests/fixtures/replay/*/events.jsonl was found"


@pytest.mark.parametrize("path", REPLAY_FIXTURES, ids=lambda path: path.parent.name)
def test_every_committed_replay_fixture_reads_with_no_unreadable_line(path: Path) -> None:
    def fail(number: int) -> None:
        pytest.fail(f"{path.parent.name}/{path.name} line {number} is unreadable")

    replayed = list(replay_events(path, on_unreadable=fail))

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(replayed) == len(lines)


# --- 5. a packed stream reads as its plain form ------------------------------------


def _packed(folder: Path, data: bytes) -> Path:
    """`data` packed as `benchmark pack` packs a stream (28A)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / PACKED_EVENTS_FILE_NAME
    path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    return path


def _plain(folder: Path, data: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / EVENTS_FILE_NAME
    path.write_bytes(data)
    return path


def test_a_packed_stream_yields_exactly_what_its_plain_bytes_yield(tmp_path: Path) -> None:
    written, data = _log(40)
    plain = _plain(tmp_path / "plain", data)
    packed = _packed(tmp_path / "packed", data)

    assert _replay(packed) == _replay(plain) == (written, [])
    assert _replay(packed, after=30) == _replay(plain, after=30) == (written[30:], [])


def test_a_packed_stream_names_a_malformed_line_as_its_plain_form_does(
    tmp_path: Path,
) -> None:
    written, data = _log(3)
    data = data + b"\n{broken\n" + _line(_event(4)).encode()
    plain = _plain(tmp_path / "plain", data)
    packed = _packed(tmp_path / "packed", data)

    assert _replay(packed) == _replay(plain) == (written, [5])


FORMS = {"plain": _plain, "packed": _packed}


def _cut_inside_a_character(event: AgentEvent) -> bytes:
    """`event`'s line as a write cut short in non-ASCII text leaves it: every byte up to and
    including the first of its first `±` (a tolerance sign, two bytes in UTF-8), so the
    line ends in half a character and has no newline."""
    line = _line(event).encode()
    sign = "±".encode()
    assert len(sign) == 2 and sign in line
    return line[: line.index(sign) + 1]


@pytest.mark.parametrize("form", FORMS)
def test_a_last_line_cut_inside_a_multibyte_character_stops_the_replay_and_is_named(
    tmp_path: Path, form: str
) -> None:
    """A line that is not UTF-8 ends the replay as a line that is not JSON does, in either
    form; a reader without the hook (the pane) gets the same prefix and no exception."""
    written, data = _log(3)
    path = FORMS[form](tmp_path, data + _cut_inside_a_character(_event(4, "10 ± 0.02")))

    assert _replay(path) == (written, [4])
    assert list(replay_events(path)) == written


@pytest.mark.parametrize("form", FORMS)
def test_a_cut_character_with_later_events_after_it_stops_at_the_cut_line(
    tmp_path: Path, form: str
) -> None:
    """A session continued after the cut appends its next event to the cut line, which had
    no newline: that line is not UTF-8, the replay stops at it, and the lines before it are
    yielded although one read holds them and the damage."""
    written, data = _log(3)
    cut = _cut_inside_a_character(_event(4, "10 ± 0.02"))
    later = _line(_event(5)).encode() + _line(_event(6)).encode()
    path = FORMS[form](tmp_path, data + cut + later)

    assert _replay(path) == (written, [4])
    assert list(replay_events(path)) == written


@pytest.mark.parametrize("form", FORMS)
def test_a_lone_carriage_return_ends_a_line_as_at_be01974(tmp_path: Path, form: str) -> None:
    """Lines end where text mode ends them, at `\\n`, `\\r\\n` or a lone `\\r` (universal
    newlines, as at `be01974`; owner decision 38A), in either form."""
    written = [_event(1), _event(2), _event(3)]
    first, second, third = (event.model_dump_json().encode() for event in written)
    path = FORMS[form](tmp_path, first + b"\r\n" + second + b"\r" + third + b"\r\n")

    assert _replay(path) == (written, [])
    assert [event.seq for event in replay_events(path)] == [1, 2, 3]


@pytest.mark.parametrize("form", FORMS)
def test_a_lone_carriage_return_is_a_line_end_in_the_number(tmp_path: Path, form: str) -> None:
    """Two lone carriage returns after the second event end its line and a blank one, both
    counted, so the broken line after them is line 4."""
    first, second = _event(1), _event(2)
    data = b"\r".join(
        [first.model_dump_json().encode(), second.model_dump_json().encode(), b"", b"{broken\n"]
    )
    path = FORMS[form](tmp_path, data + _line(_event(3)).encode())

    assert _replay(path) == ([first, second], [4])


def test_a_packed_stream_that_does_not_exist_is_an_empty_stream(tmp_path: Path) -> None:
    assert _replay(tmp_path / PACKED_EVENTS_FILE_NAME) == ([], [])


def _assert_stopped_at_the_line_being_read(
    replayed: list[AgentEvent], numbers: list[int], written: list[AgentEvent]
) -> None:
    """What precedes the damage is yielded in order, and the line being read is named."""
    assert replayed == written[: len(replayed)]
    assert numbers == [len(replayed) + 1]


def test_a_packed_stream_truncated_mid_archive_yields_what_precedes_the_cut(
    tmp_path: Path,
) -> None:
    written, data = _log(400, "x" * 1000)
    whole = gzip.compress(data, compresslevel=9, mtime=0)
    truncated = whole[: len(whole) // 2]
    with pytest.raises(EOFError):
        gzip.decompress(truncated)
    path = tmp_path / PACKED_EVENTS_FILE_NAME
    path.write_bytes(truncated)

    replayed, numbers = _replay(path)

    assert 0 < len(replayed) < len(written)
    _assert_stopped_at_the_line_being_read(replayed, numbers, written)
    assert list(replay_events(path)) == replayed, "without the hook: the prefix, no raise"


def test_a_packed_stream_whose_header_is_not_gzip_stops_at_line_one(
    tmp_path: Path,
) -> None:
    _, data = _log(3)
    corrupt = b"\x00" + gzip.compress(data, compresslevel=9, mtime=0)[1:]
    with pytest.raises(gzip.BadGzipFile):
        gzip.decompress(corrupt)
    path = tmp_path / PACKED_EVENTS_FILE_NAME
    path.write_bytes(corrupt)

    assert _replay(path) == ([], [1])


def test_a_packed_stream_whose_crc_does_not_match_stops_after_its_last_line(
    tmp_path: Path,
) -> None:
    """The trailer is read once every line has been: the line being read is the next."""
    written, data = _log(3)
    whole = bytearray(gzip.compress(data, compresslevel=9, mtime=0))
    whole[-8] ^= 0xFF
    corrupt = bytes(whole)
    with pytest.raises(gzip.BadGzipFile):
        gzip.decompress(corrupt)
    path = tmp_path / PACKED_EVENTS_FILE_NAME
    path.write_bytes(corrupt)

    assert _replay(path) == (written, [4])


def test_a_packed_stream_whose_deflate_data_does_not_inflate_yields_what_precedes_it(
    tmp_path: Path,
) -> None:
    """The archive is written in two parts with a full flush between them, so the second
    part starts a new deflate block on a byte boundary; that block's type is set to the
    reserved value (`BTYPE` 3), which no inflater accepts. The first part is far larger
    than any read the reader makes, so its lines arrive before the damage does."""
    before, data_before = _log(300, "x" * 1000)
    after = [_event(seq, "y" * 1000) for seq in range(301, 311)]
    packer = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    first = packer.compress(data_before) + packer.flush(zlib.Z_FULL_FLUSH)
    second = bytearray(packer.compress("".join(map(_line, after)).encode()) + packer.flush())
    second[0] |= 0b110
    corrupt = first + bytes(second)
    with pytest.raises(zlib.error):
        gzip.decompress(corrupt)
    path = tmp_path / PACKED_EVENTS_FILE_NAME
    path.write_bytes(corrupt)

    replayed, numbers = _replay(path)

    assert 0 < len(replayed) <= len(before)
    _assert_stopped_at_the_line_being_read(replayed, numbers, before)


# --- 6. event_stream ----------------------------------------------------------------


def test_the_two_file_names() -> None:
    assert EVENTS_FILE_NAME == "events.jsonl"
    assert PACKED_EVENTS_FILE_NAME == "events.jsonl.gz"


def test_event_stream_names_the_plain_stream_when_it_exists(tmp_path: Path) -> None:
    (tmp_path / EVENTS_FILE_NAME).write_bytes(b"")

    assert event_stream(tmp_path) == tmp_path / EVENTS_FILE_NAME


def test_event_stream_names_the_packed_stream_when_only_it_exists(tmp_path: Path) -> None:
    (tmp_path / PACKED_EVENTS_FILE_NAME).write_bytes(gzip.compress(b"", mtime=0))

    assert event_stream(tmp_path) == tmp_path / PACKED_EVENTS_FILE_NAME


def test_event_stream_names_the_plain_path_when_neither_exists_and_it_reads_empty(
    tmp_path: Path,
) -> None:
    stream = event_stream(tmp_path)

    assert stream == tmp_path / EVENTS_FILE_NAME
    assert not stream.exists()
    assert _replay(stream) == ([], [])


def test_event_stream_refuses_a_folder_holding_both_as_an_unfinished_pack(
    tmp_path: Path,
) -> None:
    _, data = _log(2)
    _plain(tmp_path, data)
    _packed(tmp_path, data)
    message = (
        f"{tmp_path} holds events.jsonl and events.jsonl.gz: a pack did not finish; "
        "run swreview benchmark pack on its run again"
    )

    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        event_stream(tmp_path)


# --- 4 and 6: scoring and attempt facts each read through event_stream (T086, T209) ---


def two_scored_packages(tmp_path: Path) -> tuple[Path, Path, BenchmarkSet]:
    """`test_scorecard_usage.py`'s scored package twice, each with its `events.jsonl`."""
    run_dir = tmp_path / "run"
    keys = tmp_path / "answer_keys"
    usage = SessionUsage.summed([make_usage()], [1])
    refs = [
        write_scored_package(run_dir, keys, package_id, usage=usage)
        for package_id in ("pkg-a", "pkg-b")
    ]
    return run_dir, keys, BenchmarkSet(name="pilot", packages=refs)


def test_score_run_replays_each_package_s_stream_once_per_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, keys, benchmark_set = two_scored_packages(tmp_path)
    calls: list[Path] = []
    real = events.replay_events

    def spy(path: Path | str, after: int = 0, **hooks: Any) -> Iterator[AgentEvent]:
        calls.append(Path(path))
        return real(path, after, **hooks)

    monkeypatch.setattr(events, "replay_events", spy)

    score_run(run_dir, keys, benchmark_set)

    # One pass for attempt facts (cost and served ids), one for timing and withdrawals.
    assert calls == [
        run_dir / package / EVENTS_FILE_NAME
        for package in ("pkg-a", "pkg-b")
        for _ in ("attempt facts", "scoring")
    ]


def test_score_run_finds_each_package_s_stream_through_event_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, keys, benchmark_set = two_scored_packages(tmp_path)
    folders: list[Path] = []
    real = events.event_stream

    def spy(folder: Path | str) -> Path:
        folders.append(Path(folder))
        return real(folder)

    monkeypatch.setattr(events, "event_stream", spy)

    score_run(run_dir, keys, benchmark_set)

    assert folders == [
        run_dir / package
        for package in ("pkg-a", "pkg-b")
        for _ in ("attempt facts", "scoring")
    ]


# --- 4: read_recording reads its log once, through replay_events (T159) --------------------


@pytest.mark.usefixtures("vocabulary")
def test_read_recording_replays_the_folder_s_event_log_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patched as the name `recording` calls, as `score_run`'s row patches its caller: the
    folder's own `EVENTS_FILE_NAME`, never resolved through `event_stream`, since a recording
    is never packed (RF-83), and with an `on_unreadable` hook, so a damaged log is never read as
    a whole one."""
    run = recorded_run(tmp_path)
    calls: list[tuple[Path, bool]] = []
    real = events.replay_events

    def spy(path: Path | str, after: int = 0, **hooks: Any) -> Iterator[AgentEvent]:
        calls.append((Path(path), callable(hooks.get("on_unreadable"))))
        return real(path, after, **hooks)

    def no_stream(folder: Path | str) -> Path:
        pytest.fail(f"read_recording resolved {folder} through event_stream")

    monkeypatch.setattr(recording, "replay_events", spy)
    monkeypatch.setattr(events, "event_stream", no_stream)

    recording.read_recording(run)

    assert calls == [(run / EVENTS_FILE_NAME, True)]


# --- 4: attempt_facts reads each attempt once, found through event_stream (T187) ------------


def test_attempt_facts_replays_each_attempt_s_stream_once_found_through_event_stream(
    tmp_path: Path, tmp_package_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from swreview.agent.providers.fake import ScriptedTurn

    attempts = [
        write_attempt(tmp_package_dir, tmp_path / name, (ScriptedTurn(text="Done."),))[0]
        for name in ("attempt-one", "attempt-two")
    ]
    folders: list[Path] = []
    replayed: list[Path] = []
    real_stream, real_replay = events.event_stream, events.replay_events

    def stream_spy(folder: Path | str) -> Path:
        folders.append(Path(folder))
        return real_stream(folder)

    def replay_spy(path: Path | str, after: int = 0, **hooks: Any) -> Iterator[AgentEvent]:
        replayed.append(Path(path))
        return real_replay(path, after, **hooks)

    monkeypatch.setattr(events, "event_stream", stream_spy)
    monkeypatch.setattr(events, "replay_events", replay_spy)

    for attempt in attempts:
        runner.attempt_facts(attempt.out_dir)
    runner.attempt_facts(tmp_path / "missing")

    assert folders == [*(attempt.out_dir for attempt in attempts), tmp_path / "missing"]
    assert replayed == [folder / EVENTS_FILE_NAME for folder in folders]


# --- 4: the structural half, no other reader of a stream under benchmark/ (T159, 81A, 85A) --

BENCHMARK_SOURCES = sorted(Path(recording.__file__).parent.glob("*.py"))

STREAM_NAMES = frozenset({"EVENTS_FILE_NAME", "PACKED_EVENTS_FILE_NAME"})
STREAM_STRINGS = frozenset({EVENTS_FILE_NAME, PACKED_EVENTS_FILE_NAME})
READERS = frozenset({"replay_events", "event_stream"})
GZIP_READS = frozenset({"open", "decompress", "GzipFile"})

EXEMPT_MODULES: frozenset[str] = frozenset({"streams.py"})
"""Packing is the one exception: it copies a stream's bytes and parses no event
(T214, T215; RF-83)."""

NAMED_SENTENCES: frozenset[tuple[str, str]] = frozenset({("scorecard.py", "NO_EVENT_STREAM")})
"""Owner decision 81A: the module-level sentences that may name the stream files, by module and
constant. Each must stay a module-level assignment whose value calls nothing, and no module uses
it, by any name, as a path (owner decision 85A)."""

SENTENCES = frozenset(name for _, name in NAMED_SENTENCES)

PATH_CALLS = frozenset(
    {"Path", "PurePath", "open", "replay_events", "event_stream", "read_text", "read_bytes"}
)
"""The calls that open, resolve or read a path: a named sentence anywhere in their arguments is a
path."""


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls_a_reader(function: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and _called_name(node) in READERS for node in ast.walk(function)
    )


def _folded(node: ast.AST) -> str | None:
    """The string an expression of constants spells: a string constant, a `+` of two, or an
    f-string holding constants only (owner decision 85A); `None` for anything else."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded(node.left), _folded(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts = [_folded(value) for value in node.values]
        return "".join(part for part in parts if part is not None) if None not in parts else None
    return None


def _is_stream_reference(node: ast.AST) -> bool:
    return (
        (isinstance(node, ast.Name) and node.id in STREAM_NAMES)
        or (isinstance(node, ast.Attribute) and node.attr in STREAM_NAMES | {"events_path"})
        or (
            isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr))
            and _folded(node) in STREAM_STRINGS
        )
    )


def _gzip_names(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    """The names the module binds to `gzip`, and to each of its reading functions, by any
    import: `import gzip as gz`, `from gzip import open as gopen` (owner decision 85A)."""
    modules: set[str] = set()
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == "gzip"}
        elif isinstance(node, ast.ImportFrom) and node.module == "gzip":
            for alias in node.names:
                if alias.name in GZIP_READS:
                    functions[alias.asname or alias.name] = alias.name
    return modules, functions


def _decompression(call: ast.Call, modules: set[str], functions: dict[str, str]) -> str | None:
    """The `gzip` reading function `call` calls, by whatever name, or `None`."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.attr if func.value.id in modules and func.attr in GZIP_READS else None
    if isinstance(func, ast.Name):
        return functions.get(func.id)
    return None


def _in_named_sentence(module: str, node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether `node` lies in the value of a module-level assignment 81A names."""
    while node in parents:
        parent = parents[node]
        if isinstance(parent, ast.Module):
            return (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and (module, node.targets[0].id) in NAMED_SENTENCES
            )
        node = parent
    return False


def _offences_in(module: str, source: str) -> list[str]:
    """Every reference to a stream outside a reader, and every decompression, in one module."""
    tree = ast.parse(source, filename=module)
    parents = _parents(tree)
    modules, functions = _gzip_names(tree)
    offences: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            read = _decompression(node, modules, functions)
            if read is not None:
                offences.append(f"{module} line {node.lineno}: calls gzip.{read}")
        if not _is_stream_reference(node):
            continue
        in_import = False
        enclosing: ast.AST | None = None
        cursor = node
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, (ast.Import, ast.ImportFrom)):
                in_import = True
            if enclosing is None and isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing = cursor
        if in_import:
            continue
        if enclosing is not None and _calls_a_reader(enclosing):
            continue
        if _in_named_sentence(module, node, parents):
            continue
        offences.append(
            f"{module} line {node.lineno}: {ast.unparse(node)} outside a function that "
            "reads through replay_events or event_stream"
        )
    return offences


def _names_a_sentence(node: ast.AST, names: set[str]) -> bool:
    return (isinstance(node, ast.Name) and node.id in names) or (
        isinstance(node, ast.Attribute) and node.attr in SENTENCES
    )


def _sentence_names(module: str, tree: ast.AST) -> set[str]:
    """Every name a named sentence goes by in `module`: its own in its module, each import of it
    under any name, and each name assigned a value that holds one of those (owner decision 85A)."""
    names = {name for owner, name in NAMED_SENTENCES if owner == module}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname or alias.name for alias in node.names if alias.name in SENTENCES}
    grew = True
    while grew:
        grew = False
        for node in ast.walk(tree):
            bound = _binding(node)
            if bound is None:
                continue
            targets, value = bound
            if any(_names_a_sentence(part, names) for part in ast.walk(value)):
                for name in (name for target in targets for name in _bound_names(target)):
                    if name not in names:
                        names.add(name)
                        grew = True
    return names


def _binding(node: ast.AST) -> tuple[list[ast.expr], ast.expr] | None:
    """An assignment's targets and value: plain, annotated, or a walrus (owner decision 92A)."""
    if isinstance(node, ast.Assign):
        return list(node.targets), node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return [node.target], node.value
    if isinstance(node, ast.NamedExpr):
        return [node.target], node.value
    return None


def _bound_names(target: ast.expr) -> list[str]:
    """The names a target binds: a name, or each name of a tuple or list, starred included."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _bound_names(element)]
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return []


def _sentence_offences(module: str, source: str) -> list[str]:
    """Every use of a named sentence, by any name, as a path: an operand of `/`, or anywhere in
    the arguments of a call that opens, resolves or reads a path, an f-string's included."""
    tree = ast.parse(source, filename=module)
    names = _sentence_names(module, tree)
    parents = _parents(tree)
    offences: list[str] = []
    for node in ast.walk(tree):
        is_use = _names_a_sentence(node, names) and not (
            isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)
        )
        if not is_use:
            continue
        child, cursor = node, parents.get(node)
        while cursor is not None and not isinstance(cursor, ast.stmt):
            if isinstance(cursor, ast.BinOp) and isinstance(cursor.op, ast.Div):
                offences.append(
                    f"{module} line {node.lineno}: {ast.unparse(node)} is used as a path"
                )
            if (
                isinstance(cursor, ast.Call)
                and child is not cursor.func
                and _called_name(cursor) in PATH_CALLS
            ):
                offences.append(
                    f"{module} line {node.lineno}: {ast.unparse(node)} is passed to "
                    f"{_called_name(cursor)}"
                )
            child, cursor = cursor, parents.get(cursor)
    return offences


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_there_are_benchmark_modules_to_read() -> None:
    names = {path.name for path in BENCHMARK_SOURCES}

    assert {"recording.py", "scorecard.py", "compare.py"} <= names


def test_no_module_under_benchmark_reads_a_stream_but_through_the_one_reader() -> None:
    """RF-29 and RF-83: a stream's file name, an `events_path` attribute or the files' names,
    literal or spelled by constants, appear only in an import or inside a function that reads
    through `replay_events` or resolves through `event_stream`, and no module decompresses a
    stream itself, under any name it imports `gzip` by."""
    offences = [
        offence
        for path in BENCHMARK_SOURCES
        if path.name not in EXEMPT_MODULES
        for offence in _offences_in(path.name, _source(path))
    ]

    assert offences == []


@pytest.mark.parametrize("module, name", sorted(NAMED_SENTENCES))
def test_every_named_sentence_is_one_module_level_assignment_calling_nothing(
    module: str, name: str
) -> None:
    """81A's allowance holds only while the constant is what it was allowed as."""
    path = Path(recording.__file__).parent / module
    tree = ast.parse(_source(path), filename=str(path))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [target.id for target in node.targets if isinstance(target, ast.Name)] == [name]
    ]
    assert len(assignments) == 1, f"{module}: {name} is not one module-level assignment"
    calls = [
        ast.unparse(node) for node in ast.walk(assignments[0].value) if isinstance(node, ast.Call)
    ]
    assert calls == [], f"{module}: {name} calls {calls}"


def test_no_module_under_benchmark_uses_a_named_sentence_as_a_path() -> None:
    """Owner decision 85A: every module, every name the sentence goes by."""
    offences = [
        offence
        for path in BENCHMARK_SOURCES
        for offence in _sentence_offences(path.name, _source(path))
    ]

    assert offences == []


@pytest.mark.parametrize(
    ("source", "offence"),
    [
        ("import gzip as gz\ndef read(path):\n    return gz.open(path)\n", "calls gzip.open"),
        (
            "from gzip import decompress as inflate\ndef read(data):\n    return inflate(data)\n",
            "calls gzip.decompress",
        ),
        ('NAME = "events" + ".jsonl"\n', "outside a function"),
        ('NAME = "events.json" + "l" + ".gz"\n', "outside a function"),
        ('NAME = f"events.jsonl"\n', "outside a function"),
    ],
    ids=["gzip-as", "from-gzip-as", "concatenated", "concatenated-packed", "f-string"],
)
def test_the_structural_rule_sees_through_aliases_and_concatenations(
    source: str, offence: str
) -> None:
    found = _offences_in("probe.py", source)

    assert found and all(offence in line for line in found), found


@pytest.mark.parametrize(
    ("source", "offence"),
    [
        (
            "from pathlib import Path\n"
            "from swreview.benchmark.scorecard import NO_EVENT_STREAM as reason\n"
            "def where():\n"
            '    return Path(f"{reason}")\n',
            "is passed to Path",
        ),
        (
            "from swreview.benchmark import scorecard\n"
            "def where(folder):\n"
            "    return folder / scorecard.NO_EVENT_STREAM\n",
            "is used as a path",
        ),
        (
            "from swreview.benchmark.scorecard import NO_EVENT_STREAM\n"
            "REASON = NO_EVENT_STREAM\n"
            "def where():\n"
            '    return open(f"x-{REASON}")\n',
            "is passed to open",
        ),
    ],
    ids=["imported-as", "attribute", "assigned-alias"],
)
def test_a_named_sentence_used_as_a_path_is_found_by_any_name(source: str, offence: str) -> None:
    found = _sentence_offences("probe.py", source)

    assert found and all(offence in line for line in found), found


def test_a_named_sentence_returned_as_a_reason_is_no_path() -> None:
    source = (
        "from swreview.benchmark.scorecard import NO_EVENT_STREAM\n"
        "def why():\n"
        "    return None, NO_EVENT_STREAM\n"
    )

    assert _sentence_offences("probe.py", source) == []


# --- 4: the report reads each package's stream once, found through event_stream (T166) -----


def test_the_report_replays_each_transcript_s_stream_once_found_through_event_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over two scored run folders `studies.write_run` writes: each spy sees exactly one call per
    transcript page, `event_stream` given the package folder and `replay_events` the path it
    returned and an `on_unreadable` hook."""
    packages = (PackageSpec(package_id="pkg-a"), PackageSpec(package_id="pkg-b"))
    runs = [
        write_run(tmp_path / "runs", RunSpec(run=name, arm=arm, packages=packages))
        for name, arm in (("off-1", "off"), ("on-1", "on"))
    ]
    folders: list[Path] = []
    replayed: list[tuple[Path, bool]] = []
    real_stream, real_replay = events.event_stream, events.replay_events

    def stream_spy(folder: Path | str) -> Path:
        folders.append(Path(folder))
        return real_stream(folder)

    def replay_spy(path: Path | str, after: int = 0, **hooks: Any) -> Iterator[AgentEvent]:
        replayed.append((Path(path), callable(hooks.get("on_unreadable"))))
        return real_replay(path, after, **hooks)

    monkeypatch.setattr(report_page, "event_stream", stream_spy)
    monkeypatch.setattr(report_page, "replay_events", replay_spy)

    built = report_page.build_report(runs, tmp_path / "report")

    expected = [run / package.package_id for run in runs for package in packages]
    assert built.transcripts == len(expected) == 4
    assert folders == expected
    assert replayed == [(folder / EVENTS_FILE_NAME, True) for folder in expected]


@pytest.mark.parametrize(
    "source",
    [
        "from swreview.benchmark.scorecard import NO_EVENT_STREAM\n"
        "REASON: str = NO_EVENT_STREAM\n"
        "def where():\n"
        "    return open(REASON)\n",
        "from swreview.benchmark.scorecard import NO_EVENT_STREAM\n"
        "REASON, OTHER = NO_EVENT_STREAM, 1\n"
        "def where():\n"
        "    return open(REASON)\n",
        "from swreview.benchmark.scorecard import NO_EVENT_STREAM\n"
        "def where():\n"
        "    if (reason := NO_EVENT_STREAM):\n"
        "        return open(reason)\n",
    ],
    ids=["annotated", "tuple-target", "walrus"],
)
def test_92a_the_alias_walk_follows_annotated_tuple_and_walrus_bindings(source: str) -> None:
    found = _sentence_offences("probe.py", source)

    assert found and all("is passed to open" in line for line in found), found
