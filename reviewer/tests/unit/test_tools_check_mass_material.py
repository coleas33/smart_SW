"""`check_mass_material`, the argument-free mass and material tool (feature 010 T066).

`contracts/code-first.md` section 3 and `contracts/mass-material.md` section 5: the tool
takes no argument, records the passes of `mass.material_assigned` as one `checked` item and
every density verdict as a finding, counts what was not read in one skipped item, and
returns counts rather than a payload. It is a check tool and the second name in
`CODE_FIRST_CHECKS` (T067), so the pre-run calls it after `check_joints` at no model round.
"""

from __future__ import annotations

import inspect
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from swreview.ir.loader import load_package
from swreview.tools import checks_mechanical
from swreview.tools.checks_mechanical import check_mass_material
from swreview.tools.context import ToolContext, build_context, use_context
from swreview.tools.registry import ToolRegistry, check_tools

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"


def run(name: str) -> tuple[ToolContext, dict[str, Any]]:
    context = build_context(load_package(FIXTURES / name))
    with use_context(context):
        return context, check_mass_material()


@pytest.fixture(scope="module")
def big() -> tuple[ToolContext, dict[str, Any]]:
    return run("big-assembly")


def test_the_tool_takes_no_argument() -> None:
    assert inspect.signature(check_mass_material).parameters == {}


def test_it_is_a_check_tool_and_the_second_code_first_check() -> None:
    assert check_mass_material in check_tools()
    assert checks_mechanical.CODE_FIRST_CHECKS.index("check_mass_material") == 1


def test_through_the_registry_it_is_one_real_step_and_refuses_an_argument() -> None:
    context = build_context(load_package(FIXTURES / "small-assembly"))
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}

    assert tools["check_mass_material"].call({}).payload["status"] == "recorded"
    assert [step.tool for step in context.require_session().steps] == ["check_mass_material"]
    assert tools["check_mass_material"].call({"document_id": "doc:0001"}).is_error is True


def test_it_returns_counts_and_the_documents_it_reached(big) -> None:
    context, result = big
    session = context.require_session()

    assert result["status"] == "recorded"
    assert result["documents"] == 26
    assert result["findings"] == len(session.findings)
    assert result["finding_ids"] == [finding.id for finding in session.findings]
    assert result["coverage"] == {"checked": 1, "skipped": 1, "unresolved": 0}


def test_material_passes_are_one_checked_item_and_not_findings(big) -> None:
    context, _ = big
    session = context.require_session()

    [item] = [item for item in session.coverage.checked if item.check == "mass.material_assigned"]
    # 20 part documents were opened: 19 carry a material; the surface-only one does not.
    assert item.reason == "19 parts have a material or a deliberate mass override"
    assigned = [
        finding for finding in session.findings if finding.check == "mass.material_assigned"
    ]
    assert [finding.status for finding in assigned] == ["unresolved"]


def test_every_density_verdict_is_a_finding_with_its_calculation(big) -> None:
    context, _ = big

    density = [
        finding for finding in context.require_session().findings if finding.check == "mass.density"
    ]

    # The 19 parts with a material class and a volume: 18 in range, the steel one at 1000.
    assert Counter(finding.status for finding in density) == {
        "checked_within_scope": 18,
        "demonstrated": 1,
    }
    assert all(finding.calculation is not None for finding in density)
    [default] = [finding for finding in density if finding.status == "demonstrated"]
    assert default.observed.startswith("FICT-FENNARVO-1006.SLDPRT weighs")
    assert default.component_ids == ["cmp:0006"]


def test_the_round_sub_assembly_is_suspected_and_bound_to_its_instance(big) -> None:
    context, _ = big

    [override] = [
        finding
        for finding in context.require_session().findings
        if finding.check == "mass.assembly_override"
    ]

    assert override.status == "suspected"
    assert override.component_ids == ["cmp:0012"]


def test_the_unread_are_one_skipped_coverage_item(big) -> None:
    context, _ = big

    [item] = context.require_session().coverage.skipped
    assert item.check == "mass.coverage"
    assert item.reason.startswith("3 components were not read (lightweight 2, suppressed 1, ")


def test_every_part_with_a_mass_and_a_volume_has_a_verdict(big) -> None:
    """SC-005: a finding (density, or the material rule) or the counted material pass."""
    context, _ = big
    package = context.ir
    session = context.require_session()
    judged = {
        cid
        for finding in session.findings
        if finding.check in ("mass.density", "mass.material_assigned")
        for cid in finding.component_ids
    }
    parts = {
        item.document_id
        for item in package.documents
        if item.kind == "part" and item.mass is not None and item.mass.volume_m3 > 0
    }

    instances = [item for item in package.components if item.document_id in parts]
    assert instances and all(item.id in judged for item in instances)


def test_the_small_fixture_has_three_passing_densities_and_no_override() -> None:
    context, result = run("small-assembly")
    session = context.require_session()

    assert result["documents"] == 3
    assert Counter((finding.check, finding.status) for finding in session.findings) == {
        ("mass.density", "checked_within_scope"): 2
    }


def test_the_root_assembly_binds_to_its_document() -> None:
    """The root has no component instance, so an override finding names the document."""
    from tests.support.mechanical import PackageBuilder

    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    part = builder.document(
        "FICT-KALOMIR-0001", "part", material="6061-T6", mass_kg=0.27, volume_mm3=100_000.0
    )
    builder.component(part, component_id="cmp:0001")
    builder.set_mass(builder.root_id, 1.0, 100_000.0)
    package = builder.build().package
    from swreview.tools.context import context_for

    context = context_for(package)
    with use_context(context):
        check_mass_material()

    [override] = [
        finding
        for finding in context.require_session().findings
        if finding.check == "mass.assembly_override"
    ]
    assert override.component_ids == []
    assert [entry.document_id for entry in override.provenance] == ["doc:0001"]
