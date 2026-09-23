"""Lever 2, first half: the docstring split, the no-loss pin and the caps (T052).

`parse_docstring` already recognised Google-style section headers and already collected a
`Notes:` block into a `sections` dict it then threw away. Lever 2 turns that block into the
second half of the tool description: the **first paragraph** stays on the tool, where the
model reads it to choose among 32, and everything else moves under a `Notes:` header **in
the same docstring**, so the text still lives in exactly one place and a note that goes
stale goes stale once.

What this module pins is the half of the split that must never move. With
`trim_tool_descriptions` **off**, the adapters and the MCP toolset are handed the
**rejoined** string - the description, one blank line, the dedented notes - and FR-039 pins
it **byte-equal** to the pre-split docstring body, so the post-split commit with every flag
off reproduces the pre-split wire bytes and SC-007 holds. `PRE_SPLIT_DESCRIPTIONS` at the
bottom of this file is that pre-split text, all 35 of them, read off this tree before any
docstring was touched. It is a **pin, not a fixture**: when T056 rewrites the 35 docstrings
the rejoin must still come back byte-equal to it, and the only honest way to make that go
green is to split at an existing paragraph boundary with no rewording. Nothing regenerates
it; a diff against it is the entire point. Byte equality rather than "modulo whitespace" is
what makes the flag-off path reproduce the pre-split wire bytes.

The caps are the other half. A run-time cap that truncates mid-sentence produces "...and
never used as o" and the model reads the fragment as complete, so the cap is by
construction: **160 characters** for a description and **90** for an `Args:` entry, the
numbers the 23,834-byte / 30 percent row of `contracts/levers.md` is measured at, so the
enforced cap and the quoted saving are one number. `cap_violations` is what a test calls to
fail the build over them. The caps are **not** asserted over the real docstrings here: T056
rewrites the 35 and T054 is where all 35 are held to the cap. What is asserted here is that
the checker counts the right things, at the right boundary, in characters.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from swreview.agent.providers.schema import (
    MAX_DESCRIPTION_LENGTH,
    MAX_PARAMETER_DESCRIPTION_LENGTH,
    ToolSpec,
    canonical_schema,
    cap_violations,
    parse_docstring,
    tool_spec,
)
from swreview.tools import query
from swreview.tools.registry import BRIDGE_TOOL_FUNCTIONS, TOOL_FUNCTIONS

ALL_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = (*TOOL_FUNCTIONS, *BRIDGE_TOOL_FUNCTIONS)
"""Every function whose docstring reaches a provider: the review array plus the bridge."""


# --- parse_docstring's third value ---------------------------------------------------

WITH_NOTES = """One-line summary the model reads to choose this tool.

Args:
    scope: Which components to list.

Notes:
    A paragraph that moved out of the description.

    And a second one, with an indented line below it:
        stays indented relative to the block.
"""

WITHOUT_NOTES = """One-line summary the model reads to choose this tool.

A second paragraph that has not moved yet.

Args:
    scope: Which components to list.
"""

NOTES_BEFORE_ARGS = """One-line summary the model reads to choose this tool.

Notes:
    A paragraph that moved out of the description.

Args:
    scope: Which components to list.
"""

SINGULAR_NOTE = """One-line summary the model reads to choose this tool.

Note:
    A paragraph that moved out of the description.
"""


def test_parse_docstring_returns_description_arguments_and_notes() -> None:
    """Three values now: the `Notes:` text is returned instead of being thrown away."""
    description, arguments, notes = parse_docstring(WITH_NOTES)
    assert description == "One-line summary the model reads to choose this tool."
    assert arguments == {"scope": "Which components to list."}
    assert notes.startswith("A paragraph that moved out of the description.")


def test_notes_is_dedented_to_column_zero() -> None:
    """The block's own base indent comes off; indentation *below* the base survives."""
    _, _, notes = parse_docstring(WITH_NOTES)
    assert notes == (
        "A paragraph that moved out of the description.\n"
        "\n"
        "And a second one, with an indented line below it:\n"
        "    stays indented relative to the block."
    )


def test_notes_is_empty_when_the_docstring_has_no_notes_section() -> None:
    """Every docstring in the tree looks like this until T056 splits it."""
    description, _, notes = parse_docstring(WITHOUT_NOTES)
    assert notes == ""
    assert description == (
        "One-line summary the model reads to choose this tool.\n"
        "\n"
        "A second paragraph that has not moved yet."
    )


def test_notes_parses_the_same_before_or_after_the_args_block() -> None:
    """Section order is the author's choice and must not change what reaches the model."""
    before = parse_docstring(NOTES_BEFORE_ARGS)
    assert before[1] == {"scope": "Which components to list."}
    assert before[2] == "A paragraph that moved out of the description."


def test_the_singular_note_header_is_collected_too() -> None:
    """`Note:` already ended the description, so not collecting it would lose the text."""
    assert parse_docstring(SINGULAR_NOTE)[2] == "A paragraph that moved out of the description."


def test_parse_docstring_of_nothing_is_three_empty_values() -> None:
    """An undocumented function is `tool_spec`'s `ValueError`, not a crash in the parser."""
    assert parse_docstring(None) == ("", {}, "")


# --- the spec carries both halves ------------------------------------------------------


def with_notes(scope: str) -> None:
    """One-line summary the model reads to choose this tool.

    Args:
        scope: Which components to list.

    Notes:
        A paragraph that moved out of the description.
    """


def undocumented_parameter(scope: str) -> None:
    """One-line summary the model reads to choose this tool.

    Notes:
        A paragraph that moved out of the description.
    """


def parameter_that_does_not_exist(scope: str) -> None:
    """One-line summary the model reads to choose this tool.

    Args:
        scope: Which components to list.
        depth: A parameter this function does not take.

    Notes:
        A paragraph that moved out of the description.
    """


def test_tool_spec_carries_the_notes_beside_the_description() -> None:
    """`ToolSpec.notes` is the second half; `description` is the first paragraph alone."""
    spec = tool_spec(with_notes)
    assert spec.description == "One-line summary the model reads to choose this tool."
    assert spec.notes == "A paragraph that moved out of the description."


def test_the_rejoin_is_the_description_a_blank_line_and_the_notes() -> None:
    """The flag-off string, spelled out: this is the shape FR-039 pins byte-equal."""
    spec = tool_spec(with_notes)
    assert spec.full_description == f"{spec.description}\n\n{spec.notes}"


def test_the_rejoin_is_the_description_alone_when_there_are_no_notes() -> None:
    """No notes means no separator, or every pre-split description gains two bytes."""
    spec = tool_spec(query.list_components)
    assert spec.notes == ""
    assert spec.full_description == spec.description


def test_canonical_schema_still_refuses_a_parameter_with_no_args_entry() -> None:
    """A `Notes:` block is not an `Args:` block: the description is still mandatory."""
    with pytest.raises(ValueError, match="undocumented parameter"):
        canonical_schema(undocumented_parameter)


def test_canonical_schema_still_refuses_an_args_entry_with_no_parameter() -> None:
    """The other half of the same guard, asserted with a `Notes:` block in the way."""
    with pytest.raises(ValueError, match="does not take"):
        canonical_schema(parameter_that_does_not_exist)


# --- the no-loss pin -------------------------------------------------------------------


def test_the_pin_covers_exactly_the_tools_that_reach_a_provider() -> None:
    """A new tool must be added to the pin deliberately, not discovered missing at T056."""
    assert set(PRE_SPLIT_DESCRIPTIONS) == {function.__name__ for function in ALL_TOOL_FUNCTIONS}
    assert len(PRE_SPLIT_DESCRIPTIONS) == 35


@pytest.mark.parametrize(
    "function", ALL_TOOL_FUNCTIONS, ids=[function.__name__ for function in ALL_TOOL_FUNCTIONS]
)
def test_the_rejoined_description_is_byte_equal_to_the_pre_split_docstring(
    function: Callable[..., Any],
) -> None:
    """FR-039: flag off hands over exactly the text the pre-split tree sent. No tolerance."""
    spec = tool_spec(function)
    assert spec.full_description == PRE_SPLIT_DESCRIPTIONS[function.__name__]


def test_the_rejoined_descriptions_weigh_what_they_weighed_before_the_split() -> None:
    """One number over the whole set, so a pin regenerated wholesale is still a red diff."""
    total = sum(
        len(tool_spec(function).full_description.encode("utf-8"))
        for function in ALL_TOOL_FUNCTIONS
    )
    assert total == PRE_SPLIT_DESCRIPTION_BYTES


# --- the caps ---------------------------------------------------------------------------


def spec_with(description: str, parameters: dict[str, str]) -> ToolSpec:
    """A `ToolSpec` built by hand, so the cap can be tested at its exact boundary."""
    return ToolSpec(
        name="a_tool",
        description=description,
        notes="",
        schema={
            "type": "object",
            "properties": {
                name: {"type": "string", "description": text} for name, text in parameters.items()
            },
            "required": sorted(parameters),
        },
        fn=with_notes,
    )


def test_the_caps_are_the_numbers_the_lever_is_measured_at() -> None:
    """160 and 90: the row of `contracts/levers.md` that quotes 23,834 bytes, 30 percent."""
    assert MAX_DESCRIPTION_LENGTH == 160
    assert MAX_PARAMETER_DESCRIPTION_LENGTH == 90


def test_a_description_at_the_cap_is_not_a_violation() -> None:
    """The cap is inclusive; 160 characters is the longest legal description."""
    assert cap_violations(spec_with("d" * 160, {"scope": "p" * 90})) == []


def test_a_description_one_character_over_the_cap_is_a_violation() -> None:
    """And the message names the tool and both numbers, so the fix is obvious from the log."""
    violations = cap_violations(spec_with("d" * 161, {"scope": "p" * 90}))
    assert len(violations) == 1
    assert "a_tool" in violations[0]
    assert "161" in violations[0]
    assert "160" in violations[0]


def test_a_parameter_description_one_character_over_the_cap_is_a_violation() -> None:
    """The `Args:` entry cap, named by parameter and not only by tool."""
    violations = cap_violations(spec_with("d" * 160, {"scope": "p" * 91}))
    assert len(violations) == 1
    assert "a_tool.scope" in violations[0]
    assert "91" in violations[0]
    assert "90" in violations[0]


def test_every_offender_is_listed_not_just_the_first() -> None:
    """A build that fails one docstring at a time is a build nobody finishes fixing."""
    violations = cap_violations(spec_with("d" * 200, {"scope": "p" * 91, "depth": "p" * 120}))
    assert len(violations) == 3


def test_the_cap_counts_characters_and_not_bytes() -> None:
    """160 accented characters is 320 bytes and still a legal description (T053)."""
    assert cap_violations(spec_with("é" * 160, {"scope": "é" * 90})) == []


def test_a_parameter_with_no_description_is_not_a_cap_violation() -> None:
    """`canonical_schema` is what refuses that one, with a better message than a cap."""
    assert cap_violations(spec_with("d" * 160, {})) == []


def test_cap_violations_runs_over_the_real_specs_and_names_them() -> None:
    """The checker on real input, asserted as shape and not as count.

    Today most descriptions are far over the cap and after T056 none should be; this is
    true either way. T054 is the test that holds all 35 to the cap, once T056 has split
    them - putting that assertion here would only mean writing it twice.
    """
    for function in ALL_TOOL_FUNCTIONS:
        spec = tool_spec(function)
        for message in cap_violations(spec):
            assert spec.name in message


def test_a_tool_already_under_the_caps_reports_nothing() -> None:
    """`list_components` is 55 characters over a 72-character parameter: it fits today."""
    assert cap_violations(tool_spec(query.list_components)) == []


# --- the pinned pre-split text -----------------------------------------------------------

PRE_SPLIT_DESCRIPTION_BYTES = 16_041
"""16,006 until feature 010 T022 said what a touching group now is (a contact); edited
deliberately with the one entry below that moved."""
"""UTF-8 bytes of the 35 pre-split descriptions. The split moves text; it never loses any."""

PRE_SPLIT_DESCRIPTIONS: dict[str, str] = {
    "get_package_summary": """\
Census of the evidence package under review. Call this first.

Reports the design, its active configuration, how many documents, components, holes,
fasteners and drawing sheets were extracted, every manifest discrepancy, and how many
gaps the extractor recorded.""",
    "list_components": """\
List the component instances directly under one parent.""",
    "get_component": """\
Everything the package holds about one component instance.

Returns the instance itself plus the holes, fasteners, faces and mates that belong
to it.""",
    "find_components": """\
Component instance ids whose name or instance path matches a glob.

Matching is case-insensitive; `*`, `?` and `[seq]` work as in a shell glob.""",
    "list_mates": """\
Mates, optionally only those that touch one component instance.""",
    "list_holes": """\
Holes, optionally filtered by component instance and hole type.

A hole whose usable thread depth was not reported comes back with
`thread_depth: null` and `thread_depth_note: "unknown"`. Drill depth
(`hole_depth`) is not usable thread depth and must not be used as one.""",
    "list_fasteners": """\
Fasteners with the source their identity came from.

`identity_source` says how much the thread designation and length can be trusted:
`toolbox` is Toolbox data, `name_parse` was read out of a file name.""",
    "list_interferences": """\
Interference results grouped by `group_key`, including truncated and failed ones.

A group whose status is not `computed` is not a clear result: it is unresolved
coverage and has to be reported as such.""",
    "get_drawing_sheet": """\
One drawing sheet: its notes, dimensions, views and parse status.

When `parse_status` is not `text` the sheet carries no readable dimensions and the
result says why. That is unresolved coverage, not a pass.""",
    "find_dimensions": """\
Dimensions read off drawing sheets, with the text exactly as it was read.

`text_as_read` is the raw callout; `nominal` and `tolerance` are what the dimension
grammar made of it. A tolerance whose kind is `none` was not stated on the drawing.""",
    "list_gaps": """\
Everything the extractor could not provide, and why.

A gap is the reason a check stays unresolved. Read this early: it bounds what can be
concluded from this package at all.""",
    "get_exceptions": """\
Retained exceptions (previously accepted conditions) that apply to this package.

Empty when no exception store is wired to this run, which is the case for a package
reviewed without the exception store.""",
    "list_features": """\
The feature tree of one document, in traversal order, with its derived columns.

`class` and `group` are the method's own answers, not the extractor's: `class` is
`unknown` for a type name the RMS type table does not carry and `ambiguous` for one
that spans classes, and `group` is `null` for a feature before the first group folder.
Folders and end-tag markers are listed like any other row. `folder_id` is the nearest
enclosing *feature* as the extractor reported it, which is `null` in the traversal
shape that reports no sub-features; `folder` filters on the enclosing folder, which is
the same answer in both shapes.

A document whose tree was not extracted - an assembly, a suppressed component's part -
has no rows here; `list_gaps` says why.""",
    "get_feature": """\
Everything the package holds about one feature, plus what the method makes of it.

The whole `Feature` as it was extracted, then `class`, `group`, `is_folder` and
`is_end_tag` derived from the RMS type table and the group assignment, and then
`child_names`, `parent_names` and `consumer_names` - the dependency, dependent and
sketch-consumer id lists resolved to feature names, position by position.

A null id list stays null: it means `GetChildren` or `GetParents` failed for this
feature, which is not the same as having none. A name is null where the id names a
feature this package does not carry. `consumer_names` is null for a feature that has
no sketch at all; `sketch` itself says which of the two it is.""",
    "list_equations": """\
One document's equation manager, row by row, in the order the manager holds them.

Every field of `Equation` and nothing derived: `text` as it was read, `lhs` (the text
left of the first `=`, unquoted) as evidence only, `is_global` as
`IEquationMgr.GlobalVariable(i)` answered, and `value`. A row whose global flag could
not be read carries `is_global: null`, which is not `false`: it is why
`check_rms_equations` leaves the document unresolved rather than reporting that it has
no global variables, and `list_gaps` gives the reason.

A document whose equation manager was not read - `--equations off`, an assembly, a
part nobody opened - has no rows here, which is also not "it has no equations".""",
    "measure_axis_distance": """\
Closest distance and angle between the axes of two holes, in the world frame.

For parallel axes the distance is the perpendicular distance between them; for skew
axes it is the common-perpendicular distance. `relation` says which case this is:
`coincident`, `parallel`, `intersecting` or `skew`.

This is a measurement, not a verdict: comparing it with a tolerance is
`check_hole_alignment`.""",
    "measure_face_gap": """\
Signed gap between two parallel planes or two coaxial cylinders.

For planes the gap is measured along face A's normal, so it is positive when B lies
on the side A faces. For cylinders it is the radius difference B - A, negative when B
is the smaller of the two - the shaft-in-bore convention.

Any other pair - non-parallel planes, offset cylinders, a cone or a torus, a face
whose surface the extractor did not record - comes back `unsupported` with the reason.
That is unresolved coverage, not a measurement of zero.""",
    "check_tool_envelope": """\
Sweep a driving tool back from a fastener head and report what it runs into.

The envelope is a cylinder whose radius comes from `checks/tool_envelopes.yaml` - a
multiple of the fastener's nominal thread diameter, plus a clearance - swept from the
head plane along the fastener axis, away from the tip, for `length`. The result lists
every component the sweep hits and how far away the first hit is.

The bodies swept are the ones whose exported mesh could be loaded, excluding the
fastener's own. Any body whose mesh is missing makes the result `unresolved` and is
named: a sweep that could not test a body has not shown it is out of the way.""",
    "bounding_box": """\
World axis-aligned bounding box of one component, from its extracted faces.

The box is the union of the world bounding boxes the extractor recorded per face, so
it covers the faces that were extracted and nothing else: with `--faces needed` that
is a subset of the part, and the result says how many faces went into it. A component
with no extracted face geometry is `unresolved`, never a zero-sized box.""",
    "check_fit": """\
Clearance or interference between a bore and a shaft, from the drawn sizes alone.

Both dimensions are read off the drawing sheets in the package; there is no way to
supply a size directly. Returns the `fit.size_only` finding, which reports the
minimum and maximum diametral clearance, the fit class, and the effects size alone
does not cover (position, form, coating, temperature, deflection).

A tolerance the drawing does not state makes the finding `unresolved` naming the
side; an unknown or ambiguous reference is an error result.""",
    "check_axial_stack": """\
Worst-case sum of drawn dimensions along one axis, against a target gap.

Every dimension is read off the drawing sheets in the package. `signs` says how each
one enters the stack: `+1` adds it, `-1` subtracts it, so a gap is the enclosing
dimension `+1` and everything inside it `-1`. Returns the `stack.worst_case` finding
with the nominal sum, the band around it, and - with a target gap - whether the
stack can fall outside it.

A contributor whose tolerance the drawing does not state makes the finding
`unresolved` naming it; an unknown or ambiguous reference, or a sign that is not +1
or -1, is an error result.""",
    "check_fastener_joint": """\
Check one screw-in-tapped-hole joint: bottoming, engagement, thread, head clearance.

Returns one finding per check. The clamped stack is the components you name, in order
from the head; each layer's thickness comes from its `Thickness` custom property, or
from its extracted bounding box measured along the fastener axis, or is unknown - and
the result says which for every layer. Washers coaxial with the fastener are found in
the package and added to the stack; you do not name them.

A screw whose usable thread depth the package does not carry leaves bottoming and
engagement `unresolved`: drill depth is not thread depth and is never used as one.
Head clearance stays `unresolved` until `check_tool_envelope` has swept the meshes.

A joint kind this phase does not model (a pin, a rivet, a nut) produces no finding at
all: it is recorded as `out_of_scope` coverage.""",
    "check_hole_alignment": """\
Compare the offset between two hole axes with a coaxiality tolerance off a drawing.

The offset is the closest distance between the axes as modelled, with the angle
between them reported alongside. `tolerance` names the drawing dimension that governs
the pair; its nominal is read as the permitted offset. Without one the offset is still
measured and the finding is `unresolved` - the number is evidence, the verdict is not
available.

This compares modelled axes, not GD&T: no datum reference frame, no material
condition, no form error, and no allowance for component position or mate play.""",
    "check_interference_group": """\
The verdict on one grouped interference condition, honoring retained exceptions.

`group_key` is the key `list_interferences` prints. Every pair in the group is one
condition: the finding names them all rather than repeating itself once per pair.

A group with an overlap volume is `demonstrated` - the overlap is a fact SOLIDWORKS
computed. A group whose pairs only touch (zero volume, or none and the possible
flag) is a `contact` on the session, not a finding. A group with a truncated or
failed pair is `unresolved` and each such pair is also written into the session's
unresolved coverage: nothing is known about them, and an exception cannot speak for
a pair that was never evaluated.

An exception accepted for exactly these components in this configuration clears the
group and is cited on the finding; one whose geometry or configuration has since
changed leaves the finding standing and says so.""",
    "check_rms_part": """\
Grade one part's feature tree, or every part's, against the part-scope RMS rules.

Each failing rule becomes one finding naming the features it is about, each passing,
skipped or unresolved rule becomes one aggregated coverage item per bucket, and the
`modeling.resilience` summary is rewritten from everything the session holds. Each
call re-evaluates its scope in full and replaces its own earlier *coverage* items, so
running it twice leaves one coverage item per rule; findings are appended, as they are
by every check tool, so a second call over a document you already graded adds a second
finding for each of its conditions. Grade every part in one call - no argument - and
re-grade a single document only when you mean to add findings for it.

A `fail` outcome consults the retained exceptions for exactly these component
instances, this configuration and this rule id: an `active` exception waives the
finding and is cited on it, one whose feature tree has changed leaves the finding
standing and says so. A `warn` outcome is advisory and never consults them.

A part whose tree was never read - every instance lightweight, suppressed or unloaded
- is unresolved for every part- and equation-scope rule, with the component state as
the reason. It is never silently left out of the report.""",
    "check_rms_assembly": """\
Grade the root assembly's mates and components against the assembly-scope RMS rules.

Four rules: the mates reference planes, axes, points or coordinate systems rather than
faces, edges or vertices (`fail`); the first component is fixed or fully constrained
(`fail`); no component is more than three mates from the fixed root (`warn`); and
Toolbox hardware is inserted as parts rather than as configurations of one file
(`warn`). Each failing rule becomes one finding naming the mates and components it is
about, everything else becomes one aggregated coverage item per rule per bucket, and
the `modeling.resilience` summary is rewritten from everything the session holds.

There is no argument because there is no choice: only the root assembly document's
mates are extracted, so that is the one document these rules can grade. The
subassemblies are reported as unresolved by name rather than passed over.

A package with no assembly document - a part-only dump, where the root document id
names the part - grades nothing: `documents` comes back empty and all four rules are
unresolved, naming that document and its kind. Nothing is claimed about an assembly
this package does not carry.

A `fail` outcome consults the retained exceptions for the root assembly instance, this
configuration and this rule id; a `warn` outcome is advisory and never does. Calling
this twice replaces its coverage and appends a second copy of every finding, so call
it once.""",
    "check_rms_equations": """\
Grade one part's equation manager, or every part's, against the equation rules.

The same two rules for every part document: at least one global variable exists
(`fail`), and at least one dimension is driven by an equation (`warn`). A manager that
was read and holds nothing is an answer and becomes those two outcomes; a manager
nobody could read - the `equations` gap, or a row whose global flag threw - is
unresolved instead, because "this part has no global variables" is a claim about data
someone actually saw (constitution Principle I).

Dispatch, exceptions, coverage and the effect of calling it twice are `check_rms_part`'s
exactly: null grades every part document including the ones whose tree was never read,
a `fail` outcome consults the retained exceptions for this rule id, coverage is
replaced and findings are appended.""",
    "request_evidence": """\
Record something you need and the package does not have. Returns its id.

Use this instead of assuming a missing value. The request stays open in the report
until an engineer answers it, and the check it blocks stays unresolved.""",
    "mark_coverage": """\
Record what a check covered, or why it could not be run.

Nothing is silently skipped: every checklist item ends the review with a finding or a
coverage entry. `failed` is not available here; the tool layer writes that bucket when
a tool fails.""",
    "record_drawing_finding": """\
Record a drawing problem that no calculation stands behind.

For missing manufacturing inputs, ambiguous callouts and unreadable sheets. Because
nothing numeric backs it, the strongest status available is `suspected`;
`demonstrated` and `checked_within_scope` are not.""",
    "get_review_checklist": """\
The mandatory review checklist with the bucket each item currently sits in.

`bucket` is `finding` when a finding already covers the item, one of `checked`,
`skipped`, `unresolved`, `out_of_scope` when a coverage entry does, and `open` when
nothing does yet. The review is not finished while anything is `open`.""",
    "request_capture": """\
A rendered view of one entity, when the package already holds one.

Returns an existing capture from the package. Without the live SOLIDWORKS bridge
there is no way to make a new one, and the result is `unresolved` rather than a
description of what the view would show.""",
    "bridge_capture": """\
Render one entity in the open SOLIDWORKS document and save a PNG.

The host frames the entity the persistent reference resolves to, applies the view, and
saves an image; it chooses where, so no path is ever sent. The capture is added to the
package so the report can show it, and the result carries its package-relative path.""",
    "bridge_measure": """\
SOLIDWORKS' own Measure between two entities, with the units it reports.

This is the live counterpart of `measure_axis_distance` and `measure_face_gap`: it
measures what the open document holds rather than what the package recorded, which is
the point of running with the bridge at all. The result is the host's, unaltered -
note that it answers in **metres**, not the millimetres the offline tools report.""",
    "bridge_interference": """\
Run interference detection live and add the results to the package.

The results come back in the IR's own shape and are appended to the package under
review, so `list_interferences` and `check_interference_group` work on them exactly as
they work on results the extractor dumped. A result whose id the package already holds
is not added twice. Every `Gap` the host reports - the volume-unit caveat among them -
is appended to the package's gaps, because it bounds what the results mean.

Each row carries its own status: a `truncated` or `failed` row is unresolved coverage,
never a pass.""",
}
"""The docstring body of every tool as this tree sent it before the split (T052).

Read off the tree, transcribed once, and never regenerated: after T056 the rejoin of each
split docstring must come back byte-equal to its entry here. A whitespace tolerance is
exactly the crack the deleted two-commit exception would crawl back through.
"""
