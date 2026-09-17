"""The seven assembly-scope checks of `contracts/rules.md` (T041).

One class per check, each covering the four columns the contract gives it - fail, checked,
skipped and unresolved - with the subjects and the observed text asserted rather than the
outcome alone, because a check that lands in the right bucket while naming the wrong
component is exactly the failure a release gate cannot afford.

Three rules of the contract are asserted across every class rather than once:

- **every assembly document the traversal reaches is graded**, sub-assemblies included
  (difference v), so each class that can be evaluated for a sub-assembly is;
- **a signal that was not read is unresolved**, never a pass and never a fail (FR-029), so
  every null reading has its own case and the reason names what was missing;
- **FR-005's instance-signal half**: a suppressed, lightweight or unloaded instance is not a
  subject of `one_fixed`, `fully_mated`, `not_transparent` or `not_hidden`, is named in that
  check's *skipped* coverage with its state, and is never a pass - which is `TestFr005`.

`standards.assembly.not_transparent` is unresolved for every component of every assembly
while `TRANSPARENCY_POLARITY` is `unsettled` (FR-012, SC-014, difference d). The settled
halves are exercised by setting the constant, which is what PROBE-2 will do in one edit.

Every value-bearing string here comes from the fictional fixture profile (FR-001).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from swreview.checks.standards import assembly as assembly_module
from swreview.checks.standards.assembly import (
    TRANSPARENCY_POLARITY,
    evaluate_assembly,
)
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.results import RuleResult
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.models import EvidencePackage, Gap
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    DocumentSpec,
    MateEntitySpec,
    MateSpec,
    PartSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE = load_profile(FIXTURE_DIR / "profile-a.yaml")
"""The fictional profile every package here is written for: the builder prefixes every path
with its `vault_root`, so a component under `catalog/screws/hex` is under its one-mate
prefix without this file repeating the string."""

NOT_EXPLODED = "standards.assembly.not_exploded"
REBUILD_ERRORS = "standards.assembly.rebuild_errors"
MATE_REFERENCES = "standards.assembly.mate_references"
ONE_FIXED = "standards.assembly.one_fixed"
FULLY_MATED = "standards.assembly.fully_mated"
NOT_TRANSPARENT = "standards.assembly.not_transparent"
NOT_HIDDEN = "standards.assembly.not_hidden"

INSTANCE_SIGNAL_CHECKS = (ONE_FIXED, FULLY_MATED, NOT_TRANSPARENT, NOT_HIDDEN)
"""The four checks whose subject is the instance itself (FR-005, instance signal)."""

UNDER_DEFINED = 2
FULLY_DEFINED = 3
OVER_DEFINED = 4
SOLVER_UNKNOWN = 1
"""`swConstrainedStatus_e`, as `checks/rms_types.yaml` calibrated them."""

HIDDEN = 0
VISIBLE = 1
VISIBILITY_UNKNOWN = -1


# --- the fixtures -------------------------------------------------------------------------


def package_of(*documents: DocumentSpec, gaps: Sequence[Gap] = ()) -> EvidencePackage:
    """A standards package for `PROFILE` whose first document is the root."""
    return standards_package(documents=list(documents), profile=PROFILE, gaps=gaps)


def gap(entity_kind: str, entity_id: str | None, reason: str) -> Gap:
    """One recorded gap: what the dump could not read, and why."""
    return Gap(
        kind="not_extracted",
        entity_kind=entity_kind,
        entity_id=entity_id,
        reason=reason,
        error=None,
    )


def evaluate(package: EvidencePackage, document_id: str = "doc:1") -> list[RuleResult]:
    """Every assembly check over one graded document of `package`."""
    document = next(
        checked
        for checked in graded_documents(package, PROFILE)
        if checked.document_id == document_id
    )
    return evaluate_assembly(document, package, PROFILE)


def row(results: Sequence[RuleResult], check: str, outcome: str) -> RuleResult:
    """The one result of `check` in `outcome`, or a failure naming what was there."""
    found = [
        result for result in results if result.rule_id == check and result.outcome == outcome
    ]
    assert len(found) == 1, (
        f"expected one {outcome!r} result for {check}, got "
        f"{[(result.rule_id, result.outcome) for result in results if result.rule_id == check]}"
    )
    return found[0]


def outcomes(results: Sequence[RuleResult], check: str) -> set[str]:
    """Every bucket `check` reached for this document."""
    return {result.outcome for result in results if result.rule_id == check}


def observed(results: Sequence[RuleResult], check: str) -> str:
    result = row(results, check, "fail")
    assert result.result is not None
    return result.result.observed


def reason(results: Sequence[RuleResult], check: str, outcome: str) -> str:
    found = row(results, check, outcome)
    assert found.reason is not None
    return found.reason


def renamed(package: EvidencePackage, **paths: str) -> EvidencePackage:
    """`package` with the named component instances' `full_path` rewritten.

    The builder keys a component instance by its spec name, so it cannot express the shape
    a sub-assembly used twice actually has: one child of one name, once per occurrence,
    under a different parent each time. Rewriting `full_path` afterwards is the smallest
    way to say it, and the last segment of `full_path` is exactly what the assembly checks
    group a child's occurrences by.
    """
    rows = [
        row.model_copy(update={"full_path": paths[row.name]}) if row.name in paths else row
        for row in package.components
    ]
    return package.model_copy(update={"components": rows})


def sub_assembly_used_twice(
    first: ComponentSpec, second: ComponentSpec, *others: ComponentSpec
) -> EvidencePackage:
    """A sub-assembly instanced twice, whose one child `bolt` has two occurrences.

    `first` and `second` are that child as each occurrence records it - they carry the
    per-occurrence readings the checks make - and `others` are further children of the
    sub-assembly, once each under the first occurrence.
    """
    package = package_of(
        AssemblySpec(
            "top",
            components=[ComponentSpec("sub_1", "sub"), ComponentSpec("sub_2", "sub")],
        ),
        AssemblySpec("sub", components=[first, second, *others]),
        PartSpec("plate"),
    )
    return renamed(package, **{first.name: "sub_1/bolt", second.name: "sub_2/bolt"})


# --- standards.assembly.not_exploded ------------------------------------------------------


class TestNotExploded:
    """FR-007: one finding per exploded assembly document, sub-assemblies included."""

    def test_an_exploded_root_fails_naming_the_document(self) -> None:
        package = package_of(
            AssemblySpec("top", is_exploded=True, components=[ComponentSpec("p1", "plate")]),
            PartSpec("plate"),
        )
        results = evaluate(package)
        result = row(results, NOT_EXPLODED, "fail")

        assert result.subjects == ["doc:1"]
        assert result.result is not None
        assert result.result.status == "demonstrated"
        assert result.result.severity == "medium"
        assert "top.SLDASM" in result.result.observed
        assert "exploded" in result.result.observed

    def test_an_exploded_sub_assembly_fails_too(self) -> None:
        """Difference v: the macro drops this check for sub-assemblies; this one does not."""
        package = package_of(
            AssemblySpec("top", components=[ComponentSpec("sub_1", "sub")]),
            AssemblySpec(
                "sub", is_exploded=True, components=[ComponentSpec("p1", "plate", parent="sub_1")]
            ),
            PartSpec("plate"),
        )
        results = evaluate(package, "doc:2")

        assert outcomes(results, NOT_EXPLODED) == {"fail"}
        assert "sub.SLDASM" in observed(results, NOT_EXPLODED)

    def test_a_collapsed_assembly_is_checked(self) -> None:
        package = package_of(
            AssemblySpec("top", is_exploded=False, components=[ComponentSpec("p1", "plate")]),
            PartSpec("plate"),
        )
        assert outcomes(evaluate(package), NOT_EXPLODED) == {"pass"}

    def test_an_unread_exploded_state_is_unresolved_naming_the_gap(self) -> None:
        package = package_of(
            AssemblySpec("top", is_exploded=None, components=[ComponentSpec("p1", "plate")]),
            PartSpec("plate"),
            gaps=[gap("assembly_exploded", "doc:1", "IsExploded threw E_FAIL")],
        )
        result = row(evaluate(package), NOT_EXPLODED, "unresolved")

        assert result.reason is not None
        assert "IsExploded threw E_FAIL" in result.reason
        assert "assembly_exploded" in result.reason

    def test_an_unread_exploded_state_with_no_gap_says_so(self) -> None:
        """A null with no gap is still unresolved: it is never read as "not exploded"."""
        package = package_of(
            AssemblySpec("top", is_exploded=None, components=[ComponentSpec("p1", "plate")]),
            PartSpec("plate"),
        )
        result = row(evaluate(package), NOT_EXPLODED, "unresolved")

        assert result.reason is not None
        assert "no gap" in result.reason

    def test_it_is_never_skipped(self) -> None:
        for is_exploded in (True, False, None):
            package = package_of(
                AssemblySpec("top", is_exploded=is_exploded),
            )
            assert "skip" not in outcomes(evaluate(package), NOT_EXPLODED)

    def test_a_sub_assembly_reached_only_through_unresolved_instances_is_unresolved(self) -> None:
        """FR-005, document evidence: the reading is about a document nobody opened."""
        package = package_of(
            AssemblySpec(
                "top", components=[ComponentSpec("sub_1", "sub", suppression="suppressed")]
            ),
            AssemblySpec(
                "sub", is_exploded=True, components=[ComponentSpec("p1", "plate", parent="sub_1")]
            ),
            PartSpec("plate"),
        )
        results = evaluate(package, "doc:2")
        result = row(results, NOT_EXPLODED, "unresolved")

        assert outcomes(results, NOT_EXPLODED) == {"unresolved"}
        assert result.reason is not None
        assert "cmp:0002" in result.reason
        assert "suppressed" in result.reason


# --- standards.assembly.rebuild_errors ----------------------------------------------------


class TestAssemblyRebuildErrors:
    """FR-008: the document-level count, as the document stood, with nothing rebuilt."""

    def test_a_non_zero_count_fails_naming_the_count_and_the_no_rebuild_sentence(self) -> None:
        package = package_of(
            AssemblySpec("top", rebuild_error_count=3, components=[ComponentSpec("p1", "plate")]),
            PartSpec("plate"),
        )
        result = row(evaluate(package), REBUILD_ERRORS, "fail")

        assert result.subjects == ["doc:1"]
        assert result.result is not None
        assert "3" in result.result.observed
        assert "nothing was rebuilt" in result.result.observed
        assert "counts as the document stood; nothing was rebuilt" in result.result.coverage_limits

    def test_a_zero_count_is_checked(self) -> None:
        package = package_of(
            AssemblySpec("top", rebuild_error_count=0, components=[ComponentSpec("p1", "plate")]),
            PartSpec("plate"),
        )
        assert outcomes(evaluate(package), REBUILD_ERRORS) == {"pass"}

    def test_an_unread_count_is_unresolved(self) -> None:
        package = package_of(
            AssemblySpec("top", rebuild_error_count=None),
            gaps=[gap("rebuild_error_count", "doc:1", "GetWhatsWrongCount threw")],
        )
        result = row(evaluate(package), REBUILD_ERRORS, "unresolved")

        assert result.reason is not None
        assert "GetWhatsWrongCount threw" in result.reason

    def test_per_feature_codes_are_not_substituted_for_an_unread_count(self) -> None:
        """The document count also covers mate errors that no feature carries."""
        package = package_of(
            AssemblySpec(
                "top", rebuild_error_count=None, components=[ComponentSpec("p1", "plate")]
            ),
            PartSpec("plate", rebuild_error_count=7),
        )
        assert outcomes(evaluate(package), REBUILD_ERRORS) == {"unresolved"}

    def test_a_sub_assembly_carries_its_own_count(self) -> None:
        package = package_of(
            AssemblySpec("top", components=[ComponentSpec("sub_1", "sub")]),
            AssemblySpec("sub", rebuild_error_count=2),
        )
        assert outcomes(evaluate(package, "doc:2"), REBUILD_ERRORS) == {"fail"}


# --- standards.assembly.mate_references ---------------------------------------------------


class TestMateReferences:
    """FR-009: a mate that resolves fewer entities than it has has lost a reference."""

    def package(self, *mates: MateSpec) -> EvidencePackage:
        return package_of(
            AssemblySpec(
                "top",
                components=[ComponentSpec("p1", "plate"), ComponentSpec("p2", "plate")],
                mates=list(mates),
            ),
            PartSpec("plate"),
        )

    def test_a_lost_reference_fails_naming_the_mate_both_counts_and_the_entities(self) -> None:
        package = self.package(
            MateSpec(
                entities=[
                    MateEntitySpec("p1"),
                    MateEntitySpec("p2", entity_kind="EDGE", resolution_status="unresolved"),
                ]
            )
        )
        results = evaluate(package)
        result = row(results, MATE_REFERENCES, "fail")

        assert result.subjects == ["mate:0001"]
        assert result.result is not None
        assert "1 of 2" in result.result.observed
        assert "EDGE" in result.result.observed
        assert "p2" in result.result.observed

    def test_every_entity_resolving_is_checked(self) -> None:
        package = self.package(
            MateSpec(entities=[MateEntitySpec("p1"), MateEntitySpec("p2")]),
        )
        results = evaluate(package)

        assert outcomes(results, MATE_REFERENCES) == {"pass"}
        assert row(results, MATE_REFERENCES, "pass").subjects == ["mate:0001"]

    def test_an_assembly_with_no_mates_is_skipped_with_no_mates(self) -> None:
        """Difference e: the macro dereferences a null mate group and raises here."""
        result = row(evaluate(self.package()), MATE_REFERENCES, "skip")

        assert result.reason == "no mates"

    def test_a_mate_phase_the_dump_lost_is_unresolved_not_no_mates(self) -> None:
        """An empty `mates[]` is two different facts and only one of them is a skip."""
        package = package_of(
            AssemblySpec("top", components=[ComponentSpec("p1", "plate")]),
            PartSpec("plate"),
            gaps=[gap("mate", None, "Failed to read the assembly mates.")],
        )
        results = evaluate(package)

        assert outcomes(results, MATE_REFERENCES) == {"unresolved"}
        assert "did not read its mate group" in reason(results, MATE_REFERENCES, "unresolved")
        assert "Failed to read the assembly mates." in reason(
            results, MATE_REFERENCES, "unresolved"
        )

    def test_an_unknown_entity_status_is_unresolved_for_that_mate(self) -> None:
        package = self.package(
            MateSpec(
                entities=[
                    MateEntitySpec("p1"),
                    MateEntitySpec("p2", resolution_status="unknown"),
                ]
            ),
            MateSpec(entities=[MateEntitySpec("p1"), MateEntitySpec("p2")]),
        )
        results = evaluate(package)
        unknown = row(results, MATE_REFERENCES, "unresolved")

        assert unknown.subjects == ["mate:0001"]
        assert row(results, MATE_REFERENCES, "pass").subjects == ["mate:0002"]

    def test_a_null_entity_status_is_unresolved_too(self) -> None:
        """Null is a package written before 1.4.0: it is not evidence of a resolved entity."""
        package = self.package(
            MateSpec(entities=[MateEntitySpec("p1", resolution_status=None), MateEntitySpec("p2")]),
        )
        results = evaluate(package)

        assert outcomes(results, MATE_REFERENCES) == {"unresolved"}

    def test_a_sub_assembly_with_no_recorded_mates_is_unresolved_naming_it(self) -> None:
        """Difference h: the package walks only the root assembly's mate group."""
        package = package_of(
            AssemblySpec("top", components=[ComponentSpec("sub_1", "sub")]),
            AssemblySpec("sub", components=[ComponentSpec("p1", "plate", parent="sub_1")]),
            PartSpec("plate"),
        )
        results = evaluate(package, "doc:2")
        result = row(results, MATE_REFERENCES, "unresolved")

        assert outcomes(results, MATE_REFERENCES) == {"unresolved"}
        assert result.reason is not None
        assert "sub.SLDASM" in result.reason
        assert "mate" in result.reason

    def test_a_sub_assembly_whose_mates_the_package_records_is_graded(self) -> None:
        package = package_of(
            AssemblySpec("top", components=[ComponentSpec("sub_1", "sub")]),
            AssemblySpec(
                "sub",
                components=[
                    ComponentSpec("p1", "plate", parent="sub_1"),
                    ComponentSpec("p2", "plate", parent="sub_1"),
                ],
                mates=[
                    MateSpec(
                        entities=[
                            MateEntitySpec("p1"),
                            MateEntitySpec("p2", resolution_status="unresolved"),
                        ]
                    )
                ],
            ),
            PartSpec("plate"),
        )
        assert outcomes(evaluate(package, "doc:2"), MATE_REFERENCES) == {"fail"}


# --- standards.assembly.one_fixed ---------------------------------------------------------


class TestOneFixed:
    """FR-010: at most one immediate child of an assembly is fixed."""

    def test_two_fixed_children_fail_naming_every_fixed_component(self) -> None:
        package = package_of(
            AssemblySpec(
                "top",
                components=[
                    ComponentSpec("p1", "plate", is_fixed=True),
                    ComponentSpec("p2", "plate", is_fixed=True),
                    ComponentSpec("p3", "plate"),
                ],
            ),
            PartSpec("plate"),
        )
        results = evaluate(package)
        result = row(results, ONE_FIXED, "fail")

        assert result.subjects == ["cmp:0002", "cmp:0003"]
        assert result.result is not None
        assert "p1" in result.result.observed
        assert "p2" in result.result.observed
        assert "p3" not in result.result.observed

    @pytest.mark.parametrize("fixed", [0, 1])
    def test_zero_or_one_fixed_child_is_checked(self, fixed: int) -> None:
        package = package_of(
            AssemblySpec(
                "top",
                components=[
                    ComponentSpec("p1", "plate", is_fixed=fixed == 1),
                    ComponentSpec("p2", "plate"),
                ],
            ),
            PartSpec("plate"),
        )
        assert outcomes(evaluate(package), ONE_FIXED) == {"pass"}

    def test_an_assembly_with_no_children_is_skipped(self) -> None:
        result = row(evaluate(package_of(AssemblySpec("top"))), ONE_FIXED, "skip")

        assert result.reason is not None
        assert "no immediate child" in result.reason

    def test_a_component_whose_fixed_state_was_not_read_is_unresolved(self) -> None:
        package = package_of(
            AssemblySpec(
                "top",
                components=[ComponentSpec("p1", "plate"), ComponentSpec("p2", "plate")],
            ),
            PartSpec("plate"),
            gaps=[gap("component_fixed", "cmp:0002", "IsFixed threw")],
        )
        results = evaluate(package)
        result = row(results, ONE_FIXED, "unresolved")

        assert result.subjects == ["cmp:0002"]
        assert result.reason is not None
        assert "IsFixed threw" in result.reason
        assert row(results, ONE_FIXED, "pass").subjects == ["cmp:0003"]

    def test_only_immediate_children_count(self) -> None:
        """A fixed component inside a sub-assembly is that sub-assembly's row, not the root's."""
        package = package_of(
            AssemblySpec(
                "top",
                components=[ComponentSpec("sub_1", "sub", is_fixed=True)],
            ),
            AssemblySpec(
                "sub",
                components=[
                    ComponentSpec("p1", "plate", parent="sub_1", is_fixed=True),
                    ComponentSpec("p2", "plate", parent="sub_1", is_fixed=True),
                ],
            ),
            PartSpec("plate"),
        )
        assert outcomes(evaluate(package), ONE_FIXED) == {"pass"}
        assert outcomes(evaluate(package, "doc:2"), ONE_FIXED) == {"fail"}


# --- standards.assembly.fully_mated -------------------------------------------------------


class TestFullyMated:
    """FR-011: under-constrained components, and the library minimum where one applies."""

    def package(
        self, *components: ComponentSpec, mates: Sequence[MateSpec] = ()
    ) -> EvidencePackage:
        return package_of(
            AssemblySpec("top", components=list(components), mates=list(mates)),
            PartSpec("plate"),
            PartSpec("hex_screw", folder="catalog/screws/hex"),
            PartSpec("spacer", folder="catalog/spacers"),
        )

    def test_an_under_constrained_component_with_no_mate_prefix_fails(self) -> None:
        package = self.package(ComponentSpec("p1", "plate", constrained_status_raw=UNDER_DEFINED))
        results = evaluate(package)
        result = row(results, FULLY_MATED, "fail")

        assert result.subjects == ["cmp:0002"]
        assert result.result is not None
        assert "under-constrained" in result.result.observed

    @pytest.mark.parametrize("status", [FULLY_DEFINED, OVER_DEFINED])
    def test_a_fully_or_over_constrained_component_is_checked(self, status: int) -> None:
        package = self.package(ComponentSpec("p1", "plate", constrained_status_raw=status))
        assert outcomes(evaluate(package), FULLY_MATED) == {"pass"}

    def test_a_one_mate_prefix_component_below_its_minimum_fails_naming_both(self) -> None:
        """The longest match across the two lists decides: `catalog/screws/hex/` is one mate."""
        package = self.package(
            ComponentSpec("s1", "hex_screw", constrained_status_raw=UNDER_DEFINED)
        )
        results = evaluate(package)
        result = row(results, FULLY_MATED, "fail")

        assert result.result is not None
        assert "1" in result.result.observed
        assert "catalog/screws/hex/" in result.result.observed

    def test_a_one_mate_prefix_component_meeting_its_minimum_is_checked(self) -> None:
        package = self.package(
            ComponentSpec("s1", "hex_screw", constrained_status_raw=UNDER_DEFINED),
            ComponentSpec("p1", "plate", constrained_status_raw=FULLY_DEFINED),
            mates=[MateSpec(entities=[MateEntitySpec("s1"), MateEntitySpec("p1")])],
        )
        assert outcomes(evaluate(package), FULLY_MATED) == {"pass"}

    def test_a_suppressed_mate_does_not_count(self) -> None:
        """Difference s: a suppressed mate constrains nothing."""
        package = self.package(
            ComponentSpec("s1", "hex_screw", constrained_status_raw=UNDER_DEFINED),
            ComponentSpec("p1", "plate", constrained_status_raw=FULLY_DEFINED),
            mates=[
                MateSpec(entities=[MateEntitySpec("s1"), MateEntitySpec("p1")], suppressed=True)
            ],
        )
        assert outcomes(evaluate(package), FULLY_MATED) == {"fail"}

    def test_a_two_mate_prefix_component_needs_two_unsuppressed_mates(self) -> None:
        package = self.package(
            ComponentSpec("sp1", "spacer", constrained_status_raw=UNDER_DEFINED),
            ComponentSpec("p1", "plate", constrained_status_raw=FULLY_DEFINED),
            mates=[MateSpec(entities=[MateEntitySpec("sp1"), MateEntitySpec("p1")])],
        )
        results = evaluate(package)
        result = row(results, FULLY_MATED, "fail")

        assert result.result is not None
        assert "2" in result.result.observed
        assert "catalog/spacers/" in result.result.observed

    def test_a_pattern_instance_is_skipped_naming_the_pattern(self) -> None:
        """Difference t: a patterned instance is positioned by its pattern, not by mates."""
        package = self.package(
            ComponentSpec(
                "p1",
                "plate",
                constrained_status_raw=UNDER_DEFINED,
                is_pattern_instance=True,
                pattern_id="LocalLPattern1",
            )
        )
        results = evaluate(package)
        result = row(results, FULLY_MATED, "skip")

        assert result.subjects == ["cmp:0002"]
        assert result.reason is not None
        assert "LocalLPattern1" in result.reason

    def test_the_root_instance_is_not_a_subject(self) -> None:
        package = self.package(ComponentSpec("p1", "plate", constrained_status_raw=FULLY_DEFINED))
        results = evaluate(package)

        assert "cmp:0001" not in row(results, FULLY_MATED, "pass").subjects

    def test_a_part_opened_alone_has_no_assembly_results(self) -> None:
        """Its synthesized root is not an immediate child of anything."""
        package = standards_package(documents=[PartSpec("plate")], profile=PROFILE)
        document = next(
            checked
            for checked in graded_documents(package, PROFILE)
            if checked.document_id == "doc:1"
        )
        with pytest.raises(ValueError, match="part"):
            evaluate_assembly(document, package, PROFILE)

    @pytest.mark.parametrize("status", [SOLVER_UNKNOWN, None])
    def test_an_unknown_constrained_status_is_unresolved(self, status: int | None) -> None:
        package = self.package(ComponentSpec("p1", "plate", constrained_status_raw=status))
        results = evaluate(package)
        result = row(results, FULLY_MATED, "unresolved")

        assert result.subjects == ["cmp:0002"]
        assert result.reason is not None
        assert "constrained status" in result.reason

    def test_a_null_pattern_origin_is_unresolved(self) -> None:
        package = self.package(
            ComponentSpec(
                "p1", "plate", constrained_status_raw=UNDER_DEFINED, is_pattern_instance=None
            )
        )
        results = evaluate(package)
        result = row(results, FULLY_MATED, "unresolved")

        assert result.subjects == ["cmp:0002"]
        assert result.reason is not None
        assert "pattern" in result.reason

    def test_an_assembly_with_no_children_is_skipped(self) -> None:
        result = row(evaluate(package_of(AssemblySpec("top"))), FULLY_MATED, "skip")

        assert result.reason is not None
        assert "no immediate child" in result.reason

    def test_a_sub_assemblys_mate_prefix_component_is_unresolved(self) -> None:
        """The package records only the root's mates, so the minimum cannot be counted."""
        package = package_of(
            AssemblySpec("top", components=[ComponentSpec("sub_1", "sub")]),
            AssemblySpec(
                "sub",
                components=[
                    ComponentSpec(
                        "s1", "hex_screw", parent="sub_1", constrained_status_raw=UNDER_DEFINED
                    ),
                    ComponentSpec(
                        "p1", "plate", parent="sub_1", constrained_status_raw=UNDER_DEFINED
                    ),
                ],
            ),
            PartSpec("plate"),
            PartSpec("hex_screw", folder="catalog/screws/hex"),
        )
        results = evaluate(package, "doc:2")
        unresolved = row(results, FULLY_MATED, "unresolved")

        assert unresolved.subjects == ["cmp:0003"]
        assert unresolved.reason is not None
        assert "sub.SLDASM" in unresolved.reason
        assert row(results, FULLY_MATED, "fail").subjects == ["cmp:0004"]


# --- standards.assembly.not_transparent ---------------------------------------------------


class TestNotTransparent:
    """FR-012 and SC-014: nothing is graded until PROBE-2 settles the polarity."""

    def package(self, *components: ComponentSpec, gaps: Sequence[Gap] = ()) -> EvidencePackage:
        return package_of(
            AssemblySpec("top", components=list(components)),
            PartSpec("plate"),
            gaps=gaps,
        )

    def test_the_polarity_ships_unsettled(self) -> None:
        assert TRANSPARENCY_POLARITY == "unsettled"

    def test_every_component_is_unresolved_while_the_polarity_is_unsettled(self) -> None:
        package = self.package(
            ComponentSpec("p1", "plate", has_appearance_override=True, transparency_raw=0.5),
            ComponentSpec("p2", "plate", has_appearance_override=False),
        )
        results = evaluate(package)
        result = row(results, NOT_TRANSPARENT, "unresolved")

        assert outcomes(results, NOT_TRANSPARENT) == {"unresolved"}
        assert result.subjects == ["cmp:0002", "cmp:0003"]
        assert result.reason is not None
        assert "PROBE-2" in result.reason
        assert "unsettled" in result.reason

    def test_a_settled_polarity_grades_the_recorded_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(assembly_module, "TRANSPARENCY_POLARITY", "zero_is_opaque")
        package = self.package(
            ComponentSpec("p1", "plate", has_appearance_override=True, transparency_raw=0.4),
            ComponentSpec("p2", "plate", has_appearance_override=True, transparency_raw=0.0),
            ComponentSpec("p3", "plate", has_appearance_override=False),
        )
        results = evaluate(package)
        result = row(results, NOT_TRANSPARENT, "fail")

        assert result.subjects == ["cmp:0002"]
        assert outcomes(results, NOT_TRANSPARENT) == {"fail"}, (
            "a check that failed on this document is not also checked for it"
        )
        assert result.result is not None
        assert "0.4" in result.result.observed

    def test_the_opposite_polarity_reads_the_same_value_the_other_way(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Which is why guessing it would mislabel every component that carries one."""
        monkeypatch.setattr(assembly_module, "TRANSPARENCY_POLARITY", "one_is_opaque")
        package = self.package(
            ComponentSpec("p1", "plate", has_appearance_override=True, transparency_raw=1.0),
            ComponentSpec("p2", "plate", has_appearance_override=True, transparency_raw=0.0),
        )
        results = evaluate(package)

        assert row(results, NOT_TRANSPARENT, "fail").subjects == ["cmp:0003"], (
            "the value the other polarity reads as opaque is the one this one fails on"
        )

    def test_an_unread_override_is_unresolved_once_settled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(assembly_module, "TRANSPARENCY_POLARITY", "zero_is_opaque")
        package = self.package(
            ComponentSpec("p1", "plate", has_appearance_override=None),
            ComponentSpec("p2", "plate", has_appearance_override=True, transparency_raw=None),
            gaps=[gap("component_transparency", "cmp:0002", "HasMaterialPropertyValues threw")],
        )
        results = evaluate(package)
        result = row(results, NOT_TRANSPARENT, "unresolved")

        assert result.subjects == ["cmp:0002", "cmp:0003"]
        assert result.reason is not None
        assert "HasMaterialPropertyValues threw" in result.reason

    def test_an_assembly_with_no_children_is_unresolved_while_unsettled(self) -> None:
        results = evaluate(package_of(AssemblySpec("top")))

        assert outcomes(results, NOT_TRANSPARENT) == {"unresolved"}
        assert row(results, NOT_TRANSPARENT, "unresolved").subjects == []


# --- standards.assembly.not_hidden --------------------------------------------------------


class TestNotHidden:
    """FR-013: a hidden component, and suppression is never hidden (difference c)."""

    def package(self, *components: ComponentSpec, gaps: Sequence[Gap] = ()) -> EvidencePackage:
        return package_of(
            AssemblySpec("top", components=list(components)), PartSpec("plate"), gaps=gaps
        )

    def test_a_hidden_component_fails(self) -> None:
        package = self.package(
            ComponentSpec("p1", "plate", visibility_raw=HIDDEN),
            ComponentSpec("p2", "plate", visibility_raw=VISIBLE),
        )
        results = evaluate(package)
        result = row(results, NOT_HIDDEN, "fail")

        assert result.subjects == ["cmp:0002"]
        assert result.result is not None
        assert "hidden" in result.result.observed
        assert "p1" in result.result.observed

    def test_a_visible_component_is_checked(self) -> None:
        package = self.package(ComponentSpec("p1", "plate", visibility_raw=VISIBLE))
        assert outcomes(evaluate(package), NOT_HIDDEN) == {"pass"}

    def test_a_suppressed_component_is_never_a_hidden_finding(self) -> None:
        package = self.package(
            ComponentSpec("p1", "plate", suppression="suppressed", visibility_raw=HIDDEN)
        )
        results = evaluate(package)

        assert outcomes(results, NOT_HIDDEN) == {"skip"}
        assert "suppressed" in (row(results, NOT_HIDDEN, "skip").reason or "")

    def test_an_unread_visibility_is_unresolved(self) -> None:
        package = self.package(
            ComponentSpec("p1", "plate", visibility_raw=None),
            gaps=[gap("component_visibility", "cmp:0002", "Visible threw")],
        )
        result = row(evaluate(package), NOT_HIDDEN, "unresolved")

        assert result.subjects == ["cmp:0002"]
        assert result.reason is not None
        assert "Visible threw" in result.reason

    def test_the_unknown_visibility_state_is_unresolved(self) -> None:
        package = self.package(ComponentSpec("p1", "plate", visibility_raw=VISIBILITY_UNKNOWN))
        result = row(evaluate(package), NOT_HIDDEN, "unresolved")

        assert result.subjects == ["cmp:0002"]
        assert result.reason is not None
        assert "-1" in result.reason


# --- a child with more than one occurrence --------------------------------------------------


class TestEveryOccurrence:
    """FR-003 and `BUCKET_ORDER`: one row per child, decided over **every** occurrence.

    A sub-assembly used twice carries one instance of each of its children per occurrence,
    and what these four checks read sits on the instance. Grouping the occurrences keeps a
    gearbox used twice from reporting each of its components twice; grading only the first
    would report a child whose second occurrence is hidden, fixed or transparent as
    compliant, which is a silent pass on the defect the check exists to find.
    """

    def test_a_second_occurrence_that_is_hidden_fails(self) -> None:
        package = sub_assembly_used_twice(
            ComponentSpec("bolt_a", "plate", parent="sub_1", visibility_raw=VISIBLE),
            ComponentSpec("bolt_b", "plate", parent="sub_2", visibility_raw=HIDDEN),
        )
        results = evaluate(package, "doc:2")
        result = row(results, NOT_HIDDEN, "fail")

        assert outcomes(results, NOT_HIDDEN) == {"fail"}
        assert result.subjects == ["cmp:0005"]
        assert result.result is not None
        assert "sub_2/bolt" in result.result.observed

    def test_a_first_occurrence_that_is_hidden_fails_naming_that_occurrence(self) -> None:
        package = sub_assembly_used_twice(
            ComponentSpec("bolt_a", "plate", parent="sub_1", visibility_raw=HIDDEN),
            ComponentSpec("bolt_b", "plate", parent="sub_2", visibility_raw=VISIBLE),
        )
        results = evaluate(package, "doc:2")
        result = row(results, NOT_HIDDEN, "fail")

        assert result.subjects == ["cmp:0004"]
        assert "sub_1/bolt" in observed(results, NOT_HIDDEN)

    def test_a_child_that_is_compliant_in_both_occurrences_is_one_pass(self) -> None:
        package = sub_assembly_used_twice(
            ComponentSpec("bolt_a", "plate", parent="sub_1", visibility_raw=VISIBLE),
            ComponentSpec("bolt_b", "plate", parent="sub_2", visibility_raw=VISIBLE),
        )
        results = evaluate(package, "doc:2")

        assert outcomes(results, NOT_HIDDEN) == {"pass"}
        assert row(results, NOT_HIDDEN, "pass").subjects == ["cmp:0004"]

    def test_an_unread_signal_on_one_occurrence_leaves_the_child_unknown(self) -> None:
        """A compliant occurrence beside an unread one does not clear it (FR-029)."""
        package = sub_assembly_used_twice(
            ComponentSpec("bolt_a", "plate", parent="sub_1", visibility_raw=VISIBLE),
            ComponentSpec("bolt_b", "plate", parent="sub_2", visibility_raw=None),
        )
        results = evaluate(package, "doc:2")

        assert outcomes(results, NOT_HIDDEN) == {"unresolved"}
        assert row(results, NOT_HIDDEN, "unresolved").subjects == ["cmp:0005"]

    def test_a_suppressed_occurrence_does_not_hide_a_resolved_one(self) -> None:
        package = sub_assembly_used_twice(
            ComponentSpec(
                "bolt_a",
                "plate",
                parent="sub_1",
                suppression="suppressed",
                visibility_raw=VISIBLE,
            ),
            ComponentSpec("bolt_b", "plate", parent="sub_2", visibility_raw=HIDDEN),
        )
        results = evaluate(package, "doc:2")

        assert outcomes(results, NOT_HIDDEN) == {"fail"}
        assert row(results, NOT_HIDDEN, "fail").subjects == ["cmp:0005"]

    def test_a_child_fixed_in_both_occurrences_is_one_ground(self) -> None:
        """The de-duplication FR-003 asks for: one fixed child, not two fixed instances."""
        package = sub_assembly_used_twice(
            ComponentSpec("bolt_a", "plate", parent="sub_1", is_fixed=True),
            ComponentSpec("bolt_b", "plate", parent="sub_2", is_fixed=True),
        )
        results = evaluate(package, "doc:2")

        assert outcomes(results, ONE_FIXED) == {"pass"}
        assert row(results, ONE_FIXED, "pass").subjects == ["cmp:0004"]

    def test_a_child_fixed_in_one_occurrence_counts_as_fixed(self) -> None:
        package = sub_assembly_used_twice(
            ComponentSpec("bolt_a", "plate", parent="sub_1", is_fixed=False),
            ComponentSpec("bolt_b", "plate", parent="sub_2", is_fixed=True),
            ComponentSpec("washer", "plate", parent="sub_1", is_fixed=True),
        )
        results = evaluate(package, "doc:2")
        result = row(results, ONE_FIXED, "fail")

        assert result.subjects == ["cmp:0005", "cmp:0006"]
        assert "2 immediate children" in observed(results, ONE_FIXED)


# --- FR-005, the instance-signal half -----------------------------------------------------


class TestFr005:
    """An unresolved instance is skipped with its state, and is never a pass or a finding."""

    @pytest.mark.parametrize("state", ["suppressed", "lightweight", "unloaded"])
    def test_an_unresolved_instance_is_skipped_with_its_state(self, state: str) -> None:
        package = package_of(
            AssemblySpec(
                "top",
                components=[
                    ComponentSpec(
                        "p1",
                        "plate",
                        suppression=state,  # type: ignore[arg-type]
                        is_fixed=True,
                        visibility_raw=HIDDEN,
                        constrained_status_raw=UNDER_DEFINED,
                        has_appearance_override=True,
                        transparency_raw=0.9,
                    ),
                    ComponentSpec("p2", "plate", constrained_status_raw=FULLY_DEFINED),
                ],
            ),
            PartSpec("plate"),
        )
        results = evaluate(package)

        for check in INSTANCE_SIGNAL_CHECKS:
            skipped = row(results, check, "skip")
            assert skipped.subjects == ["cmp:0002"], check
            assert state in (skipped.reason or ""), check
            assert "fail" not in outcomes(results, check), check
            passing = [
                result for result in results if result.rule_id == check and result.outcome == "pass"
            ]
            assert all("cmp:0002" not in result.subjects for result in passing), check

    def test_an_unresolved_instance_whose_signal_was_not_read_is_unresolved_instead(self) -> None:
        """FR-005's exception: a state cannot excuse a reading nobody made."""
        package = package_of(
            AssemblySpec(
                "top",
                components=[
                    ComponentSpec("p1", "plate", suppression="suppressed", visibility_raw=None)
                ],
            ),
            PartSpec("plate"),
        )
        results = evaluate(package)

        assert outcomes(results, NOT_HIDDEN) == {"unresolved"}
        assert row(results, NOT_HIDDEN, "unresolved").subjects == ["cmp:0002"]
