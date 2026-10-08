"""The brun design (`cases.md` 6.2): a shaft in a bearing housing: seat bore, spacer stack, cover
screws.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `brun-1` and `brun-2` and their twins. That task touches no other
design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="brun", places={}, lay=unlaid("brun"))
SPECS: tuple[CaseSpec, ...] = ()
