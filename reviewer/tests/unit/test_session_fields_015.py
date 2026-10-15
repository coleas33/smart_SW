"""015 records are additive, closed, and saved without changing existing bytes.

The SHA-256 values below were captured with pre-feature ``save_session`` on the
accepted 010/014 baseline, before T014. The Windows result contains 127 CRLFs;
the other value is its LF spelling. The ticked scenario is read before its
characterization normalizer ever runs.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from swreview import atomic
from swreview.prerun import LiveOutcome
from swreview.report import session as records
from tests.unit import test_chat_server as chat
from tests.unit.test_session import build_session, session_validator
from tests.unit.test_session_fields_013 import committed_sessions

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir

WHEN = datetime(2026, 10, 8, 9, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
DOCUMENT = {"path": r"C:\Fictional\FICT-7000.SLDASM", "configuration": "Default"}
BASELINE_SAVE_SHA256 = {
    "nt": "a93738400f23128dfe7eb9a827a6eac03373abea6a8592e8823963e835aa0969",
    "posix": "25467c28c50babadaee86094437fc0383bede4759378f8cc3ed866dc421a8ca6",
}


def status(**changes: Any) -> Any:
    return records.ModelStatus(
        **{"state": "not_sent", "document": DOCUMENT, "checked_at": WHEN, **changes}
    )


def test_model_status_required_fields_and_default_omissions() -> None:
    dumped = status().model_dump(mode="json")
    assert dumped == {
        "state": "not_sent", "document": DOCUMENT, "checked_at": WHEN.isoformat()
    }
    for field in ("state", "document", "checked_at"):
        incomplete = {key: value for key, value in dumped.items() if key != field}
        with pytest.raises(ValidationError):
            records.ModelStatus.model_validate_json(json.dumps(incomplete))


@pytest.mark.parametrize("state", ["not_sent", "send_failed", "sent"])
def test_each_model_state_is_explicit(state: str) -> None:
    assert status(state=state).state == state


@pytest.mark.parametrize("state", ["waiting", "running", "", None, 1])
def test_unknown_model_states_are_refused(state: Any) -> None:
    with pytest.raises(ValidationError):
        status(state=state)


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": True},
        {"document": {**DOCUMENT, "unknown": True}},
        {"document": {"path": DOCUMENT["path"]}},
        {"profile": {"path": r"C:\Fictional\profile.yaml"}},
        {"profile": {"path": "FICT-profile", "sha256": "bad"}},
        {"profile": {"path": "FICT-profile", "sha256": None, "unknown": True}},
        {"opening_finding_ids": ["ER-001"]},
        {"opening_finding_ids": ["F--1"]},
    ],
)
def test_model_status_refuses_incomplete_or_unrecognized_values(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        status(**changes)


@pytest.mark.parametrize("digest", [None, "a" * 64])
def test_profile_identity_keeps_its_path_and_digest(digest: str | None) -> None:
    profile = {"path": r"C:\Fictional\FICT-profile.yaml", "sha256": digest}
    assert status(profile=profile).model_dump(mode="json")["profile"] == profile


def test_complete_model_status_retains_times_offset_failures_and_opening_order() -> None:
    failure = records.SendFailure(at=WHEN, error_class="FictFailure", reason="Fictional reason")
    estimate = records.SendEstimate(input_tokens=13151, encoding="o200k_base", approximate=False)
    earlier = UUID("12345678-1234-4234-8234-123456789abc")
    model_status = status(
        state="sent", rechecked_from=earlier, failures=[failure],
        sent_at=WHEN + timedelta(minutes=1), estimate=estimate,
        opening_finding_ids=["F-010", "F-001"],
    )
    dumped = model_status.model_dump(mode="json")
    assert dumped["checked_at"] == WHEN.isoformat()
    assert dumped["sent_at"] == (WHEN + timedelta(minutes=1)).isoformat()
    assert dumped["rechecked_from"] == str(earlier)
    assert dumped["failures"] == [
        {"at": WHEN.isoformat(), "error_class": "FictFailure", "reason": "Fictional reason"}
    ]
    assert dumped["estimate"] == {
        "input_tokens": 13151, "encoding": "o200k_base", "approximate": False
    }
    assert dumped["opening_finding_ids"] == ["F-010", "F-001"]


@pytest.mark.parametrize("tokens", [None, 0, 1, 13151])
def test_estimate_keeps_unknown_distinct_from_zero(tokens: int | None) -> None:
    estimate = records.SendEstimate(input_tokens=tokens, encoding="o200k_base", approximate=True)
    assert estimate.model_dump() == {
        "input_tokens": tokens, "encoding": "o200k_base", "approximate": True
    }


@pytest.mark.parametrize(
    "changes", [{"input_tokens": -1}, {"input_tokens": "1"}, {"encoding": "unknown"}]
)
def test_estimate_refuses_bad_count_or_encoding(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        records.SendEstimate(**{
            "input_tokens": 1, "encoding": "o200k_base", "approximate": False, **changes
        })


@pytest.mark.parametrize("name", ["SendFailure", "SendEstimate", "DrawingOutcome"])
def test_new_record_models_refuse_unknown_keys(name: str) -> None:
    values = {
        "SendFailure": {"at": WHEN, "error_class": "FictFailure", "reason": "Fictional"},
        "SendEstimate": {"input_tokens": None, "encoding": "o200k_base", "approximate": False},
        "DrawingOutcome": {"file": "FICT-7000.SLDDRW", "outcome": "Fictional drawing read"},
    }
    with pytest.raises(ValidationError):
        getattr(records, name)(**values[name], unknown=True)


@pytest.mark.parametrize("not_attempted", [None, "no_bridge", "not_assembly"])
def test_live_outcome_round_trip_carries_every_dataclass_field(not_attempted: str | None) -> None:
    outcome = LiveOutcome(
        configuration="FICT-config", settings={"treat_coincident_as_interference": True},
        step_index=12, not_attempted=not_attempted, groups=3, rows_detected=5,
        rows_added=4, rows_collided=1, error="Fictional call error",
        persist_error="Fictional write error",
    )
    record = outcome.as_record()
    assert set(type(record).model_fields) == {field.name for field in fields(LiveOutcome)}
    assert {field.name: getattr(record, field.name) for field in fields(LiveOutcome)} == {
        field.name: getattr(outcome, field.name) for field in fields(LiveOutcome)
    }
    assert LiveOutcome.from_record(record) == outcome


@pytest.mark.parametrize("field", ["groups", "rows_detected", "rows_added", "rows_collided"])
def test_live_counts_cannot_be_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        records.LiveDetectionRecord(configuration="Default", settings={}, **{field: -1})


def test_new_session_fields_are_omitted_by_default_and_model_status_follows_provider() -> None:
    session = build_session()
    assert not {"model_status", "live_detection", "drawing_outcomes"} & set(
        session.model_dump(mode="json")
    )
    names = list(records.ReviewSession.model_fields)
    assert names[names.index("provider_info") + 1] == "model_status"


@pytest.mark.parametrize("state", ["not_sent", "send_failed", "sent"])
def test_new_values_validate_and_round_trip_without_moving_the_model_status(
    state: str, tmp_path: Path
) -> None:
    session = build_session(
        model_status=status(
            state=state,
            profile={"path": "FICT-profile.yaml", "sha256": "a" * 64},
            rechecked_from=UUID("12345678-1234-4234-8234-123456789abc"),
            failures=[records.SendFailure(at=WHEN, error_class="FictFailure", reason="Fictional")],
            sent_at=WHEN + timedelta(minutes=1),
            estimate=records.SendEstimate(
                input_tokens=None, encoding="o200k_base", approximate=True
            ),
            opening_finding_ids=["F-010", "F-001"],
        ),
        live_detection=LiveOutcome(configuration="Default", settings={}).as_record(),
        drawing_outcomes=[records.DrawingOutcome(file="FICT-7000.SLDDRW", outcome="Read")],
    )
    path = records.save_session(session, tmp_path / "session.json")
    payload = json.loads(path.read_bytes())
    session_validator().validate(payload)
    assert records.load_session(path) == session
    keys = list(payload)
    assert keys[keys.index("provider_info") + 1] == "model_status"
    assert path.read_bytes().index(b'"model_status"') < path.read_bytes().index(b'"findings"')


@pytest.mark.parametrize("path", committed_sessions(), ids=lambda path: path.parent.name)
def test_committed_session_keeps_its_existing_bytes(path: Path, tmp_path: Path) -> None:
    written = records.save_session(records.load_session(path), tmp_path / "session.json")
    assert written.read_bytes() == path.read_bytes()


def test_old_save_bytes_are_the_captured_pre_feature_output(tmp_path: Path) -> None:
    raw = records.save_session(build_session(), tmp_path / "session.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BASELINE_SAVE_SHA256[os.name]


def test_save_uses_the_shared_atomic_writer_with_exact_baseline_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, bytes]] = []
    write = atomic.write_atomic

    def spy(path: Path, data: bytes) -> None:
        calls.append((path, data))
        write(path, data)

    monkeypatch.setattr(atomic, "write_atomic", spy)
    path = records.save_session(build_session(), tmp_path / "nested" / "session.json")
    assert calls == [(path, path.read_bytes())]
    assert hashlib.sha256(calls[0][1]).hexdigest() == BASELINE_SAVE_SHA256[os.name]


def test_failed_replace_keeps_the_previous_session_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "session.json"
    path.write_bytes(b"the old canonical record\r\n")

    def fail(*args: Any) -> None:
        raise OSError("Fictional replace refusal")

    monkeypatch.setattr(atomic.os, "replace", fail)
    with pytest.raises(OSError, match="Fictional replace refusal"):
        records.save_session(build_session(), path)
    assert path.read_bytes() == b"the old canonical record\r\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["session.json"]


def test_ticked_scenario_round_trips_the_raw_saved_session(
    client: Any, app: Any, run_dir: Path, tmp_path: Path
) -> None:
    from tests.unit.test_ticked_review_golden import play_ticked_review

    folder = play_ticked_review(client, app, run_dir)
    before = (folder / "session.json").read_bytes()
    target = records.save_session(
        records.load_session(folder / "session.json"), tmp_path / "copy.json"
    )
    assert target.read_bytes() == before
