"""The run-folder index the reuse lookup reads, and its bounded fallback (T090, for T091).

Lever 9 needs one answer before it can do anything: *is there a run folder here whose
package was dumped from this design, this way?* There is no index of run folders today
(all VERIFIED): `RunFolders.Create` always makes a fresh timestamped folder
(`Review/RunFolders.cs:296-317`), "the pane's latest run" is an in-memory field cleared on
detach (`Review/ReviewHost.cs:258,271,288,380`), and `RunFolders.ProfileOf` reads only the
first 8 KiB of one `package.json` (`:52,125-186`) **precisely because** a full package is
tens of megabytes and the read happens on the SOLIDWORKS application thread. A lookup that
parsed every `package.json` under the run root is the thing those classes were written to
avoid.

So the dump appends one line per run folder to `run_root/package-index.json`
(data-model.md 9.4) and the lookup reads that. Three rules are asserted here, one per way
this can go wrong:

- **A missing or unparseable index is a miss, never an error.** The index is a cache of
  something that is already on disk; a review that failed because a cache was corrupt would
  be a lever that made the product less reliable than not having it.
- **The lookup verifies the folder and its `package.json` still exist.** The index cannot
  know that an engineer deleted a folder in Explorer, and a row pointing at nothing is the
  one thing that must not become "reuse this".
- **The fallback is bounded.** With no index, the N most recent folders are examined with
  the `ProfileOf` technique - the head of the file only, which is why `reuse_key` is written
  near the top of a package.

Matching is only half the decision: `reusable_for` puts the key, the index and the refusals
of `benchmark/reuse.py` together, because a package that matches can still be one that must
not be reused.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from swreview.benchmark.package_index import (
    INDEX_FILE_NAME,
    SCAN_FOLDER_LIMIT,
    PackageIndexRow,
    append_row,
    find_reusable,
    read_index,
    reusable_for,
)
from swreview.benchmark.reuse import DumpOptions, package_reuse_key
from swreview.ir.models import EvidencePackage
from tests.support.packages import build_package
from tests.support.reuse import reuse_package

OPTIONS = DumpOptions()
WRITTEN_AT = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
KEY = "a" * 64
OTHER_KEY = "b" * 64


def write_run(
    run_root: Path,
    folder: str,
    *,
    reuse_key: str | None = KEY,
    profile: str = "full",
    padding: int = 0,
) -> Path:
    """A run folder holding a package whose head carries `reuse_key` and `profile`.

    `padding` pushes the key past the head the scan reads, which is how "only the head is
    read" is asserted as behaviour rather than trusted.
    """
    directory = run_root / folder
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": "1.4.0",
        "package_id": "11111111-2222-4333-8444-555555555555",
        "created_at": "2026-09-12T12:00:00Z",
    }
    if padding:
        payload["design_name"] = "x" * padding
    payload["reuse_key"] = reuse_key
    payload["extractor"] = {"name": "SwReview.Extractor", "profile": profile}
    (directory / "package.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return directory


def row(folder: str, *, reuse_key: str = KEY, profile: str = "full") -> PackageIndexRow:
    return PackageIndexRow(
        reuse_key=reuse_key,
        folder=folder,
        written_at=WRITTEN_AT,
        profile=profile,
        package_bytes=262_144,
    )


def find(run_root: Path, **kwargs: object) -> PackageIndexRow | None:
    return find_reusable(run_root, KEY, "full", **kwargs)  # type: ignore[arg-type]


# --- appending -----------------------------------------------------------------------


def test_the_index_holds_one_line_per_run_folder(tmp_path: Path) -> None:
    append_row(tmp_path, row("20260912-120000-cover"))
    append_row(tmp_path, row("20260912-130000-cover", reuse_key=OTHER_KEY))

    lines = (tmp_path / INDEX_FILE_NAME).read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert [json.loads(line)["folder"] for line in lines] == [
        "20260912-120000-cover",
        "20260912-130000-cover",
    ]


def test_appending_keeps_the_rows_that_were_already_there(tmp_path: Path) -> None:
    """Appending rather than rewriting: a run that crashes mid-write must not be able to
    cost every earlier folder its row."""
    append_row(tmp_path, row("20260912-120000-cover"))
    append_row(tmp_path, row("20260912-130000-cover"))

    assert [entry.folder for entry in read_index(tmp_path)] == [
        "20260912-120000-cover",
        "20260912-130000-cover",
    ]


def test_a_row_records_what_the_lookup_needs_before_opening_anything(tmp_path: Path) -> None:
    append_row(tmp_path, row("20260912-120000-cover"))

    entry = read_index(tmp_path)[0]

    assert entry.reuse_key == KEY
    assert entry.profile == "full"
    assert entry.written_at == WRITTEN_AT
    assert entry.package_bytes == 262_144


def test_a_negative_package_size_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        PackageIndexRow(
            reuse_key=KEY,
            folder="20260912-120000-cover",
            written_at=WRITTEN_AT,
            profile="full",
            package_bytes=-1,
        )


# --- a miss is never an error ---------------------------------------------------------


def test_no_index_at_all_is_a_miss(tmp_path: Path) -> None:
    assert read_index(tmp_path) == []
    assert find(tmp_path) is None


def test_an_unparseable_index_is_a_miss_and_not_an_error(tmp_path: Path) -> None:
    (tmp_path / INDEX_FILE_NAME).write_text("this is not json\n{\n", encoding="utf-8")

    assert read_index(tmp_path) == []
    assert find(tmp_path) is None


def test_a_half_written_last_line_does_not_cost_the_earlier_rows(tmp_path: Path) -> None:
    """One line per dump means a dump killed mid-append leaves a partial line. The rows
    written before it are still true, so they are still read."""
    write_run(tmp_path, "20260912-120000-cover")
    append_row(tmp_path, row("20260912-120000-cover"))
    with (tmp_path / INDEX_FILE_NAME).open("a", encoding="utf-8") as index:
        index.write('{"reuse_key": "aaa')

    assert [entry.folder for entry in read_index(tmp_path)] == ["20260912-120000-cover"]
    assert find(tmp_path) is not None


def test_a_row_missing_a_member_is_skipped_rather_than_raised(tmp_path: Path) -> None:
    (tmp_path / INDEX_FILE_NAME).write_text(
        json.dumps({"reuse_key": KEY, "folder": "20260912-120000-cover"}) + "\n",
        encoding="utf-8",
    )

    assert read_index(tmp_path) == []


def test_an_unreadable_run_root_is_a_miss(tmp_path: Path) -> None:
    assert find(tmp_path / "no-such-root") is None


# --- what the lookup verifies ---------------------------------------------------------


def test_a_matching_row_whose_folder_still_exists_is_a_hit(tmp_path: Path) -> None:
    write_run(tmp_path, "20260912-120000-cover")
    append_row(tmp_path, row("20260912-120000-cover"))

    found = find(tmp_path)

    assert found is not None
    assert found.folder == "20260912-120000-cover"


def test_a_row_whose_folder_was_deleted_by_hand_is_a_miss(tmp_path: Path) -> None:
    append_row(tmp_path, row("20260912-120000-cover"))

    assert find(tmp_path) is None


def test_a_folder_without_a_package_is_a_miss(tmp_path: Path) -> None:
    (tmp_path / "20260912-120000-cover").mkdir()
    append_row(tmp_path, row("20260912-120000-cover"))

    assert find(tmp_path) is None


def test_a_different_key_is_a_miss(tmp_path: Path) -> None:
    write_run(tmp_path, "20260912-120000-cover", reuse_key=OTHER_KEY)
    append_row(tmp_path, row("20260912-120000-cover", reuse_key=OTHER_KEY))

    assert find(tmp_path) is None


def test_a_different_profile_is_a_miss(tmp_path: Path) -> None:
    """A `model_check` package has empty `holes[]`, `fasteners[]`, `faces[]` and `bodies[]`
    by design, so handing one to a Review that asked for `full` silently narrows it. The
    row carries the profile so the mismatch is rejected before any file is opened."""
    write_run(tmp_path, "20260912-120000-cover", profile="model_check")
    append_row(tmp_path, row("20260912-120000-cover", profile="model_check"))

    assert find(tmp_path) is None


def test_a_folder_escape_in_a_row_is_refused(tmp_path: Path) -> None:
    """The row names a folder relative to the run root. Anything that leaves the run root is
    a row nobody wrote on purpose."""
    append_row(tmp_path, row("../elsewhere"))

    assert find(tmp_path) is None


def test_the_most_recent_matching_row_wins(tmp_path: Path) -> None:
    write_run(tmp_path, "20260912-120000-cover")
    write_run(tmp_path, "20260912-130000-cover")
    append_row(tmp_path, row("20260912-120000-cover"))
    append_row(
        tmp_path,
        PackageIndexRow(
            reuse_key=KEY,
            folder="20260912-130000-cover",
            written_at=WRITTEN_AT + timedelta(hours=1),
            profile="full",
            package_bytes=262_144,
        ),
    )

    found = find(tmp_path)

    assert found is not None
    assert found.folder == "20260912-130000-cover"


# --- the bounded fallback -------------------------------------------------------------


def test_with_no_index_the_most_recent_folders_are_scanned(tmp_path: Path) -> None:
    write_run(tmp_path, "20260912-120000-cover")

    found = find(tmp_path)

    assert found is not None
    assert found.folder == "20260912-120000-cover"
    assert found.package_bytes > 0


def test_the_scan_is_capped_at_the_most_recent_folders(tmp_path: Path) -> None:
    """A run root accumulates a folder per review. Walking all of them on the SOLIDWORKS
    thread is exactly what `ProfileOf` exists to avoid, so the scan stops after the cap and
    a match older than that is a miss - one wasted dump, never a stall."""
    write_run(tmp_path, "20260101-000000-cover")
    for index in range(SCAN_FOLDER_LIMIT):
        write_run(tmp_path, f"20260912-1200{index:02d}-cover", reuse_key=OTHER_KEY)

    assert find(tmp_path) is None
    assert find(tmp_path, scan_limit=SCAN_FOLDER_LIMIT + 1) is not None


def test_the_scan_reads_only_the_head_of_a_package(tmp_path: Path) -> None:
    """`reuse_key` is written near the top of a package for this reason; a key pushed past
    the head the scan reads is not found, which is the bound doing its job."""
    write_run(tmp_path, "20260912-120000-cover", padding=16 * 1024)

    assert find(tmp_path) is None


def test_the_index_is_preferred_to_the_scan(tmp_path: Path) -> None:
    """The index says which folder without opening a package; the scan is the fallback."""
    write_run(tmp_path, "20260912-120000-cover", padding=16 * 1024)
    append_row(tmp_path, row("20260912-120000-cover"))

    found = find(tmp_path)

    assert found is not None
    assert found.folder == "20260912-120000-cover"


def test_a_file_in_the_run_root_is_not_a_run_folder(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("nothing here", encoding="utf-8")

    assert find(tmp_path) is None


# --- matching is not the whole decision ------------------------------------------------


def test_a_package_that_matches_is_reusable(tmp_path: Path) -> None:
    package = reuse_package()
    key = package_reuse_key(package, OPTIONS)
    write_run(tmp_path, "20260912-120000-cover", reuse_key=key)
    append_row(tmp_path, row("20260912-120000-cover", reuse_key=key))

    found = reusable_for(package, OPTIONS, tmp_path, unsaved_changes=False)

    assert found is not None
    assert found.folder == "20260912-120000-cover"


def test_a_refusal_beats_a_matching_key(tmp_path: Path) -> None:
    """Extraction is minutes and a wrong finding is hours: reuse never crosses a refusal,
    however well the key matches."""
    package = reuse_package()
    key = package_reuse_key(package, OPTIONS)
    write_run(tmp_path, "20260912-120000-cover", reuse_key=key)
    append_row(tmp_path, row("20260912-120000-cover", reuse_key=key))

    assert reusable_for(package, OPTIONS, tmp_path, unsaved_changes=True) is None
    assert reusable_for(package, OPTIONS, tmp_path, unsaved_changes=None) is None


def test_a_package_with_no_recorded_file_stat_is_never_reusable(tmp_path: Path) -> None:
    """A 1.2.0 package's key computes, but it cannot see a change at all, so the refusal
    fires before the lookup is worth making."""
    package: EvidencePackage = build_package()
    key = package_reuse_key(package, OPTIONS)
    write_run(tmp_path, "20260912-120000-cover", reuse_key=key)
    append_row(tmp_path, row("20260912-120000-cover", reuse_key=key))

    assert reusable_for(package, OPTIONS, tmp_path, unsaved_changes=False) is None


def test_the_profile_the_lookup_matches_on_is_the_packages_own(tmp_path: Path) -> None:
    package = reuse_package(extractor=reuse_package().extractor.model_copy(
        update={"profile": "model_check"}
    ))
    key = package_reuse_key(package, OPTIONS)
    write_run(tmp_path, "20260912-120000-cover", reuse_key=key, profile="full")
    append_row(tmp_path, row("20260912-120000-cover", reuse_key=key, profile="full"))

    assert reusable_for(package, OPTIONS, tmp_path, unsaved_changes=False) is None
