"""Every part has a believable mass and a material (feature 010 T064, `contracts/mass-material.md`
sections 2 and 3, research R2.16).

- `mass.material_assigned`: a part passes with a material, or with an override read as
  true; fails with neither when the override was read as false; is unresolved when there is
  no material and the override was not read. Passes are counted, not findings.
- `mass.density`: mass over volume against the material class's range; a density outside it
  is demonstrated, and one within 2 percent of SOLIDWORKS' no-material 1000 kg/m3 says so.
  Passes are findings with their calculation. An overridden part gets no density verdict.
- `mass.assembly_override`: an overridden assembly is suspected for confirmation; with the
  override unread, a mass that is not its read children's sum, or a round mass while a
  child was never read, is suspected.
- One `mass.coverage` item counts what was not read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.mass import (
    CHECK_ASSEMBLY_OVERRIDE,
    CHECK_COVERAGE,
    CHECK_DENSITY,
    CHECK_MATERIAL_ASSIGNED,
    MassChecks,
    run_mass_checks,
)
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from tests.support.mechanical import PackageBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"


def results_of(checks: MassChecks, check: str) -> list:
    return [item for item in checks.findings if item.result.check == check]


def one_part(
    *,
    material: str | None = "6061-T6",
    density: float | None = 2700.0,
    volume_mm3: float | None = 10_000.0,
    overridden: bool | None = None,
    opened: bool = True,
    suppression: str = "resolved",
) -> EvidencePackage:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    mass = None if density is None or volume_mm3 is None else volume_mm3 * 1e-9 * density
    document = builder.document(
        "FICT-KALOMIR-0001",
        "part",
        material=material,
        mass_kg=mass,
        volume_mm3=volume_mm3,
        opened=opened,
    )
    builder.component(document, component_id="cmp:0001", suppression=suppression)  # type: ignore[arg-type]
    package = builder.build().package
    if overridden is not None:
        documents = [
            item.model_copy(update={"mass_overridden": overridden})
            if item.document_id == document
            else item
            for item in package.documents
        ]
        gaps = [gap for gap in package.gaps if gap.entity_kind != "mass_override"]
        package = package.model_copy(update={"documents": documents, "gaps": gaps})
    return package


# --- mass.material_assigned ----------------------------------------------------------------


def test_a_part_with_a_material_passes_and_is_counted_not_reported() -> None:
    checks = run_mass_checks(one_part())

    assert results_of(checks, CHECK_MATERIAL_ASSIGNED) == []
    [item] = [item for item in checks.checked if item.check == CHECK_MATERIAL_ASSIGNED]
    assert item.reason == "1 part has a material or a deliberate mass override"
    assert item.scope.component_ids == ["cmp:0001"]


def test_no_material_and_an_override_read_as_true_passes() -> None:
    checks = run_mass_checks(one_part(material=None, overridden=True))

    assert results_of(checks, CHECK_MATERIAL_ASSIGNED) == []


def test_no_material_and_an_override_read_as_false_is_demonstrated() -> None:
    checks = run_mass_checks(one_part(material=None, overridden=False))

    [finding] = results_of(checks, CHECK_MATERIAL_ASSIGNED)
    assert (finding.result.status, finding.result.severity) == ("demonstrated", "medium")
    assert finding.result.observed.startswith(
        "FICT-KALOMIR-0001.SLDPRT has no material and its mass is not overridden"
    )
    assert finding.component_ids == ("cmp:0001",)


def test_no_material_and_an_unread_override_is_unresolved_naming_the_gap() -> None:
    checks = run_mass_checks(one_part(material=None))

    [finding] = results_of(checks, CHECK_MATERIAL_ASSIGNED)
    assert finding.result.status == "unresolved"
    assert "mass_override gap" in finding.result.observed
    assert "IMassProperty.OverrideMass could not be read" in finding.result.observed


def test_a_document_that_was_not_opened_is_not_checked_but_counted() -> None:
    checks = run_mass_checks(one_part(opened=False, suppression="lightweight"))

    assert checks.findings == ()
    [coverage] = checks.skipped
    assert coverage.check == CHECK_COVERAGE
    assert coverage.reason.startswith("1 component was not read (lightweight 1, suppressed 0, ")


# --- mass.density ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("material", "density", "status"),
    [
        ("6061-T6", 2700.0, "checked_within_scope"),
        ("6061-T6", 2600.0, "checked_within_scope"),
        ("6061-T6", 2850.0, "checked_within_scope"),
        ("6061-T6", 2900.0, "demonstrated"),
        ("Alloy Steel", 7850.0, "checked_within_scope"),
        ("Alloy Steel", 7000.0, "demonstrated"),
        ("PEEK", 1300.0, "checked_within_scope"),
    ],
)
def test_density_against_the_class_range(material: str, density: float, status: str) -> None:
    checks = run_mass_checks(one_part(material=material, density=density))

    [finding] = results_of(checks, CHECK_DENSITY)
    assert finding.result.status == status
    calculation = finding.result.calculation
    assert calculation is not None
    assert calculation.result["density_kg_m3"] == pytest.approx(density, rel=1e-6)


def test_a_density_outside_the_range_names_both_numbers_and_the_class_row() -> None:
    checks = run_mass_checks(one_part(material="6061-T6", density=2900.0))

    [finding] = results_of(checks, CHECK_DENSITY)
    assert finding.result.observed == (
        "FICT-KALOMIR-0001.SLDPRT weighs 0.029 kg for 10000.0 mm3: 2900.0 kg/m3, outside the "
        "2600.0 to 2850.0 kg/m3 of its material class aluminum (6061-T6)"
    )
    assert finding.result.severity == "medium"


@pytest.mark.parametrize("density", [1000.0, 980.0, 1020.0])
def test_a_named_material_at_the_no_material_default_says_so(density: float) -> None:
    """Within 2 percent of 1000 kg/m3 and outside the class's range: the mass is the
    no-material default, whatever the material field says."""
    checks = run_mass_checks(one_part(material="Alloy Steel", density=density))

    [finding] = results_of(checks, CHECK_DENSITY)
    assert finding.result.status == "demonstrated"
    assert "the density is SOLIDWORKS' no-material default" in finding.result.observed


def test_just_outside_2_percent_of_the_default_is_the_plain_range_finding() -> None:
    checks = run_mass_checks(one_part(material="Alloy Steel", density=1021.0))

    [finding] = results_of(checks, CHECK_DENSITY)
    assert "no-material default" not in finding.result.observed


def test_a_plastic_near_1000_is_inside_its_range_and_passes() -> None:
    """ABS is 1020 kg/m3 in SOLIDWORKS' library: inside the plastic range, not a default."""
    checks = run_mass_checks(one_part(material="ABS", density=1020.0))

    [finding] = results_of(checks, CHECK_DENSITY)
    assert finding.result.status == "checked_within_scope"


def test_an_overridden_part_gets_no_density_verdict() -> None:
    checks = run_mass_checks(one_part(material="6061-T6", density=9000.0, overridden=True))

    assert results_of(checks, CHECK_DENSITY) == []


@pytest.mark.parametrize(
    ("options", "why"),
    [
        ({"material": "unobtainium"}, "no material class with a density range"),
        ({"material": None}, "no material class with a density range"),
        ({"volume_mm3": None}, "no material class with a density range"),
    ],
)
def test_no_class_range_or_no_volume_is_not_checked_but_counted(
    options: dict, why: str
) -> None:
    checks = run_mass_checks(one_part(**options))

    assert results_of(checks, CHECK_DENSITY) == []
    [coverage] = checks.skipped
    assert "1 part has no material class with a density range or no volume" in coverage.reason
    del why


# --- mass.assembly_override -------------------------------------------------------------------


def assembly(
    *,
    root_mass: float,
    overridden: bool | None = None,
    child_suppression: str = "resolved",
    child_opened: bool = True,
) -> EvidencePackage:
    """An assembly of two 0.27 kg parts (0.54 kg together); the first one's state varies."""
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    first = builder.document(
        "FICT-KALOMIR-0001",
        "part",
        material="6061-T6",
        mass_kg=0.27,
        volume_mm3=100_000.0,
        opened=child_opened,
    )
    second = builder.document(
        "FICT-KALOVEN-0002", "part", material="6061-T6", mass_kg=0.27, volume_mm3=100_000.0
    )
    builder.component(first, component_id="cmp:0001", suppression=child_suppression)  # type: ignore[arg-type]
    builder.component(second, component_id="cmp:0002")
    builder.set_mass(builder.root_id, root_mass, 200_000.0)
    package = builder.build().package
    if overridden is not None:
        documents = [
            item.model_copy(update={"mass_overridden": overridden})
            if item.document_id == builder.root_id
            else item
            for item in package.documents
        ]
        package = package.model_copy(update={"documents": documents})
    return package


def test_an_overridden_assembly_is_suspected_for_confirmation() -> None:
    checks = run_mass_checks(assembly(root_mass=0.54, overridden=True))

    [finding] = results_of(checks, CHECK_ASSEMBLY_OVERRIDE)
    assert (finding.result.status, finding.result.severity) == ("suspected", "low")
    assert finding.result.observed == (
        "The assembly mass of FICT-KALO-0000.SLDASM is overridden; confirm 0.54 kg is intended"
    )
    assert finding.document_ids == ("doc:0001",)


def test_an_unread_override_whose_mass_is_the_childrens_sum_is_no_finding() -> None:
    checks = run_mass_checks(assembly(root_mass=0.54))

    assert results_of(checks, CHECK_ASSEMBLY_OVERRIDE) == []


def test_within_0_1_percent_of_the_sum_is_no_finding_and_beyond_it_is_suspected() -> None:
    assert results_of(run_mass_checks(assembly(root_mass=0.5405)), CHECK_ASSEMBLY_OVERRIDE) == []

    [finding] = results_of(run_mass_checks(assembly(root_mass=0.5406)), CHECK_ASSEMBLY_OVERRIDE)
    assert finding.result.status == "suspected"
    assert "0.5406 kg" in finding.result.observed and "0.54 kg" in finding.result.observed


def test_an_override_read_as_false_is_no_finding() -> None:
    assert results_of(
        run_mass_checks(assembly(root_mass=0.7, overridden=False)), CHECK_ASSEMBLY_OVERRIDE
    ) == []


def test_a_round_mass_while_a_child_was_never_read_is_suspected() -> None:
    package = assembly(root_mass=2.0, child_suppression="lightweight", child_opened=False)

    [finding] = results_of(run_mass_checks(package), CHECK_ASSEMBLY_OVERRIDE)

    assert finding.result.observed == (
        "The assembly mass of FICT-KALO-0000.SLDASM is a round 2.0 kg while 1 child was never "
        "read; it may be overridden"
    )


def test_a_round_mass_under_100_g_is_not_suspected() -> None:
    package = assembly(root_mass=0.05, child_suppression="lightweight", child_opened=False)

    assert results_of(run_mass_checks(package), CHECK_ASSEMBLY_OVERRIDE) == []


def test_a_mass_in_uneven_grams_with_an_unread_child_is_no_finding() -> None:
    package = assembly(root_mass=0.5437, child_suppression="lightweight", child_opened=False)

    assert results_of(run_mass_checks(package), CHECK_ASSEMBLY_OVERRIDE) == []


def test_an_assembly_is_never_given_a_density() -> None:
    checks = run_mass_checks(assembly(root_mass=0.54))

    assert "doc:0001" not in {item.document_id for item in results_of(checks, CHECK_DENSITY)}
    assert len(results_of(checks, CHECK_DENSITY)) == 2


# --- the fixtures (contracts/mass-material.md section 5) -----------------------------------------


@pytest.fixture(scope="module")
def big() -> MassChecks:
    return run_mass_checks(load_package(FIXTURES / "big-assembly").package)


def test_the_big_fixture_aluminium_at_2700_passes_and_steel_at_1000_is_demonstrated(big) -> None:
    density = {
        item.result.observed.split(" ", 1)[0]: item.result
        for item in results_of(big, CHECK_DENSITY)
    }

    assert density["FICT-VENTAMIR-1002.SLDPRT"].status == "checked_within_scope"
    assert density["FICT-FENNARVO-1006.SLDPRT"].status == "demonstrated"
    assert "no-material default" in density["FICT-FENNARVO-1006.SLDPRT"].observed
    assert density["FICT-BRUNKALO-1001.SLDPRT"].status == "checked_within_scope"


def test_the_big_fixture_2_kg_subassembly_is_suspected(big) -> None:
    [finding] = results_of(big, CHECK_ASSEMBLY_OVERRIDE)

    assert finding.result.observed == (
        "The assembly mass of FICT-OKTAVEN-0100.SLDASM is a round 2.0 kg while 3 children were "
        "never read; it may be overridden"
    )


def test_the_big_fixture_counts_what_was_not_read(big) -> None:
    [coverage] = big.skipped

    assert coverage.reason == (
        "3 components were not read (lightweight 2, suppressed 1, not opened 0); 3 bodies "
        "could not be read; 1 part has no material class with a density range or no volume"
    )
    assert coverage.scope.component_ids == ["cmp:0013", "cmp:0014", "cmp:0015", "cmp:0022",
                                            "cmp:0028"]


def test_every_part_with_a_mass_and_a_volume_has_a_verdict(big) -> None:
    """SC-005."""
    package = load_package(FIXTURES / "big-assembly").package
    with_mass = {
        item.document_id
        for item in package.documents
        if item.kind == "part" and item.mass is not None and item.mass.volume_m3 > 0
    }

    judged = {
        item.document_id
        for item in big.findings
        if item.result.check in (CHECK_DENSITY, CHECK_MATERIAL_ASSIGNED)
    }
    assert with_mass <= judged
    assert big.documents == 26


def test_the_surface_only_part_is_unresolved_for_its_material(big) -> None:
    [finding] = results_of(big, CHECK_MATERIAL_ASSIGNED)

    assert finding.result.status == "unresolved"
    assert finding.result.observed.startswith("whether the mass of FICT-LORITESSA-1010.SLDPRT")


def test_the_small_fixture_assembly_is_its_part_plus_two_pins() -> None:
    checks = run_mass_checks(load_package(FIXTURES / "small-assembly").package)

    assert results_of(checks, CHECK_ASSEMBLY_OVERRIDE) == []
    assert {item.result.status for item in results_of(checks, CHECK_DENSITY)} == {
        "checked_within_scope"
    }
