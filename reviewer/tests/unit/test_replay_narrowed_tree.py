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

By the defaults taken 2026-09-27 on review (013 T159, research R2.48, 008 research R2.61), the
clause removes only what each check can no longer name: `standards.part.rebuild_errors` reads the
same `Part.features` since T133 and is named beside the sketch check; a carried row is a place for
every check that still grades it as its owner's - the three RMS sketch rules and both Standards
checks - so a carried sketch or sub-feature their finding drops is lost; and a Standards check's
places are counted without the type table. The checks that name a carried row on the planner's
absorbed-sketches fixture are pinned to exactly those families.

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
from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import evaluate_part as rms_evaluate_part
from swreview.checks.rms_types import load_table
from swreview.checks.standards.part import evaluate_part as standards_evaluate_part
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import RULES as STANDARDS_RULES
from swreview.checks.standards.traversal import graded_documents
from swreview.findings import Finding, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package
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
STANDARDS_REBUILD_ERRORS = "standards.part.rebuild_errors"
STANDARDS_TREE_READERS = (STANDARDS_SKETCHES, STANDARDS_REBUILD_ERRORS)
"""The Standards checks that read `Part.features`, the shared tree reading, since T133 (T159)."""
OTHER_STANDARDS_CHECKS = tuple(sorted(set(STANDARDS_RULES) - set(STANDARDS_TREE_READERS)))
"""Every other Standards check: none reads the shared tree reading."""
DESCRIBED = "rms.intent.every_feature_described"
"""An RMS rule that reads `PartTree.content`, where a carried row holds no place."""
ONE_SKETCH = "rms.sketches.one_sketch_per_feature"
RMS_SKETCH_RULES = ("rms.sketches.fully_defined", "rms.sketches.not_over_defined", ONE_SKETCH)
"""The RMS rules that grade every sketch once, a carried sketch included, as its owner's."""
CARRIED_GRADERS = (*RMS_SKETCH_RULES, *STANDARDS_TREE_READERS)
"""Every check that still grades a carried row: for each it is a place, never removed (T159)."""
ABSORBED_FIXTURE = (
    Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "remodel-plan"
    / "remodel-absorbed-sketches"
)
"""The planner's fixture of the two shapes: three absorbed sketches each listed twice, and the Hole
Wizard's profile sketch `feat:0012` listed only under its hole `feat:0010`."""
CARRIED_ID = "feat:0012"
STANDARDS_PROFILE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "profile-a.yaml"
)
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


def before_the_reading(run: Path, check: str = LOOSE, *, carried: bool = True) -> None:
    """Each `check` finding of `run` (the loose one by default) as a recording made before T133
    names it: each absorbed sketch's location once more, for its second listing, and - with
    `carried` - the carried row's location, what the part check named when it read every row the
    dump lists. A check that still grades the carried row named it before T133 as it does today,
    so its recording gains the second listings alone (`carried=False`)."""
    package = real_shape()
    absorbed = {(at(package, name).document_id, at(package, name).persist_ref) for name in ABSORBED}
    carried_row = at(package, CARRIED).model_dump(mode="json")

    def unfolded(session: dict[str, Any]) -> None:
        for finding in session["findings"]:
            if finding["check"] != check:
                continue
            locations = []
            for location in finding["drawing_locations"]:
                locations.append(location)
                if (location["document_id"], location.get("persist_ref")) in absorbed:
                    locations.append(dict(location))
            finding["drawing_locations"] = [*locations, *([carried_row] if carried else [])]

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


# --- the Standards checks that read the tree (T134-Q2, T159) --------------------------------


@pytest.mark.parametrize("check", STANDARDS_TREE_READERS)
def test_a_standards_finding_that_lost_only_a_second_listing_narrows(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """The Standards sketch check and the rebuild-error check read the same tree since T133 and
    name an absorbed sketch once where the recording named its depth-0 row and its second listing:
    by T134-Q2's default, and T159's for the rebuild-error check, the tree-reading clause reads it,
    one location removed, neither lost nor added."""
    comparison = compared(
        tmp_path,
        recorded,
        ["Sketch1", "Sketch1", "Sketch2"],
        ["Sketch1", "Sketch2"],
        check=check,
    )

    assert outcome(comparison) == ((), ((0, 1),), 0)


@pytest.mark.parametrize("check", CARRIED_GRADERS)
def test_a_finding_still_naming_its_carried_row_narrows_by_the_listing_alone(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """Every check that still grades the hole's carried profile sketch, as its hole's, names it
    today as before T133: the finding narrows by the second listing's occurrence alone."""
    comparison = compared(
        tmp_path,
        recorded,
        ["Sketch1", "Sketch1", CARRIED],
        ["Sketch1", CARRIED],
        check=check,
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
@pytest.mark.parametrize("check", STANDARDS_TREE_READERS)
def test_a_real_subject_lost_from_a_standards_finding_stays_lost(
    recorded: Finding,
    tmp_path: Path,
    recorded_names: list[str],
    current_names: list[str],
    check: str,
) -> None:
    """The depth-0 row is a real position the reading never drops: a sketch the current finding
    no longer names, one swapped for another, one gained, or a pair de-duplicated beyond its one
    second listing is lost and the current finding added, as for `rms.*`."""
    comparison = compared(tmp_path, recorded, recorded_names, current_names, check=check)

    assert outcome(comparison) == ((0,), (), 1)


@pytest.mark.parametrize("check", STANDARDS_TREE_READERS)
def test_the_type_tables_clause_never_narrows_a_standards_finding(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """A location naming only rows the table does not count, and no row the reading folds, is
    decision 23A's to remove; the type table decides the RMS rules' subjects, not what a
    Standards check names. The same two findings narrow under an `rms.*` check and are lost
    under a Standards check that reads the tree."""
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
        check=check,
    )

    assert outcome(rms) == ((), ((0, 1),), 0)
    assert outcome(standards) == ((0,), (), 1)


@pytest.mark.parametrize("check", STANDARDS_TREE_READERS)
def test_narrowed_key_reads_a_standards_finding_by_the_readings_merged_half_alone(
    recorded: Finding, check: str
) -> None:
    """The second listing's occurrence goes; the carried row, a place for a check that still
    grades it (T159), and the row the table does not count, although it is in the type table's
    set, stay."""
    package = real_shape()
    table = load_table()
    finding = naming(
        recorded,
        package,
        ["Front Plane", "Sketch1", "Sketch1", CARRIED],
        check=check,
    )

    narrowed = narrowed_key(
        finding, not_content_locations(package, table), folded=folded_locations(package, table)
    )

    assert narrowed is not None
    assert narrowed.removed_locations == 1
    assert narrowed.key == key_of(
        recorded, package, ["Front Plane", "Sketch1", CARRIED], check=check
    )


def test_every_other_standards_check_is_listed() -> None:
    """The cases below run over the catalogue itself, so a Standards check added later is held."""
    assert set(STANDARDS_TREE_READERS) <= set(STANDARDS_RULES)
    assert len(OTHER_STANDARDS_CHECKS) == len(STANDARDS_RULES) - len(STANDARDS_TREE_READERS)
    assert all(check.startswith("standards.") for check in OTHER_STANDARDS_CHECKS)


@pytest.mark.parametrize("check", OTHER_STANDARDS_CHECKS)
def test_any_other_standards_check_is_never_narrowed(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """Only the sketch check and the rebuild-error check read the shared tree reading; no other
    Standards check reads a part's tree, so a subject it no longer names is a real one: lost,
    never narrowed."""
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


# --- what each check can still name (T159) ---------------------------------------------------


@pytest.mark.parametrize("check", CARRIED_GRADERS)
def test_a_carried_row_a_check_still_grades_is_lost_when_its_finding_drops_it(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """The RMS sketch rules and the Standards checks that read the tree still grade the Hole
    Wizard's carried profile sketch, as its hole's: a finding that no longer names it lost a real
    subject, alone or beside a second listing's occurrence the reading did fold."""
    alone = compared(tmp_path / "alone", recorded, ["Sketch1", CARRIED], ["Sketch1"], check=check)
    with_a_listing = compared(
        tmp_path / "listing", recorded, ["Sketch1", "Sketch1", CARRIED], ["Sketch1"], check=check
    )

    assert outcome(alone) == ((0,), (), 1)
    assert outcome(with_a_listing) == ((0,), (), 1)


@pytest.mark.parametrize("check", [LOOSE, DESCRIBED])
def test_a_carried_row_a_rule_gives_no_place_still_narrows(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """The other `rms.*` rules read `PartTree.content`, where a carried row holds no place: it
    goes, as T134-Q1's default says."""
    comparison = compared(tmp_path, recorded, [BOSS, CARRIED], [BOSS], check=check)

    assert outcome(comparison) == ((), ((0, 1),), 0)


def test_the_type_tables_clause_still_reads_the_rms_sketch_rules(
    recorded: Finding, tmp_path: Path
) -> None:
    """A carried sketch is a place for the RMS sketch rules; a row the table does not count is
    still decision 23A's to remove (`one_sketch_per_feature` names such consumers, research R5)."""
    comparison = compared(
        tmp_path,
        recorded,
        ["Front Plane", "Sketch1", "Sketch1", CARRIED],
        ["Sketch1", CARRIED],
        check=ONE_SKETCH,
    )

    assert outcome(comparison) == ((), ((0, 2),), 0)


def origin_pair() -> EvidencePackage:
    """The real shape with both listings of `Sketch2` named `Origin`, a name the type table
    excludes: a merged pair none of whose rows the table counts."""
    package = real_shape()
    return package.model_copy(
        update={
            "features": [
                row.model_copy(update={"name": "Origin"}) if row.name == "Sketch2" else row
                for row in package.features
            ]
        }
    )


@pytest.mark.parametrize("check", STANDARDS_TREE_READERS)
def test_a_standards_checks_places_are_counted_without_the_type_table(
    recorded: Finding, tmp_path: Path, check: str
) -> None:
    """The type table decides the RMS rules' subjects, not what a Standards check names: the
    depth-0 row of a merged pair the table does not count is still a place, so dropping it is a
    loss, and only the second listing's occurrence may go."""
    package = origin_pair()
    origin = at(package, "Origin")
    assert (origin.document_id, origin.persist_ref) in not_content_locations(package, load_table())

    dropped = compared(
        tmp_path / "dropped", recorded, ["Origin", "Sketch1"], ["Sketch1"],
        package=package, check=check,
    )
    de_duplicated = compared(
        tmp_path / "de-duplicated", recorded, ["Origin", "Origin", "Sketch1"],
        ["Origin", "Sketch1"], package=package, check=check,
    )

    assert outcome(dropped) == ((0,), (), 1)
    assert outcome(de_duplicated) == ((), ((0, 1),), 0)


def absorbed_fixture(**changes: dict[str, Any]) -> EvidencePackage:
    """The planner's absorbed-sketches package with `feat:0012`-style keys' fields replaced
    (`feat_0012={"raw_status": 2}`; `raw_status`, `consumer_ids` and `text_segment_count` are the
    sketch's)."""
    package = load_package(ABSORBED_FIXTURE).package
    rows = []
    for row in package.features:
        change = dict(changes.get(row.id.replace(":", "_"), {}))
        sketch_fields = {
            key: change.pop(key)
            for key in ("raw_status", "consumer_ids", "text_segment_count")
            if key in change
        }
        if sketch_fields:
            assert row.sketch is not None
            change["sketch"] = row.sketch.model_copy(update=sketch_fields)
        rows.append(row.model_copy(update=change))
    return package.model_copy(update={"features": rows})


def test_the_rms_rules_that_name_a_carried_sketch_are_the_ones_it_is_a_place_for() -> None:
    """The Hole Wizard's carried profile sketch made every kind of bad an RMS rule grades - under-
    defined, then over-defined, consumed by two features both times - so every rule that grades
    it names it; those rules are exactly `CARRIED_SKETCH_RMS_CHECKS`, and for every other rule it
    holds no place."""
    table = load_table()
    naming_it: set[str] = set()
    for status in (2, 4):
        package = absorbed_fixture(
            feat_0012={"raw_status": status, "consumer_ids": ["feat:0010", "feat:0008"]}
        )
        rows = list(package.features)
        for result in rms_evaluate_part("doc:1", rows, table, assign_groups(rows, table), package):
            if result.outcome == "fail" and CARRIED_ID in [row.id for row in result.subject_rows]:
                naming_it.add(result.rule_id)

    assert naming_it == set(RMS_SKETCH_RULES)
    assert replay_module.CARRIED_SKETCH_RMS_CHECKS == frozenset(RMS_SKETCH_RULES)


def test_the_standards_checks_that_name_a_carried_row_are_the_ones_that_read_the_tree() -> None:
    """The carried profile sketch under-defined and carrying a rebuild error: the Standards checks
    that name it are exactly `TREE_READING_STANDARDS_CHECKS`, which read `Part.features`."""
    profile = load_profile(STANDARDS_PROFILE)
    package = absorbed_fixture(
        feat_0012={"raw_status": 2, "text_segment_count": 0, "error_code": 1}
    )
    [document] = [
        checked for checked in graded_documents(package, profile) if checked.document_id == "doc:1"
    ]

    naming_it = {
        result.rule_id
        for result in standards_evaluate_part(document, package, profile)
        if result.outcome == "fail" and CARRIED_ID in result.subjects
    }

    assert naming_it == set(STANDARDS_TREE_READERS)
    assert replay_module.TREE_READING_STANDARDS_CHECKS == frozenset(STANDARDS_TREE_READERS)


# --- the rule's parts ------------------------------------------------------------------------


def test_the_reading_folds_the_merged_pairs_and_the_carried_row() -> None:
    """Each merged pair: one depth-0 row, a place for every family, and one second listing. The
    carried row: a place only for the checks that still grade it (T159)."""
    package = real_shape()
    folded = folded_locations(package, load_table())

    expected = {
        (at(package, name).document_id, at(package, name).persist_ref): FoldedLocation(
            positions=1, carried=0, features=1, listings=1
        )
        for name in ABSORBED
    }
    carried = at(package, CARRIED)
    expected[(carried.document_id, carried.persist_ref)] = FoldedLocation(
        positions=0, carried=1, features=1, listings=0
    )
    assert folded == expected


def test_a_merged_pair_the_table_does_not_count_is_a_place_for_the_standards_checks_alone() -> None:
    """Named `Origin`, the pair holds no position the table counts (`positions`), but the reading
    still keeps its depth-0 row as a feature (`features`)."""
    package = origin_pair()
    origin = at(package, "Origin")

    folded = folded_locations(package, load_table())

    assert folded[(origin.document_id, origin.persist_ref)] == FoldedLocation(
        positions=0, carried=0, features=1, listings=1
    )


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


REFUSED = (["the finding keys differ: 1 recorded keys are missing and 1 are new"], 0, 0)


@pytest.mark.parametrize(
    ("check", "carried", "expected"),
    [
        pytest.param(
            STANDARDS_SKETCHES, False, ([], 0, 1), id="the-standards-sketch-check-narrows"
        ),
        pytest.param(
            STANDARDS_REBUILD_ERRORS, False, ([], 0, 1), id="the-rebuild-error-check-narrows"
        ),
        pytest.param(STANDARDS_SKETCHES, True, REFUSED, id="a-carried-sketch-dropped-refuses"),
        pytest.param(
            STANDARDS_REBUILD_ERRORS, True, REFUSED, id="a-carried-sub-feature-dropped-refuses"
        ),
        pytest.param(
            OTHER_STANDARDS_CHECKS[0], False, REFUSED, id="another-standards-check-refuses"
        ),
    ],
)
def test_the_generator_reads_the_standards_tree_readers_through_the_same_function(
    tmp_path: Path, check: str, carried: bool, expected: tuple[list[str], int, int]
) -> None:
    """T134-Q2's and T159's defaults in the generator's finding check, which compares every
    recorded finding, standards included: a recording made before T133, against today's fixture
    one node per position, narrows by its second listings under either Standards check that reads
    the tree, refuses the fixture when the recording also named the carried row the fixture does
    not - a place for both checks - and refuses it under any other Standards check."""
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
    before_the_reading(recording, check, carried=carried)

    checked = generator.finding_problems(read_recording(recording), read_recording(fixture), fmap)

    assert unchanged == ([], 0, 0)
    assert checked == expected
