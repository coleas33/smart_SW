"""The model-view settings: what the model reads is a setting, not a lever (feature 008 T052).

Payload slimming and history pruning change what the model reads, never what the review
records, so they are settings beside `EfficiencySettings` rather than a thirteenth and
fourteenth lever: `LEVER_NAMES` and every lever-count pin stay as they are (research R2.32).
Two named values cover every surface: `MODEL_VIEW_OFF` for the command line and `benchmark
run`, `MODEL_VIEW_PANE` for the pane, and `pane_defaults(provider)` is the one function the
pane, `swreview review --pane-defaults` and the replay read. The session records what ran;
a session written before this feature has no `model_view`, which means off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.agent.settings import (
    LEVER_NAMES,
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    ModelViewSettings,
    PaneDefaults,
    pane_defaults,
    pane_efficiency,
)
from swreview.report.markdown import render_report
from swreview.report.session import load_session
from tests.unit.test_session import PRE_008_SESSION, build_session, session_validator


def test_the_settings_are_frozen_closed_and_need_both_booleans() -> None:
    settings = ModelViewSettings(payload_slimming=True, history_pruning=False)

    with pytest.raises(ValidationError):
        settings.payload_slimming = False  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ModelViewSettings(payload_slimming=True, history_pruning=True, turbo=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ModelViewSettings(payload_slimming=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ModelViewSettings(history_pruning=True)  # type: ignore[call-arg]


def test_the_prune_age_is_at_least_one_round() -> None:
    with pytest.raises(ValidationError):
        ModelViewSettings(payload_slimming=False, history_pruning=True, prune_after_rounds=0)
    assert ModelViewSettings(
        payload_slimming=False, history_pruning=True, prune_after_rounds=1
    ).prune_after_rounds == 1


def test_the_two_named_values_are_the_contracts() -> None:
    assert MODEL_VIEW_OFF == ModelViewSettings(
        payload_slimming=False, history_pruning=False, prune_after_rounds=2
    )
    assert MODEL_VIEW_PANE == ModelViewSettings(
        payload_slimming=True, history_pruning=True, prune_after_rounds=2
    )


@pytest.mark.parametrize("provider", list(ProviderName))
def test_the_pane_defaults_are_one_function_of_the_provider(provider: ProviderName) -> None:
    assert pane_defaults(provider) == PaneDefaults(pane_efficiency(provider), MODEL_VIEW_PANE)


def test_the_view_settings_are_not_levers() -> None:
    assert len(LEVER_NAMES) == 12
    assert not {"payload_slimming", "history_pruning", "prune_after_rounds"} & set(LEVER_NAMES)


# --- the session records what ran ------------------------------------------------------------


def test_a_session_without_the_field_loads_renders_and_keeps_its_bytes() -> None:
    session = load_session(PRE_008_SESSION)

    assert session.model_view is None
    assert render_report(session)
    assert "model_view" not in json.loads(session.model_dump_json())


@pytest.mark.parametrize("value", [None, MODEL_VIEW_OFF, MODEL_VIEW_PANE])
def test_a_written_session_validates_with_and_without_the_field(
    tmp_path: Path, value: ModelViewSettings | None
) -> None:
    session = build_session(model_view=value)
    target = tmp_path / "session.json"
    target.write_text(session.model_dump_json(indent=2), encoding="utf-8")

    written = json.loads(target.read_text(encoding="utf-8"))
    session_validator().validate(written)
    assert ("model_view" in written) is (value is not None)
    assert load_session(target).model_view == value


def reviewed(tmp_package_dir: Path, tmp_path: Path, **options: object) -> object:
    run = start_review(
        tmp_package_dir,
        tmp_path / "run",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        **options,  # type: ignore[arg-type]
    )
    return run.start()


def test_start_review_records_off_when_not_given(tmp_package_dir: Path, tmp_path: Path) -> None:
    session = reviewed(tmp_package_dir, tmp_path)

    assert session.model_view == MODEL_VIEW_OFF  # type: ignore[attr-defined]
    written = json.loads((tmp_path / "run" / "session.json").read_text(encoding="utf-8"))
    assert written["model_view"] == MODEL_VIEW_OFF.model_dump()


def test_start_review_records_the_settings_given(tmp_package_dir: Path, tmp_path: Path) -> None:
    given = ModelViewSettings(payload_slimming=True, history_pruning=True, prune_after_rounds=1)

    session = reviewed(tmp_package_dir, tmp_path, model_view=given)

    assert session.model_view == given  # type: ignore[attr-defined]
