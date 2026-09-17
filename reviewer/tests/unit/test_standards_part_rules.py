"""The four part-scope checks of `contracts/rules.md` (T043).

One class per check, each covering the four columns the contract gives it, with the subjects
and the observed text asserted. Four rules run through every class:

- **every feature and every sketch the package records is a subject, at any depth**
  (difference z). The macro walks only the top level of the tree, so a defect inside a
  folder or consumed by another feature is invisible to it;
- **the library prefix lists are matched independently** (FR-006). `skip_prefixes` skips the
  four part checks; `sketch_exempt_prefixes` skips one of them and nothing else; an **empty**
  list exempts nothing and is never itself a skip;
- **a reading that was not made is unresolved**, naming what was missing (FR-029) - and for
  the two rebuild-error checks the finding says the counts are as the document stood and
  that nothing was rebuilt (difference g);
- **FR-005's document-evidence half**: a part reached only through suppressed, lightweight
  or unloaded instances is unresolved for all four checks, naming the component and its
  state, because the package's readings are not readings of a document nobody opened.

Every value-bearing string here comes from the fictional fixture profile (FR-001).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from swreview.checks.standards.part import evaluate_part
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.results import RuleResult
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.models import EvidencePackage, Gap
from tests.support.features import FeatureSpec, SketchSpec
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    CutListSpec,
    DocumentSpec,
    PartSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE = load_profile(FIXTURE_DIR / "profile-a.yaml")

SKETCHES_FULLY_DEFINED = "standards.part.sketches_fully_defined"
REBUILD_ERRORS = "standards.part.rebuild_errors"
MATERIAL_ASSIGNED = "standards.part.material_assigned"
CUT_LIST_EXCLUDED = "standards.part.cut_list_excluded"

PART_CHECKS = (SKETCHES_FULLY_DEFINED, REBUILD_ERRORS, MATERIAL_ASSIGNED, CUT_LIST_EXCLUDED)

UNDER_DEFINED = 2
FULLY_DEFINED = 3
OVER_DEFINED = 4
SOLVER_UNKNOWN = 1

SKIPPED_FOLDER = "catalog/gaskets"
"""Under `library.skip_prefixes` of the fictional profile - and under
`sketch_exempt_prefixes` too, which is what makes the two lists independent testable."""

SKETCH_EXEMPT_FOLDER = "catalog/brackets"
"""Under `sketch_exempt_prefixes` (`catalog/`) and under no skip prefix."""

MATERIAL_CONFIGURATION = PROFILE.material.configuration


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
    """Every part check over one graded part document of `package`."""
    document = next(
        checked
        for checked in graded_documents(package, profile)
        if checked.document_id == document_id
    )
    return evaluate_part(document, package, profile)


def row(results: Sequence[RuleResult], check: str, outcome: str) -> RuleResult:
    found = [
        result for result in results if result.rule_id == check and result.outcome == outcome
    ]
    assert len(found) == 1, (
        f"expected one {outcome!r} result for {check}, got "
        f"{[(result.rule_id, result.outcome) for result in results if result.rule_id == check]}"
    )
    return found[0]


def outcomes(results: Sequence[RuleResult], check: str) -> set[str]:
    return {result.outcome for result in results if result.rule_id == check}


def observed(results: Sequence[RuleResult], check: str) -> str:
    result = row(results, check, "fail")
    assert result.result is not None
    return result.result.observed


def reason(results: Sequence[RuleResult], check: str, outcome: str) -> str:
    found = row(results, check, outcome)
    assert found.reason is not None
    return found.reason


def sketch(name: str, status: int | None = FULLY_DEFINED, text: int | None = 0) -> FeatureSpec:
    return FeatureSpec(
        name, "ProfileFeature", sketch=SketchSpec(raw_status=status, text_segments=text)
    )


# --- standards.part.sketches_fully_defined ------------------------------------------------


class TestSketchesFullyDefined:
    """FR-014: every recorded sketch, at any depth, with the chain that reaches it."""

    def part(
        self, *features: FeatureSpec, folder: str = "", gaps: Sequence[Gap] = ()
    ) -> EvidencePackage:
        return package_of(
            PartSpec(
                "plate",
                folder=folder,
                configuration=MATERIAL_CONFIGURATION,
                features=features,
            ),
            gaps=gaps,
        )

    def test_an_under_defined_sketch_fails_naming_its_parent_chain(self) -> None:
        package = self.part(
            FeatureSpec(
                "Boss-Extrude1",
                "Extrusion",
                contents=(sketch("Sketch1", UNDER_DEFINED),),
            ),
        )
        results = evaluate(package)
        result = row(results, SKETCHES_FULLY_DEFINED, "fail")

        assert result.result is not None
        assert "Sketch1" in result.result.observed
        assert "Boss-Extrude1" in result.result.observed
        assert len(result.subjects) == 1

    def test_a_sketch_at_depth_is_a_subject(self) -> None:
        """Difference z: the macro walks the top level only."""
        package = self.part(
            FeatureSpec(
                "Folder1",
                "FtrFolder",
                contents=(
                    FeatureSpec(
                        "Cut-Extrude1",
                        "Extrusion",
                        contents=(sketch("Sketch2", UNDER_DEFINED),),
                    ),
                ),
            ),
        )
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"fail"}
        assert "Folder1" in observed(results, SKETCHES_FULLY_DEFINED)
        assert "Cut-Extrude1" in observed(results, SKETCHES_FULLY_DEFINED)

    def test_a_hole_wizard_sketch_names_that_feature(self) -> None:
        package = self.part(
            FeatureSpec(
                "HoleWizard1", "HoleWzd", contents=(sketch("Sketch3", UNDER_DEFINED),)
            ),
        )
        results = evaluate(package)

        assert "hole-wizard" in observed(results, SKETCHES_FULLY_DEFINED)
        assert "HoleWizard1" in observed(results, SKETCHES_FULLY_DEFINED)

    @pytest.mark.parametrize("status", [FULLY_DEFINED, OVER_DEFINED])
    def test_a_defined_sketch_is_checked(self, status: int) -> None:
        package = self.part(sketch("Sketch1", status))
        assert outcomes(evaluate(package), SKETCHES_FULLY_DEFINED) == {"pass"}

    def test_a_sketch_carrying_text_is_skipped_naming_the_exemption(self) -> None:
        package = self.part(sketch("Sketch1", UNDER_DEFINED, text=2))
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"skip"}
        assert "text" in reason(results, SKETCHES_FULLY_DEFINED, "skip")

    def test_a_skip_prefix_skips_the_whole_check_naming_the_prefix(self) -> None:
        package = self.part(sketch("Sketch1", UNDER_DEFINED), folder=SKIPPED_FOLDER)
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"skip"}
        assert "catalog/gaskets/" in reason(results, SKETCHES_FULLY_DEFINED, "skip")

    def test_a_sketch_exempt_prefix_skips_the_whole_check_naming_the_prefix(self) -> None:
        package = self.part(sketch("Sketch1", UNDER_DEFINED), folder=SKETCH_EXEMPT_FOLDER)
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"skip"}
        assert "catalog/" in reason(results, SKETCHES_FULLY_DEFINED, "skip")
        assert "sketch_exempt_prefixes" in reason(results, SKETCHES_FULLY_DEFINED, "skip")

    def test_an_empty_sketch_exempt_list_exempts_nothing(self) -> None:
        """An empty list is a statement that no part is exempt, never a skip of its own."""
        profile = PROFILE.model_copy(
            update={
                "library": PROFILE.library.model_copy(update={"sketch_exempt_prefixes": []})
            }
        )
        package = standards_package(
            documents=[
                PartSpec(
                    "plate",
                    folder=SKETCH_EXEMPT_FOLDER,
                    configuration=MATERIAL_CONFIGURATION,
                    features=[sketch("Sketch1", UNDER_DEFINED)],
                )
            ],
            profile=profile,
        )
        assert outcomes(evaluate(package, profile=profile), SKETCHES_FULLY_DEFINED) == {"fail"}

    def test_a_part_with_no_sketches_is_skipped(self) -> None:
        package = self.part(FeatureSpec("Boss-Extrude1", "Extrusion"))
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"skip"}
        assert "no sketches" in reason(results, SKETCHES_FULLY_DEFINED, "skip")

    def test_a_part_whose_feature_tree_was_lost_is_unresolved_not_skipped(self) -> None:
        """A tree the dump lost is not a part with no sketches (FR-029)."""
        package = self.part(
            gaps=[
                gap(
                    "feature_tree_unavailable",
                    "doc:1",
                    "The feature tree of plate.SLDPRT was not read: the walk of its feature "
                    "tree failed.",
                )
            ]
        )
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"unresolved"}
        assert "did not read its feature tree" in reason(
            results, SKETCHES_FULLY_DEFINED, "unresolved"
        )

    def test_a_part_that_records_features_is_skipped_though_a_phase_gap_stands(self) -> None:
        """The tree was read for this part: what it holds is the answer, not the gap."""
        package = self.part(
            FeatureSpec("Boss-Extrude1", "Extrusion"),
            gaps=[gap("feature", None, "Failed to read the part feature trees.")],
        )

        assert outcomes(evaluate(package), SKETCHES_FULLY_DEFINED) == {"skip"}

    @pytest.mark.parametrize("status", [None, SOLVER_UNKNOWN])
    def test_an_unread_status_is_unresolved(self, status: int | None) -> None:
        package = package_of(
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                features=[sketch("Sketch1", status)],
            ),
            gaps=[gap("sketch_status", "feat:0001", "GetConstrainedStatus threw")],
        )
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"unresolved"}
        assert "GetConstrainedStatus threw" in reason(results, SKETCHES_FULLY_DEFINED, "unresolved")

    def test_an_unread_text_segment_count_is_unresolved(self) -> None:
        """The exemption can then neither be applied nor ruled out."""
        package = package_of(
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                features=[sketch("Sketch1", UNDER_DEFINED, text=None)],
            ),
            gaps=[gap("sketch_text", "feat:0001", "GetSketchTextSegments threw")],
        )
        results = evaluate(package)

        assert outcomes(results, SKETCHES_FULLY_DEFINED) == {"unresolved"}
        assert "GetSketchTextSegments threw" in reason(
            results, SKETCHES_FULLY_DEFINED, "unresolved"
        )


# --- standards.part.rebuild_errors --------------------------------------------------------


class TestPartRebuildErrors:
    """FR-015: any non-zero feature code at any depth, or a non-zero document count."""

    def part(
        self,
        *features: FeatureSpec,
        folder: str = "",
        count: int | None = 0,
        gaps: Sequence[Gap] = (),
    ) -> EvidencePackage:
        return package_of(
            PartSpec(
                "plate",
                folder=folder,
                configuration=MATERIAL_CONFIGURATION,
                rebuild_error_count=count,
                features=features,
            ),
            gaps=gaps,
        )

    def test_a_feature_error_code_fails_naming_the_code_and_the_chain(self) -> None:
        package = self.part(
            FeatureSpec(
                "Boss-Extrude1",
                "Extrusion",
                contents=(FeatureSpec("Fillet1", "Fillet", error_code=419),),
            ),
        )
        results = evaluate(package)
        result = row(results, REBUILD_ERRORS, "fail")

        assert result.result is not None
        assert "Fillet1" in result.result.observed
        assert "419" in result.result.observed
        assert "Boss-Extrude1" in result.result.observed
        assert "nothing was rebuilt" in result.result.observed
        assert "counts as the document stood; nothing was rebuilt" in result.result.coverage_limits

    def test_a_warning_code_still_counts_and_is_named(self) -> None:
        """Difference u: the macro ignores the warning out-parameter, so a warning counts
        as an error; this feature keeps the condition and names the code."""
        package = self.part(FeatureSpec("Fillet1", "Fillet", error_code=2))
        assert "2" in observed(evaluate(package), REBUILD_ERRORS)

    def test_a_non_zero_document_count_fails_naming_the_count(self) -> None:
        package = self.part(FeatureSpec("Boss-Extrude1", "Extrusion"), count=4)
        results = evaluate(package)
        result = row(results, REBUILD_ERRORS, "fail")

        assert "4" in observed(results, REBUILD_ERRORS)
        assert "doc:1" in result.subjects

    def test_every_code_zero_and_a_zero_count_is_checked(self) -> None:
        package = self.part(FeatureSpec("Boss-Extrude1", "Extrusion"), count=0)
        assert outcomes(evaluate(package), REBUILD_ERRORS) == {"pass"}

    def test_a_part_with_no_features_and_a_zero_count_still_lands_in_a_bucket(self) -> None:
        """`contracts/rules.md`: every check lands in at least one bucket per document.

        No feature reaches a subject and the document count is zero, so without the
        terminal branch this check returns nothing at all and simply disappears for the
        document - an absence that reads as neither a pass nor a skip.
        """
        results = [
            result for result in evaluate(self.part(count=0)) if result.rule_id == REBUILD_ERRORS
        ]

        assert len(results) == 1
        assert results[0].outcome == "pass"
        assert results[0].subjects == ["doc:1"]

    def test_a_part_with_no_features_and_a_lost_feature_tree_is_unresolved(self) -> None:
        """A tree the dump lost is not a part with no features (FR-029)."""
        package = self.part(
            count=0,
            gaps=[
                gap(
                    "feature_tree_unavailable",
                    None,
                    "The part feature trees were not read: the dump was run with "
                    "--features none.",
                )
            ],
        )
        results = evaluate(package)

        assert outcomes(results, REBUILD_ERRORS) == {"unresolved"}
        assert "--features none" in reason(results, REBUILD_ERRORS, "unresolved")

    def test_a_dropped_feature_tree_for_this_document_is_unresolved(self) -> None:
        package = self.part(
            count=0,
            gaps=[
                gap(
                    "feature",
                    "doc:1",
                    "Failed to walk the feature tree of plate.SLDPRT.",
                )
            ],
        )
        results = evaluate(package)

        assert outcomes(results, REBUILD_ERRORS) == {"unresolved"}
        assert "walk the feature tree" in reason(results, REBUILD_ERRORS, "unresolved")

    def test_a_lost_tree_and_an_unread_count_name_the_document_once(self) -> None:
        package = self.part(
            count=None,
            gaps=[gap("feature", None, "Failed to read the part feature trees.")],
        )
        result = row(evaluate(package), REBUILD_ERRORS, "unresolved")

        assert result.subjects == ["doc:1"]
        assert "did not read its feature tree" in (result.reason or "")
        assert "rebuild-error count" in (result.reason or "")

    def test_an_unread_feature_code_is_unresolved(self) -> None:
        package = self.part(
            FeatureSpec("Boss-Extrude1", "Extrusion", error_code=None),
            gaps=[gap("feature", "feat:0001", "GetErrorCode2 threw")],
        )
        results = evaluate(package)

        assert outcomes(results, REBUILD_ERRORS) == {"unresolved"}
        assert "GetErrorCode2 threw" in reason(results, REBUILD_ERRORS, "unresolved")

    def test_an_unread_document_count_is_unresolved_once(self) -> None:
        package = self.part(FeatureSpec("Boss-Extrude1", "Extrusion"), count=None)
        result = row(evaluate(package), REBUILD_ERRORS, "unresolved")

        assert result.subjects == ["doc:1"]

    def test_a_skip_prefix_skips_the_whole_check(self) -> None:
        package = self.part(
            FeatureSpec("Boss-Extrude1", "Extrusion", error_code=419),
            folder=SKIPPED_FOLDER,
            count=3,
        )
        results = evaluate(package)

        assert outcomes(results, REBUILD_ERRORS) == {"skip"}
        assert "catalog/gaskets/" in reason(results, REBUILD_ERRORS, "skip")

    def test_it_is_never_skipped_otherwise(self) -> None:
        package = self.part(folder=SKETCH_EXEMPT_FOLDER)
        assert "skip" not in outcomes(evaluate(package), REBUILD_ERRORS)


# --- standards.part.material_assigned -----------------------------------------------------


class TestMaterialAssigned:
    """FR-016: all four cells of the truth table, two of them failing (difference b)."""

    def part(self, **fields: object) -> EvidencePackage:
        return package_of(
            PartSpec("plate", configuration=MATERIAL_CONFIGURATION, **fields)  # type: ignore[arg-type]
        )

    def test_no_material_and_no_mass_override_fails(self) -> None:
        """The macro's dead branch: this cell is never reported by it (limitation L1)."""
        results = evaluate(self.part(material=None, mass_overridden=False))
        result = row(results, MATERIAL_ASSIGNED, "fail")

        assert result.result is not None
        assert "no material" in result.result.observed
        assert MATERIAL_CONFIGURATION in result.result.observed
        assert "not overridden" in result.result.observed

    def test_no_material_with_a_deliberate_mass_override_is_checked(self) -> None:
        results = evaluate(self.part(material=None, mass_overridden=True))
        assert outcomes(results, MATERIAL_ASSIGNED) == {"pass"}

    def test_a_material_with_no_mass_override_is_checked(self) -> None:
        results = evaluate(self.part(material="Bronze C-4", mass_overridden=False))
        assert outcomes(results, MATERIAL_ASSIGNED) == {"pass"}

    def test_a_material_and_a_mass_override_fails_naming_both(self) -> None:
        results = evaluate(self.part(material="Bronze C-4", mass_overridden=True))
        result = row(results, MATERIAL_ASSIGNED, "fail")

        assert result.result is not None
        assert "Bronze C-4" in result.result.observed
        assert "overridden" in result.result.observed
        assert "not computed from the geometry" in result.result.observed

    def test_a_material_read_in_another_configuration_is_unresolved_naming_both(self) -> None:
        package = package_of(
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                configurations=[MATERIAL_CONFIGURATION, "As Welded"],
                material="Bronze C-4",
                material_configuration="As Welded",
            )
        )
        results = evaluate(package)

        assert outcomes(results, MATERIAL_ASSIGNED) == {"unresolved"}
        assert "As Welded" in reason(results, MATERIAL_ASSIGNED, "unresolved")
        assert MATERIAL_CONFIGURATION in reason(results, MATERIAL_ASSIGNED, "unresolved")

    def test_a_document_with_no_such_configuration_is_unresolved_naming_both(self) -> None:
        package = package_of(
            PartSpec(
                "plate",
                configuration="As Welded",
                configurations=["As Welded"],
                material="Bronze C-4",
            )
        )
        results = evaluate(package)

        assert outcomes(results, MATERIAL_ASSIGNED) == {"unresolved"}
        assert "As Welded" in reason(results, MATERIAL_ASSIGNED, "unresolved")
        assert MATERIAL_CONFIGURATION in reason(results, MATERIAL_ASSIGNED, "unresolved")

    def test_an_unread_mass_override_is_unresolved(self) -> None:
        package = package_of(
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                material="Bronze C-4",
                mass_overridden=None,
            ),
            gaps=[gap("mass_override", "doc:1", "OverrideMass threw")],
        )
        results = evaluate(package)

        assert outcomes(results, MATERIAL_ASSIGNED) == {"unresolved"}
        assert "OverrideMass threw" in reason(results, MATERIAL_ASSIGNED, "unresolved")

    def test_an_unread_material_is_unresolved_rather_than_no_material(self) -> None:
        package = package_of(
            PartSpec("plate", configuration=MATERIAL_CONFIGURATION, material=None),
            gaps=[
                gap(
                    "document",
                    "doc:1",
                    "'plate.SLDPRT' is not open in SOLIDWORKS, so its properties, material "
                    "and mass were not read.",
                )
            ],
        )
        results = evaluate(package)

        assert outcomes(results, MATERIAL_ASSIGNED) == {"unresolved"}
        assert "not open in SOLIDWORKS" in reason(results, MATERIAL_ASSIGNED, "unresolved")

    def test_a_skip_prefix_skips_the_whole_check(self) -> None:
        package = package_of(
            PartSpec(
                "plate",
                folder=SKIPPED_FOLDER,
                configuration=MATERIAL_CONFIGURATION,
                material=None,
                mass_overridden=False,
            )
        )
        results = evaluate(package)

        assert outcomes(results, MATERIAL_ASSIGNED) == {"skip"}
        assert "catalog/gaskets/" in reason(results, MATERIAL_ASSIGNED, "skip")

    def test_an_overridden_mass_is_checked_though_its_document_gap_is_recorded(self) -> None:
        """Truth table row 2 on real data: `ReadMass` records this gap for **every** part
        whose mass is overridden, so reading the `document` gap kind alone would make the
        (no material, overridden) = checked cell unreachable."""
        package = package_of(
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                material=None,
                mass_overridden=True,
            ),
            gaps=[
                gap(
                    "document",
                    "doc:1",
                    "The mass properties are OVERRIDDEN in SOLIDWORKS; the values recorded "
                    "were typed by a user, not computed from the geometry.",
                )
            ],
        )

        assert outcomes(evaluate(package), MATERIAL_ASSIGNED) == {"pass"}

    def test_a_surface_only_part_with_no_material_still_fails(self) -> None:
        """Difference b, the macro's dead branch: `ReadMass` records a `document` gap for
        every surface-only part, and suppressing the check on it would hide the defect."""
        package = package_of(
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                material=None,
                mass_overridden=False,
            ),
            gaps=[
                gap(
                    "document",
                    "doc:1",
                    "The model has no solid volume (surface bodies only); mass and volume "
                    "are unknown.",
                )
            ],
        )
        results = evaluate(package)

        assert outcomes(results, MATERIAL_ASSIGNED) == {"fail"}
        assert "no material is assigned" in observed(results, MATERIAL_ASSIGNED)


# --- standards.part.cut_list_excluded -----------------------------------------------------


class TestCutListExcluded:
    """FR-017: every displayed cut-list item is excluded from the cut list."""

    def part(
        self, *items: CutListSpec, folder: str = "", gaps: Sequence[Gap] = ()
    ) -> EvidencePackage:
        return package_of(
            PartSpec(
                "plate",
                folder=folder,
                configuration=MATERIAL_CONFIGURATION,
                cut_list=items,
            ),
            gaps=gaps,
        )

    def test_an_item_that_is_not_excluded_fails_naming_it_and_its_folder(self) -> None:
        package = self.part(
            CutListSpec("Tube 40x40", folder_name="Cut-List-Item1", excluded_from_cut_list=False),
            CutListSpec("Tube 20x20", folder_name="Cut-List-Item2"),
        )
        results = evaluate(package)
        result = row(results, CUT_LIST_EXCLUDED, "fail")

        assert result.subjects == ["cut:0001"]
        assert result.result is not None
        assert "Tube 40x40" in result.result.observed
        assert "Cut-List-Item1" in result.result.observed

    def test_every_item_excluded_is_checked(self) -> None:
        package = self.part(CutListSpec("Tube 40x40"), CutListSpec("Tube 20x20"))
        assert outcomes(evaluate(package), CUT_LIST_EXCLUDED) == {"pass"}

    def test_an_item_in_an_empty_folder_is_not_a_subject(self) -> None:
        """SOLIDWORKS does not display a folder that holds no bodies."""
        package = self.part(
            CutListSpec(
                "Tube 40x40",
                folder_name="Cut-List-Item1",
                body_count=0,
                excluded_from_cut_list=False,
            ),
            CutListSpec("Tube 20x20", folder_name="Cut-List-Item2"),
        )
        results = evaluate(package)

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"pass", "skip"}
        assert row(results, CUT_LIST_EXCLUDED, "pass").subjects == ["cut:0002"]
        assert "2" in reason(results, CUT_LIST_EXCLUDED, "skip")
        assert "displayable" in reason(results, CUT_LIST_EXCLUDED, "skip")

    def test_a_part_with_no_cut_list_items_is_skipped(self) -> None:
        """Difference aa: the macro prints nothing here, which reads as a pass."""
        results = evaluate(self.part())

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"skip"}
        assert "no cut-list items" in reason(results, CUT_LIST_EXCLUDED, "skip")

    def test_an_unread_exclusion_flag_is_unresolved(self) -> None:
        package = self.part(
            CutListSpec("Tube 40x40", excluded_from_cut_list=None),
            gaps=[gap("cut_list_exclusion", "cut:0001", "ExcludeFromCutList threw")],
        )
        results = evaluate(package)

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"unresolved"}
        assert "ExcludeFromCutList threw" in reason(results, CUT_LIST_EXCLUDED, "unresolved")

    def test_an_unread_body_count_is_unresolved_once_per_item(self) -> None:
        """Each row **is** a body folder: `GetBodyCount` is read on the item's own folder.

        `folder_name` is the enclosing `Cut list` feature, which every item of a real
        weldment shares, so one unread count speaks for one item and not for its siblings.
        """
        package = self.part(
            CutListSpec("Tube 40x40", folder_name="Cut-List-Item1", body_count=None),
            CutListSpec("Tube 20x20", folder_name="Cut-List-Item1", body_count=None),
            CutListSpec("Tube 10x10", folder_name="Cut-List-Item2"),
        )
        results = evaluate(package)
        unresolved = row(results, CUT_LIST_EXCLUDED, "unresolved")

        assert unresolved.subjects == ["cut:0001", "cut:0002"]
        assert "Tube 40x40" in (unresolved.reason or "")
        assert "Tube 20x20" in (unresolved.reason or "")

    def test_a_sibling_with_no_bodies_does_not_switch_the_check_off(self) -> None:
        """One empty item folder is one skipped row, never the whole part's answer."""
        package = self.part(
            CutListSpec("Tube 40x40", folder_name="Cut list", body_count=0),
            CutListSpec(
                "Tube 20x20",
                folder_name="Cut list",
                body_count=3,
                excluded_from_cut_list=False,
            ),
        )
        results = evaluate(package)

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"fail", "skip"}
        assert row(results, CUT_LIST_EXCLUDED, "fail").subjects == ["cut:0002"]
        assert row(results, CUT_LIST_EXCLUDED, "skip").subjects == ["cut:0001"]
        assert "1 displayable" in reason(results, CUT_LIST_EXCLUDED, "skip")

    def test_an_unread_body_count_leaves_its_siblings_in_a_bucket(self) -> None:
        """Every item lands somewhere: no row may disappear because a sibling is unknown."""
        package = self.part(
            CutListSpec("Tube 40x40", folder_name="Cut list", body_count=None),
            CutListSpec(
                "Tube 20x20",
                folder_name="Cut list",
                body_count=3,
                excluded_from_cut_list=False,
            ),
        )
        results = evaluate(package)

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"fail", "unresolved"}
        assert row(results, CUT_LIST_EXCLUDED, "unresolved").subjects == ["cut:0001"]
        assert row(results, CUT_LIST_EXCLUDED, "fail").subjects == ["cut:0002"]

    def test_no_cut_list_items_with_a_lost_cut_list_phase_is_unresolved(self) -> None:
        """A phase the dump lost is not a part with no cut list (FR-029)."""
        package = self.part(
            gaps=[gap("cutlist", None, "Failed to read the part cut lists.")]
        )
        results = evaluate(package)

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"unresolved"}
        assert "did not read its cut list" in reason(
            results, CUT_LIST_EXCLUDED, "unresolved"
        )

    def test_a_dropped_cut_list_for_this_document_is_unresolved(self) -> None:
        package = self.part(
            gaps=[
                gap(
                    "cut_list_folder",
                    "doc:1",
                    "'plate.SLDPRT' has no loaded model document, so its cut list was not "
                    "read.",
                )
            ]
        )
        results = evaluate(package)

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"unresolved"}
        assert "no loaded model document" in reason(
            results, CUT_LIST_EXCLUDED, "unresolved"
        )

    def test_a_skip_prefix_skips_the_whole_check(self) -> None:
        package = self.part(
            CutListSpec("Tube 40x40", excluded_from_cut_list=False), folder=SKIPPED_FOLDER
        )
        results = evaluate(package)

        assert outcomes(results, CUT_LIST_EXCLUDED) == {"skip"}
        assert "catalog/gaskets/" in reason(results, CUT_LIST_EXCLUDED, "skip")


# --- FR-005, the document-evidence half ---------------------------------------------------


class TestFr005:
    """A part nobody opened is unresolved for all four checks, naming why."""

    @pytest.mark.parametrize("state", ["suppressed", "lightweight", "unloaded"])
    def test_a_part_reached_only_through_unresolved_instances_is_unresolved(
        self, state: str
    ) -> None:
        package = package_of(
            AssemblySpec(
                "top",
                components=[
                    ComponentSpec("p1", "plate", suppression=state)  # type: ignore[arg-type]
                ],
            ),
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                material=None,
                mass_overridden=False,
                features=[sketch("Sketch1", UNDER_DEFINED)],
                cut_list=[CutListSpec("Tube 40x40", excluded_from_cut_list=False)],
                rebuild_error_count=5,
            ),
        )
        results = evaluate(package, "doc:2")

        for check in PART_CHECKS:
            assert outcomes(results, check) == {"unresolved"}, check
            assert "cmp:0002" in reason(results, check, "unresolved"), check
            assert state in reason(results, check, "unresolved"), check

    def test_a_part_reached_through_one_resolved_instance_is_graded(self) -> None:
        package = package_of(
            AssemblySpec(
                "top",
                components=[
                    ComponentSpec("p1", "plate", suppression="suppressed"),
                    ComponentSpec("p2", "plate"),
                ],
            ),
            PartSpec(
                "plate",
                configuration=MATERIAL_CONFIGURATION,
                material=None,
                mass_overridden=False,
            ),
        )
        assert outcomes(evaluate(package, "doc:2"), MATERIAL_ASSIGNED) == {"fail"}
