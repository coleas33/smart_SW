"""Integration test for T092: answer-key isolation against the real `benchmarks/` tree.

Runs against the committed `benchmarks/sets/pilot.json` rather than a synthetic fixture.
Marked `integration` like every other test that depends on repo-tree state that may not be
present in every checkout; `tests/conftest.py` skips the whole `integration` marker
automatically when the native benchmark package is absent, which is fine here too - this
test only needs the committed set file, not a native package, but it shares the marker
deliberately so it is exercised in the same environments as the rest of the integration
suite.

Feature 014 T038 (RF-49) deleted its one `load_answer_key` call and the key assertions around
it: the committed keys are asserted on every machine by the unmarked
`tests/unit/test_committed_answer_keys.py`, where a stale assertion cannot hide behind this
marker. Its isolation checks stay.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.benchmark.runner import run_benchmark
from swreview.benchmark.sets import load_set

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
PILOT_SET = REPO_ROOT / "benchmarks" / "sets" / "pilot.json"


def test_real_pilot_set_loads_and_never_resolves_into_answer_keys() -> None:
    benchmark_set = load_set(PILOT_SET)

    assert benchmark_set.name == "pilot"
    assert benchmark_set.packages
    for ref in benchmark_set.packages:
        parts = {part.lower() for part in ref.path.parts}
        assert not {"benchmarks", "answer_keys"} <= parts


def test_run_benchmark_on_the_real_pilot_set_never_passes_an_answer_key_path(
    tmp_path: Path,
) -> None:
    calls: list[Path] = []

    def fake_review_fn(
        package_dir: Path,
        session_out_dir: Path,
        *,
        provider: str,
        model: str,
        effort: str,
        efficiency: object,
        attempt: object,
    ) -> None:
        calls.append(package_dir)

    run_benchmark(
        PILOT_SET,
        tmp_path / "out",
        provider="openai",
        model="gpt-5.6",
        effort="high",
        review_fn=fake_review_fn,
    )

    assert calls
    for package_dir in calls:
        parts = {part.lower() for part in package_dir.parts}
        assert not {"benchmarks", "answer_keys"} <= parts
