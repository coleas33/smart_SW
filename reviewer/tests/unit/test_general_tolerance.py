"""The profile's general tolerance block (feature 010 T080, `contracts/tolerances.md` section 3).

By decimal places (owner answer 2026-09-23): a dimension written to `.XX` takes the band
declared for 2 decimal places. The band values are the profile's - the example file carries
clearly labelled placeholders until the owner supplies the real ones - and never a number in
the source. Outside every band, on a version 1 profile, for a position, or for a subject
whose written precision is not recorded, the block gives nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks import tolerances
from swreview.checks.result import limits_mm
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.tolerances import ToleranceSubject, general_tolerance_dimension

REVIEWER = Path(__file__).resolve().parents[1].parent
PROFILE_A = REVIEWER / "tests" / "fixtures" / "standards" / "profile-a.yaml"
EXAMPLE = REVIEWER.parent / "config" / "standards.example.yaml"


@pytest.fixture(scope="module")
def profile() -> StandardsProfile:
    return load_profile(PROFILE_A)


def subject(places: int | None, kind: str = "hole_size") -> ToleranceSubject:
    return ToleranceSubject(
        kind=kind,  # type: ignore[arg-type]
        nominal_mm=12.0,
        document_id="doc:0002",
        instance_id="hol:0001#1",
        decimal_places=places,
    )


@pytest.mark.parametrize("places", [1, 2, 3])
def test_the_band_is_selected_by_decimal_places(profile: StandardsProfile, places: int) -> None:
    assert profile.general_tolerance is not None
    band = next(item for item in profile.general_tolerance.linear if item.decimal_places == places)

    dimension = general_tolerance_dimension(profile, subject(places))

    assert not isinstance(dimension, str)
    assert dimension.tolerance.kind == "symmetric"
    limits = limits_mm(dimension)
    assert (limits.min_mm, limits.max_mm) == (
        pytest.approx(12.0 - band.plus_minus_mm),
        pytest.approx(12.0 + band.plus_minus_mm),
    )


def test_the_dimension_cites_the_profile_identity_and_no_value(profile: StandardsProfile) -> None:
    dimension = general_tolerance_dimension(profile, subject(2))

    assert not isinstance(dimension, str)
    cited = dimension.tolerance.source.annotation
    assert cited is not None
    assert cited.startswith(
        f"general_tolerance of the standards profile sha256 {profile.identity.sha256[:12]}"
    )
    assert "2-decimal band" in cited
    assert dimension.text_as_read == "12.00"


def test_a_profile_is_named_by_its_sha256_or_as_built_in_memory(
    profile: StandardsProfile,
) -> None:
    """One reading of a profile's identity (`profile_sha256`), worded by each caller: the
    citation here, and the brief's `conformance.profile` (feature 011 review, 2026-09-23)."""
    in_memory = StandardsProfile.model_validate(profile.model_dump())

    assert tolerances.profile_sha256(profile) == profile.identity.sha256[:12]
    assert tolerances.profile_sha256(in_memory) is None
    assert tolerances.profile_name(profile) == (
        f"the standards profile sha256 {profile.identity.sha256[:12]}"
    )
    assert tolerances.profile_name(in_memory) == "the standards profile (built in memory)"


def test_a_precision_no_band_names_gives_nothing(profile: StandardsProfile) -> None:
    assert general_tolerance_dimension(profile, subject(4)) == (
        "the profile declares no band for 4 decimal places"
    )


def test_an_unrecorded_precision_gives_nothing(profile: StandardsProfile) -> None:
    answer = general_tolerance_dimension(profile, subject(None))

    assert answer == (
        "the precision its dimension is written to is not recorded, so no decimal-place band "
        "applies (a drawing records it, feature 011)"
    )


def test_a_version_1_profile_gives_nothing(profile: StandardsProfile) -> None:
    version_1 = profile.model_copy(
        update={"version": 1, "hygiene": None, "general_tolerance": None}
    )

    assert general_tolerance_dimension(version_1, subject(2)) == (
        "the profile is version 1, which declares no general tolerance"
    )


def test_no_profile_gives_nothing() -> None:
    assert general_tolerance_dimension(None, subject(2)) == "no standards profile is attached"


def test_an_empty_block_gives_nothing(profile: StandardsProfile) -> None:
    assert profile.general_tolerance is not None
    empty = profile.model_copy(
        update={"general_tolerance": profile.general_tolerance.model_copy(update={"linear": []})}
    )

    assert general_tolerance_dimension(empty, subject(2)) == (
        "the profile declares no general tolerance band"
    )


def test_a_position_is_never_given_a_general_tolerance(profile: StandardsProfile) -> None:
    assert general_tolerance_dimension(profile, subject(2, "hole_position")) == (
        "a general tolerance block tolerances sizes, never a position zone"
    )


def test_the_example_bands_are_labelled_placeholders() -> None:
    """The owner has not supplied the real bands (research R5): the example says so."""
    text = EXAMPLE.read_text(encoding="utf-8")
    block = text.split("general_tolerance:", 1)[1].split("hygiene:", 1)[0]

    assert "EXAMPLE" in block and "placeholder" in block.lower()


def test_no_band_value_is_in_the_source(profile: StandardsProfile) -> None:
    source = Path(tolerances.__file__).read_text(encoding="utf-8")

    assert profile.general_tolerance is not None
    for band in profile.general_tolerance.linear:
        assert repr(band.plus_minus_mm) not in source
