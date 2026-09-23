"""SC-001 on the real recordings (008 T026, research R2.12, `contracts/replay.md` §10).

The committed fixtures are regression locks built by the same accounting the replay prices
with; only the real recordings measure the replay's fidelity independently. They live on the
development machine only (`%LOCALAPPDATA%\\SwReview\\handover\\2026-09-20-gui\\dumps`) and never
enter the repository, so this test skips, saying why, wherever they are absent - which is CI.

Replayed as they were recorded - no bridge and, deliberately, no standards profile - every
round must land within 1% of what the provider billed (observed at most 0.023%), and the
findings the replay reproduces plus the ones it can only list as not replayable must be the
recorded set: on the big run 88 reproduced and 11 not replayable (six interference findings
behind the live bridge call, five standards findings that need a profile).

No `pytest.mark.integration`: that marker means "needs a saved native evidence package" and
`tests/conftest.py` skips it whole when that package is absent, which it is on the machine that
holds the recordings; the dumps folder is this test's own input, and its skip names it.
"""

from __future__ import annotations

import os
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from swreview.agent.settings import MODEL_VIEW_OFF, EfficiencySettings
from swreview.benchmark.replay import ReplayReport, replay

DUMPS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "SwReview" / "handover" / "2026-09-20-gui" / "dumps"
)
RUNS = (
    "20260920-192014-830-02342",
    "20260920-191314-810-11249",
    "20260920-190840-810-11249",
)
TOLERANCE = 0.01

pytestmark = [
    pytest.mark.skipif(
        not DUMPS.is_dir(), reason=f"the recorded runs are not on this machine: {DUMPS}"
    ),
    pytest.mark.usefixtures("vocabulary"),
]


@cache
def as_recorded(run: str) -> ReplayReport:
    return replay(DUMPS / run, requested=(EfficiencySettings(), MODEL_VIEW_OFF))


@pytest.mark.parametrize("run", RUNS)
def test_every_recorded_round_is_reproduced_within_one_percent(run: str) -> None:
    report = as_recorded(run)

    worst = max(
        abs(r.as_recorded_input - r.recorded_input) / r.recorded_input for r in report.rounds
    )
    assert worst < TOLERANCE, f"{run}: worst round {worst:.4%}"


@pytest.mark.parametrize("run", RUNS)
def test_replayed_and_not_replayable_findings_are_the_recorded_set(run: str) -> None:
    findings = as_recorded(run).findings

    assert findings.lost == []
    assert findings.added == []
    assert findings.replayed + len(findings.not_replayable) == findings.recorded


def test_the_big_run_replays_88_findings_and_lists_11_it_cannot() -> None:
    findings = as_recorded(RUNS[0]).findings

    assert (findings.replayed, len(findings.not_replayable)) == (88, 11)
    families = Counter(item.check.split(".")[0] for item in findings.not_replayable)
    assert families == {"interference": 6, "standards": 5}
