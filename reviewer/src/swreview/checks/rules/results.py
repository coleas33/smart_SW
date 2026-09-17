"""What one rule concluded about one document: `RuleResult` and its six constructors.

This module is the only place a `RuleResult` is built, so the four things every rule would
otherwise restate live here once (constitution Principle V, DRY):

- **the outcome invariant.** A `fail`, `warn` or `waived` result carries a `CheckResult`; a
  `skip`, `unresolved` or `waived` result carries a reason; a `pass` carries neither.
  `__post_init__` enforces it, so a rule that forgets its reason fails at the rule, not
  three layers later in the report;
- **the evidence format.** A subject is a feature, mate, or component id, and the string
  the finding carries in `inputs` is `<id> <name> [<type_name>] persist_ref=<ref>
  scope=<document_id>` - one per subject, in the order the rule named them;
- **severity.** A violation's status and severity come from the rule's severity read
  through its **family** (`CheckFamily.status_by_severity`), with `CheckFamily.high_severity`
  naming the checks reported `high` rather than the map's value. No id and no prefix is
  written here: a family's vocabulary is the family's, and this module knows none of them -
  it imports no family's rule type at all, which is what keeps one family from depending on
  another's names (FR-028);
- **suppressed subjects.** A finding naming a suppressed feature says so in its observed
  text *and* in `coverage_limits`. The constructor appends both, so no rule can name a
  suppressed feature and stay silent about it.

The `Calculation` half of a finding stays `None`: these rules read a model, they do not
compute a number, and the report layer supplies the `tool_result_ids` entry that
`build_finding` requires of a `demonstrated` finding instead.

**Outcome and severity are two vocabularies, not one.** `RuleOutcome` is the family-neutral
set of six report buckets; a family's severity is its own word for how hard a violation is
(`fail`/`warn`, `error`/`warning`). The bridge between them is the finding status the
family maps its severity to: a `demonstrated` violation is a `fail` outcome and a
`suspected` one a `warn`, whichever word the family used to say so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from swreview.checks.result import CheckResult
from swreview.checks.rules.family import CheckFamily
from swreview.checks.rules.registry import Rule
from swreview.findings import FindingStatus, Severity
from swreview.ir.models import Feature

__all__ = [
    "RuleOutcome",
    "RuleResult",
    "finding",
    "passed",
    "severity_of",
    "skipped",
    "subject_input",
    "subject_reasons",
    "unresolved",
    "verdict",
]

RuleOutcome = Literal["pass", "fail", "warn", "skip", "unresolved", "waived"]
"""The six outcomes, one report bucket each. Family-neutral: a family's severity vocabulary
does not add a seventh, it maps onto these."""

_WITH_RESULT: frozenset[str] = frozenset({"fail", "warn", "waived"})
_WITH_REASON: frozenset[str] = frozenset({"skip", "unresolved", "waived"})

_OUTCOME_BY_STATUS: dict[FindingStatus, RuleOutcome] = {
    "demonstrated": "fail",
    "suspected": "warn",
    "checked_within_scope": "waived",
}
"""Which bucket a violation lands in, read from the finding status its family gives it.

This is the one place outcome and severity meet, and it is a fact about the result model
rather than about any family: a demonstrated violation failed, a suspected one is a warning,
and a waived one has been accepted. A family that called its severities `error` and
`warning` lands in exactly the same six buckets as one that called them `fail` and `warn`.
"""


def severity_of(family: CheckFamily, rule: Rule) -> Severity:
    """The `Finding` severity of `rule`: its family's map, overridden for a high check."""
    _, severity = _status_and_severity(family, rule)
    return severity


def _status_and_severity(family: CheckFamily, rule: Rule) -> tuple[FindingStatus, Severity]:
    """`rule`'s finding status and severity, or `ValueError` naming what is missing."""
    if rule.severity is None:  # pragma: no cover - `bind` refuses a coverage-only rule
        raise ValueError(f"{rule.id} is coverage-only; it has no finding to report")
    try:
        status, severity = family.status_by_severity[rule.severity]
    except KeyError:
        raise ValueError(
            f"{rule.id}: severity {rule.severity!r} is not one of the {family.name} "
            f"family's ({', '.join(sorted(family.severities))})"
        ) from None
    if status == "demonstrated" and rule.id in family.high_severity:
        return status, "high"
    return status, severity


@dataclass(frozen=True)
class RuleResult:
    """One rule's conclusion about the subjects of one document that share an outcome.

    A rule returns a list of these - one per outcome it reached - so a rule that fails on
    two features, cannot read a third, and finds the rest in order returns three results
    and lands in three buckets of the report.
    """

    rule_id: str
    document_id: str
    outcome: RuleOutcome
    subjects: list[str] = field(default_factory=list)
    """Feature, mate, or component ids sharing this outcome, in the order the rule named
    them; empty when the subject is the document itself."""

    subject_rows: tuple[Feature, ...] = ()
    """The rows behind `subjects`, in the same order, when a rule named any.

    `subjects` is what a rule result *says*; these are what it said it about, kept so the
    report layer can emit each subject a second time as a `SourceRef` and as a structured
    entry without looking a display string back up or re-finding the row in the package.
    Annotated `Feature` for a structural reason rather than a nominal one: a mate, a
    component instance and a drawing annotation are subjects too, and each is presented in
    the same seven attributes. Empty when a result was built without rows - the subject is
    then the document itself.
    """

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
    """One subject as a finding input.

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


def passed(rule: Rule, document_id: str, subjects: Sequence[Feature] = ()) -> RuleResult:
    """The subjects of `document_id` that `rule` evaluated and found compliant."""
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome="pass",
        subjects=[row.id for row in subjects],
        subject_rows=tuple(subjects),
    )


def skipped(
    rule: Rule, document_id: str, reason: str, subjects: Sequence[Feature] = ()
) -> RuleResult:
    """`rule` had nothing to evaluate here - no group, no shell, no second radius."""
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome="skip",
        subjects=[row.id for row in subjects],
        subject_rows=tuple(subjects),
        reason=reason,
    )


def unresolved(
    rule: Rule, document_id: str, reason: str, subjects: Sequence[Feature] = ()
) -> RuleResult:
    """`rule` lacked an input for these subjects; never a pass and never a fail."""
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome="unresolved",
        subjects=[row.id for row in subjects],
        subject_rows=tuple(subjects),
        reason=reason,
    )


def verdict(
    rule: Rule,
    document_id: str,
    *,
    violation: RuleResult | None = None,
    passing: Sequence[Feature] = (),
    unknown: Sequence[tuple[Feature, str]] = (),
) -> list[RuleResult]:
    """The outcomes of a per-subject rule: at most one verdict, plus the unresolved half.

    Every rule that grades subjects one at a time ends this way, so it is written once
    here rather than once per evaluator module (constitution Principle V). Three branches:

    - a violation *replaces* the pass - a rule that failed on this document is not also
      `checked` for it;
    - a rule whose every subject was unresolved reports only that, with no vacuous pass
      beside it, while a rule with nothing to look at at all passes vacuously;
    - the unresolved half is one result carrying every subject the rule lacked an input
      for, with the per-subject reasons joined the way `subject_reasons` joins them.

    `passing` and `unknown` are annotated `Feature` for the same structural reason
    `RuleResult.subject_rows` is.
    """
    results: list[RuleResult] = []
    if violation is not None:
        results.append(violation)
    elif passing or not unknown:
        results.append(passed(rule, document_id, passing))
    if unknown:
        results.append(
            unresolved(
                rule,
                document_id,
                subject_reasons(unknown),
                [subject for subject, _ in unknown],
            )
        )
    return results


def finding(
    family: CheckFamily,
    rule: Rule,
    document_id: str,
    subjects: Sequence[Feature],
    *,
    observed: str,
    recommended_action: str,
    coverage_limits: Sequence[str] = (),
) -> RuleResult:
    """A violation of `rule`, in the bucket its family's severity maps it to.

    `observed` states what the model shows and `recommended_action` what to do about it;
    everything else - the requirement, the inputs, the status, the severity and the
    suppression marker - comes from `family`, `rule` and `subjects`.
    """
    status, severity = _status_and_severity(family, rule)
    suppressed = [row for row in subjects if row.suppressed]
    marks = [f"{row.name} is suppressed in {row.configuration}" for row in suppressed]
    limits = [
        *(f"{row.id} {row.name}: suppressed in {row.configuration}" for row in suppressed),
        *coverage_limits,
    ]
    return RuleResult(
        rule_id=rule.id,
        document_id=document_id,
        outcome=_OUTCOME_BY_STATUS[status],
        subjects=[row.id for row in subjects],
        subject_rows=tuple(subjects),
        result=CheckResult(
            check=rule.id,
            status=status,
            severity=severity,
            observed="; ".join([observed, *marks]),
            requirement=rule.statement,
            inputs=[subject_input(row) for row in subjects],
            calculation=None,
            coverage_limits=limits,
            recommended_action=recommended_action,
        ),
    )
