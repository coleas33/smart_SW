"""A thread modelled as a cylinder is a contact, bounded (feature 010 T048, `contracts/
contacts.md` section 1 rule 5, research R2.10).

A screw modelled at its major diameter in a tap-drill bore overlaps the plate by exactly
the annulus between the two, `pi/4 (d^2 - D^2) L`. That overlap is the thread model, not a
clash, and it is a contact linked to the joint - but only up to that bound, and only between
the screw and the part it threads into, so the rule cannot hide a real overlap (Principle VI
forbids blanket exclusions).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from swreview.checks.fastener_identity import recognise_fasteners
from swreview.checks.interference import classify_group, group_interferences
from swreview.checks.joints import JointMap, build_joint_map
from swreview.ir.models import EvidencePackage
from swreview.tools.checks_interference import check_interference_group
from swreview.tools.context import context_for, use_context
from tests.support.mechanical import Face, Instance, PackageBuilder

Z = (0.0, 0.0, 1.0)
BOUND_MM3 = math.pi / 4.0 * (5.0**2 - 4.2**2) * 6.0
"""An M5 screw at its major diameter, a 4.2 mm tap-drill bore, 6 mm of overlap: 34.68 mm3."""


def package_with(volume_mm3: float, *, other: str = "cmp:0001", shank_mm: float = 5.0) -> tuple[
    EvidencePackage, JointMap
]:
    """A plate with a blind M5 tap, an M5x16 screw 6 mm into it, a third part, and one
    interference row between the screw and `other`."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    plate = builder.document("FICT-KALOMIR-0001", "part", material="Alloy Steel")
    builder.component(plate, component_id="cmp:0001")
    block = builder.document("FICT-KALOVEN-0003", "part", material="Alloy Steel")
    builder.component(block, component_id="cmp:0003")
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M5x0.8",
        thread="M5x0.8",
        thread_depth_mm=10.0,
        end_condition="blind",
        instances=[Instance((0.0, 0.0, 0.0), Z, (Face(4.2, -12.0, 0.0),))],
    )
    screw_document = builder.screw_document("SHC", "M5-0.8", 16.0, serial=1)
    builder.screw(
        screw_document,
        bearing_mm=(0.0, 0.0, 10.0),
        direction=Z,
        component_id="cmp:0002",
        shank_face_mm=shank_mm,
    )
    builder.interference("cmp:0002", other, volume_mm3=volume_mm3)
    package = builder.build().package
    return package, build_joint_map(package, fasteners=recognise_fasteners(package))


def outcome_of(volume_mm3: float, **options: Any):
    package, joint_map = package_with(volume_mm3, **options)
    [group] = group_interferences(package)
    return classify_group(group, package, None, joint_map=joint_map)


def test_an_overlap_within_the_annulus_is_a_thread_model_contact_linked_to_the_joint() -> None:
    outcome = outcome_of(round(BOUND_MM3 - 0.01, 6))

    assert outcome.finding is None
    assert outcome.contact is not None
    assert outcome.contact.kind == "thread_model"
    assert outcome.contact.joint_id == "jnt:0001"
    assert outcome.contact.volume_mm3 == pytest.approx(BOUND_MM3 - 0.01)
    assert "a thread modelled as a cylinder explains in joint jnt:0001" in outcome.contact.reason
    assert "34.683" in outcome.contact.reason


def test_an_overlap_at_exactly_the_bound_is_still_a_contact() -> None:
    """Volumes are compared to 1e-9 mm3, the precision `volume_mm3` reports them in."""
    outcome = outcome_of(round(BOUND_MM3, 9))

    assert outcome.contact is not None and outcome.contact.kind == "thread_model"


def test_an_overlap_above_the_bound_stays_a_finding() -> None:
    outcome = outcome_of(round(BOUND_MM3 + 0.01, 6))

    assert outcome.contact is None
    assert outcome.finding is not None
    assert outcome.finding.status == "demonstrated"


def test_an_overlap_with_a_part_the_screw_is_not_jointed_with_stays_a_finding() -> None:
    outcome = outcome_of(1.0, other="cmp:0003")

    assert outcome.contact is None and outcome.finding is not None


def test_without_the_joint_map_the_rule_does_not_fire() -> None:
    package, _ = package_with(1.0)
    [group] = group_interferences(package)

    outcome = classify_group(group, package, None)

    assert outcome.finding is not None


def test_a_screw_modelled_at_its_minor_diameter_never_reaches_the_rule() -> None:
    """It overlaps nothing: SOLIDWORKS reports zero, which is rule 4's contact."""
    outcome = outcome_of(0.0, shank_mm=4.2)

    assert outcome.contact is not None
    assert outcome.contact.kind == "zero_volume"


def test_a_screw_whose_shank_contradicts_its_name_has_no_bound() -> None:
    """An untrusted size cannot bound anything: the finding stands."""
    outcome = outcome_of(1.0, shank_mm=3.3)

    assert outcome.finding is not None and outcome.contact is None


def test_the_tool_records_the_thread_model_contact_with_its_joint() -> None:
    package, _ = package_with(round(BOUND_MM3 / 2.0, 6))
    context = context_for(package)
    [group] = group_interferences(package)

    with use_context(context):
        result = check_interference_group(group_key=group.group_key)

    assert result["status"] == "contact"
    [contact] = context.require_session().contacts
    assert (contact.kind, contact.joint_id) == ("thread_model", "jnt:0001")
    assert context.require_session().findings == []


def test_the_tool_builds_the_joint_map_once_per_context() -> None:
    package, _ = package_with(round(BOUND_MM3 / 2.0, 6))
    context = context_for(package)
    [group] = group_interferences(package)

    with use_context(context):
        check_interference_group(group_key=group.group_key)
        first = context.joint_analysis
        check_interference_group(group_key=group.group_key)

    assert first is not None and context.joint_analysis is first
