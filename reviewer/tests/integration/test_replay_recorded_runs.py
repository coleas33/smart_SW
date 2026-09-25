"""The replay against the real recordings (008 T026 and T118, research R2.12 and R2.55).

The committed fixtures are regression locks built by the same accounting the replay prices
with; only the real recordings measure the replay's fidelity independently. They live on the
development machine only and never enter the repository, and neither do their folder names,
which carry the designs' numbers (decision 11B): the owner's local mapping
(`%LOCALAPPDATA%\\SwReview\\recordings.json`, `tests/support/recordings.py`) says which folder
is the big assembly's recording and which are the small assembly's two, and this test skips,
saying why, wherever the mapping or a recording is absent - which is CI.

Replayed as they were recorded - no bridge and, deliberately, no standards profile. Since the
owner's decision 3A of 2026-09-23 (`contracts/replay.md` section 10) the rounds are not held to
1% of the bill: the recordings can never be regenerated, and the code they are replayed
against changes on purpose. Every token by which a round differs from the bill must instead
be the size change of the results that round's recorded request carried - a residual of
exactly zero (`tests/support/drift.round_drifts`) - which a deliberate change to a result can
never break and a defect in how the replay rebuilds a request always does. The findings the
replay reproduces plus the ones it can only list as not replayable must be the recorded set:
on the big run 88 reproduced and 11 not replayable (six interference findings behind the live
bridge call, five standards findings that need a profile). Since the owner's decision 23A a
recorded RMS finding that lost only the subjects the current type table stopped counting is
**narrowed** - matched to the replayed finding once those locations are taken out, and listed -
so it is among the reproduced, never lost or added, and each recording's narrowed findings are
pinned by check and by the locations removed.

No `pytest.mark.integration`: that marker means "needs a saved native evidence package" and
`tests/conftest.py` skips it whole when that package is absent, which it is on the machine that
holds the recordings; the recordings are this test's own input, and its skip names what is
missing.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import ReplayPasses, ReplayReport, replay_passes, report_of
from tests.support.drift import round_drifts
from tests.support.recordings import RECORDING_NAMES, recording_folder
from tests.support.replay import ALL_OFF

RUNS = RECORDING_NAMES
"""The big assembly's recording, then the small assembly's two, by the fixture each generates."""
MAIN_ROUNDS = dict(zip(RUNS, (40, 38, 36), strict=True))
"""The recordings' main rounds (research R1 counts usage rounds, the presentation included):
the rule must cover every one, or it would pass by holding nothing."""

pytestmark = pytest.mark.usefixtures("vocabulary")


def as_recorded(run: str) -> tuple[ReplayPasses, ReplayReport]:
    """Both passes of the recording with its own settings (every lever and the view off);
    skips, saying why, where the recording is not on this machine."""
    return replayed(recording_folder(run))


@cache
def replayed(folder: Path) -> tuple[ReplayPasses, ReplayReport]:
    recording = read_recording(folder)
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


NARROWED: dict[str, Counter[str]] = {run: Counter() for run in RUNS}
"""The recorded findings each recording's replay narrows, by check (owner decision 23A,
`contracts/replay.md` sections 5 and 10): none while the type table the recordings were graded
with is the one the code ships."""
REMOVED_LOCATIONS = dict.fromkeys(RUNS, 0)
"""The drawing locations those narrowed findings lose, in all."""


@pytest.mark.parametrize("run", RUNS)
def test_the_narrowed_findings_are_what_the_type_table_stopped_counting(run: str) -> None:
    """A narrowed finding is one the replayed pass matched once the locations naming only rows
    the current table does not count were taken out: listed, never lost, never added."""
    findings = as_recorded(run)[1].findings

    assert Counter(item.check for item in findings.narrowed) == NARROWED[run]
    assert sum(item.removed_locations for item in findings.narrowed) == REMOVED_LOCATIONS[run]


def test_the_big_run_replays_88_findings_and_lists_11_it_cannot() -> None:
    findings = as_recorded(RUNS[0])[1].findings

    assert (findings.replayed, len(findings.not_replayable)) == (88, 11)
    families = Counter(item.check.split(".")[0] for item in findings.not_replayable)
    assert families == {"interference": 6, "standards": 5}
