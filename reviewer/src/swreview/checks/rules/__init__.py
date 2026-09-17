"""The family-neutral half of a check family: rules, results, report, run folder.

A **check family** is a catalogue of rules with an evaluation entry point and a report
layer. `checks/rms/` is one; `checks/standards/` is another. What differs between them is
their catalogue, their evaluators and a handful of facts (`family.CheckFamily`); what is
identical is everything around those - what a rule row looks like, what one rule concluded
about one document, how a conclusion becomes a `Finding` or a `CoverageItem`, and how a run
folder is written and read back.

This package is that identical half, extracted from feature 003's `checks/rms/` rather than
copied out of it (constitution Principle V, FR-028). It names no family: a module here that
imported one family's rule type would make the other family depend on it through the back
door, which is the dependency the design rejects. The family arrives as an argument.

Read the pieces in this order:

- `family.py` - `CheckFamily`, the facts that differ, as a frozen dataclass;
- `registry.py` - `Rule`, and the five things every catalogue needs done to it;
- `results.py` - `RuleResult` and its six constructors: what one rule concluded;
- `report.py` - `report_results`: results become session findings and coverage;
- `run.py` - the run folder: the carry-forward, the recorded call, `check.json`.
"""

from __future__ import annotations

from swreview.checks.rules.family import CheckFamily
from swreview.checks.rules.registry import (
    Rule,
    RuleCoverageBucket,
    RuleFn,
    binder,
    by_scope,
    catalogue,
    coverage_only,
    evaluable,
)
from swreview.checks.rules.results import (
    RuleOutcome,
    RuleResult,
    finding,
    passed,
    severity_of,
    skipped,
    subject_input,
    subject_reasons,
    unresolved,
    verdict,
)

__all__ = [
    "CheckFamily",
    "Rule",
    "RuleCoverageBucket",
    "RuleFn",
    "RuleOutcome",
    "RuleResult",
    "binder",
    "by_scope",
    "catalogue",
    "coverage_only",
    "evaluable",
    "finding",
    "passed",
    "severity_of",
    "skipped",
    "subject_input",
    "subject_reasons",
    "unresolved",
    "verdict",
]
