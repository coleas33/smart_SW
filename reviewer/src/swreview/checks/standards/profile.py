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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, NonNegativeInt, PrivateAttr, ValidationError

__all__ = [
    "DEFAULT_PATH",
    "PROFILE_VERSION",
    "SETTING_NAME",
    "DataCardSection",
    "ExportControlSection",
    "LibrarySection",
    "MaterialSection",
    "PartNumberSection",
    "ProfileError",
    "ProfileIdentity",
    "ProfileInvalid",
    "ProfileUnreadable",
    "RevisionCell",
    "RevisionSection",
    "StandardsProfile",
    "load_profile",
]

PROFILE_VERSION = 1
"""The one schema version this build knows. A profile carrying another is refused naming
both, rather than loaded while its unrecognised fields are ignored."""

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


class StandardsProfile(_Section):
    """The whole schema. Built by `load_profile`, which is what gives it its identity."""

    version: int
    vault_root: str
    library: LibrarySection
    data_card: DataCardSection
    part_number: PartNumberSection
    revision: RevisionSection
    material: MaterialSection
    export_control: ExportControlSection

    _identity: ProfileIdentity | None = PrivateAttr(default=None)

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
    if isinstance(version, bool) or version != PROFILE_VERSION:
        raise ProfileInvalid(
            f"{path} is a version {version!r} standards profile; this build knows version "
            f"{PROFILE_VERSION}"
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
