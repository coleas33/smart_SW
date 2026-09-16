"""Lever 4, the withheld path: a tool we declined to offer, reported as such (T061).

A withheld tool is **unresolved coverage with a sentence an engineer can read** - never a
silent miss and never `failed`. Today's behaviour is wrong for it in three ways, and each
is asserted here:

1. a call to a name nothing is registered under records a **`failed`** coverage item,
   which says the tool broke when it did not - we declined to offer it;
2. `failed` is deliberately absent from the checklist's closing buckets, so the item ends
   `open` and finalization turns it into a second, vaguer `unresolved` item with the
   generic reason, and the engineer never learns we withheld the tool;
3. the error message hands the model the whole tool list in a tool result, which is the
   opposite of what a lever whose purpose is bytes should do.

The last test is the regression guard that must **not** move: a genuinely hallucinated
name still gets the old message and the old `failed` item. That path is load-bearing - a
hallucinated name is routine, not exceptional.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.checklist import ChecklistItem, load_checklist
from swreview.agent.providers import AgentEvent
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, ReviewSession, load_session, save_session
from swreview.tools.context import context_for, rms_not_gradable, use_context
from swreview.tools.registry import RMS_TIER_TOOLS
from swreview.tools.rms_checks import check_rms_assembly
from tests.support.contracts import contract_validator
from tests.support.tiers import (
    OFF,
    ON,
    assembly_without_tree_with_a_gradable_defect,
    dispatch_for,
    full_assembly_without_tree,
    part_only_without_tree,
)

WITHHELD = "check_rms_part"
CHECKLIST_ITEM = "modeling.resilience"
HALLUCINATED = "inspect_feature_tree"
"""A name nothing is registered under and no tier withholds. Deliberately not a near-miss
of a real one: this guard is about the substring never appearing, not about spelling."""
GENERIC_FINALIZATION_REASON = "the review ended without a finding or a coverage entry for it"


@pytest.fixture
def package() -> EvidencePackage:
    """An assembly with no part documents, so the tree the tier's rule reads is not there."""
    return full_assembly_without_tree()


def item() -> ChecklistItem:
    """The checklist item the RMS tier closes out."""
    return next(entry for entry in load_checklist().items if entry.id == CHECKLIST_ITEM)


def review(
    tmp_path: Path,
    package: EvidencePackage,
    *,
    calls: tuple[str, ...] = (WITHHELD,),
    efficiency: Any = ON,
) -> tuple[ReviewSession, list[AgentEvent]]:
    """One scripted review that asks for `calls`, played end to end through `start_review`."""
    package_dir = tmp_path / "package"
    save_package(package, package_dir)
    provider = FakeProvider(
        script=[
            ScriptedTurn(
                text="done",
                tool_calls=tuple(
                    ScriptedToolCall(name=name, arguments={"document_id": "doc:2"})
                    for name in calls
                ),
            )
        ],
        model="fake-scripted",
    )
    events: list[AgentEvent] = []
    run = start_review(
        package_dir,
        tmp_path / "out",
        provider=provider,
        efficiency=efficiency,
        callbacks=[events.append],
    )
    return run.start(), events


def unresolved(session: ReviewSession, check: str) -> list[CoverageItem]:
    return [entry for entry in session.coverage.unresolved if entry.check == check]


# --- 1. not on the wire, still in the dispatch ---------------------------------------------


def test_the_withheld_tool_is_absent_from_the_tool_set_but_resolves_by_name(
    package: EvidencePackage,
) -> None:
    """No schema reaches the wire - that is where the bytes are saved - and yet a model
    that asks for it is answered rather than told the tool does not exist."""
    dispatch = dispatch_for(package, efficiency=ON)

    assert WITHHELD not in [tool.name for tool in dispatch]
    assert dispatch.get(WITHHELD) is not None
    assert len(dispatch) == len([tool.name for tool in dispatch])


def test_the_result_names_the_tier_rule_and_not_the_list_of_available_tools(
    package: EvidencePackage,
) -> None:
    """One writer for the sentence: the model reads exactly what the report renders."""
    dispatch = dispatch_for(package, efficiency=ON)

    result = dispatch.call(WITHHELD, {"document_id": "doc:2"}, "call_1")

    assert result.is_error is True
    assert result.payload["error"] == rms_not_gradable(package)
    assert "the tools available are" not in result.payload["error"]
    assert "list_components" not in result.payload["error"]


def test_the_sentence_names_the_rule_its_evidence_and_what_to_do(
    package: EvidencePackage,
) -> None:
    """A reason that said only "not covered" would be worth nothing to an engineer."""
    reason = rms_not_gradable(package)

    assert reason is not None
    assert "no feature rows" in reason
    assert repr(package.extractor.profile) in reason
    assert "Extract the model again" in reason


# --- 2. what the run records ----------------------------------------------------------------


def test_the_call_is_still_traced_as_a_started_finished_pair_and_one_step(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """The pane and the step log show the attempt: we declined, we did not pretend."""
    session, events = review(tmp_path, package)

    started = [event for event in events if event.type == "tool.started"]
    finished = [event for event in events if event.type == "tool.finished"]
    assert [event.body["tool"] for event in started] == [WITHHELD]
    assert len(finished) == 1
    assert finished[0].body["status"] == "error"
    assert [step.tool for step in session.steps] == [WITHHELD]
    assert session.steps[0].error == rms_not_gradable(package)


def test_the_session_holds_one_unresolved_item_naming_the_tier_rule(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """`unresolved` with a sentence, which is the difference between "not covered" and
    "not covered because"."""
    session, _ = review(tmp_path, package)

    items = unresolved(session, CHECKLIST_ITEM)
    assert len(items) == 1
    assert items[0].reason == rms_not_gradable(package)
    assert items[0].error is None


def test_a_withheld_tool_never_writes_failed_coverage(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """`failed` says the tool broke. It did not; we chose not to offer it, and the two
    call for opposite actions."""
    session, _ = review(tmp_path, package)

    assert session.coverage.failed == []


def test_calling_a_withheld_tool_twice_still_leaves_one_item(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """The item stands for the state of the rule, not for one occurrence of the call."""
    session, _ = review(tmp_path, package, calls=(WITHHELD, "check_rms_equations"))

    assert len(unresolved(session, CHECKLIST_ITEM)) == 1
    assert len(session.steps) == 2


# --- 3. the checklist consequence -------------------------------------------------------------


def test_the_checklist_item_is_unresolved_rather_than_open(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """`unresolved` is one of the buckets `bucket_of` searches; `failed` is not, which is
    why today's behaviour leaves the item open."""
    session, _ = review(tmp_path, package)

    assert load_checklist().bucket_of(item(), session) == "unresolved"


def test_finalization_does_not_add_a_second_vaguer_item(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """The item is already closed out, so the generic sentence is never reached for it."""
    session, _ = review(tmp_path, package)

    reasons = [entry.reason for entry in unresolved(session, CHECKLIST_ITEM)]
    assert reasons == [rms_not_gradable(package)]
    assert GENERIC_FINALIZATION_REASON not in " ".join(reasons)


# --- 4. the flag off, and the hallucinated name ------------------------------------------------


def test_the_flag_off_offers_the_tool_and_writes_no_withheld_coverage(
    tmp_path: Path,
) -> None:
    """Every shipped run is this one: the lever changes nothing until it is turned on."""
    package = part_only_without_tree()
    dispatch = dispatch_for(package, efficiency=OFF)
    session, _ = review(tmp_path, package, efficiency=OFF)

    assert WITHHELD in [tool.name for tool in dispatch]
    assert [entry.reason for entry in unresolved(session, CHECKLIST_ITEM)] != [
        rms_not_gradable(package)
    ]


def test_a_hallucinated_name_still_fails_with_the_message_it_always_had(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """The regression guard. A name that is neither registered nor withheld is routine
    model behaviour and keeps the `failed` coverage item and the tool list it always had."""
    session, _ = review(tmp_path, package, calls=(HALLUCINATED,))

    failed = [entry for entry in session.coverage.failed if entry.check == f"tool.{HALLUCINATED}"]
    assert len(failed) == 1
    assert session.steps[0].error is not None
    assert f"no tool named {HALLUCINATED!r}" in session.steps[0].error
    assert "the tools available are" in session.steps[0].error


def test_the_available_tool_list_never_advertises_a_withheld_name(
    package: EvidencePackage,
) -> None:
    """A withheld tool is not available, so the hallucination message must not offer it."""
    dispatch = dispatch_for(package, efficiency=ON)

    result = dispatch.call(HALLUCINATED, {}, "call_1")

    assert not [name for name in RMS_TIER_TOOLS if name in result.payload["error"]]


# --- 5. the sentence is true about what it gives up -------------------------------------------


def test_the_assembly_rules_grade_a_package_with_no_feature_rows() -> None:
    """The premise the reason has to be honest about.

    `_refuse_empty_feature_tree` (`checks/rms/run.py`) raises only for a **document**-scoped
    family, and says why in its own docstring: the four `rms.assembly.*` rules read the
    mates and the component instances and never `features[]`. So an empty tree is not
    "nothing is gradable" - it is "the part and the equation rules are not gradable", and a
    real defect is still there to be found.
    """
    package = assembly_without_tree_with_a_gradable_defect()
    context = context_for(package)

    with use_context(context):
        result = check_rms_assembly()

    assert package.features == []
    assert [finding["check"] for finding in result["findings"]] == [
        "rms.assembly.mates_to_reference_geometry"
    ]
    assert result["findings"][0]["status"] == "demonstrated"


def test_the_reason_does_not_claim_the_assembly_rules_could_not_be_graded() -> None:
    """A reason an engineer acts on has to be true, or it is worth less than silence.

    The tier withholds `check_rms_assembly` with the five tree readers - T060 names all six
    - so the sentence must say that the assembly rules are being **given up**, not that
    they could not have run. The first is a trade an owner can weigh; the second is a
    statement the package contradicts.
    """
    package = assembly_without_tree_with_a_gradable_defect()

    reason = rms_not_gradable(package)

    assert reason is not None
    assert "assembly or equation rule could be graded" not in reason
    assert "no part rule and no equation rule could be graded" in reason
    assert "four assembly rules" in reason
    assert "withheld with them" in reason


def test_the_withheld_assembly_tool_hands_the_model_that_same_sentence() -> None:
    """One writer: what the model is told is what the report renders, wording included."""
    package = assembly_without_tree_with_a_gradable_defect()
    dispatch = dispatch_for(package, efficiency=ON)

    result = dispatch.call("check_rms_assembly", {}, "call_1")

    assert "check_rms_assembly" not in [tool.name for tool in dispatch]
    assert result.payload["error"] == rms_not_gradable(package)


# --- 6. what the ledger counts this as (FR-054) ------------------------------------------------


def test_the_run_records_which_check_the_refusal_closed(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """The split the results ledger reads is a recorded fact, not a parsed sentence.

    `unresolved_because_withheld` is "items a `WithheldTool` wrote", and the only other way
    to know which ones those are is to substring-match the reason - which would make a
    reworded sentence a silent measurement change. The run writes the check down instead.
    """
    session, _ = review(tmp_path, package)

    assert session.withheld_checks == [CHECKLIST_ITEM]
    assert [entry.check for entry in unresolved(session, CHECKLIST_ITEM)] == [CHECKLIST_ITEM]


def test_asking_twice_records_the_check_once(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """One check, one item, one entry: the same rule `replace_coverage` follows."""
    session, _ = review(tmp_path, package, calls=(WITHHELD, "check_rms_equations"))

    assert session.withheld_checks == [CHECKLIST_ITEM]


def test_a_run_that_withheld_nothing_records_nothing(tmp_path: Path) -> None:
    """Empty is the shipped state, and an empty list is what a flag-off run writes."""
    session, _ = review(tmp_path, part_only_without_tree(), efficiency=OFF)

    assert session.withheld_checks == []


def test_the_record_survives_the_session_file(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """The scorer reads `session.json` off disk hours later, so the field has to be in it."""
    session, _ = review(tmp_path, package)
    path = save_session(session, tmp_path / "session.json")

    assert load_session(path).withheld_checks == [CHECKLIST_ITEM]


def test_a_session_written_before_the_field_existed_still_loads(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """Additive, like `provider_info` and `efficiency` before it: a feature 001 session
    has no such key and loads unchanged."""
    session, _ = review(tmp_path, package)
    written = json.loads(save_session(session, tmp_path / "session.json").read_text("utf-8"))
    del written["withheld_checks"]
    path = tmp_path / "old.json"
    path.write_text(json.dumps(written), encoding="utf-8")

    assert load_session(path).withheld_checks == []
    contract_validator("review-session.schema.json").validate(written)
