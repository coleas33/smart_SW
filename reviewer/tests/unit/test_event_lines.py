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

Row 4 (a spy counting one call per package from `score_run`, per transcript from the report
and per `read_recording`, per attempt from `attempt_facts`, and the structural "no other
reader of `events.jsonl` under `benchmark/`") and 6's `score_run` spy land with their
callers (T086, T159, T166, T187).
"""

from __future__ import annotations

import gzip
import re
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swreview.agent import events
from swreview.agent.events import (
    EVENTS_FILE_NAME,
    PACKED_EVENTS_FILE_NAME,
    event_stream,
    replay_events,
)
from swreview.agent.providers import AgentEvent
from swreview.chat import sessions

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
