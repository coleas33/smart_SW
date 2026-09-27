"""The standards profile: the one schema owner, and the refusals that replace a fallback (T003).

`contracts/profile.md` is normative. Two things it says are load-bearing here and are each
measured rather than described:

- **Every key is required; every string and every list value may be empty.** A required key
  with an empty value is a deliberate statement ("we do not use this yet"); a *missing* key is
  a half-written file. Telling them apart is the difference between "this check is skipped"
  and "this profile was never finished", so a missing key is refused naming it while an empty
  string or an empty list loads.
- **There is no fallback.** No field has a default, anywhere, because a default would grade a
  document against the wrong standard and report a clean result - the worst failure a release
  gate has. `test_no_field_anywhere_in_the_schema_has_a_default` is that rule as an assertion
  rather than a promise.

The fixtures are the two fictional profiles; everything that must be malformed is hand-built
from one of them, so no test here writes a profile value of its own (FR-001, FR-002).
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from swreview.checks.standards.profile import (
    ProfileError,
    ProfileIdentity,
    ProfileInvalid,
    ProfileUnreadable,
    StandardsProfile,
    load_profile,
    load_review_profile,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE_A = FIXTURE_DIR / "profile-a.yaml"
PROFILE_B = FIXTURE_DIR / "profile-b.yaml"
FIXTURES = (PROFILE_A, PROFILE_B)

SRC = Path(__file__).resolve().parents[2] / "src" / "swreview"
EXTRACTOR = Path(__file__).resolve().parents[3] / "extractor"
OWNER = SRC / "checks" / "standards" / "profile.py"

SETTING = "StandardsProfilePath"
"""The setting the refusal must name, so an engineer knows where to look."""


def raw(path: Path) -> dict[str, Any]:
    """A fixture as plain YAML, which is what the loaded profile is compared against."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def write(tmp_path: Path, data: Any, name: str = "standards.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def dotted_paths(data: Any, prefix: str = "") -> Iterator[str]:
    """Every key of a profile mapping, `library.skip_prefixes` style, parents included."""
    for key, value in data.items():
        name = f"{prefix}{key}"
        yield name
        if isinstance(value, dict):
            yield from dotted_paths(value, f"{name}.")


def without(data: dict[str, Any], dotted: str) -> dict[str, Any]:
    copy = deepcopy(data)
    head, _, tail = dotted.partition(".")
    if tail:
        copy[head] = without(copy[head], tail)
    else:
        del copy[head]
    return copy


def replacing(data: dict[str, Any], dotted: str, value: Any) -> dict[str, Any]:
    copy = deepcopy(data)
    head, _, tail = dotted.partition(".")
    copy[head] = replacing(copy[head], tail, value) if tail else value
    return copy


PROFILE_KEYS: tuple[str, ...] = tuple(dotted_paths(raw(PROFILE_A)))
"""Every key of the schema, from the fixture rather than typed out a second time."""

STRING_FIELDS: tuple[str, ...] = (
    "vault_root",
    "part_number.pattern",
    "revision.property",
    "revision.initial",
    "revision.header_text",
    "material.configuration",
    "export_control.phrase",
    "hygiene.part_number_property",
    "hygiene.description_property",
    "drawing.drafting_standard",
    "drawing.projection",
    "drawing.dimension_unit",
    "drawing.drawing_template",
    "drawing.bom_template",
)
LIST_FIELDS: tuple[str, ...] = (
    "library.skip_prefixes",
    "library.sketch_exempt_prefixes",
    "library.one_mate_prefixes",
    "library.two_mate_prefixes",
    "data_card.properties",
    "general_tolerance.linear",
    "drawing.sheet_formats",
    # Feature 013 T013: the part_roles lists that stand alone. The switch's two value lists,
    # the distributor block and the catalogue shapes are tied to a sibling field and are
    # emptied together in `test_a_version_4_profile_with_every_signal_off_loads`.
    "part_roles.bought_prefixes",
    "part_roles.bought_folder_names",
    "part_roles.switch.bought_values",
    "part_roles.vendor_properties",
    "part_roles.catalogue_numbers.properties",
    "part_roles.custom_prefixes",
    "part_roles.bought_number_prefixes",
    "part_roles.detail_properties",
)
VERSION_2_SECTIONS: tuple[str, ...] = ("general_tolerance", "hygiene")
"""The two sections version 2 adds (feature 010 research R2.19): required on version 2,
absent on version 1."""

VERSION_3_SECTIONS: tuple[str, ...] = ("drawing",)
"""The section version 3 adds (feature 011 `contracts/profile.md` section 1): required on
version 3, absent on versions 1 and 2."""

DRAWING_KEYS: tuple[str, ...] = (
    "sheet_formats",
    "drafting_standard",
    "projection",
    "dimension_unit",
    "drawing_template",
    "bom_template",
)


VERSION_4_SECTIONS: tuple[str, ...] = ("part_roles",)
"""The section version 4 adds (feature 013 `contracts/part-roles-profile.md` section 1):
required on version 4, absent on versions 1 to 3."""


def as_version_3(data: dict[str, Any]) -> dict[str, Any]:
    """A version 4 fixture written back as the version 3 profile it extends."""
    copy = {key: value for key, value in deepcopy(data).items() if key not in VERSION_4_SECTIONS}
    copy["version"] = 3
    return copy


def as_version_2(data: dict[str, Any]) -> dict[str, Any]:
    """A version 4 fixture written back as the version 2 profile it extends.

    Edited deliberately by feature 013 T014: the fixtures moved to version 4, so version 2 is
    version 3 without its drawing section.
    """
    copy = {
        key: value
        for key, value in as_version_3(data).items()
        if key not in VERSION_3_SECTIONS
    }
    copy["version"] = 2
    return copy


def as_version_1(data: dict[str, Any]) -> dict[str, Any]:
    """A version 3 fixture written back as the version 1 profile it extends."""
    copy = {
        key: value
        for key, value in as_version_2(data).items()
        if key not in VERSION_2_SECTIONS
    }
    copy["version"] = 1
    return copy


CELL_FIELDS: tuple[str, ...] = ("revision.cell.row_from_end", "revision.cell.column")


# --- the Field rules table --------------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_a_fixture_profile_loads_field_for_field(fixture: Path) -> None:
    """Nothing is renamed, coerced away or dropped between the file and the model."""
    profile = load_profile(fixture)

    assert profile.model_dump() == raw(fixture)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_every_field_carries_the_type_the_contract_states(fixture: Path) -> None:
    profile = load_profile(fixture)

    # Edited deliberately by feature 011 T028: the fixtures moved to version 3 with the
    # drawing section (`contracts/profile.md` section 1); and by feature 013 T014: they moved
    # to version 4 with the part_roles section.
    assert profile.version == 4
    assert profile.part_roles is not None
    roles = profile.part_roles
    for field in (
        roles.bought_prefixes,
        roles.bought_folder_names,
        roles.switch.bought_values,
        roles.switch.custom_values,
        roles.vendor_properties,
        roles.distributor_block.properties,
        roles.catalogue_numbers.shapes,
        roles.catalogue_numbers.properties,
        roles.custom_prefixes,
        roles.bought_number_prefixes,
        roles.detail_properties,
    ):
        assert isinstance(field, list)
        assert all(isinstance(item, str) for item in field)
    assert isinstance(roles.switch.property, str)
    assert isinstance(roles.distributor_block.min_valued, int)
    assert profile.drawing is not None
    assert isinstance(profile.drawing.sheet_formats, list)
    assert all(isinstance(item, str) for item in profile.drawing.sheet_formats)
    for name in ("drafting_standard", "projection", "dimension_unit", "drawing_template",
                 "bom_template"):
        assert isinstance(getattr(profile.drawing, name), str), name
    assert isinstance(profile.vault_root, str)
    assert profile.general_tolerance is not None and profile.hygiene is not None
    assert isinstance(profile.general_tolerance.linear, list)
    for band in profile.general_tolerance.linear:
        assert isinstance(band.decimal_places, int)
        assert isinstance(band.plus_minus_mm, float)
    assert isinstance(profile.general_tolerance.angular_deg, float)
    assert isinstance(profile.hygiene.part_number_property, str)
    assert isinstance(profile.hygiene.description_property, str)
    for field in (
        profile.library.skip_prefixes,
        profile.library.sketch_exempt_prefixes,
        profile.library.one_mate_prefixes,
        profile.library.two_mate_prefixes,
        profile.data_card.properties,
    ):
        assert isinstance(field, list)
        assert all(isinstance(item, str) for item in field)
    assert isinstance(profile.part_number.pattern, str)
    assert isinstance(profile.revision.property, str)
    assert isinstance(profile.revision.initial, str)
    assert isinstance(profile.revision.header_text, str)
    assert isinstance(profile.revision.cell.row_from_end, int)
    assert isinstance(profile.revision.cell.column, int)
    assert isinstance(profile.material.configuration, str)
    assert isinstance(profile.export_control.phrase, str)


def test_the_two_fixtures_are_two_different_profiles() -> None:
    """The pair exists so that a value compiled into a rule cannot satisfy both (SC-005)."""
    assert load_profile(PROFILE_A).model_dump() != load_profile(PROFILE_B).model_dump()


# --- empty is valid; missing is not ------------------------------------------------------


@pytest.mark.parametrize("field", STRING_FIELDS)
def test_an_empty_string_is_a_valid_setting(tmp_path: Path, field: str) -> None:
    profile = load_profile(write(tmp_path, replacing(raw(PROFILE_A), field, "")))

    assert profile.model_dump() == replacing(raw(PROFILE_A), field, "")


@pytest.mark.parametrize("field", LIST_FIELDS)
def test_an_empty_list_is_a_valid_setting(tmp_path: Path, field: str) -> None:
    profile = load_profile(write(tmp_path, replacing(raw(PROFILE_A), field, [])))

    assert profile.model_dump() == replacing(raw(PROFILE_A), field, [])


def test_a_profile_whose_every_settable_value_is_empty_still_loads(tmp_path: Path) -> None:
    """The owner adopts the tab one setting at a time; an unfinished profile is not a lie."""
    data = raw(PROFILE_A)
    for field in STRING_FIELDS:
        data = replacing(data, field, "")
    for field in LIST_FIELDS:
        data = replacing(data, field, [])

    assert load_profile(write(tmp_path, data)).model_dump() == data


@pytest.mark.parametrize("key", PROFILE_KEYS)
def test_a_missing_key_is_refused_naming_it(tmp_path: Path, key: str) -> None:
    path = write(tmp_path, without(raw(PROFILE_A), key))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    assert key.rsplit(".", 1)[-1] in str(raised.value)
    assert str(path) in str(raised.value)


# --- the two integers --------------------------------------------------------------------


@pytest.mark.parametrize("field", CELL_FIELDS)
@pytest.mark.parametrize("value", ["", None, "two", 1.5, -1, True], ids=repr)
def test_a_revision_cell_index_that_is_not_a_whole_number_is_refused(
    tmp_path: Path, field: str, value: Any
) -> None:
    """`row_from_end` and `column` select a cell; an empty or negative one selects nothing."""
    path = write(tmp_path, replacing(raw(PROFILE_A), field, value))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    assert field.rsplit(".", 1)[-1] in str(raised.value)


@pytest.mark.parametrize("field", CELL_FIELDS)
def test_zero_is_a_valid_revision_cell_index(tmp_path: Path, field: str) -> None:
    """`row_from_end: 0` is the last row - the common case, and not a default here."""
    data = replacing(raw(PROFILE_A), field, 0)

    assert load_profile(write(tmp_path, data)).model_dump() == data


# --- unknown keys and unknown versions ---------------------------------------------------


@pytest.mark.parametrize(
    "dotted", ["nickname", "library.skip_prefix", "revision.cell.row", "data_card.property"]
)
def test_an_unknown_key_is_refused_naming_it(tmp_path: Path, dotted: str) -> None:
    """A typo in a list name must never silently disable that list."""
    path = write(tmp_path, replacing(raw(PROFILE_A), dotted, ["anything"]))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    assert dotted.rsplit(".", 1)[-1] in str(raised.value)


@pytest.mark.parametrize("version", [0, 5, 17, "4"], ids=repr)
def test_an_unknown_version_is_refused_naming_the_known_versions(
    tmp_path: Path, version: Any
) -> None:
    # Edited deliberately by feature 011 T028: 3 is a known version now, so 4 and the string
    # "3" take its place, and the refusal names all three known versions. Edited again by
    # feature 013 T014: 4 is known too, so 5 and the string "4" take its place.
    path = write(tmp_path, replacing(raw(PROFILE_A), "version", version))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    message = str(raised.value)
    assert repr(version) in message or str(version) in message
    assert "versions 1, 2, 3 and 4" in message, "the refusal names the versions this build knows"
    assert str(path) in message


# --- version 2: the general tolerance and the hygiene names (feature 010 T015) ------------


def test_a_version_1_profile_still_loads_with_neither_version_2_section(tmp_path: Path) -> None:
    """The owner's real profile is version 1 until the owner rewrites it (plan RK-7)."""
    data = as_version_1(raw(PROFILE_A))

    profile = load_profile(write(tmp_path, data))

    assert profile.version == 1
    assert (profile.general_tolerance, profile.hygiene) == (None, None)


@pytest.mark.parametrize("section", VERSION_2_SECTIONS)
def test_a_version_1_profile_carrying_a_version_2_section_is_refused_naming_it(
    tmp_path: Path, section: str
) -> None:
    data = {**as_version_1(raw(PROFILE_A)), section: raw(PROFILE_A)[section]}

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))

    assert section in str(raised.value)


@pytest.mark.parametrize("section", VERSION_2_SECTIONS)
def test_a_version_2_profile_missing_either_section_is_refused_naming_it(
    tmp_path: Path, section: str
) -> None:
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, without(as_version_2(raw(PROFILE_A)), section)))

    assert section in str(raised.value)


@pytest.mark.parametrize("section", VERSION_2_SECTIONS)
def test_a_version_2_section_written_as_null_is_refused_naming_it(
    tmp_path: Path, section: str
) -> None:
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, replacing(as_version_2(raw(PROFILE_A)), section, None)))

    assert section in str(raised.value)


# --- version 3: the drawing section (feature 011 T028, contracts/profile.md section 1) -------


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_a_version_3_profile_with_its_drawing_section_loads(tmp_path: Path, fixture: Path) -> None:
    # Edited deliberately by feature 013 T014: the fixtures are version 4, so the version 3
    # profile each extends is written back and loaded.
    profile = load_profile(write(tmp_path, as_version_3(raw(fixture))))

    assert profile.version == 3
    assert profile.part_roles is None
    assert profile.drawing is not None
    assert profile.model_dump()["drawing"] == raw(fixture)["drawing"]
    assert list(raw(fixture)["drawing"]) == list(DRAWING_KEYS)


def test_profile_a_carries_the_drawing_values_the_plate_drawing_fixture_writes() -> None:
    """Drawing A of `tests/fixtures/drawings/plate-drawing` conforms to profile A."""
    drawing = load_profile(PROFILE_A).drawing
    assert drawing is not None
    assert (drawing.projection, drawing.dimension_unit) == ("third_angle", "mm")
    assert drawing.sheet_formats == ["FICTIONAL-FORMAT-A"]
    assert drawing.drafting_standard == "FICTIONAL-STANDARD"


def test_profile_b_leaves_every_drawing_setting_empty() -> None:
    """The skipped cases of the comparison (`contracts/profile.md` section 2)."""
    drawing = load_profile(PROFILE_B).drawing
    assert drawing is not None
    assert drawing.sheet_formats == []
    assert all(
        getattr(drawing, name) == "" for name in DRAWING_KEYS if name != "sheet_formats"
    )


def test_a_version_3_profile_missing_its_drawing_section_is_refused_naming_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, without(raw(PROFILE_A), "drawing")))

    assert "drawing" in str(raised.value)


def test_a_version_3_drawing_section_written_as_null_is_refused_naming_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, replacing(raw(PROFILE_A), "drawing", None)))

    assert "drawing" in str(raised.value)


@pytest.mark.parametrize("section", VERSION_2_SECTIONS)
def test_a_version_3_profile_missing_a_version_2_section_is_refused_naming_it(
    tmp_path: Path, section: str
) -> None:
    """Version 3 also requires everything version 2 requires."""
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, without(raw(PROFILE_A), section)))

    assert section in str(raised.value)


@pytest.mark.parametrize("key", DRAWING_KEYS)
def test_a_missing_drawing_key_is_refused_naming_it(tmp_path: Path, key: str) -> None:
    path = write(tmp_path, without(raw(PROFILE_A), f"drawing.{key}"))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    assert key in str(raised.value)
    assert str(path) in str(raised.value)


@pytest.mark.parametrize(
    ("key", "value", "allowed"),
    [
        ("projection", "isometric", "first_angle, third_angle or ''"),
        ("projection", "First_Angle", "first_angle, third_angle or ''"),
        ("projection", "third angle", "first_angle, third_angle or ''"),
        ("dimension_unit", "cm", "mm, in or ''"),
        ("dimension_unit", "MM", "mm, in or ''"),
        ("dimension_unit", "inch", "mm, in or ''"),
    ],
)
def test_a_drawing_setting_outside_its_values_is_refused_naming_the_key_and_the_values(
    tmp_path: Path, key: str, value: str, allowed: str
) -> None:
    path = write(tmp_path, replacing(raw(PROFILE_A), f"drawing.{key}", value))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    message = str(raised.value)
    assert f"drawing.{key}" in message
    assert repr(value) in message
    assert allowed in message


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("projection", None),
        ("projection", 3),
        ("dimension_unit", None),
        ("drafting_standard", None),
        ("drawing_template", 7),
        ("bom_template", ["a"]),
        ("sheet_formats", "FICTIONAL-FORMAT-A"),
        ("sheet_formats", None),
        ("sheet_formats", [1]),
    ],
    ids=repr,
)
def test_a_drawing_setting_of_the_wrong_type_is_refused_naming_it(
    tmp_path: Path, key: str, value: Any
) -> None:
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, replacing(raw(PROFILE_A), f"drawing.{key}", value)))

    assert key in str(raised.value)


def test_a_repeated_sheet_format_is_refused_naming_it(tmp_path: Path) -> None:
    data = replacing(
        raw(PROFILE_A), "drawing.sheet_formats", ["FICTIONAL-FORMAT-A", "FICTIONAL-FORMAT-A"]
    )

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))

    message = str(raised.value)
    assert "sheet_formats" in message
    assert "'FICTIONAL-FORMAT-A'" in message


def test_the_general_tolerance_is_not_restated_in_the_drawing_section(tmp_path: Path) -> None:
    """`drawing.general_tolerance` is an unknown key, refused like any other (FR-045)."""
    data = raw(PROFILE_A)
    data["drawing"]["general_tolerance"] = data["general_tolerance"]

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))

    assert "general_tolerance" in str(raised.value)


def test_every_drawing_setting_may_be_empty(tmp_path: Path) -> None:
    data = replacing(
        raw(PROFILE_A),
        "drawing",
        {key: [] if key == "sheet_formats" else "" for key in DRAWING_KEYS},
    )

    profile = load_profile(write(tmp_path, data))

    assert profile.model_dump()["drawing"] == data["drawing"]


def test_a_version_2_profile_still_loads_with_no_drawing_section(tmp_path: Path) -> None:
    profile = load_profile(write(tmp_path, as_version_2(raw(PROFILE_A))))

    assert profile.version == 2
    assert profile.drawing is None
    assert profile.general_tolerance is not None and profile.hygiene is not None


def test_a_version_1_profile_has_no_drawing_section_either(tmp_path: Path) -> None:
    profile = load_profile(write(tmp_path, as_version_1(raw(PROFILE_A))))

    assert (profile.version, profile.drawing) == (1, None)


@pytest.mark.parametrize("version", [1, 2])
def test_a_drawing_section_on_an_earlier_version_is_refused_naming_it(
    tmp_path: Path, version: int
) -> None:
    earlier = as_version_1 if version == 1 else as_version_2
    data = {**earlier(raw(PROFILE_A)), "drawing": raw(PROFILE_A)["drawing"]}

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))

    message = str(raised.value)
    assert "drawing" in message
    assert f"version {version}" in message


def test_the_known_versions_are_one_to_four() -> None:
    # Edited deliberately by feature 013 T014: version 4 adds part_roles.
    from swreview.checks.standards.profile import KNOWN_VERSIONS, PROFILE_VERSION

    assert KNOWN_VERSIONS == (1, 2, 3, 4)
    assert PROFILE_VERSION == 4


# --- version 4: part_roles (feature 013 T013, contracts/part-roles-profile.md sections 1, 3) --

PART_ROLES_LISTS: tuple[str, ...] = (
    "part_roles.bought_prefixes",
    "part_roles.bought_folder_names",
    "part_roles.switch.bought_values",
    "part_roles.switch.custom_values",
    "part_roles.vendor_properties",
    "part_roles.distributor_block.properties",
    "part_roles.catalogue_numbers.shapes",
    "part_roles.catalogue_numbers.properties",
    "part_roles.custom_prefixes",
    "part_roles.bought_number_prefixes",
    "part_roles.detail_properties",
)
"""Every list of the section; each refuses a blank entry by its position."""

LEAK = "FICTLEAK"
"""A marker no refusal may quote: a refusal names the field and the position only."""

ALL_SIGNALS_OFF: dict[str, Any] = {
    "bought_prefixes": [],
    "bought_folder_names": [],
    "switch": {"property": "", "bought_values": [], "custom_values": []},
    "vendor_properties": [],
    "distributor_block": {"properties": [], "min_valued": 0},
    "catalogue_numbers": {"shapes": [], "properties": []},
    "custom_prefixes": [],
    "bought_number_prefixes": [],
    "detail_properties": [],
}
"""The section with every signal turned off: what the upgrade helper writes."""


def refusal(tmp_path: Path, data: dict[str, Any]) -> str:
    """The loader's refusal of `data`, which must be refused."""
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))
    return str(raised.value)


def with_roles(**fields: Any) -> dict[str, Any]:
    """Profile A with `part_roles` fields replaced, nested keys written `switch__property`."""
    data = raw(PROFILE_A)
    for name, value in fields.items():
        data = replacing(data, "part_roles." + name.replace("__", "."), value)
    return data


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_a_version_4_profile_with_its_part_roles_section_loads(fixture: Path) -> None:
    profile = load_profile(fixture)

    assert profile.version == 4
    assert profile.part_roles is not None
    assert profile.model_dump()["part_roles"] == raw(fixture)["part_roles"]


def test_a_version_4_profile_with_every_signal_off_loads(tmp_path: Path) -> None:
    data = replacing(raw(PROFILE_A), "part_roles", ALL_SIGNALS_OFF)

    assert load_profile(write(tmp_path, data)).model_dump()["part_roles"] == ALL_SIGNALS_OFF


@pytest.mark.parametrize("version", [1, 2, 3])
def test_every_earlier_version_still_loads_without_part_roles(
    tmp_path: Path, version: int
) -> None:
    earlier = {1: as_version_1, 2: as_version_2, 3: as_version_3}[version]

    profile = load_profile(write(tmp_path, earlier(raw(PROFILE_A))))

    assert (profile.version, profile.part_roles) == (version, None)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_part_roles_on_an_earlier_version_is_refused_naming_it(
    tmp_path: Path, version: int
) -> None:
    earlier = {1: as_version_1, 2: as_version_2, 3: as_version_3}[version]
    data = {**earlier(raw(PROFILE_A)), "part_roles": raw(PROFILE_A)["part_roles"]}

    message = refusal(tmp_path, data)

    assert "part_roles (a version 4 section)" in message
    assert f"version {version}" in message


def test_a_version_4_profile_without_part_roles_is_refused_naming_it(tmp_path: Path) -> None:
    assert "part_roles" in refusal(tmp_path, without(raw(PROFILE_A), "part_roles"))
    assert "part_roles" in refusal(tmp_path, replacing(raw(PROFILE_A), "part_roles", None))


@pytest.mark.parametrize("field", PART_ROLES_LISTS)
def test_a_blank_entry_is_refused_by_its_position(tmp_path: Path, field: str) -> None:
    data = raw(PROFILE_A)
    head, _, leaf = field.rpartition(".")
    section = data
    for key in head.split("."):
        section = section[key]
    entries = [*section[leaf], "   "]
    if field == "part_roles.distributor_block.properties":
        section["min_valued"] = 1
    section[leaf] = entries

    message = refusal(tmp_path, data)

    assert leaf in message
    assert f" {len(entries)} is blank" in message


@pytest.mark.parametrize("name", [f"{LEAK}/Purchased", f"{LEAK}\\Purchased", "/"])
def test_a_folder_name_holding_a_separator_is_refused(tmp_path: Path, name: str) -> None:
    message = refusal(tmp_path, with_roles(bought_folder_names=["FICT Supplied", name]))

    assert "folder name 2 holds a path separator; name one folder" in message
    assert LEAK not in message


@pytest.mark.parametrize("shape", ["*", "?", "@", "**", "@@*", "*?@", " * "])
def test_a_shape_made_only_of_wildcards_is_refused(tmp_path: Path, shape: str) -> None:
    message = refusal(tmp_path, with_roles(catalogue_numbers__shapes=["FICT-####", shape]))

    assert "shape 2 would match every token" in message


def test_a_shape_with_one_literal_character_loads(tmp_path: Path) -> None:
    data = with_roles(catalogue_numbers__shapes=["*-*", "#", "@@?#"])

    assert load_profile(write(tmp_path, data)).part_roles is not None


def test_a_switch_property_without_values_is_refused(tmp_path: Path) -> None:
    message = refusal(tmp_path, with_roles(switch__bought_values=[], switch__custom_values=[]))

    assert "switch.property needs at least one bought or custom value" in message


def test_switch_values_without_a_property_are_refused(tmp_path: Path) -> None:
    message = refusal(tmp_path, with_roles(switch__property=""))

    assert "switch values need switch.property" in message


def test_a_switch_with_only_one_kind_of_value_loads(tmp_path: Path) -> None:
    """The owner may mark only purchased parts, or only built ones."""
    for kind in ("bought_values", "custom_values"):
        data = with_roles(**{f"switch__{kind}": []})
        assert load_profile(write(tmp_path, data)).part_roles is not None


def test_a_value_in_both_switch_lists_is_refused(tmp_path: Path) -> None:
    data = with_roles(switch__bought_values=[f"{LEAK}One"], switch__custom_values=[f" {LEAK}ONE "])

    message = refusal(tmp_path, data)

    assert "custom value 1 repeats bought value 1" in message
    assert LEAK.casefold() not in message.casefold()


def test_a_switch_value_listed_twice_is_refused(tmp_path: Path) -> None:
    data = with_roles(switch__bought_values=[f"{LEAK}One", f"{LEAK}one"])

    message = refusal(tmp_path, data)

    assert "entry 2 repeats entry 1" in message
    assert LEAK.casefold() not in message.casefold()


@pytest.mark.parametrize(
    ("properties", "min_valued", "expected"),
    [
        ([], 1, "min_valued must be 0 when the block names no properties"),
        (["FICT A", "FICT B"], 0, "min_valued must be from 1 to the number of properties (2)"),
        (["FICT A", "FICT B"], 3, "min_valued must be from 1 to the number of properties (2)"),
    ],
)
def test_a_distributor_count_that_does_not_fit_the_block_is_refused(
    tmp_path: Path, properties: list[str], min_valued: int, expected: str
) -> None:
    data = with_roles(distributor_block={"properties": properties, "min_valued": min_valued})

    assert expected in refusal(tmp_path, data)


def test_a_negative_distributor_count_is_refused(tmp_path: Path) -> None:
    data = with_roles(distributor_block={"properties": ["FICT A"], "min_valued": -1})

    assert "min_valued" in refusal(tmp_path, data)


def test_catalogue_properties_without_a_shape_are_refused(tmp_path: Path) -> None:
    message = refusal(tmp_path, with_roles(catalogue_numbers__shapes=[]))

    assert "catalogue_numbers.properties need at least one shape" in message


@pytest.mark.parametrize(
    ("custom", "bought"),
    [
        ([f"{LEAK}-1"], [f"{LEAK}-1"]),
        ([f"{LEAK}-"], [f"{LEAK}-8"]),
        ([f"{LEAK}-8"], [f"{LEAK}-"]),
        ([f"{LEAK}-1"], [f"{LEAK.lower()}-1"]),
    ],
    ids=["equal", "custom-is-the-start", "bought-is-the-start", "case"],
)
def test_overlapping_custom_and_bought_prefixes_are_refused(
    tmp_path: Path, custom: list[str], bought: list[str]
) -> None:
    data = with_roles(custom_prefixes=["FICT-2", *custom], bought_number_prefixes=bought)

    message = refusal(tmp_path, data)

    assert "custom prefix 2 overlaps bought prefix 1" in message
    assert LEAK.casefold() not in message.casefold()


def test_prefixes_that_only_share_a_start_load(tmp_path: Path) -> None:
    """`FICT-1` and `FICT-9` share `FICT-` but neither starts the other: no number votes both."""
    data = with_roles(custom_prefixes=["FICT-1"], bought_number_prefixes=["FICT-9"])

    assert load_profile(write(tmp_path, data)).part_roles is not None


@pytest.mark.parametrize(
    "field",
    [
        "vendor_properties",
        "detail_properties",
        "catalogue_numbers__properties",
    ],
)
@pytest.mark.parametrize(
    "second", [f"{LEAK} Name", f"{LEAK}Name", f"{LEAK.lower()} name", f" {LEAK}  NAME "]
)
def test_a_property_named_twice_is_refused_ignoring_case_and_spaces(
    tmp_path: Path, field: str, second: str
) -> None:
    message = refusal(tmp_path, with_roles(**{field: [f"{LEAK} Name", second]}))

    assert "entry 2 repeats entry 1 (property names are compared ignoring case and spaces)" in (
        message
    )
    assert LEAK.casefold() not in message.casefold()


def test_a_distributor_property_named_twice_is_refused(tmp_path: Path) -> None:
    data = with_roles(distributor_block={"properties": ["FICT A", "fictA"], "min_valued": 1})

    assert "entry 2 repeats entry 1" in refusal(tmp_path, data)


@pytest.mark.parametrize(
    "dotted",
    [
        "part_roles.nickname",
        "part_roles.purchased_property",
        "part_roles.switch.nickname",
        "part_roles.distributor_block.nickname",
        "part_roles.catalogue_numbers.nickname",
    ],
)
def test_an_unknown_part_roles_key_is_refused_naming_it(tmp_path: Path, dotted: str) -> None:
    message = refusal(tmp_path, replacing(raw(PROFILE_A), dotted, ["anything"]))

    assert dotted.rsplit(".", 1)[-1] in message


def test_the_later_sections_are_derived_from_the_version_table() -> None:
    from swreview.checks.standards.profile import LATER_SECTIONS, SECTIONS_BY_VERSION

    assert LATER_SECTIONS == ("general_tolerance", "hygiene", "drawing", "part_roles")
    assert set(LATER_SECTIONS) == {name for names in SECTIONS_BY_VERSION.values() for name in names}


# --- the profile a review loads once (feature 013 contracts/part-roles.md section 5) ---------


def test_a_review_without_a_profile_loads_nothing_and_refuses_nothing() -> None:
    from swreview.checks.standards.profile import ReviewProfile, load_review_profile

    assert load_review_profile(None) == ReviewProfile(path=None, profile=None, refusal=None)


def test_a_review_profile_carries_the_loaded_profile() -> None:
    from swreview.checks.standards.profile import load_review_profile

    loaded = load_review_profile(PROFILE_A)

    assert loaded.path == str(PROFILE_A)
    assert loaded.refusal is None
    assert loaded.profile is not None
    assert loaded.profile.identity == load_profile(PROFILE_A).identity


def test_a_refused_review_profile_is_a_value_and_never_raises(tmp_path: Path) -> None:
    from swreview.checks.standards.profile import load_review_profile

    missing = load_review_profile(tmp_path / "absent.yaml")
    invalid = load_review_profile(write(tmp_path, without(raw(PROFILE_A), "part_roles")))

    assert missing.profile is None and isinstance(missing.refusal, ProfileUnreadable)
    assert invalid.profile is None and isinstance(invalid.refusal, ProfileInvalid)


def bands(*rows: tuple[Any, Any]) -> list[dict[str, Any]]:
    return [{"decimal_places": places, "plus_minus_mm": value} for places, value in rows]


def test_the_bands_are_read_by_decimal_places_in_ascending_order(tmp_path: Path) -> None:
    """Owner answer 2026-09-23: the general tolerance is by decimal places (research R5)."""
    declared = bands((1, 0.5), (2, 0.2), (3, 0.05))
    data = replacing(raw(PROFILE_A), "general_tolerance.linear", declared)

    profile = load_profile(write(tmp_path, data))

    assert profile.general_tolerance is not None
    read = [(band.decimal_places, band.plus_minus_mm) for band in profile.general_tolerance.linear]
    assert read == [(1, 0.5), (2, 0.2), (3, 0.05)]


@pytest.mark.parametrize(
    ("rows", "named"),
    [
        (((2, 0.2), (1, 0.5)), "decimal places 1 follows 2"),
        (((1, 0.5), (1, 0.2)), "decimal places 1 follows 1"),
    ],
    ids=["unordered", "overlapping"],
)
def test_unordered_or_overlapping_bands_are_refused_naming_them(
    tmp_path: Path, rows: tuple[tuple[int, float], ...], named: str
) -> None:
    data = replacing(raw(PROFILE_A), "general_tolerance.linear", bands(*rows))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))

    assert named in str(raised.value)


@pytest.mark.parametrize(
    ("row", "field"),
    [((-1, 0.5), "decimal_places"), ((1, 0.0), "plus_minus_mm"), ((1, -0.1), "plus_minus_mm"),
     ((1.5, 0.1), "decimal_places")],
    ids=["negative places", "zero band", "negative band", "fractional places"],
)
def test_a_band_that_could_not_be_meant_is_refused_naming_the_field(
    tmp_path: Path, row: tuple[Any, Any], field: str
) -> None:
    data = replacing(raw(PROFILE_A), "general_tolerance.linear", bands(row))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))

    assert field in str(raised.value)


def test_an_empty_band_list_and_no_angular_value_mean_the_company_declares_none(
    tmp_path: Path,
) -> None:
    data = replacing(raw(PROFILE_A), "general_tolerance", {"linear": [], "angular_deg": None})

    profile = load_profile(write(tmp_path, data))

    assert profile.general_tolerance is not None
    assert (profile.general_tolerance.linear, profile.general_tolerance.angular_deg) == ([], None)


@pytest.mark.parametrize("value", [0.0, -0.5], ids=repr)
def test_an_angular_tolerance_that_is_not_positive_is_refused(tmp_path: Path, value: float) -> None:
    data = replacing(raw(PROFILE_A), "general_tolerance.angular_deg", value)

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, data))

    assert "angular_deg" in str(raised.value)


# --- the file itself ---------------------------------------------------------------------


@pytest.mark.parametrize("document", ["- a\n- b\n", "not a mapping\n", "", "null\n"], ids=repr)
def test_a_profile_that_is_not_a_mapping_is_refused_naming_the_path(
    tmp_path: Path, document: str
) -> None:
    path = tmp_path / "standards.yaml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    assert str(path) in str(raised.value)


def test_a_yaml_parse_error_names_the_path_and_the_parsers_line_and_column(
    tmp_path: Path,
) -> None:
    path = tmp_path / "standards.yaml"
    path.write_text("version: 1\nlibrary: [\n  oops: : :\n", encoding="utf-8")

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    message = str(raised.value)
    assert str(path) in message
    assert "line 3" in message
    assert "column" in message


def test_a_profile_that_does_not_exist_is_unreadable_and_names_the_setting(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nowhere" / "standards.yaml"

    with pytest.raises(ProfileUnreadable) as raised:
        load_profile(path)

    assert str(path) in str(raised.value)
    assert SETTING in str(raised.value)


def test_a_profile_that_cannot_be_read_names_the_path_and_the_os_error(tmp_path: Path) -> None:
    directory = tmp_path / "standards.yaml"
    directory.mkdir()

    with pytest.raises(ProfileUnreadable) as raised:
        load_profile(directory)

    assert str(directory) in str(raised.value)
    assert isinstance(raised.value.__cause__, OSError)


def test_the_two_refusals_carry_the_contracts_error_class() -> None:
    """The page switches on these strings (`contracts/standards-check.md`)."""
    assert ProfileUnreadable.error_class == "ProfileUnreadable"
    assert ProfileInvalid.error_class == "ProfileInvalid"


# --- what leaves the reasoning side ------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_the_identity_is_the_path_and_the_digest_and_nothing_else(fixture: Path) -> None:
    identity = load_profile(fixture).identity

    assert isinstance(identity, ProfileIdentity)
    assert identity.path == str(fixture)
    assert identity.sha256 == hashlib.sha256(fixture.read_bytes()).hexdigest()


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_no_profile_value_appears_in_the_identity(fixture: Path) -> None:
    """FR-034: `{path, sha256}` is the whole of what the check record may carry."""
    identity = load_profile(fixture).identity
    rendered = f"{identity.path} {identity.sha256} {identity!r}"

    leaked = [
        value
        for value in _settable_values(raw(fixture))
        if len(value) >= 4 and value.casefold() in rendered.casefold()
    ]

    assert leaked == []


def _settable_values(data: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in data.values():
        if isinstance(value, dict):
            values.extend(_settable_values(value))
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, str):
            values.append(value)
    return values


def test_two_identities_differ_when_the_file_differs() -> None:
    assert load_profile(PROFILE_A).identity.sha256 != load_profile(PROFILE_B).identity.sha256


# --- no fallback, and exactly one schema owner -------------------------------------------


def _models(model: type[BaseModel]) -> Iterator[type[BaseModel]]:
    yield model
    for field in model.model_fields.values():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from _models(annotation)


def test_no_field_anywhere_in_the_schema_has_a_default() -> None:
    """A default here would grade a document against a standard nobody chose (FR-002)."""
    optional = [
        f"{model.__name__}.{name}"
        for model in _models(StandardsProfile)
        for name, field in model.model_fields.items()
        if not field.is_required()
    ]

    assert optional == []


LEAF_KEYS: tuple[str, ...] = tuple(
    key for key in PROFILE_KEYS if not any(other.startswith(f"{key}.") for other in PROFILE_KEYS)
)
"""The keys that carry a value; the section names (`library`, `revision`, ...) are not."""

DISTINCTIVE_KEYS: frozenset[str] = frozenset(
    key.rsplit(".", 1)[-1] for key in LEAF_KEYS if "_" in key.rsplit(".", 1)[-1]
)
"""The key names that belong to this schema and to nothing else in either tree.

`properties`, `pattern`, `configuration`, `column` and their like are ordinary words that
other models use for other reasons, and so are the section names - a BOM row has a
`part_number` too. The compound leaf names - `vault_root`, the four `*_prefixes` lists,
`row_from_end`, `header_text` - identify this schema wherever it is written down.
"""


def _schema_classes(root: Path) -> list[tuple[str, str]]:
    """Every class in `root` that declares a field name from this schema."""
    found: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            declared = {
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            }
            if declared & DISTINCTIVE_KEYS:
                found.append((path.relative_to(root).as_posix(), node.name))
    return found


def test_the_schema_is_expressed_in_exactly_one_module() -> None:
    """A second class carrying these field names is a second schema, however it is spelled."""
    assert len(DISTINCTIVE_KEYS) >= 7, DISTINCTIVE_KEYS

    owners = _schema_classes(SRC)

    assert len(owners) >= 4, f"the scan found almost nothing and would pass vacuously: {owners}"
    assert {module for module, _ in owners} == {OWNER.relative_to(SRC).as_posix()}


SHARED_WITH_THE_EVIDENCE: frozenset[str] = frozenset({"dimension_unit"})
"""Profile key names the extractor also writes, for another reason.

Version 3's `drawing.dimension_unit` (feature 011) is spelled like feature 006's
`dimension_unit` **gap kind** - a display dimension whose unit could not be determined - which
the drawing dumper writes and its tests assert. The extractor naming a gap kind is not the
extractor knowing the profile, so the C# scan below leaves that one name out (edited
deliberately by feature 011 T028). Every other key is matched as a whole word, so the IR member
`drafting_standard_name` is not read as the profile key `drafting_standard`."""


def test_the_extractor_side_knows_the_path_and_not_the_schema() -> None:
    """The host checks that a path is configured and readable; it never parses the file."""
    keys = sorted(DISTINCTIVE_KEYS - SHARED_WITH_THE_EVIDENCE)
    assert len(keys) >= 11, keys
    offenders = [
        f"{path.relative_to(EXTRACTOR).as_posix()}: {key}"
        for path in sorted(EXTRACTOR.rglob("*.cs"))
        if "/obj/" not in path.as_posix() and "/bin/" not in path.as_posix()
        for key in keys
        if re.search(rf"\b{re.escape(key)}\b", path.read_text(encoding="utf-8", errors="replace"))
    ]

    assert offenders == []


# --- a refusal's reason names no path (feature 013 T154-T155) ---------------------------------

PRIVATE = "private-owner-folder"
"""A folder name standing for the local user folder a real profile sits in."""

REFUSALS: dict[str, tuple[type[ProfileError], bytes | None, str]] = {
    "missing": (ProfileUnreadable, None, "no file at the configured path"),
    "a-folder": (ProfileUnreadable, None, "cannot be read"),
    "not-utf-8": (ProfileUnreadable, b"\xff\xfe\xfd", "not UTF-8 text"),
    "not-yaml": (ProfileInvalid, b": [\n", "not valid YAML"),
    "not-a-mapping": (ProfileInvalid, b"- a\n- b\n", "a profile is a YAML mapping"),
    "unknown-version": (ProfileInvalid, b"version: 99\n", "version 99"),
    "the-schema": (ProfileInvalid, b"version: 3\n", "not a valid standards profile"),
}
"""Every refusal the loader makes, how to provoke it, and the words its reason must still say."""


def refused_path(tmp_path: Path, kind: str) -> Path:
    folder = tmp_path / PRIVATE
    folder.mkdir()
    path = folder / "standards.yaml"
    _, content, _ = REFUSALS[kind]
    if kind == "a-folder":
        path.mkdir()
    elif content is not None:
        path.write_bytes(content)
    return path


@pytest.mark.parametrize("kind", sorted(REFUSALS))
def test_every_refusals_reason_says_why_and_names_no_path(tmp_path: Path, kind: str) -> None:
    """The part-roles state quotes the reason, and that sentence rides the bought-parts line
    into the digest, the coverage row, the summary and the report: it names what is wrong with
    the profile and never where the profile is (013 research R2.45)."""
    path = refused_path(tmp_path, kind)
    kind_of, _, says = REFUSALS[kind]

    refusal = load_review_profile(path).refusal

    assert isinstance(refusal, kind_of)
    assert says in refusal.reason
    for where in (str(path), str(path.parent), str(tmp_path), path.name, PRIVATE):
        assert where not in refusal.reason, where


@pytest.mark.parametrize("kind", sorted(REFUSALS))
def test_every_refusals_message_still_names_the_path(tmp_path: Path, kind: str) -> None:
    """The message the Standards tab and the standards line show the engineer is unchanged: it
    says which file, because that is what the engineer has to change."""
    path = refused_path(tmp_path, kind)

    refusal = load_review_profile(path).refusal

    assert refusal is not None
    assert str(path) in str(refusal)


def test_a_refusal_raised_without_a_reason_is_its_own_message() -> None:
    """Every refusal made outside the loader - the route's for an absent `profile_path` - names no
    path already, so its reason is its message."""
    refusal = ProfileUnreadable("profile_path is required")

    assert refusal.reason == str(refusal) == "profile_path is required"
