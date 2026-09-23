"""Unit tests for the IR 1.2.0 addition: `extractor.profile` (T065).

The Model check tab dumps a part with four phases switched off, so a package written by
that profile is legitimately missing holes, fasteners, faces and bodies. `profile` is the
only way a reader can tell "this package was written thin on purpose" from "this dump
lost half its evidence", which is why it is recorded rather than inferred from which
arrays came back empty.

The member is optional with the default `"full"`: every 1.0.0 and 1.1.0 package predates
it and must still load, and the schema-major gate of feature 001 is untouched - 1.2.0 is
a minor bump, so 2.0.0 still raises.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from swreview.ir.models import (
    SCHEMA_VERSION,
    EvidencePackage,
    ExtractorInfo,
    UnsupportedSchemaVersionError,
)
from swreview.ir.schema import export_schema
from tests.golden.test_golden import case_dirs
from tests.support.contracts import load_contract
from tests.support.packages import build_package

GOLDEN_FIXTURES = Path(__file__).resolve().parents[1] / "golden" / "fixtures"
GOLDEN_FIXTURE_DIRS = case_dirs(GOLDEN_FIXTURES)


def build_extractor(**overrides: object) -> ExtractorInfo:
    fields: dict[str, object] = {
        "name": "SwReview.Extractor",
        "version": "0.1.0",
        "sw_version": None,
        "machine": "test",
    }
    fields.update(overrides)
    return ExtractorInfo(**fields)  # type: ignore[arg-type]


# --- the version bump -------------------------------------------------------------


def test_the_profile_bump_is_carried_by_the_current_schema_version() -> None:
    """1.2.0 is where `extractor.profile` arrived; 1.3.0 (T089) added the reuse fields
    beside it, 1.4.0 (006 T013) widened its enumeration with `standards` and 1.5.0
    (010 T077) added the tolerance evidence without touching it."""
    assert SCHEMA_VERSION == "1.5.0"
    assert build_package().schema_version == SCHEMA_VERSION


def test_the_schema_major_gate_is_unchanged() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "2.0.0"

    with pytest.raises(UnsupportedSchemaVersionError):
        EvidencePackage.model_validate_json(json.dumps(payload))


# --- extractor.profile ------------------------------------------------------------


def test_profile_defaults_to_full() -> None:
    assert build_extractor().profile == "full"
    assert build_package().extractor.profile == "full"


def test_a_model_check_profile_round_trips_through_json() -> None:
    package = build_package(extractor=build_extractor(profile="model_check"))

    restored = EvidencePackage.model_validate_json(package.model_dump_json())

    assert restored.extractor.profile == "model_check"
    assert restored == package


def test_the_profile_is_always_written_so_a_reader_never_has_to_guess() -> None:
    dumped = json.loads(build_package().model_dump_json())

    assert dumped["extractor"]["profile"] == "full"


@pytest.mark.parametrize("value", ["quick", "FULL", "model-check", "", None])
def test_an_unknown_profile_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        build_extractor(profile=value)


def test_a_one_one_zero_package_without_a_profile_loads_as_full() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "1.1.0"
    payload["extractor"].pop("profile")

    package = EvidencePackage.model_validate_json(json.dumps(payload))

    assert package.schema_version == "1.1.0"
    assert package.extractor.profile == "full"


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURE_DIRS, ids=lambda path: path.name)
def test_every_shipped_golden_fixture_loads_at_the_profile_it_declares(
    fixture: Path,
) -> None:
    """A fixture that names no profile loads as `full`; one that names a profile keeps it.

    The pre-1.2.0 fixtures declare none, which is the back-compat case this test was
    written for and still asserts. The re-modeler's fixtures declare `model_check`, because
    that is what feature 003 US6 dumps for a part opened alone and what the planner is fed;
    reading the declaration rather than assuming its absence keeps both true at once.
    """
    text = (fixture / "package.json").read_text(encoding="utf-8")
    declared = json.loads(text)["extractor"].get("profile")

    package = EvidencePackage.model_validate_json(text)

    assert package.extractor.profile == (declared or "full")


# --- the generated contract -------------------------------------------------------


def test_the_generated_schema_makes_profile_optional_with_the_three_values() -> None:
    """`standards` joined the enumeration in 1.4.0 (006 T013); the member stays optional
    and still defaults to `full`."""
    extractor = export_schema()["$defs"]["ExtractorInfo"]

    assert "profile" not in extractor["required"]
    assert extractor["properties"]["profile"]["default"] == "full"
    assert sorted(extractor["properties"]["profile"]["enum"]) == [
        "full",
        "model_check",
        "standards",
    ]


@pytest.mark.parametrize("profile", ["full", "model_check"])
def test_both_profiles_validate_against_the_committed_contract(profile: str) -> None:
    sample = build_package(extractor=build_extractor(profile=profile)).model_dump(mode="json")

    validator = Draft202012Validator(
        load_contract("ir.schema.json"),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(sample), key=lambda error: list(error.absolute_path))

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_the_committed_contract_rejects_an_unknown_profile() -> None:
    sample = build_package().model_dump(mode="json")
    sample["extractor"]["profile"] = "quick"

    validator = Draft202012Validator(load_contract("ir.schema.json"))

    assert list(validator.iter_errors(sample)) != []
