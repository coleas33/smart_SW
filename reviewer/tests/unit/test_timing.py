"""Unit tests for T094: recording human timing against a benchmark run.

`record_timing` only ever sets `Timing`'s inputs; `net_saved_minutes` is always derived
by `swreview.report.session.Timing` itself (FR-026): `net = baseline - (supervision +
verification + false_alarm_handling)`, with unattended runtime excluded, and `None`
whenever `baseline` is `None`.

T007 adds the second half: `record_timing_at` is the one writer, over a **flat**
`<dir>/session.json` - a pane review, a CLI review, an RMS check or a standards check
folder - and `record_timing` is the benchmark harness's nested wrapper around it. The six
tests of the nested shape below are deliberately unedited, so the extraction is proved to
have changed nothing about the path that already had a caller.

*Changed 2026-11-01 on purpose (owner decision 183A; 007 T065):* the assisted minutes are setup,
supervision, verification, false-alarm handling and the review by hand together, `net = baseline -
assisted`, and the net is `None` until setup and the review by hand are both recorded. Every test
here whose figure is a net therefore records both as 0 (`setup=0.0, by_hand=0.0`, or the two
fields in its seed), its expected value unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from inspect import Parameter, signature
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from swreview.benchmark.timing import (
    TIMING_INPUTS,
    record_timing,
    record_timing_at,
    timing_with,
)
from swreview.chat.sessions import record_timing_live
from swreview.report.session import ReviewSession, Timing, load_session, save_session
from tests.support.packages import build_package


def seed_session_at(session_path: Path, **timing_overrides: object) -> Path:
    """A session with the given timing fields at exactly `session_path`."""
    package = build_package()
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


def seed_session(run_dir: Path, package_id: str, **timing_overrides: object) -> Path:
    """The nested `<run_dir>/<package_id>/session.json` the benchmark harness writes."""
    return seed_session_at(run_dir / package_id / "session.json", **timing_overrides)


def test_record_timing_computes_net_saved_minutes(tmp_path: Path) -> None:
    seed_session(tmp_path, "pkg-1", unattended_runtime_minutes=99.0)

    updated = record_timing(
        tmp_path,
        "pkg-1",
        baseline=90.0,
        supervision=10.0,
        verification=8.0,
        false_alarms=2.0,
        setup=0.0,
        by_hand=0.0,
    )

    assert updated.net_saved_minutes == pytest.approx(70.0)
    assert updated.unattended_runtime_minutes == pytest.approx(99.0)


def test_record_timing_excludes_unattended_runtime_from_net_saved(tmp_path: Path) -> None:
    seed_session(tmp_path, "pkg-1", unattended_runtime_minutes=500.0)

    updated = record_timing(
        tmp_path,
        "pkg-1",
        baseline=60.0,
        supervision=5.0,
        verification=5.0,
        setup=0.0,
        by_hand=0.0,
    )

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
        setup_minutes=0.0,
        review_by_hand_minutes=0.0,
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

    record_timing(
        tmp_path,
        "pkg-1",
        baseline=45.0,
        supervision=5.0,
        verification=5.0,
        setup=0.0,
        by_hand=0.0,
    )

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


# --- T007: the flat run folder every real run writes ---------------------------------


def flat(tmp_path: Path, **timing_overrides: object) -> Path:
    """`<tmp_path>/run/session.json`, the shape `swreview timing` is given."""
    return seed_session_at(tmp_path / "run" / "session.json", **timing_overrides)


def test_record_timing_at_computes_net_saved_minutes(tmp_path: Path) -> None:
    session_path = flat(tmp_path, unattended_runtime_minutes=99.0)

    updated = record_timing_at(
        session_path,
        baseline=90.0,
        supervision=10.0,
        verification=8.0,
        false_alarms=2.0,
        setup=0.0,
        by_hand=0.0,
    )

    assert updated.net_saved_minutes == pytest.approx(70.0)
    assert updated.unattended_runtime_minutes == pytest.approx(99.0)


def test_record_timing_at_excludes_unattended_runtime_from_net_saved(tmp_path: Path) -> None:
    session_path = flat(tmp_path, unattended_runtime_minutes=500.0)

    updated = record_timing_at(
        session_path, baseline=60.0, supervision=5.0, verification=5.0, setup=0.0, by_hand=0.0
    )

    assert updated.net_saved_minutes == pytest.approx(50.0)


def test_record_timing_at_with_none_baseline_gives_none_net_saved(tmp_path: Path) -> None:
    session_path = flat(tmp_path)

    updated = record_timing_at(
        session_path, supervision=10.0, verification=8.0, false_alarms=2.0
    )

    assert updated.baseline_minutes is None
    assert updated.net_saved_minutes is None


def test_record_timing_at_leaves_unset_fields_unchanged(tmp_path: Path) -> None:
    session_path = flat(
        tmp_path,
        baseline_minutes=90.0,
        assisted_supervision_minutes=10.0,
        assisted_verification_minutes=8.0,
        false_alarm_handling_minutes=2.0,
        unattended_runtime_minutes=25.0,
        setup_minutes=0.0,
        review_by_hand_minutes=0.0,
    )

    updated = record_timing_at(session_path, false_alarms=5.0)

    assert updated.baseline_minutes == pytest.approx(90.0)
    assert updated.assisted_supervision_minutes == pytest.approx(10.0)
    assert updated.assisted_verification_minutes == pytest.approx(8.0)
    assert updated.false_alarm_handling_minutes == pytest.approx(5.0)
    assert updated.unattended_runtime_minutes == pytest.approx(25.0)
    assert updated.net_saved_minutes == pytest.approx(90.0 - (10.0 + 8.0 + 5.0))


def test_record_timing_at_persists_to_session_json(tmp_path: Path) -> None:
    session_path = flat(tmp_path)

    record_timing_at(
        session_path, baseline=45.0, supervision=5.0, verification=5.0, setup=0.0, by_hand=0.0
    )

    reloaded = load_session(session_path)
    assert reloaded.timing.baseline_minutes == pytest.approx(45.0)
    assert reloaded.timing.net_saved_minutes == pytest.approx(35.0)


def test_record_timing_at_cannot_un_set_a_baseline(tmp_path: Path) -> None:
    """`None` means "keep" on this path too; there is no way to clear a recorded baseline."""
    session_path = flat(tmp_path, baseline_minutes=90.0)

    updated = record_timing_at(session_path, supervision=1.0)

    assert updated.baseline_minutes == pytest.approx(90.0)


def test_record_timing_at_takes_a_string_path(tmp_path: Path) -> None:
    session_path = flat(tmp_path)

    updated = record_timing_at(str(session_path), baseline=20.0, setup=0.0, by_hand=0.0)

    assert updated.net_saved_minutes == pytest.approx(20.0)


@pytest.mark.parametrize(
    ("argument", "field"),
    [
        ("baseline", "baseline_minutes"),
        ("supervision", "assisted_supervision_minutes"),
        ("verification", "assisted_verification_minutes"),
        ("false_alarms", "false_alarm_handling_minutes"),
        ("setup", "setup_minutes"),
        ("by_hand", "review_by_hand_minutes"),
    ],
)
def test_a_negative_input_is_refused_by_name_and_writes_nothing(
    tmp_path: Path, argument: str, field: str
) -> None:
    """FR-003: the refusal names the field, and `session.json` is not touched (FR-005)."""
    session_path = flat(tmp_path, baseline_minutes=30.0)
    before = session_path.read_bytes()

    with pytest.raises(ValidationError, match=field):
        record_timing_at(session_path, **{argument: -1.0})

    assert session_path.read_bytes() == before


def test_the_input_names_are_the_writers_own_signature() -> None:
    """`TIMING_INPUTS` is what the route validates a body against, so it may not drift from
    the arguments the writers take: an input added to one surface alone would be accepted by
    the command line and refused by the pane, or the other way round.

    *Changed 2026-11-01 on purpose (owner decision 183A; 007 T065):* renamed from
    `test_the_four_input_names_are_the_writers_own_signature`, the inputs being six, and
    extended to `record_timing` and `record_timing_live`, the two writers it did not read.
    """
    for writer in (record_timing_at, timing_with, record_timing, record_timing_live):
        keyword_only = tuple(
            name
            for name, parameter in signature(writer).parameters.items()
            if parameter.kind is Parameter.KEYWORD_ONLY
        )
        assert keyword_only == TIMING_INPUTS, writer.__name__


# --- owner decision 183A: setup and the review by hand (007 T065, FR-036) -------------


def test_assisted_minutes_count_setup_and_the_review_left_by_hand(tmp_path: Path) -> None:
    """The assisted minutes are setup, supervision, verification, false-alarm handling and the
    review by hand together, and the net is the baseline less them: 120 less 57 (User Story 1,
    scenario 7). Unattended runtime is still left out."""
    session_path = flat(tmp_path, unattended_runtime_minutes=99.0)

    updated = record_timing_at(
        session_path,
        baseline=120.0,
        supervision=6.0,
        verification=9.0,
        false_alarms=2.0,
        setup=10.0,
        by_hand=30.0,
    )

    assert updated.assisted_minutes == pytest.approx(57.0)
    assert updated.net_saved_minutes == pytest.approx(63.0)
    reloaded = load_session(session_path).timing
    assert (reloaded.setup_minutes, reloaded.review_by_hand_minutes) == (10.0, 30.0)
    assert reloaded.net_saved_minutes == pytest.approx(63.0)


@pytest.mark.parametrize("recorded", ["setup", "by_hand"])
def test_the_net_is_unknown_until_setup_and_the_review_left_by_hand_are_recorded(
    tmp_path: Path, recorded: str
) -> None:
    """An input not recorded stays unknown, and the net with it, as the net reads without a
    baseline; one of the two is not enough, and a recorded 0 is a value (183A)."""
    session_path = flat(tmp_path)

    four = record_timing_at(
        session_path, baseline=120.0, supervision=6.0, verification=9.0, false_alarms=2.0
    )
    one = record_timing_at(session_path, **{recorded: 0.0})
    both = record_timing_at(session_path, setup=0.0, by_hand=0.0)

    assert (four.assisted_minutes, four.net_saved_minutes) == (None, None)
    assert (one.assisted_minutes, one.net_saved_minutes) == (None, None)
    assert both.assisted_minutes == pytest.approx(17.0)
    assert both.net_saved_minutes == pytest.approx(103.0)
