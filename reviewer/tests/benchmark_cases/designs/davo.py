"""The davo design (`cases.md` 6.2): a motor-mount plate: pilot bore, four tapped holes, two dowels.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `davo-1` and `davo-2` and their twins. That task touches no other
design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="davo", places={}, lay=unlaid("davo"))
SPECS: tuple[CaseSpec, ...] = ()
