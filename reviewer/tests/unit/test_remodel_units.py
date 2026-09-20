"""The units trap, as a pure regression over the global's own literal (T088).

**The number in an equation text is in the DOCUMENT's length unit, not metres** (research
R3.6, the highest-risk single question in stage 1). The package carries metres, as every
length in the IR does; a part in mm takes `"plate_width" = 120` for 120 mm. Getting it
backwards builds a 120-**metre** part that rebuilds cleanly and passes every non-geometric
check, which is why this test exists and why it needs no seat.

FR-030 keeps dimensions out of v1 - the IR carries none - so the only number this version
ever writes into an equation is the **global's own literal**, seeded from
`GlobalEvidence.value_m`. The sequence these cases pin is R3.6's, minus its step 4:

1. read the justifying value from the package's feature data, in metres;
2. convert it to the document's length unit and seed the literal with that exact value;
3. add the global and assert it landed and evaluated;
4. **not in v1**: the dimension equation FR-030 forbids;
5. re-read the equation and assert its text and value round-trip at the document's stored
   precision, not at a loose epsilon;
6. the geometry snapshot is identical, because a global that drives nothing cannot move
   geometry.

Steps 3 and 5 are exercised against a fake equation manager that keeps
`AddEquationVerified`'s contract (append, count incremented, `get_Equation(i)` round-trips)
- the C# helper itself is pinned by `AddEquationVerifiedTests` (T067) and the executor's
call path arrives with T089. Step 6 has no snapshot to take without a seat, so what is
asserted here is the **reason** it cannot move: the text this module composes is a global
declaration that references no dimension, and composing it is a pure function of the
value, the unit and the name, with nothing in its signature that could reach a body.

A document whose length unit cannot be read **refuses the change** rather than assuming
metres, and no code path on this file reads or writes any `IDimension` member at all.
"""

from __future__ import annotations

import inspect
import math
from pathlib import Path
from typing import get_args

import pytest
from pint import DimensionalityError

from swreview.ir.models import Angle, LengthUnit, Quantity
from swreview.remodel import units
from swreview.remodel.intent import GlobalCandidate
from swreview.remodel.plan import GlobalEvidence, GlobalProposal
from tests.support.remodel import code_lines, stage_1_sources

CANDIDATE = GlobalCandidate(
    feature_id="feat:0019",
    name="Fillet1",
    parameter="default_radius",
    value_m=0.003,
)
"""One readable fillet radius, as `global_candidates` reports it: 3 mm, in metres."""


# --- 1. the document-unit conversion table ----------------------------------------


def test_the_table_is_the_irs_own_length_units_and_nothing_else() -> None:
    """A unit outside the IR's own three is refused rather than guessed at, so the C#
    side and this one share one vocabulary instead of two that overlap."""
    assert set(units.DOCUMENT_LENGTH_UNITS) == set(get_args(LengthUnit))


@pytest.mark.parametrize(
    ("value_m", "unit", "expected"),
    [
        (0.12, "mm", 120.0),
        (0.003, "mm", 3.0),
        (1.5, "mm", 1500.0),
        (0.0254, "in", 1.0),
        (0.0127, "in", 0.5),
        (0.12, "m", 0.12),
    ],
)
def test_a_value_in_metres_converts_to_the_documents_unit(
    value_m: float, unit: str, expected: float
) -> None:
    assert units.document_length(value_m, unit) == pytest.approx(expected, abs=1e-12)


def test_a_120_mm_value_never_produces_w_equals_0_12() -> None:
    """The regression R3.6 asks for by name. `"w" = 0.12` in a millimetre document is a
    120 micron feature where a 120 mm one was meant, and nothing downstream would say so.
    """
    text = units.global_equation_text("width", units.document_length(0.12, "mm"))

    assert text == '"width" = 120'
    assert "0.12" not in text


def test_the_metre_document_is_the_one_case_where_the_number_is_unchanged() -> None:
    """A document really kept in metres takes the metre value, and the conversion is the
    identity there rather than a special case anybody has to remember."""
    assert (
        units.global_equation_text("width", units.document_length(0.12, "m"))
        == '"width" = 0.12'
    )


# --- 2. the literal ---------------------------------------------------------------


def test_an_integral_value_is_written_without_a_trailing_decimal() -> None:
    assert units.global_equation_text("corner_radius", 3.0) == '"corner_radius" = 3'


@pytest.mark.parametrize(
    ("value_m", "unit", "expected"),
    [
        (0.0035, "mm", '"thickness" = 3.5'),
        (0.00123456789, "mm", '"thickness" = 1.23456789'),
        (0.0001, "mm", '"thickness" = 0.1'),
        (0.0254, "in", '"thickness" = 1'),
    ],
)
def test_the_literal_keeps_every_digit_of_the_converted_value(
    value_m: float, unit: str, expected: str
) -> None:
    """The exact value, not a rounded one: a seeded literal that is not the number the
    package carries is a change nobody asked for."""
    assert (
        units.global_equation_text("thickness", units.document_length(value_m, unit)) == expected
    )


@pytest.mark.parametrize("value_m", [0.12, 0.003, 0.00123456789, 0.0001, 1.5])
def test_the_literal_parses_back_to_exactly_the_value_it_was_written_from(
    value_m: float,
) -> None:
    """Round-tripped at the document's stored precision - `==`, not an epsilon. The text
    is the only carrier of the number once it reaches the equation manager."""
    converted = units.document_length(value_m, "mm")

    text = units.global_equation_text("thickness", converted)

    assert float(text.split("=", 1)[1]) == converted


def test_the_text_is_a_global_declaration_that_names_no_dimension() -> None:
    """A quoted left side with no `@` is what makes a row a global rather than a dimension
    equation (research R2, the reading `checks/rms/equations.py` makes of the left side).
    """
    text = units.global_equation_text("corner_radius", 3.0)

    assert text.startswith('"corner_radius" = ')
    assert "@" not in text


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_value_that_is_not_a_number_is_refused(value: float) -> None:
    with pytest.raises(units.DocumentUnitError, match="not a number"):
        units.global_equation_text("thickness", value)


# --- 3. a document unit that cannot be read ---------------------------------------


def test_a_document_whose_length_unit_could_not_be_read_refuses_the_change() -> None:
    """`GetLengthUnit` answering null is "unknown", and unknown is not metres: assuming
    metres here is exactly how a 120 metre part gets built (constitution Principle I)."""
    with pytest.raises(units.DocumentUnitError, match="metres"):
        units.document_length(0.12, None)


@pytest.mark.parametrize("unit", ["", "cm", "ft", "MM", "millimetre", "meters"])
def test_a_unit_this_version_does_not_convert_refuses_rather_than_guessing(
    unit: str,
) -> None:
    """Including the near-misses. A token that differs by a letter or by its case is a
    document this version cannot seed a literal for, and it says so."""
    with pytest.raises(units.DocumentUnitError, match="mm"):
        units.document_length(0.12, unit)


def test_an_unreadable_unit_composes_no_text_at_all() -> None:
    """The refusal happens before anything is composed, so there is no half-written
    equation for a caller to mistake for a change it may attempt."""
    with pytest.raises(units.DocumentUnitError):
        units.global_evidence(CANDIDATE, name="corner_radius", document_length_unit=None)


# --- 4. the evidence row the plan records -----------------------------------------


def test_the_evidence_row_carries_both_numbers_and_the_text_they_produced() -> None:
    """`data-model.md` section 1.9 records both because the inversion of the two is the
    highest-risk single error in stage 1: the row is the audit of this conversion."""
    evidence = units.global_evidence(
        CANDIDATE, name="corner_radius", document_length_unit="mm"
    )

    assert isinstance(evidence, GlobalEvidence)
    assert evidence.feature_id == "feat:0019"
    assert evidence.parameter == "default_radius"
    assert evidence.value_m == 0.003
    assert evidence.document_length_unit == "mm"
    assert evidence.value_document_units == 3.0
    assert evidence.equation_text == '"corner_radius" = 3'


def test_the_two_numbers_in_the_row_are_never_the_same_in_a_millimetre_document() -> None:
    """The inverted row - metres in the document-units field - is the failure this test
    file exists for, and it would show up here as two equal numbers."""
    evidence = units.global_evidence(
        CANDIDATE, name="corner_radius", document_length_unit="mm"
    )

    assert evidence.value_document_units != evidence.value_m
    assert str(evidence.value_m) not in evidence.equation_text


def test_the_row_is_built_from_the_packages_own_reading_and_nothing_else() -> None:
    """`value_m` is the candidate's, untouched: the executor converts it, it never
    re-measures it or rounds it on the way past."""
    candidate = GlobalCandidate(
        feature_id="feat:0007", name="Fillet2", parameter="default_radius", value_m=0.00123456789
    )

    evidence = units.global_evidence(candidate, name="thickness", document_length_unit="mm")

    assert evidence.value_m == candidate.value_m
    assert evidence.value_document_units == 1.23456789


def test_a_global_name_the_plan_would_refuse_is_refused_here_too() -> None:
    """One naming rule, `plan.py`'s, applied where the text is composed rather than only
    where the proposal is filed."""
    with pytest.raises(ValueError, match="name"):
        units.global_evidence(CANDIDATE, name="CornerRadius", document_length_unit="mm")


# --- 5. it lands, it evaluates, it round-trips ------------------------------------


class FakeEquationManager:
    """`IEquationMgr` as `AddEquationVerified` uses it (T067): append, count, read back.

    The C# helper's own assertions are pinned by `AddEquationVerifiedTests`; this stands
    in for the manager so the **text** can be followed through an add, a rebuild and a
    re-read without a seat.
    """

    def __init__(self) -> None:
        self._rows: list[str] = []

    def get_count(self) -> int:
        return len(self._rows)

    def add(self, text: str) -> int:
        self._rows.append(text)
        return len(self._rows) - 1

    def get_equation(self, index: int) -> str:
        return self._rows[index]

    def value(self, index: int) -> float:
        """The literal as the manager would evaluate it: the right side of a constant."""
        return float(self._rows[index].split("=", 1)[1])

    def rebuild(self) -> None:
        """`ForceRebuild3(false)`: the rows are re-read after it, not rewritten by it."""


def add_verified(manager: FakeEquationManager, text: str) -> int:
    """The helper's contract: the add is judged by the read-back, never by the answer."""
    before = manager.get_count()
    index = manager.add(text)
    assert manager.get_count() == before + 1, "the add did not land"
    assert manager.get_equation(index) == text, "the row does not read back as written"
    return index


def test_the_seeded_global_lands_and_evaluates() -> None:
    manager = FakeEquationManager()
    evidence = units.global_evidence(
        CANDIDATE, name="corner_radius", document_length_unit="mm"
    )

    index = add_verified(manager, evidence.equation_text)

    assert manager.get_count() == 1
    assert manager.get_equation(index) == '"corner_radius" = 3'
    assert manager.value(index) == evidence.value_document_units


def test_the_text_and_the_value_round_trip_across_a_rebuild() -> None:
    """At the document's stored precision, not at a loose epsilon: the assertion is `==`
    on both the text and the number."""
    manager = FakeEquationManager()
    evidence = units.global_evidence(
        GlobalCandidate(
            feature_id="feat:0007",
            name="Fillet2",
            parameter="default_radius",
            value_m=0.00123456789,
        ),
        name="thickness",
        document_length_unit="mm",
    )
    index = add_verified(manager, evidence.equation_text)

    manager.rebuild()

    assert manager.get_equation(index) == evidence.equation_text
    assert manager.value(index) == evidence.value_document_units == 1.23456789


# --- 6. a global that drives nothing cannot move geometry -------------------------


def test_seeding_a_global_is_a_pure_function_of_the_value_the_unit_and_the_name() -> None:
    """There is no document, no bridge and no body in the signature, so there is nothing
    the seeding step could move. That is why the snapshot comparison after it is an
    identity and not a tolerance question (R3.6 step 6)."""
    parameters = set(inspect.signature(units.global_evidence).parameters)

    assert parameters == {"candidate", "name", "document_length_unit"}
    first = units.global_evidence(CANDIDATE, name="corner_radius", document_length_unit="mm")
    second = units.global_evidence(CANDIDATE, name="corner_radius", document_length_unit="mm")
    assert first == second


def test_a_v1_global_names_a_value_and_drives_nothing() -> None:
    """FR-030: the proposal carries `evidence`, not `drives`. Nothing in the copy is
    rewired to a global this run adds, so no geometry can follow from adding one."""
    assert "evidence" in GlobalProposal.model_fields
    assert "drives" not in GlobalProposal.model_fields


# --- 7. angles --------------------------------------------------------------------


def test_the_equation_engine_reads_degrees() -> None:
    """`swAngularEquationUnits_e.Degrees = 1` (VERIFIED). The documented function set -
    `sin cos tan atn arcsin sqr` - takes degrees, so degrees is what an expression
    carries."""
    assert units.DEGREES == 1
    assert units.EQUATION_ANGLE_UNIT == "deg"


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(45.0, "deg", 45.0), (math.pi, "rad", 180.0), (math.pi / 4.0, "rad", 45.0)],
)
def test_an_angle_reaches_an_expression_in_degrees(
    value: float, unit: str, expected: float
) -> None:
    """The angular half of the same trap: an IR angle in radians is converted, never
    written out raw."""
    assert units.angle_degrees(Angle(value=value, unit=unit)) == pytest.approx(
        expected, abs=1e-9
    )


def test_a_length_is_never_read_as_an_angle() -> None:
    """The separation `swreview.units` holds, reused rather than re-implemented: the one
    registry keeps lengths and angles from mixing (FR-022, Principle II)."""
    with pytest.raises(DimensionalityError):
        units.angle_degrees(Quantity(value=120.0, unit="mm"))


def test_every_conversion_here_goes_through_the_one_unit_module() -> None:
    """`swreview.units` is the only place in the reviewer that converts units (research
    R6). A second conversion site is precisely the trap R3.6 names, so this module holds
    no factor of its own."""
    source = inspect.getsource(units)

    assert "1000" not in source
    assert "25.4" not in source
    assert "math.pi" not in source


# --- 8. no dimension is touched, anywhere on this path ----------------------------


def test_no_code_path_in_stage_1_reads_or_writes_any_idimension_member() -> None:
    """FR-030 keeps dimensions out of v1 entirely and `IDimension.set_Name` is off the
    stage-1 allowlist, so no file of the stage-1 surface - the re-modeler's Python, the
    extractor's `Rms` family and both guards - names the interface outside a comment."""
    for path in stage_1_sources():
        assert not [line for line in code_lines(path) if "IDimension" in line], path


def test_stage_1_scan_ignores_description_strings_but_keeps_direct_member_references(
    tmp_path: Path,
) -> None:
    """The scan filters plain probe prose while retaining executable-looking references."""
    source = tmp_path / "Probe.cs"
    source.write_text(
        'var description = "IDimension member is not read"; var value = model.IDimension;\n'
        'var interpolated = $"IDimension {model.Value}"; var dim = (IDimension)value; '
        'var other = "IDimension";\n',
        encoding="utf-8",
    )

    lines = [line for line in code_lines(source) if "IDimension" in line]

    assert lines == [
        'var description = ; var value = model.IDimension;',
        'var interpolated = $"IDimension {model.Value}"; var dim = (IDimension)value; '
        'var other = "IDimension";',
    ]


def test_no_admissible_parameter_is_a_dimension() -> None:
    """The other half of the same claim, from the data side: a global can only be
    justified by a feature-data field the package carries, and the IR carries no
    dimensions at all (FR-030)."""
    from swreview.remodel.intent import ADMISSIBLE_PARAMETERS

    assert ADMISSIBLE_PARAMETERS == ("hole_diameter", "shell_thickness", "default_radius")
    for parameter in ADMISSIBLE_PARAMETERS:
        assert "dimension" not in parameter


def test_nothing_here_takes_a_document_a_bridge_or_a_persist_ref() -> None:
    """The pure-function property stated once over the module's whole public surface:
    every call that reaches SOLIDWORKS is the executor's and goes through the guard."""
    for name in units.__all__:
        member = getattr(units, name)
        if not inspect.isfunction(member):
            continue
        for parameter in inspect.signature(member).parameters:
            assert parameter not in {"document", "bridge", "client", "persist_ref", "model_doc"}
