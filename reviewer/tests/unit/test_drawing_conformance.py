"""Each drawing compared with the profile's drawing standard (feature 011 T056, User Story 7).

`contracts/profile.md` sections 2 and 3 are normative. `compare_with_profile` compares every
attached or root drawing with the version 3 profile's `drawing` section, each setting only when
it is not empty: the sheets' format names with `sheet_formats`, `drafting_standard_name`
(ignoring case and surrounding spaces), the sheets' projection and the drawing's length unit.
One `drawing_profile.conformance` finding per drawing names every difference **with the
drawing's own value, never the profile's** (006 FR-034); a drawing that agrees is a `checked`
item, an unread value `unresolved` naming its gap, an empty setting `skipped`, and a version 1
or 2 profile, or none, one `skipped` item naming the missing section. The templates are never
compared. The finding is a review finding (manufacturing), never a release-verdict failure
(owner, 2026-09-23, R5 Q5), and its prefix is not `drawing.`, so it cannot close the checklist's
`drawing.manufacturing_inputs` item.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.drawing_context import (
    CONFORMANCE_CHECK,
    NO_DRAWING_SECTION,
    compare_with_profile,
    run_drawing_context,
)
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.drawings.brief import build_brief
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import load_policy
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.drawings import check_drawings
from swreview.tools.standards_checks import StandardsRun, attach_standards_run
from tests.support.drawings import DrawingBuilder
from tests.support.mechanical import PackageBuilder

TESTS = Path(__file__).resolve().parents[1]
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"
PROFILE_B = TESTS / "fixtures" / "standards" / "profile-b.yaml"


@pytest.fixture(scope="module")
def plate() -> EvidencePackage:
    return load_package(PLATE_DRAWING).package


@pytest.fixture(scope="module")
def profile_a() -> StandardsProfile:
    return load_profile(PROFILE_A)


def with_drawing(profile: StandardsProfile, **settings: Any) -> StandardsProfile:
    assert profile.drawing is not None
    return profile.model_copy(
        update={"drawing": profile.drawing.model_copy(update=settings)}
    )


def one_drawing(**sheet: Any) -> EvidencePackage:
    """An assembly of one part with one drawing of it; `sheet` and `drawing` settings passed."""
    drawing_fields = sheet.pop("drawing", {})
    base = PackageBuilder(design_stem="FICT-OKTAVEN-6000", schema_version="1.6.0")
    part = base.document("FICT-KALO-6001", "part")
    base.component(part)
    builder = DrawingBuilder(base.build().package)
    record = builder.drawing(builder.drawing_document("FICT-KALO-6001"), **drawing_fields)
    builder.view(builder.sheet(record, "Sheet1", **sheet), "Drawing View1", references=part)
    return builder.build()


def by_drawing(package: EvidencePackage, profile: StandardsProfile | None) -> dict[str, Any]:
    run = compare_with_profile(package, profile)
    return {item.document_id: item for item in run.drawings}


# --- 1. agreeing, differing, unread, skipped (section 2) ------------------------------------------


def test_drawing_a_conforms_to_profile_a(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    run = compare_with_profile(plate, profile_a)
    drawing_a = by_drawing(plate, profile_a)["doc:0006"]

    assert drawing_a.differs == ()
    assert drawing_a.skipped == ()
    checked = [item for bucket, item in run.coverage if bucket == "checked"]
    assert any(item.scope.document_ids == ["doc:0006"] for item in checked)
    assert all(result.document_id != "doc:0006" for result in run.findings)


def test_a_first_angle_profile_with_another_format_is_one_finding_naming_both(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    profile = with_drawing(profile_a, projection="first_angle",
                           sheet_formats=["FICT-OTHER-FORMAT"])

    run = compare_with_profile(plate, profile)

    [finding] = [item for item in run.findings if item.document_id == "doc:0006"]
    result = finding.result
    assert result.check == CONFORMANCE_CHECK == "drawing_profile.conformance"
    assert (result.status, result.severity) == ("demonstrated", "medium")
    assert by_drawing(plate, profile)["doc:0006"].differs == ("sheet_formats", "projection")
    assert "sheet Sheet1 uses the sheet format 'FICTIONAL-FORMAT-A'" in result.observed
    assert "sheet Sheet1 is drawn in third-angle projection" in result.observed
    assert "FICT-OTHER-FORMAT" not in json.dumps(asdict(result), default=str)
    assert "first" not in result.observed.lower()


@pytest.mark.parametrize(
    ("settings", "sheet", "drawing", "differs", "words"),
    [
        ({"sheet_formats": ["FICT-OTHER-FORMAT"]}, {}, {}, ("sheet_formats",),
         "sheet Sheet1 uses the sheet format 'FICTIONAL-FORMAT-A'"),
        ({"drafting_standard": "FICT-OTHER-STANDARD"}, {}, {}, ("drafting_standard",),
         "the drawing's drafting standard is 'FICTIONAL-STANDARD'"),
        ({"projection": "first_angle"}, {}, {}, ("projection",),
         "sheet Sheet1 is drawn in third-angle projection"),
        ({"projection": "third_angle"}, {"first_angle": True}, {}, ("projection",),
         "sheet Sheet1 is drawn in first-angle projection"),
        ({"dimension_unit": "in"}, {}, {}, ("dimension_unit",),
         "the drawing is dimensioned in mm"),
        ({"dimension_unit": "mm"}, {}, {"length_unit_raw": 1}, ("dimension_unit",),
         "the drawing is dimensioned in unit 1 (swLengthUnit_e)"),
    ],
)
def test_each_setting_differing_on_its_own(
    profile_a: StandardsProfile,
    settings: dict[str, Any],
    sheet: dict[str, Any],
    drawing: dict[str, Any],
    differs: tuple[str, ...],
    words: str,
) -> None:
    package = one_drawing(drawing=drawing, **sheet)
    profile = with_drawing(profile_a, **settings)

    run = compare_with_profile(package, profile)

    [finding] = run.findings
    assert run.drawings[0].differs == differs
    assert words in finding.result.observed


def test_every_setting_differing_together_is_still_one_finding(
    profile_a: StandardsProfile,
) -> None:
    package = one_drawing(first_angle=True)
    profile = with_drawing(profile_a, sheet_formats=["FICT-OTHER-FORMAT"],
                           drafting_standard="FICT-OTHER-STANDARD", projection="third_angle",
                           dimension_unit="in")

    run = compare_with_profile(package, profile)

    [finding] = run.findings
    assert run.drawings[0].differs == (
        "sheet_formats", "drafting_standard", "projection", "dimension_unit"
    )
    assert finding.documents == (run.drawings[0].document_id,)


def test_the_drafting_standard_is_compared_ignoring_case_and_surrounding_spaces(
    profile_a: StandardsProfile,
) -> None:
    package = one_drawing(drawing={"drafting_standard_name": "  fictional-standard "})

    assert compare_with_profile(package, profile_a).findings == ()


def test_an_unread_value_is_unresolved_naming_the_setting_and_its_gap(
    profile_a: StandardsProfile,
) -> None:
    package = one_drawing(first_angle=None, drawing={"drafting_standard_name": None})

    run = compare_with_profile(package, profile_a)

    [(bucket, item)] = [entry for entry in run.coverage if entry[0] == "unresolved"]
    assert bucket == "unresolved"
    assert "the projection of sheet Sheet1 was not read" in item.reason
    assert "the drafting standard of drawing doc:0003 was not read" in item.reason
    assert run.findings == ()


def test_an_empty_setting_is_skipped_never_passed(profile_a: StandardsProfile) -> None:
    package = one_drawing()
    profile = with_drawing(profile_a, sheet_formats=[], projection="")

    run = compare_with_profile(package, profile)

    assert run.drawings[0].skipped == ("sheet_formats", "projection")
    skipped = [item for bucket, item in run.coverage if bucket == "skipped"]
    assert len(skipped) == 1
    assert "sheet_formats" in skipped[0].reason and "projection" in skipped[0].reason
    checked = [item for bucket, item in run.coverage if bucket == "checked"]
    assert len(checked) == 1 and "sheet_formats" not in checked[0].reason


def test_profile_b_skips_every_drawing_setting(plate: EvidencePackage) -> None:
    run = compare_with_profile(plate, load_profile(PROFILE_B))

    assert run.findings == ()
    assert {item.skipped for item in run.drawings} == {
        ("sheet_formats", "drafting_standard", "projection", "dimension_unit")
    }
    assert [bucket for bucket, _ in run.coverage] == ["skipped", "skipped"]


@pytest.mark.parametrize("version", [1, 2, None])
def test_a_profile_without_a_drawing_section_is_one_skipped_item(
    plate: EvidencePackage, profile_a: StandardsProfile, version: int | None
) -> None:
    profile = None
    if version is not None:
        profile = profile_a.model_copy(update={"version": version, "drawing": None})

    run = compare_with_profile(plate, profile)

    [(bucket, item)] = run.coverage
    assert bucket == "skipped"
    expected = (
        f"the standards profile is version {version}, which has no drawing section"
        if version is not None
        else NO_DRAWING_SECTION
    )
    assert item.reason == expected
    assert item.scope.document_ids == ["doc:0006", "doc:0007"]
    assert run.findings == () and run.drawings == ()


def test_the_templates_are_never_compared(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    profile = with_drawing(profile_a, drawing_template="FICT-ANY.drwdot",
                           bom_template="FICT-ANY.sldbomtbt")

    assert compare_with_profile(plate, profile) == compare_with_profile(plate, profile_a)


def test_no_drawing_record_compares_nothing(profile_a: StandardsProfile) -> None:
    base = PackageBuilder(design_stem="FICT-OKTAVEN-6100", schema_version="1.6.0")

    run = compare_with_profile(base.build().package, profile_a)

    assert (run.findings, run.coverage, run.drawings) == ((), (), ())


def test_the_findings_bytes_carry_no_profile_value(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    profile = with_drawing(profile_a, projection="first_angle",
                           sheet_formats=["FICT-OTHER-FORMAT", "FICT-SECOND-FORMAT"],
                           drafting_standard="FICT-OTHER-STANDARD")

    run = compare_with_profile(plate, profile)

    text = json.dumps([asdict(item.result) for item in run.findings], default=str)
    text += json.dumps([item.model_dump() for _, item in run.coverage])
    for value in ("FICT-OTHER-FORMAT", "FICT-SECOND-FORMAT", "FICT-OTHER-STANDARD",
                  "first_angle", "first-angle", "first angle"):
        assert value not in text, value


# --- 2. through the check, the report and the checklist (section 3) -------------------------------


def reviewed(package: EvidencePackage, profile: StandardsProfile) -> ToolContext:
    context = context_for(package)
    attach_standards_run(
        context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
    )
    return context


def test_check_drawings_records_and_counts_the_finding(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    context = reviewed(plate, with_drawing(profile_a, projection="first_angle"))
    with use_context(context):
        result = check_drawings()

    session = context.require_session()
    findings = [item for item in session.findings if item.check == CONFORMANCE_CHECK]
    assert result["findings"] == 2, "drawings A and B are both third angle"
    assert result["finding_ids"] == [item.id for item in findings]
    assert [[entry.document_id for entry in item.provenance] for item in findings] == [
        ["doc:0006"], ["doc:0007"]
    ]
    assert all(item.tool_result_ids for item in findings)


def test_a_second_call_records_no_second_finding(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    context = reviewed(plate, with_drawing(profile_a, projection="first_angle"))
    with use_context(context):
        check_drawings()
        again = check_drawings()

    findings = [item for item in context.require_session().findings
                if item.check == CONFORMANCE_CHECK]
    assert len(findings) == 2
    assert again["findings"] == 2 and again["finding_ids"] == [item.id for item in findings]


def test_the_checklists_drawing_item_stays_open_after_the_finding(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    context = reviewed(plate, with_drawing(profile_a, projection="first_angle"))
    with use_context(context):
        check_drawings()

    session = context.require_session()
    [item] = [item for item in context.checklist.items if item.id == "drawing.manufacturing_inputs"]
    assert any(finding.check == CONFORMANCE_CHECK for finding in session.findings)
    assert context.checklist.bucket_of(item, session) == "open"


def test_the_finding_is_classed_manufacturing() -> None:
    assert load_policy().classes[CONFORMANCE_CHECK] == "manufacturing"


def test_the_drawing_context_carries_the_comparison(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    result = run_drawing_context(plate, profile=with_drawing(profile_a, projection="first_angle"))

    assert [item.document_id for item in result.conformance.drawings] == ["doc:0006", "doc:0007"]


def test_the_brief_fills_its_conformance_section(
    plate: EvidencePackage, profile_a: StandardsProfile
) -> None:
    profile = with_drawing(profile_a, projection="first_angle", sheet_formats=[])

    brief = json.loads(build_brief(plate, None, profile, "doc:0002").to_json())

    assert brief["conformance"]["drawings"] == [
        {"document_id": "doc:0006", "differs": ["projection"], "skipped": ["sheet_formats"]},
        {"document_id": "doc:0007", "differs": ["projection"], "skipped": ["sheet_formats"]},
    ]
    text = json.dumps(brief)
    assert "first_angle" not in text
