"""Unit tests for the thread-engagement rule table and its loader (T087).

The rule the check applied is cited in every engagement finding, so the table is data,
not code, and an unrecognised material resolves to "no rule" rather than to a default
that could clear a joint (constitution Principle I).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.engagement_rules import (
    DEFAULT_RULES_PATH,
    EngagementRules,
    load_rules,
)

RULES_VERSION = 1


@pytest.fixture
def rules() -> EngagementRules:
    return load_rules()


def test_the_shipped_table_is_version_one(rules: EngagementRules) -> None:
    """A version bump has to be a deliberate edit: the findings cite these numbers."""
    assert rules.version == RULES_VERSION
    assert rules.default_material_class == "unknown"


def test_the_default_path_is_the_yaml_next_to_the_loader() -> None:
    assert DEFAULT_RULES_PATH.name == "engagement_rules.yaml"
    assert DEFAULT_RULES_PATH.is_file()


@pytest.mark.parametrize(
    ("material", "expected_class", "expected_ratio"),
    [
        ("AISI 1018 Steel", "steel", 1.0),
        ("Stainless Steel (ferritic)", "steel", 1.0),
        ("Cast Iron, gray", "cast_iron", 1.5),
        ("6061-T6", "aluminum", 1.5),
        ("Aluminium 5052-H32", "aluminum", 1.5),
        ("Nylon 6/6", "plastic", 2.5),
        ("PEEK", "plastic", 2.5),
    ],
)
def test_every_material_class_resolves_from_a_realistic_material_name(
    rules: EngagementRules,
    material: str,
    expected_class: str,
    expected_ratio: float,
) -> None:
    rule = rules.for_material(material)

    assert rule.name == expected_class
    assert rule.min_engagement_ratio == pytest.approx(expected_ratio)
    assert rule.source != ""


def test_every_class_in_the_table_is_reachable_by_at_least_one_of_its_own_tokens(
    rules: EngagementRules,
) -> None:
    for name, rule in rules.material_classes.items():
        if name == rules.default_material_class:
            continue
        assert rule.matches, f"{name} has no match tokens and can never be selected"
        assert rules.for_material(rule.matches[0]).name == name


def test_matching_is_case_insensitive(rules: EngagementRules) -> None:
    assert rules.for_material("ALUMINUM 6061").name == "aluminum"
    assert rules.for_material("aluminum 6061").name == "aluminum"


def test_an_unknown_material_resolves_to_the_unknown_class_with_no_ratio(
    rules: EngagementRules,
) -> None:
    rule = rules.for_material("unobtainium")

    assert rule.name == "unknown"
    assert rule.min_engagement_ratio is None


def test_a_missing_material_resolves_to_the_unknown_class(rules: EngagementRules) -> None:
    assert rules.for_material(None).min_engagement_ratio is None
    assert rules.for_material("").name == "unknown"


def test_a_material_naming_two_classes_takes_the_first_listed(rules: EngagementRules) -> None:
    """Table order is the tie-break; steel is listed first, so "steel" wins."""
    assert rules.for_material("Aluminum-clad steel").name == "steel"


def test_load_rules_reads_an_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 9\n"
        "default_material_class: unknown\n"
        "material_classes:\n"
        "  titanium:\n"
        "    min_engagement_ratio: 1.25\n"
        '    matches: ["ti-6al-4v"]\n'
        '    source: "made up for this test"\n'
        "  unknown:\n"
        "    min_engagement_ratio: null\n"
        "    matches: []\n"
        '    source: "no rule"\n',
        encoding="utf-8",
    )

    rules = load_rules(path)

    assert rules.version == 9
    assert rules.for_material("Ti-6Al-4V").min_engagement_ratio == pytest.approx(1.25)


def test_a_table_without_its_default_class_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\n"
        "default_material_class: unknown\n"
        "material_classes:\n"
        "  steel:\n"
        "    min_engagement_ratio: 1.0\n"
        '    matches: ["steel"]\n'
        '    source: "s"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown"):
        load_rules(path)
