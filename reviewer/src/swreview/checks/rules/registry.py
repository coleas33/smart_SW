"""What a rule *is*, and the five things every catalogue of rules needs done to it.

A family's catalogue - which rules exist, in which order, with which statements - is the
family's own module and stays there. What is here is the shape of a row and the five
operations no catalogue should write twice: build the keyed catalogue, bind an evaluator,
partition by scope, and name the two halves of the catalogue (`evaluable`,
`coverage_only`).

Two kinds of rule live in any catalogue and the difference is one invariant:

- an **evaluable** rule carries a `severity` from its family's vocabulary and an evaluator
  bound by the family's evaluator modules; it is dispatched per subject document and
  returns one `RuleResult` per outcome it reaches;
- a **coverage-only** rule carries a `(bucket, reason)` pair instead, and no severity and
  no function: the data it needs is not extracted, or the judgement is not decidable from
  extracted data. It is never dispatched and is emitted once per review as a `CoverageItem`
  in that bucket, so a reader sees that the rule was not silently dropped.

`fn` is present exactly when `severity` is present exactly when `coverage` is null. The
severity half of that invariant is enforced on construction; the `fn` half is completed by
the binder a family builds with `binder()`.

`scope` and `severity` are plain strings here and a closed `Literal` in each family's own
module: the vocabularies are per family (`CheckFamily.scopes`, `CheckFamily.severities`)
and there is no union of them that means anything.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

from swreview.report.session import CoverageBucket

__all__ = [
    "Rule",
    "RuleCoverageBucket",
    "RuleFn",
    "binder",
    "by_scope",
    "catalogue",
    "coverage_only",
    "evaluable",
]

RuleCoverageBucket = Literal["unresolved", "out_of_scope"]
"""The two `swreview.report.session.CoverageBucket` values a coverage-only rule can land
in: `unresolved` when the data is simply not extracted yet, `out_of_scope` when this
version has decided not to decide. Named apart from the session's wider alias so that a
reader of `Rule.coverage` cannot mistake it for the full set of report buckets."""

assert set(get_args(RuleCoverageBucket)) <= set(get_args(CoverageBucket)), (
    "a coverage-only rule is emitted as a CoverageItem in its bucket, so every "
    "RuleCoverageBucket must be a swreview.report.session.CoverageBucket"
)

RuleFn = Callable[..., Any]
"""An evaluator. The argument list differs by scope - part rules read a document's
features and its group assignment, assembly rules read the package - so the alias pins
only that it is callable; every one of them returns `list[RuleResult]`."""


@dataclass
class Rule:
    """One rule of one family's contract.

    Mutable in exactly one respect: `fn` is filled in by a binder after construction,
    because the evaluator modules import the catalogue and not the other way round.
    """

    id: str
    scope: str
    statement: str
    severity: str | None = None
    coverage: tuple[RuleCoverageBucket, str] | None = None
    fn: RuleFn | None = None

    def __post_init__(self) -> None:
        if (self.severity is None) == (self.coverage is None):
            raise ValueError(
                f"{self.id}: a rule carries either a severity or a coverage reason, "
                f"never both and never neither (severity={self.severity!r}, "
                f"coverage={self.coverage!r})"
            )
        if not self.statement.strip():
            raise ValueError(f"{self.id}: a rule needs a statement to report as its requirement")


def catalogue(*rules: Rule) -> dict[str, Rule]:
    """Key the rules by id, refusing a duplicate rather than silently keeping one."""
    by_id: dict[str, Rule] = {}
    for rule in rules:
        if rule.id in by_id:
            raise ValueError(f"{rule.id} is registered twice")
        by_id[rule.id] = rule
    return by_id


def binder(rules: Mapping[str, Rule], contract: str) -> Callable[[str], Callable[[RuleFn], RuleFn]]:
    """A family's `bind` decorator over `rules`, naming `contract` when an id is unknown.

    Bound late rather than passed to `Rule` so that the evaluator modules import the
    catalogue and not the reverse; importing the family package, which imports all of its
    evaluator modules, is what completes the invariant.

    The returned decorator raises `KeyError` for an unknown id, and `ValueError` for a
    coverage-only rule (which is never dispatched) or a rule that already has an evaluator.
    """

    def bind(rule_id: str) -> Callable[[RuleFn], RuleFn]:
        def register(fn: RuleFn) -> RuleFn:
            try:
                rule = rules[rule_id]
            except KeyError:
                raise KeyError(f"{rule_id} is not a rule of {contract}") from None
            if rule.severity is None:
                raise ValueError(
                    f"{rule_id} is coverage-only ({rule.coverage}); it is never dispatched "
                    f"and takes no evaluator"
                )
            if rule.fn is not None:
                raise ValueError(f"{rule_id} already has an evaluator: {rule.fn!r}")
            rule.fn = fn
            return fn

        return register

    return bind


def by_scope(rules: Mapping[str, Rule], scopes: frozenset[str]) -> dict[str, tuple[Rule, ...]]:
    """`rules` partitioned by scope, in catalogue order; every scope of `scopes` is a key.

    Every scope is a key even when no rule has it, so a reader of the partition sees the
    family's whole vocabulary and not only the parts of it that are populated. Keys are in
    sorted order, because a `frozenset` has none of its own and a partition that came back
    differently ordered on two runs would be a needless source of diff.
    """
    groups: dict[str, list[Rule]] = {scope: [] for scope in sorted(scopes)}
    for rule in rules.values():
        groups[rule.scope].append(rule)
    return {scope: tuple(found) for scope, found in groups.items()}


def evaluable(rules: Mapping[str, Rule]) -> tuple[Rule, ...]:
    """The rules that are dispatched, in catalogue order.

    Read from `coverage`, not from `fn`, so that an evaluator module can ask which ids it
    owes a function while it is still binding them.
    """
    return tuple(rule for rule in rules.values() if rule.coverage is None)


def coverage_only(rules: Mapping[str, Rule]) -> tuple[Rule, ...]:
    """The rules that are never dispatched and are emitted as coverage, in catalogue order."""
    return tuple(rule for rule in rules.values() if rule.coverage is not None)
