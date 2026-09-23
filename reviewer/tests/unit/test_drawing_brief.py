"""The per-part drawing brief: bounded, deterministic, reference-free (feature 011 T050).

`contracts/brief.md` sections 2 to 6 are normative. `build_brief` gives, for one part or
assembly, in a fixed key order: the document; how it is assembled (feature 010's joint map);
the interfaces needing a callout, each with its current tolerance and source or what is missing,
the drawing record bound or why none, and feature 010's position budget callout; what the
drawings cover; the engineer's answers about it; and its drawings' conformance. It reuses feature
010's joint map, callout and resolver and recomputes none of them (FR-042); its compact JSON is
at most 6,000 bytes whatever the package, every cut counted in `omitted` (FR-040); it carries no
persistent reference and no profile value (FR-041).
"""

from __future__ import annotations

import base64
import json
import random
import re
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.drawings import binding
from swreview.drawings.brief import (
    BRIEF_MAX_BYTES,
    BRIEF_VERSION,
    BriefRefused,
    build_brief,
)
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import ReviewSession
from swreview.tools.context import context_for, use_context
from swreview.tools.session import request_evidence
from tests.support.drawings import Attach, DrawingBuilder
from tests.support.mechanical import Face, Instance, PackageBuilder

TESTS = Path(__file__).resolve().parents[1]
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"
Z = (0.0, 0.0, 1.0)

KEYS = [
    "brief_version",
    "document",
    "assembly",
    "interfaces",
    "drawing",
    "answers",
    "conformance",
    "omitted",
]


@pytest.fixture
def validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", True)


@pytest.fixture(scope="module")
def plate() -> EvidencePackage:
    return load_package(PLATE_DRAWING).package


@pytest.fixture(scope="module")
def profile() -> StandardsProfile:
    return load_profile(PROFILE_A)


def answered_session(package: EvidencePackage) -> ReviewSession:
    """A session holding one answered question about the plate and one open one about the
    block, as the pane's batch route leaves them."""
    context = context_for(package)
    with use_context(context):
        request_evidence("the plate's finish", "sets the fit", ["doc:0002"],
                         question="Which finish does the plate take?", options=["A", "B"])
        request_evidence("the block's finish", "sets the fit", ["doc:0003"],
                         question="Which finish does the block take?")
        request_evidence("a note about the pin", "for the stack", ["cmp:0003"])
    session = context.require_session()
    first, _, third = session.evidence_requests
    first.status, first.answer = "answered", "A"
    third.status, third.answer = "answered", "a free answer"
    return session


def brief_of(package: EvidencePackage, document_id: str, profile: StandardsProfile | None = None,
             session: ReviewSession | None = None) -> dict[str, Any]:
    brief = build_brief(package, session, profile, document_id)
    data = json.loads(brief.to_json())
    assert list(data) == KEYS
    return data


# --- 1. the plate's brief, section by section -----------------------------------------------------


@pytest.mark.usefixtures("validated")
def test_the_document_section(plate: EvidencePackage, profile: StandardsProfile) -> None:
    document = brief_of(plate, "doc:0002", profile)["document"]

    assert document == {
        "id": "doc:0002",
        "file_name": "FICT-TULMKALO-3001.SLDPRT",
        "kind": "part",
        "configuration": ["Default"],
        "description": "TULM KALO",
        "material": "6061-T6",
        "mass_kg": None,
        "instances": 1,
    }
    assert BRIEF_VERSION == 1


def test_without_a_profile_naming_a_description_property_there_is_no_description(
    plate: EvidencePackage,
) -> None:
    assert brief_of(plate, "doc:0002")["document"]["description"] is None


@pytest.mark.usefixtures("validated")
def test_the_assembly_section_folds_the_plates_two_joints(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    assembly = brief_of(plate, "doc:0002", profile, answered_session(plate))["assembly"]

    kinds = [group["kind"] for group in assembly["joints"]]
    assert sorted(kinds) == ["pin", "screw"]
    pin = next(group for group in assembly["joints"] if group["kind"] == "pin")
    screw = next(group for group in assembly["joints"] if group["kind"] == "screw")
    assert pin["partners"] == ["FICT-PIN-3X12-3003.SLDPRT", "FICT-TULMSORN-3002.SLDPRT"]
    assert screw["partners"] == ["FICT-TULMSORN-3002.SLDPRT", "SHC_M4-0.7X8_FICT-3004.SLDPRT"]
    assert screw["fastener"] == "M4x0.7" and pin["fastener"] is None
    assert all(len(group["joint_ids"]) == 1 for group in assembly["joints"])
    assert assembly["contacts"] == 0 and assembly["interference_finding_ids"] == []


def test_without_a_session_the_contacts_and_interferences_are_unknown(
    plate: EvidencePackage,
) -> None:
    assembly = brief_of(plate, "doc:0002")["assembly"]

    assert assembly["contacts"] is None and assembly["interference_finding_ids"] is None


@pytest.mark.usefixtures("validated")
def test_the_interfaces_name_each_subject_its_tolerance_its_drawing_and_its_callout(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    interfaces = brief_of(plate, "doc:0002", profile)["interfaces"]

    by_subject = {item["subject"]: item for item in interfaces}
    assert list(by_subject) == [
        "the size of hol:0001#1",
        "the position of hol:0001#1",
        "the size of hol:0002#1",
        "the position of hol:0002#1",
    ]
    dowel = by_subject["the size of hol:0001#1"]
    assert dowel["tolerance"] == {
        "source": "drawing",
        "cited": "drawing doc:0006, sheet Sheet1, view Drawing View1, ddm:0001",
        "also_found": ["model_dimension"],
    }
    assert dowel["drawing"] == {"record": "ddm:0001"}
    assert dowel["callout"].startswith("position ⌀")
    position = by_subject["the position of hol:0001#1"]
    assert position["tolerance"]["source"] == "drawing"
    assert position["tolerance"]["cited"].endswith("read in the drawing's unit, mm")
    bore = by_subject["the size of hol:0002#1"]
    assert bore["tolerance"]["source"] == "general"
    assert bore["drawing"] == {"record": "ddm:0003"}
    unresolved = by_subject["the position of hol:0002#1"]["tolerance"]["unresolved"]
    assert [source for source, _ in unresolved] == [
        "drawing", "annotation", "model_dimension", "hole_wizard", "general"
    ]
    assert by_subject["the position of hol:0002#1"]["drawing"]["why"]


def test_with_the_switch_off_the_interfaces_say_the_drawing_is_not_validated(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    interfaces = brief_of(plate, "doc:0002", profile)["interfaces"]

    dowel = next(item for item in interfaces if item["subject"] == "the size of hol:0001#1")
    assert dowel["tolerance"]["source"] == "model_dimension"
    assert dowel["drawing"]["why"].startswith("drawing callouts are read but not yet validated")


@pytest.mark.usefixtures("validated")
def test_the_drawing_section_counts_what_each_drawing_says_about_the_plate(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    drawing = brief_of(plate, "doc:0002", profile)["drawing"]

    first, second = drawing["attached"]
    assert {key: first[key] for key in (
        "document_id", "file_name", "sheets", "views_of_document", "usable_views", "unusable",
        "dimensions", "toleranced", "hole_callouts", "gtols", "datums", "surface_finishes",
    )} == {
        "document_id": "doc:0006",
        "file_name": "FICT-TULMKALO-3001.SLDDRW",
        "sheets": 1,
        "views_of_document": 1,
        "usable_views": 1,
        "unusable": [],
        "dimensions": 9,
        "toleranced": 2,
        "hole_callouts": 1,
        "gtols": 1,
        "datums": ["A", "B"],
        "surface_finishes": 1,
    }
    assert first["notes"] == [
        "FICTIONAL NOTE 1",
        "GENERAL TOLERANCE FICTIONAL: .X 0.4 .XX 0.15 .XXX 0.04",
        "BREAK SHARP EDGES FICTIONAL",
    ]
    assert [(table["kind"], table["title"]) for table in first["tables"]] == [
        ("TitleBlock", "TITLE BLOCK"),
        ("GeneralTolerance", "GENERAL TOLERANCE"),
        ("HoleChart", "HOLE TABLE"),
    ]
    assert first["tables"][0]["rows"] == [["TITLE", "FICT-TULMKALO-3001"], ["REV", "A"]]
    assert second["document_id"] == "doc:0007"
    assert (second["views_of_document"], second["usable_views"]) == (2, 0)
    assert len(second["unusable"]) == 2
    assert drawing["candidates"] == []
    assert "why" not in drawing


def test_the_blocks_brief_names_its_candidate(plate: EvidencePackage) -> None:
    drawing = brief_of(plate, "doc:0003")["drawing"]

    assert drawing["attached"] == []
    assert drawing["why"] == "no open drawing shows it"
    assert drawing["candidates"] == ["FICT-TULMSORN-3002.SLDDRW"]


def test_the_answers_are_the_answered_requests_about_the_document(
    plate: EvidencePackage,
) -> None:
    session = answered_session(plate)

    plate_answers = brief_of(plate, "doc:0002", session=session)["answers"]
    pin_answers = brief_of(plate, "doc:0004", session=session)["answers"]

    assert plate_answers == [
        {"request_id": "ER-001", "question": "Which finish does the plate take?", "answer": "A"}
    ]
    assert pin_answers == [
        {"request_id": "ER-003", "question": "a note about the pin", "answer": "a free answer"}
    ], "a request naming the pin's component is about the pin's document; `what` stands in"


def test_the_conformance_section_names_the_profile_by_identity(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    conformance = brief_of(plate, "doc:0002", profile)["conformance"]

    assert conformance["profile"] == f"sha256 {profile.identity.sha256[:12]}"
    assert brief_of(plate, "doc:0002")["conformance"]["profile"] is None


@pytest.mark.usefixtures("validated")
def test_the_plates_brief_omits_nothing_and_fits(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    brief = build_brief(plate, answered_session(plate), profile, "doc:0002")

    assert json.loads(brief.to_json())["omitted"] == {}
    assert len(brief.to_json().encode("utf-8")) <= BRIEF_MAX_BYTES


# --- 2. what it never carries ---------------------------------------------------------------------


def _profile_values(profile: StandardsProfile) -> list[str]:
    values: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and len(value) >= 4:
            values.append(value)

    walk(profile.model_dump())
    return values


@pytest.mark.usefixtures("validated")
def test_no_persistent_reference_and_no_profile_value(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    text = build_brief(plate, answered_session(plate), profile, "doc:0002").to_json()

    assert "persist_ref" not in text
    for ref in {face.persist_ref for face in plate.faces} | {
        dimension.persist_ref
        for record in plate.drawing_records
        for sheet in record.sheets
        for view in sheet.views
        for dimension in view.display_dimensions
        if dimension.persist_ref
    }:
        assert ref not in text
    for token in re.findall(r"[A-Za-z0-9+/]{8,}={0,2}", text):
        try:
            decoded = base64.b64decode(token, validate=True)
        except ValueError:
            continue
        assert not decoded.startswith((b"fac:", b"ddm:", b"dan:")), token
    offenders = [value for value in _profile_values(profile) if value in text]
    assert offenders == [], "the brief names settings, never their values"


# --- 3. the refusals (section 5) ------------------------------------------------------------------


def test_an_id_that_is_not_a_document_is_refused_naming_the_documents(
    plate: EvidencePackage,
) -> None:
    with pytest.raises(BriefRefused) as raised:
        build_brief(plate, None, None, "doc:9999")

    assert str(raised.value) == (
        "document doc:9999 is not in this package; the documents that can be briefed are: "
        "doc:0001, doc:0002, doc:0003, doc:0004, doc:0005"
    )


def test_a_drawing_is_refused_naming_the_documents_it_shows(plate: EvidencePackage) -> None:
    with pytest.raises(BriefRefused) as raised:
        build_brief(plate, None, None, "doc:0006")

    assert str(raised.value) == (
        "doc:0006 is a drawing; a brief is of a part or assembly. The documents it shows: "
        "doc:0002"
    )


def test_the_refusal_names_the_first_twenty_briefable_documents() -> None:
    base = PackageBuilder(design_stem="FICT-OKTAVEN-9000", schema_version="1.6.0")
    for number in range(25):
        base.component(base.document(f"FICT-KALO-{9001 + number}", "part"))

    with pytest.raises(BriefRefused) as raised:
        build_brief(base.build().package, None, None, "cmp:0001")

    listed = str(raised.value).split("are: ", 1)[1].split(", ")
    assert len(listed) == 20 and listed[0] == "doc:0001"


# --- 4. deterministic -----------------------------------------------------------------------------


@pytest.mark.usefixtures("validated")
def test_shuffling_the_package_arrays_changes_no_byte(
    plate: EvidencePackage, profile: StandardsProfile
) -> None:
    expected = build_brief(plate, answered_session(plate), profile, "doc:0002").to_json()
    shuffler = random.Random(3)
    for _ in range(3):
        records = [
            record.model_copy(
                update={
                    "sheets": [
                        sheet.model_copy(
                            update={
                                "views": shuffler.sample(sheet.views, len(sheet.views)),
                                "tables": sheet.tables,
                            }
                        )
                        for sheet in record.sheets
                    ]
                }
            )
            for record in plate.drawing_records
        ]
        update: dict[str, Any] = {
            name: shuffler.sample(getattr(plate, name), len(getattr(plate, name)))
            for name in ("documents", "components", "holes", "faces", "bodies",
                         "model_dimensions", "model_annotations", "drawing_candidates", "gaps")
        }
        update["drawing_records"] = shuffler.sample(records, len(records))
        shuffled = plate.model_copy(update=update)
        assert build_brief(shuffled, answered_session(shuffled), profile,
                           "doc:0002").to_json() == expected


# --- 5. the bound (section 3) ---------------------------------------------------------------------

JOINTS = 60
NOTES = 500
DIMENSIONS = 300


def pathological() -> EvidencePackage:
    """A plate with sixty dowel joints and a drawing of five hundred notes and three hundred
    dimensions: built here, never committed (`contracts/fixtures.md` section 2)."""
    base = PackageBuilder(design_stem="FICT-OKTAVEN-9900", schema_version="1.6.0")
    plate = base.document("FICT-KALO-9901", "part", material="6061-T6")
    block = base.document("FICT-SORN-9902", "part", material="Alloy Steel")
    pin = base.document("FICT-PIN-3X12-9903", "part", material="Alloy Steel")
    plate_cmp = base.component(plate)
    block_cmp = base.component(block)
    for number in range(JOINTS):
        x = 10.0 * number
        base.hole(plate_cmp, hole_type="clearance", size="Ø3.0", end_condition="through",
                  instances=[Instance((x, 0.0, 0.0), Z, (Face(3.0, 0.0, 6.0),))])
        base.hole(block_cmp, hole_type="clearance", size="Ø3.0", end_condition="through",
                  instances=[Instance((x, 0.0, 0.0), Z, (Face(3.0, -6.0, 0.0),))])
        pin_cmp = base.component(pin)
        base.cylinder_face(pin_cmp, origin_mm=(x, 0.0, 0.0), direction=Z, diameter_mm=3.0,
                           lo_mm=-5.0, hi_mm=5.0)
    builder = DrawingBuilder(base.build().package)
    record = builder.drawing(builder.drawing_document("FICT-KALO-9901"))
    sheet = builder.sheet(record, "Sheet1")
    frame = builder.view(sheet, "Sheet Format1", view_type_raw=1, configuration=None,
                         out_of_date=None, loaded=None, scale_decimal=None, orientation=None)
    for number in range(NOTES):
        builder.note(frame, f"FICTIONAL NOTE {number} " + "X" * 300)
    view = builder.view(sheet, "Drawing View1", references=plate)
    for number in range(DIMENSIONS):
        builder.dimension(view, f"KALOMIR{number}@FICT-KALO-9901", value_mm=3.0,
                          attached=[Attach("fac:0001")])
    for number in range(8):
        builder.table(sheet, frame, type_raw=0, title=f"TABLE {number}",
                      rows=[[f"{row}", "X"] for row in range(15)])
    return builder.build()


@pytest.fixture(scope="module")
def big_brief() -> tuple[EvidencePackage, Any]:
    package = pathological()
    return package, build_brief(package, None, None, "doc:0002")


def test_a_pathological_package_fits_in_six_thousand_bytes(big_brief: Any) -> None:
    _, brief = big_brief

    assert BRIEF_MAX_BYTES == 6_000
    assert len(brief.to_json().encode("utf-8")) <= BRIEF_MAX_BYTES


def test_omitted_counts_exactly_what_was_cut(big_brief: Any) -> None:
    package, brief = big_brief
    data = json.loads(brief.to_json())
    omitted = data["omitted"]
    [drawing] = data["drawing"]["attached"]

    assert len(data["assembly"]["joints"]) + omitted.get("assembly.joints", 0) == JOINTS
    assert len(data["interfaces"]) + omitted.get("interfaces", 0) == 2 * JOINTS
    assert len(drawing["notes"]) + omitted.get("drawing.notes", 0) == NOTES
    assert len(drawing["tables"]) + omitted.get("drawing.tables", 0) == 8
    rows = sum(len(table["rows"]) for table in drawing["tables"])
    assert rows + omitted.get("drawing.table_rows", 0) == 15 * len(drawing["tables"])
    assert len(data["assembly"]["joints"]) <= 20 and len(data["interfaces"]) <= 20
    assert len(drawing["notes"]) <= 10 and len(drawing["tables"]) <= 5
    assert all(len(note) <= 200 for note in drawing["notes"])
    assert drawing["dimensions"] == DIMENSIONS
    assert package is not None


def test_the_same_pathological_package_gives_the_same_bytes(big_brief: Any) -> None:
    package, brief = big_brief

    assert build_brief(package, None, None, "doc:0002").to_json() == brief.to_json()
