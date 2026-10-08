"""The inputs a run digests check out with LF endings (T057, for T058).

`specs/014-design-review-eval/contracts/provenance.md` 6.5 and 8 (INT-3, PROV-10, RK-5). Every
digest of a text input is taken over the file's raw bytes: `checklist_digest`, `prompt_digest`,
the example profile's `profile_digest` and every case file's digest. Under `* text=auto`
(`.gitattributes:2`) and Git for Windows' `core.autocrlf`, those files check out with `\\r\\n` on
Windows and `\\n` elsewhere, so two machines of one study would record different digests, which
compare refuses. `.gitattributes` gives them `eol=lf` and the checkouts agree; a working copy made
before that rule keeps its `\\r\\n` until it is checked out again, and this test names it.

The files are `config/standards.example.yaml`, `reviewer/src/swreview/agent/checklist_v1.yaml`,
every `reviewer/src/swreview/agent/prompts/*.md` and every file under `benchmarks/`, as git lists
them. A binary one (`-text`: the two drawing PDFs, a packed event stream) is checked for its `eol`
only, which sets just a text file's checkout ending. Skipped where git is absent, never passed.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from swreview.benchmark.sets import REPO_ROOT

DIGESTED_INPUTS = (
    "config/standards.example.yaml",
    "reviewer/src/swreview/agent/checklist_v1.yaml",
    "reviewer/src/swreview/agent/prompts/*.md",
    "benchmarks",
)
"""Section 6.5's files, as `git ls-files` pathspecs."""


def git_output(root: Path, *args: str, stdin: str | None = None) -> str:
    """`git <args>`'s standard output in `root`, fed `stdin`; a git that fails fails the test."""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        input=stdin,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout


def tracked(root: Path, pathspec: str) -> list[str]:
    """The `/`-separated paths `git ls-files` lists for `pathspec` in the checkout at `root`."""
    return [name for name in git_output(root, "ls-files", "-z", "--", pathspec).split("\0") if name]


def attributes(root: Path, paths: Sequence[str], *names: str) -> dict[str, dict[str, str]]:
    """What `git check-attr` reads for each of `paths` in the checkout at `root`: each attribute
    of `names` as `set`, `unset`, `unspecified` or its value. The paths go through `--stdin`, so
    a long list never meets the command line's limit."""
    output = git_output(root, "check-attr", "-z", "--stdin", *names, stdin="\0".join(paths))
    fields = output.split("\0")[:-1]
    assert len(fields) % 3 == 0, output
    found: dict[str, dict[str, str]] = {}
    for start in range(0, len(fields), 3):
        path, name, value = fields[start : start + 3]
        found.setdefault(path, {})[name] = value
    return found


def test_digested_inputs_check_out_with_lf() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    listed = {pathspec: tracked(REPO_ROOT, pathspec) for pathspec in DIGESTED_INPUTS}
    assert [pathspec for pathspec, files in listed.items() if not files] == []
    files = [name for names in listed.values() for name in names]
    found = attributes(REPO_ROOT, files, "text", "eol")

    not_lf = [name for name in files if found[name]["eol"] != "lf"]
    assert not_lf == [], (
        f"{len(not_lf)} digested inputs have no eol=lf in .gitattributes (provenance.md 6.5): "
        + ", ".join(not_lf)
    )
    with_cr = [
        name
        for name in files
        if found[name]["text"] != "unset" and b"\r" in (REPO_ROOT / name).read_bytes()
    ]
    assert with_cr == [], (
        f"{len(with_cr)} digested inputs hold a carriage return, working copies made before "
        ".gitattributes gave them eol=lf (provenance.md 6.5): delete each and check it out "
        "again with `git checkout -- <path>`: " + ", ".join(with_cr)
    )
