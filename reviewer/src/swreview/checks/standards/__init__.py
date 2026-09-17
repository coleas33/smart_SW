"""Standards checks: the release checklist, run over the evidence package.

The sixteen checks of `specs/006-standards-check/contracts/rules.md`, evaluated from the
package alone with no language model on any path (FR-045). Every company-specific value the
checks compare against arrives from the standards profile, which `profile.py` is the single
owner of and which is **not** in this repository (FR-001, FR-002).

Importing this package is what **completes the catalogue**: `registry.py` holds the sixteen
checks and each evaluator module binds its own with `@bind`, so the evaluators import the
catalogue and not the reverse, and importing them all is what fills in the `fn` half of the
rule invariant.
"""

from __future__ import annotations

from swreview.checks.standards import assembly, document, drawing, part  # noqa: F401
