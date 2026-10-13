"""US3: code applies waiting answers without a model turn, and preserves the work."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from swreview import prerun, tokens
from swreview.agent import runner
from swreview.agent.events import replay_events
from swreview.agent.providers.deferred import DeferredProvider
from swreview.agent.runner import request_prefix
from swreview.bridge.client import BridgeError
from swreview.checks.drawing_context import CANDIDATE_CONFIRM
from swreview.report.attention import family_counts, family_of
from swreview.report.session import load_session
from swreview.report.summary import load_words
from swreview.tools.model_view import count_findings
from tests.support.questions_package import QuestionsPackage, build_questions_package
from tests.support.recording_provider import RecordingProvider
from tests.support.roles_review import PIN_ID
from tests.unit import test_chat_server as chat
from tests.unit import test_send_gate_server as send_cases
from tests.unit.test_chat_timing_route import FOUR

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
pipe_app = send_cases.pipe_app
pipe_client = send_cases.pipe_client


@dataclass(frozen=True)
class Waiting:
    fixture: QuestionsPackage
    chat_id: str
    held: Any

    @property
    def run(self) -> runner.ReviewRun:
        return self.held.run


def waiting_review(app: Any, client: TestClient, folder: Path) -> Waiting:
    fixture = build_questions_package(folder)
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    response = client.post(
        "/sessions",
        json=chat.session_body(
            folder,
            standards_profile=str(fixture.profile),
            bridge={"pipe": "FICT-pipe", "secret": "FICT-secret"},
            send_when_checked=False,
        ),
    )
    assert response.status_code == 201, response.text
    chat_id = str(response.json()["chat_id"])
    assert chat.state_of(client, chat_id) == "awaiting_send"
    return Waiting(fixture, chat_id, app.state.server.chats[UUID(chat_id)])


def question(waiting: Waiting, *, drawing: bool = False) -> Any:
    return next(
        item
        for item in waiting.run.session.evidence_requests
        if (CANDIDATE_CONFIRM in item.options) == drawing
    )


def apply(client: TestClient, waiting: Waiting, *answers: tuple[str, str]) -> Any:
    return client.post(
        f"/sessions/{waiting.chat_id}/evidence",
        json={"answers": [{"request_id": rid, "answer": answer} for rid, answer in answers]},
    )


def new_events(waiting: Waiting, marker: int) -> list[Any]:
    return [event for event in replay_events(waiting.run.events_path) if event.seq > marker]


def test_all_bought_regrades_and_withdraws_without_building_a_provider_or_turn(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-all-bought")
    run = waiting.run
    pin_components = {item.id for item in run.context.ir.components if item.document_id == PIN_ID}
    role_steps = {step.index for step in run.session.steps if step.tool in runner.ROLES_RESTATED}
    withdrawn = [
        f.id
        for f in run.session.findings
        if set(f.component_ids) & pin_components and set(f.tool_result_ids) & role_steps
    ]
    assert withdrawn
    remaining = [f.id for f in run.session.findings if f.id not in withdrawn]
    marker = run.sink.seq
    answer = question(waiting)

    response = apply(client, waiting, (answer.id, "All bought"))
    assert response.status_code == 202, response.text
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    events = new_events(waiting, marker)
    assert [
        event.body["finding_id"] for event in events if event.type == "finding.withdrawn"
    ] == withdrawn
    assert [f.id for f in run.session.findings] == remaining
    assert provider_control.built == []
    assert isinstance(run.provider, DeferredProvider)
    assert run.messages == [] and run.turns == 0 and run.awaiting_send
    assert not any(event.type.startswith("turn.") for event in events)


def test_the_applied_record_report_attention_and_summary_replace_the_waiting_review(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-records")
    run = waiting.run
    before = {
        name: (run.out_dir / name).read_bytes()
        for name in ("session.json", "report.md", "attention.json")
    }
    marker = run.sink.seq
    response = apply(client, waiting, (question(waiting).id, "All bought"))
    assert response.status_code == 202, response.text
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    saved = load_session(run.session_path)
    assert saved == run.session
    assert saved.evidence_requests[0].status == "answered"
    assert saved.model_status.state == "not_sent"
    assert all((run.out_dir / name).read_bytes() != raw for name, raw in before.items())
    assert [event.type for event in new_events(waiting, marker)].count("session.ended") == 1
    report = (run.out_dir / "report.md").read_text(encoding="utf-8")
    assert "- Model: not sent to the model (checked by code only)" in report
    attention = json.loads((run.out_dir / "attention.json").read_bytes())
    assert attention["session_id"] == str(saved.session_id)
    snapshot = client.get(f"/sessions/{waiting.chat_id}/snapshot").json()
    summary = snapshot["ranking"]["summary"]
    assert summary["resume_text"] == load_words().send.apply_answers
    assert summary["send"]["state"] == "waiting"
    assert [f["id"] for f in snapshot["findings"]] == [f.id for f in saved.findings]
    assert provider_control.built == []


def test_the_apply_replaces_the_cache_once_on_its_worker_before_finalization(
    app: Any,
    client: TestClient,
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-cache")
    run = waiting.run
    old_cache = run._send_cache
    order: list[tuple[str, int]] = []
    close, build, finalize = run.close_waiting, run.build_send_cache, run.finalize
    loop: list[int] = []
    require_idle = app.state.server._require_idle

    def on_loop(held: Any) -> None:
        loop.append(threading.get_ident())
        return require_idle(held)

    def closed() -> Any:
        order.append(("close", threading.get_ident()))
        return close()

    def built() -> None:
        order.append(("build", threading.get_ident()))
        build()

    def finalized() -> Any:
        order.append(("finalize", threading.get_ident()))
        return finalize()

    monkeypatch.setattr(app.state.server, "_require_idle", on_loop)
    monkeypatch.setattr(run, "close_waiting", closed)
    monkeypatch.setattr(run, "build_send_cache", built)
    monkeypatch.setattr(run, "finalize", finalized)
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    assert [name for name, _ in order] == ["close", "build", "finalize"]
    assert len({identity for _, identity in order}) == 1
    assert loop and order[0][1] not in loop
    worker = app.state.server._workers[UUID(waiting.chat_id)]
    assert order[0][1] == next(iter(worker._threads)).ident
    assert run._send_cache is not old_cache and run._opening_changed
    assert provider_control.built == []


def test_an_answered_waiting_question_cannot_be_answered_again(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-repeat")
    answer = question(waiting)
    assert apply(client, waiting, (answer.id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    before = send_cases.files_in(waiting.fixture.folder)
    response = apply(client, waiting, (answer.id, "None bought"))
    assert response.status_code == 409 and response.json()["error_class"] == "AlreadyAnswered"
    assert send_cases.files_in(waiting.fixture.folder) == before
    assert chat.state_of(client, waiting.chat_id) == "awaiting_send"
    assert provider_control.built == []


def test_send_is_refused_while_code_is_applying_an_answer(
    app: Any,
    client: TestClient,
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-held-apply")
    entered, release = threading.Event(), threading.Event()
    original = runner.classify_part_roles

    def held(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(chat.TIMEOUT_S)
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "classify_part_roles", held)
    try:
        assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
        assert entered.wait(chat.TIMEOUT_S)
        response = client.post(f"/sessions/{waiting.chat_id}/send", json={})
        assert response.status_code == 409 and response.json()["error_class"] == "TurnRunning"
        assert provider_control.built == []
    finally:
        release.set()
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    assert provider_control.built == []


def test_an_answer_is_refused_while_a_send_is_in_flight(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-held-send")
    assert provider_control.built == []
    provider_control.hold()
    try:
        assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
        assert provider_control.started.wait(chat.TIMEOUT_S)
        response = apply(client, waiting, (question(waiting).id, "All bought"))
        assert response.status_code == 409 and response.json()["error_class"] == "TurnRunning"
        assert question(waiting).status == "open"
    finally:
        provider_control.release()
    chat.settle(client, waiting.chat_id)


@pytest.mark.parametrize("refused", [False, True])
def test_a_waiting_confirmed_drawing_records_its_outcome_without_a_turn(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    refused: bool,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-drawing")
    if refused:
        waiting.fixture.bridge._raises["drawing_read"] = BridgeError("FICT-read-refused")
    marker = waiting.run.sink.seq
    response = apply(client, waiting, (question(waiting, drawing=True).id, CANDIDATE_CONFIRM))
    assert response.status_code == 202, response.text
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    assert len(waiting.run.session.drawing_outcomes) == 1
    outcome = waiting.run.session.drawing_outcomes[0]
    assert outcome.file == "FICT-7001.SLDDRW"
    assert outcome.outcome == (
        "FICT-read-refused" if refused else "opened read-only, read and closed (1 sheet)"
    )
    assert load_session(waiting.run.session_path).drawing_outcomes == [outcome]
    assert [command for command, _ in waiting.fixture.bridge.calls].count("drawing_read") == 1
    assert not any(event.type.startswith("turn.") for event in new_events(waiting, marker))
    assert provider_control.built == []


def test_a_confirmed_read_reopens_the_real_pipe_and_the_apply_settle_closes_it(
    pipe_app: Any,
    pipe_client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    started = send_cases.pipe_review(pipe_client, run_root / "FICT-waiting-pipe")
    assert started.status_code == 201, started.text
    chat_id = str(started.json()["chat_id"])
    held = pipe_app.state.server.chats[UUID(chat_id)]
    transport = pipe_app.state.pipe_transports[0]
    request = next(
        item for item in held.run.session.evidence_requests if CANDIDATE_CONFIRM in item.options
    )
    assert transport.opened == transport.closed == 1
    response = pipe_client.post(
        f"/sessions/{chat_id}/evidence",
        json={"answers": [{"request_id": request.id, "answer": CANDIDATE_CONFIRM}]},
    )
    assert response.status_code == 202, response.text
    assert chat.settle(pipe_client, chat_id) == "awaiting_send"
    assert transport.opened == transport.closed == 2 and transport.open_pipes == 0
    assert [request["command"] for request in transport.requests].count("drawing.read") == 1
    assert held.run.session.drawing_outcomes
    assert provider_control.built == []


def test_a_reject_and_timing_written_while_waiting_are_kept_at_send(
    app: Any,
    client: TestClient,
    run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-work")
    finding = waiting.run.session.findings[0]
    decision = {"decision": "rejected", "note": "FICT engineer decision"}
    response = client.post(
        f"/sessions/{waiting.chat_id}/findings/{finding.id}/disposition",
        json=decision,
    )
    assert response.status_code == 200, response.text
    saved = load_session(waiting.run.session_path)
    assert next(f for f in saved.findings if f.id == finding.id).disposition.decision == "rejected"
    assert chat.state_of(client, waiting.chat_id) == "awaiting_send"
    timed = client.post(f"/sessions/{waiting.chat_id}/timing", json=FOUR)
    assert timed.status_code == 200, timed.text
    assert provider_control.built == []
    provider = RecordingProvider([chat.turn("FICT sent")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    sent = load_session(waiting.run.session_path)
    assert next(f for f in sent.findings if f.id == finding.id).disposition.decision == "rejected"
    assert sent.timing.baseline_minutes == 45 and sent.timing.net_saved_minutes is not None
    assert sent.timing.assisted_supervision_minutes == 6
    assert sent.timing.assisted_verification_minutes == 9
    assert sent.timing.false_alarm_handling_minutes == 2
    assert provider.log


# --- T085: rebuilt opening and exact prefix count -----------------------------------------


def wait_line(request: Any) -> str:
    return (
        f"{request.id} ({request.question}) was answered before this review was sent: "
        f"{request.answer}. The checks above were graded again by code with this answer."
    )


def applied_roles(app: Any, client: TestClient, folder: Path) -> Waiting:
    waiting = waiting_review(app, client, folder)
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    return waiting


@pytest.mark.usefixtures("vocabulary")
def test_an_answer_changes_the_count_to_the_exact_rebuilt_prefix(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-count")
    before = waiting.run._send_cache
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    current = waiting.run._send_cache
    assert current.estimate.input_tokens != before.estimate.input_tokens
    assert current.opening != before.opening
    assert current.estimate.input_tokens == tokens.count_tokens(
        request_prefix(waiting.run.system, waiting.run.tools, current.opening)
    )
    assert current.opening == waiting.run.opening_at_send()

    assert provider_control.built == []


@pytest.mark.usefixtures("vocabulary")
def test_the_size_shown_after_an_apply_is_the_size_in_the_actual_first_request(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = applied_roles(app, client, run_root / "FICT-waiting-size-sent")
    summary = client.get(f"/sessions/{waiting.chat_id}/snapshot").json()["ranking"]["summary"]
    shown = summary["send"]["input_tokens"]
    provider = RecordingProvider([chat.turn("FICT sent")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    marker = waiting.run.sink.seq
    assert provider_control.built == []
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    recorded = provider.log[0]
    specs = [
        SimpleNamespace(name=row["name"], description=row["description"], schema=row["parameters"])
        for row in recorded.tool_specs
    ]
    prefix = request_prefix(recorded.system, specs, recorded.first_message["content"])
    estimate = next(
        event.body["estimate"]["input_tokens"]
        for event in new_events(waiting, marker)
        if event.type == "session.sent"
    )
    assert tokens.count_tokens(prefix) == shown == estimate
    assert waiting.run.session.model_status.estimate.input_tokens == shown
    assert load_session(waiting.run.session_path).model_status.estimate.input_tokens == shown


def test_restated_returns_the_input_when_no_call_was_restated(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-no-restatement")
    original = waiting.run._prerun
    assert (
        prerun.restated(original, waiting.run.context, (), waiting.run._standards_gap) is original
    )

    assert provider_control.built == []


def test_restated_replaces_calls_in_place_with_standing_folded_findings_and_current_roles(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-restated")
    original = waiting.run._prerun
    recorded_call = runner.recorded_call
    calls: list[Any] = []

    def captured(*args: Any, **kwargs: Any) -> Any:
        call = recorded_call(*args, **kwargs)
        calls.append(call)
        return call

    monkeypatch.setattr(runner, "recorded_call", captured)
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    rebuilt = prerun.restated(original, waiting.run.context, calls, waiting.run._standards_gap)
    assert calls
    by_tool = {call.tool: call for call in calls}
    assert [call.tool for call in rebuilt.calls] == [call.tool for call in original.calls]
    for before, after in zip(original.calls, rebuilt.calls, strict=True):
        if before.tool not in by_tool:
            assert after is before
            continue
        current = by_tool[before.tool]
        assert after.step_index == current.step_index and after.arguments == current.arguments
        expected = tuple(
            f
            for f in waiting.run.session.findings
            if current.step_index in f.tool_result_ids and f.carried_over_from is None
        )
        assert after.findings == expected
        assert all(f in waiting.run.session.findings for f in after.findings)
    assert rebuilt.live is original.live
    assert rebuilt.families is original.families and rebuilt.withheld is original.withheld
    checks = [family.check for family in rebuilt.not_evaluated]
    assert "coverage.prerun.maybe_bought" not in checks
    assert "coverage.prerun.bought_parts" in checks
    assert waiting.run._prerun == rebuilt

    assert provider_control.built == []


def test_the_send_opening_names_only_standing_findings_and_correct_folded_family_counts(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-honest-digest")
    before = set(waiting.run._prerun.named_finding_ids())
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    run = waiting.run
    after = {f.id for f in run.session.findings}
    removed = before - after
    assert removed
    provider = RecordingProvider([chat.turn("FICT sent")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert provider_control.built == []
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    opening = provider.log[0].first_message["content"]
    assert all(fid not in opening for fid in removed)
    expected = {
        f.id
        for f in run.session.findings
        if family_of(f.check, run.session.folded_families) is None
    }
    assert expected <= set(run._send_cache.named_ids)
    assert all(fid in opening for fid in expected)
    rms = [
        f for f in run.session.findings if family_of(f.check, run.session.folded_families) == "rms"
    ]
    counts = count_findings((f.check, f.status, f.severity) for f in rms)
    statuses = ", ".join(f"{count} {status}" for status, count in counts.by_status.items())
    expected_line = (
        f"  modelling practice: {family_counts(counts.findings, counts.rules)} ({statuses}); "
        f"{prerun.FAMILY_COUNTS_NOTE}"
    )
    assert expected_line in opening
    assert not set(run.session.model_status.opening_finding_ids) & removed
    assert set(run.session.model_status.opening_finding_ids) <= after


def test_outcomes_then_wait_answers_appear_once_in_order_between_digest_and_instruction(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-lines")
    role, drawing = question(waiting), question(waiting, drawing=True)
    # Deliberately reverse id order: ordering follows answers, with ids breaking clock ties.
    assert apply(client, waiting, (drawing.id, CANDIDATE_CONFIRM)).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    assert apply(client, waiting, (role.id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    provider = RecordingProvider([chat.turn("FICT sent")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert provider_control.built == []
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    opening = provider.log[0].first_message["content"]
    lines = [
        f"Drawing {outcome.file}: {outcome.outcome}"
        for outcome in waiting.run.session.drawing_outcomes
    ] + [wait_line(drawing), wait_line(role)]
    assert "\n\n" + "\n".join(lines) + "\n\n" + runner.OPENING_MESSAGE in opening
    digest_end = opening.index(prerun.NOT_EVALUATED_HEADER)
    assert all(opening.count(line) == 1 and opening.index(line) > digest_end for line in lines)
    assert "withdrew" not in opening
    assert runner.REGRADED_LINE.split("{ids}")[0] not in opening
    assert runner.answers_message([(role.id, "All bought")]) not in opening


def test_the_rebuilt_branch_has_no_extra_separator_when_no_wait_line_exists(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-empty-lines")
    waiting.run._settle_waiting(runner.AppliedAnswers(read=(), withdrawn_by_answer=()))
    assert waiting.run.opening_at_send() == waiting.run.opening_message
    assert "\n\n\n" not in waiting.run.opening_at_send()

    assert provider_control.built == []


def test_send_after_an_apply_removes_every_finalization_row_but_keeps_code_rows(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-clean-coverage")
    run = waiting.run
    earlier = tuple(run._finalized)
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    applied = tuple(run._finalized)
    assert earlier and applied
    code_rows = [
        row
        for bucket in runner.CoverageBucket.__args__
        for row in getattr(run.session.coverage, bucket)
        if row.check in {"coverage.prerun.part_roles", "coverage.prerun.bought_parts"}
    ]
    assert code_rows
    code_coverage = {
        bucket: [
            row
            for row in getattr(run.session.coverage, bucket)
            if all(row is not final for final in applied)
        ]
        for bucket in runner.CoverageBucket.__args__
    }
    expected_buckets = {}
    for item in run.context.checklist.items:
        if item.owner != "model":
            continue
        if any(f.check.startswith(item.check_prefix) for f in run.session.findings):
            expected_buckets[item.id] = "finding"
        else:
            expected_buckets[item.id] = next(
                (
                    bucket
                    for bucket in ("checked", "skipped", "unresolved", "out_of_scope")
                    if any(row.check == item.id for row in code_coverage[bucket])
                ),
                "open",
            )
    provider = RecordingProvider(
        [
            chat.turn(
                "FICT sent",
                chat.call("get_review_checklist"),
                chat.call(
                    "request_evidence", what="FICT next evidence", why="FICT checks", entity_ids=[]
                ),
            )
        ]
    )
    request = provider._inner.run
    observed: list[dict[str, Any]] = []

    def at_request(**kwargs: Any) -> Any:
        rows = [
            row
            for bucket in runner.CoverageBucket.__args__
            for row in getattr(run.session.coverage, bucket)
        ]
        expected = [item for item in run.context.checklist.items if item.owner == "model"]
        observed.append(
            {
                "earlier_rows": [
                    row for row in rows if any(row is prior for prior in (*earlier, *applied))
                ],
                "code_rows_kept": all(any(row is code for row in rows) for code in code_rows),
                "buckets": {
                    item.id: run.context.checklist.bucket_of(item, run.session) for item in expected
                },
                "open_items": [
                    item.id for item in run.context.checklist.open_items(run.session, owner="model")
                ],
            }
        )
        return request(**kwargs)

    monkeypatch.setattr(provider._inner, "run", at_request)
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert provider_control.built == []
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    assert len(observed) == 1
    first = observed[0]
    assert first["earlier_rows"] == [] and first["code_rows_kept"]
    assert first["buckets"]
    assert first["buckets"] == expected_buckets
    open_ids = [item_id for item_id, bucket in expected_buckets.items() if bucket == "open"]
    assert open_ids and first["open_items"] == open_ids
    messages = [message for message in run.messages if message["role"] == "tool"]
    checklist = next(
        message["content"] for message in messages if message["name"] == "get_review_checklist"
    )
    assert {
        item["id"]: item["bucket"] for item in checklist["result"] if item["id"] in expected_buckets
    } == expected_buckets
    assert (
        next(message["content"] for message in messages if message["name"] == "request_evidence")[
            "open_items"
        ]
        == open_ids
    )


def test_a_failed_send_then_apply_then_send_uses_the_rebuilt_opening_once(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-failed-then-apply")
    failed = RecordingProvider([chat.turn("unused")])

    def refusal(**kwargs: Any) -> Any:
        raise RuntimeError("FICT first request refused")

    monkeypatch.setattr(failed._inner, "run", refusal)
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: failed)
    assert provider_control.built == []
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    frozen = failed.log[0].first_message["content"]
    assert apply(client, waiting, (question(waiting).id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    provider = RecordingProvider([chat.turn("FICT retry")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    chat.settle(client, waiting.chat_id)
    opening = provider.log[0].first_message["content"]
    assert opening != frozen and opening == waiting.run._send_cache.opening
    assert len([message for message in waiting.run.messages if message["role"] == "user"]) == 1
    assert opening.count(wait_line(question(waiting))) == 1


def test_wait_lines_are_not_added_to_later_answer_or_followup_or_presentation_requests(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = waiting_review(app, client, run_root / "FICT-waiting-never-repeat")
    role, drawing = question(waiting), question(waiting, drawing=True)
    assert (
        apply(client, waiting, (role.id, "All bought"), (drawing.id, CANDIDATE_CONFIRM)).status_code
        == 202
    )
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    provider = RecordingProvider(
        [
            chat.turn(
                "FICT sent",
                chat.call(
                    "request_evidence",
                    what="FICT follow-up evidence",
                    why="FICT model question",
                    entity_ids=[],
                ),
            ),
            chat.turn("FICT answered"),
            chat.turn("FICT follow-up"),
        ]
    )
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert provider_control.built == []
    assert client.post(f"/sessions/{waiting.chat_id}/send", json={}).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "waiting_engineer"
    model_question = next(
        q
        for q in waiting.run.session.evidence_requests
        if q.source != "code" and q.status == "open"
    )
    assert apply(client, waiting, (model_question.id, "FICT model answer")).status_code == 202
    chat.settle(client, waiting.chat_id)
    assert (
        client.post(
            f"/sessions/{waiting.chat_id}/messages", json={"text": "FICT later follow-up"}
        ).status_code
        == 202
    )
    chat.settle(client, waiting.chat_id)
    lines = [f"Drawing {o.file}: {o.outcome}" for o in waiting.run.session.drawing_outcomes] + [
        wait_line(role),
        wait_line(drawing),
    ]
    user_messages = [
        message["content"] for message in waiting.run.messages if message["role"] == "user"
    ]
    assert len(user_messages) == 3
    assert all(line in user_messages[0] for line in lines)
    assert all(line not in text for text in user_messages[1:] for line in lines)
    assert any(record.presentation for record in provider.log), (
        "actual presentation requests must be observed"
    )
    for record in provider.log:
        encoded = "\n".join(piece.decode("utf-8") for piece in record.encoded_history)
        assert all(encoded.count(line) <= 1 for line in lines)


def test_restated_keeps_a_standing_drawing_finding_returned_by_the_deduplicating_check() -> None:
    from swreview.checks.standards.profile import load_profile
    from swreview.ir.loader import load_package
    from swreview.tools.registry import ToolRegistry
    from tests.unit.test_drawing_conformance import PLATE_DRAWING, PROFILE_A, reviewed, with_drawing

    package = load_package(PLATE_DRAWING).package
    context = reviewed(package, with_drawing(load_profile(PROFILE_A), projection="first_angle"))
    dispatch = ToolRegistry().dispatch(context)
    initial = prerun.recorded_call(
        context, dispatch, "check_drawings", {}, call_id="FICT-first-drawing", mark="prerun"
    )
    original = prerun.PrerunResult(calls=(initial,), not_evaluated=())
    assert len(initial.findings) == 2
    repeated = prerun.recorded_call(
        context, dispatch, "check_drawings", {}, call_id="FICT-regraded-drawing", mark="regrade"
    )
    assert repeated.findings == ()
    assert repeated.payload["finding_ids"] == [finding.id for finding in initial.findings]
    assert all(repeated.step_index not in finding.tool_result_ids for finding in initial.findings)

    rebuilt = prerun.restated(original, context, (repeated,), None)

    assert rebuilt.named_finding_ids() == [finding.id for finding in initial.findings]
    assert rebuilt.calls[0].findings == initial.findings
    assert all(finding.id in rebuilt.digest() for finding in initial.findings)
