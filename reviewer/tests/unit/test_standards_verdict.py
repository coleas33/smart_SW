"""The release verdict: a state, six counts, the unresolved ids and the notes (T025).

FR-032 is three sentences and this module is the whole of them:

- `state` is computed from the **error count and the unresolved coverage alone**. A warning
  never moves it, and a waived finding is not an error - which is what lets a run reach
  `ready` with waivers, and is why the waived count and its note travel beside it;
- the counts in **every** bucket and the unresolved check ids travel with the verdict in
  **every** state, not only the third, so a page cannot render a headline without them;
- **no letter grade and no single number**. Feature 003's `RmsGrade` carries a fraction as
  its secondary number; a release verdict carries none, because "ready" is not a score.

**The unit is stated, because the six counts do not share one**: `error`, `warning` and
`waived` count **findings** - one per failing check per document (FR-003) - and the four
coverage counts count **(check, document) pairs**, so they do not sum to sixteen. That is
asserted here rather than left to the page to get right, and `COUNT_UNITS` is what the page
and the report label them from.
"""

from __future__ import annotations

import re
from dataclasses import fields

import pytest

from swreview.checks.standards import verdict as verdict_module
from swreview.checks.standards.verdict import (
    COUNT_UNITS,
    BucketCounts,
    CoveragePair,
    FindingOutcome,
    ReleaseVerdict,
    release_verdict,
)

ASSEMBLY = "standards.assembly.not_exploded"
MATES = "standards.assembly.mate_references"
MATERIAL = "standards.part.material_assigned"
CARD = "standards.document.data_card_complete"
REVISION = "standards.drawing.revision_matches"


def failing(check: str = MATERIAL, *, waived: bool = False) -> FindingOutcome:
    return FindingOutcome(check=check, severity="error", waived=waived)


def warning(check: str = REVISION) -> FindingOutcome:
    return FindingOutcome(check=check, severity="warning")


def pairs(bucket: str, check: str, *document_ids: str) -> list[CoveragePair]:
    return [
        CoveragePair(check=check, document_id=document_id, bucket=bucket)  # type: ignore[arg-type]
        for document_id in document_ids
    ]


# --- the state ------------------------------------------------------------------------------


class TestTheState:
    def test_one_error_is_not_ready(self) -> None:
        answer = release_verdict(
            findings=[failing()], coverage=pairs("checked", ASSEMBLY, "doc:1")
        )

        assert answer.state == "not_ready"

    def test_no_error_and_no_unresolved_row_is_ready(self) -> None:
        answer = release_verdict(findings=[], coverage=pairs("checked", ASSEMBLY, "doc:1"))

        assert answer.state == "ready"

    def test_no_error_and_one_unresolved_row_is_ready_coverage_incomplete(self) -> None:
        answer = release_verdict(
            findings=[],
            coverage=pairs("checked", ASSEMBLY, "doc:1") + pairs("unresolved", MATES, "doc:1"),
        )

        assert answer.state == "ready_coverage_incomplete"

    def test_an_error_outranks_unresolved_coverage(self) -> None:
        """The state is read from the error count first; coverage decides the other two."""
        answer = release_verdict(
            findings=[failing()], coverage=pairs("unresolved", MATES, "doc:1")
        )

        assert answer.state == "not_ready"

    def test_a_warning_finding_never_moves_the_state(self) -> None:
        answer = release_verdict(
            findings=[warning(), warning()], coverage=pairs("checked", ASSEMBLY, "doc:1")
        )

        assert answer.state == "ready"
        assert answer.counts.warning == 2

    def test_a_waived_error_is_not_an_error(self) -> None:
        answer = release_verdict(
            findings=[failing(waived=True)], coverage=pairs("checked", ASSEMBLY, "doc:1")
        )

        assert answer.state == "ready"
        assert answer.counts.error == 0
        assert answer.waived == 1

    def test_a_skipped_row_does_not_make_coverage_incomplete(self) -> None:
        """A skip is a stated decision; only an unresolved row is missing evidence."""
        answer = release_verdict(findings=[], coverage=pairs("skipped", CARD, "doc:1"))

        assert answer.state == "ready"

    def test_an_out_of_scope_row_does_not_make_coverage_incomplete(self) -> None:
        answer = release_verdict(findings=[], coverage=pairs("out_of_scope", REVISION, "doc:1"))

        assert answer.state == "ready"


# --- what travels in every state -------------------------------------------------------------


class TestWhatTravelsWithEveryVerdict:
    @pytest.mark.parametrize(
        ("findings", "state"),
        [
            ([failing()], "not_ready"),
            ([], "ready_coverage_incomplete"),
            ([warning()], "ready_coverage_incomplete"),
        ],
    )
    def test_the_counts_and_the_unresolved_ids_travel_in_every_state(
        self, findings: list[FindingOutcome], state: str
    ) -> None:
        answer = release_verdict(
            findings=findings,
            coverage=(
                pairs("checked", ASSEMBLY, "doc:1", "doc:2")
                + pairs("skipped", CARD, "doc:1")
                + pairs("unresolved", MATES, "doc:1")
                + pairs("out_of_scope", REVISION, "doc:1", "doc:2")
            ),
        )

        assert answer.state == state
        assert answer.counts.checked == 2
        assert answer.counts.skipped == 1
        assert answer.counts.unresolved == 1
        assert answer.counts.out_of_scope == 2
        assert answer.unresolved_check_ids == (MATES,)

    def test_a_ready_verdict_still_carries_its_counts(self) -> None:
        answer = release_verdict(findings=[], coverage=pairs("checked", ASSEMBLY, "doc:1"))

        assert answer.state == "ready"
        assert answer.counts == BucketCounts(checked=1)
        assert answer.unresolved_check_ids == ()


# --- what each count counts ------------------------------------------------------------------


class TestTheCounts:
    def test_findings_are_counted_one_each_whatever_they_carry(self) -> None:
        """A finding is one per failing check per document, however many subjects it names."""
        answer = release_verdict(
            findings=[failing(), failing(), warning()],
            coverage=[],
        )

        assert answer.counts.error == 2
        assert answer.counts.warning == 1

    def test_coverage_counts_check_document_pairs(self) -> None:
        answer = release_verdict(
            findings=[], coverage=pairs("checked", ASSEMBLY, "doc:1", "doc:2", "doc:3")
        )

        assert answer.counts.checked == 3

    def test_one_check_landing_in_two_buckets_contributes_to_both(self) -> None:
        answer = release_verdict(
            findings=[],
            coverage=(
                pairs("checked", MATES, "doc:1", "doc:2") + pairs("unresolved", MATES, "doc:3")
            ),
        )

        assert answer.counts.checked == 2
        assert answer.counts.unresolved == 1

    def test_the_same_pair_in_the_same_bucket_is_counted_once(self) -> None:
        answer = release_verdict(
            findings=[], coverage=pairs("checked", ASSEMBLY, "doc:1") * 3
        )

        assert answer.counts.checked == 1

    def test_the_six_counts_do_not_sum_to_sixteen_and_are_not_expected_to(self) -> None:
        answer = release_verdict(
            findings=[failing()],
            coverage=(
                pairs("checked", ASSEMBLY, "doc:1", "doc:2")
                + pairs("unresolved", ASSEMBLY, "doc:3")
                + pairs("out_of_scope", REVISION, "doc:1", "doc:2", "doc:3")
            ),
        )

        counted = sum(getattr(answer.counts, field.name) for field in fields(BucketCounts))

        assert counted == 7
        assert counted != 16

    def test_every_count_states_its_unit(self) -> None:
        assert set(COUNT_UNITS) == {field.name for field in fields(BucketCounts)} | {"waived"}
        assert COUNT_UNITS["error"] == COUNT_UNITS["warning"] == COUNT_UNITS["waived"]
        assert COUNT_UNITS["error"] == "findings"
        assert {COUNT_UNITS[bucket] for bucket in ("checked", "skipped", "unresolved",
                                                   "out_of_scope")} == {"(check, document) pairs"}


class TestTheUnresolvedCheckIds:
    def test_they_are_the_checks_with_an_unresolved_pair_deduplicated_in_order(self) -> None:
        answer = release_verdict(
            findings=[],
            coverage=(
                pairs("unresolved", MATES, "doc:1", "doc:2")
                + pairs("unresolved", MATERIAL, "doc:3")
                + pairs("checked", ASSEMBLY, "doc:1")
            ),
        )

        assert answer.unresolved_check_ids == (MATES, MATERIAL)

    def test_a_check_unresolved_on_one_document_and_checked_on_another_is_named(self) -> None:
        answer = release_verdict(
            findings=[],
            coverage=pairs("checked", MATES, "doc:1") + pairs("unresolved", MATES, "doc:2"),
        )

        assert answer.unresolved_check_ids == (MATES,)
        assert answer.state == "ready_coverage_incomplete"


# --- the notes ---------------------------------------------------------------------------------


class TestTheNotes:
    def test_a_clean_run_that_graded_a_drawing_carries_no_note(self) -> None:
        answer = release_verdict(
            findings=[],
            coverage=pairs("checked", ASSEMBLY, "doc:1"),
            graded_kinds=["assembly", "drawing"],
        )

        assert answer.notes == ()

    def test_a_waiver_is_always_said(self) -> None:
        answer = release_verdict(
            findings=[failing(waived=True)],
            coverage=pairs("checked", ASSEMBLY, "doc:1"),
            graded_kinds=["assembly", "drawing"],
        )

        assert answer.notes == ("1 finding waived by an accepted exception",)

    def test_two_waivers_are_said_in_the_plural(self) -> None:
        answer = release_verdict(
            findings=[failing(waived=True), failing(CARD, waived=True)],
            coverage=[],
            graded_kinds=["drawing"],
        )

        assert answer.notes == ("2 findings waived by accepted exceptions",)

    def test_a_check_skipped_because_a_profile_setting_is_empty_is_said(self) -> None:
        answer = release_verdict(
            findings=[],
            coverage=pairs("skipped", CARD, "doc:1"),
            empty_setting_checks=[CARD, REVISION],
            graded_kinds=["part", "drawing"],
        )

        assert answer.notes == ("2 checks skipped because a profile list is empty",)

    def test_that_note_counts_checks_not_documents(self) -> None:
        answer = release_verdict(
            findings=[],
            coverage=pairs("skipped", CARD, "doc:1", "doc:2", "doc:3"),
            empty_setting_checks=[CARD, CARD],
            graded_kinds=["part", "drawing"],
        )

        assert answer.notes == ("1 check skipped because a profile list is empty",)

    def test_a_run_that_graded_no_drawing_says_so(self) -> None:
        answer = release_verdict(
            findings=[], coverage=[], graded_kinds=["assembly", "part", "part"]
        )

        assert answer.notes == ("no drawing graded",)

    def test_an_unknown_kind_is_not_a_drawing(self) -> None:
        answer = release_verdict(findings=[], coverage=[], graded_kinds=["assembly", None])

        assert answer.notes == ("no drawing graded",)

    def test_the_three_notes_are_said_in_one_order(self) -> None:
        answer = release_verdict(
            findings=[failing(waived=True)],
            coverage=pairs("unresolved", MATES, "doc:1"),
            empty_setting_checks=[CARD, REVISION],
            graded_kinds=["assembly"],
        )

        assert answer.notes == (
            "1 finding waived by an accepted exception",
            "2 checks skipped because a profile list is empty",
            "no drawing graded",
        )
        assert answer.state == "ready_coverage_incomplete"


# --- what no code path produces ------------------------------------------------------------


class TestNoLetterAndNoSingleNumber:
    def test_the_verdict_carries_exactly_five_things(self) -> None:
        assert [field.name for field in fields(ReleaseVerdict)] == [
            "state",
            "counts",
            "waived",
            "unresolved_check_ids",
            "notes",
        ]

    def test_the_counts_are_exactly_the_six_buckets(self) -> None:
        assert [field.name for field in fields(BucketCounts)] == [
            "error",
            "warning",
            "checked",
            "skipped",
            "unresolved",
            "out_of_scope",
        ]

    @pytest.mark.parametrize("name", ["grade", "score", "fraction", "percent", "ratio", "letter"])
    def test_no_name_in_this_module_offers_one(self, name: str) -> None:
        public = [item for item in dir(verdict_module) if not item.startswith("_")]

        assert not [item for item in public if name in item.lower()]

    def test_the_state_is_one_of_three_words_and_never_a_letter(self) -> None:
        states = {
            release_verdict(findings=[failing()], coverage=[]).state,
            release_verdict(findings=[], coverage=[]).state,
            release_verdict(
                findings=[], coverage=pairs("unresolved", MATES, "doc:1")
            ).state,
        }

        assert states == {"not_ready", "ready", "ready_coverage_incomplete"}
        assert all(re.fullmatch(r"[a-z_]{4,}", state) for state in states)
