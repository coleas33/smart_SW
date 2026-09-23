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
- **selective**: entity ids, SOLIDWORKS names and the generic vocabulary pass through, because
  the checks read them - but not in a path, a name or a property key or value, which are
  strict: there every word is scrambled, and scrambled the same way everywhere else;
- **fictional**: every letter it writes comes from the committed syllable table, and every
  path lands under `C:\\FictionalVault\\`.

No test here carries a recorded string: every input below is invented.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

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


def test_every_word_of_a_property_key_is_scrambled_generic_or_not() -> None:
    scrambled = FictionalMap().properties({"Part Number, ZEPHYRCO": "914-55732"})

    [key] = scrambled
    assert not set(WORD.findall(key)) & {"Part", "Number", "ZEPHYRCO"}
    assert classes(key) == classes("Part Number, ZEPHYRCO")


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


def test_property_keys_and_values_are_both_strict() -> None:
    fmap = FictionalMap()

    scrambled = fmap.properties({"Author": "Quentin Oddleby", "Review Status": "Open Review"})

    keys = list(scrambled)
    assert "Author" not in keys and "Review Status" not in keys
    values = " ".join(scrambled.values())
    assert not set(WORD.findall(values)) & {"Quentin", "Oddleby", "Open", "Review"}
    [status] = [key for key in keys if " " in key]
    assert scrambled[status].split()[1] == status.split()[0], "one word, one output"


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


# --- paths reveal no vault layout, names no supplier naming (owner review, 2026-09-23) --------

FOLDERED = "E:\\Zephyr Vault\\1_ARCHIVE\\_HARDWARE\\METRIC\\PURCHASED PARTS\\V3 Bolts\\x.SLDPRT"


def folders_of(path: str) -> list[str]:
    """The folder segments of a scrambled path: between the fictional root and the file."""
    return path[len(FICTIONAL_ROOT) :].split("\\")[:-1]


def test_every_folder_segment_is_scrambled_even_when_its_words_are_generic() -> None:
    scrambled = FictionalMap().path(FOLDERED)

    original = FOLDERED.split("\\")[2:-1]
    for before, after in zip(original, folders_of(scrambled), strict=True):
        assert after != before
        assert len(after) == len(before)
        assert classes(after) == classes(before)
        assert not set(WORD.findall(after)) & set(WORD.findall(before)), (before, after)


def test_short_digits_in_a_folder_change_and_stay_digits() -> None:
    first = folders_of(FictionalMap().path(FOLDERED))[0]

    assert first[0].isdigit() and first[0] != "1"
    assert first[1] == "_"


def test_one_folder_maps_the_same_way_in_every_path() -> None:
    fmap = FictionalMap()

    one = fmap.path("E:\\Vault\\_HARDWARE\\METRIC\\a1.SLDPRT")
    two = fmap.path("E:\\Vault\\_HARDWARE\\METRIC\\b2.SLDPRT")

    assert folders_of(one) == folders_of(two)


def test_a_folder_word_is_scrambled_wherever_else_it_appears_later() -> None:
    """Once a word is a folder, no text may keep it; `package` finds folders before it maps."""
    fmap = FictionalMap()
    folder = folders_of(fmap.path("E:\\Vault\\HARDWARE\\a.SLDPRT"))[0]

    assert fmap.text("HARDWARE, METRIC") == f"{folder}, METRIC"


def test_the_file_stem_keeps_sizes_and_scrambles_head_and_finish_codes() -> None:
    fmap = FictionalMap()

    stem = fmap.path("E:\\Vault\\HW\\SHC_M8-1.25X16_ST_MA.SLDPRT").rsplit("\\", 1)[1]

    assert stem.endswith(".SLDPRT")
    head, size, finish, coating = stem[: -len(".SLDPRT")].split("_")
    assert size == "M8-1.25X16"
    assert (head, finish, coating) != ("SHC", "ST", "MA")
    assert classes(head + finish + coating) == "UUUUUUU"


@pytest.mark.parametrize("code", ["BHT", "FHT", "SHC", "SHCS", "BHCS", "FHCS", "FHTS", "MMC"])
def test_head_codes_and_supplier_codes_are_never_kept(code: str) -> None:
    assert not is_allowed_token(code)
    assert code not in FictionalMap().text(f"{code}_M3-0.5X4_ZN")


def test_a_generic_dowel_description_keeps_its_size() -> None:
    scrambled = FictionalMap().text("DOWEL PIN, 3MM X 18MM LG, SS, QRZ, 44817K212")

    assert "3MM X 18MM" in scrambled
    assert "QRZ" not in scrambled and "44817K212" not in scrambled


def test_a_component_name_and_its_file_stem_agree() -> None:
    name = "DOWEL PIN, 3MM X 18MM, QRZ, 44817K212"
    raw = {
        "documents": [
            {"path": f"E:\\Vault\\HW\\{name}.SLDPRT", "file_name": f"{name}.SLDPRT"},
        ],
        "components": [{"name": f"{name}-2", "full_path": f"Top-1/{name}-2"}],
    }

    package = FictionalMap().package(raw)

    stem = package["documents"][0]["file_name"][: -len(".SLDPRT")]
    assert package["documents"][0]["path"].endswith("\\" + stem + ".SLDPRT")
    assert package["components"][0]["name"] == stem + "-2"
    assert package["components"][0]["full_path"].endswith("/" + stem + "-2")
    assert "DOWEL" not in stem, "a file stem is a path segment: its words are scrambled"
    assert "3MM X 18MM" in stem, "sizes are generic and kept"


def test_a_supplier_code_next_to_a_catalogue_number_is_strict_even_when_generic() -> None:
    from tests.support.scramble import strict_tokens

    found = strict_tokens({"description": "SCREW, ISO, 44817K212"})

    assert "ISO" in found
    assert "ISO" not in FictionalMap(strict=found).text("per ISO, 44817K212 and ISO 2768")


def test_strict_tokens_leave_sizes_short_digits_and_single_letters_alone() -> None:
    from tests.support.scramble import strict_tokens

    found = strict_tokens({"file_name": "SHC_M8-1.25X16_ST_MA #8 X.SLDPRT"})

    assert {"SHC", "ST", "MA"} <= found
    assert not found & {"M8", "1", "25X16", "8", "X", "SLDPRT"}


def test_a_path_inside_a_persist_ref_has_its_folders_scrambled() -> None:
    fmap = FictionalMap()
    ref = encoded(b"\x01", utf16("E:\\Vault\\_HARDWARE\\METRIC\\q.SLDPRT"), b"\x02")

    text = base64.b64decode(fmap.persist_ref(ref)).decode("latin-1")

    assert "M\x00E\x00T\x00R\x00I\x00C" not in text
    assert "_\x00H\x00A\x00R\x00D" not in text


def test_path_values_are_the_path_fields_and_the_paths_inside_persist_refs() -> None:
    from tests.support.scramble import path_values

    ref = encoded(b"\x01", utf16("E:\\Vault\\HW\\q.SLDPRT"), b"\x02")
    node = {
        "documents": [{"path": "E:\\Vault\\a.SLDPRT", "file_name": "a.SLDPRT"}],
        "components": [{"full_path": "Top-1/a-1", "persist_ref": ref, "name": "a-1"}],
        "manifest": {"entries": [{"vault_path": "E:\\Vault\\b.SLDPRT"}]},
        "gaps": [{"reason": "E:\\Vault\\c.SLDPRT is not open"}],
    }

    assert sorted(path_values(node)) == sorted(
        [
            "E:\\Vault\\a.SLDPRT",
            "a.SLDPRT",
            "Top-1/a-1",
            "E:\\Vault\\HW\\q.SLDPRT",
            "E:\\Vault\\b.SLDPRT",
        ]
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("E:\\Vault\\a.b\\914-55732.SLDPRT", ("E:\\Vault\\a.b\\914-55732", "SLDPRT")),
        ("Top-1/pin.v2-1", ("Top-1/pin.v2-1", None)),
        ("E:\\Vault\\v1.2\\notes", ("E:\\Vault\\v1.2\\notes", None)),
        ("914-55732.SLDASM", ("914-55732", "SLDASM")),
    ],
)
def test_split_extension_takes_a_file_type_off_the_last_segment_only(
    value: str, expected: tuple[str, str | None]
) -> None:
    from tests.support.scramble import split_extension

    assert split_extension(value) == expected


def test_folders_of_a_path_are_every_segment_but_the_file() -> None:
    from tests.support.scramble import folders_of

    assert folders_of("E:\\Zephyr Vault\\HW\\M8\\a.SLDPRT") == ["Zephyr Vault", "HW", "M8"]
    assert folders_of("\\\\server\\share\\a.SLDPRT") == ["server", "share"]
    assert folders_of("a.SLDPRT") == []


def test_the_denylist_round_trips_its_tokens_and_its_folders(tmp_path: Path) -> None:
    from tests.support.scramble import read_denylist, write_denylist

    path = tmp_path / "SwReview" / "fixture-denylist.txt"

    write_denylist(path, {"Quentin", "Oddleby"}, {"Zephyr Vault", "V3 Bolts"})

    assert read_denylist(path) == ({"Quentin", "Oddleby"}, {"Zephyr Vault", "V3 Bolts"})


def test_the_denylist_lives_under_local_app_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.support.scramble import denylist_path

    monkeypatch.setenv("LOCALAPPDATA", "Q:\\Local")

    assert denylist_path() == Path("Q:\\Local") / "SwReview" / "fixture-denylist.txt"


def test_the_reviewers_own_sentences_are_removed_before_a_leak_check() -> None:
    """The hole check's own words `(MMC, LMC)` mean a material condition, not a supplier."""
    from swreview.checks.hole_alignment import EXCLUDED_EFFECTS
    from tests.support.scramble import without_reviewer_text

    sentence = EXCLUDED_EFFECTS[0]
    assert "MMC" in sentence

    assert "MMC" not in without_reviewer_text(f"excluded: {sentence}; bought from MMC")[:-4]
    assert without_reviewer_text("bought from MMC").endswith("MMC")


def test_the_folder_names_of_a_package_are_collected_for_the_local_denylist() -> None:
    from tests.support.scramble import folder_names

    raw = {
        "documents": [{"path": "E:\\Zephyr Vault\\_HARDWARE\\METRIC\\a.SLDPRT"}],
        "manifest": {"entries": [{"vault_path": "E:\\Zephyr Vault\\V3 Bolts\\b.SLDPRT"}]},
    }

    assert folder_names(raw) == {"Zephyr Vault", "_HARDWARE", "METRIC", "V3 Bolts"}


# --- property keys and values are strict (2026-09-23) ---------------------------------------


def test_a_property_word_is_scrambled_the_same_way_in_a_gap_reason_and_a_configuration() -> None:
    raw = {
        "documents": [
            {
                "custom_properties": {"Review Status": "Open"},
                "config_properties": {"Open": {"Review Status": "Open"}},
                "configurations": ["Open"],
            }
        ],
        "gaps": [{"reason": "Review Status is open", "kind": "not_extracted"}],
    }

    package = FictionalMap().package(raw)

    document = package["documents"][0]
    [(key, value)] = document["custom_properties"].items()
    first, second = key.split()
    assert package["gaps"][0]["reason"] == f"{first} {second} is open"
    assert document["configurations"] == [value]
    assert document["config_properties"] == {value: {key: value}}
    assert package["gaps"][0]["kind"] == "not_extracted", "structure stays verbatim"


def test_a_property_word_is_strict_in_the_recorded_arguments_too() -> None:
    from tests.support.scramble import property_tokens

    raw = {"documents": [{"custom_properties": {"Review Status": "Open"}}]}
    fmap = FictionalMap(strict=property_tokens(raw))

    key = next(iter(fmap.package(raw)["documents"][0]["custom_properties"]))
    arguments = fmap.arguments({"why": "the Review Status is not set"})

    assert arguments["why"] == f"the {key} is not set"


def test_a_solidworks_link_keeps_its_head_and_scrambles_the_configuration_and_document() -> None:
    value = '"SW-Mass@@Default@Brakewell_Template"'

    scrambled = FictionalMap().property_text(value)

    assert scrambled.startswith('"SW-Mass@@') and scrambled.endswith('"')
    assert scrambled.count("@") == 3
    assert not set(WORD.findall(scrambled)) & {"Default", "Brakewell", "Template"}


def test_a_link_head_that_is_not_solidworks_vocabulary_is_scrambled() -> None:
    assert "Zephyrco" not in FictionalMap().property_text('"SW-Zephyrco@part"')


@pytest.mark.parametrize("value", ["2026-04-16", "12.5", "3/8", "+0.007\r\n+0.018", "cmp:0003"])
def test_a_property_value_of_numbers_dates_or_an_id_is_kept_whole(value: str) -> None:
    assert FictionalMap().property_text(value) == value


def test_sizes_short_numbers_and_single_characters_in_a_property_are_kept() -> None:
    scrambled = FictionalMap().property_text("Bolt M8 x 3MM, 12 pcs")

    assert scrambled.split()[1:5] == ["M8", "x", "3MM,", "12"]
    assert "Bolt" not in scrambled and "pcs" not in scrambled


def test_a_placeholder_value_is_scrambled_and_keeps_its_punctuation() -> None:
    scrambled = FictionalMap().property_text(" - none -")

    assert "none" not in scrambled
    assert classes(scrambled) == classes(" - none -")


def test_a_word_the_profile_names_is_kept_in_any_case_everywhere() -> None:
    fmap = FictionalMap(public={"Code", "Blurb"})

    scrambled = fmap.properties({"WIDGET CODE": "blurb text"})

    [(key, value)] = scrambled.items()
    assert key.endswith(" CODE") and not key.startswith("WIDGET")
    assert value.startswith("blurb ") and "text" not in value
    assert fmap.text("the code") == "the code"


def test_a_profile_word_that_is_a_folder_word_is_still_scrambled() -> None:
    raw = {
        "documents": [
            {"path": "E:\\Vault\\Blurb\\a.SLDPRT", "custom_properties": {"Blurb": "x"}},
        ]
    }

    package = FictionalMap(public={"blurb"}).package(raw)

    assert "Blurb" not in package["documents"][0]["custom_properties"]


def test_a_replacement_of_three_letters_or_more_is_never_generic_vocabulary() -> None:
    """A strict generic word must not land on another: the hygiene test could not tell."""
    from tests.support.scramble import ALLOWED_WORDS, letters

    words = sorted(word for word in ALLOWED_WORDS if letters(word) >= 3)
    fmap = FictionalMap(strict=words)

    readable = [(word, fmap.token(word)) for word in words if is_allowed_token(fmap.token(word))]

    assert readable == []


def test_property_strings_are_the_keys_and_values_of_both_maps_not_configuration_names() -> None:
    from tests.support.scramble import property_strings

    node = {
        "documents": [
            {
                "custom_properties": {"Author": "Quentin"},
                "config_properties": {"AsMade": {"Finish": "Blue"}},
                "material": "Brass",
            }
        ]
    }

    assert sorted(property_strings(node)) == ["Author", "Blue", "Finish", "Quentin"]


def test_strict_property_words_leave_out_the_kept_pieces() -> None:
    from tests.support.scramble import strict_property_words

    words = strict_property_words('"SW-Mass@@Default@Tpl" M8 12 x', frozenset({"tpl"}))

    assert words == ["Default"]
    assert strict_property_words("2026-04-16") == []


def test_profile_words_are_the_profiles_names_and_values_and_never_its_folders(
    tmp_path: Path,
) -> None:
    import yaml

    from tests.support.scramble import profile_words

    profile = {
        "version": 1,
        "vault_root": "Q:/Brakewell Vault",
        "library": {
            "skip_prefixes": ["_hardware/"],
            "sketch_exempt_prefixes": [],
            "one_mate_prefixes": [],
            "two_mate_prefixes": ["_hardware/bolts/"],
        },
        "data_card": {"properties": ["Widget Code", "Blurb"]},
        "part_number": {"pattern": "ZP-###.SLD???"},
        "revision": {
            "property": "RevTag",
            "initial": "FRESH",
            "header_text": "CHANGES",
            "cell": {"row_from_end": 0, "column": 1},
        },
        "material": {"configuration": "AsMade"},
        "export_control": {"phrase": "ZEPHYR-ONLY"},
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile), encoding="utf-8")

    words = profile_words(path)

    assert words == {
        "widget",
        "code",
        "blurb",
        "zp",
        "sld",
        "revtag",
        "fresh",
        "changes",
        "asmade",
        "zephyr",
        "only",
    }
