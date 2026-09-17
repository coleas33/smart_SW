"""The standards report layer: results become findings, coverage and a verdict (T047).

`checks/standards/report.py` is the one place a standards `RuleResult` becomes something a
reader sees, so what is pinned here is every mapping of `specs/006-standards-check/
data-model.md` section 3 ("Finding fields", "Coverage aggregation") and
`contracts/standards-check.md` section 1, and nothing about how a check reached its verdict:

- **findings.** Exactly one `Finding` per failing check per document (FR-003), naming every
  instance that reaches that document in package order - and none at all for a drawing,
  which is bound by its `document_id` instead. One `inputs` entry per subject in this
  family's format, the check's statement as the requirement, a `tool_result_ids` step, and
  `coverage_limits` always carrying the profile identity and never a profile value;
- **subjects.** The same subjects a second time, structured and **beside** the finding, each
  saying whether the page can offer a Show control for it at all;
- **coverage.** One aggregated item per check per bucket per run through `replace_coverage`,
  the out-of-scope loop over (every check) x (every graded document), and the
  `standards.release` summary item, which carries the verdict and is not one of the sixteen;
- **the rendered check rows.** All sixteen on every run, each with the buckets it landed in
  and the worst of them, with `failed` and `warned` derived from the findings because the
  review session has no `warned` bucket to read.

The evaluators are not exercised here: results are hand-built with the constructors of
`checks/standards/results.py`, which is what a check returns, so a change in a check's
wording cannot break the report layer's tests or the other way round.

Every value-bearing string comes from the fictional fixture profile (FR-001).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, get_args

import pytest

from swreview.checks.rules.results import RuleOutcome
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import RULES, STANDARDS_FAMILY
from swreview.checks.standards.report import (
    PROFILE_LIMIT,
    SUMMARY_CHECK,
    check_rows,
    report_results,
    subject_input,
)
from swreview.checks.standards.results import (
    NO_REBUILD_NOTE,
    RuleResult,
    Subject,
    component_subject,
    document_subject,
    finding,
    passed,
    property_subject,
    skipped,
    unresolved,
)
from swreview.checks.standards.traversal import CheckedDocument, graded_documents
from swreview.exceptions import ExceptionStore, ReviewException
from swreview.ir.models import ComponentInstance, EvidencePackage
from swreview.tools.context import ToolContext, context_for
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
IDENTITY = PROFILE.identity

NOT_EXPLODED = "standards.assembly.not_exploded"
MATE_REFERENCES = "standards.assembly.mate_references"
NOT_HIDDEN = "standards.assembly.not_hidden"
SKETCHES = "standards.part.sketches_fully_defined"
PART_REBUILD = "standards.part.rebuild_errors"
DATA_CARD = "standards.document.data_card_complete"
REVISION_MATCHES = "standards.drawing.revision_matches"
DIMENSIONS = "standards.drawing.dimensions_not_overridden"

CONFORMING = "MR-40012"
"""A stem that makes every extension match the fictional pattern `MR-#####.SLD???`."""


# --- the packages every test reads --------------------------------------------------------


def package_of(*documents: DocumentSpec) -> EvidencePackage:
    return standards_package(documents=list(documents), profile=PROFILE)


def model_package() -> EvidencePackage:
    """A root assembly, a part used twice and a part used once."""
    return package_of(
        AssemblySpec(
            name="top",
            folder="jobs/mr-400",
            components=[
                ComponentSpec(name="bracket-1", document="bracket"),
                ComponentSpec(name="bracket-2", document="bracket"),
                ComponentSpec(name="plate-1", document="plate"),
            ],
        ),
        PartSpec(name="bracket", folder="jobs/mr-400"),
        PartSpec(name="plate", folder="jobs/mr-400"),
    )


def drawing_package() -> EvidencePackage:
    """A drawing root whose one view references the assembly under it."""
    return package_of(
        DrawingSpec(
            name=CONFORMING,
            folder="jobs/mr-400",
            active_sheet="Sheet1",
            sheets=[
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=[ViewSpec(name="View1", references="top")],
                )
            ],
        ),
        AssemblySpec(
            name="top",
            folder="jobs/mr-400",
            components=[ComponentSpec(name="plate-1", document="plate")],
        ),
        PartSpec(name="plate", folder="jobs/mr-400"),
    )


def documents_of(package: EvidencePackage) -> tuple[CheckedDocument, ...]:
    return graded_documents(package, PROFILE)


def document_named(
    package: EvidencePackage, documents: Sequence[CheckedDocument], name: str
) -> CheckedDocument:
    row = next(item for item in package.documents if item.file_name.startswith(name))
    return next(item for item in documents if item.document_id == row.document_id)


def instances_of(package: EvidencePackage, document_id: str) -> list[ComponentInstance]:
    return [row for row in package.components if row.document_id == document_id]


def view_subject(package: EvidencePackage, document: CheckedDocument) -> Subject:
    """The one view of the drawing package, as a drawing check would name it."""
    view = package.drawing_records[0].sheets[0].views[0]
    return Subject(
        id=view.id,
        name=view.name or view.id,
        type_name="view",
        persist_ref=view.persist_ref,
        persist_ref_scope=document.document_id,
        suppressed=False,
        configuration="Default",
    )


# --- the results every test hands over ----------------------------------------------------


def violation(
    rule_id: str,
    document_id: str,
    subjects: Sequence[Subject],
    *,
    limits: Sequence[str] = (),
) -> RuleResult:
    return finding(
        RULES[rule_id],
        document_id,
        list(subjects),
        observed="the document is not release-ready",
        recommended_action="put it right before release",
        coverage_limits=list(limits),
    )


def report(
    context: ToolContext,
    results: Sequence[RuleResult],
    documents: Sequence[CheckedDocument],
) -> dict[str, Any]:
    reported = report_results(context, list(results), list(documents), IDENTITY)
    assert "error" not in reported, reported
    return dict(reported)


def only_finding(payload: dict[str, Any]) -> dict[str, Any]:
    assert len(payload["findings"]) == 1, payload["findings"]
    return dict(payload["findings"][0])


def coverage_item(context: ToolContext, bucket: str, check: str) -> Any:
    items = [
        item for item in getattr(context.require_session().coverage, bucket) if item.check == check
    ]
    assert len(items) == 1, f"{check} in {bucket}: {items}"
    return items[0]


def held_in(context: ToolContext, bucket: str, check: str) -> bool:
    return any(
        item.check == check for item in getattr(context.require_session().coverage, bucket)
    )


def row_for(context: ToolContext, check: str) -> dict[str, Any]:
    rows = [row for row in check_rows(context.require_session()) if row["check"] == check]
    assert len(rows) == 1, rows
    return rows[0]


# --- 1. findings --------------------------------------------------------------------------


def test_one_finding_per_document_naming_every_instance_in_package_order() -> None:
    """FR-003: one finding for the document, whatever the number of instances."""
    package = model_package()
    documents = documents_of(package)
    bracket = document_named(package, documents, "bracket")
    instances = instances_of(package, bracket.document_id)
    assert len(instances) == 2

    context = context_for(package)
    payload = report(
        context,
        [violation(SKETCHES, bracket.document_id, [document_subject(bracket)])],
        documents,
    )

    assert only_finding(payload)["component_ids"] == [row.id for row in instances]


def test_inputs_are_one_entry_per_subject_in_this_familys_format() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")
    children = [row for row in package.components if row.parent_id is not None]
    subjects = [component_subject(row, "Default") for row in children[:2]]

    context = context_for(package)
    payload = report(context, [violation(NOT_HIDDEN, top.document_id, subjects)], documents)

    body = only_finding(payload)
    assert body["inputs"] == [subject_input(row) for row in subjects]
    assert body["inputs"][0] == (
        f"component {subjects[0].id} {subjects[0].name} "
        f"persist_ref={subjects[0].persist_ref} scope={subjects[0].persist_ref_scope}"
    )


def test_a_subject_with_no_persistent_reference_says_none_in_its_input() -> None:
    package = model_package()
    documents = documents_of(package)
    plate = document_named(package, documents, "plate")
    subject = property_subject(PROFILE.data_card.properties[0], plate)

    assert subject.persist_ref is None
    assert subject_input(subject) == (
        f"property {subject.id} {subject.name} persist_ref=none scope={plate.document_id}"
    )


def test_requirement_and_recommended_action_come_from_the_check() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    context = context_for(package)
    payload = report(
        context, [violation(NOT_EXPLODED, top.document_id, [document_subject(top)])], documents
    )

    body = only_finding(payload)
    assert body["requirement"] == RULES[NOT_EXPLODED].statement
    assert body["recommended_action"] == "put it right before release"


def test_tool_result_ids_name_the_step_the_call_is_recorded_as() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    context = context_for(package)
    step = context.current_step_id
    payload = report(
        context, [violation(NOT_EXPLODED, top.document_id, [document_subject(top)])], documents
    )

    assert only_finding(payload)["tool_result_ids"] == [step]


def test_coverage_limits_always_carry_the_profile_identity_and_no_profile_value() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    context = context_for(package)
    payload = report(
        context, [violation(NOT_EXPLODED, top.document_id, [document_subject(top)])], documents
    )

    limits = only_finding(payload)["coverage_limits"]
    assert limits[0] == PROFILE_LIMIT.format(path=IDENTITY.path, sha256=IDENTITY.sha256)
    assert IDENTITY.sha256 in limits[0]
    assert not any(PROFILE.export_control.phrase in limit for limit in limits), limits


def test_coverage_limits_name_the_configuration_and_the_unresolved_instances() -> None:
    package = package_of(
        AssemblySpec(
            name="top",
            folder="jobs/mr-400",
            configuration="AsBuilt",
            components=[
                ComponentSpec(name="plate-1", document="plate", suppression="lightweight")
            ],
        ),
        PartSpec(name="plate", folder="jobs/mr-400", configuration="AsBuilt"),
    )
    documents = documents_of(package)
    plate = document_named(package, documents, "plate")
    assert plate.unresolved_instances

    context = context_for(package)
    payload = report(
        context,
        [violation(SKETCHES, plate.document_id, [document_subject(plate)])],
        documents,
    )

    limits = only_finding(payload)["coverage_limits"]
    assert "configuration AsBuilt" in limits
    unresolved_limit = next(
        limit for limit in limits if limit.startswith("unresolved instances: ")
    )
    assert plate.unresolved_instances[0][0] in unresolved_limit


def test_a_limit_the_check_supplied_is_kept_after_the_profile_identity() -> None:
    package = model_package()
    documents = documents_of(package)
    plate = document_named(package, documents, "plate")

    context = context_for(package)
    payload = report(
        context,
        [
            violation(
                PART_REBUILD,
                plate.document_id,
                [document_subject(plate)],
                limits=[NO_REBUILD_NOTE],
            )
        ],
        documents,
    )

    limits = only_finding(payload)["coverage_limits"]
    assert limits[0].startswith("profile:")
    assert limits[-1] == NO_REBUILD_NOTE


@pytest.mark.parametrize(
    ("check", "status", "severity"),
    [
        (NOT_EXPLODED, "demonstrated", "medium"),
        (MATE_REFERENCES, "demonstrated", "high"),
        (PART_REBUILD, "demonstrated", "high"),
        (REVISION_MATCHES, "suspected", "low"),
    ],
)
def test_severity_is_the_familys_map_with_the_four_data_integrity_checks_high(
    check: str, status: str, severity: str
) -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    context = context_for(package)
    payload = report(
        context, [violation(check, top.document_id, [document_subject(top)])], documents
    )

    body = only_finding(payload)
    assert (body["status"], body["severity"]) == (status, severity)


def test_a_finding_counts_once_however_many_subjects_and_instances_it_names() -> None:
    package = model_package()
    documents = documents_of(package)
    bracket = document_named(package, documents, "bracket")
    subjects = [
        component_subject(row, "Default") for row in instances_of(package, bracket.document_id)
    ]
    assert len(subjects) == 2

    context = context_for(package)
    payload = report(context, [violation(SKETCHES, bracket.document_id, subjects)], documents)

    assert len(payload["findings"]) == 1
    assert payload["verdict"]["counts"]["error"] == 1


# --- 2. the structured subjects beside the finding ----------------------------------------


def test_subjects_travel_beside_the_finding_keyed_by_its_id() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")
    child = next(row for row in package.components if row.parent_id is not None)
    subjects = [component_subject(child, "Default")]

    context = context_for(package)
    payload = report(context, [violation(NOT_HIDDEN, top.document_id, subjects)], documents)

    body = only_finding(payload)
    assert "subjects" not in body
    entries = payload["subjects"][body["id"]]
    assert [entry["id"] for entry in entries] == [subjects[0].id]
    assert entries[0]["kind"] == "component"
    assert entries[0]["name"] == subjects[0].name
    assert entries[0]["persist_ref_scope"] == top.document_id
    assert entries[0]["showable"] is True


def test_a_subject_with_no_persistent_reference_is_not_showable() -> None:
    package = model_package()
    documents = documents_of(package)
    plate = document_named(package, documents, "plate")
    subjects = [property_subject(PROFILE.data_card.properties[0], plate)]

    context = context_for(package)
    payload = report(context, [violation(DATA_CARD, plate.document_id, subjects)], documents)

    entry = payload["subjects"][only_finding(payload)["id"]][0]
    assert entry["kind"] == "property"
    assert entry["persist_ref"] is None
    assert entry["showable"] is False


def test_a_subject_whose_scope_is_a_drawing_is_not_showable() -> None:
    package = drawing_package()
    documents = documents_of(package)
    drawing = document_named(package, documents, CONFORMING)
    subject = view_subject(package, drawing)
    assert subject.persist_ref is not None

    context = context_for(package)
    payload = report(context, [violation(DIMENSIONS, drawing.document_id, [subject])], documents)

    entry = payload["subjects"][only_finding(payload)["id"]][0]
    assert entry["kind"] == "view"
    assert entry["showable"] is False


def test_a_drawing_finding_is_bound_to_its_drawing_and_reaches_no_model() -> None:
    """A drawing is bound by its `document_id`, whatever rows the dump synthesized for it.

    `Finding.component_ids` are the instances that *reach* a document, and nothing places
    a drawing: T047 and `data-model.md` "Finding fields" item 1 both say the list is empty
    and the document binds the finding instead, which is why the exception record gains a
    `document_id`. A drawing-rooted dump does write one component row whose `document_id`
    is the drawing's - the synthesized forest root the referenced models hang under
    (`contracts/ir-additions.md` section 7) - but that row does not reach the drawing, so
    it is not named here: naming it would send a drawing waiver down the component path
    and skip the `document_id` comparison RK-11 and SC-008 require. The binding is decided
    by the document's kind through `DOCUMENT_SCOPED_KINDS`, so it does not depend on what
    the dump chose to synthesize.
    """
    package = drawing_package()
    documents = documents_of(package)
    drawing = document_named(package, documents, CONFORMING)
    assert drawing.instances == ()
    assert instances_of(package, drawing.document_id), "the dump wrote a forest-root row"

    context = context_for(package)
    payload = report(
        context,
        [violation(DIMENSIONS, drawing.document_id, [view_subject(package, drawing)])],
        documents,
    )

    body = only_finding(payload)
    assert body["component_ids"] == []
    assert [entry["document_id"] for entry in body["provenance"]] == [drawing.document_id]
    assert [ref["document_id"] for ref in body["drawing_locations"]] == [drawing.document_id]
    assert not held_in(context, "unresolved", DIMENSIONS)


def test_a_drawing_finding_whose_subjects_cannot_be_located_still_names_its_document() -> None:
    """The document binding is the locator, or a data-card failure on a drawing is lost.

    `standards.document.data_card_complete` grades drawings too (T045) and its subjects are
    property names with no `persist_ref` and nothing in SOLIDWORKS to select. With
    `component_ids` empty - as a drawing's must be - the finding names no component and no
    source reference, and feature 001's evidence rule ("a finding must name at least one
    of...") would refuse it, aborting the whole report. The document it was read from is
    what it names instead: `provenance` carries the drawing's manifest entry, which is the
    same binding `data-model.md` section 5 gives the exception record.
    """
    package = drawing_package()
    documents = documents_of(package)
    drawing = document_named(package, documents, CONFORMING)

    context = context_for(package)
    payload = report(
        context,
        [violation(DATA_CARD, drawing.document_id, [property_subject("Revision", drawing)])],
        documents,
    )

    body = only_finding(payload)
    assert body["component_ids"] == []
    assert body["drawing_locations"] == []
    assert [entry["document_id"] for entry in body["provenance"]] == [drawing.document_id]
    assert payload["subjects"][body["id"]][0]["showable"] is False


def test_a_part_document_with_no_instance_is_unresolved_coverage_and_not_a_finding() -> None:
    """The neutral layer's rule, unchanged for a kind that *is* reached by instances."""
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    context = context_for(package)
    payload = report(
        context, [violation(NOT_EXPLODED, top.document_id, [document_subject(top)])], documents
    )

    assert len(payload["findings"]) == 1
    assert not held_in(context, "unresolved", NOT_EXPLODED)


# --- 3. coverage --------------------------------------------------------------------------


def test_coverage_is_one_aggregated_item_per_check_per_bucket_naming_the_documents() -> None:
    package = model_package()
    documents = documents_of(package)
    bracket = document_named(package, documents, "bracket")
    plate = document_named(package, documents, "plate")

    context = context_for(package)
    report(
        context,
        [
            skipped(RULES[SKETCHES], bracket.document_id, "no sketches"),
            skipped(RULES[SKETCHES], plate.document_id, "no sketches either"),
        ],
        documents,
    )

    item = coverage_item(context, "skipped", SKETCHES)
    assert item.scope.document_ids == [bracket.document_id, plate.document_id]
    assert item.reason.startswith("2 document(s)")
    assert f"{plate.document_id}: no sketches either" in item.reason


def test_a_second_evaluation_replaces_coverage_rather_than_duplicating_it() -> None:
    package = model_package()
    documents = documents_of(package)
    plate = document_named(package, documents, "plate")

    context = context_for(package)
    results = [passed(RULES[SKETCHES], plate.document_id)]
    report(context, results, documents)
    report(context, results, documents)

    assert coverage_item(context, "checked", SKETCHES).scope.document_ids == [plate.document_id]


def test_the_out_of_scope_loop_writes_every_mismatched_pair_naming_the_kind() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")
    parts = [document.document_id for document in documents if document.kind == "part"]

    context = context_for(package)
    report(context, [passed(RULES[NOT_EXPLODED], top.document_id)], documents)

    part_scope = coverage_item(context, "out_of_scope", SKETCHES)
    assert part_scope.scope.document_ids == [top.document_id]
    assert "assembly" in part_scope.reason

    assembly_scope = coverage_item(context, "out_of_scope", NOT_HIDDEN)
    assert assembly_scope.scope.document_ids == parts
    assert "part" in assembly_scope.reason

    drawing_scope = coverage_item(context, "out_of_scope", DIMENSIONS)
    assert drawing_scope.scope.document_ids == [top.document_id, *parts]


def test_the_document_scope_check_is_never_out_of_scope_for_a_graded_document() -> None:
    package = model_package()
    documents = documents_of(package)

    context = context_for(package)
    report(context, [], documents)

    assert not held_in(context, "out_of_scope", DATA_CARD)


def test_an_unresolved_document_is_not_written_as_out_of_scope() -> None:
    """A document whose kind the package does not record is unknown, not inapplicable."""
    package = model_package()
    documents = [
        *documents_of(package)[:1],
        CheckedDocument(
            document_id="doc:404",
            kind=None,
            path=None,
            file_name=None,
            configuration=None,
            unresolved_reason="no document row",
        ),
    ]

    context = context_for(package)
    report(context, [], documents)

    for item in context.require_session().coverage.out_of_scope:
        assert "doc:404" not in item.scope.document_ids


def test_out_of_scope_is_not_a_seventh_rule_outcome() -> None:
    assert set(get_args(RuleOutcome)) == {
        "pass",
        "fail",
        "warn",
        "skip",
        "unresolved",
        "waived",
    }


# --- 4. the summary item ------------------------------------------------------------------


def test_the_summary_item_carries_the_verdict_and_the_counts() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    context = context_for(package)
    payload = report(
        context, [violation(NOT_EXPLODED, top.document_id, [document_subject(top)])], documents
    )

    assert payload["verdict"]["state"] == "not_ready"
    assert payload["verdict"]["counts"]["error"] == 1
    summary = coverage_item(context, "checked", SUMMARY_CHECK)
    assert "not_ready" in summary.reason
    assert SUMMARY_CHECK == STANDARDS_FAMILY.summary_check


def test_the_summary_moves_to_unresolved_when_a_check_is_unresolved() -> None:
    package = model_package()
    documents = documents_of(package)
    plate = document_named(package, documents, "plate")

    context = context_for(package)
    payload = report(
        context,
        [unresolved(RULES[SKETCHES], plate.document_id, "the status was not read")],
        documents,
    )

    assert payload["verdict"]["state"] == "ready_coverage_incomplete"
    assert payload["verdict"]["unresolved_check_ids"] == [SKETCHES]
    assert "ready_coverage_incomplete" in coverage_item(
        context, "unresolved", SUMMARY_CHECK
    ).reason
    assert not held_in(context, "checked", SUMMARY_CHECK)


def test_the_summary_is_not_one_of_the_sixteen_rendered_check_rows() -> None:
    package = model_package()
    documents = documents_of(package)

    context = context_for(package)
    report(context, [], documents)

    rows = check_rows(context.require_session())
    assert len(rows) == len(RULES) == 16
    assert SUMMARY_CHECK not in {row["check"] for row in rows}
    assert [row["check"] for row in rows] == list(RULES)


# --- 5. the rendered check rows -----------------------------------------------------------


def test_failed_and_warned_are_derived_from_the_findings() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    context = context_for(package)
    report(
        context,
        [
            violation(NOT_EXPLODED, top.document_id, [document_subject(top)]),
            violation(REVISION_MATCHES, top.document_id, [document_subject(top)]),
        ],
        documents,
    )

    session = context.require_session()
    assert session.coverage.failed == []
    assert not hasattr(session.coverage, "warned")

    failed = row_for(context, NOT_EXPLODED)
    assert failed["worst_bucket"] == "failed"
    assert failed["buckets"][0] == {
        "bucket": "failed",
        "document_ids": [top.document_id],
        "reason": failed["buckets"][0]["reason"],
    }
    assert row_for(context, REVISION_MATCHES)["worst_bucket"] == "warned"


def test_worst_bucket_resolves_unresolved_before_failed_and_failed_before_checked() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")
    bracket = document_named(package, documents, "bracket")
    plate = document_named(package, documents, "plate")

    context = context_for(package)
    report(
        context,
        [
            violation(SKETCHES, bracket.document_id, [document_subject(bracket)]),
            unresolved(RULES[SKETCHES], plate.document_id, "the status was not read"),
            passed(RULES[NOT_EXPLODED], top.document_id),
        ],
        documents,
    )

    row = row_for(context, SKETCHES)
    assert row["worst_bucket"] == "unresolved"
    assert [bucket["bucket"] for bucket in row["buckets"]][:2] == ["unresolved", "failed"]
    assert row_for(context, NOT_EXPLODED)["worst_bucket"] == "checked"
    assert row_for(context, NOT_HIDDEN)["worst_bucket"] == "out_of_scope"


def test_every_row_carries_the_checks_severity_and_statement() -> None:
    package = model_package()
    documents = documents_of(package)

    context = context_for(package)
    report(context, [], documents)

    row = row_for(context, REVISION_MATCHES)
    assert row["severity"] == "warning"
    assert row["statement"] == RULES[REVISION_MATCHES].statement


# --- 6. waivers ---------------------------------------------------------------------------


class WaivingStore(ExceptionStore):
    """A store that waives whatever it is asked about, and records what it was asked.

    The store's own matching rules are `test_exceptions.py`'s subject; what is asserted
    here is that the report layer asks with `check=<check id>` and reports the answer.
    """

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


def test_a_waived_finding_is_not_an_error_and_says_so_on_the_verdict() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    store = WaivingStore()
    context = context_for(package)
    context.exceptions = store
    payload = report(
        context, [violation(NOT_EXPLODED, top.document_id, [document_subject(top)])], documents
    )

    assert store.asked == [NOT_EXPLODED]
    assert payload["verdict"]["counts"]["error"] == 0
    assert payload["verdict"]["waived"] == 1
    assert payload["verdict"]["notes"][0].startswith("1 finding waived")
    assert payload["verdict"]["state"] == "ready"
    assert row_for(context, NOT_EXPLODED)["worst_bucket"] == "checked"


def test_a_warning_finding_never_consults_the_exception_store() -> None:
    package = model_package()
    documents = documents_of(package)
    top = document_named(package, documents, "top")

    store = WaivingStore()
    context = context_for(package)
    context.exceptions = store
    payload = report(
        context, [violation(REVISION_MATCHES, top.document_id, [document_subject(top)])], documents
    )

    assert store.asked == []
    assert payload["verdict"]["counts"]["warning"] == 1
