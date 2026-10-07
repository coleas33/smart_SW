"""`make_finding`, a finding built as data: the one definition the scorer's, the matcher's and the
origins' tests share (feature 014).

It builds through the product's `findings.build_finding`, over `build_package()`'s assembly: a
suspected `fastener.bottoming` finding on the housing, `cmp:0001`, but for what the caller states.
A test that needs the finding a tool writes builds it through that tool instead (research §2
d2-model-finding-unmatchable).
"""

from __future__ import annotations

from swreview.findings import Finding, build_finding
from tests.support.packages import build_package

PACKAGE = build_package()
"""The package a finding is built over unless the caller names another."""


def make_finding(**overrides: object) -> Finding:
    """A finding built with `build_finding`, `overrides` replacing its defaults."""
    fields: dict[str, object] = {
        "finding_id": "F-001",
        "check": "fastener.bottoming",
        "title": "t",
        "status": "suspected",
        "severity": "medium",
        "package": PACKAGE,
        "configuration": "Default",
        "observed": "o",
        "requirement": "r",
        "recommended_action": "a",
        "component_ids": ["cmp:0001"],
    }
    fields.update(overrides)
    return build_finding(**fields)  # type: ignore[arg-type]
