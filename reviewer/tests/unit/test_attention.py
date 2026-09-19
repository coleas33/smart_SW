"""The attention policy: the nine keys, the two 2026-09-18 orders and the empty cases (T017).

`report/attention.py` answers one question - which findings does the engineer read first -
with a total order of nine named lookups and no weights (`contracts/attention.md` section
1). This module pins that order from four directions, because each one is a different way
the rule can go wrong:

1. **One key at a time.** A table of nine pairs, each differing in one field of the
   finding, each decided by exactly one key. A pair proves both that the key fires and
   that it fires *where it does*: the two rows' key tuples must first differ at that
   position.
2. **The whole space at once.** The 4 statuses by 4 severities by 4 disposition states by
   2 exception states, 128 findings, ranked in one call. It proves `rank` is total - it
   raises on nothing - that `checked_within_scope` and the two decided dispositions sort
   last, and that `exception_id` is never read, which is the one thing a reasonable
   implementation gets wrong (research R2.1).
3. **The two committed sessions.** The orders the owner agreed on 2026-09-19 over the
   handover folders (research R2.15, `quickstart.md` Scenario 2), and the same order from
   a shuffled session, byte for byte (FR-014).
4. **The edges.** A session with no findings, a session of nothing but informational
   findings, a check id no table names, a finding with no component at all, and a module
   that must load no provider, no settings and no network code (FR-015).

`tests/unit/test_attention_fold.py` carries the fold (FR-012); `test_attention_policy_file.py`
carries the data file's own shape; the catalogue of every emittable id is T023.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from itertools import product
from typing import Any
from uuid import UUID, uuid5

import pytest

from swreview.agent.checklist import load_checklist
from swreview.findings import Disposition, Finding
from swreview.ir.models import SourceRef
from swreview.report.attention import (
    CHECKLIST_ITEM_IDS,
    CONSEQUENCE_ORDER,
    EMPTY_ALL_DECIDED,
    EMPTY_NO_FINDINGS,
    MAX_NOT_CLOSED,
    MAX_REACH,
    SEVERITY_ORDER,
    STATUS_ORDER,
    TOP_N,
    AttentionKey,
    Ranking,
    coverage_line,
    load_policy,
    rank,
    start_here_lines,
)
from swreview.report.session import ReviewSession, load_session
from tests.support.attention import (
    ASSEMBLY_DOCUMENT,
    CHECK_SESSION_FILE,
    PART_COMPONENT,
    PIN_ONE,
    PIN_TWO,
    REVIEW_SESSION_FILE,
    CoverageRow,
    CoverageSpec,
    FindingSpec,
    build_attention_session,
)

# --- building a session for one question --------------------------------------------------

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-000000000007")
"""Session ids are derived from the test's own name, so no two sessions here collide."""

STEPS: tuple[str, ...] = ("check_rms_part", "check_rms_assembly")
"""Two steps, so `tool_result_ids=(0,)` on any spec below names a step that exists."""

DECIDED_AT = "2026-09-19T09:00:00+00:00"


def disposition(decision: str) -> Disposition:
    return Disposition(
        decision=decision,  # type: ignore[arg-type]
        note=f"the engineer {decision} this finding",
        by="engineer@example.com",
        at=DECIDED_AT,
    )


def session_of(
    name: str,
    specs: Sequence[FindingSpec],
    coverage: CoverageSpec | None = None,
) -> ReviewSession:
    """A finished session over `specs`, named so its session id is stable and unique."""
    return build_attention_session(
        session_id=uuid5(NAMESPACE, name),
        findings=specs,
        coverage=coverage if coverage is not None else CoverageSpec(),
        steps=STEPS,
    )


def spec(check: str, **fields: Any) -> FindingSpec:
    """A finding that satisfies `build_finding` whatever status it is given.

    `tool_result_ids` covers the two numeric statuses and `coverage_limits` covers
    `unresolved`, so a caller here states only what the key under test reads.
    """
    fields.setdefault("component_ids", (PART_COMPONENT,))
    fields.setdefault("tool_result_ids", (0,))
    fields.setdefault("coverage_limits", ("measured in the Default configuration only.",))
    return FindingSpec(check=check, **fields)


KEY_NAMES: tuple[str, ...] = (
    "suppressed",
    "judgement",
    "consequence",
    "status",
    "severity",
    "reach",
    "carried",
    "check",
    "finding_id",
)
"""The nine positions of `contracts/attention.md` section 1, in sort order."""


def key_tuple(key: AttentionKey) -> tuple[int | str, ...]:
    return tuple(getattr(key, name) for name in KEY_NAMES)


def first_difference(first: AttentionKey, second: AttentionKey) -> int:
    """The 1-based position of the first key the two rows differ on."""
    pairs = zip(key_tuple(first), key_tuple(second), strict=True)
    for position, (left, right) in enumerate(pairs, start=1):
        if left != right:
            return position
    raise AssertionError("the two rows carry identical keys; no key can have placed them")


def order_of(ranking: Ranking) -> list[str]:
    return [row.finding_id for row in ranking.rows]


def rendered(ranking: Ranking) -> list[str]:
    """Every line the two renderers produce, which is every string an engineer reads."""
    return [*start_here_lines(ranking), *coverage_line(ranking)]


# --- 1. one key at a time ------------------------------------------------------------------

CARRIED_FROM = UUID("11111111-1111-4111-8111-111111111111")
CARRIED_AT = "2026-09-17T08:30:00+00:00"

KEY_PAIRS: tuple[tuple[int, str, FindingSpec, FindingSpec], ...] = (
    (
        1,
        "an undecided finding outranks one the engineer accepted",
        spec("rms.grouping.all_features_in_a_group"),
        spec("rms.grouping.all_features_in_a_group", disposition=disposition("accepted")),
    ),
    (
        2,
        "a needs-judgement check outranks another interface check",
        spec("fit.size_only"),
        spec("stack.worst_case"),
    ),
    (
        3,
        "a rebuild breaker outranks a discipline rule",
        spec("rms.sketches.fully_defined"),
        spec("rms.grouping.all_features_in_a_group"),
    ),
    (
        4,
        "demonstrated outranks suspected",
        spec("rms.grouping.all_features_in_a_group", status="demonstrated"),
        spec("rms.grouping.all_features_in_a_group", status="suspected"),
    ),
    (
        5,
        "high severity outranks medium, read verbatim off the finding",
        spec("rms.grouping.all_features_in_a_group", severity="high"),
        spec("rms.grouping.all_features_in_a_group", severity="medium"),
    ),
    (
        6,
        "two distinct components outrank one",
        spec("rms.grouping.all_features_in_a_group", component_ids=(PART_COMPONENT, PIN_ONE)),
        spec("rms.grouping.all_features_in_a_group", component_ids=(PART_COMPONENT,)),
    ),
    (
        7,
        "a fresh finding outranks the same verdict carried over",
        spec("rms.grouping.all_features_in_a_group"),
        spec(
            "rms.grouping.all_features_in_a_group",
            carried_over_from=CARRIED_FROM,
            carried_over_at=CARRIED_AT,
            carry_over_key="fixture-key",
        ),
    ),
    (
        8,
        "two equal discipline rules fall back to the check id",
        spec("rms.params.dimensions_driven_by_equations"),
        spec("rms.params.global_variables_present"),
    ),
    (
        9,
        "two identical findings fall back to the finding id",
        spec("rms.grouping.all_features_in_a_group"),
        spec("rms.grouping.all_features_in_a_group"),
    ),
)
"""`(key position, what it settles, the winner, the loser)` - one pair per key.

Every pair differs in exactly one field of the finding and is decided by exactly one key.
The pairs are written winner first and fed to `rank` loser first, so a rule that happened
to preserve the recording order would fail all nine.
"""


@pytest.mark.parametrize(
    ("position", "what", "winner", "loser"),
    KEY_PAIRS,
    ids=[f"{position}-{name}" for position, name, _, _ in KEY_PAIRS],
)
def test_each_key_places_its_pair(
    position: int, what: str, winner: FindingSpec, loser: FindingSpec
) -> None:
    ranking = rank(session_of(f"key-{position}", [loser, winner]))

    assert len(ranking.rows) == 2, f"{what}: the pair folded, so no key placed anything"
    first, second = ranking.rows
    assert first_difference(first.key, second.key) == position, (
        f"{what}: the pair was settled by key "
        f"{first_difference(first.key, second.key)}, not key {position} "
        f"({KEY_NAMES[position - 1]})"
    )
    # The winner was recorded second, so `F-002` leading is the rule and not the order.
    expected = "F-001" if position == 9 else "F-002"
    assert first.finding_id == expected, what


def test_the_table_settles_each_of_the_nine_keys_exactly_once() -> None:
    """A table that tested key 3 twice and key 6 never would still pass every case above."""
    positions = [position for position, _, _, _ in KEY_PAIRS]

    assert sorted(positions) == list(range(1, len(KEY_NAMES) + 1))


# --- 2. the whole space at once -------------------------------------------------------------

DISPOSITIONS: tuple[str | None, ...] = (None, "accepted", "rejected", "deferred")
EXCEPTION_IDS: tuple[str | None, ...] = (None, "EXC-001")
CROSS_PRODUCT_CHECK = "rms.grouping.all_features_in_a_group"
"""One discipline check for all 128, so keys 2, 3, 6, 7 and 8 are constant and the only
keys left to settle the order are 1, 4, 5 and 9."""


def cross_product_specs() -> list[FindingSpec]:
    """Every combination of status, severity, disposition and exception state.

    All 128 name the same one component, so none of them folds into another: the fold key
    is (check, status, severity) and two findings that share a subject never fold.
    """
    return [
        spec(
            CROSS_PRODUCT_CHECK,
            status=status,
            severity=severity,
            disposition=None if decision is None else disposition(decision),
            exception_id=exception_id,
        )
        for status, severity, decision, exception_id in product(
            STATUS_ORDER, SEVERITY_ORDER, DISPOSITIONS, EXCEPTION_IDS
        )
    ]


def is_suppressed(finding: Finding) -> bool:
    """FR-008, transcribed from the contract rather than read off the module under test."""
    return finding.status == "checked_within_scope" or (
        finding.disposition is not None and finding.disposition.decision in {"accepted", "rejected"}
    )


@pytest.fixture(scope="module")
def cross_product() -> tuple[ReviewSession, Ranking]:
    session = session_of("cross-product", cross_product_specs())
    return session, rank(session)


def test_the_cross_product_ranks_without_raising_and_drops_nothing(
    cross_product: tuple[ReviewSession, Ranking],
) -> None:
    """`rank` is total: 4 x 4 x 4 x 2 combinations, one call, every finding still a row."""
    session, ranking = cross_product

    assert len(session.findings) == 128
    assert len(ranking.rows) == 128, "a combination folded or was dropped"
    assert sorted(order_of(ranking)) == sorted(finding.id for finding in session.findings)


def test_suppressed_findings_sort_below_every_undecided_one(
    cross_product: tuple[ReviewSession, Ranking],
) -> None:
    session, ranking = cross_product
    by_id = {finding.id: finding for finding in session.findings}

    suppressed = [index for index, row in enumerate(ranking.rows) if row.key.suppressed]
    competing = [index for index, row in enumerate(ranking.rows) if not row.key.suppressed]

    assert suppressed and competing
    assert min(suppressed) > max(competing)
    assert {ranking.rows[index].finding_id for index in suppressed} == {
        finding.id for finding in session.findings if is_suppressed(finding)
    }
    assert all(is_suppressed(by_id[ranking.rows[index].finding_id]) for index in suppressed)


def test_a_deferred_disposition_keeps_competing(
    cross_product: tuple[ReviewSession, Ranking],
) -> None:
    """FR-008: deferred is not a decision, so the finding still wants the engineer."""
    session, ranking = cross_product
    deferred = {
        finding.id
        for finding in session.findings
        if finding.disposition is not None
        and finding.disposition.decision == "deferred"
        and finding.status != "checked_within_scope"
    }

    assert len(deferred) == 24, "three statuses by four severities by two exception states"
    placed = {row.finding_id: row.key.suppressed for row in ranking.rows}
    assert {placed[finding_id] for finding_id in deferred} == {0}


def test_the_exception_reference_is_never_read(
    cross_product: tuple[ReviewSession, Ranking],
) -> None:
    """Research R2.1: `exception_id` cannot tell a live waiver from one up for re-review."""
    session, ranking = cross_product
    keys = {row.finding_id: row.key for row in ranking.rows}
    by_state: dict[tuple[str, str, str | None], list[Finding]] = {}
    for finding in session.findings:
        decision = None if finding.disposition is None else finding.disposition.decision
        by_state.setdefault((finding.status, finding.severity, decision), []).append(finding)

    differing = []
    for state, twins in by_state.items():
        assert len(twins) == 2, state
        without, with_exception = sorted(twins, key=lambda one: one.exception_id or "")
        assert (without.exception_id, with_exception.exception_id) == (None, "EXC-001")
        left, right = keys[without.id], keys[with_exception.id]
        if key_tuple(left)[:-1] != key_tuple(right)[:-1]:
            differing.append((state, key_tuple(left), key_tuple(right)))

    assert differing == []


def test_within_a_suppression_bucket_the_order_is_status_then_severity_then_id(
    cross_product: tuple[ReviewSession, Ranking],
) -> None:
    """Keys 4, 5 and 9: everything else is constant across the 128."""
    session, ranking = cross_product

    def expected(finding: Finding) -> tuple[int, int, int, str]:
        return (
            1 if is_suppressed(finding) else 0,
            STATUS_ORDER.index(finding.status),
            SEVERITY_ORDER.index(finding.severity),
            finding.id,
        )

    assert order_of(ranking) == [finding.id for finding in sorted(session.findings, key=expected)]


# --- 3. the two committed sessions ----------------------------------------------------------

REVIEW_ORDER: tuple[str, ...] = (
    "F-007",
    "F-008",
    "F-004",
    "F-003",
    "F-002",
    "F-005",
    "F-006",
    "F-001",
)
"""The 2026-09-18 review, in the order the owner agreed (research R2.15, decision 1):

the two `interference.static` rows, `rms.assembly.mates_to_reference_geometry`,
`rms.sketches.fully_defined`, `rms.grouping.all_features_in_a_group`, then the two
remaining parameter rules, with `rms.folders.present` last of eight.
"""

REVIEW_CHECKS: tuple[str, ...] = (
    "interference.static",
    "interference.static",
    "rms.assembly.mates_to_reference_geometry",
    "rms.sketches.fully_defined",
    "rms.grouping.all_features_in_a_group",
    "rms.params.global_variables_present",
    "rms.params.dimensions_driven_by_equations",
    "rms.folders.present",
)

CHECK_ORDER: tuple[str, ...] = ("F-003", "F-002", "F-001")
CHECK_CHECKS: tuple[str, ...] = (
    "rms.sketches.fully_defined",
    "rms.grouping.all_features_in_a_group",
    "rms.folders.present",
)
"""The 2026-09-18 model check: no needs-judgement finding exists on that surface, so the
consequence class leads and the under-defined sketch is row one."""


def test_the_2026_09_18_review_ranks_in_the_order_the_owner_agreed() -> None:
    ranking = rank(load_session(REVIEW_SESSION_FILE))

    assert order_of(ranking) == list(REVIEW_ORDER)
    assert [row.check for row in ranking.rows] == list(REVIEW_CHECKS)
    assert ranking.rows[-1].check == "rms.folders.present"
    assert ranking.policy_version == "attention_policy_v1"
    assert ranking.empty_reason is None


def test_the_2026_09_18_model_check_leads_with_the_under_defined_sketch() -> None:
    ranking = rank(load_session(CHECK_SESSION_FILE))

    assert order_of(ranking) == list(CHECK_ORDER)
    assert [row.check for row in ranking.rows] == list(CHECK_CHECKS)


def test_every_row_of_the_review_names_the_key_that_placed_it() -> None:
    ranking = rank(load_session(REVIEW_SESSION_FILE))

    assert [row.reason for row in ranking.rows] == [
        "needs your judgement",
        "needs your judgement",
        "rebuild breaker, demonstrated",
        "rebuild breaker, demonstrated",
        "discipline, demonstrated",
        "discipline, demonstrated",
        "discipline, suspected",
        "hygiene, suspected",
    ]


def test_a_two_component_row_states_its_reach() -> None:
    """Key 6 is why the interference rows beat a one-component row of the same class."""
    ranking = rank(
        session_of(
            "reach-in-the-reason",
            [spec("stack.worst_case", component_ids=(PART_COMPONENT, PIN_TWO))],
        )
    )

    assert ranking.rows[0].reason == "interface, demonstrated, 2 components"
    assert ranking.rows[0].component_ids == sorted({PART_COMPONENT, PIN_TWO})


def test_ranking_the_review_with_its_findings_shuffled_is_byte_identical() -> None:
    """FR-014. Reversed, then rotated: two different arrivals of the same eight verdicts."""
    session = load_session(REVIEW_SESSION_FILE)
    expected = rank(session).model_dump_json(indent=2)

    reversed_session = load_session(REVIEW_SESSION_FILE)
    reversed_session.findings = list(reversed(reversed_session.findings))
    rotated_session = load_session(REVIEW_SESSION_FILE)
    rotated_session.findings = rotated_session.findings[3:] + rotated_session.findings[:3]

    assert rank(reversed_session).model_dump_json(indent=2) == expected
    assert rank(rotated_session).model_dump_json(indent=2) == expected


def test_ranking_the_same_session_twice_is_byte_identical() -> None:
    session = load_session(REVIEW_SESSION_FILE)

    assert rank(session).model_dump_json() == rank(session).model_dump_json()


# --- 4. the coverage block ---------------------------------------------------------------

REVIEW_NOT_CLOSED: tuple[str, ...] = (
    "fasteners",
    "holes.alignment",
    "interfaces.fit",
    "interfaces.stack",
    "drawing.manufacturing_inputs",
)
"""The first five of the seven close-out rows the run wrote; `provenance` and
`modeling.resilience` are the two it holds last and the block prints at most five."""


def test_the_review_coverage_block_is_the_runs_own_close_out() -> None:
    session = load_session(REVIEW_SESSION_FILE)
    reasons = {item.check: item.reason for item in session.coverage.unresolved}

    coverage = rank(session).coverage

    assert (coverage.checked, coverage.skipped) == (5, 11)
    assert (coverage.unresolved, coverage.failed, coverage.out_of_scope) == (39, 0, 7)
    assert [entry.item for entry in coverage.not_closed] == list(REVIEW_NOT_CLOSED)
    assert [entry.reason for entry in coverage.not_closed] == [
        reasons[item] for item in REVIEW_NOT_CLOSED
    ], "a close-out reason is the sentence the run recorded, verbatim"
    assert coverage.open_evidence_requests == 3
    assert (coverage.rules.unresolved, coverage.rules.skipped) == (28, 11)


CLOSEOUT_FIRST: tuple[str, ...] = (
    "coverage.closeout",
    *(item for item in CHECKLIST_ITEM_IDS if item != "coverage.closeout"),
)
"""The nine checklist ids with the run's own close-out row **leading** the session.

The committed review fixture holds that row last, where the five-row cap would drop it
anyway; a rule that never looked at the id would pass on the fixture alone.
"""


def close_out_rows(items: Sequence[str]) -> list[CoverageRow]:
    return [
        CoverageRow(check=item, reason=f"{item} was not reached on this run.") for item in items
    ]


def test_the_close_out_list_excludes_the_runs_own_close_out_row() -> None:
    """`coverage.closeout` is a checklist item id and is the run's own summary, not a gap.

    Decided 2026-09-19 after the Phase 1 builder surfaced it. Two rows here, the excluded
    one first, so neither the cap nor the session order can do the excluding.
    """
    session = session_of(
        "closeout-leading",
        [],
        CoverageSpec(unresolved=close_out_rows(("coverage.closeout", "fasteners"))),
    )

    ranking = rank(session)

    assert [entry.item for entry in ranking.coverage.not_closed] == ["fasteners"]
    assert all("coverage.closeout" not in line for line in coverage_line(ranking))
    assert ranking.coverage.rules.unresolved == 0, "the row is a close-out, not a rule"


def test_the_committed_review_never_lists_its_own_close_out_row() -> None:
    session = load_session(REVIEW_SESSION_FILE)
    assert any(item.check == "coverage.closeout" for item in session.coverage.unresolved)

    coverage = rank(session).coverage

    assert "coverage.closeout" not in [entry.item for entry in coverage.not_closed]


def test_at_most_five_close_out_rows_are_listed_in_session_order() -> None:
    session = session_of(
        "many-close-outs", [], CoverageSpec(unresolved=close_out_rows(CLOSEOUT_FIRST))
    )

    coverage = rank(session).coverage

    assert len(CLOSEOUT_FIRST) > MAX_NOT_CLOSED + 1, "the case needs more rows than the cap"
    assert [entry.item for entry in coverage.not_closed] == list(
        CLOSEOUT_FIRST[1 : MAX_NOT_CLOSED + 1]
    )


def test_a_check_folder_has_no_close_out_rows_and_still_states_its_rules() -> None:
    """A check closes one checklist item and writes no close-out rows (contract section 3)."""
    ranking = rank(load_session(CHECK_SESSION_FILE))

    assert ranking.coverage.not_closed == []
    assert ranking.coverage.open_evidence_requests == 0
    assert (ranking.coverage.rules.unresolved, ranking.coverage.rules.skipped) == (5, 11)
    assert coverage_line(ranking) == [
        "What this run could not reach: 5 unresolved, 11 skipped, 0 failed, 6 out of scope.",
        "- 5 rules unresolved and 11 skipped.",
    ]


def test_the_review_coverage_lines_read_as_the_contract_states_them() -> None:
    session = load_session(REVIEW_SESSION_FILE)
    reasons = {item.check: item.reason for item in session.coverage.unresolved}

    lines = coverage_line(rank(session))

    assert lines[0] == (
        "What this run could not reach: 39 unresolved, 11 skipped, 0 failed, 7 out of scope."
    )
    assert lines[1:6] == [f"- {item}: {reasons[item]}" for item in REVIEW_NOT_CLOSED]
    assert lines[6] == "- 3 evidence requests are still open; 28 rules unresolved and 11 skipped."
    assert len(lines) == 7


def test_the_checklist_item_ids_the_module_carries_are_the_checklists_own() -> None:
    """The module may not import the checklist loader (FR-015), so drift is caught here.

    `agent/checklist.py` imports `report/session.py`, which imports the provider port and
    the settings module; a pure policy that pulled the loader in for nine strings would
    fail the import test below. The ids are a module constant instead, and this is the
    assertion that keeps the copy honest.
    """
    assert CHECKLIST_ITEM_IDS == tuple(item.id for item in load_checklist().items)


# --- 5. the edges ----------------------------------------------------------------------------


def test_a_session_with_no_findings_says_so_and_still_states_its_coverage() -> None:
    session = session_of(
        "no-findings",
        [],
        CoverageSpec(checked=4, skipped=2, unresolved=3, failed=1, out_of_scope=0),
    )

    ranking = rank(session)

    assert ranking.rows == []
    assert ranking.empty_reason == EMPTY_NO_FINDINGS
    assert start_here_lines(ranking) == ["Nothing to start with: no findings were recorded."]
    assert coverage_line(ranking) == [
        "What this run could not reach: 3 unresolved, 2 skipped, 1 failed, 0 out of scope.",
        "- 3 rules unresolved and 2 skipped.",
    ]
    assert ranking.not_amplified.total == 0


def test_an_all_informational_session_lists_no_rows_and_counts_them() -> None:
    session = session_of(
        "all-informational",
        [
            spec("rms.grouping.all_features_in_a_group", severity="info"),
            spec("rms.folders.present", severity="info", status="suspected"),
            spec(
                "rms.sketches.fully_defined",
                status="checked_within_scope",
                severity="info",
            ),
        ],
    )

    ranking = rank(session)

    assert ranking.empty_reason == EMPTY_ALL_DECIDED
    assert len(ranking.rows) == 3, "amplify, never filter: the rows are still ranked"
    assert start_here_lines(ranking) == [
        "Nothing to start with: every finding is informational or already decided.",
        "",
        "Not amplified: 3 findings (1 checked within scope, 0 already decided, "
        "2 informational, 0 beyond the top five).",
    ]


def test_a_session_of_nothing_but_decided_findings_says_the_same() -> None:
    session = session_of(
        "all-decided",
        [
            spec("rms.grouping.all_features_in_a_group", disposition=disposition("accepted")),
            spec("rms.folders.present", disposition=disposition("rejected")),
        ],
    )

    ranking = rank(session)

    assert ranking.empty_reason == EMPTY_ALL_DECIDED
    assert ranking.not_amplified.dispositioned == 2
    assert [row.reason for row in ranking.rows] == ["already accepted", "already rejected"]


def test_a_deferred_finding_alone_is_not_an_empty_section() -> None:
    session = session_of(
        "one-deferred",
        [spec("rms.grouping.all_features_in_a_group", disposition=disposition("deferred"))],
    )

    ranking = rank(session)

    assert ranking.empty_reason is None
    assert start_here_lines(ranking)[0] == (
        "1. **F-001** `rms.grouping.all_features_in_a_group` - discipline, demonstrated"
    )


def test_the_not_amplified_line_accounts_for_every_finding_below_the_top_five() -> None:
    ranking = rank(load_session(REVIEW_SESSION_FILE))

    not_amplified = ranking.not_amplified
    assert (not_amplified.total, not_amplified.beyond_top_n) == (3, 3)
    assert (not_amplified.checked_within_scope, not_amplified.dispositioned) == (0, 0)
    assert not_amplified.info == 0
    assert start_here_lines(ranking)[-1] == (
        "Not amplified: 3 findings (0 checked within scope, 0 already decided, "
        "0 informational, 3 beyond the top five)."
    )


def test_the_not_amplified_line_names_each_reason_a_finding_was_not_amplified() -> None:
    session = session_of(
        "mixed-not-amplified",
        [
            *(spec(f"rms.advisory.{name}") for name in ("avoid_multibody", "core_shaping_cuts")),
            *(
                spec(check)
                for check in (
                    "rms.grouping.all_features_in_a_group",
                    "rms.params.global_variables_present",
                    "rms.params.dimensions_driven_by_equations",
                    "rms.folders.present",
                )
            ),
            spec("rms.detail.holes_last", status="checked_within_scope"),
            spec("rms.core.shell_last", disposition=disposition("rejected")),
            spec("rms.groups.no_solids_in_ref_or_construction", severity="info"),
        ],
    )

    ranking = rank(session)

    assert len(ranking.rows) == 9
    not_amplified = ranking.not_amplified
    assert not_amplified.total == 4
    assert not_amplified.checked_within_scope == 1
    assert not_amplified.dispositioned == 1
    assert not_amplified.info == 1
    assert not_amplified.beyond_top_n == 1


def test_a_drawing_finding_reaches_no_component_and_is_not_dropped() -> None:
    """Research R2.5: reach is a key, never a filter; a drawing row competes on the rest."""
    session = session_of(
        "drawing-finding",
        [
            spec(
                "drawing.manufacturing_inputs",
                status="suspected",
                numeric=False,
                component_ids=(),
                drawing_locations=(SourceRef(document_id=ASSEMBLY_DOCUMENT, sheet="Sheet1"),),
            ),
            spec("rms.grouping.all_features_in_a_group"),
        ],
    )

    ranking = rank(session)

    drawing = next(row for row in ranking.rows if row.check == "drawing.manufacturing_inputs")
    assert drawing.component_ids == []
    assert drawing.key.reach == MAX_REACH, "no distinct component is the bottom of key 6"
    assert drawing.reason == "manufacturing, suspected"
    assert order_of(ranking) == ["F-001", "F-002"], "manufacturing outranks discipline"


def test_a_needs_judgement_finding_checked_within_scope_sorts_last() -> None:
    """Key 1 runs before key 2: a clean numeric pass needs none of the engineer's minutes."""
    session = session_of(
        "judgement-checked-within-scope",
        [
            spec(
                "interference.static",
                status="checked_within_scope",
                severity="info",
                component_ids=(PART_COMPONENT, PIN_ONE),
            ),
            spec("rms.folders.present", status="suspected", severity="low"),
        ],
    )

    ranking = rank(session)

    assert order_of(ranking) == ["F-002", "F-001"]
    assert ranking.rows[-1].reason == "checked within scope"


def test_a_carried_over_finding_sorts_below_an_otherwise_identical_fresh_one() -> None:
    session = session_of(
        "carried-over",
        [
            spec(
                "rms.grouping.all_features_in_a_group",
                carried_over_from=CARRIED_FROM,
                carried_over_at=CARRIED_AT,
                carry_over_key="fixture-key",
            ),
            spec("rms.grouping.all_features_in_a_group"),
        ],
    )

    ranking = rank(session)

    assert order_of(ranking) == ["F-002", "F-001"]
    assert [row.key.carried for row in ranking.rows] == [0, 1]
    assert ranking.rows[-1].reason == "discipline, demonstrated, carried over"


UNNAMED_CHECK = "future.family.a_rule_no_table_names"
"""A check id `attention_policy_v1.yaml` does not name, and no needs-judgement prefix."""


def test_a_check_no_table_names_sorts_as_unclassified_and_is_printed_by_name() -> None:
    """FR-010: the omission is visible on the report rather than silently a low rank."""
    assert UNNAMED_CHECK not in load_policy().classes

    session = session_of(
        "unclassified",
        [
            spec("rms.grouping.all_features_in_a_group"),
            spec(UNNAMED_CHECK),
            spec("standards.drawing.revision_matches"),
        ],
    )

    ranking = rank(session)

    assert [row.check for row in ranking.rows] == [
        "standards.drawing.revision_matches",
        UNNAMED_CHECK,
        "rms.grouping.all_features_in_a_group",
    ], "unclassified sorts between manufacturing and discipline"
    assert [row.consequence_class for row in ranking.rows] == [
        "manufacturing",
        "unclassified",
        "discipline",
    ]
    assert ranking.rows[1].reason == f"unclassified check `{UNNAMED_CHECK}`, demonstrated"
    assert UNNAMED_CHECK in start_here_lines(ranking)[1]


def test_unclassified_sits_between_manufacturing_and_discipline_in_the_declared_order() -> None:
    assert CONSEQUENCE_ORDER == (
        "rebuild_breaker",
        "interface",
        "manufacturing",
        "unclassified",
        "discipline",
        "hygiene",
    )


def test_the_top_five_are_the_first_five_rows_and_the_rest_still_rank() -> None:
    ranking = rank(load_session(REVIEW_SESSION_FILE))

    assert ranking.top_n == TOP_N
    assert len(start_here_lines(ranking)) == TOP_N + 2, "five rows, a blank, the summary line"
    assert len(ranking.rows) == 8, "amplify, never filter"


# --- 6. the rules about the words themselves --------------------------------------------------


@pytest.mark.parametrize("path", [REVIEW_SESSION_FILE, CHECK_SESSION_FILE], ids=["review", "check"])
def test_no_rendered_string_carries_a_percent_sign(path: Any) -> None:
    """Research R2.14: the Standards page's body scan forbids one anywhere it renders."""
    ranking = rank(load_session(path))

    offenders = [line for line in rendered(ranking) if "%" in line]

    assert offenders == []
    assert "%" not in ranking.model_dump_json()


def test_no_percent_sign_reaches_an_edge_case_line_either() -> None:
    sessions = [
        session_of("percent-empty", []),
        session_of("percent-info", [spec("rms.folders.present", severity="info")]),
        session_of("percent-unclassified", [spec(UNNAMED_CHECK)]),
    ]

    offenders = [line for session in sessions for line in rendered(rank(session)) if "%" in line]

    assert offenders == []


def test_every_row_line_names_the_finding_the_check_and_the_reason() -> None:
    ranking = rank(load_session(REVIEW_SESSION_FILE))

    lines = start_here_lines(ranking)[:TOP_N]

    assert lines[0] == (
        "1. **F-007** `interference.static` - needs your judgement "
        "(Static interference between the housing and the second pin)"
    )
    assert lines[2] == (
        "3. **F-004** `rms.assembly.mates_to_reference_geometry` - rebuild breaker, demonstrated"
    )
    rows = zip(lines, ranking.rows[:TOP_N], strict=True)
    for number, (line, row) in enumerate(rows, start=1):
        assert line.startswith(f"{number}. **{row.finding_id}** `{row.check}` - {row.reason}")


# --- 7. the module is pure ---------------------------------------------------------------------

FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "swreview.agent.providers",
    "swreview.agent.settings",
    "httpx",
    "openai",
    "google",
)
"""FR-015. The policy is read on a keyless tab and in an offline command; a module that
pulled a provider SDK in would make both of those pay for an import they never use, and
would let a future edit read a key from a rank."""


def test_importing_the_policy_module_loads_no_provider_settings_or_network_module() -> None:
    code = "import sys, swreview.report.attention; print('\\n'.join(sorted(sys.modules)))"

    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    loaded = completed.stdout.split()
    assert "swreview.report.attention" in loaded, completed.stderr
    forbidden = sorted(
        name
        for name in loaded
        for prefix in FORBIDDEN_IMPORTS
        if name == prefix or name.startswith(f"{prefix}.")
    )
    assert forbidden == []


def test_the_policy_file_is_read_once_however_many_sessions_are_ranked() -> None:
    """FR-015's other half: no I/O beyond loading the table, and the table loads once."""
    first = load_policy()

    assert rank(session_of("cache-a", [spec("rms.folders.present")])) is not None
    assert load_policy() is first
