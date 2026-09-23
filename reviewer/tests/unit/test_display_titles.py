"""The title a person reads, and the title the model reads (feature 009 T061, the owner's
decision 2A of 2026-09-23, research R2.28, contracts/plain-words.md section 2).

`report/titles.py` holds both. `title_from` - the recorded title, cut at 80 characters with ids as
written - is `Finding.title` and what every tool result carries; it must not move. The display
title is the whole first sentence of a title this product recorded, with every named part named;
a title written some other way is shown as written, named. Every surface a person reads calls it:
the `finding` event, the snapshot, the Review tab's ranking, `report.md`. What must not change is
pinned beside what must: `session.json`, the ranking's order and keys, and the tool result.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_core import to_jsonable_python

from swreview.findings import Finding, build_finding
from swreview.ir.models import EvidencePackage
from swreview.report import titles
from swreview.report.attention import rank
from swreview.report.markdown import render_report
from swreview.report.names import component_names
from swreview.report.session import ReviewSession
from swreview.report.snapshot import review_snapshot
from swreview.report.summary import review_ranking
from swreview.report.titles import (
    TITLE_LENGTH,
    display_title,
    first_sentence,
    pane_finding,
    title_from,
    with_display_titles,
)
from swreview.tools import recording
from swreview.tools.context import ToolContext, context_for
from tests.support.packages import build_package

NAMES = {"cmp:0001": "housing-1", "cmp:0002": "housing-2", "cmp:0003": " "}
"""Two named parts and one whose name is blank, which keeps its id."""

LONG = (
    "Static interference between cmp:0001 and cmp:0002 in configuration Default: largest "
    "overlap 12.5 mm3 across three pairs. The second sentence is never a title."
)
"""A first sentence of 128 characters naming two named parts: cut and ids in the recorded title."""


def sentence_of(length: int) -> str:
    """`observed` whose first sentence is exactly `length` characters, then a second one."""
    head = "Clearance between the pin and the bore is short by "
    return head + "x" * (length - len(head)) + ". The second sentence is never the title."


def finding(
    observed: str,
    title: str | None = None,
    *,
    finding_id: str = "F-001",
    check: str = "interference.static",
    package: EvidencePackage | None = None,
) -> Finding:
    """A finding as this product records it - `title_from(observed)` - unless `title` is given."""
    return build_finding(
        finding_id=finding_id,
        check=check,
        title=title_from(observed) if title is None else title,
        status="suspected",
        severity="medium",
        package=package if package is not None else build_package(),
        configuration="Default",
        observed=observed,
        requirement="Parts that touch in the model touch in the build.",
        recommended_action="Check the overlap in SOLIDWORKS.",
        component_ids=["cmp:0001", "cmp:0002"],
        numeric=False,
    )


# --- the recorded title: exactly what it was ------------------------------------------------


def test_the_recorded_title_is_still_cut_at_80_with_its_ids() -> None:
    title = title_from(LONG)

    assert TITLE_LENGTH == 80
    assert len(title) <= TITLE_LENGTH and title.endswith("…")
    assert title.startswith("Static interference between cmp:0001 and cmp:0002")


@pytest.mark.parametrize(("length", "cut"), [(80, False), (81, True), (300, True)])
def test_the_recorded_title_cuts_past_80_characters_only(length: int, cut: bool) -> None:
    title = title_from(sentence_of(length))

    assert title.endswith("…") is cut
    assert len(title) == (TITLE_LENGTH if cut else length)


def test_the_tool_layer_re_exports_the_one_recorded_title() -> None:
    assert recording.title_from is titles.title_from
    assert recording.TITLE_LENGTH == titles.TITLE_LENGTH
    assert {"TITLE_LENGTH", "title_from"} <= set(recording.__all__)


@pytest.mark.parametrize(
    ("observed", "first"),
    [
        ("One. Two.", "One"),
        ("  Padded sentence.  ", "Padded sentence"),
        ("Ends with dots...", "Ends with dots"),
        ("No full stop at all", "No full stop at all"),
        ("A decimal 1.5 mm stays whole. Then more.", "A decimal 1.5 mm stays whole"),
        ("", ""),
    ],
)
def test_the_first_sentence_is_split_on_a_full_stop_and_a_space(observed: str, first: str) -> None:
    assert first_sentence(observed) == first


# --- the display title --------------------------------------------------------------------------


@pytest.mark.parametrize("length", [80, 81, 300])
def test_the_display_title_is_the_whole_first_sentence_and_never_cut(length: int) -> None:
    observed = sentence_of(length)

    shown = display_title(finding(observed), {})

    assert shown == observed.split(". ")[0]
    assert len(shown) == length
    assert "…" not in shown and not shown.endswith("...")


def test_the_display_title_names_every_named_part_and_keeps_a_blank_or_unknown_id() -> None:
    observed = "Static interference between cmp:0001, cmp:0002, cmp:0003 and cmp:0009. More."

    assert display_title(finding(observed), NAMES) == (
        "Static interference between housing-1, housing-2, cmp:0003 and cmp:0009"
    )


def test_the_display_title_of_a_cut_title_is_whole_and_named() -> None:
    shown = display_title(finding(LONG), NAMES)

    assert shown == (
        "Static interference between housing-1 and housing-2 in configuration Default: "
        "largest overlap 12.5 mm3 across three pairs"
    )
    assert len(shown) > TITLE_LENGTH


def test_a_title_this_product_did_not_record_from_observed_is_shown_as_written_and_named() -> None:
    hand_written = finding(LONG, title="The housings cmp:0001 and cmp:0002 overlap")

    assert display_title(hand_written, NAMES) == "The housings housing-1 and housing-2 overlap"


def test_a_title_another_build_cut_elsewhere_is_shown_as_written() -> None:
    """Only the cut this product makes is undone; a shorter cut is some other build's title."""
    older = finding(LONG, title=LONG[:40].rstrip() + "…")

    assert display_title(older, {}) == older.title


def test_a_name_holding_a_full_stop_does_not_split_the_title() -> None:
    """The sentence is taken first and the parts named after, so a name cannot cut it short."""
    shown = display_title(finding(LONG), {"cmp:0001": "Rev. B housing", "cmp:0002": "pin"})

    assert shown.startswith("Static interference between Rev. B housing and pin in configuration")


def test_a_name_is_printed_literally_whatever_it_holds() -> None:
    """A name is text, never a pattern: backslashes, group references and ids stay as written."""
    names = {"cmp:0001": r"pin \1 $& \g<0>", "cmp:0002": "cmp:0001"}

    shown = display_title(finding("The pin cmp:0001 touches cmp:0002. More."), names)

    assert shown == r"The pin pin \1 $& \g<0> touches cmp:0001"


def test_the_display_title_reads_the_finding_and_changes_nothing_on_it() -> None:
    recorded = finding(LONG)
    before = recorded.model_dump(mode="json")

    display_title(recorded, NAMES)

    assert recorded.model_dump(mode="json") == before


def test_an_empty_observed_has_an_empty_title_both_ways() -> None:
    assert display_title(finding("", title=""), NAMES) == ""


# --- one finding's body, as the pane receives it ----------------------------------------------


def test_the_pane_body_is_the_finding_with_only_its_title_changed() -> None:
    recorded = finding(LONG)

    body = pane_finding(recorded, NAMES)

    expected = recorded.model_dump(mode="json")
    assert list(body) == list(expected)
    assert {key: value for key, value in body.items() if key != "title"} == {
        key: value for key, value in expected.items() if key != "title"
    }
    assert body["title"] == display_title(recorded, NAMES)
    assert body["observed"] == LONG
    assert recorded.title == title_from(LONG)


# --- the ranking's rows -------------------------------------------------------------------------


def session_of(*findings: Finding, folded: tuple[str, ...] = ()) -> ReviewSession:
    session = context_for(build_package()).require_session()
    session.findings.extend(findings)
    session.folded_families = list(folded)
    return session


def test_every_unfolded_row_carries_its_survivor_s_display_title() -> None:
    first = finding(LONG, finding_id="F-001")
    second = finding(sentence_of(120), finding_id="F-002", check="fit.clearance")
    ranking = rank(session_of(first, second))

    shown = with_display_titles(ranking, [first, second], NAMES)

    by_id = {row.finding_id: row.title for row in shown.rows}
    assert by_id == {
        "F-001": display_title(first, NAMES),
        "F-002": display_title(second, NAMES),
    }


def test_only_the_titles_change_and_the_ranking_it_was_given_is_untouched() -> None:
    recorded = finding(LONG)
    ranking = rank(session_of(recorded))
    before = to_jsonable_python(ranking)

    shown = with_display_titles(ranking, [recorded], NAMES)

    assert to_jsonable_python(ranking) == before
    after = to_jsonable_python(shown)
    for row in (*before["rows"], *after["rows"]):
        row.pop("title")
    assert after == before


def test_a_folded_family_keeps_its_family_title() -> None:
    rule = finding(sentence_of(120), finding_id="F-001", check="rms.sketches.fully_defined")
    ranking = rank(session_of(rule, folded=("rms",)))
    [row] = ranking.rows
    assert row.family == "rms"

    [shown] = with_display_titles(ranking, [rule], NAMES).rows

    assert shown.title == row.title


def test_a_row_whose_finding_is_not_given_keeps_its_title() -> None:
    recorded = finding(LONG)
    ranking = rank(session_of(recorded))

    [shown] = with_display_titles(ranking, [], NAMES).rows

    assert shown.title == title_from(LONG)


def test_titling_twice_is_titling_once() -> None:
    recorded = finding(LONG)
    once = with_display_titles(rank(session_of(recorded)), [recorded], NAMES)

    assert with_display_titles(once, [recorded], NAMES) == once


# --- every surface a person reads, and what the model and the record keep ---------------------


@pytest.fixture
def recorded_context() -> tuple[ToolContext, list[tuple[str, dict[str, Any]]]]:
    """A context streaming into a list, holding one cut, id-naming finding recorded as a tool
    records it: `record_finding`, the one door to the session and the stream."""
    events: list[tuple[str, dict[str, Any]]] = []
    package = build_package()
    context = context_for(package)
    context.emit = lambda event_type, body: events.append((event_type, dict(body)))
    context.record_finding(finding(LONG, package=package))
    return context, events


def test_the_finding_event_carries_the_display_title_and_the_session_the_recorded_one(
    recorded_context: tuple[ToolContext, list[tuple[str, dict[str, Any]]]],
) -> None:
    context, events = recorded_context
    [recorded] = context.require_session().findings

    assert events == [("finding", pane_finding(recorded, component_names(context.ir)))]
    assert events[0][1]["title"] == display_title(recorded, component_names(context.ir))
    assert recorded.title == title_from(LONG)


def test_the_snapshot_carries_display_titles_on_findings_and_rows(
    recorded_context: tuple[ToolContext, list[tuple[str, dict[str, Any]]]],
) -> None:
    context, events = recorded_context
    session, package = context.require_session(), context.ir
    names = component_names(package)
    [recorded] = session.findings

    snapshot = review_snapshot(session, package, run_id="run")

    assert snapshot["findings"] == [events[0][1]]
    assert [row["title"] for row in snapshot["ranking"]["rows"]] == [
        display_title(recorded, names)
    ]
    assert session.findings[0].title == title_from(LONG)


def test_the_review_ranking_carries_display_titles_and_the_ranking_s_own_order(
    recorded_context: tuple[ToolContext, list[tuple[str, dict[str, Any]]]],
) -> None:
    context, _ = recorded_context
    session, package = context.require_session(), context.ir
    ranking = rank(session)

    shown = review_ranking(session, package)

    assert [row.title for row in shown.rows] == [
        display_title(recorded, component_names(package)) for recorded in session.findings
    ]
    assert [row.key for row in shown.rows] == [row.key for row in ranking.rows]
    assert [row.title for row in ranking.rows] == [title_from(LONG)]


def test_the_review_ranking_without_a_package_is_whole_but_names_nothing(
    recorded_context: tuple[ToolContext, list[tuple[str, dict[str, Any]]]],
) -> None:
    context, _ = recorded_context

    [row] = review_ranking(context.require_session(), None).rows

    assert row.title == first_sentence(LONG)


def test_report_md_shows_the_display_title_in_the_heading_and_in_start_here(
    recorded_context: tuple[ToolContext, list[tuple[str, dict[str, Any]]]],
) -> None:
    context, _ = recorded_context
    session, package = context.require_session(), context.ir
    shown = display_title(session.findings[0], component_names(package))

    report = render_report(session, package, ranking=rank(session))

    assert f"#### F-001: {shown}" in report
    assert f"({shown})" in report, "the needs-judgement row names what the judgement is about"
    assert title_from(LONG) not in report


def test_report_md_without_a_package_shows_the_whole_title_with_its_ids(
    recorded_context: tuple[ToolContext, list[tuple[str, dict[str, Any]]]],
) -> None:
    context, _ = recorded_context

    report = render_report(context.require_session(), ranking=rank(context.require_session()))

    assert f"#### F-001: {first_sentence(LONG)}" in report
