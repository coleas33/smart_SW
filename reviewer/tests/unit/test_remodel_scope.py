"""Unit tests for the pure scope gate (T022).

`research.md` R4.1, `data-model.md` sections 4.1 and 4.2 and FR-001 give the whole
specification, and it is five claims:

- **the verdict is made in Python from measurements, with no COM in the signature.**
  `ScopeGate.evaluate(signals)` takes one `ScopeSignals` and nothing else - no copy path,
  no document, no probe id - which is exactly what lets the host refuse a run *before any
  copy is made and before any document handle to the source exists* (FR-001). A reason the
  gate could only reach by opening something would put the refusal after the copy;
- **one refusal per failing signal, and every failing signal is reported.** Multibody, a
  weldment, a sheet-metal folder, a mesh or graphics body and 3D Interconnect each refuse;
  when two signals fail the message names both, because a message that names one of two
  reasons sends the engineer back twice (R4.1);
- **two signals are allowed and reported rather than refused.** An imported dumb solid is
  allowed and the reorganize stage is reported as a no-op; surface bodies are allowed and
  the gate's surface coverage is reported **uncovered**, never passed (FR-038);
- **a null signal is not a pass.** An unreadable refusing signal is `signal_unresolved`
  naming the signal and the verdict is `unresolved`, never `ok` (Principle I). The
  configuration count is recorded and is what drives `which_configs` on every equation add;
  unreadable, it drives nothing rather than defaulting to one configuration;
- **the code set is closed and shared with the bridge.** `Refusal.code` is one of the
  eleven tokens of data-model.md section 4.2. Four of them the bridge raises before any
  signal is returned, so the pure gate never emits them; `rms_named_folder_wrong_members`
  is the one the gate decides and the bridge spells, and it is a **scope** refusal, never a
  ninth entry in the rebuild taxonomy of FR-014.
"""

from __future__ import annotations

import inspect

import pytest

from swreview.remodel.scope import (
    BRIDGE_ONLY_CODES,
    GATE_CODES,
    REFUSAL_CODES,
    REFUSING_SIGNALS,
    RMS_NAMED_FOLDER_WRONG_MEMBERS,
    WHICH_CONFIGS_ALL,
    WHICH_CONFIGS_THIS,
    ScopeGate,
    ScopeSignals,
)
from tests.support.remodel import SCOPE_SIGNAL_FIELDS, scope_signals

REBUILD_REASONS: tuple[str, ...] = (
    "backward_reference",
    "shared_sketch",
    "splits_group",
    "cycle",
    "radius_unreadable",
    "ambiguous_name",
    "unclassified",
    "graph_unreadable",
)
"""FR-014's closed rebuild taxonomy, quoted here so this file can assert that the scope
refusal is not a ninth entry in it. `feasibility.py` owns the taxonomy itself (T017)."""

DATA_MODEL_4_2_CODES: frozenset[str] = frozenset(
    {
        "not_a_part",
        "source_dirty",
        "external_refs",
        "multibody",
        "weldment",
        "sheet_metal",
        "mesh_or_graphics_body",
        "three_d_interconnect",
        "preexisting_rebuild_errors",
        "rms_named_folder_wrong_members",
        "signal_unresolved",
    }
)
"""The closed `Refusal` code set, transcribed from data-model.md section 4.2."""


def gate(**overrides: object) -> ScopeSignals:
    """The in-scope signals with `overrides` applied, as the gate's own type."""
    return ScopeSignals(**scope_signals(**overrides))


def evaluate(**overrides: object):
    return ScopeGate.evaluate(gate(**overrides))


# --- the passing part -------------------------------------------------------------


def test_a_plain_single_body_part_passes_with_nothing_unresolved() -> None:
    result = evaluate()

    assert result.verdict == "ok"
    assert result.refusals == ()
    assert result.surface_coverage == "covered"
    assert result.reorganize_is_no_op is False
    assert result.configuration_count == 1
    assert result.which_configs == WHICH_CONFIGS_THIS


# --- one case per refusing signal -------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code", "signal"),
    [
        ({"solid_body_count": 2}, "multibody", "solid_body_count"),
        ({"is_weldment": True}, "weldment", "is_weldment"),
        ({"sheet_metal_folder_present": True}, "sheet_metal", "sheet_metal_folder_present"),
        ({"mesh_body_present": True}, "mesh_or_graphics_body", "mesh_body_present"),
        ({"graphics_body_present": True}, "mesh_or_graphics_body", "graphics_body_present"),
        ({"is_3d_interconnect": True}, "three_d_interconnect", "is_3d_interconnect"),
        (
            {"rms_named_folders": [{"name": "3-Core", "member_persist_refs": ["ref:1"]}]},
            RMS_NAMED_FOLDER_WRONG_MEMBERS,
            "rms_named_folders",
        ),
    ],
)
def test_each_signal_refuses_with_its_own_code_and_names_its_signal(
    overrides: dict[str, object], code: str, signal: str
) -> None:
    result = evaluate(**overrides)

    assert result.verdict == "refused"
    assert [refusal.code for refusal in result.refusals] == [code]
    assert result.refusals[0].signal == signal
    assert result.refusals[0].message


def test_the_refusing_signals_are_exactly_the_rows_the_data_model_names() -> None:
    """data-model.md section 4.1: a run may not proceed on an unresolved multibody,
    weldment, sheet-metal, mesh, 3D Interconnect **or `rms_named_folders`** signal."""
    assert REFUSING_SIGNALS == (
        "solid_body_count",
        "is_weldment",
        "sheet_metal_folder_present",
        "mesh_body_present",
        "graphics_body_present",
        "is_3d_interconnect",
        "rms_named_folders",
    )


def test_two_failing_signals_are_both_refused_and_the_message_names_both() -> None:
    result = evaluate(solid_body_count=3, is_weldment=True)

    assert result.verdict == "refused"
    assert [refusal.code for refusal in result.refusals] == ["multibody", "weldment"]
    assert "solid_body_count" in result.message
    assert "is_weldment" in result.message


def test_a_refusal_is_a_reported_coverage_gap_and_never_a_silent_skip() -> None:
    result = evaluate(is_weldment=True, is_3d_interconnect=True)

    assert len(result.coverage) >= len(result.refusals)
    for refusal in result.refusals:
        assert any(refusal.code in line and refusal.signal in line for line in result.coverage)


# --- the two signals that are allowed and reported --------------------------------


def test_an_imported_dumb_solid_is_allowed_and_the_reorganize_stage_is_a_no_op() -> None:
    result = evaluate(imported_file_names=["bracket.step"])

    assert result.verdict == "ok"
    assert result.refusals == ()
    assert result.reorganize_is_no_op is True
    assert any("bracket.step" in note for note in result.notes)


def test_surface_bodies_are_allowed_and_the_surface_coverage_is_uncovered() -> None:
    result = evaluate(sheet_body_count=2)

    assert result.verdict == "ok"
    assert result.refusals == ()
    assert result.surface_coverage == "uncovered"
    assert any("surface" in note for note in result.notes)


def test_an_unreadable_sheet_body_count_leaves_the_surface_coverage_unresolved() -> None:
    result = evaluate(sheet_body_count=None)

    assert result.surface_coverage == "unresolved"
    assert result.surface_coverage != "covered"


def test_an_unreadable_imported_file_listing_leaves_the_no_op_question_open() -> None:
    result = evaluate(imported_file_names=None)

    assert result.reorganize_is_no_op is None
    assert any("imported_file_names" in note for note in result.notes)


# --- the configuration count ------------------------------------------------------


@pytest.mark.parametrize(
    ("names", "count", "which"),
    [
        (["Default"], 1, WHICH_CONFIGS_THIS),
        (["Default", "Long"], 2, WHICH_CONFIGS_ALL),
        (["Default", "Long", "Short"], 3, WHICH_CONFIGS_ALL),
    ],
)
def test_the_configuration_count_is_recorded_and_drives_which_configs(
    names: list[str], count: int, which: int
) -> None:
    result = evaluate(configuration_names=names)

    assert result.configuration_count == count
    assert result.which_configs == which


@pytest.mark.parametrize("names", [None, []])
def test_an_unknown_configuration_count_drives_no_equation_add(names: list[str] | None) -> None:
    """Unknown stays unknown: `which_configs` is not defaulted to one configuration."""
    result = evaluate(configuration_names=names)

    assert result.configuration_count is None
    assert result.which_configs is None
    assert any("which_configs" in note for note in result.notes)


def test_the_which_configs_constants_are_the_verified_enum_values() -> None:
    """`swInConfigurationOpts_e {ThisConfiguration = 1, AllConfiguration = 2}` (VERIFIED)."""
    assert (WHICH_CONFIGS_THIS, WHICH_CONFIGS_ALL) == (1, 2)


# --- null signals -----------------------------------------------------------------


@pytest.mark.parametrize("signal", REFUSING_SIGNALS)
def test_a_null_refusing_signal_is_unresolved_and_never_a_silent_pass(signal: str) -> None:
    result = evaluate(**{signal: None})

    assert result.verdict == "unresolved"
    assert result.verdict != "ok"
    assert [refusal.code for refusal in result.refusals] == ["signal_unresolved"]
    assert result.refusals[0].signal == signal
    assert signal in result.refusals[0].message


def test_a_definite_refusal_outranks_an_unresolved_signal_and_both_are_reported() -> None:
    result = evaluate(is_weldment=True, rms_named_folders=None)

    assert result.verdict == "refused"
    assert {refusal.code for refusal in result.refusals} == {"weldment", "signal_unresolved"}


# --- the RMS-named folder ---------------------------------------------------------


def test_an_rms_named_folder_refuses_with_the_one_token_of_the_closed_code_set() -> None:
    result = evaluate(
        rms_named_folders=[
            {"name": "Ribs", "member_persist_refs": ["ref:1"]},
            {"name": "3-Core", "member_persist_refs": ["ref:2", "ref:3"]},
        ]
    )

    assert [refusal.code for refusal in result.refusals] == [RMS_NAMED_FOLDER_WRONG_MEMBERS]
    assert RMS_NAMED_FOLDER_WRONG_MEMBERS in REFUSAL_CODES
    assert "3-Core" in result.refusals[0].message


def test_a_folder_that_is_not_named_for_a_group_is_left_alone() -> None:
    """A derived subfolder is preserved, never dissolved: it is not a scope question."""
    result = evaluate(rms_named_folders=[{"name": "Ribs", "member_persist_refs": ["ref:1"]}])

    assert result.verdict == "ok"
    assert result.refusals == ()


def test_the_folder_refusal_is_a_scope_code_and_not_a_ninth_rebuild_reason() -> None:
    assert RMS_NAMED_FOLDER_WRONG_MEMBERS not in REBUILD_REASONS
    assert len(REBUILD_REASONS) == 8


# --- the closed code set ----------------------------------------------------------


def test_the_refusal_code_set_is_exactly_data_model_section_4_2() -> None:
    assert REFUSAL_CODES == DATA_MODEL_4_2_CODES
    assert len(REFUSAL_CODES) == 11


def test_the_gate_codes_and_the_bridge_only_codes_partition_the_set() -> None:
    assert GATE_CODES | BRIDGE_ONLY_CODES == REFUSAL_CODES
    assert GATE_CODES & BRIDGE_ONLY_CODES == frozenset()
    assert BRIDGE_ONLY_CODES == frozenset(
        {"not_a_part", "source_dirty", "external_refs", "preexisting_rebuild_errors"}
    )


def test_the_gate_never_emits_a_code_the_bridge_raises_before_the_signals_exist() -> None:
    """data-model.md section 4.2: the bridge refuses `not_a_part`, `source_dirty` and
    `external_refs` before any signals are returned, and `preexisting_rebuild_errors` on
    the copy, so the pure gate never reaches those four verdicts from signals alone."""
    result = evaluate(
        document_type=2,
        save_flag_dirty=True,
        read_only=True,
        external_reference_count=3,
        rebuild_error_count=4,
    )

    assert {refusal.code for refusal in result.refusals} & BRIDGE_ONLY_CODES == set()
    assert result.verdict == "ok"


# --- the property over the whole table --------------------------------------------


def test_every_gate_reason_is_decidable_from_scope_signals_alone() -> None:
    """FR-001: the verdict is reached before anything is copied, so every reason the gate
    can give names a row of `ScopeSignals` and the call takes nothing else."""
    parameters = list(inspect.signature(ScopeGate.evaluate).parameters)
    assert parameters == ["signals"]

    fields = set(ScopeSignals.model_fields)
    assert fields == set(SCOPE_SIGNAL_FIELDS)
    assert not [name for name in fields if name.endswith("_path") or name == "document"]

    for rule in ScopeGate.RULES:
        assert rule.signal in fields
        assert rule.code in GATE_CODES


def test_every_gate_code_is_reachable_from_some_reading_of_the_signals() -> None:
    reached = {rule.code for rule in ScopeGate.RULES} | {"signal_unresolved"}
    assert reached == GATE_CODES


def test_the_signals_type_refuses_a_row_the_data_model_does_not_carry() -> None:
    with pytest.raises(ValueError):
        ScopeSignals(**scope_signals(), copy_path="C:/runs/copy/bracket-RMS.SLDPRT")
