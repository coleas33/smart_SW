"""The tessa design (`cases.md` 6.2 and 6.3): a bracket on a base: M5x0.8 tapped holes, dowel holes
(the big assembly's bracket region).

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `tessa-1` and `tessa-2` and their twins, then the anchor case
`tessa-groups`. That task touches no other design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="tessa", places={}, lay=unlaid("tessa"))
SPECS: tuple[CaseSpec, ...] = ()
