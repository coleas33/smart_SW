"""Builders for the lever 11a carry-over tests (T104, T105).

Two test modules read this one - the key and the guards - and both need the same three
things: a package with a feature tree an `rms.*` finding can be fingerprinted against, a
finding over that tree, and a finished previous session holding it. Kept here rather than
in either module so the *package* both fingerprint against is provably the same object,
which is what makes "mutate one feature row and the finding is re-run" a statement about
the fingerprint and not about two different fixtures.

`RMS_CHECK` and `OTHER_RMS_CHECK` are real registered rule ids, asserted as such in
`tests/unit/test_carry_over_key.py`: `carry_over.py` branches on the `rms.` prefix alone,
so a made-up id would let every test here pass over a rule that does not exist.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from swreview.agent.settings import EfficiencySettings
from swreview.carry_over import stamp_carry_over_keys
from swreview.findings import Finding, FindingStatus, build_finding
from swreview.ir.models import EvidencePackage
from swreview.report.session import (
    CLOSEOUT_CHECK,
    CoverageItem,
    CoverageScope,
    ReviewSession,
)
from swreview.tools.context import new_session
from tests.support.features import (
    FeatureSpec,
    PartSpec,
    feature,
    rms_package,
    sketch_feature,
)

RMS_CHECK = "rms.sketches.fully_defined"
OTHER_RMS_CHECK = "rms.folders.present"

PREVIOUS_SESSION_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
PREVIOUS_STARTED = datetime(2026, 9, 14, 8, 0, 0, tzinfo=UTC)
PREVIOUS_ENDED = datetime(2026, 9, 14, 8, 20, 0, tzinfo=UTC)
CARRIED_AT = datetime(2026, 9, 16, 9, 0, 0, tzinfo=UTC)

COMPONENT = "cmp:0001"
"""The single instance of the part `carry_package` builds; a part-only package numbers
its first instance `cmp:0001` (`tests/support/features.rms_package`)."""


def base_features() -> tuple[FeatureSpec, ...]:
    """A sketch and an extrusion: two rows, every hashed field of both inside the digest.

    Neither row names the other. `feature_tree` hashes `child_ids`, so a fixture that wired
    the two together would make renaming one row a change to two, and the minimum bar test
    below would no longer be about one row.
    """
    return (
        sketch_feature("Sketch1"),
        feature("Boss-Extrude1", "Extrusion"),
    )


def carry_package(features: Sequence[FeatureSpec] | None = None) -> EvidencePackage:
    """A one-part package whose tree is `features`, defaulting to `base_features()`."""
    return rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                features=base_features() if features is None else tuple(features),
            )
        ]
    )


def mutated_package() -> EvidencePackage:
    """`carry_package()` with exactly one feature row changed: the extrusion is renamed.

    The name is one of the fields `fingerprint(..., "feature_tree")` hashes
    (`exceptions.py:190-246`), so this is the smallest edit that must move the digest.
    """
    sketch, _ = base_features()
    return carry_package((sketch, feature("Boss-Extrude2", "Extrusion")))


def rms_finding(
    package: EvidencePackage,
    *,
    finding_id: str = "F-001",
    check: str = RMS_CHECK,
    status: FindingStatus = "demonstrated",
    component_ids: Sequence[str] = (COMPONENT,),
) -> Finding:
    """One `rms.*` finding over `package`, with the evidence its status requires."""
    return build_finding(
        finding_id=finding_id,
        check=check,
        title=f"{check} on {', '.join(component_ids)}",
        status=status,
        severity="medium",
        package=package,
        configuration=package.design.active_configuration,
        observed="the tree shows the condition",
        requirement="the rule requires otherwise",
        recommended_action="fix the tree",
        component_ids=component_ids,
        tool_result_ids=(0,),
        coverage_limits=("the tree was read as dumped",) if status == "unresolved" else (),
    )


def previous_session(
    package: EvidencePackage,
    findings: Sequence[Finding],
    *,
    ended: bool = True,
    failed_checks: Sequence[str] = (),
    closeout_reason: str | None = None,
    stamped: bool = True,
) -> ReviewSession:
    """A previous run of `package` holding `findings`, finished unless `ended` is False.

    `stamped` is what that run's finalization did with the lever on: it left a
    `carry_over_key` on every carryable finding, which is the only record of the tree it
    graded and therefore the only thing a later run can compare against. `stamped=False` is
    a previous run made with the lever off.

    `closeout_reason` is a run that *ended* but did not finish: `ReviewRun._closeout`
    writes one `unresolved` item under `CLOSEOUT_CHECK` when a turn is cut short by
    `max_steps` or by the provider's output ceiling, and sets `ended_at` as usual. Guard 1
    is about that run, and it is the only record of it there is.
    """
    session = new_session(package)
    session.session_id = PREVIOUS_SESSION_ID
    session.started_at = PREVIOUS_STARTED
    session.ended_at = PREVIOUS_ENDED if ended else None
    session.findings = list(findings)
    session.coverage.failed = [
        CoverageItem(
            check=check,
            scope=CoverageScope(component_ids=[COMPONENT]),
            reason="the check tool raised",
            error="RuntimeError",
        )
        for check in failed_checks
    ]
    if closeout_reason is not None:
        session.coverage.unresolved = [
            CoverageItem(
                check=CLOSEOUT_CHECK,
                scope=CoverageScope(),
                reason=closeout_reason,
                error=None,
            )
        ]
    if stamped:
        stamp_carry_over_keys(session, package, efficiency=EfficiencySettings(carry_over_rms=True))
    return session
