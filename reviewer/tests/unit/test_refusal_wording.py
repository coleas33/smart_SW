"""The one wording of a pydantic refusal (feature 014; research section 9.14's slice 3 follow-ups).

`swreview.findings` holds the three helpers the formats' readers share, each written once beside
`ReviewModel`, which every one of those modules may import:

- `field_refusals`: the refusals inside one entry of a data-only format, the answer key's
  (`benchmark/answer_key_model.py`) and the case file's (`benchmark/case_file.py`): a missing
  field as `states no <field>`, any other as `<field>: <message>`, joined by `; `;
- `model_refusals`: a format's refusals as its reader names them, the answer key's
  (`benchmark/answer_key.py`) and the case file's (`benchmark/answers.load_case_file`): the
  model's own rows' sentences as they are written, pydantic's as `<field>: <message>`;
- `first_refusal`: the first refusal of a record that does not validate, `<field>: <message>`,
  or the message alone where it names no field, which the answer log's and the scorecard's
  readers put in their one line.

Each reader calls the one helper, by its own name, and keeps no copy.
"""

from __future__ import annotations

from types import ModuleType
from typing import Self

import pytest
from pydantic import ValidationError, model_validator

from swreview import findings
from swreview.benchmark import answer_key, answer_key_model, answers, case_file, scorecard
from swreview.findings import ReviewModel, field_refusals, first_refusal, model_refusals


class Inner(ReviewModel):
    name: str


class Probe(ReviewModel):
    """A strict model with a field, a nested field and one row of its own."""

    count: int
    inner: Inner | None = None

    @model_validator(mode="after")
    def _not_negative(self) -> Self:
        if self.count < 0:
            raise ValueError(f"P-{self.count} counts below zero")
        return self


def error_of(payload: object) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        Probe.model_validate(payload)
    return caught.value


def test_field_refusals_words_a_missing_field_as_states_no_and_any_other_by_its_field() -> None:
    error = error_of({"inner": {"name": 7}})

    assert field_refusals(error) == (
        "states no count; inner.name: Input should be a valid string"
    )


def test_model_refusals_keeps_a_row_s_sentence_and_words_pydantic_s_by_field() -> None:
    assert model_refusals(error_of({"count": -1})) == "P--1 counts below zero"
    assert model_refusals(error_of({"count": "1"})) == "count: Input should be a valid integer"


def test_first_refusal_is_the_first_by_its_field_or_the_message_alone() -> None:
    assert first_refusal(error_of({"inner": {"name": 7}})) == "count: Field required"
    assert first_refusal(error_of({"count": -1})) == "Value error, P--1 counts below zero"
    assert first_refusal(error_of([])) == (
        "Input should be a valid dictionary or instance of Probe"
    )


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (case_file, "field_refusals"),
        (answer_key_model, "field_refusals"),
        (answers, "model_refusals"),
        (answer_key, "model_refusals"),
        (answers, "first_refusal"),
        (scorecard, "first_refusal"),
    ],
    ids=lambda value: value.__name__.rsplit(".", 1)[-1] if isinstance(value, ModuleType) else value,
)
def test_each_reader_words_its_refusals_through_the_one_helper(
    module: ModuleType, name: str
) -> None:
    assert getattr(module, name) is getattr(findings, name)


@pytest.mark.parametrize(
    ("module", "copy"),
    [
        (case_file, "_field_refusals"),
        (answer_key_model, "_field_refusals"),
        (answers, "_model_refusal"),
        (answer_key, "_model_refusal"),
    ],
    ids=lambda value: value.__name__.rsplit(".", 1)[-1] if isinstance(value, ModuleType) else value,
)
def test_no_reader_keeps_a_copy(module: ModuleType, copy: str) -> None:
    assert not hasattr(module, copy)
