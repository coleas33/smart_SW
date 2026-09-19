"""The wall-clock budget for ranking a session (feature 007, T017).

The report is rendered on every finalize, every re-render and every check re-read, and the
ranking runs inside each of those, so a fold or a key that turned the linear pass into a
quadratic one would slow every surface at once. Five hundred findings is far beyond any run
this product has produced; the budget is here so that change cannot land without saying so.

Why it is not in the default run: the same reason the other three modules here give. A
timing assertion is a statement about the machine as much as about the code, so
`tests/perf/` is not collected unless the run asks for the `perf` marker
(`tests/conftest.py::pytest_ignore_collect`). Run it with:

    uv run pytest -m perf -s

`-s` because the measured seconds are printed: an assertion that only says "under 100 ms"
hides the trend that says the budget is about to be missed.
"""

from __future__ import annotations

import time

import pytest

from swreview.findings import FindingStatus, Severity
from swreview.report.attention import load_policy, rank
from tests.support.attention import PART_COMPONENT, PIN_ONE, PIN_TWO
from tests.unit.test_attention import UNNAMED_CHECK, session_of, spec

PERF_FINDINGS = 500
PERF_BUDGET_S = 0.100
PERF_CHECKS: tuple[str, ...] = (
    "rms.grouping.all_features_in_a_group",
    "rms.params.global_variables_present",
    "rms.folders.present",
    "interference.static",
    "standards.drawing.revision_matches",
    UNNAMED_CHECK,
)
PERF_STATUSES: tuple[FindingStatus, ...] = ("demonstrated", "suspected", "unresolved")
PERF_SEVERITIES: tuple[Severity, ...] = ("high", "medium", "low")
PERF_COMPONENTS: tuple[tuple[str, ...], ...] = (
    (PART_COMPONENT,),
    (PIN_ONE,),
    (PIN_TWO,),
    (PART_COMPONENT, PIN_ONE),
)


@pytest.mark.perf
def test_ranking_five_hundred_findings_stays_inside_its_budget() -> None:
    session = session_of(
        "perf",
        [
            spec(
                PERF_CHECKS[index % len(PERF_CHECKS)],
                status=PERF_STATUSES[index % len(PERF_STATUSES)],
                severity=PERF_SEVERITIES[index % len(PERF_SEVERITIES)],
                component_ids=PERF_COMPONENTS[index % len(PERF_COMPONENTS)],
            )
            for index in range(PERF_FINDINGS)
        ],
    )
    policy = load_policy()

    started = time.perf_counter()
    ranking = rank(session, policy)
    elapsed = time.perf_counter() - started
    print(f"ranking {PERF_FINDINGS} findings: {elapsed:.3f}s (budget {PERF_BUDGET_S:.3f}s)")

    assert sum(len(row.member_finding_ids) for row in ranking.rows) == PERF_FINDINGS
    assert elapsed < PERF_BUDGET_S, f"ranking {PERF_FINDINGS} findings took {elapsed:.3f}s"
