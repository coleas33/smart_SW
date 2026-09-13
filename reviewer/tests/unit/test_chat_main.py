"""The program the pane actually launches, driven as a subprocess (T037a).

`test_chat_server.py` drives the application in-process and `T033` drives a stub script, so
neither of them ever runs `swreview chat serve`. This module does, both ways the add-in can
start it - the console script and `python -m swreview.chat` - because the handshake is a
property of the *process*, not of the app:

- the **first** stdout line is `{"port": ..., "token": ...}` with a 32-byte base64url token,
  and the port in it is the port the server is really listening on;
- **nothing else ever reaches stdout.** uvicorn's default logging configuration sends the
  access log there, which would corrupt the handshake and can block the child once the
  parent stops draining the pipe (research R7), so both handlers are on stderr - and the
  access log is asserted to be arriving on stderr, so "stdout is empty" is not passing for
  the trivial reason that nothing was logged at all;
- the socket is **loopback only**: the workstation's own LAN address refuses;
- `--fail-bridge 3` forces three bridge failures, so the fourth call is refused by the
  breaker. `test_bridge_client.py` owns the breaker rule itself; what is asserted here is
  that the hook reaches a real session's tools through the real entry point.
"""

from __future__ import annotations

import base64
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from swreview.chat.__main__ import stderr_log_config

ORIGIN = "https://swreview.invalid"
MODEL = "fake-scripted"
TOKEN_BYTES = 32
START_TIMEOUT_S = 30.0
TURN_TIMEOUT_S = 60.0
QUIET_S = 0.5
"""How long stdout is watched after the last request before it is called silent."""

SCRIPT_NAME = "swreview.exe" if sys.platform == "win32" else "swreview"
CONSOLE_SCRIPT = Path(sys.executable).parent / SCRIPT_NAME
"""The console script beside this interpreter: what the add-in runs (`pyproject.toml`)."""

LAUNCHERS: dict[str, list[str]] = {
    "console-script": [str(CONSOLE_SCRIPT), "chat", "serve"],
    "module": [sys.executable, "-m", "swreview.chat"],
}
"""The two ways the add-in can start the backend. They must behave identically."""


@dataclass
class Backend:
    """A running backend process and everything it has said since the handshake."""

    process: subprocess.Popen[str]
    port: int
    token: str
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}",
            headers={"Authorization": f"Bearer {self.token}", "Origin": ORIGIN},
            timeout=30.0,
        )

    def wait_for_stdout(self) -> list[str]:
        """Whatever stdout says after a settling moment; the contract says: nothing."""
        time.sleep(QUIET_S)
        return list(self.stdout)


def _drain(stream: Any, sink: list[str]) -> threading.Thread:
    """Keep reading a pipe into `sink`.

    Draining is not optional: the contract warns that a parent which stops reading can
    block the child, and a test that let the pipe fill would be reproducing that bug
    rather than testing around it.
    """

    def pump() -> None:
        for line in stream:
            sink.append(line.rstrip("\r\n"))

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


@contextmanager
def backend(command: list[str], *arguments: str) -> Iterator[Backend]:
    """Start the backend, read its handshake, and make sure it is gone afterwards."""
    process = subprocess.Popen(  # noqa: S603 - the command is this test's own
        [*command, "--port", "0", "--allow-origin", ORIGIN, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    errors: list[str] = []
    assert process.stdout is not None and process.stderr is not None
    error_pump = _drain(process.stderr, errors)
    try:
        line = process.stdout.readline()
        assert line, "the backend printed nothing before exiting: " + "\n".join(errors)
        handshake = json.loads(line)
        started = Backend(
            process=process, port=int(handshake["port"]), token=str(handshake["token"])
        )
        started.stderr = errors
        _drain(process.stdout, started.stdout)
        _wait_for_health(started)
        yield started
    finally:
        process.terminate()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=15)
        if process.poll() is None:  # pragma: no cover - only a wedged child gets here
            process.kill()
        error_pump.join(timeout=5)


def _wait_for_health(started: Backend) -> None:
    """Poll `/health` until it answers: the socket is bound before the accept loop runs."""
    deadline = time.monotonic() + START_TIMEOUT_S
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with started.client() as client:
                response = client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(0.05)
    raise AssertionError(
        f"the backend never answered /health on port {started.port}: {last}\n"
        + "\n".join(started.stderr)
    )


def wait_until(predicate: Any, what: str, timeout: float = TURN_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def run_dir(run_root: Path, tmp_package_dir: Path) -> Path:
    target = run_root / "20260913-120000-bracket"
    shutil.copytree(tmp_package_dir, target)
    return target


def start_session(client: httpx.Client, run_dir: Path, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "run_dir": str(run_dir),
        "provider": "fake",
        "model": MODEL,
        "effort": "high",
        "bridge": None,
        "engineer": "a.engineer",
        "retry_of": None,
    }
    body.update(overrides)
    response = client.post("/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def events_of(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- the handshake -------------------------------------------------------------------


@pytest.mark.parametrize("launcher", sorted(LAUNCHERS))
def test_the_first_stdout_line_is_the_port_and_a_32_byte_token(launcher: str) -> None:
    """Both ways the pane can start the backend hand back the same handshake."""
    assert CONSOLE_SCRIPT.exists(), f"{CONSOLE_SCRIPT} is missing; is swreview installed?"

    with backend(LAUNCHERS[launcher]) as started:
        assert 1024 <= started.port <= 65535
        padded = started.token + "=" * (-len(started.token) % 4)
        assert len(base64.urlsafe_b64decode(padded)) == TOKEN_BYTES
        assert set(started.token) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        with started.client() as client:
            assert client.get("/health").json()["status"] == "ok"


def test_the_port_in_the_handshake_is_the_port_it_is_listening_on(run_dir: Path) -> None:
    with backend(LAUNCHERS["console-script"], "--run-root", str(run_dir.parent)) as started:
        with started.client() as client:
            assert client.get("/health").status_code == 200
        with closing(socket.create_connection(("127.0.0.1", started.port), timeout=5)):
            pass


def test_the_token_is_required_and_is_not_accepted_in_the_query_string() -> None:
    """The whole point of the handshake: the secret travels in a header, never in a URL."""
    with backend(LAUNCHERS["console-script"]) as started:
        with httpx.Client(base_url=f"http://127.0.0.1:{started.port}", timeout=30.0) as bare:
            assert bare.get("/health").status_code == 401
            assert bare.get(f"/health?token={started.token}").status_code == 401
        # The access log records the path *with* its query string, so the request that
        # was refused must not be the one that writes the live token to the log folder.
        time.sleep(QUIET_S)
        assert started.token not in "\n".join(started.stderr)


# --- stdout stays the handshake channel ------------------------------------------------


def test_nothing_else_is_ever_printed_to_stdout(run_dir: Path) -> None:
    """uvicorn's default access log goes to stdout; this build's must not (research R7)."""
    with backend(LAUNCHERS["console-script"], "--run-root", str(run_dir.parent)) as started:
        with started.client() as client:
            for _ in range(3):
                assert client.get("/health").status_code == 200
            chat = start_session(client, run_dir)
            wait_until(
                lambda: client.get(f"/sessions/{chat['chat_id']}").json()["state"] != "running",
                "the opening turn to end",
            )

        assert started.wait_for_stdout() == []
        logged = "\n".join(started.stderr)
        assert "/health" in logged, f"nothing was access-logged at all:\n{logged}"
        assert started.token not in logged


def test_the_startup_banner_names_the_loopback_address() -> None:
    with backend(LAUNCHERS["console-script"]) as started:
        with started.client() as client:
            client.get("/health")

        banner = "\n".join(started.stderr)
        assert "127.0.0.1" in banner


def test_the_socket_is_not_reachable_from_the_workstation_s_own_lan_address() -> None:
    """Loopback only: a port bound to 0.0.0.0 would be reachable from the network."""
    lan = _lan_address()
    if lan is None:  # pragma: no cover - a machine with no network interface
        pytest.skip("this machine has no non-loopback IPv4 address")

    with backend(LAUNCHERS["console-script"]) as started:
        with started.client() as client:
            assert client.get("/health").status_code == 200
        with pytest.raises(OSError):
            with closing(socket.create_connection((lan, started.port), timeout=2)):
                pass


def _lan_address() -> str | None:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:  # pragma: no cover - name resolution is not always configured
        return None
    for info in infos:
        address = str(info[4][0])
        if not address.startswith("127."):
            return address
    return None  # pragma: no cover - a machine with only loopback


# --- the logging configuration -----------------------------------------------------------


def test_no_log_handler_writes_to_stdout() -> None:
    """The unit behind the subprocess assertion: `default` *and* `access` on stderr."""
    config = stderr_log_config()

    handlers = config["handlers"]
    assert set(handlers) >= {"default", "access"}
    for name, handler in handlers.items():
        assert handler.get("stream") == "ext://sys.stderr", f"{name} does not write to stderr"


# --- the bridge breaker through the real entry point --------------------------------------


def test_fail_bridge_makes_the_fourth_bridge_call_the_circuit_open_one(run_dir: Path) -> None:
    """`--fail-bridge 3`: three forced failures, then the breaker refuses the fourth."""
    with backend(
        LAUNCHERS["console-script"], "--run-root", str(run_dir.parent), "--fail-bridge", "3"
    ) as started:
        with started.client() as client:
            chat = start_session(
                client,
                run_dir,
                bridge={"pipe": "swreview-test", "secret": "not-a-real-secret"},
            )
            wait_until(
                lambda: client.get(f"/sessions/{chat['chat_id']}").json()["state"] != "running",
                "the opening turn to end",
            )

    finished = [
        event["body"]
        for event in events_of(run_dir)
        if event["type"] == "tool.finished"
    ]
    started_calls = [
        event["body"]["tool"] for event in events_of(run_dir) if event["type"] == "tool.started"
    ]
    assert started_calls.count("bridge_measure") == 4
    bridge_results = [body for body in finished if body["status"] == "error"]
    assert len(bridge_results) == 4
    for body in bridge_results[:3]:
        assert "--fail-bridge" in str(body["error"])
        assert "circuit" not in str(body["error"])
    assert "BridgeOpenError" in str(bridge_results[3]["error"])
    assert "circuit is open" in str(bridge_results[3]["error"])


def test_without_the_hook_no_bridge_call_is_forced_to_fail(run_dir: Path) -> None:
    """The hook is off by default: an ordinary session makes no bridge call at all."""
    with backend(LAUNCHERS["console-script"], "--run-root", str(run_dir.parent)) as started:
        with started.client() as client:
            chat = start_session(client, run_dir)
            wait_until(
                lambda: client.get(f"/sessions/{chat['chat_id']}").json()["state"] != "running",
                "the opening turn to end",
            )

    tools = [
        event["body"]["tool"] for event in events_of(run_dir) if event["type"] == "tool.started"
    ]
    assert "bridge_measure" not in tools
    assert tools == ["get_package_summary"]
