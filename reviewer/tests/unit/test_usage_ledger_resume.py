"""The resume cost the questions panel states before Send (feature 009 T039).

Sending the engineer's answers resumes the review once, and the pane says what that costs
first: "Its last round sent 405,861 input tokens." (FR-016, contracts/questions.md section 5).
The figure is a measurement, never a prediction - the input of the last conversation round
before the most recent `text.done` - and two readings of "the last round" would be wrong:

- the explanation pass's presentation request is emitted **after** `text.done`
  (`agent/runner.py`), and it is small, so reading it would understate the cost;
- a turn stopped before its `text.done` wrote no answer, so the last answer is still the
  previous turn's and so is its round.

`UsageLedger` records the round count at each `text.done`; `last_conversation_input()` reads
the round before it, or `None` when there is none or it reported no input.
"""

from __future__ import annotations

from typing import Any

import pytest

from swreview.agent.providers import TokenUsage
from swreview.agent.runner import UsageLedger
from swreview.report.summary import load_words
from tests.unit.test_usage_ledger import (
    ROUND_ONE,
    ROUND_THREE,
    ROUND_TWO,
    feed,
    turn_ended,
    usage_event,
)

PRESENTATION = ROUND_ONE.model_copy(update={"input_tokens": 612})
"""The explanation pass's small request, emitted after the turn's text."""


def text_done(text: str = "done") -> tuple[str, dict[str, Any]]:
    return ("text.done", {"text": text})


def test_nothing_is_known_before_any_text_done() -> None:
    ledger = UsageLedger()
    assert ledger.last_conversation_input() is None

    feed(ledger, usage_event(ROUND_ONE), usage_event(ROUND_TWO, 1))

    assert ledger.last_conversation_input() is None


def test_it_is_the_input_of_the_last_round_before_the_latest_text_done() -> None:
    ledger = UsageLedger()

    feed(ledger, usage_event(ROUND_ONE), usage_event(ROUND_TWO, 1), text_done())

    assert ledger.last_conversation_input() == ROUND_TWO.input_tokens


def test_a_presentation_round_after_text_done_is_never_taken() -> None:
    ledger = UsageLedger()

    feed(
        ledger,
        usage_event(ROUND_ONE),
        usage_event(ROUND_TWO, 1),
        text_done(),
        usage_event(PRESENTATION, 2),
        turn_ended(),
    )

    assert ledger.last_conversation_input() == ROUND_TWO.input_tokens


def test_the_latest_answer_wins_across_turns() -> None:
    ledger = UsageLedger()

    feed(
        ledger,
        usage_event(ROUND_ONE),
        text_done(),
        turn_ended(),
        usage_event(ROUND_THREE),
        text_done(),
        turn_ended(),
    )

    assert ledger.last_conversation_input() == ROUND_THREE.input_tokens


def test_a_turn_stopped_before_its_text_done_keeps_the_previous_answer() -> None:
    ledger = UsageLedger()

    feed(
        ledger,
        usage_event(ROUND_ONE),
        text_done(),
        turn_ended(),
        usage_event(ROUND_THREE),
        ("turn.ended", {"reason": "stopped"}),
    )

    assert ledger.last_conversation_input() == ROUND_ONE.input_tokens


def test_a_round_that_reported_no_input_gives_none() -> None:
    ledger = UsageLedger()
    silent = ROUND_TWO.model_copy(update={"input_tokens": None, "total_tokens": None})

    feed(ledger, usage_event(ROUND_ONE), usage_event(silent, 1), text_done())

    assert ledger.last_conversation_input() is None


def test_a_text_done_with_no_round_before_it_gives_none() -> None:
    ledger = UsageLedger()

    feed(ledger, text_done(), usage_event(ROUND_ONE))

    assert ledger.last_conversation_input() is None


# --- the sentence -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tokens", "sentence"),
    [
        (405_861, "Sending resumes the review once. Its last round sent 405,861 input tokens."),
        (7, "Sending resumes the review once. Its last round sent 7 input tokens."),
        (None, "Sending resumes the review once."),
    ],
)
def test_the_resume_sentence_states_the_measured_figure_or_nothing(
    tokens: int | None, sentence: str
) -> None:
    assert load_words().resume.of(tokens) == sentence


def test_a_summary_given_the_ledger_carries_its_figure() -> None:
    from tests.unit.test_review_summary import request, session_of, summary_of

    ledger = UsageLedger()
    feed(
        ledger,
        usage_event(TokenUsage(**{**ROUND_ONE.model_dump(), "input_tokens": 405_861})),
        text_done(),
    )
    session = session_of("resume-ledger", [], evidence_requests=[request(1)])

    summary = summary_of(session, None, usage=ledger)

    assert summary.resume_input_tokens == 405_861
    assert summary.resume_text == (
        "Sending resumes the review once. Its last round sent 405,861 input tokens."
    )
