"""A recorded RMS finding the tree reading narrowed (feature 013 T145, T134-Q1).

008 `contracts/replay.md` section 5, 013 research R2.42, 008 research R2.59. Feature 013 T133 reads
a part's tree the way the planner does (`checks/feature_nodes.tree_nodes`): an absorbed sketch the
dump lists at depth 0 and again under the feature consuming it, with one persistent reference, is
its depth-0 row alone - the second listing merged into it - and the Hole Wizard's profile sketch,
listed only under its hole, is carried by the hole and holds no position of its own. A finding
recorded before that reading names the second listing and the carried row; the reading's finding
does not. By the default taken 2026-09-27 (T134-Q1), decision 23A's narrowed outcome reads it:

- every occurrence of a location naming only rows the reading carries or merges, or the type table
  does not count, is removed;
- a location naming a depth-0 row with the second listing merged into it loses its occurrences
  beyond the rows the reading keeps there, at most one per second listing - the second listing's
  occurrence goes, the depth-0 row's stays.

A location *may* be removed: the recorded finding narrows onto a finding nothing else matched whose
locations lie between its own and the lowest key (`narrowed_key`, every removable occurrence gone),
so a rule that still names a removable row - the sketch rules grade a carried sketch as its owner's
- keeps it. Everything else is decision 23A's and 25A's: the family, the one-to-one matching onto
a finding nothing else matched, the remaining references compared exactly.

By the default taken 2026-09-27 for T134-Q2 (013 research R2.47, 008 research R2.60), the family is
every check that reads the shared tree reading: the `rms.*` rules and, named by its id,
`standards.part.sketches_fully_defined`, which T133 moves onto the same reading. For that check the
clause is the tree reading's alone - decision 23A's type-table clause never removes one of its
locations - and every other Standards check is never narrowed.

The recordings here are made on the planner's fictional real-shape package
(`tests/support/remodel.py`). Since T133 lands (T134) today's code reads one node per position, so
a recording made before it is today's finding with each second listing's occurrence and the
carried row put back, as the part check named every row the dump lists (`before_the_reading`);
the current side is today's own finding, or the keys one node per feature position gives, written
out by name.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.benchmark import replay as replay_module
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import (
    FoldedLocation,
    compare_finding_keys,
    folded_locations,
    narrowed_key,
    not_content_locations,
)
from swreview.checks.rms_types import load_table
from swreview.checks.standards.registry import RULES as STANDARDS_RULES
from swreview.findings import Finding, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.ir.models import EvidencePackage, Feature, SourceRef
from tests.support import mechanical
from tests.support.narrowed import LOOSE, loose_findings, part_package, record
from tests.support.remodel import (
    absorbed_sketch_features,
    absorbed_twice,
    carried_under,
    remodel_package,
)
from tests.support.replay import record_scripted_review, rewrite_session
from tests.support.scramble import FictionalMap

pytestmark = pytest.mark.usefixtures("vocabulary")

ABSORBED = ("Sketch1", "Sketch2", "Sketch3")
CARRIED = "Sketch9"
"""The Hole Wizard's own profile sketch: listed only under `Hole1`."""
BOSS = "Boss-Extrude1"
CUT = "Cut-Extrude1"
STANDARDS_SKETCHES = "standards.part.sketches_fully_defined"
OTHER_STANDARDS_CHECKS = tuple(sorted(set(STANDARDS_RULES) - {STANDARDS_SKETCHES}))
"""Every Standards check but the sketch check: none reads the shared tree reading."""
GENERATOR = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "generate_fixtures.py"
SCRIPT_TOOLS = ("get_package_summary", "check_rms_part")


def real_shape() -> EvidencePackage:
    """Every absorbed sketch listed twice, and the hole's profile sketch only under the hole."""
    base = remodel_package(absorbed_sketch_features())
    return carried_under(absorbed_twice(base, *ABSORBED), "Hole1", CARRIED)


def with_rows(package: EvidencePackage, *extra: Feature) -> EvidencePackage:
    return package.model_copy(update={"features": [*package.features, *extra]})


def depth_0(package: EvidencePackage, name: str) -> Feature:
    [row] = [row for row in package.features if row.name == name and row.depth == 0]
    return row


def only(package: EvidencePackage, name: str) -> Feature:
    [row] = [row for row in package.features if row.name == name]
    return row


def sharing(row: Feature, *, id: str, type_name: str, folder_id: str | None = None) -> Feature:
    """A row carrying `row`'s reference, at depth 1, of another type: what shares a reference."""
    return row.model_copy(
        update={
            "id": id,
            "name": f"{row.name} twin",
            "type_name": type_name,
            "depth": 1,
            "folder_id": folder_id,
            "sketch": None,
            "parent_ids": [],
            "child_ids": [],
            "index": 900 + len(id),
        }
    )


def saved(tmp_path: Path, package: EvidencePackage) -> Path:
    """A folder holding `package` alone, as `compare_finding_keys` reads a recording's package."""
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / PACKAGE_FILE_NAME).write_text(package.model_dump_json(), encoding="utf-8")
    return run / PACKAGE_FILE_NAME


@pytest.fixture(scope="module")
def today(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A recording of today's loose-feature finding on the real shape: since T133 it names each
    absorbed sketch once, at its depth-0 row, and never the carried row."""
    run = record(tmp_path_factory.mktemp("tree") / "today", real_shape())
    [finding] = loose_findings(run)
    names = located_names(real_shape(), finding)
    assert names[ABSORBED[0]] == 1 and CARRIED not in names
    return run


@pytest.fixture(scope="module")
def recorded(today: Path, tmp_path_factory: pytest.TempPathFactory) -> Finding:
    """The loose-feature finding a recording made before T133 holds on the real shape: it names
    every second listing and the carried row, each with its own location."""
    run = tmp_path_factory.mktemp("tree") / "before"
    shutil.copytree(today, run)
    before_the_reading(run)
    [finding] = loose_findings(run)
    names = located_names(real_shape(), finding)
    assert names[ABSORBED[0]] == 2 and names[CARRIED] == 1
    return finding


def before_the_reading(run: Path, check: str = LOOSE) -> None:
    """Each `check` finding of `run` (the loose one by default) as a recording made before T133
    names it: each absorbed sketch's location once more, for its second listing, and the carried
    row's location - what the part check named when it read every row the dump lists."""
    package = real_shape()
    absorbed = {(at(package, name).document_id, at(package, name).persist_ref) for name in ABSORBED}
    carried = at(package, CARRIED).model_dump(mode="json")

    def unfolded(session: dict[str, Any]) -> None:
        for finding in session["findings"]:
            if finding["check"] != check:
                continue
            locations = []
            for location in finding["drawing_locations"]:
                locations.append(location)
                if (location["document_id"], location.get("persist_ref")) in absorbed:
                    locations.append(dict(location))
            finding["drawing_locations"] = [*locations, carried]

    rewrite_session(run, unfolded)


def located_names(package: EvidencePackage, finding: Finding) -> Counter[str]:
    """How many of `finding`'s locations each row name's reference accounts for."""
    by_location = {(row.persist_ref_scope, row.persist_ref): row.name for row in package.features}
    return Counter(
        by_location[(location.document_id, location.persist_ref)]
        for location in finding.drawing_locations
    )


def at(package: EvidencePackage, name: str) -> SourceRef:
    """The location a finding gives a subject: its scope and its reference (decision 25A)."""
    row = depth_0(package, name) if name != CARRIED else only(package, name)
    return SourceRef(document_id=row.persist_ref_scope, persist_ref=row.persist_ref)


def naming(
    finding: Finding, package: EvidencePackage, names: Sequence[str], *, check: str = LOOSE
) -> Finding:
    """`finding` naming exactly `names`, a name repeated for each location it holds."""
    return finding.model_copy(
        update={"check": check, "drawing_locations": [at(package, name) for name in names]}
    )


def key_of(finding: Finding, package: EvidencePackage, names: Sequence[str], **kw: Any) -> Any:
    return finding_subject_key(naming(finding, package, names, **kw))


def compared(
    tmp_path: Path,
    finding: Finding,
    recorded_names: Sequence[str],
    current_names: Sequence[str],
    *,
    package: EvidencePackage | None = None,
    check: str = LOOSE,
) -> Any:
    package = package or real_shape()
    return compare_finding_keys(
        [naming(finding, package, recorded_names, check=check)],
        [key_of(finding, package, current_names, check=check)],
        saved(tmp_path, package),
    )


def outcome(comparison: Any) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...], int]:
    return comparison.lost, comparison.narrowed, sum(comparison.added.values())


# --- narrowed -------------------------------------------------------------------------------


def test_a_finding_that_lost_only_a_second_listing_narrows(
    recorded: Finding, tmp_path: Path
) -> None:
    """Recorded naming `Sketch1` twice - its depth-0 row and its second listing - where the
    reading names it once: one location removed, neither lost nor added."""
    comparison = compared(tmp_path, recorded, ["Sketch1", "Sketch1", BOSS], ["Sketch1", BOSS])

    assert outcome(comparison) == ((), ((0, 1),), 0)


def test_a_finding_that_lost_only_a_carried_row_narrows(recorded: Finding, tmp_path: Path) -> None:
    comparison = compared(tmp_path, recorded, [BOSS, CARRIED], [BOSS])

    assert outcome(comparison) == ((), ((0, 1),), 0)


def test_both_shapes_together_narrow_and_are_counted_together(
    recorded: Finding, tmp_path: Path
) -> None:
    comparison = compared(
        tmp_path,
        recorded,
        ["Sketch1", "Sketch1", "Sketch2", "Sketch2", BOSS, CARRIED],
        ["Sketch1", "Sketch2", BOSS],
    )

    assert outcome(comparison) == ((), ((0, 3),), 0)


def test_the_locations_in_another_order_narrow_the_same(recorded: Finding, tmp_path: Path) -> None:
    """A key's locations are a multiset (decision 25A): order decides nothing."""
    comparison = compared(
        tmp_path, recorded, [BOSS, "Sketch1", CARRIED, "Sketch1"], ["Sketch1", BOSS]
    )

    assert outcome(comparison) == ((), ((0, 2),), 0)


def test_the_real_recording_shape_narrows_onto_the_readings_finding(
    recorded: Finding, today: Path, tmp_path: Path
) -> None:
    """The whole loose finding recorded before T133 against the one today's code records, one
    node per position: every second listing's occurrence and the carried row removed."""
    package = real_shape()
    [current] = loose_findings(today)
    names = located_names(package, recorded)
    one_node = [name for name in names if name != CARRIED]
    comparison = compare_finding_keys(
        [recorded], [finding_subject_key(current)], saved(tmp_path, package)
    )

    assert finding_subject_key(current) == key_of(recorded, package, one_node)
    assert outcome(comparison) == ((), ((0, len(ABSORBED) + 1),), 0)


def test_a_carried_row_sharing_its_reference_with_a_row_not_counted_is_removed(
    recorded: Finding, tmp_path: Path
) -> None:
    """The reference names the carried sketch and a system row the table does not count (kept by
    the reading, at depth 1 under no feature): every row it names is carried or not counted."""
    package = real_shape()
    carried = only(package, CARRIED)
    package = with_rows(package, sharing(carried, id="feat:0900", type_name="HistoryFolder"))

    comparison = compared(tmp_path, recorded, [BOSS, CARRIED], [BOSS], package=package)

    assert outcome(comparison) == ((), ((0, 1),), 0)


def test_a_location_the_rule_may_remove_but_the_current_finding_still_names_stays(
    recorded: Finding, tmp_path: Path
) -> None:
    """A location *may* be removed: the sketch rules still grade the carried sketch, as its
    hole's, so their current finding still names it - and the finding narrows by the second
    listing's occurrence alone (the big recording's `one_sketch_per_feature` shape)."""
    comparison = compared(
        tmp_path, recorded, ["Sketch1", "Sketch1", BOSS, CARRIED], ["Sketch1", BOSS, CARRIED]
    )

    assert outcome(comparison) == ((), ((0, 1),), 0)


def test_a_subject_the_table_does_not_count_that_the_current_finding_still_names_stays(
    recorded: Finding, tmp_path: Path
) -> None:
    """The same for the type table's clause: a rule that still names a row the table does not
    count (research R5, T129: `rms.sketches.one_sketch_per_feature` on the big recording) keeps
    it, and the finding narrows by what the reading folded."""
    package = real_shape()
    plane = at(package, "Front Plane")
    assert (plane.document_id, plane.persist_ref) in not_content_locations(package, load_table())

    comparison = compared(
        tmp_path, recorded, ["Front Plane", "Sketch1", "Sketch1"], ["Front Plane", "Sketch1"]
    )
    lowest = compared(
        tmp_path / "lowest", recorded, ["Front Plane", "Sketch1", "Sketch1"], ["Sketch1"]
    )

    assert outcome(comparison) == ((), ((0, 1),), 0)
    assert outcome(lowest) == ((), ((0, 2),), 0)


def test_of_two_current_findings_it_could_narrow_onto_the_one_keeping_most_is_taken(
    recorded: Finding, tmp_path: Path
) -> None:
    package = real_shape()
    closest = key_of(recorded, package, ["Sketch1", BOSS, CARRIED])
    farther = key_of(recorded, package, ["Sketch1", BOSS])

    comparison = compare_finding_keys(
        [naming(recorded, package, ["Sketch1", "Sketch1", BOSS, CARRIED])],
        [farther, closest],
        saved(tmp_path, package),
    )

    assert (comparison.lost, comparison.narrowed) == ((), ((0, 1),))
    assert comparison.added == Counter([farther])


def test_two_second_listings_of_one_row_de_duplicate_two_occurrences(
    recorded: Finding, tmp_path: Path
) -> None:
    package = real_shape()
    listing = next(row for row in package.features if row.name == "Sketch1" and row.depth == 1)
    cut = depth_0(package, CUT)
    another = listing.model_copy(update={"id": "feat:0901", "folder_id": cut.id, "index": 901})
    package = with_rows(package, another)

    comparison = compared(
        tmp_path, recorded, ["Sketch1", "Sketch1", "Sketch1", BOSS], ["Sketch1", BOSS],
        package=package,
    )

    assert outcome(comparison) == ((), ((0, 2),), 0)


# --- still lost ------------------------------------------------------------------------------


def test_a_depth_0_row_dropped_with_its_second_listing_is_lost(
    recorded: Finding, tmp_path: Path
) -> None:
    """The absorbed sketch named no more at all: its depth-0 row is a real position, and the
    reading never drops it, so the finding is lost and the current one added."""
    comparison = compared(tmp_path, recorded, ["Sketch1", "Sketch1", BOSS], [BOSS])

    assert outcome(comparison) == ((0,), (), 1)


def test_a_merged_pair_named_once_is_never_removed(recorded: Finding, tmp_path: Path) -> None:
    """Named once, the location may be the depth-0 row's: it stays, and the carried row's goes."""
    lost = compared(tmp_path, recorded, ["Sketch1", BOSS, CARRIED], [BOSS])
    narrowed = compared(tmp_path / "kept", recorded, ["Sketch1", BOSS, CARRIED], ["Sketch1", BOSS])

    assert outcome(lost) == ((0,), (), 1)
    assert outcome(narrowed) == ((), ((0, 1),), 0)


def test_one_second_listing_de_duplicates_one_occurrence_and_no_more(
    recorded: Finding, tmp_path: Path
) -> None:
    comparison = compared(
        tmp_path, recorded, ["Sketch1", "Sketch1", "Sketch1", BOSS], ["Sketch1", BOSS]
    )

    assert outcome(comparison) == ((0,), (), 1)


def test_a_carried_row_sharing_its_reference_with_a_kept_content_row_is_not_removed(
    recorded: Finding, tmp_path: Path
) -> None:
    package = real_shape()
    carried = only(package, CARRIED)
    package = with_rows(package, sharing(carried, id="feat:0902", type_name="Extrusion"))

    comparison = compared(tmp_path, recorded, [BOSS, CARRIED], [BOSS], package=package)

    assert outcome(comparison) == ((0,), (), 1)


def test_a_remaining_subject_swapped_for_another_is_lost(recorded: Finding, tmp_path: Path) -> None:
    """After the second listing's occurrence goes, `Boss-Extrude1` remains where the current
    finding names `Cut-Extrude1`: not the same subject, so lost (decision 25A)."""
    comparison = compared(tmp_path, recorded, ["Sketch1", "Sketch1", BOSS], ["Sketch1", CUT])

    assert outcome(comparison) == ((0,), (), 1)


def test_a_finding_that_also_gained_a_subject_is_lost(recorded: Finding, tmp_path: Path) -> None:
    comparison = compared(tmp_path, recorded, ["Sketch1", "Sketch1", BOSS], ["Sketch1", BOSS, CUT])

    assert outcome(comparison) == ((0,), (), 1)


# --- the Standards sketch check (T134-Q2) ---------------------------------------------------


def test_a_standards_sketch_finding_that_lost_only_a_second_listing_narrows(
    recorded: Finding, tmp_path: Path
) -> None:
    """The Standards sketch check reads the same tree since T133 and names an absorbed sketch once
    where the recording named its depth-0 row and its second listing: by T134-Q2's default the
    tree-reading clause reads it, one location removed, neither lost nor added."""
    comparison = compared(
        tmp_path,
        recorded,
        ["Sketch1", "Sketch1", "Sketch2"],
        ["Sketch1", "Sketch2"],
        check=STANDARDS_SKETCHES,
    )

    assert outcome(comparison) == ((), ((0, 1),), 0)


def test_a_standards_sketch_finding_still_naming_its_carried_sketch_narrows_by_the_listing(
    recorded: Finding, tmp_path: Path
) -> None:
    """T133's Standards check still grades the hole's carried profile sketch under its hole, so its
    current finding keeps it: the carried row *may* be removed, and the finding narrows by the
    second listing's occurrence alone."""
    comparison = compared(
        tmp_path,
        recorded,
        ["Sketch1", "Sketch1", CARRIED],
        ["Sketch1", CARRIED],
        check=STANDARDS_SKETCHES,
    )

    assert outcome(comparison) == ((), ((0, 1),), 0)


@pytest.mark.parametrize(
    ("recorded_names", "current_names"),
    [
        pytest.param(
            ["Sketch1", "Sketch1", "Sketch2"], ["Sketch1"], id="a-sketch-named-once-dropped"
        ),
        pytest.param(
            ["Sketch1", "Sketch1", "Sketch2", "Sketch2"],
            ["Sketch1"],
            id="a-merged-pair-dropped-whole",
        ),
        pytest.param(["Sketch1", "Sketch1"], ["Sketch2"], id="the-sketch-swapped-for-another"),
        pytest.param(["Sketch1", "Sketch1"], ["Sketch1", "Sketch2"], id="a-sketch-gained"),
        pytest.param(
            ["Sketch1", "Sketch1", "Sketch1"], ["Sketch1"], id="more-than-one-per-second-listing"
        ),
    ],
)
def test_a_real_sketch_subject_lost_from_a_standards_sketch_finding_stays_lost(
    recorded: Finding,
    tmp_path: Path,
    recorded_names: list[str],
    current_names: list[str],
) -> None:
    """The depth-0 row is a real position the reading never drops: a sketch the current finding
    no longer names, one swapped for another, one gained, or a pair de-duplicated beyond its one
    second listing is lost and the current finding added, as for `rms.*`."""
    comparison = compared(
        tmp_path, recorded, recorded_names, current_names, check=STANDARDS_SKETCHES
    )

    assert outcome(comparison) == ((0,), (), 1)


def test_the_type_tables_clause_never_narrows_a_standards_sketch_finding(
    recorded: Finding, tmp_path: Path
) -> None:
    """A location naming only rows the table does not count, and no row the reading folds, is
    decision 23A's to remove; the type table decides the RMS rules' subjects, not what a
    Standards check names. The same two findings narrow under an `rms.*` check and are lost
    under the Standards sketch check."""
    package = real_shape()
    table = load_table()
    plane = at(package, "Front Plane")
    assert (plane.document_id, plane.persist_ref) in not_content_locations(package, table)
    assert (plane.document_id, plane.persist_ref) not in folded_locations(package, table)

    rms = compared(tmp_path / "rms", recorded, ["Front Plane", "Sketch1"], ["Sketch1"])
    standards = compared(
        tmp_path / "standards",
        recorded,
        ["Front Plane", "Sketch1"],
        ["Sketch1"],
        check=STANDARDS_SKETCHES,
    )

    assert outcome(rms) == ((), ((0, 1),), 0)
    assert outcome(standards) == ((0,), (), 1)


def test_narrowed_key_reads_a_standards_sketch_finding_by_the_readings_clause_alone(
    recorded: Finding,
) -> None:
    """The second listing's occurrence and the carried row go; the row the table does not count
    stays, although it is in the type table's set."""
    package = real_shape()
    table = load_table()
    finding = naming(
        recorded,
        package,
        ["Front Plane", "Sketch1", "Sketch1", CARRIED],
        check=STANDARDS_SKETCHES,
    )

    narrowed = narrowed_key(
        finding, not_content_locations(package, table), folded=folded_locations(package, table)
    )

    assert narrowed is not None
    assert narrowed.removed_locations == 2
    assert narrowed.key == key_of(
        recorded, package, ["Front Plane", "Sketch1"], check=STANDARDS_SKETCHES
    )


def test_every_other_standards_check_is_listed() -> None:
    """The cases below run over the catalogue itself, so a Standards check added later is held."""
    assert len(OTHER_STANDARDS_CHECKS) == len(STANDARDS_RULES) - 1
    assert all(check.startswith("standards.") for check in OTHER_STANDARDS_CHECKS)


@pytest.mark.parametrize("check", OTHER_STANDARDS_CHECKS)
def test_any_other_standards_check_is_never_narrowed(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """Only the sketch check reads the shared tree reading; every other Standards check reads the
    rows as dumped, so a subject it no longer names is a real one: lost, never narrowed."""
    package = real_shape()
    table = load_table()
    names = ["Sketch1", "Sketch1", CARRIED]

    comparison = compared(tmp_path, recorded, names, ["Sketch1"], check=check)

    assert (
        narrowed_key(
            naming(recorded, package, names, check=check),
            not_content_locations(package, table),
            folded=folded_locations(package, table),
        )
        is None
    )
    assert outcome(comparison) == ((0,), (), 1)


# --- the rule's parts ------------------------------------------------------------------------


def test_the_reading_folds_the_merged_pairs_and_the_carried_row() -> None:
    package = real_shape()
    folded = folded_locations(package, load_table())

    expected = {
        (at(package, name).document_id, at(package, name).persist_ref): FoldedLocation(
            positions=1, listings=1
        )
        for name in ABSORBED
    }
    carried = at(package, CARRIED)
    expected[(carried.document_id, carried.persist_ref)] = FoldedLocation(positions=0, listings=0)
    assert folded == expected


@pytest.mark.parametrize(
    "package",
    [
        pytest.param(remodel_package(absorbed_sketch_features()), id="the-flat-walk"),
        pytest.param(part_package(), id="decision-23As-part"),
    ],
)
def test_a_tree_with_neither_shape_folds_nothing(package: EvidencePackage) -> None:
    """So every decision 23A case reads exactly as it did."""
    assert folded_locations(package, load_table()) == {}


def test_the_reading_is_per_document(tmp_path: Path) -> None:
    """A reference is scoped to the document that owns it: the same shape in each part folds
    each part's own locations, never another's."""
    one = real_shape()
    other = remodel_package(absorbed_sketch_features(), document_id="doc:2", name="cover")
    other = carried_under(absorbed_twice(other, *ABSORBED), "Hole1", CARRIED)
    renumbered = [
        row.model_copy(update={"id": row.id.replace("feat:", "feat:2"), "folder_id": (
            None if row.folder_id is None else row.folder_id.replace("feat:", "feat:2")
        )})
        for row in other.features
    ]
    both = with_rows(one, *renumbered)

    folded = folded_locations(both, load_table())

    assert len(folded) == 2 * (len(ABSORBED) + 1)
    assert {scope for scope, _ in folded} == {"doc:1", "doc:2"}


def test_narrowed_key_keeps_the_first_occurrences_and_counts_what_it_removed(
    recorded: Finding,
) -> None:
    package = real_shape()
    finding = naming(recorded, package, ["Sketch1", BOSS, "Sketch1", CARRIED])

    narrowed = narrowed_key(
        finding,
        not_content_locations(package, load_table()),
        folded=folded_locations(package, load_table()),
    )

    assert narrowed is not None
    assert narrowed.removed_locations == 2
    assert narrowed.key == key_of(recorded, package, ["Sketch1", BOSS])


def test_without_the_readings_locations_narrowed_key_is_decision_23as(recorded: Finding) -> None:
    """The type table's clause alone, as every caller before T134-Q1 called it."""
    package = real_shape()
    finding = naming(recorded, package, ["Sketch1", "Sketch1", BOSS, CARRIED])

    assert narrowed_key(finding, not_content_locations(package, load_table())) is None


def test_the_reading_is_run_only_when_an_rms_finding_is_unmatched(
    recorded: Finding, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*arguments: Any) -> Any:
        raise AssertionError("nothing could narrow, so nothing needed the reading")

    monkeypatch.setattr(replay_module, "folded_locations", refuse)
    package = real_shape()
    same = key_of(recorded, package, ["Sketch1", "Sketch1", BOSS])

    comparison = compare_finding_keys(
        [naming(recorded, package, ["Sketch1", "Sketch1", BOSS])], [same], saved(tmp_path, package)
    )

    assert outcome(comparison) == ((), (), 0)


def test_the_reading_is_run_when_a_standards_sketch_finding_is_unmatched(
    recorded: Finding, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[EvidencePackage] = []
    real = replay_module.folded_locations

    def spy(package: EvidencePackage, table: Any) -> Any:
        calls.append(package)
        return real(package, table)

    monkeypatch.setattr(replay_module, "folded_locations", spy)

    comparison = compared(
        tmp_path, recorded, ["Sketch1", "Sketch1"], ["Sketch1"], check=STANDARDS_SKETCHES
    )

    assert len(calls) == 1
    assert outcome(comparison) == ((), ((0, 1),), 0)


def test_the_reading_is_not_run_when_only_another_standards_finding_is_unmatched(
    recorded: Finding, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*arguments: Any) -> Any:
        raise AssertionError("no finding of a family narrowing reads was unmatched")

    monkeypatch.setattr(replay_module, "folded_locations", refuse)

    comparison = compared(
        tmp_path, recorded, ["Sketch1", "Sketch1"], ["Sketch1"], check=OTHER_STANDARDS_CHECKS[0]
    )

    assert outcome(comparison) == ((0,), (), 1)


def test_the_recordings_own_package_and_the_current_table_are_read(
    recorded: Finding, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], object]] = []
    real = replay_module.folded_locations

    def spy(package: EvidencePackage, table: Any) -> Any:
        calls.append(([row.id for row in package.features], table))
        return real(package, table)

    monkeypatch.setattr(replay_module, "folded_locations", spy)

    compared(tmp_path, recorded, ["Sketch1", "Sketch1", BOSS], ["Sketch1", BOSS])

    [(ids, table)] = calls
    assert ids == [row.id for row in real_shape().features]
    assert table is load_table()


# --- the generator, through the same function -------------------------------------------------


def fixture_of(tmp_path: Path, recording: Path, fmap: FictionalMap) -> Path:
    """The recording's package scrambled by `fmap` and recorded by today's code, as the
    generator writes a fixture (less the usage adjustment its finding check does not read)."""
    raw = json.loads((recording / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))
    package_dir = tmp_path / "fixture-package"
    package_dir.mkdir()
    scrambled = fmap.package(raw)
    EvidencePackage.model_validate(scrambled)
    (package_dir / PACKAGE_FILE_NAME).write_text(json.dumps(scrambled), encoding="utf-8")
    from tests.support.narrowed import SCRIPT

    return record_scripted_review(tmp_path / "fixture", package_dir, SCRIPT)


def relabelled(run: Path, check: str) -> None:
    """Every loose finding of `run` under `check`: the same subjects under another check's key."""

    def relabel(session: dict[str, Any]) -> None:
        for finding in session["findings"]:
            if finding["check"] == LOOSE:
                finding["check"] = check

    rewrite_session(run, relabel)


def test_the_generators_finding_check_narrows_through_the_same_function(
    tmp_path: Path,
) -> None:
    """The fixture is today's code on the scrambled package, one node per position; the recording
    was made before T133, naming every second listing and the carried row."""
    generator = mechanical.load_generator(GENERATOR)
    recording = record(tmp_path / "recording", real_shape())
    raw = json.loads((recording / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))
    fmap = FictionalMap(keep={row["type_name"] for row in raw["features"]})
    fixture = fixture_of(tmp_path, recording, fmap)
    unchanged = generator.finding_problems(
        read_recording(recording), read_recording(fixture), fmap
    )
    before_the_reading(recording)

    checked = generator.finding_problems(read_recording(recording), read_recording(fixture), fmap)

    assert unchanged == ([], 0, 0)
    assert checked == ([], 0, 1)


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        pytest.param(STANDARDS_SKETCHES, ([], 0, 1), id="the-standards-sketch-check-narrows"),
        pytest.param(
            OTHER_STANDARDS_CHECKS[0],
            (["the finding keys differ: 1 recorded keys are missing and 1 are new"], 0, 0),
            id="another-standards-check-refuses",
        ),
    ],
)
def test_the_generator_reads_the_standards_sketch_check_through_the_same_function(
    tmp_path: Path, check: str, expected: tuple[list[str], int, int]
) -> None:
    """T134-Q2's default in the generator's finding check, which compares every recorded finding,
    standards included: a recording made before T133, against today's fixture one node per
    position, narrows under the sketch check and refuses the fixture under any other Standards
    check."""
    generator = mechanical.load_generator(GENERATOR)
    recording = record(tmp_path / "recording", real_shape())
    raw = json.loads((recording / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))
    fmap = FictionalMap(keep={row["type_name"] for row in raw["features"]})
    fixture = fixture_of(tmp_path, recording, fmap)
    relabelled(recording, check)
    relabelled(fixture, check)
    unchanged = generator.finding_problems(
        read_recording(recording), read_recording(fixture), fmap
    )
    before_the_reading(recording, check)

    checked = generator.finding_problems(read_recording(recording), read_recording(fixture), fmap)

    assert unchanged == ([], 0, 0)
    assert checked == expected
