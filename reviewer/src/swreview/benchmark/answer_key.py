"""Answer keys: known defects and correct conditions withheld from the reviewer.

This is the only module in `swreview` that reads `benchmarks/answer_keys/` (constitution
Principle VI, FR-025); only `swreview.benchmark.scorecard` calls it, after a run has
already finished. Mirrors `benchmarks/answer_keys/cover-blind-tap.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from swreview.findings import ReviewModel


class KnownDefect(ReviewModel):
    id: str
    check: str
    component_ids: list[str]
    description: str


class CorrectCondition(ReviewModel):
    check: str
    component_ids: list[str]
    description: str


class AnswerKey(ReviewModel):
    package_id: str
    known_defects: list[KnownDefect] = Field(default_factory=list)
    correct_conditions: list[CorrectCondition] = Field(default_factory=list)


def load_answer_key(directory: Path | str, package_id: str) -> AnswerKey:
    """Read `<directory>/<package_id>.json`, e.g. `benchmarks/answer_keys/<id>.json`."""
    path = Path(directory) / f"{package_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AnswerKey.model_validate(payload)
