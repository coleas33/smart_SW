"""Unit tests for the `## Tokens` section of `report.md` (T021, contracts/usage.md 8).

Two rules decide every test here.

**The section is rendered only when `session.usage is not None`.** A feature 001, 002 or
003 session was written before this feature existed and carries no usage, so its report
must render byte for byte as it did; `test_a_session_without_usage_matches_the_golden`
pins that against a golden captured from the renderer *before* the section was added.
This is the discipline `record_partial_evidence` already follows.

**The two providers' sub-counts are never merged.** OpenAI's `reasoning_tokens` is a
subset of `output_tokens`, while Gemini's `thoughts_token_count` is a separate addend of
the total (VERIFIED, contracts/usage.md section 3), so a single "output tokens" column
would compare two different quantities. The section names each provider's own field, and
the only cross-provider number it prints is `total_tokens`, which both providers define
as the whole bill.

A count the provider did not report renders as `not reported`, never as `0` and never as
a dash that could be read as zero (Principle I). The cached input share is a third thing
again: it is *computed*, but it is only meaningful if cached input is contained in input,
which is UNVERIFIED for OpenAI until probe L1 (T025) is recorded, so it renders as
`unknown` until `CACHED_SHARE_PUBLISHABLE` says otherwise (FR-047).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pytest_regressions.file_regression import FileRegressionFixture

from swreview.agent.providers import EffortMapping, TokenUsage
from swreview.findings import build_finding
from swreview.report.markdown import render_report
from swreview.report.session import (
    Coverage,
    CoverageItem,
    CoverageScope,
    InvestigationStep,
    ProviderInfo,
    ReviewSession,
    SessionUsage,
    Timing,
)
from tests.support.packages import build_package

PACKAGE = build_package()

SESSION_ID = UUID("11111111-2222-4333-8444-555555555555")
STARTED_AT = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)
ENDED_AT = datetime(2026, 9, 12, 9, 30, tzinfo=UTC)


def make_usage(**overrides: object) -> TokenUsage:
    """One round trip, fully reported, with the OpenAI nesting the numbers assume.

    `cached_tokens` is inside `input_tokens` and `reasoning_tokens` is inside
    `output_tokens`, so `total` is `input + output`: a builder whose numbers do not add
    up would let a renderer that prints the wrong field look right.
    """
    fields: dict[str, object] = {
        "input_tokens": 12_043,
        "cached_input_tokens": 10_240,
        "cache_write_tokens": 1_803,
        "output_tokens": 512,
        "reasoning_tokens": 448,
        "tool_result_input_tokens": None,
        "total_tokens": 12_555,
        "latency_s": 4.31,
    }
    fields.update(overrides)
    return TokenUsage(**fields)  # type: ignore[arg-type]


def make_session(
    *,
    usage: SessionUsage | None = None,
    provider: str | None = "openai",
) -> ReviewSession:
    """A small but complete session, deterministic in every field the report prints."""
    provider_info = (
        None
        if provider is None
        else ProviderInfo(
            provider=provider,
            model="gpt-5.6",
            effort_mapping=EffortMapping(
                requested="medium", provider_param="reasoning.effort", provider_value="medium"
            ),
            key_source="env",
        )
    )
    return ReviewSession(
        session_id=SESSION_ID,
        package_id=PACKAGE.package_id,
        design_id=PACKAGE.design.design_id,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        model="gpt-5.6",
        provider_info=provider_info,
        steps=[
            InvestigationStep(
                index=0,
                tool="list_holes",
                arguments={"component_id": "cmp:0001"},
                result_summary="2 holes",
                status="ok",
                error=None,
                elapsed_s=0.25,
            )
        ],
        findings=[
            build_finding(
                finding_id="F-001",
                check="fastener.bottoming",
                title="Screw bottoms in a blind tapped hole",
                status="demonstrated",
                severity="high",
                package=PACKAGE,
                configuration="Default",
                observed="o",
                requirement="r",
                recommended_action="a",
                component_ids=["cmp:0001"],
                tool_result_ids=[0],
            )
        ],
        coverage=Coverage(
            checked=[
                CoverageItem(
                    check="fastener.bottoming",
                    scope=CoverageScope(component_ids=["cmp:0001"]),
                    reason="ran",
                    error=None,
                )
            ]
        ),
        timing=Timing(
            baseline_minutes=90.0,
            assisted_supervision_minutes=10.0,
            assisted_verification_minutes=8.0,
            false_alarm_handling_minutes=2.0,
            unattended_runtime_minutes=25.0,
        ),
        usage=usage,
    )


def tokens_section(report: str) -> list[str]:
    """The `## Tokens` section's lines, up to the next heading."""
    lines = report.splitlines()
    start = lines.index("## Tokens")
    for offset, line in enumerate(lines[start + 1 :], start=start + 1):
        if line.startswith("## "):
            return lines[start:offset]
    return lines[start:]


# --- the section is rendered only when there is usage ---------------------------------


def test_a_session_without_usage_renders_no_tokens_section() -> None:
    report = render_report(make_session(usage=None), PACKAGE)

    assert "## Tokens" not in report
    assert "Tokens" not in report


def test_a_session_without_usage_matches_the_golden(
    file_regression: FileRegressionFixture,
) -> None:
    """The byte-identity guard: this golden was captured from the renderer as it stood
    before the `## Tokens` section existed, so any drift in a no-usage report - a moved
    line, a changed label, a stray blank - fails here rather than in a feature 001
    baseline.
    """
    report = render_report(make_session(usage=None), PACKAGE)

    file_regression.check(report, extension=".md", encoding="utf-8", newline="")


def test_the_tokens_section_appears_when_usage_is_present() -> None:
    usage = SessionUsage.summed([make_usage()], [1])

    report = render_report(make_session(usage=usage), PACKAGE)

    assert "## Tokens" in report


def test_the_tokens_section_sits_between_timing_and_the_trace() -> None:
    usage = SessionUsage.summed([make_usage()], [1])

    report = render_report(make_session(usage=usage), PACKAGE)

    lines = report.splitlines()
    assert (
        lines.index("## Timing") < lines.index("## Tokens") < lines.index("## Investigation Trace")
    )


# --- what the section says ------------------------------------------------------------


def test_the_section_states_rounds_and_turns() -> None:
    usage = SessionUsage.summed([make_usage(), make_usage(), make_usage()], [2])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Rounds: 3" in section
    assert "- Turns: 2" in section


def test_the_section_states_every_reported_count() -> None:
    usage = SessionUsage.summed([make_usage()], [1])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Input tokens: 12043" in section
    assert "- Cached input tokens: 10240" in section
    assert "- Uncached input tokens: 1803" in section
    assert "- Cache write tokens: 1803" in section
    assert "- Output tokens: 512" in section
    assert "- Total tokens: 12555" in section


def test_the_section_sums_over_rounds() -> None:
    usage = SessionUsage.summed([make_usage(), make_usage()], [2])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Input tokens: 24086" in section
    assert "- Total tokens: 25110" in section
    assert "- Rounds: 2" in section


def test_total_model_latency_is_stated_in_seconds() -> None:
    usage = SessionUsage.summed([make_usage(), make_usage()], [2])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Model latency: 8.62 s" in section


# --- the two providers' sub-counts are never merged -----------------------------------


def test_openai_reasoning_tokens_are_named_as_a_subset_of_output() -> None:
    usage = SessionUsage.summed([make_usage()], [1])

    section = tokens_section(render_report(make_session(usage=usage, provider="openai"), PACKAGE))

    line = next(one for one in section if one.startswith("- Reasoning tokens"))
    assert line == "- Reasoning tokens (OpenAI, inside the output tokens): 448"
    assert not any(one.startswith("- Thoughts tokens") for one in section)


def test_gemini_thoughts_tokens_are_named_as_a_separate_addend() -> None:
    usage = SessionUsage.summed(
        [make_usage(cache_write_tokens=None, tool_result_input_tokens=1_204)], [1]
    )

    section = tokens_section(render_report(make_session(usage=usage, provider="gemini"), PACKAGE))

    line = next(one for one in section if one.startswith("- Thoughts tokens"))
    assert line == "- Thoughts tokens (Gemini, a separate addend of the total): 448"
    assert not any(one.startswith("- Reasoning tokens") for one in section)
    assert "- Tool-result input tokens: 1204" in section


def test_an_unnamed_provider_claims_neither_nesting() -> None:
    """A session with no `provider_info` - the fake adapter, or a session written before
    the provider port - must not be labelled with a nesting we cannot know it has.
    """
    usage = SessionUsage.summed([make_usage()], [1])

    section = tokens_section(render_report(make_session(usage=usage, provider=None), PACKAGE))

    assert "- Reasoning tokens: 448" in section
    assert not any("OpenAI" in one or "Gemini" in one for one in section)


# --- unknown stays unknown -------------------------------------------------------------


def test_an_unreported_count_renders_as_not_reported_and_never_as_zero() -> None:
    usage = SessionUsage.summed([make_usage(cache_write_tokens=None)], [1])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Cache write tokens: not reported" in section
    assert "- Cache write tokens: 0" not in section


def test_one_null_round_makes_the_whole_total_not_reported() -> None:
    """The summing rule reaches the page: a second round that reported no output count
    makes the session's output total unknown, not the first round's number.
    """
    usage = SessionUsage.summed([make_usage(), make_usage(output_tokens=None)], [2])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Output tokens: not reported" in section
    assert "- Input tokens: 24086" in section


def test_an_all_null_round_prints_no_zero_anywhere() -> None:
    usage = SessionUsage.summed(
        [
            make_usage(
                input_tokens=None,
                cached_input_tokens=None,
                cache_write_tokens=None,
                output_tokens=None,
                reasoning_tokens=None,
                tool_result_input_tokens=None,
                total_tokens=None,
            )
        ],
        [1],
    )

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    counts = [one for one in section if one.startswith("- ") and "tokens" in one.lower()]
    assert counts, "the section still lists every count"
    assert all(one.endswith("not reported") for one in counts), counts


def test_uncached_input_is_not_reported_when_either_side_is_unknown() -> None:
    usage = SessionUsage.summed([make_usage(cached_input_tokens=None)], [1])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Uncached input tokens: not reported" in section


# --- the cached share waits on probe L1 (FR-047) --------------------------------------


def test_the_cached_share_is_unknown_until_probe_l1_is_recorded() -> None:
    """As shipped, probe L1 has not run, so the share is computed and not published."""
    usage = SessionUsage.summed([make_usage()], [1])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Cached input share: unknown (probe L1 not recorded)" in section


def test_the_cached_share_renders_as_a_percentage_once_probe_l1_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("swreview.report.markdown.CACHED_SHARE_PUBLISHABLE", True)
    usage = SessionUsage.summed([make_usage()], [1])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Cached input share: 85.0%" in section


def test_the_cached_share_is_not_reported_when_the_counts_are_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("swreview.report.markdown.CACHED_SHARE_PUBLISHABLE", True)
    usage = SessionUsage.summed([make_usage(cached_input_tokens=None)], [1])

    section = tokens_section(render_report(make_session(usage=usage), PACKAGE))

    assert "- Cached input share: not reported" in section
