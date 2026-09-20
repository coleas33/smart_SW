"""Run-entry refusals happen before a provider, seat, or after-dump is touched.

These tests exercise the same ``run_remodel`` entry used by the chat worker.  The plan and
tolerance checks are deliberately tested with a bridge whose call log starts empty: a
refusal here must leave the copy and its artifacts alone, even when a caller bypasses the
HTTP route's earlier state check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.remodel import runner
from swreview.remodel.geometry import reading_from_reply
from swreview.remodel.scope import WHICH_CONFIGS_THIS
from swreview.remodel.tolerances import EQUIVALENCE, IDENTITY, UncalibratedProfileError
from tests.support.remodel_bridge import StepClock
from tests.unit.test_remodel_runner import (
    AT,
    CALIBRATED,
    PACKAGE,
    UNIT,
    attestation,
    bridge_for,
    planned,
    reading,
    settings_for,
)


def _run_kwargs(run_dir: Path, *, plan: Any, bridge: Any, tolerances: Any) -> dict[str, Any]:
    """Build a worker invocation without opening the fake seat for a baseline reading."""
    return {
        "run_dir": run_dir,
        "client": bridge,
        "plan": plan,
        "package": PACKAGE,
        "dump_after": pytest.fail,
        "baseline": 0,
        "before": reading_from_reply(reading()),
        "attestation": attestation(run_dir),
        "settings": settings_for(),
        "provider_factory": pytest.fail,
        "document_length_unit": UNIT,
        "which_configs": WHICH_CONFIGS_THIS,
        "tolerances": tolerances,
        "now": StepClock(AT, 1.0),
    }


@pytest.mark.parametrize(
    ("tolerances", "error", "message"),
    [
        (IDENTITY, UncalibratedProfileError, "calibrat"),
        (EQUIVALENCE.model_copy(update={"calibrated": True}), ValueError, "IDENTITY"),
    ],
)
def test_stage_1_profile_is_refused_before_provider_or_bridge(
    tmp_path: Path, tolerances: Any, error: type[Exception], message: str
) -> None:
    run_dir = tmp_path / "profile-refused"
    plan = planned(run_dir)
    bridge = bridge_for(PACKAGE)

    with pytest.raises(error, match=message):
        runner.run_remodel(
            **_run_kwargs(run_dir, plan=plan, bridge=bridge, tolerances=tolerances)
        )

    assert bridge.calls == []
    assert not (run_dir / "events.jsonl").exists()


@pytest.mark.parametrize(
    "plan_update",
    [
        {"state": "failed"},
        {
            "scope": lambda plan: plan.scope.model_copy(
                update={"verdict": "refused"}
            )
        },
        {"run_id": None, "copy_path": None, "source": None},
    ],
)
def test_invalid_plan_is_refused_before_provider_or_bridge(
    tmp_path: Path, plan_update: dict[str, Any]
) -> None:
    run_dir = tmp_path / "plan-refused"
    plan = planned(run_dir)
    update = {
        key: (value(plan) if callable(value) else value)
        for key, value in plan_update.items()
    }
    plan = plan.model_copy(update=update)
    bridge = bridge_for(PACKAGE)

    with pytest.raises(ValueError, match="plan|scope|copy"):
        runner.run_remodel(
            **_run_kwargs(run_dir, plan=plan, bridge=bridge, tolerances=CALIBRATED)
        )

    assert bridge.calls == []
    assert not (run_dir / "events.jsonl").exists()
