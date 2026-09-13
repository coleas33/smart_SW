"""Unit tests for the live SOLIDWORKS bridge client (T064, T073).

The wire format under test is `extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md`
version 1.0. The transport is injectable, so the whole protocol is exercised without a
named pipe and without SOLIDWORKS: a fake transport records the lines the client wrote and
replays the lines it should read. What these tests pin is research R3 and R4:

- one JSON object per line, `{"id": "<string>", "command": …, "params": {…}}`, with the
  response matched to that id;
- every failure mode - a non-`ok` status, an unreadable line, a mismatched id, a dead
  pipe, a timeout - is a `BridgeError` carrying whatever the host attached, and nothing
  else reaches the caller;
- three consecutive failures open the circuit, and the host's own `circuit_open` opens it
  at once: the client stops calling SOLIDWORKS rather than retrying into a session that is
  already unhappy.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swreview.bridge.client import (
    BRIDGE_VIEWS,
    CIRCUIT_LIMIT,
    COMMANDS,
    BridgeClient,
    BridgeError,
    BridgeOpenError,
)


class FakeTransport:
    """A scripted bridge server: one response line per request line."""

    def __init__(self, responses: list[Any], fail_with: Exception | None = None) -> None:
        self.responses = list(responses)
        self.fail_with = fail_with
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def request(self, line: str) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        self.requests.append(json.loads(line))
        response = self.responses.pop(0)
        return response if isinstance(response, str) else json.dumps(response)

    def close(self) -> None:
        self.closed = True


def ok(request_id: str, result: Any) -> dict[str, Any]:
    return {
        "id": request_id,
        "status": "ok",
        "result": result,
        "error": None,
        "elapsed_ms": 12,
    }


def failed(
    request_id: str, error: str, status: str = "error", result: Any = None
) -> dict[str, Any]:
    return {
        "id": request_id,
        "status": status,
        "result": result,
        "error": error,
        "elapsed_ms": 3,
    }


def client(*responses: Any, **kwargs: Any) -> tuple[BridgeClient, FakeTransport]:
    transport = FakeTransport(list(responses), fail_with=kwargs.pop("fail_with", None))
    return BridgeClient(transport=transport, **kwargs), transport


# --- framing ----------------------------------------------------------------------


def test_one_request_per_line_with_the_contracted_shape() -> None:
    bridge, transport = client(ok("1", {"pong": True, "protocol": "1.0"}))

    result = bridge.call("ping", {})

    assert result == {"pong": True, "protocol": "1.0"}
    assert transport.requests == [{"id": "1", "command": "ping", "params": {}}]


def test_request_ids_are_strings_and_increase() -> None:
    bridge, transport = client(ok("1", "a"), ok("2", "b"))

    bridge.call("ping", {})
    bridge.call("ping", {})

    assert [request["id"] for request in transport.requests] == ["1", "2"]


def test_a_response_for_another_request_is_refused() -> None:
    bridge, _ = client(ok("99", "a"))

    with pytest.raises(BridgeError, match="'99'"):
        bridge.call("ping", {})


def test_an_unparseable_line_answered_with_an_empty_id_is_the_hosts_error() -> None:
    """The host answers a line it could not parse with an empty id; that is not a mix-up."""
    bridge, _ = client(failed("", "the line had no command"))

    with pytest.raises(BridgeError, match="no command"):
        bridge.call("ping", {})


def test_the_pipe_name_becomes_a_windows_pipe_path() -> None:
    from swreview.bridge.client import pipe_path

    assert pipe_path("swreview") == r"\\.\pipe\swreview"


def test_the_commands_are_the_ones_the_contract_lists() -> None:
    assert set(COMMANDS) == {"capture", "measure", "interference", "ping"}


def test_the_views_are_the_ones_the_host_can_frame() -> None:
    assert set(BRIDGE_VIEWS) == {"iso", "front", "top", "right", "fit"}


def test_a_command_outside_the_allowlist_never_reaches_the_transport() -> None:
    bridge, transport = client()

    with pytest.raises(BridgeError, match="rebuild"):
        bridge.call("rebuild", {})

    assert transport.requests == []


# --- the coarse operations --------------------------------------------------------


def test_capture_measure_and_interference_send_their_parameters() -> None:
    bridge, transport = client(
        ok("1", {"capture": {}, "path": "C:/pkg/captures/cap-0001.png", "gap": None}),
        ok("2", {"distance": {"value": 0.0123, "unit": "m"}}),
        ok("3", {"interferences": [], "gaps": []}),
    )

    bridge.capture("cAbC==", "iso")
    bridge.measure("a==", "b==")
    bridge.interference(["cmp:0001"], "Default", {"treat_coincident_as_interference": True})

    assert [request["command"] for request in transport.requests] == [
        "capture",
        "measure",
        "interference",
    ]
    assert transport.requests[0]["params"] == {
        "persist_ref": "cAbC==",
        "view": "iso",
        "scope_document": None,
        "note": "",
    }
    assert transport.requests[1]["params"]["persist_ref_a"] == "a=="
    assert transport.requests[2]["params"]["component_ids"] == ["cmp:0001"]
    assert transport.requests[2]["params"]["configuration"] == "Default"
    assert transport.requests[2]["params"]["truncate_after"] is None


def test_capture_defaults_to_the_fit_view() -> None:
    bridge, transport = client(ok("1", {"capture": {}, "path": "p.png", "gap": None}))

    bridge.capture("cAbC==")

    assert transport.requests[0]["params"]["view"] == "fit"


# --- failures ---------------------------------------------------------------------


def test_an_error_status_raises_with_the_servers_message() -> None:
    bridge, _ = client(failed("1", "The reference did not resolve: deleted"))

    with pytest.raises(BridgeError, match="did not resolve"):
        bridge.capture("a==", "iso")


def test_a_failed_capture_carries_the_gap_the_host_attached() -> None:
    gap = {
        "kind": "not_extracted",
        "entity_kind": "capture",
        "entity_id": None,
        "reason": "select the entity to capture (iso view)",
        "error": "The reference did not resolve",
    }
    bridge, _ = client(
        failed("1", "could not select", result={"capture": None, "path": None, "gap": gap})
    )

    with pytest.raises(BridgeError) as caught:
        bridge.capture("a==", "iso")

    assert caught.value.result["gap"] == gap


def test_a_line_that_is_not_json_is_an_error() -> None:
    bridge, _ = client("not json at all")

    with pytest.raises(BridgeError, match="not JSON"):
        bridge.call("ping", {})


def test_a_dead_pipe_is_an_error_not_an_oserror() -> None:
    bridge, _ = client(fail_with=BrokenPipeError("the pipe has been ended"))

    with pytest.raises(BridgeError, match="pipe"):
        bridge.call("ping", {})


def test_a_timeout_is_an_error() -> None:
    bridge, _ = client(fail_with=TimeoutError("no response in 60s"))

    with pytest.raises(BridgeError, match="no response"):
        bridge.call("ping", {})


# --- the circuit breaker ----------------------------------------------------------


def test_three_consecutive_failures_open_the_circuit() -> None:
    bridge, transport = client(
        *[failed(str(index + 1), "COM failure") for index in range(3)]
    )

    for _ in range(CIRCUIT_LIMIT):
        with pytest.raises(BridgeError):
            bridge.call("ping", {})

    assert bridge.circuit_open
    with pytest.raises(BridgeOpenError, match="three"):
        bridge.call("ping", {})
    assert len(transport.requests) == CIRCUIT_LIMIT


def test_the_hosts_own_circuit_open_stops_the_client_at_once() -> None:
    bridge, transport = client(failed("1", "three COM failures", status="circuit_open"))

    with pytest.raises(BridgeOpenError, match="circuit open"):
        bridge.call("ping", {})

    assert bridge.circuit_open
    with pytest.raises(BridgeOpenError):
        bridge.call("ping", {})
    assert len(transport.requests) == 1


def test_a_success_resets_the_failure_count() -> None:
    bridge, _ = client(
        failed("1", "one"), failed("2", "two"), ok("3", "fine"), failed("4", "three")
    )

    for _ in range(2):
        with pytest.raises(BridgeError):
            bridge.call("ping", {})
    bridge.call("ping", {})
    with pytest.raises(BridgeError):
        bridge.call("ping", {})

    assert not bridge.circuit_open


def test_an_open_circuit_stays_open_and_reports_the_last_error() -> None:
    bridge, _ = client(*[failed(str(index + 1), f"failure {index}") for index in range(3)])
    for _ in range(CIRCUIT_LIMIT):
        with pytest.raises(BridgeError):
            bridge.call("ping", {})

    with pytest.raises(BridgeOpenError) as caught:
        bridge.capture("a==", "iso")

    assert "failure 2" in str(caught.value)


def test_closing_the_client_closes_the_transport() -> None:
    bridge, transport = client(ok("1", "a"))
    bridge.call("ping", {})

    bridge.close()

    assert transport.closed


# --- the default transport --------------------------------------------------------


def test_the_default_transport_is_the_named_pipe_and_is_built_lazily() -> None:
    """Constructing a client must not try to open a pipe: that is what --bridge does."""
    from swreview.bridge.client import NamedPipeTransport

    bridge = BridgeClient(pipe_name="swreview")

    assert isinstance(bridge.transport, NamedPipeTransport)
    assert bridge.transport.path == r"\\.\pipe\swreview"
    assert bridge.transport.timeout_s == 60.0
