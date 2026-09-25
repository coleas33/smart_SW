"""The fixture generator's finding check reads a narrowed RMS finding (008 T124, decision 23A).

`contracts/replay.md` section 8, research R2.58. Feature 003's decision 20A made the generator
refuse all three recordings: 20, 2 and 1 recorded `rms.grouping.all_features_in_a_group` keys
missing and as many new, each a finding that lost only the system-row subjects the type table
stopped counting. The check now compares through the replay's own function,
`benchmark/replay.compare_finding_keys`, imported rather than copied: a recorded finding that no
fixture finding matches is narrowed over the recorded package, its narrowed key carried into the
fixture's names by the same map as the rest of its key, and matched one to one. Nothing else
loosens: a key still missing after narrowing, or a new one, refuses.

A "recording" is a scripted review made by a type table that still counted `SensorFolder` as
content; a "fixture" is the same script recorded by today's code on the package the map
scrambled, which is what the generator compares (`tests/support/narrowed.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.benchmark import replay as replay_module
from swreview.benchmark.recording import read_recording
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.ir.models import EvidencePackage
from tests.support import mechanical
from tests.support.narrowed import (
    LOOSE,
    SCRIPT,
    loose_findings,
    older_table,
    part_package,
    record,
)
from tests.support.replay import record_scripted_review, rewrite_session
from tests.support.scramble import FictionalMap

pytestmark = pytest.mark.usefixtures("vocabulary")

GENERATOR = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "generate_fixtures.py"
HEX_PART = "doc:0a1b2c3d4e5f"
"""A part id shaped like an extractor's, which the map re-hexes: the narrowed key must be carried
into the fixture's names to match."""


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return mechanical.load_generator(GENERATOR)


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    """Recorded by the older table: the loose finding names the system row and the unknown one."""
    run = record(
        tmp_path / "recording",
        part_package(document_id=HEX_PART),
        older_table(tmp_path / "older"),
    )
    [finding] = loose_findings(run)
    assert len(finding.drawing_locations) == 2
    return run


def fixture_of(tmp_path: Path, recording: Path, fmap: FictionalMap) -> Path:
    """The recording's package scrambled by `fmap`, recorded by today's code - the generator's
    fixture, less the usage adjustment the finding check does not read."""
    raw = json.loads((recording / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))
    package_dir = tmp_path / "fixture-package"
    package_dir.mkdir()
    scrambled = fmap.package(raw)
    EvidencePackage.model_validate(scrambled)
    (package_dir / PACKAGE_FILE_NAME).write_text(json.dumps(scrambled), encoding="utf-8")
    return record_scripted_review(tmp_path / "fixture", package_dir, SCRIPT)


def a_map(recording: Path) -> FictionalMap:
    raw = json.loads((recording / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))
    return FictionalMap(keep={row["type_name"] for row in raw["features"]})


def check(generator: ModuleType, recording: Path, fixture: Path, fmap: FictionalMap) -> Any:
    return generator.finding_problems(read_recording(recording), read_recording(fixture), fmap)


def test_the_generator_compares_through_the_replays_function(generator: ModuleType) -> None:
    assert generator.compare_finding_keys is replay_module.compare_finding_keys


def test_a_recorded_finding_the_table_narrowed_is_matched_and_counted(
    generator: ModuleType, tmp_path: Path, recording: Path
) -> None:
    fmap = a_map(recording)
    fixture = fixture_of(tmp_path, recording, fmap)
    [today] = loose_findings(fixture)
    assert len(today.drawing_locations) == 1
    assert today.drawing_locations[0].document_id == fmap.value(HEX_PART) != HEX_PART

    assert check(generator, recording, fixture, fmap) == ([], 0, 1)


def test_the_narrowed_key_is_carried_into_the_fixtures_names(
    generator: ModuleType, tmp_path: Path, recording: Path
) -> None:
    """Against a fixture that kept the recorded part id, the narrowed key - in the fixture's
    names - matches nothing: the map, not the recorded id, decides."""
    fmap = a_map(recording)
    fmap.package(json.loads((recording / PACKAGE_FILE_NAME).read_text(encoding="utf-8")))
    unscrambled = record(tmp_path / "unscrambled", part_package(document_id=HEX_PART))

    assert check(generator, recording, unscrambled, fmap) == (
        ["the finding keys differ: 1 recorded keys are missing and 1 are new"],
        0,
        0,
    )


def test_a_key_still_missing_after_narrowing_refuses(
    generator: ModuleType, tmp_path: Path, recording: Path
) -> None:
    fmap = a_map(recording)
    fixture = fixture_of(tmp_path, recording, fmap)

    def elsewhere(session: dict[str, Any]) -> None:
        for finding in session["findings"]:
            if finding["check"] == LOOSE:
                finding["configuration"] = "Other"

    rewrite_session(recording, elsewhere)

    assert check(generator, recording, fixture, fmap) == (
        ["the finding keys differ: 1 recorded keys are missing and 1 are new"],
        0,
        0,
    )


def test_a_second_recorded_finding_onto_one_fixture_finding_refuses(
    generator: ModuleType, tmp_path: Path, recording: Path
) -> None:
    fmap = a_map(recording)
    fixture = fixture_of(tmp_path, recording, fmap)

    def twice(session: dict[str, Any]) -> None:
        [recorded] = [f for f in session["findings"] if f["check"] == LOOSE]
        session["findings"].append({**recorded, "id": "F-900"})

    rewrite_session(recording, twice)

    assert check(generator, recording, fixture, fmap) == (
        ["the finding keys differ: 1 recorded keys are missing and 0 are new"],
        0,
        1,
    )


def test_with_nothing_narrowed_the_check_is_the_one_it_was(
    generator: ModuleType, tmp_path: Path
) -> None:
    today = record(tmp_path / "today", part_package(document_id=HEX_PART))
    fmap = a_map(today)
    fixture = fixture_of(tmp_path, today, fmap)

    assert check(generator, today, fixture, fmap) == ([], 0, 0)
