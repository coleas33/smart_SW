"""The live Gemini test fails or skips for the right reason, proved offline (feature 008 T107).

`tests/support/gemini_live.call_outcome` decides it (see that module); these build each error the
SDK and httpx raise and hold the decision, so the seat's T106 run reads "1 passed" only when the
round was proved, and a failure says whether the key, the network or the protocol was at fault.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from google.genai import errors

from tests.support.gemini_live import INVALID_KEY_REASON, call_outcome

CLAIM = "the forced tool call was rejected"


def body(code: int, status: str, message: str, *reasons: str) -> dict[str, Any]:
    """An error body as the API writes it, each reason as a `google.rpc.ErrorInfo` detail."""
    return {
        "error": {
            "code": code,
            "message": message,
            "status": status,
            "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}
                for reason in reasons
            ],
        }
    }


def test_an_invalid_key_fails_as_a_key_problem_and_not_as_a_rejected_round() -> None:
    error = errors.ClientError(
        400,
        body(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
             INVALID_KEY_REASON),
    )

    outcome = call_outcome(error, claim=CLAIM)

    assert outcome.kind == "fail"
    assert INVALID_KEY_REASON in outcome.message and "key was refused" in outcome.message
    assert CLAIM not in outcome.message


def test_any_other_400_fails_as_the_protocol_failure_quoting_the_body() -> None:
    error = errors.ClientError(
        400,
        body(400, "INVALID_ARGUMENT", "Please use a valid role: user, model.", "BAD_ROLE"),
    )

    outcome = call_outcome(error, claim=CLAIM)

    assert outcome.kind == "fail"
    assert outcome.message.startswith(CLAIM + ": ")
    assert "Please use a valid role" in outcome.message


def test_a_400_with_no_error_details_is_still_the_protocol_failure() -> None:
    outcome = call_outcome(errors.ClientError(400, {"error": {"message": "bad"}}), claim=CLAIM)

    assert outcome.kind == "fail" and outcome.message.startswith(CLAIM)


@pytest.mark.parametrize(
    ("code", "status"),
    [(401, "UNAUTHENTICATED"), (403, "PERMISSION_DENIED"), (404, "NOT_FOUND"),
     (429, "RESOURCE_EXHAUSTED")],
)
def test_an_account_model_or_quota_problem_skips(code: int, status: str) -> None:
    outcome = call_outcome(errors.ClientError(code, body(code, status, "no")), claim=CLAIM)

    assert outcome.kind == "skip"
    assert str(code) in outcome.message and "not proved" in outcome.message


def test_a_server_error_skips() -> None:
    error = errors.ServerError(503, body(503, "UNAVAILABLE", "overloaded"))

    assert call_outcome(error, claim=CLAIM).kind == "skip"


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
        httpx.ConnectTimeout("timed out"),
        httpx.ReadError("connection reset by the filter"),
    ],
    ids=["connect", "timeout", "read"],
)
def test_a_network_that_never_reached_the_api_fails_as_a_network_problem(
    error: httpx.TransportError,
) -> None:
    outcome = call_outcome(error, claim=CLAIM)

    assert outcome.kind == "fail"
    assert "could not be reached" in outcome.message and type(error).__name__ in outcome.message
    assert CLAIM not in outcome.message


def test_an_unexpected_exception_fails_naming_its_class() -> None:
    outcome = call_outcome(RuntimeError("boom"), claim=CLAIM)

    assert outcome.kind == "fail" and "RuntimeError" in outcome.message
