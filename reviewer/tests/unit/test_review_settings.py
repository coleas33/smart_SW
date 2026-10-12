"""One resolver for a review's levers, model view and explanations (feature 014 T042).

`cli._review_settings` is the one place `swreview review` and `swreview benchmark replay`
turn their switches into settings, and since feature 014 it resolves three things instead of
two and returns one frozen value, `ResolvedReview(efficiency, model_view, explain_findings)`
(`specs/014-design-review-eval/contracts/benchmark-run.md` section 2; PP-1, FR-011, FR-015):

- a typed `--explain-findings` or `--no-explain-findings` wins; otherwise the base decides,
  `pane_defaults(provider)` with `--pane-defaults` (explanations on) and every change off
  without it (explanations off, as before this feature);
- the chat server reads `pane_defaults(provider).explain_findings` where it passed a literal
  `True`, so the pane's explanation setting is decided in one place;
- `benchmark replay` reads the result's levers and model view and nothing else.

Offline: the package is `tests/support/packages.build_package` saved into `tmp_path`, and every
review talks to the scripted provider, counted where a review asks it for the presentation
pass (`FakeProvider.for_presentation`).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

import swreview.chat.server as chat_server
from swreview import cli
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    EfficiencySettings,
    ModelViewSettings,
    PaneDefaults,
    ProviderSettings,
    pane_defaults,
)
from swreview.benchmark.replay import TurnPlan
from swreview.ir.loader import save_package
from swreview.report.session import load_session
from tests.support.packages import build_package
from tests.support.replay import record_scripted_review
from tests.unit.test_chat_server import ORIGIN, TOKEN, ProviderControl, settle, start_session
from tests.unit.test_cli import SCRIPT, invoke


class PresentationCounter(FakeProvider):
    """The scripted provider, counting the presentation requests a review makes of it.

    Its script records a drawing finding, which no family folds, so a review that runs the
    explanation pass has a row to explain and asks for it exactly once.
    """

    def __init__(self, *, model: str) -> None:
        super().__init__(script=SCRIPT, model=model)
        self.presentation_requests = 0

    def for_presentation(self, max_output_tokens: int) -> FakeProvider:
        self.presentation_requests += 1
        return super().for_presentation(max_output_tokens)


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "package"
    save_package(build_package(), directory)
    return directory


@pytest.fixture
def adapters(monkeypatch: pytest.MonkeyPatch) -> list[PresentationCounter]:
    """Swap `cli.provider_factory` for one that builds a `PresentationCounter` per review."""
    built: list[PresentationCounter] = []

    def factory(
        settings: ProviderSettings, efficiency: EfficiencySettings | None = None
    ) -> PresentationCounter:
        adapter = PresentationCounter(model=settings.model)
        built.append(adapter)
        return adapter

    monkeypatch.setattr(cli, "provider_factory", factory)
    return built


def resolve(provider: ProviderName, *, pane_defaults: bool, **typed: Any) -> Any:
    """`cli._review_settings` with no lever and no model-view switch typed."""
    return cli._review_settings(
        provider,
        pane_defaults=pane_defaults,
        lever=None,
        payload_slimming=False,
        history_pruning=False,
        prune_after=None,
        **typed,
    )


def reviewed(
    package_dir: Path, out: Path, adapters: list[PresentationCounter], *flags: str
) -> tuple[bool, int, EfficiencySettings | None]:
    """`swreview review --provider fake` with `flags`: what its session recorded for the
    explanations and the levers, and how many presentation requests its adapter received."""
    adapters.clear()
    result = invoke("review", str(package_dir), "--out", str(out), "--provider", "fake", *flags)
    assert result.exit_code == 0, result.stdout + result.stderr
    [adapter] = adapters
    session = load_session(out / "session.json")
    return session.explanations_enabled, adapter.presentation_requests, session.efficiency


def test_pane_defaults_include_the_explanation_pass(
    package_dir: Path, tmp_path: Path, adapters: list[PresentationCounter]
) -> None:
    """US2-1, FR-015: `--pane-defaults` is everything a pane review runs with, the
    explanation pass included, on every provider."""
    for provider in ProviderName:
        pane = pane_defaults(provider)
        resolved = resolve(provider, pane_defaults=True)

        assert resolved == cli.ResolvedReview(pane.efficiency, pane.model_view, True), provider
        assert resolved.explain_findings is True, provider
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.explain_findings = False

    enabled, requests, efficiency = reviewed(
        package_dir, tmp_path / "run", adapters, "--pane-defaults"
    )

    assert enabled is True
    assert requests == 1
    assert efficiency == pane_defaults(ProviderName.FAKE).efficiency


def test_no_explain_findings_overrides_pane_defaults_and_the_session_records_it_off(
    package_dir: Path, tmp_path: Path, adapters: list[PresentationCounter]
) -> None:
    """US2-7: a typed `--no-explain-findings` wins over the base, and only the explanations
    change - the pane's levers still run."""
    resolved = resolve(ProviderName.FAKE, pane_defaults=True, explain_findings=False)

    assert resolved.explain_findings is False
    assert resolved.efficiency == pane_defaults(ProviderName.FAKE).efficiency

    enabled, requests, efficiency = reviewed(
        package_dir, tmp_path / "run", adapters, "--pane-defaults", "--no-explain-findings"
    )

    assert enabled is False
    assert requests == 0
    assert efficiency == pane_defaults(ProviderName.FAKE).efficiency


def test_untyped_explanations_stay_off_without_pane_defaults(
    package_dir: Path, tmp_path: Path, adapters: list[PresentationCounter]
) -> None:
    """Neither flag is today's default, off; `--explain-findings` alone turns it on."""
    assert resolve(ProviderName.FAKE, pane_defaults=False) == cli.ResolvedReview(
        EfficiencySettings(), MODEL_VIEW_OFF, False
    )
    assert resolve(ProviderName.FAKE, pane_defaults=False, explain_findings=True) == (
        cli.ResolvedReview(EfficiencySettings(), MODEL_VIEW_OFF, True)
    )

    assert reviewed(package_dir, tmp_path / "off", adapters)[:2] == (False, 0)
    assert reviewed(package_dir, tmp_path / "on", adapters, "--explain-findings")[:2] == (True, 1)


def test_the_chat_server_reads_explanations_from_pane_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One decision (PP-1): the pane passes `start_review` what `pane_defaults` says about
    explanations, so changing `pane_defaults` changes the pane."""
    original = chat_server.start_review
    received: list[bool] = []

    def recording_start_review(*args: Any, **kwargs: Any) -> Any:
        received.append(kwargs["explain_findings"])
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_server, "start_review", recording_start_review)

    def pane_review(name: str) -> Path:
        run_dir = tmp_path / name
        save_package(build_package(), run_dir)
        app = chat_server.create_app(
            token=TOKEN,
            allow_origin=ORIGIN,
            run_root=tmp_path,
            provider_factory=ProviderControl().factory,
            list_models=lambda _: [],
        )
        headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        with TestClient(app, headers=headers) as client:
            settle(client, start_session(client, run_dir)["chat_id"])
        return run_dir

    pane_review("as-shipped")

    assert received == [pane_defaults(ProviderName.FAKE).explain_findings]

    shipped = chat_server.pane_defaults

    def explanations_off(provider: ProviderName) -> PaneDefaults:
        return dataclasses.replace(shipped(provider), explain_findings=False)

    monkeypatch.setattr(chat_server, "pane_defaults", explanations_off)
    run_dir = pane_review("explanations-off")

    assert received[1:] == [False]
    assert load_session(run_dir / "session.json").explanations_enabled is False


@pytest.mark.usefixtures("vocabulary")
def test_benchmark_replay_still_resolves_levers_and_model_view(
    package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`benchmark replay` hands `replay_recording` the result's levers and model view, as it
    handed the tuple, and never reads the explanation setting it has no use for."""
    run = record_scripted_review(
        tmp_path / "run",
        package_dir,
        [TurnPlan(rounds=((ScriptedToolCall("get_package_summary"),),), text="Ok.")],
    )
    resolver = cli._review_settings
    resolved: list[Any] = []
    explanation_reads: list[str] = []

    class Watched:
        """The resolver's result, noting every read of `explain_findings`."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        @property
        def efficiency(self) -> EfficiencySettings:
            return self._inner.efficiency

        @property
        def model_view(self) -> ModelViewSettings:
            return self._inner.model_view

        @property
        def explain_findings(self) -> bool:
            explanation_reads.append("explain_findings")
            return self._inner.explain_findings

    def watched_resolver(provider: ProviderName, **switches: Any) -> Watched:
        result = resolver(provider, **switches)
        resolved.append(result)
        return Watched(result)

    replay = cli.replay_recording
    requested: list[Any] = []

    def recording_replay(recording: Any, **kwargs: Any) -> Any:
        requested.append(kwargs["requested"])
        return replay(recording, **kwargs)

    monkeypatch.setattr(cli, "_review_settings", watched_resolver)
    monkeypatch.setattr(cli, "replay_recording", recording_replay)

    result = invoke("benchmark", "replay", str(run), "--json")

    assert result.exit_code == 0, result.stdout + result.stderr
    [settings] = resolved
    assert isinstance(settings, cli.ResolvedReview)
    assert requested == [(settings.efficiency, settings.model_view)]
    assert explanation_reads == []
