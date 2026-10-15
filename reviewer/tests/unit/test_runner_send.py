"""T015: one aware local clock for every model-status timestamp."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml

from swreview import cli
from swreview.agent import events, providers, runner
from swreview.agent.checklist import Checklist, ChecklistItem
from swreview.agent.providers import ProviderName
from swreview.agent.providers.deferred import DeferredProvider
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    EfficiencySettings,
    ProviderSettings,
    pane_defaults,
)
from swreview.chat import server
from swreview.findings import Finding
from swreview.prerun import DIGEST_ID_CAP, PrerunCall, PrerunResult
from swreview.report.session import (
    CLOSEOUT_CHECK,
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    SendEstimate,
    load_session,
)
from swreview.tools.checks_mechanical import review_roles
from tests.support.questions_package import build_questions_package
from tests.support.recording_provider import RecordingProvider, encoded_tools
from tests.unit import test_cli as cli_cases
from tests.unit.test_prerun_digest import template_finding
from tests.unit.test_session import build_session

fake_provider = cli_cases.fake_provider
CHECKED = datetime(2026, 10, 8, 9, 14, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_local_now_is_aware_and_is_the_machines_local_time_to_the_second() -> None:
    before = datetime.now(UTC).astimezone()
    actual = events.local_now()
    after = datetime.now(UTC).astimezone()
    assert actual.tzinfo is not None
    assert actual.utcoffset() == after.utcoffset()
    assert before.replace(microsecond=0) <= actual.replace(microsecond=0)
    assert actual.replace(microsecond=0) <= after.replace(microsecond=0)


class HookProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__(script=(), model="fake-1")
        self.calls: list[tuple[str, Any]] = []

    def use_model_view(self, view: Any) -> None:
        self.calls.append(("view", view))

    def use_prompt_cache(self, session_id: str) -> None:
        self.calls.append(("cache", session_id))

    def drop_prior_reasoning(self) -> None:
        self.calls.append(("drop", None))


@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize("drop", [False, True])
@pytest.mark.parametrize("view", [MODEL_VIEW_OFF, MODEL_VIEW_PANE])
def test_configure_provider_calls_the_enabled_hooks_in_order(
    cache: bool, drop: bool, view: Any
) -> None:
    session = build_session(
        efficiency=EfficiencySettings(prompt_cache_key=cache, drop_prior_reasoning=drop),
        model_view=view,
    )
    provider = HookProvider()
    runner.configure_provider(provider, session)
    expected: list[tuple[str, Any]] = [("view", view)]
    if cache:
        expected.append(("cache", str(session.session_id)))
    if drop:
        expected.append(("drop", None))
    assert provider.calls == expected


@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize("drop", [False, True])
def test_start_review_keeps_the_existing_provider_hook_calls(
    tmp_package_dir: Path, tmp_path: Path, cache: bool, drop: bool
) -> None:
    provider = HookProvider()
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "out",
        provider=provider,
        effort="high",
        efficiency=EfficiencySettings(prompt_cache_key=cache, drop_prior_reasoning=drop),
        model_view=MODEL_VIEW_PANE,
    )
    try:
        expected: list[tuple[str, Any]] = [("view", MODEL_VIEW_PANE)]
        if cache:
            expected.append(("cache", str(run.session.session_id)))
        if drop:
            expected.append(("drop", None))
        assert provider.calls == expected
    finally:
        run.close()


def test_configure_provider_calls_no_optional_hook_on_a_deferred_adapter() -> None:
    provider = DeferredProvider.for_settings(
        ProviderSettings(provider=ProviderName.FAKE, model="fake-1")
    )
    # Its three optional protocol members are deliberately absent. A call is a failure.
    runner.configure_provider(
        provider,
        build_session(
            efficiency=EfficiencySettings(prompt_cache_key=True, drop_prior_reasoning=True)
        ),
    )


# --- 015 US1: exactly the same checks, no model turn ---------------------------------------


def checks_only_run(tmp_path: Path, **changes: Any) -> runner.ReviewRun:
    fixture = build_questions_package(tmp_path)
    provider = DeferredProvider.for_settings(
        ProviderSettings(provider=ProviderName.FAKE, model="fake-1")
    )
    defaults = pane_defaults(provider.name)
    arguments = {
        "provider": provider, "standards_profile": fixture.profile,
        "bridge": True, "bridge_factory": lambda pipe, secret: fixture.bridge,
        "efficiency": defaults.efficiency, "model_view": defaults.model_view,
        "explain_findings": True, "send_when_checked": False,
        **changes,
    }
    return runner.start_review(fixture.folder, fixture.folder, **arguments)


def check_rows(run: runner.ReviewRun) -> dict[str, Any]:
    return {
        "findings": [finding.model_dump(mode="json") for finding in run.session.findings],
        "questions": [request.model_dump(mode="json") for request in run.session.evidence_requests],
        "coverage": run.session.coverage.model_dump(mode="json"),
    }


def test_checks_only_matches_the_ticked_runs_actual_first_recorded_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_questions_package(tmp_path / "ticked")
    provider = RecordingProvider([ScriptedTurn(text="FICT finished")])
    defaults = pane_defaults(provider.name)
    ticked = runner.start_review(
        fixture.folder, fixture.folder, provider=provider, standards_profile=fixture.profile,
        bridge=True, bridge_factory=lambda pipe, secret: fixture.bridge,
        efficiency=defaults.efficiency, model_view=defaults.model_view,
    )
    observed: list[dict[str, Any]] = []
    original = provider._inner.run

    def at_request(**kwargs: Any) -> Any:
        assert len(provider.log) == 1 and not provider.log[0].presentation
        observed.append(deepcopy(check_rows(ticked)))
        return original(**kwargs)

    monkeypatch.setattr(provider._inner, "run", at_request)
    ticked.start()
    waiting = checks_only_run(tmp_path / "waiting")
    try:
        first_request = provider.log[0]
        assert first_request.first_message is not None
        assert first_request.first_message["role"] == "user"
        assert waiting.system == first_request.system
        assert encoded_tools(waiting.tools) == first_request.encoded_tools
        assert tuple(
            {
                "name": tool.name, "description": tool.description,
                "parameters": deepcopy(tool.schema),
            }
            for tool in waiting.tools
        ) == first_request.tool_specs
        assert waiting.opening_message == first_request.first_message["content"]
        assert check_rows(waiting) == observed[0]
        assert len(waiting.session.evidence_requests) == 2
        assert [q.source for q in waiting.session.evidence_requests] == ["code", "code"]
        assert waiting.awaiting_send and waiting.turns == 0
        assert waiting._prerun is not None and waiting._standards_gap is None
        assert waiting.messages == []
        assert waiting.session.origin_marks == ticked.session.origin_marks
        assert len(waiting.session.steps) == len(ticked.session.steps)
        assert waiting._prerun.live.as_record() == waiting.session.live_detection
    finally:
        ticked.close()
        waiting.close()


@pytest.mark.parametrize("profile_kind", ["valid", "absent", "refused"])
def test_checks_only_records_the_document_profile_identity_and_module_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile_kind: str,
) -> None:
    monkeypatch.setattr(events, "local_now", lambda: CHECKED)
    fixture = build_questions_package(tmp_path / "run")
    profile = fixture.profile if profile_kind == "valid" else None
    if profile_kind == "refused":
        profile = tmp_path / "FICT-missing-profile.yaml"
    run = checks_only_run(tmp_path / "actual", standards_profile=profile)
    try:
        status = run.session.model_status
        assert status is not None and status.state == "not_sent"
        assert status.checked_at == CHECKED
        assert status.document == {
            "path": r"C:\Fictional\Vault\FICT-7000.SLDASM", "configuration": "Default",
        }
        if profile is None:
            assert status.profile is None
            assert "profile" not in status.model_dump(mode="json")
        else:
            assert status.profile == {
                "path": str(profile),
                "sha256": hashlib.sha256(profile.read_bytes()).hexdigest()
                if profile_kind == "valid" else None,
            }
        started = json.loads(run.events_path.read_text().splitlines()[0])
        assert started["type"] == "session.started"
        assert started["body"]["send_when_checked"] is False
    finally:
        run.close()


def test_checks_only_without_prerun_keeps_live_detection_absent(tmp_path: Path) -> None:
    run = checks_only_run(tmp_path / "run", efficiency=EfficiencySettings())
    try:
        assert run._prerun is None
        assert run.session.live_detection is None
        assert "live_detection" not in run.session.model_dump(mode="json")
    finally:
        run.close()


def test_earlier_requires_an_unticked_review_before_any_setup(
    tmp_package_dir: Path, tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="earlier"):
        runner.start_review(
            tmp_package_dir, tmp_path / "out", provider=FakeProvider(script=[], model="fake-1"),
            earlier=build_session(),
        )
    assert not (tmp_path / "out").exists()
    assert inspect.signature(runner.start_review).parameters["send_when_checked"].default is True
    assert inspect.signature(runner.start_review).parameters["earlier"].default is None


def test_checks_only_accepts_earlier_for_the_later_carry_task(tmp_path: Path) -> None:
    run = checks_only_run(tmp_path / "run", earlier=build_session())
    try:
        assert run.awaiting_send
    finally:
        run.close()


def test_not_sent_finalization_names_every_open_model_item_and_preserves_code_checks(
    tmp_path: Path,
) -> None:
    run = checks_only_run(tmp_path / "run")
    try:
        run.context.checklist = Checklist(version=1, items=(
            ChecklistItem("FICT.plain", "FICT plain", "FICT.plain", "FICT description"),
            ChecklistItem("FICT.answered", "FICT answered", "FICT.answered", "FICT description"),
            ChecklistItem("FICT.code", "FICT code", "FICT.code", "FICT description", owner="code"),
            ChecklistItem(
                CLOSEOUT_CHECK, "Close-out", CLOSEOUT_CHECK, "FICT description", owner="code"
            ),
        ))
        run.context.record_coverage("checked", CoverageItem(
            check="FICT.code", scope=CoverageScope(), reason="FICT code finished", error=None,
        ))
        run.session.evidence_requests.append(EvidenceRequest(
            id="ER-999", what="FICT evidence", why="FICT explanation", entity_ids=[],
            blocks="FICT.answered", status="answered", answer="FICT answer", answered_at=CHECKED,
        ))
        run.finalize()
        unresolved = {item.check: item.reason for item in run.session.coverage.unresolved}
        assert unresolved["FICT.plain"] == (
            "FICT plain: not reviewed, because the review was not sent to the model"
        )
        assert unresolved["FICT.answered"] == (
            "FICT answered: still open after ER-999 was answered: 'FICT answer'; "
            "the review was not sent to the model"
        )
        assert "FICT.code" not in unresolved
        assert any(item.check == "FICT.code" and item.reason == "FICT code finished"
                   for item in run.session.coverage.checked)
        assert not any(event["type"] in {"turn.started", "turn.ended", "usage"}
                       for event in map(json.loads, run.events_path.read_text().splitlines()))
    finally:
        run.close()


def test_not_sent_finalization_stamps_first_end_and_excludes_later_wait_from_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [CHECKED]
    monkeypatch.setattr(events, "local_now", lambda: clock[0])
    run = checks_only_run(tmp_path / "run")
    try:
        run.started = CHECKED - timedelta(minutes=2)
        run.session.started_at = run.started
        assert run.session.model_status.checked_at == CHECKED
        clock[0] += timedelta(minutes=3)
        run.finalize()
        first_end = clock[0]
        assert run.session.model_status.checked_at == first_end
        assert run.session.ended_at == first_end
        assert run.session.timing.unattended_runtime_minutes == 5
        assert load_session(run.session_path).model_status.checked_at == first_end
        clock[0] += timedelta(hours=1)
        run.finalize()
        assert run.session.model_status.checked_at == first_end
        assert run.session.timing.unattended_runtime_minutes == 5
    finally:
        run.close()


def test_not_sent_finalization_makes_no_presentation_request_before_a_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a waiting review must not make a presentation request")

    monkeypatch.setattr(DeferredProvider, "run", forbidden)
    monkeypatch.setattr(DeferredProvider, "for_presentation", forbidden)
    run = checks_only_run(tmp_path / "run")
    try:
        assert run.session.explanations_enabled
        assert run.session.findings
        run.finalize()
        assert run.session.finding_explanations == {}
        assert run.session.finding_explanation_fingerprint is None
        assert run.turns == 0
    finally:
        run.close()


def test_command_line_review_keeps_its_literal_lines_json_shape_and_options(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Any,
) -> None:
    fake_provider()
    out = tmp_path / "text"
    result = cli_cases.invoke(
        "review", str(tmp_package_dir), "--out", str(out), "--provider", "fake"
    )
    assert result.exit_code == 0, result.stdout
    session = load_session(out / "session.json")
    assert result.stdout.splitlines() == [
        f"reviewed {session.design_id} with fake {session.model}",
        f"{len(session.findings)} findings, {len(session.evidence_requests)} evidence requests, "
        f"{len(session.steps)} tool calls",
        f"session: {out.resolve() / 'session.json'}", f"report: {out.resolve() / 'report.md'}",
    ]
    assert session.model_status is None
    json_out = tmp_path / "json"
    result = cli_cases.invoke(
        "review", str(tmp_package_dir), "--out", str(json_out), "--provider", "fake", "--json",
    )
    assert result.exit_code == 0, result.stdout
    assert set(json.loads(result.stdout)) == {
        "package_dir", "out_dir", "session_file", "report_file", "provider", "model",
        "findings", "evidence_requests", "steps", "coverage",
    }
    result = cli_cases.invoke("review", "--help")
    assert result.exit_code == 0
    assert "--send" not in result.stdout and "--recheck" not in result.stdout


@contextmanager
def waiting_cache_run(
    tmp_path: Path,
    *,
    provider_name: ProviderName = ProviderName.FAKE,
    profile_mode: Literal["present", "absent", "refused"] = "present",
    efficiency: EfficiencySettings | None = None,
    deferred: bool = False,
) -> Iterator[ReviewRun]:
    """Real pane-default checks, kept before any turn or waiting finalization."""
    fixture = build_questions_package(tmp_path / "questions")
    profile: Path | None = fixture.profile
    if profile_mode == "absent":
        profile = None
    elif profile_mode == "refused":
        document = yaml.safe_load(fixture.profile.read_text(encoding="utf-8"))
        document["version"] = 99
        fixture.profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    if deferred:
        model = {
            ProviderName.OPENAI: "gpt-5.6",
            ProviderName.GEMINI: "gemini-2.5-pro",
            ProviderName.FAKE: "fake-scripted",
        }[provider_name]
        provider = DeferredProvider.for_settings(
            ProviderSettings(provider=provider_name, model=model)
        )
    else:
        provider = RecordingProvider(())
        provider.name = provider_name
    defaults = pane_defaults(provider_name)
    run = start_review(
        fixture.folder,
        fixture.folder,
        provider=provider,
        standards_profile=profile,
        bridge=True,
        bridge_factory=lambda pipe, secret: fixture.bridge,
        efficiency=efficiency if efficiency is not None else defaults.efficiency,
        model_view=defaults.model_view,
        explain_findings=defaults.explain_findings,
        send_when_checked=False,
    )
    try:
        yield run
    finally:
        run.close()


@pytest.mark.usefixtures("vocabulary")
def test_build_send_cache_keeps_the_complete_opening_estimate_and_named_ids(tmp_path: Path) -> None:
    with waiting_cache_run(tmp_path) as run:
        assert run._send_cache is None
        assert run._prerun is not None
        opening = run.opening_message

        run.build_send_cache()

        cache = run._send_cache
        assert isinstance(cache, runner.SendCache)
        assert cache.opening == opening
        assert isinstance(cache.estimate, SendEstimate)
        assert cache.named_ids == run._prerun.named_finding_ids()
        assert isinstance(run.provider, RecordingProvider)
        assert run.provider.log == []
        assert run.session.ended_at is None


@pytest.mark.usefixtures("vocabulary")
def test_a_run_without_checks_first_caches_an_empty_named_id_list(tmp_path: Path) -> None:
    with waiting_cache_run(tmp_path, efficiency=EfficiencySettings()) as run:
        assert run._prerun is None

        run.build_send_cache()

        assert run._send_cache is not None
        assert run._send_cache.opening == run.opening_message
        assert run._send_cache.named_ids == []


@pytest.mark.usefixtures("vocabulary")
def test_close_waiting_builds_once_before_finalization_on_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with waiting_cache_run(tmp_path) as run:
        called: list[str] = []
        build = run.build_send_cache
        finalize = run.finalize

        def observed_build() -> None:
            called.append("build")
            build()

        def observed_finalize() -> Any:
            called.append("finalize")
            assert run._send_cache is not None
            return finalize()

        monkeypatch.setattr(run, "build_send_cache", observed_build)
        monkeypatch.setattr(run, "finalize", observed_finalize)

        run.close_waiting()
        run.close_waiting()

        assert called == ["build", "finalize", "build", "finalize"]
        assert run.session.ended_at is not None
        assert isinstance(run.provider, RecordingProvider)
        assert run.provider.log == []


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize("profile_mode", ["present", "absent", "refused"])
def test_waiting_finalization_preserves_the_frozen_opening_and_its_builder_inputs(
    tmp_path: Path, profile_mode: Literal["present", "absent", "refused"]
) -> None:
    with waiting_cache_run(tmp_path, profile_mode=profile_mode) as run:
        frozen = run.opening_message
        assert run.opening_at_send() == frozen
        assert run._prerun is not None
        if profile_mode == "absent":
            # Setup records raw standards coverage, but the existing package brief was
            # given no gap without a profile argument. Store that same effective input.
            assert run._standards_gap is None
        elif profile_mode == "refused":
            assert run._standards_gap is not None

        run.close_waiting()

        rebuilt = runner._opening_message(
            run._prerun,
            run.session,
            run.context.ir,
            standards_gap=run._standards_gap,
            roles=review_roles(run.context),
        )
        assert run._send_cache is not None
        assert run._send_cache.opening == frozen == rebuilt == run.opening_at_send()


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize("failure_at", ["estimate", "named_ids"])
def test_a_failed_rebuild_leaves_the_previous_send_cache_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_at: str
) -> None:
    with waiting_cache_run(tmp_path) as run:
        run.build_send_cache()
        previous = run._send_cache
        expected = deepcopy(previous)

        def failed(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("cache preparation failed")

        if failure_at == "estimate":
            monkeypatch.setattr(run, "first_request_estimate", failed)
        else:
            monkeypatch.setattr(PrerunResult, "named_finding_ids", failed)

        with pytest.raises(RuntimeError, match="cache preparation failed"):
            run.build_send_cache()

        assert run._send_cache is previous
        assert run._send_cache == expected
        assert run.session.ended_at is None


def test_close_waiting_is_the_only_production_caller_of_build_send_cache() -> None:
    """71A: routes and Send must read the worker's cache, rather than rebuilding it."""
    callers: list[tuple[str, str | None]] = []

    def visit(node: ast.AST, module: str, function: str | None = None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name
        if isinstance(node, ast.Call):
            called = node.func
            if (
                isinstance(called, ast.Attribute)
                and called.attr == "build_send_cache"
                or isinstance(called, ast.Name)
                and called.id == "build_send_cache"
            ):
                callers.append((module, function))
        for child in ast.iter_child_nodes(node):
            visit(child, module, function)

    for module, source in [("runner", runner), ("server", server)]:
        assert source.__file__ is not None
        visit(ast.parse(Path(source.__file__).read_text(encoding="utf-8")), module)

    assert callers == [("runner", "close_waiting")]


def named_id_prerun() -> PrerunResult:
    """Interleaved statuses, separate calls, one capped group and a folded family."""
    template = template_finding()

    def finding(number: int, check: str, status: str = "demonstrated") -> Finding:
        return template.model_copy(
            update={"id": f"F-{number:04d}", "check": check, "status": status}
        )

    first = (
        finding(1, "hygiene.name"),
        finding(200, "rms.hole"),
        finding(100, "interference.static", "suspected"),
        finding(2, "hygiene.name"),
        finding(50, "hygiene.name", "suspected"),
    )
    second = tuple(finding(number, "hygiene.name") for number in range(3, DIGEST_ID_CAP + 3))
    calls = tuple(
        PrerunCall(tool="check_x", arguments={}, step_index=index, findings=rows, error=None)
        for index, rows in enumerate((first, second))
    )
    return PrerunResult(calls=calls, not_evaluated=(), families=("rms",))


def test_named_finding_ids_follow_the_actual_digest_order_and_each_groups_cap() -> None:
    prerun = named_id_prerun()
    expected = [f"F-{number:04d}" for number in range(1, DIGEST_ID_CAP + 1)]
    expected += ["F-0100", "F-0050"]

    assert prerun.named_finding_ids() == expected
    assert re.findall(r"F-\d+", "\n".join(prerun._finding_lines())) == expected
    assert re.findall(r"F-\d+", prerun.digest()) == expected
    assert "and 2 more" in prerun.digest()
    assert "F-0200" not in prerun.digest()


def test_a_family_names_its_ids_only_when_it_is_not_folded() -> None:
    folded = named_id_prerun()
    ordinary = PrerunResult(calls=folded.calls, not_evaluated=(), families=())
    expected = [f"F-{number:04d}" for number in range(1, DIGEST_ID_CAP + 1)]
    expected += ["F-0200", "F-0100", "F-0050"]

    assert ordinary.named_finding_ids() == expected
    assert re.findall(r"F-\d+", ordinary.digest()) == expected


def test_no_prerun_findings_means_no_named_ids() -> None:
    prerun = PrerunResult(calls=(), not_evaluated=())

    assert prerun.named_finding_ids() == []


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize("provider_name", list(ProviderName))
def test_real_deferred_cache_and_close_use_no_factory_sdk_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: ProviderName
) -> None:
    import httpx
    import openai
    from google import genai

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("FICT-unticked-cache-touched-provider-or-network")

    for name in (*server.KEY_VARIABLES, "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "provider_factory", forbidden)
    monkeypatch.setattr(server, "build_provider", forbidden)
    monkeypatch.setattr(providers, "get", forbidden)
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(openai, "AsyncOpenAI", forbidden)
    monkeypatch.setattr(genai, "Client", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    with waiting_cache_run(tmp_path, provider_name=provider_name, deferred=True) as run:
        assert isinstance(run.provider, DeferredProvider)
        frozen = run.opening_message
        run.build_send_cache()
        cache = run._send_cache
        assert cache is not None and cache.opening == frozen
        assert cache.estimate.input_tokens is not None and cache.estimate.input_tokens > 0
        assert cache.estimate.approximate == (provider_name == ProviderName.GEMINI)
        assert run.session.ended_at is None
        assert run.turns == 0
        session = run.close_waiting()
        assert session is run.session
        assert session.ended_at is not None
        assert session.model_status is not None
        assert session.model_status.state == "not_sent"
        assert session.model_status.sent_at is None
        assert run._send_cache == cache
        assert run.turns == 0
# T062/T063: Send prepares without writes, commits in order, and pins the actual provider boundary.


def send_recorder() -> RecordingProvider:
    from swreview.agent.providers.fake import ScriptedToolCall

    return RecordingProvider(
        [
            ScriptedTurn(
                text="FICT checked",
                tool_calls=(
                    ScriptedToolCall(
                        "mark_coverage",
                        {
                            "check": "drawing.context",
                            "bucket": "checked",
                            "reason": "FICT reviewed",
                        },
                    ),
                    ScriptedToolCall(
                        "request_evidence",
                        {
                            "what": "FICT depth",
                            "why": "FICT needs drawing",
                            "entity_ids": ["doc:0002"],
                        },
                    ),
                    ScriptedToolCall("get_review_checklist", {}),
                ),
            ),
            ScriptedTurn(text="FICT answer"),
        ],
        explanation_script=[ScriptedTurn(text="FICT explanation")],
        clock=lambda: 0.0,
    )


def test_send_preparation_changes_nothing_and_commit_withdraws_only_its_own_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.support.restart import disk_at, restarted_app
    from tests.support.restored import assert_restored_as_waiting
    from tests.unit import test_chat_server as chat_cases

    clock = [CHECKED]
    monkeypatch.setattr(events, "local_now", lambda: clock[0])
    run = checks_only_run(tmp_path / "FICT-send")
    try:
        run.started = CHECKED - timedelta(minutes=2)
        run.session.started_at = run.started
        run.close_waiting()
        checked = run.session.model_status.checked_at
        before = run.session.model_dump(mode="json")
        raw = run.session_path.read_bytes()
        old_events = run.events_path.read_bytes()
        previous = tuple(run._finalized)
        unrelated = CoverageItem(
            check="FICT.other", scope=CoverageScope(), reason="FICT unrelated", error=None
        )
        run.session.coverage.checked.append(unrelated)
        before = run.session.model_dump(mode="json")
        provider = send_recorder()
        order: list[str] = []
        save = runner.save_session
        configure = runner.configure_provider
        withdraw = runner.withdraw_finalization
        with (
            disk_at(run.out_dir, "before-first-usage") as before_usage,
            disk_at(run.out_dir, "after-first-usage-save") as after_usage,
        ):

            def configured(adapter: Any, session: Any) -> None:
                assert adapter is provider
                assert run.session.model_dump(mode="json") == before
                assert run.session_path.read_bytes() == raw
                assert run.events_path.read_bytes() == old_events
                assert isinstance(run.provider, DeferredProvider)
                order.append("configure")
                configure(adapter, session)

            def factory() -> Any:
                assert run.session.model_dump(mode="json") == before
                assert run.session_path.read_bytes() == raw
                assert run.events_path.read_bytes() == old_events
                order.append("factory")
                return provider

            def saved(session: Any, path: Path) -> None:
                if session.model_status.state == "send_failed":
                    assert order[-1] == "session.sent"
                    assert session.ended_at is not None
                    assert session.model_status.failures[-1].error_class == "Interrupted"
                    assert session.model_status.failures[-1].reason == runner.INTERRUPTED_SEND
                    assert all(
                        any(
                            row is old
                            for row in session.coverage.checked + session.coverage.unresolved
                        )
                        for old in previous
                    )
                    order.append("prewrite")
                elif session.model_status.state == "sent" and session.ended_at is None:
                    assert run._send_in_flight is False
                    assert session.model_status.checked_at == checked
                    assert session.model_status.sent_at == CHECKED + timedelta(hours=1)
                    assert session.model_status.estimate == run._send_cache.estimate
                    assert session.model_status.opening_finding_ids == run._send_cache.named_ids
                    assert not any(
                        f.error_class == "Interrupted" for f in session.model_status.failures
                    )
                    assert unrelated in session.coverage.checked
                    assert not any(
                        row is old
                        for row in session.coverage.checked + session.coverage.unresolved
                        for old in previous
                    )
                    order.append("first-usage-save")
                save(session, path)
                if session.model_status.state == "sent" and session.ended_at is None:
                    after_usage()

            def withdrawn(session: Any, written: Any) -> None:
                committing = session.model_status.state == "send_failed"
                if committing:
                    assert order[-1] == "prewrite"
                withdraw(session, written)
                assert not written
                if committing:
                    order.append("withdraw")

            original_run = provider.run

            def requested(**kwargs: Any) -> Any:
                assert order[-1] == "withdraw"
                before_usage()
                assert provider._inner._step_index == len(run.session.steps)
                return original_run(**kwargs)

            monkeypatch.setattr(runner, "configure_provider", configured)
            monkeypatch.setattr(runner, "save_session", saved)
            monkeypatch.setattr(runner, "withdraw_finalization", withdrawn)
            monkeypatch.setattr(provider, "run", requested)
            run.sink.add_listener(
                lambda event: order.append(event.type) if event.type == "session.sent" else None
            )
            clock[0] += timedelta(hours=1)
            run.send(factory)
            assert order[:5] == ["factory", "configure", "session.sent", "prewrite", "withdraw"]
            assert "first-usage-save" in order
            interrupted = load_session(before_usage.folder / "session.json")
            assert interrupted.model_status.state == "send_failed"
            assert interrupted.model_status.failures[-1].reason == runner.INTERRUPTED_SEND
            sent = load_session(after_usage.folder / "session.json")
            assert sent.model_status.state == "sent" and sent.ended_at is None
            with restarted_app(
                after_usage.root,
                {"token": chat_cases.TOKEN, "allow_origin": chat_cases.ORIGIN, "development": True},
            ) as fresh:
                restored = fresh.get(f"/reviews/{after_usage.folder.name}")
                assert restored.status_code == 200, restored.text
                assert restored.json()["read_only"] is True
            # 015 T099: the copy a kill before the first usage leaves is restored as the
            # `send_failed` record it holds, read-only with its dated line and Send.
            with restarted_app(
                before_usage.root,
                {"token": chat_cases.TOKEN, "allow_origin": chat_cases.ORIGIN, "development": True},
            ) as fresh:
                restored = fresh.get(f"/reviews/{before_usage.folder.name}")
                assert restored.status_code == 200, restored.text
                assert_restored_as_waiting(restored.json(), interrupted)
            assert run.session.model_status.checked_at == checked
            assert run.session.timing.unattended_runtime_minutes == 2
            assert sum(entry.presentation for entry in provider.log) == 1
    finally:
        run.close()


def _views_agree_with_the_record(folder: Path, ir: Any) -> str:
    """The report a folder holds, checked against a render of the `session.json` beside it,
    and its `attention.json` against that record's id: the two views say what the record says."""
    from swreview.report.attention import rank
    from swreview.report.attention_record import read_attention_record
    from swreview.report.markdown import render_report

    record = load_session(folder / "session.json")
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert report == render_report(record, ir, ranking=rank(record))
    assert read_attention_record(folder).session_id == record.session_id
    return report


def test_a_kill_after_sends_pre_write_or_first_usage_leaves_a_report_that_agrees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-032 (owner decision 98A item 1): the report says what the record says at both of
    Send's mid-turn saves, so a kill at either one leaves no report that contradicts it."""
    from swreview.report.attention import rank
    from swreview.report.markdown import render_report
    from tests.support.restart import disk_at

    clock = [CHECKED]
    monkeypatch.setattr(events, "local_now", lambda: clock[0])
    run = checks_only_run(tmp_path / "FICT-send-report")
    try:
        run.started = CHECKED - timedelta(minutes=2)
        run.session.started_at = run.started
        run.close_waiting()
        # What `_open_waiting` leaves beside the waiting record.
        (run.out_dir / "report.md").write_text(
            render_report(run.session, run.context.ir, ranking=rank(run.session)),
            encoding="utf-8",
        )
        assert "- Model: not sent to the model (checked by code only)" in (
            run.out_dir / "report.md"
        ).read_text(encoding="utf-8")
        provider = send_recorder()
        withdraw = runner.withdraw_finalization
        emit_turn_event = ReviewRun._emit_turn_event
        with (
            disk_at(run.out_dir, "after-pre-write") as after_pre_write,
            disk_at(run.out_dir, "after-first-usage") as after_usage,
        ):

            def withdrawn(session: Any, written: Any) -> None:
                if session.model_status.state == "send_failed":
                    after_pre_write()
                withdraw(session, written)

            def handled(self: ReviewRun, event_type: Any, body: Any) -> None:
                emit_turn_event(self, event_type, body)
                if event_type == "usage":
                    after_usage()

            monkeypatch.setattr(runner, "withdraw_finalization", withdrawn)
            monkeypatch.setattr(ReviewRun, "_emit_turn_event", handled)
            clock[0] += timedelta(hours=1)
            run.send(lambda: provider)
            monkeypatch.undo()

            interrupted = _views_agree_with_the_record(after_pre_write.folder, run.context.ir)
            assert (
                "- Model: not sent to the model; the last attempt failed at "
                f"{(CHECKED + timedelta(hours=1)).isoformat()}: {runner.INTERRUPTED_SEND}"
            ) in interrupted
            sent = _views_agree_with_the_record(after_usage.folder, run.context.ir)
            assert f"- Model: {run.session.model}" in sent
            assert f"- Sent to the model: {(CHECKED + timedelta(hours=1)).isoformat()}" in sent
            assert "not sent to the model" not in sent
    finally:
        run.close()


def test_withdraw_finalization_is_shared_by_finalize_and_send() -> None:
    assert "withdraw_finalization(" in inspect.getsource(runner.finalize_session)
    assert "withdraw_finalization(" in inspect.getsource(ReviewRun.send)
    assert "coverage.unresolved[:]" not in inspect.getsource(ReviewRun.send)
    session = build_session()
    old = CoverageItem(check="FICT.old", scope=CoverageScope(), reason="same", error=None)
    equal = old.model_copy(deep=True)
    session.coverage.checked[:] = [old, equal]
    written = [old]
    runner.withdraw_finalization(session, written)
    assert len(session.coverage.checked) == 1 and session.coverage.checked[0] is equal
    assert written == []


@pytest.mark.usefixtures("vocabulary")
def test_every_sent_request_and_tool_result_equals_ticked_and_counted_prefix(
    tmp_path: Path,
) -> None:
    from swreview.agent.providers.openai_provider import _encode_history

    waiting = checks_only_run(tmp_path / "FICT-wait")
    ticked_provider = send_recorder()
    fixture = build_questions_package(tmp_path / "FICT-tick")
    defaults = pane_defaults(ProviderName.FAKE)
    ticked = start_review(
        fixture.folder,
        fixture.folder,
        provider=ticked_provider,
        standards_profile=fixture.profile,
        bridge=True,
        bridge_factory=lambda pipe, secret: fixture.bridge,
        efficiency=defaults.efficiency,
        model_view=defaults.model_view,
        explain_findings=True,
    )
    provider = send_recorder()
    try:
        waiting.close_waiting()
        shown = waiting.send_input()["input_tokens"]
        waiting.send(lambda: provider)
        ticked.start()
        assert provider.log == ticked_provider.log
        assert _encode_history(waiting.messages) == _encode_history(ticked.messages)
        assert len([message for message in waiting.messages if message["role"] == "tool"]) == 3
        first = provider.log[0]
        # Specs come from the actual recorder, not from the waiting cache.
        specs = tuple(
            __import__("types").SimpleNamespace(
                name=row["name"], description=row["description"], schema=row["parameters"]
            )
            for row in first.tool_specs
        )
        count = runner.tokens.count_tokens(
            runner.request_prefix(first.system, specs, first.first_message["content"])
        )
        assert count == shown == waiting.session.model_status.estimate.input_tokens
        sent = next(
            json.loads(line)
            for line in waiting.events_path.read_text().splitlines()
            if json.loads(line)["type"] == "session.sent"
        )
        assert sent["body"]["estimate"]["input_tokens"] == count
        assert set(sent["body"]) == {"provider", "model", "effort_mapping", "estimate"}
        assert sum(entry.presentation for entry in provider.log) == 1
        waiting.answer_evidence(waiting.session.evidence_requests[-1].id, "FICT 12 mm")
        ticked.answer_evidence(ticked.session.evidence_requests[-1].id, "FICT 12 mm")
        assert provider.log == ticked_provider.log
    finally:
        waiting.close()
        ticked.close()


# T065: failure guard snapshots before the factory and restores waiting before error.
class FictSendError(RuntimeError):
    pass


@pytest.mark.parametrize("point", ["factory", "configure", "mapping", "event", "save"])
@pytest.mark.parametrize("prior_failure", [False, True])
def test_send_guard_restores_the_exact_record_at_each_pre_request_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
    prior_failure: bool,
) -> None:
    from swreview.report.session import SendFailure

    run = checks_only_run(tmp_path / f"FICT-guard-{point}-{prior_failure}")
    try:
        run.close_waiting()
        status = run.session.model_status
        assert status is not None
        if prior_failure:
            status.state = "send_failed"
            status.failures.append(
                SendFailure(at=CHECKED, error_class="FICT-prior", reason="FICT prior")
            )
            runner.save_session(run.session, run.session_path)
        before = status.model_copy(deep=True)
        raw = run.session_path.read_bytes()
        marker = run.sink.seq
        provider = send_recorder()
        errors: list[Any] = []
        writes: list[Any] = []
        save = runner.save_session
        emit = run.sink.emit

        def refused(*args: Any, **kwargs: Any) -> Any:
            assert run.session.model_status == before or point == "save"
            raise FictSendError("FICT secret")

        def event(kind: Any, body: Any) -> Any:
            if kind == "error":
                assert run.awaiting_send and not run._send_in_flight
                assert isinstance(run.provider, DeferredProvider)
                assert run.session.model_status == before
                assert run._send_error.reason == "FICT redacted"
                errors.append(body)
            if kind == "session.sent" and point == "event":
                refused()
            return emit(kind, body)

        def saved(session: Any, path: Path) -> Any:
            writes.append(session.model_status.model_copy(deep=True))
            if point == "save":
                refused()
            return save(session, path)

        with monkeypatch.context() as patch:
            patch.setattr(
                run, "redact", lambda text: text.replace("FICT secret", "FICT redacted")
            )
            patch.setattr(run.sink, "emit", event)
            patch.setattr(runner, "save_session", saved)
            if point == "configure":
                patch.setattr(runner, "configure_provider", refused)
            elif point == "mapping":
                patch.setattr(provider, "effort_mapping", refused)
            result = run.send(refused if point == "factory" else lambda: provider)
        assert result is run.session
        assert run.session_path.read_bytes() == raw
        assert run.session.model_status == before
        assert run.messages == [] and isinstance(run.provider, DeferredProvider)
        assert run.awaiting_send and not run._send_in_flight and provider.log == []
        tail = [
            event
            for event in events.replay_events(run.events_path)
            if event.seq > marker
        ]
        assert [event.type for event in tail] == (
            ["session.sent"] if point == "save" else []
        ) + ["error"]
        assert len(errors) == 1 and errors[0]["error_class"] == "FictSendError"
        assert len(writes) == (1 if point == "save" else 0)
        assert run.send_input()["send_error"].reason == "FICT redacted"
        retry = send_recorder()
        run.send(lambda: retry)
        assert run.session.model_status.state == "sent" and not run.awaiting_send
        assert run._send_error is None
        assert [
            failure.error_class for failure in run.session.model_status.failures
        ] == (["FICT-prior"] if prior_failure else [])
        assert sum(not entry.presentation for entry in retry.log) == 1
    finally:
        run.close()


def test_send_guard_logs_its_own_error_emit_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run = checks_only_run(tmp_path / "FICT-guard-error")
    try:
        run.close_waiting()
        raw = run.session_path.read_bytes()
        emit = run.sink.emit

        def fail(*args: Any, **kwargs: Any) -> Any:
            raise FictSendError("FICT own emit")

        with monkeypatch.context() as patch:
            patch.setattr(run.sink, "emit", fail)
            assert run.send(fail) is run.session
        assert "FICT own emit" in caplog.text
        assert run.awaiting_send and not run._send_in_flight
        assert run.session_path.read_bytes() == raw
        assert isinstance(run.provider, DeferredProvider)
        assert run.sink.emit == emit
        run.send(send_recorder)
        assert run.session.model_status.state == "sent"
    finally:
        run.close()


@pytest.mark.parametrize("after_usage", [False, True])
def test_failed_first_request_is_waiting_only_before_a_completed_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_usage: bool,
) -> None:
    from swreview.agent.providers import TokenUsage, usage_body
    from swreview.agent.providers.openai_provider import _encode_history

    run = checks_only_run(tmp_path / f"FICT-request-failure-{after_usage}")
    ticked_fixture = build_questions_package(
        tmp_path / f"FICT-ticked-retry-{after_usage}"
    )
    try:
        run.close_waiting()
        checked = run.session.model_status.checked_at
        provider = RecordingProvider((), clock=lambda: 0.0)
        error_states: list[Any] = []
        original_emit = run.sink.emit

        def request(**kwargs: Any) -> Any:
            kwargs["on_event"]("text.delta", {"text": "FICT streamed before failure"})
            if after_usage:
                kwargs["on_event"](
                    "usage",
                    usage_body(
                        TokenUsage(
                            input_tokens=7,
                            output_tokens=1,
                            cached_input_tokens=None,
                            cache_write_tokens=None,
                            reasoning_tokens=None,
                            tool_result_input_tokens=None,
                            total_tokens=8,
                            latency_s=0.0,
                        ),
                        round_index=0,
                        provider=provider.name,
                        model=provider.model,
                    ),
                )
            raise FictSendError("FICT secret")

        def emitted(kind: Any, body: Any) -> Any:
            if kind == "error":
                error_states.append(
                    (
                        run.awaiting_send,
                        run._send_in_flight,
                        run.messages.copy(),
                        run.provider,
                    )
                )
            return original_emit(kind, body)

        with monkeypatch.context() as patch:
            patch.setattr(provider._inner, "run", request)
            patch.setattr(run.sink, "emit", emitted)
            patch.setattr(
                run, "redact", lambda text: text.replace("FICT secret", "FICT redacted")
            )
            if after_usage:
                with pytest.raises(FictSendError):
                    run.send(lambda: provider)
            else:
                assert run.send(lambda: provider) is run.session
        assert len(provider.log) == 1
        assert run.session.model_status.checked_at == checked
        if after_usage:
            assert run.session.model_status.state == "sent" and not run.awaiting_send
            assert error_states[0][0:2] == (False, False)
        else:
            assert run.session.model_status.state == "send_failed" and run.awaiting_send
            assert error_states[0][0:3] == (True, False, [])
            assert isinstance(error_states[0][3], DeferredProvider)
            assert (
                run.provider.name == provider.name
                and run.provider.model == provider.model
            )
            assert [
                failure.error_class for failure in run.session.model_status.failures
            ] == ["FictSendError"]
            assert run.session.model_status.failures[0].reason == "FICT redacted"
            assert run.usage_ledger.current_round_count == 0
            assert run.messages == []
            own_rows = tuple(run._finalized)
            retry = send_recorder()
            requested = retry._inner.run

            def first(**kwargs: Any) -> Any:
                assert not any(
                    row is old
                    for row in run.session.coverage.unresolved
                    + run.session.coverage.checked
                    for old in own_rows
                )
                assert len(kwargs["messages"]) == 1
                return requested(**kwargs)

            monkeypatch.setattr(retry._inner, "run", first)
            run.send(lambda: retry)
            ticked_provider = send_recorder()
            defaults = pane_defaults(ticked_provider.name)
            ticked = runner.start_review(
                ticked_fixture.folder,
                ticked_fixture.folder,
                provider=ticked_provider,
                standards_profile=ticked_fixture.profile,
                bridge=True,
                bridge_factory=lambda pipe, secret: ticked_fixture.bridge,
                efficiency=defaults.efficiency,
                model_view=defaults.model_view,
                explain_findings=True,
            )
            try:
                ticked.start()
                assert retry.log == ticked_provider.log
                assert _encode_history(run.messages) == _encode_history(ticked.messages)
            finally:
                ticked.close()
            assert [
                failure.error_class for failure in run.session.model_status.failures
            ] == ["FictSendError"]
        tail = list(events.replay_events(run.events_path))
        assert any(
            event.type == "text.delta"
            and event.body["text"] == "FICT streamed before failure"
            for event in tail
        )
        assert any(
            event.type == "turn.ended" and event.body["reason"] == "error"
            for event in tail
        )
    finally:
        run.close()


# --- 015 US3: rebuilding an untouched opening preserves the frozen pin --------------------


def test_the_opening_builder_reproduces_the_frozen_opening_without_waiting_answers(
    tmp_path: Path,
) -> None:
    run = checks_only_run(tmp_path)
    try:
        assert runner._opening_message(
            run._prerun, run.session, run.context.ir,
            standards_gap=run._standards_gap, roles=review_roles(run.context),
        ) == run.opening_message
    finally:
        run.close()


def test_restating_nothing_keeps_the_frozen_builder_byte_equal(tmp_path: Path) -> None:
    from swreview import prerun

    run = checks_only_run(tmp_path)
    try:
        original = run._prerun
        rebuilt = prerun.restated(original, run.context, (), run._standards_gap)
        assert rebuilt is original
        assert runner._opening_message(
            rebuilt, run.session, run.context.ir,
            standards_gap=run._standards_gap, roles=review_roles(run.context),
        ) == run.opening_message
    finally:
        run.close()
