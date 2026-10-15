"""The one committable-path scanner (feature 014 T056; `contracts/provenance.md` 6.6; PROV-14,
RF-6, RF-84; FR-051).

The repository is public, and a run folder under `benchmarks/studies/` or `benchmarks/pilots/`
may be committed whole. The harness keeps a local path out of what it writes; this is the
detector a test runs over what was written. It reads every file: a JSON file as its strings,
keys and values decoded, so no escaping hides a path; a JSON-lines file the same way, line by
line; and a file whose name ends `.gz` through `gzip.decompress`, then UTF-8, as the event
streams are committed packed (RF-84). It flags:

- **a local folder**: the running checkout, the home folder and the temporary folder, each as
  spelled and as it resolves, read once when this module is imported, so a test that points the
  commands at a temporary checkout or sets HOME elsewhere moves none of them. Compared
  case-insensitively, in either separator, a separator doubled or not; a mention is reported by
  the longest folder it lies under, so the checkout inside the home folder reads as the checkout;
- **a drive-letter or UNC path outside the fictional roots**, found through
  `scramble.WINDOWS_ANCHOR`, imported rather than restated (RF-6), and a drive letter followed by
  `/`, which that anchor does not read and the profiles' `vault_root`s are written with; and **a
  rooted path** outside them: a `/` at a token boundary (not after a word character, `:`, `/` or
  `.`) followed by a non-space, so `and/or`, `1/2` and a URL's `//` are not paths, nor an HTML end
  tag's `/` (`</td>`) or a self-closing tag's `/>`, since the report slice's pages may be
  committed. A UNC anchor and a drive letter with `/` start a path only at a token boundary too
  (not after a word character), so a separator doubled inside a path is no UNC path and a URL's
  scheme no drive; a drive letter with its backslash starts one wherever it stands, glued to a
  word character included (`...\\nE:\\...` in plain text quoting an escaped line). A path runs to
  the next space, quote, `<`, `>` or `|`, and lies under a fictional root only once its `..` are
  applied, so one that climbs out of a root is flagged;
- **a private entry**: a saved set (`benchmark-set.json`) naming a path outside the repository
  (`provenance.md` 6.1);
- **a file it cannot read**: not UTF-8, a packed stream that does not decompress, or a saved set
  that is not a set, since none of them can be shown to hold no local path.

Three entry points: `scan_file`, `scan_folder` (every file beneath it) and `scan_committable`
(section 6.6's reach in a checkout: every file under the two trees git does not ignore, and the
ledger block of `docs/llm-efficiency-options.md`). Each returns the offences in file order, an
empty list meaning nothing was found.
"""

from __future__ import annotations

import gzip
import json
import posixpath
import re
import tempfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from swreview.benchmark.compare import LEDGER_BEGIN, LEDGER_END
from swreview.benchmark.runner import EXAMPLE_PROFILE, SAVED_SET_FILE, _git
from swreview.benchmark.sets import REPO_ROOT
from swreview.checks.standards.profile import load_profile
from tests.checks.golden_standards import PROFILE_DIR
from tests.support import mechanical, scramble
from tests.support.scramble import WINDOWS_ANCHOR

__all__ = [
    "CHECKOUT_FOLDER",
    "DRIVE_PATH",
    "FICTIONAL_ROOTS",
    "HOME_FOLDER",
    "LEDGER_DOCUMENT",
    "PRIVATE_ENTRY",
    "ROOTED_PATH",
    "STUDY_TREES",
    "TEMPORARY_FOLDER",
    "UNC_PATH",
    "UNREADABLE",
    "Offence",
    "scan_committable",
    "scan_file",
    "scan_folder",
]

CHECKOUT_FOLDER = "names the checkout folder"
HOME_FOLDER = "names the home folder"
TEMPORARY_FOLDER = "names the temporary folder"
DRIVE_PATH = "a drive-letter path outside the fictional roots"
UNC_PATH = "a UNC path outside the fictional roots"
ROOTED_PATH = "a rooted path outside the fictional roots"
PRIVATE_ENTRY = "a saved set naming a path outside the repository: a private entry"
UNREADABLE = (
    "cannot be read, so cannot be scanned: not UTF-8 text, a packed stream that does not "
    "decompress, or a saved set that is not a set"
)

STUDY_TREES: tuple[Path, ...] = (Path("benchmarks") / "studies", Path("benchmarks") / "pilots")
"""The two trees whose run folders may be committed (`provenance.md` 6.6; plan decision RF-36)."""

LEDGER_DOCUMENT = Path("docs") / "llm-efficiency-options.md"
"""The committed ledger's document; only the block between `compare`'s markers is scanned."""

FICTIONAL_ROOTS: tuple[str, ...] = (
    mechanical.FICTIONAL_ROOT,
    scramble.FICTIONAL_ROOT,
    load_profile(REPO_ROOT / EXAMPLE_PROFILE).vault_root,
    load_profile(PROFILE_DIR / "profile-a.yaml").vault_root,
    load_profile(PROFILE_DIR / "profile-b.yaml").vault_root,
    # Written inline by `tests/support/features.py` (`_entry`) and `tests/support/packages.py`
    # (`build_manifest`).
    "/Designs/",
    # Written inline by `tests/golden/fixtures/bracket-assy-interference/package.json`.
    "/Library/",
)
"""The absolute roots the builders and the fictional profiles write paths under (research 8.8):
the two `FICTIONAL_ROOT`s imported and the three `vault_root`s read from their files, so none
can drift from its source."""


@dataclass(frozen=True)
class Offence:
    """One thing the scanner flags: the file, why, and the text as the file spells it."""

    file: Path
    reason: str
    text: str

    def __str__(self) -> str:
        return f"{self.file}: {self.reason}: {self.text}"


_SEPARATORS = re.compile(r"[\\/]+")
_AFTER_NAME = r"(?![\w-])"
"""What ends a folder's or a root's last name: anything but a word character or `-`, so
`C:\\Fictional\\` is not the root of `C:\\FictionalVault\\` and a folder is not its longer-named
neighbour's."""

_END_TAG = r"(?<=<)/[A-Za-z][\w-]*\s*>"
"""An HTML end tag from its `/` (`</td>`, `</TABLE>`, `</p >`), which starts no path: the report
slice's pages may be committed. A `/` after `<` that a path follows (`</srv/x>`) is no end tag."""

_PATH_START = re.compile(
    rf"(?<!\w)(?P<windows>{WINDOWS_ANCHOR.pattern})"
    # The anchor glued to a word character, kept only when it is a drive and its backslash: a
    # UNC anchor's two backslashes there are a separator doubled inside a path.
    rf"|(?P<glued>{WINDOWS_ANCHOR.pattern})(?<=:\\)"
    r"|(?<!\w)(?P<drive>[A-Za-z]:/)"
    rf"|(?<![\w:/.])(?!{_END_TAG})(?P<rooted>/)(?=[^\s>])"
)
_PATH_END = re.compile(r"[\s\"'`<>|]")
_TRAILING = ".,;:!?)]}"
"""Sentence punctuation after a path, which the path does not take."""


def _spelling(path: str) -> str:
    """A pattern for `path` in either separator, any separator after its leading ones doubled or
    not. Its leading separators are kept in number, so a rooted root never reads a UNC path's
    two."""
    leading = len(path) - len(path.lstrip("\\/"))
    names = _SEPARATORS.split(path.strip("\\/"))
    return r"[\\/]" * leading + r"[\\/]+".join(re.escape(name) for name in names)


def _local_folders() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Each local folder as spelled and as it resolves, with its reason, longest first; a tie
    goes to the checkout, then the temporary folder. A bare anchor (`/`, `C:\\`) would match
    every path, and is left to the anchor rules."""
    spelled: dict[str, str] = {}
    for reason, folder in (
        (CHECKOUT_FOLDER, REPO_ROOT),
        (TEMPORARY_FOLDER, Path(tempfile.gettempdir())),
        (HOME_FOLDER, Path.home()),
    ):
        for form in (folder, folder.resolve()):
            if form.parent != form:
                spelled.setdefault(str(form), reason)
    longest_first = sorted(spelled.items(), key=lambda item: len(item[0]), reverse=True)
    return tuple(
        (reason, re.compile(r"(?<![\w.])" + _spelling(text) + _AFTER_NAME, re.IGNORECASE))
        for text, reason in longest_first
    )


_LOCAL_FOLDERS = _local_folders()
_FICTIONAL = tuple(
    re.compile(_spelling(root) + _AFTER_NAME, re.IGNORECASE) for root in FICTIONAL_ROOTS
)


def scan_file(path: Path) -> list[Offence]:
    """Every offence in the one file at `path`, in the file's order, a saved set's private
    entries last."""
    path = Path(path)
    name = path.name
    data = path.read_bytes()
    try:
        if name.endswith(".gz"):
            data = gzip.decompress(data)
            name = name.removesuffix(".gz")
        text = data.decode("utf-8")
    except (OSError, EOFError, zlib.error, UnicodeDecodeError):
        return [Offence(path, UNREADABLE, path.name)]
    offences = [
        offence for string in _strings(name, text) for offence in _text_offences(path, string)
    ]
    if path.name == SAVED_SET_FILE:
        offences += _private_entries(path, text)
    return offences


def scan_folder(folder: Path) -> list[Offence]:
    """Every offence in every file beneath `folder`, at any depth, in path order."""
    files = sorted(path for path in Path(folder).rglob("*") if path.is_file())
    return [offence for path in files for offence in scan_file(path)]


def scan_committable(root: Path = REPO_ROOT) -> list[Offence]:
    """Section 6.6's reach in the checkout at `root`: every file under `STUDY_TREES` git does
    not ignore, in path order, then the ledger block of `LEDGER_DOCUMENT` when it is there."""
    offences = [offence for path in _committable_files(root) for offence in scan_file(path)]
    document = root / LEDGER_DOCUMENT
    if document.is_file():
        offences += _text_offences(document, _ledger_block(document.read_text(encoding="utf-8")))
    return offences


def _committable_files(root: Path) -> list[Path]:
    """The files under `STUDY_TREES` git does not ignore: tracked ones, a rule notwithstanding,
    and untracked ones no rule ignores. Where git cannot answer, every file of the two trees,
    the side that refuses (`provenance.md` 6.4)."""
    trees = [tree.as_posix() for tree in STUDY_TREES]
    listed = _git(
        root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *trees
    )
    if listed is None:
        candidates = [path for tree in STUDY_TREES for path in (root / tree).rglob("*")]
    else:
        candidates = [root / name for name in listed.split("\0") if name]
    return sorted({path for path in candidates if path.is_file()})


def _ledger_block(document: str) -> str:
    """What sits between `compare`'s two markers, or the whole document when it holds no pair."""
    start = document.find(LEDGER_BEGIN)
    end = document.find(LEDGER_END)
    if start < 0 or end < start:
        return document
    return document[start + len(LEDGER_BEGIN) : end]


def _strings(name: str, text: str) -> Iterator[str]:
    """What is scanned of a file named `name` holding `text`: a JSON file's strings, a
    JSON-lines file's line by line, and the text itself where it, or a line, is not JSON."""
    if name.endswith(".json"):
        yield from _json_texts(text)
    elif name.endswith(".jsonl"):
        for line in text.splitlines():
            yield from _json_texts(line)
    else:
        yield text


def _json_texts(text: str) -> Iterator[str]:
    try:
        node = json.loads(text)
    except ValueError:
        yield text
        return
    yield from _json_strings(node)


def _json_strings(node: Any) -> Iterator[str]:
    """Every key and every string value of a parsed JSON node."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _json_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _json_strings(item)
    elif isinstance(node, str):
        yield node


def _text_offences(file: Path, text: str) -> list[Offence]:
    """The local folders `text` names, longest first, then each path start outside those
    mentions that lies under no fictional root; one offence per mention, in the text's order."""
    spans: list[tuple[int, int, str]] = []
    for reason, folder in _LOCAL_FOLDERS:
        for match in folder.finditer(text):
            end = _path_end(text, match.end())
            if not _overlaps(spans, match.start(), end):
                spans.append((match.start(), end, reason))
    position = 0
    while (start := _PATH_START.search(text, position)) is not None:
        end = _path_end(text, start.end())
        if _anchor_reason(start) in (ROOTED_PATH, UNC_PATH) and text[: start.start()].endswith(
            ("<run>", "<repo>", "<tmp>", "<home>")
        ):
            position = start.end()
            continue
        if not _overlaps(spans, start.start(), end) and not _fictional(text[start.start() : end]):
            spans.append((start.start(), end, _anchor_reason(start)))
        position = end
    return [Offence(file, reason, text[begin:end]) for begin, end, reason in sorted(spans)]


def _path_end(text: str, position: int) -> int:
    """Where the path running through `position` ends: at the next space, quote, `<`, `>` or
    `|`, sentence punctuation after it left out."""
    found = _PATH_END.search(text, position)
    end = found.start() if found is not None else len(text)
    while end > position and text[end - 1] in _TRAILING:
        end -= 1
    return end


def _overlaps(spans: list[tuple[int, int, str]], begin: int, end: int) -> bool:
    return any(begin < other_end and other_begin < end for other_begin, other_end, _ in spans)


def _fictional(path: str) -> bool:
    """Whether `path` lies under a fictional root once its `..` are applied: one that starts at a
    root and climbs out of it lies under none."""
    applied = posixpath.normpath(path.replace("\\", "/"))
    return any(root.match(path) and root.match(applied) for root in _FICTIONAL)


def _anchor_reason(start: re.Match[str]) -> str:
    if start.lastgroup == "rooted":
        return ROOTED_PATH
    return UNC_PATH if start.group().startswith("\\") else DRIVE_PATH


def _private_entries(path: Path, text: str) -> list[Offence]:
    """A saved set's package entries naming a path outside the repository: any string value
    with a drive or a root, in either platform's spelling, or a relative one climbing out."""
    try:
        entries = [entry.values() for entry in json.loads(text)["packages"]]
    except (ValueError, KeyError, TypeError, AttributeError):
        return [Offence(path, UNREADABLE, path.name)]
    return [
        Offence(path, PRIVATE_ENTRY, value)
        for values in entries
        for value in values
        if isinstance(value, str) and _outside_repository(value)
    ]


def _outside_repository(value: str) -> bool:
    if PureWindowsPath(value).anchor:
        return True
    return posixpath.normpath(value.replace("\\", "/")).split("/")[0] == ".."
