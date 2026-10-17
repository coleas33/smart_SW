"""Independent redraw checks for the simulator's S-9 and S-10 searches."""

from __future__ import annotations

import numpy as np

from swreview.benchmark import simulate, stats, verdict


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
