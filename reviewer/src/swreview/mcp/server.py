"""`swreview mcp`: the read-only toolset general chat reaches (`contracts/mcp-toolset.md`).

A stdio MCP server named `swreview` (no underscores - Gemini names tools
`mcp_swreview_<tool>`, and an underscore here would split that name) over the run folder
the Task Pane is working in. The CLI in the Terminal tab talks to it; the engineer talks to
the CLI.

**It reimplements nothing.** Every call goes through the same `RecordedTool` the review
loop uses (`tools/registry.py`, T013), with two of its seams taken up rather than copied:
the recording sink is a `ChatLogSink` instead of the review session's, and `ToolContext`
carries no session at all. Argument validation, the `{"error": ...}`-to-error-result
conversion, and the rule that a tool call never raises past its caller are therefore the
same code here as there - which is why a tool that raised and a tool that returned an error
reach the CLI as the *same* error result, and why both leave a `status: "error"` line in
`chat-log.jsonl` (FR-022, SC-003).

**The tool surface is narrower than the review's, by construction.** The two rows of
feature 001's registry that write - the check tools, which create findings, and the session
tools, which create coverage and evidence requests - are simply not referenced here, so
general chat cannot create a finding, coverage or an evidence request (FR-025), and
`bridge_interference` is left out of the bridge pair because an interference run is long and
writes into `package.json`. The withholding is enforced a second time outside this process:
the general-chat bridge secret is scoped so the in-process host answers `interference` with
`unauthorized` (`contracts/README.md`). A CLI can read its own generated profile, so an
allowlist alone was never going to be the boundary.

**A run folder with no package is a working server, not a crash.** The engineer may open
the Terminal tab before pressing Review. The tool list is offered in full - a CLI that
cannot list tools cannot explain itself to anyone - and every call comes back as an error
result naming the missing `package.json`, so the CLI can say "press Review or Dump IR
first" rather than inventing an answer.

**stdout belongs to the transport.** Nothing in this module prints; diagnostics are
logging, which goes to stderr.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
import mcp_types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError

from swreview import __version__
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import ToolCallResult
from swreview.agent.providers.schema import ToolSpec
from swreview.agent.runner import load_exceptions
from swreview.agent.settings import configure_logging_redaction
from swreview.ir.loader import PACKAGE_FILE_NAME, LoadedPackage, load_package
from swreview.mcp.chat_log import ChatLogSink, chat_log_path
from swreview.report.dispositions import REPORT_FILE_NAME
from swreview.tools import bridge as bridge_tools
from swreview.tools import query, session
from swreview.tools.context import ToolContext
from swreview.tools.registry import (
    ToolDispatch,
    ToolRegistry,
    error_payload,
    measurement_tools,
    query_tools,
    record_call,
    spec_for,
)

__all__ = [
    "MCP_BRIDGE_TOOL_FUNCTIONS",
    "MCP_REGISTRY",
    "MCP_TOOL_FUNCTIONS",
    "PACKAGE_SUMMARY_URI",
    "REPORT_URI",
    "SERVER_NAME",
    "Toolset",
    "build_toolset",
    "create_server",
    "serve",
]

SERVER_NAME = "swreview"
"""The MCP server name. No underscores (`contracts/mcp-toolset.md`)."""

SERVER_VERSION = __version__
"""This build, reported in `serverInfo` so a tool-listing check can name what it talked to.

The distribution's own version and not a literal beside it: the two had already drifted
apart from what `GET /health` reported (constitution V)."""

PACKAGE_SUMMARY_URI = "swreview://package/summary"
REPORT_URI = "swreview://report"

MCP_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = (
    *query_tools(),
    *measurement_tools(),
    session.request_capture,
)
"""The contract's table, row by row: package query, measurement, captures.

The first two rows *are* feature 001's own groups, so they are referenced rather than
retyped - a new read-only query tool belongs in general chat too. The third row is one
named tool out of the session group, because the rest of that group writes. The check
group is not referenced at all. `tests/unit/test_mcp_server.py` pins the resulting names
against the contract, so a group that grows something that writes goes red here.
"""

MCP_BRIDGE_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = (
    bridge_tools.bridge_capture,
    bridge_tools.bridge_measure,
)
"""Two of feature 001's three bridge tools. `bridge_interference` is withheld: the run is
long and it writes its results into `package.json`."""

MCP_REGISTRY = ToolRegistry(
    functions=MCP_TOOL_FUNCTIONS, bridge_functions=MCP_BRIDGE_TOOL_FUNCTIONS
)
"""Feature 001's registry over the narrower lists: same wrapper, fewer tools."""


def _tool_functions(*, with_bridge: bool) -> tuple[Callable[..., Any], ...]:
    """The tools this server offers - the same tuple `ToolRegistry.dispatch` will build.

    `ToolRegistry.functions_for` answers this from a `ToolContext`, and a run folder with
    no package has none, so the one bit of state that decides it is passed directly.
    """
    if not with_bridge:
        return MCP_REGISTRY.functions
    return (*MCP_REGISTRY.functions, *MCP_REGISTRY.bridge_functions)


# --- the toolset --------------------------------------------------------------------------


@dataclass(frozen=True)
class Toolset:
    """What the server can offer and how it calls it, for one run folder.

    `dispatch` is `None` exactly when `package` is: there is no context to bind tools to,
    so `unavailable` says why and every call becomes that error - recorded through the same
    sink and in the same shape as any other failed call, because a call the engineer made
    that no log mentions is the one thing SC-003 forbids.
    """

    specs: tuple[ToolSpec, ...]
    sink: ChatLogSink
    package: LoadedPackage | None
    dispatch: ToolDispatch | None
    unavailable: str | None

    def call(self, name: str, arguments: Mapping[str, Any]) -> ToolCallResult:
        """Dispatch one call, or refuse it because this run folder has no package."""
        if self.dispatch is not None:
            return self.dispatch.call(name, arguments)
        message = self.unavailable or f"no {PACKAGE_FILE_NAME} for this run"
        payload = error_payload(message)
        record_call(
            self.sink,
            tool=name,
            arguments=arguments,
            payload=payload,
            elapsed_s=0.0,
            error=message,
        )
        return ToolCallResult(call_id="", payload=payload, is_error=True)


def build_toolset(
    run_dir: Path,
    *,
    bridge: Any | None = None,
    sink: ChatLogSink | None = None,
) -> Toolset:
    """Load `run_dir/package.json` and bind the read-only tools over it.

    An unreadable `exceptions.json` is **not** caught: an accepted condition that was
    silently dropped would be re-raised at the engineer as a fresh problem, so the server
    refuses to start instead (`agent/runner.py:load_exceptions`).
    """
    recorder = sink if sink is not None else ChatLogSink(chat_log_path(run_dir))
    functions = _tool_functions(with_bridge=bridge is not None)
    specs = tuple(spec_for(function) for function in functions)
    loaded, unavailable = _load(run_dir)
    if loaded is None:
        return Toolset(
            specs=specs, sink=recorder, package=None, dispatch=None, unavailable=unavailable
        )
    # `session=None` is the general-chat context the registry was given a sink seam for:
    # nothing here writes a finding, so there is no review session to write it to. The
    # checklist is the real one even though `get_review_checklist` is withheld - a stub
    # would be wrong the moment anything read it.
    context = ToolContext(
        package=loaded,
        session=None,
        checklist=load_checklist(),
        exceptions=load_exceptions(loaded),
        bridge=bridge,
    )
    return Toolset(
        specs=specs,
        sink=recorder,
        package=loaded,
        dispatch=MCP_REGISTRY.dispatch(context, sink=recorder),
        unavailable=None,
    )


def _load(run_dir: Path) -> tuple[LoadedPackage | None, str | None]:
    """The package in `run_dir`, or `None` and the sentence every call will report.

    The two failures read differently on purpose. "Not there yet" is the ordinary state of
    a run folder the engineer opened the Terminal tab in first, and the answer is an action
    they can take. "There but unreadable" is a real problem and says what went wrong.
    """
    package_file = run_dir / PACKAGE_FILE_NAME
    if not package_file.is_file():
        return None, (
            f"no {PACKAGE_FILE_NAME} in {run_dir}: this run folder holds no evidence package "
            "yet; press Review or Dump IR in the SOLIDWORKS Task Pane first, then restart "
            "this CLI"
        )
    try:
        return load_package(run_dir), None
    except Exception as exc:  # noqa: BLE001 - every failure becomes a tool result
        return None, (
            f"{package_file} is not an evidence package this build can read: "
            f"{type(exc).__name__}: {exc}"
        )


# --- the MCP server -------------------------------------------------------------------------


def _client_name(context: ServerRequestContext[Any]) -> str | None:
    """The `clientInfo.name` of the CLI on the other end, when it introduced itself."""
    params = context.session.client_params
    if params is None or params.client_info is None:
        return None
    return params.client_info.name


def _as_tool(spec: ToolSpec) -> types.Tool:
    """One `ToolSpec` as MCP sees it: the canonical schema, unaltered."""
    return types.Tool(name=spec.name, description=spec.description, inputSchema=spec.schema)


def _as_result(result: ToolCallResult) -> types.CallToolResult:
    """One `ToolCallResult` as MCP sees it: the payload as JSON text, error flag and all."""
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(result.payload, indent=2, ensure_ascii=False, default=str),
            )
        ],
        isError=result.is_error,
    )


def _resources(toolset: Toolset, run_dir: Path) -> list[types.Resource]:
    """The resources this run folder actually has, checked when they are asked for.

    The report is checked per request rather than at startup because a review running in
    the Review tab writes one while the CLI is connected.
    """
    offered: list[types.Resource] = []
    if toolset.package is not None:
        offered.append(
            types.Resource(
                name="package summary",
                uri=PACKAGE_SUMMARY_URI,
                description="Census of the evidence package in this run folder.",
                mimeType="application/json",
            )
        )
    if (run_dir / REPORT_FILE_NAME).is_file():
        offered.append(
            types.Resource(
                name="review report",
                uri=REPORT_URI,
                description=f"The latest {REPORT_FILE_NAME} written into this run folder.",
                mimeType="text/markdown",
            )
        )
    return offered


def _read_resource(toolset: Toolset, run_dir: Path, uri: str) -> types.TextResourceContents:
    """One resource's text, or an MCP error naming what this run folder has not got."""
    if uri == PACKAGE_SUMMARY_URI and toolset.package is not None:
        body = query.package_summary(toolset.package.package)
        return types.TextResourceContents(
            uri=uri,
            mimeType="application/json",
            text=json.dumps(body, indent=2, ensure_ascii=False),
        )
    report = run_dir / REPORT_FILE_NAME
    if uri == REPORT_URI and report.is_file():
        return types.TextResourceContents(
            uri=uri, mimeType="text/markdown", text=report.read_text(encoding="utf-8")
        )
    raise MCPError(
        code=types.INVALID_PARAMS,
        message=f"this run folder offers no resource {uri!r}",
        data=[str(item.uri) for item in _resources(toolset, run_dir)],
    )


def default_bridge_factory(pipe_name: str, secret: str | None) -> Any:
    """The live-bridge client the `bridge_*` tools call through.

    The client is cheap to build and opens the pipe on its first request, so a CLI session
    that never asks for a capture never touches SOLIDWORKS.

    `secret` is the general-chat secret from the environment, and it goes on every request
    line: the in-process tool service answers `unauthorized` without it. `None` is the
    console host of feature 001, which asks for none.
    """
    from swreview.bridge.client import BridgeClient

    return BridgeClient(pipe_name=pipe_name, secret=secret)


def create_server(
    run_dir: Path | str,
    *,
    bridge_pipe: str | None = None,
    bridge_secret: str | None = None,
    bridge_factory: Callable[[str, str | None], Any] = default_bridge_factory,
) -> Server[Any]:
    """The MCP server for one run folder, ready to be run over any stream pair.

    Args:
        run_dir: The run folder; its `package.json` is the tool context and its
            `chat-log.jsonl` is where every call is recorded.
        bridge_pipe: The in-process tool service's pipe name. Without one the two
            `bridge_*` tools are not offered at all.
        bridge_secret: The general-chat secret for that pipe, resolved from the
            environment by the caller. Never a command-line argument.
        bridge_factory: How the bridge client is built; a test passes its own.
    """
    folder = Path(run_dir)
    bridge = bridge_factory(bridge_pipe, bridge_secret) if bridge_pipe else None
    toolset = build_toolset(folder, bridge=bridge)
    calling = anyio.Lock()

    async def on_list_tools(
        context: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[_as_tool(spec) for spec in toolset.specs])

    async def on_call_tool(
        context: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        # One call at a time, and the log line's `cli` set under the same lock: the tools
        # are blocking and the sink is shared, and the in-process host serves one request
        # at a time anyway (contracts/README.md).
        async with calling:
            toolset.sink.cli = _client_name(context) or toolset.sink.cli
            arguments = dict(params.arguments or {})
            result = await anyio.to_thread.run_sync(toolset.call, params.name, arguments)
        return _as_result(result)

    async def on_list_resources(
        context: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=_resources(toolset, folder))

    async def on_read_resource(
        context: ServerRequestContext[Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[_read_resource(toolset, folder, str(params.uri))]
        )

    return Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        instructions=(
            "Read-only access to the SOLIDWORKS evidence package in this run folder. "
            "These tools report what was extracted; they never change the model and never "
            "create findings."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
    )


def resolve_bridge_secret(bridge_secret_env: str | None) -> str | None:
    """The secret in the named environment variable.

    Raises `ValueError` when the variable was named but is unset or empty: a bridge call
    with no secret is answered `unauthorized` by the in-process host, and failing at launch
    with the variable's name is far easier to act on than every capture failing later.
    """
    if bridge_secret_env is None:
        return None
    secret = os.environ.get(bridge_secret_env, "")
    if not secret:
        raise ValueError(
            f"--bridge-secret-env names {bridge_secret_env}, which is unset or empty in this "
            "process; the add-in passes the general-chat secret in the CLI's environment block"
        )
    return secret


def serve(
    run_dir: Path | str,
    *,
    bridge_pipe: str | None = None,
    bridge_secret: str | None = None,
) -> None:
    """Serve one run folder on stdio until the CLI closes it.

    The secret is installed in the logging redactor before anything can log, the way the
    chat backend installs the provider key: this process's logs are collected off the
    workstation, and a secret in one of them is a secret on someone else's disk.
    """
    configure_logging_redaction((bridge_secret,))
    server = create_server(run_dir, bridge_pipe=bridge_pipe, bridge_secret=bridge_secret)

    async def main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(main)
