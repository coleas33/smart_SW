"""Record the four human timing inputs against a run, so a net saving can be computed.

`net_saved_minutes` is always derived by `swreview.report.session.Timing`, never supplied
directly (FR-026, and FR-004 of feature 007): the writers here only ever set the inputs
(`baseline_minutes`, the three assisted-effort buckets) and let the model recompute it.

There is **one** writer, `record_timing_at`, and it takes the path of a `session.json`:
a pane review, a command-line review, an RMS check or a standards check all write their
session flat in the run folder, and the benchmark harness writes one per package a level
down. `record_timing` is that second shape's wrapper, which is all "against a benchmark
run" ever meant (contract `007-attention-policy-gate/contracts/timing.md` section 1).
"""

from __future__ import annotations

from pathlib import Path

from swreview.report.session import Timing, load_session, save_session

__all__ = ["TIMING_INPUTS", "record_timing", "record_timing_at", "timing_with"]

TIMING_INPUTS: tuple[str, str, str, str] = (
    "baseline",
    "supervision",
    "verification",
    "false_alarms",
)
"""The four human inputs, by the name every caller spells them.

The command line's options, `POST /sessions/{chat_id}/timing`'s body keys and the keyword
arguments below are one vocabulary, named once: the route refuses a body key that is not in
here, and `tests/unit/test_timing.py` pins the tuple against this module's own signature so
a fifth input cannot be added to one of the three surfaces alone.
"""


def _session_path(run_dir: Path | str, package_id: str) -> Path:
    return Path(run_dir) / package_id / "session.json"


def timing_with(
    current: Timing,
    *,
    baseline: float | None = None,
    supervision: float | None = None,
    verification: float | None = None,
    false_alarms: float | None = None,
) -> Timing:
    """`current` with every input that is not `None` applied and the net derived again.

    The one place the four public names are mapped onto the model's fields, so the offline
    writer below and `chat.sessions.record_timing_live` - which writes a live review's
    session instead of a file - cannot drift on which input sets which field. Raises
    `pydantic.ValidationError` for a negative value, naming the field.
    """
    changes = {
        "baseline_minutes": baseline,
        "assisted_supervision_minutes": supervision,
        "assisted_verification_minutes": verification,
        "false_alarm_handling_minutes": false_alarms,
    }
    return current.replace(**{name: value for name, value in changes.items() if value is not None})


def record_timing_at(
    session_path: Path | str,
    *,
    baseline: float | None = None,
    supervision: float | None = None,
    verification: float | None = None,
    false_alarms: float | None = None,
) -> Timing:
    """Update the `Timing` in the session at `session_path`, and return the new one.

    Any argument left `None` keeps that field's current value, so a caller records one
    input without restating the other three; `unattended_runtime_minutes` is never touched
    here, because only the runner knows it. Nothing is written when the new values do not
    validate - a negative minute count raises `pydantic.ValidationError` naming the field
    and leaves the file exactly as it was (FR-003, FR-005).
    """
    session = load_session(session_path)
    updated = timing_with(
        session.timing,
        baseline=baseline,
        supervision=supervision,
        verification=verification,
        false_alarms=false_alarms,
    )
    session.timing = updated
    save_session(session, session_path)
    return updated


def record_timing(
    run_dir: Path | str,
    package_id: str,
    *,
    baseline: float | None = None,
    supervision: float | None = None,
    verification: float | None = None,
    false_alarms: float | None = None,
) -> Timing:
    """Update the `Timing` in `<run_dir>/<package_id>/session.json`.

    The benchmark harness's shape, which is the only one that nests a session under a
    package id. Everything it does is `record_timing_at`'s.
    """
    return record_timing_at(
        _session_path(run_dir, package_id),
        baseline=baseline,
        supervision=supervision,
        verification=verification,
        false_alarms=false_alarms,
    )
