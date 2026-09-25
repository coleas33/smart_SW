"""A derived or mirrored part is refused, with a reason that is true (T146, decision 17A).

A mirrored part (`MirrorStock`, which one of the real packages is) or a derived part
(`Stock`, Insert Part's base feature) gets its body whole from another part file. The six
groups organize the features that build a body, and this part has none: the planner used to
report the base feature `unclassified`, leave the rest of the tree as it was, and plan folder
changes around it, which reads as a part that could be reorganized.

The refusal is a **tree** code, `derived_part`: decided from the package's feature rows,
after the copy, the way the cycle refusal is, because no scope signal carries the tree yet.
T161 adds the probe's reading, which moves it before the copy. What is pinned here:

- the plan over such a part is `failed`, carries no change, and names the refusal - its
  code, the feature, and the reason - in `tree_refusals`, in `plan_refusals` and in the
  sentence that says why the change list is empty;
- a scope verdict of `ok` does not rescue it, and a part without a derived base is not
  refused for one;
- `RemodelPlan` takes only tree codes in `tree_refusals`, and a plan that carries one is
  never `planned`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage
from swreview.remodel.plan import RemodelPlan, plan_reorganize, require_runnable_plan
from swreview.remodel.scope import DERIVED_PART, Refusal, ScopeSignals
from swreview.remodel.summary import plan_lines, plan_refusals, plan_summary_row
from tests.support.remodel import (
    dependency_chain_features,
    derived_part_features,
    remodel_package,
    scope_signals,
)

TABLE = load_table()
AT = datetime(2026, 9, 25, 9, 0, 0, tzinfo=UTC)


def derived() -> EvidencePackage:
    return remodel_package(derived_part_features())


def plan(package: EvidencePackage, **kwargs: object) -> RemodelPlan:
    return plan_reorganize(package, now=AT, **kwargs)  # type: ignore[arg-type]


def base_id(package: EvidencePackage) -> str:
    (row,) = [row for row in package.features if row.type_name == "MirrorStock"]
    return row.id


def test_a_mirrored_part_is_refused_and_plans_no_change() -> None:
    package = derived()
    result = plan(package)

    assert result.state == "failed"
    assert result.changes == ()
    (refusal,) = result.tree_refusals
    assert refusal.code == DERIVED_PART
    assert base_id(package) in refusal.message


def test_the_reason_says_why_the_six_groups_cannot_organize_it() -> None:
    (refusal,) = plan(derived()).tree_refusals

    assert "another part" in refusal.message
    assert "six groups" in refusal.message


def test_the_changes_coverage_says_the_part_was_refused_for_its_base_feature() -> None:
    result = plan(derived())
    (changes,) = [item for item in result.coverage if item.item == "changes"]

    assert "no change is planned" in changes.reason
    assert DERIVED_PART in changes.reason or "derived or mirrored" in changes.reason
    assert "nothing refused" not in changes.reason


def test_the_refusal_is_listed_with_every_other_refusal() -> None:
    package = derived()
    result = plan(package)

    refusals = plan_refusals(result)
    assert refusals[-1]["code"] == DERIVED_PART
    assert base_id(package) in refusals[-1]["message"]
    document = package.documents[0]
    lines = plan_lines(plan_summary_row(result, document, TABLE))
    assert any(line.strip().startswith(f"refused {DERIVED_PART}") for line in lines)


def test_an_ok_scope_does_not_rescue_a_derived_part() -> None:
    result = plan(derived(), signals=ScopeSignals(**scope_signals()), probe_id="probe:1")

    assert result.scope.verdict == "ok"
    assert result.state == "failed"
    assert [refusal.code for refusal in result.tree_refusals] == [DERIVED_PART]


def test_a_refused_plan_can_never_enter_the_mutation_phases() -> None:
    result = plan(derived(), signals=ScopeSignals(**scope_signals()), probe_id="probe:1")

    with pytest.raises(ValueError, match="failed"):
        require_runnable_plan(result)


def test_a_part_without_a_derived_base_is_not_refused_for_one() -> None:
    result = plan(remodel_package(dependency_chain_features()))

    assert result.tree_refusals == ()
    assert result.state == "planned"


def test_the_plan_type_takes_only_tree_codes_in_tree_refusals() -> None:
    result = plan(remodel_package(dependency_chain_features()))
    gate_code = Refusal(code="weldment", message="is_weldment is true", signal="is_weldment")

    with pytest.raises(ValidationError, match="tree"):
        RemodelPlan(**{**dict(result), "tree_refusals": (gate_code,)})


def test_a_plan_carrying_a_tree_refusal_is_never_planned() -> None:
    result = plan(derived())

    with pytest.raises(ValidationError, match="planned"):
        RemodelPlan(**{**dict(result), "state": "planned"})
