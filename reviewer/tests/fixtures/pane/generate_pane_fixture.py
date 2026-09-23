"""Write the Review tab's pane fixture from the big-assembly replay fixture (feature 009 T023).

Run from `reviewer/` and commit what it writes:

    uv run python tests/fixtures/pane/generate_pane_fixture.py --write

It writes `report/snapshot.review_snapshot` of feature 008's committed, fictional
`tests/fixtures/replay/big-assembly/` - as the live snapshot route would answer it for a
finished chat, its last seq the event log's last - plus the words file's `labels` block, to
`extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json`. Every finding's title is
recomputed first by the current `tools/recording.title_from` from its `observed`, so the
fixture shows what a review recorded by this build shows, not what the recording's build
wrote. The WebView2 acceptance tests of User Stories 3 to 7 load that file, so the page is
tested against exactly what the backend produces (research R2.24).

`tests/unit/test_pane_fixture.py` fails when the committed file differs from a fresh
generation; the fix is this command, never a hand edit. Nothing here reads a recording: the
source is already fictional and hygiene-checked (008 `contracts/replay.md` section 8).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from swreview.ir.loader import load_package
from swreview.report.session import ReviewSession, load_session
from swreview.report.snapshot import review_snapshot
from swreview.report.summary import load_words
from swreview.tools.recording import title_from

FIXTURE_ROOT = Path(__file__).resolve().parent
REVIEWER = FIXTURE_ROOT.parents[2]
SOURCE = REVIEWER / "tests" / "fixtures" / "replay" / "big-assembly"
TARGET = (
    REVIEWER.parent / "extractor" / "SwReview.AddIn.Tests" / "Fixtures" / "review-big-assembly.json"
)
RUN_ID = "big-assembly"
"""The run folder name the fixture's review goes by: the source fixture's own folder."""
CHAT_STATE = "ended"
WRITE_COMMAND = "uv run python tests/fixtures/pane/generate_pane_fixture.py --write"


def with_current_titles(session: ReviewSession) -> ReviewSession:
    """`session` with every finding's title as this build's `title_from` would write it."""
    findings = [
        finding.model_copy(update={"title": title_from(finding.observed)})
        for finding in session.findings
    ]
    return session.model_copy(update={"findings": findings})


def last_seq(events: Path) -> int:
    """The `seq` of the event log's last event: where a live snapshot's stream stands."""
    lines = [line for line in events.read_text(encoding="utf-8").splitlines() if line.strip()]
    return int(json.loads(lines[-1])["seq"])


def pane_fixture() -> dict[str, Any]:
    """The snapshot of the big-assembly review, plus the labels the page reads."""
    session = with_current_titles(load_session(SOURCE / "session.json"))
    package = load_package(SOURCE).package
    snapshot = review_snapshot(
        session,
        package,
        run_id=RUN_ID,
        chat_state=CHAT_STATE,
        last_seq=last_seq(SOURCE / "events.jsonl"),
    )
    return {**snapshot, "labels": load_words().labels.model_dump(mode="json")}


def render(fixture: dict[str, Any]) -> str:
    """The file's text: indented, key order kept, non-ASCII kept as written."""
    return json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help=f"write {TARGET.name}")
    options = parser.parse_args(argv)
    if not options.write:
        print(f"usage: {WRITE_COMMAND}", file=sys.stderr)
        return 2
    TARGET.write_text(render(pane_fixture()), encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
