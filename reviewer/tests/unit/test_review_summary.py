"""The review summary (feature 009 T009), against `contracts/review-summary.md` 2 and 4.

The Review tab prints the summary and counts nothing (FR-009), so every number and word
the engineer reads in the first ten seconds is decided here. The rules this pins:

- **every finding is in exactly one group, first match winning**, by the ranking's own
  keys: within scope, decided, needs judgement ("Decide"), demonstrated ("Fix"), suspected
  or unresolved ("Verify"). Severity is never read (research R2.3);
- **the three owner groups are always there**, in the order Decide, Fix, Verify, at zero
  too; "Decided" and "Within limits" only when they hold a finding;
- **the headline is findings and issues**, the issues being the ranking's rows;
- **questions are the open requests**, in session order;
- **a folded family is its own line** (T016): its findings are in no group, the
  modelling-practice line is its ranking row, and the partition still holds;
- **the ranking is untouched**: `ReviewRanking` serializes `rank(session)` byte for byte
  plus one `summary` key, and the ranking module does not even import this one.

The goal lines (section 3) are `test_review_goals.py`'s.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, get_args
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import AttentionRow, rank
from swreview.report.session import (
    Contact,
    Coverage,
    CoverageBucket,
    EvidenceRequest,
    ReviewSession,
    load_session,
)
from swreview.report.summary import (
    COVERAGE_BUCKETS,
    ModellingPractice,
    ReviewRanking,
    ReviewSummary,
    contacts_of,
    load_words,
    review_ranking,
    review_summary,
)
from tests.support.attention import (
    ASSEMBLY_DOCUMENT,
    PART_COMPONENT,
    PIN_ONE,
    PIN_TWO,
    REVIEW_FOLDER,
    ROOT_COMPONENT,
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
)
from tests.unit.test_attention import STEPS, disposition, spec

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-000000000009")

BIG_ASSEMBLY = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "big-assembly"
"""Feature 008's committed, fictional replay fixture of a big assembly review (its T018)."""


def session_of(
    name: str,
    specs: Sequence[FindingSpec],
    coverage: CoverageSpec | None = None,
    evidence_requests: Sequence[EvidenceRequest] = (),
) -> ReviewSession:
    """A finished session over `specs`, named so its session id is stable and unique."""
    return build_attention_session(
        session_id=uuid5(NAMESPACE, name),
        findings=specs,
        coverage=coverage if coverage is not None else CoverageSpec(),
        steps=STEPS,
        evidence_requests=evidence_requests,
    )


def summary_of(
    session: ReviewSession, package: EvidencePackage | None = None, **kwargs: object
) -> ReviewSummary:
    return review_summary(rank(session), session, package, **kwargs)  # type: ignore[arg-type]


def request(
    number: int, *, status: str = "open", entity_ids: Sequence[str] = (PART_COMPONENT,)
) -> EvidenceRequest:
    answered = status == "answered"
    return EvidenceRequest(
        id=f"ER-{number:03d}",
        what=f"The evidence of request {number}",
        why=f"request {number} unblocks a check",
        entity_ids=list(entity_ids),
        status=status,  # type: ignore[arg-type]
        answer="it is 12 mm" if answered else None,
        answered_at="2026-09-23T10:00:00+00:00" if answered else None,  # type: ignore[arg-type]
    )


def group_counts(summary: ReviewSummary) -> dict[str, int]:
    return {group.kind: group.count for group in summary.groups}


def kind_of(check: str, **fields: object) -> str:
    """The one group a single finding lands in."""
    summary = summary_of(
        session_of(f"kind-{check}-{sorted(fields.items())}", [spec(check, **fields)])
    )
    nonzero = [group.kind for group in summary.groups if group.count]
    assert len(nonzero) == 1, summary.groups
    return nonzero[0]


# --- 1. the first match wins ---------------------------------------------------------------


def test_a_within_scope_judgement_finding_is_within_scope() -> None:
    assert kind_of("interference.static", status="checked_within_scope") == "within_scope"


def test_a_within_scope_finding_that_is_also_accepted_is_within_scope() -> None:
    """The order `attention._not_amplified` counts them in: within scope before decided."""
    fields = {"status": "checked_within_scope", "disposition": disposition("accepted")}
    assert kind_of("interference.static", **fields) == "within_scope"


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_a_decided_judgement_finding_is_decided(decision: str) -> None:
    assert kind_of("interference.static", disposition=disposition(decision)) == "decided"


def test_a_deferred_finding_is_not_decided() -> None:
    """`deferred` decides nothing, so the finding keeps its group (FR-008 of 007)."""
    assert kind_of("interference.static", disposition=disposition("deferred")) == "decide"


def test_a_suspected_judgement_finding_is_decide() -> None:
    assert kind_of("hole.coaxiality", status="suspected") == "decide"


def test_a_demonstrated_rule_finding_is_fix() -> None:
    assert kind_of("rms.folders.present", status="demonstrated") == "fix"


@pytest.mark.parametrize("status", ["suspected", "unresolved"])
def test_a_suspected_or_unresolved_rule_finding_is_verify(status: str) -> None:
    assert kind_of("rms.folders.present", status=status) == "verify"


@pytest.mark.parametrize("severity", ["high", "medium", "low", "info"])
def test_severity_is_never_read(severity: str) -> None:
    assert kind_of("rms.folders.present", status="demonstrated", severity=severity) == "fix"


# --- 2. the groups: which, in what order, in what words -------------------------------------


def test_the_three_owner_groups_are_present_at_zero_in_their_order() -> None:
    summary = summary_of(session_of("empty", []))

    assert [(g.kind, g.label, g.count, g.text) for g in summary.groups] == [
        ("decide", "Decide", 0, "0 need your decision"),
        ("fix", "Fix", 0, "0 to fix"),
        ("verify", "Verify", 0, "0 to verify"),
    ]
    assert all(group.by_goal == [] for group in summary.groups)


def test_decided_and_within_limits_follow_only_when_they_hold_a_finding() -> None:
    specs = [
        spec("rms.folders.present", status="checked_within_scope"),
        spec("interference.static", disposition=disposition("rejected")),
    ]
    summary = summary_of(session_of("decided-and-within", specs))

    assert [g.kind for g in summary.groups] == [
        "decide",
        "fix",
        "verify",
        "decided",
        "within_scope",
    ]
    assert [(g.label, g.text) for g in summary.groups[3:]] == [
        ("Decided", "1 decided"),
        ("Within limits", "1 within limits"),
    ]


@pytest.mark.parametrize(
    ("count", "text"),
    [(1, "1 needs your decision"), (2, "2 need your decision"), (3, "3 need your decision")],
)
def test_a_group_sentence_is_one_at_one_and_many_otherwise(count: int, text: str) -> None:
    specs = [
        spec("interference.static", component_ids=(one,))
        for one in (PART_COMPONENT, PIN_ONE, PIN_TWO)[:count]
    ]
    decide = summary_of(session_of(f"sentence-{count}", specs)).groups[0]

    assert (decide.kind, decide.count, decide.text) == ("decide", count, text)


def test_by_goal_lists_the_goals_with_a_count_in_goal_order() -> None:
    specs = [
        spec("rms.folders.present"),  # modelling practice
        spec("standards.part.cut_list_excluded"),  # hygiene
        spec("rms.grouping.all_features_in_a_group"),  # modelling practice
        spec("stack.gap"),  # fits and stacks (`fit.` would be a judgement: Decide)
    ]
    fix = summary_of(session_of("by-goal", specs)).groups[1]

    assert fix.kind == "fix"
    assert [(g.goal, g.title, g.count) for g in fix.by_goal] == [
        ("fits_and_stacks", "Fits and stacks", 1),
        ("hygiene", "Hygiene", 1),
        ("modelling_practice", "Modelling practice", 2),
    ]


def test_a_finding_whose_check_has_no_goal_counts_in_its_group_and_in_no_goal() -> None:
    fix = summary_of(session_of("no-goal", [spec("tool.something_new")])).groups[1]

    assert (fix.count, fix.by_goal) == (1, [])


def test_the_groups_partition_the_findings() -> None:
    specs = [
        spec("interference.static"),
        spec("interference.static", component_ids=(PIN_ONE,), status="checked_within_scope"),
        spec("hole.coaxiality", status="unresolved", disposition=disposition("accepted")),
        spec("rms.folders.present"),
        spec("rms.folders.present", status="suspected", severity="info"),
        spec("standards.part.cut_list_excluded", status="unresolved"),
    ]
    session = session_of("partition", specs)
    summary = summary_of(session)

    assert sum(group_counts(summary).values()) == len(session.findings) == summary.findings
    assert group_counts(summary) == {
        "decide": 1,
        "fix": 1,
        "verify": 2,
        "decided": 1,
        "within_scope": 1,
    }


# --- 3. the headline ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("components", "headline", "issues"),
    [
        ((PART_COMPONENT,), "1 finding in 1 issue", 1),
        ((PART_COMPONENT, PIN_ONE), "2 findings in 1 issue", 1),
        ((PART_COMPONENT, PART_COMPONENT, PIN_ONE), "3 findings in 2 issues", 2),
    ],
)
def test_the_headline_counts_findings_and_the_rankings_rows(
    components: tuple[str, ...], headline: str, issues: int
) -> None:
    specs = [spec("rms.folders.present", component_ids=(one,)) for one in components]
    session = session_of(f"headline-{len(components)}-{issues}", specs)
    ranking = rank(session)
    summary = review_summary(ranking, session, None)

    assert summary.headline == headline
    assert summary.issues == len(ranking.rows) == issues
    assert summary.findings == len(components)


def test_no_findings_is_said_in_words() -> None:
    summary = summary_of(session_of("nothing", []))

    assert summary.headline == "No findings were recorded"
    assert (summary.findings, summary.issues) == (0, 0)


def test_the_big_assembly_headline() -> None:
    session = load_session(BIG_ASSEMBLY / "session.json")

    assert summary_of(session).headline == "99 findings in 18 issues"


# --- 4. the questions ----------------------------------------------------------------------


def test_the_questions_are_the_open_requests_in_session_order() -> None:
    requests = [request(1), request(2, status="answered"), request(3), request(4)]
    questions = summary_of(session_of("questions", [], evidence_requests=requests)).questions

    assert (questions.count, questions.text) == (3, "3 questions for you")
    assert [item.id for item in questions.items] == ["ER-001", "ER-003", "ER-004"]


def test_one_question_is_said_in_the_singular() -> None:
    questions = summary_of(session_of("one-question", [], evidence_requests=[request(1)])).questions

    assert (questions.count, questions.text) == (1, "1 question for you")


def test_no_open_question_has_no_text() -> None:
    requests = [request(1, status="answered")]
    questions = summary_of(session_of("no-question", [], evidence_requests=requests)).questions

    assert (questions.count, questions.text, questions.items) == (0, None, [])


def test_a_request_without_the_short_form_asks_its_what_verbatim() -> None:
    requests = [request(1, entity_ids=(PART_COMPONENT, ASSEMBLY_DOCUMENT, "hole:0012"))]
    session = session_of("what", [], evidence_requests=requests)
    item = summary_of(session, attention_package()).questions.items[0]

    assert item.question == item.what == "The evidence of request 1"
    assert item.why == "request 1 unblocks a check"
    assert (item.options, item.blocks, item.blocks_title) == ([], None, None)
    assert [(one.id, one.name) for one in item.about] == [
        (PART_COMPONENT, "housing-1"),
        (ASSEMBLY_DOCUMENT, "cover-assy.SLDASM"),
        ("hole:0012", None),
    ]


def test_a_request_with_the_short_form_asks_its_short_question() -> None:
    """contracts/questions.md section 3 (T037): the short question, its offered answers in
    order, the checklist item it blocks and that item's goal title; `what` and `why` stay
    verbatim for the fold."""
    requests = [
        request(1).model_copy(
            update={
                "question": "What is the usable thread depth?",
                "options": ["8 mm", "6 mm", "Through"],
                "blocks": "fasteners",
            }
        ),
        request(2).model_copy(update={"question": "Which drawing governs the housing?"}),
        request(3).model_copy(update={"blocks": "interfaces.fit"}),
        request(4).model_copy(update={"blocks": "coverage.closeout"}),
    ]
    items = summary_of(session_of("short-form", [], evidence_requests=requests)).questions.items

    assert [(item.question, item.options, item.blocks, item.blocks_title) for item in items] == [
        ("What is the usable thread depth?", ["8 mm", "6 mm", "Through"], "fasteners", "Fasteners"),
        ("Which drawing governs the housing?", [], None, None),
        ("The evidence of request 3", [], "interfaces.fit", "Fits and stacks"),
        ("The evidence of request 4", [], "coverage.closeout", None),
    ]
    assert (items[0].what, items[0].why) == (
        "The evidence of request 1",
        "request 1 unblocks a check",
    )


# --- 5. the parts not loaded and the names ---------------------------------------------------


def with_states(package: EvidencePackage, states: dict[str, str]) -> EvidencePackage:
    components = [
        component.model_copy(
            update={"suppression": states.get(component.id, component.suppression)}
        )
        for component in package.components
    ]
    return package.model_copy(update={"components": components})


def test_the_parts_not_loaded_come_from_not_examined() -> None:
    package = with_states(attention_package(), {PIN_ONE: "lightweight", PIN_TWO: "suppressed"})
    not_loaded = summary_of(session_of("not-loaded", []), package).not_loaded

    assert not_loaded is not None
    assert (not_loaded.count, not_loaded.total, not_loaded.text) == (
        2,
        4,
        "2 of 4 parts not loaded",
    )


def test_every_part_read_or_no_package_has_no_not_loaded_line() -> None:
    session = session_of("all-read", [])

    assert summary_of(session, attention_package()).not_loaded is None
    assert summary_of(session, None).not_loaded is None


def test_component_names_hold_the_non_blank_names_only() -> None:
    package = attention_package()
    blank = package.components[1].model_copy(update={"name": "  "})
    package = package.model_copy(
        update={"components": [package.components[0], blank, *package.components[2:]]}
    )

    names = summary_of(session_of("names", []), package).component_names

    assert names == {
        ROOT_COMPONENT: "cover-assy-1",
        PART_COMPONENT: "housing-1",
        PIN_TWO: "dowel-pin-2",
    }
    assert summary_of(session_of("names", []), None).component_names == {}


# --- 6. the folded family (T016, feature 008's `folded_families` and its family row) ---------

FAMILY_MIX: list[FindingSpec] = [
    spec("interference.static"),  # F-001: decide
    spec("rms.folders.present"),  # F-002: family (fix, were it not folded)
    spec("rms.sketches.fully_defined", status="suspected"),  # F-003: family (verify)
    spec("rms.grouping.all_features_in_a_group", disposition=disposition("rejected")),  # F-004
    spec("rms.folders.present", status="checked_within_scope", component_ids=(PIN_ONE,)),  # F-005
    spec("rms.params.global_variables_present", status="unresolved"),  # F-006: family (verify)
    spec("stack.gap"),  # F-007: fix
    spec("hole.coaxiality", status="suspected", component_ids=(PIN_TWO,)),  # F-008: decide
]
"""Five `rms.*` findings of four rules - demonstrated, suspected, decided, within scope and
unresolved, so unfolded they would reach every group - beside three findings of other goals."""

FAMILY_IDS = ["F-002", "F-003", "F-004", "F-005", "F-006"]


def folded(session: ReviewSession, *families: str) -> ReviewSession:
    return session.model_copy(update={"folded_families": list(families)})


def family_row_of(session: ReviewSession) -> AttentionRow:
    [row] = [row for row in rank(session).rows if row.family is not None]
    return row


def test_a_folded_familys_findings_are_in_no_group() -> None:
    summary = summary_of(folded(session_of("family-groups", FAMILY_MIX), "rms"))

    assert group_counts(summary) == {"decide": 2, "fix": 1, "verify": 0}
    assert [goal.goal for group in summary.groups for goal in group.by_goal] == [
        "interference",
        "hole_alignment",
        "fits_and_stacks",
    ]


def test_the_modelling_practice_line_is_the_family_row() -> None:
    session = folded(session_of("family-line", FAMILY_MIX), "rms")
    row = family_row_of(session)

    practice = summary_of(session).modelling_practice

    assert practice == ModellingPractice(
        title=row.title,
        findings=len(row.member_finding_ids),
        rules=row.rule_count,  # type: ignore[arg-type]
        finding_ids=row.member_finding_ids,
    )
    assert practice.model_dump() == {
        "title": "Modelling practice: 5 findings across 4 rules",
        "findings": 5,
        "rules": 4,
        "finding_ids": FAMILY_IDS,
    }


def test_the_partition_holds_with_the_family() -> None:
    session = folded(session_of("family-partition", FAMILY_MIX), "rms")
    summary = summary_of(session)

    assert summary.modelling_practice is not None
    assert sum(group_counts(summary).values()) + summary.modelling_practice.findings == len(
        session.findings
    )
    assert summary.findings == len(session.findings) == 8


def test_the_family_is_one_issue_and_every_finding_in_the_headline() -> None:
    summary = summary_of(folded(session_of("family-headline", FAMILY_MIX), "rms"))

    assert (summary.headline, summary.issues) == ("8 findings in 4 issues", 4)


def test_the_modelling_practice_goal_still_counts_the_familys_open_findings() -> None:
    """The goal says whether the family was reached, the groups say what to do (data-model
    section 2): folding moves nothing on a goal line. T016 says "hygiene"; since 2026-09-23
    `rms.` is the modelling-practice goal's own prefix (research R2.4)."""
    plain = session_of("family-goals", FAMILY_MIX)

    unfolded = summary_of(plain)
    summary = summary_of(folded(plain, "rms"))

    lines = {line.goal: line for line in summary.goals}
    assert (lines["modelling_practice"].state, lines["modelling_practice"].findings) == (
        "issues",
        4,
    ), "every family finding but the within-scope one"
    assert lines["hygiene"].findings == 0
    assert summary.goals == unfolded.goals


def test_a_family_of_within_scope_findings_is_still_the_line_and_its_goal_reads_checked() -> None:
    specs = [
        spec("interference.static"),
        spec("rms.folders.present", status="checked_within_scope"),
        spec("rms.sketches.fully_defined", status="checked_within_scope"),
    ]
    summary = summary_of(folded(session_of("family-within-scope", specs), "rms"))

    assert summary.modelling_practice is not None
    assert (summary.modelling_practice.findings, summary.modelling_practice.rules) == (2, 2)
    assert group_counts(summary) == {"decide": 1, "fix": 0, "verify": 0}
    lines = {line.goal: line for line in summary.goals}
    assert (lines["modelling_practice"].state, lines["modelling_practice"].findings) == (
        "checked",
        0,
    )


def test_a_family_row_without_its_rule_count_is_refused_not_guessed() -> None:
    session = folded(session_of("family-no-rules", FAMILY_MIX), "rms")
    ranking = rank(session)
    rows = [
        row.model_copy(update={"rule_count": None}) if row.family is not None else row
        for row in ranking.rows
    ]

    with pytest.raises(ValidationError, match="rules"):
        review_summary(ranking.model_copy(update={"rows": rows}), session, None)


def test_without_the_field_the_same_session_gives_todays_groups_and_no_line() -> None:
    session = session_of("family-unfolded", FAMILY_MIX)

    summary = summary_of(session, attention_package())

    assert session.folded_families == []
    assert summary.modelling_practice is None
    assert group_counts(summary) == {
        "decide": 2,
        "fix": 2,
        "verify": 2,
        "decided": 1,
        "within_scope": 1,
    }


def test_a_folded_family_with_no_finding_has_no_line_and_moves_nothing() -> None:
    specs = [spec("interference.static"), spec("stack.gap")]
    plain = session_of("family-empty", specs)

    summary = summary_of(folded(plain, "rms"))

    assert summary.modelling_practice is None
    assert summary.groups == summary_of(plain).groups


def test_a_second_folded_family_stays_in_the_groups() -> None:
    """The line is the first family row in rank order (contract section 2 names one row);
    a second family's findings are counted in the groups as unfolded, so the partition
    still holds and nothing is lost from the summary."""
    specs = [
        spec("rms.folders.present", status="demonstrated", severity="high"),  # F-001
        spec("rms.sketches.fully_defined"),  # F-002
        spec("standards.part.cut_list_excluded"),  # F-003: fix, hygiene
        spec("standards.part.material_assigned", status="suspected"),  # F-004: verify
    ]
    session = folded(session_of("family-two", specs), "rms", "standards")
    rows = [row for row in rank(session).rows if row.family is not None]

    summary = summary_of(session)

    assert [row.family for row in rows] == ["rms", "standards"]
    assert summary.modelling_practice is not None
    assert summary.modelling_practice.finding_ids == ["F-001", "F-002"]
    assert group_counts(summary) == {"decide": 0, "fix": 1, "verify": 1}
    assert sum(group_counts(summary).values()) + summary.modelling_practice.findings == 4


# --- 7. the size-for-size contacts (T018, feature 010's `ReviewSession.contacts`) ----------


def contact(number: int, components: Sequence[str], **fields: Any) -> Contact:
    values: dict[str, Any] = {
        "id": f"C-{number:03d}",
        "kind": "zero_volume",
        "group_key": f"group-{number}",
        "configuration": "Default",
        "interference_ids": [f"I-{number:03d}"],
        "component_ids": list(components),
        "volume_mm3": 0.0,
        "joint_id": None,
        "reason": "the two parts touch at nominal size.",
        "tool_result_ids": [0],
    }
    values.update(fields)
    return Contact(**values)


def with_contacts(session: ReviewSession, *contacts: Contact) -> ReviewSession:
    return session.model_copy(update={"contacts": list(contacts)})


def test_each_contact_is_a_view_in_session_order_with_the_packages_names() -> None:
    package = attention_package()
    session = with_contacts(
        session_of("contacts", []),
        contact(1, (PIN_ONE, PART_COMPONENT)),
        contact(
            2,
            (PIN_TWO, PART_COMPONENT),
            kind="possible_only",
            volume_mm3=None,
            configuration="Machined",
        ),
    )

    contacts = summary_of(session, package).contacts

    assert contacts is not None
    assert (contacts.count, contacts.text) == (2, "2 size-for-size contacts")
    assert [item.model_dump() for item in contacts.items] == [
        {
            "id": "C-001",
            "component_ids": [PIN_ONE, PART_COMPONENT],
            "names": ["dowel-pin-1", "housing-1"],
            "configuration": "Default",
            "kind": "zero_volume",
            "kind_label": "touching",
            "volume_mm3": 0.0,
            "text": "dowel-pin-1 and housing-1",
        },
        {
            "id": "C-002",
            "component_ids": [PIN_TWO, PART_COMPONENT],
            "names": ["dowel-pin-2", "housing-1"],
            "configuration": "Machined",
            "kind": "possible_only",
            "kind_label": "possible only",
            "volume_mm3": None,
            "text": "dowel-pin-2 and housing-1",
        },
    ]


def test_a_part_with_no_name_is_named_by_its_id() -> None:
    package = attention_package()
    blank = package.components[1].model_copy(update={"name": " "})
    package = package.model_copy(
        update={"components": [package.components[0], blank, *package.components[2:]]}
    )
    session = with_contacts(session_of("contact-blank", []), contact(1, (PIN_ONE, PART_COMPONENT)))

    contacts = summary_of(session, package).contacts

    assert contacts is not None
    assert (contacts.text, contacts.items[0].names, contacts.items[0].text) == (
        "1 size-for-size contact",
        [None, "housing-1"],
        f"{PIN_ONE} and housing-1",
    )


def test_three_parts_in_one_contact_are_listed_with_a_final_and() -> None:
    session = with_contacts(
        session_of("contact-three", []), contact(1, (PIN_ONE, PART_COMPONENT, PIN_TWO))
    )

    contacts = summary_of(session, attention_package()).contacts

    assert contacts is not None
    assert contacts.items[0].text == "dowel-pin-1, housing-1 and dowel-pin-2"


def test_the_thread_model_kind_has_its_label() -> None:
    session = with_contacts(
        session_of("contact-thread", []), contact(1, (PIN_ONE, PART_COMPONENT), kind="thread_model")
    )

    contacts = summary_of(session, attention_package()).contacts

    assert contacts is not None
    assert contacts.items[0].kind_label == "thread model"


def test_no_contact_or_a_session_before_contacts_has_no_list() -> None:
    session = session_of("no-contacts", [])
    older = load_session(REVIEW_FOLDER / "session.json")

    assert "contacts" not in older.model_dump(mode="json"), "written before feature 010"
    assert contacts_of(session, {}) is None
    assert contacts_of(older, {}) is None
    assert summary_of(older, attention_package()).contacts is None


def test_a_contact_is_counted_in_no_group_and_no_goal() -> None:
    specs = [spec("interference.static"), spec("rms.folders.present")]
    plain = session_of("contacts-uncounted", specs)
    touching = with_contacts(plain, contact(1, (PIN_ONE, PART_COMPONENT)))

    without = summary_of(plain, attention_package())
    with_list = summary_of(touching, attention_package())

    assert with_list.groups == without.groups
    assert with_list.goals == without.goals
    assert (with_list.headline, with_list.findings) == (without.headline, without.findings)


def test_without_a_ledger_the_resume_cost_is_unknown() -> None:
    summary = summary_of(session_of("no-ledger", [], evidence_requests=[request(1)]))

    assert summary.resume_input_tokens is None
    assert summary.resume_text == "Sending resumes the review once."


def test_the_summary_names_the_words_it_was_written_in() -> None:
    assert summary_of(session_of("version", [])).version == load_words().version


# --- 8. the ranking is untouched -------------------------------------------------------------


def test_the_review_ranking_is_the_ranking_byte_for_byte_plus_its_summary() -> None:
    specs = [spec("interference.static"), spec("rms.folders.present", status="suspected")]
    session = session_of("ranking", specs)
    package = attention_package()

    body = to_jsonable_python(review_ranking(session, package))
    summary = body.pop("summary")

    assert json.dumps(body) == json.dumps(to_jsonable_python(rank(session)))
    assert summary == to_jsonable_python(review_summary(rank(session), session, package))


def test_review_ranking_of_copies_every_ranking_field() -> None:
    session = session_of("of", [spec("rms.folders.present")])
    ranking = rank(session)
    summary = review_summary(ranking, session, None)

    wrapped = ReviewRanking.of(ranking, summary)

    assert {name: getattr(wrapped, name) for name in type(ranking).model_fields} == dict(ranking)
    assert wrapped.summary == summary


def modules_loaded_by(module: str) -> list[str]:
    code = f"import sys, {module}; print('\\n'.join(sorted(sys.modules)))"
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return completed.stdout.split()


def test_the_ranking_module_does_not_import_the_summary() -> None:
    loaded = modules_loaded_by("swreview.report.attention")

    assert "swreview.report.attention" in loaded
    assert "swreview.report.summary" not in loaded


def test_the_summary_loads_no_provider_settings_or_network_module() -> None:
    """Contract section 1: the summary imports no provider and no settings."""
    loaded = modules_loaded_by("swreview.report.summary")
    forbidden = ("swreview.agent.providers", "swreview.agent.settings", "httpx", "openai", "google")

    assert "swreview.report.summary" in loaded
    assert [name for name in loaded if name.startswith(forbidden)] == []


def test_the_big_assembly_package_loads_for_the_headline_test() -> None:
    """Guards the fixture path the headline test above reads."""
    assert load_package(BIG_ASSEMBLY).package.components


def test_the_summarys_bucket_names_are_the_sessions() -> None:
    """Copied so the summary need not import the session module (see its docstring)."""
    assert get_args(CoverageBucket) == COVERAGE_BUCKETS
    assert tuple(Coverage.model_fields) == COVERAGE_BUCKETS
