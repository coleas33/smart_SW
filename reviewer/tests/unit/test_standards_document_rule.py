"""`standards.document.data_card_complete`, the one document-scope check (T045).

The only check of the sixteen that grades all three document kinds, and the only one whose
subjects are not IR rows: its subjects are the profile's data-card property **names**, each
saying whether it was absent from the card or present and blank (difference m). Five rules
are asserted here:

- **which documents it is evaluated for**: every part, assembly and drawing document whose
  **file name, taken from the path and including its extension**, matches
  `part_number.pattern` - `#` one digit, `?` one character, everything else literal,
  whole-string and case-insensitive. Never a window title: SOLIDWORKS can be configured to
  hide extensions in titles and the macro's version of this check then switches itself off
  entirely (difference l, limitation L9);
- **one finding per document**, whatever the number of blank or absent fields (difference n:
  the macro counts four for a blank card);
- **the two empty settings are skips, not passes**: an empty `part_number.pattern` or an
  empty `data_card.properties` leaves nothing to test, so the check is skipped naming the
  setting rather than passing a document nobody configured a card for;
- **`library.skip_prefixes` applies to part documents only**: an assembly under the same
  prefix is graded, as the macro graded it (`contracts/rules.md`, library prefix effects);
- **the configuration-independent property set is the one read**, and the observed text says
  so, because a value that exists only in a configuration-specific property is reported
  absent and an engineer has to be able to see why.

Every value-bearing string here comes from the fictional fixture profile (FR-001).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from swreview.checks.standards.document import DataCardFieldResult, evaluate_document
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.results import RuleResult
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.models import EvidencePackage, Gap
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    DocumentSpec,
    DrawingSpec,
    PartSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE = load_profile(FIXTURE_DIR / "profile-a.yaml")

DATA_CARD_COMPLETE = "standards.document.data_card_complete"

CONFORMING = "MR-40012"
"""A stem that makes every extension match the fictional pattern `MR-#####.SLD???`."""

NON_CONFORMING = "bracket"

PROPERTIES = tuple(PROFILE.data_card.properties)
COMPLETE: Mapping[str, str] = {name: f"value of {name}" for name in PROPERTIES}

SKIPPED_FOLDER = "catalog/gaskets"


# --- the fixtures -------------------------------------------------------------------------


def package_of(*documents: DocumentSpec, gaps: Sequence[Gap] = ()) -> EvidencePackage:
    return standards_package(documents=list(documents), profile=PROFILE, gaps=gaps)


def gap(entity_kind: str, entity_id: str | None, reason: str) -> Gap:
    return Gap(
        kind="not_extracted",
        entity_kind=entity_kind,
        entity_id=entity_id,
        reason=reason,
        error=None,
    )


def evaluate(
    package: EvidencePackage,
    document_id: str = "doc:1",
    profile: StandardsProfile = PROFILE,
) -> list[RuleResult]:
    document = next(
        checked
        for checked in graded_documents(package, profile)
        if checked.document_id == document_id
    )
    return evaluate_document(document, package, profile)


def row(results: Sequence[RuleResult], outcome: str) -> RuleResult:
    found = [result for result in results if result.outcome == outcome]
    assert len(found) == 1, (
        f"expected one {outcome!r} result, got {[result.outcome for result in results]}"
    )
    return found[0]


def outcomes(results: Sequence[RuleResult]) -> set[str]:
    return {result.outcome for result in results}


def reason(results: Sequence[RuleResult], outcome: str) -> str:
    found = row(results, outcome)
    assert found.reason is not None
    return found.reason


def observed(results: Sequence[RuleResult]) -> str:
    found = row(results, "fail")
    assert found.result is not None
    return found.result.observed


def without(*names: str) -> dict[str, str]:
    return {name: value for name, value in COMPLETE.items() if name not in names}


# --- which documents are evaluated --------------------------------------------------------


class TestWhichDocumentsAreEvaluated:
    """Every kind, decided by the file name in the path (FR-022)."""

    def test_a_conforming_part_is_evaluated(self) -> None:
        package = package_of(PartSpec(CONFORMING, properties=COMPLETE))
        assert outcomes(evaluate(package)) == {"pass"}

    def test_a_conforming_assembly_is_evaluated(self) -> None:
        package = package_of(AssemblySpec(CONFORMING, properties=without("Short Note")))
        assert outcomes(evaluate(package)) == {"fail"}

    def test_a_conforming_drawing_is_evaluated(self) -> None:
        package = package_of(DrawingSpec(CONFORMING, properties=without("Short Note")))
        assert outcomes(evaluate(package)) == {"fail"}

    def test_a_name_that_does_not_follow_the_convention_is_skipped(self) -> None:
        package = package_of(PartSpec(NON_CONFORMING, properties={}))
        results = evaluate(package)

        assert outcomes(results) == {"skip"}
        assert "convention" in reason(results, "skip")
        assert "bracket.SLDPRT" in reason(results, "skip")

    def test_the_name_is_taken_from_the_path_and_never_from_a_window_title(self) -> None:
        """Difference l: the macro switches itself off when titles hide extensions."""
        package = package_of(PartSpec(CONFORMING, properties=without("Plating Spec")))
        retitled = package.model_copy(
            update={
                "documents": [
                    row.model_copy(update={"file_name": "Part1"}) for row in package.documents
                ]
            }
        )
        assert outcomes(evaluate(retitled)) == {"fail"}

    def test_the_match_is_case_insensitive(self) -> None:
        package = package_of(PartSpec(CONFORMING.lower(), properties=COMPLETE))
        assert outcomes(evaluate(package)) == {"pass"}


# --- the failing card ---------------------------------------------------------------------


class TestAnIncompleteCard:
    """One finding per document, naming each property and which of the two it was."""

    def test_an_absent_and_a_blank_property_are_distinguished(self) -> None:
        package = package_of(
            PartSpec(CONFORMING, properties={**without("Short Note"), "Plating Spec": "   "})
        )
        results = evaluate(package)
        result = row(results, "fail")

        assert result.subjects == ["property:Short Note", "property:Plating Spec"]
        assert "Short Note" in observed(results)
        assert "absent" in observed(results)
        assert "Plating Spec" in observed(results)
        assert "blank" in observed(results)

    def test_whitespace_only_counts_as_blank(self) -> None:
        package = package_of(PartSpec(CONFORMING, properties={**COMPLETE, "Raw Stock Code": "\t "}))
        results = evaluate(package)

        assert row(results, "fail").subjects == ["property:Raw Stock Code"]
        assert "blank" in observed(results)

    def test_a_wholly_blank_card_is_one_finding(self) -> None:
        """Difference n: the macro counts four defects for one blank card."""
        package = package_of(PartSpec(CONFORMING, properties={}))
        results = evaluate(package)
        result = row(results, "fail")

        assert len(result.subjects) == len(PROPERTIES)
        assert result.result is not None
        assert result.result.status == "demonstrated"
        assert len([item for item in results if item.outcome == "fail"]) == 1

    def test_the_observed_text_names_the_property_scope_it_read(self) -> None:
        package = package_of(
            PartSpec(
                CONFORMING,
                properties=without("Short Note"),
                config_properties={"Default": {"Short Note": "only in this configuration"}},
            )
        )
        results = evaluate(package)

        assert "configuration-independent" in observed(results)

    def test_a_complete_card_is_checked(self) -> None:
        package = package_of(PartSpec(CONFORMING, properties=COMPLETE))
        assert outcomes(evaluate(package)) == {"pass"}

    def test_the_resolved_value_is_the_one_compared(self) -> None:
        """`GetAll3`'s resolved value is what a drawing or a BOM would show."""
        result = DataCardFieldResult(property="Short Note", state="present", resolved_value="A")
        assert result.state == "present"
        assert DataCardFieldResult("Short Note", "absent", None).resolved_value is None


# --- the skips and the one unresolved row -------------------------------------------------


class TestSkippedAndUnresolved:
    def test_an_empty_pattern_skips_the_check_naming_the_setting(self) -> None:
        profile = PROFILE.model_copy(
            update={"part_number": PROFILE.part_number.model_copy(update={"pattern": ""})}
        )
        package = standards_package(
            documents=[PartSpec(CONFORMING, properties={})], profile=profile
        )
        results = evaluate(package, profile=profile)

        assert outcomes(results) == {"skip"}
        assert "part_number.pattern" in reason(results, "skip")

    def test_an_empty_property_list_skips_the_check_naming_the_setting(self) -> None:
        profile = PROFILE.model_copy(
            update={"data_card": PROFILE.data_card.model_copy(update={"properties": []})}
        )
        package = standards_package(
            documents=[PartSpec(CONFORMING, properties={})], profile=profile
        )
        results = evaluate(package, profile=profile)

        assert outcomes(results) == {"skip"}
        assert "data_card.properties" in reason(results, "skip")

    def test_a_library_part_is_skipped_naming_the_prefix(self) -> None:
        package = package_of(PartSpec(CONFORMING, folder=SKIPPED_FOLDER, properties={}))
        results = evaluate(package)

        assert outcomes(results) == {"skip"}
        assert "catalog/gaskets/" in reason(results, "skip")

    def test_an_assembly_under_a_library_prefix_is_graded(self) -> None:
        """`library.skip_prefixes` applies to part documents only."""
        package = package_of(AssemblySpec(CONFORMING, folder=SKIPPED_FOLDER, properties={}))
        assert outcomes(evaluate(package)) == {"fail"}

    def test_unread_custom_properties_are_unresolved(self) -> None:
        package = package_of(
            PartSpec(CONFORMING, properties={}),
            gaps=[
                gap(
                    "document",
                    "doc:1",
                    "'MR-40012.SLDPRT' is not open in SOLIDWORKS, so its properties, material "
                    "and mass were not read.",
                )
            ],
        )
        results = evaluate(package)

        assert outcomes(results) == {"unresolved"}
        assert "not open in SOLIDWORKS" in reason(results, "unresolved")

    @pytest.mark.parametrize(
        "mass_gap",
        [
            "CreateMassProperty2 returned nothing; mass and volume are unknown.",
            "Mass properties could not be recalculated (a surface-only model has none); "
            "mass and volume are unknown.",
            "The model has no solid volume (surface bodies only); mass and volume are "
            "unknown.",
            "The mass properties are OVERRIDDEN in SOLIDWORKS; the values recorded were "
            "typed by a user, not computed from the geometry.",
        ],
    )
    def test_a_mass_property_gap_does_not_suppress_the_data_card(self, mass_gap: str) -> None:
        """`PropertyDumper` records four `document` gaps that speak for the **mass**.

        A surface-only part and a part whose mass an engineer deliberately overrode each
        carry one of them and their custom properties were read perfectly well, so reading
        the gap **kind** alone would report the card unresolved with a false reason on a
        large share of real parts.
        """
        package = package_of(
            PartSpec(CONFORMING, properties=COMPLETE),
            gaps=[gap("document", "doc:1", mass_gap)],
        )

        assert outcomes(evaluate(package)) == {"pass"}

    @pytest.mark.parametrize("state", ["suppressed", "lightweight", "unloaded"])
    def test_a_document_reached_only_through_unresolved_instances_is_unresolved(
        self, state: str
    ) -> None:
        package = package_of(
            AssemblySpec(
                "top",
                components=[
                    ComponentSpec("p1", CONFORMING, suppression=state)  # type: ignore[arg-type]
                ],
            ),
            PartSpec(CONFORMING, properties={}),
        )
        results = evaluate(package, "doc:2")

        assert outcomes(results) == {"unresolved"}
        assert "cmp:0002" in reason(results, "unresolved")
        assert state in reason(results, "unresolved")

    def test_the_check_id_is_the_contracts(self) -> None:
        package = package_of(PartSpec(CONFORMING, properties=COMPLETE))
        assert {result.rule_id for result in evaluate(package)} == {DATA_CARD_COMPLETE}
