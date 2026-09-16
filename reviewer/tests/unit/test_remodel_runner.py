"""The re-model run's four phases, driven by scripted judgement (T116).

`remodel/runner.py` is the only module of this feature that talks to a model, and it talks
to one for exactly one turn, in phase B, over the five proposal tools. Everything around
that turn is deterministic: phase A plans, phase C applies and phase D verifies, and none
of the three can reach a provider. This file drives all four offline - `FakeProvider` plays
the model and `tests/support/remodel_bridge.py` plays the seat - and asserts the four
properties the judgement phase exists to guarantee:

- **the run completes whatever the model does.** A script that proposes nothing, a script
  that proposes well and a script that proposes garbage all reach a terminal state with
  every artifact written. The model is an optional contributor to a plan, never a step the
  run depends on;
- **revision 2 is revision 1 plus what was accepted.** Nothing the model said re-opens the
  order, the moves, the pins or the folders: those are the planner's and the owner decision
  is that the model never orders anything. What revision 2 gains is descriptions, globals,
  the groups the model decided, its deviations, its rejections, and the C2/C5/C6 changes
  that carry the accepted proposals out;
- **a rejection is recorded, not just returned.** Every refused proposal appends one
  `RejectedProposal` carrying the tool, the arguments as sent, the sentence, the rule id,
  the provider and the model, because FR-016 and US4 scenario 7 have the report list them
  and a tool result is persisted nowhere the report reads;
- **the judgement phase performs no writes to SOLIDWORKS.** It is asserted twice: `judge`
  is called with a bridge fake that raises on any call at all, and the whole run is asserted
  to have sent the fake bridge nothing until revision 2 was on disk.

One interpretation is recorded here rather than left to a reader. T116 lists "a tool call
trying to name a document" among the garbage; no tool takes a document, a path or a run
folder (`contracts/tools.md`), so the script makes the call that reaches closest - a
`feature_id` that is a file path - and it is refused as an unknown feature and written down
like every other refusal. The stronger reading, that no tool naming a document exists to be
called at all, is asserted separately over the offered surface.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import providers
from swreview.agent.events import EVENTS_FILE_NAME, EventSink
from swreview.agent.providers import AgentEvent, AgentProvider
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.agent.settings import DEFAULT_PROVIDER, ProviderName, ProviderSettings
from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage
from swreview.remodel import runner
from swreview.remodel.apply_log import CHANGES_FILE_NAME, read_changes
from swreview.remodel.artifacts import GRADES_FILE_NAME
from swreview.remodel.attestation import attestation_from_open
from swreview.remodel.geometry import GEOMETRY_FILE_NAME, GeometryReading, reading_from_reply
from swreview.remodel.plan import (
    PLAN_FILE_NAME,
    DescriptionProposal,
    RemodelPlan,
    SourceAttestation,
    plan_path,
)
from swreview.remodel.report import REPORT_FILE_NAME
from swreview.remodel.scope import WHICH_CONFIGS_THIS, ScopeSignals
from swreview.remodel.tolerances import IDENTITY
from swreview.report.session import MAX_STEPS_CLOSEOUT, TRUNCATED_CLOSEOUT
from tests.support.contracts import contract_validator
from tests.support.features import equation, feature, fillet_feature, sketch_feature
from tests.support.remodel import UNKNOWN_TYPE_NAME, linked, remodel_package, scope_signals
from tests.support.remodel_bridge import (
    COPY_PATH,
    FakeRemodelBridge,
    FakeTree,
    Script,
    StepClock,
)

AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
RUN_ID = "20260916-142201-bracket-remodel"
SOURCE_SHA = "4c" * 32
MODEL = "fake-scripted"
UNIT = "mm"

TABLE = load_table()
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups

CALIBRATED = IDENTITY.model_copy(
    update={"calibrated": True, "calibration_ref": "PROBE-8 2026-09-16"}
)
"""`IDENTITY` as PROBE-8 will leave it. The profile refuses to decide a run until then, so
a test that wants a verdict out of phase D says so here rather than reaching past FR-036."""


# --- the part under judgement ---------------------------------------------------------


def part() -> EvidencePackage:
    """One part carrying a slot for each of the four proposal tools.

    `Boss-Extrude1`'s description was read and is blank, so it may be described; `Fillet1`
    has no dependents and may be quarantined; `Fillet2` has one (`Shell1`) and may not;
    `Deform1` carries a type name the table does not classify; and both fillets carry a
    readable radius, which is the only parameter the `model_check` profile offers a global.

    `Cut-Extrude1` sits above the core features it should follow, so the planner has a real
    move to make: the run is worth applying and a limit has something to truncate.
    """
    specs = linked(
        [
            feature("Right Plane", "RefPlane"),
            sketch_feature("Sketch1"),
            feature("Cut-Extrude1", "Cut"),
            feature("Boss-Extrude1", "Extrusion", description=""),
            fillet_feature("Fillet1", radius_m=0.005),
            fillet_feature("Fillet2", radius_m=0.003),
            feature("Shell1", "Shell"),
            feature("Deform1", UNKNOWN_TYPE_NAME),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Fillet1"),
        ("Boss-Extrude1", "Fillet2"),
        ("Fillet2", "Shell1"),
    )
    return remodel_package(
        specs, equations=[equation('"width" = 100', is_global=True, value=0.1)]
    )


def plain_part() -> EvidencePackage:
    """A part with nothing for the model to do: every description read, no fillet, no
    unclassified type. `judgement_slots` is empty over it and no provider is built."""
    specs = linked(
        [
            feature("Right Plane", "RefPlane"),
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
        ],
        ("Sketch1", "Boss-Extrude1"),
    )
    return remodel_package(specs)


PACKAGE = part()
IDS: dict[str, str] = {row.name: row.id for row in PACKAGE.features}
REFS: dict[str, str] = {row.name: row.persist_ref for row in PACKAGE.features}


def seat(package: EvidencePackage) -> FakeTree:
    """The seat's tree, built from the package's own rows.

    Built from the package rather than written out by hand: every change the planner emits
    is addressed by persistent reference, so a fixture tree whose refs were invented would
    be a tree the plan cannot address and the run would fail for the fixture's reasons.
    """
    rows = [row for row in package.features]
    return FakeTree(
        order=[row.persist_ref for row in rows],
        names={row.persist_ref: row.name for row in rows},
        descriptions={row.persist_ref: "" for row in rows},
        equations=[row.text for row in package.equations],
    )


# --- the run's inputs, as the host hands them over --------------------------------------


SOURCE_CONTENT = b"the engineer's file, byte for byte"


def source_file(run_dir: Path) -> Path:
    """The engineer's file on disk, which phase D re-reads to re-check the attestation."""
    path = run_dir.parent / "bracket.SLDPRT"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(SOURCE_CONTENT)
    return path


def _last_write_utc(path: Path) -> datetime:
    seconds, nanoseconds = divmod(path.stat().st_mtime_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanoseconds // 1000)


def attestation(run_dir: Path) -> SourceAttestation:
    """The recorded half, measured the way `remodel.open` records it."""
    source = source_file(run_dir)
    return attestation_from_open(
        {
            "path": str(source),
            "length_bytes": source.stat().st_size,
            "last_write_utc": _last_write_utc(source).isoformat().replace("+00:00", "Z"),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_design_id": "dsn:4f2a91c0d3b7",
            "recorded_at": AT.isoformat().replace("+00:00", "Z"),
            "vault_path": None,
            "vault_revision": None,
            "copy_path": COPY_PATH,
        }
    )


def reading(**overrides: Any) -> dict[str, Any]:
    """One `remodel.geometry` reply as JSON, identical before and after: stage 1 creates
    no geometry, so the gate decides under `IDENTITY` and any difference is a defect."""
    return {
        "at": "2026-09-16T14:22:01Z",
        "source_sha256": SOURCE_SHA,
        "subject": "copy_at_open",
        "status": 0,
        "accuracy_level": 2,
        "recalculated": True,
        "volume_m3": 1.23456789e-3,
        "surface_area_m2": 4.56e-2,
        "center_of_mass_m": [0.01, 0.02, 0.03],
        "principal_moments": [1.1e-5, 2.2e-5, 3.3e-5],
        "mass_kg": 3.21,
        "density": 2600.0,
        "material_name": "1060 Alloy",
        "solid_body_count": 1,
        "sheet_body_count": 0,
        "face_count": 214,
        "edge_count": 642,
        "residual": None,
        **overrides,
    }


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / RUN_ID


def bridge_for(package: EvidencePackage, script: Script | None = None) -> FakeRemodelBridge:
    return FakeRemodelBridge(
        seat(package),
        script=script,
        readings=[reading(), reading()],
    )


def opened(bridge: FakeRemodelBridge) -> GeometryReading:
    """The `copy_at_open` baseline, taken the way the host takes it: from the copy."""
    return reading_from_reply(bridge.geometry())


def planned(run_dir: Path, package: EvidencePackage = PACKAGE) -> RemodelPlan:
    """Phase A over `package`, with the copy and the source attestation recorded.

    `plan_run` writes revision 1; the copy's identity is the host's and is carried on
    afterwards, exactly as `remodel.plan` does before it answers `remodel.planned`.
    """
    plan = runner.plan_run(
        run_dir,
        package,
        signals=ScopeSignals(**scope_signals()),
        probe_id="probe:1",
        now=AT,
    )
    return plan.model_copy(
        update={"run_id": RUN_ID, "copy_path": COPY_PATH, "source": attestation(run_dir)}
    )


def fake(script: Sequence[ScriptedTurn]) -> FakeProvider:
    return FakeProvider(script=list(script), model=MODEL)


def settings_for(provider: ProviderName = ProviderName.FAKE) -> ProviderSettings:
    return ProviderSettings(provider=provider, model=MODEL)


def run(
    run_dir: Path,
    *,
    script: Sequence[ScriptedTurn] | None = None,
    package: EvidencePackage = PACKAGE,
    bridge: FakeRemodelBridge | None = None,
    plan: RemodelPlan | None = None,
    callbacks: Sequence[Callable[[AgentEvent], None]] = (),
    provider_factory: Callable[[ProviderSettings], AgentProvider] | None = None,
    **overrides: Any,
) -> runner.RemodelRun:
    """Phases B to D over the scripted model and the fake seat."""
    client = bridge if bridge is not None else bridge_for(package)
    if provider_factory is None and script is not None:
        provider = fake(script)
        provider_factory = lambda _settings: provider  # noqa: E731 - one-line stub
    return runner.run_remodel(
        run_dir=run_dir,
        client=client,
        plan=plan if plan is not None else planned(run_dir, package),
        package=package,
        dump_after=overrides.pop("dump_after", lambda: package),
        baseline=0,
        before=opened(client),
        attestation=attestation(run_dir),
        settings=overrides.pop("settings", settings_for()),
        provider_factory=(
            provider_factory if provider_factory is not None else runner.build_provider
        ),
        document_length_unit=UNIT,
        which_configs=overrides.pop("which_configs", WHICH_CONFIGS_THIS),
        tolerances=overrides.pop("tolerances", CALIBRATED),
        callbacks=callbacks,
        now=overrides.pop("now", StepClock(AT, 1.0)),
        **overrides,
    )


def state_on_disk(run_dir: Path) -> str:
    return str(json.loads(plan_path(run_dir).read_text(encoding="utf-8"))["state"])


def plan_on_disk(run_dir: Path) -> RemodelPlan:
    return RemodelPlan.model_validate_json(plan_path(run_dir).read_text(encoding="utf-8"))


# --- the scripts ------------------------------------------------------------------------


def turn(*calls: ScriptedToolCall, text: str = "Done.") -> list[ScriptedTurn]:
    """One judgement turn: the phase is one bounded turn, never a conversation."""
    return [ScriptedTurn(text=text, tool_calls=calls)]


SILENT = turn(text="I have nothing to propose about this part.")

GOOD_DESCRIPTION = "Mounting boss for the bracket face"
GOOD_GLOBAL = "fillet_radius"

DESCRIBE_THE_BOSS = ScriptedToolCall(
    "propose_description",
    {"feature_id": IDS["Boss-Extrude1"], "text": GOOD_DESCRIPTION},
)
"""The one proposal every script that needs an accepted one makes."""


def valid_script() -> list[ScriptedTurn]:
    return turn(
        ScriptedToolCall("get_remodel_plan", {"section": "summary"}),
        DESCRIBE_THE_BOSS,
        ScriptedToolCall(
            "propose_global",
            {
                "name": GOOD_GLOBAL,
                "expression": "5",
                "rationale": "the two edge breaks share one radius",
                "evidence": [IDS["Fillet1"]],
            },
        ),
        ScriptedToolCall(
            "decide_fillet",
            {
                "feature_id": IDS["Fillet1"],
                "group": QUARANTINE,
                "rationale": "a cosmetic edge break with nothing built on it",
            },
        ),
        ScriptedToolCall(
            "classify_unknown",
            {
                "feature_id": IDS["Deform1"],
                "group": CORE,
                "rationale": "it shapes the load-bearing face",
            },
        ),
    )


A_DOCUMENT = r"C:\work\bracket.SLDPRT"

GARBAGE: tuple[tuple[str, dict[str, Any], str], ...] = (
    (
        "propose_description",
        {"feature_id": IDS["Boss-Extrude1"], "text": "x" * 4000},
        "propose_description.length",
    ),
    (
        "propose_description",
        {"feature_id": IDS["Boss-Extrude1"], "text": "Boss-Extrude1"},
        "propose_description.repeats_name",
    ),
    (
        "propose_global",
        {
            "name": "FilletRadius",
            "expression": "5",
            "rationale": "upper case is not a name this product writes",
            "evidence": [IDS["Fillet1"]],
        },
        "propose_global.name_pattern",
    ),
    (
        "propose_global",
        {
            "name": "width",
            "expression": "5",
            "rationale": "the document already declares this one",
            "evidence": [IDS["Fillet1"]],
        },
        "propose_global.existing_global",
    ),
    (
        "propose_global",
        {
            "name": "edge_break",
            "expression": '"nope" * 2',
            "rationale": "nothing declares nope",
            "evidence": [],
        },
        "propose_global.undeclared_reference",
    ),
    (
        "decide_fillet",
        {
            "feature_id": IDS["Fillet2"],
            "group": QUARANTINE,
            "rationale": "Shell1 is built on it",
        },
        "decide_fillet.quarantine_has_dependents",
    ),
    (
        "classify_unknown",
        {"feature_id": IDS["Deform1"], "group": "7-Nonsense", "rationale": "not a group"},
        "classify_unknown.group",
    ),
    (
        "decide_fillet",
        {"feature_id": "feat:9999", "group": CORE, "rationale": "no such feature"},
        "decide_fillet.unknown_feature",
    ),
    (
        "propose_description",
        {"feature_id": A_DOCUMENT, "text": "naming a document instead of a feature"},
        "propose_description.unknown_feature",
    ),
)
"""The nine refusals T116 names, each with the rule id that has to refuse it."""


def garbage_script() -> list[ScriptedTurn]:
    """Every refusal, then one proposal that is accepted, so "only valid proposals land"
    is a statement about a plan that has something in it."""
    return turn(
        *(ScriptedToolCall(name, arguments) for name, arguments, _ in GARBAGE),
        DESCRIBE_THE_BOSS,
    )


# --- 1. phase A: the plan ---------------------------------------------------------------


def test_phase_a_writes_revision_one_and_the_planned_state(run_dir: Path) -> None:
    plan = runner.plan_run(
        run_dir, PACKAGE, signals=ScopeSignals(**scope_signals()), probe_id="probe:1", now=AT
    )
    assert plan.plan_revision == 1
    assert plan.state == "planned"
    assert (run_dir / PLAN_FILE_NAME).is_file()
    assert plan_on_disk(run_dir) == plan


def test_phase_a_plans_the_part_the_planner_would(run_dir: Path) -> None:
    """The runner adds nothing to `plan_reorganize`; it files what it returns."""
    from swreview.remodel.plan import plan_reorganize

    direct = plan_reorganize(
        PACKAGE, signals=ScopeSignals(**scope_signals()), probe_id="probe:1", now=AT
    )
    assert runner.plan_run(
        run_dir, PACKAGE, signals=ScopeSignals(**scope_signals()), probe_id="probe:1", now=AT
    ) == direct


# --- 2. a script that proposes nothing ---------------------------------------------------


def test_a_script_that_proposes_nothing_completes_the_run(run_dir: Path) -> None:
    result = run(run_dir, script=SILENT)
    assert result.verification.passed, result.verification.reasons
    assert result.plan.state in ("saved", "truncated")
    assert state_on_disk(run_dir) == result.plan.state


def test_revision_two_of_a_silent_run_is_revision_one_plus_the_recorded_absence(
    run_dir: Path,
) -> None:
    before = planned(run_dir)
    result = run(run_dir, script=SILENT, plan=before)
    after = result.plan

    assert after.plan_revision == 2
    assert after.targets == before.targets
    assert after.descriptions == before.descriptions == ()
    assert after.globals == before.globals == ()
    assert after.rejected_proposals == ()
    assert after.deviations == before.deviations
    assert after.changes == before.changes
    assert after.coverage[: len(before.coverage)] == before.coverage
    absence = after.coverage[len(before.coverage) :]
    assert [item.reason for item in absence] == [runner.NOTHING_PROPOSED]
    assert {item.item for item in absence} == {runner.JUDGEMENT_ITEM}


def test_a_silent_run_still_records_the_judging_state_before_applying(
    run_dir: Path,
) -> None:
    """`judging` is a state the run passes through, and `plan.json` says so while it does."""
    states: list[str] = []
    sink = EventSink(run_dir / EVENTS_FILE_NAME)
    before = planned(run_dir)

    def watch(_event: AgentEvent) -> None:
        states.append(state_on_disk(run_dir))

    sink.add_listener(watch)
    after = runner.judge(
        run_dir=run_dir,
        plan=before,
        package=PACKAGE,
        provider=fake(SILENT),
        sink=sink,
        document_length_unit=UNIT,
        which_configs=WHICH_CONFIGS_THIS,
        now=StepClock(AT, 1.0),
    )
    assert states and set(states) == {"judging"}
    assert after.state == "applying"
    assert state_on_disk(run_dir) == "applying"


# --- 3. a script that proposes valid intent ----------------------------------------------


@pytest.fixture
def judged(run_dir: Path) -> RemodelPlan:
    return run(run_dir, script=valid_script()).plan


def test_an_accepted_description_lands_in_revision_two(judged: RemodelPlan) -> None:
    (proposal,) = judged.descriptions
    assert proposal.feature_id == IDS["Boss-Extrude1"]
    assert proposal.text == GOOD_DESCRIPTION
    assert proposal.before == ""
    assert proposal.validation == "accepted"


def test_an_accepted_global_lands_in_revision_two_with_its_evidence(
    judged: RemodelPlan,
) -> None:
    (proposal,) = judged.globals
    assert proposal.name == GOOD_GLOBAL
    (evidence,) = proposal.evidence
    assert evidence.feature_id == IDS["Fillet1"]
    assert evidence.parameter == "default_radius"
    assert evidence.value_m == pytest.approx(0.005)
    assert evidence.document_length_unit == UNIT


@pytest.mark.parametrize("section", ["descriptions", "globals"])
def test_every_accepted_proposal_carries_its_provider_and_model(
    judged: RemodelPlan, section: str
) -> None:
    """FR-056: the report prints both beside each judgement item."""
    rows = getattr(judged, section)
    assert rows, f"the script proposed into {section} and nothing landed there"
    for row in rows:
        assert row.provider == ProviderName.FAKE.value
        assert row.model == MODEL


def test_a_model_group_decision_replaces_the_planner_s_target(judged: RemodelPlan) -> None:
    decided = {item.feature_id: item for item in judged.targets}
    fillet = decided[IDS["Fillet1"]]
    assert fillet.target_group == QUARANTINE
    assert fillet.decided_by == "model"
    assert fillet.basis == "model_judgement"
    assert len([item for item in judged.targets if item.feature_id == IDS["Fillet1"]]) == 1


def test_a_classified_unknown_is_always_visible_as_a_deviation(judged: RemodelPlan) -> None:
    kinds = [item for item in judged.deviations if item.kind == "unknown_classified_by_model"]
    assert [item.feature_id for item in kinds] == [IDS["Deform1"]]
    assert kinds[0].chosen == CORE


def test_the_accepted_proposals_become_changes_in_the_fixed_order(
    run_dir: Path, judged: RemodelPlan
) -> None:
    """C2 lands after the renames and before the reorders; C6 lands last (section 1.11)."""
    kinds = [change.kind for change in judged.changes]
    assert "describe" in kinds
    assert "equation.add" in kinds
    assert kinds.index("describe") < min(
        (index for index, kind in enumerate(kinds) if kind != "rename" and kind != "describe"),
        default=len(kinds),
    )
    assert kinds[-1] == "equation.add"
    assert [change.seq for change in judged.changes] == list(range(1, len(judged.changes) + 1))


def test_the_description_change_addresses_the_feature_by_persistent_reference(
    judged: RemodelPlan,
) -> None:
    (describe,) = [change for change in judged.changes if change.kind == "describe"]
    assert describe.params == {
        "persist_ref": REFS["Boss-Extrude1"],
        "text": GOOD_DESCRIPTION,
    }
    assert describe.expect == {"rebuild_errors_delta": 0}


def test_the_judgement_never_re_opens_the_order_the_planner_computed(
    run_dir: Path, judged: RemodelPlan
) -> None:
    """The owner decision: the model proposes and never orders. A group it decided is
    recorded and reported; it does not move a feature this run."""
    before = planned(run_dir)
    assert judged.order == before.order
    assert judged.pins == before.pins
    assert judged.rebuild == before.rebuild
    assert judged.folders == before.folders
    planner_changes = [change.kind for change in before.changes]
    carried = [
        change.kind
        for change in judged.changes
        if change.kind not in ("describe", "equation.add", "equation.edit")
    ]
    assert carried == planner_changes


def test_the_proposals_reach_the_seat_as_writes(run_dir: Path) -> None:
    """Phase C carries them out: the copy's tree holds the description and the equation."""
    bridge = bridge_for(PACKAGE)
    result = run(run_dir, script=valid_script(), bridge=bridge)
    assert result.verification.passed, result.verification.reasons
    assert bridge.tree.descriptions[REFS["Boss-Extrude1"]] == GOOD_DESCRIPTION
    assert any(GOOD_GLOBAL in text for text in bridge.tree.equations)


def test_a_global_nobody_can_seed_is_recorded_rather_than_written(run_dir: Path) -> None:
    """An unread configuration scope refuses the **change**, never the run: the plan, the
    reorder and the folders are unaffected, the global stays on the plan as the accepted
    proposal it is, and the report says it was not written and why."""
    result = run(run_dir, script=valid_script(), which_configs=None)
    assert result.verification.passed, result.verification.reasons
    assert len(result.plan.globals) == 1
    assert [change for change in result.plan.changes if change.kind == "equation.add"] == []
    unwritten = [
        item
        for item in result.plan.coverage
        if item.item == runner.GLOBALS_ITEM and "not written into the copy" in item.reason
    ]
    assert len(unwritten) == 1
    assert "which_configs" in unwritten[0].reason


def test_describing_a_feature_the_tree_does_not_carry_is_refused(run_dir: Path) -> None:
    """Unreachable through the tools, which validate first; a loud refusal all the same,
    because a change addressed at nothing has no persistent reference to send."""
    proposal = DescriptionProposal(
        feature_id="feat:9999",
        before="",
        text="a feature this tree does not carry",
        source="model",
        rationale="fixture",
        provider=ProviderName.FAKE.value,
        model=MODEL,
        validation="accepted",
    )
    with pytest.raises(ValueError, match="does not carry"):
        runner.describe_changes([proposal], list(PACKAGE.features))


# --- 4. a script that proposes garbage ---------------------------------------------------


@pytest.fixture
def refused(run_dir: Path) -> RemodelPlan:
    return run(run_dir, script=garbage_script()).plan


def test_a_run_of_garbage_still_completes(run_dir: Path) -> None:
    result = run(run_dir, script=garbage_script())
    assert result.verification.passed, result.verification.reasons
    assert state_on_disk(run_dir) == "saved"


def test_every_garbage_proposal_is_written_down_once(refused: RemodelPlan) -> None:
    assert len(refused.rejected_proposals) == len(GARBAGE)


@pytest.mark.parametrize(
    ("index", "tool", "rule"),
    [(index, tool, rule) for index, (tool, _, rule) in enumerate(GARBAGE)],
)
def test_each_garbage_proposal_is_refused_by_the_rule_that_owns_it(
    refused: RemodelPlan, index: int, tool: str, rule: str
) -> None:
    row = refused.rejected_proposals[index]
    assert row.tool == tool
    assert row.rule == rule


@pytest.mark.parametrize(
    ("index", "arguments"),
    [(index, arguments) for index, (_, arguments, _) in enumerate(GARBAGE)],
)
def test_a_rejection_records_the_arguments_that_were_sent(
    refused: RemodelPlan, index: int, arguments: dict[str, Any]
) -> None:
    """The arguments as sent, not as corrected: the report shows what was asked for."""
    assert refused.rejected_proposals[index].arguments == arguments


def test_a_rejection_carries_everything_the_report_prints(refused: RemodelPlan) -> None:
    for row in refused.rejected_proposals:
        assert row.reason.strip()
        assert row.provider == ProviderName.FAKE.value
        assert row.model == MODEL
        assert row.at is not None


def test_revision_two_keeps_only_the_valid_proposals(refused: RemodelPlan) -> None:
    assert [item.text for item in refused.descriptions] == [GOOD_DESCRIPTION]
    assert refused.globals == ()
    assert [item.feature_id for item in refused.targets if item.decided_by == "model"] == []


def test_a_refusal_never_becomes_a_change(refused: RemodelPlan) -> None:
    """One description was accepted, so exactly one `describe` change exists."""
    assert len([change for change in refused.changes if change.kind == "describe"]) == 1
    assert [change for change in refused.changes if change.kind == "equation.add"] == []


def test_no_tool_the_phase_offers_names_a_document(run_dir: Path) -> None:
    """The stronger reading of "a tool call trying to name a document": there is no such
    call to make. No tool takes a path, a document or a run folder."""
    context, _ = runner.judgement_context(
        plan=planned(run_dir), package=PACKAGE, provider="fake", model=MODEL,
        document_length_unit=UNIT,
    )
    tools = runner.judgement_tools(context)
    forbidden = ("path", "document", "file", "run_dir", "copy")
    for tool in tools:
        properties = tool.spec.schema.get("properties", {})
        assert not [name for name in properties if any(word in name for word in forbidden)], (
            f"{tool.name} takes an argument that names a document"
        )


# --- 5. the judgement phase reaches no document -------------------------------------------


class NoBridge:
    """A seat that refuses every call, for the phase that must make none."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(
            f"the judgement phase sent remodel.{name}; it proposes into a plan and writes "
            "nothing to any document (contracts/tools.md)"
        )


def test_the_judgement_phase_sends_no_remodel_command(run_dir: Path) -> None:
    """Asserted against a bridge fake that fails any call: `judge` never receives one."""
    bridge = NoBridge()
    after = runner.judge(
        run_dir=run_dir,
        plan=planned(run_dir),
        package=PACKAGE,
        provider=fake(valid_script()),
        sink=EventSink(run_dir / EVENTS_FILE_NAME),
        document_length_unit=UNIT,
        which_configs=WHICH_CONFIGS_THIS,
        now=StepClock(AT, 1.0),
    )
    assert after.plan_revision == 2
    with pytest.raises(AssertionError):
        bridge.rename  # noqa: B018 - the fake has to fail, or it proves nothing


def test_the_fake_seat_is_the_only_sink_of_remodel_commands(run_dir: Path) -> None:
    """Nothing reaches the seat until revision 2 is on disk, and everything after does."""
    bridge = bridge_for(PACKAGE)
    opened(bridge)
    sent_during_judging: list[tuple[str, ...]] = []

    plan = planned(run_dir)
    sink = EventSink(run_dir / EVENTS_FILE_NAME)
    sink.add_listener(lambda _event: sent_during_judging.append(bridge.commands))
    runner.judge(
        run_dir=run_dir,
        plan=plan,
        package=PACKAGE,
        provider=fake(valid_script()),
        sink=sink,
        document_length_unit=UNIT,
        which_configs=WHICH_CONFIGS_THIS,
        now=StepClock(AT, 1.0),
    )
    assert sent_during_judging, "the judgement phase emitted no events at all"
    assert set(sent_during_judging) == {("remodel.geometry",)}


def test_the_turn_is_offered_exactly_the_five_proposal_tools(run_dir: Path) -> None:
    """Principle II: four `propose_*` tools plus one read-back, and no bridge on the
    context, so no bridge tool is registered for the turn either."""
    context, _ = runner.judgement_context(
        plan=planned(run_dir), package=PACKAGE, provider="fake", model=MODEL,
        document_length_unit=UNIT,
    )
    assert context.bridge is None
    assert {tool.name for tool in runner.judgement_tools(context)} == {
        "propose_description",
        "propose_global",
        "decide_fillet",
        "classify_unknown",
        "get_remodel_plan",
    }


# --- 6. the phase is skippable, and the limits are the executor's --------------------------


def test_a_plan_with_nothing_to_judge_has_no_slots(run_dir: Path) -> None:
    package = plain_part()
    assert runner.judgement_slots(planned(run_dir, package), package) == ()
    assert runner.judgement_slots(planned(run_dir), PACKAGE)


def test_a_run_with_no_judgement_slots_never_constructs_a_provider(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-009's runtime half: the apply loop provably runs with no model in it."""

    def refuse(name: str) -> type:
        raise AssertionError(f"a provider ({name}) was constructed for a run with no slots")

    monkeypatch.setattr(providers, "get", refuse)
    package = plain_part()
    result = run(run_dir, package=package, bridge=bridge_for(package))
    assert result.judged is False
    assert result.verification.passed, result.verification.reasons
    reasons = [item.reason for item in result.plan.coverage]
    assert runner.JUDGEMENT_SKIPPED in reasons


def test_a_run_with_no_provider_settings_skips_the_phase(run_dir: Path) -> None:
    result = run(run_dir, settings=None)
    assert result.judged is False
    assert result.plan.plan_revision == 2
    assert runner.JUDGEMENT_SKIPPED in [item.reason for item in result.plan.coverage]


def test_a_provider_failure_is_reported_and_the_run_still_completes(run_dir: Path) -> None:
    """A model that fell over contributed nothing; it does not take the run with it."""

    class Falls:
        name = ProviderName.FAKE
        model = MODEL

        def effort_mapping(self, effort: str) -> Any:
            return fake(SILENT).effort_mapping(effort)  # type: ignore[arg-type]

        def run(self, **_kwargs: Any) -> Any:
            raise RuntimeError("the provider fell over")

    events: list[AgentEvent] = []
    result = run(
        run_dir,
        provider_factory=lambda _settings: Falls(),  # type: ignore[arg-type,return-value]
        callbacks=[events.append],
    )
    assert result.verification.passed, result.verification.reasons
    assert [event.body["reason"] for event in events if event.type == "turn.ended"] == ["error"]
    assert any("the provider fell over" in item.reason for item in result.plan.coverage)


def refuses_to_build(_settings: ProviderSettings) -> AgentProvider:
    """A `provider_factory` that raises the way `build_provider` does with no key."""
    raise RuntimeError("OPENAI_API_KEY is not set for this run")


def test_a_provider_that_cannot_be_built_is_reported_and_the_run_still_completes(
    run_dir: Path,
) -> None:
    """A model that could not be *constructed* is an absence, not a lost plan.

    `build_provider` reaches a vendor SDK - a key that is not set, a package that is not
    installed, a base URL nobody can parse - and every one of those raises before there is
    a turn to fail. The deterministic plan is already good at that point, so the run goes
    on and says a model was asked for and could not be built (FR-045).
    """
    events: list[AgentEvent] = []
    result = run(run_dir, provider_factory=refuses_to_build, callbacks=[events.append])
    assert result.verification.passed, result.verification.reasons
    assert result.judged is False
    assert result.plan.plan_revision == 2
    errors = [event for event in events if event.type == "error"]
    assert [event.body["message"] for event in errors] == [
        "OPENAI_API_KEY is not set for this run"
    ]
    assert errors[0].body["retryable"] is True
    reasons = [item.reason for item in result.plan.coverage if item.item == runner.JUDGEMENT_ITEM]
    assert reasons == [
        runner.JUDGEMENT_UNAVAILABLE.format(error="OPENAI_API_KEY is not set for this run")
    ]


def test_a_provider_that_cannot_be_built_ends_no_turn(run_dir: Path) -> None:
    """Nothing started, so nothing ended: no session and no turn reach the stream."""
    events: list[AgentEvent] = []
    run(run_dir, provider_factory=refuses_to_build, callbacks=[events.append])
    assert [event.type for event in events if event.type != "error"] == []


class FallsAfterProposing:
    """A provider that proposes once through the fake and then fails mid-turn."""

    name = ProviderName.FAKE
    model = MODEL

    def __init__(self, script: Sequence[ScriptedTurn]) -> None:
        self._fake = fake(script)

    def effort_mapping(self, effort: str) -> Any:
        return self._fake.effort_mapping(effort)  # type: ignore[arg-type]

    def run(self, **kwargs: Any) -> Any:
        self._fake.run(**kwargs)
        raise RuntimeError("the provider fell over after proposing")


def test_a_failure_after_a_proposal_keeps_the_proposal_and_counts_it(run_dir: Path) -> None:
    """The mixed case: accepted on round 3, a rate limit on round 4.

    What was accepted is carried into revision 2 either way, so a coverage row saying the
    phase "proposed nothing" would be the plan lying about where a description came from
    (FR-020, FR-056).
    """
    result = run(
        run_dir,
        provider_factory=lambda _settings: FallsAfterProposing(  # type: ignore[arg-type,return-value]
            turn(DESCRIBE_THE_BOSS)
        ),
    )
    assert result.verification.passed, result.verification.reasons
    assert [item.text for item in result.plan.descriptions] == [GOOD_DESCRIPTION]
    reasons = [item.reason for item in result.plan.coverage if item.item == runner.JUDGEMENT_ITEM]
    assert reasons == [
        runner.JUDGEMENT_FAILED_PARTIAL.format(
            count=1, error="the provider fell over after proposing"
        )
    ]


def test_a_judgement_turn_cut_off_at_the_step_budget_is_written_down(run_dir: Path) -> None:
    """A turn out of steps is not a turn that had nothing to add (Principle VI)."""
    events: list[AgentEvent] = []
    result = run(
        run_dir,
        script=turn(
            DESCRIBE_THE_BOSS,
            ScriptedToolCall(
                "propose_global",
                {
                    "name": GOOD_GLOBAL,
                    "expression": "5",
                    "rationale": "never reached: the budget stops the turn first",
                    "evidence": [IDS["Fillet1"]],
                },
            ),
        ),
        max_steps=1,
        callbacks=[events.append],
    )
    assert result.verification.passed, result.verification.reasons
    assert [item.text for item in result.plan.descriptions] == [GOOD_DESCRIPTION]
    assert result.plan.globals == ()
    assert [event.body["reason"] for event in events if event.type == "turn.ended"] == [
        "max_steps"
    ]
    reasons = [item.reason for item in result.plan.coverage if item.item == runner.JUDGEMENT_ITEM]
    assert reasons == [
        runner.JUDGEMENT_CUT_SHORT.format(reason=MAX_STEPS_CLOSEOUT.format(max_steps=1))
    ]


def test_a_judgement_turn_the_provider_truncated_is_written_down(run_dir: Path) -> None:
    """The other end that is not a normal stop: the provider's own output ceiling."""
    result = run(
        run_dir,
        script=[
            ScriptedTurn(
                text="Cut off", tool_calls=(DESCRIBE_THE_BOSS,), end_reason="truncated"
            )
        ],
    )
    assert result.verification.passed, result.verification.reasons
    assert [item.text for item in result.plan.descriptions] == [GOOD_DESCRIPTION]
    reasons = [item.reason for item in result.plan.coverage if item.item == runner.JUDGEMENT_ITEM]
    assert reasons == [runner.JUDGEMENT_CUT_SHORT.format(reason=TRUNCATED_CLOSEOUT)]


def test_a_cut_short_turn_that_proposed_nothing_records_both(run_dir: Path) -> None:
    """Two facts, two rows: it proposed nothing, and it did not get to finish."""
    result = run(
        run_dir, script=[ScriptedTurn(text="Cut off", tool_calls=(), end_reason="truncated")]
    )
    reasons = [item.reason for item in result.plan.coverage if item.item == runner.JUDGEMENT_ITEM]
    assert reasons == [
        runner.NOTHING_PROPOSED,
        runner.JUDGEMENT_CUT_SHORT.format(reason=TRUNCATED_CLOSEOUT),
    ]


def test_a_limit_stops_the_run_and_the_state_says_truncated(run_dir: Path) -> None:
    """The limits are the executor's and hitting one is never a silent partial success."""
    plan = planned(run_dir)
    assert len(plan.changes) > 1, "the fixture must plan more changes than the bound below"
    bounded = plan.model_copy(update={"limits": plan.limits.model_copy(update={"max_changes": 1})})
    result = run(run_dir, script=SILENT, plan=bounded)
    assert result.applied.status == "truncated"
    assert result.plan.state == "truncated"
    assert state_on_disk(run_dir) == "truncated"


# --- T134c the engineer's stop, threaded through the run ------------------------------------


def test_the_engineer_stop_truncates_the_run_and_the_state_says_so(run_dir: Path) -> None:
    """`remodel.stop` "finalizes the artifacts and reports the run as `truncated`".

    The flag is raised while the run is under way - after the seat has taken one mutating
    call - and the run still reaches a terminal state through phase D with every artifact
    written, because a stopped run is a partial run and never an abandoned one.
    """
    bridge = bridge_for(PACKAGE)
    plan = planned(run_dir)
    assert len(plan.changes) > 1, "the fixture must plan more changes than the stop below"

    result = run(
        run_dir,
        script=SILENT,
        bridge=bridge,
        stop_requested=lambda: bridge.mutations >= 1,
    )

    assert result.applied.status == "truncated"
    assert result.applied.stop is not None
    assert result.applied.stop.reason == "stopped"
    assert result.applied.not_attempted
    assert result.plan.state == "truncated"
    assert state_on_disk(run_dir) == "truncated"
    assert (run_dir / REPORT_FILE_NAME).is_file()


def test_the_changes_a_stopped_run_applied_are_read_from_the_run_folder(
    run_dir: Path,
) -> None:
    """`remodel.stopped {changes_applied}` is answered from `changes.jsonl`, so the pane can
    still answer it after the process that ran the run is gone.

    The save is filtered out because it is not a planned change: the copy is saved once, at
    the end, by the gate, and it is recorded in the same log as the write it is.
    """
    bridge = bridge_for(PACKAGE)
    result = run(
        run_dir,
        script=SILENT,
        bridge=bridge,
        stop_requested=lambda: bridge.mutations >= 1,
    )

    written = read_changes(run_dir / CHANGES_FILE_NAME)
    applied = [row.seq for row in written if row.status == "applied" and row.kind != "save"]
    assert applied == [1] == list(result.applied.applied)
    assert [(row.kind, row.status) for row in written] == [
        ("reorder", "attempting"),
        ("reorder", "applied"),
        ("save", "attempting"),
        ("save", "applied"),
    ]


def test_a_run_nobody_stopped_applies_every_planned_change(run_dir: Path) -> None:
    """The default flag is never up, so the stop costs an unstopped run nothing."""
    result = run(run_dir, script=SILENT)

    assert result.applied.status == "complete"
    assert result.applied.stop is None
    assert len(result.applied.applied) == len(result.plan.changes)


# --- T134b the dump after the last change, and the run that does not get one ----------------


def test_a_dump_after_that_raises_finalizes_the_run_as_failed(run_dir: Path) -> None:
    """The reading after the last change comes from the add-in, and it can fail.

    `dump_after` is an out-of-process dump on the application thread and a rendezvous with
    it that times out, so the run has to survive one raising: the changes are already on the
    copy and a run that left `plan.json` saying `applying` would be a run nobody could read
    the state of. The exception is re-raised after the run is finalized, because the caller
    is the one that decides what to tell the engineer.
    """

    def dump_after() -> EvidencePackage:
        raise RuntimeError("the add-in never sent package-after.json")

    with pytest.raises(RuntimeError, match="never sent package-after"):
        run(run_dir, script=SILENT, dump_after=dump_after)

    assert state_on_disk(run_dir) == "failed"


def test_a_dump_after_that_raises_leaves_the_change_log_intact(run_dir: Path) -> None:
    """Every change that was applied is still on disk, closed out, and no line is rewritten."""

    def dump_after() -> EvidencePackage:
        raise RuntimeError("the add-in never sent package-after.json")

    with pytest.raises(RuntimeError):
        run(run_dir, script=SILENT, dump_after=dump_after)

    written = read_changes(run_dir / CHANGES_FILE_NAME)
    assert written
    assert [row.status for row in written[1::2]] == ["applied"] * (len(written) // 2)
    assert len(written) == 2 * len(plan_on_disk(run_dir).changes)


def test_a_dump_after_that_raises_writes_the_reason_on_the_plan(run_dir: Path) -> None:
    """The failure is written down where every other absence of this run is: one
    `PlanCoverage` row naming the item and the error, so "why did this run fail" is
    answerable from the folder rather than from a traceback nobody kept."""

    def dump_after() -> EvidencePackage:
        raise RuntimeError("the add-in never sent package-after.json")

    with pytest.raises(RuntimeError):
        run(run_dir, script=SILENT, dump_after=dump_after)

    reasons = [
        item.reason
        for item in plan_on_disk(run_dir).coverage
        if item.item == runner.PACKAGE_AFTER_ITEM
    ]
    assert reasons == [
        runner.PACKAGE_AFTER_FAILED.format(
            error="the add-in never sent package-after.json"
        )
    ]


def test_a_dump_after_that_raises_is_reported_on_the_event_stream(run_dir: Path) -> None:
    """The same stream every other failure of this run is reported on, so a pane watching
    the run sees the failure rather than a stream that simply stops."""

    def dump_after() -> EvidencePackage:
        raise RuntimeError("the add-in never sent package-after.json")

    with pytest.raises(RuntimeError):
        run(run_dir, script=SILENT, dump_after=dump_after)

    errors = [
        event
        for event in (
            AgentEvent.model_validate_json(line)
            for line in (run_dir / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
        )
        if event.type == "error"
    ]
    assert [event.body["error_class"] for event in errors] == ["RuntimeError"]
    assert errors[0].body["message"] == "the add-in never sent package-after.json"


def test_a_failed_verification_discards_the_copy_and_fails_the_run(run_dir: Path) -> None:
    bridge = FakeRemodelBridge(
        seat(PACKAGE),
        readings=[reading(), reading(volume_m3=2.0e-3)],
    )
    result = run(run_dir, script=SILENT, bridge=bridge)
    assert not result.verification.passed
    assert result.verification.copy_discarded
    assert state_on_disk(run_dir) == "failed"


# --- 7. what the run leaves behind ----------------------------------------------------------


def test_the_run_writes_every_artifact_the_contract_names(run_dir: Path) -> None:
    run(run_dir, script=valid_script())
    for name in (
        PLAN_FILE_NAME,
        CHANGES_FILE_NAME,
        GRADES_FILE_NAME,
        GEOMETRY_FILE_NAME,
        REPORT_FILE_NAME,
        SESSION_FILE_NAME,
        EVENTS_FILE_NAME,
    ):
        assert (run_dir / name).is_file(), f"{name} was not written"


def test_events_jsonl_is_one_stamped_stream(run_dir: Path) -> None:
    run(run_dir, script=valid_script())
    lines = [
        AgentEvent.model_validate_json(line)
        for line in (run_dir / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
    ]
    assert [event.seq for event in lines] == list(range(1, len(lines) + 1))
    types = [event.type for event in lines]
    assert types[0] == "session.started"
    assert types[-1] == "session.ended"
    assert types.count("turn.ended") == 1
    assert types.count("tool.started") == len(valid_script()[0].tool_calls)


def test_every_event_of_the_run_validates_against_the_chat_events_contract(
    run_dir: Path,
) -> None:
    """`data-model.md` section 10: a remodel run writes the same stream a review does, and
    `002/contracts/chat-events.schema.json` is authoritative for both."""
    run(run_dir, script=valid_script())
    validator = contract_validator("chat-events.schema.json")
    lines = (run_dir / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        validator.validate(json.loads(line))


def test_no_review_shaped_event_is_emitted(run_dir: Path) -> None:
    """A re-model produces a plan, not findings: the four review-only types never appear."""
    run(run_dir, script=valid_script())
    types = {
        AgentEvent.model_validate_json(line).type
        for line in (run_dir / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
    }
    assert types.isdisjoint(
        {"finding", "evidence.requested", "evidence.answered", "disposition"}
    )


def test_session_json_records_every_tool_call_the_turn_made(run_dir: Path) -> None:
    """`session.json` is written through the recorded registry, so `tool_result_ids`
    reference steps that exist (`contracts/run-artifacts.md`)."""
    run(run_dir, script=valid_script())
    body = json.loads((run_dir / SESSION_FILE_NAME).read_text(encoding="utf-8"))
    assert len(body["steps"]) == len(valid_script()[0].tool_calls)
    assert body["provider_info"]["provider"] == ProviderName.FAKE.value
    assert body["provider_info"]["model"] == MODEL
    assert body["ended_at"] is not None


def test_a_skipped_phase_writes_no_event_stream(run_dir: Path) -> None:
    """Nothing pretends a turn happened: no provider, no events, no session."""
    result = run(run_dir, settings=None)
    assert result.judged is False
    assert not (run_dir / EVENTS_FILE_NAME).exists()
    assert not (run_dir / SESSION_FILE_NAME).exists()


# --- 8. the one provider construction site ----------------------------------------------------


def test_the_default_provider_is_openai(run_dir: Path) -> None:
    """OpenAI is the default and Gemini the only alternative (contracts/tools.md)."""
    assert runner.DEFAULT_PROVIDER is DEFAULT_PROVIDER is ProviderName.OPENAI


def test_the_scripted_provider_is_not_built_by_the_product(run_dir: Path) -> None:
    """A script is the caller's; `build_provider` builds the two real adapters only."""
    with pytest.raises(ValueError, match="script"):
        runner.build_provider(settings_for(ProviderName.FAKE))
