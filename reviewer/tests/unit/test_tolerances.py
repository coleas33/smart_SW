"""The tolerance resolver (feature 010 T082, `contracts/tolerances.md` section 4, SC-007).

`resolve_tolerance` walks five sources in precedence - drawing callout, model annotation,
model dimension, Hole Wizard class, general block - and returns the first that binds the
subject, listing every lower one that also carried a tolerance and naming a conflict when
their limits differ; or every source searched and why none bound. Binding is by geometry: an
annotation by the persist reference of a face it is attached to, a model dimension by being
the one dimension of its value in the subject's document. Nothing else produces a limit.
"""

from __future__ import annotations

import math
from dataclasses import replace as _replace
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.result import limits_mm
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.tolerances import (
    SOURCE_ORDER,
    DrawingAnswer,
    ResolvedTolerance,
    ResolverLookup,
    ToleranceSubject,
    UnresolvedTolerance,
    drawing_answer,
    resolve_tolerance,
)
from swreview.drawings import binding as drawing_binding
from swreview.drawings.binding import NOT_VALIDATED
from swreview.ir.models import EvidencePackage, HoleWizardData
from tests.support.drawings import Attach, DrawingBuilder
from tests.support.mechanical import Face, Instance, PackageBuilder, load_generator

REVIEWER = Path(__file__).resolve().parents[1].parent
PROFILE_A = REVIEWER / "tests" / "fixtures" / "standards" / "profile-a.yaml"
Z = (0.0, 0.0, 1.0)


@pytest.fixture(scope="module")
def profile() -> StandardsProfile:
    return load_profile(PROFILE_A)


class Plate:
    """A 1.5.0 plate with one 3.0 mm clearance hole and one 3.0 mm pin, and what binds."""

    def __init__(self, wizard: HoleWizardData | None = None) -> None:
        self.builder = PackageBuilder(design_stem="FICT-KALO-0000", schema_version="1.5.0")
        self.plate = self.builder.document("FICT-KALOMIR-0001", "part", material="6061-T6")
        self.builder.component(self.plate, component_id="cmp:0001")
        self.hole = self.builder.hole(
            "cmp:0001",
            hole_type="clearance",
            size="Ø3.0",
            end_condition="through",
            instances=[Instance((0.0, 0.0, 0.0), Z, (Face(3.0, 0.0, 6.0),))],
            wizard=wizard,
        )
        self.face = "fac:0001"
        self.pin = self.builder.document("FICT-PIN-3X12-0002", "part", material="Alloy Steel")
        self.builder.component(self.pin, component_id="cmp:0002")
        self.pin_face = self.builder.cylinder_face(
            "cmp:0002", origin_mm=(0, 0, 0), direction=Z, diameter_mm=3.0, lo_mm=0.0, hi_mm=6.0
        )

    def package(self) -> EvidencePackage:
        return self.builder.build().package

    def hole_size(self, places: int | None = None) -> ToleranceSubject:
        return ToleranceSubject(
            kind="hole_size",
            nominal_mm=3.0,
            document_id=self.plate,
            face_ids=(self.face,),
            instance_id=f"{self.hole}#1",
            component_id="cmp:0001",
            decimal_places=places,
        )

    def hole_position(self) -> ToleranceSubject:
        return ToleranceSubject(
            kind="hole_position",
            nominal_mm=3.0,
            document_id=self.plate,
            face_ids=(self.face,),
            instance_id=f"{self.hole}#1",
            component_id="cmp:0001",
        )

    def pin_size(self) -> ToleranceSubject:
        return ToleranceSubject(
            kind="pin_size",
            nominal_mm=3.0,
            document_id=self.pin,
            face_ids=(self.pin_face,),
            component_id="cmp:0002",
        )


def resolved(answer: ResolvedTolerance | UnresolvedTolerance) -> ResolvedTolerance:
    assert isinstance(answer, ResolvedTolerance), answer
    return answer


def searched(answer: ResolvedTolerance | UnresolvedTolerance) -> dict[str, str]:
    assert isinstance(answer, UnresolvedTolerance), answer
    return dict(answer.searched)


# --- each source on its own --------------------------------------------------------------------


def test_a_unique_model_dimension_binds_by_value() -> None:
    plate = Plate()
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=("bilateral", 0.02, 0.005))

    answer = resolved(resolve_tolerance(plate.package(), None, plate.hole_size()))

    assert answer.source_kind == "model_dimension"
    assert answer.cited == "dimension KALOMIR1@FICT-HOLE-0001 (mdm:0001)"
    limits = limits_mm(answer.dimension)
    assert (limits.min_mm, limits.max_mm) == (3.005, 3.02)
    assert answer.dimension.source.persist_ref is not None


def test_a_radius_dimension_binds_a_diameter_with_its_tolerance_doubled() -> None:
    plate = Plate()
    plate.builder.model_dimension(
        plate.plate, nominal_mm=1.5, dimension_type="radius", tolerance=("bilateral", 0.01, 0.0)
    )

    limits = limits_mm(
        resolved(resolve_tolerance(plate.package(), None, plate.hole_size())).dimension
    )

    assert (limits.min_mm, limits.max_mm) == (3.0, 3.02)


def test_a_class_only_fit_on_the_dimension_binds_through_iso_286() -> None:
    """The C# lane's finding: a hole's H7 arrives on its model dimension, not the wizard."""
    plate = Plate()
    plate.builder.model_dimension(
        plate.plate, nominal_mm=3.0, tolerance=None, tolerance_type_raw=8, fit_hole_class="H7"
    )

    answer = resolved(resolve_tolerance(plate.package(), None, plate.hole_size()))

    assert answer.cited == (
        "dimension KALOMIR1@FICT-HOLE-0001 (mdm:0001): fit class H7, per ISO 286-1 (iso286.yaml)"
    )
    limits = limits_mm(answer.dimension)
    assert (limits.min_mm, limits.max_mm) == (3.0, 3.01)


def test_a_shaft_class_binds_the_pin() -> None:
    plate = Plate()
    plate.builder.model_dimension(
        plate.pin, nominal_mm=3.0, tolerance=None, tolerance_type_raw=8, fit_shaft_class="h6"
    )

    limits = limits_mm(
        resolved(resolve_tolerance(plate.package(), None, plate.pin_size())).dimension
    )

    assert (limits.min_mm, limits.max_mm) == (2.994, 3.0)


def test_a_hole_wizard_iso_class_binds() -> None:
    plate = Plate(wizard=HoleWizardData(fit_class_raw="H7"))

    answer = resolved(resolve_tolerance(plate.package(), None, plate.hole_size()))

    assert answer.source_kind == "hole_wizard"
    assert answer.cited == "the Hole Wizard fit class H7 of hol:0001, per ISO 286-1 (iso286.yaml)"


def test_a_hole_wizard_clearance_fit_binds_nothing_and_says_why() -> None:
    plate = Plate(wizard=HoleWizardData(fit_class_raw="swScrewClearanceNormal"))

    why = searched(resolve_tolerance(plate.package(), None, plate.hole_size()))["hole_wizard"]

    assert why.startswith("the fit class swScrewClearanceNormal of hol:0001 is no ISO 286 class")
    assert why.endswith("a Hole Wizard fit is a screw clearance fit")


def test_the_general_block_binds_a_size_whose_precision_is_recorded(profile) -> None:
    plate = Plate()

    answer = resolved(resolve_tolerance(plate.package(), profile, plate.hole_size(places=2)))

    assert answer.source_kind == "general"
    assert answer.cited.startswith("general_tolerance of the standards profile sha256")


def test_an_annotation_with_a_stated_unit_binds_a_position_by_face_reference() -> None:
    plate = Plate()
    plate.builder.model_annotation(
        plate.plate, face_ids=[plate.face], symbols=["<IGTOL-POSI>"], values=["0.02mm"]
    )

    answer = resolved(resolve_tolerance(plate.package(), None, plate.hole_position()))

    assert answer.source_kind == "annotation"
    assert answer.cited == "man:0001 (frame 1) attached to a face of hol:0001#1"
    assert math.isclose(answer.dimension.nominal.value, 0.02)


def test_an_annotation_attached_elsewhere_binds_nothing() -> None:
    plate = Plate()
    plate.builder.model_annotation(
        plate.pin, face_ids=[plate.pin_face], symbols=["<IGTOL-POSI>"], values=["0.02mm"]
    )

    why = searched(resolve_tolerance(plate.package(), None, plate.hole_position()))["annotation"]

    assert why == "no geometric tolerance is attached to the faces of hol:0001#1"


def test_an_annotation_without_a_unit_binds_nothing_rather_than_guess_one() -> None:
    """GTol frame values are display strings; the part's length unit is not in the package."""
    plate = Plate()
    plate.builder.model_annotation(
        plate.plate, face_ids=[plate.face], symbols=["<IGTOL-POSI>"], values=["0.02"]
    )

    why = searched(resolve_tolerance(plate.package(), None, plate.hole_position()))["annotation"]

    assert why == (
        "man:0001 is attached to hol:0001#1 and states a position zone of 0.02, but the part's "
        "length unit is not in the package, so the zone's size is unknown"
    )


def test_an_annotation_states_no_size() -> None:
    plate = Plate()
    plate.builder.model_annotation(
        plate.plate, face_ids=[plate.face], symbols=["<IGTOL-POSI>"], values=["0.02mm"]
    )

    why = searched(resolve_tolerance(plate.package(), None, plate.hole_size()))["annotation"]

    assert why == "the geometric tolerances attached to hol:0001#1 state no size tolerance"


def test_the_drawing_slot_says_no_drawing_of_the_document_was_read() -> None:
    """Edited deliberately by feature 011 T034: the slot is filled, and with no drawing record
    its reason is the one sentence that changes (`contracts/drawing-source.md` section 4)."""
    plate = Plate()

    assert searched(resolve_tolerance(plate.package(), None, plate.hole_size()))["drawing"] == (
        "no drawing of doc:0002 was read"
    )


# --- precedence, also found, conflicts ------------------------------------------------------------


def test_precedence_picks_the_model_dimension_over_the_wizard_and_lists_the_wizard() -> None:
    plate = Plate(wizard=HoleWizardData(fit_class_raw="H7"))
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=None, fit_hole_class="H7")

    answer = resolved(resolve_tolerance(plate.package(), None, plate.hole_size()))

    assert answer.source_kind == "model_dimension"
    assert answer.also_found == ("hole_wizard",)
    assert answer.conflict is None


def test_sources_that_disagree_are_a_conflict_naming_both() -> None:
    plate = Plate(wizard=HoleWizardData(fit_class_raw="H9"))
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=("bilateral", 0.02, 0.0))

    answer = resolved(resolve_tolerance(plate.package(), None, plate.hole_size()))

    assert answer.conflict == (
        "model dimension and Hole Wizard class give the size of hol:0001#1 different "
        "tolerances; the model dimension is used"
    )


def test_an_explicit_tolerance_always_wins_over_the_general_block(profile) -> None:
    plate = Plate()
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=("bilateral", 0.02, 0.0))

    answer = resolved(resolve_tolerance(plate.package(), profile, plate.hole_size(places=2)))

    assert answer.source_kind == "model_dimension"
    assert answer.also_found == ("general",)


# --- what binds nothing --------------------------------------------------------------------------


def test_an_equal_pair_of_dimensions_binds_nothing() -> None:
    plate = Plate()
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=("bilateral", 0.02, 0.0))
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=("bilateral", 0.03, 0.0))

    why = searched(resolve_tolerance(plate.package(), None, plate.hole_size()))["model_dimension"]

    assert why == (
        "2 dimensions of doc:0002 are 3.0 mm (mdm:0001, mdm:0002), so none binds to one hole alone"
    )


def test_a_dimension_in_another_document_binds_nothing() -> None:
    plate = Plate()
    plate.builder.model_dimension(plate.pin, nominal_mm=3.0, tolerance=("bilateral", 0.02, 0.0))

    why = searched(resolve_tolerance(plate.package(), None, plate.hole_size()))["model_dimension"]

    assert why == "no diameter or radius dimension of doc:0002 is 3.0 mm"


def test_an_untoleranced_dimension_binds_nothing() -> None:
    plate = Plate()
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=("none", 0.0, None))

    why = searched(resolve_tolerance(plate.package(), None, plate.hole_size()))["model_dimension"]

    assert why == "dimension KALOMIR1@FICT-HOLE-0001 (mdm:0001) is untoleranced (none)"


def test_a_position_is_never_bound_by_the_general_block_or_a_diameter(profile) -> None:
    plate = Plate()
    plate.builder.model_dimension(plate.plate, nominal_mm=3.0, tolerance=("bilateral", 0.02, 0.0))

    reasons = searched(resolve_tolerance(plate.package(), profile, plate.hole_position()))

    assert reasons["general"] == "a general tolerance block tolerances sizes, never a position zone"
    assert reasons["model_dimension"] == "a diameter dimension tolerances a size, not a position"


def test_an_unresolved_subject_names_every_source_and_why(profile) -> None:
    plate = Plate()

    answer = resolve_tolerance(plate.package(), profile, plate.hole_size())

    assert isinstance(answer, UnresolvedTolerance)
    assert [source for source, _ in answer.searched] == list(SOURCE_ORDER)
    assert dict(answer.searched) == {
        "drawing": "no drawing of doc:0002 was read",  # feature 011 T034, deliberately
        "annotation": "the package carries no model annotation (DimXpert or MBD)",
        "model_dimension": "the package carries no model dimension",
        "hole_wizard": "no Hole Wizard data is recorded for hol:0001",
        "general": (
            "the precision its dimension is written to is not recorded, so no decimal-place "
            "band applies (a drawing records it, feature 011)"
        ),
    }


def test_a_version_1_profile_is_listed_as_searched(profile) -> None:
    version_1 = profile.model_copy(
        update={"version": 1, "hygiene": None, "general_tolerance": None}
    )
    plate = Plate()

    why = searched(resolve_tolerance(plate.package(), version_1, plate.hole_size(places=2)))

    assert why["general"] == "the profile is version 1, which declares no general tolerance"


@pytest.mark.parametrize("kind", ["hole_size", "pin_size", "hole_position"])
def test_no_path_returns_a_limit_without_a_bound_source(kind: str) -> None:
    """SC-007: with nothing in the package and no profile, every subject is unresolved."""
    plate = Plate(wizard=HoleWizardData())
    subject = {
        "hole_size": plate.hole_size(places=2),
        "pin_size": plate.pin_size(),
        "hole_position": plate.hole_position(),
    }[kind]

    answer = resolve_tolerance(plate.package(), None, subject)

    assert isinstance(answer, UnresolvedTolerance)
    assert len(answer.searched) == 5


# --- the lookup ----------------------------------------------------------------------------------


def test_a_package_with_nothing_that_can_bind_holds_no_source(profile) -> None:
    """A profile with general bands alone cannot bind (no written precision before 011), and
    neither can a Hole Wizard clearance fit, an untoleranced dimension or a unitless zone."""
    plate = Plate(wizard=HoleWizardData(fit_class_raw="swScrewClearanceNormal"))
    plate.builder.model_dimension(plate.plate, nominal_mm=9.0, tolerance=None)
    plate.builder.model_dimension(plate.plate, nominal_mm=8.0, tolerance=("none", 0.0, None))
    plate.builder.model_annotation(
        plate.plate, face_ids=[plate.face], symbols=["<IGTOL-POSI>"], values=["0.02"]
    )

    assert ResolverLookup(plate.package(), profile).holds_any_source() is False


@pytest.mark.parametrize("source", ["dimension", "fit_class", "wizard", "zone"])
def test_a_package_with_something_that_can_bind_holds_a_source(source: str) -> None:
    plate = Plate(wizard=HoleWizardData(fit_class_raw="H7") if source == "wizard" else None)
    if source == "dimension":
        plate.builder.model_dimension(
            plate.plate, nominal_mm=9.0, tolerance=("bilateral", 0.1, 0.0)
        )
    if source == "fit_class":
        plate.builder.model_dimension(
            plate.plate, nominal_mm=9.0, tolerance=None, fit_hole_class="H8"
        )
    if source == "zone":
        plate.builder.model_annotation(
            plate.plate, face_ids=[plate.face], symbols=["<IGTOL-POSI>"], values=["0.02mm"]
        )

    lookup = ResolverLookup(plate.package(), None)

    assert lookup.holds_any_source() is True


def test_the_lookup_resolves_with_the_profile_it_was_given(profile) -> None:
    plate = Plate()

    answer = ResolverLookup(plate.package(), profile).resolve(plate.hole_size(places=2))

    assert resolved(answer).source_kind == "general"


# --- feature 011: the drawing source (T034, `contracts/drawing-source.md` section 4) -------------
#
# Small packages built on feature 010's tolerances assembly with `tests/support/drawings.py`:
# the plate `doc:0002` (`cmp:0001`) carries the dowel hole `hol:0001` on `fac:0001` (Ø3.0, a
# class-only H7 model dimension `mdm:0001`) and the counterbore `hol:0002` on `fac:0002` (Ø4.5,
# two equal 4.5 mm model dimensions, so source 3 binds nothing) and `fac:0003` (Ø8.0). Every test
# sets `DRAWING_BINDING_VALIDATED` except those that name the switch.

MECHANICAL = REVIEWER / "tests" / "fixtures" / "mechanical" / "generate_fixtures.py"

DOWEL = ToleranceSubject(
    kind="hole_size", nominal_mm=3.0, document_id="doc:0002", face_ids=("fac:0001",),
    instance_id="hol:0001#1", component_id="cmp:0001",
)
BORE = ToleranceSubject(
    kind="hole_size", nominal_mm=4.5, document_id="doc:0002", face_ids=("fac:0002", "fac:0003"),
    instance_id="hol:0002#1", component_id="cmp:0001",
)


@pytest.fixture
def validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drawing_binding, "DRAWING_BINDING_VALIDATED", True)


def tolerances_package() -> EvidencePackage:
    return load_generator(MECHANICAL).build_tolerances_assembly().package  # type: ignore[no-any-return]


class Drawn:
    """The tolerances assembly with drawings of the plate, one view each."""

    def __init__(self) -> None:
        self.builder = DrawingBuilder(tolerances_package())
        self.drawings = 0
        self.dimensions = 90

    def view(self, **view: Any) -> Any:
        self.drawings += 1
        stem = "FICT-TULMKALO-3001" + ("" if self.drawings == 1 else f"-{chr(64 + self.drawings)}")
        record = self.builder.drawing(
            self.builder.drawing_document(stem), **view.pop("drawing", {})
        )
        return self.builder.view(
            self.builder.sheet(record, "Sheet1"), "Drawing View1", references="doc:0002", **view
        )

    def dimension(self, view: Any, face: str, value_mm: float, **fields: Any) -> None:
        self.dimensions += 1
        self.builder.dimension(
            view, f"KALOMIR{self.dimensions}@FICT-TULMKALO-3001", value_mm=value_mm,
            attached=[Attach(face)], **fields,
        )

    def package(self) -> EvidencePackage:
        return self.builder.build()


def with_unit(profile: StandardsProfile, unit: str) -> StandardsProfile:
    assert profile.drawing is not None
    return profile.model_copy(
        update={"drawing": profile.drawing.model_copy(update={"dimension_unit": unit})}
    )


def as_version_2(profile: StandardsProfile) -> StandardsProfile:
    return profile.model_copy(update={"version": 2, "drawing": None})


@pytest.mark.usefixtures("validated")
def test_the_drawing_binds_first_and_the_model_dimension_is_also_found() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0001", 3.0, tolerance=("bilateral", 0.010, 0.0),
                    tolerance_type_raw=2)

    answer = resolved(resolve_tolerance(drawn.package(), None, DOWEL))

    assert answer.source_kind == "drawing"
    assert answer.cited == "drawing doc:0006, sheet Sheet1, view Drawing View1, ddm:0001"
    assert answer.also_found == ("model_dimension",)
    assert answer.conflict is None, "H7 on 3.0 is 3.000/3.010, the drawing's limits too"
    limits = limits_mm(answer.dimension)
    assert (limits.min_mm, limits.max_mm) == (3.0, 3.01)
    assert answer.dimension.source.annotation == "ddm:0001"


@pytest.mark.usefixtures("validated")
def test_a_drawing_that_disagrees_with_the_model_is_the_cross_source_conflict() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0001", 3.0, tolerance=("bilateral", 0.020, 0.005),
                    tolerance_type_raw=2)

    answer = resolved(resolve_tolerance(drawn.package(), None, DOWEL))

    assert answer.conflict == (
        "drawing callout and model dimension give the size of hol:0001#1 different tolerances; "
        "the drawing callout is used"
    )


@pytest.mark.usefixtures("validated")
def test_two_drawings_with_different_limits_are_the_drawing_sources_own_conflict() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0001", 3.0, tolerance=("bilateral", 0.010, 0.0),
                    tolerance_type_raw=2)
    drawn.dimension(drawn.view(), "fac:0001", 3.0, tolerance=("bilateral", 0.020, 0.005),
                    tolerance_type_raw=2)
    package = drawn.package()

    answer = drawing_answer(package, DOWEL)
    bound = resolved(resolve_tolerance(package, None, DOWEL))

    first = "drawing doc:0006, sheet Sheet1, view Drawing View1, ddm:0001"
    second = "drawing doc:0007, sheet Sheet1, view Drawing View1, ddm:0002"
    assert answer.conflict == (
        f"{first} and {second} give the size of hol:0001#1 different tolerances; {first} is used"
    )
    assert bound.cited == first
    assert bound.conflict == answer.conflict


@pytest.mark.usefixtures("validated")
def test_a_radial_dimensions_limits_are_doubled() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0001", 1.5, type_raw=5, prefix="R",
                    tolerance=("bilateral", 0.005, 0.0), tolerance_type_raw=2)

    limits = limits_mm(resolved(resolve_tolerance(drawn.package(), None, DOWEL)).dimension)

    assert (limits.min_mm, limits.max_mm) == (3.0, 3.01)


@pytest.mark.usefixtures("validated")
def test_an_untoleranced_radius_gets_the_general_band_doubled(profile: StandardsProfile) -> None:
    """The band tolerances the value written, a radius: R2.25 at two decimals is 2.25 +/- 0.15,
    so the diameter spans 4.2 to 4.8 - the limits an explicit R2.25 +/- 0.15 gives (step 1
    doubles those), never the 4.35 to 4.65 a diameter written to two decimals gets."""
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 2.25, type_raw=5, prefix="R", precision=2)
    package = drawn.package()

    answer = drawing_answer(package, BORE)
    bound = resolved(resolve_tolerance(package, profile, BORE))

    assert (answer.decimal_places, answer.unit, answer.radial) == (2, "mm", True)
    assert answer.why == (
        "ddm:0001 states no tolerance of its own and writes 2 decimals in mm as a radius, which "
        "the general tolerance reads, doubled for the diameter"
    )
    assert bound.source_kind == "general"
    assert bound.cited.endswith("the 2-decimal band, doubled: the drawing writes it as a radius")
    limits = limits_mm(bound.dimension)
    assert (limits.min_mm, limits.max_mm) == (4.2, 4.8)


@pytest.mark.usefixtures("validated")
def test_an_explicit_radius_tolerance_and_the_doubled_band_agree(
    profile: StandardsProfile,
) -> None:
    """One rule for a radius, whichever step binds it."""
    explicit = Drawn()
    explicit.dimension(explicit.view(), "fac:0002", 2.25, type_raw=5, prefix="R",
                       tolerance=("symmetric", 0.15, None), tolerance_type_raw=4)
    general = Drawn()
    general.dimension(general.view(), "fac:0002", 2.25, type_raw=5, prefix="R", precision=2)

    by_drawing = limits_mm(resolved(resolve_tolerance(explicit.package(), profile, BORE)).dimension)
    by_band = limits_mm(resolved(resolve_tolerance(general.package(), profile, BORE)).dimension)

    assert (by_drawing.min_mm, by_drawing.max_mm) == (by_band.min_mm, by_band.max_mm) == (4.2, 4.8)


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize("radius_first", [True, False])
def test_a_radius_and_a_diameter_at_one_precision_bind_nothing_and_say_so(
    profile: StandardsProfile, radius_first: bool
) -> None:
    """The band gives a radius twice the diameter's tolerance, so the two disagree."""
    drawn = Drawn()
    radius = {"type_raw": 5, "prefix": "R", "precision": 2}
    if radius_first:
        drawn.dimension(drawn.view(), "fac:0002", 2.25, **radius)
        drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
    else:
        drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
        drawn.dimension(drawn.view(), "fac:0002", 2.25, **radius)
    package = drawn.package()

    answer = drawing_answer(package, BORE)
    why = searched(resolve_tolerance(package, profile, BORE))

    radius_id, diameter_id = ("ddm:0001", "ddm:0002") if radius_first else ("ddm:0002", "ddm:0001")
    assert (answer.decimal_places, answer.unit, answer.radial) == (None, None, False)
    assert answer.why == (
        f"{radius_id} is written as a radius and {diameter_id} as a diameter, so the general "
        "tolerance's band would give the size two different tolerances"
    )
    assert why["general"].startswith("the precision its dimension is written to is not recorded")


@pytest.mark.usefixtures("validated")
def test_a_fit_class_on_the_drawing_binds_through_iso_286() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0001", 3.0, tolerance_type_raw=7, fit_hole_class="H8")

    answer = resolved(resolve_tolerance(drawn.package(), None, DOWEL))

    assert answer.source_kind == "drawing"
    assert answer.cited == (
        "drawing doc:0006, sheet Sheet1, view Drawing View1, ddm:0001: fit class H8, per ISO "
        "286-1 (iso286.yaml)"
    )
    limits = limits_mm(answer.dimension)
    assert (limits.min_mm, limits.max_mm) == (3.0, 3.014)


@pytest.mark.usefixtures("validated")
def test_a_fit_class_the_table_does_not_carry_supplies_no_limits() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0001", 3.0, tolerance_type_raw=7, fit_hole_class="Z9")

    answer = drawing_answer(drawn.package(), DOWEL)

    assert answer.dimension is None
    assert "Z9" in answer.why and "iso286.yaml" in answer.why


@pytest.mark.usefixtures("validated")
def test_an_untoleranced_two_decimal_dimension_hands_two_decimals_to_the_general_block(
    profile: StandardsProfile,
) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
    package = drawn.package()

    answer = drawing_answer(package, BORE)
    bound = resolved(resolve_tolerance(package, profile, BORE))

    assert (answer.dimension, answer.decimal_places, answer.unit) == (None, 2, "mm")
    assert answer.record_id == "ddm:0001"
    assert bound.source_kind == "general"
    assert bound.cited.endswith("the 2-decimal band")
    limits = limits_mm(bound.dimension)
    assert (limits.min_mm, limits.max_mm) == (4.35, 4.65)


@pytest.mark.usefixtures("validated")
def test_the_general_block_names_the_unit_when_the_drawing_writes_another(
    profile: StandardsProfile,
) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)

    why = searched(resolve_tolerance(drawn.package(), with_unit(profile, "in"), BORE))["general"]

    assert why == (
        "the drawing writes the size of hol:0002#1 in mm and the profile's bands are counted in in"
    )


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize("variant", ["version_2", "empty_unit"])
def test_the_general_block_names_the_missing_unit_setting(
    profile: StandardsProfile, variant: str
) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
    chosen = as_version_2(profile) if variant == "version_2" else with_unit(profile, "")

    why = searched(resolve_tolerance(drawn.package(), chosen, BORE))["general"]

    assert why == (
        "the profile does not say which unit its decimal places are counted in "
        "(drawing.dimension_unit)"
    )


@pytest.mark.usefixtures("validated")
def test_with_no_profile_the_general_block_says_so_as_before() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)

    why = searched(resolve_tolerance(drawn.package(), None, BORE))["general"]

    assert why == "no standards profile is attached"


@pytest.mark.usefixtures("validated")
def test_a_drawing_in_inches_binds_under_an_inch_profile(profile: StandardsProfile) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(drawing={"length_unit_raw": 3}), "fac:0002", 4.5, precision=3)

    bound = resolved(resolve_tolerance(drawn.package(), with_unit(profile, "in"), BORE))

    assert bound.source_kind == "general"
    assert bound.cited.endswith("the 3-decimal band")


@pytest.mark.usefixtures("validated")
def test_block_behaves_as_none() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=1, tolerance_type_raw=10)

    answer = drawing_answer(drawn.package(), BORE)

    assert (answer.decimal_places, answer.unit) == (1, "mm")


@pytest.mark.usefixtures("validated")
def test_general_names_the_table_and_supplies_nothing() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2, tolerance_type_raw=11)

    answer = drawing_answer(drawn.package(), BORE)

    assert (answer.dimension, answer.decimal_places, answer.unit) == (None, None, None)
    assert answer.why == (
        "ddm:0001 is governed by the drawing's general tolerance table, which is not converted"
    )


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize("general_first", [True, False])
def test_a_general_table_binding_beside_a_written_precision_binds_nothing(
    profile: StandardsProfile, general_first: bool
) -> None:
    """One dimension says an ISO 2768 class governs the size, another that the company band of
    its written precision does: the drawing disagrees with itself (FR-023), so no precision is
    handed to the general block and the reason names both, whichever comes first."""
    drawn = Drawn()
    if general_first:
        drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2, tolerance_type_raw=11)
        drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
    else:
        drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
        drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2, tolerance_type_raw=11)
    package = drawn.package()

    answer = drawing_answer(package, BORE)
    why = searched(resolve_tolerance(package, profile, BORE))

    governed, written = ("ddm:0001", "ddm:0002") if general_first else ("ddm:0002", "ddm:0001")
    assert (answer.decimal_places, answer.unit, answer.conflict) == (None, None, None)
    assert answer.why == (
        f"{governed} is governed by the drawing's general tolerance table, which is not "
        f"converted, and {written} writes 2 decimals; the two disagree, so no precision is "
        "handed to the general tolerance"
    )
    assert why["drawing"] == answer.why
    assert why["general"].startswith("the precision its dimension is written to is not recorded")


@pytest.mark.usefixtures("validated")
def test_disagreeing_precisions_bind_nothing_and_say_so(profile: StandardsProfile) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=3)
    package = drawn.package()

    answer = drawing_answer(package, BORE)
    why = searched(resolve_tolerance(package, profile, BORE))

    assert (answer.decimal_places, answer.unit) == (None, None)
    assert answer.why == "ddm:0001 writes 2 decimals and ddm:0002 writes 3"
    assert why["drawing"] == answer.why
    assert why["general"].startswith("the precision its dimension is written to is not recorded")


@pytest.mark.usefixtures("validated")
def test_disagreeing_units_bind_nothing_and_say_so() -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
    drawn.dimension(drawn.view(drawing={"length_unit_raw": 3}), "fac:0002", 4.5, precision=2)

    answer = drawing_answer(drawn.package(), BORE)

    assert answer.decimal_places is None
    assert answer.why == "ddm:0001 is written in mm and ddm:0002 in in"


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"precision": None}, "the precision ddm:0001 is written to was not read"),
        ({"units_raw": 1, "uses_document_units": False},
         "dimension ddm:0001 is written in unit 1 (swLengthUnit_e), which is neither mm nor in"),
        ({"uses_document_units": None},
         "whether dimension ddm:0001 uses its drawing's unit was not read"),
    ],
)
def test_an_unread_precision_or_unit_supplies_nothing(fields: dict[str, Any], reason: str) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0002", 4.5, **{"precision": 2, **fields})

    answer = drawing_answer(drawn.package(), BORE)

    assert (answer.decimal_places, answer.unit) == (None, None)
    assert answer.why == reason


@pytest.mark.usefixtures("validated")
def test_explicit_limits_win_over_a_written_precision() -> None:
    drawn = Drawn()
    view = drawn.view()
    drawn.dimension(view, "fac:0002", 4.5, precision=2)
    drawn.dimension(view, "fac:0002", 4.5, tolerance=("bilateral", 0.1, 0.0),
                    tolerance_type_raw=2)

    answer = drawing_answer(drawn.package(), BORE)

    assert answer.dimension is not None and answer.record_id == "ddm:0002"
    assert answer.decimal_places is None


def test_with_the_switch_off_the_drawing_binds_nothing_and_says_why(
    profile: StandardsProfile,
) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(), "fac:0001", 3.0, tolerance=("bilateral", 0.010, 0.0),
                    tolerance_type_raw=2)
    drawn.dimension(drawn.view(), "fac:0002", 4.5, precision=2)
    package = drawn.package()

    dowel = resolved(resolve_tolerance(package, profile, DOWEL))
    bore = searched(resolve_tolerance(package, profile, BORE))

    assert dowel.source_kind == "model_dimension"
    assert bore["drawing"] == NOT_VALIDATED
    assert bore["general"].startswith("the precision its dimension is written to is not recorded")
    assert drawing_answer(package, DOWEL) == DrawingAnswer(why=NOT_VALIDATED)


def _only_the_drawing(package: EvidencePackage) -> EvidencePackage:
    """`package` with the tolerances assembly's own sources taken out, so only the drawing can
    be one: no model dimension, no model annotation, no Hole Wizard data."""
    holes = [hole.model_copy(update={"wizard": None}) for hole in package.holes]
    return package.model_copy(
        update={"model_dimensions": [], "model_annotations": [], "holes": holes}
    )


def test_holds_any_source_counts_a_bindable_drawing_dimension_only_while_the_switch_is_set(
    monkeypatch: pytest.MonkeyPatch, profile: StandardsProfile
) -> None:
    """A drawing that states a tolerance, or writes an untoleranced dimension under a version
    3 profile with bands and a unit, is a source - once the seat has validated the binding."""
    toleranced, untoleranced = Drawn(), Drawn()
    toleranced.dimension(toleranced.view(), "fac:0001", 3.0,
                         tolerance=("bilateral", 0.010, 0.0), tolerance_type_raw=2)
    untoleranced.dimension(untoleranced.view(), "fac:0002", 4.5, precision=2)
    bare = [_only_the_drawing(item.package()) for item in (toleranced, untoleranced)]

    assert [ResolverLookup(item, profile).holds_any_source() for item in bare] == [False, False]
    monkeypatch.setattr(drawing_binding, "DRAWING_BINDING_VALIDATED", True)
    assert [ResolverLookup(item, profile).holds_any_source() for item in bare] == [True, True]
    assert ResolverLookup(bare[1], as_version_2(profile)).holds_any_source() is False
    assert ResolverLookup(bare[1], with_unit(profile, "")).holds_any_source() is False
    assert ResolverLookup(bare[1], None).holds_any_source() is False
    assert ResolverLookup(bare[0], None).holds_any_source() is True


@pytest.mark.usefixtures("validated")
def test_holds_any_source_ignores_a_drawing_whose_views_are_unusable(
    profile: StandardsProfile,
) -> None:
    drawn = Drawn()
    drawn.dimension(drawn.view(out_of_date=True), "fac:0001", 3.0,
                    tolerance=("bilateral", 0.010, 0.0), tolerance_type_raw=2)

    assert ResolverLookup(_only_the_drawing(drawn.package()), profile).holds_any_source() is False


@pytest.mark.usefixtures("validated")
def test_with_no_drawing_record_every_answer_is_todays_but_source_1s_wording(
    profile: StandardsProfile,
) -> None:
    """A package with no drawing record resolves exactly as feature 010 did, the switch set or
    not: only source 1's reason reads differently."""
    package = tolerances_package()
    subjects = (
        DOWEL,
        BORE,
        _replace(DOWEL, kind="hole_position"),
        ToleranceSubject(kind="pin_size", nominal_mm=3.0, document_id="doc:0004",
                         face_ids=("fac:0006",), component_id="cmp:0003"),
    )
    for subject in subjects:
        answer = resolve_tolerance(package, profile, subject)
        if isinstance(answer, UnresolvedTolerance):
            assert dict(answer.searched)["drawing"] == (
                f"no drawing of {subject.document_id} was read"
            )
        else:
            assert answer.source_kind != "drawing"
            assert "drawing" not in answer.also_found
