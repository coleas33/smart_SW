"""Where every surface says who wrote it (feature 013 T100), against its `contracts/sources.md`
sections 1 and 2: the backend's half that needs no record field yet.

A finding, a question and a coverage row each carry an optional `source`, `code` or `model`,
omitted from `session.json` at each kind's usual author (lane S's 013 T007 adds the fields; until
then these tests set them the way that task will, on a copy). What the pane and `report.md` are
given is decided here:

- **the words**: `labels.source`, "Checked by code" and "AI guidance", served by `GET /labels`;
- **the grouped rows**: each `GroupRow` states its `source`, and its `chip` is the word for a
  model row and `null` for a code row, so the page prints what it is given;
- **the questions**: `QuestionView.source` always stated;
- **the goal lines and close-out rows**: `GoalLine.detail_source` and `NotClosed.source` only for
  `model`, omitted for `code`, so `attention.json` keeps its bytes;
- **the report**: a model finding says "Source: AI guidance", the evidence requests table has a
  Source column, and a model-written close-out sentence is marked "(AI guidance)".

The bodies the pane receives from the stream and the snapshot (`pane_finding`, the evidence and
coverage bodies) state the source once T007's schema carries the field: that half is noted for
the integrator in `tasks.md`.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid5

import yaml

from swreview.report.attention import (
    coverage_line,
    coverage_source,
    finding_source,
    load_policy,
    rank,
    request_source,
)
from swreview.report.attention_record import AttentionRecord
from swreview.report.finding_groups import findings_by_type, goal_lines
from swreview.report.markdown import render_report
from swreview.report.session import EvidenceRequest, ReviewSession
from swreview.report.summary import WORDS_FILE, load_words, review_summary
from tests.support.attention import (
    PART_COMPONENT,
    CoverageRow,
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
)
from tests.unit.test_attention import STEPS, spec

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-00000000013c")

CODE_WORD = "Checked by code"
MODEL_WORD = "AI guidance"


def session_of(
    name: str,
    specs: list[FindingSpec],
    coverage: CoverageSpec | None = None,
    requests: list[EvidenceRequest] | None = None,
) -> ReviewSession:
    return build_attention_session(
        session_id=uuid5(NAMESPACE, name),
        findings=specs,
        coverage=coverage if coverage is not None else CoverageSpec(),
        steps=STEPS,
        evidence_requests=requests or [],
    )


def written_by(record, source: str):
    """`record` as lane S's 013 T007 writes it with `source` set (a copy; the field is optional
    and omitted at its kind's default)."""
    return record.model_copy(update={"source": source})


def with_model_finding(session: ReviewSession, index: int = 0) -> ReviewSession:
    findings = list(session.findings)
    findings[index] = written_by(findings[index], "model")
    return session.model_copy(update={"findings": findings})


def request(number: int) -> EvidenceRequest:
    return EvidenceRequest(
        id=f"ER-{number:03d}",
        what=f"The evidence of request {number}",
        why=f"request {number} unblocks a check",
        entity_ids=[PART_COMPONENT],
        status="open",
        answer=None,
        answered_at=None,
    )


# --- 1. the words --------------------------------------------------------------------------------


def test_the_source_words_are_the_contracts_and_errors_stays_last() -> None:
    labels = load_words().labels
    assert labels.source == {"code": CODE_WORD, "model": MODEL_WORD}
    raw = yaml.safe_load(WORDS_FILE.read_text(encoding="utf-8"))
    assert list(raw["labels"])[-1] == "errors", "ErrorLabelsCoverTheHostTests reads it last"
    assert list(raw["labels"])[-2] == "source"


def test_each_kind_reads_its_own_default_when_the_record_says_nothing() -> None:
    """013 `contracts/sources.md` section 1: a finding and a coverage row default to code, a
    request to model, so no byte the model reads moves."""
    session = session_of("defaults", [spec("rms.folders.present")], requests=[request(1)])
    item = session.coverage.checked[0] if session.coverage.checked else None

    assert finding_source(session.findings[0]) == "code"
    assert request_source(session.evidence_requests[0]) == "model"
    if item is not None:
        assert coverage_source(item) == "code"
    assert finding_source(written_by(session.findings[0], "model")) == "model"
    assert request_source(written_by(session.evidence_requests[0], "code")) == "code"


# --- 2. the grouped rows --------------------------------------------------------------------------


def test_a_model_row_carries_the_ai_guidance_chip_and_a_code_row_none() -> None:
    session = with_model_finding(
        session_of("rows", [spec("drawing.manufacturing_inputs"), spec("rms.folders.present")])
    )

    view = findings_by_type(session, attention_package(), load_words(), load_policy())

    rows = {row.finding_id: row for group in view.groups for row in group.rows}
    assert (rows["F-001"].source, rows["F-001"].chip) == ("model", MODEL_WORD)
    assert (rows["F-002"].source, rows["F-002"].chip) == ("code", None)
    body = rows["F-002"].model_dump(mode="json")
    assert body["source"] == "code" and body["chip"] is None, "always stated to the pane"


# --- 3. the questions --------------------------------------------------------------------------


def test_each_question_states_its_source() -> None:
    requests = [request(1), written_by(request(2), "code")]
    session = session_of("questions", [], requests=requests)

    groups = findings_by_type(session, None, load_words(), load_policy())
    items = review_summary(groups, session, None).questions.items

    assert [(item.id, item.source) for item in items] == [("ER-001", "model"), ("ER-002", "code")]


# --- 4. the goal lines and the close-out rows ------------------------------------------------


def test_a_goal_detail_from_a_model_row_says_so_and_a_code_row_says_nothing() -> None:
    coverage = CoverageSpec(
        unresolved=[
            CoverageRow(check="interfaces.fit", reason="the model found no limits."),
            CoverageRow(check="fasteners", reason="no fastener was extracted."),
        ]
    )
    session = session_of("details", [], coverage)
    unresolved = list(session.coverage.unresolved)
    unresolved[0] = written_by(unresolved[0], "model")
    session.coverage.unresolved[:] = unresolved

    lines = {line.goal: line for line in goal_lines(session, load_words())}

    assert lines["fits_and_stacks"].detail_source == "model"
    assert lines["fasteners"].detail_source is None
    assert "detail_source" in lines["fits_and_stacks"].model_dump(mode="json")
    assert "detail_source" not in lines["fasteners"].model_dump(mode="json")


def test_a_model_written_close_out_row_says_so_and_the_record_keeps_its_bytes_otherwise() -> None:
    coverage = CoverageSpec(
        unresolved=[
            CoverageRow(check="fasteners", reason="no fastener was extracted."),
            CoverageRow(check="interfaces.fit", reason="the fit could not be computed."),
        ]
    )
    plain = session_of("closeout", [spec("rms.folders.present")], coverage)
    marked = plain.model_copy(deep=True)
    marked.coverage.unresolved[0] = written_by(marked.coverage.unresolved[0], "model")

    record_plain = AttentionRecord.of(rank(plain), plain.session_id).model_dump_json()
    not_closed = rank(marked).coverage.not_closed

    assert [(entry.item, entry.source) for entry in not_closed] == [
        ("fasteners", "model"),
        ("interfaces.fit", None),
    ]
    assert '"source"' not in record_plain, (
        "a code row is omitted, so attention.json keeps its bytes"
    )


def test_the_gate_and_the_command_line_print_no_mark_and_the_report_does() -> None:
    coverage = CoverageSpec(
        unresolved=[CoverageRow(check="fasteners", reason="no fastener was extracted.")]
    )
    session = session_of("closeout-mark", [], coverage)
    session.coverage.unresolved[0] = written_by(session.coverage.unresolved[0], "model")
    ranking = rank(session)

    assert "- fasteners: no fastener was extracted." in coverage_line(ranking)
    report = render_report(session, ranking=ranking).splitlines()
    assert f"- fasteners: no fastener was extracted. ({MODEL_WORD})" in report


# --- 5. report.md ----------------------------------------------------------------------------


def test_a_model_finding_says_its_source_in_the_report_and_a_code_finding_does_not() -> None:
    session = with_model_finding(
        session_of(
            "report-finding", [spec("drawing.manufacturing_inputs"), spec("rms.folders.present")]
        )
    )

    text = render_report(session, attention_package(), ranking=rank(session))

    first = text.index("#### F-001:")
    second = text.index("#### F-002:")
    assert f"- Source: {MODEL_WORD}" in text[first:second]
    assert "- Source:" not in text[second:]


def test_the_evidence_requests_table_names_each_requests_source() -> None:
    requests = [request(1), written_by(request(2), "code")]
    session = session_of("report-requests", [], requests=requests)

    lines = render_report(session).splitlines()

    assert "| ID | What | Why | Entity IDs | Status | Answer | Answered At | Source |" in lines
    rows = {line.split(" | ")[0]: line for line in lines if line.startswith("| ER-")}
    assert rows["| ER-001"].endswith(f"| {MODEL_WORD} |")
    assert rows["| ER-002"].endswith(f"| {CODE_WORD} |")


def test_no_source_token_reaches_a_rendered_word() -> None:
    session = with_model_finding(session_of("tokens", [spec("drawing.manufacturing_inputs")]))

    text = render_report(session, attention_package(), ranking=rank(session))

    assert "Source: model" not in text and "Source: code" not in text
    assert json.dumps(load_words().labels.source) == json.dumps(
        {"code": CODE_WORD, "model": MODEL_WORD}
    )
