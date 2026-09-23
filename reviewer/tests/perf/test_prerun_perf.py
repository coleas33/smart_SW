"""The wall-clock budget for checks first over a thousand interference groups (feature 008 T041).

SC-006 needs every detected group judged, and live detection on a large assembly can return
many: the recorded big run found 113, and the edge case the spec names is "thousands". The
pre-run judges each group with its own `check_interference_group` call through the dispatch,
and `groups_of` is recomputed per call (research R5 names it quadratic), so this budget is
what stops a change from turning a slow setup into an unusable one without saying so. The
digest must still be one collapsed line for the thousand calls.

Not in the default run, for the reason every module here gives: a timing assertion measures
the machine as much as the code (`tests/conftest.py::pytest_ignore_collect`). Run it with:

    uv run pytest -m perf -s tests/perf/test_prerun_perf.py
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage, Interference
from swreview.prerun import INTERFERENCE_TOOL
from tests.support.prerun import CHECKS_FIRST, LIVE_ROWS, live_prerun_package

PERF_GROUPS = 1_000
PERF_BUDGET_S = 30.0


def thousand_group_package() -> EvidencePackage:
    template = Interference.model_validate(LIVE_ROWS[1])
    rows = [
        template.model_copy(update={"id": f"int:{2 * n + k + 1:05d}", "group_key": f"g{n:04d}"})
        for n in range(PERF_GROUPS)
        for k in range(2)
    ]
    return live_prerun_package().model_copy(update={"interferences": rows})


@pytest.mark.perf
def test_the_pre_run_judges_a_thousand_groups_inside_its_budget(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    save_package(thousand_group_package(), folder)

    started = time.perf_counter()
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=CHECKS_FIRST,
    )
    elapsed = time.perf_counter() - started
    print(f"checks first over {PERF_GROUPS} groups: {elapsed:.2f} s")

    group_steps = [s for s in run.session.steps if s.tool == INTERFERENCE_TOOL]
    assert len(group_steps) == PERF_GROUPS
    lines = [line for line in run.opening_message.splitlines() if INTERFERENCE_TOOL in line]
    assert len(lines) == 1
    assert lines[0].startswith(f"  {INTERFERENCE_TOOL} x{PERF_GROUPS} -> {PERF_GROUPS} ok")
    assert elapsed < PERF_BUDGET_S
