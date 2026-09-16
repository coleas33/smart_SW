"""Carrying an unchanged resilient-modeling verdict forward instead of re-running it.

Lever 11a (`EfficiencySettings.carry_over_rms`, default off and staying off). The second
and later reviews of one design re-run every check over a tree that mostly did not move;
this module lets a previous run's `rms.*` findings stand when the fingerprint says the
tree behind them is the tree in front of us.

**No second hashing scheme is written.** `exceptions.fingerprint(package, component_ids,
kind)` already hashes both kinds - `geometry` per component over the transform and the
sorted face parameters, `feature_tree` per document over every feature row and equation -
and `exceptions.fingerprint_kind_for(check)` already picks between them by the `rms.`
prefix. This module composes those answers into a key and never re-implements them. That is
the DRY line to hold in code review: a private re-implementation here would hash the same
fields today and drift apart on the first change to either.

The one thing it does hash for itself is the **gap set** (`_gap_digest`), which no
fingerprint touches and nothing else in the tree digests, because a dump that could not
read a phase hashes to the same tree as one that could - see `carry_over_key`, whose four
non-fingerprint members are guard 5.

**Only `rms.*`, and not `rms.detail.individually_suppressible`.** A carry-over is a much
stronger claim than an exception refresh: an exception says "this accepted condition still
looks the same", a carry-over says "re-running this check would produce the same verdict",
which needs *everything the check reads*. The resilient-modeling family is the only one on
this tree whose entire input is inside one fingerprint, and the one rule of it that reads
`rms_suppress_test` is excluded because that array is in neither fingerprint (OQ-7,
FR-097).

**A carry is never silent** (FR-099, FR-101, FR-102). `carry_over_findings` is the one
writer and it writes through `ToolContext.record_finding` and `record_coverage`, so
`session.json`, `events.jsonl` and the report cannot disagree about what was carried: the
finding carries `carried_over_from`, `carried_over_at` and `carry_over_key`, the `checked`
coverage item's reason starts with "carried over from ", and `report/markdown.py` names the
originating run in the finding's heading and counts carried against computed.

**`Finding.status` is not touched.** A carried `demonstrated` finding is still
demonstrated; what changed is who demonstrated it and when, which is provenance and not
status. Overloading `status` would break the scorecard's matching rules (FR-100).

What a carried finding keeps that belongs to the other run is its `tool_result_ids`: they
index the *originating* session's steps, which this session does not have. They are kept
rather than cleared because the schema requires a `demonstrated` finding to carry either a
calculation or a tool result, and today's `rms.*` findings carry no calculation
(`checks/rms/results.py`); the heading line that names the originating run is what tells a
reader which run those step numbers belong to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from swreview.agent.checklist import load_checklist
from swreview.agent.settings import EfficiencySettings
from swreview.checks.rms.part import INDIVIDUALLY_SUPPRESSIBLE
from swreview.checks.rms.registry import RULES_VERSION
from swreview.exceptions import (
    RMS_CHECK_PREFIX,
    ExceptionStore,
    fingerprint,
    fingerprint_kind_for,
)
from swreview.findings import Finding, FindingStatus
from swreview.ir.models import EvidencePackage
from swreview.report.session import (
    CoverageItem,
    CoverageScope,
    ReviewSession,
    load_session,
    was_cut_short,
)
from swreview.tools.context import ToolContext

__all__ = [
    "CARRIED_REASON_PREFIX",
    "CARRYABLE_STATUSES",
    "MAX_CARRY_OVER_RUNS",
    "Carried",
    "CarryOverDecision",
    "carried_copy",
    "carry_over_findings",
    "carryable",
    "carry_over_key",
    "select_carry_over",
    "stamp_carry_over_keys",
]

CARRYABLE_STATUSES: tuple[FindingStatus, ...] = ("demonstrated", "checked_within_scope")
"""The two statuses a deterministic computation stands behind.

`suspected` and `unresolved` are where the model's judgement sits, which is exactly what
must not be frozen, and an `unresolved` finding with an open evidence request is precisely
what a new run might resolve (guard 2, data-model.md 10.5).
"""

MAX_CARRY_OVER_RUNS = 1
"""How far a verdict may travel from the run that computed it (guard 6).

A finding carried for twenty consecutive runs has not been computed for twenty runs. The
three provenance fields the contract defines say *which* run produced a verdict, not how
many times it has since been reused, so the only bound expressible without inventing a
fourth field is "not twice": a finding that arrives already carrying `carried_over_from` is
re-run. That is the conservative direction, which is the right one for a review tool, and
it costs nothing on the second review, which is what the lever is measured on.
"""

CARRIED_REASON_PREFIX = "carried over from "
"""How a carried finding's `checked` coverage item opens (FR-101).

The `checked` bucket is reused rather than a sixth bucket added: a new bucket would touch
`review-session.schema.json`, the report renderer and the scorecard aggregate to carry
information `Finding.carried_over_from` already carries.
"""

_CARRIED_REASON = CARRIED_REASON_PREFIX + "session {session_id}, carried at {at}, key {key}"


def _carryable_check(check: str) -> bool:
    """Whether a verdict for `check` is inside one fingerprint end to end (FR-097)."""
    return check.startswith(RMS_CHECK_PREFIX) and check != INDIVIDUALLY_SUPPRESSIBLE


def _gap_digest(package: EvidencePackage) -> str:
    """A SHA-256 over this package's gap set: what the extractor could not read.

    Not covered by either fingerprint, and not coverable by them: a gap says a phase did
    not run or a document did not parse, and the rows that *did* come through are identical
    either way, so the tree hashes the same while the review has less to read. Carrying a
    verdict across that is carrying "nothing wrong here" out of a dump that could not look.

    `kind`, `entity_kind`, `entity_id` and `reason` - not `error`, whose text can carry an
    exception message that moves between runs for the same missing thing. Digested rather
    than listed because the shipped extractor writes one `unsupported` gap per document on
    every dump (`ManifestBuilder.cs:57,92-98`), and the key is stored on every carried
    finding of every session. That is a new hash of a field nothing else hashes, not a
    second implementation of an existing one: FR-096's rule is that the *tree* is
    fingerprinted in one place, and it still is.
    """
    rows = sorted(
        json.dumps(
            [gap.kind, gap.entity_kind, gap.entity_id, gap.reason],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for gap in package.gaps
    )
    return sha256("\n".join(rows).encode("utf-8")).hexdigest()


@cache
def _checklist_version() -> int:
    """The version of the mandatory checklist this build grades against (guard 5).

    Cached because `checklist_v1.yaml` ships beside the code and cannot change inside one
    process, and because the key is computed once per finding.
    """
    return load_checklist().version


def carry_over_key(package: EvidencePackage, finding: Finding) -> str:
    """The per-finding key that decides whether `finding` may be carried (FR-098).

    A compact JSON array, deliberately **not** a digest of its members: the key is stored on
    the finding so the decision is reproducible by hand against the package, and hashing the
    whole would hide what was compared. JSON rather than a delimited string because a
    component id needs no escaping convention invented here. Its members, in order:

    0. `finding.check`;
    1. the calculation's `function_version` when the finding carries one, which today is
       null for every carryable finding - see member 8;
    2. `sorted(finding.component_ids)`;
    3. the fingerprint kind `exceptions.fingerprint_kind_for` chose;
    4. that fingerprint, which is the tree or the geometry the verdict was computed over;
    5. `extractor.profile`, because a `model_check` dump and a `full` dump of one design
       hold the same feature rows and answer different questions;
    6. `_gap_digest(package)`, because what the extractor could not read is not in the rows
       it did read;
    7. `_checklist_version()`, the checklist the run graded against;
    8. `RULES_VERSION`, the rms catalogue's own version, which is the check version member 1
       cannot supply: `rms.*` findings carry no calculation.

    Members 5 to 8 are guard 5's other half. The fingerprint answers "is this the same
    tree?"; on its own it would carry a verdict across a narrowed dump, a phase that failed,
    a new checklist item or a reworded rule, all with the tree untouched (RK-15). They are
    in the key rather than compared session to session because the key is the only thing a
    previous run leaves behind that records the package **and** the build it graded under.

    Raises `LookupError` through `exceptions.fingerprint` when the package does not hold
    one of the finding's components: a key is never silently re-bound to whatever is left.
    """
    kind = fingerprint_kind_for(finding.check)
    return json.dumps(
        [
            finding.check,
            finding.calculation.function_version if finding.calculation is not None else None,
            sorted(finding.component_ids),
            kind,
            fingerprint(package, finding.component_ids, kind),
            package.extractor.profile,
            _gap_digest(package),
            _checklist_version(),
            RULES_VERSION,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class Carried:
    """One finding of a previous session that may stand, and the key that says so."""

    finding: Finding
    key: str


@dataclass(frozen=True)
class CarryOverDecision:
    """What carry-over decided over the whole of a previous session.

    Every finding the previous session held is in exactly one of the two lists, which is
    the invariant data-model.md 10.5 pins: `carried + re_run == len(previous.findings)`.
    """

    carried: tuple[Carried, ...] = ()
    re_run: tuple[Finding, ...] = ()

    @property
    def total(self) -> int:
        return len(self.carried) + len(self.re_run)


def _flagged_component_ids(
    package: EvidencePackage, exceptions: ExceptionStore | None
) -> frozenset[str]:
    """Components touched by an exception in `needs_review` (guard 4).

    `refresh` runs first, because the point of the guard is that the accepted condition is
    re-checked against *this* package before anything is carried past it. An exception that
    an earlier run already flagged counts too: what says the accepted condition is
    unverified is the flag, not the transition, and only an engineer's `reaccept` clears it.
    """
    if exceptions is None:
        return frozenset()
    exceptions.refresh(package)
    bindings = {
        binding
        for exception in exceptions.exceptions
        if exception.status == "needs_review"
        for binding in exception.bindings
    }
    return frozenset(
        component.id
        for component in package.components
        if (component.persist_ref, component.persist_ref_scope) in bindings
    )


def _failed_checks(previous: ReviewSession) -> frozenset[str]:
    return frozenset(item.check for item in previous.coverage.failed)


def carryable(finding: Finding) -> bool:
    """Whether a verdict for `finding` could ever be carried, from the finding alone.

    The scope rule and nothing else: `rms.*` because that family's whole input is inside
    one fingerprint, not `rms.detail.individually_suppressible` because it reads
    `rms_suppress_test` (FR-097), and only the two statuses a computation stands behind. It
    is read twice - by `stamp_carry_over_keys`, deciding what to leave a key for, and by
    `select_carry_over`, deciding what to carry - and the two must agree, or a run would
    stamp keys nothing reads or look for keys nothing wrote.
    """
    return _carryable_check(finding.check) and finding.status in CARRYABLE_STATUSES


def _may_carry(
    finding: Finding, *, failed: frozenset[str], flagged: frozenset[str]
) -> bool:
    """The per-finding half of the guards. The session-wide half is in `select_carry_over`."""
    return (
        carryable(finding)  # scope, and guard 2
        and finding.check not in failed  # guard 1, per check
        and finding.disposition is None  # guard 3
        and not set(finding.component_ids) & flagged  # guard 4
        and finding.carried_over_from is None  # guard 6, MAX_CARRY_OVER_RUNS == 1
    )


def select_carry_over(
    package: EvidencePackage,
    previous: ReviewSession | None,
    *,
    exceptions: ExceptionStore | None = None,
    at: datetime,
) -> CarryOverDecision:
    """Partition `previous`'s findings into the ones that may stand and the ones to re-run.

    `at` is not read here - it is the caller's carry time, taken as an argument so the
    selector and the writer agree on one clock - but a selection made at a different time
    is a different decision, and taking it keeps that visible at every call site.

    Guard 5 is the comparison this whole module exists for: the key `previous` left on the
    finding, against the key the same finding produces over *this* package and this build.
    Equal means every input the check reads is where it was - the tree, and the profile, gap
    set, checklist version and rule version `carry_over_key` puts beside it; different means
    something moved and the verdict is recomputed. A finding with no stored key is re-run,
    which is what a previous run made with the lever off leaves behind - the honest answer,
    since such a run recorded nothing about the tree it graded.

    Three refusals are whole-session rather than per finding: a session that never ended
    and a session that ended without finishing are not verdicts to reuse at all (guard 1,
    `report.session.was_cut_short`), and a session about another design is not evidence
    about this one. All three leave every finding in `re_run`, so the invariant holds.
    """
    if previous is None:
        return CarryOverDecision()
    if (
        previous.ended_at is None
        or was_cut_short(previous)
        or previous.design_id != package.design.design_id
    ):
        return CarryOverDecision(re_run=tuple(previous.findings))

    failed = _failed_checks(previous)
    flagged = _flagged_component_ids(package, exceptions)

    carried: list[Carried] = []
    re_run: list[Finding] = []
    for finding in previous.findings:
        if not _may_carry(finding, failed=failed, flagged=flagged):
            re_run.append(finding)
            continue
        try:
            key = carry_over_key(package, finding)
        except LookupError:
            # A component the previous run cited is not in this package: the fingerprint
            # refuses to re-bind, and a finding whose subject we cannot identify is re-run.
            re_run.append(finding)
            continue
        if finding.carry_over_key != key:  # guard 5
            re_run.append(finding)
            continue
        carried.append(Carried(finding=finding, key=key))
    return CarryOverDecision(carried=tuple(carried), re_run=tuple(re_run))


def carried_copy(
    finding: Finding, *, finding_id: str, from_session: UUID, key: str, at: datetime
) -> Finding:
    """`finding` as this run will record it: a new id, and the three provenance fields.

    The id comes from *this* run's allocator because `F-001` is an identifier within one
    session (`swreview.ids`); which run produced the verdict is what `carried_over_from`
    says, and the key is what makes the decision reproducible by hand.
    """
    return finding.model_copy(
        update={
            "id": finding_id,
            "carried_over_from": from_session,
            "carried_over_at": at,
            "carry_over_key": key,
        }
    )


def _coverage_item(finding: Finding, *, from_session: UUID, key: str, at: datetime) -> CoverageItem:
    return CoverageItem(
        check=finding.check,
        scope=CoverageScope(
            component_ids=list(finding.component_ids),
            configuration=finding.configuration,
        ),
        reason=_CARRIED_REASON.format(session_id=from_session, at=at.isoformat(), key=key),
        error=None,
    )


def stamp_carry_over_keys(
    session: ReviewSession, package: EvidencePackage, *, efficiency: EfficiencySettings
) -> int:
    """Leave a `carry_over_key` on every carryable finding this run computed, and say how
    many.

    The other half of the lever, and the half without which the first half can decide
    nothing: a key is a statement about the package a verdict was computed over, and the
    only run that holds that package is the one that computed it. Written at finalization
    rather than as each finding is recorded, because that is the one point where the run is
    over, the package is in hand and the work is done once instead of once per finding
    write.

    It runs only with `carry_over_rms` on, so a run with the lever off writes nothing and
    leaves nothing for a later run to carry - the off arm of the A/B has no memory at all,
    which is what makes the two arms comparable. Recomputing is idempotent: finalizing
    twice stamps the same values, and a finding carried into this run already holds the key
    this recomputes.

    A finding whose components this package no longer holds is left unstamped rather than
    raising: finalization must not fail on the way to writing the session (rule 5).
    """
    if not efficiency.carry_over_rms:
        return 0
    stamped = 0
    for index, finding in enumerate(session.findings):
        if not carryable(finding):
            continue
        try:
            key = carry_over_key(package, finding)
        except LookupError:
            continue
        session.findings[index] = finding.model_copy(update={"carry_over_key": key})
        stamped += 1
    return stamped


def carry_over_findings(
    context: ToolContext,
    *,
    previous_session: Path | str | None,
    efficiency: EfficiencySettings,
    at: datetime | None = None,
) -> CarryOverDecision:
    """Carry what may stand from `previous_session` into `context`'s session (lever 11a).

    The one writer. Called where the review starts, beside `record_partial_evidence`, so
    the command line and the pane get the same answer and two places do not decide what a
    carry means.

    With the flag off nothing is read and nothing is written, whatever `previous_session`
    says - that is the off arm of the A/B and it must be indistinguishable from a build
    without the lever. With the flag on and `previous_session` named, the file is read and
    a missing one raises: silently carrying nothing would make an on-arm secretly an off
    arm, and the results row would then compare the lever against itself.

    Args:
        context: The run being set up. Its session, package and exception store are read,
            and its `record_finding` / `record_coverage` are what write, so the event
            stream sees a carried finding exactly as it sees a computed one.
        previous_session: Path to the `session.json` of the run to carry from, or `None`
            when there is no earlier run to carry from.
        efficiency: This run's levers. Only `carry_over_rms` is read.
        at: The carry time recorded on every carried finding; now when omitted.

    Returns:
        What was decided, so a caller can report carried against re-run without recounting.
    """
    if not efficiency.carry_over_rms or previous_session is None:
        return CarryOverDecision()

    context.require_session()
    package = context.ir
    previous = load_session(previous_session)
    carried_at = at if at is not None else datetime.now(UTC)
    decision = select_carry_over(
        package, previous, exceptions=context.exception_store(), at=carried_at
    )

    for carried in decision.carried:
        finding = carried_copy(
            carried.finding,
            finding_id=next(context.finding_ids),
            from_session=previous.session_id,
            key=carried.key,
            at=carried_at,
        )
        context.record_finding(finding)
        context.record_coverage(
            "checked",
            _coverage_item(
                finding, from_session=previous.session_id, key=carried.key, at=carried_at
            ),
        )
    return decision

