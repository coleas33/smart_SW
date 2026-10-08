"""The okta design (`cases.md` 6.2): a clevis, a pin through both legs, two bushings; a base with
three dowel-hole pairs.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `okta-1` (US5-16) and `okta-2` and their twins. That task touches no
other design's module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="okta", places={}, lay=unlaid("okta"))
SPECS: tuple[CaseSpec, ...] = ()
