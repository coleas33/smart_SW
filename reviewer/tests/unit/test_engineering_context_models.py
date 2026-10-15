import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from swreview.engineering_context.models import (
    ContextArtifact,
    CoordinateFrame,
    EvidenceBaseline,
    ForceQuantity,
    Provenance,
    RequirementRecord,
    TargetAnchor,
    canonical_bytes,
    context_digest,
)
from swreview.units import force_newtons


def test_force_conversion_is_checked_and_keeps_magnitude():
    assert force_newtons(2.0, "kN") == pytest.approx(2000.0)
    assert force_newtons(1.0, "lbf") == pytest.approx(4.4482216152605)
    assert force_newtons(0.0, "N") == 0.0


@pytest.mark.parametrize(
    "value,unit",
    [(-1.0, "N"), (float("nan"), "N"), (float("inf"), "N"), (1.0, "mm"), (1.0, "rad"), (1.0, "Pa")],
)
def test_force_conversion_refuses_invalid_or_other_dimensions(value, unit):
    with pytest.raises(ValueError):
        force_newtons(value, unit)


def test_frame_model_refuses_nonrigid_transform():
    with pytest.raises(ValueError):
        CoordinateFrame(
            frame_id="scaled",
            document_id="doc:root",
            transform=(
                (2.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0, 1.0),
            ),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(state="known", value=None, unit="N"),
        dict(state="known", value=-1.0, unit="N"),
        dict(state="unknown", value=0.0, unit="N"),
        dict(state="unknown", unit="N"),
        dict(state="known", value=float("nan"), unit="N"),
    ],
)
def test_force_quantity_refuses_contradictory_unknown(kwargs):
    with pytest.raises(ValidationError):
        ForceQuantity(**kwargs)


def test_zero_and_unknown_are_distinct():
    zero = ForceQuantity(state="known", value=0.0, unit="N")
    missing = ForceQuantity(state="unknown", unit="N", reason="Awaiting load case")
    assert zero.value == 0.0 and missing.value is None


def example_context():
    package_id = uuid4()
    baseline = EvidenceBaseline(
        package_id=package_id,
        package_sha256="a" * 64,
        schema_version="1.6.0",
        root_document_id="doc:root",
        configuration="Default",
    )
    record = RequirementRecord(
        record_id="req:001",
        revision=1,
        anchor=TargetAnchor(
            anchor_id="target:001",
            package_id=package_id,
            kind="document",
            entity_id="doc:root",
            document_id="doc:root",
            configuration="Default",
        ),
        provenance=Provenance(kind="engineer", source="manual"),
        text="The bracket shall support the specified operating load.",
    )
    return ContextArtifact(
        context_id=uuid4(),
        revision=1,
        baseline=baseline,
        records=(record,),
        updated_at=datetime.now(UTC),
    )


def test_schema_is_strict_immutable_and_canonical_round_trip():
    context = example_context()
    assert ContextArtifact.model_validate_json(canonical_bytes(context)) == context
    assert len(context_digest(context)) == 64
    with pytest.raises(ValidationError):
        context.records[0].text = "silently changed"
    with pytest.raises(ValidationError):
        ContextArtifact.model_validate_json(
            canonical_bytes(context).replace(
                b'"schema_version":"1.0.0"', b'"schema_version":"2.0.0"'
            )
        )


def test_context_refuses_duplicate_ids_and_unaware_timestamp():
    context = example_context()
    payload = context.model_dump(mode="json")
    payload["records"].append(payload["records"][0])
    import json

    with pytest.raises(ValidationError):
        ContextArtifact.model_validate_json(json.dumps(payload))
    with pytest.raises(ValidationError):
        ContextArtifact(
            context_id=uuid4(),
            revision=1,
            baseline=context.baseline,
            updated_at=datetime(2026, 10, 14),
        )


def test_blank_engineering_content_and_actor_are_refused():
    from swreview.engineering_context.models import ConfirmationReceipt

    context = example_context()
    with pytest.raises(ValidationError):
        RequirementRecord.model_validate_json(
            context.records[0].model_dump_json().replace(context.records[0].text, "   ")
        )
    with pytest.raises(ValidationError):
        ConfirmationReceipt(
            receipt_id=uuid4(),
            record_id="req:001",
            record_revision=1,
            record_digest="a" * 64,
            dependency_digest="b" * 64,
            actor="  ",
            confirmed_at=datetime.now(UTC),
        )


def test_schema_contract_and_fictional_force_fixture():
    from jsonschema import Draft202012Validator

    from swreview.engineering_context.binding import force_in_root

    root = Path(__file__).resolve().parents[3]
    schema = json.loads(
        (
            root / "specs/016-engineering-context/contracts/engineering-context.schema.json"
        ).read_bytes()
    )
    assert schema == ContextArtifact.model_json_schema()
    raw = (
        root / "reviewer/tests/fixtures/engineering-context/requirements-and-force.json"
    ).read_bytes()
    Draft202012Validator(schema).validate(json.loads(raw))
    artifact = ContextArtifact.model_validate_json(raw)
    force = next(r for r in artifact.records if r.kind == "applied_force")
    resolved = force_in_root(force)
    assert resolved.vector_n == pytest.approx((0.0, 2000.0, 0.0))
    assert resolved.point_m == pytest.approx((1.0, 3.0, 3.0))


def test_revision_is_bounded_for_projection_and_interop():
    with pytest.raises(ValidationError):
        RequirementRecord.model_validate_json(
            example_context()
            .records[0]
            .model_dump_json()
            .replace('"revision":1', '"revision":2147483648')
        )
