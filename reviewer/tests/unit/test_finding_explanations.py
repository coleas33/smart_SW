"""U5: bounded model explanations stay presentation-only and reproducible."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.chat.server import TurnStopped
from swreview.ir.loader import load_package
from swreview.report.attention import rank
from swreview.report.explanations import (
    MAX_EXPLANATION_CHARS,
    MAX_EXPLANATION_PROMPT_BYTES,
    MAX_EXPLANATIONS,
    _prompt,
    parse_explanations,
)
from swreview.report.rerender import rerender_run_folder
from swreview.report.session import load_session
from tests.support.attention import (
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
)
from tests.unit.test_runner_provider import RaisingProvider

MODEL = "fake-u5"
EXPLANATION = "This finding means the reviewed model carries a traceability risk."


def _batch(*pairs: tuple[str, str]) -> str:
    return json.dumps(
        {
            "explanations": [
                {"finding_id": finding_id, "explanation": text} for finding_id, text in pairs
            ]
        }
    )


def _session():
    package = attention_package()
    return build_attention_session(
        session_id=package.package_id,  # only uniqueness matters to this unit fixture
        findings=[
            FindingSpec(
                check="rms.grouping.all_features_in_a_group",
                title="Loose features",
                status="suspected",
                component_ids=("cmp:0003",),
                tool_result_ids=(0,),
                coverage_limits=("The extracted tree was partial.",),
                observed="The reviewed housing has loose features outside folders.",
                requirement="Features should be grouped so later edits remain traceable.",
                recommended_action="Group the loose features and review the resulting tree.",
            )
        ],
        coverage=CoverageSpec(),
        package=package,
        steps=("check_rms_part",),
    )


def test_parse_explanations_accepts_fenced_json_and_normalizes_whitespace() -> None:
    parsed = parse_explanations(
        "```json\n" + _batch(("F-001", "  one\n two  ")) + "\n```",
        allowed_ids=("F-001",),
    )

    assert parsed == {"F-001": "one two"}


@pytest.mark.parametrize(
    ("body", "allowed", "match"),
    [
        (_batch(("F-999", EXPLANATION)), ("F-001",), "unknown"),
        (_batch(("F-001", EXPLANATION), ("F-001", "again")), ("F-001",), "repeats"),
        (_batch(("F-001", "")), ("F-001",), "blank"),
        (_batch(("F-001", "x" * (MAX_EXPLANATION_CHARS + 1))), ("F-001",), "exceeds"),
    ],
)
def test_parse_explanations_rejects_unsafe_rows(
    body: str, allowed: tuple[str, ...], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        parse_explanations(body, allowed_ids=allowed)


def test_parse_explanations_rejects_more_than_the_amplified_cap() -> None:
    body = _batch(*[(f"F-{index:03d}", EXPLANATION) for index in range(1, MAX_EXPLANATIONS + 2)])

    with pytest.raises(ValueError, match="more than"):
        parse_explanations(body, allowed_ids=tuple(f"F-{index:03d}" for index in range(1, 8)))


def test_prompt_contains_bounded_member_evidence_and_component_names() -> None:
    session = _session()
    ranking = rank(session)
    prompt = _prompt(ranking.rows, session=session, package=attention_package())

    assert len(prompt.encode("utf-8")) <= MAX_EXPLANATION_PROMPT_BYTES
    assert "The reviewed housing has loose features" in prompt
    assert "Group the loose features" in prompt
    assert "housing-1" in prompt
    assert "F-001" in prompt


def test_prompt_refuses_runaway_evidence() -> None:
    session = _session()
    session.findings[0].observed = "x" * MAX_EXPLANATION_PROMPT_BYTES

    with pytest.raises(ValueError, match="prompt exceeds"):
        _prompt(rank(session).rows, session=session, package=attention_package())


class ScriptedPresentationProvider(FakeProvider):
    """Fake review turns plus a public presentation provider counter."""

    def __init__(self, *, script: Sequence[ScriptedTurn], presentation: str = EXPLANATION) -> None:
        super().__init__(
            script=script,
            model=MODEL,
            explanation_script=[ScriptedTurn(text=_batch(("F-001", presentation)))],
        )
        self.presentation_calls = 0

    def for_presentation(self, *, max_output_tokens: int) -> FakeProvider:
        assert max_output_tokens == 2048
        self.presentation_calls += 1
        return super().for_presentation(max_output_tokens=max_output_tokens)


def _finding_call() -> ScriptedToolCall:
    return ScriptedToolCall(
        name="record_drawing_finding",
        arguments={
            "document_id": "doc:2",
            "sheet": "Sheet1",
            "observed": "The tapped hole has no usable thread depth.",
            "requirement": "The callout states usable thread depth.",
            "source_refs": [{"document_id": "doc:2", "sheet": "Sheet1"}],
            "status": "suspected",
            "recommended_action": "Add the usable thread depth to the callout.",
        },
    )


def test_opted_in_run_persists_and_rerenders_one_explanation_without_changing_rank(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    provider = ScriptedPresentationProvider(
        script=[ScriptedTurn(text="done", tool_calls=(_finding_call(),))]
    )
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "run",
        provider=provider,
        model=MODEL,
        effort="high",
        explain_findings=True,
    )
    try:
        session = run.start()
        before = [row.key.model_dump() for row in rank(session).rows]
        report = rerender_run_folder(
            tmp_path / "run", package=load_package(tmp_package_dir).package
        )
        assert report.is_file()
        persisted = load_session(run.session_path)
        assert persisted.finding_explanations == {"F-001": EXPLANATION}
        assert [row.key.model_dump() for row in rank(persisted).rows] == before
        attention = json.loads((tmp_path / "run" / "attention.json").read_text())
        assert attention["rows"][0]["explanation"] == EXPLANATION
        assert EXPLANATION in (tmp_path / "run" / "report.md").read_text()
        assert provider.presentation_calls == 1
    finally:
        run.close()


def test_disabled_run_never_requests_presentation(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedPresentationProvider(script=[ScriptedTurn(text="done")])
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "run",
        provider=provider,
        explain_findings=False,
    )
    run.session.findings.extend(_session().findings)
    monkeypatch.setattr(
        runner, "generate_explanations", lambda *args, **kwargs: pytest.fail("called")
    )
    try:
        run.start()
    finally:
        run.close()
    assert provider.presentation_calls == 0


def test_failure_and_stopped_turns_never_request_presentation(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def forbidden(*args: Any, **kwargs: Any) -> dict[str, str]:
        nonlocal calls
        calls += 1
        raise AssertionError("presentation requested after an incomplete turn")

    monkeypatch.setattr(runner, "generate_explanations", forbidden)
    failed = runner.start_review(
        tmp_package_dir,
        tmp_path / "failed",
        provider=RaisingProvider(),
        explain_findings=True,
    )
    failed.session.findings.extend(_session().findings)
    with pytest.raises(RuntimeError):
        failed.start()
    failed.close()

    stopped = runner.start_review(
        tmp_package_dir,
        tmp_path / "stopped",
        provider=FakeProvider(script=[ScriptedTurn(text="", end_reason="stopped")], model=MODEL),
        explain_findings=True,
    )
    stopped.session.findings.extend(_session().findings)
    try:
        stopped.start()
    finally:
        stopped.close()
    assert calls == 0


def test_unchanged_followup_reuses_the_persisted_batch_and_usage_includes_it(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    provider = ScriptedPresentationProvider(
        script=[
            ScriptedTurn(text="done", tool_calls=(_finding_call(),)),
            ScriptedTurn(text="nothing changed"),
        ]
    )
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "run",
        provider=provider,
        explain_findings=True,
    )
    try:
        run.start()
        first = dict(run.session.finding_explanations)
        run.continue_session("Please repeat the current result.")
        assert run.session.finding_explanations == first
        assert provider.presentation_calls == 1
        assert run.session.usage is not None
        assert run.session.usage.rounds == 3
        assert run.session.usage.turns == 2
        groups: list[list[int]] = [[]]
        for line in (tmp_path / "run" / "events.jsonl").read_text().splitlines():
            event = json.loads(line)
            if event["type"] == "usage":
                groups[-1].append(event["body"]["round_index"])
            elif event["type"] == "turn.ended":
                groups.append([])
        assert groups == [[0, 1], [0], []]
        assert run.session.timing.unattended_runtime_minutes >= 0
    finally:
        run.close()


def test_final_runtime_includes_the_presentation_pass(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = datetime(2026, 9, 20, tzinfo=UTC)
    clock = [baseline]

    class Clock:
        @staticmethod
        def now(tz):
            return clock[0]

    monkeypatch.setattr(runner, "datetime", Clock)
    provider = ScriptedPresentationProvider(
        script=[ScriptedTurn(text="done", tool_calls=(_finding_call(),))]
    )
    original = provider.for_presentation

    def presentation(*, max_output_tokens: int):
        clock[0] += timedelta(seconds=12)
        return original(max_output_tokens=max_output_tokens)

    provider.for_presentation = presentation
    run = runner.start_review(
        tmp_package_dir, tmp_path / "run", provider=provider, explain_findings=True
    )
    run.started = baseline
    try:
        run.start()
        assert run.session.ended_at == baseline + timedelta(seconds=12)
        assert run.session.timing.unattended_runtime_minutes == pytest.approx(0.2)
    finally:
        run.close()


def test_stop_at_the_presentation_boundary_makes_finalization_local(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    provider = ScriptedPresentationProvider(
        script=[ScriptedTurn(text="done", tool_calls=(_finding_call(),))]
    )
    run = runner.start_review(
        tmp_package_dir, tmp_path / "run", provider=provider, explain_findings=True
    )

    def stopped() -> None:
        raise TurnStopped()

    run.check_presentation_cancelled = stopped
    try:
        with pytest.raises(TurnStopped):
            run.start()
        assert provider.presentation_calls == 0
        # The chat host records Stop, then requests a local finalization.
        run.sink.emit("turn.ended", {"reason": "stopped"})
        run.cancel_presentation()
        run.finalize()
        assert provider.presentation_calls == 0
        assert run.session.usage is not None
        assert run.session.usage.turns == 1
        assert load_session(run.session_path).finding_explanations
    finally:
        run.close()


def test_explanations_are_literal_text_in_the_report() -> None:
    from swreview.report.markdown import render_report

    session = _session()
    session.finding_explanations = {"F-001": "<script>bad</script> [link](https://example.com)"}
    report = render_report(session, attention_package(), ranking=rank(session))
    assert "<script>" not in report
    assert "[link](https://example.com)" not in report
    assert report.count("&lt;script&gt;bad&lt;/script&gt;") == 2


def test_stop_after_the_final_provider_event_does_not_persist_generated_prose(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedPresentationProvider(
        script=[ScriptedTurn(text="done", tool_calls=(_finding_call(),))]
    )
    original_factory = provider.for_presentation
    stop_requested = False

    def presentation_with_late_stop(*, max_output_tokens: int) -> FakeProvider:
        presentation = original_factory(max_output_tokens=max_output_tokens)
        original_run = presentation.run

        def finish_then_stop(**kwargs: Any) -> Any:
            nonlocal stop_requested
            result = original_run(**kwargs)
            stop_requested = True
            return result

        monkeypatch.setattr(presentation, "run", finish_then_stop)
        return presentation

    monkeypatch.setattr(provider, "for_presentation", presentation_with_late_stop)
    run = runner.start_review(
        tmp_package_dir, tmp_path / "run", provider=provider, explain_findings=True
    )

    def check_cancelled() -> None:
        if stop_requested:
            raise TurnStopped()

    run.check_presentation_cancelled = check_cancelled
    try:
        with pytest.raises(TurnStopped):
            run.start()
        assert provider.presentation_calls == 1
        run.sink.emit("turn.ended", {"reason": "stopped"})
        run.cancel_presentation()
        run.finalize()
        assert EXPLANATION not in load_session(run.session_path).finding_explanations.values()
        assert provider.presentation_calls == 1
        assert run.session.usage is not None
        assert run.session.usage.turns == 1
    finally:
        run.close()


# --- feature 008 T045: the folded family is never explained ---------------------------------


def test_a_family_row_in_the_top_five_is_never_sent_to_the_presentation_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-014: the model is told only a folded family's counts, and the explanation request
    sends each row's finding evidence - so a family row never reaches it, and no fallback
    is written against its representative either (research R2.22)."""
    from swreview.ir.loader import save_package
    from tests.support.prerun import CHECKS_FIRST, prerun_package

    folder = tmp_path / "run"
    save_package(prerun_package(), folder)
    received: list[list[Any]] = []

    def spy(provider: Any, rows: Sequence[Any], **kwargs: Any) -> dict[str, str]:
        received.append(list(rows))
        return {}

    monkeypatch.setattr(runner, "generate_explanations", spy)
    run = runner.start_review(
        folder,
        folder,
        provider=ScriptedPresentationProvider(script=[ScriptedTurn(text="done")]),
        efficiency=CHECKS_FIRST,
        explain_findings=True,
    )
    try:
        session = run.start()
    finally:
        run.close()

    ranking = rank(session)
    [family] = [row for row in ranking.rows[: ranking.top_n] if row.family is not None]
    assert received, "the presentation pass ran for the other rows"
    assert all(row.family is None for rows in received for row in rows)
    assert family.finding_id not in session.finding_explanations
    assert session.finding_explanations, "the non-family rows still get their fallback"
