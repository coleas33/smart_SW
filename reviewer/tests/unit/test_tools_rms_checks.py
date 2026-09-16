"""Unit tests for the RMS check tools (T027; assembly T034, equations T041).

`checks/rms/part.py` and `checks/rms/equations.py` decide what a rule concludes and
`checks/rms/report.py` decides what a conclusion looks like in the session; all three have
their own tests. What is pinned here is the tool in between - the rows of
`specs/003-resilient-modeling/contracts/tools.md` that say what each tool is dispatched
over and what a caller gets back:

- **`document_id=null` means every part document, including the unresolved ones.** A part
  whose tree was never read is still evaluated - as unresolved for every part- and
  equation-scope rule - rather than quietly dropped, because a document nobody looked at
  is not a document that passed (`rules.md`, "Unresolved part documents");
- **an id that names nothing, or names an assembly, is an error result**, never an
  exception and never an empty run that reads like "there was nothing to check";
- **the session is what the tool writes**: findings for the failing rules, one aggregated
  coverage item per rule per bucket, and - because each call re-evaluates its scope in
  full - a second call that replaces those *coverage* items instead of doubling them,
  while its findings are appended like every other check tool's;
- **exceptions are consulted for `fail` outcomes only, and always with `check=<rule id>`**,
  so a waiver accepted for one rule cannot quieten another rule about the same part.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from swreview.checks.rms import RULES
from swreview.checks.rms.report import SUMMARY_CHECK
from swreview.exceptions import ExceptionStore, ReviewException
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, ReviewSession
from swreview.tools import rms_checks
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.registry import RecordedTool, ToolRegistry
from tests.support.features import (
    AssemblySpec,
    InstanceSpec,
    MateSpec,
    PartSpec,
    SubassemblySpec,
    equation,
    feature,
    folder,
    rms_package,
    sketch_feature,
)

ROOT = "doc:1"
FRAME = "doc:2"
"""The compliant part: six groups, everything described, nothing out of order."""

COVER = "doc:3"
"""The part that fails `rms.intent.every_feature_described` and warns on
`rms.folders.present`, so one call reaches both a waivable and a non-waivable outcome."""

GHOST = "doc:4"
"""The part with no feature rows and no resolved instance: unresolved for every rule."""

COVER_INSTANCE = "cmp:0003"

DESCRIBED_RULE = "rms.intent.every_feature_described"
FOLDERS_PRESENT_RULE = "rms.folders.present"
GLOBALS_RULE = "rms.params.global_variables_present"
DIMENSIONS_RULE = "rms.params.dimensions_driven_by_equations"

PART_AND_EQUATION_RULE_IDS: tuple[str, ...] = tuple(
    rule.id
    for rule in RULES.values()
    if rule.coverage is None and rule.scope in ("part", "equations")
)

EQUATION_RULE_IDS: tuple[str, ...] = tuple(
    rule.id for rule in RULES.values() if rule.coverage is None and rule.scope == "equations"
)


def frame() -> PartSpec:
    """Six groups in the method's order, one described feature, one defined sketch.

    Its equation manager holds a global and a dimension driven from it, so the part that
    passes the part rules passes the equation rules too and `check_rms_equations` over it
    writes coverage and no finding.
    """
    return PartSpec(
        document_id=FRAME,
        name="frame",
        equations=(
            equation('"thickness" = 3mm', is_global=True, value=0.003),
            equation('"D1@Sketch1" = "thickness" * 2', value=0.006),
        ),
        features=(
            folder("1-Ref", feature("Plane1", "RefPlane")),
            folder("2-Construction", feature("Surface1", "SurfaceExtrude")),
            folder(
                "3-Core",
                sketch_feature("Sketch1", consumers=("Boss-Extrude1",)),
                feature("Boss-Extrude1", "Extrusion", parent_names=("Sketch1",)),
            ),
            folder("4-Detail", feature("Hole1", "HoleWzd")),
            folder("5-Modify", feature("Draft1", "Draft")),
            folder("6-Quarantine", feature("Chamfer1", "Chamfer")),
        ),
    )


def cover() -> PartSpec:
    """Two groups only, a Core feature nobody described, and an empty equation manager.

    A manager that was read and holds nothing is an answer, not a gap: it fails
    `rms.params.global_variables_present` and warns on
    `rms.params.dimensions_driven_by_equations`, so one `check_rms_equations` call reaches
    both a waivable and a non-waivable outcome.
    """
    return PartSpec(
        document_id=COVER,
        name="cover",
        features=(
            folder("3-Core", feature("Boss-Extrude2", "Extrusion", description="")),
            folder("4-Detail", feature("Hole2", "HoleWzd")),
        ),
    )


def ghost() -> PartSpec:
    """A part whose only instance is suppressed, so its tree was never read."""
    return PartSpec(
        document_id=GHOST,
        name="ghost",
        features=(),
        instances=(InstanceSpec("ghost-1", suppression="suppressed"),),
    )


def package() -> EvidencePackage:
    return rms_package(
        parts=[frame(), cover(), ghost()],
        assembly=AssemblySpec(document_id=ROOT, name="cover-assy"),
    )


@pytest.fixture
def evidence() -> EvidencePackage:
    return package()


@pytest.fixture
def context(evidence: EvidencePackage) -> Iterator[ToolContext]:
    tool_context = context_for(evidence)
    with use_context(tool_context):
        yield tool_context


def recorded(context: ToolContext, name: str) -> RecordedTool:
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


def session_of(context: ToolContext) -> ReviewSession:
    session = context.session
    assert session is not None
    return session


def items(session: ReviewSession, bucket: str) -> list[CoverageItem]:
    return list(getattr(session.coverage, bucket))


def checks_in(session: ReviewSession, bucket: str) -> list[str]:
    return [item.check for item in items(session, bucket)]


def documents_for(session: ReviewSession, bucket: str, check: str) -> list[str]:
    matching = [item for item in items(session, bucket) if item.check == check]
    assert len(matching) == 1, f"{check} appears {len(matching)} time(s) in {bucket}"
    return list(matching[0].scope.document_ids)


# --- the tool is registered ---------------------------------------------------------


def test_check_rms_part_is_a_registered_check_tool(context: ToolContext) -> None:
    assert recorded(context, "check_rms_part").name == "check_rms_part"


# --- one document, every document ---------------------------------------------------


def test_one_document_evaluates_that_document_only(context: ToolContext) -> None:
    result = rms_checks.check_rms_part(document_id=COVER)

    assert result["status"] == "recorded"
    assert result["documents"] == [COVER]
    session = session_of(context)
    assert {
        document
        for bucket in ("checked", "skipped", "unresolved")
        for item in items(session, bucket)
        if item.check in PART_AND_EQUATION_RULE_IDS
        for document in item.scope.document_ids
    } == {COVER}


def test_one_document_names_only_that_documents_instances_on_its_findings(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part(document_id=COVER)

    session = session_of(context)
    assert session.findings
    assert {tuple(item.component_ids) for item in session.findings} == {(COVER_INSTANCE,)}


def test_every_part_document_is_evaluated_when_no_id_is_given(context: ToolContext) -> None:
    result = rms_checks.check_rms_part()

    assert result["documents"] == [FRAME, COVER, GHOST]


def test_the_unresolved_document_is_unresolved_for_every_part_and_equation_rule(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part()

    session = session_of(context)
    unresolved = {
        item.check
        for item in items(session, "unresolved")
        if GHOST in item.scope.document_ids and item.check != SUMMARY_CHECK
    }
    assert unresolved == set(PART_AND_EQUATION_RULE_IDS)


def test_the_unresolved_documents_reason_names_the_component_state(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part(document_id=GHOST)

    session = session_of(context)
    reasons = [
        item.reason
        for item in items(session, "unresolved")
        if item.check in PART_AND_EQUATION_RULE_IDS
    ]
    assert len(reasons) == len(PART_AND_EQUATION_RULE_IDS)
    assert all(
        f"{GHOST}: component ghost-1 suppressed; tree not read" in reason
        for reason in reasons
    )


def test_the_compliant_part_produces_no_finding(context: ToolContext) -> None:
    result = rms_checks.check_rms_part(document_id=FRAME)

    assert result["findings"] == []
    assert session_of(context).findings == []


# --- ids that name nothing a part rule can read -------------------------------------


def test_an_unknown_document_id_is_an_error_result(context: ToolContext) -> None:
    result = rms_checks.check_rms_part(document_id="doc:99")

    assert result == {"error": "unknown document id 'doc:99'"}
    assert session_of(context).findings == []
    assert not session_of(context).coverage.checked


def test_an_assembly_document_id_is_an_error_result(context: ToolContext) -> None:
    result = rms_checks.check_rms_part(document_id=ROOT)

    assert "error" in result
    assert ROOT in result["error"]
    assert "part" in result["error"]


def test_an_error_result_is_recorded_as_a_failed_call(context: ToolContext) -> None:
    tool = recorded(context, "check_rms_part")
    call = tool.call({"document_id": "doc:99"})

    assert call.is_error
    session = session_of(context)
    assert [step.status for step in session.steps] == ["error"]
    assert checks_in(session, "failed") == ["tool.check_rms_part"]


# --- what lands in the session ------------------------------------------------------


def test_a_failing_rule_becomes_a_finding_with_the_rules_severity(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part(document_id=COVER)

    session = session_of(context)
    described = [item for item in session.findings if item.check == DESCRIBED_RULE]
    assert len(described) == 1
    assert described[0].status == "demonstrated"
    assert described[0].severity == "medium"
    assert "Boss-Extrude2" in described[0].observed


def test_a_warning_rule_becomes_a_suspected_finding(context: ToolContext) -> None:
    rms_checks.check_rms_part(document_id=COVER)

    session = session_of(context)
    present = [item for item in session.findings if item.check == FOLDERS_PRESENT_RULE]
    assert len(present) == 1
    assert (present[0].status, present[0].severity) == ("suspected", "low")


def test_coverage_is_aggregated_one_item_per_rule_per_bucket(context: ToolContext) -> None:
    rms_checks.check_rms_part()

    session = session_of(context)
    for bucket in ("checked", "skipped", "unresolved", "out_of_scope"):
        checks = checks_in(session, bucket)
        assert len(checks) == len(set(checks)), f"{bucket} holds a duplicated check"


def test_an_aggregated_item_lists_every_document_that_reached_that_bucket(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part()

    session = session_of(context)
    assert documents_for(session, "checked", DESCRIBED_RULE) == [FRAME]
    assert documents_for(session, "unresolved", DESCRIBED_RULE) == [GHOST]


def test_the_never_dispatched_rules_and_the_summary_are_written_once(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part()

    session = session_of(context)
    assert "rms.assembly.subassemblies" in checks_in(session, "unresolved")
    assert "rms.advisory.description_quality" in checks_in(session, "out_of_scope")
    summary = [
        item.check
        for bucket in ("checked", "unresolved")
        for item in items(session, bucket)
        if item.check == SUMMARY_CHECK
    ]
    assert summary == [SUMMARY_CHECK]


def test_the_result_reports_the_findings_and_the_coverage_it_wrote(
    context: ToolContext,
) -> None:
    result = rms_checks.check_rms_part(document_id=COVER)

    session = session_of(context)
    assert [item["check"] for item in result["findings"]] == [
        item.check for item in session.findings
    ]
    assert {entry["check"] for entry in result["coverage"]} >= {
        SUMMARY_CHECK,
        "rms.folders.ordered",
    }


# --- step recording -----------------------------------------------------------------


def test_the_call_is_recorded_as_one_step(context: ToolContext) -> None:
    tool = recorded(context, "check_rms_part")
    tool.call({"document_id": COVER})

    session = session_of(context)
    assert [step.tool for step in session.steps] == ["check_rms_part"]
    assert session.steps[0].status == "ok"


def test_every_finding_cites_the_step_the_call_is_recorded_as(context: ToolContext) -> None:
    tool = recorded(context, "check_rms_part")
    tool.call({"document_id": COVER})

    session = session_of(context)
    assert session.findings
    assert all(item.tool_result_ids == [0] for item in session.findings)


# --- a second call replaces coverage ------------------------------------------------


BUCKETS: tuple[str, ...] = ("checked", "skipped", "unresolved", "out_of_scope")


def coverage_state(session: ReviewSession) -> dict[str, list[tuple[str, list[str]]]]:
    """Every coverage bucket as `(check, documents)` pairs, for a before/after compare."""
    return {
        bucket: [(item.check, list(item.scope.document_ids)) for item in items(session, bucket)]
        for bucket in BUCKETS
    }


def test_a_second_call_replaces_the_aggregated_coverage_rather_than_adding_to_it(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part()
    first = coverage_state(session_of(context))

    rms_checks.check_rms_part()
    second = coverage_state(session_of(context))

    for bucket in BUCKETS:
        assert sorted(second[bucket]) == sorted(first[bucket]), bucket


def test_a_second_call_appends_its_findings_rather_than_replacing_them(
    context: ToolContext,
) -> None:
    """Coverage is replaced on a re-run; findings are not. That asymmetry is the contract.

    `contracts/tools.md` promises exactly one thing about a second call - "running a tool
    twice does not duplicate coverage" - because an aggregated coverage item stands for
    the current state of a rule, while a finding stands for one occurrence and is written
    through the same `ToolContext.record_finding` every other check tool appends to. So a
    second call over the same documents leaves the same coverage and a second copy of
    every finding. It is pinned here because the tool description and the system prompt
    have to say so: the model grades a document once (no argument grades them all), and
    re-grading one is how it adds findings, not how it refreshes them.
    """
    rms_checks.check_rms_part()
    session = session_of(context)
    first = [finding.check for finding in session.findings]
    assert first

    rms_checks.check_rms_part()
    after = [finding.check for finding in session.findings]

    assert after == first + first
    assert len({finding.id for finding in session.findings}) == len(after)


def test_a_narrower_second_call_replaces_only_the_rules_it_re_evaluated(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_part()
    rms_checks.check_rms_part(document_id=COVER)

    session = session_of(context)
    assert documents_for(session, "checked", DESCRIBED_RULE) == [FRAME]
    assert documents_for(session, "unresolved", "rms.folders.ordered") == [GHOST]


# --- exceptions ---------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    check: str
    component_ids: list[str]
    configuration: str


class RecordingStore(ExceptionStore):
    """An `ExceptionStore` that remembers every lookup the report layer made."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def match(
        self,
        package: EvidencePackage,
        component_ids: Sequence[str],
        configuration: str,
        check: str,
    ) -> ReviewException | None:
        self.calls.append((tuple(component_ids), check))
        return super().match(package, component_ids, configuration, check)


def accept(
    store: ExceptionStore,
    evidence: EvidencePackage,
    check: str,
    component_ids: Sequence[str],
) -> ReviewException:
    return store.accept(
        AcceptedFinding(
            check=check,
            component_ids=list(component_ids),
            configuration=evidence.design.active_configuration,
        ),
        evidence,
        by="owner",
        note="legacy tree, accepted by the owner",
        at=datetime(2026, 9, 15, tzinfo=UTC),
    )


def test_the_store_is_asked_once_per_fail_outcome_with_that_rules_id(
    context: ToolContext,
) -> None:
    store = RecordingStore()
    context.exceptions = store

    rms_checks.check_rms_part(document_id=COVER)

    assert store.calls == [((COVER_INSTANCE,), DESCRIBED_RULE)]


def test_a_warn_outcome_never_asks_the_store(context: ToolContext) -> None:
    store = RecordingStore()
    context.exceptions = store

    rms_checks.check_rms_part()

    assert FOLDERS_PRESENT_RULE not in [check for _, check in store.calls]


def test_an_active_exception_for_the_rule_waives_the_finding(
    context: ToolContext, evidence: EvidencePackage
) -> None:
    store = ExceptionStore()
    exception = accept(store, evidence, DESCRIBED_RULE, [COVER_INSTANCE])
    context.exceptions = store

    rms_checks.check_rms_part(document_id=COVER)

    session = session_of(context)
    described = next(item for item in session.findings if item.check == DESCRIBED_RULE)
    assert described.status == "checked_within_scope"
    assert described.exception_id == exception.id


def test_an_exception_for_another_rule_does_not_clear_this_one(
    context: ToolContext, evidence: EvidencePackage
) -> None:
    store = ExceptionStore()
    accept(store, evidence, "rms.core.shell_last", [COVER_INSTANCE])
    context.exceptions = store

    rms_checks.check_rms_part(document_id=COVER)

    session = session_of(context)
    described = next(item for item in session.findings if item.check == DESCRIBED_RULE)
    assert described.status == "demonstrated"
    assert described.exception_id is None


# --- check_rms_equations (T041) -----------------------------------------------------
#
# The same three questions as `check_rms_part`, because the row of `contracts/tools.md`
# is the same shape - which documents a call is dispatched over, what an id that names
# nothing does, and what lands in the session - and the tool reuses the same
# `part_documents` and `report_results`. What is new is only the dispatch: the *equation*
# rules, over the same part documents.


def test_check_rms_equations_is_a_registered_check_tool(context: ToolContext) -> None:
    assert recorded(context, "check_rms_equations").name == "check_rms_equations"


def test_check_rms_equations_grades_every_part_document_by_default(
    context: ToolContext,
) -> None:
    result = rms_checks.check_rms_equations()

    assert result["status"] == "recorded"
    assert result["documents"] == [FRAME, COVER, GHOST]


def test_check_rms_equations_for_one_document_evaluates_that_document_only(
    context: ToolContext,
) -> None:
    result = rms_checks.check_rms_equations(document_id=FRAME)

    assert result["documents"] == [FRAME]
    session = session_of(context)
    assert {
        document
        for bucket in ("checked", "skipped", "unresolved")
        for item in items(session, bucket)
        if item.check in EQUATION_RULE_IDS
        for document in item.scope.document_ids
    } == {FRAME}


def test_check_rms_equations_names_only_that_documents_instances_on_its_findings(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_equations(document_id=COVER)

    session = session_of(context)
    assert session.findings
    assert {tuple(item.component_ids) for item in session.findings} == {(COVER_INSTANCE,)}


def test_check_rms_equations_does_not_dispatch_the_part_rules(context: ToolContext) -> None:
    """The scopes are separate tools: grading equations must not re-grade the tree."""
    rms_checks.check_rms_equations()

    session = session_of(context)
    part_rules = set(PART_AND_EQUATION_RULE_IDS) - set(EQUATION_RULE_IDS)
    written = {
        item.check
        for bucket in ("checked", "skipped", "unresolved")
        for item in items(session, bucket)
    }
    assert not written & part_rules
    assert {finding.check for finding in session.findings} <= set(EQUATION_RULE_IDS)


def test_the_part_whose_manager_holds_a_global_and_a_driven_dimension_passes(
    context: ToolContext,
) -> None:
    result = rms_checks.check_rms_equations(document_id=FRAME)

    assert result["findings"] == []
    assert documents_for(session_of(context), "checked", GLOBALS_RULE) == [FRAME]


def test_an_empty_equation_manager_fails_the_globals_rule(context: ToolContext) -> None:
    rms_checks.check_rms_equations(document_id=COVER)

    session = session_of(context)
    globals_finding = [item for item in session.findings if item.check == GLOBALS_RULE]
    assert len(globals_finding) == 1
    assert globals_finding[0].status == "demonstrated"
    assert globals_finding[0].severity == "medium"
    assert "no equations" in globals_finding[0].observed
    assert globals_finding[0].component_ids == [COVER_INSTANCE]


def test_an_empty_equation_manager_warns_on_the_dimensions_rule(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_equations(document_id=COVER)

    session = session_of(context)
    dimensions = [item for item in session.findings if item.check == DIMENSIONS_RULE]
    assert len(dimensions) == 1
    assert (dimensions[0].status, dimensions[0].severity) == ("suspected", "low")


def test_the_unresolved_document_is_unresolved_for_both_equation_rules(
    context: ToolContext,
) -> None:
    rms_checks.check_rms_equations(document_id=GHOST)

    session = session_of(context)
    reasons = [
        item.reason for item in items(session, "unresolved") if item.check in EQUATION_RULE_IDS
    ]
    assert len(reasons) == len(EQUATION_RULE_IDS)
    assert all(
        f"{GHOST}: component ghost-1 suppressed; tree not read" in reason for reason in reasons
    )


def test_check_rms_equations_rejects_an_unknown_document_id(context: ToolContext) -> None:
    result = rms_checks.check_rms_equations(document_id="doc:99")

    assert result == {"error": "unknown document id 'doc:99'"}
    assert session_of(context).findings == []


def test_check_rms_equations_rejects_an_assembly_document_id(context: ToolContext) -> None:
    result = rms_checks.check_rms_equations(document_id=ROOT)

    assert "error" in result
    assert ROOT in result["error"]


def test_check_rms_equations_writes_the_summary_and_the_undispatched_rules(
    context: ToolContext,
) -> None:
    """Whichever of the three tools runs first writes them; here that is this one."""
    rms_checks.check_rms_equations()

    session = session_of(context)
    assert "rms.assembly.subassemblies" in checks_in(session, "unresolved")
    assert "rms.advisory.description_quality" in checks_in(session, "out_of_scope")
    assert SUMMARY_CHECK in [
        item.check for bucket in ("checked", "unresolved") for item in items(session, bucket)
    ]


def test_a_second_equations_call_replaces_its_coverage(context: ToolContext) -> None:
    rms_checks.check_rms_equations()
    first = coverage_state(session_of(context))

    rms_checks.check_rms_equations()
    second = coverage_state(session_of(context))

    for bucket in BUCKETS:
        assert sorted(second[bucket]) == sorted(first[bucket]), bucket


def test_the_equations_call_is_recorded_as_one_step_its_findings_cite(
    context: ToolContext,
) -> None:
    tool = recorded(context, "check_rms_equations")
    tool.call({"document_id": COVER})

    session = session_of(context)
    assert [step.tool for step in session.steps] == ["check_rms_equations"]
    assert session.steps[0].status == "ok"
    assert session.findings
    assert all(item.tool_result_ids == [0] for item in session.findings)


def test_the_store_is_asked_for_the_failing_equation_rule_only(context: ToolContext) -> None:
    store = RecordingStore()
    context.exceptions = store

    rms_checks.check_rms_equations(document_id=COVER)

    assert store.calls == [((COVER_INSTANCE,), GLOBALS_RULE)]


def test_an_active_exception_waives_the_globals_finding(
    context: ToolContext, evidence: EvidencePackage
) -> None:
    store = ExceptionStore()
    exception = accept(store, evidence, GLOBALS_RULE, [COVER_INSTANCE])
    context.exceptions = store

    rms_checks.check_rms_equations(document_id=COVER)

    session = session_of(context)
    globals_finding = next(item for item in session.findings if item.check == GLOBALS_RULE)
    assert globals_finding.status == "checked_within_scope"
    assert globals_finding.exception_id == exception.id


# --- check_rms_assembly (T034) ------------------------------------------------------

# What the second tool of the family adds to the contract above.
#
# `check_rms_assembly` takes no arguments at all, so there is no dispatch *argument* to
# pin - what there is instead is the dispatch *decision* `contracts/tools.md` makes for
# it: the root assembly document and nothing else. The subassembly documents are not
# graded, and they are not silently absent either; they arrive through `report_results`
# as the `rms.assembly.subassemblies` item that names them.

SUBASSEMBLY = "doc:5"
"""The subassembly document the assembly rules never reach."""

ROOT_INSTANCE = "cmp:0001"

FACE = "swSelFACES"
"""A geometry entity kind, so the one mate below fails `mates_to_reference_geometry`."""

UNDER_DEFINED = 2
"""`swConstrainedStatus_e.swUnderConstrained`, as `checks/rms_types.yaml` maps it."""

MATES_RULE = "rms.assembly.mates_to_reference_geometry"
FIRST_COMPONENT_RULE = "rms.assembly.first_component_fixed"
CHAIN_RULE = "rms.assembly.mate_chain_depth"
TOOLBOX_RULE = "rms.assembly.toolbox_parts_not_configurations"
SUBASSEMBLIES_RULE = "rms.assembly.subassemblies"

ASSEMBLY_RULE_IDS: tuple[str, ...] = tuple(
    rule.id for rule in RULES.values() if rule.coverage is None and rule.scope == "assembly"
)


def assembly_package() -> EvidencePackage:
    """A root assembly that reaches a fail, a warn, a skip and a pass in one call.

    `frame-1` is the first child of `cmp:0001` and is neither fixed nor fully constrained,
    so `first_component_fixed` fails; the one mate sits on faces, so
    `mates_to_reference_geometry` fails; `cover-1` is fixed and one mate away, so
    `mate_chain_depth` passes; nothing is Toolbox, so that rule skips. The parts carry no
    feature rows: an assembly call must not evaluate a part rule, and a package with
    nothing for one to read makes that visible rather than merely plausible.
    """
    return rms_package(
        parts=[
            PartSpec(
                document_id=FRAME,
                name="frame",
                instances=(InstanceSpec("frame-1", constrained_status_raw=UNDER_DEFINED),),
            ),
            PartSpec(
                document_id=COVER,
                name="cover",
                instances=(InstanceSpec("cover-1", is_fixed=True),),
            ),
        ],
        assembly=AssemblySpec(
            document_id=ROOT,
            name="cover-assy",
            mates=(MateSpec(entities=(("frame-1", FACE), ("cover-1", FACE))),),
            subassembly=SubassemblySpec(document_id=SUBASSEMBLY, name="gearbox"),
        ),
    )


@pytest.fixture
def assembly_evidence() -> EvidencePackage:
    return assembly_package()


@pytest.fixture
def assembly_context(assembly_evidence: EvidencePackage) -> Iterator[ToolContext]:
    tool_context = context_for(assembly_evidence)
    with use_context(tool_context):
        yield tool_context


def test_check_rms_assembly_is_a_registered_check_tool(assembly_context: ToolContext) -> None:
    assert recorded(assembly_context, "check_rms_assembly").name == "check_rms_assembly"


# --- the root assembly document, and only it ----------------------------------------


def test_the_root_assembly_document_is_the_only_document_graded(
    assembly_context: ToolContext,
) -> None:
    result = rms_checks.check_rms_assembly()

    assert result["status"] == "recorded"
    assert result["documents"] == [ROOT]
    session = session_of(assembly_context)
    assert {
        document
        for bucket in ("checked", "skipped", "unresolved")
        for item in items(session, bucket)
        if item.check in ASSEMBLY_RULE_IDS
        for document in item.scope.document_ids
    } == {ROOT}


def test_no_part_rule_is_dispatched_by_an_assembly_call(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    written = {
        item.check
        for bucket in ("checked", "skipped", "unresolved")
        for item in items(session, bucket)
    }
    assert written & set(PART_AND_EQUATION_RULE_IDS) == set()


def test_the_assembly_findings_name_the_root_assembly_instance(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    assert session.findings
    assert {tuple(item.component_ids) for item in session.findings} == {(ROOT_INSTANCE,)}


def test_the_subassembly_document_is_named_by_the_undispatched_rule(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    assert documents_for(session, "unresolved", SUBASSEMBLIES_RULE) == [SUBASSEMBLY]


# --- what lands in the session ------------------------------------------------------


def test_a_failing_assembly_rule_becomes_a_finding_with_the_rules_severity(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    first = [item for item in session.findings if item.check == FIRST_COMPONENT_RULE]
    assert len(first) == 1
    assert (first[0].status, first[0].severity) == ("demonstrated", "medium")
    assert "frame-1" in first[0].observed
    mates = [item for item in session.findings if item.check == MATES_RULE]
    assert len(mates) == 1
    assert mates[0].status == "demonstrated"


def test_a_passing_and_a_skipping_assembly_rule_become_coverage(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    assert documents_for(session, "checked", CHAIN_RULE) == [ROOT]
    assert TOOLBOX_RULE in checks_in(session, "skipped")


def test_assembly_coverage_is_aggregated_one_item_per_rule_per_bucket(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    for bucket in ("checked", "skipped", "unresolved", "out_of_scope"):
        checks = checks_in(session, bucket)
        assert len(checks) == len(set(checks)), f"{bucket} holds a duplicated check"


def test_the_summary_and_the_out_of_scope_rules_are_written_by_an_assembly_call(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    assert "rms.advisory.description_quality" in checks_in(session, "out_of_scope")
    summary = [
        item.check
        for bucket in ("checked", "unresolved")
        for item in items(session, bucket)
        if item.check == SUMMARY_CHECK
    ]
    assert summary == [SUMMARY_CHECK]


def test_the_assembly_result_reports_the_findings_and_the_coverage_it_wrote(
    assembly_context: ToolContext,
) -> None:
    result = rms_checks.check_rms_assembly()

    session = session_of(assembly_context)
    assert [item["check"] for item in result["findings"]] == [
        item.check for item in session.findings
    ]
    assert {entry["check"] for entry in result["coverage"]} >= {SUMMARY_CHECK, CHAIN_RULE}


# --- a package with no assembly document ---------------------------------------------

# `design.root_assembly_document_id` is whatever document the dump was rooted at -
# `PackageWriter` sets it to `DocumentIds.For(tree.RootDocumentPath)` - so a part-only dump
# names a *part* there. The assembly rules have no subject then, and the counterpart of
# `part_documents` refusing an assembly id is that this call must not grade that part as
# though it were the root assembly: "3 skipped" saying the root assembly has no mates is a
# claim about an assembly that is not in the package (constitution Principle I).


def part_only_package() -> EvidencePackage:
    """A package with no assembly document; `design` then names the one part."""
    return rms_package(parts=[PartSpec(document_id=FRAME, name="frame")])


@pytest.fixture
def part_only_context() -> Iterator[ToolContext]:
    tool_context = context_for(part_only_package())
    with use_context(tool_context):
        yield tool_context


def test_an_assembly_call_on_a_part_only_package_grades_no_document(
    part_only_context: ToolContext,
) -> None:
    result = rms_checks.check_rms_assembly()

    assert result["status"] == "recorded"
    assert result["documents"] == []
    assert result["findings"] == []


def test_every_assembly_rule_is_unresolved_when_there_is_no_assembly_document(
    part_only_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(part_only_context)
    unresolved = {item.check: item for item in items(session, "unresolved")}
    assert set(ASSEMBLY_RULE_IDS) <= set(unresolved)
    for rule_id in ASSEMBLY_RULE_IDS:
        reason = unresolved[rule_id].reason
        assert FRAME in reason, reason
        assert "part document" in reason, reason


def test_a_root_document_id_the_package_does_not_carry_is_unresolved_too() -> None:
    """The other half of the guard: `design` names a document the package does not hold,
    so there is nothing to look the kind up on and still nothing to grade."""
    package = part_only_package()
    package = package.model_copy(
        update={
            "design": package.design.model_copy(
                update={"root_assembly_document_id": "doc:99"}
            )
        }
    )
    context = context_for(package)
    with use_context(context):
        result = rms_checks.check_rms_assembly()

    assert result["documents"] == []
    reasons = [item.reason for item in items(session_of(context), "unresolved")]
    assert any("doc:99" in reason for reason in reasons), reasons


def test_no_assembly_rule_passes_or_skips_when_there_is_no_assembly_document(
    part_only_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()

    session = session_of(part_only_context)
    for bucket in ("checked", "skipped"):
        assert set(checks_in(session, bucket)) & set(ASSEMBLY_RULE_IDS) == set(), bucket


# --- step recording -----------------------------------------------------------------


def test_the_assembly_call_is_recorded_as_one_step(assembly_context: ToolContext) -> None:
    tool = recorded(assembly_context, "check_rms_assembly")
    tool.call({})

    session = session_of(assembly_context)
    assert [step.tool for step in session.steps] == ["check_rms_assembly"]
    assert session.steps[0].status == "ok"


def test_every_assembly_finding_cites_the_step_the_call_is_recorded_as(
    assembly_context: ToolContext,
) -> None:
    tool = recorded(assembly_context, "check_rms_assembly")
    tool.call({})

    session = session_of(assembly_context)
    assert session.findings
    assert all(item.tool_result_ids == [0] for item in session.findings)


# --- a second call replaces coverage ------------------------------------------------


def test_a_second_assembly_call_replaces_the_aggregated_coverage(
    assembly_context: ToolContext,
) -> None:
    rms_checks.check_rms_assembly()
    first = coverage_state(session_of(assembly_context))

    rms_checks.check_rms_assembly()
    second = coverage_state(session_of(assembly_context))

    for bucket in BUCKETS:
        assert sorted(second[bucket]) == sorted(first[bucket]), bucket
