"""Unit tests for the fastener and hole-alignment check tools (T090).

Two rows of the "Check tools" table in contracts/agent-tools.md. The deterministic checks
behind them are already covered by `test_checks_fastener.py` and
`test_checks_hole_alignment.py`; what these tests pin is the tool layer's job, which is
resolving ids into the entities those checks need without inventing anything:

- the thickness of a clamped layer comes from the `Thickness` custom property, else from
  the component's extracted bounding box along the fastener axis, else it is `None` and
  the joint stays unresolved naming that component (constitution Principle I);
- washers are found by geometry - a `washer` fastener coaxial with this one - not by
  being told about them;
- a joint kind the pilot does not model is `out_of_scope` coverage, never a finding and
  never a pass (FR-024).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from swreview.ir.models import (
    Axis,
    BBox3D,
    ComponentInstance,
    Dimension,
    Document,
    DrawingSheet,
    EvidencePackage,
    FaceGeometry,
    Fastener,
    Hole,
    Manifest,
    ManifestEntry,
    PlaneFace,
    Quantity,
    SourceRef,
    Tolerance,
    Vec3,
)
from swreview.tools import checks_fastener
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.registry import RecordedTool, ToolRegistry
from tests.support.packages import IDENTITY_TRANSFORM, persist_ref

MakePackage = Callable[..., EvidencePackage]

DRAWING = "doc:9"
SHEET = "Sheet1"


def vec(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Vec3:
    return Vec3(x=x, y=y, z=z)


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


# The joint axis: the head sits at z = 20 mm and the screw points down into the housing.
DOWN = Axis(origin=vec(z=0.02), direction=vec(z=-1.0))
OFF_AXIS = Axis(origin=vec(x=0.05, z=0.02), direction=vec(z=-1.0))


def document(document_id: str, properties: dict[str, str], material: str | None) -> Document:
    return Document(
        document_id=document_id,
        kind="part",
        file_name=f"{document_id.replace(':', '-')}.SLDPRT",
        path=f"native/{document_id.replace(':', '-')}.SLDPRT",
        configurations=["Default"],
        active_configuration="Default",
        custom_properties=properties,
        config_properties={},
        material=material,
        mass=None,
    )


def entry(document_id: str) -> ManifestEntry:
    return ManifestEntry(
        document_id=document_id,
        vault_path=f"/Designs/{document_id}.SLDPRT",
        vault_version=1,
        revision="A",
        configuration="Default",
        local_modified=False,
        export_method="native",
    )


def component(component_id: str, name: str, document_id: str) -> ComponentInstance:
    return ComponentInstance(
        id=component_id,
        persist_ref=persist_ref(component_id),
        persist_ref_scope="doc:1",
        name=name,
        full_path=name,
        document_id=document_id,
        parent_id=None,
        referenced_configuration="Default",
        transform=IDENTITY_TRANSFORM,
        suppression="resolved",
        is_fixed=False,
        pattern_id=None,
        is_toolbox=False,
    )


def slab_face(face_id: str, component_id: str, low_z_m: float, high_z_m: float) -> FaceGeometry:
    """A face whose world bounding box spans the component's thickness along z."""
    return FaceGeometry(
        id=face_id,
        persist_ref=persist_ref(face_id),
        persist_ref_scope="doc:2",
        component_id=component_id,
        body_id=f"bod:{face_id}",
        kind="plane",
        cylinder=None,
        plane=PlaneFace(origin=vec(z=low_z_m), normal=vec(z=1.0)),
        bbox=BBox3D(min=vec(-0.05, -0.05, low_z_m), max=vec(0.05, 0.05, high_z_m)),
        area_m2=0.01,
    )


def tapped_hole(hole_id: str, thread_depth: Quantity | None) -> Hole:
    return Hole(
        id=hole_id,
        persist_ref=persist_ref(hole_id),
        persist_ref_scope="doc:2",
        component_id="cmp:0001",
        feature_name="M6 Tapped Hole1",
        hole_type="tapped",
        standard="ISO",
        size="M6",
        thread_designation="M6x1.0",
        thread_depth=thread_depth,
        hole_depth=mm(14.0),
        end_condition="blind",
        diameter=mm(5.0),
        axis=DOWN,
        face_ids=[],
    )


def fastener(
    fastener_id: str,
    kind: str,
    component_id: str,
    fastener_axis: Axis,
    length: Quantity | None,
    designation: str | None = "M6x1.0",
) -> Fastener:
    return Fastener(
        id=fastener_id,
        persist_ref=persist_ref(fastener_id),
        persist_ref_scope="doc:1",
        component_id=component_id,
        kind=kind,  # type: ignore[arg-type]
        identity_source="toolbox",
        thread_designation=designation,
        length=length,
        head_type="socket head cap",
        head_diameter=mm(10.0),
        head_height=mm(6.0),
        drive="hex",
        axis=fastener_axis,
        material=None,
    )


TOLERANCE_DIMENSION = Dimension(
    nominal=mm(0.2),
    tolerance=Tolerance(
        kind="none",
        upper=None,
        lower=None,
        source=SourceRef(document_id=DRAWING, sheet=SHEET, annotation="dim-1-1"),
    ),
    source=SourceRef(document_id=DRAWING, sheet=SHEET, annotation="dim-1-1"),
    text_as_read="0.2",
)


def joint_package(make_package: MakePackage) -> EvidencePackage:
    """A tapped housing, a cover with a stated thickness, a spacer with only a box."""
    base = make_package()
    documents = [
        *base.documents,
        document("doc:3", {"Thickness": "8.0"}, "6061-T6"),
        document("doc:4", {}, "Steel, Alloy"),
        document("doc:5", {}, "6061-T6"),
        document("doc:6", {}, "6061-T6"),
        Document(
            document_id=DRAWING,
            kind="drawing",
            file_name="housing.SLDDRW",
            path="pdf/housing.pdf",
            configurations=["Default"],
            active_configuration="Default",
            custom_properties={},
            config_properties={},
            material=None,
            mass=None,
        ),
    ]
    manifest = Manifest(
        entries=[
            *base.manifest.entries,
            *(entry(document_id) for document_id in ("doc:3", "doc:4", "doc:5", "doc:6")),
            entry(DRAWING),
        ],
        discrepancies=[],
    )
    components = [
        *base.components,
        component("cmp:0003", "cover-1", "doc:3"),
        component("cmp:0004", "screw-1", "doc:4"),
        component("cmp:0005", "plate-1", "doc:5"),
        component("cmp:0006", "spacer-1", "doc:6"),
    ]
    sheet = DrawingSheet(
        document_id=DRAWING,
        sheet_name=SHEET,
        page=1,
        scale="1:1",
        units="mm",
        general_notes=[],
        dimensions=[TOLERANCE_DIMENSION],
        views=[],
        parse_status="text",
        parser="pymupdf",
    )
    return make_package(
        documents=documents,
        manifest=manifest,
        components=components,
        drawings=[sheet],
        holes=[
            tapped_hole("hole:tapped", mm(12.0)),
            tapped_hole("hole:unknown-depth", None),
            Hole(
                id="hole:far",
                persist_ref=persist_ref("hole:far"),
                persist_ref_scope="doc:2",
                component_id="cmp:0003",
                feature_name="Clearance1",
                hole_type="clearance",
                standard=None,
                size=None,
                thread_designation=None,
                thread_depth=None,
                hole_depth=mm(8.0),
                end_condition="through",
                diameter=mm(6.6),
                axis=OFF_AXIS,
                face_ids=[],
            ),
        ],
        faces=[
            # The spacer: 1.5 mm thick along the joint axis, and nothing states it.
            slab_face("face:spacer", "cmp:0006", 0.0, 0.0015),
        ],
        fasteners=[
            fastener("fst:screw", "screw", "cmp:0004", DOWN, mm(20.0)),
            fastener("fst:washer", "washer", "cmp:0004", DOWN, mm(1.6)),
            fastener("fst:washer-thin", "washer", "cmp:0004", OFF_AXIS, mm(1.0)),
            fastener("fst:pin", "pin", "cmp:0004", DOWN, mm(20.0)),
            fastener("fst:no-length", "screw", "cmp:0004", OFF_AXIS, None),
        ],
    )


@pytest.fixture
def context(make_package: MakePackage) -> Iterator[ToolContext]:
    tool_context = context_for(joint_package(make_package))
    with use_context(tool_context):
        yield tool_context


def recorded(context: ToolContext, name: str) -> RecordedTool:
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


def by_check(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {finding["check"]: finding for finding in result["findings"]}


# --- check_fastener_joint ---------------------------------------------------------


def test_the_joint_produces_one_finding_per_check(context: ToolContext) -> None:
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0003"])

    assert result["status"] == "recorded"
    assert set(by_check(result)) == {
        "fastener.bottoming",
        "fastener.engagement",
        "fastener.thread_match",
        "fastener.head_clearance",
    }
    assert [item.id for item in context.session.findings] == ["F-001", "F-002", "F-003", "F-004"]


def test_a_stated_thickness_property_is_the_clamped_layer(context: ToolContext) -> None:
    """Cover 8 mm plus a 1.6 mm washer: the screw protrudes 10.4 mm into 12 mm of thread."""
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0003"])

    bottoming = by_check(result)["fastener.bottoming"]
    assert bottoming["status"] == "checked_within_scope"
    assert bottoming["calculation"]["result"]["protrusion_mm"] == pytest.approx(10.4)
    assert bottoming["calculation"]["result"]["margin_mm"] == pytest.approx(1.6)
    assert bottoming["calculation"]["inputs"]["clamped_0_cmp:0003_mm"]["value"] == 8.0


def test_the_thickness_source_is_reported(context: ToolContext) -> None:
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0003"])

    assert result["clamped"] == [
        {
            "component_id": "cmp:0003",
            "thickness": {"value": 8.0, "unit": "mm"},
            "source": "Thickness custom property of document doc:3",
        }
    ]


def test_a_component_with_no_property_falls_back_to_its_bounding_box(
    context: ToolContext,
) -> None:
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0006"])

    layer = result["clamped"][0]
    assert layer["thickness"]["value"] == pytest.approx(1.5)
    assert "bounding box" in layer["source"]


def test_a_component_with_neither_leaves_the_joint_unresolved(context: ToolContext) -> None:
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0005"])

    assert result["clamped"][0]["thickness"] is None
    bottoming = by_check(result)["fastener.bottoming"]
    assert bottoming["status"] == "unresolved"
    assert "cmp:0005" in bottoming["observed"]


def test_a_coaxial_washer_is_found_and_an_off_axis_one_is_not(context: ToolContext) -> None:
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0003"])

    assert [washer["fastener_id"] for washer in result["washers"]] == ["fst:washer"]
    assert result["washers"][0]["thickness"] == {"value": 1.6, "unit": "mm"}


def test_the_hole_material_comes_from_the_tapped_component(context: ToolContext) -> None:
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0003"])

    engagement = by_check(result)["fastener.engagement"]
    assert engagement["calculation"]["inputs"]["hole_material"] == "6061-T6"
    assert engagement["calculation"]["inputs"]["material_class"] == "aluminum"
    assert result["hole_material"] == "6061-T6"


def test_an_unknown_thread_depth_is_never_cleared(context: ToolContext) -> None:
    result = checks_fastener.check_fastener_joint(
        "fst:screw", "hole:unknown-depth", ["cmp:0003"]
    )

    findings = by_check(result)
    assert findings["fastener.bottoming"]["status"] == "unresolved"
    assert "usable thread depth" in findings["fastener.bottoming"]["observed"]
    assert findings["fastener.engagement"]["status"] == "unresolved"


def test_an_unsupported_joint_kind_is_out_of_scope_coverage_not_a_finding(
    context: ToolContext,
) -> None:
    result = checks_fastener.check_fastener_joint("fst:pin", "hole:tapped", ["cmp:0003"])

    assert result["status"] == "out_of_scope"
    assert context.session.findings == []
    item = context.session.coverage.out_of_scope[0]
    assert item.check == "fastener.unsupported"
    assert "pin" in item.reason
    assert "cmp:0004" in item.scope.component_ids


def test_head_clearance_is_unresolved_without_a_tool_envelope(context: ToolContext) -> None:
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:0003"])

    head = by_check(result)["fastener.head_clearance"]
    assert head["status"] == "unresolved"
    assert "envelope raycast" in head["recommended_action"]
    assert head["coverage_limits"]


def test_unknown_ids_are_error_results(context: ToolContext) -> None:
    assert checks_fastener.check_fastener_joint("fst:nope", "hole:tapped", []) == {
        "error": "unknown fastener id 'fst:nope'"
    }
    assert checks_fastener.check_fastener_joint("fst:screw", "hole:nope", []) == {
        "error": "unknown hole id 'hole:nope'"
    }
    result = checks_fastener.check_fastener_joint("fst:screw", "hole:tapped", ["cmp:9999"])
    assert "cmp:9999" in result["error"]
    assert context.session.findings == []


def test_check_fastener_joint_is_registered_and_records_a_step(context: ToolContext) -> None:
    tool = recorded(context, "check_fastener_joint")

    payload = tool.call(
        {
            "fastener_id": "fst:screw",
            "hole_id": "hole:tapped",
            "clamped_component_ids": ["cmp:0003"],
        }
    ).payload

    assert len(payload["findings"]) == 4
    assert [step.tool for step in context.session.steps] == ["check_fastener_joint"]


def test_an_unknown_id_through_the_registry_is_failed_coverage(context: ToolContext) -> None:
    tool = recorded(context, "check_fastener_joint")

    result = tool.call(
        {"fastener_id": "fst:nope", "hole_id": "hole:tapped", "clamped_component_ids": []}
    )

    assert result.is_error is True

    assert [item.check for item in context.session.coverage.failed] == [
        "tool.check_fastener_joint"
    ]


# --- check_hole_alignment ---------------------------------------------------------


def test_hole_alignment_against_a_drawn_tolerance(context: ToolContext) -> None:
    result = checks_fastener.check_hole_alignment(
        "hole:tapped",
        "hole:far",
        {"document_id": DRAWING, "sheet": SHEET, "annotation": "dim-1-1"},
    )

    finding = result["finding"]
    assert finding["check"] == "hole.coaxiality"
    assert finding["status"] == "demonstrated"
    assert finding["calculation"]["result"]["offset_mm"] == pytest.approx(50.0)
    assert finding["calculation"]["result"]["tolerance_mm"] == 0.2
    assert [location["annotation"] for location in finding["drawing_locations"]] == ["dim-1-1"]
    assert sorted(finding["component_ids"]) == ["cmp:0001", "cmp:0003"]


def test_hole_alignment_without_a_tolerance_is_unresolved(context: ToolContext) -> None:
    result = checks_fastener.check_hole_alignment("hole:tapped", "hole:far", None)

    finding = result["finding"]
    assert finding["status"] == "unresolved"
    assert finding["calculation"]["result"]["offset_mm"] == pytest.approx(50.0)
    assert finding["coverage_limits"]


def test_hole_alignment_rejects_an_unknown_hole(context: ToolContext) -> None:
    assert checks_fastener.check_hole_alignment("hole:tapped", "hole:nope", None) == {
        "error": "unknown hole id 'hole:nope'"
    }


def test_hole_alignment_rejects_an_unknown_tolerance_reference(context: ToolContext) -> None:
    result = checks_fastener.check_hole_alignment(
        "hole:tapped",
        "hole:far",
        {"document_id": DRAWING, "sheet": SHEET, "annotation": "dim-9-9"},
    )

    assert "no drawing dimension at" in result["error"]
    assert context.session.findings == []


def test_check_hole_alignment_is_registered_and_records_a_step(context: ToolContext) -> None:
    tool = recorded(context, "check_hole_alignment")

    payload = tool.call(
        {"hole_id_a": "hole:tapped", "hole_id_b": "hole:far", "tolerance": None}
    ).payload

    assert payload["finding"]["check"] == "hole.coaxiality"
    assert [step.tool for step in context.session.steps] == ["check_hole_alignment"]
