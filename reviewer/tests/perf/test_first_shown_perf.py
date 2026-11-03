"""The seconds the first-shown match adds to a review's start (002 cycle 17, T389).

When a review starts, `report/first_shown.first_shown_dates` reads the earlier reviews of the same
document in the run root, so the card can name when one first showed each finding (roadmap hole
H-a-009). Its reads are bounded by structure - names first, so another run's folder is never
opened, and each earlier record once - and this times them on a fictional run root of thirty
earlier reviews of feature 008's big-assembly replay fixture (a 96-finding, 0.66 MB record each),
a Model check folder beside each, and prints the seconds. 002 research.md, cycle 17, records them.

Not in the default run, for the reason every module here gives: a timing assertion measures the
machine as much as the code (`tests/conftest.py::pytest_ignore_collect`). Run it with:

    uv run pytest -m perf -s tests/perf/test_first_shown_perf.py
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pytest

from swreview.findings import finding_subject_key
from swreview.ir.loader import load_package
from swreview.report.attention import SUPPRESSED_STATUS
from swreview.report.first_shown import document_name, first_shown_dates
from swreview.report.session import SESSION_FILE_NAME, load_session
from swreview.report.snapshot import root_document

SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "big-assembly"
"""Feature 008's committed, fictional big-assembly review, the record each earlier review holds."""

EARLIER_REVIEWS = 30
BUDGET_S = 2.0
"""Well above what the match was measured at, so the budget says when a change made it slow."""


@pytest.mark.perf
def test_thirty_earlier_reviews_are_matched_inside_the_budget(tmp_path: Path) -> None:
    package = load_package(SOURCE).package
    document = root_document(package)
    assert document is not None
    label = document_name(document["path"])
    record = (SOURCE / SESSION_FILE_NAME).read_bytes()
    for day in range(1, EARLIER_REVIEWS + 1):
        folder = tmp_path / f"202609{day:02d}-090000-{label}"
        folder.mkdir()
        (folder / SESSION_FILE_NAME).write_bytes(record)
        (tmp_path / f"202609{day:02d}-091500-{label}-check").mkdir()
    own = tmp_path / f"20261103-090000-{label}"
    own.mkdir()

    started = time.perf_counter()
    dates = first_shown_dates(tmp_path, own, package, before=datetime(2026, 11, 3, 9, 0))
    elapsed = time.perf_counter() - started
    print(
        f"matching {EARLIER_REVIEWS} earlier reviews of {len(record)} bytes each: "
        f"{elapsed:.3f}s (budget {BUDGET_S:.1f}s)"
    )

    flagged = {
        finding_subject_key(finding)
        for finding in load_session(SOURCE / SESSION_FILE_NAME).findings
        if finding.status != SUPPRESSED_STATUS
    }
    assert flagged and set(dates) == flagged
    assert set(dates.values()) == {"2026-09-01"}
    assert elapsed < BUDGET_S, f"matching {EARLIER_REVIEWS} earlier reviews took {elapsed:.3f}s"
