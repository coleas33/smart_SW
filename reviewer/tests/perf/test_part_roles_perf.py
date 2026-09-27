"""The wall-clock budget for classifying the big assembly's parts (feature 013 T018).

`classify_parts` runs once per review, before the pre-run, and again after an answer; the plan
gives it 50 ms on the big-assembly pane fixture's package (the replay fixture the pane fixture
is generated from), classified against fictional profile A, version 4. The best of five runs is
measured, so one slow scheduler tick does not fail it.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from swreview.checks.part_roles import classify_parts
from swreview.checks.standards.profile import load_profile
from swreview.ir.loader import load_package

pytestmark = pytest.mark.perf

TESTS = Path(__file__).resolve().parents[1]
BIG_ASSEMBLY = TESTS / "fixtures" / "replay" / "big-assembly"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"
BUDGET_SECONDS = 0.050


def test_the_big_assembly_is_classified_inside_its_budget() -> None:
    package = load_package(BIG_ASSEMBLY).package
    profile = load_profile(PROFILE_A)
    documents = sum(1 for document in package.documents if document.kind != "drawing")

    timings = []
    for _ in range(5):
        started = time.perf_counter()
        roles = classify_parts(package, profile)
        timings.append(time.perf_counter() - started)

    assert len(roles.by_document) == documents
    assert min(timings) < BUDGET_SECONDS, f"best of five took {min(timings) * 1000:.1f} ms"
