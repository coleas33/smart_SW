"""User Story 1 on the shaped fixtures: every group judged, contacts listed apart (T025).

SC-001: on the fixture shaped like 830-02342 every detected interference group is judged -
against 6 of 113 in the recorded review - and no zero-volume contact occupies a "Start here"
slot. The small fixture, shaped like 810-11249, carries the pin whose two zero-volume rows
took two of those slots in the recorded evening run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.interference import CONTACT_VOLUME_MM3, interference_outcomes
from swreview.ir.loader import load_package
from swreview.prerun import prerun_checks
from swreview.report.attention import rank
from swreview.report.session import ReviewSession
from swreview.tools import checks_interference
from swreview.tools.context import ToolContext, build_context, use_context
from swreview.tools.registry import ToolRegistry
from tests.support.prerun import ON

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"


def context_of(name: str) -> ToolContext:
    return build_context(load_package(FIXTURES / name))


def judge_every_group(context: ToolContext) -> ReviewSession:
    """Call the tool once per group key, as the pre-run and a thorough model would."""
    with use_context(context):
        for key in dict.fromkeys(
            group.group_key for group in checks_interference.groups_of(context.ir)
        ):
            result = checks_interference.check_interference_group(key)
            assert "error" not in result, result
    return context.require_session()


@pytest.fixture(scope="module")
def big_session() -> tuple[ToolContext, ReviewSession]:
    context = context_of("big-assembly")
    return context, judge_every_group(context)


def test_every_one_of_the_113_groups_is_judged(big_session) -> None:
    context, session = big_session

    outcomes = interference_outcomes(session, context.ir)

    assert outcomes == {
        "groups": 113,
        "findings": 8,
        "contacts": 105,
        "unresolved": 0,
        "excepted": 0,
    }
    assert outcomes["findings"] + outcomes["contacts"] == outcomes["groups"]


def test_every_interference_finding_carries_a_real_overlap(big_session) -> None:
    _, session = big_session

    for finding in session.findings:
        assert finding.check == "interference.static"
        assert finding.status == "demonstrated"
        assert finding.calculation is not None
        assert float(finding.calculation.result["max_volume_mm3"]) > CONTACT_VOLUME_MM3


def test_no_contact_and_no_zero_volume_group_reaches_the_ranking(big_session) -> None:
    """SC-001: the ranking reads findings only, so a contact cannot take a slot."""
    _, session = big_session

    ranking = rank(session)

    finding_ids = {finding.id for finding in session.findings}
    ranked = [member for row in ranking.rows for member in row.member_finding_ids]
    assert ranked and set(ranked) <= finding_ids
    contact_groups = {contact.group_key for contact in session.contacts}
    by_id = {finding.id: finding for finding in session.findings}
    for finding_id in ranked:
        result = by_id[finding_id].calculation.result  # type: ignore[union-attr]
        assert result["group_key"] not in contact_groups
        assert float(result["max_volume_mm3"]) > CONTACT_VOLUME_MM3


def test_the_contacts_are_numbered_and_cite_the_groups_they_came_from(big_session) -> None:
    _, session = big_session

    assert [contact.id for contact in session.contacts][:3] == ["C-001", "C-002", "C-003"]
    assert len({contact.group_key for contact in session.contacts}) == 105
    kinds = {contact.kind for contact in session.contacts}
    assert kinds == {"zero_volume", "possible_only"}


def test_the_small_fixture_yields_one_contact_naming_the_pin_and_the_plate() -> None:
    session = judge_every_group(context_of("small-assembly"))

    assert session.findings == []
    [contact] = session.contacts
    assert contact.component_ids == ["cmp:0001", "cmp:0003"]
    assert contact.interference_ids == ["int:0001", "int:0002"]
    assert contact.kind == "zero_volume"


def pre_run_lines(name: str) -> dict[str, str]:
    context = context_of(name)
    dispatch = ToolRegistry().dispatch(context)
    result = prerun_checks(context, dispatch, efficiency=ON)
    assert result is not None
    return {
        call.label: call.line() for call in result.calls if call.tool == "check_interference_group"
    }


def test_with_lever_5_on_a_contact_group_reads_one_contact() -> None:
    lines = pre_run_lines("small-assembly")

    assert lines == {
        "check_interference_group(group_key='cmp:0001|cmp:0003')": (
            "  check_interference_group(group_key='cmp:0001|cmp:0003') -> ok, 1 contact"
        )
    }


def test_with_lever_5_on_a_finding_group_reads_one_finding() -> None:
    lines = pre_run_lines("big-assembly")

    assert lines["check_interference_group(group_key='cmp:0001|cmp:0003')"].endswith(
        "-> ok, 1 finding"
    )
    assert sum(line.endswith("-> ok, 1 contact") for line in lines.values()) == 105
