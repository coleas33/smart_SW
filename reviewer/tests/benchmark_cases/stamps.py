"""The held-out stamp (feature 014 `cases.md` 5; FR-031; owner decisions 15A and 25A; INT-3).

A held-out item of a committed case is held out against the system prompt, the checklist and the
tool descriptions as they stood when its case was written. `CURRENT` records them: the digests
`benchmark/answer_key.current_stamp()` printed on a working copy whose `test_line_endings.py`
was green (INT-3, RK-5), copied here as a literal, because the generator never imports the key's
loader (`generator.md` 9). When the prompt, the checklist or a tool description changes, the
stamp test fails listing every held-out item; that commit moves each item the change cites to
tuned-on in its case spec, sets `CURRENT` to the new digests, and regenerates (`cases.md` 5).
"""

from __future__ import annotations

from swreview.benchmark.answer_key_model import Stamp

CURRENT = Stamp(
    prompt="03235a11335b15ec809d8a7519f2cc46c647e7b6baa05a231b69e7962e8e8992",
    checklist="8a964dd514d863e196e9a854a2682b301ab7a8dca9f73d7da86f5d2c2c3f874b",
    tools="2a1e9bfe01cccdd16013ea31e8acbb86fc88e38ed2d27aade22d6a9fcae33015",
)
"""The stamp every held-out seed and key-only entry of a committed case carries."""
