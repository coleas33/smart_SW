"""The one matcher: when a finding matches an answer-key entry, and when two entries overlap.

Feature 014 `contracts/scoring.md` section 2 and `contracts/answer-key.md` section 5. A finding
**matches** a known defect or a correct condition when all three hold:

1. **Checks** (2.1, FR-001): the finding's check equals the entry's exact check, or starts with
   a family's id and a dot. A sibling rule never matches: `fastener.thread_match` is not a
   `fastener.bottoming` finding (owner decision 4A removed the prefix rule that said it was).
2. **Targets** (2.2, FR-003): the finding's parts meet the entry's `component_ids`, or its
   documents meet the entry's `document_ids` (`targets_overlap`).
3. **References** (2.3, FR-061): on a reference-keyed check, the finding's references, read from
   its `inputs` alone by the kind of item the check names, **equal** one covered item's
   references. Equality, not "names all those of one", so a stack with an extra contributor or
   an entry naming part of a joint cannot let one finding match two entries (SC-002); roles are
   never compared, so a fit called with bore and shaft swapped names the same pair.

Two entries **overlap** when one finding could match both (`entries_overlap`), which the key
loader refuses for the pairs `answer-key.md` 5 names: the same three conditions, read off two
entries instead of a finding and an entry, so the refusal can never disagree with the scorer.

This is the one implementation (plan "Phase 0 and Phase 1" point 1): the scorer, the key
loader's overlap row, the oracle builder and the pilot's never-detected list, which asks
`targets_overlap` alone, all call it. The check-pattern grammar and the reference kinds are
`benchmark/answer_key_model.py`'s, read from there and never restated.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from swreview.benchmark.answer_key_model import (
    REFERENCE_KEYED_CHECKS,
    CorrectCondition,
    KnownDefect,
    Reference,
    ReferenceKind,
    pattern_covers,
)
from swreview.findings import Finding
from swreview.ir.models import Dimension

Entry = KnownDefect | CorrectCondition
"""An entry on one check pattern, on its parts or documents, and, on a reference-keyed check,
on the items it covers. Forbidden entries join with their model (US3, T080 and T084)."""


# --- 2.2: targets ----------------------------------------------------------------------------


def finding_parts(finding: Finding) -> frozenset[str]:
    """The finding's parts: its `component_ids`."""
    return frozenset(finding.component_ids)


def finding_documents(finding: Finding) -> frozenset[str]:
    """The finding's documents: its drawing locations' `document_id`s and, only when it names
    no component and no drawing location, its provenance's.

    A finding with neither is document-scoped (`findings.py:338-343`): a standards finding on
    a drawing, bound through `document_ids`, names its document in its provenance and nowhere
    else. A component finding's provenance holds its part document (`findings.py:273-290`)
    and is never read, so a hygiene finding on a part does not reach an entry on a drawing or
    document of that part (SR-2).
    """
    if not finding.component_ids and not finding.drawing_locations:
        return frozenset(entry.document_id for entry in finding.provenance)
    return frozenset(location.document_id for location in finding.drawing_locations)


def _targets_meet(parts: Collection[str], documents: Collection[str], entry: Entry) -> bool:
    """2.2's intersection, either list sufficing: `parts` meet the entry's `component_ids`, or
    `documents` its `document_ids`."""
    parts_meet = not set(parts).isdisjoint(entry.component_ids)
    documents_meet = not set(documents).isdisjoint(entry.document_ids)
    return parts_meet or documents_meet


def targets_overlap(finding: Finding, entry: Entry) -> bool:
    """Whether the finding's parts or documents meet the entry's (2.2 alone): the one target
    test, which `matches` calls and the pilot's never-detected list calls by itself."""
    return _targets_meet(finding_parts(finding), finding_documents(finding), entry)


# --- 2.3: references -------------------------------------------------------------------------


def _ids(finding: Finding) -> frozenset[Reference]:
    """The `str` inputs without `#`: a joint's fastener and hole ids, a hole pair's two holes."""
    return frozenset(
        value for value in finding.inputs if isinstance(value, str) and "#" not in value
    )


def _instances(finding: Finding) -> frozenset[Reference]:
    """The `str` inputs with `#`: hole instances as the joint map writes them
    (`checks/joints.py:649`), a recess's or a joint's."""
    return frozenset(value for value in finding.inputs if isinstance(value, str) and "#" in value)


def _dimensions(finding: Finding) -> frozenset[Reference]:
    """Each `Dimension` input as `(document_id, sheet, annotation)`, the triple a key's
    dimension reference names. A dimension whose source has no sheet or annotation keeps its
    `None`, which no key's triple equals, so it is never dropped from a stack's set."""
    return frozenset(
        (value.source.document_id, value.source.sheet, value.source.annotation)
        for value in finding.inputs
        if isinstance(value, Dimension)
    )


_READ_BY_KIND: dict[ReferenceKind, Callable[[Finding], frozenset[Reference]]] = {
    "joint": _ids,
    "hole pair": _ids,
    "recess": _instances,
    "joint instances": _instances,
    "fit": _dimensions,
    "stack": _dimensions,
}
"""`scoring.md` 2.3's table: what each kind of covered item is read from in a finding's
`inputs`. Never `calculation.inputs` or `drawing_locations`, which repeat what `inputs` holds
once owner decision 19A writes every reference-keyed result's references there (SR-3, SR-5)."""


def finding_references(finding: Finding, kind: ReferenceKind) -> frozenset[Reference]:
    """The finding's references of `kind`, read from its `inputs` only (`findings.py:119`).

    `fastener.head_fit` writes the recess instance beside the screw's component
    (`checks/tool_access.py:409`): the recess kind reads the `#` instance and not the
    component; a drawn tolerance beside `hole.coaxiality`'s two ids is not a `str`, and the
    hole-pair kind does not read it.
    """
    return _READ_BY_KIND[kind](finding)


def covered_items(entry: Entry) -> list[frozenset[Reference]]:
    """The items the entry covers, each `references` element as the set of its references (an
    entry on a check that is not reference-keyed covers none)."""
    return [element.reference_set() for element in entry.references or []]


# --- 2: the match, and answer-key.md 5: the overlap ------------------------------------------


def matches(finding: Finding, entry: Entry) -> bool:
    """Whether `finding` matches `entry`: its check under the entry's pattern (2.1), its
    targets meeting the entry's (2.2), and, on a reference-keyed check, its references equal to
    one covered item's (2.3)."""
    if not pattern_covers(entry.check, finding.check) or not targets_overlap(finding, entry):
        return False
    kind = REFERENCE_KEYED_CHECKS.get(entry.check)
    if kind is None:
        return True
    return finding_references(finding, kind) in covered_items(entry)


def entries_overlap(a: Entry, b: Entry) -> bool:
    """Whether one finding could match both entries (`answer-key.md` 5): their checks meet,
    one covering the other, which also reads two families (`rms.*` covers `rms.sketches.*`);
    their parts or their documents intersect; and, when both name references, they share an
    equal covered item. `fastener.head` never overlaps `fastener.head.*`."""
    checks = pattern_covers(a.check, b.check) or pattern_covers(b.check, a.check)
    if not checks or not _targets_meet(a.component_ids, a.document_ids, b):
        return False
    if a.references is None or b.references is None:
        return True
    return not set(covered_items(a)).isdisjoint(covered_items(b))
