"""Unit tests for the finding builder (T015).

`build_finding` is the one place a finding can be created, so it is where the evidence
rules of constitution Principle I are enforced: a demonstrated finding shows its work, an
unresolved finding says what it could not see, and every finding carries the provenance
of the documents it used.
"""

from __future__ import annotations

import pytest

from swreview.findings import Calculation, FindingIdAllocator, build_finding
from swreview.ir.models import Quantity, SourceRef
from tests.support.packages import build_package

PACKAGE = build_package()

CALCULATION = Calculation(
    model="fastener.engagement",
    inputs={"thread_depth": Quantity(value=12.0, unit="mm")},
    assumptions=["full thread over the stated depth"],
    excluded_effects=["thread form", "coating"],
    result={"engagement_ratio": 1.5},
    units_out="mm",
    function="swreview.checks.fastener.check_fastener_joint",
    function_version="1",
)

DRAWING_LOCATION = SourceRef(document_id="doc:1", sheet="Sheet1", annotation="DIM-4")


def make(**overrides: object):
    fields: dict[str, object] = {
        "finding_id": "F-001",
        "check": "fastener.engagement",
        "title": "Screw bottoms before clamping",
        "status": "demonstrated",
        "severity": "high",
        "package": PACKAGE,
        "configuration": "Default",
        "observed": "20 mm screw into a 12 mm deep hole",
        "requirement": "Thread engagement of at least 1.0 x D",
        "recommended_action": "Shorten the screw to 16 mm",
        "component_ids": ["cmp:0001"],
        "calculation": CALCULATION,
    }
    fields.update(overrides)
    return build_finding(**fields)  # type: ignore[arg-type]


def test_demonstrated_with_a_calculation_is_accepted() -> None:
    finding = make()

    assert finding.id == "F-001"
    assert finding.status == "demonstrated"
    assert finding.calculation is not None
    assert finding.disposition is None


def test_demonstrated_with_a_tool_result_is_accepted() -> None:
    finding = make(calculation=None, tool_result_ids=[3])

    assert finding.tool_result_ids == [3]


def test_demonstrated_without_calculation_or_tool_result_raises() -> None:
    with pytest.raises(ValueError, match="calculation"):
        make(calculation=None)


def test_checked_within_scope_without_evidence_raises() -> None:
    with pytest.raises(ValueError, match="calculation"):
        make(status="checked_within_scope", calculation=None)


def test_checked_within_scope_with_evidence_is_accepted() -> None:
    finding = make(status="checked_within_scope", calculation=None, tool_result_ids=[1, 2])

    assert finding.status == "checked_within_scope"


def test_unresolved_without_coverage_limits_raises() -> None:
    with pytest.raises(ValueError, match="coverage_limits"):
        make(status="unresolved", calculation=None)


def test_unresolved_with_coverage_limits_is_accepted() -> None:
    finding = make(
        status="unresolved",
        calculation=None,
        coverage_limits=["usable thread depth unknown (gap: hole:1)"],
    )

    assert finding.coverage_limits == ["usable thread depth unknown (gap: hole:1)"]


def test_suspected_needs_no_calculation() -> None:
    assert make(status="suspected", calculation=None).status == "suspected"


def test_a_finding_must_name_a_component_or_a_drawing_location() -> None:
    with pytest.raises(ValueError, match="component_ids"):
        make(component_ids=[])


def test_a_drawing_location_alone_is_enough() -> None:
    finding = make(component_ids=[], drawing_locations=[DRAWING_LOCATION])

    assert finding.drawing_locations[0].annotation == "DIM-4"


def test_provenance_is_attached_for_every_referenced_document() -> None:
    finding = make(component_ids=["cmp:0001"], drawing_locations=[DRAWING_LOCATION])

    assert [entry.document_id for entry in finding.provenance] == ["doc:2", "doc:1"]
    assert finding.provenance[0].revision == "A"
    assert finding.provenance[1].vault_version == 7


def test_provenance_has_no_duplicates() -> None:
    finding = make(component_ids=["cmp:0001", "cmp:0002"])

    assert [entry.document_id for entry in finding.provenance] == ["doc:2"]


def test_unknown_component_id_raises() -> None:
    with pytest.raises(ValueError, match="cmp:9999"):
        make(component_ids=["cmp:9999"])


def test_document_without_a_manifest_entry_raises() -> None:
    with pytest.raises(ValueError, match="doc:404"):
        make(drawing_locations=[SourceRef(document_id="doc:404", sheet="Sheet1")])


@pytest.mark.parametrize("status", ["demonstrated", "checked_within_scope"])
def test_non_numeric_findings_cannot_claim_a_numeric_status(status: str) -> None:
    with pytest.raises(ValueError, match="numeric"):
        make(
            status=status,
            numeric=False,
            calculation=None,
            tool_result_ids=[1],
            component_ids=[],
            drawing_locations=[DRAWING_LOCATION],
        )


@pytest.mark.parametrize("status", ["suspected", "unresolved"])
def test_non_numeric_findings_may_be_suspected_or_unresolved(status: str) -> None:
    finding = make(
        status=status,
        numeric=False,
        calculation=None,
        coverage_limits=["drawing text only"],
        component_ids=[],
        drawing_locations=[DRAWING_LOCATION],
    )

    assert finding.status == status


def test_finding_id_allocator_yields_padded_ids() -> None:
    allocator = FindingIdAllocator()

    assert [next(allocator) for _ in range(3)] == ["F-001", "F-002", "F-003"]


def test_finding_id_allocator_keeps_going_past_999() -> None:
    allocator = FindingIdAllocator(start=999)

    assert [next(allocator) for _ in range(2)] == ["F-999", "F-1000"]
