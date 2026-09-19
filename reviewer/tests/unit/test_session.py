"""Unit tests for the review session model (T017).

`session.json` is the source of truth for the report and the scorecard (research R10),
so it has to round-trip and it has to validate against the committed contract - which
`$ref`s the IR schema, hence the registry below.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from swreview.agent.providers import EffortMapping
from swreview.findings import build_finding
from swreview.ir.models import SourceRef
from swreview.report.session import (
    Coverage,
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    EvidenceRequestIdAllocator,
    InvestigationStep,
    ProviderInfo,
    ReviewSession,
    Timing,
    load_session,
    save_session,
)
from tests.support.contracts import load_contract
from tests.support.packages import build_package

PACKAGE = build_package()


def session_validator() -> Draft202012Validator:
    ir_schema = Resource.from_contents(load_contract("ir.schema.json"))
    registry: Registry = ir_schema @ Registry()
    return Draft202012Validator(
        load_contract("review-session.schema.json"),
        registry=registry,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def build_session(**overrides: object) -> ReviewSession:
    finding = build_finding(
        finding_id="F-001",
        check="fastener.engagement",
        title="Usable thread depth unknown",
        status="unresolved",
        severity="medium",
        package=PACKAGE,
        configuration="Default",
        observed="Hole feature reports drill depth only",
        requirement="Thread engagement of at least 1.0 x D",
        recommended_action="Add the tapped depth to the drawing",
        component_ids=["cmp:0001"],
        drawing_locations=[SourceRef(document_id="doc:1", sheet="Sheet1")],
        coverage_limits=["gap: hole:1 usable thread depth not extracted"],
    )
    fields: dict[str, object] = {
        "session_id": UUID("99999999-8888-4777-8666-555555555555"),
        "package_id": PACKAGE.package_id,
        "design_id": PACKAGE.design.design_id,
        "started_at": datetime(2026, 9, 12, 13, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 9, 12, 13, 21, tzinfo=UTC),
        "model": "claude-opus-5",
        "steps": [
            InvestigationStep(
                index=0,
                tool="list_holes",
                arguments={"component_id": "cmp:0001"},
                result_summary="1 hole, thread depth unknown",
                status="ok",
                error=None,
                elapsed_s=0.12,
            )
        ],
        "evidence_requests": [
            EvidenceRequest(
                id="ER-001",
                what="Tapped depth of M6 Tapped Hole1",
                why="fastener.engagement",
                entity_ids=["hole:1"],
                status="open",
                answer=None,
                answered_at=None,
            )
        ],
        "findings": [finding],
        "coverage": Coverage(
            unresolved=[
                CoverageItem(
                    check="fastener.engagement",
                    scope=CoverageScope(component_ids=["cmp:0001"], configuration="Default"),
                    reason="usable thread depth unknown",
                    error=None,
                )
            ]
        ),
        "timing": Timing(
            baseline_minutes=90.0,
            assisted_supervision_minutes=10.0,
            assisted_verification_minutes=8.0,
            false_alarm_handling_minutes=2.0,
            unattended_runtime_minutes=25.0,
        ),
    }
    fields.update(overrides)
    return ReviewSession(**fields)  # type: ignore[arg-type]


def test_session_json_validates_against_the_contract() -> None:
    payload = build_session().model_dump(mode="json")

    errors = sorted(session_validator().iter_errors(payload), key=lambda e: list(e.absolute_path))

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_session_round_trips_through_disk(tmp_path: Path) -> None:
    original = build_session()
    target = tmp_path / "session.json"

    save_session(original, target)
    reloaded = load_session(target)

    assert reloaded.model_dump(mode="json") == original.model_dump(mode="json")
    assert reloaded.findings[0].coverage_limits


def test_coverage_has_all_five_buckets() -> None:
    coverage = Coverage()

    assert set(coverage.model_dump()) == {
        "checked",
        "skipped",
        "unresolved",
        "failed",
        "out_of_scope",
    }
    assert all(bucket == [] for bucket in coverage.model_dump().values())


def test_net_saved_minutes_excludes_unattended_runtime() -> None:
    timing = Timing(
        baseline_minutes=90.0,
        assisted_supervision_minutes=10.0,
        assisted_verification_minutes=8.0,
        false_alarm_handling_minutes=2.0,
        unattended_runtime_minutes=25.0,
    )

    assert timing.net_saved_minutes == pytest.approx(70.0)


def test_net_saved_minutes_is_none_without_a_baseline() -> None:
    timing = Timing(
        baseline_minutes=None,
        assisted_supervision_minutes=10.0,
        assisted_verification_minutes=8.0,
        false_alarm_handling_minutes=2.0,
        unattended_runtime_minutes=25.0,
    )

    assert timing.net_saved_minutes is None


def test_net_saved_minutes_is_recomputed_when_loaded() -> None:
    timing = Timing.model_validate(
        {
            "baseline_minutes": 60.0,
            "assisted_supervision_minutes": 5.0,
            "assisted_verification_minutes": 5.0,
            "false_alarm_handling_minutes": 0.0,
            "unattended_runtime_minutes": 40.0,
            "net_saved_minutes": 999.0,
        }
    )

    assert timing.net_saved_minutes == pytest.approx(50.0)


def test_a_negative_baseline_is_refused_by_name() -> None:
    """T010: `baseline_minutes` was the one input without `ge=0`, so a negative baseline
    was accepted and derived a negative net saving. The committed schema has said
    `"minimum": 0` for it all along; the model now agrees with its own contract (FR-003).
    """
    with pytest.raises(ValidationError, match="baseline_minutes"):
        Timing(
            baseline_minutes=-5.0,
            assisted_supervision_minutes=10.0,
            assisted_verification_minutes=8.0,
            false_alarm_handling_minutes=2.0,
            unattended_runtime_minutes=25.0,
        )


def test_a_zero_baseline_is_allowed_and_validates_against_the_contract() -> None:
    """Zero is a recordable answer - an unassisted review that took no time - and the
    boundary the constraint must not exclude."""
    timing = Timing(
        baseline_minutes=0.0,
        assisted_supervision_minutes=0.0,
        assisted_verification_minutes=0.0,
        false_alarm_handling_minutes=0.0,
        unattended_runtime_minutes=0.0,
    )
    assert timing.net_saved_minutes == pytest.approx(0.0)

    payload = build_session(timing=timing).model_dump(mode="json")

    errors = sorted(session_validator().iter_errors(payload), key=lambda e: list(e.absolute_path))
    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_evidence_request_id_pattern_is_enforced() -> None:
    with pytest.raises(ValidationError, match="pattern"):
        EvidenceRequest(
            id="ER-1",
            what="Tapped depth",
            why="fastener.engagement",
            entity_ids=[],
            status="open",
            answer=None,
            answered_at=None,
        )


def test_evidence_request_id_allocator_yields_padded_ids() -> None:
    allocator = EvidenceRequestIdAllocator()

    assert [next(allocator) for _ in range(2)] == ["ER-001", "ER-002"]


def test_investigation_step_records_an_error() -> None:
    step = InvestigationStep(
        index=1,
        tool="measure_face_gap",
        arguments={"a": "face:1", "b": "face:2"},
        result_summary="tool failed",
        status="error",
        error="faces are not parallel",
        elapsed_s=0.01,
    )

    assert step.status == "error"
    assert step.error == "faces are not parallel"


# --- feature 002: the optional provider fields (T016) --------------------------------


def test_provider_info_and_retry_of_round_trip_and_validate(tmp_path: Path) -> None:
    previous = "6f1d1d6a-6c8a-4f29-9f3f-0b0f6f5b9e11"
    session = build_session(
        provider_info=ProviderInfo(
            provider="openai",
            model="gpt-test",
            effort_mapping=EffortMapping(
                requested="high", provider_param="reasoning.effort", provider_value="high"
            ),
            key_source="env",
        ),
        retry_of=previous,
    )

    path = save_session(session, tmp_path / "session.json")
    written = json.loads(path.read_text(encoding="utf-8"))
    session_validator().validate(written)

    reloaded = load_session(path)
    assert reloaded.provider_info is not None
    assert reloaded.provider_info.provider == "openai"
    assert reloaded.provider_info.effort_mapping.provider_value == "high"
    assert reloaded.provider_info.key_source == "env"
    assert str(reloaded.retry_of) == previous


def test_an_integer_effort_value_is_recorded_and_validates(tmp_path: Path) -> None:
    session = build_session(
        provider_info=ProviderInfo(
            provider="gemini",
            model="gemini-test",
            effort_mapping=EffortMapping(
                requested="low", provider_param="thinking_budget", provider_value=1024
            ),
            key_source="settings",
        )
    )

    path = save_session(session, tmp_path / "session.json")
    session_validator().validate(json.loads(path.read_text(encoding="utf-8")))
    assert load_session(path).provider_info.effort_mapping.provider_value == 1024  # type: ignore[union-attr]


def test_a_session_without_the_provider_fields_still_validates(tmp_path: Path) -> None:
    session = build_session()

    assert session.provider_info is None
    assert session.retry_of is None
    path = save_session(session, tmp_path / "session.json")
    session_validator().validate(json.loads(path.read_text(encoding="utf-8")))


def test_provider_info_rejects_an_unknown_key_source() -> None:
    with pytest.raises(ValidationError):
        ProviderInfo(
            provider="openai",
            model="gpt-test",
            effort_mapping=EffortMapping(
                requested="high", provider_param="reasoning.effort", provider_value="high"
            ),
            key_source="hard-coded",  # type: ignore[arg-type]
        )
