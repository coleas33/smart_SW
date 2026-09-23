"""A zero-volume or possible-only group is a contact, not an interference (feature 010 T017).

`contracts/contacts.md` section 1 is normative: `classify_group` decides, first match
wins, whether a detected group is a finding or a contact. Two parts touching at nominal size
- a 3.0 mm dowel in a 3.0 mm hole, coincident faces - are listed on their own so a
line-to-line fit stays visible, and never occupy a "Start here" slot again (SC-001, owner
decision 2026-09-23). A group with any real overlap stays the finding it is today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.interference import (
    CONTACT_VOLUME_MM3,
    GroupOutcome,
    check_interference_group,
    classify_group,
    group_interferences,
)
from swreview.exceptions import ExceptionStore
from swreview.ir.models import Volume
from tests.unit.test_checks_interference import accepted_store, interference, mm3, package_with


def outcome_of(*members, exceptions: ExceptionStore | None = None) -> GroupOutcome:
    package = package_with(list(members))
    return classify_group(group_interferences(package)[0], package, exceptions)


# --- rule 4: the contact --------------------------------------------------------------------


@pytest.mark.parametrize(
    "volume",
    [Volume(value=0.0, unit="mm3"), Volume(value=0.0, unit="m3"), Volume(value=0.0, unit="in3")],
    ids=["mm3", "m3", "in3"],
)
def test_a_zero_volume_in_any_unit_is_a_contact(volume: Volume) -> None:
    outcome = outcome_of(interference("int:1", "cmp:0001", "cmp:0002", volume=volume))

    assert outcome.finding is None
    assert outcome.contact is not None
    assert outcome.contact.kind == "zero_volume"
    assert outcome.contact.volume_mm3 == 0.0


def test_a_volume_of_exactly_the_contact_threshold_is_a_contact() -> None:
    outcome = outcome_of(
        interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(CONTACT_VOLUME_MM3))
    )

    assert outcome.contact is not None
    assert outcome.contact.volume_mm3 == CONTACT_VOLUME_MM3


def test_a_volume_just_above_the_contact_threshold_is_a_finding() -> None:
    outcome = outcome_of(interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(2e-6)))

    assert outcome.contact is None
    assert outcome.finding is not None
    assert outcome.finding.status == "demonstrated"


def test_no_volume_and_the_possible_flag_is_a_possible_only_contact() -> None:
    outcome = outcome_of(interference("int:1", "cmp:0001", "cmp:0002", is_possible=True))

    assert outcome.finding is None
    assert outcome.contact is not None
    assert outcome.contact.kind == "possible_only"
    assert outcome.contact.volume_mm3 is None


def test_no_volume_without_the_possible_flag_is_todays_suspected_finding() -> None:
    outcome = outcome_of(interference("int:1", "cmp:0001", "cmp:0002"))

    assert outcome.contact is None
    assert outcome.finding is not None
    assert outcome.finding.status == "suspected"


def test_a_zero_volume_member_beside_a_possible_one_is_a_zero_volume_contact() -> None:
    outcome = outcome_of(
        interference("int:1", "cmp:0001", "cmp:0002", group_key="k", volume=mm3(0.0)),
        interference("int:2", "cmp:0001", "cmp:0003", group_key="k", is_possible=True),
    )

    assert outcome.contact is not None
    assert outcome.contact.kind == "zero_volume"


def test_a_mixed_group_is_a_finding_whose_inputs_list_the_zero_volume_member() -> None:
    outcome = outcome_of(
        interference("int:1", "cmp:0001", "cmp:0002", group_key="k", volume=mm3(3.5)),
        interference("int:2", "cmp:0001", "cmp:0003", group_key="k", volume=mm3(0.0)),
    )

    assert outcome.contact is None
    assert outcome.finding is not None
    assert outcome.finding.status == "demonstrated"
    assert any("int:2" in str(item) and "0.0 mm3" in str(item) for item in outcome.finding.inputs)


def test_the_contact_names_both_parts_the_configuration_the_key_and_the_members() -> None:
    outcome = outcome_of(
        interference("int:1", "cmp:0002", "cmp:0001", group_key="k", volume=mm3(0.0)),
        interference("int:2", "cmp:0003", "cmp:0001", group_key="k", volume=mm3(0.0)),
    )

    contact = outcome.contact
    assert contact is not None
    assert contact.group_key == "k"
    assert contact.configuration == "Default"
    assert contact.interference_ids == ("int:1", "int:2")
    assert contact.component_ids == ("cmp:0001", "cmp:0002", "cmp:0003")
    assert contact.reason == (
        "cmp:0001 and cmp:0002, cmp:0003 touch at nominal in configuration Default: "
        "SOLIDWORKS reported 0.0 mm3 (2 pairs); this is a contact, not an interference."
    )


def test_a_possible_only_contact_says_so_in_its_reason() -> None:
    outcome = outcome_of(interference("int:1", "cmp:0001", "cmp:0002", is_possible=True))

    assert outcome.contact is not None
    assert outcome.contact.reason == (
        "cmp:0001 and cmp:0002 touch at nominal in configuration Default: SOLIDWORKS reported "
        "no overlap volume, only a possible interference (1 pair); this is a contact, not an "
        "interference."
    )


def test_a_converted_zero_volume_reads_as_it_was_reported() -> None:
    outcome = outcome_of(
        interference("int:1", "cmp:0001", "cmp:0002", volume=Volume(value=0.0, unit="in3"))
    )

    assert outcome.contact is not None
    assert "0.0 in3 (0.0 mm3)" in outcome.contact.reason


# --- precedence: rules 1 to 3 before the contact ------------------------------------------


def test_an_uncomputed_member_beats_the_contact() -> None:
    outcome = outcome_of(
        interference("int:1", "cmp:0001", "cmp:0002", group_key="k", volume=mm3(0.0)),
        interference("int:2", "cmp:0001", "cmp:0003", group_key="k", status="truncated"),
    )

    assert outcome.contact is None
    assert outcome.finding is not None
    assert outcome.finding.status == "unresolved"


def test_an_active_exception_beats_the_contact(tmp_path: Path) -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(0.0))]
    package = package_with(members)
    group = group_interferences(package)[0]
    store = accepted_store(package, tmp_path, "active")

    outcome = classify_group(group, package, store)

    assert outcome.contact is None
    assert outcome.finding is not None
    assert outcome.finding.status == "checked_within_scope"
    assert "exception:EX-001" in outcome.finding.coverage_limits


def test_a_needs_review_exception_beats_the_contact(tmp_path: Path) -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", is_possible=True)]
    package = package_with(members)
    group = group_interferences(package)[0]
    store = accepted_store(package, tmp_path, "needs_review")

    outcome = classify_group(group, package, store)

    assert outcome.contact is None
    assert outcome.finding is not None
    assert outcome.finding.status == "suspected"


# --- rules 1 to 3 and 6 are today's verdicts, byte for byte ---------------------------------


@pytest.mark.parametrize(
    "members",
    [
        [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(12.5))],
        [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(0.4))],
        [interference("int:1", "cmp:0001", "cmp:0002")],
        [interference("int:1", "cmp:0001", "cmp:0002", status="failed", error="boom")],
    ],
    ids=["high", "medium", "no-volume", "failed"],
)
def test_a_finding_group_is_exactly_what_check_interference_group_returns(members) -> None:
    package = package_with(members)
    group = group_interferences(package)[0]

    assert classify_group(group, package).finding == check_interference_group(group, package)


def test_the_joint_map_argument_is_accepted_and_changes_nothing_before_us4() -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(12.5))]
    package = package_with(members)
    group = group_interferences(package)[0]

    assert classify_group(group, package, joint_map=None) == classify_group(group, package)
