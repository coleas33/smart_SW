"""Sessions shaped like the two 2026-09-18 workstation runs (T002).

Feature 007 ranks findings that already exist, so what it needs committed is a *session*,
not a package. Two are built here and written under `tests/fixtures/attention/`:

- **the review**: eight findings over a four-component dowel-pin assembly - two static
  interferences, the mates rule bound to the root assembly's own component with the part
  and the pin in its inputs, the under-defined sketch, the grouping rule, the two equation
  rules and the missing folders - with coverage 5 checked, 11 skipped, 39 unresolved, 0
  failed, 7 out of scope;
- **the model check**: the three rule findings the Model check tab produced on the part,
  with coverage 5 / 11 / 5 / 0 / 6.

**The handover folders are not in this repository and nothing is copied out of them.**
Their packages carry vault paths, document names and property names, and this repository is
public (`tests/unit/test_standards_no_company_values.py` scans it). What is mirrored is the
*shape*: the check ids, the statuses and severities, how many distinct components each
finding names, the disposition and exception state (none on either run), the five bucket
counts and which check ids the unresolved rows carry. Every string below is this module's
own, and every sentence is true of the fixture package it is written against - a coverage
reason that claimed a gap this package does not have would be the same defect in miniature
that the reviewer refuses in a finding.

The package is `tests/support/packages.py`'s, extended rather than restated: the schema
version, the package id, the creation time, the extractor block, the two vault-shaped
manifest entries and `persist_ref` all come from there, and this module adds the third
document and the four component instances the two runs need.

Regeneration is a command, not a hand edit:

    uv run python -m tests.support.attention --write

`tests/unit/test_support_attention.py` asserts that re-running the builder reproduces every
committed byte, so a drifted fixture is a red test rather than a quiet rewrite.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from swreview.agent.providers import EffortMapping, TokenUsage
from swreview.agent.settings import EfficiencySettings
from swreview.checks.rms.registry import RMS_FAMILY, RULES
from swreview.checks.rules.run import CHECK_FILE_NAME, NO_RUN_ROOT, write_check_record
from swreview.findings import (
    Calculation,
    Disposition,
    Finding,
    FindingStatus,
    Severity,
    build_finding,
)
from swreview.ir.loader import save_package
from swreview.ir.models import (
    ComponentInstance,
    Document,
    EvidencePackage,
    Manifest,
    ManifestEntry,
    SourceRef,
)
from swreview.report.dispositions import SESSION_FILE_NAME
from swreview.report.session import (
    Coverage,
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    InvestigationStep,
    ProviderInfo,
    ReviewSession,
    SessionUsage,
    Timing,
    save_session,
)
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

__all__ = [
    "ASSEMBLY_DOCUMENT",
    "CHECK_FOLDER",
    "CHECK_SESSION_FILE",
    "CHECK_SESSION_ID",
    "FIXTURE_DIR",
    "PART_COMPONENT",
    "PART_DOCUMENT",
    "PIN_DOCUMENT",
    "PIN_ONE",
    "PIN_TWO",
    "REVIEW_FOLDER",
    "REVIEW_SESSION_FILE",
    "REVIEW_SESSION_ID",
    "ROOT_COMPONENT",
    "CoverageRow",
    "CoverageSpec",
    "FindingSpec",
    "attention_package",
    "build_attention_session",
    "check_session",
    "main",
    "review_session",
    "write_fixtures",
]

# --- where the fixtures live --------------------------------------------------------------

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "attention"
REVIEW_SESSION_FILE = FIXTURE_DIR / "session-20260918-review.json"
CHECK_SESSION_FILE = FIXTURE_DIR / "session-20260918-check.json"
REVIEW_FOLDER = FIXTURE_DIR / "review-folder"
CHECK_FOLDER = FIXTURE_DIR / "check-folder"

# --- the package the two runs are recorded against ----------------------------------------

ASSEMBLY_DOCUMENT = "doc:1"
PART_DOCUMENT = "doc:2"
PIN_DOCUMENT = "doc:3"

ROOT_COMPONENT = "cmp:0001"
"""The root assembly's own component instance: what the mates rule binds to."""

PIN_ONE = "cmp:0002"
PART_COMPONENT = "cmp:0003"
PIN_TWO = "cmp:0004"
"""Two instances of one pin document either side of the graded part, as the run had them."""

CONFIGURATION = "Default"

REVIEW_SESSION_ID = UUID("6f1c0a2e-9b6d-4a51-9f30-0b1f5a7c2d10")
CHECK_SESSION_ID = UUID("6f1c0a2e-9b6d-4a51-9f30-0b1f5a7c2d11")
REVIEW_STARTED_AT = datetime(2026, 9, 18, 21, 57, 55, tzinfo=UTC)
REVIEW_ENDED_AT = datetime(2026, 9, 18, 21, 59, 32, tzinfo=UTC)
CHECK_STARTED_AT = datetime(2026, 9, 18, 22, 3, 10, tzinfo=UTC)
CHECK_ENDED_AT = datetime(2026, 9, 18, 22, 3, 11, tzinfo=UTC)


def attention_package() -> EvidencePackage:
    """The four-component dowel-pin assembly both fixtures cite.

    `build_package` owns everything that is not about this design - the schema version, the
    package id, the created-at stamp, the extractor block and the two manifest entries the
    assembly and the housing already have - and this adds the pin document, its manifest
    entry and the four instances. No hole, fastener or gap is recorded: the run this is
    shaped after extracted none, and the coverage reasons below say exactly that.
    """
    base = build_package()
    pin_document = Document(
        document_id=PIN_DOCUMENT,
        kind="part",
        file_name="dowel-pin.SLDPRT",
        path="native/dowel-pin.SLDPRT",
        configurations=[CONFIGURATION],
        active_configuration=CONFIGURATION,
        custom_properties={},
        config_properties={},
        material="303 stainless",
        mass=None,
    )
    pin_entry = ManifestEntry(
        document_id=PIN_DOCUMENT,
        vault_path="/Designs/dowel-pin.SLDPRT",
        vault_version=2,
        revision="A",
        configuration=CONFIGURATION,
        local_modified=None,
        export_method="native",
    )
    return build_package(
        manifest=Manifest(entries=[*base.manifest.entries, pin_entry], discrepancies=[]),
        documents=[*base.documents, pin_document],
        components=[
            _component(ROOT_COMPONENT, "cover-assy-1", ASSEMBLY_DOCUMENT, None, is_fixed=True),
            _component(PIN_ONE, "dowel-pin-1", PIN_DOCUMENT, ROOT_COMPONENT),
            _component(PART_COMPONENT, "housing-1", PART_DOCUMENT, ROOT_COMPONENT),
            _component(PIN_TWO, "dowel-pin-2", PIN_DOCUMENT, ROOT_COMPONENT),
        ],
        holes=[],
        fasteners=[],
        gaps=[],
    )


def _component(
    component_id: str,
    name: str,
    document_id: str,
    parent_id: str | None,
    *,
    is_fixed: bool = False,
) -> ComponentInstance:
    return ComponentInstance(
        id=component_id,
        persist_ref=persist_ref(component_id),
        persist_ref_scope=ASSEMBLY_DOCUMENT,
        name=name,
        full_path=name if parent_id is None else f"cover-assy-1/{name}",
        document_id=document_id,
        parent_id=parent_id,
        referenced_configuration=CONFIGURATION,
        transform=IDENTITY_TRANSFORM,
        suppression="resolved",
        is_fixed=is_fixed,
        pattern_id=None,
        is_toolbox=False,
    )


COMPONENT_NAMES: dict[str, str] = {
    component.id: component.name for component in attention_package().components
}
"""`cmp:0003 -> housing-1`, so a generated sentence names a component the way a report does."""


# --- the two dials: a finding, and a coverage bucket ---------------------------------------


@dataclass(frozen=True)
class FindingSpec:
    """One finding of a fixture session, in the terms the attention policy reads.

    Everything the nine keys of `contracts/attention.md` section 1 look at is settable here
    and nothing is derived: `status` and `severity` are written as given (research R2.4 -
    the policy reads severity, it never recomputes it), `component_ids` is the reach, and
    the disposition, the exception id and the three carry-over fields are what the
    suppressed and carried keys read.

    The four prose fields default to a sentence naming the check and its subjects, so a
    synthetic session for one key's test needs three arguments and no invention; the
    committed fixtures write their own.
    """

    check: str
    status: FindingStatus = "demonstrated"
    severity: Severity = "medium"
    component_ids: tuple[str, ...] = ()
    drawing_locations: tuple[SourceRef, ...] = ()
    inputs: tuple[str, ...] = ()
    tool_result_ids: tuple[int, ...] = ()
    calculation: Calculation | None = None
    coverage_limits: tuple[str, ...] = ()
    disposition: Disposition | None = None
    exception_id: str | None = None
    carried_over_from: UUID | None = None
    carried_over_at: datetime | None = None
    carry_over_key: str | None = None
    numeric: bool = True
    title: str | None = None
    observed: str | None = None
    requirement: str | None = None
    recommended_action: str | None = None

    @property
    def subjects(self) -> str:
        """What a generated sentence calls this finding's subjects."""
        named = [COMPONENT_NAMES.get(one, one) for one in self.component_ids]
        named.extend(location.sheet or location.document_id for location in self.drawing_locations)
        return " and ".join(named) if named else "the package"


@dataclass(frozen=True)
class CoverageRow:
    """One coverage item, by check id and the reason the run recorded for it."""

    check: str
    reason: str
    component_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()

    def item(self) -> CoverageItem:
        return CoverageItem(
            check=self.check,
            scope=CoverageScope(
                component_ids=list(self.component_ids),
                configuration=CONFIGURATION,
                document_ids=list(self.document_ids),
            ),
            reason=self.reason,
            error=None,
        )


Bucket = Sequence[CoverageRow] | int
"""A coverage bucket: the rows themselves, or how many filler rows to write."""


@dataclass(frozen=True)
class CoverageSpec:
    """The five buckets, each by count or by row.

    A count is for a test that cares only about the numbers the coverage block prints - "a
    session with 39 unresolved items" - and writes rows whose check is `coverage.fixture.*`,
    an id no check emits, so a filler row can never be mistaken for a close-out row or a
    rule row. The two committed fixtures name every row.
    """

    checked: Bucket = 0
    skipped: Bucket = 0
    unresolved: Bucket = 0
    failed: Bucket = 0
    out_of_scope: Bucket = 0

    def build(self) -> Coverage:
        return Coverage(
            checked=_items("checked", self.checked),
            skipped=_items("skipped", self.skipped),
            unresolved=_items("unresolved", self.unresolved),
            failed=_items("failed", self.failed),
            out_of_scope=_items("out_of_scope", self.out_of_scope),
        )


def _items(bucket: str, rows: Bucket) -> list[CoverageItem]:
    if isinstance(rows, int):
        count = rows
        rows = [
            CoverageRow(
                check=f"coverage.fixture.{bucket}",
                reason=f"filler row {number} of {count} in the {bucket} bucket.",
            )
            for number in range(1, count + 1)
        ]
    return [row.item() for row in rows]


# --- the session builder --------------------------------------------------------------------


def build_attention_session(
    *,
    session_id: UUID,
    findings: Sequence[FindingSpec],
    coverage: CoverageSpec,
    steps: Sequence[str] = (),
    evidence_requests: Sequence[EvidenceRequest] = (),
    package: EvidencePackage | None = None,
    started_at: datetime = REVIEW_STARTED_AT,
    ended_at: datetime = REVIEW_ENDED_AT,
    model: str = "gpt-fixture",
    provider_info: ProviderInfo | None = None,
    usage: SessionUsage | None = None,
    unattended_runtime_minutes: float = 1.62,
) -> ReviewSession:
    """A finished `ReviewSession` over `findings`, valid against the committed contract.

    `steps` are tool names; a finding's `tool_result_ids` index them, so every id a fixture
    cites names a step the session actually holds. Timing carries no baseline, as every
    handover run does: User Story 1 exists because no run has ever carried one.
    """
    ir = package if package is not None else attention_package()
    return ReviewSession(
        session_id=session_id,
        package_id=ir.package_id,
        design_id=ir.design.design_id,
        started_at=started_at,
        ended_at=ended_at,
        model=model,
        provider_info=provider_info,
        efficiency=EfficiencySettings(),
        usage=usage,
        steps=[_step(index, tool) for index, tool in enumerate(steps)],
        evidence_requests=list(evidence_requests),
        findings=[
            _finding(spec, f"F-{number:03d}", ir) for number, spec in enumerate(findings, start=1)
        ],
        coverage=coverage.build(),
        timing=Timing(
            baseline_minutes=None,
            assisted_supervision_minutes=0.0,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=unattended_runtime_minutes,
        ),
    )


def _step(index: int, tool: str) -> InvestigationStep:
    return InvestigationStep(
        index=index,
        tool=tool,
        arguments={"configuration": CONFIGURATION},
        result_summary=f"{tool} returned its result",
        status="ok",
        error=None,
        elapsed_s=round(0.25 * (index + 1), 2),
    )


def _finding(spec: FindingSpec, finding_id: str, package: EvidencePackage) -> Finding:
    """`build_finding`, then the three fields it does not take, as `test_report.py` does."""
    finding = build_finding(
        finding_id=finding_id,
        check=spec.check,
        title=spec.title or f"{spec.check} on {spec.subjects}",
        status=spec.status,
        severity=spec.severity,
        package=package,
        configuration=CONFIGURATION,
        observed=spec.observed or f"{spec.check} was recorded against {spec.subjects}.",
        requirement=spec.requirement or _requirement(spec.check),
        recommended_action=spec.recommended_action or f"read {spec.check} and decide.",
        component_ids=spec.component_ids,
        drawing_locations=spec.drawing_locations,
        inputs=spec.inputs,
        calculation=spec.calculation,
        tool_result_ids=spec.tool_result_ids,
        coverage_limits=spec.coverage_limits,
        exception_id=spec.exception_id,
        numeric=spec.numeric,
    )
    finding.disposition = spec.disposition
    finding.carried_over_from = spec.carried_over_from
    finding.carried_over_at = spec.carried_over_at
    finding.carry_over_key = spec.carry_over_key
    return finding


def _requirement(check: str) -> str:
    """The rule's own statement when the catalogue holds one, so no rule is paraphrased."""
    rule = RULES.get(check)
    return rule.statement if rule is not None else f"{check} must hold for this design."


# --- the 2026-09-18 review ---------------------------------------------------------------


REVIEW_STEPS: tuple[str, ...] = (
    "check_rms_part",
    "check_rms_assembly",
    "check_rms_equations",
    "check_interference",
)

REVIEW_EVIDENCE_REQUESTS: tuple[EvidenceRequest, ...] = (
    EvidenceRequest(
        id="ER-001",
        what="The vault version and the local-modification state of every reviewed document",
        why="provenance cannot be confirmed from the manifest as dumped",
        entity_ids=[ASSEMBLY_DOCUMENT, PART_DOCUMENT, PIN_DOCUMENT],
        status="open",
        answer=None,
        answered_at=None,
    ),
    EvidenceRequest(
        id="ER-002",
        what="A part drawing for the housing carrying material, tolerance and thread notes",
        why="drawing.manufacturing_inputs has no sheet to read",
        entity_ids=[PART_DOCUMENT],
        status="open",
        answer=None,
        answered_at=None,
    ),
    EvidenceRequest(
        id="ER-003",
        what="The pin geometry and the hole each pin seats in",
        why="interfaces.fit and holes.alignment cannot be computed without them",
        entity_ids=[PIN_ONE, PIN_TWO],
        status="open",
        answer=None,
        answered_at=None,
    ),
)


def _interference_calculation(volume_mm3: float, pin: str) -> Calculation:
    """What the interference family records, in the shape a real finding carries it."""
    return Calculation(
        model="interference.static",
        inputs={
            "configuration": CONFIGURATION,
            "pair": f"{PART_COMPONENT} and {pin}",
            # A volume is not a `Quantity`: that model's units are mm, in and m only, and
            # the interference family reports its volumes as read, in text, for that reason.
            "volume_as_reported": f"{volume_mm3} mm^3",
        },
        assumptions=["the pins are modelled at nominal diameter"],
        excluded_effects=["thermal expansion", "press-fit deformation"],
        result={"member_count": 2.0, "max_volume_mm3": volume_mm3},
        units_out="mm^3",
        function="swreview.checks.interference.static",
        function_version="1",
    )


REVIEW_FINDINGS: tuple[FindingSpec, ...] = (
    FindingSpec(
        check="rms.folders.present",
        status="suspected",
        severity="low",
        component_ids=(PART_COMPONENT,),
        tool_result_ids=(0,),
        title="Three of the six groups are missing from the part tree",
        observed="housing-1 carries three of the six groups as folders.",
        recommended_action="add the missing group folders before the next release.",
    ),
    FindingSpec(
        check="rms.grouping.all_features_in_a_group",
        component_ids=(PART_COMPONENT,),
        tool_result_ids=(0,),
        drawing_locations=(
            SourceRef(document_id=PART_DOCUMENT, persist_ref=persist_ref("feat:0007")),
            SourceRef(document_id=PART_DOCUMENT, persist_ref=persist_ref("feat:0011")),
        ),
        title="Content features sit outside every group",
        observed="two content features of housing-1 sit outside any group folder.",
        recommended_action="move both features into the group their intent belongs to.",
    ),
    FindingSpec(
        check="rms.sketches.fully_defined",
        component_ids=(PART_COMPONENT,),
        tool_result_ids=(0,),
        drawing_locations=(
            SourceRef(document_id=PART_DOCUMENT, persist_ref=persist_ref("feat:0003")),
        ),
        title="An under-defined sketch drives a Core feature",
        observed="one sketch of housing-1 is under defined.",
        recommended_action="fully define the sketch before the geometry is relied on.",
    ),
    FindingSpec(
        check="rms.assembly.mates_to_reference_geometry",
        component_ids=(ROOT_COMPONENT,),
        tool_result_ids=(1,),
        inputs=("housing-1", "dowel-pin-1"),
        title="Two mates reference faces rather than reference geometry",
        observed=(
            "two mates of the root assembly reference a face of housing-1 and a face of "
            "dowel-pin-1."
        ),
        recommended_action="remate both to planes or axes so an edit cannot orphan them.",
    ),
    FindingSpec(
        check="rms.params.global_variables_present",
        component_ids=(PART_COMPONENT,),
        tool_result_ids=(2,),
        title="The part declares no global variable",
        observed="housing-1 declares no global variable.",
        recommended_action="name the driving sizes as global variables.",
    ),
    FindingSpec(
        check="rms.params.dimensions_driven_by_equations",
        status="suspected",
        severity="low",
        component_ids=(PART_COMPONENT,),
        tool_result_ids=(2,),
        title="No dimension is driven by an equation",
        observed="no dimension of housing-1 is driven by an equation.",
        recommended_action="drive the sizes that must move together from one equation.",
    ),
    FindingSpec(
        check="interference.static",
        component_ids=(PART_COMPONENT, PIN_TWO),
        calculation=_interference_calculation(0.8, PIN_TWO),
        coverage_limits=["measured in the Default configuration only."],
        inputs=("housing-1", "dowel-pin-2"),
        title="Static interference between the housing and the second pin",
        observed="housing-1 and dowel-pin-2 overlap by 0.8 mm^3 in the Default configuration.",
        requirement="Components do not occupy the same volume unless the fit is intended.",
        recommended_action=(
            "confirm whether the overlap is the intended press fit, or open the bore."
        ),
    ),
    FindingSpec(
        check="interference.static",
        component_ids=(PIN_ONE, PART_COMPONENT),
        calculation=_interference_calculation(0.5, PIN_ONE),
        coverage_limits=["measured in the Default configuration only."],
        inputs=("housing-1", "dowel-pin-1"),
        title="Static interference between the housing and the first pin",
        observed="housing-1 and dowel-pin-1 overlap by 0.5 mm^3 in the Default configuration.",
        requirement="Components do not occupy the same volume unless the fit is intended.",
        recommended_action=(
            "confirm whether the overlap is the intended press fit, or open the bore."
        ),
    ),
)

# The rule rows of both runs' coverage. Every id is a rule of `checks/rms/registry.py`, and
# the reasons follow the four kinds a run actually writes: a bare document count for a rule
# that passed, the missing group for one that had nothing to evaluate, the unread tree for
# the lightweight pin document, and - for the ten rules that are never dispatched - the
# catalogue's own coverage reason, read from the registry rather than copied.

GRADED_ONE_DOCUMENT = "1 document(s)"

CHECKED_RULES: tuple[str, ...] = (
    "rms.refs.direction",
    "rms.intent.every_feature_described",
    "rms.sketches.not_over_defined",
    "rms.sketches.one_sketch_per_feature",
)
"""The part rules that passed on the graded housing; with the three findings and the eleven
skipped rules below they account for all eighteen dispatched part rules."""

SKIPPED_RULES: tuple[tuple[str, str], ...] = (
    ("rms.folders.ordered", "fewer than two groups"),
    ("rms.groups.no_solids_in_ref_or_construction", "no Reference or Construction group"),
    ("rms.core.shell_last", "no Core group"),
    ("rms.detail.holes_last", "no Detail group"),
    ("rms.detail.no_internal_references", "no Detail group"),
    ("rms.detail.individually_suppressible", "no Detail group"),
    ("rms.modify.transform_before_replicate", "no Modify group"),
    ("rms.quarantine.chamfers_before_fillets", "no Quarantine group"),
    ("rms.quarantine.largest_fillet_first", "no Quarantine group"),
    ("rms.quarantine.only_fillets_and_chamfers", "no Quarantine group"),
    ("rms.refs.quarantine_has_no_children", "no Quarantine group"),
)
"""The eleven part rules whose group does not exist on the graded housing."""

UNSETTLED_ASSEMBLY_RULES: tuple[tuple[str, str], ...] = (
    ("rms.assembly.mates_to_reference_geometry", "one mate's entity kinds could not be read"),
    ("rms.assembly.mate_chain_depth", "no fixed child of the root assembly"),
    ("rms.assembly.toolbox_parts_not_configurations", "toolbox identity not readable"),
)
"""Assembly rules the run dispatched and could not settle on part of their subject."""

CENSUS_ROW = CoverageRow(
    check="rms.types.unknown",
    reason="feature type names not in the calibrated table: 3 feature(s) on the pin document.",
    document_ids=(PIN_DOCUMENT,),
)
"""The rms family's own census row, which is a coverage check and not a rule."""


def _unread_pin_rules() -> tuple[CoverageRow, ...]:
    """Every dispatched part and equation rule, unresolved on the unread pin document."""
    return tuple(
        CoverageRow(
            check=rule.id,
            reason=(
                f"{GRADED_ONE_DOCUMENT}: {PIN_DOCUMENT}: both pin instances are lightweight, "
                "so the tree was not read."
            ),
            document_ids=(PIN_DOCUMENT,),
        )
        for rule in RULES.values()
        if rule.coverage is None and rule.scope in ("part", "equations")
    )


def _catalogue_rows(bucket: str) -> tuple[CoverageRow, ...]:
    """The rules that are never dispatched, with the catalogue's own reason (registry)."""
    return tuple(
        CoverageRow(
            check=rule.id,
            reason=rule.coverage[1],
            document_ids=(ASSEMBLY_DOCUMENT,),
        )
        for rule in RULES.values()
        if rule.coverage is not None and rule.coverage[0] == bucket
    )


def _skipped_rows() -> tuple[CoverageRow, ...]:
    return tuple(
        CoverageRow(
            check=check,
            reason=f"{GRADED_ONE_DOCUMENT}: {PART_DOCUMENT}: {why}.",
            document_ids=(PART_DOCUMENT,),
        )
        for check, why in SKIPPED_RULES
    )


REVIEW_CLOSE_OUT: tuple[CoverageRow, ...] = (
    CoverageRow(
        check="fasteners",
        reason=(
            "list_fasteners returned zero instances, so no screw or bolt joint could be checked."
        ),
    ),
    CoverageRow(
        check="holes.alignment",
        reason="no hole was extracted from either pin, so no coaxial pair could be checked.",
        component_ids=(PIN_ONE, PIN_TWO),
    ),
    CoverageRow(
        check="interfaces.fit",
        reason="pin geometry was not extracted, so the dowel fit could not be computed.",
        component_ids=(PIN_ONE, PIN_TWO),
    ),
    CoverageRow(
        check="interfaces.stack",
        reason="no drawing dimensions, target gap or stack contributors were extracted.",
    ),
    CoverageRow(
        check="drawing.manufacturing_inputs",
        reason="no drawing documents or sheets were included.",
    ),
    CoverageRow(
        check="provenance",
        reason="the local-modification state is unavailable for two of the three documents.",
        document_ids=(PART_DOCUMENT, PIN_DOCUMENT),
    ),
    CoverageRow(
        check="modeling.resilience",
        reason=(
            "5 checked, 11 skipped, 28 unresolved rule result(s) over 3 document(s); 6 finding(s)."
        ),
    ),
)
"""The seven checklist items the run left open, each with the sentence the report prints.

The order is the order the coverage block reads them in, so the first five are the five it
prints; `provenance` and `modeling.resilience` are last because they are the two an engineer
can act on least directly.
"""


def _review_coverage() -> CoverageSpec:
    evidence_rows = tuple(
        CoverageRow(
            check="coverage.evidence_request",
            reason=f"{request.id} is still open: {request.what}.",
            document_ids=tuple(
                entity for entity in request.entity_ids if entity.startswith("doc:")
            ),
        )
        for request in REVIEW_EVIDENCE_REQUESTS
    )
    close_out_row = CoverageRow(
        check="coverage.closeout",
        reason=(
            "the package carries no hole, fastener or drawing evidence, so four checklist "
            "items closed out unresolved."
        ),
    )
    return CoverageSpec(
        checked=[
            CoverageRow(check=check, reason=GRADED_ONE_DOCUMENT, document_ids=(PART_DOCUMENT,))
            for check in CHECKED_RULES
        ]
        + [
            CoverageRow(
                check="rms.assembly.first_component_fixed",
                reason=GRADED_ONE_DOCUMENT,
                document_ids=(ASSEMBLY_DOCUMENT,),
            )
        ],
        skipped=list(_skipped_rows()),
        unresolved=[
            *_unread_pin_rules(),
            *(
                CoverageRow(
                    check=check,
                    reason=f"{GRADED_ONE_DOCUMENT}: {ASSEMBLY_DOCUMENT}: {why}.",
                    document_ids=(ASSEMBLY_DOCUMENT,),
                )
                for check, why in UNSETTLED_ASSEMBLY_RULES
            ),
            *_catalogue_rows("unresolved"),
            CENSUS_ROW,
            *REVIEW_CLOSE_OUT,
            close_out_row,
            *evidence_rows,
        ],
        out_of_scope=[
            *_catalogue_rows("out_of_scope"),
            CoverageRow(
                check="interference",
                reason=(
                    "the assembly holds no mechanism, so no position other than Default was "
                    "checked."
                ),
            ),
        ],
    )


def review_session() -> ReviewSession:
    """The session shaped like the 2026-09-18 review: eight findings, 5/11/39/0/7."""
    return build_attention_session(
        session_id=REVIEW_SESSION_ID,
        findings=REVIEW_FINDINGS,
        coverage=_review_coverage(),
        steps=REVIEW_STEPS,
        evidence_requests=REVIEW_EVIDENCE_REQUESTS,
        started_at=REVIEW_STARTED_AT,
        ended_at=REVIEW_ENDED_AT,
        provider_info=ProviderInfo(
            provider="openai",
            model="gpt-fixture",
            effort_mapping=EffortMapping(
                requested="high", provider_param="reasoning.effort", provider_value="high"
            ),
            key_source="env",
        ),
        usage=SessionUsage.summed(
            [
                TokenUsage(
                    input_tokens=12000,
                    cached_input_tokens=0,
                    cache_write_tokens=0,
                    output_tokens=900,
                    reasoning_tokens=640,
                    tool_result_input_tokens=None,
                    total_tokens=12900,
                    latency_s=18.5,
                ),
                TokenUsage(
                    input_tokens=15000,
                    cached_input_tokens=11000,
                    cache_write_tokens=0,
                    output_tokens=700,
                    reasoning_tokens=320,
                    tool_result_input_tokens=None,
                    total_tokens=15700,
                    latency_s=21.0,
                ),
            ],
            [2],
        ),
        unattended_runtime_minutes=1.62,
    )


# --- the 2026-09-18 model check ------------------------------------------------------------


CHECK_FINDINGS: tuple[FindingSpec, ...] = tuple(
    replace(spec, tool_result_ids=(0,)) for spec in REVIEW_FINDINGS[:3]
)
"""The same three part-rule findings, recorded by the one `check_rms_part` call.

The Model check tab offers no assembly scope, so this run holds no needs-judgement finding
at all - which is why the consequence class is the leading key on this surface (spec, Edge
Cases) and why this fixture is worth committing beside the review.
"""


def _check_coverage() -> CoverageSpec:
    return CoverageSpec(
        checked=[
            CoverageRow(
                check="modeling.resilience",
                reason=(
                    "4 checked, 11 skipped, 5 unresolved rule result(s) over 1 document(s); "
                    "3 finding(s)."
                ),
                document_ids=(PART_DOCUMENT,),
            ),
            *(
                CoverageRow(check=check, reason=GRADED_ONE_DOCUMENT, document_ids=(PART_DOCUMENT,))
                for check in CHECKED_RULES
            ),
        ],
        skipped=list(_skipped_rows()),
        unresolved=[*_catalogue_rows("unresolved"), CENSUS_ROW],
        out_of_scope=list(_catalogue_rows("out_of_scope")),
    )


def check_session() -> ReviewSession:
    """The session shaped like the 2026-09-18 model check: three findings, 5/11/5/0/6."""
    return build_attention_session(
        session_id=CHECK_SESSION_ID,
        findings=CHECK_FINDINGS,
        coverage=_check_coverage(),
        steps=("check_rms_part",),
        started_at=CHECK_STARTED_AT,
        ended_at=CHECK_ENDED_AT,
        unattended_runtime_minutes=0.02,
    )


def _subject(feature_id: str, name: str, type_name: str) -> dict[str, object]:
    """One structured subject of a check finding, as `check.json` records them."""
    return {
        "feature_id": feature_id,
        "name": name,
        "type_name": type_name,
        "group": None,
        "persist_ref": persist_ref(feature_id),
        "persist_ref_scope": PART_DOCUMENT,
        "component_ids": [PART_COMPONENT],
        "reason": None,
    }


def check_record_body() -> dict[str, object]:
    """`check.json` for the check folder: an rms check of the part, naming its session."""
    return {
        "session_id": str(CHECK_SESSION_ID),
        "scope": "part",
        "documents": [PART_DOCUMENT],
        "assembly_document": None,
        "subjects": {
            "F-001": [],
            "F-002": [
                _subject("feat:0007", "Boss-Extrude2", "ExtrudeFeature"),
                _subject("feat:0011", "Fillet1", "FilletFeature"),
            ],
            "F-003": [_subject("feat:0003", "Sketch3", "ProfileFeature")],
        },
        "exceptions_carried_forward": {"from_run": None, "count": 0, "reason": NO_RUN_ROOT},
        "unavailable_scopes": [],
    }


# --- writing the fixtures ---------------------------------------------------------------------


def write_fixtures(directory: Path | str = FIXTURE_DIR) -> list[Path]:
    """Write all four fixtures under `directory` and return every file written, sorted.

    The two folder fixtures carry the same two sessions the two loose files do: the CLI and
    the re-render need a folder with a package beside the session, and a second session
    written for them would be a second thing to keep in step with the first.
    """
    root = Path(directory)
    package = attention_package()
    review, check = review_session(), check_session()
    written = [
        save_session(review, root / REVIEW_SESSION_FILE.name),
        save_session(check, root / CHECK_SESSION_FILE.name),
        save_session(review, root / REVIEW_FOLDER.name / SESSION_FILE_NAME),
        save_package(package, root / REVIEW_FOLDER.name),
        save_session(check, root / CHECK_FOLDER.name / SESSION_FILE_NAME),
        save_package(package, root / CHECK_FOLDER.name),
        write_check_record(
            root / CHECK_FOLDER.name / CHECK_FILE_NAME, RMS_FAMILY, check_record_body()
        ),
    ]
    return sorted(written)


USAGE = "usage: uv run python -m tests.support.attention --write"


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate the committed fixtures. Deliberate, and never a side effect of a test."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["--write"]:
        print(USAGE)
        return 2
    for path in write_fixtures():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
