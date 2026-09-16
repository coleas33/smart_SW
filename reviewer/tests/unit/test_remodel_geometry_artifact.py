"""`geometry.json`, the artifact the gate leaves behind (T102).

`contracts/run-artifacts.md` gives the shape - `before`, `after`, `gate` and `tolerances`
- and `data-model.md` section 3 gives every field name inside it. The artifact exists so
that a reader who was not there can see what was measured, what it was compared against,
what the verdict was, and **what the verdict cannot cover**.

The claims this file pins are the ones that would be invisible in a passing run:

- **both readings are of the copy** (FR-037): `copy_at_open` after the baseline rollback
  and rebuild, `copy_at_end` after the last change. The artifact refuses any other
  pairing, so a reading of something else cannot be filed as a baseline;
- **the source is never opened for the comparison, in any mode**. `source_sha256` is the
  attested hash that makes the baseline stand for the source, identical on both readings,
  and the writer touches nothing outside the run folder - asserted here against a fake
  filesystem that fails any open of a path other than the artifact's;
- **no tolerance that has never been compared against a known answer decides a shipped
  run** (FR-036, `data-model.md` section 3.2): the writer refuses a profile whose
  `calibrated` flag is false, so the artifact cannot record a pass under bounds nobody
  has measured;
- **no reference body enters any tree**, so `IPartDoc.InsertPart3` appears nowhere in
  stage 1 - scanned over every file the stage-1 surface is written in, Python and C# -
  and there is no prototype reading to hold one;
- `coverage_limits` is written on **every** run including a passing one, and names the
  difference produced by the baseline rollback and rebuild themselves alongside the five
  differences tier 1 is blind to.
"""

from __future__ import annotations

import json
import pathlib
from pathlib import Path
from typing import Any, get_args

import pytest

from swreview.remodel.geometry import (
    COVERAGE_LIMITS,
    GeometryArtifact,
    GeometryReading,
    Subject,
    evaluate,
    write_geometry_json,
)
from swreview.remodel.tolerances import CALIBRATION_LEDGER, IDENTITY, UncalibratedProfileError
from tests.support.remodel import code_lines, stage_1_sources

SOURCE_SHA = "4c" * 32
OTHER_SHA = "77" * 32

CALIBRATION_REF = "PROBE-8 2026-09-16"
CALIBRATED = IDENTITY.model_copy(update={"calibrated": True, "calibration_ref": CALIBRATION_REF})
"""`IDENTITY` as a shipping run may use it: the same bounds, once PROBE-8 has measured the
attained error against a part of exactly known analytic volume and the ledger says so.
`contracts/run-artifacts.md` shows exactly this block in `geometry.json`."""

BASELINE: dict[str, Any] = {
    "at": "2026-09-16T14:22:01Z",
    "source_sha256": SOURCE_SHA,
    "subject": "copy_at_open",
    "status": 0,
    "accuracy_level": 2,
    "recalculated": True,
    "volume_m3": 1.23456789e-3,
    "surface_area_m2": 4.56e-2,
    "center_of_mass_m": (0.01, 0.02, 0.03),
    "principal_moments": (1.1e-5, 2.2e-5, 3.3e-5),
    "mass_kg": 3.21,
    "density": 2600.0,
    "material_name": "1060 Alloy",
    "solid_body_count": 1,
    "sheet_body_count": 0,
    "face_count": 214,
    "edge_count": 642,
    "residual": None,
}


def reading(**overrides: Any) -> GeometryReading:
    return GeometryReading(**{**BASELINE, **overrides})


def written(tmp_path: Path) -> dict[str, Any]:
    before = reading()
    after = reading(subject="copy_at_end", at="2026-09-16T14:41:55Z")
    gate = evaluate(before, after, CALIBRATED)
    path = write_geometry_json(
        tmp_path, before=before, after=after, gate=gate, tolerances=CALIBRATED
    )
    assert path == tmp_path / "geometry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_artifact_carries_the_four_named_blocks(tmp_path: Path) -> None:
    body = written(tmp_path)
    assert set(body) == {"before", "after", "gate", "tolerances"}


def test_both_readings_carry_every_field_of_data_model_section_3_1(tmp_path: Path) -> None:
    body = written(tmp_path)
    for side in ("before", "after"):
        assert set(body[side]) == {
            "at",
            "source_sha256",
            "subject",
            "status",
            "accuracy_level",
            "recalculated",
            "volume_m3",
            "surface_area_m2",
            "center_of_mass_m",
            "principal_moments",
            "mass_kg",
            "density",
            "material_name",
            "solid_body_count",
            "sheet_body_count",
            "face_count",
            "edge_count",
            "residual",
        }, side
    assert body["before"]["volume_m3"] == 1.23456789e-3
    assert body["before"]["principal_moments"] == [1.1e-5, 2.2e-5, 3.3e-5]
    assert body["before"]["residual"] is None, "tier 2 does not run in v1"


def test_both_readings_are_of_the_copy_and_name_the_source_they_stand_for(
    tmp_path: Path,
) -> None:
    body = written(tmp_path)
    assert body["before"]["subject"] == "copy_at_open"
    assert body["after"]["subject"] == "copy_at_end"
    assert body["before"]["source_sha256"] == SOURCE_SHA
    assert body["after"]["source_sha256"] == SOURCE_SHA


def test_the_gate_block_carries_the_verdict_and_everything_it_was_reached_from(
    tmp_path: Path,
) -> None:
    body = written(tmp_path)
    assert set(body["gate"]) == {
        "verdict",
        "profile",
        "tier_1",
        "tier_2",
        "deltas",
        "material_changed",
        "coverage_limits",
        "diagnosis",
    }
    assert body["gate"]["verdict"] == "pass"
    assert body["gate"]["profile"] == "IDENTITY"
    assert body["gate"]["tier_1"] == {"ran": True, "verdict": "pass", "reason": None}
    assert body["gate"]["tier_2"] is None
    assert body["gate"]["material_changed"] is False
    assert body["gate"]["diagnosis"] is None


def test_each_delta_carries_its_quantity_its_bound_and_whether_it_was_within(
    tmp_path: Path,
) -> None:
    body = written(tmp_path)
    volume = [d for d in body["gate"]["deltas"] if d["quantity"] == "volume_m3"]
    assert len(volume) == 1
    assert set(volume[0]) == {
        "quantity",
        "before",
        "after",
        "absolute",
        "relative",
        "bound",
        "within",
        "gates",
    }
    assert volume[0]["bound"] == CALIBRATED.volume_rel
    assert volume[0]["within"] is True


def test_coverage_limits_are_written_on_a_passing_run(tmp_path: Path) -> None:
    body = written(tmp_path)
    limits = body["gate"]["coverage_limits"]
    assert list(COVERAGE_LIMITS) == limits[: len(COVERAGE_LIMITS)]
    printed = " | ".join(limits)
    assert "reflection" in printed
    assert "rigid rotation about a symmetry axis" in printed
    assert "compensating add and remove" in printed
    assert "occupying no volume" in printed
    assert "wire-body" in printed
    assert "baseline rollback and rebuild" in printed


def test_the_tolerance_block_carries_the_profile_with_its_calibration(tmp_path: Path) -> None:
    body = written(tmp_path)
    assert body["tolerances"]["volume_rel"] == 1e-9
    assert body["tolerances"]["area_rel"] == 1e-9
    assert body["tolerances"]["com_rel"] == 1e-9
    assert body["tolerances"]["moment_rel"] == 1e-9
    assert body["tolerances"]["face_count"] == "exact"
    assert body["tolerances"]["body_count"] == "exact"
    assert body["tolerances"]["calibrated"] is True
    assert body["tolerances"]["calibration_ref"] == CALIBRATION_REF


def test_an_uncalibrated_profile_never_reaches_the_artifact(tmp_path: Path) -> None:
    """FR-036: a tolerance that has never been compared against a known answer does not ship.

    `IDENTITY` as it stands today is uncalibrated - PROBE-8 has not run - so the writer
    refuses it by name rather than filing a `pass` beside bounds nobody has measured, and
    it refuses before writing anything at all.
    """
    before = reading()
    after = reading(subject="copy_at_end")
    gate = evaluate(before, after, IDENTITY)
    assert gate.verdict == "pass", "the gate still decides; it is the artifact that refuses"
    with pytest.raises(UncalibratedProfileError) as raised:
        write_geometry_json(tmp_path, before=before, after=after, gate=gate, tolerances=IDENTITY)
    message = str(raised.value)
    assert "IDENTITY" in message
    assert "PROBE-8" in message
    assert CALIBRATION_LEDGER in message
    assert not (tmp_path / "geometry.json").exists(), "and nothing is written"


def test_the_artifact_round_trips_through_its_own_model(tmp_path: Path) -> None:
    before = reading()
    after = reading(subject="copy_at_end")
    gate = evaluate(before, after, CALIBRATED)
    path = write_geometry_json(
        tmp_path, before=before, after=after, gate=gate, tolerances=CALIBRATED
    )
    reloaded = GeometryArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    assert reloaded.before == before
    assert reloaded.after == after
    assert reloaded.gate == gate
    assert reloaded.tolerances == CALIBRATED


def test_a_baseline_that_is_not_the_copy_at_open_is_refused(tmp_path: Path) -> None:
    before = reading(subject="copy_at_end")
    after = reading(subject="copy_at_end")
    gate = evaluate(before, after, CALIBRATED)
    with pytest.raises(ValueError, match="copy_at_open"):
        write_geometry_json(tmp_path, before=before, after=after, gate=gate, tolerances=CALIBRATED)


def test_a_final_reading_that_is_not_the_copy_at_end_is_refused(tmp_path: Path) -> None:
    before = reading()
    after = reading()
    gate = evaluate(before, after, CALIBRATED)
    with pytest.raises(ValueError, match="copy_at_end"):
        write_geometry_json(tmp_path, before=before, after=after, gate=gate, tolerances=CALIBRATED)


def test_two_readings_that_stand_for_different_sources_are_refused(tmp_path: Path) -> None:
    before = reading()
    after = reading(subject="copy_at_end", source_sha256=OTHER_SHA)
    gate = evaluate(before, after, CALIBRATED)
    with pytest.raises(ValueError, match="source_sha256"):
        write_geometry_json(tmp_path, before=before, after=after, gate=gate, tolerances=CALIBRATED)


def test_a_gate_decided_by_another_profile_than_the_one_filed_is_refused(tmp_path: Path) -> None:
    before = reading()
    after = reading(subject="copy_at_end")
    gate = evaluate(before, after, CALIBRATED)
    other = CALIBRATED.model_copy(update={"name": "EQUIVALENCE"})
    with pytest.raises(ValueError, match="profile"):
        write_geometry_json(tmp_path, before=before, after=after, gate=gate, tolerances=other)


def test_the_writer_opens_nothing_but_the_artifact_it_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fake fails any open of a path other than the copy's own run folder.

    The source is never opened for the comparison in any mode (FR-037), and the artifact
    writer is the only place in this module that touches the filesystem at all, so the
    whole gate is covered by this one guard.
    """
    artifact = tmp_path / "geometry.json"
    source = tmp_path.parent / "bracket.SLDPRT"
    source.write_text("the engineer's file", encoding="utf-8")
    real_open = pathlib.Path.open

    def guarded_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self != artifact:
            raise AssertionError(f"the gate opened {self}, which is not the run artifact")
        return real_open(self, *args, **kwargs)

    def refuse_read(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"the gate read {self}, and it reads nothing")

    monkeypatch.setattr(pathlib.Path, "open", guarded_open)
    monkeypatch.setattr(pathlib.Path, "read_text", refuse_read)
    monkeypatch.setattr(pathlib.Path, "read_bytes", refuse_read)

    before = reading()
    after = reading(subject="copy_at_end")
    gate = evaluate(before, after, CALIBRATED)
    written_path = write_geometry_json(
        tmp_path, before=before, after=after, gate=gate, tolerances=CALIBRATED
    )
    assert written_path == artifact
    monkeypatch.undo()
    assert source.read_text(encoding="utf-8") == "the engineer's file"
    assert json.loads(artifact.read_text(encoding="utf-8"))["gate"]["verdict"] == "pass"


def test_no_reference_body_can_enter_any_tree_anywhere_in_stage_1() -> None:
    """There is no prototype reading, so `IPartDoc.InsertPart3` has nothing to insert.

    The type carries two subjects and neither is a prototype, and no file of the stage-1
    surface - the re-modeler's Python, the extractor's `Rms` family and both guards -
    names the member outside a comment.
    """
    assert set(get_args(Subject)) == {"copy_at_open", "copy_at_end"}
    assert "prototype" not in GeometryReading.model_fields
    for path in stage_1_sources():
        assert not [line for line in code_lines(path) if "InsertPart3" in line], path
