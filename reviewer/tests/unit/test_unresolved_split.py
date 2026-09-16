"""The unresolved count read as two numbers (FR-054), lever 4's quality metric.

Lever 4 buys bytes by not offering a tool, and the way it can go wrong is precise: the
review stops covering something. `unresolved_count` cannot see that at all - it counts
*findings* whose status is unresolved, not coverage items - and the bucket mix can see the
total move without saying which half moved. So the unresolved **coverage** items are read
as two numbers: the ones a withheld tool wrote, which lever 4 is *expected* to raise, and
everything else, which is the number T064's gate says must not rise. One number would hide
exactly the failure the lever can cause (contracts/usage.md section 8).

**The marker is recorded, never inferred.** `WithheldTool.call` writes its `unresolved`
item and records the check it wrote against on `session.withheld_checks`, so the split is a
set membership over a field the run wrote down. The alternative - substring-matching the
reason sentence - would make a reworded sentence a silent measurement change, and this
feature has already reworded that sentence once.

**They sum to the unresolved bucket, not to `unresolved_count`.** Those are two different
populations and the ledger must never add one to the other; `test_the_two_numbers_sum_to_the
_unresolved_bucket` pins which one this is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swreview.benchmark.scorecard import coverage_bucket_mix, unresolved_split
from swreview.report.session import Coverage, CoverageItem, CoverageScope, ReviewSession
from tests.support.contracts import contract_validator
from tests.unit.test_scorecard_usage import score
from tests.unit.test_stop_predicate import empty_session

WITHHELD_CHECK = "modeling.resilience"


def item(check: str) -> CoverageItem:
    return CoverageItem(check=check, scope=CoverageScope(), reason="because", error=None)


def session_with(unresolved: tuple[str, ...], withheld: tuple[str, ...]) -> ReviewSession:
    """A session whose unresolved bucket holds `unresolved`, `withheld` of them withheld."""
    return empty_session(
        coverage=Coverage(unresolved=[item(check) for check in unresolved]),
        withheld_checks=list(withheld),
    )


# --- 1. the split itself ---------------------------------------------------------------


def test_the_split_counts_the_items_a_withheld_tool_wrote() -> None:
    session = session_with(("a", WITHHELD_CHECK, "b"), (WITHHELD_CHECK,))

    assert unresolved_split(session) == (1, 2)


def test_a_session_that_withheld_nothing_puts_every_item_in_the_other_half() -> None:
    """Every shipped run is this one: the lever is off, so the first number is zero and
    that zero is a measurement rather than an absence."""
    session = session_with(("a", "b", "c"), ())

    assert unresolved_split(session) == (0, 3)


def test_a_withheld_check_the_run_resolved_anyway_counts_in_neither() -> None:
    """The count is over the items that are there, not over what was withheld: a check a
    later call covered is not unresolved, and the row must not claim it is."""
    session = session_with(("a",), (WITHHELD_CHECK,))

    assert unresolved_split(session) == (0, 1)


def test_the_two_numbers_sum_to_the_unresolved_bucket_and_not_to_unresolved_count() -> None:
    """`unresolved_count` counts findings; this splits coverage items. Adding one to the
    other is the confusion this assertion exists to prevent."""
    session = session_with(("a", WITHHELD_CHECK, "b"), (WITHHELD_CHECK,))

    because, other = unresolved_split(session)

    assert because + other == coverage_bucket_mix(session)["unresolved"]


# --- 2. what the run records ------------------------------------------------------------


def test_the_scorecard_carries_both_numbers(tmp_path: Path) -> None:
    scorecard = score(
        tmp_path,
        coverage=Coverage(unresolved=[item("a"), item(WITHHELD_CHECK)]),
        withheld_checks=[WITHHELD_CHECK],
    )

    package = scorecard.per_package[0]
    assert package.unresolved_because_withheld == 1
    assert package.unresolved_other == 1


def test_the_scorecard_contract_holds_both_numbers(tmp_path: Path) -> None:
    """`contracts/scorecard.schema.json` is `additionalProperties: false` with every
    property also required, so a field the model carries and the contract does not is a
    validation error rather than a quiet extra key."""
    scorecard = score(tmp_path, withheld_checks=[WITHHELD_CHECK])
    validator = contract_validator("scorecard.schema.json")

    validator.validate(json.loads(scorecard.model_dump_json()))


@pytest.mark.parametrize("field", ["unresolved_because_withheld", "unresolved_other"])
def test_the_contract_requires_the_field_rather_than_merely_allowing_it(field: str) -> None:
    contract = contract_validator("scorecard.schema.json").schema
    package = contract["$defs"]["PackageScore"]

    assert field in package["properties"]
    assert field in package["required"]
