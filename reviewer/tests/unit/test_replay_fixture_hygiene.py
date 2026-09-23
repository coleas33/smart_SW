"""The committed replay fixtures carry nothing real (008 T017, research R2.11).

The three fixtures under `tests/fixtures/replay/` are generated from recorded runs whose
packages named real documents, vault folders, people and part numbers. The generator scrambles
every identifying string and refuses to write a fixture in which one survives; this test is the
second lock, and the one that runs everywhere:

- every document path and vault path sits under the fictional root `C:\\FictionalVault\\`;
- no string anywhere is a drive-letter path outside that root, an email address, an http(s)
  URL, or carries a copyright sign;
- none of the recorded design ids appears;
- none of the words that would rebuild a vault layout or a supplier's naming
  (`FORBIDDEN_WORDS`) appears: in a path-valued field compared whole-word and case-insensitive,
  anywhere else whole-word as written (the lower-case checklist id `fasteners` is generic, and
  the reviewer's own sentences, `scramble.REVIEWER_OWN_TEXT`, are taken out first);
- no custom or configuration property key or value keeps a readable word: every word of three
  letters or more is either one `config/standards.example.yaml` names (it is public, and the
  profile the fixtures are graded with must find its properties) or not generic vocabulary
  (`scramble.is_allowed_token`), so a company's property names, workflow states and
  export-control wording cannot survive. Numbers, dates, sizes and the head of a SOLIDWORKS
  link (`SW-Mass@`) are not words here (`scramble.strict_property_words`);
- where the owner keeps a denylist outside the repository
  (`%LOCALAPPDATA%\\SwReview\\fixture-denylist.txt`, written by the generator), none of its
  token lines appears as a whole token, and no folder between the fictional root and the file
  name equals, case-insensitively, a folder name the recorded packages carried. Where the file
  is absent those two parts are skipped, saying why.

The checks that read strings - drive paths, email, URL and copyright, the design ids, the
forbidden words and the owner's denylist - also run over the Review tab's pane fixture
(`extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json`, feature 009 T023). It is
derived from big-assembly by its own generator, carries the display titles a person reads, and
is just as public, so a later change that let text from anywhere else into it would be caught
here rather than only if it also reached a replay fixture. The checks of a package's shape - its
document paths and its property words - stay with the replay fixtures: the pane fixture holds no
package.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.support.mechanical import load_generator
from tests.support.scramble import (
    FICTIONAL_ROOT,
    denylist_path,
    folders_of,
    is_allowed_token,
    letters,
    path_values,
    profile_words,
    property_strings,
    read_denylist,
    strict_property_words,
    strings_of,
    tokens_of,
    without_reviewer_text,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay"
EXAMPLE_PROFILE = Path(__file__).resolve().parents[3] / "config" / "standards.example.yaml"
NAMES = ("big-assembly", "small-assembly-a", "small-assembly-b")
FILES = ("package.json", "session.json", "events.jsonl")
PANE = "pane"
"""The pane fixture's label among the committed fixtures the string checks read."""
PANE_GENERATOR = FIXTURES.parent / "pane" / "generate_pane_fixture.py"
RECORDED_DESIGN_IDS = ("830-02342", "810-11249", "810-11281")
FORBIDDEN_WORDS = (
    "_LIBRARY",
    "LIBRARY",
    "DESIGNED PARTS",
    "NOT LIBRARY",
    "FASTENERS",
    "SHCS",
    "BHCS",
    "FHCS",
    "MMC",
)
"""Folder and supplier words the owner's review found reconstructing the vault layout."""

DRIVE_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
URL = re.compile(r"https?://", re.IGNORECASE)


def whole_word(word: str, *, ignore_case: bool) -> re.Pattern[str]:
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", flags)


IN_PATHS = [whole_word(word, ignore_case=True) for word in FORBIDDEN_WORDS]
ELSEWHERE = [whole_word(word, ignore_case=False) for word in FORBIDDEN_WORDS]


def committed_files(name: str) -> tuple[Path, ...]:
    """The files one committed fixture is: a replay folder's three, or the pane fixture - where
    its generator writes it (`TARGET`), so the path is not spelled a second time here."""
    if name == PANE:
        return (Path(load_generator(PANE_GENERATOR).TARGET),)
    return tuple(FIXTURES / name / file for file in FILES)


def documents(files: Sequence[Path]) -> Iterator[tuple[str, Any]]:
    """`(file name, parsed JSON)` for every JSON document of `files`, one per event line."""
    for path in files:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            for number, line in enumerate(text.splitlines(), start=1):
                if line.strip():
                    yield f"{path.name}:{number}", json.loads(line)
        else:
            yield path.name, json.loads(text)


def under_root(path: str) -> str:
    """A path without the fictional root, which is the one folder allowed to be generic."""
    return path[len(FICTIONAL_ROOT) :] if path.startswith(FICTIONAL_ROOT) else path


@pytest.fixture(params=NAMES)
def fixture(request: pytest.FixtureRequest) -> Path:
    return FIXTURES / request.param


@pytest.fixture(params=(*NAMES, PANE))
def files(request: pytest.FixtureRequest) -> tuple[Path, ...]:
    """Every committed fixture the string checks read: the three replay folders and the pane."""
    found = committed_files(request.param)
    missing = [path for path in found if not path.is_file()]
    assert missing == [], f"{missing} missing; regenerate the fixture"
    return found


def test_the_pane_fixture_is_among_the_files_the_string_checks_read() -> None:
    """The pane fixture's parametrization reads the file the C# tests load, not an empty set."""
    [pane] = committed_files(PANE)

    assert pane.parts[-3:] == ("SwReview.AddIn.Tests", "Fixtures", "review-big-assembly.json")
    assert [name for name, _ in documents((pane,))] == [pane.name]


def test_each_fixture_holds_a_package_a_session_and_an_event_log(fixture: Path) -> None:
    assert fixture.is_dir(), f"{fixture} is missing; run generate_fixtures.py (T018)"
    for name in FILES:
        assert (fixture / name).is_file(), f"{fixture / name} is missing"


def test_every_document_and_vault_path_is_under_the_fictional_root(fixture: Path) -> None:
    package = json.loads((fixture / "package.json").read_text(encoding="utf-8"))
    paths = [document["path"] for document in package["documents"]]
    paths += [entry["vault_path"] for entry in package["manifest"]["entries"]]

    assert paths, "a package with no document is not shaped like a recording"
    assert [path for path in paths if not path.startswith(FICTIONAL_ROOT)] == []


def test_no_string_is_a_drive_path_outside_the_root_an_email_a_url_or_a_copyright(
    files: tuple[Path, ...],
) -> None:
    offenders: list[str] = []
    for where, document in documents(files):
        for text in strings_of(document):
            for match in DRIVE_PATH.finditer(text):
                if not text.startswith(FICTIONAL_ROOT, match.start()):
                    offenders.append(f"{where}: drive path {text[match.start() :][:60]!r}")
            if EMAIL.search(text):
                offenders.append(f"{where}: email {EMAIL.search(text).group(0)!r}")  # type: ignore[union-attr]
            if URL.search(text):
                offenders.append(f"{where}: url in {text[:60]!r}")
            if "\u00a9" in text:
                offenders.append(f"{where}: copyright sign in {text[:60]!r}")

    assert offenders == []


def test_no_recorded_design_id_appears(files: tuple[Path, ...]) -> None:
    for path in files:
        text = path.read_text(encoding="utf-8")
        for design_id in RECORDED_DESIGN_IDS:
            assert design_id not in text, f"{path.parent.name}/{path.name} carries {design_id}"


def test_the_package_has_path_values_to_check(fixture: Path) -> None:
    """The path checks below read `path_values`; a package it finds nothing in proves nothing."""
    package = json.loads((fixture / "package.json").read_text(encoding="utf-8"))

    values = list(path_values(package))

    assert sum(1 for value in values if value.startswith(FICTIONAL_ROOT)) >= len(
        package["documents"]
    )


def test_no_forbidden_word_is_in_a_path_value_in_any_case(files: tuple[Path, ...]) -> None:
    offenders = [
        f"{where}: {pattern.pattern} in {value!r}"
        for where, document in documents(files)
        for value in path_values(document)
        for pattern in IN_PATHS
        if pattern.search(under_root(value))
    ]

    assert offenders == []


def test_no_forbidden_word_is_anywhere_else_as_written(files: tuple[Path, ...]) -> None:
    offenders = [
        f"{where}: {pattern.pattern} in {text[:80]!r}"
        for where, document in documents(files)
        for text in strings_of(document)
        for pattern in ELSEWHERE
        if pattern.search(without_reviewer_text(text))
    ]

    assert offenders == []


def test_the_package_has_property_keys_and_values_to_check(fixture: Path) -> None:
    """The property check below reads `property_strings`; a package it finds none in proves
    nothing."""
    package = json.loads((fixture / "package.json").read_text(encoding="utf-8"))

    assert any(letters(word) >= 3 for text in property_strings(package) for word in tokens_of(text))


def test_no_property_key_or_value_keeps_a_readable_word(fixture: Path) -> None:
    package = json.loads((fixture / "package.json").read_text(encoding="utf-8"))
    public = profile_words(EXAMPLE_PROFILE)

    offenders = sorted(
        {
            f"{word!r} in {text!r}"
            for text in property_strings(package)
            for word in strict_property_words(text, public)
            if letters(word) >= 3 and is_allowed_token(word)
        }
    )

    assert offenders == []


def owners_denylist() -> tuple[set[str], set[str]]:
    path = denylist_path()
    if not path.is_file():
        pytest.skip("the owner's denylist is not on this machine")
    return read_denylist(path)


def test_no_token_of_the_owners_denylist_appears(files: tuple[Path, ...]) -> None:
    tokens, _ = owners_denylist()

    offenders: list[str] = []
    for path in files:
        text = without_reviewer_text(path.read_text(encoding="utf-8"))
        offenders += [
            f"{path.name}: token {token!r}"
            for token in sorted(tokens.intersection(tokens_of(text)))
        ]

    assert offenders == []


def test_no_folder_is_named_like_a_folder_of_the_recorded_packages(
    files: tuple[Path, ...],
) -> None:
    _, folders = owners_denylist()
    recorded = {folder.casefold() for folder in folders}
    assert recorded, "the owner's denylist names no recorded folder; regenerate the fixtures"

    offenders = [
        f"{where}: folder {segment!r} of {value!r}"
        for where, document in documents(files)
        for value in path_values(document)
        if value.startswith(FICTIONAL_ROOT)
        for segment in folders_of(value)[1:]
        if segment.casefold() in recorded
    ]

    assert offenders == []
