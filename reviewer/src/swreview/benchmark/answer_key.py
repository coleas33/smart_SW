"""Answer keys: the one reader, its load-time refusals, and the held-out stamp.

Feature 014 `contracts/answer-key.md` 1, 4 and 6 and `cases.md` 5. A key's format is
`benchmark/answer_key_model.py`, data only, the one definition the generator writes through; this
module reads a key file into that model and runs the refusals that need more than the model: the
matcher (`benchmark/matching.py`), the report's goals and the package.

This is the only module in `swreview` that reads `benchmarks/answer_keys/` (constitution
Principle VI, FR-025): only the scorer, and from the validation slice the validation and the set
summary, call it, after a run has finished. Nothing under `tools/`, `agent/`, `checks/` or
`benchmark/runner.py` imports it or the model (FR-032): runs never read keys.

## The refusals, in order

`load_answer_key` builds the model first, whose rows (1, 3, 4, 5, 7 and row 6's grammar) refuse
naming the entry; then this module's rows, the first failing row ending the load:

- row 2: `package_id` equals the file's stem (its set half lands with keyed sets);
- row 6's typo guard (AK-6): every check, a family's id read with its trailing dot, falls under a
  goal of the report's words file, so `hygeine.*` cannot grade nothing and pass every test;
- row 8: no two known defects, and no known defect and correct condition, overlap, through
  `matching.entries_overlap`, the scorer's own primitives;
- row 12 (section 6): a key-only key loads with no package, its ids unchecked; a key-only key whose
  package exists, and a key without the marker whose package is missing, are refused;
- with the package, row 13: every id resolves, component and document ids as
  `ToolContext.entity_kind` reads them, holes, fasteners and hole instances against the package,
  dimensions through `tools/refs.resolve_dimension` with its own message; and row 14: every
  reference is owned by the entry's parts or documents, so a reference match implies the target
  overlap FR-003 asks for.

Every refusal is an `AnswerKeyError`, a `ValueError` the command line prints as one line, starting
"answer key {file name}:" and naming the entry, or both entries of an overlap.

## The stamp

`current_stamp()` names, once, what a held-out item is held out against (owner decision 25A): the
system prompt's and the checklist's raw-bytes digests, the very `sha256_of` provenance records a
run's digests with, and `tool_descriptions_digest()`, the canonical digest of every tool a design
review can offer, its full description and its schema, so an `Args:` entry, which reaches the
model only as its parameter's schema description, moves the stamp too. A stale stamp is not a load
refusal (15A); the set summary lists it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from itertools import combinations
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from swreview.agent.checklist import CHECKLIST_FILE, SYSTEM_PROMPT_FILE, Checklist
from swreview.benchmark import digest, matching
from swreview.benchmark.answer_key_model import (
    AnswerKey,
    DimensionReference,
    FitReference,
    HolePairReference,
    JointInstancesReference,
    JointReference,
    RecessReference,
    ReferenceElement,
    StackReference,
    Stamp,
    is_family,
)
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import EvidencePackage
from swreview.report.finding_groups import goal_of
from swreview.report.summary import Words
from swreview.tools import registry
from swreview.tools.context import ToolContext, build_context
from swreview.tools.refs import resolve_dimension

__all__ = [
    "AnswerKeyError",
    "current_stamp",
    "load_answer_key",
    "tool_descriptions_digest",
]

_HOLE_INSTANCE = re.compile(r"(?P<hole>.+)#[1-9][0-9]*")
"""A hole instance as the joint map writes it, `f"{hole.id}#{number}"` from 1
(`checks/joints.py:649`)."""


class AnswerKeyError(ValueError):
    """A key this build refuses to read: "answer key {file name}: ..." naming the entry."""


# --- the stamp (cases.md 5; answer-key.md 2.2) -----------------------------------------------


def _review_tool_functions() -> tuple[Callable[..., Any], ...]:
    """Every tool function a design review can offer (`tools/registry.py:203-274`). The remodel
    tools are left out: no design review is offered them (`ToolRegistry._offered`)."""
    return (
        *registry.TOOL_FUNCTIONS,
        *registry.COMPACT_QUERY_TOOL_FUNCTIONS,
        *registry.FINDING_DETAIL_TOOL_FUNCTIONS,
        *registry.BRIDGE_TOOL_FUNCTIONS,
        *registry.standards_tools(),
        *registry.drawing_tools(),
    )


def tool_descriptions_digest() -> str:
    """`digest.canonical_sha256` of `{name: {"description", "schema"}}` over every review tool,
    each through `spec_for`: every word the model reads of a tool, on either arm of lever 2."""
    specs = [registry.spec_for(function) for function in _review_tool_functions()]
    return digest.canonical_sha256(
        {
            spec.name: {"description": spec.full_description, "schema": spec.schema}
            for spec in specs
        }
    )


def current_stamp() -> Stamp:
    """What a held-out entry written now is held out against."""
    return Stamp(
        prompt=digest.sha256_of(SYSTEM_PROMPT_FILE),
        checklist=digest.sha256_of(CHECKLIST_FILE),
        tools=tool_descriptions_digest(),
    )


# --- the reader ------------------------------------------------------------------------------


def load_answer_key(
    path: Path | str,
    *,
    package: EvidencePackage | None,
    checklist: Checklist,
    words: Words,
) -> AnswerKey:
    """Read the key at `path`, refusing it by section 4's rows in order.

    `package` is the package the set names, or `None` when it is not on disk (section 6).
    `checklist` builds the context row 13 reads ids through; the coverage rows of the
    key-extensions slice read its items. `words` is `report.summary.load_words()`, whose goals
    the typo guard reads.
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AnswerKeyError(f"answer key {path.name}: not JSON ({error})") from None
    try:
        key = AnswerKey.model_validate(payload)
    except ValidationError as error:
        raise AnswerKeyError(f"answer key {path.name}: {_model_refusal(error)}") from None
    for reason in _loader_refusals(path, key, package, checklist, words):
        if reason is not None:
            raise AnswerKeyError(f"answer key {path.name}: {reason}")
    if package is None:
        key.mark_ids_unchecked(
            f"the package {key.package_id} is not built, so this key's ids were not checked "
            "against it (answer-key.md 6)"
        )
    return key


def _model_refusal(error: ValidationError) -> str:
    """The model's refusals as one clause each: its own rows' sentences as they are written,
    which name the entry, and pydantic's as `<field>: <message>`, joined by `; `."""
    clauses = []
    for line in error.errors(include_url=False):
        if line["type"] == "value_error":
            clauses.append(line["msg"].removeprefix("Value error, "))
        else:
            field = ".".join(str(part) for part in line["loc"])
            clauses.append(f"{field}: {line['msg']}" if field else line["msg"])
    return "; ".join(clauses)


def _loader_refusals(
    path: Path,
    key: AnswerKey,
    package: EvidencePackage | None,
    checklist: Checklist,
    words: Words,
) -> Iterator[str | None]:
    """This module's rows in section 4's order, each the reason it refuses the key or `None`.
    A generator, so a row runs only once every row before it has passed."""
    yield _stem_refusal(path, key)
    yield from _typo_refusals(key, words)
    yield _overlap_refusal(key)
    yield _key_only_refusal(key, package)
    if package is not None:
        context = _context(package, checklist)
        yield from _id_refusals(key, context)
        yield from _ownership_refusals(key, context)


def _stem_refusal(path: Path, key: AnswerKey) -> str | None:
    """Row 2's stem half: the key names the package its file is named for."""
    if key.package_id != path.stem:
        return f"package_id {key.package_id} differs from the file's stem {path.stem}"
    return None


def _typo_refusals(key: AnswerKey, words: Words) -> Iterator[str | None]:
    """Row 6's typo guard (AK-6): `finding_groups.goal_of` of each check, a family's id with its
    trailing dot, is a goal."""
    for entry in _checked_entries(key):
        read = entry.check.removesuffix("*") if is_family(entry.check) else entry.check
        if goal_of(read, words.goals) is None:
            yield (
                f"{entry.id} checks {entry.check}, which falls under no goal of the report's words "
                "file, so it would grade nothing: a typo? (answer-key.md 3)"
            )


def _overlap_refusal(key: AnswerKey) -> str | None:
    """Row 8: known defect against known defect, then known defect against correct condition,
    in key order, through the matcher's own overlap test (section 5)."""
    pairs = [
        *combinations(key.known_defects, 2),
        *(
            (defect, condition)
            for defect in key.known_defects
            for condition in key.correct_conditions
        ),
    ]
    for first, second in pairs:
        if matching.entries_overlap(first, second):
            return (
                f"{first.id} and {second.id} overlap: one finding could match both "
                "(answer-key.md 5)"
            )
    return None


def _key_only_refusal(key: AnswerKey, package: EvidencePackage | None) -> str | None:
    """Row 12 (section 6; AK-3): the explicit marker, so a missing package is never mistaken
    for an unbuilt one."""
    if key.key_only and package is not None:
        return "the package now exists; remove key_only so its ids are checked"
    if not key.key_only and package is None:
        return (
            f"the package {key.package_id} is missing, and the key is not marked "
            '"key_only": true; a missing package is never read as an unbuilt one '
            "(answer-key.md 6)"
        )
    return None


# --- rows 13 and 14: the package --------------------------------------------------------------


def _context(package: EvidencePackage, checklist: Checklist) -> ToolContext:
    """A tool context over the package in memory, so ids are looked up as the tools look them
    up (`ToolContext.entity_kind`, `tools/context.py:433-446`)."""
    return build_context(LoadedPackage(package=package, base_dir=Path(".")), checklist=checklist)


def _id_refusals(key: AnswerKey, context: ToolContext) -> Iterator[str | None]:
    """Row 13 (FR-009): every id the key names is in the package, by its kind."""
    for entry in _checked_entries(key):
        for kind, ids in (("component", entry.component_ids), ("document", entry.document_ids)):
            for entity_id in ids:
                if context.entity_kind(entity_id) != kind:
                    yield f"{entry.id} names the {kind} {entity_id}, which is not in the package"
        for element in entry.references or []:
            for kind, entity_id in _entities_named(element):
                if kind == "hole instance":
                    yield _instance_refusal(entry.id, entity_id, context)
                elif context.entity_kind(entity_id) != kind:
                    yield f"{entry.id} names the {kind} {entity_id}, which is not in the package"
            for dimension in _dimensions_named(element):
                try:
                    resolve_dimension(context.ir, dimension.model_dump())
                except LookupError as error:
                    yield f"{entry.id} references {_cite(dimension)}: {error}"


def _instance_refusal(entry_id: str, instance: str, context: ToolContext) -> str | None:
    """A hole instance is `<hole id>#<n>`, `n` a whole number from 1, of a hole the package
    holds. Whether the joint map forms that instance is the reachability check's (AK-5)."""
    match = _HOLE_INSTANCE.fullmatch(instance)
    if match is None:
        return (
            f"{entry_id} names the hole instance {instance}, which is not <hole id>#<n> with n a "
            "whole number from 1"
        )
    hole = match["hole"]
    if context.entity_kind(hole) != "hole":
        return (
            f"{entry_id} names the hole instance {instance}, whose hole {hole} is not in the "
            "package"
        )
    return None


def _ownership_refusals(key: AnswerKey, context: ToolContext) -> Iterator[str | None]:
    """Row 14 (FR-003): a hole's or fastener's component is in the entry's `component_ids`, a
    dimension's document in its `document_ids`."""
    for entry in _checked_entries(key):
        for element in entry.references or []:
            for kind, entity_id in _entities_named(element):
                owner = _owning_component(kind, entity_id, context)
                if owner not in entry.component_ids:
                    yield (
                        f"{entry.id} references the {kind} {entity_id}, whose component {owner} "
                        "it does not name in component_ids"
                    )
            for dimension in _dimensions_named(element):
                if dimension.document_id not in entry.document_ids:
                    yield (
                        f"{entry.id} references {_cite(dimension)}, whose document "
                        f"{dimension.document_id} it does not name in document_ids"
                    )


def _owning_component(kind: str, entity_id: str, context: ToolContext) -> str:
    """The component a fastener, a hole or a hole instance's hole sits on. Row 13 ran first, so
    each is in the package and each hole instance is well formed."""
    if kind == "fastener":
        fastener = context.fastener(entity_id)
        assert fastener is not None
        return fastener.component_id
    if kind == "hole instance":
        instance = _HOLE_INSTANCE.fullmatch(entity_id)
        assert instance is not None
        entity_id = instance["hole"]
    hole = context.hole(entity_id)
    assert hole is not None
    return hole.component_id


def _entities_named(element: ReferenceElement) -> list[tuple[str, str]]:
    """The `(kind, id)` of every package entity a covered item names (section 2.5's table)."""
    if isinstance(element, JointReference):
        return [("fastener", element.fastener), ("hole", element.hole)]
    if isinstance(element, RecessReference):
        return [("hole instance", element.recess)]
    if isinstance(element, HolePairReference):
        return [("hole", hole) for hole in element.holes]
    if isinstance(element, JointInstancesReference):
        return [("hole instance", instance) for instance in element.hole_instances]
    return []


def _dimensions_named(element: ReferenceElement) -> list[DimensionReference]:
    """The drawing dimensions a covered item names: a fit's two, a stack's contributors and its
    target."""
    if isinstance(element, FitReference):
        return [element.bore, element.shaft]
    if isinstance(element, StackReference):
        return [*element.contributors, *([element.target] if element.target is not None else [])]
    return []


def _cite(dimension: DimensionReference) -> str:
    return f"the dimension {dimension.document_id} {dimension.sheet} {dimension.annotation}"


def _checked_entries(key: AnswerKey) -> list[matching.Entry]:
    """The key's entries on one check: its known defects, then its correct conditions."""
    return [*key.known_defects, *key.correct_conditions]
