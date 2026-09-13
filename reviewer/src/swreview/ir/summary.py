"""A one-line census of an evidence package.

Used by `swreview validate` and by the golden harness as the cheapest end-to-end check
that a package loaded and carries what it claims.
"""

from __future__ import annotations

from swreview.ir.models import EvidencePackage


def summarize(package: EvidencePackage) -> dict[str, int]:
    """Count the entities a reviewer asks about first."""
    return {
        "documents": len(package.documents),
        "components": len(package.components),
        "holes": len(package.holes),
        "fasteners": len(package.fasteners),
        "gaps": len(package.gaps),
    }
