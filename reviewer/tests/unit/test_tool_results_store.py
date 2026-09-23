"""Every tool result of every review is kept in full in the run folder (008 T066, FR-021, SC-008).

The model reads a view, and after two rounds only a stub of it; the run folder keeps the
record. `SessionSink.record` - the one funnel every step passes through, which is also what
decides the step's index - writes `tool-results/step-<index>.json` for every recorded step of
a review: ok, error, withheld, an invented tool name, the pre-run's steps and the re-call
guard's answers, whatever the settings, and before the adapter's next request. The file holds
the tool's full return, never the view. Only `start_review` gives the context a folder, so a
check run and an MCP call write none. A write that fails is failed coverage naming the step,
and the review goes on.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from swreview.agent.providers import ProviderTool, ToolCallResult, ToolSet
from swreview.agent.providers.fake import (
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import MODEL_VIEW_PANE, EfficiencySettings
from swreview.chat.server import _next_free_index
from swreview.checks.rms.run import run_rms_check
from swreview.ir.loader import save_package
from swreview.mcp.server import create_server
from swreview.report.session import ReviewSession
from tests.support.prerun import CHECKS_FIRST, prerun_package
from tests.unit import test_chat_server as chat
from tests.unit.test_chat_server import settle, start_session
from tests.unit.test_mcp_server import call as mcp_call

STORE = "tool-results"

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir


def stored(folder: Path) -> dict[int, dict[str, Any]]:
    """The stored results by step index."""
    return {
        int(path.stem.removeprefix("step-")): json.loads(path.read_text(encoding="utf-8"))
        for path in (folder / STORE).glob("step-*.json")
    }


def reviewed(
    tmp_path: Path,
    turn: ScriptedTurn,
    *,
    package: Any = None,
    name: str = "run",
    **options: Any,
) -> ReviewRun:
    folder = tmp_path / name
    save_package(package if package is not None else prerun_package(), folder)
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(script=[turn], model="fake-scripted"),
        **options,
    )
    run.start()
    return run


MIXED = ScriptedTurn(
    text="done",
    tool_calls=(
        ScriptedToolCall("get_package_summary"),
        ScriptedToolCall("get_component", {"component_id": "cmp:9999"}),
        ScriptedToolCall("no_such_tool"),
        ScriptedToolCall("check_rms_part"),
    ),
)
"""An ok call, an error, an invented name, and - under checks first - a guarded repeat."""


def assert_every_step_is_stored(session: ReviewSession, folder: Path) -> dict[int, Any]:
    files = stored(folder)
    assert sorted(files) == [step.index for step in session.steps]
    for step in session.steps:
        envelope = files[step.index]
        assert set(envelope) == {"session_id", "step", "tool", "arguments", "status", "payload"}
        assert envelope["session_id"] == str(session.session_id)
        assert envelope["step"] == step.index
        assert envelope["tool"] == step.tool
        assert envelope["arguments"] == step.arguments
        assert envelope["status"] == step.status
    return files


def test_every_step_of_a_checks_first_review_is_stored_in_full(tmp_path: Path) -> None:
    run = reviewed(tmp_path, MIXED, efficiency=CHECKS_FIRST)
    files = assert_every_step_is_stored(run.session, run.out_dir)

    by_tool = {files[i]["tool"]: files[i] for i in sorted(files)}
    assert by_tool["get_package_summary"]["status"] == "ok"
    assert by_tool["get_component"]["status"] == "error"
    assert "cmp:9999" in by_tool["get_component"]["payload"]["error"]
    assert by_tool["no_such_tool"]["status"] == "error"
    guarded = files[max(i for i in files if files[i]["tool"] == "check_rms_part")]
    assert guarded["payload"]["status"] == "already_run"
    prerun = files[min(i for i in files if files[i]["tool"] == "check_rms_part")]
    assert prerun["payload"]["findings"], "the pre-run's step is stored with its findings"


def test_a_withheld_call_is_stored_too(tmp_path: Path) -> None:
    no_tree = prerun_package().model_copy(update={"features": []})
    run = reviewed(
        tmp_path,
        ScriptedTurn(text="done", tool_calls=(ScriptedToolCall("check_rms_part"),)),
        package=no_tree,
        efficiency=EfficiencySettings(tool_tiers=True),
    )

    files = assert_every_step_is_stored(run.session, run.out_dir)
    [withheld] = [envelope for envelope in files.values() if envelope["tool"] == "check_rms_part"]
    assert withheld["status"] == "error"


def test_with_slimming_on_the_stored_payload_is_the_return_never_the_view(
    tmp_path: Path,
) -> None:
    run = reviewed(
        tmp_path,
        ScriptedTurn(text="done", tool_calls=(ScriptedToolCall("check_rms_part"),)),
        model_view=MODEL_VIEW_PANE,
    )

    [envelope] = stored(run.out_dir).values()
    payload = envelope["payload"]
    assert isinstance(payload["findings"], list), "the envelope, not the digest"
    assert "detail" not in payload
    assert any("persist_ref" in json.dumps(finding) for finding in payload["findings"])


class FileWitness:
    """The run's `ToolSet`, asserting before each call that every earlier step is on disk."""

    def __init__(self, tools: ToolSet, run: ReviewRun) -> None:
        self.tools = tools
        self.run = run
        self.checked = 0

    def __iter__(self) -> Iterator[ProviderTool]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def call(self, name: str, arguments: Mapping[str, Any], call_id: str = "") -> ToolCallResult:
        for step in self.run.session.steps:
            assert (self.run.out_dir / STORE / f"step-{step.index}.json").is_file()
            self.checked += 1
        return self.tools.call(name, arguments, call_id)


def test_each_result_is_on_disk_before_the_next_request(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    save_package(prerun_package(), folder)
    turn = ScriptedTurn(
        text="done",
        rounds=(
            ScriptedRound((ScriptedToolCall("get_package_summary"),)),
            ScriptedRound((ScriptedToolCall("list_holes"),)),
        ),
    )
    run = start_review(folder, folder, provider=FakeProvider(script=[turn], model="fake"))
    witness = FileWitness(run.tools, run)
    run.tools = witness

    run.start()

    assert witness.checked == 1, "the second round's call saw the first round's file"


def test_a_check_run_writes_no_tool_results(tmp_path: Path) -> None:
    folder = tmp_path / "check"
    save_package(prerun_package(), folder)

    run_rms_check(folder)

    assert not (folder / STORE).exists()


def test_an_mcp_call_writes_no_tool_results(tmp_path: Path) -> None:
    folder = tmp_path / "20260913-090000-chat"
    save_package(prerun_package(), folder)
    server = create_server(folder)

    mcp_call(server, "get_package_summary", {})

    assert not (folder / STORE).exists()


def test_an_unwritable_store_is_failed_coverage_naming_the_step_and_the_review_goes_on(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "run"
    save_package(prerun_package(), folder)
    (folder / STORE).write_text("a file where the folder should be", encoding="utf-8")
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[ScriptedTurn(text="done", tool_calls=(ScriptedToolCall("list_holes"),))],
            model="fake",
        ),
    )

    session = run.start()

    [item] = [i for i in session.coverage.failed if i.check == "coverage.tool_results"]
    assert "step 0" in item.reason
    assert item.error
    assert session.ended_at is not None
    assert [step.tool for step in session.steps] == ["list_holes"]


# --- the pane rotates the store with the session -------------------------------------------


def test_a_pane_retry_moves_the_store_beside_the_rotated_session(
    client: TestClient, run_dir: Path
) -> None:
    first = start_session(client, run_dir)
    settle(client, first["chat_id"])
    first_files = stored(run_dir)
    assert first_files

    second = start_session(client, run_dir, retry_of=first["chat_id"])
    settle(client, second["chat_id"])

    rotated = run_dir / f"{STORE}.1"
    assert rotated.is_dir()
    assert (run_dir / "session.1.json").is_file()
    moved = {
        int(path.stem.removeprefix("step-")): json.loads(path.read_text(encoding="utf-8"))
        for path in rotated.glob("step-*.json")
    }
    assert moved == first_files
    assert {e["session_id"] for e in moved.values()} == {first["review_session_id"]}
    assert {e["session_id"] for e in stored(run_dir).values()} == {second["review_session_id"]}


def test_the_next_free_index_skips_an_occupied_store(tmp_path: Path) -> None:
    (tmp_path / f"{STORE}.1").mkdir()

    assert _next_free_index(tmp_path) == 2
