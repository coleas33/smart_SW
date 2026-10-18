"""T007: five ticked-review baselines captured before any 015 product edit.

The raw UTF-8 file strings retain their actual Windows CRLF/LF bytes; on another platform the
native-newline files are spelled as Windows writes them (`as_windows_writes`). Only times,
durations, UUIDs and this harness's explicit run/profile paths are normalized;
fictional evidence paths and unknown absolute paths remain visible.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.agent import events, runner
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.report.session import load_session
from swreview.tools import context
from tests.support.questions_package import QuestionsPackage, build_questions_package
from tests.support.recording_provider import RecordingProvider
from tests.support.roles_review import PLATE_ID
from tests.unit import test_chat_server as chat
from tests.unit.test_fake_provider import frozen_clock

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir


@pytest.fixture(autouse=True)
def baseline_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """One fictional clock preserves timestamp identity without wall-clock collisions."""
    counter = 0
    lock = threading.Lock()
    start = datetime(2026, 10, 12, tzinfo=UTC)

    def now() -> datetime:
        nonlocal counter
        with lock:
            counter += 1
            return start + timedelta(milliseconds=counter)

    class ClockDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            stamped = now()
            return stamped.astimezone(tz) if tz is not None else stamped.replace(tzinfo=None)

    monkeypatch.setattr(events, "utc_now", now)
    monkeypatch.setattr(runner, "utc_now", now)
    monkeypatch.setattr(runner, "datetime", ClockDatetime)
    monkeypatch.setattr(context, "datetime", ClockDatetime)


OUTPUTS = ("events.jsonl", "session.json", "report.md", "attention.json")
TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
)
UUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)
DURATION = re.compile(
    r'(?P<prefix>(?:\\?")(?:elapsed_s|latency_s|unattended_runtime_minutes)'
    r'(?:\\?")\s*:\s*)(?P<value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r"|(?P<report>- Unattended runtime minutes: )"
    r"(?P<minutes>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)
TRACE_DURATION = re.compile(
    r"(?m)^(?P<prefix>\| \d+ \| [^|\r\n]+ \| (?:ok|error) \| )"
    r"(?P<value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?P<tail> \|)(?=\r?$)"
)


class Normalizer:
    """Normalize known volatility without guessing which absolute paths are private."""

    def __init__(self, folder: Path, profile: Path) -> None:
        self.paths: list[tuple[re.Pattern[str], str]] = []
        for path, placeholder in ((profile, "<PROFILE_PATH>"), (folder, "<RUN_DIR>")):
            # The same path occurs as prose, JSON and JSON encoded inside history.
            raw = str(path)
            for _ in range(3):
                # These paths are complete JSON values or complete lines in this capture.
                # Spaces and commas are legal sibling-name characters, not boundaries.
                start = r'(?:(?<=\")|(?<=[\r\n])|^)'
                end = r'(?=$|[\r\n]|(?:\\)*\")'
                pattern = re.compile(start + re.escape(raw) + end)
                self.paths.append((pattern, placeholder))
                raw = raw.replace("\\", "\\\\")
        self.values: dict[str, dict[str, str]] = {"TIME": {}, "UUID": {}, "DURATION": {}}
        self.duration_count = 0

    def placeholder(self, kind: str, value: str) -> str:
        if kind == "DURATION":
            # Equality of two measured durations is volatile; preserve each occurrence.
            self.duration_count += 1
            return f"<DURATION_{self.duration_count}>"
        values = self.values[kind]
        return values.setdefault(value, f"<{kind}_{len(values) + 1}>")

    def text(self, value: str, *, report: bool = False) -> str:
        for pattern, placeholder in sorted(
            self.paths, key=lambda entry: len(entry[0].pattern), reverse=True
        ):
            value = pattern.sub(lambda match, replacement=placeholder: replacement, value)
        value = TIME.sub(lambda match: self.placeholder("TIME", match[0]), value)
        value = UUID.sub(lambda match: self.placeholder("UUID", match[0]), value)

        def duration(match: re.Match[str]) -> str:
            prefix = match["prefix"] or match["report"]
            number = match["value"] or match["minutes"]
            return prefix + self.placeholder("DURATION", number)

        value = DURATION.sub(duration, value)
        return self.report_trace(value) if report else value

    def report_trace(self, value: str) -> str:
        """Only this report section and its exact header identify measured trace cells."""
        in_trace = False
        in_table = False
        lines = []
        for line in value.splitlines(keepends=True):
            content = line.rstrip("\r\n")
            if content.startswith("## "):
                in_trace = content == "## Investigation Trace"
                in_table = False
            elif in_trace and content == "| Index | Tool | Status | Elapsed (s) |":
                in_table = True
            elif in_table and content.startswith("|"):
                line = TRACE_DURATION.sub(
                    lambda match: (
                        match["prefix"]
                        + self.placeholder("DURATION", match["value"])
                        + match["tail"]
                    ),
                    line,
                )
            elif in_table:
                in_table = False
            lines.append(line)
        return "".join(lines)

    def __call__(self, value: Any, path: tuple[str, ...] = ()) -> Any:
        if isinstance(value, str):
            return self.text(value, report=path == ("files", "report.md"))
        if isinstance(value, Mapping):
            return {key: self(item, (*path, key)) for key, item in value.items()}
        if isinstance(value, list):
            return [self(item, path) for item in value]
        return value


class ProviderWrapper:
    """Hold or fail a scripted request; the shared helper remains the only recorder."""

    def __init__(
        self,
        provider: RecordingProvider,
        *,
        fail_after_round: bool = False,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.provider = provider
        self.fail_after_round = fail_after_round
        self.started = started
        self.release = release

    def __getattr__(self, name: str) -> Any:
        return getattr(self.provider, name)

    def run(self, **kwargs: Any) -> Any:
        if self.started is not None:
            self.started.set()
            assert self.release is not None and self.release.wait(chat.TIMEOUT_S)
        if self.fail_after_round:
            callback = kwargs["on_event"]

            def completed(event: str, body: Mapping[str, Any]) -> None:
                callback(event, body)
                if event == "usage":
                    raise RuntimeError("Fictional request failed after one completed round.")

            kwargs["on_event"] = completed
        return self.provider.run(**kwargs)


def prepare(
    app: Any, folder: Path, script: tuple[ScriptedTurn, ...], **wrapper: Any
) -> QuestionsPackage:
    fixture = build_questions_package(folder)
    provider = RecordingProvider(
        script,
        explanation_script=(ScriptedTurn(text='{"explanations": []}'),),
        clock=frozen_clock,
    )
    app.state.characterization_provider = provider
    app.state.characterization_fixture = fixture
    app.state.characterization_response = None
    adapter = ProviderWrapper(provider, **wrapper) if wrapper else provider
    app.state.server.provider_factory = lambda settings: adapter
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    return fixture


def begin(client: TestClient, fixture: QuestionsPackage, **keys: Any) -> str:
    body = chat.session_body(
        fixture.folder,
        standards_profile=str(fixture.profile),
        bridge={"pipe": "FICT-review-pipe", "secret": None},
        **keys,
    )
    response = client.post("/sessions", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["chat_id"])


def play_ticked_review(
    client: TestClient, app: Any, run_dir: Path, *, new_keys: bool = False
) -> Path:
    """The real success run, returned raw for T013's session-byte round trip."""
    fixture = prepare(
        app,
        run_dir,
        (
            ScriptedTurn(text="The fictional bracket review is ready."),
            ScriptedTurn(text="Regraded after the supplied answer."),
            ScriptedTurn(
                text="The fictional follow-up is complete.",
                tool_calls=(
                    ScriptedToolCall(
                        "record_drawing_finding",
                        {
                            "document_id": PLATE_ID,
                            "sheet": "FICT-sheet",
                            "observed": "The fictional drawing omits its finish note.",
                            "requirement": "The fictional drawing states its surface finish.",
                            "source_refs": [{"document_id": PLATE_ID, "sheet": "FICT-sheet"}],
                            "status": "suspected",
                            "recommended_action": "Add the fictional finish note.",
                        },
                    ),
                ),
            ),
        ),
    )
    keys = {"send_when_checked": True, "recheck": False} if new_keys else {}
    chat_id = begin(client, fixture, **keys)
    chat.settle(client, chat_id)
    session = load_session(run_dir / "session.json")
    question = next(item for item in session.evidence_requests if "All bought" in item.options)
    response = client.post(
        f"/sessions/{chat_id}/evidence/{question.id}", json={"answer": "All bought"}
    )
    assert response.status_code == 202, response.text
    chat.settle(client, chat_id)
    response = client.post(
        f"/sessions/{chat_id}/messages", json={"text": "Explain the remaining fictional checks."}
    )
    assert response.status_code == 202, response.text
    chat.settle(client, chat_id)
    log = app.state.characterization_provider.log
    assert [entry.presentation for entry in log] == [False, True, False, True, False, True]
    assert "Checks first graded again after your answer: withdrew" in str(log[2].encoded_history)
    assert any(
        finding.observed == "The fictional drawing omits its finish note."
        for finding in load_session(run_dir / "session.json").findings
    )
    return run_dir


def play_factory_failure(client: TestClient, app: Any, run_dir: Path) -> Path:
    fixture = prepare(app, run_dir, ())

    def no_key(settings: Any) -> Any:
        raise RuntimeError("The fictional provider key is unavailable.")

    app.state.server.provider_factory = no_key
    response = client.post(
        "/sessions", json=chat.session_body(run_dir, standards_profile=str(fixture.profile))
    )
    assert response.status_code == 502, response.text
    app.state.characterization_response = {
        "status": response.status_code,
        "body": response.json(),
        "listing": sorted(path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*")),
    }
    assert not app.state.characterization_provider.log
    return run_dir


def play_first_request_failure(client: TestClient, app: Any, run_dir: Path) -> Path:
    fixture = prepare(app, run_dir, ())
    chat_id = begin(client, fixture)
    assert chat.settle(client, chat_id) == "failed"
    assert len(app.state.characterization_provider.log) == 1
    assert not any(
        json.loads(line)["type"] == "usage"
        for line in (run_dir / "events.jsonl").read_text().splitlines()
    )
    return run_dir


def play_completed_round_failure(client: TestClient, app: Any, run_dir: Path) -> Path:
    fixture = prepare(
        app,
        run_dir,
        (ScriptedTurn(text="Never reaches this closing text."),),
        fail_after_round=True,
    )
    chat_id = begin(client, fixture)
    assert chat.settle(client, chat_id) == "failed"
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert len([event for event in events if event["type"] == "usage"]) == 1
    assert len(app.state.characterization_provider.log) == 1
    return run_dir


def play_stop_at_tool_boundary(client: TestClient, app: Any, run_dir: Path) -> Path:
    started, release = threading.Event(), threading.Event()
    fixture = prepare(
        app,
        run_dir,
        (
            ScriptedTurn(
                text="Never finished.", tool_calls=(ScriptedToolCall("get_package_summary"),)
            ),
        ),
        started=started,
        release=release,
    )
    chat_id = begin(client, fixture)
    chat.wait_until(started.is_set, "the first request to reach its hold")
    try:
        response = client.post(f"/sessions/{chat_id}/stop")
        assert response.status_code == 202, response.text
    finally:
        release.set()
    assert chat.settle(client, chat_id) == "ended"
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert (
        next(event["body"]["reason"] for event in events if event["type"] == "turn.ended")
        == "stopped"
    )
    assert len(app.state.characterization_provider.log) == 1
    return run_dir


NATIVE_NEWLINE_OUTPUTS = frozenset({"events.jsonl", "session.json", "report.md"})
"""The outputs the product writes with `os.linesep` line endings; `attention.json` is LF.

`save_session` turns each `\\n` into `os.linesep` on purpose (it matches the text writer it
replaced), and `events.jsonl` and `report.md` are text-mode writes, so on Windows these three
files hold CRLF and elsewhere LF. The goldens hold the Windows bytes, the pilot seat's.
"""


def as_windows_writes(text: str, name: str) -> str:
    """`text` as this file's bytes read on Windows, from whichever platform wrote it.

    Each file's line endings are checked against the rule it is written by before anything
    is translated, so a product change to them still fails here on every platform: a native
    file must end every line with `os.linesep` and an LF file must hold no carriage return.
    Only then is a native file's `os.linesep` spelled CRLF, which on Windows changes nothing.
    """
    if name in NATIVE_NEWLINE_OUTPUTS:
        assert text.count("\n") == text.count(os.linesep), f"{name}: not all {os.linesep!r}"
        return text.replace(os.linesep, "\n").replace("\n", "\r\n")
    assert "\r" not in text, f"{name}: a carriage return in an LF-only file"
    return text


def captured(app: Any, folder: Path) -> dict[str, Any]:
    provider = app.state.characterization_provider
    raw = {
        "requests": [
            {
                "presentation": entry.presentation,
                "system": entry.system,
                "encoded_tools": entry.encoded_tools.decode("utf-8"),
                "encoded_history": [item.decode("utf-8") for item in entry.encoded_history],
            }
            for entry in provider.log
        ],
        "files": {
            name: as_windows_writes((folder / name).read_bytes().decode("utf-8"), name)
            for name in OUTPUTS
            if (folder / name).is_file()
        },
    }
    if app.state.characterization_response is not None:
        raw["response"] = app.state.characterization_response
    fixture = app.state.characterization_fixture
    return Normalizer(folder, fixture.profile)(raw)


@pytest.mark.parametrize("new_keys", [False, True], ids=["old-body", "host-body"])
def test_success(
    client: TestClient, app: Any, run_dir: Path, data_regression: Any, new_keys: bool
) -> None:
    folder = play_ticked_review(client, app, run_dir, new_keys=new_keys)
    data_regression.check(captured(app, folder), basename="success")


@pytest.mark.parametrize(
    "scenario",
    [
        play_factory_failure,
        play_first_request_failure,
        play_completed_round_failure,
        play_stop_at_tool_boundary,
    ],
    ids=[
        "factory-failure",
        "first-request-failure",
        "completed-round-failure",
        "stop-at-tool-boundary",
    ],
)
def test_failure_or_stop(
    client: TestClient, app: Any, run_dir: Path, data_regression: Any, scenario: Any
) -> None:
    folder = scenario(client, app, run_dir)
    data_regression.check(captured(app, folder), basename=scenario.__name__.removeprefix("play_"))


def test_normalization_preserves_unknown_paths_stable_content_and_raw_newlines(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "run"
    profile = folder / "profile.yaml"
    normalizer = Normalizer(folder, profile)
    raw = str(folder) + "\r\n" + str(profile) + "\nC:\\Fictional\\FICT-7000.SLDASM\r\n"
    raw += "D:\\Unexpected\\keep-me.yaml\n/unknown/workspace/keep-me\n"
    raw += '"elapsed_s": 0.012, "steps": 7\n'
    raw += "2026-10-12T13:30:00.123+05:30 2026-10-12T13:30:00.123+05:30\n"
    raw += "12345678-1234-4234-8234-123456789abc 12345678-1234-4234-8234-123456789abc"
    raw += "\n| 1 | check_hygiene | ok | 0.003123 |\r\n"
    raw += str(folder) + "-unrelated/keep.txt\n" + str(profile) + ".bak\n"
    raw += str(folder / "unrecognized" / "keep.txt") + "\n"
    raw += str(folder) + " archive/keep.txt\n" + str(profile) + ",backup\n"
    assert normalizer(raw) == (
        "<RUN_DIR>\r\n<PROFILE_PATH>\nC:\\Fictional\\FICT-7000.SLDASM\r\n"
        "D:\\Unexpected\\keep-me.yaml\n/unknown/workspace/keep-me\n"
        '"elapsed_s": <DURATION_1>, "steps": 7\n'
        "<TIME_1> <TIME_1>\n<UUID_1> <UUID_1>"
        "\n| 1 | check_hygiene | ok | 0.003123 |\r\n"
        + str(folder)
        + "-unrelated/keep.txt\n"
        + str(profile)
        + ".bak\n"
        + str(folder / "unrecognized" / "keep.txt")
        + "\n"
        + str(folder)
        + " archive/keep.txt\n"
        + str(profile)
        + ",backup\n"
    )
    assert Normalizer(folder, profile)(
        json.dumps({"run": str(folder), "profile": str(profile)})
    ) == json.dumps({"run": "<RUN_DIR>", "profile": "<PROFILE_PATH>"})
    assert Normalizer(folder, profile)(
        json.dumps(json.dumps({"profile": str(profile)}))
    ) == json.dumps(json.dumps({"profile": "<PROFILE_PATH>"}))


def test_only_the_captured_reports_named_trace_column_is_a_duration(tmp_path: Path) -> None:
    table = (
        "| Index | Tool | Status | Elapsed (s) |\r\n"
        "| --- | --- | --- | --- |\r\n"
        "| 1 | check_hygiene | ok | 0.003123 |\r\n"
    )
    stable = "| 1 | fixtures | ok | 7 |\r\n"
    report = (
        "## Fixture Counts\r\n" + table + stable + "\r\n"
        "## Investigation Trace\r\n\r\n" + table + "\r\n"
        "## Stable Content\r\n" + stable
        + "## Investigation Trace\r\n"
        + "| Index | Tool | Status | Count |\r\n" + stable
    )
    raw = {"requests": [table, stable], "files": {"report.md": report, "other.md": table}}
    actual = Normalizer(tmp_path / "run", tmp_path / "profile.yaml")(raw)
    assert actual["requests"] == [table, stable]
    assert actual["files"]["other.md"] == table
    assert actual["files"]["report.md"] == report.replace(
        "## Investigation Trace\r\n\r\n" + table,
        "## Investigation Trace\r\n\r\n" + table.replace("0.003123", "<DURATION_1>"),
    )


@pytest.mark.parametrize("linesep", ["\r\n", "\n"], ids=["windows", "posix"])
@pytest.mark.parametrize("name", sorted(NATIVE_NEWLINE_OUTPUTS))
def test_a_native_newline_file_reads_as_windows_writes_it_from_either_platform(
    monkeypatch: pytest.MonkeyPatch, linesep: str, name: str
) -> None:
    monkeypatch.setattr(os, "linesep", linesep)
    written = "first\nsecond\n\nlast\n".replace("\n", linesep)
    assert as_windows_writes(written, name) == "first\r\nsecond\r\n\r\nlast\r\n"


@pytest.mark.parametrize("name", sorted(NATIVE_NEWLINE_OUTPUTS))
def test_a_native_newline_file_with_a_bare_lf_on_windows_still_fails(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(os, "linesep", "\r\n")
    with pytest.raises(AssertionError, match=f"{name}: not all"):
        as_windows_writes("first\r\nsecond\n", name)


@pytest.mark.parametrize("linesep", ["\r\n", "\n"], ids=["windows", "posix"])
def test_attention_json_is_lf_on_every_platform_and_a_carriage_return_fails(
    monkeypatch: pytest.MonkeyPatch, linesep: str
) -> None:
    monkeypatch.setattr(os, "linesep", linesep)
    assert "attention.json" not in NATIVE_NEWLINE_OUTPUTS
    assert as_windows_writes('{\n  "rows": []\n}\n', "attention.json") == '{\n  "rows": []\n}\n'
    with pytest.raises(AssertionError, match="attention.json: a carriage return"):
        as_windows_writes('{\r\n  "rows": []\r\n}\r\n', "attention.json")
