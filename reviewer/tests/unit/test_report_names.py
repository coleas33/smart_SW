"""`report/names.py` (feature 009 T005): one component-name helper, three callers.

The explanations pass, the summary and finding titles all need "which part is `cmp:0003`",
and each of them building its own map would be three chances to disagree about a blank
name (research R2.6). What this pins:

- `component_names(package)` is exactly the map `report/explanations.py` built by hand -
  every component, blank names included - so moving the explanations onto it changes no
  byte of the request they send (the characterization at the bottom, captured on
  `01d2590` before the refactor);
- `with_component_names(text, names)` replaces a whole `cmp:` id token (the IR's
  `^cmp:[0-9]{4,}$`) whose name is non-blank, and nothing else: an id with a blank or no
  name, a token too short to be an id, and an id inside a longer token all stay as written.
"""

from __future__ import annotations

import hashlib

import pytest

from swreview.ir.loader import load_package
from swreview.report.attention import rank
from swreview.report.explanations import _prompt
from swreview.report.names import and_list, component_names, plural, with_component_names
from swreview.report.session import load_session
from tests.support.attention import REVIEW_FOLDER, attention_package

NAMES = {"cmp:0001": "Base-1", "cmp:0003": "Pin-A-1", "cmp:0004": "", "cmp:12345": "Plate-9"}
"""A lookup with one blank name and one five-digit id, as a package can carry both."""


# --- component_names -------------------------------------------------------------------


def test_component_names_is_every_component_by_id_blank_names_included() -> None:
    package = attention_package()
    blank = package.components[1].model_copy(update={"name": ""})
    package = package.model_copy(update={"components": [package.components[0], blank]})

    assert component_names(package) == {c.id: c.name for c in package.components}
    assert component_names(package)[blank.id] == ""


def test_component_names_of_the_fixture_package() -> None:
    assert component_names(attention_package()) == {
        "cmp:0001": "cover-assy-1",
        "cmp:0002": "dowel-pin-1",
        "cmp:0003": "housing-1",
        "cmp:0004": "dowel-pin-2",
    }


# --- with_component_names --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Clash (cmp:0003) found", "Clash (Pin-A-1) found"),
        ("cmp:0003, then cmp:0001", "Pin-A-1, then Base-1"),
        ("It touches cmp:0003.", "It touches Pin-A-1."),
        ("It touches cmp:0003", "It touches Pin-A-1"),
        ("cmp:0003", "Pin-A-1"),
        ("between cmp:0001 and cmp:0003 in Default", "between Base-1 and Pin-A-1 in Default"),
    ],
)
def test_a_named_id_is_replaced_wherever_it_stands_as_a_token(text: str, expected: str) -> None:
    assert with_component_names(text, NAMES) == expected


@pytest.mark.parametrize(
    "text",
    [
        "a blank name keeps its id: cmp:0004.",
        "an unknown id keeps itself: cmp:0099.",
        "too short to be an id: cmp:12 and cmp:123.",
        "inside a longer token: xcmp:0003 and cmp:00031 and cmp:0003x.",
        "no id at all, and punctuation kept: (a), b. c;",
        "",
    ],
)
def test_everything_else_is_left_byte_identical(text: str) -> None:
    assert with_component_names(text, NAMES) == text


def test_a_five_digit_id_that_is_a_key_is_replaced() -> None:
    assert with_component_names("see cmp:12345.", NAMES) == "see Plate-9."


def test_a_whitespace_only_name_counts_as_blank() -> None:
    assert with_component_names("cmp:0001 stays", {"cmp:0001": "   "}) == "cmp:0001 stays"


def test_the_inputs_are_not_mutated() -> None:
    names = dict(NAMES)
    text = "cmp:0003 and cmp:0001"

    with_component_names(text, names)

    assert names == NAMES
    assert text == "cmp:0003 and cmp:0001"


# --- and_list: names in prose -----------------------------------------------------------


@pytest.mark.parametrize(
    ("names", "text"),
    [
        (["Pin-A-1"], "Pin-A-1"),
        (["Pin-A-1", "Plate-1"], "Pin-A-1 and Plate-1"),
        (["a-1", "b-1", "c-1"], "a-1, b-1 and c-1"),
    ],
)
def test_and_list_joins_names_as_a_sentence_does(names: list[str], text: str) -> None:
    assert and_list(names) == text


@pytest.mark.parametrize(
    ("count", "text"),
    [(0, "0 drawings"), (1, "1 drawing"), (2, "2 drawings"), (11, "11 drawings")],
)
def test_plural_counts_one_noun_the_one_way_every_digest_does(count: int, text: str) -> None:
    """The one spelling rule the pre-run's digest, the joint coverage and the drawing check
    share (feature 011 review, 2026-09-23: three byte-identical copies became this one)."""
    assert plural(count, "drawing") == text


# --- the characterization: the explanations request did not move -------------------------

EXPLANATION_PROMPT_SHA256 = "8383a2da6dbe23979de9bec4a7d8904f5b44f81138d1a1434f0de725d049525c"
"""sha256 of `_prompt` over the attention review folder, captured on `01d2590` before
`report/explanations.py` was moved onto `component_names` (research R2.6)."""


def test_the_explanation_request_is_byte_identical_after_the_refactor() -> None:
    session = load_session(REVIEW_FOLDER / "session.json")
    package = load_package(REVIEW_FOLDER).package

    prompt = _prompt(rank(session).rows, session=session, package=package)

    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == EXPLANATION_PROMPT_SHA256
