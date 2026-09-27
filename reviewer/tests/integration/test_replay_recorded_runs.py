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
pinned by check and by the locations removed. Since feature 013 T133 the RMS part rules read the
tree one node per feature position, and by the default for T134-Q1 (`contracts/replay.md` section
5) a recorded finding that lost only a merged second listing's occurrence or a carried row is
narrowed the same way.

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


LOOSE = "rms.grouping.all_features_in_a_group"
FULLY_DEFINED = "rms.sketches.fully_defined"
ONE_SKETCH = "rms.sketches.one_sketch_per_feature"
NARROWED: dict[str, Counter[str]] = dict(
    zip(
        RUNS,
        (
            Counter({LOOSE: 20, FULLY_DEFINED: 3, ONE_SKETCH: 3}),
            Counter({LOOSE: 2, FULLY_DEFINED: 1}),
            Counter({LOOSE: 1, FULLY_DEFINED: 1}),
        ),
        strict=True,
    )
)
"""The recorded findings each recording's replay narrows, by check (owner decision 23A, feature
013's default for T134-Q1; `contracts/replay.md` sections 5 and 10). None until feature 003's
decision 20A made the eleven system types of the real dumps `tolerated_loose` (003 T090 to T092);
then 20, 2 and 1 part checks' loose-feature findings, each on the same part and configuration as
recorded, without its system-row subjects. Since 013 T133 reads the tree one node per feature
position (013 T134), also 3, 1 and 1 sketch findings naming an absorbed sketch once where the
recording named its depth-0 row and its second listing, and on the big recording 3
`one_sketch_per_feature` findings that no longer count a second listing as a consumer. No
Standards finding is among them: the recordings are replayed with no standards profile, so the
Standards sketch check's findings are not replayable here (the fixtures, graded with the example
profile, carry that case)."""
REMOVED_LOCATIONS: dict[str, Counter[str]] = dict(
    zip(
        RUNS,
        (
            Counter({LOOSE: 272, FULLY_DEFINED: 4, ONE_SKETCH: 7}),
            Counter({LOOSE: 28, FULLY_DEFINED: 1}),
            Counter({LOOSE: 20, FULLY_DEFINED: 1}),
        ),
        strict=True,
    )
)
"""The drawing locations those narrowed findings lose, by check, both clauses counted together:
283, 29 and 21 in all (013 T134; 106, 10 and 5 before T133, one per system row the part check
named loose when the recordings were made, the rows 003 T092 counted)."""


@pytest.mark.parametrize("run", RUNS)
def test_the_narrowed_findings_are_what_the_table_and_the_tree_reading_took_away(
    run: str,
) -> None:
    """A narrowed finding is one the replayed pass matched once locations naming only rows the
    current table does not count, or the tree reading folds, were taken out: listed, never lost,
    never added."""
    findings = as_recorded(run)[1].findings

    assert Counter(item.check for item in findings.narrowed) == NARROWED[run]
    removed: Counter[str] = Counter()
    for item in findings.narrowed:
        removed[item.check] += item.removed_locations
    assert removed == REMOVED_LOCATIONS[run]


def test_the_big_run_replays_88_findings_and_lists_11_it_cannot() -> None:
    findings = as_recorded(RUNS[0])[1].findings

    assert (findings.replayed, len(findings.not_replayable)) == (88, 11)
    families = Counter(item.check.split(".")[0] for item in findings.not_replayable)
    assert families == {"interference": 6, "standards": 5}
