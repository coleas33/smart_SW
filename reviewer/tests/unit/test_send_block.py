"""The Send summary is supplied in backend words, with the recorded wall clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

import swreview.report.summary as summary
from swreview.report.session import ModelStatus, SendFailure
from tests.unit.test_session import build_session

AT = datetime(2026, 10, 8, 9, 14, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def failure(reason: str = "Fictional refusal", at: datetime = AT) -> SendFailure:
    return SendFailure(at=at, error_class="FictRefusal", reason=reason)


def status(state: str = "not_sent", history: list[SendFailure] | None = None) -> ModelStatus:
    return ModelStatus(
        state=state,  # type: ignore[arg-type]
        checked_at=AT,
        document={"path": r"C:\Fictional\FICT-1001.SLDASM", "configuration": "Default"},
        failures=history or [],
    )


def body(*, send: dict[str, Any] | None = None, model_status: ModelStatus | None = None) -> dict:
    session = build_session(model_status=model_status)
    return summary.review_ranking(session, None, send=send).model_dump(mode="json")


def waiting(tokens: int | None = 13_151, provider: str = "openai", **changes: object) -> dict:
    return {"state": "waiting", "input_tokens": tokens, "provider": provider,
            "send_error": None, **changes}


def test_absent_send_is_omitted_and_retains_the_previous_resume_sentence() -> None:
    session = build_session()
    default = summary.review_ranking(session, None).model_dump(mode="json")
    explicit = body()
    assert explicit == default
    assert "send" not in explicit["summary"]
    assert explicit["summary"]["resume_text"] == "Sending resumes the review once."


@pytest.mark.parametrize("provider", ["openai", "fake", "gemini"])
@pytest.mark.parametrize("tokens", [13_151, 0, None])
def test_waiting_block_has_exactly_the_contract_fields_and_honest_count(
    provider: str, tokens: int | None,
) -> None:
    result = body(send=waiting(tokens, provider))["summary"]
    send = result["send"]
    words = summary.load_words().send
    if tokens is None:
        text = "Send starts the model's review."
    elif provider == "gemini":
        text = (
            "Send starts the model's review. Its first request is about "
            f"{tokens:,} input tokens (approximate: Gemini counts tokens its own way); "
            "the requests after it are not counted in advance."
        )
    else:
        text = (
            f"Send starts the model's review. Its first request is {tokens:,} input tokens; "
            "the requests after it are not counted in advance."
        )
    assert send == {
        "state": "waiting", "input_tokens": tokens, "approximate": provider == "gemini",
        "text": text, "failure": None, "rerun_failed_text": None,
    }
    assert result["resume_text"] == words.apply_answers
    assert "o200k_base" not in send["text"]


@pytest.mark.parametrize("provider", ["openai", "gemini", "fake"])
def test_restored_block_is_uncounted_and_contains_no_id_or_restored_line(provider: str) -> None:
    send = body(send={**waiting(None, provider), "state": "restored"})["summary"]["send"]
    assert send == {
        "state": "restored", "input_tokens": None, "approximate": provider == "gemini",
        "text": "Send checks the saved evidence again, then starts the model's review.",
        "failure": None,
        "rerun_failed_text": (
            "The saved evidence could not be checked again, "
            "so nothing changed and nothing was sent. "
            "The next Send tries again."
        ),
    }
    assert "session_id" not in send and "restored_line" not in send


def test_prepare_failure_takes_precedence_over_recorded_request_failures() -> None:
    send = body(
        send=waiting(send_error=failure("Fictional build refused")),
        model_status=status("send_failed", [failure("Fictional older request refused")]),
    )["summary"]["send"]
    assert send["failure"] == (
        "Send to model could not start: Fictional build refused (09:14). "
        "Nothing was sent; Send to model is offered again."
    )


@pytest.mark.parametrize("state", ["waiting", "restored"])
def test_latest_recorded_failed_request_uses_its_original_wall_clock(state: str) -> None:
    send = body(
        send={**waiting(None), "state": state},
        model_status=status("send_failed", [
            failure("Fictional older refusal", AT - timedelta(minutes=10)),
            failure("Fictional latest refusal"),
        ]),
    )["summary"]["send"]
    assert send["failure"] == (
        "The model did not answer: Fictional latest refusal (09:14). "
        "Nothing else changed; Send to model is offered again."
    )


@pytest.mark.parametrize("state", ["not_sent", "sent"])
def test_retained_failure_history_is_not_shown_as_a_current_failed_request(state: str) -> None:
    send = body(send=waiting(), model_status=status(state, [failure()]))["summary"]["send"]
    assert send["failure"] is None


def test_send_failed_without_optional_history_does_not_invent_a_failure_line() -> None:
    send = body(send=waiting(), model_status=status("send_failed"))["summary"]["send"]
    assert send["failure"] is None


def test_one_tokens_formatter_is_used_for_send_and_the_previous_resume_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    def formatter(tokens: int) -> str:
        seen.append(tokens)
        return "FICT-count"

    monkeypatch.setattr(summary, "tokens_text", formatter)
    assert "FICT-count" in body(send=waiting())["summary"]["send"]["text"]
    assert "FICT-count" in summary.load_words().resume.of(13_151)
    assert seen == [13_151, 13_151]


@pytest.mark.parametrize(
    "kind", ["waiting", "approximate", "unknown", "restored", "failed", "prepare"]
)
def test_each_send_sentence_comes_from_the_words_file(
    kind: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = summary.load_words()
    send_words = original.send.model_copy(update={
        "first_request": "FICT-first {tokens}",
        "first_request_approximate": "FICT-about {tokens}",
        "without": "FICT-uncounted",
        "restored": "FICT-restored",
        "failed": "FICT-failed {reason} {time}",
        "not_started": "FICT-prepare {reason} {time}",
        "apply_answers": "FICT-apply",
        "rerun_failed": "FICT-rerun-failed",
    })
    monkeypatch.setattr(
        summary, "load_words", lambda: original.model_copy(update={"send": send_words})
    )
    inputs = waiting()
    record = None
    expected = "FICT-first 13,151"
    field = "text"
    if kind == "approximate":
        inputs = waiting(provider="gemini")
        expected = "FICT-about 13,151"
    elif kind == "unknown":
        inputs = waiting(None)
        expected = "FICT-uncounted"
    elif kind == "restored":
        inputs = {**waiting(None), "state": "restored"}
        expected = "FICT-restored"
    elif kind == "failed":
        record = status("send_failed", [failure()])
        expected, field = "FICT-failed Fictional refusal 09:14", "failure"
    elif kind == "prepare":
        inputs = waiting(send_error=failure())
        expected, field = "FICT-prepare Fictional refusal 09:14", "failure"
    result = body(send=inputs, model_status=record)["summary"]
    assert result["send"][field] == expected
    assert result["resume_text"] == "FICT-apply"
    if kind == "restored":
        assert result["send"]["rerun_failed_text"] == "FICT-rerun-failed"


def test_send_block_rejects_unknown_fields_and_states() -> None:
    cls = summary.SendBlock
    values = dict(
        state="waiting", input_tokens=None, approximate=False,
        text="FICT-text", failure=None, rerun_failed_text=None,
    )
    with pytest.raises(ValidationError):
        cls(**{**values, "session_id": "FICT-forbidden"})
    with pytest.raises(ValidationError):
        cls(**{**values, "state": "running"})
