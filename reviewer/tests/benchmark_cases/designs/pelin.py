"""The pelin design (`cases.md` 6.2): a flange coupling: two flanges on a spigot, a bolt circle into
tapped holes.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `pelin-1` and `pelin-2` and their twins. That task touches no other
design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="pelin", places={}, lay=unlaid("pelin"))
SPECS: tuple[CaseSpec, ...] = ()
