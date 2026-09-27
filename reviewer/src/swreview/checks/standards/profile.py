"""The standards profile: the one place this repository expresses the company's schema.

`specs/006-standards-check/contracts/profile.md` is normative. The file itself is never
committed here (FR-001): the repository ships `config/standards.example.yaml` with fictional
placeholder values, the tests use two fictional fixtures, and the owner writes the real file
on the workstation at the path the `StandardsProfilePath` setting names.

Three rules shape this module, and each of them is a refusal rather than a convenience:

- **There are no fallback values.** A missing, unreadable or schema-invalid profile refuses
  the run. A default would grade a document against the wrong standard and report a clean
  result, which is the worst failure a release gate has (FR-002).
- **Every key is required; every string and every list value may be empty.** An empty value
  is a deliberate statement ("we do not use this setting yet") and makes its check *skipped*
  coverage; a missing key is a half-written file, and is named. Unknown keys are refused
  naming them, so a typo in a list name cannot silently disable that list.
- **Only `{path, sha256}` leaves this module.** `ProfileIdentity` is what the check record,
  the session, the report and every finding's `coverage_limits` carry: no profile *value*
  appears in any of them (FR-034).

The host (the add-in) checks only that a path is configured and that the file is readable, and
refuses before it creates a run folder or dumps anything. It does not parse this schema, and
no second copy of it exists in either tree.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    PositiveFloat,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

__all__ = [
    "DEFAULT_PATH",
    "DIMENSION_UNITS",
    "KNOWN_VERSIONS",
    "LATER_SECTIONS",
    "PROFILE_VERSION",
    "PROJECTIONS",
    "SECTIONS_BY_VERSION",
    "SETTING_NAME",
    "VERSION_2_SECTIONS",
    "VERSION_3_SECTIONS",
    "VERSION_4_SECTIONS",
    "CatalogueNumbers",
    "DataCardSection",
    "DistributorBlock",
    "DrawingSection",
    "ExportControlSection",
    "GeneralToleranceSection",
    "HygieneSection",
    "LibrarySection",
    "LinearBand",
    "MaterialSection",
    "PartNumberSection",
    "PartRolesSection",
    "ProfileError",
    "ProfileIdentity",
    "ProfileInvalid",
    "ProfileUnreadable",
    "ProfileUpgradeRefused",
    "ReviewProfile",
    "RevisionCell",
    "RevisionSection",
    "StandardsProfile",
    "SwitchSection",
    "load_profile",
    "load_review_profile",
    "name_matches",
    "property_key",
    "propose_version_4",
]

PROFILE_VERSION = 4
"""The newest schema version this build writes into its examples. A profile carrying a
version outside `KNOWN_VERSIONS` is refused naming it and the known ones, rather than loaded
while its unrecognised fields are ignored."""

KNOWN_VERSIONS: tuple[int, ...] = (1, 2, 3, 4)
"""Version 1 is feature 006's schema; version 2 adds `general_tolerance` and `hygiene`
(feature 010 research R2.19); version 3 adds `drawing` (feature 011 `contracts/profile.md`
section 1); version 4 adds `part_roles` (feature 013 `contracts/part-roles-profile.md`). All
four load: the owner's real profile stays at its version until the owner rewrites it, and the
newer sources are simply absent until then (plan RK-7, 011 RK-9)."""

VERSION_2_SECTIONS: tuple[str, ...] = ("general_tolerance", "hygiene")
"""Required on versions 2 to 4, absent on version 1: every key is required, so adding them to
version 1 would have refused every version 1 file."""

VERSION_3_SECTIONS: tuple[str, ...] = ("drawing",)
"""Required on versions 3 and 4, absent on versions 1 and 2, for the same reason."""

VERSION_4_SECTIONS: tuple[str, ...] = ("part_roles",)
"""Required on version 4, absent on versions 1 to 3, for the same reason."""

SECTIONS_BY_VERSION: dict[int, tuple[str, ...]] = {
    1: (),
    2: VERSION_2_SECTIONS,
    3: (*VERSION_2_SECTIONS, *VERSION_3_SECTIONS),
    4: (*VERSION_2_SECTIONS, *VERSION_3_SECTIONS, *VERSION_4_SECTIONS),
}
"""The optional-by-version sections each known version must carry; every other one it must
not. One table, so "version 3 also requires everything version 2 requires" is a row, not a
second validator."""

LATER_SECTIONS: tuple[str, ...] = tuple(
    dict.fromkeys(name for names in SECTIONS_BY_VERSION.values() for name in names)
)
"""Every section some version adds, in the order the versions add them: what
`_no_section_of_a_later_version` checks, derived from the table so a version 5 needs no edit
there (feature 013 `contracts/part-roles-profile.md` section 3)."""

PATH_SEPARATORS: tuple[str, ...] = ("/", "\\")
WILDCARDS: frozenset[str] = frozenset("*?@")
"""A catalogue shape made only of these would match every token, so it is refused."""

PROJECTIONS: tuple[str, ...] = ("first_angle", "third_angle", "")
"""`drawing.projection`: first-angle or third-angle projection, or empty to skip it."""

DIMENSION_UNITS: tuple[str, ...] = ("mm", "in", "")
"""`drawing.dimension_unit`: the unit `general_tolerance`'s decimal places are counted in, or
empty, which leaves the general tolerance binding nothing by decimals (011 FR-022)."""

SETTING_NAME = "StandardsProfilePath"
"""The add-in setting that names the file, quoted in the refusal so a reader knows where to
look (`contracts/profile.md`, "Where it lives")."""

DEFAULT_PATH = "%LOCALAPPDATA%\\SwReview\\standards.yaml"
"""The path `SETTING_NAME` documents as its default, quoted beside it in a refusal.

**Not a fallback.** Nothing reads this: a run with no configured profile is refused, and
this is only what the refusal tells the engineer to look for. A constant rather than prose
in a message, because the command line and the host both name it and two copies of a path
are free to disagree."""


class ProfileError(Exception):
    """A refusal to grade anything. `error_class` is what the page switches on."""

    error_class: ClassVar[str]


class ProfileUnreadable(ProfileError):
    """No file at the configured path, or the file cannot be read."""

    error_class = "ProfileUnreadable"


class ProfileInvalid(ProfileError):
    """The file was read and is not a profile this build can use, field by field."""

    error_class = "ProfileInvalid"


@dataclass(frozen=True, slots=True)
class ProfileIdentity:
    """What leaves the reasoning side: where the profile was, and exactly which bytes."""

    path: str
    sha256: str


class _Section(BaseModel):
    """Strict and closed: no coercion, no unknown key, no default anywhere below."""

    model_config = ConfigDict(extra="forbid", strict=True)


class LibrarySection(_Section):
    """The four prefix lists, matched independently (`contracts/profile.md`, rule 4)."""

    skip_prefixes: list[str]
    sketch_exempt_prefixes: list[str]
    one_mate_prefixes: list[str]
    two_mate_prefixes: list[str]


class DataCardSection(_Section):
    properties: list[str]


class PartNumberSection(_Section):
    pattern: str


class RevisionCell(_Section):
    """`row_from_end` `0` is the last row; `column` is a zero-based index."""

    row_from_end: NonNegativeInt
    column: NonNegativeInt


class RevisionSection(_Section):
    property: str
    initial: str
    header_text: str
    cell: RevisionCell


class MaterialSection(_Section):
    configuration: str


class ExportControlSection(_Section):
    phrase: str


class LinearBand(_Section):
    """One band of a general tolerance block: the dimensions written to `decimal_places`
    decimals take `plus_minus_mm` (`.XX` is 2). Owner answer 2026-09-23: by decimal places."""

    decimal_places: NonNegativeInt
    plus_minus_mm: PositiveFloat


class GeneralToleranceSection(_Section):
    """The company's general tolerance block, applied only to a dimension with no tolerance
    of its own (feature 010 FR-023). An empty `linear` and a null `angular_deg` are the
    statement "the company declares none"; nothing defaults to a standard class."""

    linear: list[LinearBand]
    angular_deg: PositiveFloat | None

    @model_validator(mode="after")
    def _bands_ascend(self) -> GeneralToleranceSection:
        """Each band names more decimal places than the one before: no band is read twice."""
        for earlier, later in pairwise(self.linear):
            if later.decimal_places <= earlier.decimal_places:
                raise ValueError(
                    f"the linear bands must ascend by decimal places: decimal places "
                    f"{later.decimal_places} follows {earlier.decimal_places}"
                )
        return self


class HygieneSection(_Section):
    """Which properties the hygiene checks read (feature 010 US7); an empty name skips the
    checks that need it."""

    part_number_property: str
    description_property: str


class DrawingSection(_Section):
    """The company's drawing standard (profile version 3, feature 011 `contracts/profile.md`
    section 1), compared with every drawing a review reads by `drawing_profile.conformance`.

    Every key is required and every value may be empty, which skips that comparison.
    `general_tolerance` is **not** restated here: `dimension_unit` names the unit its
    decimal places are counted in (011 FR-045), and a `general_tolerance` key here is an
    unknown key like any other. The two templates are recorded for drawing creation (feature
    012); a finished drawing does not record the template it was made from, so neither is
    compared.
    """

    sheet_formats: list[str]
    drafting_standard: str
    projection: str
    dimension_unit: str
    drawing_template: str
    bom_template: str

    @field_validator("sheet_formats")
    @classmethod
    def _each_format_once(cls, value: list[str]) -> list[str]:
        repeated = next((name for index, name in enumerate(value) if name in value[:index]), None)
        if repeated is not None:
            raise ValueError(f"sheet format {repeated!r} is listed twice; list each name once")
        return value

    @field_validator("projection")
    @classmethod
    def _a_known_projection(cls, value: str) -> str:
        return _one_of(value, PROJECTIONS, "projection")

    @field_validator("dimension_unit")
    @classmethod
    def _a_known_unit(cls, value: str) -> str:
        return _one_of(value, DIMENSION_UNITS, "unit")


def _one_of(value: str, allowed: tuple[str, ...], what: str) -> str:
    """`value` when it is one of `allowed`, matched exactly; otherwise the refusal naming both."""
    if value in allowed:
        return value
    named = [item or "''" for item in allowed]
    raise ValueError(
        f"{value!r} is not a {what} this profile knows; use {', '.join(named[:-1])} or "
        f"{named[-1]} (empty skips the comparison)"
    )


def property_key(name: str) -> str:
    """How a custom property's name is compared: folded, with every space removed.

    Real files spell one property both with and without a space, and SOLIDWORKS reads a name
    without regard to case (feature 013 `contracts/part-roles-profile.md` section 2). Every
    reader of a named property - the part-role signals, the hygiene checks, the refusal of a
    name listed twice below - compares through this, so the two spellings are one property
    everywhere. Defined here, the lowest module of the family; `traversal.py` re-exports it
    beside `name_matches`.
    """
    return "".join(name.split()).casefold()


_CONVENTION_CLASSES: dict[str, str] = {"#": "[0-9]", "?": "."}
"""The part-number convention's vocabulary (feature 006 `contracts/rules.md`)."""

_WILDCARD_CLASSES: dict[str, str] = {**_CONVENTION_CLASSES, "@": "[^\\W\\d_]", "*": ".*"}
"""Profile version 4's catalogue-number shapes add one letter and any run (feature 013
`contracts/part-roles-profile.md` section 2). `[^\\W\\d_]` is a word character that is
neither a digit nor an underscore: a letter, in any script a file name can carry."""


def name_matches(pattern: str, text: str, *, wildcards: bool = False) -> bool:
    """Whether the whole of `text` is spelled by `pattern`, ignoring case.

    The one matcher of the names the owner writes. `#` is one digit and `?` any one
    character; with `wildcards`, `@` is one letter and `*` any run, the empty run included;
    every other character is itself. `part_number.pattern` is matched with `wildcards`
    false, so the convention keeps the vocabulary the macro had and `@` or `*` in it is a
    literal character. An empty pattern or an empty text matches nothing. The owner writes
    no regular expression: the pattern is translated into one here, every other character
    escaped. Defined here, beside the schema whose patterns it reads and below every module
    that matches them; `traversal.py` re-exports it.
    """
    if not pattern or not text:
        return False
    classes = _WILDCARD_CLASSES if wildcards else _CONVENTION_CLASSES
    expression = "".join(classes.get(character, re.escape(character)) for character in pattern)
    return re.fullmatch(expression, text, flags=re.IGNORECASE) is not None


def _value_key(value: str) -> str:
    """How a value the owner writes is compared: folded, surrounding spaces ignored."""
    return value.strip().casefold()


def _no_blank(entries: list[str], what: str = "entry") -> list[str]:
    """Refuse a blank entry by its position (1-based), never quoting a value (a refusal can
    reach a public log)."""
    blank = next((index for index, entry in enumerate(entries, 1) if not entry.strip()), None)
    if blank is not None:
        raise ValueError(f"{what} {blank} is blank; remove it or write the value")
    return entries


def _no_repeat(entries: list[str], key: Callable[[str], str], rule: str) -> list[str]:
    """Refuse an entry that repeats an earlier one under `key`, by both positions."""
    seen: dict[str, int] = {}
    for index, entry in enumerate(entries, 1):
        folded = key(entry)
        if folded in seen:
            raise ValueError(f"entry {index} repeats entry {seen[folded]} ({rule})")
        seen[folded] = index
    return entries


_NAMES_RULE = "property names are compared ignoring case and spaces"
_VALUES_RULE = "compared ignoring case"


def _property_names(entries: list[str]) -> list[str]:
    return _no_repeat(_no_blank(entries), property_key, _NAMES_RULE)


class SwitchSection(_Section):
    """The make-or-buy switch the engineer sets (feature 013 `contracts/part-roles.md`
    section 2.1): its bought value is strong evidence, its custom value weak. An empty
    property with no values means the signal is not used."""

    property: str
    bought_values: list[str]
    custom_values: list[str]

    @field_validator("bought_values", "custom_values")
    @classmethod
    def _values_are_written(cls, values: list[str]) -> list[str]:
        return _no_repeat(_no_blank(values, "value"), _value_key, _VALUES_RULE)

    @model_validator(mode="after")
    def _a_property_and_its_values_come_together(self) -> SwitchSection:
        has_values = bool(self.bought_values or self.custom_values)
        if self.property.strip() and not has_values:
            raise ValueError("switch.property needs at least one bought or custom value")
        if has_values and not self.property.strip():
            raise ValueError("switch values need switch.property, the property that holds them")
        bought = {_value_key(value): index for index, value in enumerate(self.bought_values, 1)}
        for index, value in enumerate(self.custom_values, 1):
            if _value_key(value) in bought:
                raise ValueError(
                    f"custom value {index} repeats bought value {bought[_value_key(value)]}; a "
                    "value cannot mean both"
                )
        return self


class DistributorBlock(_Section):
    """A distributor's download block: strong bought evidence when at least `min_valued` of
    its properties carry a value. No properties with `min_valued` 0 means not used."""

    properties: list[str]
    min_valued: NonNegativeInt

    @field_validator("properties")
    @classmethod
    def _names_are_written(cls, values: list[str]) -> list[str]:
        return _property_names(values)

    @model_validator(mode="after")
    def _the_count_fits_the_block(self) -> DistributorBlock:
        count = len(self.properties)
        if count == 0 and self.min_valued != 0:
            raise ValueError("min_valued must be 0 when the block names no properties")
        if count and not 1 <= self.min_valued <= count:
            raise ValueError(f"min_valued must be from 1 to the number of properties ({count})")
        return self


class CatalogueNumbers(_Section):
    """Catalogue-number shapes, in the name-pattern vocabulary, and the properties whose
    values they are tested on besides file-name tokens and configuration names."""

    shapes: list[str]
    properties: list[str]

    @field_validator("shapes")
    @classmethod
    def _shapes_say_something(cls, values: list[str]) -> list[str]:
        _no_blank(values, "shape")
        for index, shape in enumerate(values, 1):
            if set(shape.strip()) <= WILDCARDS:
                raise ValueError(f"shape {index} would match every token")
        return _no_repeat(values, _value_key, _VALUES_RULE)

    @field_validator("properties")
    @classmethod
    def _names_are_written(cls, values: list[str]) -> list[str]:
        return _property_names(values)

    @model_validator(mode="after")
    def _properties_need_a_shape(self) -> CatalogueNumbers:
        if self.properties and not self.shapes:
            raise ValueError("catalogue_numbers.properties need at least one shape to test")
        return self


class PartRolesSection(_Section):
    """What each part-role signal looks for (profile version 4, feature 013
    `contracts/part-roles-profile.md` section 1). The strengths are the classifier's, not the
    profile's; every value may be empty, which turns its signal off."""

    bought_prefixes: list[str]
    bought_folder_names: list[str]
    switch: SwitchSection
    vendor_properties: list[str]
    distributor_block: DistributorBlock
    catalogue_numbers: CatalogueNumbers
    custom_prefixes: list[str]
    bought_number_prefixes: list[str]
    detail_properties: list[str]

    @field_validator("bought_prefixes")
    @classmethod
    def _prefixes_are_written(cls, values: list[str]) -> list[str]:
        return _no_blank(values)

    @field_validator("bought_folder_names")
    @classmethod
    def _folder_names_are_one_folder(cls, values: list[str]) -> list[str]:
        _no_blank(values, "folder name")
        for index, name in enumerate(values, 1):
            if any(separator in name for separator in PATH_SEPARATORS):
                raise ValueError(f"folder name {index} holds a path separator; name one folder")
        return _no_repeat(values, _value_key, _VALUES_RULE)

    @field_validator("vendor_properties", "detail_properties")
    @classmethod
    def _names_are_written(cls, values: list[str]) -> list[str]:
        return _property_names(values)

    @field_validator("custom_prefixes", "bought_number_prefixes")
    @classmethod
    def _number_prefixes_are_written(cls, values: list[str]) -> list[str]:
        return _no_repeat(_no_blank(values, "prefix"), _value_key, _VALUES_RULE)

    @property
    def signals_unused(self) -> bool:
        """Whether every signal this section configures is off: what `swreview profile upgrade`
        writes before the owner fills it in (`propose_version_4`). Such a section decides nothing
        a version 3 profile would not, so the classifier reads the profile as the version 3 file
        it was proposed from (feature 013 `contracts/part-roles.md` section 1, amended
        2026-09-27): Toolbox and the part-number convention decide, and the unclear parts are
        asked about, where every signal off fired the zero-match guard and asked nothing."""
        return not (
            self.bought_prefixes
            or self.bought_folder_names
            or self.switch.property.strip()
            or self.vendor_properties
            or self.distributor_block.properties
            or self.catalogue_numbers.shapes
            or self.custom_prefixes
            or self.bought_number_prefixes
            or self.detail_properties
        )

    @model_validator(mode="after")
    def _a_number_votes_one_way(self) -> PartRolesSection:
        """A custom and a bought prefix that overlap would let one number vote both ways."""
        for custom_index, custom in enumerate(self.custom_prefixes, 1):
            for bought_index, bought in enumerate(self.bought_number_prefixes, 1):
                left, right = _value_key(custom), _value_key(bought)
                if left.startswith(right) or right.startswith(left):
                    raise ValueError(
                        f"custom prefix {custom_index} overlaps bought prefix {bought_index}; "
                        "a number could then vote both ways"
                    )
        return self


def _introduced_in(section: str) -> int:
    """The first version that carries `section`."""
    return min(version for version, names in SECTIONS_BY_VERSION.items() if section in names)


class StandardsProfile(_Section):
    """The whole schema. Built by `load_profile`, which is what gives it its identity.

    The version 2 to 4 sections are required fields that may only be null on a version that
    predates them: a version 1 file carries none of the four and reads as all absent, a
    version 2 file carries `general_tolerance` and `hygiene`, a version 3 file adds `drawing`,
    a version 4 file adds `part_roles`, and none has a default (FR-002). `SECTIONS_BY_VERSION`
    is the one table both validators read.
    """

    version: int
    vault_root: str
    library: LibrarySection
    data_card: DataCardSection
    part_number: PartNumberSection
    revision: RevisionSection
    material: MaterialSection
    export_control: ExportControlSection
    general_tolerance: GeneralToleranceSection | None
    hygiene: HygieneSection | None
    drawing: DrawingSection | None
    part_roles: PartRolesSection | None

    _identity: ProfileIdentity | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _no_section_of_a_later_version(cls, data: Any) -> Any:
        """A section the declared version predates is refused naming it; the rest read as
        absent. An unknown version is `load_profile`'s refusal and is left alone here."""
        if not isinstance(data, dict):
            return data
        version = data.get("version")
        if isinstance(version, bool) or version not in SECTIONS_BY_VERSION:
            return data
        later = [name for name in LATER_SECTIONS if name not in SECTIONS_BY_VERSION[version]]
        carried = [name for name in later if name in data]
        if carried:
            named = ", ".join(
                f"{name} (a version {_introduced_in(name)} section)" for name in carried
            )
            raise ValueError(f"a version {version} profile carries no {named}")
        return {**data, **dict.fromkeys(later)}

    @model_validator(mode="after")
    def _the_version_carries_its_sections(self) -> StandardsProfile:
        required = SECTIONS_BY_VERSION.get(self.version, ())
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"a version {self.version} profile needs {' and '.join(missing)}")
        return self

    @property
    def identity(self) -> ProfileIdentity:
        """`{path, sha256}`, and never a profile value (FR-034)."""
        if self._identity is None:
            raise RuntimeError(
                "this profile was built in memory rather than loaded from a file, so it has "
                "no identity to report; call load_profile"
            )
        return self._identity


def load_profile(path: Path | str) -> StandardsProfile:
    """Read and validate the profile at `path`, or refuse.

    `ProfileUnreadable` when there is no file or it cannot be read; `ProfileInvalid` when it
    is not YAML, is not a mapping, carries an unknown version, or fails the schema. Nothing
    is graded on a refusal, and there is no partly-loaded profile to fall back to.
    """
    path = Path(path)
    content = _read(path)
    identity = ProfileIdentity(path=str(path), sha256=hashlib.sha256(content).hexdigest())
    data = _parse(path, content)
    _check_version(path, data)

    try:
        profile = StandardsProfile.model_validate(data)
    except ValidationError as error:
        raise ProfileInvalid(
            f"{path} is not a valid standards profile: {_fields(error)}"
        ) from error

    profile._identity = identity
    return profile


@dataclass(frozen=True, slots=True)
class ReviewProfile:
    """What a review loaded, once: the path it was given, and the profile or the refusal.

    `start_review` loads the profile once and hands this to the classifier and to
    `attach_standards` (feature 013 `contracts/part-roles.md` section 5), so the two cannot
    read two different files and nothing loads it twice. Exactly one of `profile` and
    `refusal` is set when `path` is; neither when the review was started without one.
    """

    path: str | None
    profile: StandardsProfile | None
    refusal: ProfileError | None


def load_review_profile(path: Path | str | None) -> ReviewProfile:
    """Load the profile at `path` for a review, turning a refusal into a value.

    Never raises for a profile problem: a review with a refused profile is still a review, and
    the refusal is what the standards line and the part-roles state say (`attach_standards`,
    `classify_parts(profile_refusal=...)`).
    """
    if path is None:
        return ReviewProfile(path=None, profile=None, refusal=None)
    try:
        return ReviewProfile(path=str(path), profile=load_profile(path), refusal=None)
    except ProfileError as error:
        return ReviewProfile(path=str(path), profile=None, refusal=error)


class ProfileUpgradeRefused(ProfileError):
    """`swreview profile upgrade` will not write a proposal from this input."""

    error_class = "ProfileUpgradeRefused"


_VERSION_3_LINE = re.compile(r"(?m)^version:[ \t]*3(?=[ \t]*(?:#[^\r\n]*)?\r?$)")
"""The top-level `version: 3` line, a trailing comment allowed, in either line ending."""

_PROPOSALS: tuple[tuple[str, str], ...] = (
    ("skip_prefixes", "'Standards skips this'"),
    ("sketch_exempt_prefixes", "'no sketch check here'"),
)
"""The library lists the upgrade proposes as bought prefixes, and what each one means instead
(feature 013 `contracts/part-roles-profile.md` section 5)."""


def propose_version_4(text: str, profile: StandardsProfile) -> str:
    """The version 3 profile `text` as a proposed version 4 profile, deciding nothing.

    The input's own text is kept - its comments and its layout - with the `version: 3` line
    raised to 4 and a `part_roles` section appended in which every signal is unused. The
    library's skip and sketch-exempt entries are offered under `bought_prefixes` as commented
    lines only: neither list means "bought", so nothing is treated as bought until the owner
    uncomments it (feature 013 `contracts/part-roles-profile.md` section 5, research R2.2).

    Raises `ProfileUpgradeRefused` for a version 1 or 2 profile, naming the sections it lacks
    (version 4 is version 3 plus one section; the helper does not invent values the owner has
    not written), for a version 4 profile, and for a text whose version line it cannot find.
    """
    if profile.version == 4:
        raise ProfileUpgradeRefused("the profile is already version 4")
    if profile.version != 3:
        has = SECTIONS_BY_VERSION[profile.version]
        lacking = [name for name in SECTIONS_BY_VERSION[3] if name not in has]
        named = lacking[0] if len(lacking) == 1 else f"{', '.join(lacking[:-1])} and {lacking[-1]}"
        raise ProfileUpgradeRefused(
            f"a version {profile.version} profile lacks {named}; version 4 adds part_roles to "
            "a version 3 profile, and the upgrade does not write sections you have not written"
        )
    raised, found = _VERSION_3_LINE.subn("version: 4", text)
    if found != 1:
        raise ProfileUpgradeRefused(
            "the profile's version is not written on one top-level line as 'version: 3'"
        )
    newline = "\r\n" if "\r\n" in text else "\n"
    kept = raised.rstrip("\r\n")
    section = newline.join(_proposal(profile))
    proposed = f"{kept}{newline}{newline}{section}{newline}"
    StandardsProfile.model_validate(yaml.safe_load(proposed))
    return proposed


def _proposal(profile: StandardsProfile) -> list[str]:
    """The appended `part_roles` section, one line per list item, every signal unused."""
    lines = [
        "part_roles:",
        "  # Written by `swreview profile upgrade` (feature 013). Every signal below is unused",
        "  # until you fill it in; config/standards.example.yaml shows what each one looks for.",
        "  bought_prefixes: []",
    ]
    proposals = [
        (name, meaning, getattr(profile.library, name))
        for name, meaning in _PROPOSALS
        if getattr(profile.library, name)
    ]
    if proposals:
        lines.append(
            "    # To use a proposal, uncomment it and write 'bought_prefixes:' without the []."
        )
    for name, meaning, entries in proposals:
        lines.append(
            f"    # Proposed from library.{name}, which means {meaning}, not 'bought'. "
            "Uncomment what is bought."
        )
        lines.extend(f"    # - {json.dumps(entry)}" for entry in entries)
    lines.extend(
        [
            "  bought_folder_names: []",
            "  switch:",
            '    property: ""',
            "    bought_values: []",
            "    custom_values: []",
            "  vendor_properties: []",
            "  distributor_block:",
            "    properties: []",
            "    min_valued: 0",
            "  catalogue_numbers:",
            "    shapes: []",
            "    properties: []",
            "  custom_prefixes: []",
            "  bought_number_prefixes: []",
            "  detail_properties: []",
        ]
    )
    return lines


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as error:
        raise ProfileUnreadable(
            f"no standards profile at {path}; the setting is {SETTING_NAME}"
        ) from error
    except OSError as error:
        raise ProfileUnreadable(f"the standards profile at {path} cannot be read: {error}") from (
            error
        )


def _parse(path: Path, content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProfileUnreadable(
            f"the standards profile at {path} is not UTF-8 text: {error}"
        ) from error

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ProfileInvalid(f"{path} is not valid YAML{_where(error)}: {_problem(error)}") from (
            error
        )

    if not isinstance(data, dict):
        raise ProfileInvalid(
            f"{path} is not a standards profile: a profile is a YAML mapping, and this file "
            f"parsed as {type(data).__name__}"
        )
    return data


def _check_version(path: Path, data: dict[str, Any]) -> None:
    """A version this build does not know is refused naming both, not partly honoured.

    A missing `version` key is left to the schema, which names it like any other missing key.
    """
    if "version" not in data:
        return
    version = data["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version not in KNOWN_VERSIONS:
        numbers = [str(item) for item in KNOWN_VERSIONS]
        known = f"{', '.join(numbers[:-1])} and {numbers[-1]}"
        raise ProfileInvalid(
            f"{path} is a version {version!r} standards profile; this build knows versions "
            f"{known}"
        )


def _where(error: yaml.YAMLError) -> str:
    mark = getattr(error, "problem_mark", None)
    if mark is None:
        return ""
    return f" at line {mark.line + 1}, column {mark.column + 1}"


def _problem(error: yaml.YAMLError) -> str:
    return str(getattr(error, "problem", None) or error).strip()


def _fields(error: ValidationError) -> str:
    """Every failure, field by field, so one edit fixes the whole file."""
    return "; ".join(
        f"{'.'.join(str(item) for item in failure['loc']) or '(root)'}: {failure['msg']}"
        for failure in error.errors()
    )
