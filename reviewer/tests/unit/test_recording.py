"""Unit tests for `tools/recording.py` carrying tool result ids (T017).

Every RMS rule result is a finding whose evidence is a feature tree, not arithmetic: the
`Calculation` block that backs a fit or a stack has nothing to say about "this feature has
no description". `build_finding` already allows that - a numeric status may be backed by a
calculation *or* by at least one `tool_result_id` - but the three recording helpers had no
way to pass one, so an RMS `demonstrated` result could not be recorded at all. These tests
pin the forwarding, and pin that the rule underneath it still bites when no id is given.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from swreview.checks.result import CheckResult
from swreview.findings import Calculation
from swreview.ir.models import EvidencePackage, Quantity, SourceRef
from swreview.tools import session as session_tools
from swreview.tools.context import context_for, use_context
from swreview.tools.recording import (
    TITLE_LENGTH,
    record_result,
    record_results,
    result_to_finding,
    title_from,
)

MakePackage = Callable[..., EvidencePackage]

COMPONENT = "cmp:0001"
STEP_ID = 7


def tree_result(check: str = "rms.part.every_feature_described") -> CheckResult:
    """A rule result the way an RMS rule reports it: evidence, and no calculation."""
    return CheckResult(
        check=check,
        status="demonstrated",
        severity="medium",
        observed="Boss-Extrude1 carries no description. Every content feature needs one.",
        requirement="Every content feature carries a description.",
        inputs=["feature f:1 Boss-Extrude1 (extrusion) in doc:2"],
        calculation=None,
        coverage_limits=[],
        recommended_action="Describe Boss-Extrude1.",
    )


def calculated_result() -> CheckResult:
    """A result that carries its own arithmetic, so it needs no step id."""
    return CheckResult(
        check="fit.clearance",
        status="demonstrated",
        severity="medium",
        observed="The bore and shaft interfere by 0.01 mm at the tight limit.",
        requirement="A clearance fit keeps a positive gap at every limit.",
        inputs=[],
        calculation=Calculation(
            model="clearance",
            inputs={"bore_min_mm": Quantity(value=40.0, unit="mm")},
            assumptions=[],
            excluded_effects=[],
            result={"clearance_min_mm": Quantity(value=-0.01, unit="mm")},
            units_out="mm",
            function="check_fit",
            function_version="1",
        ),
        coverage_limits=[],
        recommended_action="Open the bore.",
    )


def test_result_to_finding_forwards_tool_result_ids(make_package: MakePackage) -> None:
    context = context_for(make_package())

    finding = result_to_finding(
        context,
        tree_result(),
        component_ids=[COMPONENT],
        tool_result_ids=[STEP_ID],
    )

    assert finding.tool_result_ids == [STEP_ID]


def test_result_to_finding_needs_a_step_id_when_there_is_no_calculation(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())

    with pytest.raises(ValueError, match="requires a calculation or at least one tool_result_id"):
        result_to_finding(context, tree_result(), component_ids=[COMPONENT])


def test_result_to_finding_leaves_tool_result_ids_empty_by_default(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())

    finding = result_to_finding(context, calculated_result(), component_ids=[COMPONENT])

    assert finding.tool_result_ids == []


def test_record_result_forwards_tool_result_ids_to_the_session(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())
    session = context.session
    assert session is not None

    recorded = record_result(
        context,
        tree_result(),
        component_ids=[COMPONENT],
        tool_result_ids=[STEP_ID],
    )

    assert recorded["status"] == "recorded"
    assert session.findings[0].tool_result_ids == [STEP_ID]
    assert recorded["finding"]["tool_result_ids"] == [STEP_ID]  # type: ignore[index]


def test_record_result_carries_an_exception_id_alongside_the_step_ids(
    make_package: MakePackage,
) -> None:
    """The two optional arguments are passed by keyword, so an added parameter cannot
    silently slide one into the other's place."""
    context = context_for(make_package())
    session = context.session
    assert session is not None

    recorded = record_result(
        context,
        tree_result(),
        component_ids=[COMPONENT],
        exception_id="EX-001",
        tool_result_ids=[STEP_ID],
    )

    assert recorded["status"] == "recorded"
    assert session.findings[0].exception_id == "EX-001"
    assert session.findings[0].tool_result_ids == [STEP_ID]
    assert recorded["finding"]["exception_id"] == "EX-001"  # type: ignore[index]


def test_record_result_without_a_step_id_is_an_error_and_writes_nothing(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())
    session = context.session
    assert session is not None

    recorded = record_result(context, tree_result(), component_ids=[COMPONENT])

    assert "requires a calculation or at least one tool_result_id" in str(recorded["error"])
    assert session.findings == []


def test_record_results_forwards_tool_result_ids_to_every_finding(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())
    session = context.session
    assert session is not None
    results = [tree_result(), tree_result("rms.part.grouping")]

    recorded = record_results(
        context,
        results,
        component_ids=[COMPONENT],
        tool_result_ids=[STEP_ID],
    )

    assert recorded["status"] == "recorded"
    assert [finding.tool_result_ids for finding in session.findings] == [[STEP_ID], [STEP_ID]]
    assert [finding.check for finding in session.findings] == [
        "rms.part.every_feature_described",
        "rms.part.grouping",
    ]


def test_record_results_without_a_step_id_is_an_error_and_writes_nothing(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())
    session = context.session
    assert session is not None

    recorded = record_results(context, [tree_result()], component_ids=[COMPONENT])

    assert "requires a calculation or at least one tool_result_id" in str(recorded["error"])
    assert session.findings == []


# --- the recorded title: what the model reads, unchanged (feature 009 decision 2A) ---------

LONG_OBSERVED = (
    "The bore of cmp:0001 and the shaft of cmp:0002 interfere by 0.01 mm at the tight limit of "
    "the fit. The second sentence is never the title."
)
"""A first sentence past 80 characters naming both parts of the package by id."""


def test_a_recorded_finding_keeps_the_cut_title_with_its_ids(make_package: MakePackage) -> None:
    """The whole, named title is built where a person reads it (research R2.28), never here:
    `Finding.title` is in the tool result, so it is exactly `title_from(observed)`."""
    result = replace(calculated_result(), observed=LONG_OBSERVED)
    context = context_for(make_package())

    finding = result_to_finding(context, result, component_ids=[COMPONENT])

    assert finding.title == title_from(LONG_OBSERVED)
    assert finding.title.endswith("…") and len(finding.title) <= TITLE_LENGTH
    assert finding.title.startswith("The bore of cmp:0001 and the shaft of cmp:0002")
    assert finding.observed == LONG_OBSERVED


def test_a_drawing_finding_keeps_the_cut_title_with_its_ids(make_package: MakePackage) -> None:
    observed = (
        "The drawing of cmp:0001 calls out the tapped hole without the usable thread depth, so "
        "the engagement cannot be judged. Nothing else is missing."
    )
    context = context_for(make_package())
    with use_context(context):
        result = session_tools.record_drawing_finding(
            document_id="doc:2",
            sheet="Sheet1",
            observed=observed,
            requirement="A tapped hole callout states the usable thread depth",
            source_refs=[SourceRef(document_id="doc:2", sheet="Sheet1")],
            status="suspected",
            recommended_action="Add the tapped depth to the hole callout",
        )

    assert result["finding"]["title"] == title_from(observed)
    assert result["finding"]["title"].startswith("The drawing of cmp:0001")
    assert result["finding"]["observed"] == observed
