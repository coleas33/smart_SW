"""The house rules (feature 010 T070, `contracts/hygiene.md` sections 1 and 2).

Five checks over the part and assembly documents the component tree reaches, each once,
reading their property names from the standards profile (version 2) so no company value is
compiled into the source:

- the part-number property matches the file name's stem (the configuration property first);
- no two different documents share a description, or a part number - one finding per value;
- every model carries its revision;
- every lightweight or suppressed component of the reviewed configuration is a finding.

A check whose setting is absent (a version 1 profile), empty, or has no profile at all is one
skipped item naming the setting. Passes are counted, never findings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks import hygiene
from swreview.checks.hygiene import (
    CHECK_COMPONENT_NOT_RESOLVED,
    CHECK_COVERAGE,
    CHECK_DUPLICATE_DESCRIPTION,
    CHECK_DUPLICATE_PART_NUMBER,
    CHECK_PART_NUMBER,
    CHECK_REVISION,
    HYGIENE_CHECKS,
    HygieneChecks,
    run_hygiene_checks,
)
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from tests.support.mechanical import HYGIENE_PROPERTIES, PackageBuilder

REVIEWER = Path(__file__).resolve().parents[1].parent
PROFILE_A = REVIEWER / "tests" / "fixtures" / "standards" / "profile-a.yaml"
FIXTURES = REVIEWER / "tests" / "fixtures" / "mechanical"
PART_NUMBER, SUMMARY, REVISION = HYGIENE_PROPERTIES


@pytest.fixture(scope="module")
def profile() -> StandardsProfile:
    return load_profile(PROFILE_A)


def version_1(profile: StandardsProfile) -> StandardsProfile:
    return profile.model_copy(update={"version": 1, "hygiene": None, "general_tolerance": None})


def findings_of(checks: HygieneChecks, check: str) -> list:
    return [item for item in checks.findings if item.result.check == check]


def props(
    stem: str, summary: str, *, part_number: str | None = None, revision: str | None = "A"
) -> dict[str, str]:
    values = {PART_NUMBER: part_number if part_number is not None else stem, SUMMARY: summary}
    if revision is not None:
        values[REVISION] = revision
    return values


def package_of(
    *parts: tuple[str, dict[str, str]], suppression: str = "resolved"
) -> EvidencePackage:
    builder = PackageBuilder(
        design_stem="FICT-KALO-0000", root_properties=props("FICT-KALO-0000", "KALO ROOT")
    )
    for index, (stem, properties) in enumerate(parts, start=1):
        document = builder.document(stem, "part", material="6061-T6", properties=properties)
        builder.component(
            document,
            component_id=f"cmp:{index:04d}",
            suppression=suppression if index == len(parts) else "resolved",  # type: ignore[arg-type]
        )
    return builder.build().package


# --- hygiene.part_number_matches_file ---------------------------------------------------------


def test_a_part_number_that_is_the_stem_passes_and_is_counted(profile) -> None:
    checks = run_hygiene_checks(
        package_of(("FICT-MIR-0001", props("FICT-MIR-0001", "MIR"))), profile
    )

    assert findings_of(checks, CHECK_PART_NUMBER) == []
    [item] = [item for item in checks.checked if item.check == CHECK_PART_NUMBER]
    assert item.reason == "2 documents: the part number matches the file name"


def test_the_comparison_is_stripped_and_case_insensitive(profile) -> None:
    package = package_of(
        ("FICT-MIR-0001", props("FICT-MIR-0001", "MIR", part_number=" fict-mir-0001 "))
    )

    assert findings_of(run_hygiene_checks(package, profile), CHECK_PART_NUMBER) == []


def test_a_part_number_that_differs_from_the_stem_is_demonstrated_with_both(profile) -> None:
    package = package_of(
        ("FICT-MIR-0001", props("FICT-MIR-0001", "MIR", part_number="FICT-MIR-0091"))
    )

    [finding] = findings_of(run_hygiene_checks(package, profile), CHECK_PART_NUMBER)

    assert (finding.result.status, finding.result.severity) == ("demonstrated", "low")
    assert finding.result.observed == (
        "FICT-MIR-0001.SLDPRT has Meridian Part Ref 'FICT-MIR-0091', which is not its file name "
        "'FICT-MIR-0001'"
    )
    assert finding.component_ids == ("cmp:0001",)


def test_a_missing_part_number_property_is_demonstrated(profile) -> None:
    properties = props("FICT-MIR-0001", "MIR")
    del properties[PART_NUMBER]

    [finding] = findings_of(
        run_hygiene_checks(package_of(("FICT-MIR-0001", properties)), profile), CHECK_PART_NUMBER
    )

    assert finding.result.observed == "FICT-MIR-0001.SLDPRT has no Meridian Part Ref"


def test_the_configuration_property_is_read_before_the_custom_one(profile) -> None:
    package = package_of(("FICT-MIR-0001", props("FICT-MIR-0001", "MIR", part_number="WRONG-0001")))
    documents = [
        item.model_copy(update={"config_properties": {"Default": {PART_NUMBER: "FICT-MIR-0001"}}})
        if item.file_name == "FICT-MIR-0001.SLDPRT"
        else item
        for item in package.documents
    ]
    package = package.model_copy(update={"documents": documents})

    assert findings_of(run_hygiene_checks(package, profile), CHECK_PART_NUMBER) == []


def test_property_names_match_whatever_their_case(profile) -> None:
    properties = {PART_NUMBER.upper(): "FICT-MIR-0001", SUMMARY: "MIR", REVISION: "A"}

    checks = run_hygiene_checks(package_of(("FICT-MIR-0001", properties)), profile)

    assert findings_of(checks, CHECK_PART_NUMBER) == []


# --- the duplicates -----------------------------------------------------------------------------


def test_two_documents_sharing_a_description_are_one_finding_naming_both(profile) -> None:
    package = package_of(
        ("FICT-MIR-0001", props("FICT-MIR-0001", "Venta Lori")),
        ("FICT-VEN-0002", props("FICT-VEN-0002", " VENTA LORI ")),
        ("FICT-SORN-0003", props("FICT-SORN-0003", "SORN")),
    )

    [finding] = findings_of(run_hygiene_checks(package, profile), CHECK_DUPLICATE_DESCRIPTION)

    assert finding.result.status == "demonstrated"
    assert finding.result.observed == (
        "2 documents share the Meridian Summary 'Venta Lori': FICT-MIR-0001.SLDPRT, "
        "FICT-VEN-0002.SLDPRT"
    )
    assert finding.component_ids == ("cmp:0001", "cmp:0002")


def test_one_document_instanced_twice_is_never_a_duplicate_of_itself(profile) -> None:
    builder = PackageBuilder(
        design_stem="FICT-KALO-0000", root_properties=props("FICT-KALO-0000", "R")
    )
    document = builder.document("FICT-MIR-0001", "part", properties=props("FICT-MIR-0001", "MIR"))
    builder.component(document, component_id="cmp:0001")
    builder.component(document, component_id="cmp:0002")

    checks = run_hygiene_checks(builder.build().package, profile)

    assert findings_of(checks, CHECK_DUPLICATE_DESCRIPTION) == []
    assert findings_of(checks, CHECK_DUPLICATE_PART_NUMBER) == []


def test_two_documents_sharing_a_part_number_are_one_finding(profile) -> None:
    package = package_of(
        ("FICT-MIR-0001", props("FICT-MIR-0001", "MIR", part_number="FICT-0001")),
        ("FICT-VEN-0002", props("FICT-VEN-0002", "VEN", part_number="fict-0001")),
    )

    [finding] = findings_of(run_hygiene_checks(package, profile), CHECK_DUPLICATE_PART_NUMBER)

    assert finding.result.observed.startswith("2 documents share the Meridian Part Ref 'FICT-0001'")


def test_an_empty_value_is_never_a_duplicate(profile) -> None:
    package = package_of(
        ("FICT-MIR-0001", props("FICT-MIR-0001", " ")),
        ("FICT-VEN-0002", props("FICT-VEN-0002", "")),
    )

    assert findings_of(run_hygiene_checks(package, profile), CHECK_DUPLICATE_DESCRIPTION) == []


# --- the revision --------------------------------------------------------------------------------


@pytest.mark.parametrize("revision", [None, "", "   "])
def test_a_model_with_no_revision_is_demonstrated(profile, revision: str | None) -> None:
    properties = props("FICT-MIR-0001", "MIR", revision=revision)

    [finding] = findings_of(
        run_hygiene_checks(package_of(("FICT-MIR-0001", properties)), profile), CHECK_REVISION
    )

    assert finding.result.observed == "FICT-MIR-0001.SLDPRT carries no MeridianRev"


def test_the_revision_check_runs_on_a_version_1_profile(profile) -> None:
    """`revision.property` is a version 1 setting, so the check needs no version 2 profile."""
    properties = props("FICT-MIR-0001", "MIR", revision=None)

    checks = run_hygiene_checks(package_of(("FICT-MIR-0001", properties)), version_1(profile))

    assert len(findings_of(checks, CHECK_REVISION)) == 1


# --- unresolved components ------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["lightweight", "suppressed"])
def test_a_lightweight_or_suppressed_component_is_a_finding_naming_it(profile, state: str) -> None:
    package = package_of(
        ("FICT-MIR-0001", props("FICT-MIR-0001", "MIR")),
        ("FICT-VEN-0002", props("FICT-VEN-0002", "VEN")),
        suppression=state,
    )

    [finding] = findings_of(run_hygiene_checks(package, profile), CHECK_COMPONENT_NOT_RESOLVED)

    assert finding.result.observed == (
        f"1 instance of FICT-VEN-0002.SLDPRT is {state} in the reviewed configuration: cmp:0002"
    )
    assert finding.component_ids == ("cmp:0002",)


def test_an_unloaded_component_is_left_to_coverage(profile) -> None:
    package = package_of(("FICT-MIR-0001", props("FICT-MIR-0001", "MIR")))
    components = [
        item.model_copy(update={"suppression": "unloaded"}) for item in package.components
    ]

    checks = run_hygiene_checks(package.model_copy(update={"components": components}), profile)

    assert findings_of(checks, CHECK_COMPONENT_NOT_RESOLVED) == []


def test_the_component_check_needs_no_profile() -> None:
    package = package_of(
        ("FICT-MIR-0001", props("FICT-MIR-0001", "MIR")),
        ("FICT-VEN-0002", {}),
        suppression="lightweight",
    )

    checks = run_hygiene_checks(package, None)

    assert len(findings_of(checks, CHECK_COMPONENT_NOT_RESOLVED)) == 1


# --- settings missing ---------------------------------------------------------------------------


def skipped_reasons(checks: HygieneChecks) -> dict[str, str]:
    return {item.check: item.reason for item in checks.skipped}


def test_a_version_1_profile_skips_the_property_checks_naming_the_setting(profile) -> None:
    checks = run_hygiene_checks(
        package_of(("FICT-MIR-0001", props("FICT-MIR-0001", "MIR", part_number="X"))),
        version_1(profile),
    )

    reasons = skipped_reasons(checks)
    assert reasons[CHECK_PART_NUMBER] == (
        "hygiene.part_number_matches_file not evaluated: the standards profile names no "
        "part-number property (hygiene.part_number_property)"
    )
    assert reasons[CHECK_DUPLICATE_PART_NUMBER].endswith("(hygiene.part_number_property)")
    assert reasons[CHECK_DUPLICATE_DESCRIPTION] == (
        "hygiene.duplicate_description not evaluated: the standards profile names no "
        "description property (hygiene.description_property)"
    )
    assert findings_of(checks, CHECK_PART_NUMBER) == []


def test_an_empty_setting_skips_its_checks(profile) -> None:
    assert profile.hygiene is not None
    empty = profile.model_copy(
        update={"hygiene": profile.hygiene.model_copy(update={"description_property": ""})}
    )

    reasons = skipped_reasons(
        run_hygiene_checks(package_of(("FICT-MIR-0001", props("FICT-MIR-0001", "MIR"))), empty)
    )

    assert set(reasons) == {CHECK_DUPLICATE_DESCRIPTION}


def test_no_profile_skips_every_property_check_and_runs_the_component_check() -> None:
    reasons = skipped_reasons(
        run_hygiene_checks(package_of(("FICT-MIR-0001", props("FICT-MIR-0001", "MIR"))), None)
    )

    assert set(reasons) == {
        CHECK_PART_NUMBER,
        CHECK_DUPLICATE_DESCRIPTION,
        CHECK_DUPLICATE_PART_NUMBER,
        CHECK_REVISION,
    }
    assert reasons[CHECK_REVISION] == (
        "hygiene.revision_present not evaluated: no standards profile is attached, so no "
        "revision property is named (revision.property)"
    )


def test_unread_documents_are_named_in_one_coverage_item(profile) -> None:
    builder = PackageBuilder(
        design_stem="FICT-KALO-0000", root_properties=props("FICT-KALO-0000", "R")
    )
    unread = builder.document("FICT-OKTA-0001", "part", opened=False)
    builder.component(unread, component_id="cmp:0001", suppression="lightweight")

    checks = run_hygiene_checks(builder.build().package, profile)

    reasons = skipped_reasons(checks)
    assert reasons[CHECK_COVERAGE] == (
        "1 document's properties were not read, so the property checks did not see it: "
        "FICT-OKTA-0001.SLDPRT"
    )


def test_every_check_id_is_listed() -> None:
    assert HYGIENE_CHECKS == (
        CHECK_PART_NUMBER,
        CHECK_DUPLICATE_DESCRIPTION,
        CHECK_DUPLICATE_PART_NUMBER,
        CHECK_REVISION,
        CHECK_COMPONENT_NOT_RESOLVED,
    )


def test_no_property_name_is_in_the_source() -> None:
    """Company property names are the profile's to declare (the no-company-values rule)."""
    source = Path(hygiene.__file__).read_text(encoding="utf-8")

    for name in (*HYGIENE_PROPERTIES, "Part Number", "Description", "Revision"):
        assert f'"{name}"' not in source and f"'{name}'" not in source


# --- the big fixture (contracts/hygiene.md section 5) ------------------------------------------


@pytest.fixture(scope="module")
def big(profile) -> HygieneChecks:
    return run_hygiene_checks(load_package(FIXTURES / "big-assembly").package, profile)


def test_the_big_fixture_part_number_that_is_not_its_file_name(big) -> None:
    [finding] = findings_of(big, CHECK_PART_NUMBER)

    assert finding.result.observed.startswith("FICT-VENTAMIR-1002.SLDPRT has Meridian Part Ref")


def test_the_big_fixture_shared_summary_is_one_finding(big) -> None:
    [finding] = findings_of(big, CHECK_DUPLICATE_DESCRIPTION)

    assert finding.result.observed == (
        "2 documents share the Meridian Summary 'VENTA LORI': FICT-OMBRANIXA-1008.SLDPRT, "
        "FICT-TULMZEPH-1007.SLDPRT"
    )


def test_the_big_fixture_model_without_a_revision(big) -> None:
    [finding] = findings_of(big, CHECK_REVISION)

    assert finding.result.observed == "FICT-PELINSORN-1004.SLDPRT carries no MeridianRev"


def test_the_big_fixture_unresolved_components_one_per_document(big) -> None:
    states = sorted(
        item.result.observed.split(" is ", 1)[1].split(" ", 1)[0]
        for item in findings_of(big, CHECK_COMPONENT_NOT_RESOLVED)
    )

    assert states == ["lightweight", "lightweight", "suppressed"]
    assert findings_of(big, CHECK_DUPLICATE_PART_NUMBER) == []


def test_the_big_fixture_with_a_version_1_profile(profile) -> None:
    checks = run_hygiene_checks(load_package(FIXTURES / "big-assembly").package, version_1(profile))

    assert findings_of(checks, CHECK_PART_NUMBER) == []
    assert CHECK_PART_NUMBER in skipped_reasons(checks)
    assert len(findings_of(checks, CHECK_COMPONENT_NOT_RESOLVED)) == 3
