"""SC-003's backend half (feature 009 T061), on the big-assembly replay fixture: the summary.

The page half (`ReviewPageDefaultViewScanTests`, T065) reads the default Results view and finds
no component id where a name exists, no raw status or bucket token and no check id. The page
prints what the backend sends, so the backend's half is that what it sends is words: no line of
the summary the engineer reads first - the headline, the groups and their goals, the goal
lines' titles, states and reasons, the questions line, the parts not loaded - nor the
not-examined headline holds a check id of the fixture or an underscore-joined status or bucket
token. The recorded sentences behind the goal lines (`detail`) are in a fold and are the run's
own words, so they are not scanned.

T061's other half - every finding title, as `title_from(observed, names)` records it, holds no
`cmp:` id of a named part - waits for T062, which is not landed: whole, named titles change
every check tool's result, and feature 008's replay acceptance on its committed recordings
(`test_replay_fixtures.py`) pins those results to the recorded ones.
"""

from __future__ import annotations

import re
from typing import get_args

import pytest

from swreview.findings import FindingStatus
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import rank
from swreview.report.session import CoverageBucket, ReviewSession, load_session
from swreview.report.summary import ReviewSummary, review_summary
from swreview.report.unexamined import not_examined
from tests.unit.test_review_summary import BIG_ASSEMBLY

RAW_TOKENS = tuple(
    token for token in (*get_args(FindingStatus), *get_args(CoverageBucket)) if "_" in token
)


@pytest.fixture(scope="module")
def session() -> ReviewSession:
    return load_session(BIG_ASSEMBLY / "session.json")


@pytest.fixture(scope="module")
def package() -> EvidencePackage:
    return load_package(BIG_ASSEMBLY).package


@pytest.fixture(scope="module")
def summary(session: ReviewSession, package: EvidencePackage) -> ReviewSummary:
    return review_summary(rank(session), session, package)


def test_the_raw_tokens_scanned_for_are_the_underscore_joined_ones() -> None:
    assert RAW_TOKENS == ("checked_within_scope", "out_of_scope")


def summary_lines(summary: ReviewSummary, headline: str | None) -> list[str]:
    lines = [summary.headline]
    for group in summary.groups:
        lines += [group.label, group.text, *(goal.title for goal in group.by_goal)]
    for goal in summary.goals:
        lines += [goal.title, goal.state_label, *([goal.reason] if goal.reason else [])]
    lines += [text for text in (summary.questions.text, headline) if text]
    if summary.not_loaded is not None:
        lines.append(summary.not_loaded.text)
    return lines


def test_no_summary_line_holds_a_check_id_or_a_raw_token(
    session: ReviewSession, package: EvidencePackage, summary: ReviewSummary
) -> None:
    block = not_examined(package)
    assert block is not None
    checks = {finding.check for finding in session.findings} | {
        item.check
        for bucket in get_args(CoverageBucket)
        for item in getattr(session.coverage, bucket)
    }
    lines = summary_lines(summary, block.headline)

    offending = [
        (line, token)
        for line in lines
        for token in (*checks, *RAW_TOKENS)
        if re.search(rf"(?<![A-Za-z0-9_.]){re.escape(token)}(?![A-Za-z0-9_])", line)
    ]

    assert offending == []
    assert len(lines) > 20, "the scan reads every summary line, not an empty list"
