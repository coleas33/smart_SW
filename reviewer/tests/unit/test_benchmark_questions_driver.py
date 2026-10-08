"""The driver's delivery decisions through the one matcher (feature 014, T091 for T092).

`contracts/questions.md` 3's scripted-answer row, 4's identity and 9's driver bullet; FR-022,
FR-053, US4-1; spec Edge Cases, "a request naming an item and no ids, on an item with several
scripted answers, is unscripted, the ambiguity named".

`questions.scripted_answer_for(request, answers, *, ids)` is the one decision the answer driver
makes for each open request: a `Delivery` of the one case-file entry the request asks within, or
`Unscripted` with its reason, `ambiguous` naming the entries it matched in file order,
`no_answer`, or `names_nothing`. The part-roles question is matched by its identity alone, by the
`part_roles` entry; every other request, model- or code-written, through `asks_within` against
each entry that is not `part_roles`. There is no second matcher.

Case-file entries are built in memory through `benchmark.case_file.CaseFile`, requests as data,
and the part-roles question through the one writer of code questions, over the questions
reader's fictional package (`questions.md` 7's ids): the plate `doc:0002` with its instance
`cmp:0001` and hole `hol:0001`, the bought pin `doc:0003` with its instances `cmp:0002` and
`cmp:0003`.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

import pytest

from swreview.benchmark import questions
from swreview.benchmark.case_file import CASE_FILE_VERSION, CaseFile, ScriptedAnswer
from swreview.benchmark.questions import Delivery, QuestionIds, Unscripted
from swreview.report.session import EvidenceRequest
from swreview.tools import session as tools_session
from swreview.tools.context import context_for
from tests.unit.test_benchmark_questions import (
    PACKAGE,
    PART_ROLES_SPEC,
    PIN_1,
    PIN_2,
    PIN_DOC,
    PLATE_1,
    PLATE_DOC,
    PLATE_HOLE,
    request,
)

FIT = "interfaces.fit"
FASTENERS = "fasteners"

IDS = QuestionIds(PACKAGE)


def answers(*entries: dict[str, Any]) -> list[ScriptedAnswer]:
    """The entries of a case file built in memory, in file order, as the driver reads them."""
    case = CaseFile.model_validate(
        {
            "case_file_version": CASE_FILE_VERSION,
            "package_id": "fict-questions",
            "answers": list(entries),
        }
    )
    return case.answers


def on(entry_id: str, item: str | None, *entity_ids: str) -> dict[str, Any]:
    """An entry answering the questions on `item` (`None` for none) asked within `entity_ids`."""
    return {"id": entry_id, "item": item, "ids": list(entity_ids), "answer": f"{entry_id}'s words"}


def roles(entry_id: str = "A-9") -> dict[str, Any]:
    """The entry answering the part-roles question."""
    return {"id": entry_id, "part_roles": True, "answer": "All bought"}


def part_roles_question() -> EvidenceRequest:
    """The part-roles question on the pin, recorded as `agent/runner.ask_part_roles` records
    it, through the one writer of code questions."""
    return tools_session.record_question(context_for(PACKAGE), PART_ROLES_SPEC)


def decide(asked: EvidenceRequest, entries: list[ScriptedAnswer]) -> Delivery | Unscripted:
    return questions.scripted_answer_for(asked, entries, ids=IDS)


# --- a delivery: the one entry a request asks within (questions.md 3; QA-11) ---------------------


@pytest.mark.parametrize(
    "named", [PLATE_DOC, PLATE_HOLE, PLATE_1], ids=["document", "hole", "self"]
)
def test_an_entry_keyed_to_the_plate_s_instance_answers_a_request_naming_the_plate(
    named: str,
) -> None:
    """The model names a part by its document, its instance or a hole on it interchangeably;
    each resolves to the instance the entry is keyed to (`questions.md` 2)."""
    entries = answers(on("A-1", FIT, PLATE_1), on("A-2", FASTENERS, PLATE_1))

    assert decide(request("ER-002", FIT, [named]), entries) == Delivery("A-1")


def test_an_entry_answers_a_request_naming_some_of_its_ids() -> None:
    entries = answers(on("A-1", FIT, PLATE_1, PIN_1))

    assert decide(request("ER-002", FIT, [PIN_1]), entries) == Delivery("A-1")


def test_an_item_only_request_with_one_entry_on_its_item_is_a_delivery_of_it() -> None:
    """R-3's "now give numeric limits": the item-only branch, with one entry to ask within."""
    entries = answers(on("A-1", FIT, PLATE_1, PIN_1), on("A-2", FASTENERS, PLATE_1))

    assert decide(request("ER-003", FIT, []), entries) == Delivery("A-1")


def test_an_entry_on_no_item_answers_a_request_on_no_item_naming_its_parts() -> None:
    """`null` equals `null`, and only `null`: the same entry answers no fit question."""
    entries = answers(on("A-1", None, PIN_DOC))

    assert decide(request("ER-002", None, [PIN_2]), entries) == Delivery("A-1")
    assert decide(request("ER-003", FIT, [PIN_2]), entries) == Unscripted("no_answer")


# --- unscripted: ambiguous, no_answer, names_nothing (questions.md 3; spec Edge Cases) ----------


def test_an_item_only_request_with_two_entries_on_its_item_is_ambiguous_naming_both() -> None:
    """Row 8 lets two entries share an item only on disjoint ids, so only a request naming the
    item and no ids can match both (RR3-4): it is given nothing, the ambiguity named, the
    entries in file order and the entry on another item left out."""
    entries = answers(
        on("A-3", FIT, PIN_1, PIN_2),
        on("A-1", FASTENERS, PLATE_1),
        on("A-2", FIT, PLATE_1),
    )

    assert decide(request("ER-003", FIT, []), entries) == Unscripted("ambiguous", ("A-3", "A-2"))


def test_a_request_naming_no_item_and_no_id_names_nothing() -> None:
    """It asks within nothing, whatever the case file holds (`questions.md` 3)."""
    entries = answers(on("A-1", FIT, PLATE_1), on("A-2", None, PIN_DOC), roles())

    assert decide(request("ER-002", None, []), entries) == Unscripted("names_nothing")
    assert decide(request("ER-002", None, []), []) == Unscripted("names_nothing")


@pytest.mark.parametrize(
    ("item", "entity_ids"),
    [(FASTENERS, [PIN_1]), (FIT, [PLATE_1, PIN_2]), (None, [PLATE_1]), (FIT, [PIN_DOC])],
    ids=["another-item", "beyond-the-entry-s-ids", "no-item", "every-pin-instance"],
)
def test_a_request_no_entry_matches_has_no_answer(item: str | None, entity_ids: list[str]) -> None:
    """The pin's document names both its instances, and the entry holds only the first."""
    entries = answers(on("A-1", FIT, PLATE_1, PIN_1), roles())

    assert decide(request("ER-002", item, entity_ids), entries) == Unscripted("no_answer")


def test_with_no_entry_a_request_naming_something_has_no_answer() -> None:
    assert decide(request("ER-002", FIT, [PLATE_1]), []) == Unscripted("no_answer")


# --- the part-roles question, by identity alone (questions.md 4; QA-14) -------------------------


def test_the_part_roles_question_is_answered_by_the_part_roles_entry_only() -> None:
    """Under the relation, an entry on no item naming the pin would ask within the part-roles
    question, which names the pin on no item; the identity keeps it out."""
    asked = part_roles_question()
    assert questions.is_part_roles_question(asked)

    with_roles = answers(on("A-1", None, PIN_DOC), roles("A-2"), on("A-3", FIT, PIN_1))

    assert decide(asked, with_roles) == Delivery("A-2")


def test_the_part_roles_question_has_no_answer_without_the_part_roles_entry() -> None:
    asked = part_roles_question()

    without_roles = answers(on("A-1", None, PIN_DOC), on("A-3", FIT, PIN_1))

    assert decide(asked, without_roles) == Unscripted("no_answer")
    assert decide(asked, []) == Unscripted("no_answer")


def test_a_model_question_in_the_part_roles_words_is_matched_by_item_and_ids() -> None:
    """Never by the `part_roles` entry: a model question in its words is not it."""
    look_alike = part_roles_question().model_copy(update={"source": "model"})
    assert not questions.is_part_roles_question(look_alike)

    assert decide(look_alike, answers(on("A-1", None, PIN_DOC), roles("A-2"))) == Delivery("A-1")
    assert decide(look_alike, answers(roles("A-2"))) == Unscripted("no_answer")


def test_a_code_request_that_is_not_the_part_roles_question_is_matched_like_a_model_one() -> None:
    entries = answers(on("A-1", FIT, PLATE_1), roles("A-2"))
    by_code = request("ER-004", FIT, [PLATE_DOC], source="code")
    assert not questions.is_part_roles_question(by_code)

    assert decide(by_code, entries) == Delivery("A-1")
    assert decide(request("ER-005", FASTENERS, [PLATE_DOC], source="code"), entries) == (
        Unscripted("no_answer")
    )


# --- one relation, no second matcher (questions.md 3; FR-053) -----------------------------------


def spy_on_asks_within(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str | None, frozenset[str], str | None, frozenset[str]]]:
    """Every call `scripted_answer_for` makes to `asks_within`, answered by the real one."""
    asked: list[tuple[str | None, frozenset[str], str | None, frozenset[str]]] = []
    real = questions.asks_within

    def spy(
        later_item: str | None,
        later_ids: Collection[str],
        earlier_item: str | None,
        earlier_ids: Collection[str],
        *,
        ids: QuestionIds,
    ) -> bool:
        asked.append((later_item, frozenset(later_ids), earlier_item, frozenset(earlier_ids)))
        return real(later_item, later_ids, earlier_item, earlier_ids, ids=ids)

    monkeypatch.setattr(questions, "asks_within", spy)
    return asked


def test_a_request_is_matched_through_asks_within_once_per_entry_that_is_not_part_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = answers(on("A-1", FIT, PLATE_1), roles("A-2"), on("A-3", None, PIN_DOC))
    asked = spy_on_asks_within(monkeypatch)

    decided = decide(request("ER-002", FIT, [PLATE_HOLE]), entries)

    assert decided == Delivery("A-1")
    assert asked == [
        (FIT, frozenset({PLATE_HOLE}), FIT, frozenset({PLATE_1})),
        (FIT, frozenset({PLATE_HOLE}), None, frozenset({PIN_DOC})),
    ]


def test_the_part_roles_question_is_never_put_to_asks_within(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked_question = part_roles_question()
    entries = answers(on("A-1", None, PIN_DOC), roles("A-2"))
    asked = spy_on_asks_within(monkeypatch)

    assert decide(asked_question, entries) == Delivery("A-2")
    assert asked == []
