"""The one serialization of a tool result (008 T003, research R2.9).

`tool_result_text` is "what the model reads of a result": the OpenAI adapter encodes every
`function_call_output` with it, and the replay and the step sizes count tokens over it, so the
three cannot drift apart. It is `json.dumps` today, byte for byte, and the adapter's request
must not move by a byte when it starts calling it - which is why the expected request below was
captured from `_encode_history` **before** the refactor and is written here literally.
"""

from __future__ import annotations

import json
from typing import Any

from swreview.agent.providers import FRAMING_TOKENS, tool_result_text
from swreview.agent.providers.openai_provider import _encode_history

OK_PAYLOAD: dict[str, Any] = {"id": "cmp:0001", "name": "housing-1", "is_fixed": True}
ERROR_PAYLOAD: dict[str, Any] = {"error": "component_id not in this package: 'cmp:9999'"}
NESTED_PAYLOAD: dict[str, Any] = {
    "result": [
        {"id": "hol:0001", "size": "Ø 6 H7", "note": "bore of 12 µm runout", "tags": ["a", "b"]},
        {"id": "hol:0002", "size": None, "values": [1, 2.5, -3e-07], "flag": False},
    ],
    "coverage": {"checked": 2, "unresolved": 0},
}


def test_an_ok_payload_is_its_json() -> None:
    assert tool_result_text(OK_PAYLOAD) == json.dumps(OK_PAYLOAD)


def test_an_error_payload_is_its_json() -> None:
    assert tool_result_text(ERROR_PAYLOAD) == json.dumps(ERROR_PAYLOAD)


def test_a_nested_payload_with_non_ascii_text_is_its_json() -> None:
    text = tool_result_text(NESTED_PAYLOAD)

    assert text == json.dumps(NESTED_PAYLOAD)
    assert "\\u00d8" in text, "default json.dumps escapes non-ASCII, and so must this"


def test_compact_is_the_same_json_without_the_spaces() -> None:
    """Feature 008 T070: payload slimming's compact form, through the one serialization."""
    for payload in (OK_PAYLOAD, ERROR_PAYLOAD, NESTED_PAYLOAD):
        compact = tool_result_text(payload, compact=True)
        assert compact == json.dumps(payload, separators=(",", ":"))
        assert json.loads(compact) == payload
        assert len(compact) < len(tool_result_text(payload))


def test_the_framing_constant_is_twelve() -> None:
    assert FRAMING_TOKENS == 12


LITERAL_HISTORY: list[dict[str, Any]] = [
    {"role": "user", "content": "Review this assembly."},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "call_id": "call_1",
                "name": "get_component",
                "arguments": {"component_id": "cmp:0001"},
            },
            {"call_id": "call_2", "name": "list_mates", "arguments": {}},
        ],
    },
    {
        "role": "tool",
        "call_id": "call_1",
        "name": "get_component",
        "content": {"id": "cmp:0001", "name": "Gehäuse Ø12", "mass_kg": 0.25},
        "is_error": False,
    },
    {
        "role": "tool",
        "call_id": "call_2",
        "name": "list_mates",
        "content": {"error": "no mates in this package"},
        "is_error": True,
    },
]

EXPECTED_ITEMS: list[dict[str, Any]] = [
    {"role": "user", "content": "Review this assembly."},
    {
        "type": "function_call",
        "call_id": "call_1",
        "name": "get_component",
        "arguments": '{"component_id": "cmp:0001"}',
    },
    {"type": "function_call", "call_id": "call_2", "name": "list_mates", "arguments": "{}"},
    {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"id": "cmp:0001", "name": "Geh\\u00e4use \\u00d812", "mass_kg": 0.25}',
    },
    {
        "type": "function_call_output",
        "call_id": "call_2",
        "output": '{"error": "no mates in this package"}',
    },
]
"""Captured from `_encode_history(LITERAL_HISTORY)` before it called `tool_result_text`."""


def test_the_openai_history_encoding_is_byte_identical_to_before_the_refactor() -> None:
    assert _encode_history(LITERAL_HISTORY) == EXPECTED_ITEMS


def test_the_openai_tool_output_is_the_one_serialization() -> None:
    outputs = [item["output"] for item in _encode_history(LITERAL_HISTORY) if "output" in item]

    assert outputs == [tool_result_text(m["content"]) for m in LITERAL_HISTORY[2:]]
