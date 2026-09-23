"""Old tool results as stubs in the model's view: one pure function for every request.

Feature 008 User Story 3 (FR-020, FR-022, `contracts/model-view.md` section 7). On the big
recorded assembly 95.7% of every request was earlier tool output resent in full; the model
needs to have read a result once, not forty times. With history pruning on, a tool result
that has been in the model's view for `prune_after_rounds` rounds is replaced - in the
request, never in the history - by a stub naming the tool, its arguments, its counts and the
ids it returned, and saying how to fetch it again.

**A pure view of an append-only history** (research R2.29). `prune_history` returns a new
list and never touches the one it is given: the runner's history stays append-only, each
round's request is built from it afresh, and so pruning applies between turns with no
further code - a follow-up carries stubs, not payloads. Both adapters call this one function
(OpenAI before `_encode_history`, Gemini by rebuilding `contents` each round), and so does
the replay, so the stubs and ages the replay prices are the ones the adapters send.

**Deterministic** (research R2.30): the stub is a function of `(name, arguments, content)`
alone, built in a fixed key order, so the same result always gives the same bytes and the
cached prefix of a request up to the previous result survives.

This module lives with the providers because it is a function of the neutral history they
own; it knows nothing about tools beyond the shape of a result (lists of objects with ids),
and imports nothing from `tools/`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

__all__ = [
    "NOT_OFFERED_REFETCH",
    "PRUNED_NOTE",
    "STUB_ID_CAP",
    "prunable",
    "prune_history",
    "result_stub",
]

PRUNED_NOTE = "shown in full earlier; summarised here"
"""What a stub says it is, so the model never reads a stub as the result itself."""

STUB_ID_CAP = 20
"""How many ids a stub names; the rest are counted in `ids_omitted`. The follow-up budget
(SC-004) rests on this cap (research R2.51)."""

NOT_OFFERED_REFETCH = "{name} is not offered this session, so it cannot be called again"
"""A stub's `refetch` for a tool the caller's array does not carry (feature 008 FR-030): a
stub never points the model at a tool it does not have."""

_FINDING_ID = re.compile(r"^F-[0-9]+$")


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def result_stub(
    name: str,
    arguments: Mapping[str, Any],
    content: Mapping[str, Any],
    *,
    finding_detail: bool = True,
    offered: Collection[str] | None = None,
) -> dict[str, Any]:
    """The stub one result becomes (data-model section 11): what it was and how to get it back.

    `counts` has the length of each top-level list of what the model read; `ids` the `id` of
    every object in those lists, then the `finding_ids` when present, each once, at most
    `STUB_ID_CAP` with the rest counted. `refetch` says to call the tool again with the same
    arguments, and names `get_finding` when the content carries finding ids and
    `finding_detail` says the tool is offered (payload slimming on).

    `offered` is the names on the caller's tool array; `None` means every tool is. A tool
    not among them - one lever 13 withheld, answered by the re-call guard when the model
    called it anyway (feature 008 FR-030) - cannot be called again, and its stub says so
    instead of asking for the call.
    """
    counts: dict[str, int] = {}
    ids: list[str] = []
    for key, value in content.items():
        if not isinstance(value, list):
            continue
        counts[key] = len(value)
        for item in value:
            if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                ids.append(item["id"])
    finding_ids = content.get("finding_ids")
    if isinstance(finding_ids, list):
        ids.extend(item for item in finding_ids if isinstance(item, str))
    unique = list(dict.fromkeys(ids))
    has_findings = finding_detail and any(_FINDING_ID.match(item) for item in unique)
    if offered is None or name in offered:
        refetch = f"call {name} again with these arguments to read it in full"
        if has_findings:
            refetch += " or get_finding(<id>) for one finding"
    else:
        refetch = NOT_OFFERED_REFETCH.format(name=name)
        if has_findings:
            refetch += "; get_finding(<id>) reads one finding"
    return {
        "pruned": PRUNED_NOTE,
        "tool": name,
        "arguments": dict(arguments),
        "counts": counts,
        "ids": unique[:STUB_ID_CAP],
        "ids_omitted": max(0, len(unique) - STUB_ID_CAP),
        "refetch": refetch,
    }


def _arguments_by_position(
    messages: Sequence[Mapping[str, Any]],
) -> dict[int, Mapping[str, Any]]:
    """Each tool message's arguments, read from the calls of the assistant message before it.

    By position, never by call id: Gemini sends empty call ids, and the parallel calls of one
    round are answered in the order they were asked. A tool message past the calls its
    assistant message recorded, or whose name is not the name at its position, has no
    arguments here - OpenAI's `_append_unrun` answers calls it could not run after an
    assistant message that recorded none - and is therefore never replaced.
    """
    arguments: dict[int, Mapping[str, Any]] = {}
    calls: Sequence[Mapping[str, Any]] = ()
    position = 0
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            calls = message.get("tool_calls") or ()
            position = 0
        elif role == "tool":
            if position < len(calls) and calls[position].get("name") == message.get("name"):
                arguments[index] = calls[position].get("arguments") or {}
            position += 1
        else:
            calls, position = (), 0
    return arguments


def prunable(
    messages: Sequence[Mapping[str, Any]], prune_after_rounds: int
) -> dict[int, Mapping[str, Any]]:
    """The tool messages old enough to become stubs, by position, each with its arguments.

    Three of the four conditions of `contracts/model-view.md` section 7: its age - the
    number of assistant messages after it - is at least `prune_after_rounds`; it is not an
    error; its arguments are known by position. The fourth - the stub shorter than the
    content - needs the content, so it is the caller's: `prune_history` compares the two,
    and the replay, which knows only the size of a result it could not run, compares that.
    """
    arguments = _arguments_by_position(messages)
    old: dict[int, Mapping[str, Any]] = {}
    age = 0
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        role = message.get("role")
        if role == "assistant":
            age += 1
        elif (
            role == "tool"
            and age >= prune_after_rounds
            and not message.get("is_error")
            and index in arguments
        ):
            old[index] = arguments[index]
    return old


def prune_history(
    messages: Sequence[Mapping[str, Any]],
    prune_after_rounds: int,
    *,
    finding_detail: bool = True,
    offered: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """The history as the next request should carry it: old results replaced by stubs.

    A `tool` message is replaced when all four hold (`contracts/model-view.md` section 7):
    it is `prunable` - old enough, not an error, its arguments known by position - and its
    compact stub is shorter than its compact content. A message that already is a stub is
    left as it is, so pruning twice is pruning once. User and assistant messages - the
    opening digest, the engineer's words, the answer message - are never touched. Returns a
    new list of new dicts; `messages` and its dicts are never mutated.

    `finding_detail` is whether `get_finding` is offered (payload slimming on), and `offered`
    the names on the caller's tool array (`None`: every tool); a stub never points the model
    at a tool it does not have.
    """
    pruned: list[dict[str, Any]] = [dict(message) for message in messages]
    for index, arguments in prunable(messages, prune_after_rounds).items():
        message = messages[index]
        content = message.get("content")
        if not isinstance(content, Mapping) or content.get("pruned") == PRUNED_NOTE:
            continue
        stub = result_stub(
            str(message.get("name", "")),
            arguments,
            content,
            finding_detail=finding_detail,
            offered=offered,
        )
        if len(_compact(stub)) < len(_compact(content)):
            pruned[index]["content"] = stub
    return pruned
