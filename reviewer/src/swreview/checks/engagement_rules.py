"""Loader for `engagement_rules.yaml`, the minimum thread engagement table (T087).

The rule is data, not code, so an engineer can read the number that cleared or failed a
joint and override it per project. Every engagement finding cites the class it resolved
and that class's `source` line.

Which class a material belongs to is `material_classes.for_material`'s answer (feature 010
research R2.16): one classifier for engagement and density, so the match tokens live in
`material_classes.yaml` and this table keeps one ratio per class name. An unrecognised
material resolves to the default class, whose `min_engagement_ratio` is `None`, and so does
a class this table carries no row for: no rule applied, so the check reports the measured
engagement and stays `unresolved` rather than clearing the joint against a guessed rule
(constitution Principle I).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from swreview.checks.material_classes import MaterialClasses, load_material_classes

__all__ = ["DEFAULT_RULES_PATH", "EngagementRules", "MaterialRule", "load_rules"]

DEFAULT_RULES_PATH = Path(__file__).with_name("engagement_rules.yaml")


@dataclass(frozen=True)
class MaterialRule:
    """One material class: how deep a thread has to be, and where the number came from."""

    name: str
    min_engagement_ratio: float | None
    source: str


@dataclass(frozen=True)
class EngagementRules:
    """The whole table: a rule per class name, resolved through the material classes."""

    version: int
    default_material_class: str
    material_classes: dict[str, MaterialRule]
    classes: MaterialClasses

    def for_material(self, material: str | None) -> MaterialRule:
        """Resolve a material name to its class (`material_classes.for_material`) and the
        class to its rule. A `None`, empty or unrecognised material resolves to the default
        class, which carries no ratio; a class with no row carries none either."""
        name = self.classes.for_material(material).name
        return self.material_classes.get(
            name,
            MaterialRule(
                name=name,
                min_engagement_ratio=None,
                source=f"No engagement rule for material class {name}",
            ),
        )


def _parse(document: object, path: Path, classes: MaterialClasses) -> EngagementRules:
    if not isinstance(document, dict):
        raise ValueError(f"{path}: engagement rules must be a mapping")

    rules: dict[str, MaterialRule] = {}
    for name, row in document["material_classes"].items():
        if name not in classes.classes:
            raise ValueError(
                f"{path}: {name!r} is not a material class of material_classes.yaml "
                f"{sorted(classes.classes)}"
            )
        ratio = row["min_engagement_ratio"]
        rules[name] = MaterialRule(
            name=name,
            min_engagement_ratio=None if ratio is None else float(ratio),
            source=row["source"],
        )

    default = classes.default_class
    if default in rules and rules[default].min_engagement_ratio is not None:
        raise ValueError(
            f"{path}: the default material class {default!r} carries a ratio; the fallback "
            "class must apply no rule so an unknown material cannot clear a joint"
        )

    return EngagementRules(
        version=int(document["version"]),
        default_material_class=default,
        material_classes=rules,
        classes=classes,
    )


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> EngagementRules:
    return _parse(yaml.safe_load(path.read_text(encoding="utf-8")), path, load_material_classes())


def load_rules(path: Path | str | None = None) -> EngagementRules:
    """Read the engagement table; `path` defaults to the one shipped with the package.

    Results are cached per resolved path: the table is read once per process. The classes
    are the shipped `material_classes.yaml`.
    """
    return _load_cached(Path(path or DEFAULT_RULES_PATH).resolve())
