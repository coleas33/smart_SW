"""T230 S-7 and S-9: the three full 4,000-simulation searches, opt-in under `-m simulation`.

Moved whole from `tests/unit/test_benchmark_simulate.py` by owner decision 114A: they took about
3.5 minutes of every default run. Their assertions are unchanged; the default run keeps small
seeded versions of both, which check the search's shape and its independent recompute but
cannot carry the 5% bound and 80% power claims made here. Run before any approval (T247),
beside S-10: `uv run pytest -m simulation`.
"""

from __future__ import annotations

import pytest

from swreview.benchmark import simulate
from tests.support.simulation_reference import (
    assert_repetitions_then_growth,
    assert_search_measurements,
    assert_search_structure,
)

pytestmark = pytest.mark.simulation
SEED = 20261016
DEFAULT_SCENARIOS = (
    "half-sd1.0-fa1-nb0.5",
    "uniform-sd1.0-fa1-nb0.5-clear",
    "uniform-sd1.0-fa1-nb0.5-code",
)
"""S-9's three named scenarios; the name is kept from the default suite they left."""


@pytest.fixture(scope="module")
def reference_results():
    """S-9's three 4,000-study searches, once for this module."""
    return {
        name: simulate.search(simulate.SCENARIOS[name], seed=SEED, sims=4000)
        for name in DEFAULT_SCENARIOS
    }


def test_s7_half_at_sd_one_reaches_ten_then_grows(reference_results):
    search = reference_results[DEFAULT_SCENARIOS[0]]
    assert_repetitions_then_growth(search)


@pytest.mark.parametrize("name", DEFAULT_SCENARIOS)
def test_s9_three_full_searches_hold_both_bounds_and_both_powers(name, reference_results):
    search = reference_results[name]
    result = search.result
    assert_search_structure(simulate.SCENARIOS[name], search, seed=SEED, sims=4000)
    assert result.identical_loss <= result.identical_loss_upper <= .05
    assert result.no_loss_at_drop <= result.no_loss_at_drop_upper <= .05
    assert result.power_room >= .8
    assert result.power_proportional >= .8
    assert_search_measurements(simulate.SCENARIOS[name], search, seed=SEED, sims=4000)
