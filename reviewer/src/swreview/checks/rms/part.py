"""Part-scope rule evaluators.

**Placeholder: T020 replaces this module.** `contracts/rules.md` grades 18 part rules and
`registry.py` already names every one of them; T020 writes one pure function per rule,
each decorated `@bind("<rule id>")` and returning `list[RuleResult]`, plus
`evaluate_part(document_id, features, table, assignment, package)`.

Until then each of those ids is bound to a stub, so the registry invariant - a function
exactly where there is a severity - holds from the first import rather than only once the
real evaluators land.
"""

from __future__ import annotations

from typing import Any, NoReturn

from swreview.checks.rms.registry import bind, evaluable

SCOPE = "part"


def _not_implemented(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise NotImplementedError("implemented in T020")


for _rule in evaluable():
    if _rule.scope == SCOPE:
        bind(_rule.id)(_not_implemented)
