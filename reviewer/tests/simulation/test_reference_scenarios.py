"""T230 S-10: the opt-in 39-scenario sweep, never collected by the default gate."""

from __future__ import annotations

import pytest

from swreview.benchmark import simulate
from tests.support.simulation_reference import assert_search_measurements

pytestmark = pytest.mark.simulation
SEED = 20261016


@pytest.mark.parametrize("name", tuple(simulate.SCENARIOS))
def test_s10_reference_scenario_holds_the_bounds_and_power(name):
    scenario = simulate.SCENARIOS[name]
    search = simulate.search(scenario, seed=SEED, sims=4000)
    printed = simulate.render_result(scenario, search, seed=SEED, sims=4000, cap=10)
    print(printed)
    result = search.result
    assert result is not None, name
    print(
        f"BOUND {name} reps={result.reps} defects={result.defects} alpha={result.alpha} "
        f"identical_loss_upper={result.identical_loss_upper:.8f} "
        f"no_loss_at_drop_upper={result.no_loss_at_drop_upper:.8f} "
        f"power_proportional={result.power_proportional} power_room={result.power_room}",
    )
    assert result.alpha in simulate.ALPHA_LADDER
    assert result.identical_loss <= result.identical_loss_upper <= .05
    assert result.no_loss_at_drop <= result.no_loss_at_drop_upper <= .05
    for power in (result.power_proportional, result.power_room):
        if power is not None:
            assert power >= .8
    assert result.power_proportional is not None or result.power_room is not None
    assert_search_measurements(scenario, search, seed=SEED, sims=4000)
    for row in search.tried:
        assert row.reps >= 3
        assert row.defects >= 34
        assert row.defects == 34 + 2 * row.growth_units
        assert row.packages == 51 + 3 * row.growth_units
        # The search prints every attempted size, including sizes with no passing alpha.
        assert f"reps={row.reps} packages={row.packages} defects={row.defects}" in printed
    if name.startswith("half-sd1.0-"):
        assert result.reps == 10
        assert result.growth_units >= 1
        first_growth = next(index for index, row in enumerate(search.tried) if row.growth_units)
        assert [row.reps for row in search.tried[:first_growth]] == list(range(3, 11))
        assert all(row.reps == 10 for row in search.tried[first_growth:])
