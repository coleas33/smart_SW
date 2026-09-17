"""The document-scoped finding the moved report layer admits (T010).

`checks/rules/report.py` turns a finding-shaped result whose document has no
`ComponentInstance` into unresolved coverage: a finding that names no component is not a
finding, and an invented id is worse. A **drawing** has no instance by nature - it is
opened, not placed - so that rule would turn every drawing finding into a coverage row
(`specs/006-standards-check/data-model.md` section 2, `research.md` R7 point 5).

The widening is asserted here, on the neutral layer, with a fictional family and a
fictional rule: what decides is the **document's kind** and not the family's name, which is
why the same code leaves an rms result about a part with no instance exactly where it was
(`test_rms_report.py`, the test that a document with no instance yields unresolved
coverage and no finding).

The family here is invented for the test rather than imported, so this module keeps
asserting the neutral behaviour when a real second family arrives and changes its own mind
about something.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from swreview.checks.rules.family import CheckFamily
from swreview.checks.rules.registry import Rule
from swreview.checks.rules.report import report_results
from swreview.checks.rules.results import finding
from swreview.ir.models import Document, EvidencePackage, ManifestEntry
from swreview.report.session import CoverageItem
from swreview.tools.context import ToolContext, context_for
from tests.support.packages import build_package, persist_ref

DRAWING = "doc:9"
"""A drawing document: in the package, referenced by nothing, instanced nowhere."""

PART_WITHOUT_INSTANCE = "doc:8"
"""A part document nothing places - the data gap the unresolved row exists to report."""

FAMILY = CheckFamily(
    name="fictional",
    summary_check="fictional.summary",
    rules_version="1",
    scopes=frozenset({"drawing", "part"}),
    tools={"drawing": "check_fictional_drawing"},
    check_file_family="fictional",
    severities=frozenset({"error", "warning"}),
    status_by_severity={
        "error": ("demonstrated", "medium"),
        "warning": ("suspected", "low"),
    },
    high_severity=frozenset(),
    waiver_labels={"unknown": "invalid (unknown check)", "warning": "invalid (warning check)"},
)

RULE = Rule(
    id="fictional.drawing.something",
    scope="drawing",
    severity="error",
    statement="Something about a drawing holds.",
)

RULES = {RULE.id: RULE}


def a_document(document_id: str, kind: str) -> Document:
    return Document(
        document_id=document_id,
        kind=kind,  # type: ignore[arg-type]
        file_name=f"{document_id.replace(':', '-')}.file",
        path=f"native/{document_id.replace(':', '-')}.file",
        configurations=["Default"],
        active_configuration="Default",
        custom_properties={},
        config_properties={},
        material=None,
        mass=None,
    )


def a_manifest_entry(document_id: str) -> ManifestEntry:
    """Provenance for the added documents: a finding cannot cite one without it."""
    return ManifestEntry(
        document_id=document_id,
        vault_path=f"/Designs/{document_id.replace(':', '-')}.file",
        vault_version=1,
        revision="A",
        configuration="Default",
        local_modified=False,
        export_method="native",
    )


@pytest.fixture
def package() -> EvidencePackage:
    """The base package plus a drawing and an uninstanced part, neither with an instance."""
    base = build_package()
    return base.model_copy(
        update={
            "documents": [
                *base.documents,
                a_document(PART_WITHOUT_INSTANCE, "part"),
                a_document(DRAWING, "drawing"),
            ],
            "manifest": base.manifest.model_copy(
                update={
                    "entries": [
                        *base.manifest.entries,
                        a_manifest_entry(PART_WITHOUT_INSTANCE),
                        a_manifest_entry(DRAWING),
                    ]
                }
            ),
        }
    )


@pytest.fixture
def context(package: EvidencePackage) -> ToolContext:
    return context_for(package)


@dataclass(frozen=True)
class Subject:
    """A drawing annotation in the shape the constructors render a subject in.

    Structural, not nominal, exactly as `checks/rms/assembly.py` renders a mate: the
    constructors read these seven attributes off a subject and are annotated `Feature`
    because the part rules were written first.
    """

    id: str
    name: str
    type_name: str
    persist_ref: str | None
    persist_ref_scope: str | None
    suppressed: bool
    configuration: str


def a_subject(document_id: str) -> Subject:
    """One annotation of `document_id`, with a persistent reference."""
    return Subject(
        id="dan:0001",
        name="NOTE1",
        type_name="Note",
        persist_ref=persist_ref("dan:0001"),
        persist_ref_scope=document_id,
        suppressed=False,
        configuration="Default",
    )


def violation(document_id: str) -> object:
    return finding(
        FAMILY,
        RULE,
        document_id,
        [a_subject(document_id)],  # type: ignore[list-item]
        observed="the note says the wrong thing",
        recommended_action="say the right thing",
    )


def items(context: ToolContext, bucket: str) -> list[CoverageItem]:
    return list(getattr(context.require_session().coverage, bucket))


class TestADrawingIsGradedAsItself:
    def test_the_finding_is_recorded_with_no_component_ids(
        self, context: ToolContext
    ) -> None:
        report_results(FAMILY, RULES, context, [violation(DRAWING)])

        [recorded] = context.require_session().findings
        assert recorded.check == RULE.id
        assert recorded.component_ids == []

    def test_it_is_bound_by_the_document_through_its_subject(
        self, context: ToolContext
    ) -> None:
        """A drawing finding names the document; that is what makes it a finding at all."""
        report_results(FAMILY, RULES, context, [violation(DRAWING)])

        [recorded] = context.require_session().findings
        assert [ref.document_id for ref in recorded.drawing_locations] == [DRAWING]

    def test_it_is_not_reported_as_unresolved_coverage(self, context: ToolContext) -> None:
        report_results(FAMILY, RULES, context, [violation(DRAWING)])

        assert [item.check for item in items(context, "unresolved")] == []

    def test_its_subjects_travel_beside_the_finding(self, context: ToolContext) -> None:
        result = report_results(FAMILY, RULES, context, [violation(DRAWING)])

        [recorded] = context.require_session().findings
        [entry] = result["subjects"][recorded.id]  # type: ignore[index]
        assert entry["feature_id"] == "dan:0001"
        assert entry["component_ids"] == []


class TestEveryOtherKindIsUnchanged:
    def test_a_part_with_no_instance_is_still_unresolved_coverage(
        self, context: ToolContext
    ) -> None:
        report_results(FAMILY, RULES, context, [violation(PART_WITHOUT_INSTANCE)])

        assert context.require_session().findings == []
        [item] = [
            entry for entry in items(context, "unresolved") if entry.check == RULE.id
        ]
        assert f"no component instance for {PART_WITHOUT_INSTANCE}" in item.reason

    def test_a_document_the_package_does_not_carry_is_unresolved_coverage(
        self, context: ToolContext
    ) -> None:
        """Absence is a gap, not a document-scoped subject: there is no kind to read."""
        report_results(FAMILY, RULES, context, [violation("doc:404")])

        assert context.require_session().findings == []
        assert RULE.id in [item.check for item in items(context, "unresolved")]
