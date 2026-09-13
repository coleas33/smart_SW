"""Unit tests for the Markdown report renderer and dispositions (T029).

`session.json` is the source of truth (research R10); these tests check that
`render_report` surfaces every FR-009 field and every coverage bucket, that discrepancies
lead the report, that navigation links resolve through the package, and that
`apply_disposition` writes the session and re-renders the report on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from swreview.findings import Calculation, Disposition, FindingGroup, build_finding
from swreview.ir.models import Dimension, Discrepancy, Manifest, Quantity, SourceRef, Tolerance
from swreview.report.dispositions import apply_disposition
from swreview.report.markdown import render_report
from swreview.report.session import (
    Coverage,
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    InvestigationStep,
    ReviewSession,
    Timing,
    load_session,
    save_session,
)
from tests.support.packages import build_package, persist_ref

PACKAGE = build_package()


def _dimension() -> Dimension:
    return Dimension(
        nominal=Quantity(value=12.0, unit="mm"),
        tolerance=Tolerance(
            kind="symmetric",
            upper=Quantity(value=0.1, unit="mm"),
            lower=Quantity(value=0.1, unit="mm"),
            source=SourceRef(document_id="doc:2", sheet="Sheet1"),
        ),
        source=SourceRef(document_id="doc:2", sheet="Sheet1", annotation="Note 3"),
        text_as_read="12.00 +/-0.10",
    )


def full_finding(package=PACKAGE):
    """A finding populated with every optional field FR-009 requires."""
    finding = build_finding(
        finding_id="F-001",
        check="fastener.thread_engagement",
        title="Blind tapped hole thread engagement unresolved",
        status="checked_within_scope",
        severity="high",
        package=package,
        configuration="Default",
        observed="Hole feature reports drill depth only, no usable thread depth",
        requirement="Thread engagement of at least 1.0 x nominal diameter",
        recommended_action="Add tapped depth callout to the drawing",
        component_ids=["cmp:0001", "cmp:0002"],
        inputs=[_dimension(), Quantity(value=6.0, unit="mm"), "free-text note"],
        calculation=Calculation(
            model="fit.thread_engagement",
            inputs={"hole_depth": Quantity(value=12.0, unit="mm"), "note": "measured"},
            assumptions=["assume nominal diameter M6"],
            excluded_effects=["thermal expansion"],
            result={"engaged": True, "margin": Quantity(value=1.0, unit="mm")},
            units_out="mm",
            function="swreview.checks.fastener.thread_engagement",
            function_version="1.0.0",
        ),
        tool_result_ids=[0, 1],
        coverage_limits=["did not consider dynamic loading"],
        group=FindingGroup(key="pattern:P1", member_component_ids=["cmp:0001", "cmp:0002"]),
        capture_ids=["cap:1"],
        exception_id="EXC-001",
    )
    finding.disposition = Disposition(
        decision="deferred",
        note="waiting on drawing update",
        by="engineer@example.com",
        at=datetime(2026, 9, 12, 14, 0, tzinfo=UTC),
    )
    return finding


def drawing_finding(package=PACKAGE):
    """A finding with no calculation, no disposition, drawing-location based."""
    return build_finding(
        finding_id="F-002",
        check="drawing.completeness",
        title="Drawing missing tapped depth callout",
        status="suspected",
        severity="low",
        package=package,
        configuration="Default",
        observed="Sheet1 shows drill depth only",
        requirement="Tapped depth must be called out for a blind tapped hole",
        recommended_action="Ask drafter to add a tapped-depth note",
        drawing_locations=[SourceRef(document_id="doc:1", sheet="Sheet1", annotation="Note 3")],
        numeric=False,
    )


def build_session(**overrides: object) -> ReviewSession:
    fields: dict[str, object] = {
        "session_id": "99999999-8888-4777-8666-555555555555",
        "package_id": str(PACKAGE.package_id),
        "design_id": PACKAGE.design.design_id,
        "started_at": datetime(2026, 9, 12, 13, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 9, 12, 13, 30, tzinfo=UTC),
        "model": "claude-opus-5",
        "steps": [
            InvestigationStep(
                index=0,
                tool="list_holes",
                arguments={"component_id": "cmp:0001"},
                result_summary="1 hole found",
                status="ok",
                error=None,
                elapsed_s=0.1,
            ),
            InvestigationStep(
                index=1,
                tool="record_drawing_finding",
                arguments={"sheet": "Sheet1"},
                result_summary="recorded",
                status="ok",
                error=None,
                elapsed_s=0.2,
            ),
        ],
        "evidence_requests": [
            EvidenceRequest(
                id="ER-001",
                what="Tapped depth of M6 Tapped Hole1",
                why="fastener.thread_engagement",
                entity_ids=["hole:1"],
                status="open",
                answer=None,
                answered_at=None,
            )
        ],
        "findings": [full_finding(), drawing_finding()],
        "coverage": Coverage(
            unresolved=[
                CoverageItem(
                    check="fastener.thread_engagement",
                    scope=CoverageScope(component_ids=["cmp:0001"], configuration="Default"),
                    reason="usable thread depth unknown",
                    error=None,
                )
            ]
        ),
        "timing": Timing(
            baseline_minutes=90.0,
            assisted_supervision_minutes=10.0,
            assisted_verification_minutes=8.0,
            false_alarm_handling_minutes=2.0,
            unattended_runtime_minutes=25.0,
        ),
    }
    fields.update(overrides)
    return ReviewSession(**fields)  # type: ignore[arg-type]


# --- rendering: FR-009 fields ------------------------------------------------------


def test_render_report_includes_every_fr009_field() -> None:
    session = build_session()

    text = render_report(session, package=PACKAGE)

    # id, check, title, status, severity, configuration
    assert "F-001" in text
    assert "fastener.thread_engagement" in text
    assert "Blind tapped hole thread engagement unresolved" in text
    assert "checked_within_scope" in text
    assert "high" in text
    assert "Default" in text
    # components + full_path names resolved through the package
    assert "cmp:0001" in text
    assert "cmp:0002" in text
    assert "housing-1" in text
    assert "housing-2" in text
    # provenance: vault path, version, revision, configuration
    assert "/Designs/cover-assy.SLDASM" in text
    assert "/Designs/housing.SLDPRT" in text
    # observed, requirement
    assert "Hole feature reports drill depth only, no usable thread depth" in text
    assert "Thread engagement of at least 1.0 x nominal diameter" in text
    # inputs: dimension text_as_read + units, quantity units, plain string
    assert "12.00 +/-0.10" in text
    assert "6.0" in text and "mm" in text
    assert "free-text note" in text
    # calculation: model, inputs, assumptions, excluded effects, result, function+version
    assert "fit.thread_engagement" in text
    assert "assume nominal diameter M6" in text
    assert "thermal expansion" in text
    assert "margin" in text
    assert "swreview.checks.fastener.thread_engagement" in text
    assert "1.0.0" in text
    # tool result step indices
    assert "0" in text and "1" in text
    # coverage limits, recommended action
    assert "did not consider dynamic loading" in text
    assert "Add tapped depth callout to the drawing" in text
    # group members
    assert "pattern:P1" in text
    # captures
    assert "cap:1" in text
    # disposition
    assert "deferred" in text
    assert "waiting on drawing update" in text
    assert "engineer@example.com" in text
    # exception id
    assert "EXC-001" in text
    # navigation link
    assert "swreview://open?doc=" in text


def test_finding_without_calculation_or_disposition_says_so() -> None:
    session = build_session()

    text = render_report(session, package=PACKAGE)

    assert "no calculation" in text.lower()
    assert "not yet dispositioned" in text.lower()


def test_grouped_finding_lists_members() -> None:
    session = build_session()

    text = render_report(session, package=PACKAGE)

    group_section_start = text.index("pattern:P1")
    nearby = text[group_section_start : group_section_start + 400]
    assert "cmp:0001" in nearby
    assert "cmp:0002" in nearby


# --- manifest discrepancies come first ----------------------------------------------


def test_manifest_discrepancies_render_before_any_finding(fake_manifest: Manifest) -> None:
    manifest = Manifest(
        entries=fake_manifest.entries,
        discrepancies=[
            Discrepancy(
                document_id="doc:2",
                kind="version_mismatch",
                expected=3,
                actual=4,
                note="vault bumped after export",
            )
        ],
    )
    package = build_package(manifest=manifest)
    session = build_session()

    text = render_report(session, package=package)

    assert "vault bumped after export" in text
    assert text.index("vault bumped after export") < text.index("F-001")
    assert text.index("vault bumped after export") < text.index("F-002")


def test_report_without_package_notes_it_was_not_supplied() -> None:
    session = build_session()

    text = render_report(session)

    assert "not supplied" in text.lower()
    assert "swreview://open?finding=F-001" in text


# --- coverage: five buckets always present ------------------------------------------


def test_all_five_coverage_buckets_render_even_when_empty() -> None:
    session = build_session(coverage=Coverage())

    text = render_report(session, package=PACKAGE)

    for bucket in ("Checked", "Skipped", "Unresolved", "Failed", "Out of Scope"):
        assert bucket in text


# --- navigation link resolves document id and persist_ref through the package ------


def test_navigation_link_contains_document_id_and_persist_ref() -> None:
    session = build_session()

    text = render_report(session, package=PACKAGE)

    component = next(c for c in PACKAGE.components if c.id == "cmp:0001")
    assert f"doc={component.document_id}" in text
    assert f"ref={persist_ref('cmp:0001')}" in text


# --- zero findings still renders every section --------------------------------------


def test_zero_findings_session_still_renders_every_section() -> None:
    session = build_session(
        findings=[],
        evidence_requests=[],
        coverage=Coverage(),
        steps=[],
    )

    text = render_report(session, package=PACKAGE)

    assert "Findings" in text
    assert "Evidence Requests" in text
    for bucket in ("Checked", "Skipped", "Unresolved", "Failed", "Out of Scope"):
        assert bucket in text
    assert "Timing" in text
    assert "Investigation Trace" in text


def test_investigation_trace_collapses_after_fifty_steps() -> None:
    steps = [
        InvestigationStep(
            index=i,
            tool="list_holes",
            arguments={},
            result_summary="ok",
            status="ok",
            error=None,
            elapsed_s=0.01,
        )
        for i in range(60)
    ]
    session = build_session(steps=steps)

    text = render_report(session, package=PACKAGE)

    assert "60" in text
    assert "10" in text  # 60 - 50 collapsed


# --- dispositions --------------------------------------------------------------------


def test_apply_disposition_writes_session_and_rerenders_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    save_session(build_session(), run_dir / "session.json")

    updated = apply_disposition(
        run_dir,
        finding_id="F-002",
        decision="accepted",
        note="reviewed and fine",
        by="engineer@example.com",
        at=datetime(2026, 9, 12, 15, 0, tzinfo=UTC),
    )

    finding = next(f for f in updated.findings if f.id == "F-002")
    assert finding.disposition is not None
    assert finding.disposition.decision == "accepted"

    reloaded = load_session(run_dir / "session.json")
    reloaded_finding = next(f for f in reloaded.findings if f.id == "F-002")
    assert reloaded_finding.disposition is not None
    assert reloaded_finding.disposition.decision == "accepted"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "accepted" in report_text
    assert "reviewed and fine" in report_text


def test_apply_disposition_deferred_then_accepted_is_allowed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    session = build_session()
    finding = next(f for f in session.findings if f.id == "F-001")
    assert finding.disposition is not None and finding.disposition.decision == "deferred"
    save_session(session, run_dir / "session.json")

    updated = apply_disposition(
        run_dir,
        finding_id="F-001",
        decision="accepted",
        note="drawing updated",
        by="engineer@example.com",
    )

    finding = next(f for f in updated.findings if f.id == "F-001")
    assert finding.disposition is not None
    assert finding.disposition.decision == "accepted"


def test_apply_disposition_rejects_invalid_transition_from_accepted(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    save_session(build_session(), run_dir / "session.json")
    apply_disposition(
        run_dir,
        finding_id="F-002",
        decision="accepted",
        note="first pass",
        by="engineer@example.com",
    )

    with pytest.raises(ValueError, match="accepted"):
        apply_disposition(
            run_dir,
            finding_id="F-002",
            decision="rejected",
            note="changed my mind",
            by="engineer@example.com",
        )


def test_apply_disposition_rejects_unknown_decision(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    save_session(build_session(), run_dir / "session.json")

    with pytest.raises(ValueError):
        apply_disposition(
            run_dir,
            finding_id="F-002",
            decision="approved",
            note="typo decision",
            by="engineer@example.com",
        )


def test_apply_disposition_unknown_finding_id_raises_key_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    save_session(build_session(), run_dir / "session.json")

    with pytest.raises(KeyError):
        apply_disposition(
            run_dir,
            finding_id="F-999",
            decision="accepted",
            note="n/a",
            by="engineer@example.com",
        )
