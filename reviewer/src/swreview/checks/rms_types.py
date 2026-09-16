"""Loader for `rms_types.yaml`, the one normative RMS type table (T008).

`GetTypeName2` returns a bare string and SOLIDWORKS promises nothing about it, so every
question the Resilient Modeling rules ask about a feature - what class it is, whether it is
a folder, an end-tag marker, or content that must be grouped and described - is answered
here, from data an engineer can read and change, and never from a guess in a rule. The
same shape as `engagement_rules.py` and `tool_envelopes.py`, for the same reason.

Two answers are deliberately not classifications (constitution Principle I):

- a type name the table does not carry classifies as `unknown`, which is *not* a class a
  rule may act on. `contracts/rules.md` ("Class vocabulary") has a class-dependent rule
  report such a feature `unresolved`, while the rules that need no class still treat it as
  content - an unrecognised feature is exactly the kind a reviewer must look at;
- an absent constrained status is `unavailable`, never `fully_defined`. `unknown` (the
  solver's own "I do not know", including autosolve off) and `unavailable` (nothing was
  read) stay distinct so a finding can say which one it hit.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

import yaml

from swreview.ir.models import Feature

__all__ = [
    "DEFAULT_TYPES_PATH",
    "FEATURE_CLASSES",
    "AssemblyTable",
    "Classification",
    "ConstrainedStatus",
    "FeatureClass",
    "RmsTypeTable",
    "class_of",
    "load_table",
]

DEFAULT_TYPES_PATH = Path(__file__).with_name("rms_types.yaml")

FeatureClass = Literal[
    "sketch",
    "solid",
    "cut",
    "hole",
    "fillet",
    "chamfer",
    "shell",
    "draft",
    "pattern",
    "reference",
    "construction",
]
"""The eleven classes a recognised type name can have (`contracts/rules.md`)."""

FEATURE_CLASSES: tuple[FeatureClass, ...] = get_args(FeatureClass)
"""`FeatureClass` as a value, in contract order; the table must carry exactly these."""

Classification = FeatureClass | Literal["unknown", "ambiguous"]
"""What `classify` returns: one class, or one of the two non-answers."""

ConstrainedStatus = Literal[
    "unknown",
    "under_defined",
    "fully_defined",
    "over_defined",
    "solver_error",
    "unavailable",
]
"""The named `swConstrainedStatus_e` outcomes, plus `unavailable` for a status that was
never read. Only the first five may appear in the table; `unavailable` is the loader's
answer to a null, so a table that named it would be claiming a reading it does not have."""

_TABLE_CONSTRAINED_STATUSES = frozenset(get_args(ConstrainedStatus)) - {"unavailable"}


@dataclass(frozen=True)
class AssemblyTable:
    """The assembly half of the table: mate entity kinds and the chain-depth limit.

    The two kind lists are not exhaustive. A kind in neither - a sketch entity, or the
    `unknown(<n>)` the dumper writes for a `swSelectType_e` value with no name - leaves the
    mate unresolved rather than passing or failing it.
    """

    reference_entity_kinds: tuple[str, ...]
    geometry_entity_kinds: tuple[str, ...]
    mate_chain_depth_limit: int


@dataclass(frozen=True)
class RmsTypeTable:
    """The whole table. `classes` keeps the file's order and its sets are disjoint."""

    version: int
    calibrated_version: str
    groups: tuple[str, ...]
    folder_type: str
    end_tag_suffix: str
    classes: dict[FeatureClass, frozenset[str]]
    ambiguous: frozenset[str]
    tolerated_loose: frozenset[str]
    default_names_excluded: frozenset[str]
    constrained_status_map: dict[int, ConstrainedStatus]
    assembly: AssemblyTable

    def classify(self, type_name: str) -> Classification:
        """The one class of `type_name`, or `unknown`/`ambiguous`.

        Matching is exact and case-sensitive: `type_name` is a `GetTypeName2` string,
        and a near-miss is a name the table has not been calibrated against.
        """
        for name, members in self.classes.items():
            if type_name in members:
                return name
        if type_name in self.ambiguous:
            return "ambiguous"
        return "unknown"

    def is_folder(self, feature: Feature) -> bool:
        """A folder-typed feature that is not an end-tag marker (rules.md, "Group
        assignment")."""
        return feature.type_name == self.folder_type and not self.is_end_tag(feature)

    def is_end_tag(self, feature: Feature) -> bool:
        """The folder-typed marker that closes a folder in the flat traversal shape.

        Both halves are required: a feature of another type whose name happens to end in
        the suffix is an ordinary feature someone named oddly, not a marker.
        """
        return feature.type_name == self.folder_type and feature.name.endswith(
            self.end_tag_suffix
        )

    def is_content(self, feature: Feature) -> bool:
        """Whether the method holds `feature` to the grouping and intent rules.

        `contracts/rules.md` ("Content features"): not a folder, not an end-tag marker,
        not one of the excluded default names, and not a tolerated type. Class plays no
        part - a feature of class `unknown` is content, because a feature nobody
        recognises is precisely one that has to be grouped and described.
        """
        return (
            not self.is_folder(feature)
            and not self.is_end_tag(feature)
            and feature.name not in self.default_names_excluded
            and feature.type_name not in self.tolerated_loose
        )

    def constrained_status(self, raw: int | None) -> ConstrainedStatus:
        """Name a raw `swConstrainedStatus_e` value.

        `None` means nothing was read, which is `unavailable`. A value the table does not
        list - a newer enum member, or a number from a call that half-failed - is
        `unknown`: the rules report both as unresolved and neither as a defined sketch.
        """
        if raw is None:
            return "unavailable"
        return self.constrained_status_map.get(raw, "unknown")


def _parse_classes(
    document: dict[str, object], path: Path
) -> dict[FeatureClass, frozenset[str]]:
    raw = document["classes"]
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: classes must be a mapping")

    unexpected = sorted(set(raw) - set(FEATURE_CLASSES))
    if unexpected:
        raise ValueError(
            f"{path}: unknown class name(s) {unexpected}; the vocabulary is "
            f"{list(FEATURE_CLASSES)}"
        )
    missing = [name for name in FEATURE_CLASSES if name not in raw]
    if missing:
        raise ValueError(f"{path}: no members listed for class(es) {missing}")

    classes: dict[FeatureClass, frozenset[str]] = {}
    owner: dict[str, str] = {}
    for name in FEATURE_CLASSES:
        members = frozenset(raw[name])
        for type_name in sorted(members):
            if type_name in owner:
                raise ValueError(
                    f"{path}: {type_name!r} is in both class {owner[type_name]!r} and "
                    f"class {name!r}; the class sets must be disjoint"
                )
            owner[type_name] = name
        classes[name] = members
    return classes


def _parse_constrained_status(
    document: dict[str, object], path: Path
) -> dict[int, ConstrainedStatus]:
    raw = document["constrained_status"]
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: constrained_status must be a mapping")

    mapping: dict[int, ConstrainedStatus] = {}
    for key, value in raw.items():
        if not isinstance(key, int) or isinstance(key, bool):
            raise ValueError(
                f"{path}: constrained_status key {key!r} is not an int; the keys are raw "
                "swConstrainedStatus_e values"
            )
        if value not in _TABLE_CONSTRAINED_STATUSES:
            raise ValueError(
                f"{path}: constrained_status[{key}] is {value!r}; the table may only name "
                f"{sorted(_TABLE_CONSTRAINED_STATUSES)}"
            )
        mapping[key] = value
    if not mapping:
        raise ValueError(f"{path}: constrained_status names no value")
    return mapping


def _parse(document: object, path: Path) -> RmsTypeTable:
    if not isinstance(document, dict):
        raise ValueError(f"{path}: the RMS type table must be a mapping")

    assembly = document["assembly"]
    reference_kinds = tuple(assembly["reference_entity_kinds"])
    geometry_kinds = tuple(assembly["geometry_entity_kinds"])
    overlap = sorted(set(reference_kinds) & set(geometry_kinds))
    if overlap:
        raise ValueError(
            f"{path}: entity kind(s) {overlap} are listed as both reference and geometry"
        )
    depth_limit = int(assembly["mate_chain_depth_limit"])
    if depth_limit < 1:
        raise ValueError(
            f"{path}: mate_chain_depth_limit must be at least 1, got {depth_limit}"
        )

    folder_type = str(document["folder_type"])
    end_tag_suffix = str(document["end_tag_suffix"])
    if not folder_type or not end_tag_suffix:
        raise ValueError(f"{path}: folder_type and end_tag_suffix must not be empty")

    return RmsTypeTable(
        version=int(document["version"]),
        calibrated_version=str(document["calibrated_version"]),
        groups=tuple(document["groups"]),
        folder_type=folder_type,
        end_tag_suffix=end_tag_suffix,
        classes=_parse_classes(document, path),
        ambiguous=frozenset(document["ambiguous"]),
        tolerated_loose=frozenset(document["tolerated_loose"]),
        default_names_excluded=frozenset(document["default_names_excluded"]),
        constrained_status_map=_parse_constrained_status(document, path),
        assembly=AssemblyTable(
            reference_entity_kinds=reference_kinds,
            geometry_entity_kinds=geometry_kinds,
            mate_chain_depth_limit=depth_limit,
        ),
    )


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> RmsTypeTable:
    return _parse(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_table(path: Path | str | None = None) -> RmsTypeTable:
    """Read the RMS type table, defaulting to the one that ships with the package.

    Cached by resolved path, so every rule in a review shares one table object and two
    spellings of the same file are one entry.
    """
    resolved = (Path(path) if path is not None else DEFAULT_TYPES_PATH).resolve()
    return _load_cached(resolved)


def class_of(feature: Feature, table: RmsTypeTable | None = None) -> Classification:
    """The class of one feature: the single helper every class-dependent rule calls.

    Kept as a function rather than a `Feature` member because the answer is the table's,
    not the extractor's - the IR carries `type_name` verbatim and derives nothing.
    """
    return (table or load_table()).classify(feature.type_name)
