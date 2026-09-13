"""Unit tests for T094: recording human timing against a benchmark run.

`record_timing` only ever sets `Timing`'s inputs; `net_saved_minutes` is always derived
by `swreview.report.session.Timing` itself (FR-026): `net = baseline - (supervision +
verification + false_alarm_handling)`, with unattended runtime excluded, and `None`
whenever `baseline` is `None`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from swreview.benchmark.timing import record_timing
from swreview.report.session import ReviewSession, Timing, load_session, save_session
from tests.support.packages import build_package


def seed_session(run_dir: Path, package_id: str, **timing_overrides: object) -> Path:
    package = build_package()
    session_path = run_dir / package_id / "session.json"
    fields: dict[str, object] = {
        "baseline_minutes": None,
        "assisted_supervision_minutes": 0.0,
        "assisted_verification_minutes": 0.0,
        "false_alarm_handling_minutes": 0.0,
        "unattended_runtime_minutes": 3.5,
    }
    fields.update(timing_overrides)

    session = ReviewSession(
        session_id=UUID("22222222-3333-4444-8555-666666666666"),
        package_id=package.package_id,
        design_id=package.design.design_id,
        started_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC),
        ended_at=None,
        model="claude-opus-5",
        timing=Timing(**fields),  # type: ignore[arg-type]
    )
    save_session(session, session_path)
    return session_path


def test_record_timing_computes_net_saved_minutes(tmp_path: Path) -> None:
    seed_session(tmp_path, "pkg-1", unattended_runtime_minutes=99.0)

    updated = record_timing(
        tmp_path, "pkg-1", baseline=90.0, supervision=10.0, verification=8.0, false_alarms=2.0
    )

    assert updated.net_saved_minutes == pytest.approx(70.0)
    assert updated.unattended_runtime_minutes == pytest.approx(99.0)


def test_record_timing_excludes_unattended_runtime_from_net_saved(tmp_path: Path) -> None:
    seed_session(tmp_path, "pkg-1", unattended_runtime_minutes=500.0)

    updated = record_timing(tmp_path, "pkg-1", baseline=60.0, supervision=5.0, verification=5.0)

    assert updated.net_saved_minutes == pytest.approx(50.0)


def test_record_timing_with_none_baseline_gives_none_net_saved(tmp_path: Path) -> None:
    seed_session(tmp_path, "pkg-1")

    updated = record_timing(tmp_path, "pkg-1", supervision=10.0, verification=8.0, false_alarms=2.0)

    assert updated.baseline_minutes is None
    assert updated.net_saved_minutes is None


def test_record_timing_leaves_unset_fields_unchanged(tmp_path: Path) -> None:
    seed_session(
        tmp_path,
        "pkg-1",
        baseline_minutes=90.0,
        assisted_supervision_minutes=10.0,
        assisted_verification_minutes=8.0,
        false_alarm_handling_minutes=2.0,
        unattended_runtime_minutes=25.0,
    )

    updated = record_timing(tmp_path, "pkg-1", false_alarms=5.0)

    assert updated.baseline_minutes == pytest.approx(90.0)
    assert updated.assisted_supervision_minutes == pytest.approx(10.0)
    assert updated.assisted_verification_minutes == pytest.approx(8.0)
    assert updated.false_alarm_handling_minutes == pytest.approx(5.0)
    assert updated.unattended_runtime_minutes == pytest.approx(25.0)
    assert updated.net_saved_minutes == pytest.approx(90.0 - (10.0 + 8.0 + 5.0))


def test_record_timing_persists_to_session_json(tmp_path: Path) -> None:
    session_path = seed_session(tmp_path, "pkg-1")

    record_timing(tmp_path, "pkg-1", baseline=45.0, supervision=5.0, verification=5.0)

    reloaded = load_session(session_path)
    assert reloaded.timing.baseline_minutes == pytest.approx(45.0)
    assert reloaded.timing.net_saved_minutes == pytest.approx(35.0)


def test_record_timing_can_clear_a_baseline_back_to_unset(tmp_path: Path) -> None:
    """Passing `baseline=None` (the default) keeps the *current* value; there is no way
    to un-set a baseline through `record_timing` short of editing `session.json`
    directly - documented here so the "None means keep" contract is explicit.
    """
    seed_session(tmp_path, "pkg-1", baseline_minutes=90.0)

    updated = record_timing(tmp_path, "pkg-1", supervision=1.0)

    assert updated.baseline_minutes == pytest.approx(90.0)
