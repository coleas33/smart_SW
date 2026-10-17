"""Independent redraw checks for the simulator's S-9 and S-10 searches."""

from __future__ import annotations

import numpy as np
import pytest

from swreview.benchmark import simulate, stats, verdict


def assert_repetitions_then_growth(search):
    """S-7's shared cap walk and consecutive growth units at that cap."""
    assert search.result is not None
    assert search.result.reps == 10
    assert search.result.growth_units >= 1
    first_growth = next(index for index, row in enumerate(search.tried) if row.growth_units)
    assert [row.reps for row in search.tried[:first_growth]] == list(range(3, 11))
    grown = search.tried[first_growth:]
    assert all(row.reps == 10 for row in grown)
    assert [row.growth_units for row in grown] == list(range(1, len(grown) + 1))


def assert_search_structure(scenario, search, *, seed, sims):
    """S-9's shared size, guard, stress and printed-row assertions at any sims."""
    result = search.result
    assert result is not None, scenario.name
    assert result.alpha in simulate.ALPHA_LADDER
    assert all(row.reps >= 3 and row.defects >= 34 for row in search.tried)
    assert result.defects == 34 + 2 * result.growth_units
    assert result.packages == 51 + 3 * result.growth_units
    if scenario.name.endswith("-clear"):
        assert search.cleared_guard_decides is False
        assert search.cleared_guard_reason
    if scenario.name.endswith("-code"):
        assert search.stress_case == pytest.approx(simulate.stress_case(
            np.full(10, .95), result.reps,
        ))
    printed = simulate.render_result(scenario, search, seed=seed, sims=sims).splitlines()
    assert [line.split(" growth_units=")[0] for line in printed if line.startswith("reps=")] == [
        f"reps={row.reps} packages={row.packages} defects={row.defects}" for row in search.tried
    ]
    assert f"chosen reps={result.reps} packages={result.packages}" in printed[-1]


def assert_search_measurements(scenario, search, *, seed, sims):
    """Recompute every tried size without using measure, choose or their streams."""
    chosen = search.result
    assert chosen is not None
    for index, row in enumerate(search.tried):
        layout = simulate.REFERENCE_LAYOUT.grown(row.growth_units)
        drawn = {}
        for shape, drop in (("null", 0), ("proportional", .1), ("room", .1)):
            drawn[shape] = verdict.prepare_judge(simulate.draw_studies(
                scenario, seed=seed, sims=sims, reps=row.reps, layout=layout,
                drop=drop, shape="room" if shape == "null" else shape,
            ))

        def recompute(alpha, decides, drawn=drawn):
            outcomes = {
                shape: verdict.judge(prepared, verdict.VerdictRules(alpha, decides), named=False)
                for shape, prepared in drawn.items()
            }
            null_hits = int(np.count_nonzero(outcomes["null"].quality_loss))
            powers, no_loss, upper = {}, [], []
            for shape in ("proportional", "room"):
                result = outcomes[shape]
                count = len(result.quality_loss)
                # Main recall alone is power; guard/false-alarm/sensitivity hits
                # cannot contribute to this numerator.
                powers[shape] = np.count_nonzero(result.recall_loss[:, 0]) / count
                hits = int(np.count_nonzero(result.no_loss))
                no_loss.append(hits / count)
                upper.append(stats.mc_upper_bound(hits, count))
            return (
                null_hits / sims, stats.mc_upper_bound(null_hits, sims),
                powers, max(no_loss), max(upper),
            )

        alpha = .0025 if row.alpha is None else row.alpha
        identical, identical_upper, powers, no_loss, upper = recompute(alpha, False)
        assert row.identical_loss == identical
        assert row.identical_loss_upper == identical_upper
        assert row.power_proportional == powers["proportional"]
        assert row.power_room == powers["room"]
        assert row.no_loss_at_drop == no_loss
        assert row.no_loss_at_drop_upper == upper
        if row.alpha is None:
            for candidate in (.025, .02, .015, .01, .005, .0025):
                _, null_upper, _, _, drop_upper = recompute(candidate, False)
                assert null_upper > .05 or drop_upper > .05
        elif index < len(search.tried) - 1:
            assert min(powers.values()) < .8
        else:
            assert min(powers.values()) >= .8

        if index == len(search.tried) - 1:
            assert (chosen.reps, chosen.growth_units) == (row.reps, row.growth_units)
            identical, identical_upper, powers, no_loss, upper = recompute(
                chosen.alpha, search.cleared_guard_decides,
            )
            assert chosen.identical_loss == identical
            assert chosen.identical_loss_upper == identical_upper <= .05
            assert chosen.power_proportional == powers["proportional"] >= .8
            assert chosen.power_room == powers["room"] >= .8
            assert chosen.no_loss_at_drop == no_loss
            assert chosen.no_loss_at_drop_upper == upper <= .05
