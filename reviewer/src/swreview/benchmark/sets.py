"""Benchmark sets: which packages belong to a run, and which are held out.

Mirrors `benchmarks/sets/pilot.json` (benchmarks/README.md): a name plus a list of
package references, each a `package_id`, a path (repo-root relative in the committed
file), optionally a case file of scripted answers, and a `held_out` flag consumed by the
scorer's recall calculation.

One root decides every path rule: the running checkout's, `REPO_ROOT`, unless a caller
passes another (feature 014 `contracts/cases.md` 4.2; plan decision RF-4). A relative
entry resolves against it only in a set file lying in `<root>/benchmarks/sets/`, and the
two written forms, `BenchmarkSet.file_form` and `saved_form`, name every path inside it
root-relative, so a saved set's bytes, and its digest, ignore where the checkout lies
(FR-051).

This module never reads an answer key, and only digests a case file. It does refuse, at
load time, any package path that resolves under `benchmarks/answer_keys/` or
`benchmarks/case_files/` - the same rule `swreview.ir.loader` enforces when the reviewer
actually opens a package, applied here so a misconfigured set fails before a run ever
starts (constitution Principle VI, FR-025) - and any package path that holds, or lies in
the folder of, a case file the set names (`contracts/cases.md` 4.3 row 5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swreview.benchmark.digest import sha256_of
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


SET_PATH_FIELDS = ("path", "case_file")
"""The entry fields that name a path, each resolved by the one rule: absolute as written,
relative against the root only in a set file lying in `<root>/benchmarks/sets/` (row 3)."""

CASE_FILE_SHA256 = "case_file_sha256"
"""The saved form's one field a set file never holds (`contracts/cases.md` 4.1)."""

WITHHELD_FROM_THE_PACKAGE = (
    "the reviewer reads the package folder; keep keys and case files outside it"
)
"""Row 5's gist (`contracts/cases.md` 4.3)."""


class BenchmarkPackageRef(ReviewModel):
    """One package entry in a benchmark set (feature 014 `contracts/cases.md` 4.1).

    `case_file` names the entry's scripted answers (`contracts/scripted-answers.md` 2.1), and
    `case_file_sha256` is the digest of its bytes, computed at load and carried into the saved
    set, never into a set file, so a study whose arms read different answers is refused by the
    set digest (plan decision QA-7). Both are absent for an entry naming no case file, whose
    questions are all unscripted.
    """

    package_id: str
    path: Path
    case_file: Path | None = None
    held_out: bool = False
    case_file_sha256: str | None = None


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
        return self._form(root, saved=False)

    def saved_form(self, *, root: Path = REPO_ROOT) -> bytes:
        """The set as `benchmark run` saves it into a run folder, the bytes `set_digest`
        is taken over (`contracts/provenance.md` 6.1).

        Through the same entry serializer as `file_form`, adding each entry's
        `case_file_sha256`, which a set file never holds: one changed byte in a case file
        changes the saved bytes, and so `set_digest` (plan decisions RF-54, QA-7).
        """
        return self._form(root, saved=True)

    def _form(self, root: Path, *, saved: bool) -> bytes:
        """Both written forms: the set's name and each entry through `_entry_form`."""
        payload = {
            "name": self.name,
            "packages": [_entry_form(ref, root, saved=saved) for ref in self.packages],
        }
        return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _entry_form(ref: BenchmarkPackageRef, root: Path, *, saved: bool) -> dict[str, Any]:
    """One entry as both written forms hold it: its path and case file through
    `_path_form`, an absent optional field omitted rather than written as null, and its
    `case_file_sha256` in the saved form only."""
    entry = ref.model_dump(mode="json", exclude_none=True)
    entry["path"] = _path_form(ref.path, root)
    if ref.case_file is not None:
        entry["case_file"] = _path_form(ref.case_file, root)
    if not saved:
        entry.pop(CASE_FILE_SHA256, None)
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

    A relative package path or case file resolves against `root` only when the set file
    lies in `<root>/benchmarks/sets/`. A set file anywhere else names every path
    absolutely, and a relative one there is a `SetError` (feature 014 `contracts/cases.md`
    4.3 row 3), which names both roots when the file lies in another checkout's
    `benchmarks/sets/`. A set file holding a `case_file_sha256` is a `SetError` too (row
    1): the digest is computed here, from each case file's bytes. Every path is resolved,
    and `AnswerKeyAccessError` is raised if a package path - directly, or through a symlink
    or junction - lies under `benchmarks/answer_keys/` or `benchmarks/case_files/` (row 4);
    row 5 then refuses a package path at or under a named case file's folder, and a case
    file inside any entry's package folder.
    """
    return _read_set(path, root, saved=False)


def load_saved_set(path: Path | str, *, root: Path = REPO_ROOT) -> BenchmarkSet:
    """Read the `benchmark-set.json` a run folder saved (`BenchmarkSet.saved_form`).

    `load_set`'s core, except that a saved copy's relative entries resolve against `root`
    wherever the copy lies: a run folder is no sets folder, and its grandparent is no
    checkout (`contracts/provenance.md` 6.1). Each entry's `case_file_sha256` is read as
    saved, the digest of the bytes the run read, never recomputed from a case file changed
    since. A copy saved before feature 014 names every path absolutely and reads as it did.
    """
    return _read_set(path, root, saved=True)


def _read_set(path: Path | str, root: Path, *, saved: bool) -> BenchmarkSet:
    """The one set core: row 1's `case_file_sha256` and row 3 for a set file (never for a
    saved copy), then every entry resolved against `root`, its package path through the
    answer-key guard (row 4), then row 5 over every package folder and case file."""
    set_path = Path(path).resolve()
    checkout = root.resolve()
    payload = json.loads(set_path.read_text(encoding="utf-8"))
    entries = payload["packages"]
    if not saved:
        _refuse_a_case_file_digest(set_path, entries)
        _refuse_relative_paths_outside_sets(set_path, checkout, entries)

    packages = [_package_ref(entry, checkout, saved=saved) for entry in entries]
    _refuse_case_files_overlapping_package_folders(set_path, packages)
    return BenchmarkSet(name=payload["name"], packages=packages)


def _package_ref(entry: dict[str, Any], checkout: Path, *, saved: bool) -> BenchmarkPackageRef:
    """One entry resolved against `checkout`.

    Its package path passes the answer-key guard; its case file resolves by the same rule
    but never meets the guard, since a committed one lies in `benchmarks/case_files/`,
    withheld from the reviewer and not from the set. The case file's digest is a saved
    copy's as saved, else computed from the file's bytes when it can be read; one that
    cannot be read keeps no digest, so `benchmark.runner.preflight_set` refuses it naming
    the file (`contracts/scripted-answers.md` 2.3 row 1).
    """
    package_path = reject_answer_key_path(
        _named_path(entry["path"], checkout),
        "a benchmark set may not reference an answer key as a package",
    )
    named_case_file = entry.get("case_file")
    case_file = None
    if named_case_file is not None:
        case_file = _named_path(named_case_file, checkout).resolve()
    if saved:
        case_file_sha256 = entry.get(CASE_FILE_SHA256)
    else:
        case_file_sha256 = _case_file_digest(case_file)
    return BenchmarkPackageRef(
        package_id=entry["package_id"],
        path=package_path,
        case_file=case_file,
        held_out=bool(entry.get("held_out", False)),
        case_file_sha256=case_file_sha256,
    )


def _named_path(named: str, checkout: Path) -> Path:
    """A path an entry names: absolute as written, or relative against `checkout`."""
    path = Path(named)
    return path if path.is_absolute() else checkout / path


def _case_file_digest(case_file: Path | None) -> str | None:
    """The digest of `case_file`'s raw bytes, through the one raw-bytes digest (plan
    decision RF-48), or `None` when there is no case file or it cannot be read."""
    if case_file is None:
        return None
    try:
        return sha256_of(case_file)
    except OSError:
        return None


def _refuse_a_case_file_digest(set_path: Path, entries: list[dict[str, Any]]) -> None:
    """Row 1's `case_file_sha256` (the rest of row 1 is US5's): the digest is computed at load
    and carried into the saved set, so a set file never holds one (`contracts/cases.md` 4.1)."""
    holding = next((entry for entry in entries if CASE_FILE_SHA256 in entry), None)
    if holding is not None:
        raise _refused(
            set_path,
            f"entry {holding['package_id']} holds {CASE_FILE_SHA256}, which a set file never "
            "holds: it is computed from the case file at load and carried into the saved set",
        )


def _named_paths(entry: dict[str, Any]) -> list[str]:
    """The paths `entry` names, in `SET_PATH_FIELDS` order: its package folder and, where it
    names one, its case file."""
    return [entry[field] for field in SET_PATH_FIELDS if entry.get(field) is not None]


def _refuse_relative_paths_outside_sets(
    set_path: Path, root: Path, entries: list[dict[str, Any]]
) -> None:
    """Row 3: a relative path resolves only in a set file lying in `<root>/benchmarks/sets/`.

    Checked over every path every entry names before any is resolved, in 4.3's order. A set
    file in another checkout's `benchmarks/sets/` is refused naming both roots: resolving it
    against either would give one set two saved forms, so two `set_digest`s (plan decision
    RF-4).
    """
    holder = _sets_checkout(set_path)
    if holder == root:
        return
    relative = next(
        (
            (entry, named)
            for entry in entries
            for named in _named_paths(entry)
            if not Path(named).is_absolute()
        ),
        None,
    )
    if relative is None:
        return
    if holder is not None:
        raise _refused(
            set_path,
            f"{set_path} belongs to the checkout at {holder}, and this code runs from "
            f"{root}: run it from that checkout",
        )
    entry, named = relative
    raise _refused(
        set_path,
        "a set file outside benchmarks/sets names every path absolutely, and entry "
        f"{entry['package_id']} names the relative path {named}",
    )


def _refuse_case_files_overlapping_package_folders(
    set_path: Path, packages: list[BenchmarkPackageRef]
) -> None:
    """Row 5's case-file half (`contracts/cases.md` 4.3; `contracts/scripted-answers.md` 2.1
    and 6): each case file the set names and the folder it lies in are withheld paths, so a
    package folder that is, or lies under, that folder is refused, and so is a case file
    lying inside any entry's package folder, each naming both paths. Every case file against
    every entry's package folder, its own entry's included, so a private case file can
    neither sit in nor contain a folder the reviewer loads (US4-9). The key half is US5's.
    """
    for holder in packages:
        if holder.case_file is None:
            continue
        for ref in packages:
            if ref.path.is_relative_to(holder.case_file.parent):
                raise _refused(
                    set_path,
                    f"entry {ref.package_id}'s package folder {ref.path} is or lies under the "
                    f"folder of entry {holder.package_id}'s case file {holder.case_file}: "
                    f"{WITHHELD_FROM_THE_PACKAGE}",
                )
            if holder.case_file.is_relative_to(ref.path):
                raise _refused(
                    set_path,
                    f"entry {holder.package_id}'s case file {holder.case_file} lies inside "
                    f"entry {ref.package_id}'s package folder {ref.path}: "
                    f"{WITHHELD_FROM_THE_PACKAGE}",
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
