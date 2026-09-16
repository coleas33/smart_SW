"""What the curated tool array costs on the wire, pinned per provider encoding.

Every request of every round carries the whole tool array, so a new tool with a long
docstring adds its bytes to every round of every review. This module measures that array
the way the adapters actually encode it - `openai_provider.tool_param` plus `strictify`,
and `types.FunctionDeclaration` plus `gemini_adapt` dumped with the SDK's wire aliases -
and pins the result, so a tool that quietly adds two kilobytes to every request goes red
here rather than on the invoice.

**The numbers are regenerated, never transcribed.** `python -m tests.unit.test_tool_payload
--write` prints the baseline table from this same computation; `docs/llm-efficiency-options.md`
and the lever 4 tier test read their figures from here rather than restating them. Two
figures in the feature 005 package had already diverged from each other by being typed in
twice.

Nothing here calls a provider or needs a key: an encoding is a pure function of the tool
functions, and the two schema converters are already deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from google.genai import types

from swreview.agent.providers.openai_provider import tool_param
from swreview.agent.providers.schema import ToolSpec, gemini_adapt, tool_spec
from swreview.mcp.server import MCP_BRIDGE_TOOL_FUNCTIONS, MCP_TOOL_FUNCTIONS
from swreview.tools.registry import BRIDGE_TOOL_FUNCTIONS, TOOL_FUNCTIONS

ToolFunction = Callable[..., Any]

# --- the two encodings ----------------------------------------------------------------


def _compact(payload: Any) -> bytes:
    """The bytes an HTTP client puts on the wire: no whitespace, UTF-8."""
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def openai_objects(specs: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """The array `OpenAIProvider.run` builds: `tool_param` per tool (`openai_provider.py`)."""
    return [tool_param(spec) for spec in specs]


def gemini_objects(specs: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """The array `GeminiProvider._config` builds, in the shape the SDK sends it.

    `_config` hands the SDK `types.FunctionDeclaration` objects, and the request layer
    serializes them by alias (`parameters_json_schema` is declared with the alias
    `parametersJsonSchema`, VERIFIED against the installed google-genai), dropping the
    fields it never set. Dumping the declaration is therefore the honest wire form; the
    plain snake_case dict this adapter passes in is 64 bytes larger over 32 tools and is
    not what leaves the process.
    """
    declarations = [
        types.FunctionDeclaration(
            name=spec.name,
            description=spec.description,
            parameters_json_schema=gemini_adapt(spec.schema),
        )
        for spec in specs
    ]
    return [
        declaration.model_dump(mode="json", by_alias=True, exclude_none=True)
        for declaration in declarations
    ]


ENCODINGS: dict[str, Callable[[Sequence[ToolSpec]], list[dict[str, Any]]]] = {
    "openai": openai_objects,
    "gemini": gemini_objects,
}
"""The provider encodings this feature measures. No Claude: the product has two providers."""


def specs_of(functions: Iterable[ToolFunction]) -> list[ToolSpec]:
    """`ToolSpec` per function, built through `tool_spec` and not through the process cache.

    `spec_for`'s `_SPECS` is process-global and keyed by function, which is the right
    thing for a review and the wrong thing for a measurement: a measurement must see the
    tree, not whatever the first caller in this process happened to cache.
    """
    return [tool_spec(function) for function in functions]


# --- one measured row -----------------------------------------------------------------


@dataclass(frozen=True)
class PayloadRow:
    """One toolset under one encoding: how many tools and how many bytes."""

    label: str
    encoding: str
    tools: int
    total_bytes: int
    largest_tool: str
    largest_tool_bytes: int


def measure(label: str, functions: Sequence[ToolFunction], encoding: str) -> PayloadRow:
    """Encode this toolset and weigh it, whole array and largest single object."""
    specs = specs_of(functions)
    objects = ENCODINGS[encoding](specs)
    sizes = {spec.name: len(_compact(obj)) for spec, obj in zip(specs, objects, strict=True)}
    largest = max(sizes, key=lambda name: sizes[name]) if sizes else ""
    return PayloadRow(
        label=label,
        encoding=encoding,
        tools=len(specs),
        total_bytes=len(_compact(objects)),
        largest_tool=largest,
        largest_tool_bytes=sizes.get(largest, 0),
    )


TOOLSETS: dict[str, tuple[ToolFunction, ...]] = {
    "review": TOOL_FUNCTIONS,
    "review+bridge": (*TOOL_FUNCTIONS, *BRIDGE_TOOL_FUNCTIONS),
    "mcp": MCP_TOOL_FUNCTIONS,
    "mcp+bridge": (*MCP_TOOL_FUNCTIONS, *MCP_BRIDGE_TOOL_FUNCTIONS),
}
"""The four arrays that actually get sent. The Ask tab's is not the review's (FR-039b)."""


def baseline_rows() -> list[PayloadRow]:
    """Every toolset under every encoding, in table order."""
    return [
        measure(label, functions, encoding)
        for label, functions in TOOLSETS.items()
        for encoding in ENCODINGS
    ]


# --- the RMS tier (lever 4 reads this) --------------------------------------------------

RMS_TIER_WITHHELD: tuple[str, ...] = (
    "check_rms_part",
    "check_rms_assembly",
    "check_rms_equations",
    "list_features",
    "get_feature",
    "list_equations",
)
"""The six tools a package with no feature tree cannot use, withheld together (lever 4)."""


@dataclass(frozen=True)
class TierDelta:
    """What withholding a set of tools takes off the wire, separators included."""

    encoding: str
    withheld: tuple[str, ...]
    kept_tools: int
    kept_bytes: int
    full_bytes: int
    object_bytes: int
    """The withheld tool objects weighed on their own, without the separators they take."""

    @property
    def delta_bytes(self) -> int:
        """What the array actually loses: the objects plus one separator each."""
        return self.full_bytes - self.kept_bytes

    @property
    def delta_percent(self) -> float:
        return round(100 * self.delta_bytes / self.full_bytes, 1)


def tier_delta(
    withheld: Sequence[str] = RMS_TIER_WITHHELD, encoding: str = "openai"
) -> TierDelta:
    """Weigh the curated array with `withheld` taken out of it.

    The saving is the **array** delta and not the sum of the tool objects: six objects
    leave six separators with them. Quoting the object sum understates by exactly six
    bytes, and a hand-typed figure is how that discrepancy got into the package twice.
    """
    names = set(withheld)
    kept = [function for function in TOOL_FUNCTIONS if function.__name__ not in names]
    sizes = tool_object_bytes(encoding)
    return TierDelta(
        encoding=encoding,
        withheld=tuple(withheld),
        kept_tools=len(kept),
        kept_bytes=measure("kept", kept, encoding).total_bytes,
        full_bytes=measure("review", TOOL_FUNCTIONS, encoding).total_bytes,
        object_bytes=sum(sizes[name] for name in withheld),
    )


# --- what the descriptions cost (docs/llm-efficiency-options.md reads this) ---------------


def description_bytes() -> dict[str, int]:
    """UTF-8 bytes of each tool's own description, longest first."""
    sizes = {spec.name: len(spec.description.encode("utf-8")) for spec in specs_of(TOOL_FUNCTIONS)}
    return dict(sorted(sizes.items(), key=lambda item: (-item[1], item[0])))


def tool_object_bytes(encoding: str = "openai") -> dict[str, int]:
    """Encoded bytes of each whole tool object, largest first."""
    specs = specs_of(TOOL_FUNCTIONS)
    objects = ENCODINGS[encoding](specs)
    sizes = {spec.name: len(_compact(obj)) for spec, obj in zip(specs, objects, strict=True)}
    return dict(sorted(sizes.items(), key=lambda item: (-item[1], item[0])))


def _emptied(node: Any) -> Any:
    """Every `description`, at every depth, replaced by the empty string."""
    if isinstance(node, dict):
        return {
            key: "" if key == "description" and isinstance(value, str) else _emptied(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_emptied(item) for item in node]
    return node


def structural_floor_bytes(encoding: str = "openai") -> int:
    """The array with every description emptied: names, types and structure alone.

    This is the floor no amount of description trimming can reach, which is what makes
    "trim the docstrings" a bounded lever rather than an open-ended one.
    """
    objects = ENCODINGS[encoding](specs_of(TOOL_FUNCTIONS))
    return len(_compact([_emptied(obj) for obj in objects]))


def encoding_digests() -> dict[str, str]:
    """sha256 of the curated array under each encoding. Equal across interpreter runs."""
    specs = specs_of(TOOL_FUNCTIONS)
    return {
        name: hashlib.sha256(_compact(encode(specs))).hexdigest()
        for name, encode in sorted(ENCODINGS.items())
    }


# --- the pinned baseline ----------------------------------------------------------------

REVIEW_TOOL_COUNT = 32
REVIEW_BRIDGE_TOOL_COUNT = 35
OPENAI_ARRAY_BYTES = 34_065
GEMINI_ARRAY_BYTES = 34_217
"""**Deviation from T001, recorded in `specs/005-llm-efficiency/probe-log.md`.** The task
asks for 34,248; this tree produces 34,217, and a pin is a measurement or it is nothing.
Six files of the spec package still quote 34,248 (and 37,709 for the bridge, measured
37,712); probe-log.md lists them by line for the change that is allowed to edit them."""
MCP_TOOL_COUNT = 20
MCP_OPENAI_ARRAY_BYTES = 14_866
MCP_GEMINI_ARRAY_BYTES = 14_084
LARGEST_TOOL = "check_axial_stack"
LARGEST_TOOL_BYTES = 2_734
RMS_TIER_KEPT_TOOLS = 26
RMS_TIER_KEPT_BYTES = 25_972
RMS_TIER_DELTA_BYTES = 8_093
RMS_TIER_DELTA_PERCENT = 23.8
STRUCTURAL_FLOOR_BYTES = 15_274

TOOL_OBJECT_CEILING = {"openai": 3_000, "gemini": 3_500}
"""No single tool may weigh more than this. Headroom, not a target."""

ARRAY_CEILING = 36_000
"""The curated array's ceiling in either encoding: roughly 5 percent above today."""


# --- the tests ---------------------------------------------------------------------------


def test_curated_tool_count_is_pinned() -> None:
    """32 tools, 35 with the bridge. A new tool is a decision, not an accident."""
    assert len(TOOL_FUNCTIONS) == REVIEW_TOOL_COUNT
    assert len(TOOLSETS["review+bridge"]) == REVIEW_BRIDGE_TOOL_COUNT


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("openai", OPENAI_ARRAY_BYTES), ("gemini", GEMINI_ARRAY_BYTES)],
)
def test_curated_array_bytes_per_encoding(encoding: str, expected: int) -> None:
    """The whole tool array, compact, as each adapter sends it."""
    assert measure("review", TOOL_FUNCTIONS, encoding).total_bytes == expected


@pytest.mark.parametrize("encoding", sorted(ENCODINGS))
def test_no_tool_object_exceeds_its_ceiling(encoding: str) -> None:
    """The largest single tool object sits under the ceiling, with room to spare."""
    sizes = tool_object_bytes(encoding)
    ceiling = TOOL_OBJECT_CEILING[encoding]
    over = {name: size for name, size in sizes.items() if size >= ceiling}
    assert over == {}, f"{encoding}: tool object(s) at or over {ceiling} bytes: {over}"


def test_largest_tool_object_is_check_axial_stack() -> None:
    """Named because `docs/llm-efficiency-options.md` quotes it and lever 2 targets it."""
    row = measure("review", TOOL_FUNCTIONS, "openai")
    assert (row.largest_tool, row.largest_tool_bytes) == (LARGEST_TOOL, LARGEST_TOOL_BYTES)


@pytest.mark.parametrize("encoding", sorted(ENCODINGS))
def test_whole_array_under_ceiling(encoding: str) -> None:
    """A guard on the array itself, so 32 small additions cannot pass the per-tool one."""
    assert measure("review", TOOL_FUNCTIONS, encoding).total_bytes < ARRAY_CEILING


def test_rms_tier_row_is_the_array_delta_not_the_object_sum() -> None:
    """Withholding the six RMS tools: 32 tools to 26, and what that takes off the wire."""
    delta = tier_delta()
    assert delta.kept_tools == RMS_TIER_KEPT_TOOLS
    assert delta.kept_bytes == RMS_TIER_KEPT_BYTES
    assert delta.delta_bytes == RMS_TIER_DELTA_BYTES
    assert delta.delta_percent == RMS_TIER_DELTA_PERCENT
    # The six array separators are the whole difference between the two figures that
    # diverged across the feature package: 8,093 on the wire, 8,087 of tool objects.
    assert delta.object_bytes == 8_087
    assert delta.delta_bytes == delta.object_bytes + len(RMS_TIER_WITHHELD)


def test_rms_tier_delta_is_smaller_on_gemini() -> None:
    """Stated so no reader quotes the OpenAI saving for a Gemini run."""
    assert tier_delta(encoding="gemini").delta_bytes < RMS_TIER_DELTA_BYTES


def test_mcp_toolset_is_a_different_payload_from_the_review() -> None:
    """The Ask tab sends `MCP_TOOL_FUNCTIONS`, a narrower list (FR-039b)."""
    assert len(MCP_TOOL_FUNCTIONS) == MCP_TOOL_COUNT
    assert set(MCP_TOOL_FUNCTIONS) < set(TOOL_FUNCTIONS)
    assert measure("mcp", MCP_TOOL_FUNCTIONS, "openai").total_bytes == MCP_OPENAI_ARRAY_BYTES
    assert measure("mcp", MCP_TOOL_FUNCTIONS, "gemini").total_bytes == MCP_GEMINI_ARRAY_BYTES
    assert MCP_OPENAI_ARRAY_BYTES != OPENAI_ARRAY_BYTES


def test_structural_floor_is_45_percent_of_the_payload() -> None:
    """Emptying every description everywhere still leaves this much. Lever 2 is bounded."""
    floor = structural_floor_bytes()
    assert floor == STRUCTURAL_FLOOR_BYTES
    assert round(100 * floor / OPENAI_ARRAY_BYTES) == 45


def test_longest_descriptions_and_largest_objects_are_the_documented_ones() -> None:
    """The two lists `docs/llm-efficiency-options.md` quotes, regenerated here (T002)."""
    assert list(description_bytes().items())[:4] == [
        ("check_rms_assembly", 1_455),
        ("check_rms_part", 1_296),
        ("check_fastener_joint", 871),
        ("check_interference_group", 870),
    ]
    assert list(tool_object_bytes().items())[:3] == [
        ("check_axial_stack", 2_734),
        ("check_fit", 2_413),
        ("record_drawing_finding", 2_156),
    ]


_REVIEWER_ROOT = Path(__file__).resolve().parents[2]
_DIGEST_PROGRAM = (
    "from tests.unit.test_tool_payload import encoding_digests;"
    "print(';'.join(f'{k}={v}' for k, v in encoding_digests().items()))"
)


def _digests_under(hash_seed: str) -> str:
    environment = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(_REVIEWER_ROOT)}
    completed = subprocess.run(
        [sys.executable, "-c", _DIGEST_PROGRAM],
        cwd=_REVIEWER_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def test_both_encodings_are_byte_identical_across_hash_seeds() -> None:
    """Determinism, asserted the only way it can be: in fresh interpreters.

    `strictify` and `gemini_adapt` build their output in insertion order, so neither is
    at the mercy of `PYTHONHASHSEED` - but that is a property of today's code, and an
    encoding that varied run to run would make every byte figure in this feature
    meaningless while still passing every in-process test.
    """
    digests = [_digests_under(seed) for seed in ("0", "1", "12345")]
    assert digests[0] == digests[1] == digests[2]
    expected = ";".join(f"{name}={value}" for name, value in encoding_digests().items())
    assert digests[0] == expected


# --- the --write helper -------------------------------------------------------------------


def baseline_table() -> str:
    """The markdown table `docs/llm-efficiency-options.md` and the ledger quote."""
    lines = [
        "| Toolset | Encoding | Tools | Bytes | Largest tool | Bytes |",
        "|---|---|---:|---:|---|---:|",
    ]
    for row in baseline_rows():
        lines.append(
            f"| {row.label} | {row.encoding} | {row.tools} | {row.total_bytes:,} "
            f"| `{row.largest_tool}` | {row.largest_tool_bytes:,} |"
        )
    lines.append("")
    lines.append("| RMS tier | Encoding | Kept tools | Kept bytes | Delta | Delta % |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for encoding in ENCODINGS:
        delta = tier_delta(encoding=encoding)
        lines.append(
            f"| withhold {len(delta.withheld)} RMS tools | {encoding} | {delta.kept_tools} "
            f"| {delta.kept_bytes:,} | {delta.delta_bytes:,} | {delta.delta_percent} |"
        )
    lines.append("")
    floor = structural_floor_bytes()
    total = measure("review", TOOL_FUNCTIONS, "openai").total_bytes
    lines.append(
        f"Structural floor (every description emptied, openai): {floor:,} bytes, "
        f"{round(100 * floor / total)} percent of {total:,}."
    )
    lines.append("")
    longest = ", ".join(f"`{n}` {b:,}" for n, b in list(description_bytes().items())[:4])
    largest = ", ".join(f"`{n}` {b:,}" for n, b in list(tool_object_bytes().items())[:3])
    lines.append(f"Longest descriptions: {longest}")
    lines.append(f"Largest tool objects (openai): {largest}")
    lines.append("")
    lines.append("sha256: " + ", ".join(f"{k} {v}" for k, v in encoding_digests().items()))
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - the regeneration helper, not a test path
    if "--write" not in sys.argv[1:]:
        print("usage: python -m tests.unit.test_tool_payload --write", file=sys.stderr)
        raise SystemExit(2)
    print(baseline_table())
