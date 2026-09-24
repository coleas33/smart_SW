"""The drawing questions the Review tab's page tests play are what the backend produces (011).

`extractor/SwReview.AddIn.Tests/Fixtures/review-drawing-questions.json` is what
`ReviewPageDrawingQuestionsTests` loads: the drawing questions, the engineer's batch, the
coverage and the questions still open afterwards, of one scripted review played through the
real runner, `check_drawings`, session writer and `BridgeClient`
(`tests/fixtures/pane/generate_drawing_questions.py`). The page lane first wrote those tests
against hand-built samples from the contract, and the backend lane's words differed from them
(the candidate's and the governing questions' `what`, the governing questions' `about`, the
"read from" list's last "and", and the bridge's wording of a host refusal); this module holds
the committed file to a fresh generation so the page is tested against the backend's words
from now on (research R2.24).

It also pins the far end of the pipe the generator plays - the host's not-validated sentence and
the members of its `drawing.read` result are the add-in's own, found in the C# source - and the
properties the page tests rely on: the three questions are the candidate question, a governing
question with its file names offered and one with its stem shortened and nothing offered; the
answers are offered words; the checked bucket arrives out of sorted order, so a page that sorted
it would fail; and every name the package contributed is fictional.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.checks.drawing_context import ALL_APPLY, CANDIDATE_CONFIRM, CANDIDATE_OPTIONS
from swreview.report.summary import drawings_of
from swreview.tools.drawings import CONFIRMED_OPEN_CHECK
from tests.support.drawings import drawing_fictional_offences
from tests.support.fixture_denylist import (
    DENYLIST_PATH,
    PUBLISHED_HEAD_CODES,
    load_denylist,
    offending_tokens,
)
from tests.support.mechanical import load_generator

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "reviewer" / "tests" / "fixtures" / "pane" / "generate_drawing_questions.py"
DRAWING_OPEN_SCOPE = REPO / "extractor" / "SwReview.Extractor" / "Sw" / "DrawingOpenScope.cs"
BRIDGE_DISPATCHER = REPO / "extractor" / "SwReview.Extractor" / "Bridge" / "BridgeDispatcher.cs"
DRIVE_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
URL = re.compile(r"https?://", re.IGNORECASE)


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return load_generator(GENERATOR)


@pytest.fixture(scope="module")
def committed(generator: ModuleType) -> str:
    target = generator.TARGET
    assert target.is_file(), f"{target} is missing; run `{generator.WRITE_COMMAND}` from reviewer/"
    # Text mode: the checkout's line endings are the platform's, the generator's too.
    return target.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fixture(committed: str) -> dict[str, Any]:
    return json.loads(committed)


def items(block: dict[str, Any]) -> list[dict[str, Any]]:
    return list(block["items"])


def strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for member in value.values():
            yield from strings(member)
    elif isinstance(value, list):
        for member in value:
            yield from strings(member)


# --- the file is the backend's ------------------------------------------------------------------


def test_the_committed_fixture_is_a_fresh_generation(generator: ModuleType, committed: str) -> None:
    fresh = generator.render(generator.drawing_questions_fixture())

    assert committed == fresh, (
        f"{generator.TARGET.name} differs from a fresh generation; run "
        f"`{generator.WRITE_COMMAND}` from reviewer/ and commit the result"
    )


def test_it_is_written_where_the_page_tests_load_it(generator: ModuleType) -> None:
    """The add-in test project copies `Fixtures/review-*.json` beside its tests."""
    target = Path(generator.TARGET)

    assert target.parts[-3:] == (
        "SwReview.AddIn.Tests", "Fixtures", "review-drawing-questions.json"
    )


def test_it_holds_the_asked_questions_the_answers_the_coverage_and_what_stays_open(
    fixture: dict[str, Any],
) -> None:
    """Edited deliberately for T090 (2026-09-23): `summary_drawings`, the summary's drawings line
    after the first turn, which `SummarySample` in the add-in's tests prints."""
    assert list(fixture) == [
        "run_id",
        "questions_asked",
        "summary_drawings",
        "answers",
        "coverage",
        "questions_open_after",
    ]


# --- the far end of the pipe is the add-in's ----------------------------------------------------


def test_the_host_refusal_it_plays_is_the_seams_sentence_word_for_word(
    generator: ModuleType,
) -> None:
    source = DRAWING_OPEN_SCOPE.read_text(encoding="utf-8")

    assert f'NotValidatedSentence =\n        "{generator.NOT_VALIDATED}";' in source


def test_the_host_results_it_plays_carry_exactly_the_members_the_host_writes(
    generator: ModuleType,
) -> None:
    source = BRIDGE_DISPATCHER.read_text(encoding="utf-8")
    body = source[source.index("public sealed class ConfirmedDrawingResult") :]
    body = body[: body.index("\n}\n")]
    members = re.findall(r'JsonPropertyName\("([a-z_]+)"\)', body)

    answers = generator.host_answers(generator.drawing_review_package())
    results = [result for status, result in answers.values() if status == "ok"]
    assert results and all(list(result) == members for result in results)


def test_the_host_document_id_is_the_extractors_derivation() -> None:
    """`DocumentIds.For`: SHA-1 over the lower-cased, backslash path, 12 hex digits."""
    generator = load_generator(GENERATOR)

    assert generator.host_document_id("C:/Fictional/Vault/A.SLDDRW") == generator.host_document_id(
        "c:\\fictional\\vault\\a.slddrw"
    )
    assert re.fullmatch(r"doc:[0-9a-f]{12}", generator.host_document_id("C:\\Fictional\\A"))


# --- what the page tests rely on ----------------------------------------------------------------


def test_the_first_question_is_the_candidate_question_and_its_first_answer_acts(
    fixture: dict[str, Any],
) -> None:
    candidate = items(fixture["questions_asked"])[0]

    assert candidate["options"] == list(CANDIDATE_OPTIONS)
    assert candidate["options"][0] == CANDIDATE_CONFIRM
    assert candidate["options"][0] == candidate["options"][0].strip()
    assert candidate["blocks"] == "drawing.manufacturing_inputs"
    assert candidate["blocks_title"]


def test_the_second_offers_the_drawings_by_file_name_then_they_all_apply(
    fixture: dict[str, Any],
) -> None:
    governing = items(fixture["questions_asked"])[1]
    drawings = [about["name"] for about in governing["about"][1:]]

    assert governing["options"] == [*drawings, ALL_APPLY]
    assert governing["blocks"] is None


def test_the_third_is_shortened_and_offers_nothing(fixture: dict[str, Any]) -> None:
    long_named = items(fixture["questions_asked"])[2]

    assert long_named["options"] == []
    assert "\u2026" in long_named["question"]
    assert len(long_named["about"]) == 6


def test_the_answers_are_offered_words_of_the_first_two_questions(
    fixture: dict[str, Any],
) -> None:
    asked = items(fixture["questions_asked"])

    assert [request_id for request_id, _ in fixture["answers"]] == [asked[0]["id"], asked[1]["id"]]
    assert fixture["answers"][0][1] == CANDIDATE_CONFIRM
    assert fixture["answers"][1][1] == ALL_APPLY
    assert all(
        answer in question["options"]
        for (_, answer), question in zip(fixture["answers"], asked, strict=False)
    )


def test_only_the_skipped_question_stays_open(fixture: dict[str, Any]) -> None:
    assert items(fixture["questions_open_after"]) == [items(fixture["questions_asked"])[2]]


def test_the_checked_bucket_arrives_out_of_sorted_order(fixture: dict[str, Any]) -> None:
    """So a page that sorted a bucket by its check would fail the page test."""
    checked = [row["item"]["check"] for row in fixture["coverage"] if row["bucket"] == "checked"]

    assert checked != sorted(checked)
    assert checked.index("drawing.context") < checked.index(CONFIRMED_OPEN_CHECK)


def test_the_three_confirmed_reads_each_leave_one_coverage_item(
    fixture: dict[str, Any], generator: ModuleType
) -> None:
    confirmed = [
        (row["bucket"], row["item"]["reason"])
        for row in fixture["coverage"]
        if row["item"]["check"] == CONFIRMED_OPEN_CHECK
    ]

    assert confirmed == [
        ("checked", "opened read-only, read and closed (1 sheet)"),
        ("unresolved", f"the bridge returned status 'error': {generator.NOT_VALIDATED}"),
        ("checked", "read as it stood; it was already open, so it was left open"),
    ]


def test_the_summarys_drawings_line_is_the_backends_for_the_package_it_plays(
    fixture: dict[str, Any], generator: ModuleType
) -> None:
    """Feature 011 T090: the page's sample of decision 10A's line is `report/summary.drawings_of`
    over the review's package - both halves of the line, the drawings read and the same-name
    drawings found but not open - so the page is tested on words the backend writes."""
    line = drawings_of(generator.drawing_review_package())

    assert line is not None
    assert fixture["summary_drawings"] == line.model_dump(mode="json")
    assert len(line.read) == len(generator.PLATE_DRAWINGS) + len(generator.LONG_PART_DRAWINGS)
    assert line.candidates == [f"{stem}.SLDDRW" for stem in generator.BLOCKS]


# --- public-repository hygiene ------------------------------------------------------------------


def package_names(fixture: dict[str, Any]) -> list[str]:
    """The file names the package contributed: every question's `about` names, every file name
    a governing question offers, and every file name the summary's drawings line names. The rest
    is the backend's own words."""
    asked = items(fixture["questions_asked"])
    names = [about["name"] for question in asked for about in question["about"]]
    names += [option for question in asked[1:] for option in question["options"]]
    names += [*fixture["summary_drawings"]["read"], *fixture["summary_drawings"]["candidates"]]
    return [name for name in names if name != ALL_APPLY]


def test_every_name_the_package_contributed_is_fictional(fixture: dict[str, Any]) -> None:
    names = package_names(fixture)

    assert names
    assert {name: drawing_fictional_offences(name) for name in names} == dict.fromkeys(names, [])


def test_no_string_is_a_drive_path_an_email_or_a_url(fixture: dict[str, Any]) -> None:
    offenders = [
        text
        for text in strings(fixture)
        if DRIVE_PATH.search(text) or EMAIL.search(text) or URL.search(text)
    ]

    assert offenders == []


def test_no_token_of_the_owners_denylist_occurs_in_a_name(fixture: dict[str, Any]) -> None:
    """Over the names, as `test_drawing_fixtures_are_fictional.py` checks the drawing fixtures'
    strings; the backend's own sentences are not the package's and are not scanned here."""
    denylist = load_denylist()
    if denylist is None:
        pytest.skip(f"the owner's denylist is not on this machine ({DENYLIST_PATH})")
    checked = denylist - PUBLISHED_HEAD_CODES

    assert [name for name in package_names(fixture) if offending_tokens(name, checked)] == []
