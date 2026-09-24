"""No tracked file carries a recorded design number (the owner's decision 11B of 2026-09-24).

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

A binary file (a NUL byte, and no UTF-16 byte-order mark) is skipped; any other file is read
as text, bytes that are not UTF-8 replaced, since the digits are ASCII in every encoding the
tree uses. Where the denylist is absent, which is CI, the scan skips saying why: the numbers
cannot be listed here, since this file is tracked too. A failure names each file and line,
never the token - a denylisted token is a recorded string, and a failure message can end up in
a public log (`tests/support/fixture_denylist.py` keeps the same rule).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Set
from pathlib import Path

import pytest

from tests.support.scramble import denylist_path, read_denylist, tokens_of

REPO = Path(__file__).resolve().parents[3]
MIN_DIGITS = 5
"""A denylist token with at least this many digits is a number that identifies a design;
shorter digit runs are counts and sizes that appear legitimately everywhere."""
UTF16_MARKS = (b"\xff\xfe", b"\xfe\xff")


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


def offending_lines(text: str, numbers: Set[str]) -> list[int]:
    """The 1-based numbers of the lines of `text` holding one of `numbers` as a whole token."""
    if numbers.isdisjoint(tokens_of(text)):
        return []
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if not numbers.isdisjoint(tokens_of(line))
    ]


def test_no_tracked_file_carries_a_number_of_the_owners_denylist() -> None:
    path = denylist_path()
    if not path.is_file():
        pytest.skip(f"the owner's denylist is not on this machine: {path}")
    if not (REPO / ".git").exists():
        pytest.skip(f"{REPO} is not a git checkout, so there is no list of tracked files")
    tokens, _ = read_denylist(path)
    numbers = long_numbers(tokens)
    assert numbers, "the owner's denylist holds no number; regenerate the replay fixtures"

    offenders: list[str] = []
    for tracked in tracked_files():
        text = text_of(tracked)
        if text is not None:
            where = tracked.relative_to(REPO).as_posix()
            offenders += [f"{where}:{line}" for line in offending_lines(text, numbers)]

    assert offenders == [], (
        f"{len(offenders)} lines carry a recorded design number (decision 11B); name the "
        "design in words instead (the big assembly, the small assembly): " + ", ".join(offenders)
    )


# --- the scan's own parts, which run everywhere ------------------------------------------------

FICTIONAL = frozenset({"13579", "99913579"})
"""A fictional number in both spellings, as the denylist holds a recorded one."""


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
    if not (REPO / ".git").exists():
        pytest.skip(f"{REPO} is not a git checkout, so there is no list of tracked files")

    files = {path.resolve() for path in tracked_files()}

    assert (REPO / "README.md").resolve() in files
    assert (REPO / "reviewer" / "pyproject.toml").resolve() in files
    assert all(path.is_file() for path in files)
