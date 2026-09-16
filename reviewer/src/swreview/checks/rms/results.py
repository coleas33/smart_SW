"""What one RMS rule concluded about one document: `RuleResult` and its constructors.

`data-model.md` section 2 defines the type; this module is the only place it is built, so
the four things every rule would otherwise restate live here once (constitution Principle
V, DRY):

- **the outcome invariant.** A `fail`, `warn` or `waived` result carries a `CheckResult`;
  a `skip`, `unresolved` or `waived` result carries a reason; a `pass` carries neither.
  `__post_init__` enforces it, so a rule that forgets its reason fails at the rule, not
  three layers later in the report;
- **the evidence format.** A subject is a feature, mate, or component id, and the string
  the finding carries in `inputs` is `<id> <name> [<type_name>] persist_ref=<ref>
  scope=<document_id>` - one per subject, in the order the rule named them;
- **severity.** `fail` is `demonstrated`/`medium`, `high` for the two rule families that
  break a rebuild rather than untidy the tree (`rms.refs.*`,
  `rms.sketches.not_over_defined`); `warn` is `suspected`/`low`. The mapping is
  data-model section 2's table and nothing else decides it;
- **suppressed subjects.** A finding naming a suppressed feature says so in its observed
  text *and* in `coverage_limits` (`contracts/rules.md`, "Suppressed features"). The
  constructor appends both, so no rule can name a suppressed feature and stay silent
  about it.

The `Calculation` half of a finding stays `None`: an RMS rule reads a tree, it does not
compute a number, and the report layer supplies the `tool_result_ids` entry that
`build_finding` requires of a `demonstrated` finding instead (data-model section 2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from swreview.checks.result import CheckResult
from swreview.checks.rms.registry import RmsRule
from swreview.findings import FindingStatus, Severity
from swreview.ir.models import Feature

__all__ = [
    "HIGH_SEVERITY_RULES",
    "HIGH_SEVERITY_RULE_PREFIX",
    "RuleOutcome",
    "RuleResult",
    "finding",
    "passed",
    "severity_of",
    "skipped",
    "subject_input",
    "subject_reasons",
    "unresolved",
]

RuleOutcome = Literal["pass", "fail", "warn", "skip", "unresolved", "waived"]
"""The six outcomes of data-model section 2, one report bucket each."""

_WITH_RESULT: frozenset[str] = frozenset({"fail", "warn", "waived"})
_WITH_REASON: frozenset[str] = frozenset({"skip", "unresolved", "waived"})

_STATUS_BY_OUTCOME: dict[str, FindingStatus] = {
    "fail": "demonstrated",
    "warn": "suspected",
    "waived": "checked_within_scope",
}

HIGH_SEVERITY_RULE_PREFIX = "rms.refs."
HIGH_SEVERITY_RULES: frozenset[str] = frozenset({"rms.sketches.not_over_defined"})
"""The `fail` rules reported `high` rather than `medium` (data-model section 2): a
reference that points the wrong way and an over-defined sketch both break a rebuild,
where the other `fail` rules describe a tree that works but will not survive editing."""


def severity_of(rule: RmsRule) -> Severity:
    """The `Finding` severity of `rule`, from its method severity and its id."""
    if rule.severity == "warn":
        return "low"
    if rule.id.startswith(HIGH_SEVERITY_RULE_PREFIX) or rule.id in HIGH_SEVERITY_RULES:
        return "high"
    return "medium"


@dataclass(frozen=True)
class RuleResult:
    """One rule's conclusion about the subjects of one document that share an outcome.

    A rule returns a list of these - one per outcome it reached - so a rule that fails on
    two features, cannot read a third, and finds the rest in order returns three results
    and lands in three buckets of the report (`contracts/rules.md`, preamble).
    """

    rule_id: str
    document_id: str
    outcome: RuleOutcome
    subjects: list[str] = field(default_factory=list)
    """Feature, mate, or component ids sharing this outcome, in the order the rule named
    them; empty when the subject is the document itself."""

    result: CheckResult | None = None
    """The finding body, for `fail`, `warn` and `waived`; `None` otherwise."""

    reason: str | None = None
    """Why, for `skip`, `unresolved` and `waived`; the per-subject reasons joined with
    `; ` when there is more than one."""

    def __post_init__(self) -> None:
        if (self.outcome in _WITH_RESULT) != (self.result is not None):
            takes = "requires" if self.outcome in _WITH_RESULT else "takes no"
            raise ValueError(f"{self.rule_id}: outcome {self.outcome!r} {takes} a CheckResult")
        if self.outcome in _WITH_REASON and not (self.reason or "").strip():
            raise ValueError(f"{self.rule_id}: outcome {self.outcome!r} requires a reason")
        if self.outcome not in _WITH_REASON and self.reason is not None:
            raise ValueError(f"{self.rule_id}: outcome {self.outcome!r} takes no reason")
        if self.result is not None and self.result.check != self.rule_id:
            raise ValueError(
                f"{self.rule_id}: its CheckResult reports check {self.result.check!r}"
            )


def subject_input(row: Feature) -> str:
    """One subject as a finding input (data-model section 2, "Subjects to Finding fields").

    `scope` is the document the persistent reference resolves against: the document that
    owns the tree for a feature, the owning assembly for a mate.
    """
    return (
        f"{row.id} {row.name} [{row.type_name}] "
        f"persist_ref={row.persist_ref} scope={row.persist_ref_scope}"
    )


def subject_reasons(items: Sequence[tuple[Feature, str]]) -> str:
    """The per-subject reasons of one `skip` or `unresolved` result, joined with `; `."""
    return "; ".join(f"{row.id} {row.name}: {why}" for row, why in items)


def passed(rule: RmsRule, document_id: str, subjects: Sequence[Feature] = ()) -> RuleResult:
    """The subjects of `document_id` that `rule` evaluated and found compliant."""
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome="pass",
        subjects=[row.id for row in subjects],
    )


def skipped(
    rule: RmsRule, document_id: str, reason: str, subjects: Sequence[Feature] = ()
) -> RuleResult:
    """`rule` had nothing to evaluate here - no group, no shell, no second radius."""
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome="skip",
        subjects=[row.id for row in subjects],
        reason=reason,
    )


def unresolved(
    rule: RmsRule, document_id: str, reason: str, subjects: Sequence[Feature] = ()
) -> RuleResult:
    """`rule` lacked an input for these subjects; never a pass and never a fail."""
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome="unresolved",
        subjects=[row.id for row in subjects],
        reason=reason,
    )


def finding(
    rule: RmsRule,
    document_id: str,
    subjects: Sequence[Feature],
    *,
    observed: str,
    recommended_action: str,
    coverage_limits: Sequence[str] = (),
) -> RuleResult:
    """A violation of `rule`: outcome `fail` or `warn`, whichever the rule's severity is.

    `observed` states what the tree shows and `recommended_action` what to do about it;
    everything else - the requirement, the inputs, the status, the severity and the
    suppression marker - comes from `rule` and `subjects`.
    """
    if rule.severity is None:  # pragma: no cover - `bind` refuses a coverage-only rule
        raise ValueError(f"{rule.id} is coverage-only; it has no finding to report")
    suppressed = [row for row in subjects if row.suppressed]
    marks = [f"{row.name} is suppressed in {row.configuration}" for row in suppressed]
    limits = [
        *(f"{row.id} {row.name}: suppressed in {row.configuration}" for row in suppressed),
        *coverage_limits,
    ]
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome=rule.severity,
        subjects=[row.id for row in subjects],
        result=CheckResult(
            check=rule.id,
            status=_STATUS_BY_OUTCOME[rule.severity],
            severity=severity_of(rule),
            observed="; ".join([observed, *marks]),
            requirement=rule.statement,
            inputs=[subject_input(row) for row in subjects],
            calculation=None,
            coverage_limits=limits,
            recommended_action=recommended_action,
        ),
    )
