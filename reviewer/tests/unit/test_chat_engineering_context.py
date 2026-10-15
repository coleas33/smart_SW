"""Pane context entry is explicit, private and bound to one exact saved package."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from swreview.engineering_context import workflow
from swreview.engineering_context.brief import build_summary, compact_json
from swreview.ir.loader import load_package, save_package
from tests.support.packages import build_package
from tests.support.prerun import FIRST_INSTANCE, LIVE_ROWS, live_prerun_package
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge
from tests.unit import test_chat_server as chat

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir


def endpoint(run_dir: Path, suffix: str = "") -> str:
    return f"/engineering-context/{run_dir.name}{suffix}"


def initialize(client: TestClient, run_dir: Path) -> dict:
    response = client.post(endpoint(run_dir, "/init"), json={})
    assert response.status_code == 201, response.text
    return response.json()


def requirement(head: dict, **changes) -> dict:
    return {
        "expected_head": head["head_digest"],
        "record_id": "req:operating",
        "kind": "component",
        "entity_id": "cmp:0001",
        "text": "Support the operating load.",
        "provenance_kind": "engineer",
        "assumptions": [],
        **changes,
    }


def test_uninitialized_get_is_read_only_and_labels_the_saved_targets(
    client: TestClient, run_dir: Path, run_root: Path, provider_control
):
    before = {p: p.read_bytes() for p in run_root.rglob("*") if p.is_file()}
    response = client.get(endpoint(run_dir))
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["initialized"] is False
    assert view["records"] == []
    assert view["scope"] == "saved_snapshot"
    assert view["native_model_state"] == "not_observed"
    target = next(t for t in view["targets"] if t["entity_id"] == "cmp:0001")
    assert target["kind"] == "component"
    assert "housing-1" in target["label"] and "Default" in target["label"]
    assert len(view["package_sha256"]) == 64
    assert not (run_root / ".engineering-context").exists()
    assert before == {p: p.read_bytes() for p in run_root.rglob("*") if p.is_file()}
    assert not provider_control.built


def test_entry_confirmation_edit_and_operator_privacy(client: TestClient, run_dir: Path):
    initial = initialize(client, run_dir)
    response = client.post(endpoint(run_dir, "/requirement"), json=requirement(initial))
    assert response.status_code == 200, response.text
    head = response.json()
    preview = client.get(endpoint(run_dir)).json()
    row = preview["records"][0]
    assert row["record"]["text"] == "Support the operating load."
    assert row["record"]["provenance"] == {"kind": "engineer"}
    assert row["decision"] == "draft"
    assert row["binding"]["status"] == "matched_snapshot"
    confirmed = client.post(
        endpoint(run_dir, "/confirm"),
        json={
            "expected_head": head["head_digest"],
            "record_id": "req:operating",
            "actor": "private-engineer",
            "expected_record_digest": row["record_digest"],
            "expected_dependency_digest": row["dependency_digest"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    preview = client.get(endpoint(run_dir)).json()
    assert preview["records"][0]["decision"] == "confirmed"
    raw = json.dumps(preview)
    for private in ("persist_ref", "native/", "native\\", "private-engineer", "confirmations"):
        assert private not in raw
    edited = client.post(
        endpoint(run_dir, "/requirement"),
        json=requirement(confirmed.json(), text="Support the revised load."),
    )
    assert edited.status_code == 200, edited.text
    assert client.get(endpoint(run_dir)).json()["records"][0]["decision"] == "needs_review"


def test_force_numbers_and_unknowns_are_preserved(client: TestClient, run_dir: Path):
    head = initialize(client, run_dir)
    body = {
        "expected_head": head["head_digest"],
        "record_id": "force:operating",
        "kind": "component",
        "entity_id": "cmp:0001",
        "magnitude": 2.0,
        "unit": "kN",
        "direction": [0.0, 0.0, -1.0],
        "point_m": [0.1, 0.0, 0.0],
        "provenance_kind": "ai_proposal",
        "assumptions": ["Total force."],
    }
    response = client.post(endpoint(run_dir, "/force"), json=body)
    assert response.status_code == 200, response.text
    row = client.get(endpoint(run_dir)).json()["records"][0]
    assert row["record"]["magnitude"] == {
        "state": "known",
        "value": 2.0,
        "unit": "kN",
        "reason": None,
    }
    assert row["record"]["direction"] == [0.0, 0.0, -1.0]
    assert row["record"]["point_m"] == [0.1, 0.0, 0.0]
    assert row["resolved_force"]["vector_n"] == [0.0, 0.0, -2000.0]
    body.update(
        expected_head=response.json()["head_digest"],
        magnitude=None,
        unknown_reason="Awaiting operating case.",
    )
    response = client.post(endpoint(run_dir, "/force"), json=body)
    assert response.status_code == 200, response.text
    row = client.get(endpoint(run_dir)).json()["records"][0]
    assert row["record"]["magnitude"]["state"] == "unknown"
    assert row["record"]["magnitude"]["value"] is None
    assert row["resolved_force"] is None


def test_stale_head_and_changed_evidence_are_conflicts(client: TestClient, run_dir: Path):
    head = initialize(client, run_dir)
    assert client.post(endpoint(run_dir, "/requirement"), json=requirement(head)).status_code == 200
    assert client.post(endpoint(run_dir, "/requirement"), json=requirement(head)).status_code == 409
    current = client.get(endpoint(run_dir)).json()
    (run_dir / "package.json").write_bytes((run_dir / "package.json").read_bytes() + b"\n")
    refused = client.post(endpoint(run_dir, "/requirement"), json=requirement(current))
    assert refused.status_code == 409, refused.text
    assert client.get(endpoint(run_dir)).json()["records"][0]["binding"]["needs_review"]


@pytest.mark.parametrize(
    "bad",
    [
        {"text": "", "source_path": "C:\\private\\secret.SLDPRT"},
        {"kind": "document", "entity_id": "missing-document"},
        {"expected_head": "not-a-digest"},
        {"provenance_kind": "extracted"},
    ],
)
def test_bad_inputs_do_not_echo_private_values_or_change_head(
    client: TestClient, run_dir: Path, bad: dict
):
    head = initialize(client, run_dir)
    response = client.post(endpoint(run_dir, "/requirement"), json=requirement(head, **bad))
    assert response.status_code == 400, response.text
    assert "private" not in response.text and "secret.SLDPRT" not in response.text
    assert client.get(endpoint(run_dir)).json()["head_digest"] == head["head_digest"]


@pytest.mark.parametrize(
    "run_id", ["..", "bad:alias", "CON", "private.", "private ", ".engineering-context"]
)
def test_run_ids_cannot_name_other_workstation_paths(client: TestClient, run_id: str):
    response = client.get(f"/engineering-context/{run_id}")
    assert response.status_code in (400, 404), response.text
    assert "run root" not in response.text


def test_attachment_is_explicit_and_verified_before_provider_setup(
    app, client: TestClient, run_dir: Path, provider_control
):
    head = initialize(client, run_dir)
    attachment = {key: head[key] for key in ("context_id", "head_digest", "package_sha256")}
    invalid = client.post(
        "/sessions",
        json=chat.session_body(
            run_dir, engineering_context={**attachment, "head_digest": "a" * 64}
        ),
    )
    assert invalid.status_code == 409, invalid.text
    assert not provider_control.built
    provider_control.hold()
    started = chat.start_session(client, run_dir, engineering_context=attachment)
    try:
        held = app.state.server.chats[UUID(started["chat_id"])]
        assert held.run.context.engineering_context.context_id == UUID(head["context_id"])
        refused = client.post(endpoint(run_dir, "/requirement"), json=requirement(head))
        assert refused.status_code == 409, refused.text
    finally:
        provider_control.release()
    chat.settle(client, started["chat_id"])


def test_ordinary_session_does_not_attach_existing_context(app, client: TestClient, run_dir: Path):
    initialize(client, run_dir)
    started = chat.start_session(client, run_dir)
    chat.settle(client, started["chat_id"])
    assert app.state.server.chats[UUID(started["chat_id"])].run.context.engineering_context is None


def test_context_routes_use_the_existing_authentication_guard(app, run_dir: Path):
    with TestClient(app) as unauthenticated:
        assert unauthenticated.get(endpoint(run_dir)).status_code == 401
        assert unauthenticated.post(endpoint(run_dir, "/init"), json={}).status_code == 401


def test_preview_preserves_long_prose_and_omits_embedded_private_references(
    client: TestClient, run_dir: Path
):
    head = initialize(client, run_dir)
    text = "A" * 1000 + ' Read "C:\\private\\source.SLDPRT"; native_reference=YWJj'
    response = client.post(endpoint(run_dir, "/requirement"), json=requirement(head, text=text))
    assert response.status_code == 200, response.text
    preview = client.get(endpoint(run_dir)).json()
    shown = preview["records"][0]["record"]["text"]
    assert shown.startswith("A" * 1000)
    assert "private path omitted" in shown and "native reference omitted" in shown
    assert "source.SLDPRT" not in json.dumps(preview)
    assert "YWJj" not in json.dumps(preview)


def test_target_list_is_bounded_with_exact_omission_count(
    client: TestClient, run_dir: Path, monkeypatch
):
    from swreview.chat import engineering_context

    label = engineering_context._target_label
    indexes = []

    def counted(*args, **kwargs):
        indexes.append((kwargs.get("documents"), kwargs.get("components")))
        return label(*args, **kwargs)

    monkeypatch.setattr(engineering_context, "_target_label", counted)
    package = build_package()
    package.components = [
        package.components[0].model_copy(
            update={
                "id": f"cmp:{number:04d}",
                "full_path": f"housing-{number}",
            }
        )
        for number in range(1, 503)
    ]
    save_package(package, run_dir)
    view = client.get(endpoint(run_dir)).json()
    assert len(view["targets"]) == 500
    assert view["targets_omitted"] == 4
    assert len(indexes) == 500
    assert indexes[0][0] is not None and indexes[0][1] is not None
    assert all(docs is indexes[0][0] and comps is indexes[0][1] for docs, comps in indexes)


def test_source_switch_does_not_relabel_the_historical_occurrence(
    client: TestClient, run_dir: Path
):
    head = initialize(client, run_dir)
    assert client.post(endpoint(run_dir, "/requirement"), json=requirement(head)).status_code == 200
    package = load_package(run_dir).package
    package.components[0].full_path = "replacement-instance"
    save_package(package, run_dir)
    row = client.get(endpoint(run_dir)).json()["records"][0]
    assert row["binding"]["needs_review"]
    assert "housing-1" in row["record"]["anchor"]["label"]
    assert "replacement-instance" not in row["record"]["anchor"]["label"]


def test_startup_reservation_blocks_writes_and_provider_failure_releases_it(
    app, client: TestClient, run_dir: Path
):
    head = initialize(client, run_dir)
    entered, release = threading.Event(), threading.Event()

    def fail_provider(settings):
        entered.set()
        assert release.wait(5.0)
        raise RuntimeError("Fictional provider construction failed.")

    app.state.server.provider_factory = fail_provider
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(client.post, "/sessions", json=chat.session_body(run_dir))
        try:
            assert entered.wait(5.0)
            refused = client.post(endpoint(run_dir, "/requirement"), json=requirement(head))
            assert refused.status_code == 409, refused.text
        finally:
            release.set()
        assert response.result().status_code == 502
    saved = client.post(endpoint(run_dir, "/requirement"), json=requirement(head))
    assert saved.status_code == 200, saved.text


@pytest.mark.parametrize("attachment", [None, {}, {"source_path": "C:\\private\\input.json"}])
def test_malformed_attachments_never_construct_a_provider(
    client: TestClient, run_dir: Path, provider_control, attachment
):
    response = client.post(
        "/sessions", json=chat.session_body(run_dir, engineering_context=attachment)
    )
    assert response.status_code == 400, response.text
    assert "private" not in response.text
    assert not provider_control.built


def test_changed_package_attachment_is_refused_before_provider_setup(
    client: TestClient, run_dir: Path, provider_control
):
    head = initialize(client, run_dir)
    attachment = {key: head[key] for key in ("context_id", "head_digest", "package_sha256")}
    (run_dir / "package.json").write_bytes((run_dir / "package.json").read_bytes() + b"\n")
    response = client.post(
        "/sessions", json=chat.session_body(run_dir, engineering_context=attachment)
    )
    assert response.status_code == 409, response.text
    assert not provider_control.built


def test_symlinked_package_and_private_store_are_refused(
    client: TestClient, run_dir: Path, run_root: Path, tmp_path: Path
):
    source = run_dir / "package.json"
    real = tmp_path / "private-package.json"
    source.rename(real)
    try:
        source.symlink_to(real)
    except OSError:
        real.rename(source)
        pytest.skip("Windows symlink privilege is unavailable")
    assert client.get(endpoint(run_dir)).status_code == 404
    source.unlink()
    real.rename(source)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (run_root / ".engineering-context").symlink_to(elsewhere, target_is_directory=True)
    response = client.post(endpoint(run_dir, "/init"), json={})
    assert response.status_code == 400, response.text
    assert list(elsewhere.iterdir()) == []


def test_checks_first_reassesses_attached_context_before_the_opening_prompt(
    app, client: TestClient, run_dir: Path
):
    save_package(live_prerun_package(), run_dir)
    head = initialize(client, run_dir)
    saved = client.post(
        endpoint(run_dir, "/requirement"),
        json=requirement(head, entity_id=FIRST_INSTANCE),
    )
    assert saved.status_code == 200, saved.text
    row = client.get(endpoint(run_dir)).json()["records"][0]
    confirmed = client.post(
        endpoint(run_dir, "/confirm"),
        json={
            "expected_head": saved.json()["head_digest"],
            "record_id": "req:operating",
            "actor": "fictional-engineer",
            "expected_record_digest": row["record_digest"],
            "expected_dependency_digest": row["dependency_digest"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    head = confirmed.json()
    attachment = {key: head[key] for key in ("context_id", "head_digest", "package_sha256")}
    bridge = ScriptedReviewBridge(
        results={
            "interference": [
                {
                    "interferences": [dict(row) for row in LIVE_ROWS],
                    "gaps": [dict(VOLUME_UNIT_GAP)],
                }
            ]
        }
    )
    app.state.server.bridge_factory = lambda pipe, secret: bridge
    started = chat.start_session(
        client,
        run_dir,
        engineering_context=attachment,
        bridge={"pipe": "fictional-pipe", "secret": "fictional-secret"},
    )
    chat.settle(client, started["chat_id"])
    assert [name for name, _ in bridge.calls] == ["interference"]
    run = app.state.server.chats[UUID(started["chat_id"])].run
    current = build_summary(run.context.engineering_context, run.context.package)
    assert current["records"][0]["decision"] == "confirmed"
    # Owner decision 107A: the live check's rewrite of the package keeps the input matched.
    assert current["records"][0]["binding"] == "matched_snapshot"
    assert current["records"][0]["needs_review"] is False
    retained = json.loads((run_dir / "engineering-context-summary.json").read_text())
    assert retained == current
    assert compact_json(current) in run.opening_message
    assert client.get(endpoint(run_dir)).json()["head_digest"] == head["head_digest"]


def test_reserved_native_reference_ids_are_refused_without_echoing_the_value(
    client: TestClient, run_dir: Path
):
    head = initialize(client, run_dir)
    response = client.post(
        endpoint(run_dir, "/requirement"),
        json=requirement(head, record_id="native_reference:YWJj"),
    )
    assert response.status_code == 400, response.text
    assert "YWJj" not in response.text
    assert client.get(endpoint(run_dir)).json()["head_digest"] == head["head_digest"]


def test_existing_private_identifiers_are_omitted_from_operator_projection(
    client: TestClient, run_dir: Path, run_root: Path
):
    head = initialize(client, run_dir)
    workflow.enter_requirement(
        run_dir,
        run_root / ".engineering-context" / run_dir.name,
        record_id="native_reference:YWJj",
        kind="component",
        entity_id="cmp:0001",
        text="Fictional requirement.",
        expected_head=head["head_digest"],
    )
    response = client.get(endpoint(run_dir))
    assert response.status_code == 200, response.text
    assert response.json()["records"][0]["record"]["record_id"] is None
    assert "YWJj" not in response.text


@pytest.mark.parametrize("segment", ["answer_keys", "case_files"])
@pytest.mark.parametrize("location", ["root", "run"])
def test_withheld_paths_are_neutral_refusals_before_any_package_read(
    app,
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
    provider_control,
    segment: str,
    location: str,
):
    from swreview.chat import engineering_context

    def forbidden_read(*args, **kwargs):
        pytest.fail("A refused path reached the package loader")

    monkeypatch.setattr(engineering_context, "load_package", forbidden_read)
    fictional = tmp_path / "fictional" / "benchmarks"
    if location == "root":
        root, run_id = fictional / segment, "saved-run"
    else:
        root, run_id = fictional, segment
    (root / run_id).mkdir(parents=True)
    app.state.server.run_root = root
    response = client.get(f"/engineering-context/{run_id}")
    assert response.status_code == 404, response.text
    assert str(tmp_path) not in response.text and "benchmarks" not in response.text
    response = client.post(f"/engineering-context/{run_id}/init", json={})
    assert response.status_code == 404, response.text
    assert str(tmp_path) not in response.text and "benchmarks" not in response.text
    assert not provider_control.built


def test_waiting_engineer_review_keeps_the_attached_context_frozen(
    app, client: TestClient, run_dir: Path, provider_control
):
    head = initialize(client, run_dir)
    saved = client.post(endpoint(run_dir, "/requirement"), json=requirement(head))
    assert saved.status_code == 200, saved.text
    head = saved.json()
    row = client.get(endpoint(run_dir)).json()["records"][0]
    attachment = {key: head[key] for key in ("context_id", "head_digest", "package_sha256")}
    provider_control.script = [
        chat.turn(
            "I need the thread depth.", chat.call("request_evidence", **chat.EVIDENCE_ARGUMENTS)
        ),
        chat.turn("Thanks; the question is answered."),
    ]
    started = chat.start_session(client, run_dir, engineering_context=attachment)
    assert chat.settle(client, started["chat_id"]) == "waiting_engineer"
    response = client.post(endpoint(run_dir, "/requirement"), json=requirement(head))
    assert response.status_code == 409, response.text
    response = client.post(
        endpoint(run_dir, "/confirm"),
        json={
            "expected_head": head["head_digest"],
            "record_id": "req:operating",
            "actor": "fictional-engineer",
            "expected_record_digest": row["record_digest"],
            "expected_dependency_digest": row["dependency_digest"],
        },
    )
    assert response.status_code == 409, response.text
    assert client.get(endpoint(run_dir)).json()["head_digest"] == head["head_digest"]
    held = app.state.server.chats[UUID(started["chat_id"])].run.context.engineering_context
    assert held.revision == head["revision"]
    assert (
        client.post(
            f"/sessions/{started['chat_id']}/evidence/ER-001", json={"answer": "12 mm"}
        ).status_code
        == 202
    )
    assert chat.settle(client, started["chat_id"]) == "ended"
    assert client.post(endpoint(run_dir, "/requirement"), json=requirement(head)).status_code == 200
