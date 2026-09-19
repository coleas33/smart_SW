"""Reading Typer's Rich-rendered console output in a test.

Typer renders `--help` and usage errors through Rich. Under a colour-forcing terminal, which
CI sets and a developer's shell usually does not, Rich wraps each dash of an option name in
its own escape sequence and may break a long name across a box's lines, so `--package` is
never a contiguous substring of the raw output and a test that passed locally fails on
every CI leg. Strip the codes before asserting on the words; join the lines when the name
may have wrapped.
"""

from __future__ import annotations

import re

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def plain(text: str) -> str:
    """`text` with every ANSI escape sequence removed."""
    return ANSI_ESCAPE.sub("", text)


def plain_one_line(text: str) -> str:
    """`plain(text)` with its line breaks removed, for a word Rich may have wrapped."""
    return plain(text).replace("\n", "")
