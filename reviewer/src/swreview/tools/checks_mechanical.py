"""The mechanical checks of feature 010, and the one hook that runs them before the model.

`contracts/code-first.md` is normative. Every check here takes no argument a model chooses:
the joints come from the geometry, the masses and the properties from the package, so each
tool is a pure function of what was extracted and runs in the code-first pass - the pre-run
under lever 5 or lever 11 today, feature 008's pane default later - at no model round.

**`CODE_FIRST_CHECKS` is the only hook into the pre-run** (research R2.20). It names the
argument-free check tools in the order the pre-run calls them; `prerun.planned_calls` reads
it and plans `(name, {})` for each one the run did not withhold, after the interference
groups and before `check_standards`. A check that needed its own pre-run branch, or its own
memory of having run, would be a second copy of what feature 008 owns. The tuple grows with
the stories: empty after the foundational phase, then `check_joints` (US2), then
`check_mass_material` (US6) and `check_hygiene` (US7).
"""

from __future__ import annotations

__all__ = ["CODE_FIRST_CHECKS"]

CODE_FIRST_CHECKS: tuple[str, ...] = ()
"""The argument-free check tools the pre-run calls, in order. Each must be in
`registry.check_tools()` and take no parameter; `test_code_first_registration.py` holds it
to both."""
