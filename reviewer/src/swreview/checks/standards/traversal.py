"""Which documents a standards run grades, once each, and by what reached them.

FR-003 in one function. The graded set is:

1. the **root** document, whatever its kind;
2. for a **drawing** root, every document a view on any sheet references, and
3. every document reachable through a component tree - the root assembly's, and each
   referenced model's when the root is a drawing.

It is **deduplicated by `document_id`**: a document reached from the root and again from a
drawing's referenced model is graded once, carrying every instance that reaches it, so a
failing check produces exactly one finding for it naming them all. The macro this feature
re-implements collected the same set and never used it; this is that intent, finished.

**Reaching a document is not the same as being able to grade it** (FR-004), and the two
halves of that rule are asymmetric on purpose:

- a **reached** document whose kind or path the package does not record - a virtual
  component, a library-feature part, a kind that is not a part, an assembly or a drawing -
  is carried here with `unresolved_reason` set and its readings null. The report layer turns
  it into `unresolved` coverage for every check that would have applied to it. The run is
  never refused for it;
- only the **root** can refuse the run, through `UngradableRootError`: a root with no kind
  has no check sequence to run, and a root with no path has nothing to match the profile's
  library prefixes or its part-number convention against. A document that has never been
  saved has no path, which is the same refusal said in the words an engineer can act on.

**Nothing here opens, loads or resolves anything** (FR-025, FR-044): the set is computed
from the rows the package already carries, and an instance that is suppressed, lightweight
or unloaded is carried with its state rather than resolved to get at its document.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

from swreview.checks.rules.run import CheckRunError
from swreview.checks.standards.profile import StandardsProfile
from swreview.ir.models import ComponentInstance, Document, EvidencePackage

__all__ = [
    "CheckedDocument",
    "DocumentKind",
    "ReachedBy",
    "UngradableRootError",
    "graded_documents",
    "part_number_matches",
]

DocumentKind = Literal["part", "assembly", "drawing"]
"""The three kinds a standards run can grade; anything else is an unresolved document."""

ReachedBy = Literal["root", "component_tree", "drawing_reference"]
"""How a graded document entered the set. First reach wins, so a document referenced by a
view and also hanging under another referenced assembly is a `drawing_reference`: it is
named on the drawing, which is what an engineer reading the row is looking at."""

RESOLVED = "resolved"
"""The one `ComponentInstance.suppression` state that carries evidence. The other three -
suppressed, lightweight, unloaded - are one rule (FR-005) and are carried with their state
rather than distinguished here."""

NO_DOCUMENT_ROW = (
    "{document_id} is reached by the traversal and the package records no document row for "
    "it, so neither its kind nor its path is known"
)

NO_PATH = (
    "{document_id} is reached by the traversal and the package records no path for it, so it "
    "cannot be matched against the profile's library prefixes or its part-number convention"
)

ROOT_HAS_NO_DOCUMENT_ROW = (
    "the root document {document_id} has no document row in this package, so neither its "
    "kind nor its path is known and there is no check sequence to run; extract the design "
    "again with the standards profile"
)

ROOT_HAS_NO_PATH = (
    "the root document {document_id} has never been saved, so it has no path; a standards "
    "run matches the profile's library prefixes and its part-number convention against the "
    "path, and there is nothing to match. Save it first"
)


class UngradableRootError(CheckRunError):
    """The root document cannot be graded, so there is no run to make (FR-004)."""

    error_class = "UngradableRoot"


@dataclass(frozen=True)
class CheckedDocument:
    """One document of the graded set: what it is, and everything that reaches it."""

    document_id: str
    kind: DocumentKind | None
    """`None` when the package records no row for this document - it is unresolved, and
    every check that would have applied to it is an unresolved coverage row."""

    path: str | None
    """The document's path, or `None` when the package records none (blank counts as none:
    a document that has never been saved has an empty path, not a path of one space)."""

    file_name: str | None
    """`Document.file_name` as recorded. The **part-number match** is made against the name
    in `path` instead, because a window title can be configured to hide extensions and the
    macro's version of that check switched itself off when it was (difference l)."""

    configuration: str | None
    """The configuration the package read this document in."""

    instances: tuple[ComponentInstance, ...] = ()
    """Every component instance that reaches this document, in package order - what a
    finding names in `component_ids`. Empty for the root of a run and for a drawing, which
    is never instantiated as a component."""

    reached_by: ReachedBy = "component_tree"
    matches_part_number: bool = False
    unresolved_instances: tuple[tuple[str, str], ...] = ()
    """The `(id, state)` of each instance above that is suppressed, lightweight or
    unloaded. A document whose every instance is here was reached only through unresolved
    instances; it is still graded, and the checks say so (FR-005)."""

    unresolved_reason: str | None = None
    """Why this document cannot be graded, or `None` when it can. Set exactly when `kind`
    or `path` is `None`."""


def graded_documents(
    package: EvidencePackage, profile: StandardsProfile
) -> tuple[CheckedDocument, ...]:
    """The graded set of `package`, in traversal order, each document exactly once.

    Raises `UngradableRootError` when the root document has no recorded kind or no path;
    every other document the traversal reaches is carried, resolved or not.
    """
    rows = {row.document_id: row for row in package.documents}
    root_id = package.design.root_assembly_document_id
    _check_root(root_id, rows.get(root_id))

    reached = _Reached()
    reached.add(root_id, "root")

    root = rows[root_id]
    referenced = _referenced_documents(package, root_id) if root.kind == "drawing" else ()
    for document_id in referenced:
        reached.add(document_id, "drawing_reference")

    for instance in _walk(package.components, root):
        reached.add(instance.document_id, "component_tree", instance)

    pattern = profile.part_number.pattern
    return tuple(
        _checked(document_id, entry, rows.get(document_id), pattern)
        for document_id, entry in reached.items()
    )


def part_number_matches(pattern: str, file_name: str) -> bool:
    """Whether `file_name` follows the profile's part-number convention.

    `#` is one digit, `?` is one character, every other character is literal, and the match
    is **whole-string** and **case-insensitive** against the file name including its
    extension (`contracts/rules.md`, "Matching the pattern"). An empty pattern matches
    nothing: there is no convention to follow, which is why the data-card check reports the
    empty setting as skipped coverage rather than grading anything against it.
    """
    if not pattern or not file_name:
        return False
    expression = "".join(
        "[0-9]" if character == "#" else "." if character == "?" else re.escape(character)
        for character in pattern
    )
    return re.fullmatch(expression, file_name, flags=re.IGNORECASE) is not None


# --- the reached set ------------------------------------------------------------------------


@dataclass
class _Entry:
    """One document's accumulating half of the set: how it was reached, and by what."""

    reached_by: ReachedBy
    instances: list[ComponentInstance] = field(default_factory=list)


class _Reached:
    """The graded set as it is built: insertion-ordered, one entry per `document_id`."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def add(
        self, document_id: str, reached_by: ReachedBy, instance: ComponentInstance | None = None
    ) -> None:
        """Record one reach. The first `reached_by` for a document is the one it keeps."""
        entry = self._entries.get(document_id)
        if entry is None:
            entry = self._entries[document_id] = _Entry(reached_by=reached_by)
        if instance is not None:
            entry.instances.append(instance)

    def items(self) -> Iterator[tuple[str, _Entry]]:
        return iter(self._entries.items())


def _check_root(root_id: str, row: Document | None) -> None:
    """The one refusal a traversal can make (FR-004)."""
    if row is None:
        raise UngradableRootError(ROOT_HAS_NO_DOCUMENT_ROW.format(document_id=root_id))
    if not row.path.strip():
        raise UngradableRootError(ROOT_HAS_NO_PATH.format(document_id=root_id))


def _referenced_documents(package: EvidencePackage, root_id: str) -> tuple[str, ...]:
    """Every document a view on any sheet of the root drawing references, in sheet order.

    **Every sheet**, not only the active one (difference q). A view whose referenced model
    is not a document of this package contributes nothing: the dump records a gap naming
    the model, and there is no document to grade.
    """
    seen: dict[str, None] = {}
    for record in package.drawing_records:
        if record.document_id != root_id:
            continue
        for sheet in record.sheets:
            for view in sheet.views:
                if view.referenced_document_id is not None:
                    seen.setdefault(view.referenced_document_id, None)
    return tuple(seen)


def _walk(components: Sequence[ComponentInstance], root: Document) -> Iterable[ComponentInstance]:
    """Every instance of the component forest exactly once: each top, breadth first.

    The forest's tops are the instances with no parent - the root assembly's own instance
    for an assembly root, the synthesized instance of a part opened alone, and, for a
    drawing root, the synthesized forest root the dump hangs one subtree per referenced
    model under (`research.md` R9).

    **Every instance is walked, whether or not a top reaches it.** A dump whose instance
    names a parent the package does not carry, or names itself, or sits in a cycle of its
    own is a defect in whatever wrote it - but dropping its subtree would grade fewer
    documents than the package describes and say nothing about it, and a release gate that
    silently grades less is worse than one that grades a defective package. So the tops are
    walked first, in package order, and then every instance no top reached is walked in
    package order too. `seen` makes that terminate and keeps every instance to one visit.

    **The root document is never a component of itself**: an instance whose `document_id`
    is the root's - the root assembly's own instance, the synthesized root of a part opened
    alone, the synthesized forest root of a drawing - is walked through and is not yielded,
    because `CheckedDocument.instances` is what a finding names in `component_ids` and the
    root is not reached through an instance (`contracts/rules.md`, granularity).
    """
    children: dict[str, list[ComponentInstance]] = defaultdict(list)
    for instance in components:
        if instance.parent_id is not None:
            children[instance.parent_id].append(instance)

    tops = [instance for instance in components if instance.parent_id is None]
    seen: set[str] = set()
    for start in (*tops, *components):
        queue = [start]
        while queue:
            instance = queue.pop(0)
            if instance.id in seen:
                continue
            seen.add(instance.id)
            if instance.document_id != root.document_id:
                yield instance
            queue.extend(children[instance.id])


def _checked(
    document_id: str, entry: _Entry, row: Document | None, pattern: str
) -> CheckedDocument:
    """One `CheckedDocument`: the row's readings, or the reason there are none."""
    instances = tuple(entry.instances)
    unresolved = tuple(
        (instance.id, instance.suppression)
        for instance in instances
        if instance.suppression != RESOLVED
    )
    if row is None:
        return CheckedDocument(
            document_id=document_id,
            kind=None,
            path=None,
            file_name=None,
            configuration=None,
            instances=instances,
            reached_by=entry.reached_by,
            matches_part_number=False,
            unresolved_instances=unresolved,
            unresolved_reason=NO_DOCUMENT_ROW.format(document_id=document_id),
        )

    path = row.path.strip() or None
    return CheckedDocument(
        document_id=document_id,
        kind=row.kind,
        path=path,
        file_name=row.file_name,
        configuration=row.active_configuration,
        instances=instances,
        reached_by=entry.reached_by,
        matches_part_number=(
            part_number_matches(pattern, _name_in(path)) if path is not None else False
        ),
        unresolved_instances=unresolved,
        unresolved_reason=None if path else NO_PATH.format(document_id=document_id),
    )


def _name_in(path: str) -> str:
    """The file name a path ends in, separator-agnostic: packages carry Windows paths."""
    return re.split(r"[\\/]", path)[-1]
