"""A recorded RMS finding the type table narrowed (008 T124, owner decision 23A).

`contracts/replay.md` section 5, research R2.58. Feature 003's decision 20A moves the system types
of the real dumps into `tolerated_loose`, so the part check stops naming those rows as loose
subjects. A recorded `rms.*` finding that lost only such subjects keeps its part and its
configuration, but `finding_subject_key` holds one drawing location per subject, so the strict
comparison read it as a recorded finding lost and a new one added. It is **narrowed** exactly
when, after removing each drawing location whose `(scope, persist_ref)` names only rows the
current type table does not count as content, its key equals the key of a finding in the
requested pass that nothing else matched - one to one - and it is listed with the locations
removed. A finding still unmatched after narrowing stays lost.

The recordings are made by a copy of the shipped table that still counted `SensorFolder` as
content and replayed by the shipped table, which tolerates it (`tests/support/narrowed.py`).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.benchmark import replay as replay_module
from swreview.benchmark.replay import (
    NarrowedKey,
    compare_finding_keys,
    narrowed_key,
    not_content_locations,
    replay,
    subject_of,
)
from swreview.checks.rms_types import load_table
from swreview.findings import Finding, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package
from swreview.ir.models import EvidencePackage, SourceRef
from tests.support.narrowed import (
    BOSS,
    CORE,
    HISTORY,
    LOOSE,
    PART,
    SENSORS,
    WIDGET,
    loose_findings,
    older_table,
    part_package,
    record,
    row_named,
)
from tests.support.packages import persist_ref
from tests.support.replay import ALL_OFF, rewrite_session

pytestmark = pytest.mark.usefixtures("vocabulary")

runner = CliRunner()

NARROWED_SUBJECT = f"components cmp:0002; at {PART}; at {PART}; configuration Default"
"""The recorded finding's subject: its two loose subjects, `Sensors` and `Widget1`, each one
location on the part; today's finding holds `Widget1`'s alone."""


@pytest.fixture
def older(tmp_path: Path) -> Path:
    return older_table(tmp_path / "older")


@pytest.fixture
def run(tmp_path: Path, older: Path) -> Path:
    """Recorded by the older table: the loose finding names `Sensors` and `Widget1`."""
    recorded = record(tmp_path / "run", part_package(), older)
    [finding] = loose_findings(recorded)
    assert len(finding.drawing_locations) == 2
    return recorded


def recorded_loose(run: Path) -> Finding:
    [finding] = loose_findings(run)
    return finding


def edit_loose(run: Path, change: Callable[[dict[str, Any]], None]) -> None:
    def edited(session: dict[str, Any]) -> None:
        for finding in session["findings"]:
            if finding["check"] == LOOSE:
                change(finding)

    rewrite_session(run, edited)


def replay_cli(run: Path, *extra: str) -> Any:
    return runner.invoke(cli.app, ["benchmark", "replay", str(run), *extra])


def not_content_of(run: Path) -> frozenset[tuple[str, str]]:
    return not_content_locations(load_package(run).package, load_table())


# --- narrowed -----------------------------------------------------------------------------------


def test_the_shipped_table_no_longer_names_the_system_row_loose(tmp_path: Path) -> None:
    """The premise: today's code names `Widget1` alone, so the strict key comparison reads the
    recorded finding as lost and today's as added."""
    [finding] = loose_findings(record(tmp_path / "today", part_package()))

    assert len(finding.drawing_locations) == 1


def test_a_finding_that_lost_only_a_system_subject_is_narrowed_not_lost(run: Path) -> None:
    report = replay(run, requested=ALL_OFF)

    [item] = report.findings.narrowed
    assert (item.check, item.subject, item.step, item.removed_locations) == (
        LOOSE,
        NARROWED_SUBJECT,
        1,
        1,
    )
    assert report.findings.lost == []
    assert report.findings.added == []
    assert report.findings.not_replayable == []
    assert report.findings.reclassified == []
    assert report.findings.recorded == report.findings.replayed


def test_the_subject_listed_is_the_recorded_findings(run: Path) -> None:
    [item] = replay(run, requested=ALL_OFF).findings.narrowed

    assert item.subject == subject_of(finding_subject_key(recorded_loose(run)))


def test_the_human_output_counts_and_names_it_and_exits_0(run: Path) -> None:
    result = replay_cli(run)

    assert result.exit_code == 0, result.output
    assert "0 reclassified as contacts, 1 narrowed by the type table" in result.stdout
    assert f"  narrowed: {LOOSE} - {NARROWED_SUBJECT} (1 location removed)" in result.stdout


def test_the_json_report_lists_it_with_the_locations_removed(run: Path) -> None:
    result = replay_cli(run, "--json")

    assert result.exit_code == 0, result.output
    findings = json.loads(result.stdout)["findings"]
    assert findings["narrowed"] == [
        {"check": LOOSE, "subject": NARROWED_SUBJECT, "step": 1, "removed_locations": 1}
    ]
    assert findings["lost"] == []


def test_every_location_removed_is_counted(tmp_path: Path) -> None:
    """Two system rows loose when recorded - a table that counted `HistoryFolder` too - both
    removed, both counted, and the plural printed."""
    table = older_table(tmp_path / "older", counted=("SensorFolder", "HistoryFolder"))
    run = record(tmp_path / "run", part_package(), table)
    assert len(recorded_loose(run).drawing_locations) == 3

    [item] = replay(run, requested=ALL_OFF).findings.narrowed

    assert item.removed_locations == 2
    assert "(2 locations removed)" in replay_cli(run).stdout


def test_an_untouched_recording_narrows_nothing(tmp_path: Path) -> None:
    run = record(tmp_path / "today", part_package())

    report = replay(run, requested=ALL_OFF)

    assert report.findings.narrowed == []
    assert json.loads(replay_cli(run, "--json").stdout)["findings"]["narrowed"] == []
    assert "0 narrowed by the type table" in replay_cli(run).stdout


def test_a_system_row_whose_reference_only_other_system_rows_share_is_removed(
    tmp_path: Path, older: Path
) -> None:
    """The real packages' case: one reference among several system folders, none of them
    content, names only rows the table does not count."""
    run = record(tmp_path / "run", part_package(share=(SENSORS, HISTORY)), older)

    report = replay(run, requested=ALL_OFF)

    [item] = report.findings.narrowed
    assert item.removed_locations == 1
    assert report.findings.lost == []


# --- still lost ---------------------------------------------------------------------------------


def test_a_finding_that_also_lost_a_content_subject_is_lost(run: Path) -> None:
    """After the system row's location goes, the recorded finding still names `Boss1`, content
    that today's finding does not name: not equal, so lost - and today's added."""
    boss = row_named(load_package(run).package, BOSS)

    edit_loose(
        run,
        lambda finding: finding["drawing_locations"].append(
            {"document_id": PART, "persist_ref": boss.persist_ref}
        ),
    )

    report = replay(run, requested=ALL_OFF)

    assert report.findings.narrowed == []
    assert [item.check for item in report.findings.lost] == [LOOSE]
    assert [item.check for item in report.findings.added] == [LOOSE]
    assert replay_cli(run).exit_code == 1


def test_a_finding_that_also_moved_configuration_is_lost(run: Path) -> None:
    def elsewhere(finding: dict[str, Any]) -> None:
        finding["configuration"] = "Other"

    edit_loose(run, elsewhere)

    report = replay(run, requested=ALL_OFF)

    assert report.findings.narrowed == []
    [lost] = report.findings.lost
    assert (lost.check, lost.subject.endswith("configuration Other")) == (LOOSE, True)
    assert [item.check for item in report.findings.added] == [LOOSE]


def test_two_recorded_findings_narrowing_onto_one_narrow_the_first_and_lose_the_second(
    run: Path,
) -> None:
    def twice(session: dict[str, Any]) -> None:
        [recorded] = [f for f in session["findings"] if f["check"] == LOOSE]
        session["findings"].append({**recorded, "id": "F-900"})

    rewrite_session(run, twice)

    report = replay(run, requested=ALL_OFF)

    assert len(report.findings.narrowed) == 1
    assert [(item.check, item.subject) for item in report.findings.lost] == [
        (LOOSE, NARROWED_SUBJECT)
    ]
    assert report.findings.added == []
    assert replay_cli(run).exit_code == 1


def test_a_system_row_whose_reference_a_content_row_shares_is_not_removed(
    tmp_path: Path, older: Path
) -> None:
    """"Only": the location names `Boss1` too, which is content, so it stays - and the finding,
    still naming two locations where today's names one, is lost."""
    run = record(tmp_path / "run", part_package(share=(SENSORS, BOSS)), older)

    report = replay(run, requested=ALL_OFF)

    assert report.findings.narrowed == []
    assert [item.check for item in report.findings.lost] == [LOOSE]
    assert [item.check for item in report.findings.added] == [LOOSE]


# --- the rule's parts ---------------------------------------------------------------------------


def test_the_current_table_decides_which_references_name_only_rows_that_are_not_content(
    older: Path,
) -> None:
    package = part_package()
    shipped = not_content_locations(package, load_table())
    before = not_content_locations(package, load_table(older))

    def location(name: str) -> tuple[str, str]:
        row = row_named(package, name)
        return row.persist_ref_scope, row.persist_ref

    assert location(SENSORS) in shipped
    assert location(SENSORS) not in before
    for table in (shipped, before):
        assert location(HISTORY) in table
        assert location(CORE) in table, "a folder is not content, as `is_content` says"
        assert location(WIDGET) not in table
        assert location(BOSS) not in table


def test_a_shared_reference_is_not_content_only_when_no_row_carrying_it_is() -> None:
    table = load_table()
    with_content = part_package(share=(SENSORS, BOSS))
    with_system = part_package(share=(SENSORS, HISTORY))

    boss = row_named(with_content, BOSS)
    history = row_named(with_system, HISTORY)
    assert (PART, boss.persist_ref) not in not_content_locations(with_content, table)
    assert (PART, history.persist_ref) in not_content_locations(with_system, table)


def test_the_scope_is_part_of_the_location() -> None:
    """The same reference under another document's scope names no row of this part."""
    package = part_package()
    sensors = row_named(package, SENSORS)

    assert ("doc:9", sensors.persist_ref) not in not_content_locations(package, load_table())


def test_narrowed_key_removes_only_the_locations_that_name_only_rows_not_content(
    run: Path,
) -> None:
    finding = recorded_loose(run)
    widget = row_named(load_package(run).package, WIDGET)
    kept = [ref for ref in finding.drawing_locations if ref.persist_ref == widget.persist_ref]
    assert len(kept) == 1

    assert narrowed_key(finding, not_content_of(run)) == NarrowedKey(
        key=finding_subject_key(finding.model_copy(update={"drawing_locations": kept})),
        removed_locations=1,
    )


def test_a_location_naming_no_feature_row_or_carrying_no_reference_stays(run: Path) -> None:
    finding = recorded_loose(run)
    mate = SourceRef(document_id=PART, persist_ref=persist_ref("mate:0001"))
    sheet = SourceRef(document_id=PART, sheet="Sheet1")
    extended = finding.model_copy(
        update={"drawing_locations": [*finding.drawing_locations, mate, sheet]}
    )

    narrowed = narrowed_key(extended, not_content_of(run))

    assert narrowed is not None
    assert narrowed.removed_locations == 1
    assert len(narrowed.key[2]) == 3, "the unknown row's, the mate's and the sheet's stay"


def test_a_finding_that_loses_no_location_has_no_narrowed_key(tmp_path: Path) -> None:
    run = record(tmp_path / "today", part_package())

    assert narrowed_key(recorded_loose(run), not_content_of(run)) is None


def test_a_finding_of_another_family_is_never_narrowed(run: Path) -> None:
    """The same finding under another check: the type table decides only the RMS family."""
    finding = recorded_loose(run)
    package_path = run / PACKAGE_FILE_NAME
    narrowed = narrowed_key(finding, not_content_of(run))
    assert narrowed is not None
    other = finding.model_copy(update={"check": "hole.coaxiality"})
    other_today = ("hole.coaxiality", *narrowed.key[1:])

    assert narrowed_key(other, not_content_of(run)) is None
    rms = compare_finding_keys([finding], [narrowed.key], package_path)
    assert (rms.lost, rms.narrowed, rms.added) == ((), ((0, 1),), Counter())
    family = compare_finding_keys([other], [other_today], package_path)
    assert (family.lost, family.narrowed, family.added) == ((0,), (), Counter([other_today]))


# --- compare_finding_keys: one to one, nothing else matched --------------------------------------


def test_equal_keys_match_exactly_and_nothing_needs_narrowing(run: Path) -> None:
    finding = recorded_loose(run)
    key = finding_subject_key(finding)

    comparison = compare_finding_keys([finding], [key], run / PACKAGE_FILE_NAME)

    assert (comparison.lost, comparison.narrowed, comparison.added) == ((), (), Counter())


def test_of_several_recorded_findings_with_one_key_the_later_are_unmatched(run: Path) -> None:
    finding = recorded_loose(run)
    twin = finding.model_copy(update={"id": "F-900"})

    comparison = compare_finding_keys(
        [finding, twin], [finding_subject_key(finding)], run / PACKAGE_FILE_NAME
    )

    assert (comparison.lost, comparison.narrowed, comparison.added) == ((1,), (), Counter())


def test_narrowing_takes_only_a_current_finding_nothing_else_matched(run: Path) -> None:
    """A current finding an uncompared recorded key equals - a not-replayable or reclassified
    finding's - is matched already, so a narrowed key cannot take it."""
    finding = recorded_loose(run)
    narrowed = narrowed_key(finding, not_content_of(run))
    assert narrowed is not None
    package_path = run / PACKAGE_FILE_NAME

    free = compare_finding_keys([finding], [narrowed.key], package_path)
    taken = compare_finding_keys(
        [finding], [narrowed.key], package_path, uncompared=[narrowed.key]
    )

    assert free.narrowed == ((0, 1),)
    assert (taken.lost, taken.narrowed, taken.added) == ((0,), (), Counter())


def test_an_uncompared_key_is_never_added(run: Path) -> None:
    key = finding_subject_key(recorded_loose(run))

    comparison = compare_finding_keys([], [key, key], run / PACKAGE_FILE_NAME, uncompared=[key])

    assert comparison.added == Counter([key])


def test_the_named_keys_are_compared(run: Path) -> None:
    """`named` carries each recorded key - narrowed or not - into the current side's names, as
    the fixture generator carries a recorded key into the fixture's."""
    finding = recorded_loose(run)
    narrowed = narrowed_key(finding, not_content_of(run))
    assert narrowed is not None

    def renamed(key: Any) -> Any:
        return (*key[:4], f"{key[4]} (fixture)")

    comparison = compare_finding_keys(
        [finding], [renamed(narrowed.key)], run / PACKAGE_FILE_NAME, named=renamed
    )
    unnamed = compare_finding_keys([finding], [renamed(narrowed.key)], run / PACKAGE_FILE_NAME)

    assert comparison.narrowed == ((0, 1),)
    assert (unnamed.lost, unnamed.narrowed) == ((0,), ())


def test_the_package_is_read_only_when_an_rms_finding_is_unmatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = record(tmp_path / "today", part_package())

    def refuse(*arguments: Any) -> Any:
        raise AssertionError("nothing could narrow, so nothing needed the package")

    monkeypatch.setattr(replay_module, "not_content_locations", refuse)

    report = replay(run, requested=ALL_OFF)

    assert report.findings.lost == report.findings.narrowed == []


def test_the_recordings_own_package_and_the_current_table_are_read(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], object]] = []
    real = replay_module.not_content_locations

    def spy(package: EvidencePackage, table: Any) -> Any:
        calls.append(([row.persist_ref for row in package.features], table))
        return real(package, table)

    monkeypatch.setattr(replay_module, "not_content_locations", spy)

    replay(run, requested=ALL_OFF)

    [(references, table)] = calls
    assert references == [row.persist_ref for row in load_package(run).package.features]
    assert table is load_table()
