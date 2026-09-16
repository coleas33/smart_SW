"""Unit tests for the RMS report layer (T021).

`checks/rms/report.py` is the one place a `RuleResult` becomes something a reader sees, so
what is pinned here is every mapping of `specs/003-resilient-modeling/data-model.md`
section 2 ("Subjects to Finding fields", "Coverage aggregation") and nothing about how a
rule reached its verdict:

- **findings.** `component_ids` are every instance of the subject document in package
  order, one `inputs` string per subject, `tool_result_ids` carries the step the call is
  being recorded as, `calculation` stays null, and the severity comes from the rule;
- **exceptions.** A `fail` outcome consults the store with `check=<rule id>`; `active`
  waives it, `needs_review` leaves the finding standing and says so. A `warn` outcome
  never consults the store at all;
- **coverage.** One aggregated item per rule per bucket through
  `ToolContext.replace_coverage`, the `modeling.resilience` summary, the
  `rms.types.unknown` item, and the ten coverage-only rules written once per session.

The rule evaluators are not exercised here: results are hand-built with the constructors
of `checks/rms/results.py`, which is what a rule returns, so a change in a rule's wording
cannot break the report layer's tests and vice versa. The one exception is the unresolved
part document, where `evaluate_part` itself is the subject of the assertion.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from swreview.checks.rms import RULES, coverage_only, evaluable
from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import evaluate_part
from swreview.checks.rms.report import report_results
from swreview.checks.rms.results import RuleResult, finding, passed, skipped, unresolved
from swreview.checks.rms_types import load_table
from swreview.exceptions import ExceptionStore, ReviewException
from swreview.ir.models import EvidencePackage, Feature, Gap
from swreview.report.session import CoverageItem
from swreview.tools.context import ToolContext, context_for
from tests.support.features import (
    AssemblySpec,
    FeatureSpec,
    InstanceSpec,
    PartSpec,
    SubassemblySpec,
    feature,
    folder,
    rms_package,
    sketch_feature,
)

TABLE = load_table()
REFERENCE, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups

HOUSING = "doc:3"
"""The part with two component instances; `doc:1` is the root assembly, `doc:2` its
subassembly, so a finding on the housing must name `cmp:0002` and `cmp:0003`."""

BRACKET = "doc:4"
GHOST = "doc:5"
"""The part with feature rows and no component instance at all."""

ROOT = "doc:1"
SUBASSEMBLY = "doc:2"

PART_RULE_IDS = tuple(rule.id for rule in evaluable() if rule.scope == "part")
EQUATION_RULE_IDS = tuple(rule.id for rule in evaluable() if rule.scope == "equations")


# --- the package every test reads -------------------------------------------------


def housing_features() -> list[FeatureSpec]:
    return [
        folder(CORE, feature("Boss", "Extrusion")),
        folder(
            DETAIL,
            sketch_feature("Sketch7", consumers=("Hole1",)),
            feature("Hole1", "HoleWzd"),
        ),
    ]


def build_package(
    *,
    housing_instances: Sequence[InstanceSpec] | None = None,
    ghost: bool = False,
    gaps: Sequence[Gap] = (),
    configurations: Sequence[str] | None = None,
) -> EvidencePackage:
    """The root assembly, one subassembly and two (optionally three) part documents."""
    parts = [
        PartSpec(
            document_id=HOUSING,
            name="housing",
            features=housing_features(),
            instances=(
                housing_instances
                if housing_instances is not None
                else [InstanceSpec("housing-1"), InstanceSpec("housing-2")]
            ),
            configurations=configurations,
        ),
        PartSpec(
            document_id=BRACKET,
            name="bracket",
            features=[folder(CORE, feature("Boss2", "Extrusion"))],
        ),
    ]
    if ghost:
        parts.append(
            PartSpec(
                document_id=GHOST,
                name="ghost",
                features=[folder(CORE, feature("Boss3", "Extrusion"))],
                instances=(),
            )
        )
    return rms_package(
        parts=parts,
        assembly=AssemblySpec(
            document_id=ROOT,
            subassembly=SubassemblySpec(document_id=SUBASSEMBLY, name="inner-assy"),
        ),
        gaps=gaps,
    )


@pytest.fixture
def package() -> EvidencePackage:
    return build_package()


@pytest.fixture
def context(package: EvidencePackage) -> ToolContext:
    return context_for(package)


def rows_of(package: EvidencePackage, document_id: str) -> list[Feature]:
    return [row for row in package.features if row.document_id == document_id]


def named(package: EvidencePackage, document_id: str, *names: str) -> list[Feature]:
    by_name = {row.name: row for row in rows_of(package, document_id)}
    return [by_name[name] for name in names]


# --- hand-built rule results ------------------------------------------------------


def fail_result(
    package: EvidencePackage,
    rule_id: str,
    document_id: str,
    *names: str,
    coverage_limits: Sequence[str] = (),
) -> RuleResult:
    subjects = named(package, document_id, *names)
    return finding(
        RULES[rule_id],
        document_id,
        subjects,
        observed=f"{', '.join(names)} violates {rule_id}",
        recommended_action="Fix it.",
        coverage_limits=coverage_limits,
    )


def coverage_items(context: ToolContext, bucket: str) -> list[CoverageItem]:
    return list(getattr(context.require_session().coverage, bucket))


def item_for(context: ToolContext, bucket: str, check: str) -> CoverageItem:
    matches = [item for item in coverage_items(context, bucket) if item.check == check]
    assert len(matches) == 1, f"{check} in {bucket}: {matches}"
    return matches[0]


def checks_in(context: ToolContext, bucket: str) -> list[str]:
    return [item.check for item in coverage_items(context, bucket)]


# --- exceptions -------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    check: str
    component_ids: list[str]
    configuration: str


def accepted(
    package: EvidencePackage,
    context: ToolContext,
    check: str,
    *,
    status: str = "active",
    note: str = "legacy tree, accepted by the owner",
) -> ReviewException:
    """One exception bound to the housing's instances for `check`, put on the context."""
    store = ExceptionStore()
    exception = store.accept(
        AcceptedFinding(
            check=check,
            component_ids=[
                component.id for component in package.components if component.document_id == HOUSING
            ],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note=note,
        at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    exception.status = status  # type: ignore[assignment]
    context.exceptions = store
    return exception


# --- 1. findings: components, inputs, provenance ----------------------------------


class TestFindingFields:
    def test_component_ids_are_every_instance_of_the_document_in_package_order(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert recorded.component_ids == ["cmp:0002", "cmp:0003"]

    def test_a_root_assembly_finding_names_the_root_instance(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        rule = RULES["rms.assembly.first_component_fixed"]
        result = finding(
            rule, ROOT, [], observed="housing-1 is not fixed", recommended_action="Fix it."
        )
        report_results(context, [result])

        [recorded] = context.require_session().findings
        assert recorded.component_ids == ["cmp:0001"]

    def test_one_inputs_string_per_subject_naming_id_name_type_ref_and_scope(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(
            context,
            [fail_result(package, "rms.intent.every_feature_described", HOUSING, "Boss", "Hole1")],
        )

        [recorded] = context.require_session().findings
        boss, hole = named(package, HOUSING, "Boss", "Hole1")
        assert recorded.inputs == [
            f"{boss.id} Boss [Extrusion] persist_ref={boss.persist_ref} scope={HOUSING}",
            f"{hole.id} Hole1 [HoleWzd] persist_ref={hole.persist_ref} scope={HOUSING}",
        ]

    def test_tool_result_ids_carry_the_current_step_and_no_calculation_is_invented(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        step_id = context.current_step_id
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert recorded.tool_result_ids == [step_id]
        assert recorded.calculation is None

    def test_a_document_with_no_instance_yields_unresolved_coverage_and_no_finding(self) -> None:
        package = build_package(ghost=True)
        context = context_for(package)
        report_results(context, [fail_result(package, "rms.core.shell_last", GHOST, "Boss3")])

        assert context.require_session().findings == []
        item = item_for(context, "unresolved", "rms.core.shell_last")
        assert item.scope.document_ids == [GHOST]
        assert f"no component instance for {GHOST}" in item.reason

    def test_a_finding_on_a_document_with_other_configurations_says_they_were_not_read(
        self,
    ) -> None:
        package = build_package(
            configurations=["Default", "Machining", "Casting"],
            gaps=[
                Gap(
                    kind="not_extracted",
                    entity_kind="feature_tree_configuration",
                    entity_id=HOUSING,
                    reason="also used under Machining, Casting",
                    error=None,
                )
            ],
        )
        context = context_for(package)
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert "other configurations not read: Machining, Casting" in recorded.coverage_limits

    def test_a_document_without_the_gap_carries_no_configuration_limit(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert not any("other configurations" in limit for limit in recorded.coverage_limits)


# --- 2. severities ----------------------------------------------------------------


class TestSeverity:
    @pytest.mark.parametrize(
        ("rule_id", "status", "severity"),
        [
            ("rms.core.shell_last", "demonstrated", "medium"),
            ("rms.refs.direction", "demonstrated", "high"),
            ("rms.refs.quarantine_has_no_children", "demonstrated", "high"),
            ("rms.sketches.not_over_defined", "demonstrated", "high"),
            ("rms.sketches.fully_defined", "demonstrated", "medium"),
            ("rms.detail.holes_last", "suspected", "low"),
            ("rms.folders.present", "suspected", "low"),
        ],
    )
    def test_status_and_severity_come_from_the_rule(
        self,
        package: EvidencePackage,
        context: ToolContext,
        rule_id: str,
        status: str,
        severity: str,
    ) -> None:
        report_results(context, [fail_result(package, rule_id, HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert (recorded.check, recorded.status, recorded.severity) == (rule_id, status, severity)


# --- 3. exceptions ----------------------------------------------------------------


class TestExceptions:
    def test_an_active_exception_waives_the_finding_and_is_cited(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        exception = accepted(package, context, "rms.core.shell_last")
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert recorded.status == "checked_within_scope"
        assert recorded.severity == "info"
        assert recorded.exception_id == exception.id
        assert f"exception:{exception.id}: {exception.note}" in recorded.coverage_limits

    def test_a_needs_review_exception_leaves_the_finding_standing_with_the_marker(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        exception = accepted(package, context, "rms.core.shell_last", status="needs_review")
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert recorded.status == "demonstrated"
        assert f"needs re-review: {exception.id}" in recorded.observed
        assert recorded.exception_id == exception.id

    def test_an_exception_for_another_rule_does_not_clear_this_one(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        accepted(package, context, "rms.sketches.fully_defined")
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert recorded.status == "demonstrated"
        assert recorded.exception_id is None

    def test_a_warn_outcome_never_consults_the_store(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        accepted(package, context, "rms.detail.holes_last")
        report_results(context, [fail_result(package, "rms.detail.holes_last", HOUSING, "Hole1")])

        [recorded] = context.require_session().findings
        assert recorded.status == "suspected"
        assert recorded.exception_id is None

    def test_a_run_with_no_store_records_the_finding_unchanged(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        assert context.exception_store() is None
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        [recorded] = context.require_session().findings
        assert recorded.status == "demonstrated"


# --- 4. aggregated coverage -------------------------------------------------------


class TestAggregatedCoverage:
    def test_one_item_per_rule_per_bucket_with_documents_and_reasons(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        rule = RULES["rms.quarantine.chamfers_before_fillets"]
        report_results(
            context,
            [
                skipped(rule, HOUSING, "no Quarantine group"),
                skipped(rule, BRACKET, "no Quarantine group"),
                passed(RULES["rms.core.shell_last"], HOUSING),
                passed(RULES["rms.core.shell_last"], BRACKET),
            ],
        )

        skip_item = item_for(context, "skipped", rule.id)
        assert skip_item.scope.document_ids == [HOUSING, BRACKET]
        assert skip_item.scope.configuration == package.design.active_configuration
        assert skip_item.reason == (
            f"2 document(s): {HOUSING}: no Quarantine group; {BRACKET}: no Quarantine group"
        )

        checked_item = item_for(context, "checked", "rms.core.shell_last")
        assert checked_item.scope.document_ids == [HOUSING, BRACKET]
        assert checked_item.reason == "2 document(s)"

    def test_a_rule_in_two_buckets_writes_one_item_in_each(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        rule = RULES["rms.sketches.fully_defined"]
        report_results(
            context,
            [
                passed(rule, HOUSING, named(package, HOUSING, "Sketch7")),
                unresolved(rule, BRACKET, "Sketch9: sketch status unavailable"),
            ],
        )

        assert item_for(context, "checked", rule.id).scope.document_ids == [HOUSING]
        item = item_for(context, "unresolved", rule.id)
        assert item.scope.document_ids == [BRACKET]
        assert item.reason == f"1 document(s): {BRACKET}: Sketch9: sketch status unavailable"

    def test_a_second_evaluation_replaces_rather_than_duplicates(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        results = [
            passed(RULES["rms.core.shell_last"], HOUSING),
            passed(RULES["rms.core.shell_last"], BRACKET),
        ]
        report_results(context, results)
        report_results(context, results)

        item = item_for(context, "checked", "rms.core.shell_last")
        assert item.scope.document_ids == [HOUSING, BRACKET]
        assert checks_in(context, "checked").count("rms.core.shell_last") == 1

    def test_findings_are_not_also_aggregated_as_coverage(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [fail_result(package, "rms.core.shell_last", HOUSING, "Boss")])

        assert "rms.core.shell_last" not in checks_in(context, "checked")
        assert "rms.core.shell_last" not in checks_in(context, "unresolved")


# --- 5. the review summary --------------------------------------------------------


class TestSummary:
    def test_checked_when_no_rule_was_unresolved_for_any_document(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(
            context,
            [
                passed(RULES["rms.core.shell_last"], HOUSING),
                skipped(RULES["rms.quarantine.largest_fillet_first"], HOUSING, "no Quarantine"),
                fail_result(package, "rms.sketches.fully_defined", HOUSING, "Sketch7"),
            ],
        )

        assert "modeling.resilience" not in checks_in(context, "unresolved")
        item = item_for(context, "checked", "modeling.resilience")
        assert item.reason == (
            "1 checked, 1 skipped, 0 unresolved rule result(s) over 1 document(s); 1 finding(s)"
        )
        assert item.scope.document_ids == [HOUSING]

    def test_unresolved_when_a_rule_was_unresolved_with_the_count(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(
            context,
            [
                passed(RULES["rms.core.shell_last"], HOUSING),
                unresolved(RULES["rms.sketches.fully_defined"], BRACKET, "status unavailable"),
            ],
        )

        assert "modeling.resilience" not in checks_in(context, "checked")
        item = item_for(context, "unresolved", "modeling.resilience")
        assert item.reason == (
            "1 checked, 0 skipped, 1 unresolved rule result(s) over 2 document(s); 0 finding(s)"
        )
        assert item.scope.document_ids == [HOUSING, BRACKET]

    def test_a_later_call_moves_the_summary_out_of_the_bucket_it_was_in(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])
        assert "modeling.resilience" in checks_in(context, "checked")

        report_results(
            context,
            [unresolved(RULES["rms.assembly.mate_chain_depth"], ROOT, "no fixed child")],
        )

        assert "modeling.resilience" not in checks_in(context, "checked")
        assert "modeling.resilience" in checks_in(context, "unresolved")

    def test_the_coverage_only_rules_do_not_make_the_summary_unresolved(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])

        assert "rms.assembly.mates_described" in checks_in(context, "unresolved")
        assert "modeling.resilience" in checks_in(context, "checked")


# --- 6. unknown type names --------------------------------------------------------


class TestUnknownTypes:
    def test_absent_when_every_type_name_is_in_the_table(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])

        assert "rms.types.unknown" not in checks_in(context, "unresolved")

    def test_lists_each_unknown_type_name_with_its_count_and_the_documents(self) -> None:
        package = rms_package(
            parts=[
                PartSpec(
                    document_id=HOUSING,
                    name="housing",
                    features=[
                        folder(
                            CORE,
                            feature("Widget1", "SmartComponent"),
                            feature("Widget2", "SmartComponent"),
                            feature("Gizmo", "MagicFeature"),
                        )
                    ],
                ),
                PartSpec(
                    document_id=BRACKET,
                    name="bracket",
                    features=[folder(CORE, feature("Widget3", "SmartComponent"))],
                ),
            ]
        )
        context = context_for(package)
        report_results(
            context,
            [
                passed(RULES["rms.core.shell_last"], HOUSING),
                passed(RULES["rms.core.shell_last"], BRACKET),
            ],
        )

        item = item_for(context, "unresolved", "rms.types.unknown")
        assert item.reason == (
            "feature type names not in the calibrated table: SmartComponent x3, MagicFeature x1"
        )
        assert item.scope.document_ids == [HOUSING, BRACKET]

    def test_folders_and_end_tags_are_not_unknown_type_names(self) -> None:
        package = rms_package(
            parts=[
                PartSpec(
                    document_id=HOUSING,
                    name="housing",
                    features=[folder(CORE, feature("Boss", "Extrusion"))],
                    shape="flat",
                )
            ]
        )
        context = context_for(package)
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])

        assert "rms.types.unknown" not in checks_in(context, "unresolved")


# --- 7. the rules that are never dispatched ---------------------------------------


class TestCoverageOnlyRules:
    def test_the_four_data_gaps_and_six_out_of_scope_rules_are_written_once(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])

        gaps = [rule for rule in coverage_only() if rule.coverage[0] == "unresolved"]
        out = [rule for rule in coverage_only() if rule.coverage[0] == "out_of_scope"]
        assert (len(gaps), len(out)) == (4, 6)
        for rule in gaps:
            item = item_for(context, "unresolved", rule.id)
            assert item.reason == rule.coverage[1]
        for rule in out:
            item = item_for(context, "out_of_scope", rule.id)
            assert item.reason == rule.coverage[1]
        assert checks_in(context, "out_of_scope") == [rule.id for rule in out]

    def test_subassemblies_item_names_the_subassembly_documents(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])

        item = item_for(context, "unresolved", "rms.assembly.subassemblies")
        assert item.scope.document_ids == [SUBASSEMBLY]

    def test_the_other_data_gap_items_name_no_document(
        self, package: EvidencePackage, context: ToolContext
    ) -> None:
        report_results(context, [passed(RULES["rms.core.shell_last"], HOUSING)])

        item = item_for(context, "unresolved", "rms.assembly.mates_described")
        assert item.scope.document_ids == []
        assert item.scope.configuration == package.design.active_configuration


# --- 8. the unresolved part document ----------------------------------------------


class TestUnresolvedDocument:
    def test_every_part_and_equation_rule_reports_the_component_state(self) -> None:
        package = build_package(
            housing_instances=[InstanceSpec("housing-1", suppression="lightweight")]
        )
        package = package.model_copy(
            update={"features": [row for row in package.features if row.document_id != HOUSING]}
        )
        context = context_for(package)
        results = evaluate_part(HOUSING, [], TABLE, assign_groups([], TABLE), package)

        report_results(context, results)

        for rule_id in PART_RULE_IDS + EQUATION_RULE_IDS:
            item = item_for(context, "unresolved", rule_id)
            assert item.scope.document_ids == [HOUSING]
            assert item.reason == (
                f"1 document(s): {HOUSING}: component housing-1 lightweight; tree not read"
            )
        assert context.require_session().findings == []
