"""Render a `ReviewSession` to a Markdown report (research R10, FR-009 through FR-013).

`session.json` is the only source of truth; this module never reads or writes it. The
report is plain Markdown - headings and pipe tables, no HTML (constitution Principle VI):
an engineer must be able to reproduce any finding from what is printed here.

Section order: title, manifest discrepancies, summary counts, findings grouped by
severity (high to info), evidence requests, coverage (all five buckets, always), timing,
investigation trace (collapsed past 50 steps).
"""

from __future__ import annotations

from datetime import datetime

from swreview.findings import Calculation, Disposition, Finding
from swreview.ir.models import (
    Angle,
    ComponentInstance,
    Dimension,
    EvidencePackage,
    ManifestEntry,
    Quantity,
    SourceRef,
)
from swreview.report.session import Coverage, CoverageItem, CoverageScope, ReviewSession

_SEVERITY_ORDER = ("high", "medium", "low", "info")
_SEVERITY_HEADINGS = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}
_COVERAGE_BUCKETS = (
    ("checked", "Checked"),
    ("skipped", "Skipped"),
    ("unresolved", "Unresolved"),
    ("failed", "Failed"),
    ("out_of_scope", "Out of Scope"),
)
_TRACE_COLLAPSE_LIMIT = 50


def render_report(session: ReviewSession, package: EvidencePackage | None = None) -> str:
    """Render `session` (and optionally the `package` it reviewed) to Markdown text."""
    components_by_id = _components_by_id(package)
    lines: list[str] = []

    lines.extend(_render_title(session))
    lines.append("")
    lines.extend(_render_discrepancies(package))
    lines.append("")
    lines.extend(_render_summary(session))
    lines.append("")
    lines.extend(_render_findings(session, package, components_by_id))
    lines.append("")
    lines.extend(_render_evidence_requests(session))
    lines.append("")
    lines.extend(_render_coverage(session.coverage))
    lines.append("")
    lines.extend(_render_timing(session))
    lines.append("")
    lines.extend(_render_trace(session))

    return "\n".join(lines).rstrip() + "\n"


# --- title ---------------------------------------------------------------------------


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "unknown"


def _render_title(session: ReviewSession) -> list[str]:
    return [
        f"# Design Review Report: {session.design_id}",
        "",
        f"- Session: {session.session_id}",
        f"- Model: {session.model}",
        f"- Started: {_fmt_dt(session.started_at)}",
        f"- Ended: {_fmt_dt(session.ended_at)}",
    ]


# --- manifest discrepancies ------------------------------------------------------------


def _render_discrepancies(package: EvidencePackage | None) -> list[str]:
    lines = ["## Manifest Discrepancies"]
    if package is None:
        lines.append("")
        lines.append("_The evidence package was not supplied to the renderer._")
        return lines

    discrepancies = package.manifest.discrepancies
    lines.append("")
    if not discrepancies:
        lines.append("No discrepancies between the manifest and the reviewed documents.")
        return lines

    lines.append("| Document | Kind | Expected | Actual | Note |")
    lines.append("|---|---|---|---|---|")
    for discrepancy in discrepancies:
        lines.append(
            f"| {discrepancy.document_id} | {discrepancy.kind} | {discrepancy.expected} "
            f"| {discrepancy.actual} | {discrepancy.note} |"
        )
    return lines


# --- summary -----------------------------------------------------------------------


def _render_summary(session: ReviewSession) -> list[str]:
    lines = ["## Summary", ""]

    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for finding in session.findings:
        by_status[finding.status] = by_status.get(finding.status, 0) + 1
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1

    lines.append(f"- Total findings: {len(session.findings)}")
    if by_status:
        status_text = ", ".join(f"{status}: {count}" for status, count in sorted(by_status.items()))
        lines.append(f"- By status: {status_text}")
    if by_severity:
        severity_text = ", ".join(
            f"{severity}: {count}" for severity, count in sorted(by_severity.items())
        )
        lines.append(f"- By severity: {severity_text}")

    open_requests = sum(1 for request in session.evidence_requests if request.status == "open")
    lines.append(f"- Open evidence requests: {open_requests} of {len(session.evidence_requests)}")

    coverage_counts = ", ".join(
        f"{heading}: {len(getattr(session.coverage, key))}" for key, heading in _COVERAGE_BUCKETS
    )
    lines.append(f"- Coverage: {coverage_counts}")

    return lines


# --- findings ------------------------------------------------------------------------


def _components_by_id(package: EvidencePackage | None) -> dict[str, ComponentInstance]:
    if package is None:
        return {}
    return {component.id: component for component in package.components}


def _fmt_quantity(value: Quantity) -> str:
    return f"{value.value} {value.unit}"


def _fmt_angle(value: Angle) -> str:
    return f"{value.value} {value.unit}"


def _fmt_nominal(value: Quantity | Angle) -> str:
    return _fmt_quantity(value) if isinstance(value, Quantity) else _fmt_angle(value)


def _fmt_dimension(value: Dimension) -> str:
    nominal = _fmt_nominal(value.nominal)
    return f"{value.text_as_read} ({nominal}, tolerance: {value.tolerance.kind})"


def _fmt_input(value: Dimension | Quantity | str) -> str:
    if isinstance(value, Dimension):
        return _fmt_dimension(value)
    if isinstance(value, Quantity):
        return _fmt_quantity(value)
    return str(value)


def _fmt_calc_scalar(value: Quantity | Angle | bool | str | float) -> str:
    if isinstance(value, Quantity):
        return _fmt_quantity(value)
    if isinstance(value, Angle):
        return _fmt_angle(value)
    return str(value)


def _fmt_source_ref(location: SourceRef) -> str:
    parts = [f"document {location.document_id}"]
    if location.sheet is not None:
        parts.append(f"sheet {location.sheet}")
    if location.view is not None:
        parts.append(f"view {location.view}")
    if location.annotation is not None:
        parts.append(f"annotation {location.annotation}")
    if location.page is not None:
        parts.append(f"page {location.page}")
    return ", ".join(parts)


def _fmt_provenance(entries: list[ManifestEntry]) -> list[str]:
    lines = [
        "- Provenance:",
        "",
        "  | Document | Vault Path | Version | Revision | Configuration |",
        "  |---|---|---|---|---|",
    ]
    for entry in entries:
        lines.append(
            f"  | {entry.document_id} | {entry.vault_path} | {entry.vault_version} "
            f"| {entry.revision} | {entry.configuration} |"
        )
    return lines


def _fmt_calculation(calculation: Calculation | None) -> list[str]:
    if calculation is None:
        return ["- Calculation: no calculation"]

    lines = ["- Calculation:"]
    lines.append(f"  - model: {calculation.model}")
    lines.append(
        "  - inputs: "
        + ", ".join(f"{key}={_fmt_calc_scalar(value)}" for key, value in calculation.inputs.items())
    )
    lines.append("  - assumptions: " + "; ".join(calculation.assumptions))
    lines.append("  - excluded effects: " + "; ".join(calculation.excluded_effects))
    lines.append(
        "  - result: "
        + ", ".join(f"{key}={_fmt_calc_scalar(value)}" for key, value in calculation.result.items())
    )
    lines.append(f"  - units_out: {calculation.units_out}")
    lines.append(f"  - function: {calculation.function} (version {calculation.function_version})")
    return lines


def _fmt_disposition(disposition: Disposition | None) -> list[str]:
    if disposition is None:
        return ["- Disposition: not yet dispositioned"]
    return [
        "- Disposition:",
        f"  - decision: {disposition.decision}",
        f"  - by: {disposition.by}",
        f"  - at: {_fmt_dt(disposition.at)}",
        f"  - note: {disposition.note}",
    ]


def _navigation_link(
    finding: Finding,
    package: EvidencePackage | None,
    components_by_id: dict[str, ComponentInstance],
) -> str:
    if package is not None and finding.component_ids:
        component = components_by_id.get(finding.component_ids[0])
        if component is not None:
            return f"swreview://open?doc={component.document_id}&ref={component.persist_ref}"
    if package is not None and finding.drawing_locations:
        location = finding.drawing_locations[0]
        ref = location.persist_ref if location.persist_ref is not None else finding.id
        return f"swreview://open?doc={location.document_id}&ref={ref}"
    return f"swreview://open?finding={finding.id}"


def _render_finding(
    finding: Finding,
    package: EvidencePackage | None,
    components_by_id: dict[str, ComponentInstance],
) -> list[str]:
    lines = [f"#### {finding.id}: {finding.title}", ""]
    lines.append(f"- Check: {finding.check}")
    lines.append(f"- Status: {finding.status}")
    lines.append(f"- Severity: {finding.severity}")
    lines.append(f"- Configuration: {finding.configuration}")

    if finding.component_ids:
        if package is not None:
            described = [
                f"{cid} ({components_by_id[cid].full_path})"
                if cid in components_by_id
                else cid
                for cid in finding.component_ids
            ]
        else:
            described = list(finding.component_ids)
        lines.append("- Components: " + ", ".join(described))
    if finding.drawing_locations:
        lines.append(
            "- Drawing locations: "
            + "; ".join(_fmt_source_ref(location) for location in finding.drawing_locations)
        )

    lines.extend(_fmt_provenance(finding.provenance))
    lines.append(f"- Observed: {finding.observed}")
    lines.append(f"- Requirement: {finding.requirement}")

    if finding.inputs:
        lines.append("- Inputs:")
        for value in finding.inputs:
            lines.append(f"  - {_fmt_input(value)}")
    else:
        lines.append("- Inputs: none")

    lines.extend(_fmt_calculation(finding.calculation))

    tool_result_ids = ", ".join(str(index) for index in finding.tool_result_ids) or "none"
    lines.append(f"- Tool result steps: {tool_result_ids}")

    coverage_limits = "; ".join(finding.coverage_limits) or "none"
    lines.append(f"- Coverage limits: {coverage_limits}")

    lines.append(f"- Recommended action: {finding.recommended_action}")

    if finding.group is not None:
        members = ", ".join(finding.group.member_component_ids)
        lines.append(f"- Group: {finding.group.key} members: {members}")
    else:
        lines.append("- Group: none")

    capture_ids = ", ".join(finding.capture_ids) or "none"
    lines.append(f"- Captures: {capture_ids}")

    lines.extend(_fmt_disposition(finding.disposition))

    lines.append(f"- Exception: {finding.exception_id or 'none'}")
    lines.append(f"- Navigation: {_navigation_link(finding, package, components_by_id)}")

    return lines


def _render_findings(
    session: ReviewSession,
    package: EvidencePackage | None,
    components_by_id: dict[str, ComponentInstance],
) -> list[str]:
    lines = ["## Findings", ""]
    if not session.findings:
        lines.append("No findings.")
        return lines

    by_severity: dict[str, list[Finding]] = {severity: [] for severity in _SEVERITY_ORDER}
    for finding in session.findings:
        by_severity[finding.severity].append(finding)

    for severity in _SEVERITY_ORDER:
        findings = by_severity[severity]
        if not findings:
            continue
        lines.append(f"### {_SEVERITY_HEADINGS[severity]}")
        lines.append("")
        for finding in findings:
            lines.extend(_render_finding(finding, package, components_by_id))
            lines.append("")

    return lines


# --- evidence requests ---------------------------------------------------------------


def _render_evidence_requests(session: ReviewSession) -> list[str]:
    lines = ["## Evidence Requests", ""]
    if not session.evidence_requests:
        lines.append("No evidence requests.")
        return lines

    ordered = sorted(
        session.evidence_requests, key=lambda request: 0 if request.status == "open" else 1
    )
    lines.append("| ID | What | Why | Entity IDs | Status | Answer | Answered At |")
    lines.append("|---|---|---|---|---|---|---|")
    for request in ordered:
        answered_at = _fmt_dt(request.answered_at) if request.answered_at else ""
        lines.append(
            f"| {request.id} | {request.what} | {request.why} "
            f"| {', '.join(request.entity_ids)} | {request.status} "
            f"| {request.answer or ''} | {answered_at} |"
        )
    return lines


# --- coverage --------------------------------------------------------------------------


def _fmt_scope(scope: CoverageScope) -> str:
    parts = []
    if scope.component_ids:
        parts.append("components: " + ", ".join(scope.component_ids))
    if scope.pairs:
        parts.append("pairs: " + ", ".join(f"({a}, {b})" for a, b in scope.pairs))
    if scope.configuration is not None:
        parts.append(f"configuration: {scope.configuration}")
    if scope.positions:
        parts.append("positions: " + ", ".join(scope.positions))
    if scope.document_ids:
        parts.append("documents: " + ", ".join(scope.document_ids))
    return "; ".join(parts) if parts else "none"


def _render_coverage_bucket(heading: str, items: list[CoverageItem]) -> list[str]:
    lines = [f"### {heading}", ""]
    if not items:
        lines.append("None.")
        return lines
    lines.append("| Check | Scope | Reason | Error |")
    lines.append("|---|---|---|---|")
    for item in items:
        lines.append(
            f"| {item.check} | {_fmt_scope(item.scope)} | {item.reason} | {item.error or ''} |"
        )
    return lines


def _render_coverage(coverage: Coverage) -> list[str]:
    lines = ["## Coverage", ""]
    for key, heading in _COVERAGE_BUCKETS:
        lines.extend(_render_coverage_bucket(heading, getattr(coverage, key)))
        lines.append("")
    return lines


# --- timing --------------------------------------------------------------------------


def _fmt_minutes(value: float | None) -> str:
    return str(value) if value is not None else "unknown"


def _render_timing(session: ReviewSession) -> list[str]:
    timing = session.timing
    return [
        "## Timing",
        "",
        f"- Baseline minutes: {_fmt_minutes(timing.baseline_minutes)}",
        f"- Assisted supervision minutes: {timing.assisted_supervision_minutes}",
        f"- Assisted verification minutes: {timing.assisted_verification_minutes}",
        f"- False alarm handling minutes: {timing.false_alarm_handling_minutes}",
        f"- Unattended runtime minutes: {timing.unattended_runtime_minutes}",
        f"- Net saved minutes: {_fmt_minutes(timing.net_saved_minutes)}",
    ]


# --- investigation trace ---------------------------------------------------------------


def _render_trace(session: ReviewSession) -> list[str]:
    lines = ["## Investigation Trace", ""]
    steps = session.steps
    if not steps:
        lines.append("No investigation steps.")
        return lines

    shown = steps[:_TRACE_COLLAPSE_LIMIT]
    lines.append("| Index | Tool | Status | Elapsed (s) |")
    lines.append("|---|---|---|---|")
    for step in shown:
        lines.append(f"| {step.index} | {step.tool} | {step.status} | {step.elapsed_s} |")

    remaining = len(steps) - len(shown)
    if remaining > 0:
        lines.append("")
        lines.append(
            f"_Showing the first {len(shown)} of {len(steps)} steps; {remaining} more steps "
            "collapsed._"
        )

    return lines
