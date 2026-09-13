"""Deterministic checks: pure functions over the IR (plan.md Phase 1, design point 2).

Each check takes IR entities and returns a `swreview.checks.result.CheckResult`. No
check reads a file, calls the network or builds a `Finding`; the tool layer does that.
"""
