"""Loader for `engagement_rules.yaml`, the minimum thread engagement table (T087).

The rule is data, not code, so an engineer can read the number that cleared or failed a
joint and override it per project. Every engagement finding cites the class it resolved
and that class's `source` line.

An unrecognised material resolves to the `unknown` class, whose `min_engagement_ratio` is
`None`: no rule applied, so the check reports the measured engagement and stays
`unresolved` rather than clearing the joint against a guessed rule (constitution
Principle I).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = ["DEFAULT_RULES_PATH", "EngagementRules", "MaterialRule", "load_rules"]

DEFAULT_RULES_PATH = Path(__file__).with_name("engagement_rules.yaml")


@dataclass(frozen=True)
class MaterialRule:
    """One material class: how deep a thread has to be, and where the number came from."""

    name: str
    min_engagement_ratio: float | None
    matches: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class EngagementRules:
    """The whole table. `material_classes` keeps the file's order; the first match wins."""

    version: int
    default_material_class: str
    material_classes: dict[str, MaterialRule]

    def for_material(self, material: str | None) -> MaterialRule:
        """Resolve a material name to its rule, case-insensitively on `matches` substrings.

        A `None`, empty or unrecognised material resolves to `default_material_class`,
        which carries no ratio.
        """
        if material:
            needle = material.lower()
            for rule in self.material_classes.values():
                if any(token in needle for token in rule.matches):
                    return rule
        return self.material_classes[self.default_material_class]


def _parse(document: object, path: Path) -> EngagementRules:
    if not isinstance(document, dict):
        raise ValueError(f"{path}: engagement rules must be a mapping")

    classes: dict[str, MaterialRule] = {}
    for name, row in document["material_classes"].items():
        ratio = row["min_engagement_ratio"]
        classes[name] = MaterialRule(
            name=name,
            min_engagement_ratio=None if ratio is None else float(ratio),
            matches=tuple(token.lower() for token in row["matches"]),
            source=row["source"],
        )

    default = document["default_material_class"]
    if default not in classes:
        raise ValueError(
            f"{path}: default_material_class {default!r} is not one of the material classes "
            f"{sorted(classes)}"
        )
    if classes[default].min_engagement_ratio is not None:
        raise ValueError(
            f"{path}: default_material_class {default!r} carries a ratio; the fallback class "
            "must apply no rule so an unknown material cannot clear a joint"
        )

    return EngagementRules(
        version=int(document["version"]),
        default_material_class=default,
        material_classes=classes,
    )


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> EngagementRules:
    return _parse(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_rules(path: Path | str | None = None) -> EngagementRules:
    """Read the engagement table; `path` defaults to the one shipped with the package.

    Results are cached per resolved path: the table is read once per process.
    """
    return _load_cached(Path(path or DEFAULT_RULES_PATH).resolve())
