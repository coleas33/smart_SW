"""A carried RMS finding holds an earlier dump's references (008 T129, review of decision 25A).

`contracts/replay.md` section 5, research R2.8. Since the owner's decision 25A a key's drawing
location carries its persistent reference, which is safe only while both sides of a comparison
hold one dump's references. A finding lever 11a carried (`carry_over.carry_over_findings`) does
not: it keeps the drawing locations of the session it was carried from, and carry-over decides
"unchanged" from a `feature_tree` fingerprint that hashes no reference (`exceptions._feature_row`),
so a later dump that re-encoded a reference still carries the earlier one. Replayed with checks
first, the current code computes the finding again with this dump's reference, and the exact
comparison read the pair as lost plus added (exit 1), where before decision 25A they matched.

So a carried recorded finding that nothing matched exactly, and that narrowing did not match, takes
one current finding nothing else matched whose key, references left out, equals its own,
references left out - the comparison every finding had before decision 25A. A computed finding is
compared by reference as before; a carried finding whose count, configuration or components moved
is still lost.

The recordings are two scripted sessions of the part in `tests/support/narrowed.py` with
`carry_over_rms` on: the first runs the part check, the second - on a dump that re-encoded
`Widget1`'s reference - only reads the summary, so its loose finding is the first's, carried.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.settings import MODEL_VIEW_OFF, EfficiencySettings
from swreview.benchmark.replay import Requested, TurnPlan, compare_finding_keys, replay
from swreview.findings import Finding, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.ir.models import EvidencePackage, SourceRef
from tests.support import mechanical
from tests.support.narrowed import (
    BOSS,
    LOOSE,
    PART,
    SENSORS,
    SUMMARY,
    WIDGET,
    edit_loose,
    loose_findings,
    older_table,
    part_package,
    record,
    row_named,
)
from tests.support.packages import persist_ref
from tests.support.scramble import FictionalMap

pytestmark = pytest.mark.usefixtures("vocabulary")

runner = CliRunner()

GENERATOR = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "generate_fixtures.py"
CARRY = EfficiencySettings(carry_over_rms=True)
CHECKS_FIRST: Requested = (EfficiencySettings(prerun_checks=True), MODEL_VIEW_OFF)
SUMMARY_ONLY = [TurnPlan(rounds=((SUMMARY,),), text="Done.")]
"""The second session's script: nothing that computes a finding, so its loose finding is carried."""
CARRIED_FROM = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
"""The session a hand-built carried finding says it came from."""
FIRST_DUMP = row_named(part_package(), WIDGET).persist_ref
RE_ENCODED = persist_ref(f"{PART}/{WIDGET} (dump 2)")
"""`Widget1`'s reference as a later dump wrote it: the same row, the bytes changed."""


def redumped(package: EvidencePackage, reference: str = RE_ENCODED) -> EvidencePackage:
    """`package` as a later dump wrote it: `Widget1`'s reference re-encoded, nothing else moved -
    no field carry-over's fingerprint hashes."""
    return package.model_copy(
        update={
            "features": [
                row.model_copy(update={"persist_ref": reference}) if row.name == WIDGET else row
                for row in package.features
            ]
        }
    )


def carried_over(
    tmp_path: Path, second: EvidencePackage, table: Path | None = None
) -> Path:
    """The second of two sessions with `carry_over_rms` on, both made by `table`: the first runs
    the part check on `part_package()`, the second reads only the summary of `second`."""
    first = record(tmp_path / "first", part_package(), table, efficiency=CARRY)
    return record(
        tmp_path / "second",
        second,
        table,
        SUMMARY_ONLY,
        efficiency=CARRY,
        previous_session=first / "session.json",
    )


def carried_loose(run: Path) -> Finding:
    [finding] = loose_findings(run)
    assert finding.carried_over_from is not None, "the premise: the loose finding was carried"
    return finding


def references(finding: Finding) -> list[str | None]:
    return [location.persist_ref for location in finding.drawing_locations]


@pytest.fixture
def run(tmp_path: Path) -> Path:
    """The carried loose finding names `Widget1` by the first dump's reference; the recording's
    own package carries the re-encoded one."""
    recorded = carried_over(tmp_path, redumped(part_package()))
    assert references(carried_loose(recorded)) == [FIRST_DUMP]
    return recorded


def lost_and_added(report: Any) -> tuple[list[str], list[str]]:
    return (
        [item.check for item in report.findings.lost],
        [item.check for item in report.findings.added if item.check == LOOSE],
    )


# --- the premise ---------------------------------------------------------------------------------


def test_a_carried_finding_names_a_reference_the_recordings_package_does_not_carry(
    run: Path,
) -> None:
    package = EvidencePackage.model_validate_json((run / PACKAGE_FILE_NAME).read_bytes())

    assert row_named(package, WIDGET).persist_ref == RE_ENCODED
    assert FIRST_DUMP not in {row.persist_ref for row in package.features}


# --- kept ----------------------------------------------------------------------------------------


def test_checks_first_keeps_a_carried_finding_whose_reference_was_re_encoded(run: Path) -> None:
    """The requested pass computes the loose finding again, naming `Widget1` by this dump's
    reference: the same subject, so neither lost nor added."""
    report = replay(run, requested=CHECKS_FIRST)

    assert lost_and_added(report) == ([], [])
    assert report.findings.narrowed == []


def test_the_command_lines_default_replay_exits_0(run: Path) -> None:
    """A scripted recording's provider is `fake`, whose pane runs checks first."""
    result = runner.invoke(cli.app, ["benchmark", "replay", str(run)])

    assert result.exit_code == 0, result.output
    assert f"  lost: {LOOSE}" not in result.stdout
    assert f"  added: {LOOSE}" not in result.stdout


def test_a_carried_finding_whose_reference_did_not_move_matches_exactly(tmp_path: Path) -> None:
    run = carried_over(tmp_path, part_package())
    carried = carried_loose(run)
    [today] = loose_findings(record(tmp_path / "today", part_package()))

    assert finding_subject_key(carried) == finding_subject_key(today)
    assert lost_and_added(replay(run, requested=CHECKS_FIRST)) == ([], [])


# --- still lost ----------------------------------------------------------------------------------


def test_a_computed_finding_is_still_compared_by_reference(run: Path) -> None:
    """The same recorded finding, not carried: its reference is this recording's own dump's, so a
    different one is a different subject (owner decision 25A) - lost, and today's added."""

    def uncarried(finding: dict[str, Any]) -> None:
        for field in ("carried_over_from", "carried_over_at", "carry_over_key"):
            finding.pop(field, None)

    edit_loose(run, uncarried)
    [finding] = loose_findings(run)
    assert finding.carried_over_from is None

    assert lost_and_added(replay(run, requested=CHECKS_FIRST)) == ([LOOSE], [LOOSE])


def another_subject(finding: dict[str, Any]) -> None:
    finding["drawing_locations"].append(
        {"document_id": PART, "persist_ref": row_named(part_package(), BOSS).persist_ref}
    )


def another_configuration(finding: dict[str, Any]) -> None:
    finding["configuration"] = "Other"


def another_component(finding: dict[str, Any]) -> None:
    finding["component_ids"] = ["cmp:0099"]


@pytest.mark.parametrize("change", [another_subject, another_configuration, another_component])
def test_a_carried_finding_that_moved_otherwise_is_still_lost(run: Path, change: Any) -> None:
    """References left out, the key still counts the subjects in each scope and holds the
    configuration and the components."""
    edit_loose(run, change)

    report = replay(run, requested=CHECKS_FIRST)

    assert lost_and_added(report) == ([LOOSE], [LOOSE])
    assert runner.invoke(cli.app, ["benchmark", "replay", str(run)]).exit_code == 1


def test_no_pass_recomputes_a_carried_finding_without_checks_first(run: Path) -> None:
    """Unchanged by this rule: the replay plays no previous session, so with every lever off
    nothing computes the carried finding and it is lost, as it was before decision 25A."""
    report = replay(run, requested=(EfficiencySettings(), MODEL_VIEW_OFF))

    assert lost_and_added(report) == ([LOOSE], [])


def test_a_carried_finding_re_encoded_and_narrowed_is_lost(tmp_path: Path) -> None:
    """Carried from a session an older table made, so it also names `Sensors`: narrowing reads a
    reference in this recording's package, which `Widget1`'s first-dump reference is not, so the
    remaining location keeps it and nothing matches. Lost - the safe side - never narrowed."""
    older = older_table(tmp_path / "older")
    run = carried_over(tmp_path, redumped(part_package()), older)
    sensors = row_named(part_package(), SENSORS).persist_ref
    assert sorted(references(carried_loose(run))) == sorted([sensors, FIRST_DUMP])

    report = replay(run, requested=CHECKS_FIRST)

    assert lost_and_added(report) == ([LOOSE], [LOOSE])
    assert report.findings.narrowed == []


# --- compare_finding_keys: the order of the matches ----------------------------------------------


def with_reference(finding: Finding, reference: str) -> Finding:
    return finding.model_copy(
        update={"drawing_locations": [SourceRef(document_id=PART, persist_ref=reference)]}
    )


def computed(finding: Finding) -> Finding:
    """`finding` as the run that recorded it computed it: no carry-over field."""
    return finding.model_copy(
        update={"carried_over_from": None, "carried_over_at": None, "carry_over_key": None}
    )


def test_an_exact_match_is_served_before_a_carried_findings(run: Path) -> None:
    """Recorded first, the carried finding still waits for every exact match: the computed finding
    naming today's reference takes the one current finding, and the carried one is lost."""
    carried = carried_loose(run)
    today = computed(with_reference(carried, RE_ENCODED))

    comparison = compare_finding_keys(
        [carried, today], [finding_subject_key(today)], run / PACKAGE_FILE_NAME
    )

    assert (comparison.lost, comparison.narrowed, comparison.added) == ((0,), (), Counter())


def test_narrowing_is_served_before_a_carried_findings_match(tmp_path: Path) -> None:
    """A computed finding the table narrowed onto today's finding takes it before a carried
    finding, recorded first, that equals it with references left out."""
    older_run = record(tmp_path / "older-run", part_package(), older_table(tmp_path / "older"))
    [narrowing] = loose_findings(older_run)
    [today] = loose_findings(record(tmp_path / "today", part_package()))
    carried = with_reference(today, persist_ref(f"{PART}/{WIDGET} (dump 0)")).model_copy(
        update={"carried_over_from": CARRIED_FROM}
    )

    comparison = compare_finding_keys(
        [carried, narrowing], [finding_subject_key(today)], older_run / PACKAGE_FILE_NAME
    )

    assert (comparison.lost, comparison.narrowed, comparison.added) == ((0,), ((1, 1),), Counter())


def test_two_carried_findings_onto_one_current_finding_keep_the_first(run: Path) -> None:
    carried = carried_loose(run)
    twin = carried.model_copy(update={"id": "F-900"})
    today = computed(with_reference(carried, RE_ENCODED))

    comparison = compare_finding_keys(
        [carried, twin], [finding_subject_key(today)], run / PACKAGE_FILE_NAME
    )

    assert (comparison.lost, comparison.narrowed, comparison.added) == ((1,), (), Counter())


def test_a_carried_finding_takes_no_current_finding_an_uncompared_key_holds(run: Path) -> None:
    carried = carried_loose(run)
    today = finding_subject_key(computed(with_reference(carried, RE_ENCODED)))

    comparison = compare_finding_keys(
        [carried], [today], run / PACKAGE_FILE_NAME, uncompared=[today]
    )

    assert (comparison.lost, comparison.narrowed, comparison.added) == ((0,), (), Counter())


# --- the fixture generator -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return mechanical.load_generator(GENERATOR)


def test_the_generator_compares_a_carried_finding_without_its_references(
    generator: ModuleType, run: Path
) -> None:
    """Through the map the generator names a recorded key with: a carried finding's first-dump
    reference, scrambled, is not the fixture's scrambled reference, and the key without them is."""
    fmap = FictionalMap()
    carried = carried_loose(run)
    fixture = generator.scrambled_key(
        fmap, finding_subject_key(computed(with_reference(carried, RE_ENCODED)))
    )

    def named(key: Any) -> Any:
        return generator.scrambled_key(fmap, key)

    kept = compare_finding_keys([carried], [fixture], run / PACKAGE_FILE_NAME, named=named)
    lost = compare_finding_keys(
        [computed(carried)], [fixture], run / PACKAGE_FILE_NAME, named=named
    )

    assert named(finding_subject_key(carried)) != fixture
    assert (kept.lost, kept.narrowed, kept.added) == ((), (), Counter())
    assert (lost.lost, lost.added) == ((0,), Counter([fixture]))
