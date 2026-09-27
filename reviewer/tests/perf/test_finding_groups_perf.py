"""The wall-clock budget for the grouped view (feature 013 T047, its plan's performance goals).

`findings_by_type` runs on every attention, snapshot and disk route and every report render of a
review, beside the ranking it re-reads, so a goal lookup or a placement that turned its linear
passes into a quadratic one would slow each of them. The budget is the plan's: under 100 ms on
the big-assembly pane fixture's session and package (96 findings over 89 instances).

Not in the default run, for the reason `tests/perf/test_attention_perf.py` gives. Run it with:

    uv run pytest -m perf -s
"""

from __future__ import annotations

import time

import pytest

from swreview.ir.loader import load_package
from swreview.report.attention import load_policy
from swreview.report.finding_groups import findings_by_type
from swreview.report.session import load_session
from swreview.report.summary import load_words
from tests.unit.test_review_summary import BIG_ASSEMBLY

PERF_BUDGET_S = 0.100


@pytest.mark.perf
def test_grouping_the_big_assembly_stays_inside_its_budget() -> None:
    session = load_session(BIG_ASSEMBLY / "session.json")
    package = load_package(BIG_ASSEMBLY).package
    words, policy = load_words(), load_policy()

    started = time.perf_counter()
    view = findings_by_type(session, package, words, policy)
    elapsed = time.perf_counter() - started
    print(
        f"grouping {len(session.findings)} findings: {elapsed:.3f}s (budget {PERF_BUDGET_S:.3f}s)"
    )

    listed = sum(len(row.member_finding_ids) for group in view.groups for row in group.rows)
    assert listed == len(session.findings)
    assert elapsed < PERF_BUDGET_S, f"grouping took {elapsed:.3f}s"
