"""The two digests every feature-014 record uses (T004, for T005).

`benchmark/digest.py` holds them both, and nothing else (plan decisions RF-48, RF-56):

1. **`sha256_of(path)` is the sha256 of a file's raw bytes.** Nothing normalises, so one
   text written with `\\r\\n` and with `\\n` is two digests (INT-3): the checkouts agree
   through `.gitattributes` `eol=lf`, never through the digest, and a key's stamp of the
   checklist is the very number a run's `checklist_digest` records (`answer-key.md` 2.2).
2. **`canonical_sha256(value)` is the sha256 of a parsed value's canonical JSON**: sorted
   keys, no whitespace, non-ASCII written as itself and hashed as its UTF-8 bytes. Two
   values equal as data are one digest whatever their key order; list order counts, since
   a list's order is data.
3. **The module is dependency-free**, the standard library only, so the key's stamp, the
   set and the generator can import it without loading the runner, the agent or each
   other (RF-1, RF-48). `benchmark/runner.py` re-exports `sha256_of` - the same function,
   not a copy - because `benchmark/compare.py`, `cli.py` and `tests/support/studies.py`
   import it from there.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from swreview.benchmark import digest, runner, sets
from swreview.benchmark.digest import canonical_sha256, sha256_of

STANDARD_LIBRARY_ONLY = {"__future__", "hashlib", "json", "pathlib"}
"""Every module `benchmark/digest.py` may import (tasks.md T004)."""


# --- sha256_of: a file's raw bytes ------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [b"", b"abc", b"\x00\xff\x80", b"first\r\nsecond\r\n", b"first\nsecond\n"],
    ids=["empty", "known", "binary", "crlf", "lf"],
)
def test_sha256_of_bytes_is_the_sha256_of_the_given_bytes(data: bytes) -> None:
    assert digest.sha256_of_bytes(data) == hashlib.sha256(data).hexdigest()


def test_sha256_of_calls_the_one_raw_bytes_digest_once_per_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = [b"first\r\nfile\r\n", b"second\nfile\n"]
    paths = [tmp_path / "crlf.md", tmp_path / "lf.md"]
    for path, content in zip(paths, data, strict=True):
        path.write_bytes(content)
    expected = [digest.sha256_of_bytes(path.read_bytes()) for path in paths]
    real_digest = digest.sha256_of_bytes
    calls: list[bytes] = []

    def watched(content: bytes) -> str:
        calls.append(content)
        return real_digest(content)

    monkeypatch.setattr(digest, "sha256_of_bytes", watched)
    for number, path in enumerate((paths[0], str(paths[1]))):
        assert digest.sha256_of(path) == expected[number]
        assert calls == data[: number + 1]


def test_sha256_of_is_the_sha256_of_the_file_s_raw_bytes(tmp_path: Path) -> None:
    path = tmp_path / "checklist_v1.yaml"
    path.write_bytes(b"items:\n  - id: fit\n")

    assert sha256_of(path) == hashlib.sha256(b"items:\n  - id: fit\n").hexdigest()


def test_sha256_of_takes_a_path_written_as_a_string(tmp_path: Path) -> None:
    path = tmp_path / "set.json"
    path.write_bytes(b'{"name": "study"}')

    assert sha256_of(str(path)) == sha256_of(path)


def test_one_text_written_with_crlf_and_with_lf_is_two_digests(tmp_path: Path) -> None:
    """INT-3: the digest never normalises line endings, so a stale CRLF copy shows."""
    crlf = tmp_path / "crlf.md"
    lf = tmp_path / "lf.md"
    crlf_bytes = b"You review designs.\r\nCite evidence.\r\n"
    lf_bytes = b"You review designs.\nCite evidence.\n"
    crlf.write_bytes(crlf_bytes)
    lf.write_bytes(lf_bytes)

    assert sha256_of(crlf) == hashlib.sha256(crlf_bytes).hexdigest()
    assert sha256_of(lf) == hashlib.sha256(lf_bytes).hexdigest()
    assert sha256_of(crlf) != sha256_of(lf)


# --- canonical_sha256: a parsed value's canonical JSON ----------------------------


def test_two_dicts_differing_only_in_key_order_are_one_digest() -> None:
    first = {"study": "lever-3", "runs": {"off": 1, "on": 2}, "seed": 7}
    second = {"seed": 7, "runs": {"on": 2, "off": 1}, "study": "lever-3"}

    assert list(first) != list(second)
    assert list(first["runs"]) != list(second["runs"])
    assert canonical_sha256(first) == canonical_sha256(second)


def test_the_canonical_form_is_sorted_keys_no_whitespace_and_utf_8_spelled_by_hand() -> None:
    """The bytes are written out by hand, so the test does not restate the implementation.

    `⌀` is U+2300, three bytes in UTF-8 (`e2 8c 80`); with `ensure_ascii` left on it would
    be the six characters `\\u2300`, and the digest a different number.
    """
    value = {"tool": {"schema": [1, 2], "description": "⌀6 H7"}, "name": "fit"}
    by_hand = b'{"name":"fit","tool":{"description":"\xe2\x8c\x806 H7","schema":[1,2]}}'

    assert canonical_sha256(value) == hashlib.sha256(by_hand).hexdigest()
    escaped = b'{"name":"fit","tool":{"description":"\\u23006 H7","schema":[1,2]}}'
    assert canonical_sha256(value) != hashlib.sha256(escaped).hexdigest()


def test_list_order_counts() -> None:
    assert canonical_sha256(["a", "b"]) != canonical_sha256(["b", "a"])
    assert canonical_sha256({"runs": [1, 2]}) != canonical_sha256({"runs": [2, 1]})


def test_a_value_json_cannot_hold_is_refused_never_stringified() -> None:
    with pytest.raises(TypeError):
        canonical_sha256({"runs": {1, 2}})


# --- the module: one function, standard library only ------------------------------


def test_the_runner_re_exports_the_one_sha256_of_not_a_copy() -> None:
    assert runner.sha256_of is digest.sha256_of
    assert sets.sha256_of is digest.sha256_of


def test_the_digest_module_imports_the_standard_library_only() -> None:
    path = Path(digest.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))

    assert imported <= STANDARD_LIBRARY_ONLY, sorted(imported - STANDARD_LIBRARY_ONLY)
