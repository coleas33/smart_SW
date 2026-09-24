"""No tracked file carries a recorded design number or a forbidden identifier (the owner's
decisions 11B and 13A of 2026-09-24).

The repository is public. While the replay was built, the numbers of the designs the pilot
recorded - the big assembly, the small assembly, and parts inside them - were written into
documents, specs, tests and comments; decision 11B took them out of the tree (git history keeps
the older mentions), and this test keeps them out. It reads the owner's denylist
(`scramble.denylist_path`, outside the repository; feature 008's replay-fixture generator
writes it from the tokens it replaced) and fails if any of its tokens with five digits or more
is a whole token (`scramble.tokens_of`, the split every leak check uses) of any file
`git ls-files` lists. So a number is caught however its groups are joined - a hyphen, a space,
an underscore, a dot - and inside a folder or file name; written with no separator it is one
longer token, which the owner's denylist lists too for the two assemblies' numbers. A digit run
inside a longer one, such as a float's tail, is not the number and is not matched.

Decision 13A extends 11B to every design: no company part number and no product or assembly
folder name of any design stays in the tree. The fixture denylist holds only what the replay's
recordings carried, so the owner keeps a second list beside it, outside the repository:
`%LOCALAPPDATA%\\SwReview\\repo-identifiers.txt` (`identifiers_path`), which no generator
writes. Its shape (`read_identifiers`): UTF-8, one identifier per line; blank lines, lines
starting with `#` and a byte-order mark are ignored. The second scan fails if any identifier
is in any tracked text file or in any tracked file's path. An identifier is matched as its
letter-and-digit runs in order, each a whole token, joined by nothing or by up to
`MAX_SEPARATOR` characters that are neither, ignoring case (`identifier_pattern`): `999-13579`
is caught as `999_13579`, `999 13579`, `99913579` or inside a run folder's name, and a name
listed as its words (`Osprey Harness Tray`) is caught spaced, joined or cased any way.

A binary file (a NUL byte, and no UTF-16 byte-order mark) is skipped; any other file is read
as text, bytes that are not UTF-8 replaced, since the digits are ASCII in every encoding the
tree uses. A binary file's path is still scanned for identifiers. Where the denylist or the
identifier list is absent, which is CI, its scan skips saying why: neither can be listed here,
since this file is tracked too. A failure names each file and line - a path holding an
identifier with each identifier masked as `MASK` - never the token or the identifier: both are
recorded strings, and a failure message can end up in a public log
(`tests/support/fixture_denylist.py` keeps the same rule).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Iterator, Set
from pathlib import Path

import pytest

from tests.support.scramble import denylist_path, read_denylist, tokens_of

REPO = Path(__file__).resolve().parents[3]
MIN_DIGITS = 5
"""A denylist token with at least this many digits is a number that identifies a design;
shorter digit runs are counts and sizes that appear legitimately everywhere."""
UTF16_MARKS = (b"\xff\xfe", b"\xfe\xff")
IDENTIFIERS_FILE = "repo-identifiers.txt"
"""The owner's list of forbidden identifiers (decision 13A), beside `fixture-denylist.txt`."""
MAX_SEPARATOR = 3
"""An identifier's groups may be joined by up to this many characters that are neither letters
nor digits: a hyphen, an underscore, a space, a dot, ` - `, a Markdown-escaped `\\-`, or a
hyphen and a line break."""
MASK = "…"
"""What stands for an identifier in a reported path, as the docs name a run folder."""


def require_checkout() -> None:
    """Skip, saying why, where the repository is not a git checkout."""
    if not (REPO / ".git").exists():
        pytest.skip(f"{REPO} is not a git checkout, so there is no list of tracked files")


def long_numbers(tokens: Iterable[str]) -> set[str]:
    """The tokens with `MIN_DIGITS` digits or more."""
    return {token for token in tokens if sum(char.isdigit() for char in token) >= MIN_DIGITS}


def tracked_files(repo: Path = REPO) -> list[Path]:
    """Every file `git ls-files` lists that is in the working tree."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [repo / name for name in listed.split("\0") if name and (repo / name).is_file()]


def text_of(path: Path) -> str | None:
    """The file as text, or `None` for a binary."""
    content = path.read_bytes()
    if content.startswith(UTF16_MARKS):
        return content.decode("utf-16", errors="replace")
    if b"\0" in content:
        return None
    return content.decode("utf-8", errors="replace")


def tracked_texts(repo: Path = REPO) -> Iterator[tuple[str, str | None]]:
    """Each tracked file's `/`-separated path under `repo`, with its text (`None`: a binary)."""
    for path in tracked_files(repo):
        yield path.relative_to(repo).as_posix(), text_of(path)


def offending_lines(text: str, numbers: Set[str]) -> list[int]:
    """The 1-based numbers of the lines of `text` holding one of `numbers` as a whole token."""
    if numbers.isdisjoint(tokens_of(text)):
        return []
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if not numbers.isdisjoint(tokens_of(line))
    ]


def identifiers_path() -> Path:
    """The owner's forbidden identifiers: `%LOCALAPPDATA%\\SwReview\\repo-identifiers.txt`."""
    return denylist_path().with_name(IDENTIFIERS_FILE)


def read_identifiers(path: Path) -> list[str]:
    """The identifiers `path` lists, one per line, trimmed; blank lines and `#` lines skipped."""
    lines = (line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def identifier_pattern(identifiers: Iterable[str]) -> re.Pattern[str]:
    """One pattern matching any of `identifiers`, in any separator form and any case.

    An empty list, or an identifier with no letter or digit, would match everywhere, so either
    is refused - an identifier by its position in the list, never by its text.
    """
    separator = f"[^A-Za-z0-9]{{0,{MAX_SEPARATOR}}}"
    alternatives: list[str] = []
    for position, identifier in enumerate(identifiers, start=1):
        groups = tokens_of(identifier)
        if not groups:
            raise ValueError(f"identifier {position} has no letter or digit")
        alternatives.append(separator.join(re.escape(group) for group in groups))
    if not alternatives:
        raise ValueError("there is no identifier to match")
    return re.compile(
        rf"(?<![A-Za-z0-9])(?:{'|'.join(alternatives)})(?![A-Za-z0-9])", re.IGNORECASE
    )


def lines_matching(text: str, pattern: re.Pattern[str]) -> list[int]:
    """The 1-based numbers of the lines of `text` on which a match of `pattern` starts."""
    lines: list[int] = []
    line, position = 1, 0
    for match in pattern.finditer(text):
        line += text.count("\n", position, match.start())
        position = match.start()
        if not lines or lines[-1] != line:
            lines.append(line)
    return lines


def identifier_offenders(
    files: Iterable[tuple[str, str | None]], pattern: re.Pattern[str]
) -> list[str]:
    """`path (path)` for each path holding an identifier and `path:line` for each line holding
    one, every identifier in a reported path masked as `MASK`, so no report names one."""
    offenders: list[str] = []
    for name, text in files:
        where = pattern.sub(MASK, name)
        if where != name:
            offenders.append(f"{where} (path)")
        if text is not None:
            offenders += [f"{where}:{line}" for line in lines_matching(text, pattern)]
    return offenders


def test_no_tracked_file_carries_a_number_of_the_owners_denylist() -> None:
    path = denylist_path()
    if not path.is_file():
        pytest.skip(f"the owner's denylist is not on this machine: {path}")
    require_checkout()
    tokens, _ = read_denylist(path)
    numbers = long_numbers(tokens)
    assert numbers, "the owner's denylist holds no number; regenerate the replay fixtures"

    offenders: list[str] = []
    for where, text in tracked_texts():
        if text is not None:
            offenders += [f"{where}:{line}" for line in offending_lines(text, numbers)]

    assert offenders == [], (
        f"{len(offenders)} lines carry a recorded design number (decision 11B); name the "
        "design in words instead (the big assembly, the small assembly): " + ", ".join(offenders)
    )


def test_no_tracked_file_or_path_carries_an_identifier_of_the_owners_list() -> None:
    path = identifiers_path()
    if not path.is_file():
        pytest.skip(f"the owner's list of forbidden identifiers is not on this machine: {path}")
    require_checkout()
    identifiers = read_identifiers(path)
    assert identifiers, f"{path} lists no identifier; list one per line (decision 13A)"

    offenders = identifier_offenders(tracked_texts(), identifier_pattern(identifiers))

    assert offenders == [], (
        f"{len(offenders)} places carry an identifier of the owner's list (decision 13A); name "
        "the design in words instead (a pin part, an earlier assembly review), or use a "
        "FICT- value in a test: " + ", ".join(offenders)
    )


# --- the scans' own parts, which run everywhere ------------------------------------------------

FICTIONAL = frozenset({"13579", "99913579"})
"""A fictional number in both spellings, as the denylist holds a recorded one."""

FICTIONAL_IDENTIFIERS = ["999-13579", "Osprey Harness Tray"]
"""A fictional number and a fictional folder name, as the owner's list holds recorded ones."""


def test_only_tokens_with_five_digits_or_more_are_numbers() -> None:
    assert long_numbers({"1234", "12345", "AB1234C5", "M8", "word", "123456789"}) == {
        "12345",
        "AB1234C5",
        "123456789",
    }


@pytest.mark.parametrize(
    "line",
    [
        "the 999-13579 assembly",
        "999_13579",
        "999 13579",
        "999.13579",
        "C:\\runs\\20990101-000000-999-13579-check\\report.md",
        "13579.SLDASM",
        "99913579",
    ],
)
def test_a_number_is_caught_however_its_groups_are_joined(line: str) -> None:
    assert offending_lines(f"first line\n{line}\nlast line", FICTIONAL) == [2]


@pytest.mark.parametrize(
    "line",
    ["-0.00135799999999999997", "1135790", "a13579b", "1357", "no number here"],
)
def test_a_digit_run_inside_a_longer_token_is_not_the_number(line: str) -> None:
    assert offending_lines(line, FICTIONAL) == []


def test_every_line_holding_a_number_is_named() -> None:
    assert offending_lines("13579\nclean\n999-13579\n", FICTIONAL) == [1, 3]


def test_a_binary_is_skipped_and_every_text_encoding_is_read(tmp_path: Path) -> None:
    binary = tmp_path / "image.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\0\0 13579")
    utf16 = tmp_path / "script.ps1"
    utf16.write_bytes("# 999-13579\r\n".encode("utf-16"))
    latin1 = tmp_path / "notes.txt"
    latin1.write_bytes("caf\xe9 999-13579\n".encode("latin-1"))

    assert text_of(binary) is None
    assert offending_lines(text_of(utf16) or "", FICTIONAL) == [1]
    assert offending_lines(text_of(latin1) or "", FICTIONAL) == [1]


def test_the_tracked_files_are_in_the_tree_and_include_the_readme_and_the_project() -> None:
    require_checkout()

    files = {path.resolve() for path in tracked_files()}

    assert (REPO / "README.md").resolve() in files
    assert (REPO / "reviewer" / "pyproject.toml").resolve() in files
    assert all(path.is_file() for path in files)


def test_the_tracked_texts_name_each_file_by_its_path_under_the_repository() -> None:
    require_checkout()

    texts = dict(tracked_texts())

    assert "reviewer/pyproject.toml" in texts
    assert "[tool.ruff]" in (texts["reviewer/pyproject.toml"] or "")


def test_the_identifier_list_sits_beside_the_fixture_denylist() -> None:
    assert identifiers_path() == denylist_path().parent / "repo-identifiers.txt"


def test_the_identifier_list_skips_blank_lines_comments_and_a_byte_order_mark(
    tmp_path: Path,
) -> None:
    listed = tmp_path / IDENTIFIERS_FILE
    content = "\ufeff999-13579\n\n# a comment, not an identifier\n  Osprey Harness Tray  \r\n   \n"
    listed.write_bytes(content.encode("utf-8"))

    assert read_identifiers(listed) == FICTIONAL_IDENTIFIERS


@pytest.mark.parametrize(
    "line",
    [
        "the 999-13579 assembly",
        "999_13579",
        "999 13579",
        "999.13579",
        "99913579",
        "999 - 13579",
        "999\\-13579",
        "999--13579",
        "999-13579-2",
        "999-13579.SLDDRW",
        "C:\\runs\\20990101-000000-999-13579-check\\report.md",
        "C:\\vault\\Osprey Harness Tray\\FICT-0001.SLDASM",
        "C:\\vault\\OspreyHarnessTray\\FICT-0001.SLDASM",
        "osprey_harness_tray",
        "OSPREY-HARNESS-TRAY",
    ],
)
def test_an_identifier_is_caught_in_any_separator_form_and_any_case(line: str) -> None:
    pattern = identifier_pattern(FICTIONAL_IDENTIFIERS)

    assert lines_matching(f"first line\n{line}\nlast line", pattern) == [2]


@pytest.mark.parametrize(
    "line",
    [
        "1999-13579",
        "999-135790",
        "a999-13579",
        "999x13579",
        "999 ,  13579",
        "13579",
        "Osprey Harness",
        "OspreyHarnessTrays",
        "no identifier here",
    ],
)
def test_an_identifier_is_only_caught_as_whole_tokens_close_together(line: str) -> None:
    assert lines_matching(line, identifier_pattern(FICTIONAL_IDENTIFIERS)) == []


def test_an_identifier_broken_across_a_line_is_caught_on_the_line_it_starts() -> None:
    pattern = identifier_pattern(FICTIONAL_IDENTIFIERS)

    assert lines_matching("clean\nthe part 999-\n13579 again\n", pattern) == [2]
    assert lines_matching("clean\r\nthe part 999-\r\n13579 again\r\n", pattern) == [2]


def test_every_line_holding_an_identifier_is_named_once() -> None:
    pattern = identifier_pattern(FICTIONAL_IDENTIFIERS)

    text = "999-13579 and 99913579\nclean\nOspreyHarnessTray\n\n999_13579"

    assert lines_matching(text, pattern) == [1, 3, 5]


def test_an_identifier_with_no_letter_or_digit_is_refused_by_its_position() -> None:
    with pytest.raises(ValueError, match="^identifier 2 has no letter or digit$"):
        identifier_pattern(["999-13579", "---"])


def test_an_empty_identifier_list_is_refused_rather_than_matching_everything() -> None:
    with pytest.raises(ValueError, match="no identifier"):
        identifier_pattern([])


def test_a_report_names_the_file_line_and_path_but_never_the_identifier() -> None:
    files = [
        ("docs/runs/20990101-000000-999-13579/report.md", "clean\nsee 999-13579\n"),
        ("images/OspreyHarnessTray.png", None),
        ("docs/clean.md", "nothing here\n"),
        ("docs/notes.md", "one\ntwo\nC:\\vault\\Osprey Harness Tray\\FICT-0001.SLDASM\n"),
    ]

    offenders = identifier_offenders(files, identifier_pattern(FICTIONAL_IDENTIFIERS))

    assert offenders == [
        f"docs/runs/20990101-000000-{MASK}/report.md (path)",
        f"docs/runs/20990101-000000-{MASK}/report.md:2",
        f"images/{MASK}.png (path)",
        "docs/notes.md:3",
    ]
    report = " ".join(offenders).lower()
    assert "13579" not in report
    assert "osprey" not in report
