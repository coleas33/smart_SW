"""Benchmark sets: which packages belong to a run, and which are held out.

Mirrors `benchmarks/sets/pilot.json` (benchmarks/README.md): a name plus a list of
package references, each a `package_id`, a path (repo-root relative in the committed
file), optionally its answer key, a case file of scripted answers, its design, the case it
is the clean twin of and the anchors it represents, and a `held_out` flag consumed by the
scorer's recall calculation. A set in which some entry names its key is keyed, and every
entry then names its own; a set naming none is keyless, as every set written before feature
014, and reads its keys from `--answer-keys` (`key_path`, the one rule; plan decision RF-4).

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
the folder of, a key or case file the set names (`contracts/cases.md` 4.3 row 5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from swreview.benchmark.digest import sha256_of
from swreview.benchmark.families import ANCHOR_FAMILY
from swreview.findings import ReviewModel, model_refusals
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

    A `ValueError`, so the command line prints it as one line and exits 1. Every refusal of
    a set file starts "benchmark set {file name}:"; `key_path`'s, which reads one entry and
    no file, names the entry. The answer-key guard's own refusal stays
    `AnswerKeyAccessError` (`swreview.ir.loader`).
    """


SET_PATH_FIELDS = ("path", "key", "case_file")
"""The entry fields that name a path, each resolved by the one rule: absolute as written,
relative against the root only in a set file lying in `<root>/benchmarks/sets/` (row 3)."""

CASE_FILE_SHA256 = "case_file_sha256"
"""The saved form's one field a set file never holds (`contracts/cases.md` 4.1)."""

WITHHELD_FROM_THE_PACKAGE = (
    "the reviewer reads the package folder; keep keys and case files outside it"
)
"""Row 5's gist (`contracts/cases.md` 4.3)."""

EVERY_ENTRY_NAMES_ITS_KEY = "every entry of a keyed set names its key"
"""Row 6's gist for an entry of a keyed set naming no key (`contracts/cases.md` 4.3)."""

KEYS_ON_THEIR_SIDE = (
    "a committed case's key and case file live in the repository, a private case's outside it"
)
"""Row 6's gist for a key or case file on the other side of the root from its package."""


class BenchmarkPackageRef(ReviewModel):
    """One package entry in a benchmark set (feature 014 `contracts/cases.md` 4.1).

    `key` names the entry's answer key, a path as `path` is: a set in which some entry names
    one is keyed, and row 6 then holds every entry to its own; a set naming none is keyless
    and its keys are read from `--answer-keys` (`key_path`; plan decision RF-4). `case_file`
    names the entry's scripted answers (`contracts/scripted-answers.md` 2.1), and
    `case_file_sha256` is the digest of its bytes, computed at load and carried into the saved
    set, never into a set file, so a study whose arms read different answers is refused by the
    set digest (plan decision QA-7). Both are absent for an entry naming no case file, whose
    questions are all unscripted. `design` is the case's design, `twin_of` the package id of
    the entry this one is the clean twin of (FR-028), and `represents` the anchors R-1 to R-8
    and analyst-found defects AF-1 to AF-3 it stands for (FR-029). Every field but the first
    two is optional, so a set or saved copy written before feature 014 still loads, and
    absent unless named (plan decision CS-13).
    """

    package_id: str
    path: Path
    key: Path | None = None
    case_file: Path | None = None
    held_out: bool = False
    design: str | None = None
    twin_of: str | None = None
    represents: list[str] | None = None
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
    """One entry as both written forms hold it: each path it names (`SET_PATH_FIELDS`, its
    package folder, key and case file) through `path_form`, its other fields as given, an
    absent optional field omitted rather than written as null, and its `case_file_sha256` in
    the saved form only."""
    entry = ref.model_dump(mode="json", exclude_none=True)
    for field in SET_PATH_FIELDS:
        named = getattr(ref, field)
        if named is not None:
            entry[field] = path_form(named, root)
    if not saved:
        entry.pop(CASE_FILE_SHA256, None)
    return entry


def path_form(path: Path, root: Path) -> str:
    """`path` relative to `root` when it lies inside it, else as it is; `/` either way: how a
    set's entry names a path, which `benchmark.runner.preflight_set`'s refusals name too."""
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

    Refused by feature 014 `contracts/cases.md` 4.3's rows, in order, each a `SetError`
    but row 4. Row 1: a file that cannot be read or is not JSON, or that the strict models
    refuse (an unknown field, a missing required one, a wrong type), naming the field; a set
    file holding a `case_file_sha256`, since the digest is computed here, from each case
    file's bytes. Row 2: a `package_id` named twice. Row 3: a relative package path, key or
    case file resolves against `root` only when the set file lies in `<root>/benchmarks/sets/`;
    a set file anywhere else names every path absolutely, and one in another checkout's
    `benchmarks/sets/` is refused naming both roots. Every path is then resolved, and row 4
    raises `AnswerKeyAccessError` if a package path - directly, or through a symlink or
    junction - lies under `benchmarks/answer_keys/` or `benchmarks/case_files/`. Row 5: a
    package path at or under a named key's or case file's folder, and a key or case file
    inside any entry's package folder. Row 6, in a keyed set only: an entry naming no key, or
    a key or case file on the other side of the root from its package. Row 7: a `twin_of`
    naming no other entry, a `represents` value outside R-1 to R-8 and AF-1 to AF-3, or one
    repeated. A missing optional field stays absent.
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


def key_path(entry: BenchmarkPackageRef, answer_keys: Path | None) -> Path:
    """Where `entry`'s answer key lives, the one rule `score_run` and the set summary read
    (feature 014 `contracts/cases.md` 4.1; plan decision RF-4).

    In a keyed set it is the entry's own `key`, resolved at load, whatever directory is
    given; row 6 holds every entry of a loaded keyed set to one, so an entry naming none is
    in a keyless set, whose key is `<answer_keys>/<package_id>.json`, as `benchmark score`
    has always read it. A keyless entry given no directory is a `SetError` naming
    `--answer-keys`.
    """
    if entry.key is not None:
        return entry.key
    if answer_keys is None:
        raise SetError(
            f"set entry {entry.package_id} names no key, so its set is keyless and reads its "
            "keys from --answer-keys <dir>, which was not given"
        )
    return Path(answer_keys) / f"{entry.package_id}.json"


def _read_set(path: Path | str, root: Path, *, saved: bool) -> BenchmarkSet:
    """The one set core, in `contracts/cases.md` 4.3's order: row 1, the file through the
    strict models and, for a set file (never a saved copy), its `case_file_sha256`; row 2;
    row 3 for a set file; every entry resolved against `root`, its package path through the
    answer-key guard (row 4); then rows 5, 6 and 7 over the resolved entries."""
    set_path = Path(path).resolve()
    checkout = root.resolve()
    written, entries = _written_set(set_path)
    if not saved:
        _refuse_a_case_file_digest(set_path, entries)
    _refuse_a_repeated_package_id(set_path, written.packages)
    if not saved:
        _refuse_relative_paths_outside_sets(set_path, checkout, entries)

    packages = [_package_ref(ref, checkout, saved=saved) for ref in written.packages]
    _refuse_withheld_files_overlapping_package_folders(set_path, packages)
    _refuse_a_keyed_set_s_entries_off_their_side(set_path, checkout, packages)
    _refuse_unknown_twins_and_represents(set_path, packages)
    return BenchmarkSet(name=written.name, packages=packages)


def _written_set(set_path: Path) -> tuple[BenchmarkSet, list[dict[str, Any]]]:
    """Row 1: the file as written, through the strict models, with its entries as raw JSON,
    whose paths row 3 reads as spelled.

    A file that is missing, cannot be read or is not UTF-8 is refused like one that is not
    JSON, as the key's and the case file's readers refuse theirs; an `OSError` is named by its
    `strerror`, or its type when it has none, never its text, which carries the absolute path
    the read was given. The models then refuse an unknown field, a missing required one and a
    wrong type, naming each (`findings.model_refusals`); their paths stay as written, since
    the JSON reading of a strict `Path` field takes a string.
    """
    try:
        text = set_path.read_text(encoding="utf-8")
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise _refused(set_path, f"cannot be read ({reason})") from None
    except UnicodeDecodeError as error:
        raise _refused(set_path, f"not UTF-8 ({error})") from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise _refused(set_path, f"not JSON ({error})") from None
    try:
        written = BenchmarkSet.model_validate_json(text)
    except ValidationError as error:
        raise _refused(set_path, model_refusals(error)) from None
    return written, payload["packages"]


def _package_ref(
    written: BenchmarkPackageRef, checkout: Path, *, saved: bool
) -> BenchmarkPackageRef:
    """One entry as written, resolved against `checkout`, every other field as given.

    Its package path passes the answer-key guard; its key and case file resolve by the same
    rule but never meet the guard, since a committed key lies in `benchmarks/answer_keys/`
    and a committed case file in `benchmarks/case_files/`, withheld from the reviewer and not
    from the set. The case file's digest is a saved copy's as saved, else computed from the
    file's bytes when it can be read; one that cannot be read keeps no digest, so
    `benchmark.runner.preflight_set` refuses it naming the file (`contracts/scripted-answers.md`
    2.3 row 1).
    """
    package_path = reject_answer_key_path(
        _named_path(written.path, checkout),
        "a benchmark set may not reference an answer key as a package",
    )
    case_file = _resolved(written.case_file, checkout)
    if saved:
        case_file_sha256 = written.case_file_sha256
    else:
        case_file_sha256 = _case_file_digest(case_file)
    return written.model_copy(
        update={
            "path": package_path,
            "key": _resolved(written.key, checkout),
            "case_file": case_file,
            "case_file_sha256": case_file_sha256,
        }
    )


def _named_path(named: Path, checkout: Path) -> Path:
    """A path an entry names: absolute as written, or relative against `checkout`."""
    return named if named.is_absolute() else checkout / named


def _resolved(named: Path | None, checkout: Path) -> Path | None:
    """A key or case file an entry names, resolved by `_named_path`'s rule, or `None`."""
    return None if named is None else _named_path(named, checkout).resolve()


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
    """Row 1's `case_file_sha256`, after the strict models (`_written_set`): the digest is
    computed at load and carried into the saved set, so a set file never holds one
    (`contracts/cases.md` 4.1)."""
    holding = next((entry for entry in entries if CASE_FILE_SHA256 in entry), None)
    if holding is not None:
        raise _refused(
            set_path,
            f"entry {holding['package_id']} holds {CASE_FILE_SHA256}, which a set file never "
            "holds: it is computed from the case file at load and carried into the saved set",
        )


def named_paths(entry: dict[str, Any]) -> list[str]:
    """The paths `entry`, a set file's or a saved copy's entry as written, names, in
    `SET_PATH_FIELDS` order: its package folder and, where it names them, its key and case
    file. Row 3 reads them here, and compare's ledger guard (`compare._names_an_absolute_path`)."""
    return [entry[field] for field in SET_PATH_FIELDS if entry.get(field) is not None]


def _refuse_a_repeated_package_id(set_path: Path, packages: list[BenchmarkPackageRef]) -> None:
    """Row 2: a package id names one entry, as it names one key, case file and run folder
    (`contracts/cases.md` 2 and 4.3)."""
    seen: set[str] = set()
    for ref in packages:
        if ref.package_id in seen:
            raise _refused(set_path, f"package_id {ref.package_id} is named twice")
        seen.add(ref.package_id)


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
            for named in named_paths(entry)
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


def _withheld_files(ref: BenchmarkPackageRef) -> list[tuple[str, Path]]:
    """The files `ref` names that the reviewer never reads, each with the word a refusal
    names it by: its key, then its case file, where it names them (rows 5 and 6)."""
    named = [("key", ref.key), ("case file", ref.case_file)]
    return [(kind, path) for kind, path in named if path is not None]


def _refuse_withheld_files_overlapping_package_folders(
    set_path: Path, packages: list[BenchmarkPackageRef]
) -> None:
    """Row 5 (`contracts/cases.md` 4.3; `contracts/scripted-answers.md` 2.1 and 6; plan
    decision CS-15): each key and case file the set names, and the folder it lies in, are
    withheld paths, so a package folder that is, or lies under, that folder is refused, and
    so is a key or case file lying inside any entry's package folder, each naming both paths.
    Every withheld file against every entry's package folder, its own entry's included, so a
    private key or case file can neither sit in nor contain a folder the reviewer loads
    (US4-9, US5-11).
    """
    for holder in packages:
        for kind, withheld in _withheld_files(holder):
            for ref in packages:
                if ref.path.is_relative_to(withheld.parent):
                    raise _refused(
                        set_path,
                        f"entry {ref.package_id}'s package folder {ref.path} is or lies under "
                        f"the folder of entry {holder.package_id}'s {kind} {withheld}: "
                        f"{WITHHELD_FROM_THE_PACKAGE}",
                    )
                if withheld.is_relative_to(ref.path):
                    raise _refused(
                        set_path,
                        f"entry {holder.package_id}'s {kind} {withheld} lies inside "
                        f"entry {ref.package_id}'s package folder {ref.path}: "
                        f"{WITHHELD_FROM_THE_PACKAGE}",
                    )


def _refuse_a_keyed_set_s_entries_off_their_side(
    set_path: Path, checkout: Path, packages: list[BenchmarkPackageRef]
) -> None:
    """Row 6, in a keyed set only (`contracts/cases.md` 4.1 and 4.3; plan decision RF-4):
    every entry names its key, and an entry's key and case file lie on its package's side
    of the root, inside it for a committed entry and outside it for a private one (4.2), so
    no committed case leans on a private file and no private key enters the repository
    (FR-051). A keyless set, every set written before feature 014, reads its keys from
    `--answer-keys` and is not checked here.
    """
    if all(ref.key is None for ref in packages):
        return
    for ref in packages:
        if ref.key is None:
            raise _refused(
                set_path, f"entry {ref.package_id} names no key: {EVERY_ENTRY_NAMES_ITS_KEY}"
            )
        committed = checkout_relative(ref.path, root=checkout) is not None
        for kind, withheld in _withheld_files(ref):
            if (checkout_relative(withheld, root=checkout) is not None) == committed:
                continue
            package_side, file_side = ("inside", "outside") if committed else ("outside", "inside")
            raise _refused(
                set_path,
                f"entry {ref.package_id}'s package folder lies {package_side} the repository "
                f"and its {kind} {withheld} {file_side} it: {KEYS_ON_THEIR_SIDE}",
            )


def _refuse_unknown_twins_and_represents(
    set_path: Path, packages: list[BenchmarkPackageRef]
) -> None:
    """Row 7 (`contracts/cases.md` 4.1 and 4.3; FR-028, FR-029): a `twin_of` names another
    entry of the same set, never its own; each `represents` value is an anchor R-1 to R-8 or
    an analyst-found defect AF-1 to AF-3, the ids `families.ANCHOR_FAMILY` maps, spelled
    exactly, and named once. Read in keyed and keyless sets alike."""
    package_ids = {ref.package_id for ref in packages}
    for ref in packages:
        if ref.twin_of is not None and (
            ref.twin_of == ref.package_id or ref.twin_of not in package_ids
        ):
            raise _refused(
                set_path,
                f"entry {ref.package_id}'s twin_of {ref.twin_of} names no other entry of the set",
            )
        seen: set[str] = set()
        for value in ref.represents or []:
            if value not in ANCHOR_FAMILY:
                raise _refused(
                    set_path,
                    f"entry {ref.package_id} represents {value}, which is neither an anchor "
                    "R-1 to R-8 nor an analyst-found defect AF-1 to AF-3",
                )
            if value in seen:
                raise _refused(
                    set_path, f"entry {ref.package_id} represents {value} more than once"
                )
            seen.add(value)


def _sets_checkout(set_path: Path) -> Path | None:
    """The checkout whose `benchmarks/sets/` folder itself holds `set_path`, else `None`."""
    if len(set_path.parents) < 3:
        return None
    checkout = set_path.parents[2]
    return checkout if set_path.parent == checkout / "benchmarks" / "sets" else None


def _refused(set_path: Path, detail: str) -> SetError:
    """A `SetError` carrying the prefix every set refusal starts with."""
    return SetError(f"benchmark set {set_path.name}: {detail}")
