"""Render a `ReviewSession` to a Markdown report (research R10, FR-009 through FR-013).

`session.json` is the only source of truth; this module never reads or writes it. The
report is plain Markdown - headings and pipe tables, no HTML (constitution Principle VI):
an engineer must be able to reproduce any finding from what is printed here.

Section order: title, manifest discrepancies, summary counts, start here (only when the
caller supplies a ranking), findings grouped by severity (high to info), evidence
requests, coverage (all five buckets, always), timing, tokens (only when the session
carries usage), investigation trace (collapsed past 50 steps).
"""

from __future__ import annotations

from datetime import datetime

from swreview.agent.providers import CACHED_SHARE_PUBLISHABLE, TokenUsage
from swreview.findings import Calculation, Disposition, Finding, carried_and_computed
from swreview.ir.models import (
    Angle,
    ComponentInstance,
    Dimension,
    EvidencePackage,
    ManifestEntry,
    Quantity,
    SourceRef,
)
from swreview.report.attention import Ranking, coverage_line, start_here_lines
from swreview.report.session import (
    CoverageItem,
    CoverageScope,
    ReviewSession,
    SessionUsage,
)
from swreview.report.text import markdown_text
from swreview.report.unexamined import not_examined

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
_NOT_REPORTED = "not reported"
"""What a count the provider never sent renders as. Not `0`, which is a measurement, and
not a dash, which a reader can mistake for one (Principle I)."""


def render_report(
    session: ReviewSession,
    package: EvidencePackage | None = None,
    *,
    ranking: Ranking | None = None,
) -> str:
    """Render `session` (and optionally the `package` it reviewed) to Markdown text.

    `ranking` is keyword-only and comes after `package`, which six of the eight call sites
    pass positionally (research R2.6). With no ranking the output is what this renderer
    produced before "Start here" existed, byte for byte.
    """
    components_by_id = _components_by_id(package)
    lines: list[str] = []

    lines.extend(_render_title(session))
    lines.append("")
    lines.extend(_render_discrepancies(package))
    lines.append("")
    lines.extend(_render_summary(session, package))
    lines.append("")
    if ranking is not None:
        lines.extend(_render_start_here(ranking))
        lines.append("")
    explanations = (
        {
            member_id: row.explanation
            for row in ranking.rows
            if row.explanation is not None
            for member_id in row.member_finding_ids
        }
        if ranking is not None
        else {}
    )
    lines.extend(_render_findings(session, package, components_by_id, explanations))
    lines.append("")
    lines.extend(_render_evidence_requests(session))
    lines.append("")
    lines.extend(_render_coverage(session))
    lines.append("")
    lines.extend(_render_timing(session))
    lines.append("")
    if session.usage is not None:
        lines.extend(_render_tokens(session.usage, _provider_name(session)))
        lines.append("")
    lines.extend(_render_trace(session))

    return "\n".join(lines).rstrip() + "\n"


# --- title ---------------------------------------------------------------------------


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "unknown"


def _render_title(session: ReviewSession) -> list[str]:
    lines = [
        f"# Design Review Report: {session.design_id}",
        "",
        f"- Session: {session.session_id}",
        f"- Model: {session.model}",
    ]
    lines.extend(_render_provider_info(session))
    lines.append(f"- Started: {_fmt_dt(session.started_at)}")
    lines.append(f"- Ended: {_fmt_dt(session.ended_at)}")
    return lines


def _render_provider_info(session: ReviewSession) -> list[str]:
    """The provider, its effort control, and the failed session this one retries.

    Both fields are optional in the contract, so a session written before the provider
    port renders exactly as it did: the lines appear only when there is something to say.
    """
    lines: list[str] = []
    info = session.provider_info
    if info is not None:
        mapping = info.effort_mapping
        lines.append(
            f"- Provider: {info.provider} (effort {mapping.requested} sent as "
            f"{mapping.provider_param}={mapping.provider_value}; key from {info.key_source})"
        )
    if session.retry_of is not None:
        lines.append(f"- Retry of session: {session.retry_of}")
    if session.reused_from is not None:
        # Lever 9: the evidence was copied from an earlier run rather than dumped for this
        # one. A reader deciding how much to trust a finding needs that on the first screen,
        # not in `session.json`.
        lines.append(f"- Evidence reused from run: {session.reused_from}")
    return lines


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


def _render_summary(session: ReviewSession, package: EvidencePackage | None) -> list[str]:
    """The counts, and - when the package is in hand - what the run never read.

    The not-examined line is the report's half of the lightweight warning
    (`report/unexamined.py`): an assembly whose pins were lightweight reads as clean
    without it. It needs the package, so a render from the session alone prints nothing
    rather than guessing, and a package whose every instance was read prints nothing
    rather than a zero the eye learns to skip.
    """
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

    unread = not_examined(package) if package is not None else None
    if unread is not None:
        lines.append(f"- Not examined: {unread.sentence}")

    return lines


# --- start here ------------------------------------------------------------------------


def _render_start_here(ranking: Ranking) -> list[str]:
    """The ranking, immediately above Findings (contracts/attention.md section 3).

    Amplify, never filter: this section names at most `ranking.top_n` rows, and every
    finding still renders in full below in its severity section. The rows, the
    not-amplified line and the coverage block are `attention.py`'s own words - this
    function adds the heading, the blank lines between the three blocks and the footer,
    which names the version the ranking was computed under rather than a literal, so a
    report rendered from a future policy says which one ranked it.
    """
    return [
        "## Start here",
        "",
        *start_here_lines(ranking),
        "",
        *coverage_line(ranking),
        "",
        f"Ranked by {ranking.policy_version}; the rule is in "
        "reviewer/src/swreview/report/attention.py.",
    ]


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
    explanations: dict[str, str] | None = None,
) -> list[str]:
    heading = f"#### {finding.id}: {finding.title}"
    if finding.carried_over_from is not None:
        # The originating run in the heading, so an engineer scanning the report sees
        # which verdicts were not computed today before reading a word of them (FR-102).
        heading += f" (carried over from session {finding.carried_over_from})"
    lines = [heading, ""]
    explanation = (explanations or {}).get(finding.id)
    if explanation is not None:
        lines.append(f"- Explanation: {markdown_text(explanation)}")
    lines.append(f"- Check: {finding.check}")
    lines.append(f"- Status: {finding.status}")
    lines.append(f"- Severity: {finding.severity}")
    lines.append(f"- Configuration: {finding.configuration}")

    if finding.component_ids:
        if package is not None:
            described = [
                f"{cid} ({components_by_id[cid].full_path})" if cid in components_by_id else cid
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
    explanations: dict[str, str] | None = None,
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
            lines.extend(_render_finding(finding, package, components_by_id, explanations))
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


def _render_coverage(session: ReviewSession) -> list[str]:
    """The five buckets, and - only when something was carried - what was not computed.

    The carried line is written from `session.findings` rather than from the coverage
    items, so it counts the findings in this report and cannot disagree with them. It is
    omitted entirely when nothing was carried, which is every run with lever 11a off, so
    the report of such a run is byte-identical to the one this build wrote before.
    """
    lines = ["## Coverage", ""]
    carried, computed = carried_and_computed(session.findings)
    if carried:
        lines.append(
            f"- Findings carried over from an earlier run: {carried}; "
            f"computed in this run: {computed}."
        )
        lines.append("")
    for key, heading in _COVERAGE_BUCKETS:
        lines.extend(_render_coverage_bucket(heading, getattr(session.coverage, key)))
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


# --- tokens --------------------------------------------------------------------------


def _fmt_count(value: int | None) -> str:
    """A reported count, or `not reported`. Never `0` and never a dash (Principle I)."""
    return str(value) if value is not None else _NOT_REPORTED


def _provider_name(session: ReviewSession) -> str | None:
    """Which provider ran this session, or `None` when it does not say."""
    return session.provider_info.provider if session.provider_info is not None else None


def _render_reasoning(usage: TokenUsage, provider: str | None) -> str:
    """The one line the two providers must never share.

    OpenAI's `reasoning_tokens` is a subset of `output_tokens`; Gemini's
    `thoughts_token_count` is a separate addend of the total (VERIFIED,
    contracts/usage.md section 3). One "output tokens" line would compare two different
    quantities, so the line names the provider's own field and its own nesting - and when
    the session names no provider, it claims neither.
    """
    count = _fmt_count(usage.reasoning_tokens)
    if provider == "gemini":
        return f"- Thoughts tokens (Gemini, a separate addend of the total): {count}"
    if provider == "openai":
        return f"- Reasoning tokens (OpenAI, inside the output tokens): {count}"
    return f"- Reasoning tokens: {count}"


def _render_cached_share(usage: TokenUsage) -> str:
    """The share, or why it is not being shown.

    Two different unknowns, said two different ways: `not reported` means the provider
    gave us no counts to divide, and `unknown (probe L1 not recorded)` means we have the
    counts but have not yet measured that the cached count is contained in the input
    count, without which the ratio is not a share (FR-047).
    """
    if not CACHED_SHARE_PUBLISHABLE:
        return "- Cached input share: unknown (probe L1 not recorded)"
    share = usage.cached_input_share
    if share is None:
        return f"- Cached input share: {_NOT_REPORTED}"
    return f"- Cached input share: {share:.1%}"


def _render_tokens(usage: SessionUsage, provider: str | None) -> list[str]:
    """What the run cost. The caller renders this only when the session carries usage.

    A feature 001, 002 or 003 session was written before this feature and has none, so
    its report is byte-identical to the one the renderer produced then (contracts/usage.md
    section 8). Every count here is the session's own summed total, read and never
    recomputed: `SessionUsage.summed` is the one place token counts are added.
    """
    totals = usage.totals
    return [
        "## Tokens",
        "",
        f"- Rounds: {usage.rounds}",
        f"- Turns: {usage.turns}",
        f"- Input tokens: {_fmt_count(totals.input_tokens)}",
        f"- Cached input tokens: {_fmt_count(totals.cached_input_tokens)}",
        f"- Uncached input tokens: {_fmt_count(totals.uncached_input_tokens)}",
        f"- Cache write tokens: {_fmt_count(totals.cache_write_tokens)}",
        f"- Output tokens: {_fmt_count(totals.output_tokens)}",
        _render_reasoning(totals, provider),
        f"- Tool-result input tokens: {_fmt_count(totals.tool_result_input_tokens)}",
        f"- Total tokens: {_fmt_count(totals.total_tokens)}",
        _render_cached_share(totals),
        f"- Model latency: {totals.latency_s:.2f} s",
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
