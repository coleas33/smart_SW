"""A saved report names what ran, using the record's original wall clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from swreview.agent.providers import EffortMapping
from swreview.report.markdown import render_report
from swreview.report.session import ModelStatus, ProviderInfo, SendFailure
from tests.unit.test_session import build_session

WHEN = datetime(2026, 10, 8, 9, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
INFO = ProviderInfo(
    provider="openai", model="FICT-model",
    effort_mapping=EffortMapping(
        requested="high", provider_param="reasoning.effort", provider_value="high"
    ), key_source="none",
)
PROVIDER_LINE = (
    "- Provider: openai (effort high sent as reasoning.effort=high; key from none)"
)


def header(**changes: object) -> list[str]:
    session = build_session(model="FICT-model", provider_info=INFO, **changes)
    return render_report(session).split("\n\n## Manifest Discrepancies", 1)[0].splitlines()


def status(state: str, **changes: object) -> ModelStatus:
    return ModelStatus(**{
        "state": state, "checked_at": WHEN,
        "document": {"path": r"C:\Fictional\FICT-7000.SLDASM", "configuration": "Default"},
        **changes,
    })


def failures() -> list[SendFailure]:
    return [
        SendFailure(at=WHEN, error_class="FictEarlier", reason="Fictional earlier refusal"),
        SendFailure(at=WHEN + timedelta(minutes=2), error_class="FictLatest",
                    reason="Fictional latest refusal"),
    ]


def test_not_sent_header_names_code_only_and_no_provider_that_ran() -> None:
    lines = header(model_status=status("not_sent"))
    assert "- Model: not sent to the model (checked by code only)" in lines
    assert not any(line.startswith("- Provider:") for line in lines)
    assert "- Model: FICT-model" not in lines


def test_failed_send_names_only_its_latest_failure_and_original_wall_clock() -> None:
    lines = header(model_status=status("send_failed", failures=failures()))
    assert (
        "- Model: not sent to the model; the last attempt failed at "
        "2026-10-08T09:14:00+05:30: Fictional latest refusal"
    ) in lines
    assert not any(line.startswith("- Provider:") for line in lines)
    assert not any("Fictional earlier refusal" in line for line in lines)


def test_a_schema_valid_failed_record_without_details_still_reports_not_sent() -> None:
    lines = header(model_status=status("send_failed"))
    assert "- Model: not sent to the model; the last attempt failed (details unavailable)" in lines
    assert not any(line.startswith("- Provider:") for line in lines)


@pytest.mark.parametrize("history", [[], failures()])
def test_sent_header_retains_old_model_and_provider_then_records_send_time(
    history: list[SendFailure],
) -> None:
    sent = WHEN + timedelta(hours=1)
    lines = header(model_status=status("sent", sent_at=sent, failures=history))
    model = lines.index("- Model: FICT-model")
    assert lines[model + 1:model + 3] == [
        PROVIDER_LINE,
        "- Sent to the model: 2026-10-08T10:12:00+05:30 "
        "(checks finished 2026-10-08T09:12:00+05:30)",
    ]
    assert ("- Earlier attempts that failed: 2" in lines) is bool(history)


@pytest.mark.parametrize("state", ["not_sent", "send_failed", "sent"])
def test_rechecked_from_is_beside_the_existing_retry_line(state: str) -> None:
    retry = UUID("aaaaaaaa-1234-4234-8234-123456789abc")
    earlier = UUID("bbbbbbbb-1234-4234-8234-123456789abc")
    lines = header(
        retry_of=retry,
        model_status=status(state, rechecked_from=earlier, failures=failures(), sent_at=WHEN),
    )
    index = lines.index(f"- Retry of session: {retry}")
    assert lines[index + 1] == f"- Checked again from session: {earlier}"


def test_pre_feature_header_is_exactly_the_previous_header() -> None:
    assert header() == [
        "# Design Review Report: dsn:1", "",
        "- Session: 99999999-8888-4777-8666-555555555555",
        "- Model: FICT-model", PROVIDER_LINE,
        "- Started: 2026-09-12T13:00:00+00:00",
        "- Ended: 2026-09-12T13:21:00+00:00",
    ]
