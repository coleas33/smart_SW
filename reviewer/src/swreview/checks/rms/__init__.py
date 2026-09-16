"""Resilient Modeling Strategy checks: the rule catalogue and its evaluators.

`registry.py` holds the 34 rules of `specs/003-resilient-modeling/contracts/rules.md`;
`part.py`, `assembly.py` and `equations.py` bind an evaluator to each of the 24 the
contract grades, and the remaining 10 are coverage-only. Importing this package is what
makes the registry complete, so every caller reads the rules through
`swreview.checks.rms` and never through `registry` alone.

The evaluator modules themselves import `bind` from `swreview.checks.rms.registry`
directly: they run while this module is still executing, so its names are not there yet.
"""

from __future__ import annotations

from swreview.checks.rms import assembly, equations, part  # noqa: F401  (binds on import)
from swreview.checks.rms.registry import (
    RULES,
    CoverageBucket,
    RmsRule,
    RuleFn,
    RuleScope,
    RuleSeverity,
    by_scope,
    coverage_only,
    evaluable,
)

__all__ = [
    "RULES",
    "CoverageBucket",
    "RmsRule",
    "RuleFn",
    "RuleScope",
    "RuleSeverity",
    "by_scope",
    "coverage_only",
    "evaluable",
]
