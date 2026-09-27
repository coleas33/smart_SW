"""The one name matcher and the one property-name key (feature 013 T002).

`specs/013-engineer-first-review/contracts/part-roles-profile.md` section 2 is normative. The
part-number convention keeps its vocabulary - `#` a digit, `?` any one character, every other
character literal - and the catalogue-number shapes of profile version 4 add `@` (one letter) and
`*` (any run, the empty run included). One function answers both, so the two vocabularies cannot
drift apart: `wildcards=False` is the convention's, `wildcards=True` the shapes'.

`property_key` is how every reader of a named property compares names: real files spell one
property both with and without a space, so a name is folded and stripped of every space.

Every value here is fictional.
"""

from __future__ import annotations

import pytest

from swreview.checks.standards.traversal import name_matches, part_number_matches, property_key

# --- the convention's vocabulary is unchanged ---------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("FICT-####.SLD???", "FICT-1234.SLDPRT", True),
        ("FICT-####.SLD???", "fict-1234.sldprt", True),
        ("FICT-####.SLD???", "FICT-123.SLDPRT", False),
        ("FICT-####.SLD???", "FICT-12345.SLDPRT", False),
        ("FICT-####.SLD???", "FICT-12A4.SLDPRT", False),
        ("FICT-####.SLD???", "XFICT-1234.SLDPRT", False),
        ("FICT-####.SLD???", "FICT-1234.SLDPRT.bak", False),
        ("??-#", "AB-1", True),
        ("??-#", "1B-1", True),
        ("", "anything.SLDPRT", False),
        ("FICT-####.SLD???", "", False),
    ],
)
def test_the_convention_vocabulary(pattern: str, text: str, expected: bool) -> None:
    assert name_matches(pattern, text) is expected
    assert name_matches(pattern, text, wildcards=False) is expected


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("FICT@-*.SLDPRT", "FICT@-*.SLDPRT", True),
        ("FICT@-*.SLDPRT", "FICTA-1.SLDPRT", False),
        ("*", "*", True),
        ("*", "FICT", False),
    ],
)
def test_without_wildcards_at_and_star_are_literal(pattern: str, text: str, expected: bool) -> None:
    """`part_number.pattern` never learnt `@` or `*`: they are characters there."""
    assert name_matches(pattern, text, wildcards=False) is expected


def test_part_number_matches_is_the_convention() -> None:
    assert part_number_matches("FICT-####.SLD???", "FICT-1234.SLDPRT")
    assert not part_number_matches("FICT-@###.SLD???", "FICT-A234.SLDPRT")


# --- the shapes' vocabulary ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("FICT@###", "FICTA123", True),
        ("FICT@###", "FICTz123", True),
        ("FICT@###", "FICT1123", False),
        ("FICT@###", "FICT-123", False),
        ("#####@###", "12345A678", True),
        ("#####@###", "12345A67", False),
        ("#####@###", "12345AB678", False),
    ],
)
def test_at_is_one_letter_and_never_a_digit(pattern: str, text: str, expected: bool) -> None:
    assert name_matches(pattern, text, wildcards=True) is expected


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("FICT-*", "FICT-", True),
        ("FICT-*", "FICT-a long run of 40 characters, spaces too", True),
        ("*-FICT", "-FICT", True),
        ("@@*##", "AB12", True),
        ("@@*##", "AB-anything-12", True),
        ("@@*##", "AB-anything-1", False),
        ("FICT*X*", "FICT_M6X20_STEEL", True),
    ],
)
def test_star_is_any_run_the_empty_run_included(pattern: str, text: str, expected: bool) -> None:
    assert name_matches(pattern, text, wildcards=True) is expected


@pytest.mark.parametrize(
    ("pattern", "text"),
    [("FICT#", "FICT12"), ("FICT#", "XFICT1"), ("FICT*", "XFICT"), ("?", "")],
)
def test_the_match_is_whole_string(pattern: str, text: str) -> None:
    assert not name_matches(pattern, text, wildcards=True)


def test_the_match_ignores_case_on_both_sides() -> None:
    assert name_matches("fict-@#", "FICT-Q7", wildcards=True)
    assert name_matches("FICT-@#", "fict-q7", wildcards=True)


@pytest.mark.parametrize("character", [".", "+", "(", ")", "[", "]", "{", "}", "^", "$", "|", "\\"])
def test_every_other_character_is_literal(character: str) -> None:
    """The owner writes no regular expression: a metacharacter is only itself."""
    pattern = f"FICT{character}#"

    assert name_matches(pattern, f"FICT{character}1", wildcards=True)
    assert not name_matches(pattern, "FICTX1", wildcards=True)


def test_an_empty_pattern_or_text_matches_nothing() -> None:
    assert not name_matches("", "FICT", wildcards=True)
    assert not name_matches("*", "", wildcards=True)


# --- property names ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    ["FICT Part Ref", "FICT PartRef", "fict part ref", "FICTPARTREF", " FICT  Part\tRef "],
)
def test_one_property_spelled_with_and_without_its_spaces_is_one_key(spelling: str) -> None:
    assert property_key(spelling) == property_key("FICT Part Ref")


def test_different_properties_keep_different_keys() -> None:
    assert property_key("FICT Part Ref") != property_key("FICT Part Refs")
    assert property_key("FICT Part, Ref") != property_key("FICT Part Ref")


def test_a_blank_name_is_the_empty_key() -> None:
    assert property_key("   ") == ""
