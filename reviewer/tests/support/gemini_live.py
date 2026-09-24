"""What a failed live Gemini call means for the proof the live test exists to give (008 T106).

`tests/live/test_gemini_live_function_response.py` proves that Gemini accepts a `role="tool"`
function response. The seat task T106 records it green, and "green" must mean *proved*: a run
that skips proved nothing, and a run that fails must say whether the protocol or the seat was at
fault. So each way the call can fail is decided here, once, and unit-tested offline
(`tests/unit/test_gemini_live_outcomes.py`):

- a `400` whose error names `API_KEY_INVALID` **fails as a key problem** - the API refused the
  key, not the round, and reporting it as a rejected round would be a false protocol failure;
- any other `400` **fails as the protocol failure** the test exists to catch, the body quoted;
- a connection that never reached the API (`httpx.TransportError`: a web filter, no network, a
  timeout) **fails as a network problem** - without it the test would error with a bare
  traceback, or pass nothing;
- a `401`, `403`, `404`, `429` or `5xx` - an account, a model name or the service - **skips**,
  so a throttled account never turns a CI run red; T106 asks for `1 passed, 0 skipped`, so a
  skip at the seat is not recorded as green.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx
from google.genai import errors

INVALID_KEY_REASON = "API_KEY_INVALID"
"""The `google.rpc.ErrorInfo` reason the API gives a key it does not accept, with a `400`."""


@dataclass(frozen=True)
class Outcome:
    """Whether the live test fails or skips on one error, and the sentence it says."""

    kind: Literal["fail", "skip"]
    message: str


def _reasons(details: Any) -> list[str]:
    """Every `reason` in an error body's `error.details`, in order; none for any other shape."""
    error = details.get("error") if isinstance(details, dict) else None
    entries = error.get("details") if isinstance(error, dict) else None
    if not isinstance(entries, list):
        return []
    return [
        entry["reason"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str)
    ]


def call_outcome(error: BaseException, *, claim: str) -> Outcome:
    """What the live test does with `error`, raised by a call whose rejection means `claim`."""
    not_proved = "the response role is not proved"
    if isinstance(error, httpx.TransportError):
        return Outcome(
            "fail",
            f"the Gemini API could not be reached ({type(error).__name__}: {error}); a web filter "
            f"or no network on this machine - {not_proved}",
        )
    if isinstance(error, errors.ClientError):
        if error.code == 400 and INVALID_KEY_REASON in _reasons(error.details):
            return Outcome(
                "fail",
                f"the Gemini key was refused ({INVALID_KEY_REASON}); set a valid key in "
                f"GEMINI_API_KEY or GOOGLE_API_KEY for this shell - {not_proved}",
            )
        if error.code == 400:
            return Outcome("fail", f"{claim}: {error}")
        return Outcome("skip", f"API unavailable ({error.code}); {not_proved}")
    if isinstance(error, errors.ServerError):
        return Outcome("skip", f"API unavailable ({error}); {not_proved}")
    return Outcome("fail", f"the call failed unexpectedly ({type(error).__name__}: {error})")
