"""`CheckFamily`: what one family of rules is, as facts rather than as a base class.

A **check family** is a catalogue of rules, an evaluation entry point and a report layer.
Feature 003 shipped one of them (the Resilient Modeling rules) and hard-coded four things
about itself into the machinery around it: the summary check id, the rule-scope vocabulary,
the catalogue version, and the severity vocabulary with its map to a `Finding` status and
severity. A second family over the same machinery makes all four **data**, and this is
where that data lives.

The descriptor is a frozen dataclass with no behaviour. A family is a list of facts, not a
base class with hooks: there is nothing here to override and no method to call, which is
what keeps "which family is this?" a question about values rather than about types. The two
callables the report layer needs - the per-family subject decorator and the extra-coverage
steps - are supplied by the family **module** at the call (`checks/rules/report.py`), not
carried here, so the descriptor stays data.

The catalogue itself is deliberately **not** a field: the rules are a family's own module
and are passed to the neutral layer at the call, so a descriptor can be read, compared and
written down without importing a catalogue.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from swreview.checks.rules.registry import Rule
from swreview.findings import FindingStatus, Severity

__all__ = ["WAIVABLE_STATUS", "CheckFamily", "waiver_invalidity"]

WAIVABLE_STATUS: FindingStatus = "demonstrated"
"""The one finding status an acceptance may waive, in every family.

A waiver is an engineer accepting a condition the reviewer **demonstrated**; a `suspected`
finding is advisory and there is nothing yet to accept. So "which severities are waivable"
is not a fifth fact to carry - it is `status_by_severity` read for this status, which is
why `fail` is waivable for the rms family and `error` for the standards one without either
of them saying so twice (`specs/006-standards-check/contracts/cli.md`).
"""


@dataclass(frozen=True)
class CheckFamily:
    """The facts that differ between one family of checks and another."""

    name: str
    """`"rms"`, `"standards"`: the family in prose, in a log line and in an error."""

    summary_check: str
    """The one aggregated coverage item that is the family's verdict for a run, and is not
    one of its checks - `"modeling.resilience"` for the rms rules. It is written once per
    call from everything the session holds, so several tools of one family accumulate into
    one answer rather than overwriting each other's."""

    rules_version: str
    """The catalogue's own version: the family's `Calculation.function_version` stand-in.

    Bumped whenever a rule's verdict over an unchanged model could change, because a
    verdict carried over from an earlier run is a claim that *this* implementation would
    conclude the same thing."""

    scopes: frozenset[str]
    """What a rule of this family can be evaluated over - the rule-scope vocabulary. A
    rule's `scope` is one of these, and the set is closed: a scope the family does not have
    is a rule that was never written, not a rule that never runs."""

    tools: Mapping[str, str]
    """The curated tool each scope is dispatched as, keyed by scope.

    Fewer keys than `scopes`: a scope with no tool is in the catalogue and is not
    dispatched by this build, which is reported rather than silently skipped. The tool is
    the unit of dispatch and not the function, because the step recorded for it is what
    every finding of that scope cites."""

    check_file_family: str
    """The value written into a run folder's `check.json` as its `family`, which is how a
    backend handed a folder knows whose check it is holding."""

    severities: frozenset[str]
    """The family's own severity vocabulary: `{"fail", "warn"}` for the rms rules,
    `{"error", "warning"}` for the standards checks. The two families do not share one, so
    a rule's severity says nothing until it is read through this family."""

    status_by_severity: Mapping[str, tuple[FindingStatus, Severity]]
    """Each severity as a `Finding` status and severity. Every severity is a key, and
    `high_severity` is the one thing that overrides the severity half."""

    high_severity: frozenset[str]
    """The check ids this family reports `high` rather than the severity map's value.

    An id set rather than a predicate: every family's answer so far is a handful of named
    checks, and a set can be read, printed and asserted, where a predicate can only be
    called."""

    waiver_labels: Mapping[str, str]
    """Why a listed check id cannot be waived, as the line a waiver import prints.

    Keyed by the reason: `"unknown"` for an id that is not a check of this family at all,
    the family's own **severity** name for a check whose severity is not waivable, and the
    **coverage bucket** for a catalogue whose rules can be coverage-only. The labels are
    printed verbatim, so they are a fact about the family and not a constant in the command
    that prints them (`specs/006-standards-check/contracts/cli.md`)."""

    def __post_init__(self) -> None:
        unmapped = self.severities.symmetric_difference(self.status_by_severity)
        if unmapped:
            raise ValueError(
                f"{self.name}: every severity is mapped to a finding status and severity, "
                f"and nothing else is; {', '.join(sorted(unmapped))} is not"
            )
        strays = set(self.tools) - self.scopes
        if strays:
            raise ValueError(
                f"{self.name}: a tool is dispatched for a scope the family has; "
                f"{', '.join(sorted(strays))} is not one of {sorted(self.scopes)}"
            )
        if "unknown" not in self.waiver_labels:
            raise ValueError(
                f"{self.name}: waiver_labels needs an 'unknown' label, because an id a "
                f"waiver file lists and the catalogue does not hold has to be reported"
            )
        unlabelled = sorted(
            severity
            for severity, (status, _) in self.status_by_severity.items()
            if status != WAIVABLE_STATUS and severity not in self.waiver_labels
        )
        if unlabelled:
            raise ValueError(
                f"{self.name}: a severity that cannot be waived is refused by name, so "
                f"{', '.join(unlabelled)} needs a waiver_labels entry"
            )


def waiver_invalidity(
    family: CheckFamily, rules: Mapping[str, Rule], check_id: str
) -> str | None:
    """Why a waiver naming `check_id` is invalid in `family`, or `None` when it is waivable.

    One reader for every family, because "may this be waived, and what does the refusal
    say" is `waiver_labels` read with `status_by_severity` - two facts already on the
    descriptor - and a second copy of it in the command line or in a route is exactly how
    the tab and `swreview exceptions accept-<family>` would come to disagree about one
    waiver (FR-042, `specs/006-standards-check/contracts/cli.md`).

    Three answers, in this order:

    1. an id the catalogue does not hold at all is the `"unknown"` label;
    2. an evaluable rule whose severity maps to `WAIVABLE_STATUS` is waivable: `None`;
    3. anything else is refused **by its own name** - its severity when it has one, its
       coverage bucket when it is coverage-only - so a rule refused because the data it
       needs is not extracted is not reported as a warning the reader could argue with.
    """
    rule = rules.get(check_id)
    if rule is None:
        return family.waiver_labels["unknown"]
    if (
        rule.severity is not None
        and family.status_by_severity[rule.severity][0] == WAIVABLE_STATUS
    ):
        return None
    key = rule.severity if rule.coverage is None else rule.coverage[0]
    return family.waiver_labels[str(key)]
