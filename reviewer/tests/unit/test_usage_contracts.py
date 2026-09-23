"""The three amended contracts, and what the amendments must not break (T019).

Everything this feature adds to a contract is **additive**, and "additive" is a claim that
has to be tested rather than asserted in a commit message. Three schemas changed in one
step and each has its own house style, which is why each is checked its own way:

- `chat-events.schema.json` has a closed top-level `type` enum and
  `additionalProperties: false` on every body, so the new `usage` event is a new enum
  member **and** a new `allOf` branch, and `session.ended` grows an optional `usage` with
  `required` left at `["ended_at", "timing"]`. The test that matters is that **every event
  type that validated before still validates unchanged**.
- `review-session.schema.json` is `additionalProperties: false` at the top level, with
  `provider_info` and `retry_of` already the pattern for a new optional field: added to
  `properties`, left out of `required`. So a feature 001 `session.json` carrying neither
  `usage` nor `efficiency` loads and validates, and a session carrying both does too.
  Because the top level forbids extras, the schema and `ReviewSession` can only be right
  together, and the field-by-field comparison below is what says so out loud.
- `scorecard.schema.json` uses the opposite style - every property also in `required`,
  nullability carrying "may be absent" - so its additions follow that, and a scorecard
  over a session with no usage produces nulls and does not raise.

This is deliberately **not** `test_schema_sync.py`, which compares the IR models to
`ir.schema.json` and touches the session contract only to check it is valid JSON Schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import ValidationError as SchemaValidationError

from swreview.agent.providers import TokenUsage, usage_body
from swreview.report.session import ReviewSession, SessionUsage, load_session, save_session
from tests.support.contracts import contract_validator, load_any_contract, load_contract
from tests.unit.test_provider_protocol import event, valid_bodies
from tests.unit.test_scorecard_usage import make_usage, score
from tests.unit.test_session import build_session, session_validator

EVENTS_CONTRACT = "chat-events.schema.json"
EVENTS_SCHEMA = load_any_contract(EVENTS_CONTRACT)
SESSION_SCHEMA = load_contract("review-session.schema.json")
SCORECARD_SCHEMA = load_contract("scorecard.schema.json")

PRE_FEATURE_FIELDS: tuple[str, ...] = ("usage", "efficiency")
"""What a session written before feature 005 does not have. Both optional, both absent."""

ROUND = TokenUsage(
    input_tokens=12_043,
    cached_input_tokens=10_240,
    cache_write_tokens=1_803,
    output_tokens=512,
    reasoning_tokens=448,
    tool_result_input_tokens=None,
    total_tokens=12_555,
    latency_s=4.31,
)
"""The worked example of contracts/usage.md section 5."""


def usage_event(**overrides: Any) -> dict[str, Any]:
    """One serialized `usage` event, built the way the adapters build it."""
    body = usage_body(ROUND, round_index=0, provider="openai", model="gpt-5.6")
    body.update(overrides)
    return event("usage", body)


# --- chat-events.schema.json ---------------------------------------------------------------


def test_usage_is_a_member_of_the_closed_event_type_enum() -> None:
    assert "usage" in EVENTS_SCHEMA["properties"]["type"]["enum"]


def test_a_usage_event_validates_against_the_amended_contract() -> None:
    contract_validator(EVENTS_CONTRACT).validate(usage_event())


def test_a_usage_event_whose_counts_are_all_null_validates() -> None:
    """The provider-said-nothing round is a shape the contract has to accept."""
    unreported = TokenUsage(
        input_tokens=None,
        cached_input_tokens=None,
        cache_write_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        tool_result_input_tokens=None,
        total_tokens=None,
        latency_s=0.0,
    )
    body = usage_body(unreported, round_index=7, provider="gemini", model="gemini-3-pro")

    contract_validator(EVENTS_CONTRACT).validate(event("usage", body))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("round_index", -1),
        ("provider", "anthropic"),
        ("latency_s", None),
        ("total_tokens", "12555"),
    ],
)
def test_the_contract_rejects_a_usage_body_it_should_reject(field: str, value: Any) -> None:
    """Negative controls. `provider` is the same closed enum `session.started` uses, and
    a null `latency_s` would mean a request we made and did not time."""
    with pytest.raises(SchemaValidationError):
        contract_validator(EVENTS_CONTRACT).validate(usage_event(**{field: value}))


def test_a_usage_body_with_an_extra_field_is_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        contract_validator(EVENTS_CONTRACT).validate(usage_event(turn_index=0))


@pytest.mark.parametrize("event_type", sorted(set(valid_bodies()) - {"usage"}))
def test_every_event_type_that_validated_before_still_validates(event_type: str) -> None:
    """The additive claim, one type at a time: nothing else in the schema moved."""
    contract_validator(EVENTS_CONTRACT).validate(event(event_type, valid_bodies()[event_type]))


def session_ended_branch() -> dict[str, Any]:
    return next(
        rule
        for rule in EVENTS_SCHEMA["allOf"]
        if rule["if"]["properties"]["type"].get("const") == "session.ended"
    )["then"]["properties"]["body"]


def test_session_ended_still_requires_only_what_it_required_before() -> None:
    """`usage` is in `properties` and out of `required`, so every stream written before
    this feature is still a valid one."""
    branch = session_ended_branch()
    assert branch["required"] == ["ended_at", "timing"]
    assert "usage" in branch["properties"]


def test_a_session_ended_event_carrying_usage_validates() -> None:
    body = {
        "ended_at": "2026-09-13T12:10:00Z",
        "timing": valid_bodies()["session.ended"]["timing"],
        "usage": SessionUsage.summed([ROUND], [1]).model_dump(mode="json"),
    }

    contract_validator(EVENTS_CONTRACT).validate(event("session.ended", body))


def test_a_session_ended_event_carrying_a_malformed_usage_is_rejected() -> None:
    """The `$ref` into the session contract is really followed, so the negative control
    has to fail for the right reason: a `SessionUsage` missing a required field."""
    usage = SessionUsage.summed([ROUND], [1]).model_dump(mode="json")
    del usage["totals"]
    body = {
        "ended_at": "2026-09-13T12:10:00Z",
        "timing": valid_bodies()["session.ended"]["timing"],
        "usage": usage,
    }

    with pytest.raises(SchemaValidationError):
        contract_validator(EVENTS_CONTRACT).validate(event("session.ended", body))


# --- review-session.schema.json --------------------------------------------------------------


def pre_feature_session_json() -> dict[str, Any]:
    """A `session.json` as feature 001 wrote it: neither new field present at all."""
    written = json.loads(build_session().model_dump_json())
    for name in PRE_FEATURE_FIELDS:
        written.pop(name, None)
    return written


def test_a_feature_001_session_validates_against_the_amended_schema() -> None:
    written = pre_feature_session_json()

    assert not set(PRE_FEATURE_FIELDS) & set(written)
    session_validator().validate(written)


def test_a_feature_001_session_loads_unchanged_and_carries_neither_field(
    tmp_path: Path,
) -> None:
    """Loading it must not invent a zero-cost run or a lever configuration it never had."""
    path = tmp_path / "session.json"
    path.write_text(json.dumps(pre_feature_session_json()), encoding="utf-8")

    loaded = load_session(path)

    assert loaded.usage is None
    assert loaded.efficiency is None


def test_a_session_carrying_usage_and_efficiency_validates(tmp_path: Path) -> None:
    from swreview.agent.settings import EfficiencySettings

    session = build_session()
    session.usage = SessionUsage.summed([ROUND, ROUND], [2])
    session.efficiency = EfficiencySettings()
    path = tmp_path / "session.json"
    save_session(session, path)

    session_validator().validate(json.loads(path.read_text(encoding="utf-8")))
    assert load_session(path).usage == session.usage


def test_neither_new_field_is_required() -> None:
    """The `provider_info` and `retry_of` pattern: in `properties`, out of `required`."""
    for name in PRE_FEATURE_FIELDS:
        assert name in SESSION_SCHEMA["properties"]
        assert name not in SESSION_SCHEMA["required"]


def test_the_schema_and_the_model_carry_exactly_the_same_fields() -> None:
    """The top level is `additionalProperties: false`, so a field added to one and not
    the other is a session that cannot be written - which is the desired behaviour, and
    this is the assertion that names it rather than leaving it to a distant failure."""
    assert set(SESSION_SCHEMA["properties"]) == set(ReviewSession.model_fields)


def test_the_session_contract_defines_the_two_new_types_it_refs() -> None:
    for name in ("TokenUsage", "SessionUsage", "EfficiencySettings"):
        assert name in SESSION_SCHEMA["$defs"]


# --- optional late levers in the session contract -------------------------------------------

LEVER_11 = "procedural_gate"
LEVER_12 = "compact_queries"
LEVER_13 = "withhold_prerun_tools"


def efficiency_block() -> dict[str, Any]:
    return SESSION_SCHEMA["$defs"]["EfficiencySettings"]


def test_the_eleventh_lever_is_in_properties_and_not_in_required() -> None:
    """The one edit that could break every committed session at once.

    `EfficiencySettings` is `additionalProperties: false`, so the name has to be in
    `properties` or a session that records it cannot be written; and it has to stay out of
    `required` or every session written before it existed stops validating (research
    R2.10, the fourth pinned place)."""
    block = efficiency_block()

    assert LEVER_11 in block["properties"]
    assert LEVER_11 not in block["required"]


def test_the_compact_query_lever_is_optional_in_the_session_contract() -> None:
    block = efficiency_block()

    assert LEVER_12 in block["properties"]
    assert LEVER_12 not in block["required"]


def test_lever_13_is_optional_in_the_session_contract() -> None:
    """Feature 008's amendment of 2026-09-23 (research R2.53): declared, never required."""
    block = efficiency_block()

    assert LEVER_13 in block["properties"]
    assert LEVER_13 not in block["required"]


def test_a_session_carrying_all_thirteen_levers_validates_and_loads(tmp_path: Path) -> None:
    """Lever 13 is written when it is on - every pane review - and read back as it ran."""
    from swreview.agent.settings import EfficiencySettings

    session = build_session()
    session.efficiency = EfficiencySettings(prerun_checks=True, withhold_prerun_tools=True)
    path = tmp_path / "session.json"
    save_session(session, path)

    written = json.loads(path.read_text(encoding="utf-8"))

    assert len(written["efficiency"]) == 13
    assert written["efficiency"][LEVER_11] is False
    assert written["efficiency"][LEVER_12] is False
    assert written["efficiency"][LEVER_13] is True
    session_validator().validate(written)
    assert load_session(path).efficiency == session.efficiency


def test_lever_13_off_is_omitted_so_every_older_session_keeps_its_bytes(
    tmp_path: Path,
) -> None:
    """A session written before lever 13 existed carries twelve booleans; one written with
    it off is written the same way, so committed sessions round-trip to their own bytes
    (FR-028), and both load with the lever off."""
    from swreview.agent.settings import EfficiencySettings

    session = build_session()
    session.efficiency = EfficiencySettings(prerun_checks=True)
    path = tmp_path / "session.json"
    save_session(session, path)
    written = json.loads(path.read_text(encoding="utf-8"))

    assert LEVER_13 not in written["efficiency"]
    assert len(written["efficiency"]) == 12
    session_validator().validate(written)
    loaded = load_session(path)
    assert loaded.efficiency == EfficiencySettings(prerun_checks=True)
    assert loaded.efficiency.withhold_prerun_tools is False
    save_session(loaded, tmp_path / "again.json")
    assert (tmp_path / "again.json").read_bytes() == path.read_bytes()


def test_a_session_written_before_lever_eleven_existed_still_validates(
    tmp_path: Path,
) -> None:
    """A run folder from before the late levers carries the original ten booleans."""
    from swreview.agent.settings import EfficiencySettings

    session = build_session()
    session.efficiency = EfficiencySettings()
    path = tmp_path / "session.json"
    save_session(session, path)
    written = json.loads(path.read_text(encoding="utf-8"))
    del written["efficiency"][LEVER_11]
    del written["efficiency"][LEVER_12]

    assert len(written["efficiency"]) == 10
    session_validator().validate(written)


def test_the_efficiency_block_and_the_model_carry_exactly_the_same_levers() -> None:
    """`extra="forbid"` on one side and `additionalProperties: false` on the other: the
    two can only be right together, and this is the assertion that says so out loud."""
    from swreview.agent.settings import EfficiencySettings

    assert set(efficiency_block()["properties"]) == set(EfficiencySettings.model_fields)


def test_the_two_contracts_spell_token_usage_the_same_way() -> None:
    """The scorecard carries the same record; two spellings of it would be two records."""
    assert (
        SCORECARD_SCHEMA["$defs"]["TokenUsage"]["required"]
        == SESSION_SCHEMA["$defs"]["TokenUsage"]["required"]
        == list(TokenUsage.model_fields)
    )


# --- scorecard.schema.json -------------------------------------------------------------------


def test_a_scorecard_over_a_session_with_no_usage_produces_nulls_and_does_not_raise(
    tmp_path: Path,
) -> None:
    scorecard = score(tmp_path, usage=None)

    package = scorecard.per_package[0]
    assert package.usage is None
    assert package.round_trips is None
    assert package.cached_input_share is None
    assert scorecard.aggregate.packages_with_usage == 0


def test_a_scorecard_with_no_usage_validates_against_the_amended_contract(
    tmp_path: Path,
) -> None:
    scorecard = score(tmp_path, usage=None)

    contract_validator("scorecard.schema.json").validate(
        json.loads(scorecard.model_dump_json())
    )


def test_a_scorecard_with_usage_validates_against_the_amended_contract(
    tmp_path: Path,
) -> None:
    scorecard = score(tmp_path, usage=SessionUsage.summed([make_usage()], [1]))

    contract_validator("scorecard.schema.json").validate(
        json.loads(scorecard.model_dump_json())
    )


def test_the_scorecard_keeps_its_house_style_of_requiring_every_property() -> None:
    """Its opposite convention to the session contract's: everything is required and
    nullability is what says "may be absent". The additions follow it rather than
    importing the other file's style."""
    for name in ("PackageScore", "Aggregate"):
        definition = SCORECARD_SCHEMA["$defs"][name]
        assert set(definition["required"]) == set(definition["properties"])
