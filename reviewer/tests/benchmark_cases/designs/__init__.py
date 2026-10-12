"""The designs, in order (feature 014 `generator.md` 1 and 7; `cases.md` 6.2 to 6.4).

Each module holds one design's `DESIGN` (its one-word name, places and `lay`) and `SPECS` (its
case specs, the core cases first, then the anchor cases in `cases.md` 6.3's order). `DESIGNS`
is the order the committed set's entries follow; `generate.render_all()` refuses through
`spec.check_anchor_coverage` until every anchor and analyst-found defect is represented.
"""

from __future__ import annotations

from tests.benchmark_cases.designs import (
    brun,
    cover,
    davo,
    kalo,
    lori,
    mir,
    okta,
    pelin,
    rusk,
    tessa,
    venta,
)

DESIGNS = (kalo, tessa, okta, brun, pelin, davo, rusk, lori, venta, mir, cover)
"""The design modules, in the committed set's order."""
