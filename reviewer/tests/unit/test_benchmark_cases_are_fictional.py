"""No recorded string reaches the committed benchmark cases (feature 014 T150; `generator.md` 8 and
11; FR-048, SC-011; GN-6).

The repository is public, and the generator writes every committed case from fictional strings.
This module proves it on the files as committed, every file `generate.render_all()` names read
from disk as git stores it (`as_committed`), two ways:

1. **the names check, on every machine**: `render.names_offences`, the generator's own rows 9
   and 10, finds nothing: every name is built from the case vocabulary and every path lies under
   a named fictional root;
2. **the owner's denylist**, through the reader the fixture scans share
   (`tests/support/fixture_denylist.py`), skipped naming the file where it is absent and never
   passed there: every string value of every JSON file but the schema's own, names by substring
   (`offending_tokens`) and sentences by whole word (`offending_words`), and every GLB's JSON
   chunk (`glb_json`).

**Names, sentences and schema values** (owner decision 66A). Sentences are English: the
author's (`generator.md` 8), a key entry's `description`, a scripted `answer` and a drawing's
general note, and the extractor's, a gap's `reason`. Schema values and check ids, the string
values of the `source`, `kind`, `hole_type`, `check` and `item` fields, are the IR's and the
key's own vocabulary and are left out, as feature 010's scan leaves them. Every other string
value is a name, matched as a substring, a persist ref decoded back to the id it encodes first,
as the fixture scans read them. A GLB's generator URL is `trimesh`'s and is not read. The tokens
themselves are never printed, nor the list's path: a failure names the generated file and a skip
the list's file name, since a message can reach a public log.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import pytest

from swreview.benchmark.sets import REPO_ROOT
from tests.benchmark_cases import generate, render
from tests.support.fixture_denylist import (
    DENYLIST_PATH,
    PUBLISHED_HEAD_CODES,
    glb_json,
    json_strings,
    load_denylist,
    offending_tokens,
    offending_words,
)
from tests.support.mechanical import as_committed

SENTENCE_FIELDS: frozenset[str] = frozenset({"description", "answer"})
"""A key entry's description and a case file's scripted answer: the author's English."""

SENTENCES_WITHIN: dict[str, str] = {"general_notes": "text", "gaps": "reason"}
"""The fields that are sentences inside a list: a drawing's general notes' `text`, the author's
English, and a gap's `reason`, the extractor's (owner decision 66A)."""

SCHEMA_FIELDS: frozenset[str] = frozenset({"source", "kind", "hole_type", "check", "item"})
"""The fields whose string values are schema values or check ids, the IR's and the key's own
vocabulary, which the scan leaves out as feature 010's does (owner decision 66A); a `source`
that is a reference is read, its ids being names."""


@pytest.fixture(scope="module")
def committed() -> dict[str, bytes]:
    """Every generated file, by repository-relative path, read from disk as git stores it."""
    return {path: as_committed(REPO_ROOT / path) for path in generate.render_all()}


def test_the_names_check_finds_nothing_in_any_committed_generated_file(
    committed: dict[str, bytes],
) -> None:
    assert committed
    assert render.names_offences(committed) == []


def strings(
    data: Any, field: str | None = None, *, within: str | None = None
) -> Iterator[tuple[str, bool]]:
    """Every string value of a parsed JSON document but a schema value, each with whether it is
    a sentence; a persist ref decoded to the id it encodes. `within` is the nearest enclosing
    field of `SENTENCES_WITHIN`."""
    if isinstance(data, str):
        if field in SCHEMA_FIELDS:
            return
        if field == "persist_ref":
            yield base64.b64decode(data).decode("utf-8"), False
        else:
            sentence = field in SENTENCE_FIELDS or (
                within is not None and SENTENCES_WITHIN[within] == field
            )
            yield data, sentence
    elif isinstance(data, dict):
        for name, value in data.items():
            yield from strings(value, name, within=name if name in SENTENCES_WITHIN else within)
    elif isinstance(data, list):
        for item in data:
            yield from strings(item, field, within=within)


def test_strings_tells_a_sentence_from_a_name_and_leaves_schema_values_out() -> None:
    """The reading itself, so a scan that read everything as a sentence, or left out more than
    the schema's own values, would fail here."""
    document = {
        "description": "a sentence",
        "file_name": "EX-1101-01.SLDPRT",
        "kind": "part",
        "answers": [{"answer": "All bought"}],
        "known_defects": [{"check": "fastener.thread_match", "checks": ["hole.*"]}],
        "expected_coverage": [{"item": "fasteners"}],
        "holes": [{"hole_type": "tapped", "size": "M5x0.8"}],
        "drawings": [
            {
                "general_notes": [
                    {
                        "text": "a note",
                        "kind": "other",
                        "source": {"document_id": "doc:0006", "sheet": "Sheet1"},
                    }
                ],
                "text_as_read": "Ø3.0",
                "source": "pdf_ingest",
            }
        ],
        "gaps": [{"kind": "no_text", "reason": "a gap's reason", "error": "an error"}],
        "persist_ref": base64.b64encode(b"cmp:0001").decode("ascii"),
    }

    assert sorted(strings(document)) == [
        ("All bought", True),
        ("EX-1101-01.SLDPRT", False),
        ("M5x0.8", False),
        ("Sheet1", False),
        ("a gap's reason", True),
        ("a note", True),
        ("a sentence", True),
        ("an error", False),
        ("cmp:0001", False),
        ("doc:0006", False),
        ("hole.*", False),
        ("Ø3.0", False),
    ]


def test_no_token_of_the_owners_denylist_occurs_in_any_generated_string(
    committed: dict[str, bytes],
) -> None:
    denylist = load_denylist()
    if denylist is None:
        # The file only, never its folder, which names the machine's user (owner decision 66A).
        pytest.skip(f"the owner's denylist {DENYLIST_PATH.name} is not on this machine")
    # The vendor screw names carry a published head code, as every fixture scan allows.
    checked = denylist - PUBLISHED_HEAD_CODES

    offenders = []
    for path, content in committed.items():
        if path.endswith(".glb"):
            document = glb_json(REPO_ROOT / path)
            document.get("asset", {}).pop("generator", None)
            found = any(offending_tokens(text, checked) for text in json_strings(document))
        else:
            found = any(
                offending_words(text, checked) if sentence else offending_tokens(text, checked)
                for text, sentence in strings(json.loads(content))
            )
        if found:
            offenders.append(path)

    # The tokens themselves are never printed: naming the file is enough to act on.
    assert offenders == [], "denylisted tokens occur in these generated files"
