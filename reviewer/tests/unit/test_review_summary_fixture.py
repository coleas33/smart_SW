"""The US3 backend acceptance (feature 009 T022): the big-assembly summary, re-derived by hand.

Feature 008's committed `big-assembly` replay fixture is shaped like the big recorded review
(99 findings over 89 component instances, fictional names). Every number and word below was
read off the fixture's own findings and coverage with `contracts/review-summary.md` sections 2
to 4 in hand, and written in literally; the comment on each goal names the rows that decide
it. Written after the implementation and passing with no further production code.
"""

from __future__ import annotations

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import rank
from swreview.report.session import ReviewSession, load_session
from swreview.report.summary import GoalLine, ReviewSummary, review_summary
from tests.unit.test_review_summary import BIG_ASSEMBLY

FASTENERS_CLOSEOUT = (
    "Bu fastener records were extracted despite many screw-like component names; joint "
    "mapping, washer data, fiz usable thread depth are unavailable, including unknown thread "
    "depth for hol:0009 fiz hol:0021."
)
FIT_CLOSEOUT = (
    "Mating holes fiz mates are present, but no drawing kudo/shaft limits or tolerances are "
    "available; check_fit cannot be run without drawing source references."
)
DRAWINGS_CLOSEOUT = (
    "Bu drawing documents, sheets, or dimensions were extracted; the drawing phase did duv "
    "run, so material/tolerance/finish/thread-depth/fit tedikune cannot be reviewed."
)
MATERIAL_ROW_HEAD = (
    "23 document(s): doc:792f2ea287a0: 359-17543.SLDPRT has no configuration 'AsBuilt', "
    "which is the profile's material configuration;"
)
"""The head of the unresolved `standards.part.material_assigned` rule row's reason, which
runs to 23 documents; the test compares the whole of it with the row, verbatim."""


@pytest.fixture(scope="module")
def session() -> ReviewSession:
    return load_session(BIG_ASSEMBLY / "session.json")


@pytest.fixture(scope="module")
def package() -> EvidencePackage:
    return load_package(BIG_ASSEMBLY).package


@pytest.fixture(scope="module")
def summary(session: ReviewSession, package: EvidencePackage) -> ReviewSummary:
    return review_summary(rank(session), session, package)


def goal(summary: ReviewSummary, goal_id: str) -> GoalLine:
    return next(line for line in summary.goals if line.goal == goal_id)


def test_the_headline(summary: ReviewSummary) -> None:
    assert summary.headline == "99 findings in 18 issues"


def test_the_three_groups_with_their_goals(summary: ReviewSummary) -> None:
    # Decide: 6 interference.static (demonstrated) and 3 hole.coaxiality (unresolved), both
    # needs-judgement families. Fix: 51 demonstrated rms.* and 5 demonstrated
    # standards.part.* (1 cut_list_excluded, 4 sketches_fully_defined). Verify: 20
    # rms.folders.present and 14 rms.params.dimensions_driven_by_equations, all suspected.
    # No finding is within scope or decided, so only the owner's three groups are listed.
    assert [
        (group.label, group.text, [(one.title, one.count) for one in group.by_goal])
        for group in summary.groups
    ] == [
        ("Decide", "9 need your decision", [("Interference", 6), ("Hole alignment", 3)]),
        ("Fix", "56 to fix", [("Hygiene", 5), ("Modelling practice", 51)]),
        ("Verify", "34 to verify", [("Modelling practice", 34)]),
    ]


def test_the_questions_and_the_parts_not_loaded(summary: ReviewSummary) -> None:
    # ER-001 to ER-004 are all open. cmp:0020 and cmp:0021 are lightweight and cmp:0029 is
    # suppressed, of 89 instances.
    assert summary.questions.text == "4 questions for you"
    assert [item.id for item in summary.questions.items] == ["ER-001", "ER-002", "ER-003", "ER-004"]
    assert summary.not_loaded is not None
    assert summary.not_loaded.text == "3 of 89 parts not loaded"


def test_every_goal_line(summary: ReviewSummary, session: ReviewSession) -> None:
    lines = {
        line.goal: (line.state_label, line.findings, line.reason, line.detail)
        for line in summary.goals
    }
    material_row = next(
        item.reason
        for item in session.coverage.unresolved
        if item.check == "standards.part.material_assigned"
    )

    assert list(lines) == [
        "interference",
        "fasteners",
        "hole_alignment",
        "fits_and_stacks",
        "tool_access",
        "mass_and_material",
        "hygiene",
        "drawings",
        "modelling_practice",
    ]
    # Interference: 6 interference.static findings are demonstrated; issues outrank the
    # `interference` checked row.
    assert lines["interference"] == ("issues found", 6, None, None)
    # Fasteners: no fastener.* finding; the `fasteners` close-out row is unresolved.
    assert lines["fasteners"] == ("not reached", 0, "evidence missing", FASTENERS_CLOSEOUT)
    # Hole alignment: 3 hole.coaxiality findings are unresolved - a status other than within
    # scope - so issues outrank the unresolved `holes.alignment` close-out row.
    assert lines["hole_alignment"] == ("issues found", 3, None, None)
    # Fits and stacks: no fit.* or stack.* finding; `interfaces.fit` is the first unresolved
    # close-out row of the goal (before `interfaces.stack`).
    assert lines["fits_and_stacks"] == ("not reached", 0, "evidence missing", FIT_CLOSEOUT)
    # Tool access: no finding and no row under fastener.head_clearance or fastener.head_fit.
    assert lines["tool_access"] == ("not reached", 0, "no check ran", None)
    # Mass and material: only standards.part.material_assigned rows, one unresolved and one
    # out of scope, no checklist item - the case section 3's last row closes: not reached,
    # from the unresolved rule row. The out-of-scope row does not make it "not applicable".
    assert lines["mass_and_material"] == ("not reached", 0, "evidence missing", material_row)
    assert material_row.startswith(MATERIAL_ROW_HEAD)
    # Hygiene: 5 standards.part.* findings are demonstrated (material_assigned is mass and
    # material by its longer prefix, and has no finding).
    assert lines["hygiene"] == ("issues found", 5, None, None)
    # Drawings: no drawing.* finding; the `drawing.manufacturing_inputs` close-out row is
    # unresolved, and the rms.drawing./standards.drawing. rows are out of scope only.
    assert lines["drawings"] == ("not reached", 0, "evidence missing", DRAWINGS_CLOSEOUT)
    # Modelling practice: 85 rms.* findings (51 demonstrated, 34 suspected); issues outrank
    # the unresolved `modeling.resilience` close-out row.
    assert lines["modelling_practice"] == ("issues found", 85, None, None)


def test_no_state_is_computed_from_severity_or_left_empty(summary: ReviewSummary) -> None:
    assert {line.state for line in summary.goals} == {"issues", "not_reached"}
    assert all(line.state_label for line in summary.goals)
    assert goal(summary, "tool_access").detail is None
