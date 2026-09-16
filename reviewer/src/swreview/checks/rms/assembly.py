"""Assembly-scope rule evaluators, for the root assembly document only.

**Placeholder: T033 replaces this module.** `contracts/rules.md` grades 4 of the 8
assembly rules - the other 4 are coverage-only data gaps the registry never dispatches -
and T033 writes `MateGraph` and `evaluate_assembly(package, table)` with one pure function
per graded rule, each decorated `@bind("<rule id>")` and returning `list[RuleResult]`.

Until then each graded id is bound to a stub, so the registry invariant - a function
exactly where there is a severity - holds from the first import rather than only once the
real evaluators land.
"""

from __future__ import annotations

from typing import Any, NoReturn

from swreview.checks.rms.registry import bind, evaluable

SCOPE = "assembly"


def _not_implemented(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise NotImplementedError("implemented in T033")


for _rule in evaluable():
    if _rule.scope == SCOPE:
        bind(_rule.id)(_not_implemented)
