"""The wall-clock budgets of the drawing index and the brief (feature 011 plan, T050).

The plan's performance goals: `DrawingIndex.for_package` under 50 ms and `build_brief` under
200 ms on the `plate-drawing` fixture, the brief measured with the binding switch set so every
drawing answer is computed rather than refused. Not collected unless the run asks for the
`perf` marker (`tests/conftest.py`): run with `uv run pytest -m perf tests/perf -s`. Loading
the package and the profile is outside the timer.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from swreview.checks.standards.profile import load_profile
from swreview.drawings import binding
from swreview.drawings.brief import build_brief
from swreview.drawings.evidence import DrawingIndex
from swreview.ir.loader import load_package

pytestmark = pytest.mark.perf

TESTS = Path(__file__).resolve().parents[1]
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"

INDEX_BUDGET_SECONDS = 0.05
BRIEF_BUDGET_SECONDS = 0.2


def test_the_drawing_index_is_built_inside_its_budget() -> None:
    package = load_package(PLATE_DRAWING).package

    start = time.perf_counter()
    index = DrawingIndex.for_package(package)
    elapsed = time.perf_counter() - start

    assert len(index.views) == 3
    print(f"\nDrawingIndex.for_package: {elapsed:.4f} s, budget {INDEX_BUDGET_SECONDS} s")
    assert elapsed < INDEX_BUDGET_SECONDS


def test_the_plates_brief_is_built_inside_its_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", True)
    package = load_package(PLATE_DRAWING).package
    profile = load_profile(PROFILE_A)

    start = time.perf_counter()
    brief = build_brief(package, None, profile, "doc:0002")
    elapsed = time.perf_counter() - start

    assert brief.to_json()
    print(f"\nbuild_brief of the plate: {elapsed:.4f} s, budget {BRIEF_BUDGET_SECONDS} s")
    assert elapsed < BRIEF_BUDGET_SECONDS
