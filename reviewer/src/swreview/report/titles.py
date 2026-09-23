"""A finding's two titles: the one the model reads, and the one a person reads (feature 009).

**The recorded title** is `Finding.title`, written once by `title_from`: the first sentence of
`observed`, cut at `TITLE_LENGTH` characters with an ellipsis, component ids as the check wrote
them. It is in every check tool's result and its slim view, so the model reads it on every round
and feature 008's replay prices it; it also stays in `session.json`, `attention.json`, the gate
brief and the explanation pass's prompt. It must not move, and nothing here changes it.

**The display title** is what a person reads, and the owner's decision 2A of 2026-09-23 (feature
009 research R2.28) is that it is built only where a person reads it: whole - never cut - with
every part named where the part has a name. `display_title` is the one function that builds it,
and every surface a person reads calls it, directly or through the two helpers below:

- `pane_finding` - one finding as the pane receives it: the `finding` event
  (`ToolContext.finding_body`, used by the tool layer and by the runner's re-announcement) and
  the snapshot's findings (`report/snapshot.py`);
- `with_display_titles` - the ranking rows the pane prints (`report/summary.review_ranking`, and
  both check bodies' `attention` in `chat/server.py`) and `report.md`'s Start here;
- `report/markdown.py` - each finding's heading.

The page prints `title` verbatim wherever it arrives; it builds no title (contracts/plain-words.md
section 2).

The two live in one module because the display title undoes exactly the cut the recorded title
made: a title this product recorded from `observed` is shown as the whole first sentence, and any
other title - one written by hand, or by an older build with another rule - is shown as it was
written. Either way the parts are named.

Pure: it reads its arguments and writes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from swreview.findings import Finding
from swreview.report.attention import AttentionRow, Ranking
from swreview.report.names import with_component_names

__all__ = [
    "TITLE_LENGTH",
    "display_title",
    "first_sentence",
    "pane_finding",
    "title_from",
    "with_display_titles",
]

TITLE_LENGTH = 80
"""The longest recorded title, ellipsis included. The display title has no limit: the page's
two-line clamp is the only one (FR-027)."""


def first_sentence(observed: str) -> str:
    """The first sentence of `observed` - split on ". " - trimmed, its closing periods dropped."""
    return observed.strip().split(". ")[0].strip().rstrip(".")


def title_from(observed: str) -> str:
    """The recorded title: the first sentence of `observed`, cut at `TITLE_LENGTH`."""
    first = first_sentence(observed)
    if len(first) <= TITLE_LENGTH:
        return first
    return first[: TITLE_LENGTH - 1].rstrip() + "…"


def display_title(finding: Finding, names: Mapping[str, str]) -> str:
    """The title a person reads: whole, and naming every part that has a name.

    A title this product recorded from `observed` (`title_from(observed)`, cut or not) is shown
    as the whole first sentence of `observed`; any other title is shown as written. Then every
    component id whose name in `names` is non-blank is replaced by the name
    (`report/names.with_component_names`); an id with no name, or a blank one, stays. `names` is
    `component_names(package)`, or empty when there is no package. Taking the sentence before
    naming the parts means a name that holds ". " cannot cut the title short.
    """
    recorded = finding.title == title_from(finding.observed)
    whole = first_sentence(finding.observed) if recorded else finding.title
    return with_component_names(whole, names)


def pane_finding(finding: Finding, names: Mapping[str, str]) -> dict[str, Any]:
    """`finding` as the pane receives it: its JSON body, with `title` its display title.

    Every other field, and the key order, is the `Finding`'s own, so the body still validates
    as `review-session.schema.json#/$defs/Finding` and `observed` keeps its ids.
    """
    body = finding.model_dump(mode="json")
    body["title"] = display_title(finding, names)
    return body


def with_display_titles(
    ranking: Ranking, findings: Sequence[Finding], names: Mapping[str, str]
) -> Ranking:
    """`ranking` with every row a person reads titled with its survivor's display title.

    A row's survivor is `row.finding_id`, the finding its recorded title came from. A folded
    family's row keeps its family title - it counts findings and rules and names no finding - and
    a row whose finding is not among `findings` keeps its title rather than guessing one. The
    order, keys, reasons and every other field are the ranking's own; `ranking` is not changed,
    and titling a titled ranking again changes nothing.
    """
    by_id = {finding.id: finding for finding in findings}

    def titled(row: AttentionRow) -> AttentionRow:
        survivor = by_id.get(row.finding_id)
        if row.family is not None or survivor is None:
            return row
        return row.model_copy(update={"title": display_title(survivor, names)})

    return ranking.model_copy(update={"rows": [titled(row) for row in ranking.rows]})
