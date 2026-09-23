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
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from swreview.checks.standards.profile import (
    ProfileIdentity,
    ProfileInvalid,
    ProfileUnreadable,
    StandardsProfile,
    load_profile,
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
)
LIST_FIELDS: tuple[str, ...] = (
    "library.skip_prefixes",
    "library.sketch_exempt_prefixes",
    "library.one_mate_prefixes",
    "library.two_mate_prefixes",
    "data_card.properties",
    "general_tolerance.linear",
)
VERSION_2_SECTIONS: tuple[str, ...] = ("general_tolerance", "hygiene")
"""The two sections version 2 adds (feature 010 research R2.19): required on version 2,
absent on version 1."""


def as_version_1(data: dict[str, Any]) -> dict[str, Any]:
    """A version 2 fixture written back as the version 1 profile it extends."""
    copy = {key: value for key, value in deepcopy(data).items() if key not in VERSION_2_SECTIONS}
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

    assert profile.version == 2
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


@pytest.mark.parametrize("version", [0, 3, 17, "2"], ids=repr)
def test_an_unknown_version_is_refused_naming_both_versions(tmp_path: Path, version: Any) -> None:
    path = write(tmp_path, replacing(raw(PROFILE_A), "version", version))

    with pytest.raises(ProfileInvalid) as raised:
        load_profile(path)

    message = str(raised.value)
    assert repr(version) in message or str(version) in message
    assert "1" in message and "2" in message, "the refusal names the versions this build knows"
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
        load_profile(write(tmp_path, without(raw(PROFILE_A), section)))

    assert section in str(raised.value)


@pytest.mark.parametrize("section", VERSION_2_SECTIONS)
def test_a_version_2_section_written_as_null_is_refused_naming_it(
    tmp_path: Path, section: str
) -> None:
    with pytest.raises(ProfileInvalid) as raised:
        load_profile(write(tmp_path, replacing(raw(PROFILE_A), section, None)))

    assert section in str(raised.value)


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


def test_the_extractor_side_knows_the_path_and_not_the_schema() -> None:
    """The host checks that a path is configured and readable; it never parses the file."""
    offenders = [
        f"{path.relative_to(EXTRACTOR).as_posix()}: {key}"
        for path in sorted(EXTRACTOR.rglob("*.cs"))
        if "/obj/" not in path.as_posix() and "/bin/" not in path.as_posix()
        for key in sorted(DISTINCTIVE_KEYS)
        if key in path.read_text(encoding="utf-8", errors="replace")
    ]

    assert offenders == []
