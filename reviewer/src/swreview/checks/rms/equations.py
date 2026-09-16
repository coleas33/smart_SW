"""Equation-scope rule evaluators, per part document.

**Placeholder: T040 replaces this module.** `contracts/rules.md` grades 2 equation rules
and `registry.py` already names both; T040 writes one pure function per rule, each
decorated `@bind("<rule id>")` and returning `list[RuleResult]`.

Until then both ids are bound to a stub, so the registry invariant - a function exactly
where there is a severity - holds from the first import rather than only once the real
evaluators land.
"""

from __future__ import annotations

from typing import Any, NoReturn

from swreview.checks.rms.registry import bind, evaluable

SCOPE = "equations"


def _not_implemented(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise NotImplementedError("implemented in T040")


for _rule in evaluable():
    if _rule.scope == SCOPE:
        bind(_rule.id)(_not_implemented)
