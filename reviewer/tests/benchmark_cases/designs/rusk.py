"""The rusk design (`cases.md` 6.2): a carriage on a rail: shim stack, screws into the rail.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `rusk-1` and `rusk-2` and their twins. That task touches no other
design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="rusk", places={}, lay=unlaid("rusk"))
SPECS: tuple[CaseSpec, ...] = ()
