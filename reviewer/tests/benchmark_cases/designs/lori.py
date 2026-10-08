"""The lori design (`cases.md` 6.2): a gear cover on a housing: dowels, screws, a shaft bore.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `lori-1` and `lori-2` and their twins. That task touches no other
design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="lori", places={}, lay=unlaid("lori"))
SPECS: tuple[CaseSpec, ...] = ()
