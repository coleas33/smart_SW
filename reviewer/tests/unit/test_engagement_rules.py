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


OWNER_DECISION = "Owner decision 2026-09-23: at least 1.5 x d into steel and aluminium alike"


@pytest.mark.parametrize(
    ("material", "expected_class", "expected_ratio"),
    [
        # Steel was 1.0 x d until the owner's decision of 2026-09-23 (feature 010 T042).
        ("AISI 1018 Steel", "steel", 1.5),
        ("Stainless Steel (ferritic)", "steel", 1.5),
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


@pytest.mark.parametrize("material", ["Alloy Steel", "6061-T6"])
def test_steel_and_aluminium_are_1_5_d_citing_the_owner_decision(
    rules: EngagementRules, material: str
) -> None:
    """Feature 010 FR-013: 1.5 x d into steel and aluminium alike (research R2.14)."""
    rule = rules.for_material(material)

    assert rule.min_engagement_ratio == pytest.approx(1.5)
    assert rule.source == OWNER_DECISION


@pytest.mark.parametrize(
    ("material", "ratio", "source"),
    [
        ("Cast Iron, gray", 1.5, "Common guidance for ferrous castings"),
        ("Nylon 6/6", 2.5, "Common guidance for thermoplastics without inserts"),
    ],
)
def test_the_other_classes_are_unchanged(
    rules: EngagementRules, material: str, ratio: float, source: str
) -> None:
    rule = rules.for_material(material)

    assert (rule.min_engagement_ratio, rule.source) == (pytest.approx(ratio), source)


def test_the_file_header_records_how_the_owner_answer_was_read() -> None:
    """The answer was typed "1.td into both"; the file says it was read as 1.5 x d, so a
    wrong reading is visible where the number lives."""
    header = DEFAULT_RULES_PATH.read_text(encoding="utf-8").split("version:", 1)[0]

    assert '"1.td into both"' in header
    assert "1.5 x d" in header


def test_every_class_in_the_table_is_reachable_by_at_least_one_of_its_own_tokens(
    rules: EngagementRules,
) -> None:
    """Edited deliberately by feature 010 T062: the tokens moved to `material_classes.yaml`,
    the one classifier for engagement and density; this table keeps a ratio per class name."""
    for name in rules.material_classes:
        if name == rules.default_material_class:
            continue
        tokens = rules.classes.classes[name].matches
        assert tokens, f"{name} has no match tokens and can never be selected"
        assert rules.for_material(tokens[0]).name == name


def test_a_class_with_no_engagement_row_has_no_rule(rules: EngagementRules) -> None:
    """A class may be added to the classifier (brass, titanium) with no engagement rule; its
    engagement then stays unresolved rather than borrowing a neighbour's ratio."""
    from dataclasses import replace

    trimmed = replace(
        rules,
        material_classes={
            name: rule for name, rule in rules.material_classes.items() if name != "plastic"
        },
    )

    rule = trimmed.for_material("Nylon 6/6")

    assert (rule.name, rule.min_engagement_ratio) == ("plastic", None)
    assert rule.source == "No engagement rule for material class plastic"


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
    """Edited deliberately by feature 010 T062: the rows are ratios by class name."""
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 9\n"
        "material_classes:\n"
        "  steel:\n"
        "    min_engagement_ratio: 1.25\n"
        '    source: "made up for this test"\n',
        encoding="utf-8",
    )

    rules = load_rules(path)

    assert rules.version == 9
    assert rules.for_material("AISI 1018 Steel").min_engagement_ratio == pytest.approx(1.25)
    assert rules.for_material("6061-T6").min_engagement_ratio is None


def test_a_row_for_a_class_the_classifier_lacks_is_rejected(tmp_path: Path) -> None:
    """Edited deliberately by feature 010 T062 (was: a table without its default class): the
    classes are `material_classes.yaml`'s, so a ratio for a class it does not know is a typo
    that would silently never apply."""
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\n"
        "material_classes:\n"
        "  titanium:\n"
        "    min_engagement_ratio: 1.0\n"
        '    source: "s"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="titanium"):
        load_rules(path)


def test_a_ratio_on_the_default_class_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\n"
        "material_classes:\n"
        "  unknown:\n"
        "    min_engagement_ratio: 1.0\n"
        '    source: "s"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown"):
        load_rules(path)
