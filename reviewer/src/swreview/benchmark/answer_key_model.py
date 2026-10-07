"""The answer key's format 2, data only (feature 014 `contracts/answer-key.md` 1 to 5).

The format's one definition (plan decision RF-1): the key and its entries, `Stamp`, the
reference elements and the table of reference-keyed checks of section 2.5, the check-pattern
grammar of section 3 with `pattern_covers`, and the load-time refusals that need nothing but the
model (section 4: rows 1, 3, 4, 5, 7 and row 6's grammar), which run whenever an `AnswerKey` is
built. It imports pydantic, the standard library and `findings.ReviewModel` only, so the case
generator writes keys through it without loading `benchmark/answer_key.py`, the key's one
reader, whose rows (2, 6's typo guard, 8 to 14) need the matcher, the question reader, the
checklist, the report's goals or the package. Nothing under `tools/`, `agent/`, `checks/` or
`benchmark/runner.py` imports either module: runs never read keys (FR-032).

Every refusal names its entry ("D-3 states no expected_status"), pydantic's own as well as the
model's rows, so a key the generator builds, with no loader there to name the entry, reads the
same as one the loader reads. This slice carries known defects and correct conditions: a key
holding one of section 2.1's four other lists is refused as an unknown field until US3 adds
their models here (T080).

An explicit JSON `null` for an optional field: `key_only`'s is refused naming the field (section
2.1: optional, `true` only), while `references`' on a check that is not reference-keyed and
`held_out_against`'s on a tuned-on entry read as absent, each field holding `None` either way.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    Field,
    PrivateAttr,
    StringConstraints,
    ValidationError,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

from swreview.findings import ReviewModel

KEY_FORMAT = 2
"""The one key format this build reads and the generator writes (section 2.1)."""

FORMAT_1_REFUSAL = (
    "written in key format 1; rewrite it in format 2 "
    "(specs/014-design-review-eval/contracts/answer-key.md)"
)
"""Section 2.1's refusal of a key with no `key_format`, one written for the scorer before
feature 014."""

Producer = Literal["code", "model"]
"""Who is expected to write the finding a known defect grades (SP-12, owner decision 16A),
decided by the package's evidence: `findings.Source`'s two values, written out here because
this module imports `findings.ReviewModel` alone; `test_answer_key.py` pins the two equal."""

ExpectedStatus = Literal["demonstrated", "suspected", "unresolved"]
"""The status a known defect is expected found with (owner decision 13A): a finding status,
never `checked_within_scope`, since a defect is never expected cleared."""

Tag = Literal["held_out", "tuned_on"]
"""Every entry's tag (owner decision 15A, FR-031): held out is recorded here and nowhere else."""

ReferenceKind = Literal["joint", "recess", "hole pair", "joint instances", "fit", "stack"]
"""The kinds of covered item a reference-keyed check names, as section 2.5's table names them."""

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A sha256 digest as `benchmark/digest.py` writes it: lower-case hex of 64 characters."""


class Stamp(ReviewModel):
    """What a held-out entry is held out against (section 2.2; owner decision 25A).

    `prompt` and `checklist` are `digest.sha256_of` over the raw bytes of the system prompt
    and the checklist; `tools` is `digest.canonical_sha256` of every tool description a design
    review can offer. `answer_key.current_stamp()` takes the current one; a stamp that no
    longer matches is listed as stale by the set summary, never refused at load (15A).
    """

    prompt: Sha256
    checklist: Sha256
    tools: Sha256


# --- section 3: check patterns ---------------------------------------------------------------

_CHECK_ID = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")
"""An exact check id: non-empty dot-separated segments of `[a-z0-9_]`, as every check id is."""

_FAMILY_SUFFIX = ".*"


def is_family(pattern: str) -> bool:
    """Whether `pattern` is written as a family, an exact id followed by `.*` (section 3)."""
    return pattern.endswith(_FAMILY_SUFFIX)


def _is_check_pattern(pattern: str) -> bool:
    """Section 3's grammar: an exact id, or an exact id followed by `.*`. So `*`, `x*`, `x.`,
    a `*` anywhere but a final `.*`, and an upper-case letter are no pattern."""
    return _CHECK_ID.fullmatch(pattern.removesuffix(_FAMILY_SUFFIX)) is not None


def pattern_covers(pattern: str, check: str) -> bool:
    """Whether the check pattern `pattern` covers `check` (section 3; `scoring.md` 2.1).

    An exact id covers itself alone. A family `x.*` covers every check that starts with `x`
    and a dot, at any depth, never `x` itself and never an id that merely starts with the
    same letters: `fastener.*` covers `fastener.head.fit`, not `fastener` or `fasteners.x`.
    The same rule reads a family `check`: `rms.*` covers `rms.sketches.*` and `rms.*`, whose
    ids are or lie under its own, which is how two families overlap (section 5). This is the
    one definition `benchmark/matching.py` reads.
    """
    if is_family(pattern):
        return check.startswith(pattern.removesuffix("*"))
    return check == pattern


# --- section 2.5: references -----------------------------------------------------------------

Reference = str | tuple[str, str, str]
"""One reference of a covered item: a fastener, hole or hole-instance id, or a dimension's
`(document_id, sheet, annotation)`."""


class DimensionReference(ReviewModel):
    """A drawing dimension, by the triple `tools/refs.resolve_dimension` matches on."""

    document_id: str
    sheet: str
    annotation: str

    def triple(self) -> tuple[str, str, str]:
        """The `(document_id, sheet, annotation)` a finding's `Dimension` input is read as
        (`scoring.md` 2.3)."""
        return (self.document_id, self.sheet, self.annotation)


class _ReferenceElement(ReviewModel):
    """One covered item of a reference-keyed entry, in its kind's shape (section 2.5).

    Its fields' types hold the shape; `shape_refusal` holds what they cannot (two distinct
    holes, one or more contributors), which the entry reports naming itself and the kind.
    """

    KIND: ClassVar[ReferenceKind]

    def reference_set(self) -> frozenset[Reference]:
        """The item's references as a set, roles never kept: what two elements of one entry
        are compared by (row 7), and what a finding's references must equal (`scoring.md`
        2.3)."""
        raise NotImplementedError

    def shape_refusal(self) -> str | None:
        """Why this element is not its kind's shape beyond its fields' types, or `None`."""
        return None


class JointReference(_ReferenceElement):
    """A fastener joint: the fastener and the hole it enters (the four fastener rules and
    `fastener.unsupported`)."""

    KIND: ClassVar[ReferenceKind] = "joint"

    fastener: str
    hole: str

    def reference_set(self) -> frozenset[Reference]:
        return frozenset({self.fastener, self.hole})


class RecessReference(_ReferenceElement):
    """A head recess, the hole instance `"<hole id>#<n>"` the joint map writes
    (`fastener.head_fit`)."""

    KIND: ClassVar[ReferenceKind] = "recess"

    recess: str

    def reference_set(self) -> frozenset[Reference]:
        return frozenset({self.recess})


class HolePairReference(_ReferenceElement):
    """Two distinct holes whose axes are compared (`hole.coaxiality`)."""

    KIND: ClassVar[ReferenceKind] = "hole pair"

    holes: list[str]

    def reference_set(self) -> frozenset[Reference]:
        return frozenset(self.holes)

    def shape_refusal(self) -> str | None:
        if len(self.holes) != 2 or len(set(self.holes)) != 2:
            return f"names {self.holes}, not two distinct holes"
        return None


class JointInstancesReference(_ReferenceElement):
    """The hole instances of one joint, `"<hole id>#<n>"` each (`hole.nominal_alignment`,
    `hole.position_stack`)."""

    KIND: ClassVar[ReferenceKind] = "joint instances"

    hole_instances: list[str]

    def reference_set(self) -> frozenset[Reference]:
        return frozenset(self.hole_instances)

    def shape_refusal(self) -> str | None:
        if not self.hole_instances or len(set(self.hole_instances)) != len(self.hole_instances):
            return f"names {self.hole_instances}, not one or more distinct hole instances"
        return None


class FitReference(_ReferenceElement):
    """A fit's two dimensions (`fit.size_only`). Roles are not compared, so a fit called with
    bore and shaft swapped names the same item (`scoring.md` 2.3)."""

    KIND: ClassVar[ReferenceKind] = "fit"

    bore: DimensionReference
    shaft: DimensionReference

    def reference_set(self) -> frozenset[Reference]:
        return frozenset({self.bore.triple(), self.shaft.triple()})

    def shape_refusal(self) -> str | None:
        if self.bore == self.shaft:
            return "names one dimension as both its bore and its shaft"
        return None


class StackReference(_ReferenceElement):
    """A stack's contributors and its target, if it names one (`stack.worst_case`)."""

    KIND: ClassVar[ReferenceKind] = "stack"

    contributors: list[DimensionReference]
    target: DimensionReference | None = None

    def reference_set(self) -> frozenset[Reference]:
        dimensions = [*self.contributors, *([self.target] if self.target is not None else [])]
        return frozenset(dimension.triple() for dimension in dimensions)

    def shape_refusal(self) -> str | None:
        if not self.contributors:
            return "names no contributor"
        return None


ReferenceElement = (
    JointReference
    | RecessReference
    | HolePairReference
    | JointInstancesReference
    | FitReference
    | StackReference
)
"""Any one covered item. Each kind's fields differ, so an element in a key file builds as the
one kind whose shape it has; row 7 then checks that kind is its check's."""

REFERENCE_KEYED_CHECKS: dict[str, ReferenceKind] = {
    "fastener.bottoming": "joint",
    "fastener.engagement": "joint",
    "fastener.thread_match": "joint",
    "fastener.head_clearance": "joint",
    "fastener.unsupported": "joint",
    "fastener.head_fit": "recess",
    "hole.coaxiality": "hole pair",
    "hole.nominal_alignment": "joint instances",
    "hole.position_stack": "joint instances",
    "fit.size_only": "fit",
    "stack.worst_case": "stack",
}
"""Section 2.5's eleven reference-keyed checks and the kind of item each names (FR-003,
FR-061): an entry on one of them names `references`, and an entry on any other names none."""


# --- section 2.2 and 2.3: the entries --------------------------------------------------------


class _Entry(ReviewModel):
    """The fields every entry has (section 2.2), and the one validator naming the entry in
    every refusal, pydantic's and the rows' alike."""

    ID_PREFIX: ClassVar[str]
    NOUN: ClassVar[str]

    id: str
    tag: Tag
    held_out_against: Stamp | None = None
    description: str

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
        for reason in entry._refusals():
            if reason is not None:
                raise ValueError(f"{entry.id} {reason}")
        return entry

    def _refusals(self) -> Iterator[str | None]:
        """Section 4's model rows over this entry, in the table's order, each the reason it
        refuses the entry or `None`; the first reason ends the build."""
        yield self._id_refusal()
        yield self._tag_refusal()
        yield self._description_refusal()

    def _id_refusal(self) -> str | None:
        """Row 3's prefix: the id is the list's prefix and a whole number from 1 (section 2.2).
        Uniqueness across the key is the key's (`AnswerKey._ids_are_unique`)."""
        if re.fullmatch(rf"{re.escape(self.ID_PREFIX)}[1-9][0-9]*", self.id) is None:
            return f"is not a {self.NOUN}'s id, {self.ID_PREFIX}<n> (answer-key.md 2.2)"
        return None

    def _tag_refusal(self) -> str | None:
        """Row 4's tag fields: `held_out_against` exactly when the entry is held out."""
        if self.tag == "held_out" and self.held_out_against is None:
            return "is held out and states no held_out_against {prompt, checklist, tools}"
        if self.tag == "tuned_on" and self.held_out_against is not None:
            return "is tuned on and states held_out_against, which only a held-out entry has"
        return None

    def _description_refusal(self) -> str | None:
        """Section 2.2: every entry says, in words, what it keys."""
        if not self.description.strip():
            return "states a blank description"
        return None


class _CheckedEntry(_Entry):
    """An entry on one check pattern, on its parts or documents, and, on a reference-keyed
    check, on the items it covers (section 2.3): a known defect or a correct condition."""

    check: str
    component_ids: list[str]
    document_ids: list[str]
    references: list[ReferenceElement] | None = None

    def _refusals(self) -> Iterator[str | None]:
        yield from super()._refusals()
        yield self._target_refusal()
        yield self._check_refusal()
        yield self._references_refusal()

    def _target_refusal(self) -> str | None:
        """Row 5 (FR-003): one of the two lists is non-empty."""
        if not self.component_ids and not self.document_ids:
            return "names no parts and no documents: component_ids and document_ids are both empty"
        return None

    def _check_refusal(self) -> str | None:
        """Row 6's grammar (section 3), and AK-4: a family over a reference-keyed check would
        put a joint's pass on one rule and its defect on another under one entry, so a pass
        would clear the defect, the sibling credit owner decision 19A removed."""
        if not _is_check_pattern(self.check):
            return f"checks {self.check!r}, neither a check id nor a family x.* (answer-key.md 3)"
        if is_family(self.check):
            covered = [
                keyed for keyed in REFERENCE_KEYED_CHECKS if pattern_covers(self.check, keyed)
            ]
            if covered:
                return (
                    f"checks the family {self.check}, which covers the reference-keyed "
                    f"{', '.join(covered)}: key each exactly (answer-key.md 3)"
                )
        return None

    def _references_refusal(self) -> str | None:
        """Row 7 (FR-003): references exactly on a reference-keyed check, non-empty, each of
        its check's kind and shape, and no two equal as the sets of their references."""
        kind = REFERENCE_KEYED_CHECKS.get(self.check)
        if kind is None:
            if self.references is not None:
                return (
                    f"names references, but {self.check} is not a reference-keyed check "
                    "(answer-key.md 2.5)"
                )
            return None
        if not self.references:
            return (
                f"names no references, but {self.check} is a {kind} check: name one {kind} "
                "element per item it covers (answer-key.md 2.5)"
            )
        for index, element in enumerate(self.references):
            if element.KIND != kind:
                return (
                    f"references.{index} is a {element.KIND} element, but {self.check} is a "
                    f"{kind} check (answer-key.md 2.5)"
                )
            shape = element.shape_refusal()
            if shape is not None:
                return f"references.{index}, a {kind} element, {shape}"
        sets = [element.reference_set() for element in self.references]
        if len(set(sets)) != len(sets):
            return (
                f"names two equal {kind} elements in references, compared as the sets of "
                "their references"
            )
        return None


class KnownDefect(_CheckedEntry):
    """A defect the review should find: who is expected to produce its finding, and with what
    status (section 2.3)."""

    ID_PREFIX: ClassVar[str] = "D-"
    NOUN: ClassVar[str] = "known defect"

    producer: Producer
    expected_status: ExpectedStatus


class CorrectCondition(_CheckedEntry):
    """A condition the review should not contradict, reported by its id (section 2.3; SP-5)."""

    ID_PREFIX: ClassVar[str] = "C-"
    NOUN: ClassVar[str] = "correct condition"


def _field_refusals(error: ValidationError) -> str:
    """Pydantic's refusals inside one entry as one clause: a missing field as `states no
    <field>` (row 4's wording), any other as `<field>: <message>`, joined by `; `."""
    clauses = []
    for line in error.errors(include_url=False):
        field = ".".join(str(part) for part in line["loc"])
        if line["type"] == "missing":
            clauses.append(f"states no {field}")
        else:
            clauses.append(f"{field}: {line['msg']}" if field else line["msg"])
    return "; ".join(clauses)


# --- section 2.1: the key --------------------------------------------------------------------


class AnswerKey(ReviewModel):
    """One package's answer key, format 2 (section 2.1)."""

    key_format: int
    package_id: str
    key_only: bool | None = None
    known_defects: list[KnownDefect] = Field(default_factory=list)
    correct_conditions: list[CorrectCondition] = Field(default_factory=list)

    _ids_unchecked: str | None = PrivateAttr(default=None)

    @property
    def ids_unchecked(self) -> str | None:
        """Why this key's ids were not resolved against a package, naming the package, or
        `None` when they were (section 6). Set only by the key loader, through
        `mark_ids_unchecked`, for a key-only key read with no package; never read from a file,
        where `ids_unchecked` is an unknown field."""
        return self._ids_unchecked

    def mark_ids_unchecked(self, reason: str) -> None:
        """Record why this key's ids were not checked (the loader's row 12)."""
        self._ids_unchecked = reason

    @field_validator("key_only")
    @classmethod
    def _key_only_is_true(cls, value: bool | None) -> bool | None:
        """`true` or absent (section 6): `false` and an explicit `null` are refused, the
        validator running only on a value the key states. A strict `bool`, since
        `Literal[True]` takes `1`."""
        if value is not True:
            raise ValueError("key_only is true or absent (answer-key.md 6)")
        return value

    @model_validator(mode="before")
    @classmethod
    def _format_2(cls, data: Any) -> Any:
        """Row 1's format, before any entry is read: a format 1 key would otherwise be named
        by its first entry's missing tag rather than by its format."""
        if isinstance(data, dict):
            if "key_format" not in data:
                raise ValueError(FORMAT_1_REFUSAL)
            if data["key_format"] != KEY_FORMAT:
                raise ValueError(
                    f"key_format is {data['key_format']!r}; this build reads key format "
                    f"{KEY_FORMAT}"
                )
        return data

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        """Row 3: an id names one entry across the key. It runs once every entry has built,
        each prefix checked by its entry."""
        seen: set[str] = set()
        for entry in self._entries():
            if entry.id in seen:
                raise ValueError(f"{entry.id} names two entries; an id is unique across the key")
            seen.add(entry.id)
        return self

    def holds_held_out(self) -> bool:
        """Whether some entry is tagged held out: the set's `held_out` flag, which the
        generator writes and `score` and the set summary check (plan decision RF-67)."""
        return any(entry.tag == "held_out" for entry in self._entries())

    def held_out_model_defect_ids(self) -> list[str]:
        """The held-out known defects the model is expected to produce, in key order: the
        held-out model-produced count the scorer and the set summary print is its length
        (plan decision RF-67)."""
        return [
            defect.id
            for defect in self.known_defects
            if defect.tag == "held_out" and defect.producer == "model"
        ]

    def _entries(self) -> list[_Entry]:
        return [*self.known_defects, *self.correct_conditions]
