"""Unit tests for the IR models (T009).

Rules under test come from data-model.md sections 1 and 2 and research R5: strict
pydantic models, no extra fields, a dedicated error for an unsupported schema major,
and engineering nulls that stay null.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from swreview.ir.models import (
    SCHEMA_VERSION,
    Angle,
    Axis,
    ComponentInstance,
    EvidencePackage,
    Fastener,
    Hole,
    Quantity,
    SourceRef,
    UnsupportedSchemaVersionError,
    Vec3,
)
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

ORIGIN = Axis(origin=Vec3(x=0.0, y=0.0, z=0.0), direction=Vec3(x=0.0, y=0.0, z=1.0))


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Quantity(value=1.0, unit="mm", tolerance="±0.1")  # type: ignore[call-arg]


def test_strict_mode_rejects_a_string_for_a_number() -> None:
    with pytest.raises(ValidationError):
        Quantity(value="1.0", unit="mm")  # type: ignore[arg-type]


def test_quantity_unit_enum_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Quantity(value=1.0, unit="cm")  # type: ignore[arg-type]


def test_angle_is_a_distinct_type_from_quantity() -> None:
    assert not isinstance(Angle(value=1.0, unit="deg"), Quantity)
    with pytest.raises(ValidationError):
        Angle(value=1.0, unit="mm")  # type: ignore[arg-type]


def test_supported_schema_version_loads() -> None:
    package = build_package(schema_version="1.3.0")

    assert package.schema_version == "1.3.0"


def test_unsupported_schema_major_raises_the_dedicated_error() -> None:
    with pytest.raises(UnsupportedSchemaVersionError):
        build_package(schema_version="2.0.0")


def test_unsupported_schema_major_is_a_value_error_but_not_a_validation_error() -> None:
    assert issubclass(UnsupportedSchemaVersionError, ValueError)
    assert not issubclass(UnsupportedSchemaVersionError, ValidationError)


def test_unsupported_schema_major_raised_from_json_too() -> None:
    payload = build_package().model_dump_json().replace(f'"{SCHEMA_VERSION}"', '"2.0.0"', 1)

    with pytest.raises(UnsupportedSchemaVersionError):
        EvidencePackage.model_validate_json(payload)


def test_malformed_schema_version_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        build_package(schema_version="one")


def test_hole_thread_depth_may_be_none_and_is_never_defaulted() -> None:
    hole = Hole(
        id="hole:1",
        persist_ref=persist_ref("hole:1"),
        persist_ref_scope="doc:2",
        component_id="cmp:0001",
        feature_name="M6 Tapped Hole1",
        hole_type="tapped",
        standard="ISO",
        size="M6",
        thread_designation="M6x1.0",
        thread_depth=None,
        hole_depth=Quantity(value=12.0, unit="mm"),
        end_condition="blind",
        diameter=Quantity(value=5.0, unit="mm"),
        axis=ORIGIN,
        face_ids=[],
    )

    assert hole.thread_depth is None
    assert "thread_depth" in hole.model_dump()


def test_hole_thread_depth_is_required_to_be_stated() -> None:
    with pytest.raises(ValidationError, match="thread_depth"):
        Hole(
            id="hole:1",
            persist_ref=persist_ref("hole:1"),
            persist_ref_scope="doc:2",
            component_id="cmp:0001",
            feature_name="M6 Tapped Hole1",
            hole_type="tapped",
            standard=None,
            size=None,
            thread_designation=None,
            hole_depth=None,
            end_condition="unknown",
            diameter=None,
            axis=ORIGIN,
            face_ids=[],
        )  # type: ignore[call-arg]


def test_fastener_identity_source_enum_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Fastener(
            id="fst:1",
            persist_ref=persist_ref("fst:1"),
            persist_ref_scope="doc:1",
            component_id="cmp:0002",
            kind="screw",
            identity_source="guessed",  # type: ignore[arg-type]
            thread_designation="M6x1.0",
            length=Quantity(value=20.0, unit="mm"),
            head_type=None,
            head_diameter=None,
            head_height=None,
            drive=None,
            axis=ORIGIN,
            material=None,
        )


def test_component_instance_id_pattern() -> None:
    with pytest.raises(ValidationError, match="pattern"):
        ComponentInstance(
            id="cmp:12",
            persist_ref=persist_ref("cmp:12"),
            persist_ref_scope="doc:1",
            name="bracket-3",
            full_path="sub-2/bracket-3",
            document_id="doc:2",
            parent_id=None,
            referenced_configuration="Default",
            transform=IDENTITY_TRANSFORM,
            suppression="resolved",
            is_fixed=True,
            pattern_id=None,
            is_toolbox=False,
        )


def test_component_instance_carries_scope_and_full_path() -> None:
    component = build_package().components[0]

    assert component.full_path
    assert component.persist_ref_scope
    assert component.persist_ref


def test_persist_ref_must_be_base64() -> None:
    with pytest.raises(ValidationError):
        ComponentInstance(
            id="cmp:0001",
            persist_ref="not base64!!",
            persist_ref_scope="doc:1",
            name="bracket-3",
            full_path="bracket-3",
            document_id="doc:2",
            parent_id=None,
            referenced_configuration="Default",
            transform=IDENTITY_TRANSFORM,
            suppression="resolved",
            is_fixed=True,
            pattern_id=None,
            is_toolbox=False,
        )


def test_interference_volume_unit_is_restricted_to_volume_units() -> None:
    from swreview.ir.models import Volume

    assert Volume(value=1.0, unit="mm3").unit == "mm3"
    with pytest.raises(ValidationError):
        Volume(value=1.0, unit="mm")  # type: ignore[arg-type]


def test_interference_carries_fastener_and_possible_flags() -> None:
    from swreview.ir.models import Interference, InterferenceSettings

    interference = Interference(
        id="int:1",
        configuration="Default",
        component_ids=["cmp:0001", "cmp:0002"],
        volume=None,
        settings=InterferenceSettings(
            treat_coincident_as_interference=False,
            treat_subassemblies_as_components=True,
            include_multibody=True,
            ignore_hidden=False,
            fastener_folder_treatment="include",
        ),
        is_fastener=False,
        is_possible=True,
        status="computed",
        error=None,
        group_key="cmp:0001|cmp:0002",
    )

    assert interference.is_fastener is False
    assert interference.is_possible is True
    assert interference.volume is None


def test_interference_needs_exactly_two_components() -> None:
    from swreview.ir.models import Interference, InterferenceSettings

    settings = InterferenceSettings(
        treat_coincident_as_interference=False,
        treat_subassemblies_as_components=True,
        include_multibody=True,
        ignore_hidden=False,
        fastener_folder_treatment="include",
    )
    with pytest.raises(ValidationError):
        Interference(
            id="int:1",
            configuration="Default",
            component_ids=["cmp:0001"],
            volume=None,
            settings=settings,
            is_fastener=False,
            is_possible=False,
            status="computed",
            error=None,
            group_key="k",
        )


def test_source_ref_without_a_locator_fails() -> None:
    with pytest.raises(ValidationError, match="locator"):
        SourceRef(document_id="doc:3")


@pytest.mark.parametrize(
    "locator",
    [
        {"sheet": "Sheet1"},
        {"annotation": "Dim1"},
        {"page": 2},
        {"persist_ref": persist_ref("face:1")},
    ],
)
def test_source_ref_accepts_any_single_locator(locator: dict[str, object]) -> None:
    assert SourceRef(document_id="doc:3", **locator).document_id == "doc:3"
