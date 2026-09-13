"""Record human timing against a benchmark run so the scorecard can compute net savings.

`net_saved_minutes` is always derived by `swreview.report.session.Timing`, never
supplied directly (FR-026): `record_timing` only ever sets the inputs
(`baseline_minutes`, the three assisted-effort buckets) and lets the model recompute it.
"""

from __future__ import annotations

from pathlib import Path

from swreview.report.session import Timing, load_session, save_session


def _session_path(run_dir: Path | str, package_id: str) -> Path:
    return Path(run_dir) / package_id / "session.json"


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

    Any argument left `None` keeps that field's current value; `unattended_runtime_minutes`
    is never touched here (only the runner sets it). Returns the recomputed `Timing`.
    """
    session_path = _session_path(run_dir, package_id)
    session = load_session(session_path)

    changes = {
        "baseline_minutes": baseline,
        "assisted_supervision_minutes": supervision,
        "assisted_verification_minutes": verification,
        "false_alarm_handling_minutes": false_alarms,
    }
    updated = session.timing.replace(
        **{name: value for name, value in changes.items() if value is not None}
    )
    session.timing = updated
    save_session(session, session_path)
    return updated
