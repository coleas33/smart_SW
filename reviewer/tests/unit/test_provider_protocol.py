"""Unit tests for the provider-neutral types (T008).

`contracts/chat-events.schema.json` is authoritative for the event stream, so the test
that matters is not "the model has these fields" but "what the model serializes is what
the schema says". Three things make that test easy to get wrong:

1. `jsonschema` resolves `$ref` lazily. Five event bodies (`finding`, `evidence.requested`,
   `disposition`, `coverage`, `session.ended`) are `$ref`s into the feature 001
   review-session contract; an event type whose body carries no `$ref` would pass even
   with an empty registry. Every ref'd type therefore gets both a valid case and an
   invalid case, and the invalid case is what proves the ref was really followed.
2. The cross-feature refs are absolute `$id`s, so the registry is keyed by `$id`
   (`tests.support.contracts.contract_registry`), never by file path.
3. The schema's own enumerations - event types, turn-end reasons, provider names - are
   duplicated in the Python literals. Each duplication is asserted equal to the schema
   here, so a schema change the models miss fails instead of drifting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from jsonschema import ValidationError as SchemaValidationError
from pydantic import ValidationError

from swreview.agent import providers
from swreview.agent.providers import (
    AgentEvent,
    AgentProvider,
    EffortLevel,
    EffortMapping,
    EventType,
    ProviderName,
    ToolCallRequest,
    ToolCallResult,
    TurnEndReason,
    TurnResult,
    UnknownProviderError,
    call_tool,
)
from swreview.findings import build_finding
from swreview.report.session import CoverageItem, CoverageScope, EvidenceRequest, Timing
from tests.support.contracts import contract_validator, load_any_contract
from tests.support.packages import build_package

PACKAGE = build_package()
EVENTS_SCHEMA = load_any_contract("chat-events.schema.json")
AT = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


def validator() -> Any:
    return contract_validator("chat-events.schema.json")


def event(event_type: str, body: dict[str, Any], seq: int = 1) -> dict[str, Any]:
    """One serialized `AgentEvent`: the exact shape a line of events.jsonl carries."""
    return AgentEvent(seq=seq, at=AT, type=event_type, body=body).model_dump(mode="json")


def finding_body() -> dict[str, Any]:
    finding = build_finding(
        finding_id="F-001",
        check="fit.clearance",
        title="Pin is larger than its hole",
        status="demonstrated",
        severity="high",
        package=PACKAGE,
        configuration="Default",
        observed="Pin 8.02 mm in an 8.00 mm hole",
        requirement="Clearance fit",
        recommended_action="Open the hole to 8.10 mm",
        component_ids=["cmp:0001"],
        tool_result_ids=[0],
    )
    return finding.model_dump(mode="json")


def evidence_request_body() -> dict[str, Any]:
    return EvidenceRequest(
        id="ER-001",
        what="Tapped depth of the M6 hole",
        why="fastener.engagement cannot be evaluated without it",
        entity_ids=["cmp:0001"],
        status="open",
        answer=None,
        answered_at=None,
    ).model_dump(mode="json")


def coverage_item_body() -> dict[str, Any]:
    return CoverageItem(
        check="fit.clearance",
        scope=CoverageScope(component_ids=["cmp:0001"], configuration="Default"),
        reason="checked both mating faces",
        error=None,
    ).model_dump(mode="json")


def timing_body() -> dict[str, Any]:
    return Timing(
        baseline_minutes=30.0,
        assisted_supervision_minutes=4.0,
        assisted_verification_minutes=3.0,
        false_alarm_handling_minutes=1.0,
        unattended_runtime_minutes=6.0,
    ).model_dump(mode="json")


def valid_bodies() -> dict[str, dict[str, Any]]:
    """One valid body per event type in the schema's `type` enum."""
    return {
        "session.started": {
            "session_id": "d0f1a3b4-0000-4000-8000-000000000001",
            "package_id": "bracket-assy",
            "provider": "openai",
            "model": "gpt-5.6",
            "effort_mapping": {
                "requested": "high",
                "provider_param": "reasoning.effort",
                "provider_value": "high",
            },
        },
        "text.delta": {"text": "Checking the fastener joints"},
        "text.done": {"text": "Checking the fastener joints. Two findings."},
        "tool.started": {
            "step_index": 0,
            "tool": "list_components",
            "arguments": {"configuration": "Default"},
        },
        "tool.finished": {
            "step_index": 0,
            "status": "ok",
            "result_summary": "3 items",
            "elapsed_s": 0.012,
            "error": None,
        },
        "finding": finding_body(),
        "evidence.requested": evidence_request_body(),
        "evidence.answered": {"request_id": "ER-001", "answer": "Tapped 12 mm deep"},
        "disposition": {
            "finding_id": "F-001",
            "disposition": {
                "decision": "accepted",
                "note": "will open the hole",
                "by": "engineer",
                "at": "2026-09-13T12:05:00Z",
            },
        },
        "coverage": {"bucket": "checked", "item": coverage_item_body()},
        # The worked example of contracts/usage.md section 5, written out rather than
        # built through `usage_body`: this table's job is to say independently what the
        # schema says, so a builder that drifted from the contract would pass.
        "usage": {
            "round_index": 0,
            "provider": "openai",
            "model": "gpt-5.6",
            "input_tokens": 12043,
            "cached_input_tokens": 10240,
            "cache_write_tokens": 1803,
            "output_tokens": 512,
            "reasoning_tokens": 448,
            "tool_result_input_tokens": None,
            "total_tokens": 12555,
            "latency_s": 4.31,
            "cache_diagnostic": None,
        },
        "turn.ended": {"reason": "end"},
        "session.ended": {"ended_at": "2026-09-13T12:10:00Z", "timing": timing_body()},
        "error": {
            "error_class": "RateLimitError",
            "message": "rate limited; retry after 20 s",
            "retryable": True,
        },
    }


def test_every_schema_event_type_has_a_case() -> None:
    """The body table is only meaningful if it covers the whole schema enum."""
    assert set(valid_bodies()) == set(EVENTS_SCHEMA["properties"]["type"]["enum"])


@pytest.mark.parametrize("event_type", sorted(valid_bodies()))
def test_agent_event_validates_against_the_contract(event_type: str) -> None:
    validator().validate(event(event_type, valid_bodies()[event_type]))


def test_event_type_literal_matches_the_schema() -> None:
    assert set(get_args(EventType)) == set(EVENTS_SCHEMA["properties"]["type"]["enum"])


def branch_for(event_type: str) -> dict[str, Any]:
    """The `allOf` branch the schema applies to one event type."""
    return next(
        rule
        for rule in EVENTS_SCHEMA["allOf"]
        if rule["if"]["properties"]["type"].get("const") == event_type
    )


def test_turn_end_reason_literal_matches_the_schema() -> None:
    reasons = branch_for("turn.ended")["then"]["properties"]["body"]["properties"]["reason"]["enum"]
    assert set(get_args(TurnEndReason)) == set(reasons)


def test_provider_name_matches_the_schema_enum() -> None:
    body = branch_for("session.started")["then"]["properties"]["body"]
    assert {member.value for member in ProviderName} == set(body["properties"]["provider"]["enum"])


@pytest.mark.parametrize(
    ("event_type", "broken"),
    [
        # finding: $ref review-session#/$defs/Finding - a missing required field must fail.
        ("finding", "drop_required"),
        # evidence.requested: $ref EvidenceRequest - the id pattern must be enforced.
        ("evidence.requested", "bad_id"),
        # disposition: nested $ref Disposition - an unknown decision must fail.
        ("disposition", "bad_decision"),
        # coverage: nested $ref CoverageItem - an unknown scope key must fail.
        ("coverage", "extra_scope_key"),
        # session.ended: nested $ref Timing - a negative duration must fail.
        ("session.ended", "negative_minutes"),
    ],
)
def test_refd_bodies_are_really_resolved(event_type: str, broken: str) -> None:
    """`$ref` resolves lazily: only an invalid body proves the ref was followed."""
    body = valid_bodies()[event_type]
    if broken == "drop_required":
        body.pop("requirement")
    elif broken == "bad_id":
        body["id"] = "ER-1"
    elif broken == "bad_decision":
        body["disposition"]["decision"] = "maybe"
    elif broken == "extra_scope_key":
        body["item"]["scope"]["unknown_key"] = ["cmp:0001"]
    elif broken == "negative_minutes":
        body["timing"]["assisted_supervision_minutes"] = -1.0
    with pytest.raises(SchemaValidationError):
        validator().validate(event(event_type, body))


def test_event_rejects_an_unknown_type() -> None:
    with pytest.raises(ValidationError):
        AgentEvent(seq=1, at=AT, type="text.streamed", body={"text": "x"})


def test_event_seq_starts_at_one() -> None:
    with pytest.raises(ValidationError):
        AgentEvent(seq=0, at=AT, type="text.delta", body={"text": "x"})


def test_event_timestamp_serializes_as_an_aware_iso_timestamp() -> None:
    serialized = event("text.delta", {"text": "x"})["at"]
    parsed = datetime.fromisoformat(serialized.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed == AT


def test_provider_name_rejects_unknown_values() -> None:
    assert ProviderName("openai") is ProviderName.OPENAI
    for unknown in ("anthropic", "claude", "azure", ""):
        with pytest.raises(ValueError):
            ProviderName(unknown)


def test_effort_mapping_records_string_and_integer_provider_values() -> None:
    """Gemini 2.5 maps effort to an integer `thinking_budget`; OpenAI to a string level."""
    openai_mapping = EffortMapping(
        requested="high", provider_param="reasoning.effort", provider_value="high"
    )
    gemini_mapping = EffortMapping(
        requested="high",
        provider_param="thinking_config.thinking_budget",
        provider_value=8192,
    )
    assert openai_mapping.model_dump(mode="json")["provider_value"] == "high"
    assert gemini_mapping.model_dump(mode="json")["provider_value"] == 8192
    for mapping in (openai_mapping, gemini_mapping):
        body = dict(
            valid_bodies()["session.started"],
            effort_mapping=mapping.model_dump(mode="json"),
        )
        validator().validate(event("session.started", body))


def test_effort_mapping_rejects_an_unknown_requested_level() -> None:
    assert set(get_args(EffortLevel)) == {"low", "medium", "high", "xhigh"}
    with pytest.raises(ValidationError):
        EffortMapping(
            requested="maximum", provider_param="reasoning.effort", provider_value="high"
        )


def test_tool_call_request_and_result_carry_the_call_id() -> None:
    request = ToolCallRequest(call_id="call_1", name="list_components", arguments={"limit": 2})
    ok = ToolCallResult(call_id=request.call_id, payload={"components": []}, is_error=False)
    failed = ToolCallResult(call_id=request.call_id, payload={"error": "no such id"}, is_error=True)
    assert ok.call_id == failed.call_id == "call_1"
    assert failed.is_error is True
    with pytest.raises(ValidationError):
        ToolCallResult(call_id="call_1", payload="not a mapping", is_error=False)


def test_turn_result_carries_the_end_reason_and_the_history() -> None:
    result = TurnResult(
        reason="end",
        text="done",
        steps=2,
        messages=[{"role": "user", "content": "review it"}],
    )
    assert result.reason == "end"
    with pytest.raises(ValidationError):
        TurnResult(reason="finished", text="", steps=0, messages=[])


class _StubProvider:
    """The smallest object that satisfies `AgentProvider` structurally."""

    name = ProviderName.FAKE
    model = "scripted"

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        return EffortMapping(requested=effort, provider_param="none", provider_value="none")

    def run(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: Any,
        effort: EffortLevel,
        max_steps: int,
        on_event: Any,
    ) -> TurnResult:
        return TurnResult(reason="end", text="", steps=0, messages=list(messages))

    def start_steps_at(self, index: int) -> None:
        """Part of the port since feature 005: the session's step count seeds the counter."""


def test_stub_satisfies_the_provider_protocol() -> None:
    assert isinstance(_StubProvider(), AgentProvider)


def test_registry_returns_the_registered_adapter_class() -> None:
    """The first `get` imports the adapter module, which registers the class it exports."""
    imported = providers.get(ProviderName.FAKE)
    assert imported.__module__ == providers.ADAPTER_MODULES[ProviderName.FAKE]
    providers.register(ProviderName.FAKE, _StubProvider)
    try:
        assert providers.get("fake") is _StubProvider
        assert providers.get(ProviderName.FAKE) is _StubProvider
        assert ProviderName.FAKE in providers.available()
    finally:
        providers.register(ProviderName.FAKE, imported)


@pytest.mark.parametrize("retired", ["anthropic", "claude", "Anthropic", "claude-opus-5"])
def test_registry_raises_for_the_retired_provider(retired: str) -> None:
    with pytest.raises(UnknownProviderError) as caught:
        providers.get(retired)
    message = str(caught.value)
    assert "openai" in message
    assert "gemini" in message


def test_registry_raises_for_an_unknown_provider() -> None:
    with pytest.raises(UnknownProviderError):
        providers.get("azure")


def test_every_provider_name_has_an_adapter_module() -> None:
    """`get` imports the adapter lazily; every name must have somewhere to import from."""
    assert set(providers.ADAPTER_MODULES) == set(ProviderName)


# --- one producer for the tool event pair (T068) -----------------------------------------


class _OneCallToolSet:
    """The smallest `ToolSet` `call_tool` needs: it answers one call and remembers it."""

    def __init__(self, result: ToolCallResult) -> None:
        self.result = result
        self.asked: list[tuple[str, dict[str, Any], str]] = []

    def call(self, name: str, arguments: Any, call_id: str) -> ToolCallResult:
        self.asked.append((name, dict(arguments), call_id))
        return self.result


@pytest.mark.parametrize(
    ("payload", "is_error", "status", "error"),
    [
        ({"components": []}, False, "ok", None),
        ({"error": "no such component"}, True, "error", "no such component"),
    ],
)
def test_call_tool_emits_the_contract_pair_around_one_call(
    payload: dict[str, Any], is_error: bool, status: str, error: str | None
) -> None:
    """The `tool.started`/`tool.finished` pair, shaped once for every adapter."""
    validator = contract_validator("chat-events.schema.json")
    seen: list[tuple[str, dict[str, Any]]] = []
    ticks = iter([1.0, 1.25])
    tools = _OneCallToolSet(ToolCallResult(call_id="c1", payload=payload, is_error=is_error))

    result = call_tool(
        request=ToolCallRequest(call_id="c1", name="list_components", arguments={"x": 1}),
        tools=tools,
        on_event=lambda event_type, body: seen.append((event_type, dict(body))),
        step_index=3,
        clock=lambda: next(ticks),
    )

    assert result.payload == payload
    assert tools.asked == [("list_components", {"x": 1}, "c1")]
    assert [event_type for event_type, _ in seen] == ["tool.started", "tool.finished"]
    assert seen[0][1] == {"step_index": 3, "tool": "list_components", "arguments": {"x": 1}}
    assert seen[1][1]["step_index"] == 3
    assert seen[1][1]["status"] == status
    assert seen[1][1]["error"] == error
    assert seen[1][1]["elapsed_s"] == pytest.approx(0.25)
    for event_type, body in seen:
        validator.validate(
            {"seq": 1, "at": "2026-09-13T12:00:00Z", "type": event_type, "body": body}
        )


def test_no_adapter_shapes_the_tool_event_pair_itself() -> None:
    """T068: one producer for these two bodies, not one copy per adapter.

    All three adapters had the same fifteen lines - counter, `tool.started`, the call, the
    clock arithmetic, `tool.finished` - so a field added to the contract had to be added
    three times, and a fourth adapter would have started by copying them.
    """
    offenders = sorted(
        path.name
        for path in Path(providers.__file__).parent.glob("*.py")
        if path.name != "__init__.py" and '"tool.started"' in path.read_text(encoding="utf-8")
    )

    assert offenders == []
