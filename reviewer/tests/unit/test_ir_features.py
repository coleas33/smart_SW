"""Unit tests for the IR 1.1.0 additions (T005).

Rules under test come from `specs/003-resilient-modeling/data-model.md` section 1: the
feature tree, its sketch and fillet details, equations, the suppress-test run, the raw
constrained status on a component instance, and the new gap `entity_kind` values. The
schema-major gate of feature 001 is unchanged - 1.1.0 and 1.0.0 both load, 2.0.0 still
raises - and a 1.0.0 package that predates every new member loads with the defaults.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from swreview.ir.models import (
    SCHEMA_VERSION,
    ComponentInstance,
    Equation,
    EvidencePackage,
    Feature,
    FilletInfo,
    Gap,
    Quantity,
    SketchInfo,
    SuppressTestRow,
    SuppressTestRun,
    UnsupportedSchemaVersionError,
)
from tests.golden.test_golden import case_dirs
from tests.support.features import AssemblySpec, InstanceSpec, MateSpec, PartSpec, rms_package
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

GOLDEN_FIXTURES = Path(__file__).resolve().parents[1] / "golden" / "fixtures"
GOLDEN_FIXTURE_DIRS = case_dirs(GOLDEN_FIXTURES)

OUTCOMES = (
    "ok",
    "rebuild_errors",
    "already_suppressed",
    "not_applied",
    "truncated",
    "aborted",
)

NEW_GAP_ENTITY_KINDS = (
    "feature_tree_unavailable",
    "feature_tree_configuration",
    "feature_children",
    "feature_parents",
    "sketch_status",
    "feature_description",
    "fillet_radius",
    "equations",
    "component_constrained_status",
    "mate_suppression",
)

NULLABLE_FEATURE_FIELDS = [
    "description",
    "folder_id",
    "suppressed",
    "error_code",
    "child_ids",
    "parent_ids",
]


def build_feature(**overrides: Any) -> Feature:
    """A minimal valid `Feature`; `overrides` replace fields."""
    fields: dict[str, Any] = {
        "id": "feat:0001",
        "persist_ref": persist_ref("feat:0001"),
        "persist_ref_scope": "doc:2",
        "document_id": "doc:2",
        "configuration": "Default",
        "name": "Boss-Extrude1",
        "type_name": "Extrusion",
        "description": None,
        "index": 0,
        "depth": 0,
        "folder_id": None,
        "suppressed": False,
        "error_code": 0,
        "child_ids": [],
        "parent_ids": [],
        "sketch": None,
        "fillet": None,
    }
    fields.update(overrides)
    return Feature(**fields)


def build_row(**overrides: Any) -> SuppressTestRow:
    """A minimal valid `SuppressTestRow`; `overrides` replace fields."""
    fields: dict[str, Any] = {
        "feature_id": "feat:0001",
        "persist_ref": persist_ref("feat:0001"),
        "persist_ref_scope": "doc:2",
        "name": "Boss-Extrude1",
        "outcome": "ok",
        "whats_wrong_count": 0,
        "messages": [],
        "messages_truncated": 0,
        "error": None,
        "elapsed_ms": 120,
    }
    fields.update(overrides)
    return SuppressTestRow(**fields)


def build_run(**overrides: Any) -> SuppressTestRun:
    """A minimal valid `SuppressTestRun`; `overrides` replace fields."""
    fields: dict[str, Any] = {
        "document_id": "doc:2",
        "configuration": "Default",
        "group": "Detail",
        "plan_file": "runs/2026-09-15/suppress-plan.json",
        "run_at": datetime(2026, 9, 15, 9, 30, tzinfo=UTC),
        "acknowledged": True,
        "baseline_whats_wrong_count": 0,
        "limit": 25,
        "timeout_seconds": 600,
        "features_present": 1,
        "restore_verified": True,
        "unrestored_feature_ids": [],
        "rows": [build_row()],
    }
    fields.update(overrides)
    return SuppressTestRun(**fields)


def component_fields(**overrides: Any) -> dict[str, Any]:
    """The fields of a valid `ComponentInstance`; `overrides` replace fields."""
    fields: dict[str, Any] = {
        "id": "cmp:0001",
        "persist_ref": persist_ref("cmp:0001"),
        "persist_ref_scope": "doc:1",
        "name": "housing-1",
        "full_path": "housing-1",
        "document_id": "doc:2",
        "parent_id": None,
        "referenced_configuration": "Default",
        "transform": IDENTITY_TRANSFORM,
        "suppression": "resolved",
        "is_fixed": True,
        "pattern_id": None,
        "is_toolbox": False,
    }
    fields.update(overrides)
    return fields


# --- Feature ----------------------------------------------------------------------


def test_feature_carries_the_extractor_read_fields() -> None:
    feature = build_feature()

    assert feature.id == "feat:0001"
    assert feature.persist_ref_scope == "doc:2"
    assert feature.document_id == "doc:2"
    assert feature.configuration == "Default"
    assert feature.type_name == "Extrusion"
    assert feature.index == 0
    assert feature.depth == 0
    assert feature.folder_id is None


def test_feature_id_must_use_the_feat_prefix() -> None:
    with pytest.raises(ValidationError):
        build_feature(id="f:1")


@pytest.mark.parametrize("field", ["is_folder", "is_end_tag", "group", "subfolder", "class"])
def test_feature_rejects_the_python_derived_fields(field: str) -> None:
    """The extractor decides nothing about folders, end tags, groups or classes."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        build_feature(**{field: True})


@pytest.mark.parametrize("field", NULLABLE_FEATURE_FIELDS)
def test_feature_unknowns_stay_none(field: str) -> None:
    feature = build_feature(**{field: None})

    assert getattr(feature, field) is None
    assert field in feature.model_dump()


@pytest.mark.parametrize("field", NULLABLE_FEATURE_FIELDS)
def test_feature_nullable_fields_must_be_stated(field: str) -> None:
    fields = build_feature().model_dump()
    del fields[field]

    with pytest.raises(ValidationError, match=field):
        Feature(**fields)


@pytest.mark.parametrize("field", ["index", "depth"])
def test_feature_counters_are_not_negative(field: str) -> None:
    """`index` is a position in the tree and `depth` a nesting level; neither can be < 0."""
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        build_feature(**{field: -1})


def test_feature_description_distinguishes_blank_from_unreadable() -> None:
    assert build_feature(description="").description == ""
    assert build_feature(description=None).description is None


def test_feature_child_ids_distinguish_none_from_unavailable() -> None:
    assert build_feature(child_ids=[]).child_ids == []
    assert build_feature(child_ids=None).child_ids is None


# --- SketchInfo and FilletInfo ----------------------------------------------------


def test_sketch_info_holds_only_the_raw_status_and_the_consumers() -> None:
    sketch = SketchInfo(raw_status=2, consumer_ids=["feat:0002"])

    assert set(sketch.model_dump()) == {"raw_status", "consumer_ids"}
    assert sketch.raw_status == 2
    assert sketch.consumer_ids == ["feat:0002"]


def test_sketch_info_rejects_a_derived_status_name() -> None:
    """Mapping a raw status to a name is Python's job, not the extractor's."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SketchInfo(raw_status=2, consumer_ids=[], status="under_defined")  # type: ignore[call-arg]


def test_sketch_info_unknowns_stay_none() -> None:
    sketch = SketchInfo(raw_status=None, consumer_ids=None)

    assert sketch.raw_status is None
    assert sketch.consumer_ids is None


def test_sketch_info_distinguishes_no_consumers_from_unavailable_consumers() -> None:
    assert SketchInfo(raw_status=1, consumer_ids=[]).consumer_ids == []
    assert SketchInfo(raw_status=1, consumer_ids=None).consumer_ids is None


def test_fillet_info_default_radius_is_a_quantity_or_none() -> None:
    fillet = FilletInfo(default_radius=Quantity(value=0.003, unit="m"))

    assert fillet.default_radius is not None
    assert fillet.default_radius.value == 0.003
    assert fillet.default_radius.unit == "m"
    assert FilletInfo(default_radius=None).default_radius is None


def test_fillet_info_default_radius_is_not_a_bare_float() -> None:
    with pytest.raises(ValidationError):
        FilletInfo(default_radius=0.003)  # type: ignore[arg-type]


def test_feature_carries_a_sketch_and_a_fillet() -> None:
    feature = build_feature(
        sketch=SketchInfo(raw_status=3, consumer_ids=["feat:0002"]),
        fillet=FilletInfo(default_radius=Quantity(value=0.002, unit="m")),
    )

    assert feature.sketch is not None
    assert feature.sketch.raw_status == 3
    assert feature.fillet is not None
    assert feature.fillet.default_radius == Quantity(value=0.002, unit="m")


# --- Equation ---------------------------------------------------------------------


def test_equation_carries_the_text_and_the_left_hand_side() -> None:
    equation = Equation(
        document_id="doc:2",
        index=0,
        text='"Width" = 25',
        lhs="Width",
        is_global=True,
        value=25.0,
    )

    assert equation.document_id == "doc:2"
    assert equation.index == 0
    assert equation.text == '"Width" = 25'
    assert equation.lhs == "Width"
    assert equation.is_global is True
    assert equation.value == 25.0


def test_equation_index_is_not_negative() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Equation(
            document_id="doc:2",
            index=-1,
            text='"x" = 1',
            lhs="x",
            is_global=True,
            value=1.0,
        )


def test_equation_is_global_may_be_unknown() -> None:
    equation = Equation(
        document_id="doc:2",
        index=1,
        text='"D1@Sketch1" = "Width" / 2',
        lhs="D1@Sketch1",
        is_global=None,
        value=None,
    )

    assert equation.is_global is None
    assert equation.value is None


def test_equation_is_global_must_be_stated() -> None:
    with pytest.raises(ValidationError, match="is_global"):
        Equation(  # type: ignore[call-arg]
            document_id="doc:2",
            index=0,
            text='"x" = 1',
            lhs="x",
            value=1.0,
        )


# --- SuppressTestRun and SuppressTestRow ------------------------------------------


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_suppress_test_outcome_validates(outcome: str) -> None:
    row = build_row(outcome=outcome)

    assert row.outcome == outcome


def test_an_unknown_suppress_test_outcome_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_row(outcome="restored")


def test_suppress_test_row_unknowns_stay_none() -> None:
    row = build_row(whats_wrong_count=None, elapsed_ms=None, error=None)

    assert row.whats_wrong_count is None
    assert row.elapsed_ms is None
    assert row.error is None


def test_suppress_test_row_records_how_many_messages_were_dropped() -> None:
    row = build_row(messages=[f"error {n}" for n in range(20)], messages_truncated=4)

    assert len(row.messages) == 20
    assert row.messages_truncated == 4


def test_suppress_test_row_keeps_at_most_twenty_messages() -> None:
    with pytest.raises(ValidationError):
        build_row(messages=[f"error {n}" for n in range(21)], messages_truncated=0)


def test_suppress_test_row_messages_truncated_is_not_negative() -> None:
    with pytest.raises(ValidationError):
        build_row(messages_truncated=-1)


@pytest.mark.parametrize("field", ["whats_wrong_count", "elapsed_ms"])
def test_suppress_test_row_counts_are_not_negative(field: str) -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        build_row(**{field: -1})


def test_suppress_test_run_records_the_audit_fields() -> None:
    run = build_run()

    assert run.document_id == "doc:2"
    assert run.configuration == "Default"
    assert run.group == "Detail"
    assert run.plan_file == "runs/2026-09-15/suppress-plan.json"
    assert run.baseline_whats_wrong_count == 0
    assert run.limit == 25
    assert run.timeout_seconds == 600
    assert run.acknowledged is True
    assert run.restore_verified is True
    assert run.unrestored_feature_ids == []
    assert run.features_present == len(run.rows)


def test_suppress_test_run_records_an_unrestored_tree() -> None:
    run = build_run(restore_verified=False, unrestored_feature_ids=["feat:0001"])

    assert run.restore_verified is False
    assert run.unrestored_feature_ids == ["feat:0001"]


def test_suppress_test_run_rows_may_record_a_truncated_tail() -> None:
    run = build_run(
        limit=1,
        features_present=2,
        rows=[build_row(), build_row(feature_id="feat:0002", outcome="truncated")],
    )

    assert [row.outcome for row in run.rows] == ["ok", "truncated"]


@pytest.mark.parametrize("field", ["features_present", "baseline_whats_wrong_count"])
def test_suppress_test_run_counts_are_not_negative(field: str) -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        build_run(**{field: -1})


@pytest.mark.parametrize("field", ["limit", "timeout_seconds"])
def test_suppress_test_run_budgets_are_at_least_one(field: str) -> None:
    """A run of zero features or zero seconds is not a run; the command refuses it."""
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        build_run(**{field: 0})


def test_suppress_test_run_rows_must_account_for_every_planned_feature() -> None:
    """`features_present` equals `len(rows)`: an untested feature is a `truncated` row,
    never a missing one, so a reader can never be shown a short table as a full one."""
    with pytest.raises(ValidationError, match="features_present"):
        build_run(features_present=2, rows=[build_row()])


def test_suppress_test_run_cannot_verify_a_restore_it_did_not_make() -> None:
    with pytest.raises(ValidationError, match="restore_verified"):
        build_run(restore_verified=True, unrestored_feature_ids=["feat:0001"])


def test_suppress_test_run_round_trips_through_json() -> None:
    run = build_run()

    restored = SuppressTestRun.model_validate_json(run.model_dump_json())

    assert restored == run


# --- ComponentInstance.constrained_status_raw -------------------------------------


def test_component_constrained_status_raw_defaults_to_none() -> None:
    component = ComponentInstance(**component_fields())

    assert component.constrained_status_raw is None
    assert "constrained_status_raw" in component.model_dump()


def test_component_transform_documents_the_frame_and_the_unit() -> None:
    """The contract must say what frame and unit a transform is in; a regenerated
    schema that drops the description leaves the extractor guessing."""
    description = ComponentInstance.model_fields["transform"].description

    assert description == (
        "Row-major 4x4 relative to the root assembly, translation in meters"
    )


def test_component_constrained_status_raw_is_the_verbatim_int() -> None:
    component = ComponentInstance(**component_fields(constrained_status_raw=3))

    assert component.constrained_status_raw == 3


def test_component_constrained_status_raw_is_not_a_derived_name() -> None:
    with pytest.raises(ValidationError):
        ComponentInstance(**component_fields(constrained_status_raw="over_defined"))


# --- Gap entity kinds -------------------------------------------------------------


@pytest.mark.parametrize("entity_kind", NEW_GAP_ENTITY_KINDS)
def test_the_new_gap_entity_kinds_validate(entity_kind: str) -> None:
    gap = Gap(
        kind="not_extracted",
        entity_kind=entity_kind,
        entity_id="feat:0001",
        reason="not read on this workstation",
        error=None,
    )

    assert gap.entity_kind == entity_kind


def test_the_fixture_builder_emits_only_documented_gap_entity_kinds() -> None:
    """Anchor `NEW_GAP_ENTITY_KINDS` to something that actually writes a gap.

    `Gap.entity_kind` is a free string, so the parametrized test above would pass for any
    tuple at all. The fixture builder is the one producer of these kinds in the test
    suite; a kind it emits and data-model.md section 1 does not document fails here.
    """
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="housing",
                instances=[InstanceSpec("housing-1", suppression="suppressed")],
            )
        ],
        assembly=AssemblySpec(
            mates=[MateSpec(entities=[("housing-1", "FACE")], suppression_gap=True)]
        ),
    )

    emitted = {gap.entity_kind for gap in package.gaps}

    assert emitted
    assert emitted <= set(NEW_GAP_ENTITY_KINDS)


# --- EvidencePackage --------------------------------------------------------------


def test_the_current_schema_version_is_readable_here() -> None:
    # Bumped to 1.2.0 by T065 (extractor.profile), to 1.3.0 by T089 (the reuse fields),
    # to 1.4.0 by 006 T013 (the standards evidence), to 1.5.0 by 010 T077 (the tolerance
    # evidence) and to 1.6.0 by 011 T006 (the drawing context); the 1.1.0 members below are
    # unchanged by all five.
    assert SCHEMA_VERSION == "1.6.0"


def test_the_new_package_members_default_to_empty() -> None:
    package = build_package()

    assert package.schema_version == SCHEMA_VERSION
    assert package.features == []
    assert package.equations == []
    assert package.rms_suppress_test is None


def test_a_package_carries_features_equations_and_a_suppress_test_run() -> None:
    package = build_package(
        features=[build_feature()],
        equations=[
            Equation(
                document_id="doc:2",
                index=0,
                text='"Width" = 25',
                lhs="Width",
                is_global=True,
                value=25.0,
            )
        ],
        rms_suppress_test=build_run(),
    )

    assert [feature.id for feature in package.features] == ["feat:0001"]
    assert [equation.lhs for equation in package.equations] == ["Width"]
    assert package.rms_suppress_test is not None
    assert package.rms_suppress_test.group == "Detail"


def test_a_package_with_the_new_members_round_trips_through_json() -> None:
    package = build_package(
        features=[build_feature(sketch=SketchInfo(raw_status=2, consumer_ids=None))],
        rms_suppress_test=build_run(),
    )

    restored = EvidencePackage.model_validate_json(package.model_dump_json())

    assert restored == package


def test_a_one_zero_zero_package_without_the_new_members_still_loads() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "1.0.0"
    for member in ("features", "equations", "rms_suppress_test"):
        payload.pop(member)
    for component in payload["components"]:
        component.pop("constrained_status_raw")

    package = EvidencePackage.model_validate_json(json.dumps(payload))

    assert package.schema_version == "1.0.0"
    assert package.features == []
    assert package.equations == []
    assert package.rms_suppress_test is None
    assert all(component.constrained_status_raw is None for component in package.components)


@pytest.mark.parametrize(
    "fixture", GOLDEN_FIXTURE_DIRS, ids=lambda path: path.name
)
def test_every_shipped_golden_fixture_still_loads(fixture: Path) -> None:
    """Every committed fixture loads; the pre-1.1.0 ones still get the new defaults.

    The version is read from the file rather than asserted, so a fixture written at 1.1.0
    (the RMS goldens of this feature) is covered for loading without turning the
    back-compat assertion into a contradiction.

    The fixtures are discovered by the golden harness's own walk, so a feature that groups
    its cases in a subdirectory is covered here by the same listing that runs them rather
    than by a second one that would silently skip them.
    """
    text = (fixture / "package.json").read_text(encoding="utf-8")
    declared = json.loads(text)["schema_version"]

    package = EvidencePackage.model_validate_json(text)

    assert package.schema_version == declared
    if declared == "1.0.0":
        assert package.features == []
        assert package.equations == []
        assert package.rms_suppress_test is None


def test_an_unsupported_schema_major_still_raises() -> None:
    with pytest.raises(UnsupportedSchemaVersionError):
        build_package(schema_version="2.0.0")
