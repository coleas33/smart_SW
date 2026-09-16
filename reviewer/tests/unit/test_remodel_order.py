"""Unit tests for the achievable order and the minimal edit script (T014).

`research.md` R6.3 is the whole specification and it is two algorithms with one output:

- **Kahn's algorithm with a priority queue keyed by the desired rank.** Every legal
  topological order respects the dependency graph; among them the planner takes the one
  the method would prefer, by always releasing the ready feature with the lowest desired
  rank. A FIFO Kahn would also be legal and would move features the method does not want
  moved, so the priority queue is asserted here against an order a FIFO queue cannot
  produce, not merely against legality.
- **the longest increasing subsequence of current positions under that order** names the
  features that can stay where they are; the complement is the edit script. Minimality is
  asserted as minimality - against a breadth-first search over the whole permutation
  graph on a small fixture, and against an independently computed LIS on a 200-row one -
  rather than against a fixed list of moves, which would pin one particular script and
  say nothing about whether a shorter one exists.

Three refusals are part of the contract rather than defensive habits:

- **the location set is closed at `before` and `after`.** `swMoveLocation_e.ToEnd = 1`,
  `ToTop = 4` and `ToFolder = 5` are exactly the values
  `contracts/guard-allowlist.md`'s option-composition test forbids the guard from
  composing, so a planner that emitted one would produce a change the guard's own test
  says must never exist. `Move` refuses them at construction, so "the planner can never
  emit `to_folder`" is a property of the type and not of the current call sites;
- **a cycle is refused with the cycle named**, and the function returns. A dependency
  cycle is the one input for which no legal order exists at all, and a planner that
  looped on it would hang the dry run;
- **nothing is defaulted.** A feature with no desired rank, a dependency edge naming a
  feature that is not in the tree, and a tree naming one feature twice are each a
  `ValueError` that names every offender, never a silently invented rank or a dropped
  edge (constitution Principle I).

The achievable order is produced from ids, dependencies and ranks alone - there is no
folder anywhere in the signature, because in stage 1 the folders are created after the
reorder, over runs whose contiguity the order has already made true (`data-model.md`
section 1.11, steps C3 then C4).
"""

from __future__ import annotations

import inspect
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import get_args

import pytest

from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import part_tree
from swreview.checks.rms_types import load_table
from swreview.remodel.order import LOCATIONS, Location, Move, OrderResult, plan_order
from tests.support.remodel import dependency_chain_features, remodel_package

TABLE = load_table()
DOCUMENT = "doc:1"


# --- helpers ----------------------------------------------------------------------


def ranks(order: Sequence[str]) -> dict[str, int]:
    """`order` read as the desired order: rank 0 first."""
    return {name: index for index, name in enumerate(order)}


def apply_script(current: Sequence[str], moves: Iterable[Move]) -> list[str]:
    """`current` after `moves`, exactly as `ReorderFeature(Before|After)` would leave it.

    The one simulation in this file: a move takes the feature out of the tree and puts it
    immediately before or immediately after its anchor. Every ordering assertion below
    runs the emitted script through this rather than reading the script back, because the
    tree the script produces is the thing the plan is about.
    """
    tree = list(current)
    for move in moves:
        assert move.feature_id in tree, f"{move.feature_id} is not in the tree"
        assert move.anchor_feature_id in tree, f"{move.anchor_feature_id} is not in the tree"
        assert move.feature_id != move.anchor_feature_id, "a feature cannot anchor itself"
        tree.remove(move.feature_id)
        anchor = tree.index(move.anchor_feature_id)
        tree.insert(anchor if move.location == "before" else anchor + 1, move.feature_id)
    return tree


def lis_length(values: Sequence[int]) -> int:
    """The length of the longest strictly increasing subsequence, the slow obvious way.

    O(n^2) and independent of the implementation under test on purpose: the point of the
    minimality assertions is that `move_count` equals `n - LIS`, and a test that called
    the same helper the planner calls would only assert that the planner agrees with
    itself.
    """
    best = [1] * len(values)
    for i, value in enumerate(values):
        for j in range(i):
            if values[j] < value and best[j] + 1 > best[i]:
                best[i] = best[j] + 1
    return max(best, default=0)


def minimum_moves(current: Sequence[str], target: Sequence[str]) -> int:
    """The true minimum number of moves from `current` to `target`, by search.

    A breadth-first search over the permutation graph, where an edge is one
    `before`/`after` move. Exponential in the length of the tree, so it is used on six
    features only - but it owes nothing to the LIS argument, so it is the assertion that
    `n - LIS` really is the minimum rather than merely the number this planner emits.
    """
    start = tuple(current)
    goal = tuple(target)
    seen = {start}
    queue: deque[tuple[tuple[str, ...], int]] = deque([(start, 0)])
    while queue:
        state, depth = queue.popleft()
        if state == goal:
            return depth
        for feature in state:
            for anchor in state:
                if anchor == feature:
                    continue
                for location in LOCATIONS:
                    moved = apply_script(state, [Move(feature, anchor, location)])
                    key = tuple(moved)
                    if key not in seen:
                        seen.add(key)
                        queue.append((key, depth + 1))
    raise AssertionError(f"{target} is not reachable from {current}")


def run(
    current: Sequence[str],
    dependencies: Mapping[str, Sequence[str]],
    desired: Sequence[str],
) -> OrderResult:
    """`plan_order` over a tree named by hand, with `desired` read as the desired order."""
    return plan_order(current, dependencies, ranks(desired))


# --- the achievable order ---------------------------------------------------------


def test_an_already_ordered_tree_yields_no_moves() -> None:
    current = ["a", "b", "c", "d"]
    result = run(current, {"b": ["a"], "c": ["b"], "d": ["c"]}, current)

    assert result.cycle is None
    assert result.achievable == ("a", "b", "c", "d")
    assert result.kept == ("a", "b", "c", "d")
    assert result.edit_script == ()
    assert result.move_count == 0


def test_a_reversed_tree_with_no_dependencies_yields_a_full_reorder() -> None:
    current = ["a", "b", "c", "d", "e"]
    result = run(current, {}, list(reversed(current)))

    assert result.achievable == ("e", "d", "c", "b", "a")
    assert result.move_count == len(current) - 1
    assert len(result.kept) == 1
    assert apply_script(current, result.edit_script) == list(result.achievable)


def test_kahn_takes_the_ready_feature_with_the_lowest_desired_rank() -> None:
    """The RMS-closest legal order, not merely a legal one.

    `c` wants to be first and cannot be: it depends on `a`. A first-in-first-out Kahn
    would release `a` first, because `a` stands first in the tree; the priority queue
    releases `b`, which is what the method actually asks for, and only then `a`, which
    unblocks `c`.
    """
    result = run(["a", "b", "c", "d"], {"c": ["a"]}, ["c", "b", "a", "d"])

    assert result.achievable == ("b", "a", "c", "d")
    assert result.cycle is None


def test_a_dependency_is_never_violated_however_the_ranks_pull() -> None:
    current = ["a", "b", "c", "d", "e", "f"]
    dependencies = {"b": ["a"], "c": ["b"], "e": ["d"], "f": ["c", "e"]}
    result = run(current, dependencies, list(reversed(current)))

    positions = {feature: index for index, feature in enumerate(result.achievable)}
    for child, parents in dependencies.items():
        for parent in parents:
            assert positions[parent] < positions[child], (
                f"{parent} must precede {child} in {result.achievable}"
            )
    assert apply_script(current, result.edit_script) == list(result.achievable)


def test_ties_in_the_desired_rank_fall_back_to_the_current_order() -> None:
    """A total, deterministic order: two features the method ranks equally keep the order
    the tree already has them in, which is what makes minimum movement the default."""
    current = ["a", "b", "c"]
    result = plan_order(current, {}, {"a": 1, "b": 1, "c": 0})

    assert result.achievable == ("c", "a", "b")


def test_the_same_input_twice_gives_the_same_plan() -> None:
    current = ["a", "b", "c", "d", "e"]
    dependencies = {"c": ["a"], "e": ["b"]}
    desired = ["e", "c", "a", "d", "b"]

    assert run(current, dependencies, desired) == run(current, dependencies, desired)


def test_the_achievable_order_is_produced_before_any_folder_exists() -> None:
    """Ids, edges, ranks and the rows this stage never moves - and nothing that knows what
    a folder is.

    Stage 1 reorders first and creates the six folders afterwards, over runs the order
    has already made contiguous (`data-model.md` section 1.11, C3 then C4), so the order
    cannot be allowed to depend on a folder that does not exist yet. The signature is
    asserted rather than described: a folder argument added later fails this test.
    """
    assert list(inspect.signature(plan_order).parameters) == [
        "current",
        "dependencies",
        "desired_rank",
        "immovable",
    ]

    package = remodel_package(dependency_chain_features())
    rows = [row for row in package.features if row.document_id == DOCUMENT]
    tree = part_tree(DOCUMENT, rows, TABLE, assign_groups(rows, TABLE), package)
    assert not any(TABLE.is_folder(row) for row in tree.rows), (
        "this fixture is deliberately unfoldered: the order comes first"
    )

    current = [row.id for row in tree.rows]
    result = plan_order(
        current,
        {row.id: row.parent_ids or () for row in tree.rows},
        ranks(current),
    )
    assert result.move_count == 0
    assert result.achievable == tuple(current)


# --- the minimal edit script ------------------------------------------------------


def test_the_edit_script_is_minimal_against_an_exhaustive_search() -> None:
    current = ["a", "b", "c", "d", "e", "f"]
    desired = ["c", "a", "f", "b", "d", "e"]
    result = run(current, {}, desired)

    assert result.achievable == tuple(desired)
    assert apply_script(current, result.edit_script) == desired
    assert result.move_count == minimum_moves(current, desired)


def test_the_kept_features_are_the_longest_increasing_subsequence() -> None:
    current = ["a", "b", "c", "d", "e", "f"]
    desired = ["c", "a", "f", "b", "d", "e"]
    result = run(current, {}, desired)

    positions = [current.index(feature) for feature in result.achievable]
    assert len(result.kept) == lis_length(positions)
    assert result.move_count == len(current) - len(result.kept)
    assert set(result.kept).isdisjoint({move.feature_id for move in result.edit_script})
    assert set(result.kept) | {move.feature_id for move in result.edit_script} == set(current)
    kept_in_current = [feature for feature in current if feature in result.kept]
    assert list(result.kept) == kept_in_current, "a kept feature is one that does not move"


def test_a_two_hundred_row_tree_takes_tens_of_moves_and_not_two_hundred() -> None:
    """The number that makes stage 1 affordable: every move is a guarded write plus a
    rebuild, so the script has to be the minimum and not the tree."""
    current = [f"feat:{index:04d}" for index in range(200)]
    desired = list(current)
    for start in range(3, 200, 10):
        desired.insert(min(start + 5, len(desired) - 1), desired.pop(start))

    result = run(current, {}, desired)

    positions = [current.index(feature) for feature in result.achievable]
    assert result.achievable == tuple(desired)
    assert result.move_count == len(current) - lis_length(positions)
    assert 10 <= result.move_count <= 40, (
        f"{result.move_count} moves over 200 features is not a minimal script"
    )
    assert apply_script(current, result.edit_script) == desired


# --- the closed location set ------------------------------------------------------


def test_the_location_set_is_exactly_before_and_after() -> None:
    assert LOCATIONS == ("before", "after")
    assert get_args(Location) == ("before", "after")


@pytest.mark.parametrize("location", ["to_end", "to_top", "to_folder", "", "Before"])
def test_a_move_refuses_any_other_location(location: str) -> None:
    """`swMoveLocation_e.ToEnd = 1`, `ToTop = 4` and `ToFolder = 5` are the three values
    `contracts/guard-allowlist.md` forbids the guard from composing, so the planner may
    not name one even by accident."""
    with pytest.raises(ValueError, match=location or "location"):
        Move("feat:0001", "feat:0002", location)  # type: ignore[arg-type]


def test_every_emitted_move_names_a_location_from_the_closed_set() -> None:
    current = ["a", "b", "c", "d", "e", "f"]
    for desired in (
        ["f", "e", "d", "c", "b", "a"],
        ["c", "a", "f", "b", "d", "e"],
        ["b", "a", "c", "e", "d", "f"],
    ):
        result = run(current, {}, desired)
        assert {move.location for move in result.edit_script} <= set(LOCATIONS)
        assert apply_script(current, result.edit_script) == desired


# --- refusals ---------------------------------------------------------------------


def test_a_cycle_is_refused_with_the_cycle_named() -> None:
    result = run(["a", "b", "c"], {"a": ["b"], "b": ["a"]}, ["a", "b", "c"])

    assert result.cycle is not None
    assert set(result.cycle) == {"a", "b"}
    assert result.achievable == ()
    assert result.kept == ()
    assert result.edit_script == ()
    assert result.move_count == 0


def test_a_longer_cycle_is_named_in_dependency_order() -> None:
    """`a` -> `b` -> `c` -> `a`: the cycle is named as a chain a reader can follow, each
    feature the parent of the next and the last the parent of the first."""
    dependencies = {"b": ["a"], "c": ["b"], "a": ["c"]}
    result = run(["a", "b", "c", "d"], dependencies, ["a", "b", "c", "d"])

    assert result.cycle is not None
    assert set(result.cycle) == {"a", "b", "c"}
    named = list(result.cycle)
    for parent, child in zip(named, named[1:] + named[:1], strict=True):
        assert parent in dependencies[child], (
            f"{result.cycle} does not read as a dependency chain: "
            f"{parent} is not a parent of {child}"
        )


def test_a_feature_that_depends_on_itself_is_a_cycle_and_not_a_hang() -> None:
    result = run(["a", "b"], {"a": ["a"]}, ["a", "b"])

    assert result.cycle == ("a",)


def test_a_feature_with_no_desired_rank_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="b.*c|c.*b"):
        plan_order(["a", "b", "c"], {}, {"a": 0})


def test_a_dependency_naming_a_feature_outside_the_tree_is_refused() -> None:
    with pytest.raises(ValueError, match="feat:9999"):
        plan_order(["a", "b"], {"b": ["feat:9999"]}, ranks(["a", "b"]))


def test_a_rank_naming_a_feature_outside_the_tree_is_refused() -> None:
    with pytest.raises(ValueError, match="z"):
        plan_order(["a", "b"], {}, {"a": 0, "b": 1, "z": 2})


def test_a_tree_naming_one_feature_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="a"):
        plan_order(["a", "b", "a"], {}, {"a": 0, "b": 1})


def test_an_empty_tree_is_an_empty_plan_and_not_an_error() -> None:
    result = plan_order([], {}, {})

    assert result == OrderResult(achievable=(), kept=(), edit_script=(), cycle=None)
    assert result.move_count == 0


# --- the rows the reorder never moves ---------------------------------------------


def test_an_immovable_row_holds_its_child_below_it_however_the_method_ranks_it() -> None:
    """A row the reorder never moves still occupies a tree position, so an edge into it
    is a constraint: `ReorderFeature` cannot lift a feature past its own parent."""
    current = ["a", "p", "b"]

    result = plan_order(current, {"b": ["p"]}, ranks(["b", "a", "p"]), immovable=["p"])

    assert result.achievable == ("a", "p", "b")
    assert result.edit_script == ()
    tree = apply_script(current, result.edit_script)
    assert tree.index("b") > tree.index("p")


def test_an_immovable_row_is_never_the_subject_of_a_move() -> None:
    current = ["x", "p", "y"]

    result = plan_order(current, {}, ranks(["y", "x", "p"]), immovable=["p"])

    assert [move.feature_id for move in result.edit_script] == ["y"]
    assert apply_script(current, result.edit_script) == ["y", "x", "p"]


def test_the_immovable_rows_keep_their_own_relative_order() -> None:
    current = ["p1", "a", "p2"]

    result = plan_order(current, {}, ranks(["p2", "a", "p1"]), immovable=["p1", "p2"])

    kept = [feature for feature in result.achievable if feature in {"p1", "p2"}]
    assert kept == ["p1", "p2"]
    assert all(move.feature_id not in {"p1", "p2"} for move in result.edit_script)
    assert apply_script(current, result.edit_script) == list(result.achievable)


def test_an_immovable_row_that_is_not_in_the_tree_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="q"):
        plan_order(["a", "b"], {}, ranks(["a", "b"]), immovable=["q"])
