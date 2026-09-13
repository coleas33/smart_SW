"""`swreview chat serve`: the program the Task Pane launches (`contracts/chat-api.md`).

Three things happen here that cannot happen inside the ASGI application, and each of them
is a rule the add-in depends on:

**The handshake owns stdout.** The add-in reads one line - `{"port", "token"}` - from the
child's stdout and never expects another. So the socket is bound *here*, before uvicorn is
handed it, which is the only way to know the port a `--port 0` server ended up on before it
starts serving; and the logging configuration puts uvicorn's **access** log on stderr
beside its error log. uvicorn's default sends the access log to stdout, which would corrupt
the handshake line and can block the child once the parent stops draining the pipe
(research R7). `stderr_log_config` is derived from uvicorn's own configuration rather than
copied out of it, so a formatter uvicorn changes stays in step and the only difference is
the stream.

**The token is generated per launch and never travels in a URL.** 32 bytes of
`secrets.token_urlsafe`, printed once to the parent over a pipe the parent alone holds.

**Redaction is installed before anything can log, and the token is one of the secrets it
masks.** The keys are in this process's environment (the add-in put them there), so the
record factory that masks them is installed before the server starts, not when the first
session is created - and the token is generated first so it can go into the same set. A
page is forbidden to put the token in a URL, but nothing stops anything else on the
workstation from trying: uvicorn's access log records the path *with* its query string, so
a single `GET /health?token=...` would write the live token into the log folder the
add-in collects (`chat-api.md`: "The token MUST NOT appear in a URL, a query string, or a
log line"). It reaches `create_app` too, so an error body cannot echo it either.

`--fail-bridge N` is the diagnostic hook of quickstart scenario 4: the first N bridge calls
are forced to fail so the breaker's refusal of the next one can be seen on a real
workstation - and, through this same entry point, in `tests/unit/test_chat_main.py`.
"""

from __future__ import annotations

import argparse
import copy
import json
import secrets
import socket
import sys
from functools import partial
from pathlib import Path
from typing import Any

import uvicorn

from swreview.agent.settings import configure_logging_redaction
from swreview.chat import DEFAULT_ALLOW_ORIGIN, DEFAULT_RUN_ROOT
from swreview.chat.server import (
    build_provider,
    create_app,
    environment_secrets,
    forced_failure_bridge_factory,
)

__all__ = ["HOST", "TOKEN_BYTES", "main", "serve", "stderr_log_config"]

HOST = "127.0.0.1"
"""Loopback, and not configurable: a flag that could widen this is a flag that will."""

TOKEN_BYTES = 32
"""Bytes of entropy in the per-launch token, base64url-encoded onto the handshake line."""


def stderr_log_config() -> dict[str, Any]:
    """uvicorn's logging configuration with every handler moved onto stderr.

    Both handlers, not just the access one: stdout carries the handshake and nothing else,
    so any handler left pointing at it is a corrupted line waiting to happen.
    """
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    for handler in config["handlers"].values():
        if str(handler.get("stream", "")).endswith("stdout"):
            handler["stream"] = "ext://sys.stderr"
    return config


def serve(
    *,
    port: int = 0,
    allow_origin: str = DEFAULT_ALLOW_ORIGIN,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    fail_bridge: int = 0,
    development: bool = False,
) -> None:
    """Bind the loopback socket, print the handshake, and serve until killed.

    Args:
        port: TCP port; 0 lets the OS choose and the chosen one goes on the handshake line.
        allow_origin: The page origin the server answers, echoed exactly and never as `*`.
        run_root: The settings run root; every `run_dir` must be strictly inside it.
        fail_bridge: Force the first N live-bridge calls to fail (quickstart scenario 4).
        development: Offer the scripted provider in `GET /health` (FR-027).
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    masked = (*environment_secrets(), token)
    configure_logging_redaction(masked)

    app = create_app(
        token=token,
        allow_origin=allow_origin,
        run_root=Path(run_root),
        provider_factory=partial(build_provider, fail_bridge=fail_bridge),
        bridge_factory=forced_failure_bridge_factory(fail_bridge) if fail_bridge else None,
        development=development,
        secrets=masked,
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
        bound.bind((HOST, port))
        _handshake(bound.getsockname()[1], token)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=HOST,
                port=bound.getsockname()[1],
                log_config=stderr_log_config(),
                access_log=True,
                lifespan="on",
            )
        )
        server.run(sockets=[bound])


def _handshake(port: int, token: str) -> None:
    """The one line stdout ever carries, flushed so the parent is not left waiting."""
    sys.stdout.write(json.dumps({"port": port, "token": token}) + "\n")
    sys.stdout.flush()


def build_parser() -> argparse.ArgumentParser:
    """The arguments of `swreview chat serve`; the Typer command forwards the same ones."""
    parser = argparse.ArgumentParser(
        prog="swreview chat serve",
        description="Serve the Task Pane chat backend on loopback.",
    )
    parser.add_argument("--port", type=int, default=0, help="TCP port; 0 picks a free one.")
    parser.add_argument(
        "--allow-origin",
        default=DEFAULT_ALLOW_ORIGIN,
        help="The page origin allowed to call this backend.",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=DEFAULT_RUN_ROOT,
        help="Run folders live here; every run_dir must be inside it.",
    )
    parser.add_argument(
        "--fail-bridge",
        type=int,
        default=0,
        metavar="N",
        help="Force the first N live-bridge calls to fail; diagnostic hook.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Development build: offer the scripted provider in /health.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """`python -m swreview.chat`. `swreview chat serve` calls `serve` directly."""
    arguments = build_parser().parse_args(argv)
    serve(
        port=arguments.port,
        allow_origin=arguments.allow_origin,
        run_root=arguments.run_root,
        fail_bridge=arguments.fail_bridge,
        development=arguments.dev,
    )


if __name__ == "__main__":
    main()
