"""The replay against the real recordings (008 T026 and T118, research R2.12 and R2.55).

The committed fixtures are regression locks built by the same accounting the replay prices
with; only the real recordings measure the replay's fidelity independently. They live on the
development machine only (`%LOCALAPPDATA%\\SwReview\\handover\\2026-09-20-gui\\dumps`) and never
enter the repository, so this test skips, saying why, wherever they are absent - which is CI.

Replayed as they were recorded - no bridge and, deliberately, no standards profile. Since the
owner's decision 3A of 2026-09-23 (`contracts/replay.md` section 10) the rounds are not held to
1% of the bill: the recordings can never be regenerated, and the code they are replayed
against changes on purpose. Every token by which a round differs from the bill must instead
be the size change of the results that round's recorded request carried - a residual of
exactly zero (`tests/support/drift.round_drifts`) - which a deliberate change to a result can
never break and a defect in how the replay rebuilds a request always does. The findings the
replay reproduces plus the ones it can only list as not replayable must be the recorded set:
on the big run 88 reproduced and 11 not replayable (six interference findings behind the live
bridge call, five standards findings that need a profile).

No `pytest.mark.integration`: that marker means "needs a saved native evidence package" and
`tests/conftest.py` skips it whole when that package is absent, which it is on the machine that
holds the recordings; the dumps folder is this test's own input, and its skip names it.
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import ReplayPasses, ReplayReport, replay_passes, report_of
from tests.support.drift import round_drifts
from tests.support.replay import ALL_OFF

DUMPS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "SwReview" / "handover" / "2026-09-20-gui" / "dumps"
)
RUNS = (
    "20260920-192014-830-02342",
    "20260920-191314-810-11249",
    "20260920-190840-810-11249",
)
MAIN_ROUNDS = dict(zip(RUNS, (40, 38, 36), strict=True))
"""The recordings' main rounds (research R1 counts usage rounds, the presentation included):
the rule must cover every one, or it would pass by holding nothing."""

pytestmark = [
    pytest.mark.skipif(
        not DUMPS.is_dir(), reason=f"the recorded runs are not on this machine: {DUMPS}"
    ),
    pytest.mark.usefixtures("vocabulary"),
]


@cache
def as_recorded(run: str) -> tuple[ReplayPasses, ReplayReport]:
    """Both passes of the recording with its own settings (every lever and the view off)."""
    recording = read_recording(DUMPS / run)
    with tempfile.TemporaryDirectory(prefix="swreview-recorded-") as scratch:
        passes = replay_passes(recording, scratch, requested=ALL_OFF)
    return passes, report_of(passes)


@pytest.mark.parametrize("run", RUNS)
def test_every_rounds_drift_is_the_size_change_of_the_results_it_carries(run: str) -> None:
    passes, report = as_recorded(run)

    drifts = round_drifts(passes, report)

    outside = [d for d in drifts if d.change is None]
    assert outside == [], f"{run}: no round of the recordings is flagged lower bound"
    unexplained = [d for d in drifts if d.residual != 0]
    assert unexplained == [], f"{run}: the replay rebuilt these requests wrong"
    kinds = Counter(d.kind for d in drifts)
    assert kinds == {"main": MAIN_ROUNDS[run], "presentation": 1}


@pytest.mark.parametrize("run", RUNS)
def test_replayed_and_not_replayable_findings_are_the_recorded_set(run: str) -> None:
    findings = as_recorded(run)[1].findings

    assert findings.lost == []
    assert findings.added == []
    assert findings.replayed + len(findings.not_replayable) == findings.recorded


def test_the_big_run_replays_88_findings_and_lists_11_it_cannot() -> None:
    findings = as_recorded(RUNS[0])[1].findings

    assert (findings.replayed, len(findings.not_replayable)) == (88, 11)
    families = Counter(item.check.split(".")[0] for item in findings.not_replayable)
    assert families == {"interference": 6, "standards": 5}
