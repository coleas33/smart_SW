"""Question identity preserves the answer and confirmed-read rules (015 T025).

The restart carry compares the same three ordered fields as the existing callers.
Identity does not decide whether an answer is usable or whether it opens a drawing;
those guards stay with the callers. The recording duplicate rule remains separate.
"""

from __future__ import annotations

from typing import Any

import pytest

from swreview.checks import part_roles, questions
from swreview.checks.drawing_context import CANDIDATE_CONFIRM, CANDIDATE_OPTIONS
from swreview.tools import drawings
from tests.unit.test_part_roles import two_unclear
from tests.unit.test_questions import request, spec

IDENTITY_CASES = [
    pytest.param({}, True, id="same"),
    pytest.param({"question": None}, False, id="no-question"),
    pytest.param({"question": "Another fictional question?"}, False, id="other-question"),
    pytest.param({"options": []}, False, id="no-options"),
    pytest.param({"options": ["No", "Yes"]}, False, id="option-order"),
    pytest.param({"options": ["Yes"]}, False, id="option-subset"),
    pytest.param({"options": ["Yes", "No", "Later"]}, False, id="option-superset"),
    pytest.param({"options": ["YES", "No"]}, False, id="option-case"),
    pytest.param({"entity_ids": []}, False, id="no-ids"),
    pytest.param({"entity_ids": ["doc:0003", "doc:0002"]}, False, id="id-order"),
    pytest.param({"entity_ids": ["doc:0002"]}, False, id="id-subset"),
    pytest.param(
        {"entity_ids": ["doc:0002", "doc:0003", "doc:0004"]}, False, id="id-superset"
    ),
    pytest.param(
        {"entity_ids": ["doc:0002", "doc:0003", "doc:0003"]}, False, id="repeated-id"
    ),
    pytest.param({"id": "ER-099"}, True, id="request-number"),
    pytest.param({"what": "A different fictional description"}, True, id="what"),
    pytest.param({"why": "A different fictional reason"}, True, id="why"),
    pytest.param({"blocks": None}, True, id="blocks"),
    pytest.param({"allow_text": True}, True, id="allow-text"),
    pytest.param({"source": "code"}, True, id="source"),
    pytest.param({"status": "answered", "answer": "No"}, True, id="answer-state"),
]


@pytest.mark.parametrize("new_is_request", [False, True], ids=["spec", "request"])
@pytest.mark.parametrize(("changes", "same"), IDENTITY_CASES)
def test_identity_compares_only_question_options_and_ordered_ids(
    changes: dict[str, Any], same: bool, new_is_request: bool
) -> None:
    asked = spec()
    earlier = request(asked, **changes)
    new = request(asked, id="ER-002") if new_is_request else asked

    assert questions.asks_same(earlier, new) is same
    assert questions.asks_same(new, earlier) is same


@pytest.mark.parametrize(
    "field", ["question", "options"], ids=["question-space", "option-space"]
)
def test_identity_never_normalizes_question_or_option_words(field: str) -> None:
    asked = spec()
    changes = {"question": asked.question + " "} if field == "question" else {
        "options": [asked.options[0] + " ", asked.options[1]]
    }

    assert questions.asks_same(request(asked, **changes), asked) is False


@pytest.mark.parametrize(
    ("changes", "same"),
    [
        pytest.param({}, True, id="same"),
        pytest.param({"question": "Another fictional question?"}, False, id="question"),
        pytest.param({"options": []}, False, id="options"),
        pytest.param({"reverse_options": True}, False, id="option-order"),
        pytest.param({"reverse_ids": True}, False, id="id-order"),
        pytest.param({"entity_ids": []}, False, id="ids"),
        pytest.param({"what": "Another fictional description"}, True, id="what-ignored"),
        pytest.param({"source": "model"}, True, id="source-ignored"),
    ],
)
def test_existing_answer_and_confirmed_read_callers_keep_the_identity_decisions(
    changes: dict[str, Any], same: bool
) -> None:
    package, roles_spec = two_unclear()
    candidate = spec(options=tuple(CANDIDATE_OPTIONS))
    for asked, answer in ((roles_spec, "All bought"), (candidate, CANDIDATE_CONFIRM)):
        updates = dict(changes)
        if updates.pop("reverse_options", False):
            updates["options"] = list(reversed(asked.options))
        if updates.pop("reverse_ids", False):
            updates["entity_ids"] = list(reversed(asked.entity_ids))
        earlier = request(asked, status="answered", answer=answer, **updates)
        assert questions.asks_same(earlier, asked) is same
        if asked is roles_spec:
            result = part_roles.answered_roles(earlier, roles_spec, package)
            assert (result is not None) is same
            if result is not None:
                assert result.answers == {document: "bought" for document in roles_spec.entity_ids}
        else:
            assert drawings._is_confirmed_candidate(earlier, candidate) is same


@pytest.mark.parametrize(
    ("status", "answer", "reads_roles", "opens_drawing"),
    [
        pytest.param("open", None, False, False, id="open"),
        pytest.param("answered", None, False, False, id="no-answer"),
        pytest.param("answered", "All bought", True, False, id="roles-option"),
        pytest.param("answered", "all bought.", True, False, id="roles-typed-option"),
        pytest.param("answered", CANDIDATE_CONFIRM, True, True, id="exact-confirmation"),
        pytest.param("answered", CANDIDATE_CONFIRM + " ", True, False, id="inexact-confirmation"),
    ],
)
def test_identity_leaves_status_and_answer_guards_with_each_caller(
    status: str, answer: str | None, reads_roles: bool, opens_drawing: bool
) -> None:
    package, roles_spec = two_unclear()
    candidate = spec(options=tuple(CANDIDATE_OPTIONS))
    roles_request = request(roles_spec, status=status, answer=answer)
    drawing_request = request(candidate, status=status, answer=answer)

    assert questions.asks_same(roles_request, roles_spec) is True
    assert questions.asks_same(drawing_request, candidate) is True
    result = part_roles.answered_roles(roles_request, roles_spec, package)
    assert (result is not None) is reads_roles
    assert drawings._is_confirmed_candidate(drawing_request, candidate) is opens_drawing
    assert part_roles.answered_roles(roles_request, None, package) is None
    assert drawings._is_confirmed_candidate(drawing_request, None) is False


def test_both_existing_callers_use_the_shared_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert part_roles.asks_same is questions.asks_same
    assert drawings.asks_same is questions.asks_same
    calls = []

    def no_match(earlier: Any, new: Any) -> bool:
        calls.append((earlier, new))
        return False

    package, roles_spec = two_unclear()
    candidate = spec(options=tuple(CANDIDATE_OPTIONS))
    roles_request = request(roles_spec, status="answered", answer="All bought")
    drawing_request = request(candidate, status="answered", answer=CANDIDATE_CONFIRM)
    monkeypatch.setattr(part_roles, "asks_same", no_match)
    monkeypatch.setattr(drawings, "asks_same", no_match)

    assert part_roles.answered_roles(roles_request, roles_spec, package) is None
    assert drawings._is_confirmed_candidate(drawing_request, candidate) is False
    assert calls == [(roles_request, roles_spec), (drawing_request, candidate)]


def test_recording_duplicate_identity_keeps_its_existing_what_rule() -> None:
    asked = spec()
    changed_what = request(asked, what="Another fictional description")
    changed_options = request(asked, options=["Yes, open it", "No"])

    assert questions.asks_same(changed_what, asked) is True
    assert questions.already_asked([changed_what], asked) is False
    assert questions.asks_same(changed_options, asked) is False
    assert questions.already_asked([changed_options], asked) is True
