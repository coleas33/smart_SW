"""T011: restart and kill snapshots use one fresh app and one disk-copy helper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview import atomic
from swreview.report.session import load_session
from tests.support.restart import BEFORE_REPLACE, disk_at, restarted_app
from tests.unit import test_chat_review_routes as routes
from tests.unit import test_chat_server as chat

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir
finished_chat = routes.finished_chat


def settings(provider_control: chat.ProviderControl, models: chat.Models) -> dict[str, Any]:
    return {
        "token": chat.TOKEN,
        "allow_origin": chat.ORIGIN,
        "provider_factory": provider_control.factory,
        "list_models": models,
    }


def test_restarted_app_reads_the_disk_with_no_chat_of_the_first_app(
    app: Any,
    client: TestClient,
    run_root: Path,
    run_dir: Path,
    finished_chat: str,
    provider_control: chat.ProviderControl,
    models: chat.Models,
) -> None:
    assert app.state.server.chats
    before = len(provider_control.built)
    with restarted_app(run_root, settings(provider_control, models)) as fresh:
        assert fresh.app is not app
        assert fresh.app.state.server.chats == {}
        assert fresh.get(f"/sessions/{finished_chat}/snapshot").status_code == 404
        response = fresh.get(f"/reviews/{run_dir.name}")
        assert response.status_code == 200, response.text
        assert {finding["id"] for finding in response.json()["findings"]} == {
            finding.id for finding in load_session(run_dir / "session.json").findings
        }
        assert fresh.app.state.server.chats == {}
        assert len(provider_control.built) == before


def test_a_named_custom_point_copies_the_whole_tree_once_and_execution_continues(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "FICT-review"
    nested = folder / "tool-results"
    nested.mkdir(parents=True)
    (folder / "session.json").write_bytes(b"old canonical\r\n")
    (nested / "step-1.json").write_bytes(b'{"fixture": "FICT-evidence"}\n')
    (nested / "FICT-binary.bin").write_bytes(b"\x00\xff\r\n\n\x1a")
    (nested / "FICT-empty").mkdir()
    with disk_at(folder, "before-first-usage") as cut:
        copied_root = cut.root
        assert cut.folder.name == folder.name
        assert not cut.folder.exists()
        assert cut() is None
        assert (cut.folder / "session.json").read_bytes() == b"old canonical\r\n"
        assert (cut.folder / "tool-results" / "step-1.json").read_bytes() == (
            b'{"fixture": "FICT-evidence"}\n'
        )
        assert (cut.folder / "tool-results" / "FICT-binary.bin").read_bytes() == (
            b"\x00\xff\r\n\n\x1a"
        )
        assert (cut.folder / "tool-results" / "FICT-empty").is_dir()
        (folder / "session.json").write_bytes(b"execution continued\n")
        assert cut() is None
        assert (cut.folder / "session.json").read_bytes() == b"old canonical\r\n"
    assert (folder / "session.json").read_bytes() == b"execution continued\n"
    assert not copied_root.exists()


def test_before_replace_keeps_the_old_file_and_written_temporary_beside_it(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "FICT-review"
    folder.mkdir()
    target = folder / "session.json"
    target.write_bytes(b"old canonical\r\n")
    with disk_at(folder, BEFORE_REPLACE) as cut:
        atomic.write_atomic(target, b"new canonical\n")
        assert target.read_bytes() == b"new canonical\n"
        assert (cut.folder / "session.json").read_bytes() == b"old canonical\r\n"
        temporary = list(cut.folder.glob(".session.json.*.tmp"))
        assert len(temporary) == 1
        assert temporary[0].read_bytes() == b"new canonical\n"
        assert list(folder.glob(".session.json.*.tmp")) == []


def test_a_failed_replace_cleans_the_real_folder_but_not_the_kill_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "FICT-review"
    folder.mkdir()
    target = folder / "session.json"
    target.write_bytes(b"old canonical\n")

    def refused(*args: Any) -> None:
        raise PermissionError("Fictional replace refused")

    monkeypatch.setattr(atomic.os, "replace", refused)
    with disk_at(folder, BEFORE_REPLACE) as cut:
        with pytest.raises(PermissionError, match="Fictional replace refused"):
            atomic.write_atomic(target, b"whole proposed replacement\n")
        assert target.read_bytes() == b"old canonical\n"
        assert list(folder.glob(".session.json.*.tmp")) == []
        temporary = list(cut.folder.glob(".session.json.*.tmp"))
        assert len(temporary) == 1
        assert temporary[0].read_bytes() == b"whole proposed replacement\n"


def test_the_named_point_targets_its_own_folder_and_restores_the_replace(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "FICT-review"
    other = tmp_path / "FICT-other"
    folder.mkdir()
    other.mkdir()
    replace = atomic.os.replace
    with disk_at(folder, BEFORE_REPLACE) as cut:
        atomic.write_atomic(other / "session.json", b"unrelated\n")
        assert not cut.folder.exists()
        atomic.write_atomic(folder / "session.json", b"whole\n")
        assert cut.folder.exists()
    assert atomic.os.replace is replace


def test_context_exit_after_an_exception_restores_replace_and_cleans_the_copy(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "FICT-review"
    folder.mkdir()
    replace = atomic.os.replace
    with pytest.raises(RuntimeError, match="Fictional test exception"):
        with disk_at(folder, BEFORE_REPLACE) as cut:
            copied_root = cut.root
            atomic.write_atomic(folder / "session.json", b"whole\n")
            assert cut.folder.exists()
            raise RuntimeError("Fictional test exception")

    assert atomic.os.replace is replace
    assert not copied_root.exists()
    assert (folder / "session.json").read_bytes() == b"whole\n"


def test_a_kill_copy_is_read_by_a_backend_started_fresh(
    run_dir: Path,
    finished_chat: str,
    provider_control: chat.ProviderControl,
    models: chat.Models,
) -> None:
    canonical = (run_dir / "session.json").read_bytes()
    before = len(provider_control.built)
    with disk_at(run_dir, "before-a-later-write") as cut:
        cut()
        (run_dir / "session.json").write_bytes(b"a later whole record outside the copied disk\n")
        with restarted_app(cut.root, settings(provider_control, models)) as fresh:
            assert fresh.get(f"/sessions/{finished_chat}/snapshot").status_code == 404
            response = fresh.get(f"/reviews/{run_dir.name}")
            assert response.status_code == 200, response.text
            assert (cut.folder / "session.json").read_bytes() == canonical
            assert len(provider_control.built) == before
    (run_dir / "session.json").write_bytes(canonical)
