"""One callable the golden harness can point a fixture at (T031).

`tests/golden/test_golden.py` runs `module:attribute` over a fixture's loaded package and
compares the JSON against a committed baseline. A single tool would only pin down a
single result; `snapshot` runs the slice of the curated surface that a US1 review leans on
- the census, the holes, the fasteners, the gaps, one drawing finding, and the checklist
that finding closes out - so one baseline catches a change in any of them.

It lives beside the tools rather than in `tests/` because it is the tools' own contract
that is being frozen, and because the harness imports it by dotted path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from swreview.ir.models import EvidencePackage
from swreview.tools import query, session
from swreview.tools.context import context_for, use_context

DRAWING_FINDING_ARGUMENTS: dict[str, Any] = {
    "document_id": "DRW-2001",
    "sheet": "Sheet1",
    "observed": (
        "The tapped hole callout states a drill depth of 14 only; the usable thread "
        "depth is not specified on the sheet"
    ),
    "requirement": (
        "A tapped hole callout states the usable thread depth so thread engagement can "
        "be evaluated (ASME Y14.5 hole callout practice)"
    ),
    "source_refs": [{"document_id": "DRW-2001", "sheet": "Sheet1", "view": "SECTION A-A"}],
    "status": "unresolved",
    "recommended_action": (
        "Add the usable thread depth to the callout, or state it as a separate note, "
        "and re-run the fastener engagement check"
    ),
}


def snapshot(package: EvidencePackage, base_dir: Path | str = ".") -> dict[str, Any]:
    """Every result of one pass over `package` through the curated tools.

    Args:
        package: The fixture's evidence package, as the golden harness loaded it.
        base_dir: Where package-relative files live; unused by these tools.
    """
    context = context_for(package, base_dir=base_dir)
    with use_context(context):
        return {
            "package_summary": query.get_package_summary(),
            "holes": query.list_holes(),
            "fasteners": query.list_fasteners(),
            "gaps": query.list_gaps(),
            "drawing_sheet": query.get_drawing_sheet("DRW-2002", sheet_name="Sheet2"),
            "drawing_finding": session.record_drawing_finding(**DRAWING_FINDING_ARGUMENTS),
            "checklist": session.get_review_checklist(),
        }
