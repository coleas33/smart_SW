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
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.agent.settings import (
    LEVER_NAMES,
    WORKSTATION_LEVERS,
    EfficiencySettings,
    check_study_arm,
    checks_first,
    efficiency_from_levers,
    pane_efficiency,
)
from swreview.benchmark.runner import run_benchmark
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
)
"""The thirteen levers of data-model.md section 7, written out once so the model cannot lose
one without this module noticing. Every other test here takes the names from the model.
Lever 13, `withhold_prerun_tools`, is the owner's of 2026-09-23 (feature 008 research R2.53),
appended last like lever 11.

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
    assert [getattr(settings, name) for name in EXPECTED_LEVERS] == [False] * 13


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


def test_an_unknown_lever_name_names_the_thirteen_valid_ones() -> None:
    with pytest.raises(ValueError) as caught:
        efficiency_from_levers(["turbo_mode"])

    message = str(caught.value)
    assert "turbo_mode" in message
    assert "the thirteen levers" in message
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


def test_an_unknown_study_name_names_the_thirteen_levers() -> None:
    with pytest.raises(ValueError) as caught:
        check_study_arm(study="turbo_mode", arm="on", efficiency=EfficiencySettings())

    assert "the thirteen levers" in str(caught.value)
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
    ) -> None:
        seen.append(efficiency)

    run_benchmark(
        set_path,
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


PANE_LEVERS = ("prerun_checks", "withhold_prerun_tools", "parallel_tool_calls")
"""The levers the pane decides per provider: checks first (User Story 2), the pre-run's tools
leaving the array (the amendment of 2026-09-23, T107) and, for OpenAI, parallel tool calls
(User Story 4, T080). Every other lever is the class default."""


@pytest.mark.parametrize("provider", list(ProviderName))
def test_every_other_pane_lever_is_the_class_default(provider: ProviderName) -> None:
    """Checks first is the lever User Story 2 turns on in the pane; the amendment of
    2026-09-23 widens this by exactly `withhold_prerun_tools` (T107), and US4 by exactly
    `parallel_tool_calls` (T080)."""
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
