"""A run folder the repository could commit holds no private data (T053, for T054).

`specs/014-design-review-eval/contracts/provenance.md` 6.4 and `benchmark-run.md` 3 row 5 (PROV-09;
FR-051). A folder is **committable** when it lies inside the checkout root and `git check-ignore`
does not report it ignored; inside the root, a folder git cannot answer for counts as committable.
`benchmark run` refuses, before any review, a committable `--out` for a run whose set names a
package outside the root or whose profile is not the fictional example; an `--out` outside the
root, or an ignored one inside it, takes either.

The runs are `test_benchmark_run_pane_study.py`'s: a scripted `benchmark run --provider fake` over
a temporary git repository, the command pointed at it through `swreview.benchmark.sets.REPO_ROOT`,
a spy standing in for every review. Lane P adds the committable-folder scanner's tests here (T055).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.benchmark import runner
from tests.unit.test_benchmark_run_options import benchmark_run
from tests.unit.test_benchmark_run_pane_study import (
    IGNORED,
    PACKAGE,
    another_profile,
    checkout,
    point_at,
    private_package,
    refused,
    watch_reviews,
)
from tests.unit.test_benchmark_sets import relative_entry, sets_folder, write_set


def committable_refusal(out: Path, what: str) -> str:
    """Row 5's message for `out`, the run's private data named by `what`."""
    return (
        f"{out} is inside the repository, where it may be committed; this run {what}: "
        "write it outside the repository"
    )


PRIVATE_PACKAGE = "names private package pkg-2"
ANOTHER_PROFILE = "grades against a profile other than the fictional example"


def test_a_committable_run_folder_is_refused_for_a_private_package_or_another_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A study needs no declaring here: any run's folder inside the repository may be committed,
    so a private package or another profile is refused there, and taken anywhere git ignores or
    outside the checkout."""
    private = private_package(tmp_path / "private" / "pkg-2")
    root = tmp_path / "checkout"
    with_private = checkout(root, private=(private,))
    committed_only = write_set(sets_folder(root) / "committed.json", [relative_entry()])
    point_at(root, monkeypatch)
    reviewed = watch_reviews(monkeypatch)
    profile = another_profile(tmp_path / "profiles")
    inside = root / "runs" / "committable"

    for set_file, options, what in (
        (with_private, (), PRIVATE_PACKAGE),
        (committed_only, ("--standards-profile", str(profile)), ANOTHER_PROFILE),
        (with_private, ("--standards-profile", str(profile)), PRIVATE_PACKAGE),
    ):
        line = refused(benchmark_run(set_file, inside, *options), inside, reviewed)
        assert line.endswith(committable_refusal(inside, what)), line

    # Inside a root git cannot answer for, the folder counts as committable.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    unanswered = tmp_path / "no-repository"
    unanswered_set = checkout(unanswered, private=(private,), repository=False)
    point_at(unanswered, monkeypatch)
    unanswered_out = unanswered / IGNORED / "run"
    line = refused(benchmark_run(unanswered_set, unanswered_out), unanswered_out, reviewed)
    assert line.endswith(committable_refusal(unanswered_out, PRIVATE_PACKAGE)), line

    point_at(root, monkeypatch)
    for out in (tmp_path / "runs" / "outside", root / IGNORED / "run"):
        result = benchmark_run(with_private, out, "--standards-profile", str(profile))
        assert result.exit_code == 0, result.stdout + result.stderr
    assert reviewed == [(root / PACKAGE).resolve(), private.resolve()] * 2

    result = benchmark_run(committed_only, root / "runs" / "fictional")
    assert result.exit_code == 0, result.stdout + result.stderr


def test_committable_is_inside_the_root_and_not_reported_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`runner.committable(path, *, root)`, the one reading row 5 and compare's ledger guard
    share: outside the root never, inside it unless git reports the path ignored, and inside it
    whenever git cannot answer."""
    root = tmp_path / "checkout"
    checkout(root)

    assert runner.committable(root / "runs" / "new", root=root) is True
    assert runner.committable(root / "README.md", root=root) is True
    assert runner.committable(root / IGNORED / "run", root=root) is False
    assert runner.committable(tmp_path / "elsewhere", root=root) is False

    def no_git(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("git is not on the path")

    monkeypatch.setattr("swreview.benchmark.runner.subprocess.run", no_git)
    assert runner.committable(root / IGNORED / "run", root=root) is True
    assert runner.committable(tmp_path / "elsewhere", root=root) is False
