"""Component names instead of component ids, from one map (feature 009 research R2.6).

An engineer reads "Pin-A-1", not `cmp:0003`. Three callers need that lookup, and each
building its own would be three chances to disagree about a blank name:

- `report/explanations.py`, which sends the names beside the ids to the explanation pass;
- `report/summary.py`, which carries the non-blank names to the Review tab for its
  Start-here meta, its question "about" lines and its contacts list;
- `report/titles.display_title`, which names the parts in the title a person reads while
  `observed`, and the recorded title the model reads, keep their ids (decision 2A).

`and_list` writes several names the way a sentence does; the not-loaded headline, the
contacts list and the drawing check all use it. `plural` counts one noun the one way every
digest line does (the pre-run's digest, the joint coverage, the drawing check).

Pure: it reads the package it is given and writes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from swreview.ir.models import EvidencePackage

__all__ = ["and_list", "component_names", "plural", "with_component_names"]

COMPONENT_ID = re.compile(r"(?<![A-Za-z0-9_])cmp:[0-9]{4,}(?![A-Za-z0-9_])")
"""A whole component id token, the IR's `^cmp:[0-9]{4,}$`, never part of a longer token:
`xcmp:0003` and `cmp:00031` are not `cmp:0003`."""


def component_names(package: EvidencePackage) -> dict[str, str]:
    """`{component id: name}` for every component of `package`, blank names included."""
    return {component.id: component.name for component in package.components}


def with_component_names(text: str, names: Mapping[str, str]) -> str:
    """`text` with every component id whose name is non-blank replaced by that name.

    An id with no name, or a blank one, is kept as written - an id is still better than
    nothing - and every other character of `text` is left exactly as it was.
    """

    def named(match: re.Match[str]) -> str:
        name = names.get(match.group(0))
        return name if name is not None and name.strip() else match.group(0)

    return COMPONENT_ID.sub(named, text)


def and_list(names: Sequence[str]) -> str:
    """One name as it is, two joined by "and", more with commas and a final "and"."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def plural(count: int, noun: str) -> str:
    """`1 fastener`, `0 fasteners`: one spelling rule for every count in a sentence."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
