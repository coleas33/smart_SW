"""The case file, data only (feature 014 `contracts/scripted-answers.md` 2.2 and 3).

A case's scripted answers: the words the engineer would type in the pane, each for the questions
on a checklist item (or on none) asked within some of the package's parts or documents, or for
the part-roles question. The format's one definition (plan decision INT-6): `CaseFile` and
`ScriptedAnswer`, strict, and the refusals of section 2.3 that need nothing but the model, which
run whenever a `CaseFile` is built: row 1's version and unknown fields, row 3 (ids `A-<n>`,
unique in the file, and each entry's shape) and row 4 (a blank answer). It imports pydantic, the
standard library and `findings.ReviewModel` only, so US5's case generator writes case files
through it without loading `benchmark/answers.py`, the one reader, which holds the driver and the
rows that need the set entry, the package, the checklist or the profile (rows 2 and 5 to 10).
Nothing under `tools/`, `agent/` or `checks/` imports this module.

Every refusal names its entry ("A-2 states a blank answer"), pydantic's own as well as the
model's rows, so a case file the generator builds, with no loader there to name the entry, reads
the same as one the loader reads.
"""

from __future__ import annotations

import re
from typing import Any, Self

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    ValidatorFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from swreview.findings import ReviewModel

CASE_FILE_VERSION = 1
"""The one case-file version this build reads and the generator writes (section 2.2)."""

_ENTRY_ID = re.compile(r"A-[1-9][0-9]*")
"""An entry's id: `A-` and a whole number from 1, as the answer key numbers its entries."""

_SHAPE_FIELDS = ("part_roles", "item", "ids")
"""The fields an entry states by its shape: `part_roles` alone, or `item` and `ids`."""


class ScriptedAnswer(ReviewModel):
    """One scripted answer (section 2.2): to the part-roles question (`part_roles: true`, no
    `item`, no `ids`), or to the questions on `item`, a checklist item or `null` for none, asked
    within `ids`, the package's component instances or documents.

    The shape is read from the fields the entry states (`model_fields_set`): an `item` stated
    `null` is a question naming no item, where an `item` left out is no item question at all.
    Dumped in its own shape: the other shape's fields, never stated, are left out.
    """

    id: str
    part_roles: bool = False
    """Stated `true` on the part-roles answer and left out otherwise; a strict `bool`, so `1`
    and `null` are refused, and row 3 refuses a stated `false`."""
    item: str | None = None
    ids: list[str] = Field(default_factory=list)
    answer: str
    """The engineer's words, sent trimmed as the pane trims them (`app.js:2162`)."""

    @model_validator(mode="wrap")
    @classmethod
    def _refuse_naming_the_entry(cls, data: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        """Build the entry, then run its rows; either kind of refusal is one `ValueError`
        starting with the entry's id. An entry with no id is left as pydantic names it."""
        try:
            entry = handler(data)
        except ValidationError as error:
            entry_id = data.get("id") if isinstance(data, dict) else None
            if not isinstance(entry_id, str):
                raise
            raise ValueError(f"{entry_id} {_field_refusals(error)}") from None
        for reason in (entry._id_refusal(), entry._shape_refusal(), entry._answer_refusal()):
            if reason is not None:
                raise ValueError(f"{entry.id} {reason}")
        return entry

    def _id_refusal(self) -> str | None:
        """Row 3's form: `A-<n>`. Uniqueness across the file is the file's
        (`CaseFile._ids_are_unique`)."""
        if _ENTRY_ID.fullmatch(self.id) is None:
            return "is not a scripted answer's id, A-<n> (scripted-answers.md 2.2)"
        return None

    def _shape_refusal(self) -> str | None:
        """Row 3's shape: `part_roles` stated `true` exactly when `item` and `ids` are left out,
        and otherwise `item` stated, a string or `null`, with a non-empty `ids`."""
        stated = self.model_fields_set
        if "part_roles" in stated:
            if not self.part_roles:
                return (
                    "states part_roles false: it is true, on the part-roles answer, or left out "
                    "(scripted-answers.md 2.2)"
                )
            named = [name for name in ("item", "ids") if name in stated]
            if named:
                return (
                    f"states part_roles and {' and '.join(named)}: the part-roles answer names "
                    "no item and no ids (scripted-answers.md 2.2)"
                )
            return None
        if "item" not in stated:
            return (
                "states neither part_roles nor item: an entry answers the part-roles question, "
                "or questions on an item, or on none with item null (scripted-answers.md 2.2)"
            )
        if "ids" not in stated:
            return "states no ids: an item answer names the parts or documents it answers for"
        if not self.ids:
            return "names no ids: ids is empty"
        return None

    def _answer_refusal(self) -> str | None:
        """Row 4: an answer blank once trimmed, which the pane's Send never sends and its route
        refuses (`chat/server.py:1417-1426`)."""
        if not self.answer.strip():
            return "states a blank answer"
        return None

    @model_serializer(mode="wrap")
    def _dump_in_its_own_shape(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for name in _SHAPE_FIELDS:
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data


class CaseFile(ReviewModel):
    """One package's case file (section 2.2)."""

    case_file_version: int
    package_id: str
    answers: list[ScriptedAnswer]

    @model_validator(mode="before")
    @classmethod
    def _version_1(cls, data: Any) -> Any:
        """Row 1's version, before any entry is read: a file of another version is named by
        its version, not by its first entry's shape."""
        if isinstance(data, dict) and "case_file_version" in data:
            version = data["case_file_version"]
            if version != CASE_FILE_VERSION:
                raise ValueError(
                    f"case_file_version is {version!r}; this build reads case file version "
                    f"{CASE_FILE_VERSION}"
                )
        return data

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        """Row 3: an id names one entry in the file. It runs once every entry has built, each
        id's form checked by its entry."""
        seen: set[str] = set()
        for answer in self.answers:
            if answer.id in seen:
                raise ValueError(f"{answer.id} names two entries; an id is unique in the file")
            seen.add(answer.id)
        return self


def _field_refusals(error: ValidationError) -> str:
    """Pydantic's refusals inside one entry as one clause: a missing field as `states no
    <field>`, any other as `<field>: <message>`, joined by `; `. The answer key's model words
    its entries' refusals the same way (`answer_key_model._field_refusals`); this module imports
    no other `swreview` module, so the clause is written here."""
    clauses = []
    for line in error.errors(include_url=False):
        field = ".".join(str(part) for part in line["loc"])
        if line["type"] == "missing":
            clauses.append(f"states no {field}")
        else:
            clauses.append(f"{field}: {line['msg']}" if field else line["msg"])
    return "; ".join(clauses)
