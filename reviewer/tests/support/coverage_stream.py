"""The coverage a pane rebuilds from the event stream, and the coverage the session holds.

Feature 011 T092 (002 `contracts/chat-events.schema.json`): a `coverage` event appends its item
to its bucket, and a `coverage.withdrawn` event drops every item of its `checks` from each of
its `buckets`. `mirror` applies the two, in stream order, the way the Review page's panel does
(`app.js`, `recordCoverage` and `withdrawCoverage`); `held` reads the session. The invariant
the tests hold is `mirror(events) == held(session)` over every path that restates coverage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from swreview.report.session import ReviewSession
from swreview.report.summary import COVERAGE_BUCKETS

Event = tuple[str, Mapping[str, Any]]

COVERAGE_EVENT_TYPES: frozenset[str] = frozenset({"coverage", "coverage.withdrawn"})


def mirror(events: Iterable[Event]) -> dict[str, list[dict[str, Any]]]:
    """Each bucket's items as the stream leaves them: appended, then dropped when withdrawn."""
    rows: list[tuple[str, dict[str, Any]]] = []
    for kind, body in events:
        if kind == "coverage":
            rows.append((body["bucket"], dict(body["item"])))
        elif kind == "coverage.withdrawn":
            rows = [
                (bucket, item)
                for bucket, item in rows
                if not (item["check"] in body["checks"] and bucket in body["buckets"])
            ]
    return {bucket: [item for held, item in rows if held == bucket] for bucket in COVERAGE_BUCKETS}


def held(session: ReviewSession) -> dict[str, list[dict[str, Any]]]:
    """Each bucket's items as the session holds them, dumped as a `coverage` event carries them."""
    return {
        bucket: [item.model_dump(mode="json") for item in getattr(session.coverage, bucket)]
        for bucket in COVERAGE_BUCKETS
    }
