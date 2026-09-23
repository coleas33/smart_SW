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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

import pytest
from google.genai import types

from swreview.agent.providers.openai_provider import tool_param
from swreview.agent.providers.schema import ToolSpec, gemini_adapt, tool_spec
from swreview.mcp.server import MCP_BRIDGE_TOOL_FUNCTIONS, MCP_TOOL_FUNCTIONS
from swreview.prerun import INTERFERENCE_TOOL, prerun_tools
from swreview.tokens import count_tokens
from swreview.tools.drawings import DRAWINGS_TOOL
from swreview.tools.registry import (
    BRIDGE_TOOL_FUNCTIONS,
    FINDING_DETAIL_TOOL_FUNCTIONS,
    RMS_TIER_TOOLS,
    TOOL_FUNCTIONS,
    drawing_tools,
)

ToolFunction = Callable[..., Any]

# --- the two encodings ----------------------------------------------------------------


def _compact(payload: Any) -> bytes:
    """The bytes an HTTP client puts on the wire: no whitespace, UTF-8."""
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def openai_objects(specs: Sequence[ToolSpec], *, trim: bool = False) -> list[dict[str, Any]]:
    """The array `OpenAIProvider.run` builds: `tool_param` per tool (`openai_provider.py`).

    `trim` is lever 2's arm, and it is applied through `ToolSpec.wire_description` - the
    same call `RecordedTool.description` makes for a real run - so the arm this module
    measures and the arm a run sends cannot drift apart.
    """
    return [tool_param(_for_wire(spec, trim=trim)) for spec in specs]


def _for_wire(spec: ToolSpec, *, trim: bool) -> ToolSpec:
    """`spec` with the description this arm actually sends on it."""
    return replace(spec, description=spec.wire_description(trim=trim), notes="")


def gemini_objects(specs: Sequence[ToolSpec], *, trim: bool = False) -> list[dict[str, Any]]:
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
            description=spec.wire_description(trim=trim),
            parameters_json_schema=gemini_adapt(spec.schema),
        )
        for spec in specs
    ]
    return [
        declaration.model_dump(mode="json", by_alias=True, exclude_none=True)
        for declaration in declarations
    ]


class Encoding(Protocol):
    """One provider's tool encoding, in either arm of lever 2."""

    def __call__(
        self, specs: Sequence[ToolSpec], *, trim: bool = False
    ) -> list[dict[str, Any]]: ...


ENCODINGS: dict[str, Encoding] = {
    "openai": openai_objects,
    "gemini": gemini_objects,
}
"""The provider encodings this feature measures. No Claude: the product has two providers."""

ARMS: tuple[bool, ...] = (False, True)
"""Lever 2 off, then on. `False` is the arm every pre-lever pin in this module measures."""


def arm_name(trim: bool) -> str:
    return "on" if trim else "off"


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
    trim: bool
    tools: int
    total_bytes: int
    largest_tool: str
    largest_tool_bytes: int


def measure(
    label: str, functions: Sequence[ToolFunction], encoding: str, *, trim: bool = False
) -> PayloadRow:
    """Encode this toolset and weigh it, whole array and largest single object."""
    specs = specs_of(functions)
    objects = ENCODINGS[encoding](specs, trim=trim)
    sizes = {spec.name: len(_compact(obj)) for spec, obj in zip(specs, objects, strict=True)}
    largest = max(sizes, key=lambda name: sizes[name]) if sizes else ""
    return PayloadRow(
        label=label,
        encoding=encoding,
        trim=trim,
        tools=len(specs),
        total_bytes=len(_compact(objects)),
        largest_tool=largest,
        largest_tool_bytes=sizes.get(largest, 0),
    )


def without(functions: Sequence[ToolFunction], names: Iterable[str]) -> tuple[ToolFunction, ...]:
    """`functions` less the ones named, in order."""
    left_out = set(names)
    return tuple(function for function in functions if function.__name__ not in left_out)


PRERUN_WITHHELD: tuple[str, ...] = prerun_tools()
"""The tools lever 13 takes off a pane review's array when checks first runs every one of
them to completion (feature 008 FR-030): the pre-run's own list, never retyped here."""

PRERUN_WITHHELD_WITH_BRIDGE: tuple[str, ...] = tuple(
    name for name in PRERUN_WITHHELD if name != INTERFERENCE_TOOL
)
"""With live detection offered the interference tool stays (`prerun.withheld_tools`)."""

TOOLSETS: dict[str, tuple[ToolFunction, ...]] = {
    "review": TOOL_FUNCTIONS,
    "review+bridge": (*TOOL_FUNCTIONS, *BRIDGE_TOOL_FUNCTIONS),
    "review+slim": (*TOOL_FUNCTIONS, *FINDING_DETAIL_TOOL_FUNCTIONS),
    "review+slim-prerun": without(
        (*TOOL_FUNCTIONS, *FINDING_DETAIL_TOOL_FUNCTIONS), PRERUN_WITHHELD
    ),
    "review+slim+bridge-prerun": without(
        (*TOOL_FUNCTIONS, *FINDING_DETAIL_TOOL_FUNCTIONS, *BRIDGE_TOOL_FUNCTIONS),
        PRERUN_WITHHELD_WITH_BRIDGE,
    ),
    "mcp": MCP_TOOL_FUNCTIONS,
    "mcp+bridge": (*MCP_TOOL_FUNCTIONS, *MCP_BRIDGE_TOOL_FUNCTIONS),
}
"""The arrays that actually get sent. The Ask tab's is not the review's (FR-039b); a review
with payload slimming on (the pane since feature 008) also offers `get_finding`; and a pane
review whose checks first ran every pre-run tool to completion offers neither those tools
(lever 13) nor, without a bridge, the interference tool."""


def baseline_rows() -> list[PayloadRow]:
    """Every toolset under every encoding, lever 2 off: what is on the wire today."""
    return [
        measure(label, functions, encoding)
        for label, functions in TOOLSETS.items()
        for encoding in ENCODINGS
    ]


def lever_two_rows() -> list[PayloadRow]:
    """The review array in both arms of lever 2, per encoding.

    Only the two review arrays: the MCP toolset has **one** arm, because `mcp/server.py`
    is handed the rejoined description whatever the review's flag says (FR-039b), and a
    table that printed a trimmed MCP number would be quoting bytes nothing ever sends.
    """
    return [
        measure(label, TOOLSETS[label], encoding, trim=trim)
        for label in ("review", "review+bridge")
        for encoding in ENCODINGS
        for trim in ARMS
    ]


# --- the RMS tier (lever 4 reads this) --------------------------------------------------

RMS_TIER_WITHHELD: tuple[str, ...] = RMS_TIER_TOOLS
"""The six tools a package with no feature tree cannot use, withheld together (lever 4).

Imported from `tools/registry.py`, where the tier declares them once. A second list here
would be exactly the transcription this module exists to prevent, and the byte pins below
would keep passing while the lever withheld a different six."""


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
    withheld: Sequence[str] = RMS_TIER_WITHHELD,
    encoding: str = "openai",
    *,
    trim: bool = False,
) -> TierDelta:
    """Weigh the curated array with `withheld` taken out of it.

    The saving is the **array** delta and not the sum of the tool objects: six objects
    leave six separators with them. Quoting the object sum understates by exactly six
    bytes, and a hand-typed figure is how that discrepancy got into the package twice.
    """
    names = set(withheld)
    kept = [function for function in TOOL_FUNCTIONS if function.__name__ not in names]
    sizes = tool_object_bytes(encoding, trim=trim)
    return TierDelta(
        encoding=encoding,
        withheld=tuple(withheld),
        kept_tools=len(kept),
        kept_bytes=measure("kept", kept, encoding, trim=trim).total_bytes,
        full_bytes=measure("review", TOOL_FUNCTIONS, encoding, trim=trim).total_bytes,
        object_bytes=sum(sizes[name] for name in withheld),
    )


# --- lever 13: the pre-run's tools off the pane array (feature 008 FR-030) ---------------------


def array_tokens(functions: Sequence[ToolFunction], encoding: str) -> int:
    """o200k_base tokens of the compact array: the replay's tokenizer over the wire bytes. An
    estimate of what a provider counts, which renders tool definitions its own way."""
    return count_tokens(_compact(ENCODINGS[encoding](specs_of(functions))).decode("utf-8"))


@dataclass(frozen=True)
class PrerunSaving:
    """What lever 13 takes off every request of a pane review, in one encoding."""

    encoding: str
    bridge: bool
    kept_tools: int
    kept_bytes: int
    full_bytes: int
    kept_tokens: int
    full_tokens: int

    @property
    def saved_bytes(self) -> int:
        return self.full_bytes - self.kept_bytes

    @property
    def saved_tokens(self) -> int:
        return self.full_tokens - self.kept_tokens


def prerun_saving(encoding: str = "openai", *, bridge: bool = False) -> PrerunSaving:
    """The slimmed pane array with and without the tools checks first ran to completion."""
    full = (
        *TOOL_FUNCTIONS,
        *FINDING_DETAIL_TOOL_FUNCTIONS,
        *(BRIDGE_TOOL_FUNCTIONS if bridge else ()),
    )
    kept = TOOLSETS["review+slim+bridge-prerun" if bridge else "review+slim-prerun"]
    return PrerunSaving(
        encoding=encoding,
        bridge=bridge,
        kept_tools=len(kept),
        kept_bytes=measure("kept", kept, encoding).total_bytes,
        full_bytes=measure("full", full, encoding).total_bytes,
        kept_tokens=array_tokens(kept, encoding),
        full_tokens=array_tokens(full, encoding),
    )


# --- the drawing arm (feature 011, `contracts/questions.md` section 7, FR-050) ------------------

DRAWING_FAMILY: tuple[ToolFunction, ...] = drawing_tools()
"""The drawing family, read from the registry and never retyped. `_offered` appends it last, after
every other group, and only when the package carries drawing evidence - so no array in `TOOLSETS`
carries it, and every constant above is measured with the family absent."""

DRAWING_FAMILY_NAMES: tuple[str, ...] = tuple(function.__name__ for function in DRAWING_FAMILY)

DRAWING_FAMILY_AFTER_PRERUN: tuple[ToolFunction, ...] = without(DRAWING_FAMILY, (DRAWINGS_TOOL,))
"""What of the family stays once checks first ran `check_drawings` to completion: lever 13 takes
the check off the array (`prerun.withheld_tools`) and the brief stays, since nothing pre-runs it."""


@dataclass(frozen=True)
class DrawingArm:
    """One array a review sends with the drawing family offered: an array of `TOOLSETS` (or the
    bridged slim array, which has no pin of its own) with the family appended."""

    label: str
    base: tuple[ToolFunction, ...]
    family: tuple[ToolFunction, ...]
    asserted: bool
    """Whether the array is asserted under `ARRAY_CEILING`. FR-050 holds the four arrays the
    ceiling was asserted on before this feature; the two bridged arrays of a review whose
    pre-run has not completed were over it already and are pinned only (research R2.20, R5 Q9)."""

    @property
    def functions(self) -> tuple[ToolFunction, ...]:
        return (*self.base, *self.family)


DRAWING_ARMS: tuple[DrawingArm, ...] = (
    DrawingArm("review+drawings", TOOLSETS["review"], DRAWING_FAMILY, asserted=True),
    DrawingArm("review+slim+drawings", TOOLSETS["review+slim"], DRAWING_FAMILY, asserted=True),
    DrawingArm(
        "review+slim+drawings-prerun",
        TOOLSETS["review+slim-prerun"],
        DRAWING_FAMILY_AFTER_PRERUN,
        asserted=True,
    ),
    DrawingArm(
        "review+slim+bridge+drawings-prerun",
        TOOLSETS["review+slim+bridge-prerun"],
        DRAWING_FAMILY_AFTER_PRERUN,
        asserted=True,
    ),
    DrawingArm("review+bridge+drawings", TOOLSETS["review+bridge"], DRAWING_FAMILY, asserted=False),
    DrawingArm(
        "review+slim+bridge+drawings",
        (*TOOLSETS["review+slim"], *BRIDGE_TOOL_FUNCTIONS),
        DRAWING_FAMILY,
        asserted=False,
    ),
)
"""The drawing arm, in the order `--write` prints it: the four asserted arrays, then the two
bridged arrays pinned so their growth shows. A pre-run arm is its pre-run array with the brief
appended, which is the order `_offered` builds and lever 13 then filters (the family is last)."""


def drawing_arm(label: str) -> DrawingArm:
    """The one drawing arm labelled `label`."""
    [arm] = [arm for arm in DRAWING_ARMS if arm.label == label]
    return arm


def drawing_arm_rows() -> list[PayloadRow]:
    """Every drawing arm under every encoding, lever 2 off."""
    return [
        measure(arm.label, arm.functions, encoding)
        for arm in DRAWING_ARMS
        for encoding in ENCODINGS
    ]


# --- what the descriptions cost (docs/llm-efficiency-options.md reads this) ---------------


def description_bytes(*, trim: bool = False) -> dict[str, int]:
    """UTF-8 bytes of each tool's own description on the wire, longest first."""
    sizes = {
        spec.name: len(spec.wire_description(trim=trim).encode("utf-8"))
        for spec in specs_of(TOOL_FUNCTIONS)
    }
    return dict(sorted(sizes.items(), key=lambda item: (-item[1], item[0])))


def tool_object_bytes(
    encoding: str = "openai",
    *,
    trim: bool = False,
    functions: Sequence[ToolFunction] = TOOL_FUNCTIONS,
) -> dict[str, int]:
    """Encoded bytes of each whole tool object, largest first: the curated array's unless
    `functions` names others (the drawing family's budgets read it that way)."""
    specs = specs_of(functions)
    objects = ENCODINGS[encoding](specs, trim=trim)
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

REVIEW_TOOL_COUNT = 35
REVIEW_BRIDGE_TOOL_COUNT = 38
OPENAI_ARRAY_BYTES = 35_844
GEMINI_ARRAY_BYTES = 35_915
"""**Deviation from T001, recorded in `specs/005-llm-efficiency/probe-log.md`.** The task
asks for 34,248; this tree produces 34,217, and a pin is a measurement or it is nothing.
Six files of the spec package still quote 34,248 (and 37,709 for the bridge, measured
37,712); probe-log.md lists them by line for the change that is allowed to edit them."""
BRIDGE_OPENAI_ARRAY_BYTES = 39_542
"""The bridged review array, lever 2 off: pinned and never asserted under the ceiling."""
TRIMMED_OPENAI_ARRAY_BYTES = 22_850
TRIMMED_GEMINI_ARRAY_BYTES = 22_921
TRIMMED_OPENAI_BRIDGE_ARRAY_BYTES = 25_413
"""Lever 2 on: the same 32 tools carrying the first paragraph of each docstring instead of
the whole body. **Regenerated, never transcribed** - `--write` prints them.

**Deviation, and it is in the lever's favour.** `contracts/levers.md` and T056 quote 23,834
bytes and 30 percent, measured before the split existed; the split that keeps the rejoin
byte-equal (T052) leaves 22,850 bytes and 36.3 percent on OpenAI. Nothing here is typed to
match a document: a pin is a measurement or it is nothing, and the same rule already
applies to `GEMINI_ARRAY_BYTES` above."""

MCP_TOOL_COUNT = 20
MCP_OPENAI_ARRAY_BYTES = 14_866
MCP_GEMINI_ARRAY_BYTES = 14_084
LARGEST_TOOL = "check_axial_stack"
LARGEST_TOOL_BYTES = 2_734
RMS_TIER_KEPT_TOOLS = 29
RMS_TIER_KEPT_BYTES = 27_751
RMS_TIER_DELTA_BYTES = 8_093
RMS_TIER_DELTA_PERCENT = 22.6
STRUCTURAL_FLOOR_BYTES = 16_042

SLIM_REVIEW_TOOL_COUNT = 36
SLIM_OPENAI_ARRAY_BYTES = 36_200
SLIM_GEMINI_ARRAY_BYTES = 36_220
"""The review array with payload slimming on (feature 008 T062): `TOOL_FUNCTIONS` plus
`get_finding`, which only a slimmed review offers. **Regenerated, never transcribed** -
`--write` prints them in its `review+slim` rows."""

PRERUN_REVIEW_TOOL_COUNT = 29
PRERUN_OPENAI_ARRAY_BYTES = 29_217
PRERUN_GEMINI_ARRAY_BYTES = 29_552
PRERUN_BRIDGE_TOOL_COUNT = 33
PRERUN_BRIDGE_OPENAI_ARRAY_BYTES = 34_145
PRERUN_BRIDGE_GEMINI_ARRAY_BYTES = 34_247
"""The pane arrays once checks first has run every pre-run tool to completion (feature 008
lever 13): the slimmed review array less the seven, and with a bridge less six, the
interference tool staying. **Regenerated, never transcribed** - `--write` prints them in its
`review+slim-prerun` and `review+slim+bridge-prerun` rows."""

PRERUN_SAVED_BYTES = {"openai": 6_983, "gemini": 6_668}
PRERUN_SAVED_TOKENS = {"openai": 1_496, "gemini": 1_435}
PRERUN_BRIDGE_SAVED_BYTES = {"openai": 5_753, "gemini": 5_489}
PRERUN_BRIDGE_SAVED_TOKENS = {"openai": 1_230, "gemini": 1_180}
"""What lever 13 takes off every request of a pane review, without and with a bridge: bytes
exactly, and o200k tokens of the compact array as an estimate (a provider renders tool
definitions its own way). `--write` prints them in its Lever 13 table."""

TOOL_OBJECT_CEILING = {"openai": 3_000, "gemini": 3_500}
"""No single tool may weigh more than this. Headroom, not a target."""

ARRAY_CEILING = 38_000
"""The ceiling for every array a review sends, in either encoding: headroom, not a target.

Raised from 36,000 (feature 005, "roughly 5 percent above today") on 2026-09-23 by the
owner, when feature 010's check tools and feature 008's `get_finding` took the slimmed pane
array to 36,220 bytes: about 5 percent above that. The tools the pre-run has already run
are the next thing to leave the array (about 6,700 bytes), not a higher ceiling - and they
did, with feature 008's lever 13 (`PRERUN_SAVED_BYTES`)."""

DRAWING_ARM_TOOL_COUNTS: dict[str, int] = {
    "review+drawings": 0,
    "review+slim+drawings": 0,
    "review+slim+drawings-prerun": 0,
    "review+slim+bridge+drawings-prerun": 0,
    "review+bridge+drawings": 0,
    "review+slim+bridge+drawings": 0,
}
DRAWING_ARM_BYTES: dict[str, dict[str, int]] = {
    "review+drawings": {"openai": 0, "gemini": 0},
    "review+slim+drawings": {"openai": 0, "gemini": 0},
    "review+slim+drawings-prerun": {"openai": 0, "gemini": 0},
    "review+slim+bridge+drawings-prerun": {"openai": 0, "gemini": 0},
    "review+bridge+drawings": {"openai": 0, "gemini": 0},
    "review+slim+bridge+drawings": {"openai": 0, "gemini": 0},
}
"""The drawing arm (feature 011 FR-050): every `DRAWING_ARMS` array per encoding, lever 2 off.
**Regenerated, never transcribed** - `--write` prints them in its Drawing arm table, in a commit
of their own (T055). The first four are also asserted under `ARRAY_CEILING`; the two bridged
arrays are pinned only, because they were over it before the family existed."""

DRAWING_TOOL_BUDGET: dict[str, int] = {"check_drawings": 450, "get_drawing_brief": 650}
"""The most bytes each drawing tool object may weigh, in either encoding (`contracts/questions.md`
section 1): the two together leave the slim Gemini array under the ceiling (research R2.20)."""

EXISTING_PINS: dict[tuple[str, str], int] = {
    ("review+drawings", "openai"): OPENAI_ARRAY_BYTES,
    ("review+drawings", "gemini"): GEMINI_ARRAY_BYTES,
    ("review+slim+drawings", "openai"): SLIM_OPENAI_ARRAY_BYTES,
    ("review+slim+drawings", "gemini"): SLIM_GEMINI_ARRAY_BYTES,
    ("review+slim+drawings-prerun", "openai"): PRERUN_OPENAI_ARRAY_BYTES,
    ("review+slim+drawings-prerun", "gemini"): PRERUN_GEMINI_ARRAY_BYTES,
    ("review+slim+bridge+drawings-prerun", "openai"): PRERUN_BRIDGE_OPENAI_ARRAY_BYTES,
    ("review+slim+bridge+drawings-prerun", "gemini"): PRERUN_BRIDGE_GEMINI_ARRAY_BYTES,
    ("review+bridge+drawings", "openai"): BRIDGE_OPENAI_ARRAY_BYTES,
}
"""Every constant above that a drawing arm extends, by arm and encoding: the arm with the family
taken out must measure exactly this. The bridged slim array and the bridged Gemini array had no
pin before this feature, so they have no entry."""


# --- the tests ---------------------------------------------------------------------------


def test_curated_tool_count_is_pinned() -> None:
    """35 tools, 38 with the bridge (32 and 35 until feature 010 T028 added
    `check_joints`, 33 and 36 until T067 and T075 added `check_mass_material` and
    `check_hygiene`). A new tool is a decision, not an accident."""
    assert len(TOOL_FUNCTIONS) == REVIEW_TOOL_COUNT
    assert len(TOOLSETS["review+bridge"]) == REVIEW_BRIDGE_TOOL_COUNT


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("openai", OPENAI_ARRAY_BYTES), ("gemini", GEMINI_ARRAY_BYTES)],
)
def test_curated_array_bytes_per_encoding(encoding: str, expected: int) -> None:
    """The whole tool array, compact, as each adapter sends it with every lever off."""
    assert measure("review", TOOL_FUNCTIONS, encoding).total_bytes == expected


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("openai", TRIMMED_OPENAI_ARRAY_BYTES), ("gemini", TRIMMED_GEMINI_ARRAY_BYTES)],
)
def test_trimmed_array_bytes_per_encoding(encoding: str, expected: int) -> None:
    """The same array with `trim_tool_descriptions` on: lever 2's whole arithmetic."""
    assert measure("review", TOOL_FUNCTIONS, encoding, trim=True).total_bytes == expected


def test_the_bridge_array_is_pinned_in_both_arms() -> None:
    """The 35-tool array a bridged run sends, so a US3 session is measured too."""
    bridged = TOOLSETS["review+bridge"]
    assert measure("review+bridge", bridged, "openai").total_bytes == BRIDGE_OPENAI_ARRAY_BYTES
    assert (
        measure("review+bridge", bridged, "openai", trim=True).total_bytes
        == TRIMMED_OPENAI_BRIDGE_ARRAY_BYTES
    )


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("openai", SLIM_OPENAI_ARRAY_BYTES), ("gemini", SLIM_GEMINI_ARRAY_BYTES)],
)
def test_the_slimmed_review_array_is_pinned(encoding: str, expected: int) -> None:
    """Feature 008 T062: the array a pane review sends - one tool more than the review's,
    `get_finding`, and still under the ceiling."""
    slim = TOOLSETS["review+slim"]
    total = measure("review+slim", slim, encoding).total_bytes

    assert len(slim) == SLIM_REVIEW_TOOL_COUNT == REVIEW_TOOL_COUNT + 1
    assert total == expected
    assert total < ARRAY_CEILING


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("openai", PRERUN_OPENAI_ARRAY_BYTES), ("gemini", PRERUN_GEMINI_ARRAY_BYTES)],
)
def test_the_pane_array_without_the_pre_runs_tools_is_pinned(encoding: str, expected: int) -> None:
    """Feature 008 lever 13: the array a pane review sends once checks first ran all seven."""
    array = TOOLSETS["review+slim-prerun"]
    total = measure("review+slim-prerun", array, encoding).total_bytes

    assert len(array) == PRERUN_REVIEW_TOOL_COUNT == SLIM_REVIEW_TOOL_COUNT - len(PRERUN_WITHHELD)
    assert total == expected
    assert total < ARRAY_CEILING


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("openai", PRERUN_BRIDGE_OPENAI_ARRAY_BYTES), ("gemini", PRERUN_BRIDGE_GEMINI_ARRAY_BYTES)],
)
def test_the_bridged_pane_array_without_the_pre_runs_tools_is_pinned(
    encoding: str, expected: int
) -> None:
    """With a bridge the interference tool stays: live detection can add groups only it
    judges (`prerun.withheld_tools`)."""
    array = TOOLSETS["review+slim+bridge-prerun"]
    total = measure("review+slim+bridge-prerun", array, encoding).total_bytes

    assert INTERFERENCE_TOOL in {function.__name__ for function in array}
    assert len(array) == PRERUN_BRIDGE_TOOL_COUNT
    assert total == expected
    assert total < ARRAY_CEILING


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize("encoding", sorted(ENCODINGS))
def test_the_per_round_saving_of_lever_13_is_pinned(encoding: str) -> None:
    plain = prerun_saving(encoding)
    bridged = prerun_saving(encoding, bridge=True)

    assert (plain.saved_bytes, plain.saved_tokens) == (
        PRERUN_SAVED_BYTES[encoding],
        PRERUN_SAVED_TOKENS[encoding],
    )
    assert (bridged.saved_bytes, bridged.saved_tokens) == (
        PRERUN_BRIDGE_SAVED_BYTES[encoding],
        PRERUN_BRIDGE_SAVED_TOKENS[encoding],
    )
    assert plain.full_bytes == measure("slim", TOOLSETS["review+slim"], encoding).total_bytes


def test_the_saving_is_the_withheld_objects_plus_one_separator_each() -> None:
    """As for the RMS tier: an array delta, not an object sum."""
    sizes = tool_object_bytes("openai")

    assert prerun_saving("openai").saved_bytes == (
        sum(sizes[name] for name in PRERUN_WITHHELD) + len(PRERUN_WITHHELD)
    )


def test_the_pinned_array_is_the_one_a_pane_review_offers(tmp_path: Path) -> None:
    """The pin measures what lever 13 really leaves: the array a pane review of the pre-run
    fixture hands its provider, name for name and in order."""
    from swreview.agent.providers import ProviderName
    from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
    from swreview.agent.runner import start_review
    from swreview.agent.settings import pane_defaults
    from swreview.ir.loader import save_package
    from tests.support.prerun import prerun_package

    save_package(prerun_package(), tmp_path)
    pane = pane_defaults(ProviderName.FAKE)
    run = start_review(
        tmp_path,
        tmp_path,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=pane.efficiency,
        model_view=pane.model_view,
    )

    assert [tool.name for tool in run.tools] == [
        function.__name__ for function in TOOLSETS["review+slim-prerun"]
    ]


@pytest.mark.parametrize("encoding", sorted(ENCODINGS))
def test_the_trim_takes_the_same_bytes_off_either_encoding(encoding: str) -> None:
    """The saving is description text, which both encodings carry identically; only the
    schema conversion differs, and lever 2 does not touch a schema."""
    off = measure("review", TOOL_FUNCTIONS, encoding).total_bytes
    on = measure("review", TOOL_FUNCTIONS, encoding, trim=True).total_bytes

    assert off - on == 12_994


def test_the_trim_is_bounded_by_the_structural_floor() -> None:
    """36 percent off, and the remaining 16,042 bytes is structure no trim can reach."""
    off = measure("review", TOOL_FUNCTIONS, "openai").total_bytes
    on = measure("review", TOOL_FUNCTIONS, "openai", trim=True).total_bytes

    assert round(100 * (off - on) / off, 1) == 36.3
    assert on > structural_floor_bytes()


def test_the_mcp_toolset_has_one_arm_because_it_sends_the_rejoined_description() -> None:
    """FR-039b, pinned as bytes: what the Ask tab sends does not move when lever 2 does.

    `mcp/server.py`'s `_as_tool` reads `full_description`, so the trimmed measurement
    below is a number nothing ever puts on a wire. It is asserted *different* rather than
    printed in the baseline table, so no reader can quote it as the Ask tab's payload.
    """
    off = measure("mcp", MCP_TOOL_FUNCTIONS, "openai").total_bytes
    assert off == MCP_OPENAI_ARRAY_BYTES
    assert measure("mcp", MCP_TOOL_FUNCTIONS, "openai", trim=True).total_bytes != off


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
    """Withholding the six RMS tools: 35 tools to 29, and what that takes off the wire."""
    delta = tier_delta()
    assert delta.kept_tools == RMS_TIER_KEPT_TOOLS
    assert delta.kept_bytes == RMS_TIER_KEPT_BYTES
    assert delta.delta_bytes == RMS_TIER_DELTA_BYTES
    assert delta.delta_percent == RMS_TIER_DELTA_PERCENT
    # The six array separators are the whole difference between the two figures that
    # diverged across the feature package: 8,093 on the wire, 8,087 of tool objects.
    assert delta.object_bytes == 8_087
    assert delta.delta_bytes == delta.object_bytes + len(RMS_TIER_WITHHELD)


def test_the_rms_tier_delta_shrinks_once_lever_2_has_taken_its_bytes() -> None:
    """Levers 2 and 4 are not additive: what lever 4 withholds, lever 2 already thinned.

    8,093 bytes of the untrimmed array, 2,745 of the trimmed one. An A/B row that ran both
    levers in one arm and added their published savings would overstate by 5,348 bytes,
    which is why every row records which other levers were on.
    """
    assert tier_delta(trim=True).delta_bytes == 2_745
    assert tier_delta(trim=True).delta_percent == 12.0
    assert tier_delta(trim=True).kept_tools == RMS_TIER_KEPT_TOOLS


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
    """The two lists `docs/llm-efficiency-options.md` quotes, regenerated here (T002).

    Lever 2 off, which is what the document measured: `description_bytes()` reads
    `wire_description(trim=False)`, the rejoined text, so these four numbers are the same
    ones the pre-split tree produced.
    """
    assert list(description_bytes().items())[:4] == [
        ("check_rms_assembly", 1_455),
        ("check_rms_part", 1_296),
        ("check_interference_group", 905),
        ("check_fastener_joint", 871),
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


# --- the drawing arm (feature 011, FR-050) --------------------------------------------------------

ARM_BY_ENCODING = [
    pytest.param(arm, encoding, id=f"{arm.label}-{encoding}")
    for arm in DRAWING_ARMS
    for encoding in sorted(ENCODINGS)
]
ASSERTED_ARM_BY_ENCODING = [param for param in ARM_BY_ENCODING if param.values[0].asserted]


def test_the_family_is_read_from_the_registry_and_no_existing_array_carries_it() -> None:
    """Every constant pinned before feature 011 measures an array with the family absent: the
    family is outside `REGISTRATIONS`, the MCP lists and every `TOOLSETS` array."""
    assert DRAWING_FAMILY == drawing_tools()
    assert DRAWING_FAMILY_NAMES == ("check_drawings", "get_drawing_brief")
    assert DRAWING_FAMILY_AFTER_PRERUN == (DRAWING_FAMILY[1],)
    for label, functions in TOOLSETS.items():
        carried = {function.__name__ for function in functions} & set(DRAWING_FAMILY_NAMES)
        assert carried == set(), f"{label} carries {sorted(carried)}"


def test_the_arm_is_the_four_asserted_arrays_then_the_two_bridged_ones() -> None:
    """FR-050's scope, stated once: the ceiling holds what it held before the family existed."""
    assert [arm.label for arm in DRAWING_ARMS if arm.asserted] == [
        "review+drawings",
        "review+slim+drawings",
        "review+slim+drawings-prerun",
        "review+slim+bridge+drawings-prerun",
    ]
    assert [arm.label for arm in DRAWING_ARMS if not arm.asserted] == [
        "review+bridge+drawings",
        "review+slim+bridge+drawings",
    ]
    assert set(DRAWING_ARM_TOOL_COUNTS) == set(DRAWING_ARM_BYTES) == {
        arm.label for arm in DRAWING_ARMS
    }


@pytest.mark.parametrize(("arm", "encoding"), ARM_BY_ENCODING)
def test_every_existing_constant_is_its_drawing_arm_with_the_family_absent(
    arm: DrawingArm, encoding: str
) -> None:
    """Recomputed with the family taken out, every constant the arm extends is unchanged: the
    family adds its bytes and moves no existing figure (`contracts/questions.md` section 7)."""
    absent = without(arm.functions, DRAWING_FAMILY_NAMES)

    assert absent == arm.base
    if (arm.label, encoding) in EXISTING_PINS:
        assert measure(arm.label, absent, encoding).total_bytes == EXISTING_PINS[
            (arm.label, encoding)
        ]


@pytest.mark.parametrize(("arm", "encoding"), ARM_BY_ENCODING)
def test_each_arm_is_its_base_plus_the_family_objects_and_one_separator_each(
    arm: DrawingArm, encoding: str
) -> None:
    """As for the RMS tier and lever 13: an array delta, never an object sum."""
    sizes = tool_object_bytes(encoding, functions=arm.family)
    base = measure(arm.label, arm.base, encoding).total_bytes

    assert measure(arm.label, arm.functions, encoding).total_bytes == (
        base + sum(sizes.values()) + len(arm.family)
    )


@pytest.mark.parametrize(("arm", "encoding"), ARM_BY_ENCODING)
def test_the_drawing_arm_is_pinned(arm: DrawingArm, encoding: str) -> None:
    """Every drawing arm, the two bridged ones included, so any growth shows."""
    assert len(arm.functions) == DRAWING_ARM_TOOL_COUNTS[arm.label]
    assert len(arm.functions) == len(arm.base) + len(arm.family)
    assert (
        measure(arm.label, arm.functions, encoding).total_bytes
        == DRAWING_ARM_BYTES[arm.label][encoding]
    )


@pytest.mark.parametrize(("arm", "encoding"), ASSERTED_ARM_BY_ENCODING)
def test_the_asserted_drawing_arms_stay_under_the_ceiling(arm: DrawingArm, encoding: str) -> None:
    """FR-050: every array the ceiling held before feature 011 holds it with the family offered.
    `ARRAY_CEILING` stays 38,000."""
    assert ARRAY_CEILING == 38_000
    assert measure(arm.label, arm.functions, encoding).total_bytes < ARRAY_CEILING


@pytest.mark.parametrize("encoding", sorted(ENCODINGS))
def test_each_drawing_tool_object_is_under_its_budget(encoding: str) -> None:
    """`check_drawings` at most 450 bytes and `get_drawing_brief` at most 650, per encoding, and
    no family tool without a budget."""
    sizes = tool_object_bytes(encoding, functions=DRAWING_FAMILY)

    assert set(sizes) == set(DRAWING_TOOL_BUDGET)
    over = {name: size for name, size in sizes.items() if size > DRAWING_TOOL_BUDGET[name]}
    assert over == {}, f"{encoding}: drawing tool(s) over budget: {over}"


def test_the_pinned_drawing_arm_is_the_one_a_pane_review_offers(tmp_path: Path) -> None:
    """The pre-run arm measures what a pane review of a package with drawing evidence really
    hands its provider once checks first ran everything: the pre-run array, then the brief,
    `check_drawings` withheld by lever 13 - name for name and in order."""
    from swreview.agent.providers import ProviderName
    from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
    from swreview.agent.runner import start_review
    from swreview.agent.settings import pane_defaults
    from swreview.ir.loader import save_package
    from tests.support.drawings import DrawingBuilder
    from tests.support.prerun import prerun_package

    base = prerun_package()
    builder = DrawingBuilder(base)
    builder.candidate(base.design.root_assembly_document_id)
    # `profile="standards"` keeps the base package's dump phases, so the pre-run sees the
    # package it always saw plus one drawing candidate.
    save_package(builder.build(profile="standards"), tmp_path)
    pane = pane_defaults(ProviderName.FAKE)
    run = start_review(
        tmp_path,
        tmp_path,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=pane.efficiency,
        model_view=pane.model_view,
    )

    assert [tool.name for tool in run.tools] == [
        function.__name__ for function in drawing_arm("review+slim+drawings-prerun").functions
    ]


def test_the_write_helper_prints_the_drawing_arm_in_rows_of_its_own() -> None:
    """One row per arm per encoding, after everything the table printed before the family, so
    no existing line of the baseline moves."""
    table = drawing_arm_table()
    rows = [line for line in table.splitlines() if line.startswith("| review")]

    assert baseline_table().endswith("\n\n" + table)
    assert len(rows) == len(DRAWING_ARMS) * len(ENCODINGS)
    for row in drawing_arm_rows():
        ceiling = "asserted" if drawing_arm(row.label).asserted else "pinned, not asserted"
        assert (
            f"| {row.label} | {row.encoding} | {row.tools} | {row.total_bytes:,} | {ceiling} |"
            in rows
        )
    for encoding in ENCODINGS:
        sizes = tool_object_bytes(encoding, functions=DRAWING_FAMILY)
        assert all(f"`{name}` {size:,}" in table for name, size in sizes.items())


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
    lines.append("| Lever 2 | Encoding | Arm | Tools | Bytes | Delta | Delta % |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    for row in lever_two_rows():
        off = measure(row.label, TOOLSETS[row.label], row.encoding).total_bytes
        delta = off - row.total_bytes
        lines.append(
            f"| {row.label} | {row.encoding} | {arm_name(row.trim)} | {row.tools} "
            f"| {row.total_bytes:,} | {delta:,} | {round(100 * delta / off, 1)} |"
        )
    lines.append("")
    lines.append(
        "The MCP toolset has one arm: `mcp/server.py` is handed the rejoined description "
        "whatever the review's flag says (FR-039b)."
    )
    lines.append("")
    lines.append("| RMS tier | Encoding | Arm | Kept tools | Kept bytes | Delta | Delta % |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    for encoding in ENCODINGS:
        for trim in ARMS:
            delta = tier_delta(encoding=encoding, trim=trim)
            lines.append(
                f"| withhold {len(delta.withheld)} RMS tools | {encoding} "
                f"| {arm_name(trim)} | {delta.kept_tools} | {delta.kept_bytes:,} "
                f"| {delta.delta_bytes:,} | {delta.delta_percent} |"
            )
    lines.append("")
    lines.append(
        "| Lever 13 | Encoding | Kept tools | Kept bytes | Saved bytes per round "
        "| Saved % | Saved tokens per round (o200k) |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for bridge in (False, True):
        for encoding in ENCODINGS:
            saving = prerun_saving(encoding, bridge=bridge)
            lines.append(
                f"| pane{' + bridge' if bridge else ''} | {encoding} | {saving.kept_tools} "
                f"| {saving.kept_bytes:,} | {saving.saved_bytes:,} "
                f"| {round(100 * saving.saved_bytes / saving.full_bytes, 1)} "
                f"| {saving.saved_tokens:,} |"
            )
    lines.append("")
    floor = structural_floor_bytes()
    total = measure("review", TOOL_FUNCTIONS, "openai").total_bytes
    lines.append(
        f"Structural floor (every description emptied, openai): {floor:,} bytes, "
        f"{round(100 * floor / total)} percent of {total:,}."
    )
    lines.append("")
    for trim in ARMS:
        longest = ", ".join(
            f"`{n}` {b:,}" for n, b in list(description_bytes(trim=trim).items())[:4]
        )
        largest = ", ".join(
            f"`{n}` {b:,}" for n, b in list(tool_object_bytes(trim=trim).items())[:3]
        )
        lines.append(f"Longest descriptions (lever 2 {arm_name(trim)}): {longest}")
        lines.append(f"Largest tool objects (openai, lever 2 {arm_name(trim)}): {largest}")
    lines.append("")
    lines.append("sha256: " + ", ".join(f"{k} {v}" for k, v in encoding_digests().items()))
    lines.append("")
    lines.append(drawing_arm_table())
    return "\n".join(lines)


def drawing_arm_table() -> str:
    """The drawing arm (feature 011), in rows of its own after every line printed before it:
    `DRAWING_ARM_TOOL_COUNTS` and `DRAWING_ARM_BYTES` are pasted from here, and the family's
    object sizes beside their budgets."""
    lines = [
        f"| Drawing arm | Encoding | Tools | Bytes | Under {ARRAY_CEILING:,} |",
        "|---|---|---:|---:|---|",
    ]
    for row in drawing_arm_rows():
        ceiling = "asserted" if drawing_arm(row.label).asserted else "pinned, not asserted"
        lines.append(
            f"| {row.label} | {row.encoding} | {row.tools} | {row.total_bytes:,} | {ceiling} |"
        )
    lines.append("")
    for encoding in ENCODINGS:
        sizes = tool_object_bytes(encoding, functions=DRAWING_FAMILY)
        objects = ", ".join(
            f"`{name}` {size:,} (budget {DRAWING_TOOL_BUDGET[name]:,})"
            for name, size in sizes.items()
        )
        lines.append(f"Drawing family objects ({encoding}, lever 2 off): {objects}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - the regeneration helper, not a test path
    if "--write" not in sys.argv[1:]:
        print("usage: python -m tests.unit.test_tool_payload --write", file=sys.stderr)
        raise SystemExit(2)
    print(baseline_table())
