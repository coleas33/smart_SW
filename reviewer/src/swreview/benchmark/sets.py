"""Benchmark sets: which packages belong to a run, and which are held out.

Mirrors `benchmarks/sets/pilot.json` (benchmarks/README.md): a name plus a list of
package references, each a `package_id`, a path (repo-root relative in the committed
file), and a `held_out` flag consumed by the scorer's recall calculation.

One root decides every path rule: the running checkout's, `REPO_ROOT`, unless a caller
passes another (feature 014 `contracts/cases.md` 4.2; plan decision RF-4). A relative
entry resolves against it only in a set file lying in `<root>/benchmarks/sets/`, and the
two written forms, `BenchmarkSet.file_form` and `saved_form`, name every path inside it
root-relative, so a saved set's bytes, and its digest, ignore where the checkout lies
(FR-051).

This module never reads an answer key. It does refuse, at load time, any package path
that resolves under `benchmarks/answer_keys/` - the same rule `swreview.ir.loader`
enforces when the reviewer actually opens a package, applied here so a misconfigured set
fails before a run ever starts (constitution Principle VI, FR-025).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swreview.findings import ReviewModel
from swreview.ir.loader import reject_answer_key_path

REPO_ROOT = Path(__file__).resolve().parents[4]
"""The running checkout's root, the one root every set rule reads (feature 014
`contracts/cases.md` 4.2; plan decision RF-4): a set file's relative entries resolve
against it, an entry outside it is private, and both written forms name paths relative to
it. It is also the tree `benchmark.runner.current_commit` asks git about, when this
package is running from a checkout. An installed copy has no repository above it and
records no commit."""


class SetError(ValueError):
    """A benchmark set this build refuses to load (feature 014 `contracts/cases.md` 4.3).

    A `ValueError`, so the command line prints it as one line and exits 1. Every message
    starts "benchmark set {file name}:". The answer-key guard's own refusal stays
    `AnswerKeyAccessError` (`swreview.ir.loader`).
    """


class BenchmarkPackageRef(ReviewModel):
    """One package entry in a benchmark set."""

    package_id: str
    path: Path
    held_out: bool = False


class BenchmarkSet(ReviewModel):
    name: str
    packages: list[BenchmarkPackageRef]

    def file_form(self, *, root: Path = REPO_ROOT) -> bytes:
        """The set as a set file holds it, the form the case generator writes.

        Each path inside `root` is written root-relative and each private one absolute,
        both with `/` separators (a `Path` would dump with the platform's); UTF-8 JSON,
        indent 2, LF, a final newline; absent optional fields omitted. A set file never
        holds a `case_file_sha256` (plan decision RF-54).
        """
        payload = {
            "name": self.name,
            "packages": [_entry_form(ref, root) for ref in self.packages],
        }
        return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def saved_form(self, *, root: Path = REPO_ROOT) -> bytes:
        """The set as `benchmark run` saves it into a run folder, the bytes `set_digest`
        is taken over (`contracts/provenance.md` 6.1).

        Through the same entry serializer as `file_form`, and today the same bytes: each
        entry's `case_file_sha256`, which a set file never holds, joins the saved form
        alone when case files land (feature 014 T093).
        """
        return self.file_form(root=root)


def _entry_form(ref: BenchmarkPackageRef, root: Path) -> dict[str, Any]:
    """One entry as both written forms hold it: its path through `_path_form`, and an
    absent optional field omitted rather than written as null."""
    entry = ref.model_dump(mode="json", exclude_none=True)
    entry["path"] = _path_form(ref.path, root)
    return entry


def _path_form(path: Path, root: Path) -> str:
    """`path` relative to `root` when it lies inside it, else as it is; `/` either way."""
    relative = checkout_relative(path, root=root)
    return relative.as_posix() if relative is not None else path.as_posix()


def checkout_relative(path: Path | str, *, root: Path) -> Path | None:
    """`path` relative to the checkout at `root` when it lies inside it, else `None`.

    The one inside-the-checkout rule: both resolved, so a `..`, a symlink or a junction counts
    where it leads, then `is_relative_to`, so a neighbour whose name only begins with the
    root's lies outside. The root itself is `Path(".")`. Read by both written forms here, by
    `benchmark run`'s private packages, committable folders (`runner.committable`) and
    carriage-return rule, and by compare's ledger folder (feature 014 `contracts/cases.md` 4.2,
    `provenance.md` 3.2, 6.3 and 6.4). `root` has no default, as `runner`'s predicates on a
    checkout: a caller passes the root its command read.
    """
    resolved, checkout = Path(path).resolve(), Path(root).resolve()
    return resolved.relative_to(checkout) if resolved.is_relative_to(checkout) else None


def load_set(path: Path | str, *, root: Path = REPO_ROOT) -> BenchmarkSet:
    """Read a benchmark set file such as `benchmarks/sets/pilot.json`.

    A relative package path resolves against `root` only when the set file lies in
    `<root>/benchmarks/sets/`. A set file anywhere else names every path absolutely, and a
    relative one there is a `SetError` (feature 014 `contracts/cases.md` 4.3 row 3), which
    names both roots when the file lies in another checkout's `benchmarks/sets/`. Every
    path is resolved, and `AnswerKeyAccessError` is raised if any - directly, or through a
    symlink or junction - lies under `benchmarks/answer_keys/`.
    """
    return _read_set(path, root, saved=False)


def load_saved_set(path: Path | str, *, root: Path = REPO_ROOT) -> BenchmarkSet:
    """Read the `benchmark-set.json` a run folder saved (`BenchmarkSet.saved_form`).

    `load_set`'s core, except that a saved copy's relative entries resolve against `root`
    wherever the copy lies: a run folder is no sets folder, and its grandparent is no
    checkout (`contracts/provenance.md` 6.1). A copy saved before feature 014 names every
    path absolutely and reads as it did.
    """
    return _read_set(path, root, saved=True)


def _read_set(path: Path | str, root: Path, *, saved: bool) -> BenchmarkSet:
    """The one set core: row 3 for a set file (never for a saved copy), then every entry
    resolved against `root` and passed through the answer-key guard."""
    set_path = Path(path).resolve()
    checkout = root.resolve()
    payload = json.loads(set_path.read_text(encoding="utf-8"))
    entries = payload["packages"]
    if not saved:
        _refuse_relative_paths_outside_sets(set_path, checkout, entries)

    packages = []
    for entry in entries:
        raw_path = Path(entry["path"])
        candidate = raw_path if raw_path.is_absolute() else checkout / raw_path
        resolved = reject_answer_key_path(
            candidate, "a benchmark set may not reference an answer key as a package"
        )
        packages.append(
            BenchmarkPackageRef(
                package_id=entry["package_id"],
                path=resolved,
                held_out=bool(entry.get("held_out", False)),
            )
        )
    return BenchmarkSet(name=payload["name"], packages=packages)


def _refuse_relative_paths_outside_sets(
    set_path: Path, root: Path, entries: list[dict[str, Any]]
) -> None:
    """Row 3: a relative entry resolves only in a set file lying in `<root>/benchmarks/sets/`.

    Checked over every entry before any is resolved, in 4.3's order. A set file in another
    checkout's `benchmarks/sets/` is refused naming both roots: resolving it against either
    would give one set two saved forms, so two `set_digest`s (plan decision RF-4).
    """
    holder = _sets_checkout(set_path)
    if holder == root:
        return
    relative = next((entry for entry in entries if not Path(entry["path"]).is_absolute()), None)
    if relative is None:
        return
    if holder is not None:
        raise _refused(
            set_path,
            f"{set_path} belongs to the checkout at {holder}, and this code runs from "
            f"{root}: run it from that checkout",
        )
    raise _refused(
        set_path,
        "a set file outside benchmarks/sets names every path absolutely, and entry "
        f"{relative['package_id']} names the relative path {relative['path']}",
    )


def _sets_checkout(set_path: Path) -> Path | None:
    """The checkout whose `benchmarks/sets/` folder itself holds `set_path`, else `None`."""
    if len(set_path.parents) < 3:
        return None
    checkout = set_path.parents[2]
    return checkout if set_path.parent == checkout / "benchmarks" / "sets" else None


def _refused(set_path: Path, detail: str) -> SetError:
    """A `SetError` carrying the prefix every set refusal starts with."""
    return SetError(f"benchmark set {set_path.name}: {detail}")
