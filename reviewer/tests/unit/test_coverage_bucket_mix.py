"""The closing coverage bucket mix on the scorecard (T083), lever 7's second guard.

**This ships with lever 7, not after it.** The stop predicate turns `mark_coverage` from
bookkeeping into a *turn-ending* call, and that changes what a model has to gain by using
it: nine `mark_coverage(bucket="skipped")` calls close the checklist, end the turn and
produce a short, cheap run. Today such a run merely makes a bad report. With lever 7 it
also **looks efficient in the results table** (RK-7), and every number the table already
carries agrees with it: the tokens fall, the round trips fall, and `unresolved_count` -
which counts *findings* with an unresolved status, not coverage items - does not move at
all.

`test_a_skipped_out_run_is_indistinguishable_except_for_the_mix` is that argument written
as a test: two sessions identical in every scored column but the mix. Without the
breakdown the arm cannot be read, which is why lever 7 cannot be gated without it.

The mix names all five buckets always, zeros included, because a bucket that is absent
from one arm's JSON and present in the other's cannot be compared - and `0` here is a real
measurement, not the "not measured" that `None` means everywhere else in this feature.
"""

from __future__ import annotations

import json
from pathlib import Path

from swreview.benchmark.scorecard import coverage_bucket_mix
from swreview.report.session import Coverage, CoverageItem, CoverageScope
from tests.support.contracts import contract_validator
from tests.unit.test_scorecard_usage import score
from tests.unit.test_stop_predicate import CHECKLIST, empty_session


def item(check: str) -> CoverageItem:
    return CoverageItem(check=check, scope=CoverageScope(), reason="because", error=None)


def coverage(**buckets: int) -> Coverage:
    """A `Coverage` holding `n` items in each named bucket, named after the bucket."""
    return Coverage(
        **{
            bucket: [item(f"{bucket}.{index}") for index in range(count)]
            for bucket, count in buckets.items()
        }
    )


def closed_out(bucket: str) -> Coverage:
    """Every checklist item closed out in one bucket: the nine-`skipped` run, and its twin."""
    return Coverage(**{bucket: [item(entry.id) for entry in CHECKLIST.items]})


# --- the breakdown itself -----------------------------------------------------------------


def test_the_mix_counts_the_items_in_each_bucket() -> None:
    session = empty_session(coverage=coverage(checked=3, skipped=2, failed=1))

    mix = coverage_bucket_mix(session)

    assert mix["checked"] == 3
    assert mix["skipped"] == 2
    assert mix["failed"] == 1


def test_every_bucket_is_named_even_when_it_holds_nothing() -> None:
    """Zero, not absent: two arms' rows have to line up column for column."""
    assert coverage_bucket_mix(empty_session()) == {
        "checked": 0,
        "skipped": 0,
        "unresolved": 0,
        "failed": 0,
        "out_of_scope": 0,
    }


def test_the_mix_names_exactly_the_buckets_the_session_model_has() -> None:
    """Pinned against `Coverage` itself, so a sixth bucket cannot be silently dropped."""
    session = empty_session(coverage=coverage(checked=1))

    assert list(coverage_bucket_mix(session)) == list(Coverage.model_fields)


# --- why the lever cannot be gated without it ---------------------------------------------


def test_a_skipped_out_run_is_indistinguishable_except_for_the_mix(tmp_path: Path) -> None:
    """RK-7 as a test: the cheap run and the real one differ in exactly one column."""
    checked = score(tmp_path / "checked", coverage=closed_out("checked")).per_package[0]
    skipped = score(tmp_path / "skipped", coverage=closed_out("skipped")).per_package[0]

    comparable = {"coverage_bucket_mix"}
    assert skipped.model_dump(exclude=comparable) == checked.model_dump(exclude=comparable)
    assert checked.coverage_bucket_mix["checked"] == len(CHECKLIST.items)
    assert checked.coverage_bucket_mix["skipped"] == 0
    assert skipped.coverage_bucket_mix["skipped"] == len(CHECKLIST.items)
    assert skipped.coverage_bucket_mix["checked"] == 0


# --- on the scorecard ----------------------------------------------------------------------


def test_the_package_score_carries_the_mix_of_its_session(tmp_path: Path) -> None:
    scorecard = score(tmp_path, coverage=coverage(checked=2, out_of_scope=1))

    assert scorecard.per_package[0].coverage_bucket_mix == {
        "checked": 2,
        "skipped": 0,
        "unresolved": 0,
        "failed": 0,
        "out_of_scope": 1,
    }


def test_a_session_that_recorded_no_coverage_scores_five_zeros(tmp_path: Path) -> None:
    """A run that covered nothing is a measurement, and an empty dict would hide it."""
    assert score(tmp_path).per_package[0].coverage_bucket_mix == dict.fromkeys(
        Coverage.model_fields, 0
    )


def test_the_scorecard_still_validates_against_the_contract(tmp_path: Path) -> None:
    """`coverage_bucket_mix` is an additive property with its own entry in `required`."""
    scorecard = score(tmp_path, coverage=coverage(skipped=1))

    contract_validator("scorecard.schema.json").validate(json.loads(scorecard.model_dump_json()))
