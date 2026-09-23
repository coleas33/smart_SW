"""Native drawing sheets as the model's tools read them (feature 011).

`contracts/drawing-source.md` section 2 is normative. One place turns what the drawing phase
recorded into what a tool reports, so the census, the sheet and dimension tools and the
reference a fit or stack check takes cannot read a native sheet two ways.
"""

from __future__ import annotations

from swreview.ir.models import EvidencePackage

__all__ = ["native_sheet_count"]


def native_sheet_count(package: EvidencePackage) -> int:
    """How many sheets the drawing phase read, over every drawing record of `package`.

    The census and the opening brief print it **only when it is not zero**, so a package
    that carries no native sheet reports exactly what it reported before feature 011 (FR-037).
    """
    return sum(len(record.sheets) for record in package.drawing_records)
