"""The RMS family's `RuleResult` constructors: `checks/rules/results.py`, bound to it.

What one rule concluded about one document is the same shape in every family, so the type,
the outcome invariant, the evidence format and the six constructors live in
`checks/rules/results.py` and are imported here. Two of them need to know whose rules these
are - `finding`, which turns a rule's severity into a `Finding` status and severity, and
`severity_of`, which answers the severity half alone - and this module is where they are
bound to `RMS_FAMILY` so that an evaluator calls them with a rule and nothing else.

Read `checks/rules/results.py` for what the constructors do; what is here is which family
they are doing it for.
"""

from __future__ import annotations

from collections.abc import Sequence

from swreview.checks.rms.registry import (
    HIGH_SEVERITY_RULE_PREFIX,
    HIGH_SEVERITY_RULES,
    RMS_FAMILY,
    RmsRule,
)
from swreview.checks.rules.results import (
    RuleOutcome,
    RuleResult,
    passed,
    skipped,
    subject_input,
    subject_reasons,
    unresolved,
    verdict,
)
from swreview.checks.rules.results import finding as _finding
from swreview.checks.rules.results import severity_of as _severity_of
from swreview.findings import Severity
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
    "verdict",
]


def severity_of(rule: RmsRule) -> Severity:
    """The `Finding` severity of `rule`, from its method severity and its id."""
    return _severity_of(RMS_FAMILY, rule)


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
    return _finding(
        RMS_FAMILY,
        rule,
        document_id,
        subjects,
        observed=observed,
        recommended_action=recommended_action,
        coverage_limits=coverage_limits,
    )
