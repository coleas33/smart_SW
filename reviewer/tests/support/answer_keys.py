"""`write_key`, the one key-writing test helper (feature 014 T034; plan decision RF-49).

Every test that needs an answer key on disk writes it here, through the format's one definition,
`benchmark.answer_key_model.AnswerKey`: format 2, `D-<n>` and `C-<n>` ids, every entry tagged, a
held-out entry stamped with `answer_key.current_stamp()` unless the test states its own stamp. A key
the model refuses cannot be written through it: a test of a refusal writes its payload itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from swreview.benchmark import answer_key
from swreview.benchmark.answer_key_model import KEY_FORMAT, AnswerKey


def _entry(prefix: str, number: int, fields: Mapping[str, Any], **defaults: Any) -> dict[str, Any]:
    """One entry: the id `<prefix><number>`, tuned on, on no parts and no documents, with a
    fictional description, each replaced by what `fields` states; a held-out entry that states
    no `held_out_against` is stamped with the current stamp."""
    entry: dict[str, Any] = {
        "id": f"{prefix}{number}",
        "component_ids": [],
        "document_ids": [],
        "tag": "tuned_on",
        "description": f"Fictional entry {prefix}{number}.",
        **defaults,
        **fields,
    }
    if entry["tag"] == "held_out" and "held_out_against" not in entry:
        entry["held_out_against"] = answer_key.current_stamp().model_dump()
    return entry


def write_key(
    directory: Path,
    package_id: str,
    *,
    known_defects: Sequence[Mapping[str, Any]] = (),
    correct_conditions: Sequence[Mapping[str, Any]] = (),
    key_only: bool | None = None,
) -> Path:
    """Write `<directory>/<package_id>.json` and return its path.

    Each entry is the fields the test states over these defaults: `D-<n>` or `C-<n>` by its
    position in its list, `component_ids` and `document_ids` empty, `tag` `tuned_on`, a fictional
    description, and for a known defect `producer` `model` and `expected_status` `suspected`.
    The key is built through `AnswerKey`, so a key the model refuses raises here, and written as
    UTF-8 JSON with `\\n` line endings, absent optional fields omitted.
    """
    key = AnswerKey.model_validate(
        {
            "key_format": KEY_FORMAT,
            "package_id": package_id,
            "key_only": key_only,
            "known_defects": [
                _entry("D-", number, fields, producer="model", expected_status="suspected")
                for number, fields in enumerate(known_defects, start=1)
            ],
            "correct_conditions": [
                _entry("C-", number, fields)
                for number, fields in enumerate(correct_conditions, start=1)
            ],
        }
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{package_id}.json"
    path.write_bytes((key.model_dump_json(indent=2, exclude_none=True) + "\n").encode("utf-8"))
    return path
