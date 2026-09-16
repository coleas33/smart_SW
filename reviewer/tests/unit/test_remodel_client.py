"""Unit tests for the `remodel.*` bridge client (T071).

The wire format under test is `specs/004-resilient-remodeler/contracts/bridge-remodel.md`
on top of the 1.0 envelope of `extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md`.
The transport is the injectable one `bridge/client.py` already has, so the whole command
family is exercised without a named pipe and without SOLIDWORKS.

What these tests pin is the three properties the contract calls structural:

- **the twelve commands and nothing else.** `REMODEL_COMMANDS` is `ping` plus the twelve
  rows of the contract's command table; `capture`, `measure` and `interference` are
  refused on this side before a line is written, which is the client-side mirror of
  `RemodelSecret`'s scope.
- **no document argument after `remodel.open`.** Exactly two commands name a path at all
  and both run before the scope exists; the assertion is made over the whole table, not
  command by command, so a path added to a thirteenth request shape fails here.
- **`error_code` becomes a class, unchanged.** Every row of the error table maps to the
  Python class the contract names, the token and the `detail` survive on the exception,
  and a code this client has never heard of stays itself rather than being guessed into
  the nearest class.

The circuit breaker is the one place this client does not behave like `BridgeClient`: an
open circuit is **returned** as `CircuitOpen`, never raised, because the run is
run-to-completion and has to record "the bridge stopped answering" against the change it
was making rather than unwind out of the loop.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swreview.bridge.client import (
    CIRCUIT_LIMIT,
    BridgeDocumentClosedError,
    BridgeError,
    BridgeOpenError,
    BridgeUnauthorizedError,
)
from swreview.bridge.remodel_client import (
    DOCUMENT_PARAM_NAMES,
    ERROR_CLASSES,
    REMODEL_COMMANDS,
    CircuitOpen,
    RemodelAddressError,
    RemodelChangeError,
    RemodelClient,
    RemodelContractError,
    RemodelError,
    RemodelGuardError,
    RemodelLimitError,
    RemodelNotInV1Error,
    RemodelPreflightError,
    RemodelRunInProgress,
    RemodelSaveError,
    RemodelTargetError,
)
from swreview.remodel.scope import BRIDGE_ONLY_CODES


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


def refused(
    request_id: str,
    error_code: str,
    error: str = "the host refused",
    detail: Any = None,
) -> dict[str, Any]:
    """The 1.1 error envelope: `result` carries the stable token, `error` the prose."""
    return {
        "id": request_id,
        "status": "error",
        "result": {"error_code": error_code, "detail": detail if detail is not None else {}},
        "error": error,
        "elapsed_ms": 4,
    }


def client(*responses: Any, **kwargs: Any) -> tuple[RemodelClient, FakeTransport]:
    transport = FakeTransport(list(responses), fail_with=kwargs.pop("fail_with", None))
    return RemodelClient(transport=transport, **kwargs), transport


# --- the command table ------------------------------------------------------------

# One row per command of `contracts/bridge-remodel.md`: the method, the arguments a caller
# passes, the command that goes on the wire, and the exact `params` object it carries.
CALLS: tuple[tuple[str, dict[str, Any], str, dict[str, Any]], ...] = (
    (
        "probe_scope",
        {"source_path": r"C:\parts\bracket.SLDPRT"},
        "remodel.probe_scope",
        {"source_path": r"C:\parts\bracket.SLDPRT"},
    ),
    (
        "open",
        {
            "source_path": r"C:\parts\bracket.SLDPRT",
            "copy_path": r"C:\runs\20260101-000000-bracket-remodel\copy\bracket.SLDPRT",
            "run_id": "20260101-000000-bracket-remodel",
            "probe_id": "probe-1",
        },
        "remodel.open",
        {
            "source_path": r"C:\parts\bracket.SLDPRT",
            "copy_path": r"C:\runs\20260101-000000-bracket-remodel\copy\bracket.SLDPRT",
            "run_id": "20260101-000000-bracket-remodel",
            "probe_id": "probe-1",
        },
    ),
    ("snapshot", {}, "remodel.snapshot", {}),
    (
        "rename",
        {"persist_ref": "cA==", "new_name": "Fillet1_2"},
        "remodel.rename",
        {"persist_ref": "cA==", "new_name": "Fillet1_2"},
    ),
    (
        "reorder",
        {
            "feature_persist_ref": "cA==",
            "anchor_persist_ref": "cB==",
            "location": "after",
        },
        "remodel.reorder",
        {
            "feature_persist_ref": "cA==",
            "anchor_persist_ref": "cB==",
            "location": "after",
        },
    ),
    (
        "folder",
        {
            "op": "create",
            "name": "05 Detail",
            "member_persist_refs": ["cA==", "cB=="],
        },
        "remodel.folder",
        {
            "op": "create",
            "name": "05 Detail",
            "member_persist_refs": ["cA==", "cB=="],
            "folder_persist_ref": None,
        },
    ),
    (
        "describe",
        {"persist_ref": "cA==", "text": "locating boss"},
        "remodel.describe",
        {"persist_ref": "cA==", "text": "locating boss"},
    ),
    (
        "equation",
        {"op": "add", "index": 3, "text": '"wall" = 2.5', "which_configs": 2},
        "remodel.equation",
        {"op": "add", "index": 3, "text": '"wall" = 2.5', "which_configs": 2},
    ),
    ("rebuild", {"force": False}, "remodel.rebuild", {"force": False}),
    ("geometry", {}, "remodel.geometry", {}),
    ("save", {"verdict": "pass"}, "remodel.save", {"verdict": "pass"}),
    (
        "close_document",
        {"discard_copy": True},
        "remodel.close",
        {"discard_copy": True},
    ),
)

COMMANDS_AFTER_OPEN: frozenset[str] = frozenset(
    command for _, _, command, _ in CALLS
) - {"remodel.probe_scope", "remodel.open"}


def test_the_commands_are_the_twelve_the_contract_lists_plus_ping() -> None:
    assert set(REMODEL_COMMANDS) == {
        "ping",
        "remodel.probe_scope",
        "remodel.open",
        "remodel.snapshot",
        "remodel.rename",
        "remodel.reorder",
        "remodel.folder",
        "remodel.describe",
        "remodel.equation",
        "remodel.rebuild",
        "remodel.geometry",
        "remodel.save",
        "remodel.close",
    }
    assert len(REMODEL_COMMANDS) == len(set(REMODEL_COMMANDS)) == 13


def test_every_command_of_the_table_has_a_method_and_the_table_is_the_whole_family() -> None:
    assert {command for _, _, command, _ in CALLS} == set(REMODEL_COMMANDS) - {"ping"}
    assert len(CALLS) == 12


@pytest.mark.parametrize(("method", "kwargs", "command", "params"), CALLS)
def test_each_command_sends_its_contracted_request(
    method: str, kwargs: dict[str, Any], command: str, params: dict[str, Any]
) -> None:
    bridge, transport = client(ok("1", {"done": True}))

    result = getattr(bridge, method)(**kwargs)

    assert result == {"done": True}
    assert transport.requests == [{"id": "1", "command": command, "params": params}]


def test_no_command_after_open_names_a_document(  # the whole table, not row by row
) -> None:
    for method, kwargs, command, _ in CALLS:
        if command not in COMMANDS_AFTER_OPEN:
            continue
        bridge, transport = client(ok("1", {}))

        getattr(bridge, method)(**kwargs)

        sent = transport.requests[0]["params"]
        assert set(sent) & DOCUMENT_PARAM_NAMES == set(), (
            f"{command} names a document: {sorted(set(sent) & DOCUMENT_PARAM_NAMES)}"
        )


def test_only_probe_scope_and_open_name_a_path_at_all() -> None:
    naming = {
        command
        for _, _, command, params in CALLS
        if set(params) & DOCUMENT_PARAM_NAMES
    }
    assert naming == {"remodel.probe_scope", "remodel.open"}


def test_ping_is_the_only_non_remodel_command_this_client_speaks() -> None:
    bridge, transport = client(ok("1", {"pong": True, "protocol": "1.1"}))

    assert bridge.ping() == {"pong": True, "protocol": "1.1"}
    assert transport.requests[0]["command"] == "ping"


@pytest.mark.parametrize("method", ["capture", "measure", "interference"])
def test_the_review_commands_are_refused_before_a_line_is_written(method: str) -> None:
    """The client-side mirror of `RemodelSecret`'s scope: not even attempted."""
    bridge, transport = client()
    arguments: dict[str, list[Any]] = {
        "capture": ["cA=="],
        "measure": ["cA==", "cB=="],
        "interference": [["cmp:0001"]],
    }

    with pytest.raises(BridgeError, match=method):
        getattr(bridge, method)(*arguments[method])

    assert transport.requests == []


def test_the_secret_is_on_every_remodel_request_when_one_is_configured() -> None:
    bridge, transport = client(ok("1", {}), ok("2", {}), secret="remodel-secret")

    bridge.snapshot()
    bridge.rebuild(force=False)

    assert [request["secret"] for request in transport.requests] == [
        "remodel-secret",
        "remodel-secret",
    ]


def test_the_secret_never_appears_in_a_failure_message() -> None:
    bridge, _ = client(refused("1", "guard_refused", "Save3 is not on the allowlist"),
                       secret="remodel-secret")

    with pytest.raises(RemodelGuardError) as caught:
        bridge.save("pass")

    assert "remodel-secret" not in str(caught.value)
    assert "remodel-secret" not in (bridge.last_error or "")


# --- the closed sets a request carries ---------------------------------------------


def test_a_reorder_location_outside_the_closed_set_never_reaches_the_bridge() -> None:
    bridge, transport = client()

    with pytest.raises(BridgeError, match="location"):
        bridge.reorder("cA==", "cB==", "into")

    assert transport.requests == []


def test_a_folder_op_outside_the_closed_set_never_reaches_the_bridge() -> None:
    bridge, transport = client()

    with pytest.raises(BridgeError, match="op"):
        bridge.folder("move", name="05 Detail")

    assert transport.requests == []


def test_dissolve_is_sent_and_refused_by_the_host_not_by_the_client() -> None:
    """`dissolve` is in the protocol so stage 2 adds a handler, not a command."""
    bridge, transport = client(refused("1", "not_in_v1", "dissolve is stage 2"))

    with pytest.raises(RemodelNotInV1Error):
        bridge.folder("dissolve", folder_persist_ref="cA==")

    assert transport.requests[0]["params"]["op"] == "dissolve"


def test_an_equation_op_outside_the_closed_set_never_reaches_the_bridge() -> None:
    bridge, transport = client()

    with pytest.raises(BridgeError, match="op"):
        bridge.equation("replace", index=0, text='"wall" = 2.5')

    assert transport.requests == []


def test_a_save_verdict_outside_the_closed_set_never_reaches_the_bridge() -> None:
    bridge, transport = client()

    with pytest.raises(BridgeError, match="verdict"):
        bridge.save("passed")

    assert transport.requests == []


def test_a_verdict_that_is_not_a_pass_is_still_sent_and_refused_by_the_host() -> None:
    """The gate lives on the host, beside `Save3`, not in this client's judgment."""
    bridge, transport = client(refused("1", "gate_not_passed", "the gate did not pass"))

    with pytest.raises(RemodelContractError):
        bridge.save("unresolved")

    assert transport.requests[0]["params"] == {"verdict": "unresolved"}


def test_folder_and_equation_send_a_full_param_set_with_absent_values_null() -> None:
    bridge, transport = client(ok("1", {}), ok("2", {}))

    bridge.folder("rename", name="05 Detail", folder_persist_ref="cA==")
    bridge.equation("delete", index=2)

    assert transport.requests[0]["params"] == {
        "op": "rename",
        "name": "05 Detail",
        "member_persist_refs": [],
        "folder_persist_ref": "cA==",
    }
    assert transport.requests[1]["params"] == {
        "op": "delete",
        "index": 2,
        "text": None,
        "which_configs": None,
    }


# --- error_code becomes a class, unchanged -----------------------------------------

ERROR_TABLE: tuple[tuple[str, type[RemodelError]], ...] = (
    ("not_a_part", RemodelPreflightError),
    ("source_not_open", RemodelPreflightError),
    ("scope_not_probed", RemodelContractError),
    ("scope_changed", RemodelTargetError),
    ("source_dirty", RemodelPreflightError),
    ("external_refs", RemodelPreflightError),
    ("copy_exists", RemodelPreflightError),
    ("copy_failed", RemodelPreflightError),
    ("open_failed", RemodelTargetError),
    ("tag_failed", RemodelTargetError),
    ("preexisting_rebuild_errors", RemodelPreflightError),
    ("target_mismatch", RemodelTargetError),
    ("guard_refused", RemodelGuardError),
    ("persist_ref_unresolved", RemodelAddressError),
    ("reorder_refused", RemodelContractError),
    ("folder_members_not_contiguous", RemodelContractError),
    ("equation_unverified", RemodelChangeError),
    ("rebuild_regressed", RemodelChangeError),
    ("rebuild_timeout", RemodelLimitError),
    ("gate_not_passed", RemodelContractError),
    ("save_failed", RemodelSaveError),
    ("not_in_v1", RemodelNotInV1Error),
    ("run_in_progress", RemodelRunInProgress),
    ("bad_request", RemodelContractError),
)


def test_the_error_table_is_the_contracts_twenty_four_rows() -> None:
    assert dict(ERROR_TABLE) == ERROR_CLASSES
    assert len(ERROR_TABLE) == len(ERROR_CLASSES) == 24


@pytest.mark.parametrize(("error_code", "expected"), ERROR_TABLE)
def test_each_error_code_raises_the_class_the_contract_names(
    error_code: str, expected: type[RemodelError]
) -> None:
    bridge, _ = client(
        refused("1", error_code, "the host explains itself", {"member": "IModelDoc2.Save3"})
    )

    with pytest.raises(expected) as caught:
        bridge.snapshot()

    raised = caught.value
    assert type(raised) is expected
    assert isinstance(raised, BridgeError)
    assert raised.error_code == error_code
    assert raised.detail == {"member": "IModelDoc2.Save3"}
    assert "the host explains itself" in str(raised)


def test_an_unknown_error_code_stays_itself_and_is_never_guessed_into_a_class() -> None:
    bridge, _ = client(refused("1", "some_code_from_a_newer_host", "a newer host"))

    with pytest.raises(RemodelError) as caught:
        bridge.snapshot()

    assert type(caught.value) is RemodelError
    assert caught.value.error_code == "some_code_from_a_newer_host"


def test_an_error_without_an_error_code_stays_a_plain_bridge_error() -> None:
    """A 1.0-shaped failure from a host that has not been rebuilt: no token, no guess."""
    bridge, _ = client(
        {
            "id": "1",
            "status": "error",
            "result": None,
            "error": "something went wrong",
            "elapsed_ms": 2,
        }
    )

    with pytest.raises(BridgeError) as caught:
        bridge.snapshot()

    assert not isinstance(caught.value, RemodelError)
    assert "something went wrong" in str(caught.value)


def test_unauthorized_keeps_its_existing_class() -> None:
    bridge, _ = client(
        {
            "id": "1",
            "status": "error",
            "result": None,
            "error": "unauthorized: remodel.snapshot",
            "elapsed_ms": 1,
        }
    )

    with pytest.raises(BridgeUnauthorizedError):
        bridge.snapshot()


def test_a_closed_document_keeps_its_existing_class() -> None:
    bridge, _ = client(
        {
            "id": "1",
            "status": "error",
            "result": None,
            "error": "the document is no longer open",
            "elapsed_ms": 1,
        }
    )

    with pytest.raises(BridgeDocumentClosedError):
        bridge.snapshot()


def test_every_bridge_raised_scope_code_maps_to_a_class() -> None:
    """The scope gate and this client share one vocabulary (`data-model.md` 4.2)."""
    assert BRIDGE_ONLY_CODES <= set(ERROR_CLASSES)


# --- the circuit is returned, never raised ------------------------------------------


def test_the_open_circuit_is_returned_after_three_consecutive_failures() -> None:
    bridge, transport = client(
        refused("1", "equation_unverified", "neither Add3 nor Add2 landed"),
        refused("2", "equation_unverified", "neither Add3 nor Add2 landed"),
        refused("3", "equation_unverified", "neither Add3 nor Add2 landed"),
    )

    for _ in range(CIRCUIT_LIMIT):
        with pytest.raises(RemodelChangeError):
            bridge.equation("add", index=0, text='"wall" = 2.5', which_configs=2)

    assert bridge.circuit_open is True
    sent_before = len(transport.requests)

    reply = bridge.snapshot()

    assert isinstance(reply, CircuitOpen)
    assert reply.status == "circuit_open"
    assert reply.command == "remodel.snapshot"
    assert reply.last_error is not None
    assert "neither Add3 nor Add2 landed" in reply.last_error
    assert len(transport.requests) == sent_before


def test_the_hosts_own_circuit_open_is_returned_too() -> None:
    bridge, _ = client(
        {
            "id": "1",
            "status": "circuit_open",
            "result": None,
            "error": "three SOLIDWORKS failures",
            "elapsed_ms": 0,
        }
    )

    reply = bridge.rebuild(force=False)

    assert isinstance(reply, CircuitOpen)
    assert reply.command == "remodel.rebuild"
    assert "three SOLIDWORKS failures" in (reply.last_error or "")


def test_a_returned_circuit_open_is_not_an_exception() -> None:
    """A caller that catches `BridgeError` must not be able to catch this by accident."""
    assert not isinstance(CircuitOpen(command="remodel.save", last_error=None), BaseException)
    assert not issubclass(CircuitOpen, BridgeOpenError)


def test_closing_the_client_closes_the_pipe_and_is_not_the_close_command() -> None:
    bridge, transport = client(ok("1", {"closed": True, "copy_deleted": False}))

    bridge.close_document(discard_copy=False)
    bridge.close()

    assert transport.requests[0]["command"] == "remodel.close"
    assert transport.closed is True
