"""Unit tests for accepted interference exceptions (T063).

An exception is the one place the reviewer is allowed to stay quiet about a condition it
can see, so FR-013 and constitution Principle VI bind it to the geometry and the
configuration it was accepted for: the fingerprint must ignore the order SOLIDWORKS
happened to report components and faces in, and must change the moment a radius, a
transform or the configuration does. These tests pin both halves, plus the JSON file the
engineer keeps under version control.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore, ReviewException, fingerprint
from swreview.ir.models import (
    BBox3D,
    ComponentInstance,
    CylinderFace,
    Design,
    EvidencePackage,
    FaceGeometry,
    PlaneFace,
    Vec3,
)
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

ACCEPTED_AT = datetime(2026, 9, 12, 12, 30, 0, tzinfo=UTC)


def vec(x: float, y: float, z: float) -> Vec3:
    return Vec3(x=x, y=y, z=z)


def component(
    component_id: str, *, transform: list[list[float]] | None = None
) -> ComponentInstance:
    return ComponentInstance(
        id=component_id,
        persist_ref=persist_ref(component_id),
        persist_ref_scope="doc:1",
        name=component_id.replace("cmp:", "part-"),
        full_path=component_id.replace("cmp:", "part-") + "-1",
        document_id="doc:2",
        parent_id=None,
        referenced_configuration="Default",
        transform=IDENTITY_TRANSFORM if transform is None else transform,
        suppression="resolved",
        is_fixed=False,
        pattern_id=None,
        is_toolbox=False,
    )


def cylinder_face(face_id: str, component_id: str, radius_m: float) -> FaceGeometry:
    return FaceGeometry(
        id=face_id,
        persist_ref=persist_ref(face_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        body_id="bdy:1",
        kind="cylinder",
        cylinder=CylinderFace(
            axis_origin=vec(0.0, 0.0, 0.0), axis_dir=vec(0.0, 0.0, 1.0), radius_m=radius_m
        ),
        plane=None,
        bbox=BBox3D(min=vec(-0.01, -0.01, 0.0), max=vec(0.01, 0.01, 0.02)),
        area_m2=0.001,
    )


def plane_face(face_id: str, component_id: str, z: float = 0.0) -> FaceGeometry:
    return FaceGeometry(
        id=face_id,
        persist_ref=persist_ref(face_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        body_id="bdy:1",
        kind="plane",
        cylinder=None,
        plane=PlaneFace(origin=vec(0.0, 0.0, z), normal=vec(0.0, 0.0, 1.0)),
        bbox=BBox3D(min=vec(-0.01, -0.01, z), max=vec(0.01, 0.01, z)),
        area_m2=0.0004,
    )


def two_component_package(
    *,
    radius_m: float = 0.005,
    transform: list[list[float]] | None = None,
    configuration: str = "Default",
    reversed_order: bool = False,
) -> EvidencePackage:
    components = [component("cmp:0001", transform=transform), component("cmp:0002")]
    faces = [
        cylinder_face("fce:1", "cmp:0001", radius_m),
        plane_face("fce:2", "cmp:0001"),
        plane_face("fce:3", "cmp:0002", z=0.02),
    ]
    if reversed_order:
        components = list(reversed(components))
        faces = list(reversed(faces))
    return build_package(
        components=components,
        faces=faces,
        design=Design(
            design_id="dsn:1",
            name="cover-assy",
            root_assembly_document_id="doc:1",
            active_configuration=configuration,
            drawing_document_ids=[],
        ),
    )


class Group:
    """The smallest thing `accept` needs: a check, the components, a configuration."""

    def __init__(self, component_ids: list[str], configuration: str = "Default") -> None:
        self.check = "interference.static"
        self.component_ids = component_ids
        self.configuration = configuration


GROUP = Group(["cmp:0001", "cmp:0002"])


# --- fingerprint ----------------------------------------------------------------


def test_the_fingerprint_ignores_the_order_of_components_and_faces() -> None:
    forward = fingerprint(two_component_package(), ["cmp:0001", "cmp:0002"])
    backward = fingerprint(two_component_package(reversed_order=True), ["cmp:0002", "cmp:0001"])

    assert forward == backward


def test_the_fingerprint_is_a_sha256_hex_digest() -> None:
    value = fingerprint(two_component_package(), ["cmp:0001"])

    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def test_the_fingerprint_changes_when_a_cylinder_radius_changes() -> None:
    before = fingerprint(two_component_package(), ["cmp:0001", "cmp:0002"])
    after = fingerprint(two_component_package(radius_m=0.006), ["cmp:0001", "cmp:0002"])

    assert before != after


def test_the_fingerprint_changes_when_a_component_moves() -> None:
    moved = [list(row) for row in IDENTITY_TRANSFORM]
    moved[3][0] = 0.001
    before = fingerprint(two_component_package(), ["cmp:0001", "cmp:0002"])
    after = fingerprint(two_component_package(transform=moved), ["cmp:0001", "cmp:0002"])

    assert before != after


def test_a_move_below_one_nanometre_does_not_change_the_fingerprint() -> None:
    nudged = [list(row) for row in IDENTITY_TRANSFORM]
    nudged[3][0] = 1e-13
    before = fingerprint(two_component_package(), ["cmp:0001", "cmp:0002"])
    after = fingerprint(two_component_package(transform=nudged), ["cmp:0001", "cmp:0002"])

    assert before == after


def test_the_fingerprint_covers_only_the_named_components() -> None:
    one = fingerprint(two_component_package(), ["cmp:0001"])
    both = fingerprint(two_component_package(), ["cmp:0001", "cmp:0002"])

    assert one != both


def test_the_fingerprint_refuses_an_unknown_component() -> None:
    with pytest.raises(LookupError, match="cmp:9999"):
        fingerprint(two_component_package(), ["cmp:9999"])


def test_the_fingerprint_refuses_an_empty_component_list() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        fingerprint(two_component_package(), [])


# --- accepting ------------------------------------------------------------------


def test_accepting_binds_the_exception_to_the_component_persist_refs(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)

    accepted = store.accept(
        GROUP, package, by="engineer", note="intended press fit", at=ACCEPTED_AT
    )

    assert accepted.id == "EX-001"
    assert accepted.check == "interference.static"
    assert accepted.component_persist_refs == [
        persist_ref("cmp:0001"),
        persist_ref("cmp:0002"),
    ]
    assert accepted.persist_ref_scopes == ["doc:1", "doc:1"]
    assert accepted.configuration == "Default"
    assert accepted.status == "active"
    assert accepted.accepted_by == "engineer"
    assert accepted.accepted_at == ACCEPTED_AT
    assert accepted.geometry_fingerprint == fingerprint(package, ["cmp:0001", "cmp:0002"])


def test_accepting_twice_allocates_a_second_id(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)

    store.accept(GROUP, package, by="engineer", note="one", at=ACCEPTED_AT)
    second = store.accept(Group(["cmp:0001"]), package, by="engineer", note="two", at=ACCEPTED_AT)

    assert second.id == "EX-002"
    assert len(store.exceptions) == 2


# --- the file -------------------------------------------------------------------


def test_exceptions_json_round_trips(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    store.accept(GROUP, package, by="engineer", note="intended press fit", at=ACCEPTED_AT)
    store.save()

    reloaded = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME).load()

    assert reloaded.exceptions == store.exceptions


def test_a_directory_is_read_as_its_exceptions_file(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path)
    store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)
    store.save()

    assert (tmp_path / EXCEPTIONS_FILE_NAME).is_file()
    assert ExceptionStore(tmp_path).load().exceptions == store.exceptions


def test_loading_an_absent_file_gives_an_empty_store(tmp_path: Path) -> None:
    assert ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME).load().exceptions == []


def test_an_exception_can_be_rebuilt_from_its_json(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, package, by="engineer", note="n", at=ACCEPTED_AT)

    assert ReviewException(**accepted.model_dump()) == accepted


# --- matching -------------------------------------------------------------------


def test_matching_is_independent_of_the_order_of_the_component_ids(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, package, by="engineer", note="n", at=ACCEPTED_AT)

    matched = store.match(package, ["cmp:0002", "cmp:0001"], "Default")

    assert matched is accepted


def test_a_different_component_set_does_not_match(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    store.accept(GROUP, package, by="engineer", note="n", at=ACCEPTED_AT)

    assert store.match(package, ["cmp:0001"], "Default") is None


def test_a_different_configuration_does_not_match(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    store.accept(GROUP, package, by="engineer", note="n", at=ACCEPTED_AT)

    assert store.match(package, ["cmp:0001", "cmp:0002"], "Cold") is None


def test_a_needs_review_exception_still_matches(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, package, by="engineer", note="n", at=ACCEPTED_AT)
    accepted.status = "needs_review"

    assert store.match(package, ["cmp:0001", "cmp:0002"], "Default") is accepted


def test_a_retired_exception_never_matches(tmp_path: Path) -> None:
    package = two_component_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, package, by="engineer", note="n", at=ACCEPTED_AT)
    store.retire(accepted.id)

    assert store.match(package, ["cmp:0001", "cmp:0002"], "Default") is None


# --- refresh, re-accept, retire -------------------------------------------------


def test_refresh_leaves_an_unchanged_exception_active(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)

    assert store.refresh(two_component_package()) == []
    assert accepted.status == "active"


def test_refresh_flags_a_changed_radius_for_re_review(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)

    changed = store.refresh(two_component_package(radius_m=0.006))

    assert changed == [accepted]
    assert accepted.status == "needs_review"


def test_refresh_flags_a_changed_configuration_for_re_review(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)

    store.refresh(two_component_package(configuration="Cold"))

    assert accepted.status == "needs_review"


def test_refresh_flags_an_exception_whose_component_is_gone(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)

    store.refresh(build_package(components=[component("cmp:0001")], faces=[]))

    assert accepted.status == "needs_review"


def test_refresh_leaves_a_retired_exception_retired(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)
    store.retire(accepted.id)

    store.refresh(two_component_package(radius_m=0.006))

    assert accepted.status == "retired"


def test_reaccept_returns_a_flagged_exception_to_active(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)
    changed_package = two_component_package(radius_m=0.006)
    store.refresh(changed_package)

    reaccepted = store.reaccept(accepted.id, changed_package)

    assert reaccepted.status == "active"
    assert reaccepted.geometry_fingerprint == fingerprint(
        changed_package, ["cmp:0001", "cmp:0002"]
    )
    assert store.refresh(changed_package) == []


def test_reaccept_without_a_package_keeps_the_old_fingerprint(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(GROUP, two_component_package(), by="engineer", note="n", at=ACCEPTED_AT)
    original = accepted.geometry_fingerprint
    accepted.status = "needs_review"

    reaccepted = store.reaccept(accepted.id)

    assert reaccepted.status == "active"
    assert reaccepted.geometry_fingerprint == original


def test_an_unknown_id_cannot_be_retired(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="EX-404"):
        ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME).retire("EX-404")
