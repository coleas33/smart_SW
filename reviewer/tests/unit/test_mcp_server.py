"""The general-chat MCP server, driven by a real `mcp` client over in-memory streams (T058).

Every assertion here is a line of `contracts/mcp-toolset.md`, and the point of driving a
real `mcp.client.session.ClientSession` rather than calling the handlers is that the CLI on
the workstation sees exactly this: the tool list it is offered, the schemas it encodes, and
the shape an error comes back in.

Four rules get the most attention, because each is a promise made somewhere else:

- **the tool list is the contract's, exactly.** Not a superset with the check tools quietly
  left in, and not "whatever `REGISTRATIONS` happens to hold" - general chat cannot create
  findings, coverage or evidence requests (FR-025) and cannot start an interference run,
  and the list below is written out by hand so that adding a tool to feature 001's registry
  cannot widen general chat's surface without this test going red;
- **no call is invisible.** SC-003 admits no missing call *including failures*, so a tool
  that raised, a tool that returned `{"error": ...}` and a name nobody registered all leave
  a `status: "error"` line in `chat-log.jsonl`;
- **a failure looks the same whichever way it failed.** The CLI must not have to guess
  whether an error result was a result;
- **`bridge_*` exists only when a bridge pipe was configured**, and `bridge_interference`
  never does.
"""

from __future__ import annotations

import functools
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
import pytest
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from pydantic import ValidationError

from swreview.agent.providers.schema import tool_spec
from swreview.exceptions import EXCEPTIONS_FILE_NAME
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import Design, EvidencePackage
from swreview.mcp import server as mcp_server
from swreview.mcp.chat_log import CHAT_LOG_FILE_NAME
from swreview.mcp.server import (
    MCP_BRIDGE_TOOL_FUNCTIONS,
    MCP_TOOL_FUNCTIONS,
    PACKAGE_SUMMARY_URI,
    REPORT_URI,
    create_server,
    default_bridge_factory,
)
from swreview.report.dispositions import REPORT_FILE_NAME
from swreview.tools import bridge as bridge_module
from swreview.tools import measure, query, rms_query, session
from tests.support.contracts import CONTRACTS_DIR_002

TIMEOUT_S = 10.0
"""No exchange over a memory stream takes a second; this only stops a hang from hanging CI."""

CLI_NAME = "codex"
CLI_VERSION = "0.115.0"

QUERY_TOOLS: tuple[str, ...] = (
    "get_package_summary",
    "list_components",
    "get_component",
    "find_components",
    "list_mates",
    "list_holes",
    "list_fasteners",
    "list_interferences",
    "get_drawing_sheet",
    "find_dimensions",
    "list_gaps",
    "get_exceptions",
    "list_features",
    "get_feature",
    "list_equations",
)
MEASUREMENT_TOOLS: tuple[str, ...] = (
    "measure_axis_distance",
    "measure_face_gap",
    "check_tool_envelope",
    "bounding_box",
)
CAPTURE_TOOLS: tuple[str, ...] = ("request_capture",)
BRIDGE_TOOLS: tuple[str, ...] = ("bridge_capture", "bridge_measure")

OFFLINE_TOOLS: tuple[str, ...] = (*QUERY_TOOLS, *MEASUREMENT_TOOLS, *CAPTURE_TOOLS)
"""The four rows of the contract's table that do not need a bridge, in its order."""

WITHHELD_TOOLS: tuple[str, ...] = (
    "check_fit",
    "check_axial_stack",
    "check_fastener_joint",
    "check_hole_alignment",
    "check_interference_group",
    "record_drawing_finding",
    "request_evidence",
    "mark_coverage",
    "get_review_checklist",
    "bridge_interference",
)
"""The "Not exposed, by construction" list. Named one by one so a regression names itself."""

CHAT_LOG_FIELDS: tuple[str, ...] = (
    "at",
    "cli",
    "tool",
    "arguments",
    "status",
    "result_summary",
    "elapsed_s",
    "error",
)
"""One `chat-log.jsonl` line, exactly as data-model section 6 spells it."""

TOOL_MODULES = (query, rms_query, measure, session, bridge_module)
"""Where the tool functions actually live, so the expected schemas are derived from the
tool functions themselves rather than from the server module under test."""

CLI_PROFILES = CONTRACTS_DIR_002 / "cli-profiles.md"
"""Feature 002's profile contract, whose Codex `enabled_tools` array is the allowlist the
add-in writes into the generated `config.toml` (`CliProfileWriter.EnabledTools`)."""


def contract_enabled_tools() -> list[str]:
    """The `enabled_tools` array of the Codex profile, in the contract's order.

    One line of TOML inside a fenced block, so it is read by prefix rather than by parsing
    the whole document: the C# side compares the generated config with this same fence
    byte for byte, and this is the Python end of that comparison.
    """
    for line in CLI_PROFILES.read_text(encoding="utf-8").splitlines():
        if line.startswith("enabled_tools = ["):
            return re.findall(r'"([a-z0-9_]+)"', line)
    raise AssertionError(f"{CLI_PROFILES} has no `enabled_tools` line")


def tool_function(name: str) -> Callable[..., Any]:
    """The feature 001 tool function called `name`."""
    for module in TOOL_MODULES:
        found = getattr(module, name, None)
        if found is not None:
            return found
    raise AssertionError(f"no tool function named {name!r} in {[m.__name__ for m in TOOL_MODULES]}")


# --- driving a server over in-memory streams ------------------------------------------


Scenario = Callable[[ClientSession], Awaitable[Any]]


def talk_to(server: Server[Any], scenario: Scenario, *, cli: str = CLI_NAME) -> Any:
    """Run `scenario` against `server` over a memory stream pair and return its value.

    `raise_exceptions=True` so a bug in a handler fails the test with its own traceback
    instead of arriving as a protocol error the assertions then puzzle over. An error the
    *client* raised - an `MCPError` off the wire - is caught and re-raised out here, so a
    test asserting on it does not have to unwrap the task group's `ExceptionGroup`.
    """
    captured: list[Any] = []
    failed: list[BaseException] = []

    async def main() -> None:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as group:

                async def run_server() -> None:
                    await server.run(
                        server_streams[0],
                        server_streams[1],
                        server.create_initialization_options(),
                        raise_exceptions=True,
                    )

                group.start_soon(run_server)
                async with ClientSession(
                    client_streams[0],
                    client_streams[1],
                    client_info=types.Implementation(name=cli, version=CLI_VERSION),
                ) as client:
                    with anyio.fail_after(TIMEOUT_S):
                        await client.initialize()
                        try:
                            captured.append(await scenario(client))
                        except MCPError as exc:
                            failed.append(exc)
                group.cancel_scope.cancel()

    anyio.run(main)
    if failed:
        raise failed[0]
    return captured[0]


def tool_names(server: Server[Any]) -> list[str]:
    """The names the client is offered, in the order the server lists them."""

    async def scenario(client: ClientSession) -> list[str]:
        listed = await client.list_tools()
        return [tool.name for tool in listed.tools]

    return talk_to(server, scenario)


def call(
    server: Server[Any], name: str, arguments: dict[str, Any] | None = None, *, cli: str = CLI_NAME
) -> types.CallToolResult:
    """One `tools/call`, as the CLI makes it."""

    async def scenario(client: ClientSession) -> types.CallToolResult:
        return await client.call_tool(name, arguments or {})

    result = talk_to(server, scenario, cli=cli)
    assert isinstance(result, types.CallToolResult)
    return result


def payload_of(result: types.CallToolResult) -> dict[str, Any]:
    """The single text block of a tool result, parsed. A tool result is always one object."""
    assert len(result.content) == 1, result.content
    block = result.content[0]
    assert isinstance(block, types.TextContent), block
    parsed = json.loads(block.text)
    assert isinstance(parsed, dict), parsed
    return parsed


def chat_log(run_dir: Path) -> list[dict[str, Any]]:
    """Every line of `run_dir/chat-log.jsonl`, parsed, in the order they were written."""
    path = run_dir / CHAT_LOG_FILE_NAME
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# --- fixtures --------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path, make_package: Callable[..., EvidencePackage]) -> Path:
    """A run folder holding a readable `package.json` and nothing else."""
    directory = tmp_path / "20260913-090000-cover-assy"
    save_package(make_package(), directory)
    return directory


@pytest.fixture
def empty_run_dir(tmp_path: Path) -> Path:
    """A run folder the engineer has not pressed Review in yet: no `package.json`."""
    directory = tmp_path / "20260913-091500-terminal"
    directory.mkdir(parents=True)
    return directory


# --- the tool list ---------------------------------------------------------------------


def test_tool_list_is_the_contract_exactly(run_dir: Path) -> None:
    assert tool_names(create_server(run_dir)) == list(OFFLINE_TOOLS)


def test_the_offered_tools_are_exactly_the_profile_allowlist() -> None:
    """The two halves of the same allowlist, which no task may update on one side only.

    The server decides what general chat is offered; `enabled_tools` in the generated CLI
    profile decides what the CLI may call. A tool added here and not there is a tool the
    engineer can see and not use; added there and not here, a name the CLI is told to
    expect and never gets. Bridge tools included: the profile lists them unconditionally
    and the server offers them once a bridge pipe is configured (FR-019).
    """
    offered = [
        function.__name__ for function in MCP_TOOL_FUNCTIONS + MCP_BRIDGE_TOOL_FUNCTIONS
    ]

    assert offered == contract_enabled_tools()


def test_withheld_tools_are_absent(run_dir: Path) -> None:
    offered = set(tool_names(create_server(run_dir, bridge_pipe="swreview-test")))
    assert offered.isdisjoint(WITHHELD_TOOLS)


def test_schemas_and_descriptions_are_the_canonical_ones(run_dir: Path) -> None:
    """The rejoined description, which is what this server sends in either arm (FR-039b).

    Lever 2 moves the paragraphs after the first into the *review's* system prompt. This
    server has no system prompt to move them into, so it keeps sending both halves and
    the flag does not reach it at all (`mcp/server.py:_as_tool`).
    """

    async def scenario(client: ClientSession) -> list[types.Tool]:
        return (await client.list_tools()).tools

    for tool in talk_to(create_server(run_dir, bridge_pipe="swreview-test"), scenario):
        spec = tool_spec(tool_function(tool.name))
        assert tool.input_schema == spec.schema, tool.name
        assert tool.description == spec.full_description, tool.name


def test_every_tool_schema_is_an_object(run_dir: Path) -> None:
    """A CLI that cannot read a schema cannot call the tool; there is no free-form tool."""

    async def scenario(client: ClientSession) -> list[types.Tool]:
        return (await client.list_tools()).tools

    for tool in talk_to(create_server(run_dir), scenario):
        assert tool.input_schema.get("type") == "object", tool.name


# --- bridge tools ----------------------------------------------------------------------


def test_bridge_tools_are_absent_without_a_bridge_pipe(run_dir: Path) -> None:
    offered = tool_names(create_server(run_dir))
    assert [name for name in offered if name.startswith("bridge_")] == []


def test_bridge_tools_appear_with_a_bridge_pipe(run_dir: Path) -> None:
    offered = tool_names(create_server(run_dir, bridge_pipe="swreview-abc"))
    assert offered == [*OFFLINE_TOOLS, *BRIDGE_TOOLS]


def test_bridge_interference_is_never_offered(run_dir: Path) -> None:
    offered = tool_names(create_server(run_dir, bridge_pipe="swreview-abc"))
    assert "bridge_interference" not in offered


def test_the_default_bridge_factory_puts_the_chat_secret_on_the_client() -> None:
    """The last inch of the secret's journey: add-in -> profile env -> CLI -> here.

    Every other test injects its own `bridge_factory`, so this one line is the only place
    the real client is built; a client built without the secret is answered `unauthorized`
    by the in-process host and every capture in general chat fails.
    """
    client = default_bridge_factory("swreview-abc", "s3cret")

    assert client.pipe_name == "swreview-abc"
    assert client.secret == "s3cret"


def test_the_default_bridge_factory_leaves_a_missing_secret_missing() -> None:
    """Feature 001's console host asks for no secret; the field stays off the wire."""
    assert default_bridge_factory("swreview-abc", None).secret is None


class FakeBridge:
    """A bridge that records the calls the tools make and answers one canned capture."""

    def __init__(self, pipe_name: str, secret: str | None) -> None:
        self.pipe_name = pipe_name
        self.secret = secret
        self.calls: list[tuple[str, str]] = []

    def capture(self, persist_ref: str, view: str) -> dict[str, Any]:
        self.calls.append((persist_ref, view))
        return {"capture": {"file": "captures/cap-0001.png", "view": view}}


def test_the_bridge_pipe_and_secret_both_reach_the_factory(run_dir: Path) -> None:
    """The seam every other test injects through, pinned once: both arguments, in order.

    `bridge_secret` is the general-chat secret, and it only ever reaches the wire by being
    handed to the client built here; a factory called with the pipe alone is the whole bug
    class (every bridge call answered `unauthorized`), so the pair is asserted, not the pipe.
    """
    built: list[tuple[str, str | None]] = []

    create_server(
        run_dir,
        bridge_pipe="swreview-abc",
        bridge_secret="s3cret",
        bridge_factory=lambda pipe_name, secret: built.append((pipe_name, secret)),
    )

    assert built == [("swreview-abc", "s3cret")]


def test_a_bridge_call_reaches_the_client_that_holds_the_secret(run_dir: Path) -> None:
    """End to end over the wire: the CLI's `bridge_capture` lands on the built client.

    The factory's client is the one the tools call, and the call is logged like any other,
    so a bridge wired into general chat is neither invisible nor a different code path.

    Feature 008 T056, edited deliberately: the tool takes the entity id of the run folder's
    package and the client receives that entity's persistent reference (FR-016).
    """
    built: list[FakeBridge] = []

    def factory(pipe_name: str, secret: str | None) -> FakeBridge:
        built.append(FakeBridge(pipe_name, secret))
        return built[-1]

    server = create_server(
        run_dir,
        bridge_pipe="swreview-abc",
        bridge_secret="s3cret",
        bridge_factory=factory,
    )
    component = load_package(run_dir).package.components[0]
    result = call(server, "bridge_capture", {"entity_id": component.id, "view": "iso"})

    assert result.is_error is False
    assert payload_of(result)["file"] == "captures/cap-0001.png"
    assert [(client.pipe_name, client.secret) for client in built] == [("swreview-abc", "s3cret")]
    assert built[0].calls == [(component.persist_ref, "iso")]

    entry = chat_log(run_dir)[-1]
    assert entry["tool"] == "bridge_capture"
    assert entry["status"] == "ok"


# --- the chat log ----------------------------------------------------------------------


def test_a_call_is_appended_to_the_chat_log(run_dir: Path) -> None:
    result = call(create_server(run_dir), "get_package_summary")

    assert result.is_error is False
    assert payload_of(result)["component_count"] == 2

    lines = chat_log(run_dir)
    assert len(lines) == 1
    entry = lines[0]
    assert list(entry) == list(CHAT_LOG_FIELDS)
    assert entry["tool"] == "get_package_summary"
    assert entry["status"] == "ok"
    assert entry["error"] is None
    assert entry["arguments"] == {}
    assert entry["result_summary"]
    assert entry["elapsed_s"] >= 0.0
    assert entry["at"].endswith("Z") or "+00:00" in entry["at"]


def test_the_chat_log_names_the_cli_that_called(run_dir: Path) -> None:
    call(create_server(run_dir), "list_gaps", cli="gemini-cli")
    assert [entry["cli"] for entry in chat_log(run_dir)] == ["gemini-cli"]


def test_the_chat_log_accumulates_across_connections(run_dir: Path) -> None:
    """One run folder, one log: a second CLI session appends rather than truncating."""
    call(create_server(run_dir), "list_gaps")
    call(create_server(run_dir), "get_package_summary")
    assert [entry["tool"] for entry in chat_log(run_dir)] == [
        "list_gaps",
        "get_package_summary",
    ]


# --- failures ---------------------------------------------------------------------------


def test_a_raising_tool_and_an_error_returning_tool_look_alike(run_dir: Path) -> None:
    """The two failure routes into `RecordedTool`, seen from the client. FR-022, SC-003.

    `component_id=["a"]` fails `pydantic.validate_call` and reaches the wrapper as a raised
    exception; `component_id="cmp:9999"` is a well-formed call the tool itself refuses with
    `{"error": ...}`. Neither is distinguishable from the other on the wire, and neither is
    missing from the log.
    """
    raised = call(create_server(run_dir), "get_component", {"component_id": ["a"]})
    returned = call(create_server(run_dir), "get_component", {"component_id": "cmp:9999"})

    for result in (raised, returned):
        assert result.is_error is True
        assert list(payload_of(result)) == ["error"]
        assert payload_of(result)["error"]

    entries = chat_log(run_dir)
    assert [entry["tool"] for entry in entries] == ["get_component", "get_component"]
    assert [entry["status"] for entry in entries] == ["error", "error"]
    assert all(entry["error"] for entry in entries)


def test_an_unknown_tool_name_is_a_result_and_is_logged(run_dir: Path) -> None:
    """A CLI that invents a name gets the same error shape, and the call is still recorded."""
    result = call(create_server(run_dir), "delete_everything", {"really": True})

    assert result.is_error is True
    assert "delete_everything" in payload_of(result)["error"]

    entries = chat_log(run_dir)
    assert [(entry["tool"], entry["status"]) for entry in entries] == [
        ("delete_everything", "error")
    ]


def test_a_withheld_tool_called_by_name_is_refused(run_dir: Path) -> None:
    """The allowlist is not decoration: a name that is off the list is off the dispatcher."""
    result = call(create_server(run_dir), "check_interference_group", {})
    assert result.is_error is True
    assert "check_interference_group" in payload_of(result)["error"]


# --- a run folder with no package --------------------------------------------------------


def test_missing_package_json_still_offers_every_tool(empty_run_dir: Path) -> None:
    """The server starts. A CLI that cannot list tools cannot explain itself to anyone."""
    assert tool_names(create_server(empty_run_dir)) == list(OFFLINE_TOOLS)


def test_missing_package_json_makes_every_query_an_error_naming_the_file(
    empty_run_dir: Path,
) -> None:
    for name in QUERY_TOOLS:
        result = call(create_server(empty_run_dir), name)
        assert result.is_error is True, name
        error = payload_of(result)["error"]
        assert PACKAGE_FILE_NAME in error, name
        assert str(empty_run_dir) in error, name

    entries = chat_log(empty_run_dir)
    assert [entry["tool"] for entry in entries] == list(QUERY_TOOLS)
    assert {entry["status"] for entry in entries} == {"error"}


def test_an_unreadable_package_json_is_an_error_result_too(empty_run_dir: Path) -> None:
    """Present but unparseable is a different message and the same never-crash behaviour."""
    (empty_run_dir / PACKAGE_FILE_NAME).write_text("{ not json", encoding="utf-8")

    result = call(create_server(empty_run_dir), "get_package_summary")

    assert result.is_error is True
    assert PACKAGE_FILE_NAME in payload_of(result)["error"]
    assert [entry["status"] for entry in chat_log(empty_run_dir)] == ["error"]


def test_an_unreadable_exceptions_file_is_refused_at_startup(run_dir: Path) -> None:
    """An exception an engineer accepted must never be silently dropped (runner docstring)."""
    broken = '{"exceptions": [{"id": "nope"}]}'
    (run_dir / EXCEPTIONS_FILE_NAME).write_text(broken, encoding="utf-8")

    with pytest.raises(ValidationError):
        create_server(run_dir)


# --- a package that appears or changes while the CLI is running ---------------------------


def test_a_package_written_after_the_cli_started_is_picked_up(
    empty_run_dir: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    """The Ask tab extracts evidence into the folder a CLI is already running in.

    The toolset used to be bound once, at startup, so a `package.json` that appeared a
    second later was never read and the only cure was to restart the CLI - which is exactly
    what the Extract evidence button in the Task Pane asks the engineer not to do.
    """
    server = create_server(empty_run_dir)

    async def scenario(
        client: ClientSession,
    ) -> tuple[types.CallToolResult, types.CallToolResult]:
        before = await client.call_tool("get_package_summary", {})
        save_package(make_package(), empty_run_dir)
        after = await client.call_tool("get_package_summary", {})
        return before, after

    before, after = talk_to(server, scenario)

    assert before.is_error is True
    assert PACKAGE_FILE_NAME in payload_of(before)["error"]
    assert after.is_error is False
    assert payload_of(after)["design_name"] == "cover-assy"


def test_a_package_rewritten_while_the_cli_runs_is_reloaded(
    run_dir: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    """A second extraction into the same run folder. The CLI keeps running; the evidence moves."""
    rebuilt = make_package(
        design=Design(
            design_id="dsn:1",
            name="cover-assy-rebuilt",
            root_assembly_document_id="doc:1",
            active_configuration="Default",
            drawing_document_ids=[],
        )
    )
    server = create_server(run_dir)

    async def scenario(
        client: ClientSession,
    ) -> tuple[types.CallToolResult, types.CallToolResult]:
        first = await client.call_tool("get_package_summary", {})
        save_package(rebuilt, run_dir)
        second = await client.call_tool("get_package_summary", {})
        return first, second

    first, second = talk_to(server, scenario)

    assert payload_of(first)["design_name"] == "cover-assy"
    assert payload_of(second)["design_name"] == "cover-assy-rebuilt"


def test_an_unchanged_package_is_read_once_however_many_calls_are_made(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lazily, not on every call: the package is parsed again only when the file moved."""
    loads: list[Path] = []
    real = mcp_server.load_package

    def counting(directory: Path) -> Any:
        loads.append(directory)
        return real(directory)

    monkeypatch.setattr(mcp_server, "load_package", counting)
    server = create_server(run_dir)

    async def scenario(client: ClientSession) -> None:
        await client.call_tool("get_package_summary", {})
        await client.call_tool("get_package_summary", {})

    talk_to(server, scenario)

    assert loads == [run_dir]


# --- resources ---------------------------------------------------------------------------


def test_the_package_summary_resource_is_offered_and_readable(run_dir: Path) -> None:
    async def scenario(client: ClientSession) -> tuple[list[str], types.ReadResourceResult]:
        listed = await client.list_resources()
        return [str(item.uri) for item in listed.resources], await client.read_resource(
            PACKAGE_SUMMARY_URI
        )

    uris, read = talk_to(create_server(run_dir), scenario)

    assert uris == [PACKAGE_SUMMARY_URI]
    contents = read.contents[0]
    assert isinstance(contents, types.TextResourceContents)
    assert json.loads(contents.text)["component_count"] == 2


def test_the_report_resource_appears_only_once_a_report_exists(run_dir: Path) -> None:
    async def uris(client: ClientSession) -> list[str]:
        return [str(item.uri) for item in (await client.list_resources()).resources]

    assert talk_to(create_server(run_dir), uris) == [PACKAGE_SUMMARY_URI]

    (run_dir / REPORT_FILE_NAME).write_text("# Review\n\nOne finding.\n", encoding="utf-8")

    async def scenario(client: ClientSession) -> tuple[list[str], types.ReadResourceResult]:
        return await uris(client), await client.read_resource(REPORT_URI)

    listed, read = talk_to(create_server(run_dir), scenario)
    assert listed == [PACKAGE_SUMMARY_URI, REPORT_URI]
    contents = read.contents[0]
    assert isinstance(contents, types.TextResourceContents)
    assert contents.text == "# Review\n\nOne finding.\n"


def test_no_resource_is_offered_when_there_is_no_package(empty_run_dir: Path) -> None:
    async def uris(client: ClientSession) -> list[str]:
        return [str(item.uri) for item in (await client.list_resources()).resources]

    assert talk_to(create_server(empty_run_dir), uris) == []


def test_reading_a_resource_this_run_has_not_got_is_an_error(empty_run_dir: Path) -> None:
    async def scenario(client: ClientSession) -> Any:
        return await client.read_resource(PACKAGE_SUMMARY_URI)

    with pytest.raises(MCPError) as raised:
        talk_to(create_server(empty_run_dir), scenario)
    assert PACKAGE_SUMMARY_URI in str(raised.value)


# --- the server's own identity -------------------------------------------------------------


def test_the_server_is_named_swreview_without_underscores(run_dir: Path) -> None:
    """Gemini names tools `mcp_swreview_<tool>`; an underscore here would split that name."""

    async def scenario(client: ClientSession) -> types.Implementation | None:
        return client.server_info

    info = talk_to(create_server(run_dir), scenario)
    assert info is not None
    assert info.name == "swreview"


# --- `swreview mcp` ------------------------------------------------------------------------


def _invoke_mcp(monkeypatch: pytest.MonkeyPatch, *args: str) -> tuple[Any, list[dict[str, Any]]]:
    """Run `swreview mcp ...` with the stdio server stubbed out, and report what it was told."""
    from typer.testing import CliRunner

    from swreview import cli
    from swreview.mcp import server as mcp_server

    calls: list[dict[str, Any]] = []

    def fake_serve(run_dir: Path, **keywords: Any) -> None:
        calls.append({"run_dir": run_dir, **keywords})

    monkeypatch.setattr(mcp_server, "serve", fake_serve)
    return CliRunner().invoke(cli.app, ["mcp", *args]), calls


def test_swreview_mcp_passes_the_run_dir_pipe_and_resolved_secret(
    monkeypatch: pytest.MonkeyPatch, run_dir: Path
) -> None:
    monkeypatch.setenv("SWREVIEW_BRIDGE_SECRET", "s3cret")

    result, calls = _invoke_mcp(
        monkeypatch,
        "--run-dir",
        str(run_dir),
        "--bridge-pipe",
        "swreview-abc",
        "--bridge-secret-env",
        "SWREVIEW_BRIDGE_SECRET",
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "run_dir": run_dir,
            "bridge_pipe": "swreview-abc",
            "bridge_secret": "s3cret",
        }
    ]


def test_swreview_mcp_needs_only_a_run_dir(
    monkeypatch: pytest.MonkeyPatch, run_dir: Path
) -> None:
    result, calls = _invoke_mcp(monkeypatch, "--run-dir", str(run_dir))

    assert result.exit_code == 0, result.output
    assert calls == [{"run_dir": run_dir, "bridge_pipe": None, "bridge_secret": None}]


def test_swreview_mcp_refuses_a_bridge_whose_secret_variable_is_unset(
    monkeypatch: pytest.MonkeyPatch, run_dir: Path
) -> None:
    """A bridge call with no secret is answered `unauthorized`; say so now, not per call."""
    monkeypatch.delenv("SWREVIEW_BRIDGE_SECRET", raising=False)

    result, calls = _invoke_mcp(
        monkeypatch,
        "--run-dir",
        str(run_dir),
        "--bridge-pipe",
        "swreview-abc",
        "--bridge-secret-env",
        "SWREVIEW_BRIDGE_SECRET",
    )

    assert result.exit_code == 1
    assert "SWREVIEW_BRIDGE_SECRET" in result.output
    assert calls == []


def test_swreview_mcp_never_takes_the_secret_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the *name* of a variable is accepted; a secret on a command line is public."""
    from typer.testing import CliRunner

    from swreview import cli

    # Plain, wide, colourless help: on CI typer's rich renderer wraps the option column at
    # 80 cells and interleaves ANSI codes, which split the very token this test looks for.
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})
    output = re.sub(r"\[[0-9;]*m", "", runner.invoke(cli.app, ["mcp", "--help"]).output)
    assert "--bridge-secret-env" in output
    assert "--bridge-secret " not in output


# --- a reload racing a call ----------------------------------------------------------------


def test_a_refresh_racing_a_call_never_escapes_and_always_leaves_a_log_line(
    run_dir: Path,
) -> None:
    """The reload is not serialized against the call by anything above `Toolset`.

    `on_call_tool` runs `toolset.call` on a worker thread while the resource handlers call
    `toolset.refresh()` from the event loop, and the low-level server dispatches every
    request in its own task, so the two genuinely overlap. A call that came apart in that
    overlap would raise past the sink and appear in no `chat-log.jsonl` line, which is the
    one thing SC-003 forbids - so the toolset, not its callers, has to hold a lock.

    The package is removed and restored under the refresher, because that is what makes
    `dispatch` flip between a bound dispatch and `None`: an error result is a fine answer
    here, an exception is not.
    """
    toolset = mcp_server.build_toolset(run_dir)
    package_file = run_dir / PACKAGE_FILE_NAME
    body = package_file.read_bytes()
    stop = threading.Event()
    escaped: list[BaseException] = []
    calls = 200

    def churn() -> None:
        while not stop.is_set():
            try:
                package_file.unlink(missing_ok=True)
                toolset.refresh()
                package_file.write_bytes(body)
                toolset.refresh()
            except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
                escaped.append(exc)
                return

    refresher = threading.Thread(target=churn, name="refresh-churn", daemon=True)
    refresher.start()
    try:
        for _ in range(calls):
            try:
                toolset.call("get_package_summary", {})
            except BaseException as exc:  # noqa: BLE001 - the failure under test
                escaped.append(exc)
                break
    finally:
        stop.set()
        refresher.join(timeout=10.0)

    assert escaped == []
    assert len(chat_log(run_dir)) == calls


def test_two_refreshes_never_interleave(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`refresh` assigns `package`, `dispatch` and `unavailable` together or not at all.

    Two threads inside `_bind` at once would leave a caller dispatching against one
    package with the other's dispatch. The lock is held for the whole of `refresh`, so the
    second thread waits and then sees the stamp the first one recorded.
    """
    inside = 0
    overlapped = False
    real_bind = mcp_server._bind

    def slow_bind(*args: Any, **keywords: Any) -> Any:
        nonlocal inside, overlapped
        inside += 1
        overlapped = overlapped or inside > 1
        try:
            time.sleep(0.05)
            return real_bind(*args, **keywords)
        finally:
            inside -= 1

    monkeypatch.setattr(mcp_server, "_bind", slow_bind)
    toolset = mcp_server.build_toolset(run_dir)

    def rebind() -> None:
        # A stamp that is not the one on file, so `refresh` really re-binds rather than
        # returning at its first line.
        toolset.stamp = None
        toolset.refresh()

    threads = [threading.Thread(target=rebind, name=f"refresh-{index}") for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert overlapped is False
    assert toolset.dispatch is not None


def test_a_resource_request_waits_for_the_call_it_overlaps(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`resources/list` arrives in its own task, and must not reload under a running call.

    It also must not parse a package on the event loop: the refresh goes to a worker
    thread, under the same lock `tools/call` holds, so the order below is the only one
    possible.
    """
    timeline: list[str] = []
    real_call = mcp_server.Toolset.call
    real_resources = mcp_server._resources

    def slow_call(self: Any, name: str, arguments: Any) -> Any:
        timeline.append("call-start")
        time.sleep(0.2)
        try:
            return real_call(self, name, arguments)
        finally:
            timeline.append("call-end")

    def noted_resources(*args: Any, **keywords: Any) -> Any:
        timeline.append("resources")
        return real_resources(*args, **keywords)

    monkeypatch.setattr(mcp_server.Toolset, "call", slow_call)
    monkeypatch.setattr(mcp_server, "_resources", noted_resources)
    server = create_server(run_dir)

    async def scenario(client: ClientSession) -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(functools.partial(client.call_tool, "get_package_summary", {}))
            await anyio.sleep(0.05)
            await client.list_resources()

    talk_to(server, scenario)

    assert timeline == ["call-start", "call-end", "resources"]


def test_a_call_reads_the_dispatch_it_uses_exactly_once(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrow window the stress test above can only sample: `call` used to read
    `self.dispatch` twice - once to test it, once to call it - and a refresh that cleared it
    in between raised `AttributeError` out of `call`, past the sink and into the CLI as a
    protocol error rather than an error result.

    The race is made deterministic by handing the attribute out once: what `call` found has
    to be what `call` uses, which is what a local snapshot guarantees.
    """

    class Vanishing:
        """A `dispatch` that is cleared by a concurrent refresh after its first read."""

        def __init__(self, value: Any) -> None:
            self.remaining = [value]

        def __get__(self, instance: Any, owner: Any = None) -> Any:
            return self.remaining.pop() if self.remaining else None

        def __set__(self, instance: Any, value: Any) -> None:
            self.remaining = [value]

    toolset = mcp_server.build_toolset(run_dir)
    monkeypatch.setattr(
        mcp_server.Toolset, "dispatch", Vanishing(toolset.dispatch), raising=False
    )

    result = toolset.call("get_package_summary", {})

    assert result.is_error is False
    assert result.payload["design_name"] == "cover-assy"
