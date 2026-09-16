"""Unit tests for the two tolerance profiles (T096).

`data-model.md` section 3.2 and `research.md` R4.4 give the whole specification, and it is
three claims:

- **two named profiles, declared as frozen constants, never assembled at a call site.**
  `IDENTITY` (1e-9 on volume, area, centre of mass and moments; face count exact; body
  count exact) is stage 1, where nothing geometric is supposed to change, so any measured
  difference is a defect. `EQUIVALENCE` (1e-6, 1e-5, 1e-6, 1e-5; face count warn; body
  count exact) is declared for stage 2 and is selected by no v1 code path;
- **every tolerance constant is in metres, every angle is in radians, and no comparison
  mixes an absolute bound with a relative one** (SC-010). Every profile bound is relative
  and dimensionless; the only absolute constants in the module are the tier-2 residual
  thresholds, and each one carries its unit in its name;
- **a tolerance that has never been compared against a known answer does not ship**
  (FR-036). `load_profile` raises until PROBE-8's calibration ledger is checked in, which
  is what T138 does on the workstation; the numbers then live in the ledger, not in a
  comment.
"""

from __future__ import annotations

import re

import pytest

from swreview.remodel import tolerances as tol_module
from swreview.remodel.tolerances import (
    EQUIVALENCE,
    IDENTITY,
    PROFILES,
    RESIDUAL_MIN_DIMENSION_M,
    RESIDUAL_VOLUME_FLOOR_M3,
    RESIDUAL_VOLUME_REL,
    Tolerances,
    UncalibratedProfileError,
    load_profile,
)

RELATIVE_BOUNDS = ("volume_rel", "area_rel", "com_rel", "moment_rel")


def test_identity_profile_is_the_stage_1_numbers() -> None:
    assert IDENTITY.name == "IDENTITY"
    assert IDENTITY.volume_rel == 1e-9
    assert IDENTITY.area_rel == 1e-9
    assert IDENTITY.com_rel == 1e-9
    assert IDENTITY.moment_rel == 1e-9
    assert IDENTITY.face_count == "exact"
    assert IDENTITY.body_count == "exact"


def test_equivalence_profile_is_the_stage_2_numbers() -> None:
    assert EQUIVALENCE.name == "EQUIVALENCE"
    assert EQUIVALENCE.volume_rel == 1e-6
    assert EQUIVALENCE.area_rel == 1e-5
    assert EQUIVALENCE.com_rel == 1e-6
    assert EQUIVALENCE.moment_rel == 1e-5
    assert EQUIVALENCE.face_count == "warn"
    assert EQUIVALENCE.body_count == "exact"


def test_the_two_profiles_are_the_only_ones_and_are_registered_by_name() -> None:
    assert PROFILES == {"IDENTITY": IDENTITY, "EQUIVALENCE": EQUIVALENCE}


def test_a_profile_is_a_frozen_constant_and_cannot_be_edited_at_a_call_site() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError on a frozen model
        IDENTITY.volume_rel = 1e-3  # type: ignore[misc]


def test_equivalence_is_looser_than_identity_on_every_bound() -> None:
    for field in RELATIVE_BOUNDS:
        assert getattr(EQUIVALENCE, field) > getattr(IDENTITY, field), field


def test_the_field_set_is_closed_so_a_new_bound_cannot_arrive_unnoticed() -> None:
    assert set(Tolerances.model_fields) == {
        "name",
        "volume_rel",
        "area_rel",
        "com_rel",
        "moment_rel",
        "face_count",
        "body_count",
        "calibrated",
        "calibration_ref",
    }


@pytest.mark.parametrize("profile", [IDENTITY, EQUIVALENCE], ids=["IDENTITY", "EQUIVALENCE"])
def test_every_profile_bound_is_relative_and_dimensionless(profile: Tolerances) -> None:
    """No bound is a length, so no comparison can mix an absolute with a relative one."""
    for field in RELATIVE_BOUNDS:
        value = getattr(profile, field)
        assert isinstance(value, float)
        assert 0.0 < value < 1.0, f"{field} is not a dimensionless ratio"
    assert {f for f in Tolerances.model_fields if f.endswith("_rel")} == set(RELATIVE_BOUNDS)


def test_no_profile_field_carries_a_length_or_an_angle_unit() -> None:
    """A bound named `_m`, `_mm` or `_deg` would be an absolute bound in a relative table."""
    for field in Tolerances.model_fields:
        assert not re.search(r"_(m|mm|m2|m3|deg|degrees|rad)$", field), field


def test_the_count_rules_are_the_only_non_numeric_bounds() -> None:
    assert IDENTITY.face_count in {"exact", "warn"}
    assert EQUIVALENCE.face_count in {"exact", "warn"}
    assert IDENTITY.body_count == "exact" and EQUIVALENCE.body_count == "exact"


def test_every_absolute_constant_in_the_module_names_its_unit() -> None:
    """Metres and cubic metres, said in the name: the tier-2 residual thresholds."""
    assert RESIDUAL_VOLUME_FLOOR_M3 == 1e-12
    assert RESIDUAL_VOLUME_REL == 1e-6
    assert RESIDUAL_MIN_DIMENSION_M == 1e-5
    for name, value in vars(tol_module).items():
        if name.isupper() and isinstance(value, float) and not name.endswith("_REL"):
            assert name.endswith(("_M", "_M3", "_RAD")), name


def test_no_angle_is_carried_and_none_could_arrive_in_degrees() -> None:
    """Every angle is in radians; the gate carries none, and none may arrive in degrees."""
    assert not [f for f in Tolerances.model_fields if "angle" in f or f.endswith("_deg")]
    assert not [n for n in vars(tol_module) if n.isupper() and n.endswith(("_DEG", "_DEGREES"))]


def test_loading_a_profile_raises_until_the_probe_8_ledger_is_present() -> None:
    """FR-036: a tolerance never compared against a known answer does not ship."""
    assert IDENTITY.calibrated is False
    assert IDENTITY.calibration_ref is None
    assert EQUIVALENCE.calibrated is False
    assert EQUIVALENCE.calibration_ref is None
    for name in PROFILES:
        with pytest.raises(UncalibratedProfileError) as excinfo:
            load_profile(name)  # type: ignore[arg-type]
        message = str(excinfo.value)
        assert name in message
        assert "PROBE-8" in message
        assert "tolerance-calibration" in message


def test_loading_returns_the_profile_once_the_ledger_has_calibrated_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What T138 does on the workstation: the ledger fills in the reference, nothing else."""
    calibrated = IDENTITY.model_copy(
        update={"calibrated": True, "calibration_ref": "PROBE-8 2026-09-16"}
    )
    ledger = {"IDENTITY": calibrated, "EQUIVALENCE": EQUIVALENCE}
    monkeypatch.setattr(tol_module, "PROFILES", ledger)
    assert load_profile("IDENTITY") is calibrated
    with pytest.raises(UncalibratedProfileError):
        load_profile("EQUIVALENCE")


def test_loading_an_unknown_profile_name_is_refused_by_name() -> None:
    with pytest.raises(KeyError) as excinfo:
        load_profile("LOOSE")  # type: ignore[arg-type]
    assert "LOOSE" in str(excinfo.value)
