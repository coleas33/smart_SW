"""Lever 2, second half: where the moved text lands, and what the wire weighs (T054).

T052 split the docstring in two and pinned the rejoin byte-equal to the pre-split text.
This module is the other half of the lever: the `Notes:` block a tool no longer sends is
rendered **once** into the system prompt, the flag decides which of the two strings a
provider is handed, and the caps are held over all 35 real docstrings rather than over a
hand-built fixture.

Five things are pinned here, in the order they matter:

1. **The notes are rendered once, from the specs the adapter is about to be handed.**
   `build_system_prompt` appends a `## Tool notes` block after the package census when
   `trim_tool_descriptions` is on and nothing at all when it is off. Once, in the system
   prompt, rather than once per tool per request, is the whole arithmetic of this lever;
   and the system prompt is the half of the prefix that never varies, which is the right
   direction for lever 3 as well.
2. **The flag is applied after `spec_for`.** `_SPECS` is process-global and keyed by
   function (`tools/registry.py`), so a flag read while *building* a spec would let the
   first run in a process - the benchmark runner's first package, or whichever test ran
   first - decide what every later run in that process sends. The application point is
   `RecordedTool.description`, where the run's settings are already in scope, and
   `test_two_dispatches_in_one_process_disagree_about_the_description` is the guard.
3. **SC-007 on the wire.** With every flag off, the encoded tool array in both provider
   encodings is byte-equal to the pre-split encoding `test_tool_payload` already pins, so
   the post-split commit reproduces the pre-split bytes and both A/B arms run from one
   commit. The pins are imported from that module rather than restated: one committed
   file, not new machinery.
4. **The caps, over the real docstrings.** Every first paragraph is under 160 characters.
   Every `Args:` entry is under 90 **except the nine named in `CAP_EXCEPTIONS`**, which
   are the lever 2 exceptions T053 provides for: an `Args:` entry has no paragraph
   boundary to split at, so bringing one under the cap means rewording it, and rewording
   it changes the schema in **both** arms and breaks point 3. Naming them is the honest
   answer; a silent rewrite is not, and neither is a cap nobody enforces.
5. **The MCP toolset is a stated choice, not an accident.** `mcp/server.py` builds its own
   tool list from `spec_for` and has no system prompt to render notes into (`instructions`
   is a fixed literal), so the Ask tab is handed the **rejoined** description whatever the
   review's flag says. There is no run and no `EfficiencySettings` behind an Ask-tab tool
   call to read a flag from, and a tool whose notes went nowhere would be a silent trim
   (FR-039b).

No network and no key: the one played session runs through the scripted fake.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.checklist import load_checklist
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.providers.schema import (
    MAX_DESCRIPTION_LENGTH,
    MAX_PARAMETER_DESCRIPTION_LENGTH,
    ToolSpec,
    cap_violations,
    tool_spec,
)
from swreview.agent.settings import EfficiencySettings
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import EvidencePackage
from swreview.mcp.server import MCP_BRIDGE_TOOL_FUNCTIONS, MCP_TOOL_FUNCTIONS, _as_tool
from swreview.tools.context import ToolContext
from swreview.tools.registry import (
    BRIDGE_TOOL_FUNCTIONS,
    TOOL_FUNCTIONS,
    RecordedTool,
    ToolCallRecord,
    ToolRegistry,
    spec_for,
)
from tests.support.packages import build_package
from tests.unit.test_tool_payload import (
    GEMINI_ARRAY_BYTES,
    OPENAI_ARRAY_BYTES,
    measure,
)

ALL_TOOL_FUNCTIONS = (*TOOL_FUNCTIONS, *BRIDGE_TOOL_FUNCTIONS)
ALL_MCP_TOOL_FUNCTIONS = (*MCP_TOOL_FUNCTIONS, *MCP_BRIDGE_TOOL_FUNCTIONS)

ON = EfficiencySettings(trim_tool_descriptions=True)
OFF = EfficiencySettings()


class ListSink:
    """A recording sink that keeps its records, so a sessionless context can build tools."""

    def __init__(self) -> None:
        self.records: list[ToolCallRecord] = []

    def record(self, record: ToolCallRecord) -> None:
        self.records.append(record)


def sessionless(package: EvidencePackage | None = None) -> ToolContext:
    """A context with no review session: enough to build the tools and read them."""
    return ToolContext(
        package=LoadedPackage(package=package or build_package(), base_dir=Path(".")),
        session=None,
        checklist=load_checklist(),
    )


def built(efficiency: EfficiencySettings) -> dict[str, RecordedTool]:
    """The curated tools as a provider would be handed them under these settings."""
    tools = ToolRegistry().dispatch(sessionless(), sink=ListSink(), efficiency=efficiency)
    return {tool.name: tool for tool in tools}


def specs() -> list[ToolSpec]:
    """The curated specs, built through the registry's own cache, as the runner does."""
    return [spec_for(function) for function in TOOL_FUNCTIONS]


def with_notes() -> list[ToolSpec]:
    return [spec for spec in specs() if spec.notes]


# --- the `## Tool notes` block ------------------------------------------------------


@pytest.fixture
def package() -> EvidencePackage:
    return build_package()


def prompt(efficiency: EfficiencySettings, package: EvidencePackage) -> str:
    return runner.build_system_prompt(
        load_checklist(), package, specs(), efficiency=efficiency
    )


def test_the_flag_off_prompt_carries_no_tool_notes_at_all(package: EvidencePackage) -> None:
    """Flag off is the feature 001 prompt, unchanged: no header and no note text."""
    text = prompt(OFF, package)

    assert runner.TOOL_NOTES_HEADER not in text
    for spec in with_notes():
        assert spec.notes not in text


def test_the_flag_off_prompt_is_what_the_pre_lever_signature_produced(
    package: EvidencePackage,
) -> None:
    """The block is the only difference, so a flag-off run renders identically (SC-007)."""
    assert prompt(OFF, package) == runner.build_system_prompt(load_checklist(), package)


def test_the_flag_on_prompt_carries_every_tool_s_notes_exactly_once(
    package: EvidencePackage,
) -> None:
    """The point of the lever: 10 KB moved out of every request into one prompt."""
    text = prompt(ON, package)

    assert text.count(runner.TOOL_NOTES_HEADER) == 1
    for spec in with_notes():
        assert text.count(spec.notes) == 1
        assert text.count(f"### {spec.name}\n") == 1


def test_the_notes_block_is_appended_once_after_the_package_census(
    package: EvidencePackage,
) -> None:
    """Appended, not interleaved: the prompt an engineer already knows plus a block."""
    off = prompt(OFF, package)
    on = prompt(ON, package)

    assert on.startswith(off + "\n\n" + runner.TOOL_NOTES_HEADER)


def test_a_tool_with_no_notes_gets_no_heading(package: EvidencePackage) -> None:
    """`list_components` is one paragraph and stays one: an empty heading is noise."""
    text = prompt(ON, package)

    for spec in specs():
        if not spec.notes:
            assert f"### {spec.name}\n" not in text


def test_the_block_renders_from_the_specs_it_is_handed_and_no_others(
    package: EvidencePackage,
) -> None:
    """Lever 4 will hand over fewer tools; the notes must follow the tools, not the list."""
    chosen = [spec for spec in with_notes()][:2]
    text = runner.build_system_prompt(load_checklist(), package, chosen, efficiency=ON)

    for spec in chosen:
        assert f"### {spec.name}\n" in text
    for spec in with_notes()[2:]:
        assert f"### {spec.name}\n" not in text


def test_no_tools_at_all_renders_no_block(package: EvidencePackage) -> None:
    """A header over nothing tells the model there is something it did not get."""
    assert runner.TOOL_NOTES_HEADER not in runner.build_system_prompt(
        load_checklist(), package, (), efficiency=ON
    )


# --- what a provider is handed ------------------------------------------------------


def test_the_flag_off_tools_carry_the_rejoined_description() -> None:
    """FR-039: byte-equal to the pre-split docstring body, for every curated tool."""
    tools = built(OFF)

    for spec in specs():
        assert tools[spec.name].description == spec.full_description


def test_the_flag_on_tools_carry_the_trimmed_description() -> None:
    """The first paragraph alone, which is what the model reads to choose among 32."""
    tools = built(ON)

    for spec in specs():
        assert tools[spec.name].description == spec.description


def test_a_dispatch_built_without_settings_is_the_flag_off_one() -> None:
    """Every caller that predates the lever - the MCP bind, a test - sends the full text."""
    tools = {
        tool.name: tool
        for tool in ToolRegistry().dispatch(sessionless(), sink=ListSink())
    }

    for spec in specs():
        assert tools[spec.name].description == spec.full_description


def test_two_dispatches_in_one_process_disagree_about_the_description() -> None:
    """The cache trap: `_SPECS` is process-global, so the flag is read *after* `spec_for`.

    A flag read inside `spec_for` would make the first run in a process decide for every
    later one - silently, since both runs would still record the settings they *asked*
    for. The benchmark runner plays six runs in one process, three of them off.
    """
    off = built(OFF)
    on = built(ON)

    trimmed = next(spec for spec in specs() if spec.notes)
    assert off[trimmed.name].description != on[trimmed.name].description
    assert off[trimmed.name].description == trimmed.full_description
    assert on[trimmed.name].description == trimmed.description


def test_the_cached_spec_itself_is_never_rewritten_by_the_flag() -> None:
    """`spec_for` returns one object per function; the flag must not mutate it."""
    before = spec_for(TOOL_FUNCTIONS[0]).description
    built(ON)
    built(OFF)

    assert spec_for(TOOL_FUNCTIONS[0]).description == before


# --- SC-007 on the wire --------------------------------------------------------------


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("openai", OPENAI_ARRAY_BYTES), ("gemini", GEMINI_ARRAY_BYTES)],
)
def test_the_flag_off_array_is_byte_equal_to_the_pinned_pre_split_encoding(
    encoding: str, expected: int
) -> None:
    """SC-007: the post-split commit with every flag off sends the pre-split bytes.

    The pins come from `test_tool_payload`, which measured them before a docstring was
    touched, rather than being restated here: one committed file, not new machinery.
    """
    assert measure("review", TOOL_FUNCTIONS, encoding, trim=False).total_bytes == expected


@pytest.mark.parametrize("encoding", ["openai", "gemini"])
def test_the_flag_on_array_is_smaller_than_the_flag_off_one(encoding: str) -> None:
    """The lever does something. How much is `test_tool_payload`'s pinned table."""
    off = measure("review", TOOL_FUNCTIONS, encoding, trim=False).total_bytes
    on = measure("review", TOOL_FUNCTIONS, encoding, trim=True).total_bytes

    assert on < off


# --- the caps, over all 35 real docstrings ---------------------------------------------

CAP_EXCEPTIONS: tuple[str, ...] = (
    "bridge_interference.settings",
    "check_axial_stack.dimension_refs",
    "check_fit.bore_dimension_ref",
    "check_hole_alignment.tolerance",
    "check_rms_part.document_id",
    "list_features.folder",
    "list_features.include_suppressed",
    "mark_coverage.scope",
    "record_drawing_finding.source_refs",
)
"""The nine named lever 2 exceptions, for the ledger row (T053, FR-033).

Every one is an `Args:` entry, and an `Args:` entry is the one piece of a docstring the
split cannot move: it has no paragraph boundary to break at, and it is the *schema*, not
the description, so shortening one changes what the flag-**off** arm sends and breaks
SC-007 and the same-commit A/B. They are named here rather than reworded, which is exactly
the exception T053 provides for, and `test_the_named_exceptions_are_all_still_over_the_cap`
stops the list outliving them.
"""


def parameter_violations(spec: ToolSpec) -> list[str]:
    """`cap_violations` messages about this tool's parameters, keyed `tool.parameter`."""
    return [message for message in cap_violations(spec) if message.split(":")[0].count(".") == 1]


def over_the_cap(spec: ToolSpec) -> set[str]:
    return {message.split(":")[0] for message in parameter_violations(spec)}


def test_the_split_covers_every_tool_that_reaches_a_provider() -> None:
    """35, the number T056 rewrote and the number the caps are asserted over."""
    assert len(ALL_TOOL_FUNCTIONS) == 35


@pytest.mark.parametrize(
    "function", ALL_TOOL_FUNCTIONS, ids=[function.__name__ for function in ALL_TOOL_FUNCTIONS]
)
def test_every_description_is_under_the_160_character_cap(function: Any) -> None:
    """By construction, at an existing paragraph boundary, never by truncation (T053)."""
    spec = tool_spec(function)

    assert len(spec.description) <= MAX_DESCRIPTION_LENGTH, spec.description


def test_no_parameter_is_over_the_cap_except_the_named_exceptions() -> None:
    """The 90-character `Args:` cap, with its exception list closed and named."""
    over: set[str] = set()
    for function in ALL_TOOL_FUNCTIONS:
        over |= over_the_cap(tool_spec(function))

    assert over == set(CAP_EXCEPTIONS)


def test_the_named_exceptions_are_all_still_over_the_cap() -> None:
    """A list that outlived its reasons is a cap nobody is enforcing any more."""
    lengths = {
        f"{spec.name}.{parameter}": len(schema.get("description", ""))
        for spec in (tool_spec(function) for function in ALL_TOOL_FUNCTIONS)
        for parameter, schema in spec.schema.get("properties", {}).items()
    }

    for name in CAP_EXCEPTIONS:
        assert lengths[name] > MAX_PARAMETER_DESCRIPTION_LENGTH, name


def test_every_description_still_ends_a_sentence() -> None:
    """The cheap tell for a truncation: a first paragraph that stops mid-word."""
    for function in ALL_TOOL_FUNCTIONS:
        description = tool_spec(function).description

        assert description.rstrip()[-1] in ".:!?`", description


# --- the MCP toolset (FR-039b) ---------------------------------------------------------


@pytest.mark.parametrize(
    "function",
    ALL_MCP_TOOL_FUNCTIONS,
    ids=[function.__name__ for function in ALL_MCP_TOOL_FUNCTIONS],
)
def test_the_mcp_toolset_is_handed_the_rejoined_description(function: Any) -> None:
    """The Ask tab has no system prompt to render notes into, so it sends both halves.

    `instructions` on the MCP server is a fixed literal, there is no `EfficiencySettings`
    behind an Ask-tab call to read a flag from, and a tool whose notes went nowhere would
    be a silent trim. Stated, per FR-039b, rather than left to fall out of the default.
    """
    spec = tool_spec(function)

    assert _as_tool(spec).description == spec.full_description


def test_the_mcp_toolset_does_not_read_the_review_s_flag() -> None:
    """Built through `spec_for` with no settings anywhere near it; nothing to toggle."""
    built(ON)

    spec = tool_spec(MCP_TOOL_FUNCTIONS[0])
    assert _as_tool(spec).description == spec.full_description


# --- one played session ------------------------------------------------------------------

SCRIPT: tuple[ScriptedTurn, ...] = (
    ScriptedTurn(
        text="Read the census and stopped.",
        tool_calls=(ScriptedToolCall("get_package_summary"),),
    ),
)

VOLATILE = frozenset(
    {
        "session_id",
        "started_at",
        "ended_at",
        "efficiency",
        "elapsed_s",
        "unattended_runtime_minutes",
        "latency_s",
    }
)
"""What two runs of one script necessarily disagree about, at any depth.

Identity (`session_id`), the clock (`started_at`, `ended_at`, `elapsed_s`,
`unattended_runtime_minutes`, `latency_s`) and the settings themselves. Everything else -
every finding, every coverage item, every recorded step and its arguments - must match, or
the off arm of the A/B is not the control it claims to be.
"""


def played(out: Path, package_dir: Path, efficiency: EfficiencySettings) -> dict[str, Any]:
    """Play the script once and read back `session.json` as plain JSON."""
    run = runner.start_review(
        package_dir,
        out,
        provider=FakeProvider(script=SCRIPT, model="fake-scripted"),
        efficiency=efficiency,
    )
    try:
        run.start()
    finally:
        run.close()
    return json.loads(run.session_path.read_text(encoding="utf-8"))


def normalized(node: Any) -> Any:
    """`node` with every `VOLATILE` key dropped, at every depth."""
    if isinstance(node, dict):
        return {key: normalized(value) for key, value in node.items() if key not in VOLATILE}
    if isinstance(node, list):
        return [normalized(item) for item in node]
    return node


def test_two_runs_of_one_script_differ_only_in_the_settings_they_recorded(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """The flag moves bytes between the prompt and the tools; it changes no output.

    Which is what makes the off arm of the A/B the control it claims to be: the same
    session, the same findings, the same coverage, from the same commit.
    """
    off = played(tmp_path / "off", tmp_package_dir, OFF)
    on = played(tmp_path / "on", tmp_package_dir, ON)

    assert normalized(off) == normalized(on)
    assert off["efficiency"]["trim_tool_descriptions"] is False
    assert on["efficiency"]["trim_tool_descriptions"] is True


def test_the_run_s_system_prompt_carries_the_notes_only_with_the_flag_on(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """End to end: `start_review` renders the block from the tools it just dispatched."""
    provider = FakeProvider(script=SCRIPT, model="fake-scripted")
    on = runner.start_review(
        tmp_package_dir, tmp_path / "on", provider=provider, efficiency=ON
    )
    off = runner.start_review(
        tmp_package_dir,
        tmp_path / "off",
        provider=FakeProvider(script=SCRIPT, model="fake-scripted"),
    )
    try:
        assert runner.TOOL_NOTES_HEADER in on.system
        assert runner.TOOL_NOTES_HEADER not in off.system
        for spec in with_notes():
            assert spec.notes in on.system
    finally:
        on.close()
        off.close()
