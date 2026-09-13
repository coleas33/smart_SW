"""The live SOLIDWORKS bridge client (T073, research R3 and R4).

One JSON request per line over a Windows named pipe to
`SwReview.Extractor.Console.exe serve`, which owns the single STA thread that holds the
`SldWorks.Application` reference. **The wire format is
`extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md`** (protocol version 1.0); the
`PROTOCOL.md` beside this file records only what is true of the Python end. What this
module adds around the wire format is the three guarantees the tool layer depends on:

- **an allowlist.** `COMMANDS` is the whole vocabulary - `ping`, `capture`, `measure`,
  `interference`. Nothing else reaches the pipe, so no tool can ask SOLIDWORKS to run a
  member, a macro or a file (research R4, constitution Technical Constraints).
- **one failure type.** A non-`ok` status, an unreadable line, a response for another
  request, a dead pipe and a timeout are all `BridgeError`, which carries the host's
  `result` when it sent one (a failed `capture` carries a `Gap`). Callers have one thing
  to catch, and the tool layer turns it into an error result and `failed` coverage.
- **a circuit breaker.** `status: "circuit_open"` from the host, or `CIRCUIT_LIMIT`
  consecutive failures, stops the client calling: every further call raises
  `BridgeOpenError` instead. A SOLIDWORKS session that has begun failing COM calls does
  not recover by being asked again, and the review is better off continuing offline with
  honest `failed` coverage.

The transport is injectable. The default is a named pipe; the tests use a fake, and a
workstation that needs a real read timeout can supply a `pywin32` transport without
touching this class - `pywin32` is deliberately not a dependency (see PROTOCOL.md,
"Known limitation").
"""

from __future__ import annotations

import json
from typing import Any, Protocol

__all__ = [
    "BRIDGE_VIEWS",
    "CIRCUIT_LIMIT",
    "COMMANDS",
    "DEFAULT_PIPE_NAME",
    "DEFAULT_TIMEOUT_S",
    "PROTOCOL_VERSION",
    "BridgeClient",
    "BridgeError",
    "BridgeOpenError",
    "NamedPipeTransport",
    "Transport",
    "pipe_path",
]

DEFAULT_PIPE_NAME = "swreview"
DEFAULT_TIMEOUT_S = 60.0
PROTOCOL_VERSION = "1.0"
"""The version of the host contract this client is written against; `ping` reports the
host's, and a mismatch is worth an engineer's attention before anything is trusted."""

COMMANDS: tuple[str, ...] = ("ping", "capture", "measure", "interference")
"""Every command the bridge speaks. The allowlist of research R4, enforced before the
request is written: an unknown command never reaches SOLIDWORKS."""

BRIDGE_VIEWS: tuple[str, ...] = ("iso", "front", "top", "right", "fit")
"""The views the host can frame a capture with. Narrower than the `CaptureView` enum the
session tools accept, so a view outside it is reported, never silently substituted."""

CIRCUIT_LIMIT = 3
"""Consecutive failures after which the client stops calling (research R4)."""

_ENCODING = "utf-8"


class BridgeError(RuntimeError):
    """The bridge could not do what was asked. Every failure mode arrives as this.

    `result` is whatever the host attached to the failure - a failed `capture` carries the
    `Gap` explaining what could not be selected - so the caller can record it instead of
    losing it with the message.
    """

    def __init__(self, message: str, result: Any = None) -> None:
        super().__init__(message)
        self.result = result


class BridgeOpenError(BridgeError):
    """The circuit is open: the client has stopped calling and this one did not go out."""


def pipe_path(pipe_name: str) -> str:
    """`swreview` as the Windows named-pipe path the console host listens on."""
    return rf"\\.\pipe\{pipe_name}"


class Transport(Protocol):
    """One line out, one line back. Everything else about the pipe is private to it."""

    def request(self, line: str) -> str: ...

    def close(self) -> None: ...


class NamedPipeTransport:
    """The real transport: a Windows named pipe opened as a raw byte stream.

    The pipe is opened on the first request, not in `__init__`, so constructing a client
    never blocks and a run that ends up making no bridge call never touches SOLIDWORKS.
    """

    def __init__(
        self, pipe_name: str = DEFAULT_PIPE_NAME, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> None:
        self.path = pipe_path(pipe_name)
        self.timeout_s = timeout_s
        self._pipe: Any | None = None

    def _open(self) -> Any:
        if self._pipe is None:
            # 'r+b' with no buffering: the server answers one line per line written, and
            # a buffered writer would hold the request until the buffer filled.
            self._pipe = open(self.path, "r+b", buffering=0)  # noqa: SIM115
        return self._pipe

    def request(self, line: str) -> str:
        pipe = self._open()
        pipe.write(line.encode(_ENCODING) + b"\n")
        return self._read_line(pipe)

    def _read_line(self, pipe: Any) -> str:
        """One `\\n`-terminated line, read a byte at a time.

        A raw pipe object has no `readline` that stops at the first newline without over-
        reading into the next response, so this reads to the delimiter itself. An empty
        read means the server closed the pipe.
        """
        chunks: list[bytes] = []
        while True:
            byte = pipe.read(1)
            if not byte:
                raise BridgeError(
                    f"the bridge closed the pipe {self.path} before answering; is "
                    "`SwReview.Extractor.Console.exe serve` still running?"
                )
            if byte == b"\n":
                break
            chunks.append(byte)
        return b"".join(chunks).decode(_ENCODING).strip()

    def close(self) -> None:
        if self._pipe is not None:
            self._pipe.close()
            self._pipe = None


class BridgeClient:
    """The bridge as the tools see it: four coarse calls, or an honest failure."""

    def __init__(
        self,
        pipe_name: str = DEFAULT_PIPE_NAME,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: Transport | None = None,
    ) -> None:
        self.pipe_name = pipe_name
        self.timeout_s = timeout_s
        self.transport: Transport = (
            transport
            if transport is not None
            else NamedPipeTransport(pipe_name, timeout_s)
        )
        self._next_id = 1
        self._consecutive_failures = 0
        self._last_error: str | None = None

    # --- state ------------------------------------------------------------------

    @property
    def circuit_open(self) -> bool:
        """True once the host reported `circuit_open`, or three calls in a row failed."""
        return self._consecutive_failures >= CIRCUIT_LIMIT

    @property
    def last_error(self) -> str | None:
        """The message of the most recent failure, or `None` if nothing has failed."""
        return self._last_error

    # --- the call ---------------------------------------------------------------

    def call(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Send one command and return its `result`.

        Raises `BridgeOpenError` when the circuit is already open (nothing is sent) and
        `BridgeError` for every other failure.
        """
        if command not in COMMANDS:
            raise BridgeError(
                f"{command!r} is not a bridge command; the bridge speaks {list(COMMANDS)}"
            )
        if self.circuit_open:
            raise BridgeOpenError(
                f"the bridge circuit is open after three consecutive failures "
                f"(last: {self._last_error}); no further calls are made this run"
            )

        request_id = str(self._next_id)
        self._next_id += 1
        line = json.dumps(
            {"id": request_id, "command": command, "params": dict(params or {})},
            separators=(",", ":"),
        )
        try:
            response = self._exchange(request_id, line)
        except BridgeError as exc:
            self._fail(str(exc), opened=isinstance(exc, BridgeOpenError))
            raise
        self._consecutive_failures = 0
        return response

    def _exchange(self, request_id: str, line: str) -> Any:
        try:
            raw = self.transport.request(line)
        except BridgeError:
            raise
        except (OSError, TimeoutError) as exc:
            raise BridgeError(
                f"the bridge on {pipe_path(self.pipe_name)} could not be reached: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise BridgeError(
                f"the bridge answered with a line that is not JSON: {raw!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise BridgeError(
                f"the bridge answered with a {type(payload).__name__}, not an object"
            )

        status = payload.get("status")
        answered = payload.get("id")
        # An unparseable line comes back with an empty id and an error; that is the
        # host explaining itself, not a mismatched response.
        if answered != request_id and not (answered == "" and status == "error"):
            raise BridgeError(
                f"the bridge answered request id {answered!r}; this is request "
                f"id {request_id!r}, so the two are out of step"
            )
        if status == "circuit_open":
            raise BridgeOpenError(
                "the bridge reported its circuit open after three SOLIDWORKS failures: "
                f"{payload.get('error') or 'no error text'}",
                payload.get("result"),
            )
        if status != "ok":
            raise BridgeError(
                f"the bridge returned status {status!r}: "
                f"{payload.get('error') or 'no error text'}",
                payload.get("result"),
            )
        return payload.get("result")

    def _fail(self, message: str, opened: bool = False) -> None:
        """Count a failure. The host's own `circuit_open` opens ours at once: it will not
        answer anything else until it is restarted, so counting to three would be three
        pointless round trips."""
        self._consecutive_failures = (
            CIRCUIT_LIMIT if opened else self._consecutive_failures + 1
        )
        self._last_error = message

    # --- the four operations -----------------------------------------------------

    def ping(self) -> Any:
        """Check the host is alive, and which document and configuration it is attached to."""
        return self.call("ping", {})

    def capture(
        self,
        persist_ref: str,
        view: str = "fit",
        scope_document: str | None = None,
        note: str = "",
    ) -> Any:
        """Frame an entity and save a PNG; the result carries the IR `Capture` row.

        The host chooses where the file goes (`serve --out`), so no path is ever sent: a
        filesystem path in a request would be a write the agent controls (research R4).
        """
        return self.call(
            "capture",
            {
                "persist_ref": persist_ref,
                "view": view,
                "scope_document": scope_document,
                "note": note,
            },
        )

    def measure(
        self,
        persist_ref_a: str,
        persist_ref_b: str,
        scope_document_a: str | None = None,
        scope_document_b: str | None = None,
    ) -> Any:
        """SOLIDWORKS' own Measure between two entities. Lengths come back in metres."""
        return self.call(
            "measure",
            {
                "persist_ref_a": persist_ref_a,
                "persist_ref_b": persist_ref_b,
                "scope_document_a": scope_document_a,
                "scope_document_b": scope_document_b,
            },
        )

    def interference(
        self,
        component_ids: list[str],
        configuration: str | None = None,
        settings: dict[str, Any] | None = None,
        truncate_after: int | None = None,
    ) -> Any:
        """Run interference detection live; results come back in the IR's own shape."""
        return self.call(
            "interference",
            {
                "component_ids": list(component_ids),
                "configuration": configuration,
                "settings": dict(settings or {}),
                "truncate_after": truncate_after,
            },
        )

    def close(self) -> None:
        """Close the pipe. Safe to call when nothing was ever opened."""
        self.transport.close()
