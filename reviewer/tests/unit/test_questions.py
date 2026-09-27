"""The one question shape and the one duplicate test code questions share (feature 013 T004).

Research R3 C10: the drawing check's questions (feature 011) and the part-roles question
(`contracts/part-roles.md` section 8) are one shape, `QuestionSpec`, and one duplicate test,
`already_asked`, both in `checks/questions.py`. The test is today's exact match, moved from
`tools/drawings.py` unchanged (`contracts/re-ask-guard.md` section 3): a code question can
trigger an action (`_is_confirmed_candidate`), so it is recorded unless an identical one is
already on the session. The subset rule is the model's guard (`covering_requests`), never this.
"""

from __future__ import annotations

import dataclasses

import pytest

from swreview.checks import drawing_context, questions
from swreview.checks.questions import QuestionSpec, already_asked
from swreview.report.session import EvidenceRequest
from swreview.tools import drawings


def spec(**changes: object) -> QuestionSpec:
    base = QuestionSpec(
        key="candidates",
        what="The same-name drawing FICT-7001.SLDDRW, beside a reviewed file and not open",
        why="Fits stay unresolved without a drawing.",
        entity_ids=("doc:0002", "doc:0003"),
        question="Should the review read it?",
        options=("Yes", "No"),
        blocks="drawing.manufacturing_inputs",
    )
    return dataclasses.replace(base, **changes)


def request(of: QuestionSpec, **changes: object) -> EvidenceRequest:
    fields: dict[str, object] = {
        "id": "ER-001",
        "what": of.what,
        "why": of.why,
        "entity_ids": list(of.entity_ids),
        "status": "open",
        "answer": None,
        "answered_at": None,
        "question": of.question,
        "options": list(of.options),
        "blocks": of.blocks,
    }
    fields.update(changes)
    return EvidenceRequest(**fields)  # type: ignore[arg-type]


# --- one shape -----------------------------------------------------------------------------------


def test_the_drawing_check_uses_the_shared_shape_and_test() -> None:
    """Moved, not copied: two definitions would be two shapes the day one of them changes."""
    assert drawing_context.QuestionSpec is QuestionSpec
    assert drawings.already_asked is already_asked
    assert not hasattr(drawings, "_already_asked")


def test_a_question_spec_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec().question = "changed"  # type: ignore[misc]


def test_a_question_offers_no_text_box_unless_it_says_so() -> None:
    """`allow_text` is the part-roles question's (`part-roles.md` section 8); the drawing
    check's questions keep today's buttons-only shape by the default."""
    assert spec().allow_text is False
    assert spec(allow_text=True).allow_text is True


# --- one duplicate test: today's exact match ---------------------------------------------------


def test_an_identical_question_is_already_asked() -> None:
    asked = spec()

    assert already_asked([request(asked)], asked) is True


def test_an_answered_identical_question_is_still_asked() -> None:
    """Today's rule reads the three fields and never the status: an answered code question is
    not asked again on a restated check."""
    asked = spec()

    assert already_asked([request(asked, status="answered", answer="No")], asked) is True


def test_nothing_on_the_session_asks_nothing() -> None:
    assert already_asked([], spec()) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"question": "Should the review read them?"},
        {"what": "The same-name drawings FICT-7001.SLDDRW and FICT-7002.SLDDRW"},
        {"entity_ids": ("doc:0003", "doc:0002")},
        {"entity_ids": ("doc:0002",)},
        {"entity_ids": ("doc:0002", "doc:0003", "doc:0004")},
        {"entity_ids": ()},
    ],
    ids=["question", "what", "id-order", "subset", "superset", "no-ids"],
)
def test_a_question_differing_in_question_what_or_ids_is_new(changes: dict[str, object]) -> None:
    """Exact, in order: a subset or a reordering is a different code question."""
    on_session = spec()

    assert already_asked([request(on_session)], spec(**changes)) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"why": "Another reason."},
        {"options": ("Yes, open it", "No")},
        {"blocks": None},
        {"key": "governing:doc:0002"},
        {"allow_text": True},
    ],
    ids=["why", "options", "blocks", "key", "allow-text"],
)
def test_the_fields_the_exact_test_never_read_do_not_make_a_question_new(
    changes: dict[str, object],
) -> None:
    """The moved test reads `question`, `what` and `entity_ids`, as `_already_asked` did."""
    on_session = spec()

    assert already_asked([request(on_session)], spec(**changes)) is True


def test_any_request_on_the_session_may_match() -> None:
    asked = spec()
    other = spec(question="Which drawing governs FICT-7002?")

    assert already_asked([request(other), request(asked, id="ER-002")], asked) is True


def test_the_module_exports_its_two_names() -> None:
    assert set(questions.__all__) >= {"QuestionSpec", "already_asked"}
