"""The owner's fixture denylist: tokens no committed fixture may contain (feature 010 T005).

`%LOCALAPPDATA%\\SwReview\\fixture-denylist.txt` lives outside the repository, one token per
line. Feature 008's replay-fixture generator refreshes it from the strings it scrambled out
of the recorded packages (008 T018); feature 010's fictional-fixture test reads the same file
(`test_mechanical_fixtures_are_fictional.py`). One reader for the one file, so the two
features cannot come to disagree about what the file says.

The tokens are never returned in a message a test prints: a denylisted token is a recorded
string, and a failure message can end up in a public log.
"""

from __future__ import annotations

import json
import os
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

__all__ = [
    "DENYLIST_PATH",
    "MIN_TOKEN_LENGTH",
    "glb_json",
    "json_strings",
    "load_denylist",
    "offending_tokens",
]

DENYLIST_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "SwReview" / "fixture-denylist.txt"
"""Where the owner keeps the file; absent on every machine but the owner's."""

MIN_TOKEN_LENGTH = 3
"""Shorter tokens are ignored: two characters match everywhere and prove nothing."""


def load_denylist(path: Path = DENYLIST_PATH) -> frozenset[str] | None:
    """The denylisted tokens, lower-cased, or `None` when the file is not on this machine.

    Blank lines, lines starting with `#` and tokens shorter than `MIN_TOKEN_LENGTH` are
    dropped. A file that exists but holds no token is an empty set, not `None`: the scan
    then runs and trivially passes, which is what an empty list means.
    """
    if not path.is_file():
        return None
    tokens = {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return frozenset(token for token in tokens if len(token) >= MIN_TOKEN_LENGTH)


def offending_tokens(text: str, denylist: frozenset[str]) -> set[str]:
    """The denylisted tokens that occur in `text`, as case-insensitive substrings."""
    folded = text.lower()
    return {token for token in denylist if token in folded}


def json_strings(data: Any) -> Iterator[str]:
    """Every string *value* in a parsed JSON document, depth first; keys are the schema's."""
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for value in data.values():
            yield from json_strings(value)
    elif isinstance(data, list):
        for item in data:
            yield from json_strings(item)


def glb_json(path: Path) -> dict[str, Any]:
    """The JSON chunk of a glTF 2.0 binary file: a 12-byte header, then (length, type, data).

    The binary chunk after it is float32 vertex data, where no string can live and three
    bytes spell some three-letter token by chance every few hundred kilobytes.
    """
    content = path.read_bytes()
    length, kind = struct.unpack_from("<I4s", content, 12)
    if kind != b"JSON":
        raise ValueError(f"{path.name} does not start with a JSON chunk")
    return json.loads(content[20 : 20 + length])
