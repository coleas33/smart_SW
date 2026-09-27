"""A derived or mirrored part is refused, with a reason that is true (T146, decision 17A).

A mirrored part (`MirrorStock`, which one of the real packages is) or a derived part
(`Stock`, Insert Part's base feature) gets its body whole from another part file. The six
groups organize the features that build a body, and this part has none: the planner used to
report the base feature `unclassified`, leave the rest of the tree as it was, and plan folder
changes around it, which reads as a part that could be reorganized.

The refusal is a **tree** code, `derived_part`: decided from the package's feature rows,
after the copy, the way the cycle refusal is. T161 adds the probe's reading,
`feature_type_names`, from which the scope gate reaches the same code before the copy;
the planner keeps its own reading, because a dry run has no probe and after the copy it
is a backstop (tasks.md, lane F's default 4). What is pinned here:

- the plan over such a part is `failed`, carries no change, and names the refusal - its
  code, the feature, and the reason - in `tree_refusals`, in `plan_refusals` and in the
  sentence that says why the change list is empty;
- a scope verdict of `ok` does not rescue it, and a part without a derived base is not
  refused for one;
- `RemodelPlan` takes only tree codes in `tree_refusals`, and a plan that carries one is
  never `planned`;
- when the probe's walk carries the base feature too, the gate refuses the part and the
  planner still names its own reading, each under its own signal; a dry run leaves the
  probe's half unresolved and is refused by the planner's.
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
    probe_type_names,
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


# --- the probe half (T161; lane F's defaults 3 to 5) -----------------------------------------


def probed() -> ScopeSignals:
    """What the probe reads of the mirrored part: its own walk, every other signal in scope."""
    walk = probe_type_names(derived_part_features())
    return ScopeSignals(**scope_signals(feature_type_names=walk))


def test_a_probe_that_reads_the_base_feature_refuses_the_part_at_the_scope_gate() -> None:
    result = plan(derived(), signals=probed(), probe_id="probe:1")

    assert result.scope.verdict == "refused"
    (refusal,) = result.scope.refusals
    assert refusal.code == DERIVED_PART
    assert refusal.signal == "feature_type_names"
    assert "MirrorStock" in refusal.message
    assert result.state == "failed"
    assert result.changes == ()


def test_both_readings_are_named_each_under_its_own_signal() -> None:
    """Every failing reading is reported: the probe's, before the copy, and the planner's,
    from the package. A real run never gets this far with the first - the host refuses at
    the probe - so this is what an offline plan over both readings says."""
    package = derived()
    result = plan(package, signals=probed(), probe_id="probe:1")

    derived_rows = [row for row in plan_refusals(result) if row["code"] == DERIVED_PART]
    assert [row["signal"] for row in derived_rows] == ["feature_type_names", "features[].type_name"]
    assert base_id(package) in derived_rows[1]["message"]
    assert [refusal.code for refusal in result.tree_refusals] == [DERIVED_PART]


def test_the_why_sentence_names_the_scope_gate_when_the_probe_refused() -> None:
    result = plan(derived(), signals=probed(), probe_id="probe:1")
    (changes,) = [item for item in result.coverage if item.item == "changes"]

    assert "the scope gate refused this part" in changes.reason
    assert "MirrorStock" in changes.reason


def test_a_dry_run_leaves_the_probe_half_unresolved_and_the_planner_refuses() -> None:
    """The dry run reads no signal, and the type names are never synthesised from the
    package (lane F's default 5): the gate says the question is unresolved and the
    planner's reading is what refuses the part."""
    result = plan(derived())

    assert result.scope.verdict == "unresolved"
    assert result.scope.signals_probe.feature_type_names is None
    unresolved = [r for r in result.scope.refusals if r.signal == "feature_type_names"]
    assert [refusal.code for refusal in unresolved] == ["signal_unresolved"]
    assert [row["signal"] for row in plan_refusals(result) if row["code"] == DERIVED_PART] == [
        "features[].type_name"
    ]
