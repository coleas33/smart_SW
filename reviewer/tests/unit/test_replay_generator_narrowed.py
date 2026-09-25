"""The fixture generator's finding check reads a narrowed RMS finding (008 T124, decision 23A).

`contracts/replay.md` section 8, research R2.58. Feature 003's decision 20A made the generator
refuse all three recordings: 20, 2 and 1 recorded `rms.grouping.all_features_in_a_group` keys
missing and as many new, each a finding that lost only the system-row subjects the type table
stopped counting. The check now compares through the replay's own function,
`benchmark/replay.compare_finding_keys`, imported rather than copied: a recorded finding that no
fixture finding matches is narrowed over the recorded package, its narrowed key carried into the
fixture's names by the same map as the rest of its key, and matched one to one. Nothing else
loosens: a key still missing after narrowing, or a new one, refuses.

Since the owner's decision 25A (008 T128) a key's location carries its persistent reference, and
the fixture's references are the recorded ones scrambled. `scrambled_key` carries each recorded
reference into the fixture's through `FictionalMap.persist_ref`, the function that scrambled the
package's, so the recorded findings and the fixture's compare exactly, reference by reference, and
a recorded subject swapped for another refuses.

A "recording" is a scripted review made by a type table that still counted `SensorFolder` as
content; a "fixture" is the same script recorded by today's code on the package the map
scrambled, which is what the generator compares (`tests/support/narrowed.py`).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.benchmark import replay as replay_module
from swreview.benchmark.recording import read_recording
from swreview.findings import finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.ir.models import EvidencePackage
from tests.support import mechanical
from tests.support.narrowed import (
    BOSS,
    LOOSE,
    SCRIPT,
    WIDGET,
    loose_findings,
    older_table,
    part_package,
    record,
    swap_reference,
)
from tests.support.packages import persist_ref
from tests.support.replay import record_scripted_review, rewrite_session
from tests.support.scramble import FictionalMap

pytestmark = pytest.mark.usefixtures("vocabulary")

GENERATOR = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "generate_fixtures.py"
HEX_PART = "doc:0a1b2c3d4e5f"
"""A part id shaped like an extractor's, which the map re-hexes: the narrowed key must be carried
into the fixture's names to match."""
NO_PLACE = (None, None, None, None)
"""A location's sheet, view, annotation and page, as an RMS subject's location has none."""


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


# --- references carried by the map (owner decision 25A, 008 T128) --------------------------------


def test_the_generators_mapped_keys_equal_the_fixtures_exactly(
    generator: ModuleType, tmp_path: Path
) -> None:
    """Every recorded key, through `scrambled_key`, is a fixture key, as a multiset - and the map
    moved every reference, each by the function that scrambled the package's references."""
    today = record(tmp_path / "today", part_package(document_id=HEX_PART))
    fmap = a_map(today)
    fixture = fixture_of(tmp_path, today, fmap)
    recorded = [finding_subject_key(item.finding) for item in read_recording(today).findings]
    written = [finding_subject_key(item.finding) for item in read_recording(fixture).findings]

    mapped = [generator.scrambled_key(fmap, key) for key in recorded]

    assert Counter(mapped) == Counter(written)
    pairs = [
        (location[5], carried[5])
        for key, into in zip(recorded, mapped, strict=True)
        for location, carried in zip(key[2], into[2], strict=True)
    ]
    assert pairs, "the recording's loose finding names a location with a reference"
    for reference, carried in pairs:
        assert carried == fmap.persist_ref(reference) != reference


def test_the_carried_locations_are_put_back_in_the_keys_order(generator: ModuleType) -> None:
    """The map can change which of two references sorts first; the fixture's key holds its
    locations in its own order, so the carried key must too, or equal multisets would differ."""
    fmap = FictionalMap()
    first, second = (persist_ref(f"doc:3/{name}") for name in ("Gadget1", "Sprocket1"))
    carried_first, carried_second = fmap.persist_ref(first), fmap.persist_ref(second)
    assert (first < second) != (carried_first < carried_second), "the premise: the map flips them"
    locations = (("doc:3", *NO_PLACE, first), ("doc:3", *NO_PLACE, second))
    key = (LOOSE, ("cmp:0002",), locations, (), "Default")

    carried = generator.scrambled_key(fmap, key)[2]

    assert [location[5] for location in carried] == sorted([carried_first, carried_second])


def test_a_location_without_a_reference_is_carried_without_one(generator: ModuleType) -> None:
    fmap = FictionalMap()
    location = (HEX_PART, "Sheet1", None, None, 2, None)
    key = ("drawing.manufacturing_inputs", (), (location,), (), "Default")

    [carried] = generator.scrambled_key(fmap, key)[2]

    assert carried == (fmap.value(HEX_PART), fmap.value("Sheet1"), None, None, 2, None)


def test_a_recorded_subject_swapped_for_another_refuses(
    generator: ModuleType, tmp_path: Path
) -> None:
    """The recording's loose finding names `Boss1` where the fixture's names `Widget1`: one
    location on the part either way, not the same item."""
    today = record(tmp_path / "today", part_package(document_id=HEX_PART))
    fmap = a_map(today)
    fixture = fixture_of(tmp_path, today, fmap)
    swap_reference(today, WIDGET, BOSS)

    assert check(generator, today, fixture, fmap) == (
        ["the finding keys differ: 1 recorded keys are missing and 1 are new"],
        0,
        0,
    )


def test_a_narrowed_finding_whose_remaining_subject_was_swapped_refuses(
    generator: ModuleType, tmp_path: Path, recording: Path
) -> None:
    fmap = a_map(recording)
    fixture = fixture_of(tmp_path, recording, fmap)
    swap_reference(recording, WIDGET, BOSS)

    assert check(generator, recording, fixture, fmap) == (
        ["the finding keys differ: 1 recorded keys are missing and 1 are new"],
        0,
        0,
    )
