"""The kalo design (`cases.md` 6.2 and 6.3): a plate on two dowel pins, a cover screwed to it.

A stub until its design task (T132 to T144, `tasks.md`'s design rules) fills `DESIGN` - its places
and its `lay` - and `SPECS`: `kalo-1` and `kalo-2` and their twins, then the anchor cases
`kalo-fit-1`, `kalo-fit-2`, `kalo-fit-clean`, `kalo-contact`, `kalo-contact-positive`,
`kalo-lightweight`, `kalo-empty` and `kalo-empty-positive`. That task touches no other design's
module.
"""

from __future__ import annotations

from tests.benchmark_cases.spec import CaseSpec, Design, unlaid

DESIGN = Design(name="kalo", places={}, lay=unlaid("kalo"))
SPECS: tuple[CaseSpec, ...] = ()
