"""Loader for `material_classes.yaml`: one classifier for every material name (feature 010).

`contracts/mass-material.md` section 1. Thread engagement and the mass checks both ask what
class a material belongs to - steel, aluminium, cast iron, plastic - and they must get the
same answer, so there is one table of match tokens and one function, `for_material`, that
both call (research R2.16). The class carries a density range for the mass checks; the
engagement ratio stays in `engagement_rules.yaml`, looked up by the class name this returns.

An unrecognised, empty or missing material resolves to the default class, which carries no
range and no engagement rule: nothing is cleared against a guessed class (Principle I).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = [
    "DEFAULT_CLASSES_PATH",
    "MaterialClass",
    "MaterialClasses",
    "for_material",
    "load_material_classes",
]

DEFAULT_CLASSES_PATH = Path(__file__).with_name("material_classes.yaml")


@dataclass(frozen=True)
class MaterialClass:
    """One class: the tokens that name it, the densities it can have, and their source."""

    name: str
    matches: tuple[str, ...]
    density_kg_m3: tuple[float, float] | None
    source: str


@dataclass(frozen=True)
class MaterialClasses:
    """The whole table, in file order (the first match wins)."""

    version: int
    default_class: str
    no_material_density_kg_m3: float
    no_material_density_source: str
    classes: Mapping[str, MaterialClass]

    def for_material(self, material: str | None) -> MaterialClass:
        """The class whose token is a substring of the lower-cased `material`, the first in
        file order; the default class for a `None`, empty or unrecognised material."""
        if material:
            needle = material.lower()
            for item in self.classes.values():
                if any(token in needle for token in item.matches):
                    return item
        return self.classes[self.default_class]


def _range(value: object, name: str, path: Path) -> tuple[float, float] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, int | float) and not isinstance(item, bool) for item in value)
        or not 0 < value[0] < value[1]
    ):
        raise ValueError(f"{path}: {name} density_kg_m3 must be [low, high] with 0 < low < high")
    return float(value[0]), float(value[1])


def _parse(document: object, path: Path) -> MaterialClasses:
    if not isinstance(document, Mapping):
        raise ValueError(f"{path}: the material classes must be a mapping")
    for key in (
        "version",
        "default_class",
        "no_material_density_kg_m3",
        "no_material_density_source",
        "classes",
    ):
        if key not in document:
            raise ValueError(f"{path}: {key} is missing")
    classes: dict[str, MaterialClass] = {}
    for name, row in document["classes"].items():
        for key in ("matches", "density_kg_m3", "source"):
            if key not in row:
                raise ValueError(f"{path}: class {name} carries no {key}")
        classes[str(name)] = MaterialClass(
            name=str(name),
            matches=tuple(str(token).lower() for token in row["matches"]),
            density_kg_m3=_range(row["density_kg_m3"], str(name), path),
            source=str(row["source"]),
        )
    default = document["default_class"]
    if default not in classes:
        raise ValueError(f"{path}: default_class {default!r} is not one of {sorted(classes)}")
    if classes[default].density_kg_m3 is not None or classes[default].matches:
        raise ValueError(
            f"{path}: default_class {default!r} must carry no tokens and no range, so an "
            "unrecognised material is judged against nothing"
        )
    density = document["no_material_density_kg_m3"]
    if isinstance(density, bool) or not isinstance(density, int | float) or density <= 0:
        raise ValueError(f"{path}: no_material_density_kg_m3 must be a positive number")
    return MaterialClasses(
        version=int(document["version"]),
        default_class=str(default),
        no_material_density_kg_m3=float(density),
        no_material_density_source=" ".join(str(document["no_material_density_source"]).split()),
        classes=classes,
    )


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> MaterialClasses:
    return _parse(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_material_classes(path: Path | str | None = None) -> MaterialClasses:
    """Read the material classes; `path` defaults to the file beside this module. Cached."""
    return _load_cached(Path(path or DEFAULT_CLASSES_PATH).resolve())


def for_material(material: str | None, classes: MaterialClasses | None = None) -> MaterialClass:
    """The one classification of a material name, from the shipped table by default."""
    return (classes or load_material_classes()).for_material(material)
