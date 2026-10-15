"""Feature 016's saved engineering context on feature 015's send gate (owner decision 99A).

The T116 integration review found that 016, written before 015, started reviews on its own path.
These tests pin each of its findings on the adapted branch: an unticked context review sends
nothing and Send's first request carries the context once (blocker A and the combined test 99A
names); the opening rebuilt after a waiting answer keeps the context (blocker B); a restored
waiting review's re-run carries its attachment and never loses its summary (should-fix C); and
saved context cannot change while a review that carries it is set up or waits (should-fix D).
"""

from __future__ import annotations

import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from swreview import atomic, tokens
from swreview.agent import runner
from swreview.agent.runner import request_prefix
from swreview.engineering_context.brief import build_summary, compact_json
from swreview.engineering_context.models import context_digest
from swreview.ir.loader import load_package, save_package
from swreview.report.session import load_session
from tests.support.contracts import contract_validator
from tests.support.questions_package import build_questions_package
from tests.support.recording_provider import RecordingProvider
from tests.support.restart import BEFORE_REPLACE, disk_at, restarted_app
from tests.support.restored import assert_restored_as_waiting
from tests.unit import test_chat_engineering_context as ctx
from tests.unit import test_chat_server as chat
from tests.unit import test_recheck as recheck_cases
from tests.unit import test_waiting_answers as waiting_cases

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir

ENGINEERING_LEAD = "Engineer-supplied inputs for the saved evidence snapshot follow as JSON data."
"""The first sentence of the opening's engineering block (`runner._opening_message`)."""
SUMMARY_FILE = "engineering-context-summary.json"
SESSION_SCHEMA = "https://smart-sw.local/contracts/review-session.schema.json"
IN_USE = "Engineering context is in use by a running review."


def attachment_of(client: TestClient, folder: Path, entity_id: str = "cmp:0001") -> dict[str, Any]:
    """Initialize the folder's private context with one draft requirement; its exact attachment."""
    head = ctx.initialize(client, folder)
    saved = client.post(
        ctx.endpoint(folder, "/requirement"), json=ctx.requirement(head, entity_id=entity_id)
    )
    assert saved.status_code == 200, saved.text
    published = saved.json()
    return {key: published[key] for key in ("context_id", "head_digest", "package_sha256")}


def waiting_with_context(app: Any, client: TestClient, folder: Path) -> waiting_cases.Waiting:
    """015's unticked questions review, started with a saved context attached."""
    return waiting_cases.waiting_review(
        app,
        client,
        folder,
        attach=lambda written: {"engineering_context": attachment_of(client, written)},
    )


def block_of(folder: Path) -> str:
    """The retained summary, as the opening carries it."""
    return compact_json(json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8")))


def assert_block_once(opening: str, folder: Path) -> None:
    assert opening.count(ENGINEERING_LEAD) == 1, opening
    assert opening.count(block_of(folder)) == 1, opening


def sent_opening(
    app: Any, client: TestClient, chat_id: str, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Press Send on a waiting chat with a recording provider: the first request's message."""
    provider = RecordingProvider([chat.turn("FICT sent")])
    monkeypatch.setattr(app.state.server, "provider_factory", lambda settings: provider)
    assert client.post(f"/sessions/{chat_id}/send", json={}).status_code == 202
    chat.settle(client, chat_id)
    return str(provider.log[0].first_message["content"])


# --- blocker A, and the combined test 99A names ------------------------------------------------


def test_an_unticked_context_review_builds_no_provider_and_send_carries_the_block_once(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = run_root / "FICT-context-waits"
    waiting = waiting_with_context(app, client, folder)

    assert provider_control.built == []
    assert waiting.run.context.engineering_context is not None
    assert chat.state_of(client, waiting.chat_id) == "awaiting_send"
    assert_block_once(waiting.run.opening_message, folder)

    opening = sent_opening(app, client, waiting.chat_id, monkeypatch)

    assert provider_control.built == []
    assert_block_once(opening, folder)
    assert opening.endswith(runner.OPENING_MESSAGE)


def test_a_stale_attachment_on_an_unticked_start_is_refused_before_any_setup(
    client: TestClient, run_dir: Path, provider_control: chat.ProviderControl
) -> None:
    head = ctx.initialize(client, run_dir)
    stale = {
        "context_id": head["context_id"],
        "head_digest": "a" * 64,
        "package_sha256": head["package_sha256"],
    }
    refused = client.post(
        "/sessions",
        json=chat.session_body(run_dir, send_when_checked=False, engineering_context=stale),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error_class"] == "EngineeringContextConflict"
    assert provider_control.built == []
    assert not (run_dir / "session.json").exists()
    assert not (run_dir / "events.jsonl").exists()


# --- blocker B: the opening rebuilt at Send keeps the context ----------------------------------


@pytest.mark.usefixtures("vocabulary")
def test_a_waiting_answer_rebuilds_the_opening_with_the_engineering_block_once(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = run_root / "FICT-context-answered"
    waiting = waiting_with_context(app, client, folder)
    role = waiting_cases.question(waiting)
    assert waiting_cases.apply(client, waiting, (role.id, "All bought")).status_code == 202
    assert chat.settle(client, waiting.chat_id) == "awaiting_send"
    run = waiting.run
    cache = run._send_cache
    assert cache is not None

    opening = cache.opening
    assert opening != run.opening_message
    assert_block_once(opening, folder)
    answer = waiting_cases.wait_line(role)
    assert opening.index(block_of(folder)) < opening.index(answer)
    assert opening.index(answer) < opening.rindex(runner.OPENING_MESSAGE)
    assert opening.endswith(runner.OPENING_MESSAGE)
    assert cache.estimate.input_tokens == tokens.count_tokens(
        request_prefix(run.system, run.tools, opening)
    )

    sent = sent_opening(app, client, waiting.chat_id, monkeypatch)

    assert sent == opening
    assert provider_control.built == []


def test_a_reloaded_package_rebuilds_the_summary_the_opening_and_its_file_carry(
    app: Any, client: TestClient, run_root: Path
) -> None:
    """A confirmed drawing read reloads the package (feature 011): the opening Send rebuilds
    carries the summary over that package, and the retained file says the same."""
    folder = run_root / "FICT-context-reloaded"
    waiting = waiting_with_context(app, client, folder)
    run = waiting.run
    before = block_of(folder)
    reloaded = load_package(folder)
    reloaded.package.components = [
        item for item in reloaded.package.components if item.id != "cmp:0001"
    ]
    run.context.reload_package(reloaded)
    run._settle_waiting(runner.AppliedAnswers(read=(), withdrawn_by_answer=()))

    opening = run.opening_at_send()

    current = build_summary(run.context.engineering_context, run.context.package)
    assert compact_json(current) != before
    assert compact_json(current) in opening
    assert before not in opening
    assert opening.count(ENGINEERING_LEAD) == 1
    assert json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8")) == current
    assert run.opening_at_send() == opening


# --- should-fix C: a restored waiting review's re-run carries its attachment -----------------


def test_the_waiting_record_names_its_attachment(
    app: Any, client: TestClient, run_root: Path
) -> None:
    folder = run_root / "FICT-context-recorded"
    waiting = waiting_with_context(app, client, folder)
    artifact = waiting.run.context.engineering_context
    written = json.loads((folder / "session.json").read_text(encoding="utf-8"))

    model_status = contract_validator("review-session.schema.json").evolve(
        schema={"$ref": f"{SESSION_SCHEMA}#/$defs/ModelStatus"}
    )
    model_status.validate(written["model_status"])
    assert written["model_status"]["engineering_context"] == {
        "context_id": str(artifact.context_id),
        "head_digest": context_digest(artifact),
        "package_sha256": artifact.baseline.package_sha256,
    }


def test_a_restored_context_review_rechecks_with_its_context_and_sends_it(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = run_root / "FICT-context-rechecked"
    waiting = waiting_with_context(app, client, folder)
    earlier = load_session(folder / "session.json")
    summary = (folder / SUMMARY_FILE).read_bytes()
    seat = recheck_cases.silent_seat()
    settings = recheck_cases.server_settings(provider_control, models, seat)
    with restarted_app(run_root, settings) as fresh:
        restored = fresh.get(f"/reviews/{folder.name}")
        assert restored.status_code == 200, restored.text
        assert_restored_as_waiting(restored.json(), earlier)

        response = recheck_cases.recheck(fresh, folder)

        assert response.status_code == 201, response.text
        chat_id = response.json()["chat_id"]
        held = fresh.app.state.server.chats[UUID(chat_id)]
        assert held.run.context.engineering_context == waiting.run.context.engineering_context
        assert_block_once(held.run.opening_message, folder)
        assert (folder / SUMMARY_FILE).read_bytes() == summary
        status = load_session(folder / "session.json").model_status
        assert status is not None
        assert status.engineering_context == earlier.model_status.engineering_context
        assert status.rechecked_from == earlier.session_id

        opening = sent_opening(fresh.app, fresh, chat_id, monkeypatch)

    assert_block_once(opening, folder)
    assert provider_control.built == []
    assert seat.calls == []


def test_a_changed_head_refuses_the_re_run_and_leaves_the_folder(
    client: TestClient,
    run_dir: Path,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
) -> None:
    """A part with no live check keeps its package, so its saved context can be edited after a
    restart; the re-run then refuses before anything in the folder moves."""
    attachment = attachment_of(client, run_dir)
    started = chat.start_session(
        client, run_dir, send_when_checked=False, engineering_context=attachment
    )
    assert chat.state_of(client, started["chat_id"]) == "awaiting_send"
    before = {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()}
    assert SUMMARY_FILE in before
    settings = recheck_cases.server_settings(
        provider_control, models, recheck_cases.silent_seat()
    )
    with restarted_app(run_root, settings) as fresh:
        edited = fresh.post(
            ctx.endpoint(run_dir, "/requirement"),
            json=ctx.requirement(attachment, text="FICT revised load."),
        )
        assert edited.status_code == 200, edited.text

        refused = recheck_cases.recheck(fresh, run_dir, standards_profile=None, bridge=None)

        assert refused.status_code == 409, refused.text
        assert refused.json()["error_class"] == "EngineeringContextConflict"
        assert fresh.app.state.server.chats == {}
        assert fresh.app.state.server._pending_run_dirs == set()
    after = {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()}
    assert after == before
    assert provider_control.built == []


def test_a_recheck_takes_no_attachment_of_its_own(
    app: Any, client: TestClient, run_root: Path
) -> None:
    folder = run_root / "FICT-context-own"
    waiting_with_context(app, client, folder)
    before = (folder / "session.json").read_bytes()

    refused = recheck_cases.recheck(
        client, folder, engineering_context={"context_id": "FICT", "head_digest": "FICT"}
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["error_class"] == "InvalidRequest"
    assert (folder / "session.json").read_bytes() == before


@pytest.mark.parametrize("cut", ["raises", BEFORE_REPLACE])
def test_a_re_run_stopped_at_its_record_replace_keeps_the_summary_and_record(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    cut: str,
) -> None:
    """Before the re-run's commit point (015 FR-041) the earlier record and its summary stand,
    whether the replace raises or the run is cut off there (copied with `disk_at`)."""
    folder = run_root / "FICT-context-cut"
    waiting_with_context(app, client, folder)
    record = (folder / "session.json").read_bytes()
    summary = (folder / SUMMARY_FILE).read_bytes()
    settings = recheck_cases.server_settings(
        provider_control, models, recheck_cases.silent_seat()
    )
    if cut == BEFORE_REPLACE:
        with disk_at(folder, BEFORE_REPLACE) as captured:
            with restarted_app(run_root, settings) as fresh:
                assert recheck_cases.recheck(fresh, folder).status_code == 201
            assert (captured.folder / "session.json").read_bytes() == record
            assert (captured.folder / SUMMARY_FILE).read_bytes() == summary
        return
    held_replace = atomic.os.replace

    def refused(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        if Path(dst).name == "session.json":
            raise OSError("FICT the record could not be replaced")
        held_replace(src, dst, *args, **kwargs)

    with (
        patch.object(atomic.os, "replace", refused),
        restarted_app(run_root, settings, raise_server_exceptions=False) as fresh,
    ):
        assert recheck_cases.recheck(fresh, folder).status_code == 500
    assert (folder / "session.json").read_bytes() == record
    assert (folder / SUMMARY_FILE).read_bytes() == summary


# --- should-fix D: no edit while a review that carries the context is set up or waits --------


def test_an_edit_while_the_review_waits_for_send_is_refused(
    client: TestClient, run_dir: Path
) -> None:
    attachment = attachment_of(client, run_dir)
    started = chat.start_session(
        client, run_dir, send_when_checked=False, engineering_context=attachment
    )
    assert chat.state_of(client, started["chat_id"]) == "awaiting_send"

    refused = client.post(
        ctx.endpoint(run_dir, "/requirement"),
        json=ctx.requirement(attachment, text="FICT revised load."),
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["message"] == IN_USE
    assert client.get(ctx.endpoint(run_dir)).json()["head_digest"] == attachment["head_digest"]


def held_step(
    owner: Any, monkeypatch: pytest.MonkeyPatch, step: str
) -> tuple[threading.Event, threading.Event]:
    """Hold the server's setup `step`, which runs on the thread pool, until released."""
    entered, release = threading.Event(), threading.Event()
    original = getattr(owner, step)

    def held(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(chat.TIMEOUT_S)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, step, held)
    return entered, release


def edit_refused_while_held(
    client: TestClient,
    folder: Path,
    body: dict[str, Any],
    attachment: dict[str, Any],
    entered: threading.Event,
    release: threading.Event,
) -> None:
    """Post `body` to `POST /sessions`; while its held step waits, an edit is refused as busy."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(client.post, "/sessions", json=body)
        try:
            assert entered.wait(chat.TIMEOUT_S)
            refused = client.post(
                ctx.endpoint(folder, "/requirement"),
                json=ctx.requirement(attachment, text="FICT revised load."),
            )
            assert refused.status_code == 409, refused.text
            assert refused.json()["message"] == IN_USE
        finally:
            release.set()
        assert response.result().status_code == 201, response.result().text
    assert client.get(ctx.endpoint(folder)).json()["head_digest"] == attachment["head_digest"]


def test_an_edit_while_an_unticked_start_is_set_up_is_refused(
    app: Any, client: TestClient, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attachment = attachment_of(client, run_dir)
    entered, release = held_step(app.state.server, monkeypatch, "_start_review")
    body = chat.session_body(run_dir, send_when_checked=False, engineering_context=attachment)

    edit_refused_while_held(client, run_dir, body, attachment, entered, release)


@pytest.mark.parametrize("step", ["_waiting_record", "_start_review"])
def test_an_edit_while_a_re_run_is_set_up_is_refused(
    client: TestClient,
    run_dir: Path,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> None:
    """From the claim on: `_waiting_record` runs before the attachment is read again, and an
    edit there would otherwise change the head under the re-run."""
    attachment = attachment_of(client, run_dir)
    chat.start_session(client, run_dir, send_when_checked=False, engineering_context=attachment)
    settings = recheck_cases.server_settings(
        provider_control, models, recheck_cases.silent_seat()
    )
    with restarted_app(run_root, settings) as fresh:
        entered, release = held_step(fresh.app.state.server, monkeypatch, step)
        body = recheck_cases.recheck_body(run_dir, standards_profile=None, bridge=None)

        edit_refused_while_held(fresh, run_dir, body, attachment, entered, release)


# --- the verifier's probes (owner decisions 105A-109A, 2026-10-15) ----------------------------


@pytest.mark.usefixtures("vocabulary")
def test_probe_ticked_equals_unticked_send_with_context(
    app: Any,
    client: TestClient,
    run_root: Path,
    tmp_path: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
) -> None:
    """A ticked context review's first request and an unticked one's Send are byte-identical,
    with the engineering block exactly once (SC-004 with saved context)."""
    folder = run_root / "FICT-probe-tick"
    fixture = build_questions_package(folder)
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    attachment = attachment_of(client, folder)
    saved = tmp_path / "saved"
    shutil.copytree(folder, saved)
    body = {
        "standards_profile": str(fixture.profile),
        "bridge": {"pipe": "FICT-pipe", "secret": "FICT-secret"},
        "engineering_context": attachment,
    }
    ticked = RecordingProvider([chat.turn("FICT sent")])
    app.state.server.provider_factory = lambda chosen: ticked
    started = chat.start_session(client, folder, send_when_checked=True, **body)
    chat.settle(client, started["chat_id"])

    shutil.rmtree(folder)
    shutil.copytree(saved, folder)
    unticked = RecordingProvider([chat.turn("FICT sent")])
    seat = build_questions_package(tmp_path / "seat-only").bridge
    settings = recheck_cases.server_settings(provider_control, models, seat)
    settings["provider_factory"] = lambda chosen: unticked
    with restarted_app(run_root, settings) as fresh:
        waiting = chat.start_session(fresh, folder, send_when_checked=False, **body)
        assert chat.state_of(fresh, waiting["chat_id"]) == "awaiting_send"
        assert unticked.log == []
        assert fresh.post(f"/sessions/{waiting['chat_id']}/send", json={}).status_code == 202
        chat.settle(fresh, waiting["chat_id"])

    first, sent = ticked.log[0], unticked.log[0]
    assert first.system == sent.system
    assert first.encoded_tools == sent.encoded_tools
    assert first.first_message == sent.first_message
    assert first.first_message["content"].count(ENGINEERING_LEAD) == 1
    recheck_cases.assert_sent_alike(ticked.log, unticked.log)


@pytest.mark.usefixtures("vocabulary")
def test_probe_a_re_run_with_context_sends_what_the_live_review_would_have_sent(
    app: Any,
    client: TestClient,
    run_root: Path,
    tmp_path: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
) -> None:
    """SC-008 with saved context: nothing answered, a re-run after a restart sends byte for byte
    what the live waiting review sends, the engineering block once."""
    waiting = waiting_with_context(app, client, run_root / "FICT-probe-sc008")
    live = waiting.run
    settings = recheck_cases.server_settings(
        provider_control, models, recheck_cases.silent_seat()
    )
    sent, resent, rerun = recheck_cases.sent_live_and_after_a_re_run(
        app, client, run_root, tmp_path / "saved", waiting, settings
    )

    assert rerun._send_cache.opening == live._send_cache.opening
    recheck_cases.assert_sent_alike(sent, resent)
    assert sent[0].first_message["content"].count(ENGINEERING_LEAD) == 1



# --- owner decision 107A: the live interference check keeps saved inputs matched ---------------


@pytest.mark.parametrize("ticked", [True, False], ids=["ticked", "unticked"])
def test_saved_inputs_stay_matched_after_the_live_interference_check(
    app: Any, client: TestClient, run_root: Path, ticked: bool
) -> None:
    folder = run_root / "FICT-context-live"
    fixture = build_questions_package(folder)
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    attachment = attachment_of(client, folder)
    before = (folder / "package.json").read_bytes()

    started = chat.start_session(
        client,
        folder,
        send_when_checked=ticked,
        standards_profile=str(fixture.profile),
        bridge={"pipe": "FICT-pipe", "secret": "FICT-secret"},
        engineering_context=attachment,
    )
    chat.settle(client, started["chat_id"])

    assert [name for name, _ in fixture.bridge.calls].count("interference") == 1
    assert (folder / "package.json").read_bytes() != before
    summary = json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8"))
    assert [row["binding"] for row in summary["records"]] == ["matched_snapshot"]
    assert [row["needs_review"] for row in summary["records"]] == [False]
    panel = client.get(ctx.endpoint(folder)).json()["records"]
    assert [row["binding"]["status"] for row in panel] == ["matched_snapshot"]

    package = load_package(folder).package
    package.components[0].transform[0][3] += 0.25
    save_package(package, folder)
    panel = client.get(ctx.endpoint(folder)).json()["records"]
    assert [row["binding"]["status"] for row in panel] == ["mismatch"]
    assert panel[0]["binding"]["reasons"] == ["package_digest_changed"]
