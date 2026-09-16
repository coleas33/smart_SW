"""`report.md`, the product of a re-model run (T093).

The section order is the nine-row table of `contracts/run-artifacts.md` and it is fixed:
Principle VI fixes the first three and FR-056 fixes the last. `SECTIONS` is that order,
and `render_report` walks it, so a section cannot be dropped, added or moved by editing
prose - section 9 in particular, which is the sentence that keeps a clean rebuild from
reading as an approval and is exactly what gets cut from a long report.

Three things this module will not do.

**It never claims from intent.** "Every write went to the copy" (FR-041) is stated from
two independent records - each `ChangeRecord.target_path`, which is the path `VerifyTarget`
confirmed for that write, and `remodel.log`'s per-request `target=` - and it is stated with
the counts. A record that names another path is printed, and the claim is withdrawn in the
same paragraph rather than being quietly omitted.

**It never says "success".** A run that moved 3 of 200 features has reorganized almost
nothing, and the headline says what is true of the part: this part needs rebuilding. A
truncated run says `truncated` in its first line, and a source attestation that no longer
matches says so ahead of everything else, because that one fact makes the run a failure
whatever else went well.

**It never invents attribution.** Every judgement item names the provider and the model out
of its own fields (`DescriptionProposal.provider`, `GlobalProposal.model`, and so on for a
group the model assigned), never from a run-level default, because two providers can
contribute to one run and a default would put one of them on the other's proposal.

The inputs are handed in rather than read, except for `remodel.log`, which only this
module reads (`read_log_targets`): the plan, the grades, the geometry and the change
records are already in memory at report time - `apply_log.read_changes` is the reader
for those - and a second parser here would be a second idea of an artifact the run
just wrote.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from swreview.remodel.apply_log import CHANGES_FILE_NAME, ChangeRecord, in_flight
from swreview.remodel.artifacts import GradedRun
from swreview.remodel.geometry import GeometryArtifact
from swreview.remodel.plan import RemodelPlan, SourceAttestation
from swreview.report.dispositions import REPORT_FILE_NAME

__all__ = [
    "ENGINEER_STOP",
    "GEOMETRY_NOT_READ",
    "LOG_FILE_NAME",
    "REPORT_FILE_NAME",
    "SECTIONS",
    "read_log_targets",
    "render_report",
    "write_report",
]

LOG_FILE_NAME = "remodel.log"
"""The bridge's own record of this run, beside the change log `apply_log.py` writes.

`changes.jsonl`, its `ChangeRecord` and its reader are that module's and are used here
unchanged: the report is the second reader of one log, not a second idea of it."""

SECTIONS: tuple[str, ...] = (
    "Headline",
    "Change list",
    "Grade",
    "Geometry",
    "Rebuild list",
    "Deviations",
    "Judgement",
    "Attestation",
    "Credit and status",
)
"""The nine sections of `contracts/run-artifacts.md`, in the order they are rendered.

Section 1 is the report's first line and is rendered as the title, because that is where a
truncated run, a failed gate and a changed attestation have to say so; sections 2 to 9 are
`##` headings under it.
"""

_TERMINAL: tuple[str, ...] = ("applied", "failed", "rolled_back", "rollback_failed")
"""The four statuses a change reaches, in the order the change list counts them: what
landed, what did not, what was undone, what could not be undone. `attempting` is the fifth
`Status` and is not one of them - it means the process died inside that change."""

ATTESTATION_CHANGED = (
    "the source file changed while this run was working: {path} no longer matches the "
    "length, last-write time and hash recorded before the copy was made, so this run is "
    "recorded as failed whatever else it did"
)

NEEDS_REBUILDING = "this part needs rebuilding"

RUN_FAILED = "this run failed and the copy was not saved"

GATE_DID_NOT_PASS = (
    "the geometry of the copy could not be shown unchanged, so this run did not save it"
)

GEOMETRY_NOT_READ = (
    "The `remodel.geometry` reading of the copy at the end of this run never came back, so "
    "there is no comparison to report and no `geometry.json` to read one from. What the "
    "geometry did is **unknown**, and unknown is not unchanged: the run is failed and the "
    "copy discarded on exactly that reading."
)
"""Section 4 when the second measurement did not answer. The section is written rather
than dropped, because a report missing a section reads as a run that had nothing to say
about it, and this run has something to say: nobody took the reading."""

REORGANIZED = "this run reorganized the copy"

TRUNCATED = (
    "the run was truncated by one of its limits before every planned change was applied"
)

STOPPED = "the engineer stopped this run before every planned change was applied"
"""The other way a run finalizes `truncated`, and it is not a limit.

`truncated` is one state reached two ways - the three bounds of `Limits`, and a person
pressing Stop - so the state alone cannot say why the run ended short and the headline is
where the difference has to be visible. Printing the limit sentence over a stop would
assert a cause the evidence does not support (Principle I), and `data-model.md` section 11
requires a truncated run to carry a distinct headline rather than a generic one."""

SAVE = "save"
"""`apply_log.RecordKind`'s one kind the plan never proposes (the copy is saved once, at
the end). Named because the "planned changes applied" arithmetic has to leave it out."""

ENGINEER_STOP = "stopped"
"""`apply.StopReason`'s engineer stop, as `render_report` is handed it.

Named here because this module selects the headline on it and imports nothing from
`apply.py` - `apply.py` imports this module. A test asserts the two spellings are one
token, so a rename cannot quietly take the headline back to the limit sentence."""

WRITES_WENT_TO_THE_COPY = (
    "Every write of this run went to `{copy}`. That is read from evidence rather than "
    "from intent: {records} of {total_records} change record(s) in `{changes}` name it as "
    "the target `VerifyTarget` confirmed, and {requests} of {total_requests} mutating "
    "request(s) in `{log}` name it (FR-041)."
)

WRITES_WENT_ELSEWHERE = (
    "This run **cannot claim** that every write went to `{copy}`. {records} of "
    "{total_records} change record(s) name another target ({other}), and {requests} of "
    "{total_requests} mutating request(s) in `{log}` name one. A run whose own record "
    "contradicts the claim reports the contradiction; it does not drop it (FR-041)."
)

NO_WRITE_RECORD = (
    "No write was recorded for this run, so there is nothing to state about where its "
    "writes went: `{changes}` holds no change with a target and `{log}` holds no mutating "
    "request."
)

GLOBALS_DRIVE_NOTHING = (
    "The globals added by this run **drive nothing yet**: a v1 global names a value and no "
    "dimension is driven from it, because the IR carries no dimensions and this version "
    "can neither name one nor prove what an equation on one would drive (FR-030)."
)

CREDIT = (
    "The rules this run applied, the six groups and the group vocabulary are the "
    "**Resilient Modeling Strategy**'s; this tool implements them and claims none of "
    "them as its own."
)

PROPOSAL_NOT_ACCEPTANCE = (
    "**This copy is a proposal the engineer accepts or discards, and not an engineering "
    "acceptance result.** Nothing here says the part is correct: it says a tree was "
    "reorganized and that the measurements taken of it did not move. That is why there is "
    "no letter grade anywhere in this report."
)

REBIND_COVERAGE = (
    "carried exceptions were re-bound to the copy, so a source that changed between the "
    "waiver and this run cannot be told apart from one that did not"
)

_TARGET = re.compile(r"(?:^| )target=(?P<paths>.*?)(?= refused=| error=|$)")
"""`remodel.log`'s per-request target field, as `ToolServiceRequestLogger.Format` writes
it: absent on a request that wrote nothing, comma-separated when one request wrote to
more than one path.

The field is read to the **boundary of the next field** - ` refused=` or ` error=`, the
two `Format` can write after it - and not to the first space: the host appends the target
raw and unescaped, so `C:\\Users\\First Last\\...` is an ordinary target and a parse that
stopped at its space would hand the report a truncated token that never equals the
attested copy path. The comma stays the separator it is on the host's side, because that
is what `string.Join(",", TargetPaths)` joined more than one path with."""


# --- reading the two files the run folder already holds ----------------------------


def read_log_targets(run_dir: Path | str) -> tuple[str, ...]:
    """The target path of every mutating request in `remodel.log`, in request order.

    One entry per path named, so the count in the report is a count of writes and not of
    lines. A request that wrote nothing carries no `target=` field at all and contributes
    nothing here: an empty field would read like a write whose target could not be
    recorded.
    """
    path = Path(run_dir) / LOG_FILE_NAME
    if not path.is_file():
        return ()
    targets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        found = _TARGET.search(line)
        if found is not None:
            targets.extend(part for part in found.group("paths").split(",") if part)
    return tuple(targets)


# --- the report --------------------------------------------------------------------


def render_report(
    *,
    plan: RemodelPlan,
    changes: Sequence[ChangeRecord],
    graded: GradedRun,
    geometry: GeometryArtifact | None,
    attestation: SourceAttestation,
    log_targets: Sequence[str],
    stop_reason: str | None = None,
) -> str:
    """The whole report, in the nine-section order of `contracts/run-artifacts.md`.

    Args:
        plan: The plan as the run leaves it - revision 2 when the judgement phase ran -
            carrying the state, the rebuild list, the pins, the deviations, the proposals
            and the coverage.
        changes: Every line of `changes.jsonl`, both the `attempting` lines and the
            terminal ones, as `apply_log.read_changes` returns them.
        graded: Both grades and the per-rule delta (`remodel/artifacts.py`).
        geometry: `geometry.json`: the two readings, the verdict and the profile, or
            `None` where the reading never came back and there is no artifact to read.
        attestation: The source attestation **as re-checked at report time**, not as the
            plan recorded it at copy time. It is a separate argument for that reason: a
            report that read `plan.source` would print the recorded half and could never
            say that the file changed.
        log_targets: The target path of every mutating bridge request, from
            `read_log_targets`.
        stop_reason: `ApplyResult.stop.reason` (`apply.StopReason`), or `None` where the
            apply phase ran to the end of the plan. It is handed in rather than read off
            the plan because `plan.state` records *that* a run ended short and not *why*:
            the engineer's stop and the three bounds all finalize `truncated`, and the
            headline is the one place the difference is visible.
    """
    terminal, pending = _by_change(changes)
    bodies = (
        _change_list(plan, terminal, pending, attestation, log_targets),
        _grade(graded),
        _geometry(geometry),
        _rebuild_list(plan),
        _deviations(plan, graded),
        _judgement(plan),
        _attestation(attestation),
        _credit(),
    )
    headline = _headline(plan, terminal, geometry, attestation, stop_reason)
    sections = [f"# {headline}"]
    sections.extend(
        f"## {title}\n\n{body}" for title, body in zip(SECTIONS[1:], bodies, strict=True)
    )
    return "\n\n".join(sections) + "\n"


def write_report(
    run_dir: Path | str,
    *,
    plan: RemodelPlan,
    changes: Sequence[ChangeRecord],
    graded: GradedRun,
    geometry: GeometryArtifact | None,
    attestation: SourceAttestation,
    log_targets: Sequence[str],
    stop_reason: str | None = None,
) -> Path:
    """Render the report into `run_dir/report.md` and return the file."""
    target = Path(run_dir) / REPORT_FILE_NAME
    target.write_text(
        render_report(
            plan=plan,
            changes=changes,
            graded=graded,
            geometry=geometry,
            attestation=attestation,
            log_targets=log_targets,
            stop_reason=stop_reason,
        ),
        encoding="utf-8",
    )
    return target


# --- 1. the headline ---------------------------------------------------------------


def _headline(
    plan: RemodelPlan,
    terminal: Sequence[ChangeRecord],
    geometry: GeometryArtifact | None,
    attestation: SourceAttestation,
    stop_reason: str | None,
) -> str:
    """One sentence, and never the word success.

    A changed attestation is the whole headline and nothing else is said in it: it makes
    the run a failure whatever the copy looks like, and a sentence that put it beside a
    grade would invite a reader to weigh the two.
    """
    if attestation.matches is False:
        return ATTESTATION_CHANGED.format(path=attestation.path)

    applied = _landed(terminal)
    moved = len([row for row in applied if row.kind == "reorder"])
    planned = len(plan.changes) or len(terminal)
    if geometry is None or geometry.gate.verdict != "pass":
        lead = GATE_DID_NOT_PASS
    elif plan.rebuild or plan.pins:
        lead = NEEDS_REBUILDING
    elif plan.state == "failed":
        lead = RUN_FAILED
    else:
        lead = REORGANIZED

    clauses = [
        f"{moved} of {len(plan.targets)} features moved",
        f"{len(applied)} of {planned} planned changes were applied",
    ]
    if plan.state == "truncated":
        clauses.append(STOPPED if stop_reason == ENGINEER_STOP else TRUNCATED)
    clauses.append(
        "and the geometry gate could not be read"
        if geometry is None
        else f"and the geometry gate reported {geometry.gate.verdict}"
    )
    return f"{lead}: {', '.join(clauses)}"


# --- 2. the change list ------------------------------------------------------------


def _by_change(
    changes: Sequence[ChangeRecord],
) -> tuple[list[ChangeRecord], list[ChangeRecord]]:
    """The terminal record of each change, and the one left in flight, if there is one.

    The terminal line is the one that says what happened; `apply_log.in_flight` finds
    the `attempting` line with no terminal partner, which is the change the process
    died inside. It is reported as that rather than dropped, and never as applied.
    """
    terminal = [row for row in changes if row.status != "attempting"]
    pending = in_flight(tuple(changes))
    return terminal, [] if pending is None else [pending]


def _landed(rows: Sequence[ChangeRecord]) -> list[ChangeRecord]:
    """The records of planned changes that were applied, which is never the `save`.

    The copy is saved once, at the end, and the run records that write as a change record
    like any other - with the next free `seq` in the log, which is not a plan index. So a
    reader counting "planned changes applied" that took the save for one would report a
    stopped run as having applied one more change than it did, and would name the planned
    change of that number as applied when it is exactly the change the stop prevented.
    """
    return [row for row in rows if row.status == "applied" and row.kind != SAVE]


def _change_list(
    plan: RemodelPlan,
    terminal: Sequence[ChangeRecord],
    pending: Sequence[ChangeRecord],
    attestation: SourceAttestation,
    log_targets: Sequence[str],
) -> str:
    """Every attempted change with its outcome, then where every write went."""
    applied = _landed(terminal)
    counted = ", ".join(
        f"{len([row for row in terminal if row.status == status])} {status}"
        for status in _TERMINAL
    )
    lines = [
        f"{len(terminal) + len(pending)} change(s) were attempted: {counted}, and "
        f"{len(pending)} left in flight when the run stopped."
    ]
    if plan.changes:
        missing = sorted(
            {item.seq for item in plan.changes} - {row.seq for row in applied}
        )
        lines.append(
            f"The plan carried {len(plan.changes)} change(s), of which "
            f"{len(plan.changes) - len(missing)} were applied. Planned changes that were "
            "not applied: "
            + (", ".join(f"#{seq}" for seq in missing) if missing else "none")
            + "."
        )
    lines.append("")
    lines.append("| # | kind | subject | outcome | note |")
    lines.append("|---|------|---------|---------|------|")
    for row in sorted([*terminal, *pending], key=lambda item: item.seq):
        status = row.status
        outcome = (
            "attempting (in flight when the run stopped)"
            if status == "attempting"
            else status
        )
        lines.append(
            f"| {row.seq} | {row.kind} | {_subject(row)} | {outcome} | {_note(row)} |"
        )
    lines.append("")
    lines.append(_where_the_writes_went(attestation, [*terminal, *pending], log_targets))
    return "\n".join(lines)


def _subject(row: ChangeRecord) -> str:
    """What the change was about. A `save` names nothing, which is the document."""
    if row.subject is None:
        return "the document"
    if row.subject.feature_id is None:
        return row.subject.name
    return f"{row.subject.name} ({row.subject.feature_id})"


def _note(row: ChangeRecord) -> str:
    if row.error_code is None and row.error is None:
        return "-"
    return ": ".join(part for part in (row.error_code, row.error) if part is not None)


def _where_the_writes_went(
    attestation: SourceAttestation,
    records: Sequence[ChangeRecord],
    log_targets: Sequence[str],
) -> str:
    """FR-041, stated from the two records that can contradict it."""
    copy = attestation.copy_path
    targets = [row.target_path for row in records if row.target_path]
    on_copy = [path for path in targets if path == copy]
    log_on_copy = [path for path in log_targets if path == copy]
    other = sorted({*(set(targets) - {copy}), *(set(log_targets) - {copy})})
    if not targets and not log_targets:
        return NO_WRITE_RECORD.format(changes=CHANGES_FILE_NAME, log=LOG_FILE_NAME)
    if other:
        return WRITES_WENT_ELSEWHERE.format(
            copy=copy,
            records=len(targets) - len(on_copy),
            total_records=len(targets),
            other=", ".join(f"`{path}`" for path in other),
            requests=len(log_targets) - len(log_on_copy),
            total_requests=len(log_targets),
            log=LOG_FILE_NAME,
        )
    return WRITES_WENT_TO_THE_COPY.format(
        copy=copy,
        records=len(on_copy),
        total_records=len(targets),
        changes=CHANGES_FILE_NAME,
        requests=len(log_on_copy),
        total_requests=len(log_targets),
        log=LOG_FILE_NAME,
    )


# --- 3. the grade ------------------------------------------------------------------


def _grade(graded: GradedRun) -> str:
    """Counts per bucket first, the fraction second, the unresolved rule ids named."""
    before, after = graded.before.grade, graded.after.grade
    lines = ["| bucket | before | after | change |", "|--------|--------|-------|--------|"]
    for bucket, count in before.counts.items():
        moved = graded.delta.counts[bucket]
        lines.append(
            f"| {bucket.replace('_', ' ')} | {count} | {after.counts[bucket]} | {moved:+d} |"
        )
    lines.append("")
    lines.append(
        f"Fraction of the rules that reached a verdict: {_fraction(before.fraction)} "
        f"before, {_fraction(after.fraction)} after."
    )
    lines.append(
        f"Rules nobody could evaluate, before: {_named(before.unresolved_rule_ids)}; "
        f"after: {_named(after.unresolved_rule_ids)}."
    )
    lines.append("")
    if not graded.per_rule:
        lines.append("No rule changed outcome between the two grades.")
        return "\n".join(lines)
    lines.append("| rule | before | after | subjects before | subjects after |")
    lines.append("|------|--------|-------|-----------------|----------------|")
    for row in graded.per_rule:
        lines.append(
            f"| {row.rule_id} | {row.before_outcome or 'not dispatched'} | "
            f"{row.after_outcome or 'not dispatched'} | "
            f"{_named(row.subjects_before)} | {_named(row.subjects_after)} |"
        )
    return "\n".join(lines)


def _fraction(value: float | None) -> str:
    """`None` is "no rule reached a verdict", which is not a zero."""
    return "none of them reached a verdict" if value is None else f"{value:.3f}"


def _named(items: Iterable[str]) -> str:
    listed = list(items)
    return ", ".join(listed) if listed else "none"


# --- 4. the geometry ---------------------------------------------------------------


def _geometry(geometry: GeometryArtifact | None) -> str:
    """The compared quantities, the profile it was decided under, and the blind spots.

    `None` is the reading that never came back: the section says so and names nothing else,
    because every number below it would be a number nobody measured.
    """
    if geometry is None:
        return GEOMETRY_NOT_READ
    gate, tolerances = geometry.gate, geometry.tolerances
    calibration = (
        f"calibrated by {tolerances.calibration_ref}"
        if tolerances.calibrated
        else "**not calibrated**: no measurement against a known answer stands behind "
        "these bounds"
    )
    lines = [
        f"Verdict: **{gate.verdict}**, under the `{gate.profile}` profile, {calibration}.",
        "",
        "| quantity | before | after | absolute | relative | bound | within |",
        "|----------|--------|-------|----------|----------|-------|--------|",
    ]
    for delta in gate.deltas:
        lines.append(
            f"| {delta.quantity} | {_number(delta.before)} | {_number(delta.after)} | "
            f"{_number(delta.absolute)} | {_number(delta.relative)} | {delta.bound} | "
            f"{_within(delta.within)} |"
        )
    lines.append("")
    lines.append(
        f"The material {'changed' if gate.material_changed else 'did not change'} "
        f"between the two readings."
    )
    if gate.diagnosis is not None:
        lines.append(f"Diagnosis: {gate.diagnosis}")
    lines.append("")
    lines.append("What this comparison **cannot** detect, on this run as on every run:")
    lines.extend(f"- {limit}" for limit in gate.coverage_limits)
    return "\n".join(lines)


def _number(value: float | tuple[float, ...] | None) -> str:
    if value is None:
        return "not read"
    if isinstance(value, tuple):
        return ", ".join(f"{item:.9g}" for item in value)
    return f"{value:.9g}"


def _within(value: bool | None) -> str:
    """`None` is "the comparison could not be made", which is not a pass."""
    return "not compared" if value is None else ("yes" if value else "**no**")


# --- 5. the rebuild list -----------------------------------------------------------


def _rebuild_list(plan: RemodelPlan) -> str:
    """One reason from the closed taxonomy per entry, with the edge that blocks it."""
    if not plan.rebuild and not plan.pins:
        return (
            "No feature needs rebuilding: every feature the method places was placeable "
            "by reorganizing alone."
        )
    lines: list[str] = []
    if plan.rebuild:
        lines.append(
            f"{len(plan.rebuild)} feature(s) cannot be placed by reorganizing alone:"
        )
        lines.append("")
        lines.append("| feature | reason | blocking edge | detail |")
        lines.append("|---------|--------|---------------|--------|")
        for entry in plan.rebuild:
            edge = entry.blocking_edge
            named = (
                "none recorded"
                if edge is None
                else f"{edge.parent_id} -> {edge.child_id}"
            )
            lines.append(
                f"| {entry.name} ({entry.feature_id}) | {entry.reason} | {named} | "
                f"{entry.detail} |"
            )
        lines.append("")
    if plan.pins:
        lines.append(
            f"{len(plan.pins)} feature(s) are held away from the position the method "
            f"wants for them:"
        )
        lines.append("")
        for pin in plan.pins:
            lines.append(
                f"- {pin.feature_id}: wanted at index {pin.desired_index}, achievable at "
                f"{pin.achievable_index}; {pin.reason} "
                f"({pin.blocking_edge.parent_id} -> {pin.blocking_edge.child_id})"
            )
    return "\n".join(lines).rstrip()


# --- 6. the deviations, and what was not covered -----------------------------------


def _deviations(plan: RemodelPlan, graded: GradedRun) -> str:
    """Every choice the report has to call out, then what this run did not cover."""
    lines: list[str] = ["Choices this run made that a reader has to check:", ""]
    if plan.deviations:
        for deviation in plan.deviations:
            subject = "the run" if deviation.feature_id is None else deviation.feature_id
            name = _name_of(plan, deviation.feature_id) or subject
            lines.append(
                f"- {name} -> {deviation.chosen}: {deviation.report_line} "
                f"({deviation.kind}; {deviation.rationale})"
            )
    else:
        lines.append("- no choice of this run departed from the method's own answer")
    lines.append("")
    lines.append("### Groups the model assigned")
    lines.append("")
    judged = [row for row in plan.targets if row.decided_by == "model"]
    if judged:
        lines.extend(
            f"- {row.name} ({row.feature_id}) -> {row.target_group}, by "
            f"{row.provider} {row.model}: {row.rationale}"
            for row in judged
        )
    else:
        lines.append("- none: every group came from the type table")
    lines.append("")
    lines.append("### What this run did not cover")
    lines.append("")
    lines.extend(
        f"- {item.item}: {item.reason}"
        + (f" ({_named(item.feature_ids)})" if item.feature_ids else "")
        for item in plan.coverage
    )
    if graded.exceptions is not None:
        lines.append(f"- exceptions: {REBIND_COVERAGE}")
    lines.append("")
    lines.append("### Refusals")
    lines.append("")
    if plan.scope.refusals:
        lines.extend(
            f"- scope: {refusal.message} ({refusal.code}, read from "
            f"`{refusal.signal}`)"
            for refusal in plan.scope.refusals
        )
    else:
        lines.append("- scope: none; every signal was read and none of them refuses this part")
    if plan.folders.refusals:
        lines.extend(
            f"- folder `{refusal.name}` ({refusal.existing_folder_id}): {refusal.reason}; "
            f"it holds {_named(refusal.actual_member_ids)} and the method wants "
            f"{_named(refusal.expected_member_ids)}"
            for refusal in plan.folders.refusals
        )
    else:
        lines.append("- folders: none")
    return "\n".join(lines)


def _name_of(plan: RemodelPlan, feature_id: str | None) -> str | None:
    if feature_id is None:
        return None
    found = next((row for row in plan.targets if row.feature_id == feature_id), None)
    return None if found is None else f"{found.name} ({found.feature_id})"


# --- 7. the judgement --------------------------------------------------------------


def _judgement(plan: RemodelPlan) -> str:
    """Accepted proposals with their own attribution, then the refused ones (FR-016)."""
    lines = ["**Accepted descriptions**", ""]
    if plan.descriptions:
        lines.extend(
            f"- {_name_of(plan, item.feature_id) or item.feature_id}: "
            f'"{item.text}" - {item.provider} {item.model}: {item.rationale}'
            for item in plan.descriptions
        )
    else:
        lines.append("- none")
    lines.extend(["", "**Accepted global variables**", ""])
    if plan.globals:
        lines.extend(
            f"- `{item.name}` = {item.expression} - {item.provider} {item.model}: "
            f"{item.rationale} (evidence: {_evidence(item.evidence)})"
            for item in plan.globals
        )
    else:
        lines.append("- none")
    lines.extend(["", GLOBALS_DRIVE_NOTHING, "", "**Rejected proposals**", ""])
    if plan.rejected_proposals:
        lines.extend(
            f"- `{item.tool}` {json.dumps(item.arguments, sort_keys=True)}: {item.reason} "
            f"(rule `{item.rule}`) - {item.provider} {item.model}"
            for item in plan.rejected_proposals
        )
    else:
        lines.append("- none: no proposal was refused by a rule")
    return "\n".join(lines)


def _evidence(evidence: Sequence[Any]) -> str:
    if not evidence:
        return "none recorded"
    return "; ".join(
        f"{item.feature_id} {item.parameter} = {item.value_document_units} "
        f"{item.document_length_unit}"
        for item in evidence
    )


# --- 8. the attestation ------------------------------------------------------------


def _attestation(attestation: SourceAttestation) -> str:
    """What the engineer's file was, what it is now, and the verdict on the two."""
    verdict = {
        True: "the engineer's file is byte for byte what it was when the copy was made",
        False: "**the engineer's file changed during this run**, which makes this run a "
        "failure whatever the copy looks like",
        None: "**not re-checked**: the run did not reach the re-check, so nothing is "
        "claimed about the source file",
    }[attestation.matches]
    lines = [
        f"- source: `{attestation.path}`",
        f"- length: {attestation.length_bytes} bytes",
        f"- last write (UTC): {attestation.last_write_utc.isoformat()}",
        f"- sha256: `{attestation.sha256}`",
        f"- recorded at: {attestation.recorded_at.isoformat()}",
        "- re-checked at: "
        + (
            "not re-checked"
            if attestation.rechecked_at is None
            else attestation.rechecked_at.isoformat()
        ),
        f"- copy: `{attestation.copy_path}`",
        "- copy sha256 after save: "
        + (
            "not saved"
            if attestation.copy_sha256_after_save is None
            else f"`{attestation.copy_sha256_after_save}`"
        ),
    ]
    if attestation.vault_path is not None:
        lines.append(
            f"- vault: `{attestation.vault_path}` revision {attestation.vault_revision}"
        )
    lines.extend(["", f"Verdict: {verdict}."])
    return "\n".join(lines)


# --- 9. the credit and the status --------------------------------------------------


def _credit() -> str:
    return f"{CREDIT}\n\n{PROPOSAL_NOT_ACCEPTANCE}"
