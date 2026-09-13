"""Unit tests for the fit and stack check tools (T081).

The two check tools are the first tools that write a numeric finding, so these tests pin
the three rules of contracts/agent-tools.md that make that safe:

- inputs are `SourceRef`s resolved against the package, never numbers typed by the model;
- the `CheckResult` of the deterministic check becomes a `Finding` with provenance, and
  the finding is appended to the session and returned;
- anything the tool cannot resolve - an unknown reference, an ambiguous one, an angle
  where a length belongs - comes back as an error result, never as an exception past the
  registry and never as a number (FR-022).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from anthropic.lib.tools import ToolError

from swreview.ir.models import (
    Angle,
    Dimension,
    Document,
    DrawingSheet,
    EvidencePackage,
    Manifest,
    ManifestEntry,
    Quantity,
    SheetView,
    SourceRef,
    Tolerance,
)
from swreview.tools import checks_fit
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.registry import RecordedTool, ToolRegistry
from tests.support.packages import build_manifest

MakePackage = Callable[..., EvidencePackage]

DRAWING = "doc:3"
SHEET = "Sheet1"


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


def source(annotation: str) -> SourceRef:
    return SourceRef(document_id=DRAWING, sheet=SHEET, annotation=annotation)


def ref(annotation: str, document_id: str = DRAWING, sheet: str = SHEET) -> dict[str, str]:
    """The JSON form of a `SourceRef`, as the model would send it."""
    return {"document_id": document_id, "sheet": sheet, "annotation": annotation}


def dimension(
    annotation: str,
    nominal: Quantity | Angle,
    tolerance: Tolerance,
    text: str,
) -> Dimension:
    return Dimension(
        nominal=nominal,
        tolerance=tolerance,
        source=source(annotation),
        text_as_read=text,
    )


def bilateral(annotation: str, upper: float, lower: float) -> Tolerance:
    return Tolerance(kind="bilateral", upper=mm(upper), lower=mm(lower), source=source(annotation))


def symmetric(annotation: str, half_width: float) -> Tolerance:
    return Tolerance(
        kind="symmetric", upper=mm(half_width), lower=mm(half_width), source=source(annotation)
    )


def untoleranced(annotation: str) -> Tolerance:
    return Tolerance(kind="none", upper=None, lower=None, source=source(annotation))


DIMENSIONS: list[Dimension] = [
    # A 40 H7 bore over a 40 g6 shaft: 0.009 mm to 0.05 mm diametral clearance.
    dimension("DIM-BORE", mm(40.0), bilateral("DIM-BORE", 0.025, 0.0), "40 +0.025/0"),
    dimension("DIM-SHAFT", mm(40.0), bilateral("DIM-SHAFT", -0.009, -0.025), "40 -0.009/-0.025"),
    # A stack that reaches outside its target gap: 10 +/- 0.1 less 4 +/- 0.05 against 6 +/- 0.1.
    dimension("DIM-A", mm(10.0), symmetric("DIM-A", 0.1), "10 +/-0.1"),
    dimension("DIM-B", mm(4.0), symmetric("DIM-B", 0.05), "4 +/-0.05"),
    dimension("DIM-GAP", mm(6.0), symmetric("DIM-GAP", 0.1), "6 +/-0.1"),
    dimension("DIM-UNTOL", mm(4.0), untoleranced("DIM-UNTOL"), "4"),
    dimension(
        "DIM-ANGLE",
        Angle(value=45.0, unit="deg"),
        Tolerance(
            kind="symmetric",
            upper=Angle(value=0.5, unit="deg"),
            lower=Angle(value=0.5, unit="deg"),
            source=source("DIM-ANGLE"),
        ),
        "45deg +/-0.5deg",
    ),
    # Two dimensions at one annotation: a reference that names both is ambiguous.
    dimension("DIM-DUP", mm(8.0), symmetric("DIM-DUP", 0.1), "8 +/-0.1 (a)"),
    dimension("DIM-DUP", mm(9.0), symmetric("DIM-DUP", 0.1), "9 +/-0.1 (b)"),
]


def drawing_package(make_package: MakePackage) -> EvidencePackage:
    """`make_package` plus one drawing sheet carrying every dimension these tests use."""
    documents = [
        *make_package().documents,
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
            *build_manifest().entries,
            ManifestEntry(
                document_id=DRAWING,
                vault_path="/Designs/housing.SLDDRW",
                vault_version=3,
                revision="A",
                configuration="Default",
                local_modified=False,
                export_method="pdf",
            ),
        ],
        discrepancies=[],
    )
    sheet = DrawingSheet(
        document_id=DRAWING,
        sheet_name=SHEET,
        page=1,
        scale="1:1",
        units="mm",
        general_notes=[],
        dimensions=DIMENSIONS,
        views=[SheetView(name="SECTION A-A", bbox=[0.0, 0.0, 100.0, 100.0])],
        parse_status="text",
        parser="pymupdf",
    )
    return make_package(documents=documents, manifest=manifest, drawings=[sheet])


@pytest.fixture
def context(make_package: MakePackage) -> Iterator[ToolContext]:
    """A package with drawing dimensions, behind the contextvar the tools read."""
    tool_context = context_for(drawing_package(make_package))
    with use_context(tool_context):
        yield tool_context


def recorded(context: ToolContext, name: str) -> RecordedTool:
    """The registry-built tool called `name`, bound to `context`."""
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


# --- check_fit -------------------------------------------------------------------


def test_check_fit_returns_a_finding_and_appends_it_to_the_session(
    context: ToolContext,
) -> None:
    result = checks_fit.check_fit(ref("DIM-BORE"), ref("DIM-SHAFT"))

    assert result["status"] == "recorded"
    finding = result["finding"]
    assert finding["check"] == "fit.size_only"
    assert finding["id"] == "F-001"
    assert finding["status"] == "checked_within_scope"
    assert finding["calculation"]["result"]["fit_class"] == "clearance"
    assert finding["calculation"]["result"]["min_clearance_mm"] == 0.009
    assert finding["calculation"]["result"]["max_clearance_mm"] == 0.05
    assert [location["annotation"] for location in finding["drawing_locations"]] == [
        "DIM-BORE",
        "DIM-SHAFT",
    ]
    assert [entry["document_id"] for entry in finding["provenance"]] == [DRAWING]
    assert finding["coverage_limits"]
    assert [item.id for item in context.session.findings] == ["F-001"]


def test_check_fit_is_registered_and_records_a_step(context: ToolContext) -> None:
    tool = recorded(context, "check_fit")

    payload = json.loads(
        tool.call({"bore_dimension_ref": ref("DIM-BORE"), "shaft_dimension_ref": ref("DIM-SHAFT")})
    )

    assert payload["finding"]["check"] == "fit.size_only"
    step = context.session.steps[0]
    assert step.tool == "check_fit"
    assert step.status == "ok"
    assert step.arguments["bore_dimension_ref"]["annotation"] == "DIM-BORE"
    assert step.error is None


def test_an_unknown_reference_is_an_error_result(context: ToolContext) -> None:
    result = checks_fit.check_fit(ref("DIM-NOWHERE"), ref("DIM-SHAFT"))

    assert "no drawing dimension at" in result["error"]
    assert context.session.findings == []


def test_an_ambiguous_reference_is_an_error_result(context: ToolContext) -> None:
    result = checks_fit.check_fit(ref("DIM-BORE"), ref("DIM-DUP"))

    assert "ambiguous" in result["error"]
    assert context.session.findings == []


def test_an_unknown_reference_through_the_registry_is_failed_coverage(
    context: ToolContext,
) -> None:
    tool = recorded(context, "check_fit")

    with pytest.raises(ToolError) as caught:
        tool.call(
            {"bore_dimension_ref": ref("DIM-NOWHERE"), "shaft_dimension_ref": ref("DIM-SHAFT")}
        )

    assert "no drawing dimension at" in json.loads(caught.value.content)["error"]
    assert [item.check for item in context.session.coverage.failed] == ["tool.check_fit"]
    assert context.session.steps[0].status == "error"


def test_a_missing_tolerance_is_an_unresolved_finding_not_a_default(
    context: ToolContext,
) -> None:
    result = checks_fit.check_fit(ref("DIM-BORE"), ref("DIM-UNTOL"))

    finding = result["finding"]
    assert finding["status"] == "unresolved"
    assert finding["calculation"] is None
    assert "'4'" in finding["observed"]
    assert finding["coverage_limits"]


def test_an_angle_where_a_length_belongs_is_an_error_result(context: ToolContext) -> None:
    result = checks_fit.check_fit(ref("DIM-ANGLE"), ref("DIM-SHAFT"))

    assert "TypeError" in result["error"]
    assert "angle" in result["error"]
    assert context.session.findings == []


# --- check_axial_stack -----------------------------------------------------------


def test_check_axial_stack_returns_a_finding_against_the_target_gap(
    context: ToolContext,
) -> None:
    result = checks_fit.check_axial_stack([ref("DIM-A"), ref("DIM-B")], [1, -1], ref("DIM-GAP"))

    finding = result["finding"]
    assert finding["check"] == "stack.worst_case"
    assert finding["status"] == "demonstrated"
    assert finding["severity"] == "high"
    assert finding["calculation"]["result"]["violates_target"] is True
    assert finding["calculation"]["result"]["min_mm"] == 5.85
    assert finding["calculation"]["result"]["max_mm"] == 6.15
    assert [location["annotation"] for location in finding["drawing_locations"]] == [
        "DIM-A",
        "DIM-B",
        "DIM-GAP",
    ]
    assert [item.id for item in context.session.findings] == ["F-001"]


def test_check_axial_stack_without_a_target_reports_the_band(context: ToolContext) -> None:
    result = checks_fit.check_axial_stack([ref("DIM-A"), ref("DIM-B")], [1, -1])

    finding = result["finding"]
    assert finding["status"] == "checked_within_scope"
    assert [location["annotation"] for location in finding["drawing_locations"]] == [
        "DIM-A",
        "DIM-B",
    ]


def test_check_axial_stack_is_registered_and_records_a_step(context: ToolContext) -> None:
    tool = recorded(context, "check_axial_stack")

    payload = json.loads(
        tool.call(
            {
                "dimension_refs": [ref("DIM-A"), ref("DIM-B")],
                "signs": [1, -1],
                "target_gap": ref("DIM-GAP"),
            }
        )
    )

    assert payload["finding"]["check"] == "stack.worst_case"
    assert [step.tool for step in context.session.steps] == ["check_axial_stack"]


def test_a_sign_per_dimension_is_required(context: ToolContext) -> None:
    result = checks_fit.check_axial_stack([ref("DIM-A"), ref("DIM-B")], [1])

    assert "one sign each" in result["error"]
    assert context.session.findings == []


def test_an_untoleranced_contributor_makes_the_stack_unresolved(
    context: ToolContext,
) -> None:
    result = checks_fit.check_axial_stack([ref("DIM-A"), ref("DIM-UNTOL")], [1, -1])

    finding = result["finding"]
    assert finding["status"] == "unresolved"
    assert "'4'" in finding["observed"]
    assert finding["coverage_limits"]


def test_an_unknown_target_gap_is_an_error_result(context: ToolContext) -> None:
    result = checks_fit.check_axial_stack([ref("DIM-A")], [1], ref("DIM-NOWHERE"))

    assert "no drawing dimension at" in result["error"]
    assert context.session.findings == []


# --- references only, never raw numbers ------------------------------------------


def tool_schema(context: ToolContext, name: str) -> dict[str, Any]:
    return recorded(context, name).to_dict()["input_schema"]


def test_the_check_tools_accept_only_references_and_signs(context: ToolContext) -> None:
    fit_schema = tool_schema(context, "check_fit")
    stack_schema = tool_schema(context, "check_axial_stack")

    assert set(fit_schema["properties"]) == {"bore_dimension_ref", "shaft_dimension_ref"}
    assert set(stack_schema["properties"]) == {"dimension_refs", "signs", "target_gap"}
    assert fit_schema["additionalProperties"] is False
    assert stack_schema["additionalProperties"] is False

    # Every reference is a SourceRef: locators only, no size, diameter or tolerance.
    locators = set(SourceRef.model_fields)
    for schema in (fit_schema, stack_schema):
        assert set(schema["$defs"]["SourceRef"]["properties"]) == locators
    assert not locators & {"value", "nominal", "diameter", "tolerance"}


def test_a_raw_number_instead_of_a_reference_is_refused(context: ToolContext) -> None:
    tool = recorded(context, "check_fit")

    with pytest.raises(ToolError) as caught:
        tool.call({"bore_dimension_ref": 40.0, "shaft_dimension_ref": 39.98})

    assert "error" in json.loads(caught.value.content)
    assert context.session.findings == []


def test_a_number_smuggled_into_a_reference_is_refused(context: ToolContext) -> None:
    tool = recorded(context, "check_fit")

    with pytest.raises(ToolError):
        tool.call(
            {
                "bore_dimension_ref": {**ref("DIM-BORE"), "diameter_mm": 40.0},
                "shaft_dimension_ref": ref("DIM-SHAFT"),
            }
        )

    assert context.session.findings == []
