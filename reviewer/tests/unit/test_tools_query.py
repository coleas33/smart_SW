"""Unit tests for the package query tools (T027).

One test per row of the "Package query tools" table in contracts/agent-tools.md, plus the
two rules that hold across all of them: an unknown id comes back as an error result
rather than an exception, and an unknown usable thread depth is labelled, never filled in
from the drill depth (constitution Principle I).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from swreview.ir.models import (
    Dimension,
    Discrepancy,
    Document,
    DrawingSheet,
    EvidencePackage,
    Gap,
    Interference,
    InterferenceSettings,
    Manifest,
    ManifestEntry,
    Mate,
    MateEntity,
    Note,
    Quantity,
    SheetView,
    SourceRef,
    Tolerance,
)
from swreview.tools import query
from swreview.tools.context import ToolContext, context_for, use_context
from tests.support.packages import build_manifest, persist_ref

MakePackage = Callable[..., EvidencePackage]


@pytest.fixture
def context(make_package: MakePackage) -> Iterator[ToolContext]:
    """`make_package` behind the contextvar the tools read."""
    tool_context = context_for(make_package())
    with use_context(tool_context):
        yield tool_context


def drawing_package(make_package: MakePackage) -> EvidencePackage:
    """`make_package` plus a readable drawing sheet and an unreadable one."""
    package = make_package()
    documents = [
        *package.documents,
        Document(
            document_id="doc:3",
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
                document_id="doc:3",
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
    source = SourceRef(document_id="doc:3", sheet="Sheet1", page=1, bbox=[10.0, 10.0, 40.0, 20.0])
    sheets = [
        DrawingSheet(
            document_id="doc:3",
            sheet_name="Sheet1",
            page=1,
            scale="1:1",
            units="mm",
            general_notes=[
                Note(
                    text="UNLESS OTHERWISE SPECIFIED: .X +/- 0.5",
                    source=SourceRef(document_id="doc:3", sheet="Sheet1"),
                    kind="general_tolerance",
                )
            ],
            dimensions=[
                Dimension(
                    nominal=Quantity(value=10.0, unit="mm"),
                    tolerance=Tolerance(
                        kind="symmetric",
                        upper=Quantity(value=0.02, unit="mm"),
                        lower=Quantity(value=0.02, unit="mm"),
                        source=source,
                    ),
                    source=source,
                    text_as_read="Ø10.00 ±0.02",
                )
            ],
            views=[SheetView(name="SECTION A-A", bbox=[0.0, 0.0, 100.0, 100.0])],
            parse_status="text",
            parser="pymupdf",
        ),
        DrawingSheet(
            document_id="doc:3",
            sheet_name="Sheet2",
            page=2,
            scale=None,
            units="unknown",
            general_notes=[],
            dimensions=[],
            views=[],
            parse_status="no_text",
            parser="pymupdf",
        ),
    ]
    gaps = [
        *package.gaps,
        Gap(
            kind="no_text",
            entity_kind="drawing_sheet",
            entity_id="Sheet2",
            reason="page 2 carries no text layer; it is a flattened image",
            error=None,
        ),
    ]
    return make_package(documents=documents, manifest=manifest, drawings=sheets, gaps=gaps)


def interference_package(make_package: MakePackage) -> EvidencePackage:
    settings = InterferenceSettings(
        treat_coincident_as_interference=False,
        treat_subassemblies_as_components=True,
        include_multibody=False,
        ignore_hidden=True,
        fastener_folder_treatment="include",
    )
    return make_package(
        interferences=[
            Interference(
                id="int:1",
                configuration="Default",
                component_ids=["cmp:0001", "cmp:0002"],
                volume=None,
                settings=settings,
                status="truncated",
                error="result list truncated at 100 pairs",
                group_key="housing/housing",
                is_fastener=False,
                is_possible=True,
            )
        ]
    )


def mate_package(make_package: MakePackage) -> EvidencePackage:
    return make_package(
        mates=[
            Mate(
                id="mate:1",
                persist_ref=persist_ref("mate:1"),
                persist_ref_scope="doc:1",
                type="Concentric",
                entities=[
                    MateEntity(
                        component_id="cmp:0001",
                        persist_ref=persist_ref("face:a"),
                        entity_kind="face",
                    ),
                    MateEntity(
                        component_id="cmp:0002",
                        persist_ref=persist_ref("face:b"),
                        entity_kind="face",
                    ),
                ],
                alignment="aligned",
                suppressed=False,
                distance=None,
                angle=None,
            )
        ]
    )


# --- get_package_summary ---------------------------------------------------------


def test_get_package_summary_counts_the_package(context: ToolContext) -> None:
    summary = query.get_package_summary()
    assert summary["design_name"] == "cover-assy"
    assert summary["configuration"] == "Default"
    assert summary["document_count"] == 2
    assert summary["component_count"] == 2
    assert summary["hole_count"] == 1
    assert summary["fastener_count"] == 1
    assert summary["gap_count"] == 1
    assert summary["manifest_discrepancies"] == []
    assert summary["extractor"]["sw_version"] is None


def test_get_package_summary_reports_manifest_discrepancies(make_package: MakePackage) -> None:
    manifest = build_manifest()
    manifest.discrepancies.append(
        Discrepancy(
            document_id="doc:2",
            kind="version_mismatch",
            expected=3,
            actual=4,
            note="the local copy is newer than the manifest",
        )
    )
    with use_context(context_for(make_package(manifest=manifest))):
        summary = query.get_package_summary()
    assert [item["kind"] for item in summary["manifest_discrepancies"]] == ["version_mismatch"]


# --- list_components -------------------------------------------------------------


def test_list_components_lists_the_top_level(context: ToolContext) -> None:
    components = query.list_components()
    assert [item["id"] for item in components] == ["cmp:0001", "cmp:0002"]
    assert components[0]["document_id"] == "doc:2"
    assert components[0]["is_toolbox"] is False


def test_list_components_can_drop_suppressed_instances(make_package: MakePackage) -> None:
    package = make_package()
    package.components[1].suppression = "suppressed"
    with use_context(context_for(package)):
        assert [item["id"] for item in query.list_components()] == ["cmp:0001", "cmp:0002"]
        kept = query.list_components(include_suppressed=False)
    assert [item["id"] for item in kept] == ["cmp:0001"]


def test_list_components_rejects_an_unknown_parent(context: ToolContext) -> None:
    assert query.list_components(parent_id="cmp:9999") == {
        "error": "unknown component id 'cmp:9999'"
    }


# --- get_component ---------------------------------------------------------------


def test_get_component_returns_the_instance_and_its_entities(context: ToolContext) -> None:
    result = query.get_component("cmp:0001")
    assert result["component"]["name"] == "housing-1"
    assert result["document"]["material"] == "6061-T6"
    assert [hole["id"] for hole in result["holes"]] == ["hole:1"]
    assert result["fasteners"] == []
    assert result["mates"] == []


def test_get_component_rejects_an_unknown_id(context: ToolContext) -> None:
    assert query.get_component("cmp:9999") == {"error": "unknown component id 'cmp:9999'"}


# --- find_components -------------------------------------------------------------


def test_find_components_matches_a_glob_case_insensitively(context: ToolContext) -> None:
    assert query.find_components("HOUSING-*") == ["cmp:0001", "cmp:0002"]
    assert query.find_components("*-2") == ["cmp:0002"]
    assert query.find_components("bracket*") == []


def test_find_components_can_restrict_to_one_document(context: ToolContext) -> None:
    assert query.find_components("*", document_id="doc:2") == ["cmp:0001", "cmp:0002"]
    assert query.find_components("*", document_id="doc:1") == []


def test_find_components_rejects_an_unknown_document(context: ToolContext) -> None:
    assert query.find_components("*", document_id="doc:9") == {
        "error": "unknown document id 'doc:9'"
    }


# --- list_mates ------------------------------------------------------------------


def test_list_mates_returns_mates_touching_a_component(make_package: MakePackage) -> None:
    with use_context(context_for(mate_package(make_package))):
        assert [mate["id"] for mate in query.list_mates()] == ["mate:1"]
        assert [mate["id"] for mate in query.list_mates(component_id="cmp:0002")] == ["mate:1"]
        assert query.list_mates(component_id="cmp:0001")[0]["type"] == "Concentric"


def test_list_mates_rejects_an_unknown_component(context: ToolContext) -> None:
    assert query.list_mates(component_id="cmp:9999") == {
        "error": "unknown component id 'cmp:9999'"
    }


# --- list_holes ------------------------------------------------------------------


def test_list_holes_labels_an_unknown_thread_depth(context: ToolContext) -> None:
    holes = query.list_holes()
    assert len(holes) == 1
    hole = holes[0]
    assert hole["thread_depth"] is None
    assert hole["thread_depth_note"] == "unknown"
    assert hole["hole_depth"] == {"value": 12.0, "unit": "mm"}


def test_list_holes_says_so_when_a_hole_has_no_thread_at_all(
    make_package: MakePackage,
) -> None:
    package = make_package()
    package.holes[0].hole_type = "clearance"
    package.holes[0].thread_designation = None
    with use_context(context_for(package)):
        hole = query.list_holes()[0]
    assert hole["thread_depth"] is None
    assert hole["thread_depth_note"] == "not a threaded hole"


def test_list_holes_omits_the_note_when_the_thread_depth_is_known(
    make_package: MakePackage,
) -> None:
    package = make_package()
    package.holes[0].thread_depth = Quantity(value=9.0, unit="mm")
    with use_context(context_for(package)):
        hole = query.list_holes()[0]
    assert hole["thread_depth"] == {"value": 9.0, "unit": "mm"}
    assert "thread_depth_note" not in hole


def test_list_holes_filters_by_component_and_type(context: ToolContext) -> None:
    assert len(query.list_holes(component_id="cmp:0001")) == 1
    assert query.list_holes(component_id="cmp:0002") == []
    assert len(query.list_holes(hole_type="tapped")) == 1
    assert query.list_holes(hole_type="clearance") == []


def test_list_holes_rejects_an_unknown_hole_type(context: ToolContext) -> None:
    result = query.list_holes(hole_type="threaded")
    assert result["error"].startswith("hole_type 'threaded' is not one of")


def test_list_holes_rejects_an_unknown_component(context: ToolContext) -> None:
    assert query.list_holes(component_id="cmp:9999") == {
        "error": "unknown component id 'cmp:9999'"
    }


# --- list_fasteners --------------------------------------------------------------


def test_list_fasteners_reports_the_identity_source(context: ToolContext) -> None:
    fasteners = query.list_fasteners()
    assert [item["id"] for item in fasteners] == ["fst:1"]
    assert fasteners[0]["identity_source"] == "name_parse"
    assert fasteners[0]["thread_designation"] == "M6x1.0"


def test_list_fasteners_filters_by_component_and_kind(context: ToolContext) -> None:
    assert len(query.list_fasteners(component_id="cmp:0002")) == 1
    assert query.list_fasteners(component_id="cmp:0001") == []
    assert len(query.list_fasteners(kind="screw")) == 1
    assert query.list_fasteners(kind="nut") == []


def test_list_fasteners_rejects_an_unknown_kind(context: ToolContext) -> None:
    assert query.list_fasteners(kind="cap_screw")["error"].startswith(
        "kind 'cap_screw' is not one of"
    )


# --- list_interferences ----------------------------------------------------------


def test_list_interferences_groups_and_keeps_truncated_results(
    make_package: MakePackage,
) -> None:
    with use_context(context_for(interference_package(make_package))):
        groups = query.list_interferences()
        assert [group["group_key"] for group in groups] == ["housing/housing"]
        assert groups[0]["statuses"] == ["truncated"]
        assert groups[0]["interferences"][0]["error"] == "result list truncated at 100 pairs"
        assert query.list_interferences(configuration="Machining") == []
        assert len(query.list_interferences(component_id="cmp:0001")) == 1


def test_list_interferences_rejects_an_unknown_component(context: ToolContext) -> None:
    assert query.list_interferences(component_id="cmp:9999") == {
        "error": "unknown component id 'cmp:9999'"
    }


# --- get_drawing_sheet -----------------------------------------------------------


def test_get_drawing_sheet_returns_notes_dimensions_and_views(
    make_package: MakePackage,
) -> None:
    with use_context(context_for(drawing_package(make_package))):
        sheet = query.get_drawing_sheet("doc:3")
    assert sheet["sheet_name"] == "Sheet1"
    assert sheet["parse_status"] == "text"
    assert sheet["reason"] is None
    assert sheet["general_notes"][0]["kind"] == "general_tolerance"
    assert sheet["dimensions"][0]["text_as_read"] == "Ø10.00 ±0.02"
    assert sheet["views"][0]["name"] == "SECTION A-A"
    assert sheet["available_sheets"] == ["Sheet1", "Sheet2"]


def test_get_drawing_sheet_explains_an_unreadable_sheet(make_package: MakePackage) -> None:
    with use_context(context_for(drawing_package(make_package))):
        sheet = query.get_drawing_sheet("doc:3", sheet_name="Sheet2")
    assert sheet["parse_status"] == "no_text"
    assert sheet["dimensions"] == []
    assert sheet["reason"] == "page 2 carries no text layer; it is a flattened image"


def test_get_drawing_sheet_rejects_unknown_documents_and_sheets(
    make_package: MakePackage,
) -> None:
    with use_context(context_for(drawing_package(make_package))):
        assert query.get_drawing_sheet("doc:9") == {"error": "unknown document id 'doc:9'"}
        missing = query.get_drawing_sheet("doc:3", sheet_name="Sheet7")
        assert "has no sheet 'Sheet7'" in missing["error"]
        assert query.get_drawing_sheet("doc:2")["error"] == (
            "document 'doc:2' has no extracted drawing sheets"
        )


# --- find_dimensions -------------------------------------------------------------


def test_find_dimensions_matches_text_and_view(make_package: MakePackage) -> None:
    with use_context(context_for(drawing_package(make_package))):
        every = query.find_dimensions()
        assert [item["text_as_read"] for item in every] == ["Ø10.00 ±0.02"]
        assert every[0]["document_id"] == "doc:3"
        assert every[0]["sheet_name"] == "Sheet1"
        assert query.find_dimensions(text_regex="M6x1.0") == []
        assert len(query.find_dimensions(text_regex=r"10\.00")) == 1
        assert len(query.find_dimensions(near_view="SECTION A-A")) == 1
        assert query.find_dimensions(near_view="DETAIL B") == []


def test_find_dimensions_rejects_a_broken_regex(make_package: MakePackage) -> None:
    with use_context(context_for(drawing_package(make_package))):
        result = query.find_dimensions(text_regex="(unclosed")
    assert result["error"].startswith("text_regex '(unclosed' is not a valid regex")


def test_find_dimensions_rejects_an_unknown_document(context: ToolContext) -> None:
    assert query.find_dimensions(document_id="doc:9") == {"error": "unknown document id 'doc:9'"}


# --- list_gaps -------------------------------------------------------------------


def test_list_gaps_reports_what_extraction_could_not_provide(context: ToolContext) -> None:
    gaps = query.list_gaps()
    assert len(gaps) == 1
    assert gaps[0]["entity_id"] == "hole:1"
    assert gaps[0]["kind"] == "not_extracted"


# --- get_exceptions --------------------------------------------------------------


def test_get_exceptions_is_empty_without_an_exception_store(context: ToolContext) -> None:
    assert context.exceptions is None
    assert query.get_exceptions() == []
    assert query.get_exceptions(check="interference.static") == []


def test_get_exceptions_filters_active_entries_by_check(make_package: MakePackage) -> None:
    exceptions: list[Any] = [
        {"id": "EX-1", "check": "interference.static", "status": "active"},
        {"id": "EX-2", "check": "interference.static", "status": "retired"},
        {"id": "EX-3", "check": "fastener.bottoming", "status": "needs_review"},
    ]
    tool_context = context_for(make_package())
    tool_context.exceptions = exceptions
    with use_context(tool_context):
        assert [item["id"] for item in query.get_exceptions()] == ["EX-1", "EX-3"]
        assert [
            item["id"] for item in query.get_exceptions(check="interference.static")
        ] == ["EX-1"]
