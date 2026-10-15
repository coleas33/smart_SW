"""The two digests every benchmark record uses: a file's raw bytes, a parsed value's JSON.

`sha256_of` names a file as it lies on disk, byte for byte: nothing normalises line
endings, so the checkouts agree through `.gitattributes` `eol=lf` and never through the
digest, and a key's stamp of the checklist is the very number a run's `checklist_digest`
records (plan decision INT-3). `canonical_sha256` names a parsed value: sorted keys, no
whitespace, non-ASCII written as itself and hashed as UTF-8, so a record rewritten with
other line endings or another key order keeps its digest (plan decision RF-56).

The standard library only, so the key's stamp, the set and the generator import this
without loading the runner, the agent or each other (plan decision RF-48);
`swreview.benchmark.runner` re-exports `sha256_of` for the callers that predate the move.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_of_bytes(data: bytes) -> str:
    """The sha256 of raw bytes, shared by files and packed event streams."""
    return hashlib.sha256(data).hexdigest()


def sha256_of(path: Path | str) -> str:
    """The sha256 of a file's bytes, for the set-file and checklist digests."""
    return sha256_of_bytes(Path(path).read_bytes())


def canonical_sha256(value: object) -> str:
    """The sha256 of `value`'s canonical JSON: sorted keys, no whitespace, UTF-8.

    A value JSON cannot hold raises `TypeError`, as `json.dumps` does: nothing is
    stringified into a digest that would then name a different value.
    """
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
