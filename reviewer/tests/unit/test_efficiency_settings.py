"""The lever flags and the one carrier that threads them (T017, for T018).

`EfficiencySettings` is the whole of this feature's configuration surface: twelve booleans,
every one of them off, one object threaded as one keyword argument through `start_review`,
`ReviewRun`, `run_benchmark` and `cli._review_fn` exactly as `effort` and `max_steps`
already are. The alternative - one plumbed parameter per lever - is ten signature changes
across three call sites and ten separate contract edits (data-model.md section 7.1, OQ-1).

Three things this module pins, in the order they matter:

1. **The model is closed and frozen.** `extra="forbid"` means a session carrying a flag a
   later build removed fails loudly rather than being silently ignored, because a results
   row attributed to a configuration nobody can reconstruct is worse than an error
   (data-model.md section 7.3). Frozen because `session.efficiency` is a statement about
   the run that produced it.
2. **The run records what it ran with.** Without `ReviewSession.efficiency` no results row
   can be attributed to a configuration and the A/B table cannot be rebuilt from the run
   folder. The field is optional, and a feature 001 session written before it existed
   loads unchanged - the pattern `provider_info` and `retry_of` already set.
3. **The refusals happen where the lever is chosen.** `swreview benchmark run --lever` is
   where a study arm is typed, and a refusal after six paid runs is worthless
   (contracts/ab-harness.md section 2). Every one of them is a usage error - exit 2 - with
   a message naming the rule rather than a stack trace.

No network: the only commands run here either refuse before any adapter is built, or use
`--provider fake`, which sends nothing anywhere.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.agent.settings import (
    LEVER_NAMES,
    MODEL_VIEW_OFF,
    NO_STUDY,
    PANE_STUDY,
    PRIVATE_PANE_STUDY,
    WORKSTATION_LEVERS,
    EfficiencySettings,
    check_study_arm,
    checks_first,
    efficiency_from_levers,
    pane_efficiency,
)
from swreview.benchmark.runner import AttemptRequest, preflight_set, run_benchmark
from swreview.report.session import ReviewSession, load_session

runner = CliRunner()

EXPECTED_LEVERS: tuple[str, ...] = (
    "trim_tool_descriptions",
    "tool_tiers",
    "prompt_cache_key",
    "gemini_explicit_cache",
    "prerun_checks",
    "parallel_tool_calls",
    "coverage_stop",
    "package_reuse",
    "lazy_meshes",
    "carry_over_rms",
    "procedural_gate",
    "compact_queries",
    "withhold_prerun_tools",
    "drop_prior_reasoning",
)
"""The fourteen levers of data-model.md section 7, written out once so the model cannot lose
one without this module noticing. Every other test here takes the names from the model.
Lever 13, `withhold_prerun_tools`, is the owner's of 2026-09-23 (feature 008 research R2.53),
appended last like lever 11; lever 14, `drop_prior_reasoning`, is feature 013's (T121,
`contracts/tokens.md` section 4), appended last again.

Lever 11 is **appended**, never inserted: `LEVER_NAMES` is this tuple, and a name inserted
in the middle would reorder every refusal message and every `--help` listing that iterates
it (feature 007 research R2.10)."""


SCRIPT: tuple[ScriptedTurn, ...] = (
    ScriptedTurn(
        text="Read the census and stopped.",
        tool_calls=(ScriptedToolCall("get_package_summary"),),
    ),
)


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


# --- the model -------------------------------------------------------------------


def test_every_lever_is_a_field_and_every_field_defaults_to_off() -> None:
    settings = EfficiencySettings()

    assert tuple(EfficiencySettings.model_fields) == EXPECTED_LEVERS
    assert [getattr(settings, name) for name in EXPECTED_LEVERS] == [False] * 14


def test_lever_names_come_from_the_model() -> None:
    """Every refusal message and the pane guard iterate this, never a retyped list."""
    assert LEVER_NAMES == EXPECTED_LEVERS
    assert set(WORKSTATION_LEVERS) <= set(LEVER_NAMES)


def test_efficiency_settings_is_frozen() -> None:
    settings = EfficiencySettings(prompt_cache_key=True)

    with pytest.raises(ValidationError):
        settings.prompt_cache_key = False  # type: ignore[misc]


def test_an_unknown_flag_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ValidationError):
        EfficiencySettings(turbo_mode=True)  # type: ignore[call-arg]


def test_a_removed_flag_on_an_old_session_fails_loudly() -> None:
    """data-model.md 7.3: silently ignoring it would attribute a row to nothing."""
    with pytest.raises(ValidationError):
        EfficiencySettings.model_validate({"prompt_cache_key": True, "retired_lever": True})


# --- resolving `--lever` ---------------------------------------------------------


def test_levers_resolve_to_the_named_flags_and_nothing_else() -> None:
    settings = efficiency_from_levers(["prompt_cache_key", "tool_tiers"])

    assert settings.prompt_cache_key is True
    assert settings.tool_tiers is True
    assert settings == EfficiencySettings(prompt_cache_key=True, tool_tiers=True)


def test_no_levers_resolve_to_every_flag_off() -> None:
    assert efficiency_from_levers(()) == EfficiencySettings()


def test_an_unknown_lever_name_names_the_fourteen_valid_ones() -> None:
    with pytest.raises(ValueError) as caught:
        efficiency_from_levers(["turbo_mode"])

    message = str(caught.value)
    assert "turbo_mode" in message
    assert "the fourteen levers" in message
    for name in LEVER_NAMES:
        assert name in message


def test_coverage_stop_with_prerun_checks_is_refused() -> None:
    with pytest.raises(ValueError, match="gated alone"):
        efficiency_from_levers(["coverage_stop", "prerun_checks"])


def test_procedural_gate_with_prerun_checks_is_refused_naming_both_levers() -> None:
    """Lever 11 implies the pre-run, so an arm carrying both measures one thing twice and
    can attribute nothing to either (feature 007 contracts/gate.md section 1)."""
    with pytest.raises(ValueError) as caught:
        efficiency_from_levers(["procedural_gate", "prerun_checks"])

    message = str(caught.value)
    assert "levers 5 and 11 never share an arm until each has been gated alone" in message
    assert "procedural_gate" in message
    assert "prerun_checks" in message


def test_procedural_gate_with_coverage_stop_is_refused_for_lever_five_s_reason() -> None:
    """The same failure `prerun_checks` + `coverage_stop` has: a pre-run that closes every
    checklist item plus a stop predicate ends the review before the first turn."""
    with pytest.raises(ValueError) as caught:
        efficiency_from_levers(["procedural_gate", "coverage_stop"])

    message = str(caught.value)
    assert "levers 7 and 11 never share an arm until each has been gated alone" in message
    assert "procedural_gate" in message
    assert "coverage_stop" in message


def test_procedural_gate_alone_is_allowed() -> None:
    """It is the arm the study is for; only the two combinations above are refused."""
    assert efficiency_from_levers(["procedural_gate"]).procedural_gate is True


def test_parallel_tool_calls_with_gemini_is_refused() -> None:
    with pytest.raises(ValueError, match="parallel"):
        efficiency_from_levers(["parallel_tool_calls"], provider=ProviderName.GEMINI)


def test_parallel_tool_calls_with_openai_is_allowed() -> None:
    settings = efficiency_from_levers(["parallel_tool_calls"], provider=ProviderName.OPENAI)

    assert settings.parallel_tool_calls is True


@pytest.mark.parametrize("lever", WORKSTATION_LEVERS)
def test_the_three_dump_levers_are_refused_where_nothing_dumps(lever: str) -> None:
    with pytest.raises(ValueError, match="workstation harness"):
        efficiency_from_levers([lever], allow_workstation_levers=False)


@pytest.mark.parametrize("lever", WORKSTATION_LEVERS)
def test_the_three_dump_levers_are_allowed_where_a_dump_happens(lever: str) -> None:
    assert getattr(efficiency_from_levers([lever]), lever) is True


# --- `--study`, `--arm` and the four consistency refusals ------------------------


def test_an_arm_on_needs_the_studied_lever_present() -> None:
    with pytest.raises(ValueError, match="prompt_cache_key"):
        check_study_arm(
            study="prompt_cache_key", arm="on", efficiency=EfficiencySettings()
        )


def test_an_arm_off_refuses_the_studied_lever_present() -> None:
    with pytest.raises(ValueError, match="prompt_cache_key"):
        check_study_arm(
            study="prompt_cache_key",
            arm="off",
            efficiency=EfficiencySettings(prompt_cache_key=True),
        )


def test_a_baseline_arm_refuses_any_lever() -> None:
    with pytest.raises(ValueError, match="baseline"):
        check_study_arm(
            study="none", arm="baseline", efficiency=EfficiencySettings(tool_tiers=True)
        )


def test_a_baseline_arm_refuses_a_study_other_than_none() -> None:
    with pytest.raises(ValueError, match="baseline"):
        check_study_arm(
            study="tool_tiers", arm="baseline", efficiency=EfficiencySettings()
        )


@pytest.mark.parametrize("arm", ["off", "on"])
def test_study_none_refuses_an_off_or_on_arm(arm: str) -> None:
    with pytest.raises(ValueError, match="--study none"):
        check_study_arm(study="none", arm=arm, efficiency=EfficiencySettings())


def test_an_unknown_study_name_names_the_fourteen_levers() -> None:
    with pytest.raises(ValueError) as caught:
        check_study_arm(study="turbo_mode", arm="on", efficiency=EfficiencySettings())

    assert "the fourteen levers" in str(caught.value)
    for name in LEVER_NAMES:
        assert name in str(caught.value)


def test_the_consistent_combinations_pass() -> None:
    check_study_arm(study="none", arm=None, efficiency=EfficiencySettings())
    check_study_arm(study="none", arm="baseline", efficiency=EfficiencySettings())
    check_study_arm(
        study="tool_tiers", arm="on", efficiency=EfficiencySettings(tool_tiers=True)
    )
    check_study_arm(
        study="tool_tiers",
        arm="off",
        efficiency=EfficiencySettings(prompt_cache_key=True),
    )


# --- the pane study and the two baselines (feature 014 T043) ------------------------------
#
# `specs/014-design-review-eval/contracts/provenance.md` sections 3.1 to 3.3: the pane study
# and its private twin have an `on` arm that is exactly `--pane-defaults` and an `off` arm with
# every change off, both with the explanation setting typed; a baseline's study is none, and
# the pane baseline is exactly `--pane-defaults`. What was typed reaches `check_study_arm` as
# markers, because the resolved settings cannot tell the pane's levers from typed ones.

PANE_STUDIES: tuple[str, ...] = (PANE_STUDY, PRIVATE_PANE_STUDY)

MODEL_VIEW_SWITCHES: tuple[str, ...] = ("--payload-slimming", "--history-pruning", "--prune-after")
"""`model_view_typed` says a model-view switch was typed, not which, so a refusal names all
three."""


def study_arm(
    study: str,
    arm: str | None,
    *,
    pane_defaults: bool = False,
    levers: Sequence[str] = (),
    model_view_typed: bool = False,
    explanations_typed: bool = False,
) -> None:
    """`check_study_arm` over what one command line typed and the levers it resolves to: the
    pane's under `--pane-defaults`, plus the ones named."""
    pane = pane_efficiency(ProviderName.FAKE)
    pane_levers = [name for name in LEVER_NAMES if getattr(pane, name)] if pane_defaults else []
    check_study_arm(
        study=study,
        arm=arm,
        efficiency=efficiency_from_levers([*pane_levers, *levers]),
        pane_defaults=pane_defaults,
        levers=levers,
        model_view_typed=model_view_typed,
        explanations_typed=explanations_typed,
    )


def refusal(study: str, arm: str | None, **typed: Any) -> str:
    """The message of the `ValueError` `study_arm` raises."""
    with pytest.raises(ValueError) as caught:
        study_arm(study, arm, **typed)
    return str(caught.value)


def review_settings(
    *,
    study: str,
    arm: str | None,
    pane_defaults: bool = False,
    lever: list[str] | None = None,
    payload_slimming: bool = False,
    history_pruning: bool = False,
    prune_after: int | None = None,
    explain_findings: bool | None = None,
) -> Any:
    """`cli._review_settings` with a study and an arm and no workstation lever, as `benchmark
    run` resolves through it from T051 (RF-19), so the markers are the ones it derives."""
    return cli._review_settings(
        ProviderName.FAKE,
        pane_defaults=pane_defaults,
        lever=lever,
        payload_slimming=payload_slimming,
        history_pruning=history_pruning,
        prune_after=prune_after,
        explain_findings=explain_findings,
        study=study,
        arm=arm,
        allow_workstation_levers=False,
    )


def test_the_pane_study_names_are_the_contracts() -> None:
    assert PANE_STUDY == "pane_defaults"
    assert PRIVATE_PANE_STUDY == "pane_defaults_private"


def test_an_unknown_study_name_also_names_the_pane_studies() -> None:
    message = refusal("pane_default", "on", pane_defaults=True, explanations_typed=True)

    assert "unknown --study 'pane_default'" in message
    assert PANE_STUDY in message and PRIVATE_PANE_STUDY in message


@pytest.mark.parametrize("study", PANE_STUDIES)
def test_a_pane_study_accepts_the_arms_that_follow_its_rules(study: str) -> None:
    study_arm(study, "on", pane_defaults=True, explanations_typed=True)
    study_arm(study, "off", explanations_typed=True)

    # Through the resolver: the pane's own levers are not typed levers, and a typed
    # `--no-explain-findings` is an explanation setting typed.
    on = review_settings(study=study, arm="on", pane_defaults=True, explain_findings=True)
    off = review_settings(study=study, arm="off", explain_findings=False)

    assert on.efficiency == pane_efficiency(ProviderName.FAKE)
    assert off.efficiency == EfficiencySettings()


@pytest.mark.parametrize("study", PANE_STUDIES)
def test_a_pane_study_with_no_arm_is_refused(study: str) -> None:
    message = refusal(study, None, pane_defaults=True, explanations_typed=True)

    assert f"--study {study}" in message and "--arm" in message
    assert "name the arm: on or off" in message


@pytest.mark.parametrize("study", PANE_STUDIES)
def test_a_pane_study_refuses_an_unknown_arm(study: str) -> None:
    message = refusal(study, "sideways", pane_defaults=True, explanations_typed=True)

    assert "unknown --arm 'sideways'" in message


@pytest.mark.parametrize("study", PANE_STUDIES)
def test_a_pane_study_refuses_the_baseline_arm(study: str) -> None:
    message = refusal(study, "baseline", pane_defaults=True, explanations_typed=True)

    assert "--arm baseline" in message and f"--study {study}" in message
    assert "a baseline's study is none" in message


@pytest.mark.parametrize("study", PANE_STUDIES)
@pytest.mark.parametrize(("arm", "pane_defaults"), [("on", True), ("off", False)])
def test_a_pane_study_refuses_an_explanation_setting_left_untyped(
    study: str, arm: str, pane_defaults: bool
) -> None:
    """PP-2, US2-4: both arms state the explanation setting, so compare can hold it equal."""
    message = refusal(study, arm, pane_defaults=pane_defaults)

    assert "--explain-findings" in message and "--no-explain-findings" in message
    assert (
        "type the explanation setting in both arms; the pane study holds it equal and stated"
        in message
    )
    with pytest.raises(typer.BadParameter, match="type the explanation setting"):
        review_settings(study=study, arm=arm, pane_defaults=pane_defaults)


@pytest.mark.parametrize("study", PANE_STUDIES)
@pytest.mark.parametrize(
    ("typed", "named"),
    [
        pytest.param({}, ("without --pane-defaults",), id="no-pane-defaults"),
        pytest.param({"levers": ("tool_tiers",)}, ("--lever tool_tiers",), id="a-lever-alone"),
        pytest.param(
            {"pane_defaults": True, "levers": ("tool_tiers",)},
            ("--lever tool_tiers",),
            id="pane-defaults-and-a-lever",
        ),
        pytest.param(
            {"pane_defaults": True, "model_view_typed": True},
            MODEL_VIEW_SWITCHES,
            id="pane-defaults-and-a-model-view-switch",
        ),
    ],
)
def test_the_pane_studys_on_arm_is_exactly_pane_defaults(
    study: str, typed: dict[str, Any], named: tuple[str, ...]
) -> None:
    message = refusal(study, "on", explanations_typed=True, **typed)

    assert f"--study {study}" in message and "--arm on" in message
    assert "the on arm is exactly --pane-defaults" in message
    for flag in named:
        assert flag in message


@pytest.mark.parametrize("study", PANE_STUDIES)
@pytest.mark.parametrize(
    ("typed", "named"),
    [
        pytest.param({"pane_defaults": True}, ("--pane-defaults",), id="pane-defaults"),
        pytest.param({"levers": ("tool_tiers",)}, ("--lever tool_tiers",), id="a-lever"),
        pytest.param({"model_view_typed": True}, MODEL_VIEW_SWITCHES, id="a-model-view-switch"),
    ],
)
def test_the_pane_studys_off_arm_has_every_change_off(
    study: str, typed: dict[str, Any], named: tuple[str, ...]
) -> None:
    message = refusal(study, "off", explanations_typed=True, **typed)

    assert f"--study {study}" in message and "--arm off" in message
    assert "the off arm has every change off" in message
    for flag in named:
        assert flag in message


@pytest.mark.parametrize("explanations_typed", [False, True])
def test_the_pane_baseline_is_exactly_pane_defaults(explanations_typed: bool) -> None:
    """PP-4: `--study none --arm baseline --pane-defaults` tracks the shipped configuration.
    Its resolved levers are on, which a plain baseline refuses, and its explanations may be
    left untyped, to run as the pane runs them."""
    study_arm(NO_STUDY, "baseline", pane_defaults=True, explanations_typed=explanations_typed)

    for typed, named in (
        ({"levers": ("tool_tiers",)}, ("--lever tool_tiers",)),
        ({"model_view_typed": True}, MODEL_VIEW_SWITCHES),
    ):
        message = refusal(
            NO_STUDY,
            "baseline",
            pane_defaults=True,
            explanations_typed=explanations_typed,
            **typed,
        )
        assert "--arm baseline" in message and "--pane-defaults" in message
        assert "the pane baseline is exactly --pane-defaults" in message
        for flag in named:
            assert flag in message

    explain_findings = True if explanations_typed else None
    resolved = review_settings(
        study=NO_STUDY, arm="baseline", pane_defaults=True, explain_findings=explain_findings
    )
    assert resolved.efficiency == pane_efficiency(ProviderName.FAKE)
    with pytest.raises(typer.BadParameter, match="--lever tool_tiers"):
        review_settings(study=NO_STUDY, arm="baseline", pane_defaults=True, lever=["tool_tiers"])


PLAIN_BASELINE_REFUSAL = (
    "--arm baseline with --payload-slimming, --history-pruning or --prune-after: a baseline run "
    "has every change off; the pane baseline is --arm baseline --pane-defaults"
)
"""`check_study_arm`'s refusal of a model-view switch on a plain baseline, whole. It names the
three switches whichever was typed (`MODEL_VIEW_SWITCHES`), so naming one proves nothing."""


@pytest.mark.parametrize(
    "switches",
    [
        pytest.param({"payload_slimming": True}, id="payload-slimming"),
        pytest.param({"history_pruning": True}, id="history-pruning"),
        pytest.param({"prune_after": 3}, id="prune-after"),
        pytest.param({"history_pruning": True, "prune_after": 3}, id="history-pruning-prune-after"),
    ],
)
def test_a_plain_baseline_refuses_a_model_view_switch(switches: dict[str, Any]) -> None:
    """PP-4: `agent/settings.py:756-766` named `--lever` only, so a plain baseline with the
    model view on rendered as a baseline with every change off. Each switch is typed alone, so
    its refusal is pinned to it: the same command without it is accepted, and the refusal is the
    baseline rule's whole message, never another rule's (`--prune-after` with pruning off has a
    refusal of its own that names the flag too)."""
    assert refusal(NO_STUDY, "baseline", model_view_typed=True) == PLAIN_BASELINE_REFUSAL

    plain = review_settings(study=NO_STUDY, arm="baseline")
    assert (plain.efficiency, plain.model_view) == (EfficiencySettings(), MODEL_VIEW_OFF)

    with pytest.raises(typer.BadParameter) as caught:
        review_settings(study=NO_STUDY, arm="baseline", **switches)
    assert str(caught.value) == PLAIN_BASELINE_REFUSAL


def test_the_resolver_refuses_a_workstation_lever_only_when_asked() -> None:
    """RF-19: `benchmark run` keeps its workstation-lever refusal through `_review_settings`,
    and `review` and `benchmark replay`, which leave the parameter at its default, do not."""
    with pytest.raises(typer.BadParameter, match="workstation harness"):
        review_settings(study=NO_STUDY, arm=None, lever=["lazy_meshes"])

    resolved = cli._review_settings(
        ProviderName.FAKE,
        pane_defaults=False,
        lever=["lazy_meshes"],
        payload_slimming=False,
        history_pruning=False,
        prune_after=None,
    )
    assert resolved.efficiency == EfficiencySettings(lazy_meshes=True)


# --- the session records the configuration ---------------------------------------


def test_a_session_written_before_the_field_existed_loads_unchanged(tmp_path: Path) -> None:
    """The `provider_info` and `retry_of` pattern: optional, and absent means absent."""
    written = tmp_path / "session.json"
    written.write_text(
        json.dumps(
            {
                "session_id": "11111111-1111-4111-8111-111111111111",
                "package_id": "22222222-2222-4222-8222-222222222222",
                "design_id": "dsn:1",
                "started_at": "2026-01-01T00:00:00Z",
                "ended_at": None,
                "model": "gpt-5.6",
                "steps": [],
                "evidence_requests": [],
                "findings": [],
                "coverage": {
                    "checked": [],
                    "skipped": [],
                    "unresolved": [],
                    "failed": [],
                    "out_of_scope": [],
                },
                "timing": {
                    "baseline_minutes": None,
                    "assisted_supervision_minutes": 0.0,
                    "assisted_verification_minutes": 0.0,
                    "false_alarm_handling_minutes": 0.0,
                    "unattended_runtime_minutes": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )

    session = load_session(written)

    assert session.efficiency is None
    assert session.provider_info is None
    assert session.model == "gpt-5.6"


def test_review_session_efficiency_is_optional() -> None:
    """Left out of `required` in the contract too, so feature 001 sessions stay valid."""
    assert ReviewSession.model_fields["efficiency"].is_required() is False


def test_start_review_records_the_settings_on_the_session(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    efficiency = EfficiencySettings(prompt_cache_key=True)

    run = start_review(
        tmp_package_dir,
        tmp_path / "run",
        provider=FakeProvider(script=SCRIPT, model="fake-scripted"),
        efficiency=efficiency,
    )
    try:
        assert run.efficiency == efficiency
        assert run.session.efficiency == efficiency
    finally:
        run.close()


def test_start_review_without_settings_records_every_lever_off(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """Never `None` for a run this build made: `compare` refuses a run it cannot attribute."""
    run = start_review(
        tmp_package_dir,
        tmp_path / "run",
        provider=FakeProvider(script=SCRIPT, model="fake-scripted"),
    )
    try:
        assert run.session.efficiency == EfficiencySettings()
    finally:
        run.close()


# --- threading through the benchmark runner and the CLI --------------------------


def test_run_benchmark_passes_the_settings_to_every_package(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = _one_package_set(tmp_path, tmp_package_dir)
    efficiency = EfficiencySettings(tool_tiers=True)
    seen: list[EfficiencySettings | None] = []

    def fake_review_fn(
        package_dir: Path,
        session_out_dir: Path,
        *,
        provider: str,
        model: str,
        effort: str,
        efficiency: EfficiencySettings | None,
        attempt: AttemptRequest,
    ) -> None:
        seen.append(efficiency)

    run_benchmark(
        preflight_set(set_path, None, load_checklist()),
        tmp_path / "out",
        provider="fake",
        model="fake-scripted",
        effort="high",
        review_fn=fake_review_fn,
        efficiency=efficiency,
    )

    assert seen == [efficiency]


def test_cli_review_fn_passes_the_settings_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tmp_package_dir: Path
) -> None:
    efficiency = EfficiencySettings(coverage_stop=True)
    seen: list[Any] = []

    def fake_run_review(package_dir: Path, out_dir: Path, **options: Any) -> None:
        seen.append(options["efficiency"])

    monkeypatch.setattr(cli, "run_review", fake_run_review)

    cli._review_fn(
        tmp_package_dir,
        tmp_path / "out",
        provider="fake",
        model="fake-scripted",
        effort="high",
        efficiency=efficiency,
        attempt=AttemptRequest(
            model_view=MODEL_VIEW_OFF, standards_profile=None, case_file=None, max_answer_turns=0
        ),
    )

    assert seen == [efficiency]


def _one_package_set(tmp_path: Path, package_dir: Path, *, held_out: bool = True) -> Path:
    sets_dir = tmp_path / "sets"
    sets_dir.mkdir(exist_ok=True)
    set_path = sets_dir / "study.json"
    set_path.write_text(
        json.dumps(
            {
                "name": "study",
                "packages": [
                    {"package_id": "cover", "path": str(package_dir), "held_out": held_out}
                ],
            }
        ),
        encoding="utf-8",
    )
    return set_path


# --- the command line ------------------------------------------------------------


def test_review_lever_reaches_the_session(tmp_path: Path, tmp_package_dir: Path) -> None:
    out = tmp_path / "run"

    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(out),
        "--provider",
        "fake",
        "--lever",
        "prompt_cache_key",
        "--lever",
        "tool_tiers",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    session = load_session(out / "session.json")
    assert session.efficiency == EfficiencySettings(prompt_cache_key=True, tool_tiers=True)


def test_review_without_a_lever_records_every_lever_off(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    out = tmp_path / "run"

    result = invoke(
        "review", str(tmp_package_dir), "--out", str(out), "--provider", "fake"
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert load_session(out / "session.json").efficiency == EfficiencySettings()


def test_review_with_an_unknown_lever_is_a_usage_error(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(tmp_path / "run"),
        "--provider",
        "fake",
        "--lever",
        "turbo_mode",
    )

    assert result.exit_code == 2
    output = result.stdout + result.stderr
    assert "turbo_mode" in output
    for name in LEVER_NAMES:
        assert name in output


def test_review_refuses_parallel_tool_calls_on_gemini(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(tmp_path / "run"),
        "--provider",
        "gemini",
        "--lever",
        "parallel_tool_calls",
    )

    assert result.exit_code == 2


def test_benchmark_run_lever_reaches_every_session(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = _one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "on-1"

    result = invoke(
        "benchmark",
        "run",
        "--set",
        str(set_path),
        "--out",
        str(out),
        "--provider",
        "fake",
        "--lever",
        "tool_tiers",
        "--study",
        "tool_tiers",
        "--arm",
        "on",
        "--rep",
        "1",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert load_session(out / "cover" / "session.json").efficiency == EfficiencySettings(
        tool_tiers=True
    )


@pytest.mark.parametrize("lever", WORKSTATION_LEVERS)
def test_benchmark_run_refuses_the_three_dump_levers(
    tmp_path: Path, tmp_package_dir: Path, lever: str
) -> None:
    set_path = _one_package_set(tmp_path, tmp_package_dir)

    result = invoke(
        "benchmark",
        "run",
        "--set",
        str(set_path),
        "--out",
        str(tmp_path / "runs" / "out"),
        "--provider",
        "fake",
        "--lever",
        lever,
    )

    assert result.exit_code == 2
    assert "workstation harness" in result.stdout + result.stderr


def test_benchmark_run_refuses_a_mislabelled_arm(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = _one_package_set(tmp_path, tmp_package_dir)

    result = invoke(
        "benchmark",
        "run",
        "--set",
        str(set_path),
        "--out",
        str(tmp_path / "runs" / "out"),
        "--provider",
        "fake",
        "--study",
        "tool_tiers",
        "--arm",
        "on",
    )

    assert result.exit_code == 2
    assert "tool_tiers" in result.stdout + result.stderr


def test_benchmark_run_refuses_a_set_with_no_held_out_package(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = _one_package_set(tmp_path, tmp_package_dir, held_out=False)

    result = invoke(
        "benchmark",
        "run",
        "--set",
        str(set_path),
        "--out",
        str(tmp_path / "runs" / "out"),
        "--provider",
        "fake",
        "--lever",
        "tool_tiers",
    )

    assert result.exit_code == 2
    assert "held_out" in result.stdout + result.stderr


def test_benchmark_run_accepts_a_small_set_with_the_override(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = _one_package_set(tmp_path, tmp_package_dir, held_out=False)
    out = tmp_path / "runs" / "smoke"

    result = invoke(
        "benchmark",
        "run",
        "--set",
        str(set_path),
        "--out",
        str(out),
        "--provider",
        "fake",
        "--lever",
        "tool_tiers",
        "--i-know-the-set-is-too-small",
    )

    assert result.exit_code == 0, result.stdout + result.stderr


def test_benchmark_run_without_a_study_is_not_held_to_the_set_precondition(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """A plain run of a small set is a smoke test, not a gate, and stays legal."""
    set_path = _one_package_set(tmp_path, tmp_package_dir, held_out=False)
    out = tmp_path / "runs" / "plain"

    result = invoke(
        "benchmark", "run", "--set", str(set_path), "--out", str(out), "--provider", "fake"
    )

    assert result.exit_code == 0, result.stdout + result.stderr


# --- checks first and the pane's defaults (feature 008 T027) -------------------------------


def test_checks_first_is_off_without_settings_and_with_every_lever_off() -> None:
    assert checks_first(None) is False
    assert checks_first(EfficiencySettings()) is False


def test_checks_first_is_lever_5_or_lever_11() -> None:
    """Lever 11 implies the pre-run, so either field turns checks first on (research R2.13)."""
    assert checks_first(EfficiencySettings(prerun_checks=True)) is True
    assert checks_first(EfficiencySettings(procedural_gate=True)) is True
    assert checks_first(EfficiencySettings(tool_tiers=True, coverage_stop=True)) is False


@pytest.mark.parametrize("provider", list(ProviderName))
def test_the_pane_runs_checks_first_on_every_provider(provider: ProviderName) -> None:
    pane = pane_efficiency(provider)

    assert pane.prerun_checks is True
    assert checks_first(pane) is True


PANE_LEVERS = (
    "prerun_checks",
    "withhold_prerun_tools",
    "parallel_tool_calls",
    "drop_prior_reasoning",
)
"""The levers the pane decides per provider: checks first (User Story 2), the pre-run's tools
leaving the array (the amendment of 2026-09-23, T107), for OpenAI, parallel tool calls (User
Story 4, T080), and earlier turns' reasoning out of the request view (feature 013 T125, edited
deliberately). Every other lever is the class default."""


@pytest.mark.parametrize("provider", list(ProviderName))
def test_every_other_pane_lever_is_the_class_default(provider: ProviderName) -> None:
    """Checks first is the lever User Story 2 turns on in the pane; the amendment of
    2026-09-23 widens this by exactly `withhold_prerun_tools` (T107), US4 by exactly
    `parallel_tool_calls` (T080), and feature 013 T125 by exactly `drop_prior_reasoning`."""
    pane = pane_efficiency(provider).model_dump()
    default = EfficiencySettings().model_dump()

    assert {name: value for name, value in pane.items() if name not in PANE_LEVERS} == {
        name: value for name, value in default.items() if name not in PANE_LEVERS
    }


PARALLEL_BY_PROVIDER: tuple[tuple[ProviderName, bool], ...] = (
    (ProviderName.OPENAI, True),
    (ProviderName.GEMINI, False),
    (ProviderName.FAKE, False),
)
"""Lever 6 in the pane, per provider (feature 008 FR-024, research R2.40): on for OpenAI,
whose request pins it off otherwise; off for Gemini, which has no switch and already makes
parallel calls; off for the scripted provider, which reads no request field."""


def test_the_parallel_table_names_every_provider() -> None:
    assert {provider for provider, _ in PARALLEL_BY_PROVIDER} == set(ProviderName)


@pytest.mark.parametrize(("provider", "expected"), PARALLEL_BY_PROVIDER)
def test_the_pane_asks_for_parallel_tool_calls_on_openai_only(
    provider: ProviderName, expected: bool
) -> None:
    assert pane_efficiency(provider).parallel_tool_calls is expected


@pytest.mark.parametrize("provider", list(ProviderName))
def test_the_panes_levers_pass_the_lever_resolver_for_their_provider(
    provider: ProviderName,
) -> None:
    """`--pane-defaults` feeds the pane's levers back through `efficiency_from_levers`, so no
    provider's pane may carry a lever that resolver refuses - Gemini's parallel arm above all."""
    pane = pane_efficiency(provider)
    named = [name for name, on in pane.model_dump().items() if on]

    assert efficiency_from_levers(named, provider=provider) == pane


def test_the_pane_default_does_not_loosen_the_gated_alone_rule() -> None:
    """Checks first as a pane default changes no refusal: lever 5 with lever 7 is still one
    arm nobody may run (`GATED_ALONE` unchanged)."""
    with pytest.raises(ValueError, match="levers 5 and 7 never share an arm"):
        efficiency_from_levers(["prerun_checks", "coverage_stop"], provider=ProviderName.OPENAI)


# --- lever 13: the tools checks first ran leave the array (feature 008 T107) ---------------


@pytest.mark.parametrize("provider", list(ProviderName))
def test_the_pane_withholds_the_tools_checks_first_ran_on_every_provider(
    provider: ProviderName,
) -> None:
    """Both providers: the array is resent every round whoever the provider is (R2.53)."""
    assert pane_efficiency(provider).withhold_prerun_tools is True


def test_lever_13_alone_is_refused_in_one_sentence_naming_the_levers_it_needs() -> None:
    """Without a pre-run nothing is withheld, so the arm would measure nothing - the rule
    `parallel_tool_calls` with Gemini already follows (research R2.53)."""
    with pytest.raises(ValueError) as caught:
        efficiency_from_levers(["withhold_prerun_tools"])

    message = str(caught.value)
    assert "withhold_prerun_tools" in message
    assert "prerun_checks" in message
    assert "procedural_gate" in message
    assert "measure nothing" in message
    assert "." not in message.replace("`", "").rstrip("."), "one sentence"


@pytest.mark.parametrize("pre_run", ["prerun_checks", "procedural_gate"])
def test_lever_13_with_either_pre_run_is_allowed(pre_run: str) -> None:
    settings = efficiency_from_levers(["withhold_prerun_tools", pre_run])

    assert settings.withhold_prerun_tools is True
    assert getattr(settings, pre_run) is True
    assert checks_first(settings) is True


def test_lever_13_never_turns_checks_first_on_by_itself() -> None:
    """The flag withholds only what a pre-run ran; it is not a third way to run one."""
    assert checks_first(EfficiencySettings(withhold_prerun_tools=True)) is False


def test_review_refuses_lever_13_without_a_pre_run(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(tmp_path / "run"),
        "--provider",
        "fake",
        "--lever",
        "withhold_prerun_tools",
    )

    assert result.exit_code == 2
    assert "measure nothing" in " ".join((result.stdout + result.stderr).split())
    assert not (tmp_path / "run").exists()


def test_review_accepts_lever_13_with_checks_first_and_records_both(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    out = tmp_path / "run"
    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(out),
        "--provider",
        "fake",
        "--lever",
        "prerun_checks",
        "--lever",
        "withhold_prerun_tools",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert load_session(out / "session.json").efficiency == EfficiencySettings(
        prerun_checks=True, withhold_prerun_tools=True
    )


# --- lever 14, drop_prior_reasoning (feature 013 T120, contracts/tokens.md section 4) ----------


def test_lever_14_is_off_by_default_and_on_in_the_pane() -> None:
    """013 T125 (edited deliberately): the US6 replay gate (T124) priced lever 14 off and on over
    every fixture - no recorded finding lost, the requested input lower in every configuration -
    so the pane adopts it, for every provider as lever 13 is (inert on Gemini, which sends no
    reasoning items). The class, the command line and `benchmark run` stay off."""
    from swreview.agent.providers import ProviderName
    from swreview.agent.settings import pane_efficiency

    assert EfficiencySettings().drop_prior_reasoning is False
    for provider in ProviderName:
        assert pane_efficiency(provider).drop_prior_reasoning is True


def test_lever_14_resolves_alone_from_the_command_line() -> None:
    assert efficiency_from_levers(["drop_prior_reasoning"]) == EfficiencySettings(
        drop_prior_reasoning=True
    )


def test_lever_14_is_gated_alone_with_nothing() -> None:
    from swreview.agent.settings import GATED_ALONE

    assert all(
        "drop_prior_reasoning" not in (first, second) for first, _, second, _ in GATED_ALONE
    )
    assert efficiency_from_levers(["drop_prior_reasoning", "prerun_checks"]) == (
        EfficiencySettings(drop_prior_reasoning=True, prerun_checks=True)
    )


def test_a_session_omits_lever_14_while_it_is_off_and_keeps_its_bytes() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "small-assembly-a"
    session = load_session(fixture / "session.json")

    dumped = session.model_dump(mode="json")
    assert dumped["efficiency"] is not None
    assert "drop_prior_reasoning" not in dumped["efficiency"]


def test_a_session_writes_lever_14_when_it_is_on_and_validates(tmp_path: Path) -> None:
    from tests.unit.test_session import build_session, session_validator

    session = build_session(efficiency=EfficiencySettings(drop_prior_reasoning=True))
    dumped = session.model_dump(mode="json")

    assert dumped["efficiency"]["drop_prior_reasoning"] is True
    session_validator().validate(dumped)
    target = tmp_path / "session.json"
    target.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    assert load_session(target).efficiency == EfficiencySettings(drop_prior_reasoning=True)


def test_the_session_contract_names_lever_14_as_optional() -> None:
    from tests.support.contracts import load_contract

    definition = load_contract("review-session.schema.json")["$defs"]["EfficiencySettings"]

    assert definition["properties"]["drop_prior_reasoning"]["type"] == "boolean"
    assert "drop_prior_reasoning" not in definition.get("required", [])
