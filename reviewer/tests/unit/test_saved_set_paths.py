"""The saved set is location-free, and `score` reads it against the reader's checkout (T047).

`specs/014-design-review-eval/contracts/provenance.md` 6.1 and 8, `cases.md` 4.2 and data-model
section 4 "Saved set" (PROV-08, RF-4, RF-54; FR-051; US2-11):

- `benchmark run` saves `<run>/benchmark-set.json` as `BenchmarkSet.saved_form(root=...)`: every
  path inside the checkout root-relative with `/`, a private one absolute; UTF-8, LF, one final
  newline, written through the one atomic writer before any review;
- so two checkouts of one tree at two locations save the same bytes, and the same `set_digest`;
- `benchmark score` with no `--set` reads that copy through `sets.load_saved_set(path, root=...)`,
  resolving its relative entries against the reader's checkout and never against the run
  folder's grandparent, the rule `benchmark/sets.py:45` applied at `be01974`; a copy saved before
  this feature (absolute entries) still loads.

Each run here is a scripted `benchmark run --provider fake` over a set file lying in a temporary
checkout's `benchmarks/sets/`, the command pointed at that checkout by patching
`swreview.benchmark.sets.REPO_ROOT`, the one root it reads. The second-worktree refusal, on which
"one root" rests, is `test_benchmark_sets.py`'s
`test_a_set_file_in_a_second_worktree_is_refused_naming_both_roots` (RF-4).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import atomic, cli
from swreview.benchmark import sets
from swreview.benchmark.runner import PROVENANCE_FILE
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet, load_set
from swreview.ir.loader import save_package
from tests.support.answer_keys import write_key
from tests.support.packages import build_package
from tests.unit.test_benchmark_sets import absolute_entry, relative_entry, sets_folder, write_set

SAVED_SET_FILE = "benchmark-set.json"
PACKAGE = "benchmarks/packages/pkg-1"


def checkout_with_a_package(checkout: Path) -> Path:
    """A temporary checkout holding one package under `benchmarks/packages/` and a set file
    in its `benchmarks/sets/` naming it relatively; returns the set file."""
    save_package(build_package(), checkout / PACKAGE)
    return write_set(sets_folder(checkout) / "parity.json", [relative_entry(held_out=False)])


def run_from(checkout: Path, set_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scripted `benchmark run` of `set_path` into `out`, the command's root `checkout`."""
    monkeypatch.setattr(sets, "REPO_ROOT", checkout)
    result = CliRunner().invoke(
        cli.app,
        ["benchmark", "run", "--set", str(set_path), "--out", str(out), "--provider", "fake"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr


def saved_entries(out: Path) -> list[dict[str, Any]]:
    return json.loads((out / SAVED_SET_FILE).read_text(encoding="utf-8"))["packages"]


def test_the_saved_set_names_repository_paths_relatively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-051: the run folder carries the checkout-relative path, never the checkout's location,
    and the saved bytes are exactly the loaded set's saved form."""
    checkout = tmp_path / "checkout"
    set_path = checkout_with_a_package(checkout)
    out = tmp_path / "runs" / "relative"

    run_from(checkout, set_path, out, monkeypatch)

    assert [entry["path"] for entry in saved_entries(out)] == [PACKAGE]
    saved = (out / SAVED_SET_FILE).read_bytes()
    assert saved == load_set(set_path, root=checkout).saved_form(root=checkout)


def test_two_checkouts_at_different_locations_save_the_same_bytes_and_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US2-11: one tree copied to two locations and run from each gives byte-equal saved sets
    and equal `set_digest`s, so `compare` places the two runs in one study."""
    first = tmp_path / "one" / "checkout"
    checkout_with_a_package(first)
    second = tmp_path / "two" / "deeper" / "checkout"
    shutil.copytree(first, second)
    runs = {
        first: tmp_path / "runs" / "from-one",
        second: tmp_path / "runs" / "from-two",
    }

    for checkout, out in runs.items():
        run_from(checkout, sets_folder(checkout) / "parity.json", out, monkeypatch)

    first_out, second_out = runs.values()
    assert (first_out / SAVED_SET_FILE).read_bytes() == (second_out / SAVED_SET_FILE).read_bytes()
    digests = [
        json.loads((out / PROVENANCE_FILE).read_text(encoding="utf-8"))["set_digest"]
        for out in runs.values()
    ]
    assert digests[0] == digests[1]


def test_a_private_entry_is_saved_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A package outside the root is private and keeps its absolute path; an in-checkout entry
    beside it is still relative."""
    checkout = tmp_path / "checkout"
    save_package(build_package(), checkout / PACKAGE)
    private = tmp_path / "private" / "pkg-2"
    save_package(build_package(), private)
    set_path = write_set(
        sets_folder(checkout) / "mixed.json",
        [relative_entry(held_out=False), absolute_entry("pkg-2", private)],
    )
    out = tmp_path / "runs" / "mixed"

    run_from(checkout, set_path, out, monkeypatch)

    assert [entry["path"] for entry in saved_entries(out)] == [
        PACKAGE,
        private.resolve().as_posix(),
    ]


def test_the_saved_set_is_written_with_lf_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No carriage return, one final newline, and written through `atomic.write_atomic`, never
    `write_text`, which writes `\\r\\n` on Windows and would move the digest."""
    checkout = tmp_path / "checkout"
    set_path = checkout_with_a_package(checkout)
    out = tmp_path / "runs" / "lf"
    written: list[tuple[Path, bytes]] = []
    real_write_atomic = atomic.write_atomic

    def spy(path: Path, data: bytes) -> None:
        written.append((path, data))
        real_write_atomic(path, data)

    monkeypatch.setattr(atomic, "write_atomic", spy)

    run_from(checkout, set_path, out, monkeypatch)

    saved = (out / SAVED_SET_FILE).read_bytes()
    assert b"\r" not in saved
    assert saved.endswith(b"}\n")
    assert [data for path, data in written if path.name == SAVED_SET_FILE] == [saved]


def test_the_saved_copy_resolves_against_the_readers_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`benchmark score <run>` with no `--set` reads the saved copy through
    `sets.load_saved_set(path, root=...)`, the root read as the command reads it: the reader's
    checkout, never a folder around the copy. The decoy folder holds the run folder and a built
    package at the entry's relative path, `benchmarks/packages/pkg-1`: it is the copy's
    grandparent (the run folder's parent), so an entry resolved against the copy's grandparent
    would find a package there. A copy saved before this feature, every entry absolute, still
    loads."""
    writer = tmp_path / "writer" / "checkout"
    set_path = checkout_with_a_package(writer)
    decoy = tmp_path / "decoy"
    save_package(build_package(), decoy / PACKAGE)
    out = decoy / "run"
    run_from(writer, set_path, out, monkeypatch)
    reader = tmp_path / "reader" / "checkout"
    shutil.copytree(writer, reader)
    keys = tmp_path / "keys"
    write_key(keys, "pkg-1")

    monkeypatch.setattr(sets, "REPO_ROOT", reader)
    reads: list[tuple[Path, Path]] = []
    real_load_saved_set = sets.load_saved_set

    def recording_load_saved_set(path: Path | str, *, root: Path) -> BenchmarkSet:
        reads.append((Path(path), root))
        return real_load_saved_set(path, root=root)

    monkeypatch.setattr(sets, "load_saved_set", recording_load_saved_set)
    scored: list[BenchmarkSet] = []
    real_score_run = cli.score_run

    def recording_score_run(run_dir: Path, answer_keys: Path, benchmark_set: BenchmarkSet) -> Any:
        scored.append(benchmark_set)
        return real_score_run(run_dir, answer_keys, benchmark_set)

    monkeypatch.setattr(cli, "score_run", recording_score_run)

    def score() -> None:
        result = CliRunner().invoke(
            cli.app, ["benchmark", "score", str(out), "--answer-keys", str(keys)]
        )
        assert result.exit_code == 0, result.stdout + result.stderr

    score()

    assert [(path.resolve(), root) for path, root in reads] == [
        ((out / SAVED_SET_FILE).resolve(), reader)
    ]
    assert [ref.path for ref in scored[-1].packages] == [(reader / PACKAGE).resolve()]

    written_before = BenchmarkSet(
        name="parity",
        packages=[
            BenchmarkPackageRef(
                package_id="pkg-1", path=(writer / PACKAGE).resolve(), held_out=False
            )
        ],
    )
    (out / SAVED_SET_FILE).write_text(
        written_before.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    score()

    assert len(reads) == 2
    assert [ref.path for ref in scored[-1].packages] == [(writer / PACKAGE).resolve()]
