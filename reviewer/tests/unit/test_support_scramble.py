"""The fictional-string map the replay fixtures are generated through (008 T009, research R2.10).

The committed fixtures are shaped like recorded runs whose packages carry real document paths,
people and company names. `tests/support/scramble.FictionalMap` replaces every identifying
string with a fictional one, and these tests pin the properties the generator and the checks
rely on:

- **deterministic** with no secret and no output derived from content: two fresh maps fed the
  same strings in the same order agree, because outputs are assigned in first-seen order;
- **shape-keeping**: length and character class survive (a digit stays a digit, an upper-case
  letter an upper-case letter, punctuation is kept verbatim), so a part-number convention
  still matches or still fails exactly as before;
- **consistent**: one token maps to one output everywhere, so a file stem, a component name
  and a part-number property carrying the same token still agree;
- **selective**: entity ids, SOLIDWORKS names, the generic vocabulary and property keys pass
  through, because the checks read them;
- **fictional**: every letter it writes comes from the committed syllable table, and every
  path lands under `C:\\FictionalVault\\`.

No test here carries a recorded string: every input below is invented.
"""

from __future__ import annotations

import base64
import re

import pytest

from tests.support.scramble import (
    FICTIONAL_ROOT,
    SYLLABLES,
    FictionalMap,
    is_allowed_token,
)

WORD = re.compile(r"[A-Za-z0-9]+")


def classes(text: str) -> str:
    """One letter per character: D digit, U upper, L lower, and punctuation as itself."""
    return "".join(
        "D" if c.isdigit() else "U" if c.isupper() else "L" if c.islower() else c for c in text
    )


def letters_from_table(text: str) -> bool:
    """Whether the letters of `text`, lower-cased, split into table syllables (last may be cut)."""
    letters = "".join(c for c in text if c.isalpha()).lower()
    pairs = [letters[i : i + 2] for i in range(0, len(letters), 2)]
    whole = [pair for pair in pairs if len(pair) == 2]
    tail = [pair for pair in pairs if len(pair) == 1]
    return all(pair in SYLLABLES for pair in whole) and all(
        any(syllable.startswith(t) for syllable in SYLLABLES) for t in tail
    )


INVENTED = [
    "ZEPHYRCO-99 MOUNTING PLATE",
    "Quentin Oddleby",
    "914-55732",
    "914-55732-2",
    "PRJ_4471_OSPREY",
    "Brakewell housing, rev QX",
]


# --- determinism -----------------------------------------------------------------------


def test_two_fresh_maps_fed_the_same_strings_agree() -> None:
    first, second = FictionalMap(), FictionalMap()

    assert [first.text(s) for s in INVENTED] == [second.text(s) for s in INVENTED]


def test_the_output_depends_on_first_seen_order_not_on_the_content() -> None:
    """Two different names of one shape, each first in a fresh map, get the same output."""
    assert FictionalMap().text("Quentin") == FictionalMap().text("Wendell")


def test_the_second_token_differs_from_the_first_of_the_same_shape() -> None:
    fmap = FictionalMap()

    assert fmap.text("Quentin") != fmap.text("Wendell")


def test_the_same_input_always_maps_to_the_same_output() -> None:
    fmap = FictionalMap()
    once = fmap.text("Quentin Oddleby")

    fmap.text("something else entirely")

    assert fmap.text("Quentin Oddleby") == once


# --- shape --------------------------------------------------------------------------------


@pytest.mark.parametrize("value", INVENTED)
def test_length_and_character_class_are_kept(value: str) -> None:
    scrambled = FictionalMap().text(value)

    assert len(scrambled) == len(value)
    assert classes(scrambled) == classes(value)


def test_an_identifying_token_is_replaced() -> None:
    scrambled = FictionalMap().text("Quentin Oddleby, ZEPHYRCO")

    assert "Quentin" not in scrambled
    assert "Oddleby" not in scrambled
    assert "ZEPHYRCO" not in scrambled


def test_a_token_is_consistent_across_a_stem_a_name_and_a_property() -> None:
    fmap = FictionalMap()

    stem = fmap.text("914-55732.SLDPRT")
    instance = fmap.text("914-55732-2")
    part_number = fmap.text("914-55732")

    assert stem == part_number + ".SLDPRT"
    assert instance == part_number + "-2"
    assert part_number != "914-55732"


def test_two_different_tokens_never_share_an_output() -> None:
    fmap = FictionalMap()
    outputs = {fmap.text(f"Widget{index:03d}x") for index in range(300)}

    assert len(outputs) == 300


def test_a_word_the_caller_keeps_passes_through_everywhere() -> None:
    """A package's own SOLIDWORKS type names are vocabulary, wherever else they are quoted."""
    fmap = FictionalMap(keep={"XyzFeat"})

    assert fmap.text("Skipped feature types: XyzFeat x3, Qorvath x1").startswith(
        "Skipped feature types: XyzFeat x3, "
    )
    assert "Qorvath" not in fmap.text("Qorvath")


def test_no_output_is_a_reserved_string() -> None:
    reserved = frozenset({FictionalMap().text("Quentin")})

    assert FictionalMap(reserved=reserved).text("Quentin") not in reserved


def test_every_letter_written_comes_from_the_syllable_table() -> None:
    fmap = FictionalMap()
    for value in INVENTED:
        for original, new in zip(WORD.findall(value), WORD.findall(fmap.text(value)), strict=True):
            if new != original:
                assert letters_from_table(new), (original, new)


def test_a_short_digit_token_and_a_whole_number_pass_through() -> None:
    fmap = FictionalMap()

    assert fmap.value("12.5") == "12.5"
    assert fmap.value("2026-04-16") == "2026-04-16"
    assert fmap.value("+0.007\r\n+0.018") == "+0.007\r\n+0.018"
    assert fmap.text("rev 2 of 7") == "rev 2 of 7"


def test_a_copyright_or_trademark_sign_is_spelled_out() -> None:
    """The hygiene test forbids the sign itself: a vendor's notice must not survive as one."""
    scrambled = FictionalMap().text("© Zephyrco Supply®, Widgetron™")

    assert "©" not in scrambled and "®" not in scrambled and "™" not in scrambled
    assert scrambled.startswith("(c) ")


def test_a_long_number_inside_a_name_is_scrambled() -> None:
    scrambled = FictionalMap().text("BRACKET 55732")

    assert "55732" not in scrambled
    assert scrambled.startswith("BRACKET ")


def test_a_part_number_written_only_in_digits_is_scrambled_as_a_whole_value() -> None:
    scrambled = FictionalMap().value("914-55732")

    assert "914" not in scrambled and "55732" not in scrambled
    assert classes(scrambled) == "DDD-DDDDD"


def test_a_property_key_keeps_its_generic_words_and_loses_a_company_name() -> None:
    scrambled = FictionalMap().properties({"Part Number, ZEPHYRCO": "914-55732"})

    [key] = scrambled
    assert key.startswith("Part Number, ")
    assert "ZEPHYRCO" not in key


def test_a_dropped_vault_root_is_still_recorded_for_the_leak_check() -> None:
    fmap = FictionalMap()
    fmap.path("E:\\Brakewell PDM\\Jobs\\914-55732.SLDPRT")

    assert "Brakewell" in fmap.replaced


# --- what passes through ----------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "cmp:0001",
        "feat:12345",
        "int:0113",
        "Boss-Extrude1",
        "Sketch12",
        "LocalCirPattern1",
        "Cut-List-Item1",
        "swStandardAnsiMetric",
        "swMateCOINCIDENT",
        "Default",
        "SLDPRT",
        "M8 Clearance Hole1",
    ],
)
def test_ids_solidworks_names_and_generic_vocabulary_pass_through(value: str) -> None:
    assert FictionalMap().value(value) == value


def test_entity_ids_inside_prose_pass_through() -> None:
    scrambled = FictionalMap().text("Quentin checked cmp:0015 against hol:0004")

    assert scrambled.endswith("checked cmp:0015 against hol:0004")


def test_document_ids_are_mapped_to_fictional_hex_consistently() -> None:
    fmap = FictionalMap()
    document = fmap.value("doc:0a1b2c3d4e5f")
    design = fmap.value("dsn:0a1b2c3d4e5f")

    assert re.fullmatch(r"doc:[0-9a-f]{12}", document)
    assert document != "doc:0a1b2c3d4e5f"
    assert design == "dsn:" + document[4:]
    assert fmap.text("see doc:0a1b2c3d4e5f for it") == f"see {document} for it"


def test_property_keys_pass_through_and_values_do_not() -> None:
    fmap = FictionalMap()

    scrambled = fmap.properties({"Author": "Quentin Oddleby", "Material": "ALLOY STEEL"})

    assert list(scrambled) == ["Author", "Material"]
    assert "Quentin" not in scrambled["Author"]
    assert scrambled["Material"] == "ALLOY STEEL"


@pytest.mark.parametrize("token", ["the", "Clearance", "SLDASM", "Pattern", "x"])
def test_the_generic_allowlist_admits_ordinary_words(token: str) -> None:
    assert is_allowed_token(token)


@pytest.mark.parametrize("token", ["Oddleby", "ZEPHYRCO", "OSPREY", "QX"])
def test_the_generic_allowlist_refuses_invented_names(token: str) -> None:
    assert not is_allowed_token(token)


# --- paths ------------------------------------------------------------------------------


def test_a_windows_path_keeps_its_segments_its_extension_and_gets_the_fictional_root() -> None:
    original = "E:\\Brakewell PDM\\7_JOBS\\4471_OSPREY\\914-55732.SLDPRT"

    scrambled = FictionalMap().path(original)

    assert scrambled.startswith(FICTIONAL_ROOT)
    assert FICTIONAL_ROOT == "C:\\FictionalVault\\"
    assert scrambled.count("\\") == original.count("\\")
    assert scrambled.endswith(".SLDPRT")
    assert "OSPREY" not in scrambled and "Brakewell" not in scrambled


def test_a_path_stem_matches_the_same_file_name_elsewhere() -> None:
    fmap = FictionalMap()

    path = fmap.path("E:\\Vault\\Jobs\\914-55732.SLDPRT")
    name = fmap.value("914-55732.SLDPRT")

    assert path.endswith("\\" + name)


def test_a_path_with_a_single_segment_still_lands_under_the_root() -> None:
    assert FictionalMap().path("E:\\914-55732.SLDASM").startswith(FICTIONAL_ROOT)


def test_a_unc_path_lands_under_the_root() -> None:
    scrambled = FictionalMap().path("\\\\brakewell-fs\\share\\914-55732.SLDPRT")

    assert scrambled.startswith(FICTIONAL_ROOT)
    assert "brakewell" not in scrambled


def test_value_recognises_a_path() -> None:
    assert FictionalMap().value("E:\\Vault\\a.SLDPRT").startswith(FICTIONAL_ROOT)


# --- persist references ---------------------------------------------------------------------


def encoded(*parts: bytes) -> str:
    return base64.b64encode(b"".join(parts)).decode("ascii")


def utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def test_a_persist_ref_without_strings_is_unchanged() -> None:
    ref = encoded(b"hB\x00\x00\x00\x00\x00\x00\xff\xfe\xff\x00\x00\x00\x00\x00")

    assert FictionalMap().persist_ref(ref) == ref


def test_names_and_paths_inside_a_persist_ref_are_scrambled_consistently() -> None:
    fmap = FictionalMap()
    ref = encoded(
        b"\x01\x02",
        utf16("914-55732-2@ZEPHYRCO"),
        b"\x00\x07",
        utf16("E:\\Brakewell PDM\\Jobs\\914-55732.SLDPRT"),
        b"moFaceRef_c",
    )

    scrambled = base64.b64decode(fmap.persist_ref(ref))

    text = scrambled.decode("latin-1")
    assert "Z\x00E\x00P" not in text
    assert "B\x00r\x00a\x00k" not in text
    assert utf16(fmap.text("914-55732-2")) in scrambled
    assert utf16(FICTIONAL_ROOT) in scrambled
    assert fmap.persist_ref(ref) == fmap.persist_ref(ref)


def test_the_same_persist_ref_maps_to_the_same_output_in_two_maps() -> None:
    ref = encoded(b"\x05", utf16("Quentin Oddleby"), b"\x09")

    assert FictionalMap().persist_ref(ref) == FictionalMap().persist_ref(ref)


def test_a_string_that_is_not_base64_is_scrambled_as_text() -> None:
    assert "Oddleby" not in FictionalMap().persist_ref("Quentin Oddleby")


# --- the package and the recorded arguments --------------------------------------------------


def test_the_scramble_lists_name_the_package_and_argument_fields() -> None:
    from tests.support.scramble import ARGUMENT_VERBATIM_KEYS, PACKAGE_VERBATIM_KEYS

    assert {"type_name", "kind", "status", "package_id"} <= PACKAGE_VERBATIM_KEYS
    assert {"check", "bucket"} <= ARGUMENT_VERBATIM_KEYS


def test_arguments_keep_check_ids_and_scramble_prose() -> None:
    fmap = FictionalMap()
    arguments = {
        "check": "interfaces.fit",
        "bucket": "unresolved",
        "scope": {"component_ids": ["cmp:0002"], "positions": ["Quentin's bench"]},
        "reason": "The ZEPHYRCO plate doc:0a1b2c3d4e5f has no drawing",
    }

    scrambled = fmap.arguments(arguments)

    assert scrambled["check"] == "interfaces.fit"
    assert scrambled["bucket"] == "unresolved"
    assert scrambled["scope"]["component_ids"] == ["cmp:0002"]
    assert "Quentin" not in scrambled["scope"]["positions"][0]
    assert "ZEPHYRCO" not in scrambled["reason"]
    assert "doc:0a1b2c3d4e5f" not in scrambled["reason"]
    assert arguments["reason"].startswith("The ZEPHYRCO"), "the input is not mutated"


def test_the_replaced_tokens_are_recorded_for_the_denylist() -> None:
    fmap = FictionalMap()
    fmap.text("Quentin Oddleby ok")

    assert {"Quentin", "Oddleby"} <= set(fmap.replaced)
    assert "ok" not in fmap.replaced
