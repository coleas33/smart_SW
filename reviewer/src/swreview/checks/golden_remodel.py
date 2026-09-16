"""Golden-harness adapter for the re-modeler's plans (T030).

`tests/golden/test_golden.py` hands a loaded `EvidencePackage` to the callable a fixture's
`case.json` names, with that file's `kwargs`. `plan_case` is the re-modeler's: it runs the
**real** `plan_reorganize`, the same call `swreview remodel plan` makes, so a baseline pins
what the dry run would actually print - every target with the basis that chose it, the
ranks, the achievable order and its edit script, the pins with their blocking edge, the
rebuild list with a reason each, the folder actions and refusals, the deviations and the
coverage - and a planner whose verdict, wording or reason id moves shows up as a diff
rather than as a quietly different plan.

Two arguments beyond the package, both from `case.json`:

- `signals` is the `ScopeSignals` payload `remodel.probe_scope` would have read from the
  engineer's open document. It is how a fixture expresses a refusal a *package* cannot
  carry: multibody, weldment, sheet metal, mesh and graphics bodies and 3D Interconnect are
  COM readings and appear in no dump. Omitted, it is the dry run's own answer - every
  signal unread, the gate `unresolved`, each unread signal named - which is what the
  command itself does;
- `document_id` names the part when a fixture's package carries more than one.

The plan is stamped at one fixed instant. `created_at` and `updated_at` are the only two
fields of a pure plan that are not a function of the package, and a baseline that changed
every time it was regenerated would be a baseline nobody could read a diff of.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from swreview.ir.models import EvidencePackage
from swreview.remodel.plan import RemodelPlan, plan_reorganize
from swreview.remodel.scope import ScopeSignals

__all__ = ["PLANNED_AT", "plan_case"]

PLANNED_AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
"""The instant every golden plan is stamped with, so a baseline is a function of the
package and the type table and of nothing else."""


def plan_case(
    package: EvidencePackage,
    signals: Mapping[str, Any] | None = None,
    document_id: str | None = None,
    probe_id: str | None = None,
) -> RemodelPlan:
    """The revision-1 plan for one part of `package`, as the dry run produces it."""
    return plan_reorganize(
        package,
        document_id=document_id,
        signals=None if signals is None else _signals(signals),
        probe_id=probe_id,
        now=PLANNED_AT,
    )


def _signals(signals: Mapping[str, Any]) -> ScopeSignals:
    """The case file's signals payload as the model.

    Validated in JSON mode because that is what it is - a JSON object out of `case.json` -
    and because that is also how a signals payload arrives from the bridge, so a fixture
    cannot express a shape the real path would reject.
    """
    return ScopeSignals.model_validate_json(json.dumps(dict(signals)))
