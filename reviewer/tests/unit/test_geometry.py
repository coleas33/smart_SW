"""Unit tests for the geometry helpers (T084).

Geometry is the deterministic half of US5: every distance a fastener or alignment check
reports comes from here, so the sign conventions and the "I cannot answer that" paths are
pinned before the checks are written (constitution Principles II and III).

Lengths in the IR are metres (SOLIDWORKS internal units); these helpers keep metres and
the checks convert through `swreview.units`.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import trimesh

from swreview.geometry.axis import axial_extent, axis_distance, face_gap, is_axis_aligned
from swreview.geometry.envelope import envelope_raycast
from swreview.geometry.mesh import load_mesh
from swreview.ir.models import (
    Axis,
    BBox3D,
    CylinderFace,
    FaceGeometry,
    PlaneFace,
    Vec3,
)
from tests.support.packages import persist_ref

# --- helpers ---------------------------------------------------------------------


def axis(origin: tuple[float, float, float], direction: tuple[float, float, float]) -> Axis:
    return Axis(
        origin=Vec3(x=origin[0], y=origin[1], z=origin[2]),
        direction=Vec3(x=direction[0], y=direction[1], z=direction[2]),
    )


def _face(
    face_id: str,
    *,
    kind: str,
    plane: PlaneFace | None,
    cylinder: CylinderFace | None,
) -> FaceGeometry:
    return FaceGeometry(
        id=face_id,
        persist_ref=persist_ref(face_id),
        persist_ref_scope="doc:2",
        component_id="cmp:0001",
        body_id="body:1",
        kind=kind,  # type: ignore[arg-type]
        cylinder=cylinder,
        plane=plane,
        bbox=BBox3D(
            min=Vec3(x=-0.01, y=-0.01, z=-0.01),
            max=Vec3(x=0.01, y=0.01, z=0.01),
        ),
        area_m2=None,
    )


def plane_face(
    origin: tuple[float, float, float],
    normal: tuple[float, float, float],
    face_id: str = "face:p",
) -> FaceGeometry:
    return _face(
        face_id,
        kind="plane",
        plane=PlaneFace(
            origin=Vec3(x=origin[0], y=origin[1], z=origin[2]),
            normal=Vec3(x=normal[0], y=normal[1], z=normal[2]),
        ),
        cylinder=None,
    )


def cylinder_face(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    radius_m: float,
    face_id: str = "face:c",
) -> FaceGeometry:
    return _face(
        face_id,
        kind="cylinder",
        plane=None,
        cylinder=CylinderFace(
            axis_origin=Vec3(x=origin[0], y=origin[1], z=origin[2]),
            axis_dir=Vec3(x=direction[0], y=direction[1], z=direction[2]),
            radius_m=radius_m,
        ),
    )


# --- axis_distance ---------------------------------------------------------------


def test_coincident_axes_report_zero_distance_and_zero_angle() -> None:
    relation = axis_distance(
        axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        axis((0.0, 0.0, 0.5), (0.0, 0.0, 2.0)),
    )

    assert relation.relation == "coincident"
    assert relation.distance_m == pytest.approx(0.0, abs=1e-12)
    assert relation.angle_rad == pytest.approx(0.0, abs=1e-12)


def test_antiparallel_axes_on_the_same_line_are_coincident() -> None:
    """Axis direction carries no sign meaning; a flipped direction is the same line."""
    relation = axis_distance(
        axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        axis((0.0, 0.0, 0.5), (0.0, 0.0, -1.0)),
    )

    assert relation.relation == "coincident"
    assert relation.angle_rad == pytest.approx(0.0, abs=1e-12)


def test_parallel_axes_report_the_perpendicular_distance() -> None:
    relation = axis_distance(
        axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        axis((0.003, 0.004, 7.0), (0.0, 0.0, 1.0)),
    )

    assert relation.relation == "parallel"
    assert relation.distance_m == pytest.approx(0.005, abs=1e-12)
    assert relation.angle_rad == pytest.approx(0.0, abs=1e-12)


def test_intersecting_axes_report_zero_distance_and_the_angle() -> None:
    relation = axis_distance(
        axis((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        axis((0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    )

    assert relation.relation == "intersecting"
    assert relation.distance_m == pytest.approx(0.0, abs=1e-12)
    assert relation.angle_rad == pytest.approx(math.pi / 2, abs=1e-12)


def test_skew_axes_report_the_closest_distance_and_the_angle() -> None:
    relation = axis_distance(
        axis((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        axis((0.0, 0.0, 0.002), (0.0, 1.0, 0.0)),
    )

    assert relation.relation == "skew"
    assert relation.distance_m == pytest.approx(0.002, abs=1e-12)
    assert relation.angle_rad == pytest.approx(math.pi / 2, abs=1e-12)


def test_angle_is_measured_between_lines_so_it_never_exceeds_ninety_degrees() -> None:
    relation = axis_distance(
        axis((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        axis((0.0, 0.0, 0.0), (-1.0, -1.0, 0.0)),
    )

    assert relation.angle_rad == pytest.approx(math.pi / 4, abs=1e-12)


def test_a_zero_length_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="direction"):
        axis_distance(
            axis((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        )


# --- face_gap --------------------------------------------------------------------


def test_face_gap_between_parallel_planes_is_signed_along_the_first_normal() -> None:
    a = plane_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "face:a")
    b = plane_face((0.0, 0.0, 0.002), (0.0, 0.0, 1.0), "face:b")

    gap = face_gap(a, b)

    assert gap.unit == "mm"
    assert gap.value == pytest.approx(2.0, abs=1e-9)


def test_face_gap_is_negative_when_the_second_plane_is_behind_the_first_normal() -> None:
    a = plane_face((0.0, 0.0, 0.002), (0.0, 0.0, 1.0), "face:a")
    b = plane_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "face:b")

    assert face_gap(a, b).value == pytest.approx(-2.0, abs=1e-9)


def test_face_gap_between_antiparallel_planes_still_resolves() -> None:
    a = plane_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "face:a")
    b = plane_face((0.0, 0.0, 0.002), (0.0, 0.0, -1.0), "face:b")

    assert face_gap(a, b).value == pytest.approx(2.0, abs=1e-9)


def test_face_gap_between_non_parallel_planes_is_unsupported() -> None:
    a = plane_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "face:a")
    b = plane_face((0.0, 0.0, 0.002), (0.0, 1.0, 0.0), "face:b")

    assert face_gap(a, b) == "unsupported"


def test_face_gap_between_coaxial_cylinders_is_the_radius_difference() -> None:
    bore = cylinder_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.0050, "face:bore")
    shaft = cylinder_face((0.0, 0.0, 0.020), (0.0, 0.0, 1.0), 0.0049, "face:shaft")

    gap = face_gap(bore, shaft)

    assert gap.unit == "mm"
    assert gap.value == pytest.approx(-0.1, abs=1e-9)


def test_face_gap_between_offset_cylinders_is_unsupported() -> None:
    bore = cylinder_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.005, "face:bore")
    shaft = cylinder_face((0.001, 0.0, 0.0), (0.0, 0.0, 1.0), 0.005, "face:shaft")

    assert face_gap(bore, shaft) == "unsupported"


def test_face_gap_between_a_plane_and_a_cylinder_is_unsupported() -> None:
    a = plane_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    b = cylinder_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.005)

    assert face_gap(a, b) == "unsupported"


def test_face_gap_for_a_face_kind_without_geometry_is_unsupported() -> None:
    cone = _face("face:cone", kind="cone", plane=None, cylinder=None)

    assert face_gap(cone, cone) == "unsupported"


def test_face_gap_for_a_plane_face_missing_its_plane_is_unsupported() -> None:
    broken = _face("face:broken", kind="plane", plane=None, cylinder=None)

    assert face_gap(broken, plane_face((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))) == "unsupported"


# --- load_mesh -------------------------------------------------------------------


def write_box(path: Path, extents_m: tuple[float, float, float]) -> Path:
    trimesh.creation.box(extents=extents_m).export(path)
    return path


def test_load_mesh_reads_a_glb_in_metres(tmp_path: Path) -> None:
    path = write_box(tmp_path / "body.glb", (0.010, 0.020, 0.030))

    mesh = load_mesh(path)

    assert mesh.extents == pytest.approx([0.010, 0.020, 0.030], abs=1e-9)


def test_load_mesh_refuses_an_stl_without_an_explicit_unit(tmp_path: Path) -> None:
    path = write_box(tmp_path / "body.stl", (10.0, 20.0, 30.0))

    with pytest.raises(ValueError, match="unit"):
        load_mesh(path)


def test_load_mesh_scales_an_stl_from_its_declared_unit(tmp_path: Path) -> None:
    path = write_box(tmp_path / "body.stl", (10.0, 20.0, 30.0))

    mesh = load_mesh(path, units="mm")

    assert mesh.extents == pytest.approx([0.010, 0.020, 0.030], abs=1e-9)


def test_load_mesh_scales_a_glb_when_a_unit_is_declared(tmp_path: Path) -> None:
    path = write_box(tmp_path / "body.glb", (10.0, 20.0, 30.0))

    mesh = load_mesh(path, units="mm")

    assert mesh.extents == pytest.approx([0.010, 0.020, 0.030], abs=1e-9)


def test_load_mesh_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_mesh(tmp_path / "absent.glb")


def test_load_mesh_refuses_an_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "body.step"
    path.write_text("not a mesh", encoding="utf-8")

    with pytest.raises(ValueError, match="glb"):
        load_mesh(path)


# --- envelope_raycast ------------------------------------------------------------

TOOL_AXIS = axis((0.0, 0.0, 0.010), (0.0, 0.0, 1.0))
"""Head plane at z = 10 mm, screw pointing +z into the hole; the tool arrives from -z."""


def obstruction(center_z_m: float, extent_m: float = 0.020) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=(extent_m, extent_m, extent_m))
    mesh.apply_translation((0.0, 0.0, center_z_m))
    return mesh


def test_envelope_raycast_reports_the_first_hit_on_a_blocking_body() -> None:
    # The box spans z in [-0.020, 0.000]; the rays start at z = 0.010 and travel -z.
    result = envelope_raycast(
        TOOL_AXIS,
        radius_m=0.005,
        length_m=0.050,
        meshes=[("cmp:0003", obstruction(-0.010))],
        use_embree=False,
    )

    assert result.unresolved == []
    assert [hit.component_id for hit in result.hits] == ["cmp:0003"]
    assert result.hits[0].first_hit_distance_m == pytest.approx(0.010, abs=1e-9)


def test_envelope_raycast_ignores_a_body_behind_the_head() -> None:
    """A body on the tip side of the head plane is not in the tool's way."""
    result = envelope_raycast(
        TOOL_AXIS,
        radius_m=0.005,
        length_m=0.050,
        meshes=[("cmp:0001", obstruction(0.040))],
        use_embree=False,
    )

    assert result.hits == []
    assert result.unresolved == []


def test_envelope_raycast_ignores_a_body_further_away_than_the_tool_length() -> None:
    result = envelope_raycast(
        TOOL_AXIS,
        radius_m=0.005,
        length_m=0.005,
        meshes=[("cmp:0003", obstruction(-0.010))],
        use_embree=False,
    )

    assert result.hits == []


def test_envelope_raycast_finds_a_body_that_only_the_ring_rays_reach() -> None:
    """A clamp beside the axis clears the centre ray but not the envelope circle."""
    mesh = trimesh.creation.box(extents=(0.004, 0.004, 0.004))
    mesh.apply_translation((0.006, 0.0, -0.010))

    result = envelope_raycast(
        TOOL_AXIS,
        radius_m=0.006,
        length_m=0.050,
        meshes=[("cmp:0003", mesh)],
        use_embree=False,
    )

    assert [hit.component_id for hit in result.hits] == ["cmp:0003"]


def test_envelope_raycast_reports_a_missing_mesh_as_unresolved() -> None:
    result = envelope_raycast(
        TOOL_AXIS,
        radius_m=0.005,
        length_m=0.050,
        meshes=[("cmp:0003", None)],
        use_embree=False,
    )

    assert result.hits == []
    assert result.unresolved == ["missing mesh for component cmp:0003"]


def test_envelope_raycast_rejects_a_non_positive_envelope() -> None:
    with pytest.raises(ValueError, match="radius_m"):
        envelope_raycast(TOOL_AXIS, radius_m=0.0, length_m=0.05, meshes=[], use_embree=False)
    with pytest.raises(ValueError, match="length_m"):
        envelope_raycast(TOOL_AXIS, radius_m=0.005, length_m=0.0, meshes=[], use_embree=False)


@pytest.mark.raycast
def test_envelope_raycast_with_embree_matches_the_pure_python_fallback() -> None:
    pytest.importorskip("embreex")
    meshes = [("cmp:0003", obstruction(-0.010))]

    with_embree = envelope_raycast(TOOL_AXIS, 0.005, 0.050, meshes, use_embree=True)
    fallback = envelope_raycast(TOOL_AXIS, 0.005, 0.050, meshes, use_embree=False)

    assert [hit.component_id for hit in with_embree.hits] == ["cmp:0003"]
    assert with_embree.hits[0].first_hit_distance_m == pytest.approx(
        fallback.hits[0].first_hit_distance_m, abs=1e-9
    )


def test_envelope_raycast_falls_back_when_embree_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`use_embree=None` picks embreex when it imports and the fallback when it does not."""
    from swreview.geometry import envelope

    monkeypatch.setattr(envelope, "embree_available", lambda: False)

    result = envelope_raycast(TOOL_AXIS, 0.005, 0.050, [("cmp:0003", obstruction(-0.010))])

    assert result.hits[0].first_hit_distance_m == pytest.approx(0.010, abs=1e-9)


# --- axial_extent and is_axis_aligned (feature 010 T006) ----------------------------------


def box(low: tuple[float, float, float], high: tuple[float, float, float]) -> BBox3D:
    return BBox3D(
        min=Vec3(x=low[0], y=low[1], z=low[2]), max=Vec3(x=high[0], y=high[1], z=high[2])
    )


def test_axial_extent_of_an_axis_aligned_box_is_exact_and_relative_to_the_origin() -> None:
    extent = axial_extent(
        [box((-0.01, -0.01, 0.002), (0.01, 0.01, 0.010))],
        axis((0.0, 0.0, 0.004), (0.0, 0.0, 1.0)),
    )

    assert extent == pytest.approx((-0.002, 0.006))


def test_axial_extent_spans_every_box_and_reads_a_reversed_axis_backwards() -> None:
    boxes = [
        box((0.0, 0.0, 0.0), (0.001, 0.001, 0.003)),
        box((0.0, 0.0, 0.007), (0.001, 0.001, 0.009)),
    ]

    assert axial_extent(boxes, axis((0.0, 0.0, 0.0), (0.0, 0.0, 2.0))) == pytest.approx(
        (0.0, 0.009)
    )
    assert axial_extent(boxes, axis((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))) == pytest.approx(
        (-0.009, 0.0)
    )


def test_axial_extent_projects_all_eight_corners_on_an_oblique_axis() -> None:
    """On an oblique axis the corners reach past the true extent - which is why a check that
    needs an exact length asks `is_axis_aligned` first (contracts/joint-map.md section 2)."""
    extent = axial_extent(
        [box((0.0, 0.0, 0.0), (0.001, 0.001, 0.001))], axis((0.0, 0.0, 0.0), (1.0, 1.0, 0.0))
    )

    assert extent == pytest.approx((0.0, math.sqrt(2.0) * 0.001))


def test_axial_extent_refuses_a_zero_length_direction_naming_it() -> None:
    with pytest.raises(ValueError, match="the probe axis"):
        axial_extent(
            [box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))],
            axis((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            what="the probe axis",
        )


def test_axial_extent_of_no_box_is_refused() -> None:
    with pytest.raises(ValueError, match="no box"):
        axial_extent([], axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))


@pytest.mark.parametrize(
    ("direction", "aligned"),
    [
        ((0.0, 0.0, 1.0), True),
        ((0.0, 0.0, -3.0), True),
        ((1.0, 0.0, 0.0), True),
        ((math.sin(math.radians(0.05)), 0.0, math.cos(math.radians(0.05))), True),
        ((math.sin(math.radians(0.5)), 0.0, math.cos(math.radians(0.5))), False),
        ((math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0))), False),
    ],
)
def test_is_axis_aligned_within_the_angle_of_a_coordinate_axis(
    direction: tuple[float, float, float], aligned: bool
) -> None:
    assert is_axis_aligned(Vec3(x=direction[0], y=direction[1], z=direction[2]), 0.1) is aligned


def test_is_axis_aligned_refuses_a_zero_length_direction() -> None:
    with pytest.raises(ValueError, match="zero-length"):
        is_axis_aligned(Vec3(x=0.0, y=0.0, z=0.0), 0.1)
