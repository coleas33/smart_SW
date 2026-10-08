"""The pane studies' file rules, refused before any review (T053, for T054).

`specs/014-design-review-eval/contracts/provenance.md` 3.2 and 8 and `benchmark-run.md` 3 row 6
(PROV-05, INT-3; FR-014, FR-056; US2-4, US5-15). After the set loads and before P-3, a pane study
refuses, each with one line and exit 1, no review started and nothing written:

- `pane_defaults`: no `--standards-profile`, or one whose `profile_is_example` is false, since every
  committed case is keyed against the example and one study has one profile; and a set naming a
  package outside the repository, since the private slice is its own study;
- both pane studies: a commit git cannot name, or a tracked change, since a paid study must name
  the code it measured; and a digested input inside the repository (the prompt, the checklist, the
  profile, the set file) whose bytes hold a carriage return, as a working copy made before section
  6.5's `eol=lf` keeps them, which would record digests another machine's runs do not share. A file
  outside the repository is never checked;
- `pane_defaults_private`: no `--standards-profile`. Its real profile and private packages pass,
  with `--out` outside the repository (row 5 is `test_committable_paths.py`'s).

Each run is a scripted `benchmark run --provider fake` over a temporary git repository holding a
clean committed tree: the example profile, a fictional package under `benchmarks/packages/`, its
set under `benchmarks/sets/`, and LF copies of the system prompt and the checklist at their places
in a checkout, which `agent.checklist.SYSTEM_PROMPT_FILE` and `CHECKLIST_FILE` are patched to name,
as the running checkout's own lie inside it. The command is pointed at the repository through
`swreview.benchmark.sets.REPO_ROOT`, and a spy stands in for every review. Section 3.2's price row
is lane B6's (T201, T202).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview import cli
from swreview.agent import checklist as agent_checklist
from swreview.agent.settings import PANE_STUDY, PRIVATE_PANE_STUDY
from swreview.benchmark import sets
from swreview.ir.loader import save_package
from tests.support.packages import build_package
from tests.unit.test_benchmark_run_options import benchmark_run, one_line
from tests.unit.test_run_provenance import EXAMPLE_PROFILE, git, read_record

PANE_STUDIES: tuple[str, ...] = (PANE_STUDY, PRIVATE_PANE_STUDY)

PACKAGE = "benchmarks/packages/pkg-1"
SET_FILE = "benchmarks/sets/pane.json"
EXAMPLE = "config/standards.example.yaml"
PROMPT = "reviewer/src/swreview/agent/prompts/system_v1.md"
CHECKLIST = "reviewer/src/swreview/agent/checklist_v1.yaml"
IGNORED = "ignored-runs"
"""A folder the checkout's `.gitignore` ignores: a run folder inside it is not committable."""

DIGESTED: tuple[str, ...] = (PROMPT, CHECKLIST, EXAMPLE, SET_FILE)
"""The digested inputs a pane study reads inside the repository, repository-relative, in row 6's
order; lane A3 adds the case files (T095, T097)."""

REAL_PROMPT = agent_checklist.SYSTEM_PROMPT_FILE
REAL_CHECKLIST = agent_checklist.CHECKLIST_FILE

ARMS: dict[str, tuple[str, ...]] = {
    "off": ("--arm", "off", "--no-explain-findings"),
    "on": ("--arm", "on", "--pane-defaults", "--no-explain-findings"),
}
"""Each arm as section 3.2 requires it typed, the explanation setting stated."""

OFF_ARM = ARMS["off"]

EOL_ADVICE = "out again: section 6.5's `eol=lf` has not reached this working copy"


def lf_bytes(path: Path) -> bytes:
    """`path`'s bytes with LF line endings, whatever this working copy holds (section 6.5)."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def crlf(data: bytes) -> bytes:
    """LF bytes as a working copy made before section 6.5's `eol=lf` holds them."""
    return data.replace(b"\n", b"\r\n")


def private_package(folder: Path) -> Path:
    """A fictional package written at `folder`, outside any checkout: a private entry."""
    save_package(build_package(), folder)
    return folder


def checkout(
    root: Path,
    *,
    private: tuple[Path, ...] = (),
    carriage_return_in: str | None = None,
    repository: bool = True,
) -> Path:
    """Lay out a fictional checkout at `root` and commit it; returns its set file.

    The example profile, LF copies of the system prompt and the checklist at their places in a
    checkout, a `.gitignore` ignoring `IGNORED`, one package under `benchmarks/packages/` and a set
    under `benchmarks/sets/` naming it relatively, then each folder of `private` by its absolute
    path; every package held out, so P-3 has nothing to refuse. The one file `carriage_return_in`
    names, repository-relative, is written with CRLF line endings. Committed with no line-ending
    conversion, so the tree is clean and a carriage return is in the committed bytes, as in a
    working copy git reports clean. `repository=False` leaves no repository: git cannot answer.
    """
    entries = [{"package_id": "pkg-1", "path": PACKAGE, "held_out": True}] + [
        {"package_id": folder.name, "path": str(folder), "held_out": True} for folder in private
    ]
    files = {
        EXAMPLE: lf_bytes(EXAMPLE_PROFILE),
        PROMPT: lf_bytes(REAL_PROMPT),
        CHECKLIST: lf_bytes(REAL_CHECKLIST),
        SET_FILE: (json.dumps({"name": "pane", "packages": entries}, indent=2) + "\n").encode(),
        ".gitignore": f"{IGNORED}/\n".encode(),
        "README.md": b"A fictional checkout.\n",
    }
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(crlf(data) if name == carriage_return_in else data)
    save_package(build_package(), root / PACKAGE)
    if repository:
        git(root, "init", "-q")
        git(root, "config", "core.autocrlf", "false")
        git(root, "add", "-A")
        git(
            root,
            "-c",
            "user.name=Fictional Tester",
            "-c",
            "user.email=tester@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "a fictional checkout",
        )
    return root / SET_FILE


def point_at(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the command at the checkout at `root`: its one root, and the prompt and checklist
    copies inside it, which the command names through `agent.checklist` at call time."""
    monkeypatch.setattr(sets, "REPO_ROOT", root)
    monkeypatch.setattr(agent_checklist, "SYSTEM_PROMPT_FILE", root / PROMPT)
    monkeypatch.setattr(agent_checklist, "CHECKLIST_FILE", root / CHECKLIST)


def another_profile(folder: Path) -> Path:
    """A loadable profile whose bytes are not the example's: `profile_is_example` false."""
    folder.mkdir(parents=True, exist_ok=True)
    profile = folder / "standards.yaml"
    profile.write_bytes(lf_bytes(EXAMPLE_PROFILE) + b"# another profile, not the example\n")
    return profile


def watch_reviews(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Swap `cli._review_fn` for a spy that records each package it is handed, reviewing none."""
    reviewed: list[Path] = []

    def spy(package_dir: Path, session_out_dir: Path, **_keywords: Any) -> None:
        reviewed.append(package_dir)

    monkeypatch.setattr(cli, "_review_fn", spy)
    return reviewed


def refused(result: Any, out: Path, reviewed: list[Path]) -> str:
    """The one line a refusal printed, once it is shown to have stopped the run before any
    review: exit 1, the spy never called, and nothing written where `--out` points."""
    assert result.exit_code == 1, result.stdout + result.stderr
    assert reviewed == []
    assert not out.exists()
    return one_line(result)


def pane_run(set_file: Path, out: Path, study: str, *options: str) -> Any:
    """A pane study's off arm into `out`, with `options` (a profile, most often)."""
    return benchmark_run(set_file, out, "--study", study, *OFF_ARM, *options)


# --- pane_defaults: the example profile, committed cases (FR-014, FR-056) ---------------


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_the_pane_study_requires_the_example_profile(
    arm: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every committed case is keyed against the example (FR-027) and one study has one profile
    (D5): no profile and another profile are refused; the example passes, inside the checkout or
    as a copy outside it, since its bytes decide and not its name or folder."""
    root = tmp_path / "checkout"
    set_file = checkout(root)
    point_at(root, monkeypatch)
    reviewed = watch_reviews(monkeypatch)
    study = ("--study", PANE_STUDY, *ARMS[arm])

    no_profile = tmp_path / "runs" / "no-profile"
    line = refused(benchmark_run(set_file, no_profile, *study), no_profile, reviewed)
    assert f"--study {PANE_STUDY}" in line and "no --standards-profile" in line
    assert f"pass --standards-profile {EXAMPLE}" in line

    other = tmp_path / "runs" / "another-profile"
    profile = another_profile(tmp_path / "profiles")
    line = refused(
        benchmark_run(set_file, other, *study, "--standards-profile", str(profile)),
        other,
        reviewed,
    )
    assert f"--study {PANE_STUDY}" in line
    assert "a profile other than the fictional example" in line
    assert "one study has one profile" in line

    copy = tmp_path / "copies" / "example-under-another-name.yaml"
    copy.parent.mkdir()
    copy.write_bytes((root / EXAMPLE).read_bytes())
    for name, example in (("inside", root / EXAMPLE), ("copy", copy)):
        result = benchmark_run(
            set_file, tmp_path / "runs" / name, *study, "--standards-profile", str(example)
        )
        assert result.exit_code == 0, result.stdout + result.stderr
    assert reviewed == [(root / PACKAGE).resolve()] * 2


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_the_pane_study_refuses_a_private_package(
    arm: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US5-15, FR-056: a `pane_defaults` set holds committed cases only, even with the example
    profile and an `--out` outside the repository; the private slice is its own study."""
    private = private_package(tmp_path / "private" / "pkg-2")
    root = tmp_path / "checkout"
    set_file = checkout(root, private=(private,))
    point_at(root, monkeypatch)
    reviewed = watch_reviews(monkeypatch)
    out = tmp_path / "runs" / "private"

    result = benchmark_run(
        set_file,
        out,
        "--study",
        PANE_STUDY,
        *ARMS[arm],
        "--standards-profile",
        str(root / EXAMPLE),
    )

    line = refused(result, out, reviewed)
    assert f"--study {PANE_STUDY}" in line and "private package pkg-2" in line
    assert f"`{PRIVATE_PANE_STUDY}`" in line


# --- both pane studies: the code measured, and the bytes digested (PROV-05, INT-3) -------


@pytest.mark.parametrize("study", PANE_STUDIES)
def test_a_pane_study_refuses_an_unknown_commit_and_a_dirty_tree(
    study: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paid study must name the code it measured, and two unknown commits would pass the
    must-match rule as equal: no commit git can name is refused, a modified tracked file is, and
    so is a tree git cannot vouch clean; an untracked file is no change to the code."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    reviewed = watch_reviews(monkeypatch)

    def run(root: Path, out: Path) -> Any:
        return pane_run(root / SET_FILE, out, study, "--standards-profile", str(root / EXAMPLE))

    no_repository = tmp_path / "no-repository"
    checkout(no_repository, repository=False)
    point_at(no_repository, monkeypatch)
    out = tmp_path / "runs" / "no-commit"
    line = refused(run(no_repository, out), out, reviewed)
    assert f"--study {study}" in line and "git cannot name this checkout's commit" in line
    assert "a paid study must name the code it measured" in line

    dirty = tmp_path / "dirty"
    checkout(dirty)
    (dirty / "README.md").write_bytes(b"A fictional checkout, edited after its commit.\n")
    point_at(dirty, monkeypatch)
    out = tmp_path / "runs" / "dirty"
    line = refused(run(dirty, out), out, reviewed)
    assert f"--study {study}" in line and "tracked files differ from commit" in line
    assert "a paid study must name the code it measured" in line

    clean = tmp_path / "clean"
    checkout(clean)
    (clean / "notes.txt").write_bytes(b"untracked, and no change to the code\n")
    point_at(clean, monkeypatch)
    with monkeypatch.context() as unanswered:
        unanswered.setattr(cli, "tree_dirty", lambda *, root: None)
        out = tmp_path / "runs" / "unanswered"
        line = refused(run(clean, out), out, reviewed)
    assert f"--study {study}" in line and "git cannot say whether" in line

    result = run(clean, tmp_path / "runs" / "clean")
    assert result.exit_code == 0, result.stdout + result.stderr
    assert reviewed == [(clean / PACKAGE).resolve()]


def test_a_pane_study_refuses_a_digested_input_holding_a_carriage_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INT-3: in each pane study, the prompt, the checklist, the profile and the set file, each
    in turn holding a carriage return inside the repository in a tree git reports clean, are
    refused, naming the file repository-relative. A private profile outside the repository is
    the operator's own file and is never checked."""
    reviewed = watch_reviews(monkeypatch)
    for study in PANE_STUDIES:
        for name in DIGESTED:
            root = tmp_path / study / Path(name).name
            set_file = checkout(root, carriage_return_in=name)
            point_at(root, monkeypatch)
            out = tmp_path / "runs" / study / Path(name).name

            result = pane_run(set_file, out, study, "--standards-profile", str(root / EXAMPLE))

            line = refused(result, out, reviewed)
            assert line.endswith(f": check {name} {EOL_ADVICE}"), line

    root = tmp_path / "clean"
    set_file = checkout(root)
    point_at(root, monkeypatch)
    real_profile = tmp_path / "private" / "standards.yaml"
    real_profile.parent.mkdir()
    real_profile.write_bytes(crlf(another_profile(tmp_path / "profiles").read_bytes()))

    result = pane_run(
        set_file,
        tmp_path / "runs" / "private-profile",
        PRIVATE_PANE_STUDY,
        "--standards-profile",
        str(real_profile),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert reviewed == [(root / PACKAGE).resolve()]


# --- pane_defaults_private: the real profile, private packages (PROV-05, 23A) -------------


def test_the_private_pane_study_takes_the_real_profile_and_private_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The private slice's own study grades against the real profile over private packages,
    written outside the repository; with no profile it is refused."""
    private = private_package(tmp_path / "private" / "pkg-2")
    root = tmp_path / "checkout"
    set_file = checkout(root, private=(private,))
    point_at(root, monkeypatch)
    reviewed = watch_reviews(monkeypatch)
    real_profile = another_profile(tmp_path / "profiles")

    no_profile = tmp_path / "runs" / "no-profile"
    line = refused(pane_run(set_file, no_profile, PRIVATE_PANE_STUDY), no_profile, reviewed)
    assert f"--study {PRIVATE_PANE_STUDY}" in line and "no --standards-profile" in line

    out = tmp_path / "runs" / "private"
    result = pane_run(set_file, out, PRIVATE_PANE_STUDY, "--standards-profile", str(real_profile))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert reviewed == [(root / PACKAGE).resolve(), private.resolve()]
    record = read_record(out)
    assert record["lever"] == PRIVATE_PANE_STUDY
    assert record["profile_is_example"] is False
