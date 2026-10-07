"""The held-out stamp: what a held-out item is held out against (T035, for T037).

`cases.md` 5 and `answer-key.md` 2.2 (owner decision 25A; plan decisions INT-3, RF-48, RF-64).
A held-out entry's `held_out_against` is `answer_key.current_stamp()` when the entry was written:

- `prompt` and `checklist`: `digest.sha256_of` over the raw bytes of the system prompt and the
  checklist, the very function provenance records a run's digests with, so a key's stamp and a
  run's record of one file are one number (nothing normalises line endings, INT-3);
- `tools`: `answer_key.tool_descriptions_digest()`, `digest.canonical_sha256` of
  `{name: {"description": spec.full_description, "schema": spec.schema}}` over every tool a design
  review can offer. The full description is what lever 2's off arm sends; each `Args:` entry
  reaches the model only as its parameter's schema `description`, on both arms, so the schema is
  digested beside it and every word the model reads of a tool moves the stamp.

A stale stamp is not a load refusal (15A): the set summary and the committed-item test list such an
item. This slice's bullets: the stamp's three digests, three one-character tool-description patches
each making a held-out entry stamped before them stale, and the digested set complete over every
lever combination. The parity-slice bullet (the stamp against a run's `prompt_digest` and
`checklist_digest`) is US2's (T046); the committed-item bullet is US5's (T148).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from itertools import product
from typing import Any

import pytest
from pydantic import BaseModel

from swreview.agent.checklist import CHECKLIST_FILE, SYSTEM_PROMPT_FILE
from swreview.agent.settings import EfficiencySettings, ModelViewSettings
from swreview.benchmark import answer_key, digest
from swreview.benchmark.answer_key_model import KnownDefect, Stamp
from swreview.tools import registry, session
from swreview.tools.context import context_for
from swreview.tools.drawings import drawing_evidence
from swreview.tools.registry import (
    BRIDGE_TOOL_FUNCTIONS,
    COMPACT_QUERY_TOOL_FUNCTIONS,
    FINDING_DETAIL_TOOL_FUNCTIONS,
    REMODEL_TOOL_FUNCTIONS,
    STANDARDS_RUN_ATTRIBUTE,
    TOOL_FUNCTIONS,
    ToolRegistry,
    drawing_tools,
    spec_for,
    standards_tools,
)
from tests.support.packages import build_package
from tests.unit.test_drawing_finding_number_guard import guarded_package


def review_tool_functions() -> tuple[Callable[..., Any], ...]:
    """Every tool function a design review can offer, as `cases.md` 5 lists them
    (`tools/registry.py:203-274`): the remodel tools are offered to no design review."""
    return (
        *TOOL_FUNCTIONS,
        *COMPACT_QUERY_TOOL_FUNCTIONS,
        *FINDING_DETAIL_TOOL_FUNCTIONS,
        *BRIDGE_TOOL_FUNCTIONS,
        *standards_tools(),
        *drawing_tools(),
    )


def digested_text() -> dict[str, dict[str, Any]]:
    """What the tools digest reads, written out from the contract: each review tool's full
    description and schema, through `spec_for`."""
    specs = [spec_for(function) for function in review_tool_functions()]
    return {
        spec.name: {"description": spec.full_description, "schema": spec.schema} for spec in specs
    }


def held_out_defect(stamp: Stamp) -> KnownDefect:
    """A held-out known defect stamped with `stamp`."""
    return KnownDefect.model_validate(
        {
            "id": "D-1",
            "check": "hygiene.revision_present",
            "component_ids": ["cmp:0001"],
            "document_ids": [],
            "producer": "model",
            "expected_status": "suspected",
            "tag": "held_out",
            "held_out_against": stamp.model_dump(),
            "description": "The fictional bracket's drawing carries no revision.",
        }
    )


def stale(entries: Iterable[KnownDefect]) -> list[str]:
    """The stamp check: the held-out entries whose stamp is no longer the current one."""
    current = answer_key.current_stamp()
    return [
        entry.id
        for entry in entries
        if entry.tag == "held_out" and entry.held_out_against != current
    ]


# --- the three digests -----------------------------------------------------------------------


def test_the_stamp_names_the_prompt_and_the_checklist_by_raw_bytes_and_the_tools_by_digest() -> (
    None
):
    stamp = answer_key.current_stamp()

    assert stamp == Stamp(
        prompt=digest.sha256_of(SYSTEM_PROMPT_FILE),
        checklist=digest.sha256_of(CHECKLIST_FILE),
        tools=answer_key.tool_descriptions_digest(),
    )
    assert stamp.prompt == hashlib.sha256(SYSTEM_PROMPT_FILE.read_bytes()).hexdigest()
    assert stamp.checklist == hashlib.sha256(CHECKLIST_FILE.read_bytes()).hexdigest()


def test_the_tools_digest_is_the_canonical_digest_of_each_review_tool_s_text_and_schema() -> None:
    assert answer_key.tool_descriptions_digest() == digest.canonical_sha256(digested_text())


def test_the_remodel_tools_are_not_digested() -> None:
    """No design review is offered them (`ToolRegistry._offered`): a remodel docstring edit
    moves no held-out item."""
    digested = set(review_tool_functions())

    assert REMODEL_TOOL_FUNCTIONS
    assert not digested & set(REMODEL_TOOL_FUNCTIONS)


def test_a_held_out_entry_stamped_now_is_not_stale() -> None:
    assert stale([held_out_defect(answer_key.current_stamp())]) == []


# --- each word the model reads of a tool moves the stamp -------------------------------------

REQUEST_EVIDENCE_DOC = session.request_evidence.__doc__ or ""


@pytest.mark.parametrize(
    ("where", "old", "new"),
    [
        ("body", "Returns its id.", "Returns its id!"),
        ("notes", "Use this instead of assuming", "Use thus instead of assuming"),
        # `request_evidence`'s `question` (`tools/session.py:85-86`): review policy that reaches
        # the model only as the parameter's schema description, never in the full description.
        ("args", "never guess a fit class", "never guest a fit class"),
    ],
)
def test_a_one_character_tool_description_patch_makes_an_earlier_stamp_stale(
    monkeypatch: pytest.MonkeyPatch, where: str, old: str, new: str
) -> None:
    assert REQUEST_EVIDENCE_DOC.count(old) == 1
    before = answer_key.current_stamp()
    entry = held_out_defect(before)
    spec_before = spec_for(session.request_evidence)

    monkeypatch.setattr(session.request_evidence, "__doc__", REQUEST_EVIDENCE_DOC.replace(old, new))
    monkeypatch.setattr(registry, "_SPECS", {})
    spec_after = spec_for(session.request_evidence)

    if where == "args":
        assert spec_after.full_description == spec_before.full_description
        assert spec_after.schema != spec_before.schema
    else:
        assert spec_after.full_description != spec_before.full_description
    assert answer_key.tool_descriptions_digest() != before.tools
    assert answer_key.current_stamp().prompt == before.prompt
    listed = stale([entry])
    assert listed == ["D-1"], f"stale held-out items after the {where} patch: {listed}"


# --- the digested set is complete ------------------------------------------------------------


def booleans(model: type[BaseModel]) -> list[str]:
    """The boolean fields of a settings model, in declaration order."""
    return [name for name, field in model.model_fields.items() if field.annotation is bool]


def lever_combinations() -> Iterable[tuple[EfficiencySettings, ModelViewSettings]]:
    """Every combination of the boolean levers of both settings models."""
    levers = booleans(EfficiencySettings)
    views = booleans(ModelViewSettings)
    for lever_values in product((False, True), repeat=len(levers)):
        efficiency = EfficiencySettings(**dict(zip(levers, lever_values, strict=True)))
        for view_values in product((False, True), repeat=len(views)):
            yield efficiency, ModelViewSettings(**dict(zip(views, view_values, strict=True)))


def test_no_lever_combination_offers_a_review_a_tool_outside_the_digested_set() -> None:
    """Over every lever combination, with a drawing record, a standards run and a bridge attached,
    every function `ToolRegistry` offers is digested, and each offered tool's wire schema is the
    `spec.schema` the digest read (`tools/registry.py:523-524`)."""
    context = context_for(guarded_package(build_package))
    context.bridge = object()
    setattr(context, STANDARDS_RUN_ATTRIBUTE, object())
    assert drawing_evidence(context.ir)
    digested_functions = set(review_tool_functions())
    digested = digested_text()

    arrays: dict[tuple[Callable[..., Any], ...], tuple[EfficiencySettings, ModelViewSettings]] = {}
    for efficiency, model_view in lever_combinations():
        offered = ToolRegistry().functions_for(
            context, efficiency=efficiency, model_view=model_view
        )
        outside = [function.__name__ for function in offered if function not in digested_functions]
        assert outside == [], (efficiency, model_view)
        arrays.setdefault(offered, (efficiency, model_view))

    assert len(arrays) > 1
    for efficiency, model_view in arrays.values():
        dispatch = ToolRegistry().dispatch(context, efficiency=efficiency, model_view=model_view)
        for tool in dispatch:
            assert tool.schema == digested[tool.name]["schema"], tool.name
