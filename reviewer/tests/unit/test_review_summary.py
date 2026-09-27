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
  plus one `summary` key, and the ranking module does not even import this one;
- **one drawings line** (feature 011, owner decision 10A): the drawings read and the same-name
  drawings found but not open, by file name, nothing when neither exists, and a candidate the
  product opened and read is read, not a candidate.

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
from pydantic_core import to_jsonable_python

from swreview.checks.drawing_context import CANDIDATE_CONFIRM, CANDIDATES_NAMED
from swreview.ir.loader import load_package
from swreview.ir.models import DrawingCandidate, EvidencePackage
from swreview.report.attention import load_policy, rank
from swreview.report.attention_record import AttentionRecord
from swreview.report.finding_groups import FindingsByType, findings_by_type
from swreview.report.session import (
    Contact,
    Coverage,
    CoverageBucket,
    EvidenceRequest,
    ReviewSession,
    load_session,
)
from swreview.report.summary import (
    BOUGHT_PARTS_CHECK,
    COVERAGE_BUCKETS,
    DRAWINGS_NAMED,
    DrawingsLine,
    ReviewRanking,
    ReviewSummary,
    SummaryGroup,
    contacts_of,
    drawings_of,
    goal_lines,
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
    CoverageRow,
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
)
from tests.unit.test_attention import STEPS, disposition, spec
from tests.unit.test_confirmed_drawing_read import (
    NO_DRAWING_GAP,
    StaleGap,
    candidates_package,
    drawings_read_afterwards,
    merged,
    question_id,
    reviewed,
)

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-000000000009")

BIG_ASSEMBLY = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "big-assembly"
"""Feature 008's committed, fictional replay fixture of a big assembly review (its T018)."""

BIG_ASSEMBLY_HEADLINE = "96 findings in 15 issues"
"""The big assembly's headline. Its session names no folded family, so feature 013's grouped
view - the family unfolded - holds the fifteen rows its ranking held; no finding is a pass, so
there is no "checked, no issue" part. The rows are broken down in
`test_review_summary_fixture.py`."""

DRAWING_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"
"""Feature 011's three synthetic drawing packages (its T012)."""

GOLDEN_FIXTURES = Path(__file__).resolve().parents[1] / "golden" / "fixtures"
"""Feature 001's and 006's golden packages, some with PDF-ingested drawing sheets."""


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


def by_type(session: ReviewSession, package: EvidencePackage | None = None) -> FindingsByType:
    return findings_by_type(session, package, load_words(), load_policy())


def summary_of(
    session: ReviewSession, package: EvidencePackage | None = None, **kwargs: object
) -> ReviewSummary:
    return review_summary(by_type(session, package), session, package, **kwargs)  # type: ignore[arg-type]


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
        ("Checked, no issue", "1 checked, no issue"),
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


def test_a_finding_whose_check_has_no_goal_counts_in_its_group() -> None:
    fix = summary_of(session_of("no-goal", [spec("tool.something_new")])).groups[1]

    assert fix.count == 1


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
def test_the_headline_counts_findings_and_the_rows_of_the_type_groups(
    components: tuple[str, ...], headline: str, issues: int
) -> None:
    specs = [spec("rms.folders.present", component_ids=(one,)) for one in components]
    session = session_of(f"headline-{len(components)}-{issues}", specs)
    groups = by_type(session)
    summary = review_summary(groups, session, None)

    assert summary.headline == headline
    assert summary.issues == sum(len(group.rows) for group in groups.groups) == issues
    assert summary.findings == len(components)


def test_passes_are_counted_as_checked_not_as_issues() -> None:
    """013 `contracts/grouped-list.md` section 4: "{n} findings in {m} issues · {k} checked,
    no issue" - the passes are the fold's, in no issue."""
    specs = [
        spec("interference.static"),
        spec("rms.sketches.fully_defined"),
        spec("rms.folders.present", status="checked_within_scope", component_ids=(PIN_ONE,)),
        spec("rms.folders.present", status="checked_within_scope", component_ids=(PIN_TWO,)),
    ]
    summary = summary_of(session_of("headline-passes", specs))

    assert summary.headline == "2 findings in 2 issues · 2 checked, no issue"
    assert (summary.findings, summary.issues) == (4, 2)


def test_a_review_of_passes_only_is_said_as_checked() -> None:
    specs = [spec("rms.folders.present", status="checked_within_scope")]

    assert summary_of(session_of("headline-only-passes", specs)).headline == ("1 checked, no issue")


def test_a_decided_finding_is_still_an_issue_in_the_headline() -> None:
    specs = [spec("rms.folders.present", disposition=disposition("accepted"))]

    assert summary_of(session_of("headline-decided", specs)).headline == "1 finding in 1 issue"


# --- 3b. the tally and the not-reached line (feature 013) --------------------------------------


def test_the_tally_is_one_line_of_decide_fix_and_verify() -> None:
    specs = [
        spec("interference.static"),
        spec("rms.folders.present"),
        spec("rms.sketches.fully_defined", status="suspected"),
        spec("stack.gap"),
    ]
    tally = summary_of(session_of("tally", specs)).tally

    assert tally.text == "Decide 1 · Fix 2 · Verify 1"


def test_the_tally_names_decided_findings_only_when_there_are_some() -> None:
    specs = [
        spec("rms.folders.present"),
        spec("rms.core.shell_last", disposition=disposition("rejected")),
        spec("rms.detail.holes_last", status="checked_within_scope"),
    ]
    summary = summary_of(session_of("tally-decided", specs))

    assert summary.tally.text == "Decide 0 · Fix 1 · Verify 0 · Decided 1"
    assert summary_of(session_of("tally-empty", [])).tally.text == ("Decide 0 · Fix 0 · Verify 0")


def test_the_tally_and_the_checked_count_partition_the_findings() -> None:
    session = session_of("tally-partition", FAMILY_MIX)
    summary = summary_of(session)

    assert sum(group_counts(summary).values()) == len(session.findings) == summary.findings
    checked = group_counts(summary).get("within_scope", 0)
    assert summary.headline.endswith(f"{checked} checked, no issue")


def every_goal_checked() -> CoverageSpec:
    """One checked row per goal: an item where the goal has one, a prefix where it has none."""
    return CoverageSpec(
        checked=[
            CoverageRow(check=check, reason=f"{check} was checked.")
            for check in (
                "interference",
                "fasteners",
                "holes.alignment",
                "interfaces.fit",
                "fastener.head_clearance",
                "mass.material",
                "hygiene",
                "standards.release",
                "drawing.manufacturing_inputs",
                "modeling.resilience",
            )
        ]
    )


def test_every_goal_reached_gives_no_not_reached_line() -> None:
    assert summary_of(session_of("all-reached", [], every_goal_checked())).not_reached is None


def test_the_goals_not_reached_are_named_in_goal_order() -> None:
    coverage = every_goal_checked()
    coverage = CoverageSpec(
        checked=[
            row
            for row in coverage.checked  # type: ignore[union-attr]
            if row.check not in ("drawing.manufacturing_inputs", "fastener.head_clearance")
        ]
    )

    not_reached = summary_of(session_of("two-not-reached", [], coverage)).not_reached

    assert not_reached is not None
    assert not_reached.titles == ["Tool access", "Drawings"]
    assert not_reached.text == "Not reached: Tool access and Drawings"


def test_a_review_that_reached_nothing_names_every_goal() -> None:
    not_reached = summary_of(session_of("none-reached", [])).not_reached

    assert not_reached is not None
    assert not_reached.titles == [goal.title for goal in load_words().goals]
    assert not_reached.text.startswith("Not reached: Interference, Fasteners, ")
    assert not_reached.text.endswith(" and Modelling practice")


def test_no_findings_is_said_in_words() -> None:
    summary = summary_of(session_of("nothing", []))

    assert summary.headline == "No findings were recorded"
    assert (summary.findings, summary.issues) == (0, 0)


def test_the_big_assembly_headline() -> None:
    """96 findings, the recording's three touching groups being contacts in no count here (008
    decision 3A, 2026-09-23); since feature 013 the issues are the grouped view's rows, with the
    modelling-practice family unfolded (`test_review_summary_fixture.py` breaks them down)."""
    session = load_session(BIG_ASSEMBLY / "session.json")

    assert summary_of(session).headline == BIG_ASSEMBLY_HEADLINE


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


def test_a_question_that_allows_text_says_so_and_the_list_carries_the_placeholder() -> None:
    """Feature 013 T033 (its `contracts/part-roles.md` section 8): the part-roles question has
    two options and a text box; the page draws the box for a question with `allow_text` and
    prints the list's placeholder in it, a word of the words file."""
    requests = [
        request(1).model_copy(
            update={
                "question": "Are these bought parts?",
                "options": ["All bought", "None bought"],
                "allow_text": True,
            }
        ),
        request(2).model_copy(update={"options": ["Yes", "No"]}),
        request(3),
    ]
    questions = summary_of(session_of("allow-text", [], evidence_requests=requests)).questions

    assert [(item.id, item.allow_text) for item in questions.items] == [
        ("ER-001", True),
        ("ER-002", False),
        ("ER-003", False),
    ]
    assert questions.items[0].options == ["All bought", "None bought"]
    assert questions.text_placeholder == "Or name the bought ones, separated by commas"
    assert questions.text_placeholder == load_words().questions.text_placeholder


def test_with_no_question_the_placeholder_is_still_the_words() -> None:
    questions = summary_of(session_of("no-question-placeholder", [])).questions

    assert (questions.count, questions.text_placeholder) == (
        0,
        load_words().questions.text_placeholder,
    )


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


# --- 6. a folded family is listed like every other finding (feature 013) ----------------------

FAMILY_MIX: list[FindingSpec] = [
    spec("interference.static"),  # F-001: decide
    spec("rms.folders.present"),  # F-002: fix
    spec("rms.sketches.fully_defined", status="suspected"),  # F-003: verify
    spec("rms.grouping.all_features_in_a_group", disposition=disposition("rejected")),  # F-004
    spec("rms.folders.present", status="checked_within_scope", component_ids=(PIN_ONE,)),  # F-005
    spec("rms.params.global_variables_present", status="unresolved"),  # F-006: verify
    spec("stack.gap"),  # F-007: fix
    spec("hole.coaxiality", status="suspected", component_ids=(PIN_TWO,)),  # F-008: decide
]
"""Five `rms.*` findings of four rules - demonstrated, suspected, decided, within scope and
unresolved, so they reach every group - beside three findings of other goals."""


def folded(session: ReviewSession, *families: str) -> ReviewSession:
    return session.model_copy(update={"folded_families": list(families)})


def test_a_folded_familys_findings_are_counted_in_the_groups_like_any_other() -> None:
    """Feature 013 retired the modelling-practice line (its `contracts/grouped-list.md` 4): the
    grouped view unfolds the family, so the summary of a folded session is the summary of the
    same session unfolded."""
    plain = session_of("family-groups", FAMILY_MIX)

    summary = summary_of(folded(plain, "rms"))

    assert summary == summary_of(plain)
    assert group_counts(summary) == {
        "decide": 2,
        "fix": 2,
        "verify": 2,
        "decided": 1,
        "within_scope": 1,
    }


def test_the_family_is_its_rows_in_the_headline() -> None:
    """Eight findings: seven outside the fold in seven rows (no two fold: F-002 and F-005 share
    a check but not a status), and one pass."""
    summary = summary_of(folded(session_of("family-headline", FAMILY_MIX), "rms"))

    assert (summary.headline, summary.issues) == (
        "7 findings in 7 issues · 1 checked, no issue",
        7,
    )


def test_folding_a_family_moves_nothing_on_a_goal_line() -> None:
    plain = session_of("family-goals", FAMILY_MIX)

    lines = {line.goal: line for line in goal_lines(folded(plain, "rms"), load_words())}

    assert (lines["modelling_practice"].state, lines["modelling_practice"].findings) == (
        "issues",
        4,
    ), "every family finding but the within-scope one"
    assert lines["hygiene"].findings == 0
    assert goal_lines(folded(plain, "rms"), load_words()) == goal_lines(plain, load_words())


def test_the_summary_carries_no_modelling_practice_line_and_no_goal_list() -> None:
    assert "modelling_practice" not in ReviewSummary.model_fields
    assert "goals" not in ReviewSummary.model_fields
    assert "by_goal" not in SummaryGroup.model_fields


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
    assert (with_list.tally, with_list.not_reached) == (without.tally, without.not_reached)
    assert (with_list.headline, with_list.findings) == (without.headline, without.findings)
    assert goal_lines(touching, load_words()) == goal_lines(plain, load_words())


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
    groups = body.pop("groups")

    assert json.dumps(body) == json.dumps(to_jsonable_python(rank(session)))
    assert summary == to_jsonable_python(summary_of(session, package))
    assert groups == to_jsonable_python(
        findings_by_type(session, package, load_words(), load_policy())
    )


def test_review_ranking_of_copies_every_ranking_field() -> None:
    session = session_of("of", [spec("rms.folders.present")])
    ranking = rank(session)
    groups = by_type(session)
    summary = review_summary(groups, session, None)

    wrapped = ReviewRanking.of(ranking, summary, groups)

    assert {name: getattr(wrapped, name) for name in type(ranking).model_fields} == dict(ranking)
    assert (wrapped.summary, wrapped.groups) == (summary, groups)


def test_the_attention_record_of_a_review_ranking_carries_neither_summary_nor_groups() -> None:
    """013 `contracts/grouped-list.md` section 3: `attention.json` does not carry `groups`."""
    session = session_of("record", [spec("rms.folders.present")])

    record = AttentionRecord.of(review_ranking(session, None), session.session_id)

    assert not {"summary", "groups"} & set(json.loads(record.model_dump_json()))


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


def test_the_bought_parts_check_ids_are_the_classifiers() -> None:
    """The summary copies the two row ids (it may not import the classifier, which reaches the
    session module); integration of lanes P and R, 2026-09-27: one name each, held equal here."""
    from swreview.checks import part_roles
    from swreview.report import summary

    assert summary.BOUGHT_PARTS_CHECK == part_roles.BOUGHT_PARTS_CHECK
    assert summary.MAYBE_BOUGHT_CHECK == part_roles.MAYBE_BOUGHT_CHECK


def test_the_big_assembly_package_loads_for_the_headline_test() -> None:
    """Guards the fixture path the headline test above reads."""
    assert load_package(BIG_ASSEMBLY).package.components


def test_the_summarys_bucket_names_are_the_sessions() -> None:
    """Copied so the summary need not import the session module (see its docstring)."""
    assert get_args(CoverageBucket) == COVERAGE_BUCKETS
    assert tuple(Coverage.model_fields) == COVERAGE_BUCKETS


# --- 9. the drawings line (feature 011, owner decision 10A) ----------------------------------


def drawing_fixture(name: str) -> EvidencePackage:
    return load_package(DRAWING_FIXTURES / name).package


PLATE_READ = ["FICT-TULMKALO-3001.SLDDRW", "FICT-TULMKALO-3001-B.SLDDRW"]
"""The plate fixture's two drawings, read because they were open (doc:0006, doc:0007)."""
PLATE_CANDIDATE = "FICT-TULMSORN-3002.SLDDRW"
"""The same-name drawing beside the block (doc:0003), not open."""


def kalo(count: int) -> list[str]:
    """The candidate file names `candidates_package(count)` holds, in its order."""
    return [f"FICT-KALO-{8001 + number}.SLDDRW" for number in range(count)]


def with_candidates(package: EvidencePackage, *extra: DrawingCandidate) -> EvidencePackage:
    return package.model_copy(
        update={"drawing_candidates": [*package.drawing_candidates, *extra]}
    )


def test_no_package_or_no_drawing_evidence_has_no_drawings_line() -> None:
    session = session_of("no-drawings", [])

    assert summary_of(session, None).drawings is None
    assert summary_of(session, attention_package()).drawings is None
    assert drawings_of(attention_package()) is None


def test_the_plate_names_its_two_drawings_read_and_its_candidate() -> None:
    assert drawings_of(drawing_fixture("plate-drawing")) == DrawingsLine(
        read=PLATE_READ,
        candidates=[PLATE_CANDIDATE],
        text=(
            "Drawings read: FICT-TULMKALO-3001.SLDDRW and FICT-TULMKALO-3001-B.SLDDRW. "
            "Same-name drawing found but not open: FICT-TULMSORN-3002.SLDDRW"
        ),
    )


def test_the_line_is_the_one_the_routes_answer() -> None:
    package = drawing_fixture("plate-drawing")

    summary = review_ranking(session_of("drawings-route", []), package).summary

    assert summary.drawings == drawings_of(package)


def test_a_drawing_root_names_its_one_drawing_in_the_singular() -> None:
    line = drawings_of(drawing_fixture("drawing-root"))

    assert line is not None
    assert (line.read, line.candidates, line.text) == (
        ["FICT-OKTAPELIN-4000.SLDDRW"],
        [],
        "Drawing read: FICT-OKTAPELIN-4000.SLDDRW",
    )


def test_four_drawings_read_are_listed_with_a_final_and() -> None:
    line = drawings_of(drawing_fixture("assembly-drawings"))

    assert line is not None
    assert line.text == (
        "Drawings read: FICT-OKTAVEN-5000.SLDDRW, FICT-OKTAKALO-5001.SLDDRW, "
        "FICT-OKTAKALO-5001-B.SLDDRW and FICT-OKTAKALO-5001-C.SLDDRW"
    )
    assert line.candidates == []


def test_candidates_alone_have_no_read_part() -> None:
    line = drawings_of(candidates_package(3))

    assert line is not None
    assert (line.read, line.candidates) == ([], kalo(3))
    assert line.text == (
        "Same-name drawings found but not open: FICT-KALO-8001.SLDDRW, FICT-KALO-8002.SLDDRW "
        "and FICT-KALO-8003.SLDDRW"
    )


def test_one_candidate_is_said_in_the_singular() -> None:
    line = drawings_of(candidates_package(1))

    assert line is not None
    assert line.text == "Same-name drawing found but not open: FICT-KALO-8001.SLDDRW"


def test_ten_names_are_all_named() -> None:
    line = drawings_of(candidates_package(DRAWINGS_NAMED))

    assert line is not None
    names = kalo(DRAWINGS_NAMED)
    assert line.text == (
        f"Same-name drawings found but not open: {', '.join(names[:-1])} and {names[-1]}"
    )


def test_past_ten_names_the_first_ten_and_counts_the_rest() -> None:
    line = drawings_of(candidates_package(DRAWINGS_NAMED + 2))

    assert line is not None
    names = kalo(DRAWINGS_NAMED + 2)
    assert line.candidates == names, "the list keeps every name; only the sentence is bounded"
    assert line.text == (
        f"Same-name drawings found but not open: {', '.join(names[:DRAWINGS_NAMED])} and 2 more"
    )


def test_the_bound_is_the_candidate_questions() -> None:
    """Copied, because `checks/drawing_context.py` reaches the session module and the summary
    imports no provider (see its docstring): the question and the line name the same ten."""
    assert DRAWINGS_NAMED == CANDIDATES_NAMED == 10


def test_both_lists_follow_the_packages_ids_not_its_arrays() -> None:
    plate = drawing_fixture("plate-drawing")
    candidates = candidates_package(3)

    shuffled_plate = plate.model_copy(
        update={
            "drawing_records": list(reversed(plate.drawing_records)),
            "documents": list(reversed(plate.documents)),
        }
    )
    shuffled_candidates = candidates.model_copy(
        update={"drawing_candidates": list(reversed(candidates.drawing_candidates))}
    )

    assert drawings_of(shuffled_plate) == drawings_of(plate)
    assert drawings_of(shuffled_candidates) == drawings_of(candidates)


def test_a_record_with_no_document_row_is_named_by_its_id() -> None:
    plate = drawing_fixture("plate-drawing")
    rowless = plate.model_copy(
        update={"documents": [row for row in plate.documents if row.document_id != "doc:0007"]}
    )

    line = drawings_of(rowless)

    assert line is not None
    assert line.read == [PLATE_READ[0], "doc:0007"]


def test_one_candidate_file_beside_two_documents_is_named_once() -> None:
    """A part and an assembly of one stem in one folder share their same-name drawing."""
    plate = drawing_fixture("plate-drawing")
    [candidate] = plate.drawing_candidates
    twin = candidate.model_copy(update={"document_id": "doc:0005"})

    line = drawings_of(with_candidates(plate, twin))

    assert line is not None
    assert line.candidates == [PLATE_CANDIDATE]


@pytest.mark.parametrize(
    "spelled",
    [
        pytest.param(str.upper, id="another-case"),
        pytest.param(lambda path: path.replace("\\", "/"), id="forward-slashes"),
    ],
)
def test_one_candidate_file_spelled_two_ways_is_named_once(spelled: Any) -> None:
    """013 T010: the line groups candidate rows by the shared `drawings/evidence.file_key`, so
    two rows of one file whose paths differ in case or separator name it once, as the first
    row spells it - the line is unchanged by the move."""
    plate = drawing_fixture("plate-drawing")
    [candidate] = plate.drawing_candidates
    twin = candidate.model_copy(update={"document_id": "doc:0005", "path": spelled(candidate.path)})

    line = drawings_of(with_candidates(plate, twin))

    assert line is not None
    assert line.candidates == [PLATE_CANDIDATE]


def test_pdf_ingested_sheets_are_drawings_read() -> None:
    line = drawings_of(load_package(GOLDEN_FIXTURES / "cover-blind-tap").package)

    assert line == DrawingsLine(
        read=["housing.SLDDRW", "cover.SLDDRW"],
        candidates=[],
        text="Drawings read: housing.SLDDRW and cover.SLDDRW",
    )


def test_a_drawing_read_natively_and_from_its_pdf_is_named_once() -> None:
    package = load_package(
        GOLDEN_FIXTURES / "standards-drawings" / "standards-drawings-ingested"
    ).package
    [record] = package.drawing_records
    assert {sheet.document_id for sheet in package.drawings} == {record.document_id}

    line = drawings_of(package)

    assert line is not None
    assert line.read == [
        row.file_name for row in package.documents if row.document_id == record.document_id
    ]


# --- 9b. a confirmed candidate, once read, is read (011 contracts/confirmed-open.md) ------------


def test_after_a_confirmed_read_the_drawing_is_read_and_no_longer_a_candidate(
    tmp_path: Path,
) -> None:
    """The host reads the confirmed candidate into the run folder's package and drops its row;
    the live route reads the reloaded package and the disk route the run folder's."""
    run, _, _ = reviewed(tmp_path, None, lambda folder: {"doc:0003": merged(folder, "doc:0003")})
    before = review_ranking(run.session, run.context.ir).summary.drawings
    assert before is not None
    assert (before.read, before.candidates) == (PLATE_READ, [PLATE_CANDIDATE])

    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    after = review_ranking(run.session, run.context.ir).summary.drawings
    assert after == DrawingsLine(
        read=[*PLATE_READ, PLATE_CANDIDATE],
        candidates=[],
        text=(
            "Drawings read: FICT-TULMKALO-3001.SLDDRW, FICT-TULMKALO-3001-B.SLDDRW and "
            "FICT-TULMSORN-3002.SLDDRW"
        ),
    )
    assert drawings_of(load_package(tmp_path / "run-0001").package) == after


@pytest.mark.parametrize(
    "stale_gap",
    ["reworded", "left", "dropped"],
    ids=["gap-reworded", "gap-left", "gap-dropped"],
)
def test_a_confirmed_read_is_said_the_same_whether_the_stale_gap_is_reworded_stays_or_goes(
    tmp_path: Path, stale_gap: StaleGap
) -> None:
    """No reason the backend writes reads the package-level drawing gap: the drawings line, the
    restated drawing check and every goal line say the drawing was read, whether the host rewords
    the gap that says none was - as `PackageAppender.MergeDrawing` has since feature 011 T079
    (T088) - leaves it, as a host before T079 did, or drops it."""
    package = candidates_package(1)
    package = package.model_copy(update={"gaps": [*package.gaps, NO_DRAWING_GAP]})
    [part] = [candidate.document_id for candidate in package.drawing_candidates]
    reworded = NO_DRAWING_GAP.model_copy(
        update={"reason": drawings_read_afterwards([("FICT-KALO-8001.SLDDRW", True)])}
    )
    left_by_the_host = {"reworded": [reworded], "left": [NO_DRAWING_GAP], "dropped": []}

    run, _, _ = reviewed(
        tmp_path, package, lambda folder: {part: merged(folder, part, stale_gap=stale_gap)}
    )
    run.answer_evidence_batch([(question_id(run), CANDIDATE_CONFIRM)])

    standing = [gap for gap in run.context.ir.gaps if gap in (reworded, NO_DRAWING_GAP)]
    assert standing == left_by_the_host[stale_gap]
    if stale_gap == "reworded":
        # Reworded, not removed: the gap count `get_package_summary` reports and the brief's
        # counts by kind are the same after the read as before it, the gap in its own place.
        assert len(run.context.ir.gaps) == len(package.gaps)
        assert run.context.ir.gaps.index(reworded) == package.gaps.index(NO_DRAWING_GAP)
    summary = review_ranking(run.session, run.context.ir).summary
    assert summary.drawings is not None
    assert (summary.drawings.read, summary.drawings.candidates) == (kalo(1), [])
    [context] = [
        item for item in run.session.coverage.checked if item.check == "drawing.context"
    ]
    assert context.scope.document_ids == [part]
    assert context.reason.startswith("read from FICT-KALO-8001.SLDDRW")
    reasons = [
        text
        for line in goal_lines(run.session, load_words())
        for text in (line.reason, line.detail)
        if text is not None
    ]
    reasons += [
        item.reason
        for bucket in COVERAGE_BUCKETS
        for item in getattr(run.session.coverage, bucket)
    ]
    assert not any("no drawing was read" in reason for reason in reasons)
    assert not any("Read afterwards" in reason for reason in reasons)


@pytest.mark.parametrize(
    "spelled",
    [
        pytest.param(lambda path: path, id="as-written"),
        pytest.param(str.lower, id="another-case"),
        pytest.param(lambda path: path.replace("\\", "/"), id="forward-slashes"),
    ],
)
def test_a_candidate_row_left_for_a_file_the_review_read_is_not_named_again(
    spelled: Any,
) -> None:
    """Were a merge to leave the candidate row of a drawing it read, the line still names the
    drawing once, as read: the paths are compared as discovery compares them."""
    plate = drawing_fixture("plate-drawing")
    read_path = next(row.path for row in plate.documents if row.document_id == "doc:0006")
    left = DrawingCandidate(
        document_id="doc:0002", path=spelled(read_path), reason="same_name_beside_model"
    )

    line = drawings_of(with_candidates(plate, left))

    assert line is not None
    assert (line.read, line.candidates) == (PLATE_READ, [PLATE_CANDIDATE])


def test_a_read_drawing_whose_row_mixes_separators_still_hides_its_candidate_row() -> None:
    """The drawing root fixture writes its paths with both separators."""
    root = drawing_fixture("drawing-root")
    [drawing] = [row for row in root.documents if row.kind == "drawing"]
    assert "/" in drawing.path and "\\" in drawing.path
    left = DrawingCandidate(
        document_id="doc:2", path=drawing.path.replace("/", "\\"), reason="same_name_beside_model"
    )

    line = drawings_of(with_candidates(root, left))

    assert line is not None
    assert line.candidates == []


# --- 9c. the offer follows the seat (feature 013 T092, its drawing-capability.md section 4) --


def with_mode(session: ReviewSession, mode: str | None) -> ReviewSession:
    """`session` as recorded with the seat's drawing-read mode (lane S's 013 T077 records it as
    the optional `ReviewSession.drawing_read`, which T007 adds; set here on a copy)."""
    return session.model_copy(update={"drawing_read": mode})


def root_name(package: EvidencePackage) -> str:
    root = package.design.root_assembly_document_id
    return next(row.file_name for row in package.documents if row.document_id == root)


@pytest.mark.parametrize("mode", ["none", "open_only"])
def test_while_the_seat_cannot_open_a_drawing_the_line_says_how_to_include_one(mode: str) -> None:
    package = candidates_package(1)
    session = with_mode(session_of(f"instruct-{mode}", []), mode)

    drawings = summary_of(session, package).drawings

    assert drawings is not None
    assert drawings.candidates == kalo(1)
    assert drawings.text == (
        f"Open FICT-KALO-8001.SLDDRW in SOLIDWORKS, then press Review again with "
        f"{root_name(package)} active"
    )


def test_several_candidate_files_are_named_as_a_sentence_names_them() -> None:
    package = candidates_package(3)
    session = with_mode(session_of("instruct-many", []), "open_only")

    drawings = summary_of(session, package).drawings

    assert drawings is not None
    assert drawings.text == (
        "Open FICT-KALO-8001.SLDDRW, FICT-KALO-8002.SLDDRW and FICT-KALO-8003.SLDDRW in "
        f"SOLIDWORKS, then press Review again with {root_name(package)} active"
    )


def test_past_ten_candidate_files_the_instruction_counts_the_rest() -> None:
    package = candidates_package(DRAWINGS_NAMED + 2)
    session = with_mode(session_of("instruct-past-ten", []), "none")

    drawings = summary_of(session, package).drawings

    assert drawings is not None
    names = kalo(DRAWINGS_NAMED + 2)
    assert drawings.text.startswith(f"Open {', '.join(names[:DRAWINGS_NAMED])} and 2 more in ")


def test_when_the_seat_opens_closed_drawings_the_line_says_not_open_as_before() -> None:
    package = candidates_package(1)
    session = with_mode(session_of("opens-closed", []), "opens_closed")

    drawings = summary_of(session, package).drawings

    assert drawings is not None
    assert drawings.text == "Same-name drawing found but not open: FICT-KALO-8001.SLDDRW"


def test_a_session_that_never_asked_the_seat_says_not_open_as_before() -> None:
    """No `drawing_read` - a review before feature 013, or one with no candidate to ask about -
    keeps today's words, so a re-rendered run folder says what it said."""
    package = candidates_package(1)

    drawings = summary_of(session_of("no-mode", []), package).drawings

    assert drawings is not None
    assert drawings.text == "Same-name drawing found but not open: FICT-KALO-8001.SLDDRW"


def test_the_read_part_is_kept_before_the_instruction() -> None:
    plate = drawing_fixture("plate-drawing")
    session = with_mode(session_of("read-and-instruct", []), "open_only")

    drawings = summary_of(session, plate).drawings

    assert drawings is not None
    assert drawings.text == (
        "Drawings read: FICT-TULMKALO-3001.SLDDRW and FICT-TULMKALO-3001-B.SLDDRW. "
        f"Open {PLATE_CANDIDATE} in SOLIDWORKS, then press Review again with "
        f"{root_name(plate)} active"
    )


def test_a_bought_documents_candidate_is_not_named() -> None:
    """013 drawing-capability.md section 3: candidate rows of bought documents are ignored; the
    summary knows the bought documents from the persisted bought-parts row, as its line does."""
    package = candidates_package(2)
    [first, second] = package.drawing_candidates
    bought = CoverageRow(
        check=BOUGHT_PARTS_CHECK,
        reason="1 parts not graded for modelling practice or hygiene (bought): FICT",
        document_ids=(first.document_id,),
    )
    session = with_mode(
        session_of("bought-candidate", [], CoverageSpec(skipped=[bought])), "open_only"
    )

    drawings = summary_of(session, package).drawings

    assert drawings is not None
    assert drawings.candidates == ["FICT-KALO-8002.SLDDRW"]
    assert second.document_id != first.document_id


def test_every_candidate_bought_leaves_no_candidate_part() -> None:
    package = candidates_package(1)
    [only] = package.drawing_candidates
    bought = CoverageRow(
        check=BOUGHT_PARTS_CHECK, reason="bought", document_ids=(only.document_id,)
    )
    session = with_mode(session_of("all-bought", [], CoverageSpec(skipped=[bought])), "none")

    assert summary_of(session, package).drawings is None


def test_the_drawings_line_moves_nothing_else_in_the_summary() -> None:
    """Counted in no group, goal or headline: the same session over the same package with its
    drawing evidence taken out differs in the line alone."""
    plate = drawing_fixture("plate-drawing")
    bare = plate.model_copy(update={"drawing_records": [], "drawing_candidates": []})
    specs = [spec("interference.static"), spec("rms.folders.present", status="suspected")]
    session = session_of("drawings-move-nothing", specs)

    with_line = summary_of(session, plate)
    without = summary_of(session, bare)

    assert with_line.drawings is not None
    assert without.drawings is None
    assert with_line.model_copy(update={"drawings": None}) == without
