"""The cover design (`cases.md` 6.4): `cover-blind-tap`, the PDF-ingest-shaped housing and
cover with four M6 screws in blind tapped holes.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `cover-blind-tap`, in `pilot.json` only, every item tuned-on. That
task touches no other design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="cover", places={}, lay=unlaid("cover"))
SPECS: tuple[CaseSpec, ...] = ()
