"""Custom, bought or unclear: the one reading of what each part of a review is (feature 013 US1).

`specs/013-engineer-first-review/contracts/part-roles.md` is normative. One pure function,
`classify_parts`, reads the package and the standards profile and says, for every part and
assembly document, whether it is custom (designed here), bought (catalogue, vendor, library)
or unclear, with a reason in words. It is computed once per review, attached to the review's
context under `PART_ROLES_ATTRIBUTE`, and read by every consumer: modelling-practice and
hygiene checks grade custom and unclear documents only.

**Votes, not a first match** (section 2, amended 2026-09-26 from the owner's guidance and the
local census). With a version 4 profile each signal votes custom or bought with a strength
fixed here - the profile only names what each signal looks for - and the decision reads the
votes: strong votes that all agree, with no medium vote against, win; strong votes that
conflict leave the part unclear; with no strong vote a role needs two agreeing votes, one of
them medium, and none against; no vote at all is unclear. A child of a bought assembly
inherits bought unless its own evidence says custom. The engineer's answer decides over all.

**Unknown is never a match** (constitution Principle I): a document whose properties were not
read casts no property vote and says so; a document with no path has no name to read; a
Toolbox flag that is false is not evidence. An unknown document id is graded.

**No profile value leaves this module.** Every sentence below names a signal ("a bought-parts
folder"), never the folder, shape, property or value that matched, because these words reach
the model provider through the digest and the brief (feature 006 FR-034). Every model-facing
sentence of the contract is a constant here, in one table (section 3).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from swreview.checks.questions import QuestionSpec
from swreview.checks.result import CheckResult
from swreview.ir.models import ComponentInstance, Document, EvidencePackage
from swreview.report.names import and_list, plural

if TYPE_CHECKING:
    from swreview.checks.standards.profile import PartRolesSection, StandardsProfile
    from swreview.report.session import EvidenceRequest


class _Standards(NamedTuple):
    """The standards helpers the signals read (`contracts/part-roles-profile.md` section 2)."""

    prefix_list: Any
    normalize: Callable[[str], str]
    name_matches: Callable[..., bool]
    property_key: Callable[[str], str]
    properties_gap: Callable[..., Any]


@cache
def _standards() -> _Standards:
    """The standards helpers, imported when first used rather than at the top.

    Importing any module of `checks/standards/` completes that package's catalogue, which
    reaches the rules runner and the pre-run, and those import the tools that read this
    module (`prerun._deferred` says it once). Loading them here, once, keeps this module
    importable from anywhere - the runner, the tools, the drawing check - with no deferral of
    their own.
    """
    from swreview.checks.standards.library import PrefixList, normalize
    from swreview.checks.standards.profile import name_matches, property_key
    from swreview.checks.standards.results import properties_gap

    return _Standards(PrefixList, normalize, name_matches, property_key, properties_gap)


__all__ = [
    "BOUGHT_PARTS_CHECK",
    "BOUGHT_PARTS_LABEL",
    "MAYBE_BOUGHT_CHECK",
    "MAYBE_BOUGHT_LABEL",
    "PART_ROLES_ATTRIBUTE",
    "PART_ROLES_CHECK",
    "PART_ROLES_LABEL",
    "Decision",
    "PartRole",
    "PartRoles",
    "Role",
    "RolesAnswer",
    "Signal",
    "State",
    "Strength",
    "Vote",
    "answered_roles",
    "bought_parts_sentence",
    "classify_parts",
    "guard_sentence",
    "maybe_bought_sentence",
    "note_unclear",
    "roles_question",
    "unmatched_sentence",
]

PART_ROLES_ATTRIBUTE = "part_roles"
"""The context attribute a review's roles ride on (section 5). Defined here, where the type
is, so the readers (lane P's tools) and the writer (`start_review`, lane S) share one name;
`tools/registry.py` re-exports it beside `STANDARDS_RUN_ATTRIBUTE`."""

Role = Literal["custom", "bought", "unclear"]
Voted = Literal["custom", "bought"]
State = Literal["configured", "convention_only", "absent"]
Strength = Literal["strong", "medium", "weak"]
Signal = Literal[
    "toolbox",
    "bought_path",
    "switch",
    "vendor_property",
    "distributor_block",
    "catalogue_number",
    "bought_number",
    "custom_prefix",
    "sparse",
    "same_name_drawing",
]
Decision = Literal[
    "answer",
    "strong",
    "agreement",
    "inherited",
    "conflict",
    "too_little",
    "no_evidence",
    "toolbox",
    "convention",
    "not_told_apart",
]

MODEL_KINDS: tuple[str, ...] = ("part", "assembly")
"""What is classified; a drawing never is."""

# --- 1. the words: every model-facing sentence of the contract (section 3) --------------------

SIGNALS: tuple[tuple[Signal, Voted, Strength, str], ...] = (
    ("toolbox", "bought", "strong", "a Toolbox part"),
    ("bought_path", "bought", "strong", "a bought-parts folder"),
    ("switch", "bought", "strong", "marked bought by its make-or-buy property"),
    ("switch", "custom", "weak", "marked made here by its make-or-buy property"),
    ("vendor_property", "bought", "strong", "a vendor property"),
    ("distributor_block", "bought", "strong", "a distributor's property block"),
    ("catalogue_number", "bought", "medium", "a catalogue number"),
    ("bought_number", "bought", "medium", "a bought part-number range"),
    ("custom_prefix", "custom", "medium", "the company's part-number prefix"),
    ("sparse", "custom", "weak", "few properties"),
    ("same_name_drawing", "custom", "weak", "a drawing of the same name beside it"),
)
"""Each signal, the role it votes, its strength and its words, in section 2.1's order. The
strength is this feature's decision, not the profile's (research R2.4, "Revised")."""

STRENGTHS: Mapping[tuple[Signal, Voted], Strength] = {
    (signal, role): strength for signal, role, strength, _ in SIGNALS
}
SIGNAL_WORDS: Mapping[tuple[Signal, Voted], str] = {
    (signal, role): words for signal, role, _, words in SIGNALS
}

ANSWER_REASONS: Mapping[Voted, str] = {
    "bought": "you answered it is bought",
    "custom": "you answered it is ours",
}
AGAINST = "{reason}; against it: {against}"
INHERITED = "inside a bought assembly"
CONFLICT = "the signals disagree: bought - {bought}; custom - {custom}"
TOO_LITTLE = "too little evidence: only {words}"
NO_SIGNAL = "no signal decides it"
TOOLBOX = SIGNAL_WORDS[("toolbox", "bought")]
CONVENTION = "follows the part-number convention"
NO_CONVENTION_RULE = "neither the part-number convention nor a bought-part rule decides it"
NO_PATH_TAIL = "; no path was recorded"
UNREAD_TAIL = "; its properties were not read"
ROOT_LABEL = "looks bought ({reason}); graded because it is the document under review"
NOTE = "may be a bought part: {reason}; asked in {request_id}"

STATE_NO_PROFILE = "no standards profile is attached"
STATE_REFUSED = "the standards profile was refused ({refusal})"
STATE_NO_CONVENTION = (
    "the standards profile has no part_roles section and names no part-number convention"
)

GUARD_CONFIGURED = (
    "no part-role rule decided any of the {count} documents; check the profile's part_roles section"
)
GUARD_CONVENTION = (
    "the part-number convention matched none of the {count} documents; check part_number.pattern"
)

BOUGHT_PARTS_CHECK = "coverage.prerun.bought_parts"
MAYBE_BOUGHT_CHECK = "coverage.prerun.maybe_bought"
PART_ROLES_CHECK = "coverage.prerun.part_roles"
"""The coverage rows of section 7 and the zero-match guard: the pre-run's prefix
(`prerun.PRERUN_CHECK_PREFIX`) and a family, spelled out here because this module does not
import the pre-run. The summary reads the first two back (`scope.document_ids`)."""
ROW_CHECKS: tuple[str, ...] = (BOUGHT_PARTS_CHECK, MAYBE_BOUGHT_CHECK, PART_ROLES_CHECK)
"""Every coverage check the part roles write: what `start_review` and a regrade withdraw
before they record the rows again, so a restated row replaces the earlier one."""

BOUGHT_PARTS_LABEL = "bought parts"
MAYBE_BOUGHT_LABEL = "parts that may be bought"
PART_ROLES_LABEL = "part roles"
"""What the pre-run digest calls each row (`NotEvaluated.label`)."""

BOUGHT_LINE = "{parts} not graded for modelling practice or hygiene (bought): {names}"
MAYBE_LINE = (
    "{files} graded; each finding says it may be bought; asked in {request_id}; do not ask for "
    "their drawings"
)
NOT_TOLD_APART = "Bought parts were not told apart: {reason}"
NOT_TOLD_APART_TOOLBOX = (
    "Bought parts were not told apart: {reason}; Toolbox parts were not graded: {names}"
)
WITHDRAWN_TAIL = "; withdrew {ids}"
"""Appended to the restated bought-parts sentence after the part-roles answer withdrew
findings (section 9: "the bought-parts row is restated naming the withdrawn ids")."""
UNMATCHED_ONE = "{piece} names none of the listed parts"
UNMATCHED_MANY = "{pieces} name none of the listed parts"
BOUGHT_REFUSAL = "a bought part: not graded for modelling practice"
"""What `part_documents` answers for a bought document named by id (section 6)."""

LIST_LIMIT = 10
AND_MORE = "and {count} more"

QUESTION_KEY = "part_roles"
QUESTION = (
    "Are these bought parts? Until you answer, they are graded for modelling practice and hygiene."
)
OPTION_ALL = "All bought"
OPTION_NONE = "None bought"
WHAT = "Parts no rule tells apart: {names}"
WHY = (
    "Bought parts are not graded for modelling practice or hygiene. Answer to regrade this "
    "review now."
)

_TOKEN_SEPARATORS = re.compile(r"[,\s]+")
"""A file name's tokens: its stem split at commas and whitespace (section 2.1)."""
_ANSWER_SEPARATORS = re.compile(r"[,;\r\n]+")
"""A typed answer's pieces: split at commas, semicolons and line breaks (section 9)."""


# --- 2. the records (section 4) --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Vote:
    """One signal's vote: which role it names, and how strongly."""

    signal: Signal
    role: Voted
    strength: Strength

    @property
    def words(self) -> str:
        return SIGNAL_WORDS[(self.signal, self.role)]


@dataclass(frozen=True, slots=True)
class PartRole:
    """What one document is, why, and whether it is graded."""

    document_id: str
    role: Role
    decision: Decision
    votes: tuple[Vote, ...]
    """The `configured` state's votes, in section 2.1's order; empty in the other states."""
    properties_read: bool
    reason: str
    graded: bool
    """`role != "bought"`, or the document is the review's root."""
    label: str | None = None
    """The root rule's label when the root is decided bought, else `None`."""


@dataclass(frozen=True)
class PartRoles:
    """Every document's role, and the state the classification was made in."""

    state: State
    state_reason: str | None
    by_document: Mapping[str, PartRole]
    guard_fired: bool
    asked_in: str | None = None
    """The part-roles question's request id once `start_review` has recorded it."""

    def graded(self, document_id: str) -> bool:
        """Whether modelling-practice and hygiene checks grade it; an unknown id is graded,
        because an error must fail toward grading, never toward silence."""
        role = self.by_document.get(document_id)
        return True if role is None else role.graded

    def bought(self) -> tuple[PartRole, ...]:
        """The documents not graded because bought, in package order."""
        return tuple(role for role in self.by_document.values() if not role.graded)

    def unclear(self) -> tuple[PartRole, ...]:
        """The documents no rule decided, in package order."""
        return tuple(role for role in self.by_document.values() if role.role == "unclear")

    def asking(self, request_id: str) -> PartRoles:
        """A copy that knows the question is open under `request_id`."""
        return replace(self, asked_in=request_id)

    def note_for(self, document_id: str) -> str | None:
        """The note an unclear document's findings carry while the question is open, else
        `None` (the absent state, the guard, a decided document, or no question yet)."""
        role = self.by_document.get(document_id)
        if (
            self.asked_in is None
            or self.state == "absent"
            or self.guard_fired
            or role is None
            or role.role != "unclear"
        ):
            return None
        return NOTE.format(reason=role.reason, request_id=self.asked_in)


@dataclass(frozen=True, slots=True)
class RolesAnswer:
    """What the engineer's answer to the part-roles question says (section 9)."""

    answers: Mapping[str, Voted]
    """Every listed document, custom or bought."""
    unmatched: tuple[str, ...] = ()
    """The typed pieces that named none of the listed parts, as typed (trimmed)."""


# --- 3. what the signals read (section 2.1) -----------------------------------------------------


@dataclass
class _Facts:
    """The package, indexed once for every document's signals."""

    package: EvidencePackage
    instances: dict[str, list[ComponentInstance]] = field(default_factory=dict)
    by_id: dict[str, ComponentInstance] = field(default_factory=dict)
    unread: frozenset[str] = frozenset()
    candidates: frozenset[str] = frozenset()
    drawing_stems: frozenset[str] = frozenset()

    @classmethod
    def of(cls, package: EvidencePackage) -> _Facts:
        properties_gap = _standards().properties_gap
        instances: dict[str, list[ComponentInstance]] = {}
        for component in package.components:
            instances.setdefault(component.document_id, []).append(component)
        return cls(
            package=package,
            instances=instances,
            by_id={component.id: component for component in package.components},
            unread=frozenset(
                document.document_id
                for document in package.documents
                if properties_gap(package, document.document_id) is not None
            ),
            candidates=frozenset(row.document_id for row in package.drawing_candidates),
            drawing_stems=frozenset(
                _stem_key(document.path)
                for document in package.documents
                if document.kind == "drawing" and document.path.strip()
            ),
        )

    def toolbox(self, document: Document) -> bool:
        return any(item.is_toolbox for item in self.instances.get(document.document_id, ()))

    def configurations_used(self, document: Document) -> list[str]:
        """The configurations its instances reference, in package order, each once, or its
        active configuration when no instance references it."""
        used = list(
            dict.fromkeys(
                item.referenced_configuration
                for item in self.instances.get(document.document_id, ())
            )
        )
        return used or [document.active_configuration]

    def configuration_names(self, document: Document) -> list[str]:
        return list(dict.fromkeys([*document.configurations, *self.configurations_used(document)]))

    def same_name_drawing(self, document: Document) -> bool:
        return document.document_id in self.candidates or (
            bool(document.path.strip()) and _stem_key(document.path) in self.drawing_stems
        )

    def under_bought(self, document_id: str, bought: set[str]) -> bool:
        """Every instance of it sits under an instance of a bought document."""
        owned = self.instances.get(document_id)
        if not owned:
            return False
        return all(self._has_bought_ancestor(item, bought) for item in owned)

    def _has_bought_ancestor(self, instance: ComponentInstance, bought: set[str]) -> bool:
        seen: set[str] = {instance.id}
        parent_id = instance.parent_id
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            parent = self.by_id.get(parent_id)
            if parent is None:
                return False
            if parent.document_id in bought:
                return True
            parent_id = parent.parent_id
        return False


def _file_name(document: Document) -> str | None:
    """The last segment of the document's path, or `None` when it has no path."""
    path = document.path.strip()
    if not path:
        return None
    return re.split(r"[\\/]", path)[-1] or None


def _stem(file_name: str) -> str:
    return file_name.rsplit(".", 1)[0] if "." in file_name else file_name


def _stem_key(path: str) -> str:
    """A path without its extension, spelled one way (case and separators ignored)."""
    normalized = _standards().normalize(path)
    folder, _, name = normalized.rpartition("/")
    return f"{folder}/{_stem(name)}"


def _levels(document: Document, facts: _Facts) -> list[Mapping[str, str]]:
    """The property levels a document is read at: its configurations', then its own."""
    return [
        *(document.config_properties.get(name, {}) for name in facts.configurations_used(document)),
        document.custom_properties,
    ]


def _values(level: Mapping[str, str], name: str) -> list[str]:
    """Every non-blank value `level` holds under `name`, compared ignoring case and spaces."""
    key = _standards().property_key
    wanted = key(name)
    return [
        value.strip()
        for written, value in level.items()
        if key(written) == wanted and value.strip()
    ]


def _values_anywhere(levels: Sequence[Mapping[str, str]], name: str) -> list[str]:
    return [value for level in levels for value in _values(level, name)]


def _present(levels: Sequence[Mapping[str, str]], names: Iterable[str]) -> bool:
    """Whether any level carries any of `names`, valued or not."""
    key = _standards().property_key
    wanted = {key(name) for name in names}
    return any(key(name) in wanted for level in levels for name in level)


class _Reader:
    """The version 4 section, prepared once, reading one document's votes at a time."""

    def __init__(self, profile: StandardsProfile, section: PartRolesSection) -> None:
        self.section = section
        self.pattern = profile.part_number.pattern
        self.part_number = profile.hygiene.part_number_property if profile.hygiene else ""
        self.bought_prefixes = _standards().prefix_list.from_entries(
            section.bought_prefixes, profile.vault_root
        )
        self.folder_names = {name.strip().casefold() for name in section.bought_folder_names}
        self.bought_values = {value.strip().casefold() for value in section.switch.bought_values}
        self.custom_values = {value.strip().casefold() for value in section.switch.custom_values}
        self.sparse_keys = [
            *section.vendor_properties,
            *section.distributor_block.properties,
            *section.detail_properties,
        ]

    def votes(self, document: Document, facts: _Facts) -> tuple[Vote, ...]:
        read = document.document_id not in facts.unread
        levels = _levels(document, facts) if read else []
        name = _file_name(document)
        cast: set[tuple[Signal, Voted]] = set()

        if facts.toolbox(document):
            cast.add(("toolbox", "bought"))
        if name is not None and self._in_bought_folder(document.path):
            cast.add(("bought_path", "bought"))
        if read:
            cast.update(("switch", role) for role in self._switch(levels))
            if any(_values_anywhere(levels, key) for key in self.section.vendor_properties):
                cast.add(("vendor_property", "bought"))
            if self._distributor_block(levels):
                cast.add(("distributor_block", "bought"))
        if self._catalogue_number(document, facts, name, levels):
            cast.add(("catalogue_number", "bought"))
        numbers = self._numbers(name, levels)
        if _starts_with_any(numbers, self.section.bought_number_prefixes):
            cast.add(("bought_number", "bought"))
        if _starts_with_any(numbers, self.section.custom_prefixes):
            cast.add(("custom_prefix", "custom"))
        if read and self.sparse_keys and not _present(levels, self.sparse_keys):
            cast.add(("sparse", "custom"))
        if name is not None and facts.same_name_drawing(document):
            cast.add(("same_name_drawing", "custom"))

        return tuple(
            Vote(signal, role, strength)
            for signal, role, strength, _ in SIGNALS
            if (signal, role) in cast
        )

    def _in_bought_folder(self, path: str) -> bool:
        if self.bought_prefixes.matching(path):
            return True
        folders = re.split(r"[\\/]", path.strip())[:-1]
        return any(folder.strip().casefold() in self.folder_names for folder in folders)

    def _switch(self, levels: Sequence[Mapping[str, str]]) -> set[Voted]:
        """The configurations' values, or the document's when none carries the property;
        each distinct value votes (section 2.1)."""
        name = self.section.switch.property
        if not name.strip():
            return set()
        *configurations, own = levels
        values = _values_anywhere(configurations, name) or _values(own, name)
        roles: set[Voted] = set()
        for value in values:
            key = value.casefold()
            if key in self.bought_values:
                roles.add("bought")
            if key in self.custom_values:
                roles.add("custom")
        return roles

    def _distributor_block(self, levels: Sequence[Mapping[str, str]]) -> bool:
        block = self.section.distributor_block
        if not block.properties:
            return False
        valued = sum(1 for key in block.properties if _values_anywhere(levels, key))
        return valued >= block.min_valued

    def _catalogue_number(
        self,
        document: Document,
        facts: _Facts,
        name: str | None,
        levels: Sequence[Mapping[str, str]],
    ) -> bool:
        shapes = self.section.catalogue_numbers.shapes
        if not shapes:
            return False
        candidates = [
            *(_TOKEN_SEPARATORS.split(_stem(name)) if name is not None else ()),
            *facts.configuration_names(document),
            *(
                value
                for key in self.section.catalogue_numbers.properties
                for value in _values_anywhere(levels, key)
            ),
        ]
        return any(
            _standards().name_matches(shape.strip(), candidate, wildcards=True)
            for shape in shapes
            for candidate in candidates
            if candidate
        )

    def _numbers(self, name: str | None, levels: Sequence[Mapping[str, str]]) -> list[str]:
        """Its file name when it follows the convention (or there is none), and its
        part-number property's values at every level (section 2.1)."""
        numbers: list[str] = []
        if name is not None and (not self.pattern or _standards().name_matches(self.pattern, name)):
            numbers.append(name)
        if self.part_number.strip():
            numbers.extend(_values_anywhere(levels, self.part_number))
        return numbers


def _starts_with_any(numbers: Sequence[str], prefixes: Sequence[str]) -> bool:
    wanted = [prefix.strip().casefold() for prefix in prefixes if prefix.strip()]
    return any(
        number.strip().casefold().startswith(prefix) for number in numbers for prefix in wanted
    )


# --- 4. the decision (section 2.2) ---------------------------------------------------------------


def _words(votes: Iterable[Vote]) -> str:
    return and_list([vote.words for vote in votes])


def _decide(votes: tuple[Vote, ...]) -> tuple[Role, Decision, str]:
    strong = [vote for vote in votes if vote.strength == "strong"]
    if strong:
        sides = {vote.role for vote in strong}
        if len(sides) == 1:
            (winner,) = sides
            if not any(vote.role != winner and vote.strength == "medium" for vote in votes):
                return winner, "strong", _winning_reason(votes, winner)
        return "unclear", "conflict", _conflict_reason(votes)
    if not votes:
        return "unclear", "no_evidence", NO_SIGNAL
    for side in ("custom", "bought"):
        agreeing = [vote for vote in votes if vote.role == side]
        if (
            len(agreeing) >= 2
            and any(vote.strength == "medium" for vote in agreeing)
            and len(agreeing) == len(votes)
        ):
            return side, "agreement", _words(agreeing)
    if len({vote.role for vote in votes}) == 2:
        return "unclear", "conflict", _conflict_reason(votes)
    return "unclear", "too_little", TOO_LITTLE.format(words=_words(votes))


def _winning_reason(votes: Sequence[Vote], winner: Voted) -> str:
    reason = _words(vote for vote in votes if vote.role == winner)
    against = [vote for vote in votes if vote.role != winner]
    return AGAINST.format(reason=reason, against=_words(against)) if against else reason


def _conflict_reason(votes: Sequence[Vote]) -> str:
    return CONFLICT.format(
        bought=_words(vote for vote in votes if vote.role == "bought"),
        custom=_words(vote for vote in votes if vote.role == "custom"),
    )


def _tails(reason: str, document: Document, read: bool) -> str:
    """The reason, and what it could not read (section 3)."""
    if _file_name(document) is None:
        reason += NO_PATH_TAIL
    if not read:
        reason += UNREAD_TAIL
    return reason


# --- 5. the classifier (section 1) ----------------------------------------------------------


@dataclass(frozen=True)
class _Own:
    """A document's decision on its own evidence, before answers and inheritance."""

    role: Role
    decision: Decision
    votes: tuple[Vote, ...]
    reason: str


def classify_parts(
    package: EvidencePackage,
    profile: StandardsProfile | None,
    answers: Mapping[str, Voted] | None = None,
    *,
    profile_refusal: str | None = None,
) -> PartRoles:
    """Every part and assembly document of `package`: custom, bought or unclear, and why.

    Pure: it reads its arguments only. `answers` are the engineer's answers to the part-roles
    question in this session (section 9); `profile_refusal` is the loader's reason when a
    profile was configured and refused, so the absent state can say why.
    """
    facts = _Facts.of(package)
    documents = [document for document in package.documents if document.kind in MODEL_KINDS]
    state, state_reason = _state(profile, profile_refusal)
    reader = (
        _Reader(profile, profile.part_roles)
        if state == "configured" and profile is not None and profile.part_roles is not None
        else None
    )
    own = {
        document.document_id: _own(document, facts, profile, reader, state_reason)
        for document in documents
    }
    decided_by_evidence = any(item.role != "unclear" for item in own.values())
    given = dict(answers or {})

    decided: dict[str, tuple[Role, Decision, str]] = {}
    for document in documents:
        item = own[document.document_id]
        answer = given.get(document.document_id)
        if answer is not None:
            decided[document.document_id] = (answer, "answer", ANSWER_REASONS[answer])
        else:
            decided[document.document_id] = (item.role, item.decision, item.reason)
    if state == "configured":
        _inherit(documents, facts, own, given, decided)

    root_id = package.design.root_assembly_document_id
    by_document: dict[str, PartRole] = {}
    for document in documents:
        role, decision, reason = decided[document.document_id]
        read = document.document_id not in facts.unread
        if decision not in ("answer", "not_told_apart"):
            reason = _tails(reason, document, read)
        is_root = document.document_id == root_id
        by_document[document.document_id] = PartRole(
            document_id=document.document_id,
            role=role,
            decision=decision,
            votes=own[document.document_id].votes,
            properties_read=read,
            reason=reason,
            graded=role != "bought" or is_root,
            label=ROOT_LABEL.format(reason=reason) if is_root and role == "bought" else None,
        )

    return PartRoles(
        state=state,
        state_reason=state_reason,
        by_document=by_document,
        guard_fired=state != "absent" and bool(documents) and not decided_by_evidence,
    )


def _state(
    profile: StandardsProfile | None, profile_refusal: str | None
) -> tuple[State, str | None]:
    if profile is None:
        if profile_refusal:
            return "absent", STATE_REFUSED.format(refusal=profile_refusal)
        return "absent", STATE_NO_PROFILE
    if profile.part_roles is not None and not profile.part_roles.signals_unused:
        return "configured", None
    # A section with every signal off - the upgrade helper's output before the owner fills it -
    # decides nothing a version 3 profile would not: read as the file it was proposed from.
    if profile.part_number.pattern:
        return "convention_only", None
    return "absent", STATE_NO_CONVENTION


def _own(
    document: Document,
    facts: _Facts,
    profile: StandardsProfile | None,
    reader: _Reader | None,
    state_reason: str | None,
) -> _Own:
    """One document on its own evidence, in the state the profile allows (sections 2.2, 2.4).

    `reader` is the `configured` state's; without it a profile with a convention is the
    `convention_only` table, and anything else the `absent` state's two rows.
    """
    if reader is not None:
        votes = reader.votes(document, facts)
        role, decision, reason = _decide(votes)
        return _Own(role, decision, votes, reason)
    if facts.toolbox(document):
        return _Own("bought", "toolbox", (), TOOLBOX)
    if profile is not None and profile.part_number.pattern:
        name = _file_name(document)
        if name is not None and _standards().name_matches(profile.part_number.pattern, name):
            return _Own("custom", "convention", (), CONVENTION)
        return _Own("unclear", "no_evidence", (), NO_CONVENTION_RULE)
    return _Own("unclear", "not_told_apart", (), state_reason or STATE_NO_PROFILE)


def _inherit(
    documents: Sequence[Document],
    facts: _Facts,
    own: Mapping[str, _Own],
    answers: Mapping[str, Voted],
    decided: dict[str, tuple[Role, Decision, str]],
) -> None:
    """Section 2.3: a child of a bought assembly is bought unless its own evidence says
    custom; repeated until nothing changes, so it passes through every level."""
    changed = True
    while changed:
        changed = False
        bought = {key for key, (role, _, _) in decided.items() if role == "bought"}
        for document in documents:
            key = document.document_id
            item = own[key]
            if (
                key in answers
                or decided[key][0] != "unclear"
                or any(vote.role == "custom" and vote.strength != "weak" for vote in item.votes)
                or not facts.under_bought(key, bought)
            ):
                continue
            decided[key] = ("bought", "inherited", INHERITED)
            changed = True


# --- 6. the consumers' helpers (sections 4, 6, 7, 8, 9) -------------------------------------


def note_unclear(result: CheckResult, note: str | None) -> CheckResult:
    """`result` with `note` appended to its coverage limits, or unchanged when there is none."""
    if note is None or note in result.coverage_limits:
        return result
    return replace(result, coverage_limits=[*result.coverage_limits, note])


def _listed(items: Sequence[str]) -> str:
    """The first ten, then "and {n} more" (sections 7 and 8)."""
    shown = list(items[:LIST_LIMIT])
    if len(items) > LIST_LIMIT:
        shown.append(AND_MORE.format(count=len(items) - LIST_LIMIT))
    return ", ".join(shown)


def _file_names(package: EvidencePackage) -> dict[str, str]:
    return {document.document_id: document.file_name for document in package.documents}


def bought_parts_sentence(
    roles: PartRoles, package: EvidencePackage, *, withdrawn: Sequence[str] = ()
) -> str | None:
    """The `coverage.prerun.bought_parts` sentence (section 7), or `None` with nothing to say.

    `withdrawn` names the findings the part-roles answer withdrew when a regrade restates the
    row (section 9); only a configured or convention-only review asks, so the absent state's
    sentence never carries them.
    """
    names = _file_names(package)
    bought = roles.bought()
    if roles.state == "absent":
        reason = roles.state_reason or STATE_NO_PROFILE
        if not bought:
            return NOT_TOLD_APART.format(reason=reason)
        return NOT_TOLD_APART_TOOLBOX.format(
            reason=reason, names=_listed([names[role.document_id] for role in bought])
        )
    if not bought:
        return None
    sentence = BOUGHT_LINE.format(
        parts=plural(len(bought), "part"),
        names=_listed([f"{names[role.document_id]} ({role.reason})" for role in bought]),
    )
    if withdrawn:
        sentence += WITHDRAWN_TAIL.format(ids=", ".join(withdrawn))
    return sentence


def maybe_bought_sentence(roles: PartRoles, package: EvidencePackage) -> str | None:
    """The `coverage.prerun.maybe_bought` sentence (section 7): only while the question is
    open, so never in the absent state or when the guard fired."""
    listed = [role for role in roles.unclear() if roles.note_for(role.document_id) is not None]
    if not listed or roles.asked_in is None:
        return None
    names = _file_names(package)
    return MAYBE_LINE.format(
        files=and_list([names[role.document_id] for role in listed]),
        request_id=roles.asked_in,
    )


def guard_sentence(roles: PartRoles) -> str | None:
    """The `coverage.prerun.part_roles` sentence when the zero-match guard fired (section 2)."""
    if not roles.guard_fired:
        return None
    template = GUARD_CONFIGURED if roles.state == "configured" else GUARD_CONVENTION
    return template.format(count=len(roles.by_document))


def roles_question(roles: PartRoles, package: EvidencePackage) -> QuestionSpec | None:
    """The one part-roles question (section 8), or `None` when none is asked: the absent
    state, the guard fired, or nothing is unclear. The spec carries section 8's `allow_text`;
    its one writer (`tools/session.record_question`) adds `source="code"`, as it does for
    every question code asks."""
    unclear = roles.unclear()
    if roles.state == "absent" or roles.guard_fired or not unclear:
        return None
    names = _file_names(package)
    return QuestionSpec(
        key=QUESTION_KEY,
        what=WHAT.format(names=_listed([names[role.document_id] for role in unclear])),
        why=WHY,
        entity_ids=tuple(role.document_id for role in unclear),
        question=QUESTION,
        options=(OPTION_ALL, OPTION_NONE),
        blocks=None,
        allow_text=True,
    )


def answered_roles(
    request: EvidenceRequest, spec: QuestionSpec | None, package: EvidencePackage
) -> RolesAnswer | None:
    """What an answered request says about the listed parts, when it **is** the part-roles
    question - its question, options and ids equal the spec's, as `_is_confirmed_candidate`
    matches (section 9); `None` otherwise, so a look-alike question does nothing."""
    if (
        spec is None
        or request.status != "answered"
        or request.answer is None
        or request.question != spec.question
        or tuple(request.options) != spec.options
        or tuple(request.entity_ids) != spec.entity_ids
    ):
        return None
    listed = list(spec.entity_ids)
    answer = request.answer.strip()
    if _option_key(answer) == _option_key(OPTION_ALL):
        return RolesAnswer(answers=dict.fromkeys(listed, "bought"))
    if _option_key(answer) == _option_key(OPTION_NONE):
        return RolesAnswer(answers=dict.fromkeys(listed, "custom"))
    names = _file_names(package)
    spellings = {
        document_id: {names[document_id].casefold(), _stem(names[document_id]).casefold()}
        for document_id in listed
        if document_id in names
    }
    named: set[str] = set()
    unmatched: list[str] = []
    for piece in (item.strip() for item in _ANSWER_SEPARATORS.split(answer)):
        if not piece:
            continue
        matches = [key for key, spelled in spellings.items() if piece.casefold() in spelled]
        if matches:
            named.update(matches)
        else:
            unmatched.append(piece)
    return RolesAnswer(
        answers={key: "bought" if key in named else "custom" for key in listed},
        unmatched=tuple(unmatched),
    )


def _option_key(text: str) -> str:
    """How a whole answer is compared with an option (section 9): case, runs of spaces and a
    closing full stop or exclamation mark ignored, so "all bought." typed into the text box is
    the "All bought" button - read as a name, it would grade every listed part custom."""
    return " ".join(text.split()).rstrip(".!").strip().casefold()


def unmatched_sentence(pieces: Sequence[str]) -> str | None:
    """The `coverage.prerun.part_roles` sentence quoting typed pieces that named no listed
    part (section 9), or `None` when every piece matched."""
    if not pieces:
        return None
    quoted = [f"'{piece}'" for piece in pieces]
    if len(quoted) == 1:
        return UNMATCHED_ONE.format(piece=quoted[0])
    return UNMATCHED_MANY.format(pieces=and_list(quoted))
