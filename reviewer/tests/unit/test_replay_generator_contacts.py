"""The fixture generator's finding check accepts a touching group recorded as a contact (008 T119).

Owner decision 3A of 2026-09-23 (`contracts/replay.md` section 8, research R2.56): the replay
fixtures follow the code, and since feature 010 the code records a touching group as a contact
where the recorded reviews wrote an `interference.static` finding. The generator's self-check
compared the finding keys alone, so it refused the big recording (3 keys missing) and
`small-assembly-a`'s (2). It now takes out each recorded finding a contact of the fixture
reclassifies - by the replay's own rule, `benchmark/replay.reclassifying_contacts` over
`judged_group`, imported rather than copied - after carrying the recorded group into the
fixture's fictional names (`fixture_group`, the map the rows are written with). Nothing else
loosens: a key still missing, or a new one, refuses.

A "recording" here is a scripted review made with the contact rule off (every touching group a
finding, as the evening's code wrote them); a "fixture" is the same script recorded by today's
code (the touching group a contact), which is exactly what the generator compares.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from swreview.agent.providers.fake import ScriptedToolCall
from swreview.benchmark import replay as replay_module
from swreview.benchmark.recording import Recording, read_recording
from swreview.benchmark.replay import TurnPlan
from swreview.checks import interference
from swreview.ir.loader import save_package
from swreview.ir.models import Volume
from tests.support import mechanical
from tests.support.prerun import GROUP_KEY, prerun_package
from tests.support.replay import record_scripted_review, rewrite_session
from tests.support.scramble import FictionalMap

pytestmark = pytest.mark.usefixtures("vocabulary")

GENERATOR = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "generate_fixtures.py"
SUMMARY = ScriptedToolCall("get_package_summary")
JUDGE = ScriptedToolCall("check_interference_group", {"group_key": GROUP_KEY})
SCRIPT = [TurnPlan(rounds=((SUMMARY,), (JUDGE,)), text="Done.")]
NAMED_GROUP = "Zorbexil-12|Quintarak-3"
"""A group key made of names, as an extractor's pattern ids can be: the map must scramble it."""


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return mechanical.load_generator(GENERATOR)


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    """`prerun_package` with its one interference group touching (0.0 mm3)."""
    package = prerun_package()
    [row] = package.interferences
    touching = row.model_copy(update={"volume": Volume(value=0.0, unit="mm3")})
    directory = tmp_path / "package"
    save_package(package.model_copy(update={"interferences": [touching]}), directory)
    return directory


def recording_before_contacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, package_dir: Path
) -> Path:
    with monkeypatch.context() as patched:
        patched.setattr(interference, "CONTACT_VOLUME_MM3", -1.0)
        return record_scripted_review(tmp_path / "recording", package_dir, SCRIPT)


def fixture_by_todays_code(tmp_path: Path, package_dir: Path) -> Path:
    return record_scripted_review(tmp_path / "fixture", package_dir, SCRIPT)


def check(
    generator: ModuleType, recording: Path, fixture: Path, fmap: FictionalMap | None = None
) -> tuple[list[str], int]:
    recorded: Recording = read_recording(recording)
    return generator.finding_problems(
        recorded, read_recording(fixture), fmap if fmap is not None else FictionalMap()
    )


def interference_findings(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in session["findings"] if item["check"] == "interference.static"]


@pytest.fixture
def pair(
    tmp_path: Path, package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """A recording with the touching group as a finding, and a fixture with it as a contact."""
    recording = recording_before_contacts(monkeypatch, tmp_path, package_dir)
    fixture = fixture_by_todays_code(tmp_path, package_dir)
    assert len(interference_findings(_session(recording))) == 1
    assert interference_findings(_session(fixture)) == []
    assert [c["group_key"] for c in _session(fixture)["contacts"]] == [GROUP_KEY]
    return recording, fixture


def _session(run: Path) -> dict[str, Any]:
    return json.loads((run / "session.json").read_text(encoding="utf-8"))


# --- accepted -----------------------------------------------------------------------------------


def test_a_touching_group_recorded_as_a_contact_is_reclassified_not_missing(
    generator: ModuleType, pair: tuple[Path, Path]
) -> None:
    assert check(generator, *pair) == ([], 1)


def test_the_generator_reuses_the_replays_rule_rather_than_a_copy(generator: ModuleType) -> None:
    assert generator.reclassifying_contacts is replay_module.reclassifying_contacts
    assert generator.judged_group is replay_module.judged_group


def test_a_group_key_made_of_names_is_matched_in_the_fixtures_names(
    generator: ModuleType, pair: tuple[Path, Path]
) -> None:
    """The recorded key goes through the map the rows were written with; the fixture's
    contact carries the scrambled key, never the recorded one."""
    recording, fixture = pair
    fmap = FictionalMap()
    scrambled, configuration = generator.fixture_group(fmap, (NAMED_GROUP, "Default"))
    assert scrambled != NAMED_GROUP
    assert configuration == "Default"

    def named(session: dict[str, Any]) -> None:
        for finding in interference_findings(session):
            finding["calculation"]["inputs"]["group_key"] = NAMED_GROUP

    def contact_named(key: str) -> Callable[[dict[str, Any]], None]:
        def change(session: dict[str, Any]) -> None:
            session["contacts"][0]["group_key"] = key

        return change

    rewrite_session(recording, named)
    rewrite_session(fixture, contact_named(scrambled))
    assert check(generator, recording, fixture, fmap) == ([], 1)

    rewrite_session(fixture, contact_named(NAMED_GROUP))
    problems, reclassified = check(generator, recording, fixture, fmap)
    assert reclassified == 0
    assert problems == ["the finding keys differ: 1 recorded keys are missing and 0 are new"]


def test_with_no_contact_the_check_is_the_key_comparison_it_was(
    generator: ModuleType, tmp_path: Path, package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = recording_before_contacts(monkeypatch, tmp_path, package_dir)
    with monkeypatch.context() as patched:
        patched.setattr(interference, "CONTACT_VOLUME_MM3", -1.0)
        fixture = fixture_by_todays_code(tmp_path, package_dir)

    assert check(generator, recording, fixture) == ([], 0)


# --- still refused ------------------------------------------------------------------------------


def test_a_contact_in_another_configuration_leaves_the_key_missing(
    generator: ModuleType, pair: tuple[Path, Path]
) -> None:
    recording, fixture = pair

    def elsewhere(session: dict[str, Any]) -> None:
        session["contacts"][0]["configuration"] = "Other"

    rewrite_session(fixture, elsewhere)

    assert check(generator, recording, fixture) == (
        ["the finding keys differ: 1 recorded keys are missing and 0 are new"],
        0,
    )


def test_a_contact_of_another_group_leaves_the_key_missing(
    generator: ModuleType, pair: tuple[Path, Path]
) -> None:
    recording, fixture = pair

    def other_group(session: dict[str, Any]) -> None:
        session["contacts"][0]["group_key"] = "cmp:0001|cmp:0002"

    rewrite_session(fixture, other_group)

    assert check(generator, recording, fixture)[1] == 0
    assert check(generator, recording, fixture)[0] != []


def test_another_checks_finding_with_the_same_group_key_is_never_reclassified(
    generator: ModuleType, pair: tuple[Path, Path]
) -> None:
    recording, fixture = pair

    def not_interference(session: dict[str, Any]) -> None:
        for finding in interference_findings(session):
            finding["check"] = "hole.coaxiality"

    rewrite_session(recording, not_interference)

    problems, reclassified = check(generator, recording, fixture)
    assert reclassified == 0
    assert problems == ["the finding keys differ: 1 recorded keys are missing and 0 are new"]


def test_one_contact_reclassifies_one_of_two_recorded_findings_of_its_group(
    generator: ModuleType, pair: tuple[Path, Path]
) -> None:
    recording, fixture = pair

    def twice(session: dict[str, Any]) -> None:
        extra = dict(interference_findings(session)[0])
        extra["id"] = "F-900"
        session["findings"].append(extra)

    rewrite_session(recording, twice)

    assert check(generator, recording, fixture) == (
        ["the finding keys differ: 1 recorded keys are missing and 0 are new"],
        1,
    )


def test_a_new_finding_in_the_fixture_still_refuses(
    generator: ModuleType, pair: tuple[Path, Path]
) -> None:
    recording, fixture = pair
    [recorded] = interference_findings(_session(recording))

    def added(session: dict[str, Any]) -> None:
        session["findings"].append({**recorded, "id": "F-901", "configuration": "Another"})

    rewrite_session(fixture, added)

    assert check(generator, recording, fixture) == (
        ["the finding keys differ: 0 recorded keys are missing and 1 are new"],
        1,
    )
