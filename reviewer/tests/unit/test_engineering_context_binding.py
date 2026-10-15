"""Offline identity and force-frame contracts; no native state is asserted."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

import pytest

from swreview.engineering_context.binding import (
    anchor_from_package,
    assess_binding,
    assess_record_binding,
    assess_records_binding,
    baseline_from_package,
    force_in_root,
    frame_from_package,
    normalize_direction,
    rotate_vector,
    transform_point_m,
    validate_rigid_transform,
)
from swreview.engineering_context.models import (
    AppliedForceRecord,
    EvidenceBaseline,
    ForceQuantity,
    Provenance,
)
from swreview.ir.loader import (
    AnswerKeyAccessError,
    LoadedPackage,
    append_interference_run,
    load_package,
    merged_package_text,
    save_package,
)
from swreview.ir.models import (
    BBox3D,
    EvidencePackage,
    FaceGeometry,
    Gap,
    Interference,
    PlaneFace,
    Vec3,
)
from tests.support.packages import build_package, persist_ref
from tests.support.review_bridge import interference_row

IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
TURN_AND_TRANSLATE = [
    [0.0, -1.0, 0.0, 10.0],
    [1.0, 0.0, 0.0, 20.0],
    [0.0, 0.0, 1.0, 30.0],
    [0.0, 0.0, 0.0, 1.0],
]


def test_point_is_translated_but_force_is_only_rotated() -> None:
    assert transform_point_m(TURN_AND_TRANSLATE, (2.0, 3.0, 4.0)) == (7.0, 22.0, 34.0)
    vector = rotate_vector(TURN_AND_TRANSLATE, (30.0, 40.0, 0.0))
    assert vector == (-40.0, 30.0, 0.0)
    assert math.hypot(*vector) == 50.0


def test_direction_normalization_is_separate_from_vector_rotation() -> None:
    assert normalize_direction((0.0, -5.0, 0.0)) == (0.0, -1.0, 0.0)
    assert rotate_vector(IDENTITY, (0.0, -5.0, 0.0)) == (0.0, -5.0, 0.0)
    # A zero force is meaningful; its direction must nevertheless be explicitly known.
    assert rotate_vector(IDENTITY, (0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "vector", [(0.0, 0.0, 0.0), (float("nan"), 1.0, 0.0), (0.0, float("inf"), 0.0)]
)
def test_zero_or_nonfinite_direction_is_refused(vector: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        normalize_direction(vector)


def test_normalization_handles_finite_extreme_magnitudes() -> None:
    assert normalize_direction((1e-300, 0.0, 0.0)) == (1.0, 0.0, 0.0)
    assert normalize_direction((1e308, 1e308, 0.0)) == pytest.approx(
        (math.sqrt(0.5), math.sqrt(0.5), 0.0)
    )


@pytest.mark.parametrize(
    "matrix",
    [
        [[-1.0, 0.0, 0.0, 0.0], *IDENTITY[1:]],  # Reflection.
        [[2.0, 0.0, 0.0, 0.0], *IDENTITY[1:]],  # Scale.
        [[1.0, 0.1, 0.0, 0.0], *IDENTITY[1:]],  # Shear.
        [*IDENTITY[:3], [0.0, 0.0, 1.0, 1.0]],  # Non-affine/projective.
        [[1.0, 0.0, 0.0, float("nan")], *IDENTITY[1:]],
        IDENTITY[:3],
        [[1.0, 0.0, 0.0], *IDENTITY[1:]],
    ],
)
def test_unsupported_transform_is_refused(matrix: list[list[float]]) -> None:
    with pytest.raises(ValueError):
        validate_rigid_transform(matrix)
    with pytest.raises(ValueError):
        rotate_vector(matrix, (1.0, 0.0, 0.0))


def test_identity_frame_preserves_root_part_point_and_force() -> None:
    assert transform_point_m(IDENTITY, (0.005, 0.01, -0.02)) == (0.005, 0.01, -0.02)
    assert rotate_vector(IDENTITY, (0.0, 0.0, -100.0)) == (0.0, 0.0, -100.0)


@pytest.mark.parametrize("vector", [(1.0, 2.0), (True, 1.0, 0.0), ("1", 2.0, 3.0)])
def test_malformed_vector_is_refused(vector: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        normalize_direction(vector)  # type: ignore[arg-type]


def _loaded(path: Path, package: EvidencePackage | None = None) -> LoadedPackage:
    save_package(package or build_package(), path)
    return load_package(path)


def _face(component_id: str = "cmp:0001") -> FaceGeometry:
    return FaceGeometry(
        id="face:1", persist_ref=persist_ref("face:1"), persist_ref_scope="doc:2",
        component_id=component_id, body_id="body:1", kind="plane", cylinder=None,
        plane=PlaneFace(origin=Vec3(x=0.0, y=0.0, z=0.0), normal=Vec3(x=0.0, y=0.0, z=1.0)),
        bbox=BBox3D(min=Vec3(x=0.0, y=0.0, z=0.0), max=Vec3(x=0.1, y=0.1, z=0.0)),
        area_m2=0.01,
    )


def test_baseline_attests_exact_saved_bytes_not_native_model(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    raw = (tmp_path / "package.json").read_bytes()
    baseline = baseline_from_package(loaded)
    assert baseline.package_sha256 == hashlib.sha256(raw).hexdigest()
    assert baseline.package_id == loaded.package.package_id
    assert baseline.root_document_id == "doc:1"
    assert baseline.configuration == "Default"
    assert baseline.scope == "saved_snapshot"
    # Harmless formatting is still a different exact saved evidence artifact.
    (tmp_path / "package.json").write_bytes(b" \n" + raw)
    assert baseline_from_package(load_package(tmp_path)).package_sha256 != baseline.package_sha256


def test_baseline_refuses_loaded_object_not_matching_saved_package(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    loaded.package.components[0].transform[0][3] = 1.0
    with pytest.raises(ValueError, match="saved"):
        baseline_from_package(loaded)


def test_repeated_instances_have_exact_separate_occurrence_anchors(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    first = anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")
    second = anchor_from_package(loaded, "anchor:2", "component", "cmp:0002")
    assert first.document_id == second.document_id == "doc:2"
    assert first.component_id == "cmp:0001"
    assert second.component_id == "cmp:0002"
    assert first.full_path == "housing-1"
    assert second.full_path == "housing-2"
    assert first.referenced_configuration == "Default"
    assert first.persist_ref_scope == "doc:1"
    baseline = baseline_from_package(loaded)
    matched = assess_binding(first, baseline, loaded)
    assert matched.status == "matched_snapshot"
    assert matched.needs_review is False
    impostor = first.model_copy(update={"component_id": "cmp:0002"})
    assert assess_binding(impostor, baseline, loaded).status == "mismatch"


def test_same_entity_id_and_ref_bytes_in_new_package_never_rebind(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path / "before")
    anchor = anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")
    baseline = baseline_from_package(loaded)
    refreshed = _loaded(
        tmp_path / "after", loaded.package.model_copy(update={"package_id": uuid4()})
    )
    result = assess_binding(anchor, baseline, refreshed)
    assert result.status == "unresolved"
    assert result.needs_review is True
    assert "package_changed" in result.reasons


@pytest.mark.parametrize("changed", ["configuration", "geometry", "placement"])
def test_changed_dependencies_require_review_without_rebind(tmp_path: Path, changed: str) -> None:
    package = build_package(faces=[_face()])
    loaded = _loaded(tmp_path / "before", package)
    anchor = anchor_from_package(loaded, "anchor:1", "face", "face:1")
    baseline = baseline_from_package(loaded)
    modified = package.model_copy(deep=True)
    if changed == "configuration":
        modified.components[0].referenced_configuration = "Alternate"
    elif changed == "geometry":
        modified.faces[0].area_m2 = 0.02
    else:
        modified.components[0].transform[0][3] = 0.5
    refreshed = _loaded(tmp_path / "after", modified)
    result = assess_binding(anchor, baseline, refreshed)
    assert result.status == "mismatch"
    assert result.needs_review is True
    assert "package_digest_changed" in result.reasons


def test_face_anchor_keeps_owner_scope_and_occurrence_dependencies(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path, build_package(faces=[_face()]))
    anchor = anchor_from_package(loaded, "anchor:1", "face", "face:1")
    assert anchor.document_id == "doc:2"
    assert anchor.configuration == anchor.referenced_configuration == "Default"
    assert anchor.component_id == "cmp:0001"
    assert anchor.full_path == "housing-1"
    assert anchor.persist_ref_scope == "doc:2"
    assert anchor.persist_ref == persist_ref("face:1")
    assert anchor.geometry_sha256
    assert anchor.transform_sha256
    with pytest.raises(ValueError, match="component"):
        anchor_from_package(loaded, "anchor:wrong", "face", "face:1", "cmp:0002")


@pytest.mark.parametrize("suppression", ["suppressed", "unloaded", "lightweight"])
def test_unavailable_component_remains_explicit(tmp_path: Path, suppression: str) -> None:
    package = build_package()
    package.components[0].suppression = suppression
    loaded = _loaded(tmp_path, package)
    anchor = anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")
    result = assess_binding(anchor, baseline_from_package(loaded), loaded)
    assert result.status == "unresolved"
    assert result.needs_review is True
    assert "target_" + suppression in result.reasons
    with pytest.raises(ValueError, match=suppression):
        frame_from_package(loaded, "frame:1", "cmp:0001")


def test_missing_face_stays_unresolved_without_invented_reference(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    draft = anchor_from_package(loaded, "anchor:1", "face", "face:missing", "cmp:0001")
    assert draft.entity_id == "face:missing"
    assert draft.component_id == "cmp:0001"
    assert draft.document_id == "doc:2"
    assert draft.persist_ref is None
    assert draft.geometry_sha256 is None
    result = assess_binding(draft, baseline_from_package(loaded), loaded)
    assert result.status == "unresolved"
    assert "target_missing" in result.reasons


def test_anchor_dependency_tampering_cannot_match_exact_package(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    anchor = anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")
    edited = anchor.model_copy(update={"transform_sha256": "0" * 64})
    result = assess_binding(edited, baseline_from_package(loaded), loaded)
    assert result.status == "mismatch"
    assert result.needs_review is True
    assert "dependency_changed" in result.reasons


def test_ambiguous_package_entity_ids_are_refused(tmp_path: Path) -> None:
    package = build_package()
    package.components.append(package.components[0].model_copy(deep=True))
    loaded = _loaded(tmp_path, package)
    with pytest.raises(ValueError, match="ambiguous"):
        anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")


def test_nested_component_transform_is_already_root_relative(tmp_path: Path) -> None:
    package = build_package()
    package.components[0].transform[0][3] = 100.0
    package.components[1].parent_id = "cmp:0001"
    package.components[1].full_path = "housing-1/housing-2"
    package.components[1].transform = TURN_AND_TRANSLATE
    loaded = _loaded(tmp_path, package)
    frame = frame_from_package(loaded, "frame:child", "cmp:0002")
    assert frame.document_id == "doc:2"
    assert transform_point_m(frame.transform, (2.0, 3.0, 4.0)) == (7.0, 22.0, 34.0)


def test_root_part_frame_does_not_require_a_component(tmp_path: Path) -> None:
    package = build_package()
    package.design.root_assembly_document_id = "doc:2"
    package.components = []
    loaded = _loaded(tmp_path, package)
    frame = frame_from_package(loaded, "frame:root")
    assert frame.document_id == "doc:2"
    assert frame.component_id is None
    assert frame.transform == tuple(tuple(row) for row in IDENTITY)
    anchor = anchor_from_package(loaded, "anchor:root", "document", "doc:2")
    result = assess_binding(anchor, baseline_from_package(loaded), loaded)
    assert result.status == "matched_snapshot"


@pytest.mark.parametrize("parent_state", ["suppressed", "unloaded", "missing", "cycle"])
def test_unavailable_ancestor_prevents_child_match_or_frame(
    tmp_path: Path, parent_state: str
) -> None:
    package = build_package()
    child = package.components[1]
    child.parent_id = "cmp:0001"
    child.full_path = "housing-1/housing-2"
    if parent_state == "missing":
        child.parent_id = "cmp:9999"
    elif parent_state == "cycle":
        package.components[0].parent_id = child.id
    else:
        package.components[0].suppression = parent_state
    loaded = _loaded(tmp_path, package)
    anchor = anchor_from_package(loaded, "anchor:child", "component", child.id)
    result = assess_binding(anchor, baseline_from_package(loaded), loaded)
    assert result.status == "unresolved"
    assert result.needs_review is True
    assert any("ancestor" in reason for reason in result.reasons)
    with pytest.raises(ValueError, match="ancestor"):
        frame_from_package(loaded, "frame:child", child.id)



def _force(loaded: LoadedPackage, *, unit: str = "N", value: float = 50.0) -> AppliedForceRecord:
    return AppliedForceRecord(
        record_id="load:1", revision=1,
        anchor=anchor_from_package(loaded, "anchor:1", "component", "cmp:0001"),
        provenance=Provenance(kind="engineer", source="Fictional fixture"),
        magnitude=ForceQuantity(state="known", value=value, unit=unit),
        direction=(3.0, 4.0, 0.0), frame=frame_from_package(loaded, "frame:1", "cmp:0001"),
        application="component_total", point_m=(2.0, 3.0, 4.0),
    )


def test_force_conversion_preserves_magnitude_and_transforms_point(tmp_path: Path) -> None:
    package = build_package()
    package.components[0].transform = TURN_AND_TRANSLATE
    loaded = _loaded(tmp_path, package)
    force = _force(loaded, unit="kN", value=0.05)
    resolved = force_in_root(force)
    assert resolved.magnitude_n == pytest.approx(50.0)
    assert resolved.direction == pytest.approx((-0.8, 0.6, 0.0))
    assert resolved.vector_n == pytest.approx((-40.0, 30.0, 0.0))
    assert math.hypot(*resolved.vector_n) == pytest.approx(50.0)
    assert resolved.point_m == (7.0, 22.0, 34.0)


def test_zero_known_force_is_distinct_from_unknown_force(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    zero = _force(loaded, value=0.0)
    assert force_in_root(zero).vector_n == (0.0, 0.0, 0.0)
    unknown = zero.model_copy(update={
        "magnitude": ForceQuantity(
            state="unknown", unit="N", reason="Engineer has not supplied it",
        ),
    })
    with pytest.raises(ValueError, match="unknown"):
        force_in_root(unknown)


@pytest.mark.parametrize("missing", ["frame", "direction"])
def test_incomplete_force_is_unresolved_for_rotation(tmp_path: Path, missing: str) -> None:
    force = _force(_loaded(tmp_path)).model_copy(update={missing: None})
    with pytest.raises(ValueError, match="unknown"):
        force_in_root(force)


def test_record_binding_checks_frame_against_saved_placement(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    force = _force(loaded)
    baseline = baseline_from_package(loaded)
    assert assess_record_binding(force, baseline, loaded).status == "matched_snapshot"
    moved_transform = tuple(tuple(row) for row in TURN_AND_TRANSLATE)
    forged = force.model_copy(update={"frame": force.frame.model_copy(update={
        "transform": moved_transform,
    })})
    result = assess_record_binding(forged, baseline, loaded)
    assert result.status == "mismatch"
    assert "frame_mismatch" in result.reasons
    assert result.needs_review is True


def test_unknown_or_wrong_owner_frame_cannot_be_matched(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    baseline = baseline_from_package(loaded)
    force = _force(loaded)
    unknown = force.model_copy(update={"frame": None})
    assert assess_record_binding(unknown, baseline, loaded).status == "unresolved"
    altered = force.model_copy(update={"frame": force.frame.model_copy(update={
        "document_id": "doc:wrong",
    })})
    assert assess_record_binding(altered, baseline, loaded).status == "mismatch"


def test_force_cannot_silently_use_an_alternative_frame(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    force = _force(loaded)
    other = frame_from_package(loaded, "frame:root")
    with pytest.raises(ValueError, match="override"):
        force_in_root(force, other)



def test_batch_assessment_reads_saved_package_once_without_long_lived_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _loaded(tmp_path)
    baseline = baseline_from_package(loaded)
    first = _force(loaded)
    second = first.model_copy(update={"record_id": "load:2"})
    calls: list[Path] = []
    original_read = Path.read_bytes

    def counted_read(path: Path) -> bytes:
        calls.append(path)
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    results = assess_records_binding((first, second), baseline, loaded)
    assert {key: result.status for key, result in results.items()} == {
        "load:1": "matched_snapshot", "load:2": "matched_snapshot",
    }
    assert len(calls) == 1
    loaded.package.components[0].transform[0][3] = 0.5
    results = assess_records_binding((first, second), baseline, loaded)
    assert all(result.status == "unresolved" for result in results.values())
    assert all("saved_snapshot_unavailable" in result.reasons for result in results.values())
    assert len(calls) == 2



@pytest.mark.parametrize("mode", ["anchor", "record", "batch"])
def test_unsafe_snapshot_refusal_is_generic_and_exposes_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    loaded = _loaded(tmp_path)
    baseline = baseline_from_package(loaded)
    force = _force(loaded)

    def refuse_path(*args: object) -> Path:
        # Fail before any filesystem read; the real loader's refusal contains a path.
        raise AnswerKeyAccessError("fictional private path inside a withheld directory")

    monkeypatch.setattr("swreview.engineering_context.binding.reject_answer_key_path", refuse_path)
    if mode == "anchor":
        result = assess_binding(force.anchor, baseline, loaded)
    elif mode == "record":
        result = assess_record_binding(force, baseline, loaded)
    else:
        result = assess_records_binding((force,), baseline, loaded)[force.record_id]
    assert result.status == "unresolved"
    assert result.needs_review is True
    assert result.reasons == ("saved_snapshot_unavailable",)
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize("unknown", ["document", "configuration"])
def test_unknown_ancestor_document_or_configuration_prevents_child_binding(
    tmp_path: Path, unknown: str,
) -> None:
    package = build_package()
    child = package.components[1]
    child.parent_id = "cmp:0001"
    child.full_path = "housing-1/housing-2"
    parent = package.components[0]
    if unknown == "document":
        parent.document_id = "doc:missing"
    else:
        parent.referenced_configuration = "Missing"
    loaded = _loaded(tmp_path, package)
    anchor = anchor_from_package(loaded, "anchor:child", "component", child.id)
    result = assess_binding(anchor, baseline_from_package(loaded), loaded)
    assert result.status == "unresolved"
    assert result.needs_review is True
    expected = (
        "ancestor_document_missing" if unknown == "document" else "ancestor_configuration_unknown"
    )
    assert expected in result.reasons
    with pytest.raises(ValueError, match="ancestor"):
        frame_from_package(loaded, "frame:child", child.id)


# --- owner decision 107A: the live interference check's rewrite keeps inputs matched -----------

LIVE_GAP = Gap(
    kind="unsupported",
    entity_kind="interference_volume_unit",
    entity_id=None,
    reason="IInterference.Volume unit assumed m3; verify on workstation",
    error=None,
)


def _live_checked(path: Path, *, rows: int = 1) -> LoadedPackage:
    """What the pre-run's live interference check leaves: `package.json` rewritten with the
    active configuration's rows replaced and its gaps appended (`append_interference_run`)."""
    detected = [
        Interference.model_validate(
            interference_row(
                f"int:{index:04d}", ("cmp:0001", "cmp:0002"), f"cmp:0001|cmp:0002|{index}", 12.0
            )
        )
        for index in range(1, rows + 1)
    ]
    append_interference_run(path, path, "Default", detected, [LIVE_GAP])
    return load_package(path)


@pytest.mark.parametrize("rows", [0, 2])
def test_a_live_interference_rewrite_keeps_saved_inputs_matched(tmp_path: Path, rows: int) -> None:
    loaded = _loaded(tmp_path)
    anchor = anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")
    baseline = baseline_from_package(loaded)
    before = (tmp_path / "package.json").read_bytes()

    checked = _live_checked(tmp_path, rows=rows)

    assert (tmp_path / "package.json").read_bytes() != before
    assert baseline_from_package(checked).package_sha256 != baseline.package_sha256
    result = assess_binding(anchor, baseline, checked)
    assert result.status == "matched_snapshot"
    assert result.needs_review is False


def _written_as_the_live_check_writes(path: Path, package: EvidencePackage) -> LoadedPackage:
    """`package` written in the spelling `append_interference_run` uses, so only its content
    differs from what the live check would leave."""
    text = merged_package_text(json.loads(package.model_dump_json()))
    (path / "package.json").write_bytes(text.encode("utf-8"))
    return load_package(path)


@pytest.mark.parametrize(
    "changed",
    ["none", "geometry", "document", "other_gap", "other_configuration_row", "respelled"],
)
def test_any_other_change_beside_the_live_rows_is_still_a_mismatch(
    tmp_path: Path, changed: str
) -> None:
    loaded = _loaded(tmp_path)
    anchor = anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")
    baseline = baseline_from_package(loaded)
    checked = _live_checked(tmp_path).package.model_copy(deep=True)
    if changed == "geometry":
        checked.components[1].transform[0][3] = 0.5
    elif changed == "document":
        checked.documents[0].material = "FICT-alloy-B"
    elif changed == "other_gap":
        checked.gaps.append(
            Gap(kind="tool_error", entity_kind="mate", entity_id=None, reason="FICT", error=None)
        )
    elif changed == "other_configuration_row":
        row = interference_row(
            "int:0099", ("cmp:0001", "cmp:0002"), "cmp:0001|cmp:0002|other", 1.0,
            configuration="Alternate",
        )
        checked.interferences.append(Interference.model_validate(row))
    current = _written_as_the_live_check_writes(tmp_path, checked)
    if changed == "respelled":
        (tmp_path / "package.json").write_bytes((tmp_path / "package.json").read_bytes() + b" ")
        current = load_package(tmp_path)

    result = assess_binding(anchor, baseline, current)

    if changed == "none":
        assert result.status == "matched_snapshot"
    else:
        assert result.status == "mismatch"
        assert result.reasons == ("package_digest_changed",)


def test_a_baseline_saved_before_107a_still_compares_exact_bytes(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    anchor = anchor_from_package(loaded, "anchor:1", "component", "cmp:0001")
    legacy = EvidenceBaseline.model_validate_json(
        baseline_from_package(loaded).model_dump_json(
            exclude={"without_live_interference_sha256"}
        )
    )
    assert "without_live_interference_sha256" not in legacy.model_dump(mode="json")
    assert assess_binding(anchor, legacy, loaded).status == "matched_snapshot"

    checked = _live_checked(tmp_path)

    assert assess_binding(anchor, legacy, checked).status == "mismatch"
