"""The standards family's one review-only check tool (T049).

FR-035 lets this family register **exactly one** tool, and only because the shared run
skeleton dispatches through the tool registry with a session sink so that every finding's
`tool_result_ids` names a step that exists. What is pinned here is that one tool and the
four things that keep it from widening the product's tool surface:

- it is registered by `standards_tools()` **outside `REGISTRATIONS`**, the `remodel_tools()`
  precedent, so `registry.TOOL_FUNCTIONS` - which `test_provider_schema.py` asserts is
  set-equal to `contracts/agent-tools.md`'s curated tables - does not move, and neither
  does `MCP_TOOL_FUNCTIONS`;
- it is offered by `ToolRegistry._offered` **only when the context carries a standards
  run**, so a review, a general-chat session and every other tab cannot see it at all;
- it dispatches all sixteen checks over every graded document and writes findings and
  aggregated coverage to the session, replacing its own coverage on a second call;
- a check this build does not run yet is **reported** - one unresolved row naming it, and
  one `unavailable_checks` entry - rather than silently absent. This build runs all sixteen
  (T066 bound the drawing scope), so what is pinned below is the **mechanism** over a scope
  taken out of the dispatch, plus that the list is empty as things stand.

The evaluators themselves are `test_standards_{assembly,part,document}_rules.py`'s subject,
and the finding and coverage shapes are `test_standards_report.py`'s; what is asserted here
is the dispatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import CHECK_TOOL, RULES
from swreview.checks.standards.traversal import CheckedDocument, graded_documents
from swreview.exceptions import ExceptionStore, ReviewException
from swreview.ir.models import EvidencePackage
from swreview.mcp.server import MCP_TOOL_FUNCTIONS
from swreview.tools import registry as registry_module
from swreview.tools.context import ToolContext, context_for
from swreview.tools.registry import (
    REGISTRATIONS,
    TOOL_FUNCTIONS,
    SessionSink,
    ToolRegistry,
    standards_tools,
)
from swreview.tools.standards_checks import (
    NO_STANDARDS_RUN,
    NOT_BUILT,
    SCOPE_EVALUATORS,
    StandardsRun,
    attach_standards_run,
    check_standards,
    standards_run,
    unavailable_checks,
)
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    DocumentSpec,
    DrawingSpec,
    PartSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE = load_profile(FIXTURE_DIR / "profile-a.yaml")

NOT_EXPLODED = "standards.assembly.not_exploded"
DRAWING_CHECKS = tuple(rule.id for rule in RULES.values() if rule.scope == "drawing")


# --- the packages and contexts every test reads -------------------------------------------


def package_of(*documents: DocumentSpec) -> EvidencePackage:
    return standards_package(documents=list(documents), profile=PROFILE)


def exploded_package() -> EvidencePackage:
    """A root assembly left exploded, so one check fails and the rest are ordinary."""
    return package_of(
        AssemblySpec(
            name="top",
            folder="jobs/mr-400",
            is_exploded=True,
            components=[ComponentSpec(name="plate-1", document="plate")],
        ),
        PartSpec(name="plate", folder="jobs/mr-400"),
    )


def drawing_package() -> EvidencePackage:
    return package_of(
        DrawingSpec(
            name="MR-40012",
            folder="jobs/mr-400",
            active_sheet="Sheet1",
            sheets=[
                SheetSpec(name="Sheet1", was_active=True, views=[ViewSpec(name="View1")])
            ],
        )
    )


def run_for(package: EvidencePackage) -> StandardsRun:
    return StandardsRun(profile=PROFILE, documents=graded_documents(package, PROFILE))


def context_with_run(package: EvidencePackage) -> ToolContext:
    context = context_for(package)
    attach_standards_run(context, run_for(package))
    return context


def dispatch(context: ToolContext) -> dict[str, Any]:
    """The tool as the run dispatches it: through the registry, onto a session sink."""
    result = ToolRegistry().dispatch(context, sink=SessionSink(context)).call(CHECK_TOOL, {})
    return dict(result.payload)


def coverage_checks(context: ToolContext, bucket: str) -> list[str]:
    return [item.check for item in getattr(context.require_session().coverage, bucket)]


# --- 1. one tool, registered outside the curated list -------------------------------------


def test_the_family_registers_exactly_one_review_only_check_tool() -> None:
    assert [function.__name__ for function in standards_tools()] == [CHECK_TOOL]
    assert check_standards.__name__ == CHECK_TOOL


def test_the_tool_is_registered_outside_the_curated_tool_list() -> None:
    """FR-035: the MCP function list and the terminal profile's tools do not move."""
    registered = {
        function.__name__
        for registration in REGISTRATIONS
        for function in registration()
    }
    assert CHECK_TOOL not in registered
    assert CHECK_TOOL not in {function.__name__ for function in TOOL_FUNCTIONS}
    assert CHECK_TOOL not in {function.__name__ for function in MCP_TOOL_FUNCTIONS}
    assert standards_tools not in REGISTRATIONS
    assert registry_module.standards_tools is standards_tools


def test_the_tool_is_offered_only_when_the_context_carries_a_standards_run() -> None:
    package = exploded_package()
    plain = context_for(package)
    assert standards_run(plain) is None
    assert CHECK_TOOL not in {
        function.__name__ for function in ToolRegistry().functions_for(plain)
    }

    context = context_with_run(package)
    assert standards_run(context) is not None
    assert CHECK_TOOL in {
        function.__name__ for function in ToolRegistry().functions_for(context)
    }


def test_the_tool_takes_no_arguments_because_every_check_runs_on_every_run() -> None:
    context = context_with_run(exploded_package())
    tool = next(
        item for item in ToolRegistry().build(context, sink=SessionSink(context))
        if item.name == CHECK_TOOL
    )
    assert tool.schema.get("properties", {}) == {}
    assert tool.schema.get("required", []) == []


def test_a_context_with_no_standards_run_is_refused_rather_than_grading_nothing() -> None:
    context = context_for(exploded_package())
    payload = dict(
        ToolRegistry(functions=(*TOOL_FUNCTIONS, check_standards))
        .dispatch(context, sink=SessionSink(context))
        .call(CHECK_TOOL, {})
        .payload
    )
    assert payload["error"] == NO_STANDARDS_RUN


# --- 2. what one call writes --------------------------------------------------------------


def test_it_writes_findings_and_aggregated_coverage_to_the_session() -> None:
    context = context_with_run(exploded_package())
    payload = dispatch(context)

    session = context.require_session()
    assert [finding.check for finding in session.findings] == [NOT_EXPLODED]
    assert payload["findings"][0]["check"] == NOT_EXPLODED
    assert payload["documents"] == [
        document.document_id for document in standards_run(context).documents
    ]
    assert payload["verdict"]["state"] == "not_ready"
    assert "standards.release" in coverage_checks(context, "checked") + coverage_checks(
        context, "unresolved"
    )


def test_every_finding_cites_a_step_that_exists_in_the_session() -> None:
    context = context_with_run(exploded_package())
    dispatch(context)

    session = context.require_session()
    steps = {step.index for step in session.steps}
    assert steps
    for finding in session.findings:
        assert set(finding.tool_result_ids) <= steps


def test_a_second_call_replaces_its_coverage_rather_than_duplicating_it() -> None:
    context = context_with_run(exploded_package())
    dispatch(context)
    first = sorted(coverage_checks(context, "checked"))
    dispatch(context)

    assert sorted(coverage_checks(context, "checked")) == first
    for bucket in ("checked", "skipped", "unresolved", "out_of_scope"):
        checks = coverage_checks(context, bucket)
        assert len(checks) == len(set(checks)), (bucket, checks)


def test_every_one_of_the_sixteen_lands_in_a_bucket_or_a_finding() -> None:
    context = context_with_run(exploded_package())
    dispatch(context)

    covered = {
        check
        for bucket in ("checked", "skipped", "unresolved", "out_of_scope")
        for check in coverage_checks(context, bucket)
    }
    covered.update(finding.check for finding in context.require_session().findings)
    assert set(RULES) <= covered


# --- 3. exceptions ------------------------------------------------------------------------


class WaivingStore(ExceptionStore):
    """A store that waives whatever it is asked about, recording what it was asked."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[str] = []

    def match(self, *args: Any, **kwargs: Any) -> ReviewException:
        check = str(kwargs["check"])
        self.asked.append(check)
        return ReviewException(
            id="EX-001",
            check=check,
            component_persist_refs=[],
            persist_ref_scopes=[],
            configuration="Default",
            geometry_fingerprint="0" * 64,
            fingerprint_kind="feature_tree",
            accepted_by="a.engineer",
            accepted_at="2026-09-17T10:00:00+00:00",
            note="accepted for this release",
            status="active",
        )


def test_a_failing_check_consults_the_exceptions_with_its_own_check_id() -> None:
    context = context_with_run(exploded_package())
    store = WaivingStore()
    context.exceptions = store

    payload = dispatch(context)

    assert store.asked == [NOT_EXPLODED]
    assert payload["verdict"]["waived"] == 1
    assert payload["verdict"]["counts"]["error"] == 0


def test_a_passing_or_skipped_check_never_consults_the_exceptions() -> None:
    context = context_with_run(
        package_of(
            AssemblySpec(
                name="top",
                folder="jobs/mr-400",
                components=[ComponentSpec(name="plate-1", document="plate")],
            ),
            PartSpec(name="plate", folder="jobs/mr-400"),
        )
    )
    store = WaivingStore()
    context.exceptions = store

    dispatch(context)

    assert store.asked == []


# --- 4. what this build does not run yet --------------------------------------------------


def test_this_build_runs_every_check_in_the_catalogue() -> None:
    """All sixteen since T066: nothing is reported as not built (T069a, T070)."""
    assert unavailable_checks() == []
    assert set(SCOPE_EVALUATORS) == {rule.scope for rule in RULES.values()}


def test_a_check_with_no_evaluator_is_reported_rather_than_silently_absent(
    monkeypatch: Any,
) -> None:
    """The mechanism, asked of a scope taken back out of the dispatch.

    The report is **derived** from the catalogue - a check whose scope has no entry point -
    rather than maintained as a list, which is what let it empty itself when the drawing
    evaluators landed. Removing the entry point again is the only way left to ask whether
    it would refill, and a check that silently stopped being dispatched is exactly the
    failure this measures.
    """
    monkeypatch.delitem(SCOPE_EVALUATORS, "drawing")

    assert [row["check"] for row in unavailable_checks()] == list(DRAWING_CHECKS)
    assert all(
        NOT_BUILT.format(check=row["check"]) == row["reason"] for row in unavailable_checks()
    )


def test_an_unavailable_check_is_unresolved_over_the_documents_it_would_have_graded(
    monkeypatch: Any,
) -> None:
    monkeypatch.delitem(SCOPE_EVALUATORS, "drawing")
    context = context_with_run(drawing_package())
    dispatch(context)

    unresolved = coverage_checks(context, "unresolved")
    for check in DRAWING_CHECKS:
        assert check in unresolved
    assert set(coverage_checks(context, "checked")) & set(DRAWING_CHECKS) == set()


def test_a_document_the_package_records_no_kind_for_is_unresolved_for_every_check() -> None:
    package = exploded_package()
    context = context_for(package)
    documents = (
        *graded_documents(package, PROFILE),
        CheckedDocument(
            document_id="doc:404",
            kind=None,
            path=None,
            file_name=None,
            configuration=None,
            unresolved_reason="no document row for doc:404",
        ),
    )
    attach_standards_run(context, StandardsRun(profile=PROFILE, documents=documents))

    dispatch(context)

    unresolved = {
        item.check: item
        for item in context.require_session().coverage.unresolved
        if "doc:404" in item.scope.document_ids and item.check in RULES
    }
    assert set(unresolved) == set(RULES)
    assert "no document row for doc:404" in next(iter(unresolved.values())).reason
