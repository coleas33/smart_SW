"""The mir design (`cases.md` 6.3): the 2026-09-26 sitting in one package: a custom plate, a vendor
pin of two instances, a same-name drawing beside the assembly and the plate.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: the anchor cases `mir-sitting` and `mir-sitting-positive`. That task
touches no other design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="mir", places={}, lay=unlaid("mir"))
SPECS: tuple[CaseSpec, ...] = ()
