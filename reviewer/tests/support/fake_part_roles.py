"""A stand-in for 013's part roles, as the drawing check reads them (013 lane D).

Feature 013's classifier - `checks/part_roles.py`, `classify_parts` and its `PartRoles` (lane P,
T018) - tells each part or assembly document custom, bought or unclear. The drawing check reads
the result through exactly two members of the contract (`contracts/part-roles.md` section 4):

- `graded(document_id)` - false exactly for a bought document other than the root, and true for
  an id the roles do not hold (errors fail toward grading);
- `note_for(document_id)` - "may be a bought part: ...; asked in {ER id}" for an unclear document
  while the part-roles question is open, and `None` otherwise (the absent state, the zero-match
  guard, a custom document, an answered one).

`FakePartRoles` plays those two members from a table, so lane D's tests build against the
contract before lane P's classifier lands. `test_drawing_states.py` also runs the real classifier
through the same checks once it is importable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

__all__ = ["FakePartRoles", "Role", "UNCLEAR_NOTE"]

Role = Literal["custom", "bought", "unclear"]

UNCLEAR_NOTE = (
    "may be a bought part: neither the part-number convention nor a bought-part rule decides it; "
    "asked in ER-001"
)
"""The note an unclear document carries while the question is open, in the contract's shape."""


@dataclass(frozen=True)
class FakePartRoles:
    """`PartRoles` as the drawing check reads it: `graded` and `note_for`, from a table."""

    roles: Mapping[str, Role] = field(default_factory=dict)
    """Document id to role; an id not here is unknown, and so graded."""
    root: str | None = None
    """The review's root document: always graded, whatever its role (the root rule)."""
    question_open: bool = True
    """Whether the part-roles question is open, so an unclear document carries its note; false
    plays the absent state and the zero-match guard, where no note is written."""

    def graded(self, document_id: str) -> bool:
        return self.roles.get(document_id) != "bought" or document_id == self.root

    def note_for(self, document_id: str) -> str | None:
        if self.question_open and self.roles.get(document_id) == "unclear":
            return UNCLEAR_NOTE
        return None
