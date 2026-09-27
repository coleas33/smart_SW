"""Findings by type (feature 013 T047), against its `contracts/grouped-list.md` section 3.

The Review tab and `report.md` list every finding once, in one row of one group or in the
"Checked, no issue" fold, in the attention policy's own order. The rules this pins:

- **the partition**: every finding is a member of exactly one row, and the rows' members are
  `session.findings`, whatever the session holds - passes, decided findings, a check no goal
  names, a folded family;
- **no pass in a type group**, and every pass in the fold;
- **one order**: within each group the rows are `ranked_rows`' order, also on shuffled copies of
  the session, and the decided rows last, keeping theirs;
- **the family is unfolded** - the group is the fold now - and the same-check fold kept;
- **every word is the backend's**: a row's `tail_text`, `reach_text` and `hide_card_title`, a
  group's `text`, the fold's tail for a waived pass;
- **a group with no row and no goal is left out**, so folding Mass and material into Hygiene is
  one edit of the words file.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from uuid import UUID, uuid5

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage, SourceRef
from swreview.report.attention import load_policy, ranked_rows
from swreview.report.finding_groups import (
    FindingsByType,
    GroupRow,
    TypeGroup,
    findings_by_type,
)
from swreview.report.session import ReviewSession, load_session
from swreview.report.summary import Words, load_words
from tests.support.attention import (
    ASSEMBLY_DOCUMENT,
    PART_COMPONENT,
    PIN_ONE,
    PIN_TWO,
    REVIEW_FOLDER,
    REVIEW_SESSION_FILE,
    ROOT_COMPONENT,
    CoverageRow,
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
)
from tests.unit.test_attention import STEPS, disposition, spec
from tests.unit.test_review_summary import BIG_ASSEMBLY
from tests.unit.test_review_words import raw_words

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-000000000013")

ON_A_SHEET = SourceRef(document_id=ASSEMBLY_DOCUMENT, sheet="Sheet1")
"""Where a finding with no component is located, so it still names a subject."""

SEVEN = [
    "interference_fit",
    "fasteners",
    "drawings",
    "standards",
    "modelling_practice",
    "hygiene",
    "mass_material",
]


def session_of(
    name: str, specs: Sequence[FindingSpec], coverage: CoverageSpec | None = None
) -> ReviewSession:
    return build_attention_session(
        session_id=uuid5(NAMESPACE, name),
        findings=specs,
        coverage=coverage if coverage is not None else CoverageSpec(),
        steps=STEPS,
    )


def by_type(
    session: ReviewSession,
    package: EvidencePackage | None = None,
    words: Words | None = None,
) -> FindingsByType:
    return findings_by_type(
        session, package, words if words is not None else load_words(), load_policy()
    )


def group(view: FindingsByType, group_id: str) -> TypeGroup:
    return next(one for one in view.groups if one.id == group_id)


def every_row(view: FindingsByType) -> list[GroupRow]:
    rows = [row for one in view.groups for row in one.rows]
    return rows + (view.checked.rows if view.checked is not None else [])


def members(rows: Sequence[GroupRow]) -> list[str]:
    return [member for row in rows for member in row.member_finding_ids]


MIXED: list[FindingSpec] = [
    spec("interference.static"),  # F-001: interference and fit
    spec("rms.folders.present", component_ids=(PIN_ONE,)),  # F-002: folds with F-003
    spec("rms.folders.present", component_ids=(PIN_TWO,)),  # F-003
    spec("rms.sketches.fully_defined", disposition=disposition("accepted")),  # F-004: decided
    spec("rms.core.shell_last"),  # F-005: modelling practice
    spec("standards.part.cut_list_excluded"),  # F-006: standards
    spec("hygiene.revision_present", status="checked_within_scope"),  # F-007: a pass
    spec("tool.something_new"),  # F-008: no goal - other checks
    spec("stack.gap", status="suspected"),  # F-009: interference and fit
    spec("standards.drawing.revision_matches"),  # F-010: drawings
]
"""One finding of nearly every kind the view must place, in recording order."""


# --- 1. the partition --------------------------------------------------------------------------


def fixture_sessions() -> list[ReviewSession]:
    big = load_session(BIG_ASSEMBLY / "session.json")
    return [
        session_of("partition-mixed", MIXED),
        session_of("partition-mixed-folded", MIXED).model_copy(update={"folded_families": ["rms"]}),
        load_session(REVIEW_SESSION_FILE),
        big,
        session_of("partition-empty", []),
    ]


@pytest.mark.parametrize("index", range(5), ids=["mixed", "folded", "review", "big", "empty"])
def test_every_finding_is_in_exactly_one_row_of_one_group_or_the_fold(index: int) -> None:
    session = fixture_sessions()[index]

    view = by_type(session)

    listed = members(every_row(view))
    assert sorted(listed) == sorted(finding.id for finding in session.findings)
    assert len(listed) == len(set(listed)), "no finding is a member of two rows"


def test_no_pass_is_in_a_type_group_and_every_pass_is_in_the_fold() -> None:
    view = by_type(session_of("passes", MIXED))

    assert all(row.status != "checked_within_scope" for one in view.groups for row in one.rows)
    assert view.checked is not None
    assert [row.finding_id for row in view.checked.rows] == ["F-007"]
    assert all(row.status == "checked_within_scope" for row in view.checked.rows)


def test_each_row_is_in_its_goals_group() -> None:
    view = by_type(session_of("placement", MIXED))

    placed = {one.id: members(one.rows) for one in view.groups if one.rows}
    assert placed == {
        "interference_fit": ["F-001", "F-009"],
        "drawings": ["F-010"],
        "standards": ["F-006"],
        "modelling_practice": ["F-005", "F-002", "F-003", "F-004"],
        "other": ["F-008"],
    }


# --- 2. one order --------------------------------------------------------------------------------


def test_within_each_group_the_rows_keep_the_ranked_order() -> None:
    session = session_of("order", MIXED)
    ranked = [row.finding_id for row in ranked_rows(session.findings, load_policy(), ())]

    for one in by_type(session).groups:
        ids = [row.finding_id for row in one.rows if not row.key.suppressed]
        assert ids == [finding for finding in ranked if finding in ids]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_shuffled_session_gives_the_same_view(seed: int) -> None:
    session = session_of("shuffled", MIXED)
    shuffled = list(session.findings)
    random.Random(seed).shuffle(shuffled)

    assert by_type(session.model_copy(update={"findings": shuffled})) == by_type(session)


def test_decided_rows_sit_last_in_their_group_keeping_their_order() -> None:
    specs = [
        spec("rms.core.shell_last", disposition=disposition("rejected")),  # F-001
        spec("rms.sketches.fully_defined", disposition=disposition("accepted")),  # F-002
        spec("rms.folders.present", status="suspected"),  # F-003
        spec("rms.grouping.all_features_in_a_group"),  # F-004
    ]
    session = session_of("decided-last", specs)
    practice = group(by_type(session), "modelling_practice")

    ids = [row.finding_id for row in practice.rows]
    decided = [row.finding_id for row in ranked_rows(session.findings) if row.key.suppressed]
    assert ids[-2:] == decided
    assert set(ids[:2]) == {"F-003", "F-004"}
    assert (practice.findings, practice.decided, practice.text) == (
        4,
        2,
        "4 findings · 2 decided",
    )


def test_a_check_no_goal_names_is_in_other_checks_last() -> None:
    view = by_type(session_of("other", MIXED))

    assert view.groups[-1].id == "other"
    assert (view.groups[-1].title, view.groups[-1].open) == ("Other checks", True)
    assert [row.check for row in view.groups[-1].rows] == ["tool.something_new"]
    assert view.groups[-1].goals == []


def test_other_checks_is_left_out_when_it_holds_no_row() -> None:
    view = by_type(session_of("no-other", [spec("interference.static")]))

    assert [one.id for one in view.groups] == SEVEN


# --- 3. the family unfolded, the same-check fold kept ---------------------------------------


def test_the_family_is_unfolded_and_the_same_check_fold_kept() -> None:
    session = session_of("family", MIXED).model_copy(update={"folded_families": ["rms"]})

    practice = group(by_type(session), "modelling_practice")

    assert all(row.family is None for row in practice.rows)
    assert [row.member_finding_ids for row in practice.rows] == [
        ["F-005"],
        ["F-002", "F-003"],
        ["F-004"],
    ]
    assert practice.rows[1].check == "rms.folders.present", "a row's check is its own"


def test_a_folded_session_and_an_unfolded_one_give_the_same_view() -> None:
    plain = session_of("family-same", MIXED)

    assert by_type(plain.model_copy(update={"folded_families": ["rms"]})) == by_type(plain)


# --- 4. what a row carries -----------------------------------------------------------------------


def test_a_rows_titles_are_display_titles() -> None:
    specs = [spec("interference.static", title=f"Interference between {PART_COMPONENT} and more")]
    view = by_type(session_of("titles", specs), attention_package())

    [row] = group(view, "interference_fit").rows
    assert row.title == "Interference between housing-1 and more"


def test_a_persisted_explanation_attaches_by_finding_id() -> None:
    session = session_of("explained", MIXED)
    session.finding_explanations = {"F-001": "why this matters", "F-099": "an unknown id"}

    rows = {row.finding_id: row.explanation for row in every_row(by_type(session))}

    assert rows["F-001"] == "why this matters"
    assert [one for one, text in rows.items() if text is not None] == ["F-001"]


def test_a_single_member_row_hides_its_card_title_and_carries_no_count_or_reach() -> None:
    [row] = group(
        by_type(session_of("single", [spec("interference.static")])), "interference_fit"
    ).rows

    assert (row.tail_text, row.reach_text, row.hide_card_title) == (None, None, True)


def test_a_folded_row_says_its_count_and_its_reach() -> None:
    specs = [
        spec("rms.folders.present", component_ids=(one,))
        for one in (PIN_ONE, PIN_TWO, PART_COMPONENT)
    ]
    [row] = group(by_type(session_of("folded", specs)), "modelling_practice").rows

    assert (row.tail_text, row.reach_text, row.hide_card_title) == (
        "×3",
        "reaches 3 components",
        False,
    )


def test_a_folded_row_that_names_one_component_says_so_in_the_singular() -> None:
    specs = [
        spec("rms.folders.present", component_ids=(PIN_ONE,)),
        spec("rms.folders.present", component_ids=(), drawing_locations=(ON_A_SHEET,)),
    ]
    [row] = group(by_type(session_of("folded-one", specs)), "modelling_practice").rows

    assert (row.tail_text, row.reach_text) == ("×2", "reaches 1 component")


def test_a_folded_row_that_names_no_component_has_no_reach() -> None:
    specs = [
        spec("rms.folders.present", component_ids=(), drawing_locations=(ON_A_SHEET,))
        for _ in range(2)
    ]
    [row] = group(by_type(session_of("folded-none", specs)), "modelling_practice").rows

    assert (row.tail_text, row.reach_text) == ("×2", None)


def test_a_group_rows_json_keeps_every_word_and_drops_the_family_fields() -> None:
    [row] = group(
        by_type(session_of("json", [spec("interference.static")])), "interference_fit"
    ).rows

    body = row.model_dump(mode="json")

    assert {"tail_text", "reach_text", "hide_card_title"} <= set(body)
    assert "family" not in body and "rule_count" not in body


# --- 5. the checked fold -------------------------------------------------------------------------


def test_a_waived_pass_carries_the_exception_tail() -> None:
    specs = [spec("rms.folders.present", status="checked_within_scope", exception_id="EX-001")]
    view = by_type(session_of("waived", specs))

    assert view.checked is not None
    [row] = view.checked.rows
    assert row.tail_text == "within an accepted exception"


def test_a_folded_waived_pass_carries_its_count_and_the_tail() -> None:
    specs = [
        spec(
            "rms.folders.present",
            status="checked_within_scope",
            exception_id="EX-001",
            component_ids=(one,),
        )
        for one in (PIN_ONE, PIN_TWO)
    ]
    view = by_type(session_of("waived-folded", specs))

    assert view.checked is not None
    assert view.checked.rows[0].tail_text == "×2 · within an accepted exception"


def test_a_folded_pass_waived_only_in_part_does_not_claim_the_exception() -> None:
    specs = [
        spec(
            "rms.folders.present",
            status="checked_within_scope",
            exception_id="EX-001",
            component_ids=(PIN_ONE,),
        ),
        spec("rms.folders.present", status="checked_within_scope", component_ids=(PIN_TWO,)),
    ]
    view = by_type(session_of("waived-part", specs))

    assert view.checked is not None
    assert view.checked.rows[0].tail_text == "×2"


def test_the_fold_is_collapsed_and_counts_findings() -> None:
    specs = [
        spec("rms.folders.present", status="checked_within_scope", component_ids=(one,))
        for one in (PIN_ONE, PIN_TWO)
    ] + [spec("hygiene.revision_present", status="checked_within_scope")]
    view = by_type(session_of("fold", specs))

    assert view.checked is not None
    assert (view.checked.title, view.checked.open, view.checked.findings, view.checked.text) == (
        "Checked, no issue",
        False,
        3,
        "3 findings",
    )


def test_no_pass_gives_no_fold() -> None:
    assert by_type(session_of("no-fold", [spec("interference.static")])).checked is None


# --- 6. the groups themselves --------------------------------------------------------------------


def test_the_seven_groups_come_in_order_with_their_words() -> None:
    view = by_type(session_of("seven", MIXED))

    assert [one.id for one in view.groups] == [*SEVEN, "other"]
    practice = group(view, "modelling_practice")
    assert (practice.title, practice.open) == ("Modelling practice", False)
    assert group(view, "interference_fit").text == "2 findings"
    assert group(view, "drawings").text == "1 finding"


def test_a_groups_goals_are_its_goal_lines_in_goal_order() -> None:
    view = by_type(session_of("goals", MIXED))

    assert [line.goal for line in group(view, "interference_fit").goals] == [
        "interference",
        "hole_alignment",
        "fits_and_stacks",
    ]
    assert [line.goal for line in group(view, "fasteners").goals] == ["fasteners", "tool_access"]
    assert [line.goal for line in group(view, "standards").goals] == ["standards"]


def test_an_empty_session_renders_seven_groups_of_goal_states_and_no_fold() -> None:
    view = by_type(session_of("empty", []))

    assert [one.id for one in view.groups] == SEVEN
    assert all(one.rows == [] and one.findings == 0 for one in view.groups)
    assert {one.text for one in view.groups} == {"not reached (no check ran)"}
    assert view.checked is None


def test_an_all_pass_session_lists_every_finding_in_the_fold() -> None:
    specs = [
        spec("standards.part.cut_list_excluded", status="checked_within_scope"),
        spec("rms.folders.present", status="checked_within_scope"),
    ]
    view = by_type(session_of("all-pass", specs))

    assert all(one.rows == [] for one in view.groups)
    assert view.checked is not None and view.checked.findings == 2
    assert group(view, "standards").text == "checked, no issue", "its one goal was checked"


def test_a_group_with_no_row_takes_the_first_goal_line_in_the_state_precedence() -> None:
    """Not reached before checked: the Fasteners group says Tool access was not reached,
    although the Fasteners goal before it was checked (feature 009's precedence)."""
    coverage = CoverageSpec(
        checked=[CoverageRow(check="fasteners", reason="every joint was checked.")],
        unresolved=[CoverageRow(check="fastener.head_clearance", reason="no tool was modelled.")],
    )
    view = by_type(session_of("precedence", [], coverage))

    assert [(line.goal, line.state) for line in group(view, "fasteners").goals] == [
        ("fasteners", "checked"),
        ("tool_access", "not_reached"),
    ]
    assert group(view, "fasteners").text == "not reached (evidence missing)"


def test_a_group_whose_goals_are_all_checked_says_checked() -> None:
    coverage = CoverageSpec(
        checked=[
            CoverageRow(check="fasteners", reason="every joint was checked."),
            CoverageRow(check="fastener.head_clearance", reason="every head clears."),
        ]
    )
    view = by_type(session_of("all-checked", [], coverage))

    assert group(view, "fasteners").text == "checked, no issue"


def test_folding_mass_and_material_into_hygiene_gives_six_groups_none_empty() -> None:
    words = Words.model_validate(
        {
            **raw_words(),
            "goals": [
                {**goal, "group": "hygiene"} if goal["id"] == "mass_and_material" else goal
                for goal in raw_words()["goals"]
            ],
        }
    )
    specs = [spec("mass.density"), spec("hygiene.revision_present")]

    view = by_type(session_of("six", specs), words=words)

    assert [one.id for one in view.groups] == [one for one in SEVEN if one != "mass_material"]
    assert members(group(view, "hygiene").rows) == ["F-001", "F-002"]
    assert [line.goal for line in group(view, "hygiene").goals] == [
        "mass_and_material",
        "hygiene",
    ]


# --- 7. the fixtures -----------------------------------------------------------------------------


def test_the_review_fixture_fills_its_groups() -> None:
    session = load_session(REVIEW_SESSION_FILE)
    view = by_type(session, load_package(REVIEW_FOLDER).package)

    assert [one.id for one in view.groups] == SEVEN
    assert sum(one.findings for one in view.groups) == len(session.findings)


def test_the_big_assembly_has_no_other_checks_and_no_fold() -> None:
    session = load_session(BIG_ASSEMBLY / "session.json")
    view = by_type(session, load_package(BIG_ASSEMBLY).package)

    assert [one.id for one in view.groups] == SEVEN
    assert view.checked is None
    assert group(view, "modelling_practice").findings == 85
    assert group(view, "standards").findings == 5


def test_the_view_writes_nothing_to_the_session() -> None:
    session = session_of("pure", MIXED)
    before = session.model_dump_json()

    by_type(session, attention_package())

    assert session.model_dump_json() == before


def test_the_root_component_is_named_like_any_other() -> None:
    specs = [
        spec(
            "rms.assembly.mates_to_reference_geometry",
            component_ids=(ROOT_COMPONENT,),
            title=f"Mates on {ROOT_COMPONENT}",
        )
    ]
    view = by_type(session_of("root", specs), attention_package())

    assert group(view, "modelling_practice").rows[0].title == "Mates on cover-assy-1"


def test_the_module_loads_no_provider_settings_or_network_module() -> None:
    from tests.unit.test_review_summary import modules_loaded_by

    loaded = modules_loaded_by("swreview.report.finding_groups")
    forbidden = ("swreview.agent.providers", "swreview.agent.settings", "httpx", "openai", "google")
    assert [name for name in loaded if name.startswith(forbidden)] == []
