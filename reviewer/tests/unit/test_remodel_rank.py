"""Unit tests for the planner's sort key (feature 004 T010).

`remodel/rank.py` turns a target group into a position: the key is
`(group_index, intra_rank, original_index)` and nothing else. What is pinned here:

- one case per intra-group rule feature 003 **already grades** (`rms.core.shell_last`,
  `rms.detail.holes_last`, `rms.modify.transform_before_replicate`,
  `rms.quarantine.chamfers_before_fillets`, `rms.quarantine.largest_fillet_first`), so
  the planner cannot aim at an order the checker will mark down, and the rule ids come
  from `checks/rms/part.py` rather than being spelled again here;
- a fillet whose `default_radius` is `None` is **blocked**: `rankable` is false, there is
  no key, and asking for one raises. A variable-radius fillet is never given an arbitrary
  position (research.md R6.2), it goes on the rebuild list as `radius_unreadable`;
- ties fall back to the original index, so the sort is total, deterministic, and moves
  nothing it has no reason to move.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from swreview.checks.rms.part import (
    CHAMFERS_BEFORE_FILLETS,
    HOLES_LAST,
    LARGEST_FILLET_FIRST,
    SHELL_LAST,
    TRANSFORM_BEFORE_REPLICATE,
)
from swreview.checks.rms_types import load_table
from swreview.remodel.rank import FeatureRank, group_index, rank_features
from tests.support.features import (
    FeatureSpec,
    feature,
    fillet_feature,
    folder,
    sketch_feature,
)
from tests.support.remodel import remodel_package

TABLE = load_table()
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups


def ranked(
    specs: Sequence[FeatureSpec], groups: Mapping[str, str]
) -> dict[str, FeatureRank]:
    """Rank a tree whose target groups are stated by feature name, keyed back by name."""
    package = remodel_package(list(specs))
    rows = list(package.features)
    ids = {row.name: row.id for row in rows}
    names = {row.id: row.name for row in rows}
    target_groups = {ids[name]: group for name, group in groups.items()}

    return {
        names[rank.feature_id]: rank
        for rank in rank_features(rows, target_groups, TABLE)
    }


def order_of(ranks: Mapping[str, FeatureRank]) -> list[str]:
    """The names in the order the key puts them, which is the order the plan aims at."""
    return sorted(ranks, key=lambda name: ranks[name].sort_key)


# --- the key -------------------------------------------------------------------------


def test_the_key_is_the_group_the_intra_rank_and_the_original_index() -> None:
    ranks = ranked(
        [feature("Boss-Extrude1", "Extrusion")], {"Boss-Extrude1": CORE}
    )
    rank = ranks["Boss-Extrude1"]

    assert rank.sort_key == (rank.group_index, rank.intra_rank, rank.original_index)
    assert rank.group_index == 3
    assert rank.original_index == 0


def test_the_group_comes_before_everything_else_in_the_key() -> None:
    """A Detail feature that sits first in the tree still sorts after every Core one."""
    ranks = ranked(
        [feature("Cut-Extrude1", "Cut"), feature("Boss-Extrude1", "Extrusion")],
        {"Cut-Extrude1": DETAIL, "Boss-Extrude1": CORE},
    )

    assert order_of(ranks) == ["Boss-Extrude1", "Cut-Extrude1"]


@pytest.mark.parametrize(
    ("group", "expected"),
    list(zip(TABLE.groups, range(1, 7), strict=True)),
)
def test_group_index_is_the_position_of_the_group_in_the_six(
    group: str, expected: int
) -> None:
    assert group_index(group, TABLE) == expected


def test_group_index_refuses_a_name_that_is_not_one_of_the_six() -> None:
    """`needs_judgement` is the table saying it cannot decide, not a seventh group."""
    with pytest.raises(ValueError, match="needs_judgement"):
        group_index("needs_judgement", TABLE)


# --- one case per intra-group rule ---------------------------------------------------


def test_the_shell_is_ranked_last_inside_core() -> None:
    ranks = ranked(
        [
            feature("Shell1", "Shell"),
            feature("Boss-Extrude1", "Extrusion"),
            fillet_feature("Fillet1"),
        ],
        {"Shell1": CORE, "Boss-Extrude1": CORE, "Fillet1": CORE},
    )

    assert order_of(ranks) == ["Boss-Extrude1", "Fillet1", "Shell1"]
    assert ranks["Shell1"].intra_rule_id == SHELL_LAST
    assert ranks["Shell1"].intra_rank > ranks["Boss-Extrude1"].intra_rank


def test_holes_are_ranked_as_the_trailing_block_of_detail() -> None:
    ranks = ranked(
        [
            feature("Hole1", "HoleWzd"),
            feature("Cut-Extrude1", "Cut"),
            sketch_feature("Sketch1", consumers=()),
        ],
        {"Hole1": DETAIL, "Cut-Extrude1": DETAIL, "Sketch1": DETAIL},
    )

    assert order_of(ranks) == ["Cut-Extrude1", "Sketch1", "Hole1"]
    assert ranks["Hole1"].intra_rule_id == HOLES_LAST


def test_drafts_are_ranked_before_patterns_in_modify() -> None:
    ranks = ranked(
        [feature("LPattern1", "LPattern"), feature("Draft1", "Draft")],
        {"LPattern1": MODIFY, "Draft1": MODIFY},
    )

    assert order_of(ranks) == ["Draft1", "LPattern1"]
    assert ranks["Draft1"].intra_rule_id == TRANSFORM_BEFORE_REPLICATE
    assert ranks["LPattern1"].intra_rule_id == TRANSFORM_BEFORE_REPLICATE


def test_chamfers_are_ranked_before_fillets_in_quarantine() -> None:
    ranks = ranked(
        [fillet_feature("Fillet1"), feature("Chamfer1", "Chamfer")],
        {"Fillet1": QUARANTINE, "Chamfer1": QUARANTINE},
    )

    assert order_of(ranks) == ["Chamfer1", "Fillet1"]
    assert ranks["Chamfer1"].intra_rule_id == CHAMFERS_BEFORE_FILLETS


def test_quarantine_fillets_are_ranked_largest_radius_first() -> None:
    ranks = ranked(
        [
            fillet_feature("Fillet-Small", radius_m=0.001),
            fillet_feature("Fillet-Large", radius_m=0.010),
            fillet_feature("Fillet-Medium", radius_m=0.005),
            feature("Chamfer1", "Chamfer"),
        ],
        {
            "Fillet-Small": QUARANTINE,
            "Fillet-Large": QUARANTINE,
            "Fillet-Medium": QUARANTINE,
            "Chamfer1": QUARANTINE,
        },
    )

    assert order_of(ranks) == [
        "Chamfer1",
        "Fillet-Large",
        "Fillet-Medium",
        "Fillet-Small",
    ]
    assert ranks["Fillet-Large"].intra_rule_id == LARGEST_FILLET_FIRST


def test_fillets_outside_quarantine_are_not_reordered_by_radius() -> None:
    """`largest_fillet_first` grades Quarantine and nothing else, so ordering Core
    fillets by radius would be movement the checker never asked for."""
    ranks = ranked(
        [
            fillet_feature("Fillet-Small", radius_m=0.001),
            fillet_feature("Fillet-Large", radius_m=0.010),
        ],
        {"Fillet-Small": CORE, "Fillet-Large": CORE},
    )

    assert order_of(ranks) == ["Fillet-Small", "Fillet-Large"]
    assert ranks["Fillet-Small"].intra_rank == ranks["Fillet-Large"].intra_rank
    assert ranks["Fillet-Small"].intra_rule_id is None


def test_equal_radii_keep_the_order_they_are_already_in() -> None:
    ranks = ranked(
        [
            fillet_feature("FilletA", radius_m=0.004),
            fillet_feature("FilletB", radius_m=0.004),
        ],
        {"FilletA": QUARANTINE, "FilletB": QUARANTINE},
    )

    assert order_of(ranks) == ["FilletA", "FilletB"]


# --- the unrankable fillet is blocked, never positioned ------------------------------


@pytest.mark.parametrize("group", [CORE, QUARANTINE])
def test_a_fillet_with_an_unreadable_radius_is_blocked(group: str) -> None:
    """A variable-radius fillet, or a failed read: the planner cannot say where it sits
    among the fillets, so it is not placed anywhere at all."""
    ranks = ranked([fillet_feature("Fillet-Variable1", radius_m=None)], {
        "Fillet-Variable1": group
    })
    rank = ranks["Fillet-Variable1"]

    assert rank.rankable is False
    assert rank.intra_rank is None
    assert rank.intra_rule_id is None
    assert rank.group_index == group_index(group, TABLE)


def test_a_blocked_fillet_has_no_key_and_asking_for_one_raises() -> None:
    """The failure mode this prevents is an arbitrary position that looks deliberate."""
    ranks = ranked(
        [fillet_feature("Fillet-Variable1", radius_m=None)],
        {"Fillet-Variable1": QUARANTINE},
    )

    with pytest.raises(ValueError, match="no rank"):
        _ = ranks["Fillet-Variable1"].sort_key


def test_a_fillet_with_no_fillet_reading_at_all_is_blocked() -> None:
    """`GetSpecificFeature2` returned no fillet definition: unreadable, not zero."""
    ranks = ranked(
        [feature("Fillet1", "Fillet")], {"Fillet1": QUARANTINE}
    )

    assert ranks["Fillet1"].rankable is False


def test_a_blocked_fillet_does_not_shift_the_fillets_that_are_readable() -> None:
    """The blocked one is out of the plan; the rest keep the ranks they would have had,
    so one unreadable radius does not renumber the group."""
    with_blocked = ranked(
        [
            fillet_feature("Fillet-Variable1", radius_m=None),
            fillet_feature("Fillet-Large", radius_m=0.010),
            fillet_feature("Fillet-Small", radius_m=0.001),
        ],
        {
            "Fillet-Variable1": QUARANTINE,
            "Fillet-Large": QUARANTINE,
            "Fillet-Small": QUARANTINE,
        },
    )

    assert order_of(
        {
            name: rank
            for name, rank in with_blocked.items()
            if rank.rankable
        }
    ) == ["Fillet-Large", "Fillet-Small"]


# --- ties, totality and what is ranked at all ----------------------------------------


def test_ties_fall_back_to_the_original_index() -> None:
    """Two features the rules say nothing about keep the order the part already has:
    minimum movement is the default, not an accident."""
    ranks = ranked(
        [
            feature("Boss-Extrude1", "Extrusion"),
            feature("Boss-Extrude2", "Extrusion"),
            feature("Boss-Extrude3", "Extrusion"),
        ],
        {name: CORE for name in ("Boss-Extrude1", "Boss-Extrude2", "Boss-Extrude3")},
    )

    assert order_of(ranks) == ["Boss-Extrude1", "Boss-Extrude2", "Boss-Extrude3"]
    assert [rank.original_index for rank in ranks.values()] == [0, 1, 2]


def test_the_sort_is_total_no_two_features_share_a_key() -> None:
    ranks = ranked(
        [
            feature("Shell1", "Shell"),
            feature("Boss-Extrude1", "Extrusion"),
            feature("Boss-Extrude2", "Extrusion"),
            feature("Hole1", "HoleWzd"),
            feature("Cut-Extrude1", "Cut"),
            feature("Draft1", "Draft"),
        ],
        {
            "Shell1": CORE,
            "Boss-Extrude1": CORE,
            "Boss-Extrude2": CORE,
            "Hole1": DETAIL,
            "Cut-Extrude1": DETAIL,
            "Draft1": MODIFY,
        },
    )

    keys = [rank.sort_key for rank in ranks.values()]

    assert len(set(keys)) == len(keys)


def test_only_the_features_with_a_target_group_are_ranked() -> None:
    """A folder, and a feature nobody could place, have no target group and therefore no
    rank: the caller passes the groups it resolved and gets one rank each, in tree order."""
    ranks = ranked(
        [
            folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
            feature("Cut-Extrude1", "Cut"),
        ],
        {"Boss-Extrude1": CORE, "Cut-Extrude1": DETAIL},
    )

    assert list(ranks) == ["Boss-Extrude1", "Cut-Extrude1"]


def test_the_ranks_come_back_in_tree_order() -> None:
    ranks = ranked(
        [
            feature("Hole1", "HoleWzd"),
            feature("Boss-Extrude1", "Extrusion"),
        ],
        {"Hole1": DETAIL, "Boss-Extrude1": CORE},
    )

    assert list(ranks) == ["Hole1", "Boss-Extrude1"]
    assert [rank.original_index for rank in ranks.values()] == [0, 1]


def test_a_target_group_naming_a_feature_the_tree_does_not_have_is_refused() -> None:
    package = remodel_package([feature("Boss-Extrude1", "Extrusion")])

    with pytest.raises(ValueError, match="feat:9999"):
        rank_features(list(package.features), {"feat:9999": CORE}, TABLE)


def test_a_target_group_that_is_not_one_of_the_six_is_refused() -> None:
    package = remodel_package([feature("Boss-Extrude1", "Extrusion")])
    rows = list(package.features)

    with pytest.raises(ValueError, match="7-Somewhere"):
        rank_features(rows, {rows[0].id: "7-Somewhere"}, TABLE)


def test_a_rank_is_frozen() -> None:
    ranks = ranked([feature("Boss-Extrude1", "Extrusion")], {"Boss-Extrude1": CORE})

    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError on a frozen model
        ranks["Boss-Extrude1"].intra_rank = 99
