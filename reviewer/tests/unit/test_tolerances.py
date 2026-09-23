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
from pathlib import Path

import pytest

from swreview.checks.result import limits_mm
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.tolerances import (
    DRAWING_NOT_AVAILABLE,
    SOURCE_ORDER,
    ResolvedTolerance,
    ResolverLookup,
    ToleranceSubject,
    UnresolvedTolerance,
    resolve_tolerance,
)
from swreview.ir.models import EvidencePackage, HoleWizardData
from tests.support.mechanical import Face, Instance, PackageBuilder

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


def test_the_drawing_slot_is_not_available_before_feature_011() -> None:
    plate = Plate()

    assert searched(resolve_tolerance(plate.package(), None, plate.hole_size()))["drawing"] == (
        DRAWING_NOT_AVAILABLE
    )
    assert DRAWING_NOT_AVAILABLE == "not available before feature 011"


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
        "drawing": "not available before feature 011",
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
