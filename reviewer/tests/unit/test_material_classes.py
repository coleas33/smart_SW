"""One classifier for every material name (feature 010 T062, `contracts/mass-material.md`
section 1, research R2.16).

Thread engagement and the density check both ask what class a material is, and two token
lists would drift, so the tokens moved out of `engagement_rules.yaml` into
`material_classes.yaml`. The move must change no classification: every token the
engagement table carried until 2026-09-23 is spelled out below and must resolve to the
class it resolved to then.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.engagement_rules import load_rules
from swreview.checks.material_classes import (
    DEFAULT_CLASSES_PATH,
    MaterialClasses,
    for_material,
    load_material_classes,
)

ENGAGEMENT_TOKENS_UNTIL_2026_09_23: dict[str, tuple[str, ...]] = {
    "steel": ("steel", "stainless", "aisi", "sae 10", "4140", "4340", "a36", "s355", "17-4"),
    "cast_iron": ("cast iron", "gray iron", "ductile", "gg", "ggg", "astm a48"),
    "aluminum": ("aluminum", "aluminium", "6061", "7075", "5052", "2024", "al "),
    "plastic": (
        "abs", "nylon", "pa6", "pa66", "delrin", "acetal", "pom", "peek", "polycarbonate",
        "pc", "pla", "petg",
    ),
}
"""`engagement_rules.yaml`'s `matches`, as they stood before the move, typed out once."""


@pytest.fixture(scope="module")
def classes() -> MaterialClasses:
    return load_material_classes()


def test_the_shipped_table_loads_in_the_engagement_tables_order(classes: MaterialClasses) -> None:
    assert DEFAULT_CLASSES_PATH.name == "material_classes.yaml"
    assert classes.version == 1
    assert list(classes.classes) == ["steel", "cast_iron", "aluminum", "plastic", "unknown"]
    assert classes.default_class == "unknown"


@pytest.mark.parametrize(
    ("expected", "token"),
    [
        (name, token)
        for name, tokens in ENGAGEMENT_TOKENS_UNTIL_2026_09_23.items()
        for token in tokens
    ],
)
def test_every_token_the_engagement_table_carried_resolves_to_the_same_class(
    classes: MaterialClasses, expected: str, token: str
) -> None:
    """Table-driven, so the move changes no classification: the same class as before, from
    the classifier and through the engagement rules alike."""
    assert classes.for_material(token).name == expected
    assert load_rules().for_material(token).name == expected


def test_the_tokens_moved_unchanged(classes: MaterialClasses) -> None:
    moved = {
        name: item.matches for name, item in classes.classes.items() if name != "unknown"
    }

    assert moved == ENGAGEMENT_TOKENS_UNTIL_2026_09_23


@pytest.mark.parametrize(
    ("material", "expected"),
    [
        ("Alloy Steel", "steel"),
        ("6061-T6", "aluminum"),
        ("Gray Cast Iron", "cast_iron"),
        ("PEEK", "plastic"),
        ("Aluminum-clad steel", "steel"),
        ("unobtainium", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_realistic_names_classify_first_match_in_file_order(
    material: str | None, expected: str
) -> None:
    assert for_material(material).name == expected


@pytest.mark.parametrize(
    ("name", "low", "high"),
    [("steel", 7600, 8100), ("aluminum", 2600, 2850), ("cast_iron", 6800, 7400),
     ("plastic", 850, 2200)],
)
def test_each_class_carries_a_density_range_with_a_source(
    classes: MaterialClasses, name: str, low: float, high: float
) -> None:
    item = classes.classes[name]

    assert item.density_kg_m3 == (low, high)
    assert item.source


def test_the_default_class_carries_no_range_and_no_tokens(classes: MaterialClasses) -> None:
    default = classes.classes[classes.default_class]

    assert default.density_kg_m3 is None and default.matches == ()


def test_the_no_material_density_is_solidworks_default_with_its_source(
    classes: MaterialClasses,
) -> None:
    assert classes.no_material_density_kg_m3 == 1000.0
    assert "1000 kg/m3" in classes.no_material_density_source


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "classes.yaml"
    path.write_text(body, encoding="utf-8")
    return path


HEADER = (
    "version: 1\ndefault_class: unknown\nno_material_density_kg_m3: 1000\n"
    "no_material_density_source: s\nclasses:\n"
)


@pytest.mark.parametrize("bad", ["[8100, 7600]", "[0, 10]", "[7600]", "7600"])
def test_an_unusable_range_is_refused(tmp_path: Path, bad: str) -> None:
    path = _write(
        tmp_path,
        HEADER
        + f"  steel:\n    matches: [steel]\n    density_kg_m3: {bad}\n    source: s\n"
        + "  unknown:\n    matches: []\n    density_kg_m3: null\n    source: s\n",
    )

    with pytest.raises(ValueError, match="steel"):
        load_material_classes(path)


def test_a_default_class_with_a_range_is_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path, HEADER + "  unknown:\n    matches: []\n    density_kg_m3: [1, 2]\n    source: s\n"
    )

    with pytest.raises(ValueError, match="default_class"):
        load_material_classes(path)


def test_a_missing_section_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 1\ndefault_class: unknown\nclasses: {}\n")

    with pytest.raises(ValueError, match="no_material_density_kg_m3"):
        load_material_classes(path)
