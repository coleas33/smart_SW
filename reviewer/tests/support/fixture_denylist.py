"""The owner's fixture denylist: tokens no committed fixture may contain (feature 010 T005).

`%LOCALAPPDATA%\\SwReview\\fixture-denylist.txt` lives outside the repository. Feature 008's
replay-fixture generator writes it (`scramble.write_denylist`: one token per line, then one
`folder: ` line per recorded folder) and its hygiene test reads it; feature 010's
fictional-fixture test (`test_mechanical_fixtures_are_fictional.py`) reads the same file
through the same `scramble.denylist_path` and `scramble.read_denylist`. One parser for the
one file, so the two features cannot come to disagree about what the file says - which is
T005's rule now that 008's reader is on main.

What this module adds is 010's reading of it: every token and every folder name, folded
and at least `MIN_TOKEN_LENGTH` long, matched as a substring of a name or as a whole word of
a sentence. The tokens are never returned in a message a test prints: a denylisted token is
a recorded string, and a failure message can end up in a public log.
"""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tests.support.scramble import denylist_path, read_denylist

__all__ = [
    "DENYLIST_PATH",
    "MIN_TOKEN_LENGTH",
    "glb_json",
    "json_strings",
    "load_denylist",
    "offending_tokens",
    "offending_words",
]

DENYLIST_PATH = denylist_path()
"""Where the owner keeps the file; absent on every machine but the owner's."""

MIN_TOKEN_LENGTH = 3
"""Shorter tokens are ignored: two characters match everywhere and prove nothing."""


def load_denylist(path: Path = DENYLIST_PATH) -> frozenset[str] | None:
    """Every token and recorded folder name, lower-cased, or `None` when the file is absent.

    Blank lines, lines starting with `#` and entries shorter than `MIN_TOKEN_LENGTH` are
    dropped, and a byte-order mark an editor saved is not part of the first token. A file
    that exists but holds nothing is an empty set, not `None`: the scan then runs and
    trivially passes, which is what an empty list means.
    """
    if not path.is_file():
        return None
    tokens, folders = read_denylist(path)
    entries = {entry.lstrip("\ufeff").strip().lower() for entry in tokens | folders}
    return frozenset(
        entry for entry in entries if len(entry) >= MIN_TOKEN_LENGTH and not entry.startswith("#")
    )


def offending_tokens(text: str, denylist: frozenset[str]) -> set[str]:
    """The denylisted tokens that occur in `text`, as case-insensitive substrings.

    For names and values, which are compounds: a recorded token inside one is a leak.
    """
    folded = text.lower()
    return {token for token in denylist if token in folded}


def offending_words(text: str, denylist: frozenset[str]) -> set[str]:
    """The denylisted tokens that occur in `text` as whole words, case-insensitively.

    For prose. A word boundary is anything that is not a letter or a digit - the split
    `scramble.tokens_of` uses - so `FICT_CARR-0001` holds `carr` and "carries" does not; a
    token of several words must appear with the same single spaces.
    """
    folded = text.lower()
    return {
        token
        for token in denylist
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", folded)
    }


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
