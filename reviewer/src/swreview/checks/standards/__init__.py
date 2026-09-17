"""Standards checks: the release checklist, run over the evidence package.

The sixteen checks of `specs/006-standards-check/contracts/rules.md`, evaluated from the
package alone with no language model on any path (FR-045). Every company-specific value the
checks compare against arrives from the standards profile, which `profile.py` is the single
owner of and which is **not** in this repository (FR-001, FR-002).
"""

from __future__ import annotations
