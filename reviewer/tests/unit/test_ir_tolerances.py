"""Unit tests for the IR 1.5.0 additions: the tolerance evidence (feature 010 T076).

`specs/010-mechanical-checks/data-model.md` section 10 and `contracts/tolerances.md`
section 1 are the normative list: one new optional member on an existing model
(`Hole.wizard`), two new optional package arrays (`model_dimensions`,
`model_annotations`) and four new models (`HoleWizardData`, `ModelDimension`,
`ModelAnnotation`, `GtolFrame`).

Every one of them obeys feature 006's additivity rule, and this file measures it:

- optional, with a default, and absent from `required`;
- **omitted when null** (a list, when it carries no rows), so every package written before
  1.5.0 - every golden, every fixture - re-serializes without gaining a member;
- 1.4.0 still loads, and 2.0.0 still raises.

What the extractor could verify on the 2024 SP5 interop shaped three of the fields (research
R2.23, reflected): `IWizardHoleFeatureData2.HoleFit` is an integer in
`swWzdHoleScrewClearanceTypes_e` (close, normal, loose) and applies to counterbore and
countersink holes only, so `fit_class_raw` records that member's name and never an ISO 286
class; the tolerance of a dimension is `IDimensionTolerance`, whose type has members the IR's
`Tolerance.kind` cannot express (MIN, MAX, FIT, BLOCK, GENERAL), so `tolerance` is null for
those and `tolerance_type_raw` says which; and a GTol's frames are read through the pre-2022
calls (`GetFrameValues`, `GetFrameSymbols3`) or, for a GTol in the 2022 format, through
`IGtolFrame.GetSymbolXml`, so each frame carries whichever answered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from swreview.ir.models import (
    SCHEMA_VERSION,
    Angle,
    EvidencePackage,
    GtolFrame,
    Hole,
    HoleWizardData,
    ModelAnnotation,
    ModelDimension,
    Quantity,
    SourceRef,
    Tolerance,
    UnsupportedSchemaVersionError,
)
from swreview.ir.schema import export_schema
from tests.support.contracts import load_contract
from tests.support.packages import build_package, persist_ref

TESTS_DIR = Path(__file__).resolve().parents[1]

COMMITTED_PACKAGES: list[Path] = sorted(TESTS_DIR.rglob("package.json"))
"""Every package committed under `reviewer/tests/`: the goldens, the standards and attention
fixtures, and feature 010's mechanical fixtures once they exist. None carries a 1.5.0 member:
the goldens predate the bump, and the builder-written fixtures declare whatever version their
builder wrote and still carry no tolerance evidence."""

NEW_MODELS: tuple[str, ...] = ("HoleWizardData", "ModelDimension", "ModelAnnotation", "GtolFrame")

NEW_PACKAGE_ARRAYS: tuple[str, ...] = ("model_dimensions", "model_annotations")

NEW_MEMBER_NAMES: frozenset[str] = frozenset({"wizard", *NEW_PACKAGE_ARRAYS})

WIZARD_LENGTHS: tuple[str, ...] = (
    "thru_hole_diameter",
    "tap_drill_diameter",
    "counterbore_diameter",
    "counterbore_depth",
    "countersink_diameter",
    "head_clearance",
)


# --- builders ---------------------------------------------------------------------------


def build_wizard(**overrides: Any) -> HoleWizardData:
    """Every field of a counterbore hole's wizard data, in the units SOLIDWORKS reports."""
    fields: dict[str, Any] = {
        "fit_class_raw": "swScrewClearanceNormal",
        "thread_class_raw": None,
        "thru_hole_diameter": Quantity(value=0.0066, unit="m"),
        "tap_drill_diameter": None,
        "counterbore_diameter": Quantity(value=0.011, unit="m"),
        "counterbore_depth": Quantity(value=0.0064, unit="m"),
        "countersink_diameter": None,
        "countersink_angle": None,
        "head_clearance": Quantity(value=0.0005, unit="m"),
    }
    fields.update(overrides)
    return HoleWizardData(**fields)


def build_hole(**overrides: Any) -> Hole:
    hole = build_package().holes[0]
    return hole.model_copy(update=overrides)


def build_tolerance(**overrides: Any) -> Tolerance:
    fields: dict[str, Any] = {
        "kind": "bilateral",
        "upper": Quantity(value=0.000015, unit="m"),
        "lower": Quantity(value=0.0, unit="m"),
        "source": SourceRef(
            document_id="doc:2",
            annotation="D1@Sketch1@housing.SLDPRT",
            persist_ref=persist_ref("mdm:0001"),
        ),
    }
    fields.update(overrides)
    return Tolerance(**fields)


def build_model_dimension(**overrides: Any) -> ModelDimension:
    fields: dict[str, Any] = {
        "id": "mdm:0001",
        "document_id": "doc:2",
        "feature_name": "Sketch1",
        "name": "D1@Sketch1@housing.SLDPRT",
        "dimension_type": "diameter",
        "dimension_type_raw": 6,
        "nominal": Quantity(value=0.01, unit="m"),
        "tolerance": build_tolerance(),
        "tolerance_type_raw": 8,
        "fit_hole_class": "H7",
        "fit_shaft_class": None,
        "persist_ref": persist_ref("mdm:0001"),
        "persist_ref_scope": "doc:2",
    }
    fields.update(overrides)
    return ModelDimension(**fields)


def build_gtol_frame(**overrides: Any) -> GtolFrame:
    fields: dict[str, Any] = {
        "number": 1,
        "symbols_raw": ["<GTOL-POSI>", "<MOD-MMC>", "", "", "", ""],
        "values_raw": ["0.05", "", "A", "B", ""],
        "symbol_xml_raw": None,
    }
    fields.update(overrides)
    return GtolFrame(**fields)


def build_gtol(**overrides: Any) -> ModelAnnotation:
    fields: dict[str, Any] = {
        "id": "man:0001",
        "document_id": "doc:2",
        "kind": "gtol",
        "frames": [build_gtol_frame()],
        "datum_identifier_raw": None,
        "label": None,
        "is_dimxpert": False,
        "attached_persist_refs": [persist_ref("fac:0001")],
        "persist_ref": persist_ref("man:0001"),
        "persist_ref_scope": "doc:2",
    }
    fields.update(overrides)
    return ModelAnnotation(**fields)


def build_datum(**overrides: Any) -> ModelAnnotation:
    fields: dict[str, Any] = {
        "id": "man:0002",
        "document_id": "doc:2",
        "kind": "datum",
        "label": "A",
        "attached_persist_refs": [persist_ref("fac:0002")],
    }
    fields.update(overrides)
    return ModelAnnotation(**fields)


def tolerance_package() -> EvidencePackage:
    """A 1.5.0 package carrying one of everything this feature adds."""
    package = build_package()
    return package.model_copy(
        update={
            "holes": [build_hole(wizard=build_wizard())],
            "model_dimensions": [build_model_dimension()],
            "model_annotations": [build_gtol(), build_datum()],
        }
    )


def json_paths(node: Any, prefix: str = "") -> set[str]:
    """Every key in `node` as a dotted path, list indices elided."""
    paths: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}"
            paths.add(path)
            paths |= json_paths(value, path)
    elif isinstance(node, list):
        for item in node:
            paths |= json_paths(item, f"{prefix}[]")
    return paths


# --- 1. the version bump ------------------------------------------------------------------


def test_the_bump_is_a_minor_one() -> None:
    """Every addition is optional, so the major does not move (FR-028)."""
    assert SCHEMA_VERSION == "1.5.0"
    assert build_package().schema_version == "1.5.0"


def test_a_one_four_zero_package_still_loads_with_the_new_members_absent() -> None:
    package = EvidencePackage.model_validate_json(
        build_package(schema_version="1.4.0").model_dump_json()
    )

    assert package.schema_version == "1.4.0"
    assert package.model_dimensions == []
    assert package.model_annotations == []
    assert package.holes[0].wizard is None


def test_the_schema_major_gate_is_unchanged() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "2.0.0"

    with pytest.raises(UnsupportedSchemaVersionError):
        EvidencePackage.model_validate_json(json.dumps(payload))


# --- 2. every committed package re-serializes without gaining a member -----------------


def test_the_committed_packages_are_found() -> None:
    """The walk finds the goldens, so an empty parametrization cannot pass silently."""
    assert len(COMMITTED_PACKAGES) >= 40, COMMITTED_PACKAGES


@pytest.mark.parametrize(
    "package_file",
    COMMITTED_PACKAGES,
    ids=[path.parent.relative_to(TESTS_DIR).as_posix() for path in COMMITTED_PACKAGES],
)
def test_a_committed_package_round_trips_without_gaining_or_losing_a_member(
    package_file: Path,
) -> None:
    """Additivity measured on the files themselves: a 1.5.0 member that appeared here would
    be a field serialized when it says nothing, which moves every package on disk at once."""
    on_disk = json.loads(package_file.read_bytes())
    package = EvidencePackage.model_validate_json(package_file.read_bytes())
    written = json.loads(package.model_dump_json())

    added = json_paths(written) - json_paths(on_disk)
    dropped = json_paths(on_disk) - json_paths(written)

    assert not dropped, f"{package_file} lost {sorted(dropped)}"
    leaked = {path for path in added if path.rsplit(".", 1)[-1] in NEW_MEMBER_NAMES}
    assert not leaked, f"{package_file} gained 1.5.0 members {sorted(leaked)}"


def test_a_package_carrying_none_of_this_evidence_writes_none_of_it() -> None:
    written = json.loads(build_package().model_dump_json())

    for array in NEW_PACKAGE_ARRAYS:
        assert array not in written
    assert "wizard" not in written["holes"][0]


# --- 3. HoleWizardData ------------------------------------------------------------------


def test_hole_wizard_data_carries_every_field_in_the_units_solidworks_reports() -> None:
    wizard = build_wizard(
        thread_class_raw="2B",
        tap_drill_diameter=Quantity(value=0.0042, unit="m"),
        countersink_diameter=Quantity(value=0.0104, unit="m"),
        countersink_angle=Angle(value=1.5707963267948966, unit="rad"),
    )

    assert wizard.fit_class_raw == "swScrewClearanceNormal"
    assert wizard.thread_class_raw == "2B"
    assert wizard.counterbore_diameter == Quantity(value=0.011, unit="m")
    assert wizard.countersink_angle == Angle(value=1.5707963267948966, unit="rad")


@pytest.mark.parametrize("field", WIZARD_LENGTHS)
def test_a_wizard_length_is_never_an_angle(field: str) -> None:
    with pytest.raises(ValidationError):
        build_wizard(**{field: {"value": 90.0, "unit": "deg"}})


@pytest.mark.parametrize("unit", ["mm", "in", "m"])
def test_the_countersink_angle_is_never_a_length(unit: str) -> None:
    with pytest.raises(ValidationError):
        build_wizard(countersink_angle={"value": 90.0, "unit": unit})


def test_hole_wizard_data_refuses_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        HoleWizardData.model_validate({"hole_fit": "H7"})


def test_hole_wizard_data_omits_its_unknowns() -> None:
    """A field the read could not answer is null plus a `hole_wizard` gap, and an absent key
    says the same, so the record carries only what was read."""
    written = json.loads(build_wizard().model_dump_json())

    assert "thread_class_raw" not in written
    assert "tap_drill_diameter" not in written
    assert written["fit_class_raw"] == "swScrewClearanceNormal"


def test_hole_wizard_data_with_nothing_read_is_an_empty_object() -> None:
    """Read, and nothing applied - which is not the same fact as a package that never read
    the wizard data (no `wizard` member at all)."""
    empty = HoleWizardData()

    assert json.loads(empty.model_dump_json()) == {}


def test_a_hole_without_wizard_data_writes_no_wizard() -> None:
    assert "wizard" not in json.loads(build_hole().model_dump_json())


def test_a_hole_with_wizard_data_round_trips() -> None:
    hole = build_hole(wizard=build_wizard())

    restored = Hole.model_validate_json(hole.model_dump_json())

    assert restored == hole
    assert restored.wizard is not None
    assert restored.wizard.counterbore_depth == Quantity(value=0.0064, unit="m")


def test_the_wizard_member_is_optional() -> None:
    assert not Hole.model_fields["wizard"].is_required()
    assert "wizard" not in export_schema()["$defs"]["Hole"].get("required", [])


# --- 4. ModelDimension ------------------------------------------------------------------


def test_a_model_dimension_validates() -> None:
    dimension = build_model_dimension()

    assert dimension.dimension_type == "diameter"
    assert dimension.tolerance is not None
    assert dimension.tolerance.kind == "bilateral"
    assert dimension.fit_hole_class == "H7"


@pytest.mark.parametrize("bad_id", ["mdm:001", "dim:0001", "mdm:abcd", "mdm0001", ""])
def test_a_model_dimension_id_follows_its_pattern(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        build_model_dimension(id=bad_id)


@pytest.mark.parametrize("kind", ["linear", "diameter", "radius", "angular", "other"])
def test_every_dimension_type_is_accepted(kind: str) -> None:
    assert build_model_dimension(dimension_type=kind).dimension_type == kind


def test_the_dimension_type_is_closed() -> None:
    with pytest.raises(ValidationError):
        build_model_dimension(dimension_type="ordinate")


def test_an_angular_dimension_carries_an_angle() -> None:
    dimension = build_model_dimension(
        dimension_type="angular",
        dimension_type_raw=3,
        nominal=Angle(value=1.5707963267948966, unit="rad"),
        tolerance=build_tolerance(
            kind="symmetric",
            upper=Angle(value=0.0087, unit="rad"),
            lower=Angle(value=-0.0087, unit="rad"),
        ),
        tolerance_type_raw=4,
        fit_hole_class=None,
    )

    assert isinstance(dimension.nominal, Angle)


def test_a_tolerance_the_ir_cannot_express_is_null_and_its_type_is_kept() -> None:
    """swTolFIT names classes and no numbers, and swTolMIN / MAX / BLOCK / GENERAL have no
    `Tolerance.kind`: the tolerance is null, never "none" (which means SOLIDWORKS said the
    dimension has no tolerance), and the raw type says which it was."""
    dimension = build_model_dimension(tolerance=None, tolerance_type_raw=7)

    written = json.loads(dimension.model_dump_json())

    assert "tolerance" not in written
    assert written["tolerance_type_raw"] == 7
    assert written["fit_hole_class"] == "H7"


def test_an_untoleranced_dimension_is_kind_none() -> None:
    dimension = build_model_dimension(
        tolerance=build_tolerance(kind="none", upper=None, lower=None),
        tolerance_type_raw=0,
        fit_hole_class=None,
    )

    assert dimension.tolerance is not None
    assert dimension.tolerance.kind == "none"


def test_a_model_dimension_refuses_an_unknown_field() -> None:
    payload = json.loads(build_model_dimension().model_dump_json())
    payload["tolerance_class"] = "H7"

    with pytest.raises(ValidationError):
        ModelDimension.model_validate(payload)


def test_a_model_dimension_omits_its_unknowns() -> None:
    dimension = build_model_dimension(
        dimension_type_raw=None,
        tolerance=None,
        tolerance_type_raw=None,
        fit_hole_class=None,
        persist_ref=None,
        persist_ref_scope=None,
    )

    assert json.loads(dimension.model_dump_json()) == {
        "id": "mdm:0001",
        "document_id": "doc:2",
        "feature_name": "Sketch1",
        "name": "D1@Sketch1@housing.SLDPRT",
        "dimension_type": "diameter",
        "nominal": {"value": 0.01, "unit": "m"},
    }


# --- 5. ModelAnnotation and GtolFrame ---------------------------------------------------


def test_a_gtol_annotation_validates() -> None:
    gtol = build_gtol()

    assert gtol.kind == "gtol"
    assert gtol.frames[0].values_raw[0] == "0.05"
    assert gtol.attached_persist_refs == [persist_ref("fac:0001")]


def test_a_gtol_frame_in_the_2022_format_carries_its_xml() -> None:
    frame = build_gtol_frame(symbols_raw=[], values_raw=[], symbol_xml_raw="<GTolFrame/>")

    written = json.loads(frame.model_dump_json())

    assert written == {"number": 1, "symbol_xml_raw": "<GTolFrame/>"}


@pytest.mark.parametrize("number", [0, -1])
def test_a_gtol_frame_number_is_one_based(number: int) -> None:
    with pytest.raises(ValidationError):
        build_gtol_frame(number=number)


def test_a_datum_tag_carries_its_label() -> None:
    datum = build_datum()

    assert datum.label == "A"
    assert datum.frames == []


@pytest.mark.parametrize("bad_id", ["man:01", "ann:0001", "man:x001", ""])
def test_a_model_annotation_id_follows_its_pattern(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        build_gtol(id=bad_id)


def test_the_annotation_kind_is_closed() -> None:
    with pytest.raises(ValidationError):
        build_gtol(kind="note")


def test_an_attached_persist_ref_must_be_base64() -> None:
    with pytest.raises(ValidationError):
        build_gtol(attached_persist_refs=["not base64 !"])


def test_a_model_annotation_omits_its_unknowns() -> None:
    written = json.loads(build_datum().model_dump_json())

    assert written == {
        "id": "man:0002",
        "document_id": "doc:2",
        "kind": "datum",
        "label": "A",
        "attached_persist_refs": [persist_ref("fac:0002")],
    }


def test_an_annotation_attached_to_nothing_writes_no_attachment() -> None:
    written = json.loads(build_datum(attached_persist_refs=[]).model_dump_json())

    assert "attached_persist_refs" not in written


def test_a_model_annotation_refuses_an_unknown_field() -> None:
    payload = json.loads(build_gtol().model_dump_json())
    payload["zone"] = "0.05"

    with pytest.raises(ValidationError):
        ModelAnnotation.model_validate(payload)


# --- 6. the package ---------------------------------------------------------------------


def test_the_package_carries_the_two_arrays_when_they_have_rows() -> None:
    written = json.loads(tolerance_package().model_dump_json())

    assert len(written["model_dimensions"]) == 1
    assert len(written["model_annotations"]) == 2
    assert written["holes"][0]["wizard"]["counterbore_diameter"] == {"value": 0.011, "unit": "m"}


def test_a_one_five_zero_package_round_trips() -> None:
    package = tolerance_package()

    assert EvidencePackage.model_validate_json(package.model_dump_json()) == package


def test_the_package_validates_against_the_committed_contract() -> None:
    schema = load_contract("ir.schema.json")
    instance = json.loads(tolerance_package().model_dump_json())

    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=str)

    assert errors == []


def test_the_committed_contract_refuses_a_bad_model_dimension_id() -> None:
    schema = load_contract("ir.schema.json")
    instance = json.loads(tolerance_package().model_dump_json())
    instance["model_dimensions"][0]["id"] = "dim:1"

    assert list(Draft202012Validator(schema).iter_errors(instance))


@pytest.mark.parametrize("name", NEW_MODELS)
def test_every_new_model_is_in_the_generated_and_the_committed_schema(name: str) -> None:
    assert name in export_schema()["$defs"]
    assert name in load_contract("ir.schema.json")["$defs"]


@pytest.mark.parametrize("array", NEW_PACKAGE_ARRAYS)
def test_every_new_package_array_is_optional(array: str) -> None:
    for schema in (export_schema(), load_contract("ir.schema.json")):
        assert array in schema["properties"]
        assert array not in schema.get("required", [])
