"""The venta design (`cases.md` 6.2): a two-piece clamp block: cap screws, a clamped bore.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `venta-1` and `venta-2` and their twins. That task touches no other
design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="venta", places={}, lay=unlaid("venta"))
SPECS: tuple[CaseSpec, ...] = ()
