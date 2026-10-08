"""`write_key`, the one key-writing test helper (feature 014 T034, T079; plan decision RF-49).

Every test that needs an answer key on disk writes it here, through the format's one definition,
`benchmark.answer_key_model.AnswerKey`: format 2, each list's id prefix (`D-<n>`, `C-<n>`,
`FB-<n>`, `CV-<n>`, `U-<n>`, `Q-<n>`), every entry tagged, a held-out entry stamped with
`answer_key.current_stamp()` unless the test states its own stamp. A key the model refuses cannot
be written through it: a test of a refusal writes its payload itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from swreview.benchmark import answer_key
from swreview.benchmark.answer_key_model import KEY_FORMAT, AnswerKey

_ON_NOTHING: dict[str, list[str]] = {"component_ids": [], "document_ids": []}
"""The parts and documents an entry on them names unless the test states its own."""


def _entry(prefix: str, number: int, fields: Mapping[str, Any], **defaults: Any) -> dict[str, Any]:
    """One entry: the id `<prefix><number>`, tuned on, with a fictional description and
    `defaults`, each replaced by what `fields` states; a held-out entry that states no
    `held_out_against` is stamped with the current stamp."""
    entry: dict[str, Any] = {
        "id": f"{prefix}{number}",
        "tag": "tuned_on",
        "description": f"Fictional entry {prefix}{number}.",
        **defaults,
        **fields,
    }
    if entry["tag"] == "held_out" and "held_out_against" not in entry:
        entry["held_out_against"] = answer_key.current_stamp().model_dump()
    return entry


def _entries(
    prefix: str, entries: Sequence[Mapping[str, Any]], **defaults: Any
) -> list[dict[str, Any]]:
    """Each of `entries` as `_entry` writes it, numbered by its position from 1."""
    return [
        _entry(prefix, number, fields, **defaults) for number, fields in enumerate(entries, start=1)
    ]


def write_key(
    directory: Path,
    package_id: str,
    *,
    known_defects: Sequence[Mapping[str, Any]] = (),
    correct_conditions: Sequence[Mapping[str, Any]] = (),
    forbidden: Sequence[Mapping[str, Any]] = (),
    expected_coverage: Sequence[Mapping[str, Any]] = (),
    unanswerable_requests: Sequence[Mapping[str, Any]] = (),
    question_counts: Sequence[Mapping[str, Any]] = (),
    key_only: bool | None = None,
) -> Path:
    """Write `<directory>/<package_id>.json` and return its path.

    Each entry is the fields the test states over these defaults: its list's id prefix and its
    position in its list, `tag` `tuned_on` and a fictional description; on a known defect, a
    correct condition and a forbidden entry, `component_ids` and `document_ids` empty; and on a
    known defect `producer` `model` and `expected_status` `suspected`. An expected-coverage
    entry, an unanswerable request and a question-count rule take nothing else by default: the
    test states their fields (`answer-key.md` 2.6, `questions.md` 5.1 and 5.2). The key is built
    through `AnswerKey`, so a key the model refuses raises here, and written as UTF-8 JSON with
    `\\n` line endings, absent optional fields omitted. `key_only` is stated only when the test
    states it, since the model refuses an explicit `null` there.
    """
    payload: dict[str, Any] = {
        "key_format": KEY_FORMAT,
        "package_id": package_id,
        "known_defects": _entries(
            "D-", known_defects, **_ON_NOTHING, producer="model", expected_status="suspected"
        ),
        "correct_conditions": _entries("C-", correct_conditions, **_ON_NOTHING),
        "forbidden": _entries("FB-", forbidden, **_ON_NOTHING),
        "expected_coverage": _entries("CV-", expected_coverage),
        "unanswerable_requests": _entries("U-", unanswerable_requests),
        "question_counts": _entries("Q-", question_counts),
    }
    if key_only is not None:
        payload["key_only"] = key_only
    key = AnswerKey.model_validate(payload)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{package_id}.json"
    path.write_bytes((key.model_dump_json(indent=2, exclude_none=True) + "\n").encode("utf-8"))
    return path
