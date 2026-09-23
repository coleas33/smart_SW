"""The six guards on carry-over, one test each (T105, lever 11a).

A carried-over finding looks like a verdict and is actually a memory (RK-15), so the
guards are the lever: without them it is a mechanism for publishing yesterday's answer
under today's date. data-model.md section 10.5 numbers them, and so do the sections here.

1. Carry only from a session that finished: `ended_at` non-null, and no `failed` coverage
   naming this check. A verdict from a run cut short is not a verdict to reuse.
2. Carry only `demonstrated` and `checked_within_scope`. `suspected` and `unresolved` are
   where the model's judgement sits, which is exactly what must not be frozen.
3. Never carry a finding an engineer has dispositioned.
4. Never carry when an exception touching those components is in `needs_review`.
5. Never carry across a check-version or tree change - the key covers that, and the
   minimum bar test is at the bottom of section 5: mutate **one feature row** and the
   finding is re-run.
6. Cap the carry. `MAX_CARRY_OVER_RUNS` bounds how far a verdict travels from the run that
   computed it.

Then the three things a carry must never fail to do: mark the finding, write the coverage
entry, and put both on the event stream - and the one thing the flag off must do, which is
nothing at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import run_review
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.scorecard import score_run
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet
from swreview.carry_over import (
    CARRIED_REASON_PREFIX,
    MAX_CARRY_OVER_RUNS,
    carry_over_findings,
    carry_over_key,
    select_carry_over,
    stamp_carry_over_keys,
)
from swreview.checks.rms.part import INDIVIDUALLY_SUPPRESSIBLE
from swreview.exceptions import ExceptionStore
from swreview.findings import Disposition, Finding
from swreview.ir.loader import LoadedPackage, save_package
from swreview.ir.models import EvidencePackage
from swreview.report.markdown import render_report
from swreview.report.names import component_names
from swreview.report.session import (
    MAX_STEPS_CLOSEOUT,
    TRUNCATED_CLOSEOUT,
    ReviewSession,
    save_session,
)
from swreview.tools.context import ToolContext, build_context
from tests.support.carry_over import (
    CARRIED_AT,
    COMPONENT,
    OTHER_RMS_CHECK,
    PREVIOUS_SESSION_ID,
    RMS_CHECK,
    carry_package,
    mutated_package,
    previous_session,
    rms_finding,
)
from tests.support.contracts import contract_validator

ON = EfficiencySettings(carry_over_rms=True)
OFF = EfficiencySettings()


def carried_checks(package: EvidencePackage, previous: ReviewSession) -> set[str]:
    """The checks `select_carry_over` would carry forward, as a set of rule ids."""
    decision = select_carry_over(package, previous, at=CARRIED_AT)
    return {carried.finding.check for carried in decision.carried}


# --- guard 1: only from a session that finished ---------------------------------------


def test_a_session_that_never_ended_carries_nothing() -> None:
    package = carry_package()
    previous = previous_session(package, [rms_finding(package)], ended=False)

    decision = select_carry_over(package, previous, at=CARRIED_AT)

    assert decision.carried == ()
    assert len(decision.re_run) == 1


@pytest.mark.parametrize(
    "closeout_reason",
    [
        MAX_STEPS_CLOSEOUT.format(max_steps=200),
        TRUNCATED_CLOSEOUT,
    ],
    ids=["max_steps", "output_ceiling"],
)
def test_a_run_cut_short_carries_nothing_even_though_it_ended(closeout_reason: str) -> None:
    """A run stopped by `max_steps` or by the provider's output ceiling sets `ended_at`
    like any other and records **no** `failed` item: the only trace is one `unresolved`
    item under `CLOSEOUT_CHECK` (`ReviewRun._closeout`). Reading `ended_at` alone would
    therefore carry every verdict out of a review that gave up half way, which is exactly
    the run guard 1 exists to refuse, so the refusal is whole-session.

    `CLOSEOUT_CHECK` is also a checklist item id, so the check alone does not say a run was
    cut short - `report.session.was_cut_short` reads the two reasons the runner writes, and
    both sides take them from the same constants, which is why this test can name them.
    """
    package = carry_package()
    previous = previous_session(
        package,
        [
            rms_finding(package, finding_id="F-001", check=RMS_CHECK),
            rms_finding(package, finding_id="F-002", check=OTHER_RMS_CHECK),
        ],
        closeout_reason=closeout_reason,
    )

    decision = select_carry_over(package, previous, at=CARRIED_AT)

    assert decision.carried == ()
    assert decision.re_run == tuple(previous.findings)
    assert decision.total == len(previous.findings)


def test_a_failed_coverage_item_naming_the_check_blocks_only_that_check() -> None:
    package = carry_package()
    previous = previous_session(
        package,
        [
            rms_finding(package, finding_id="F-001", check=RMS_CHECK),
            rms_finding(package, finding_id="F-002", check=OTHER_RMS_CHECK),
        ],
        failed_checks=[RMS_CHECK],
    )

    assert carried_checks(package, previous) == {OTHER_RMS_CHECK}


# --- guard 2: only demonstrated and checked_within_scope ------------------------------


@pytest.mark.parametrize("status", ["demonstrated", "checked_within_scope"])
def test_a_computed_verdict_is_carried(status: str) -> None:
    package = carry_package()
    previous = previous_session(package, [rms_finding(package, status=status)])  # type: ignore[arg-type]

    assert carried_checks(package, previous) == {RMS_CHECK}


@pytest.mark.parametrize("status", ["suspected", "unresolved"])
def test_a_judgement_is_re_run_rather_than_frozen(status: str) -> None:
    """`suspected` and `unresolved` are the model's judgement, and an `unresolved` finding
    with an open evidence request is precisely what a new run might resolve."""
    package = carry_package()
    previous = previous_session(package, [rms_finding(package, status=status)])  # type: ignore[arg-type]

    assert carried_checks(package, previous) == set()


# --- guard 3: never across a disposition ----------------------------------------------


@pytest.mark.parametrize("decision", ["accepted", "rejected", "deferred"])
def test_a_disposition_blocks_carry_over(decision: str) -> None:
    """A human decision is attached: carrying it without the decision is worse than
    re-running, and carrying it with the decision has the reviewer re-assert a human's
    judgement."""
    package = carry_package()
    finding = rms_finding(package).model_copy(
        update={
            "disposition": Disposition(
                decision=decision,  # type: ignore[arg-type]
                note="reviewed by hand",
                by="engineer",
                at=datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC),
            )
        }
    )

    assert carried_checks(package, previous_session(package, [finding])) == set()


# --- guard 4: never past an exception in needs_review ---------------------------------


def store_with_exception(package: EvidencePackage, check: str, **updates: Any) -> ExceptionStore:
    """A pathless store holding one accepted exception for `check` on `COMPONENT`."""
    store = ExceptionStore()
    exception = store.accept(
        rms_finding(package, check=check),
        package,
        by="engineer",
        note="accepted for this build",
        at=datetime(2026, 9, 13, 9, 0, 0, tzinfo=UTC),
    )
    for name, value in updates.items():
        setattr(exception, name, value)
    return store


def test_an_exception_already_in_needs_review_blocks_carry_over() -> None:
    package = carry_package()
    store = store_with_exception(package, OTHER_RMS_CHECK, status="needs_review")
    previous = previous_session(package, [rms_finding(package)])

    decision = select_carry_over(package, previous, exceptions=store, at=CARRIED_AT)

    assert decision.carried == ()


def test_the_refresh_the_selector_runs_is_what_moves_an_exception_and_blocks_the_carry() -> None:
    """The exception is `active` on the way in and is bound to a configuration the package
    no longer has, so `ExceptionStore.refresh` flags it. The feature tree is untouched, so
    the key still matches: this test isolates guard 4 from guard 5."""
    package = carry_package()
    store = store_with_exception(package, OTHER_RMS_CHECK, configuration="Legacy")
    previous = previous_session(package, [rms_finding(package)])

    decision = select_carry_over(package, previous, exceptions=store, at=CARRIED_AT)

    assert [exception.status for exception in store.exceptions] == ["needs_review"]
    assert decision.carried == ()


def test_an_exception_on_other_components_does_not_block_the_carry() -> None:
    package = carry_package()
    store = store_with_exception(package, OTHER_RMS_CHECK, status="needs_review")
    store.exceptions[0].component_persist_refs = ["not-this-component"]
    previous = previous_session(package, [rms_finding(package)])

    decision = select_carry_over(package, previous, exceptions=store, at=CARRIED_AT)

    assert len(decision.carried) == 1


# --- guard 5: never across a tree or check-version change -----------------------------
#
# The key is only half of guard 5. The other half is the key the *previous* run left
# behind: a key is a statement about the package a verdict was computed over, and the only
# run holding that package is the one that computed it.


def test_finalization_leaves_a_key_on_every_carryable_finding_and_on_nothing_else() -> None:
    package = carry_package()
    session = previous_session(
        package,
        [
            rms_finding(package, finding_id="F-001"),
            rms_finding(package, finding_id="F-002", status="suspected"),
            rms_finding(package, finding_id="F-003", check="interference.static"),
            rms_finding(package, finding_id="F-004", check=INDIVIDUALLY_SUPPRESSIBLE),
        ],
        stamped=False,
    )

    stamped = stamp_carry_over_keys(session, package, efficiency=ON)

    assert stamped == 1
    assert session.findings[0].carry_over_key == carry_over_key(package, session.findings[0])
    assert [finding.carry_over_key for finding in session.findings[1:]] == [None, None, None]


def test_a_run_with_the_flag_off_leaves_no_key_and_so_no_memory_for_the_next_run() -> None:
    """What makes the two arms comparable: the off arm has nothing to carry from, not even
    on its second review."""
    package = carry_package()
    session = previous_session(package, [rms_finding(package)], stamped=False)

    assert stamp_carry_over_keys(session, package, efficiency=OFF) == 0
    assert session.findings[0].carry_over_key is None
    assert carried_checks(package, session) == set()


def test_stamping_twice_stamps_once() -> None:
    """Finalization runs on every turn and on the failure path; it must be idempotent."""
    package = carry_package()
    session = previous_session(package, [rms_finding(package)], stamped=False)

    stamp_carry_over_keys(session, package, efficiency=ON)
    first = session.findings[0].carry_over_key
    stamp_carry_over_keys(session, package, efficiency=ON)

    assert session.findings[0].carry_over_key == first


def test_a_finding_whose_components_are_gone_is_left_unstamped_rather_than_raising() -> None:
    """Finalization must not fail on the way to writing the session (rule 5)."""
    package = carry_package()
    session = previous_session(package, [rms_finding(package)], stamped=False)
    session.findings[0] = session.findings[0].model_copy(update={"component_ids": ["cmp:9999"]})

    assert stamp_carry_over_keys(session, package, efficiency=ON) == 0
    assert session.findings[0].carry_over_key is None


def test_one_mutated_feature_row_is_re_run_rather_than_carried() -> None:
    """The minimum bar (data-model.md 10.5). The previous run graded the tree as it was;
    one renamed row means the tree it graded is not the tree in front of us."""
    before = carry_package()
    after = mutated_package()
    previous = previous_session(before, [rms_finding(before)])

    assert carried_checks(before, previous) == {RMS_CHECK}
    assert carried_checks(after, previous) == set()


# --- guard 6: the cap -----------------------------------------------------------------


def test_the_cap_is_one_run_and_an_already_carried_verdict_is_re_run() -> None:
    """A finding carried for twenty consecutive runs has not been computed for twenty
    runs. The three provenance fields say which run produced a verdict, not how many times
    it has been reused, so the bound expressible without inventing a fourth field is that
    a verdict travels one run from the one that computed it."""
    assert MAX_CARRY_OVER_RUNS == 1
    package = carry_package()
    already = rms_finding(package).model_copy(
        update={
            "carried_over_from": PREVIOUS_SESSION_ID,
            "carried_over_at": CARRIED_AT,
            "carry_over_key": carry_over_key(package, rms_finding(package)),
        }
    )

    assert carried_checks(package, previous_session(package, [already])) == set()


# --- scope: rms.* only, and not the one rule the fingerprint does not cover -----------


def test_a_finding_outside_the_rms_family_is_never_carried() -> None:
    package = carry_package()
    previous = previous_session(package, [rms_finding(package, check="interference.static")])

    assert carried_checks(package, previous) == set()


def test_individually_suppressible_is_excluded_because_the_fingerprint_misses_its_input() -> None:
    """It reads `rms_suppress_test` (`ir/models.py`), and that array is in neither
    fingerprint, so a carried verdict for it would be a claim nothing checked."""
    package = carry_package()
    previous = previous_session(
        package, [rms_finding(package, check=INDIVIDUALLY_SUPPRESSIBLE)]
    )

    assert carried_checks(package, previous) == set()


# --- a carry is never silent ----------------------------------------------------------


def run_context(package: EvidencePackage, tmp_path: Any) -> tuple[ToolContext, list[Any]]:
    """A context over `package` whose event stream is collected into a list."""
    events: list[Any] = []
    context = build_context(
        LoadedPackage(package=package, base_dir=tmp_path),
        emit=lambda event_type, body: events.append((event_type, body)),
    )
    return context, events


def written_previous(package: EvidencePackage, findings: list[Finding], tmp_path: Any) -> Any:
    path = tmp_path / "previous" / "session.json"
    save_session(previous_session(package, findings), path)
    return path


def test_a_carried_finding_is_marked_and_its_status_is_untouched(tmp_path: Any) -> None:
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, _ = run_context(package, tmp_path)

    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)

    (carried,) = context.require_session().findings
    assert carried.carried_over_from == PREVIOUS_SESSION_ID
    assert carried.carried_over_at == CARRIED_AT
    assert carried.carry_over_key == carry_over_key(package, carried)
    assert carried.status == "demonstrated"


def test_a_carried_finding_takes_an_id_from_this_run_so_ids_stay_unique(tmp_path: Any) -> None:
    package = carry_package()
    previous_path = written_previous(
        package,
        [
            rms_finding(package, finding_id="F-007"),
            rms_finding(package, finding_id="F-008", check=OTHER_RMS_CHECK),
        ],
        tmp_path,
    )
    context, _ = run_context(package, tmp_path)

    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)

    assert [finding.id for finding in context.require_session().findings] == ["F-001", "F-002"]
    assert next(context.finding_ids) == "F-003"


def test_a_carried_finding_writes_a_checked_coverage_item_saying_so(tmp_path: Any) -> None:
    """The `checked` bucket, not a sixth one: a new bucket would touch the schema, the
    report renderer and the scorecard aggregate to carry what the finding already says."""
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, _ = run_context(package, tmp_path)

    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)

    coverage = context.require_session().coverage
    (item,) = coverage.checked
    assert item.check == RMS_CHECK
    assert item.reason.startswith(CARRIED_REASON_PREFIX)
    assert str(PREVIOUS_SESSION_ID) in item.reason
    assert item.scope.component_ids == [COMPONENT]
    assert coverage.skipped == coverage.unresolved == coverage.failed == []


def test_a_carry_reaches_the_event_stream_as_it_reaches_the_session(tmp_path: Any) -> None:
    """One writer, three readers: `session.json`, the report and `events.jsonl` cannot
    disagree because all three come from `ToolContext.record_*`."""
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, events = run_context(package, tmp_path)

    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)

    types = [event_type for event_type, _ in events]
    assert types == ["finding", "coverage"]
    finding_body = events[0][1]
    assert finding_body["carried_over_from"] == str(PREVIOUS_SESSION_ID)
    assert events[1][1]["bucket"] == "checked"


def test_the_flag_off_carries_nothing_even_with_a_previous_session_in_hand(
    tmp_path: Any,
) -> None:
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, events = run_context(package, tmp_path)

    decision = carry_over_findings(
        context, previous_session=previous_path, efficiency=OFF, at=CARRIED_AT
    )

    assert decision.carried == ()
    assert decision.re_run == ()
    assert context.require_session().findings == []
    assert context.require_session().coverage.checked == []
    assert events == []


def test_a_computed_finding_serializes_without_the_three_fields_the_lever_added() -> None:
    """SC-007, and the reason the feature 001/002/003 goldens are unchanged by lever 11a.

    All three fields are optional and absent from `required` in
    `review-session.schema.json`, so a null and an absent key state the same fact - but the
    null is three extra members in every finding of every `tools/registry.py` payload the
    model is charged for, on the **off** arm of an efficiency feature, and three more in
    every `finding` line of `events.jsonl`. `ManifestEntry`'s two schema 1.3.0 additions
    (lever 9) ride along in `provenance` and are dropped by the same rule
    (`ir.models.omit_when_null`).
    """
    package = carry_package()

    payload = rms_finding(package).model_dump(mode="json")

    assert {"carried_over_from", "carried_over_at", "carry_over_key"} & set(payload) == set()
    assert all(
        {"file_modified_utc", "file_size_bytes"} & set(entry) == set()
        for entry in payload["provenance"]
    )


def test_a_carried_finding_serializes_with_them(tmp_path: Any) -> None:
    """The other half: what is dropped is the null, never the fact."""
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, _ = run_context(package, tmp_path)

    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)

    (carried,) = context.require_session().findings
    payload = carried.model_dump(mode="json")
    assert payload["carried_over_from"] == str(PREVIOUS_SESSION_ID)
    assert payload["carried_over_at"] is not None
    assert payload["carry_over_key"] == carry_over_key(package, carried)


def test_the_flag_on_with_no_previous_session_carries_nothing(tmp_path: Any) -> None:
    package = carry_package()
    context, events = run_context(package, tmp_path)

    decision = carry_over_findings(context, previous_session=None, efficiency=ON, at=CARRIED_AT)

    assert decision.carried == ()
    assert events == []


def test_a_previous_session_path_that_is_not_there_raises_rather_than_carrying_nothing(
    tmp_path: Any,
) -> None:
    """Silently carrying nothing would make an on-arm secretly an off-arm, and the A/B
    row would then compare a lever against itself."""
    package = carry_package()
    context, _ = run_context(package, tmp_path)

    with pytest.raises(FileNotFoundError):
        carry_over_findings(
            context,
            previous_session=tmp_path / "gone" / "session.json",
            efficiency=ON,
            at=CARRIED_AT,
        )


def test_a_written_session_with_a_carried_finding_validates_against_the_contract(
    tmp_path: Any,
) -> None:
    """The three fields are additive: in `properties` of `review-session.schema.json` and
    out of `required`, the pattern `provider_info` and `retry_of` set, so a feature 001
    session with none of them stays valid and this one is valid too."""
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, events = run_context(package, tmp_path)
    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)
    session = context.require_session()
    session.ended_at = CARRIED_AT

    written = json.loads(save_session(session, tmp_path / "out" / "session.json").read_bytes())
    contract_validator("review-session.schema.json").validate(written)
    contract_validator("chat-events.schema.json").validate(
        {"seq": 1, "at": CARRIED_AT.isoformat(), "type": "finding", "body": events[0][1]}
    )


# --- the report, the third reader -----------------------------------------------------


def carried_report(tmp_path: Any) -> str:
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, _ = run_context(package, tmp_path)
    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)
    return render_report(context.require_session(), package)


def test_the_finding_heading_names_the_originating_run(tmp_path: Any) -> None:
    """The heading's title is the one a person reads, so the part is named rather than
    numbered (feature 009 decision 2A, research R2.28); the run it came from follows it."""
    report = carried_report(tmp_path)
    part = component_names(carry_package())[COMPONENT]
    assert part.strip() and part != COMPONENT

    heading = (
        f"#### F-001: {RMS_CHECK} on {part} (carried over from session {PREVIOUS_SESSION_ID})"
    )
    assert heading in report


def test_the_coverage_section_states_carried_against_computed(tmp_path: Any) -> None:
    """So an engineer can see at a glance which part of the report was not computed today
    (FR-102, Principle VI)."""
    report = carried_report(tmp_path)

    assert (
        "- Findings carried over from an earlier run: 1; computed in this run: 0."
    ) in report


def test_a_report_with_nothing_carried_says_nothing_about_carrying(tmp_path: Any) -> None:
    """The lever off renders the report this build has always rendered: the heading suffix
    and the coverage line appear only when there is something to say."""
    package = carry_package()
    context, _ = run_context(package, tmp_path)
    context.record_finding(rms_finding(package))

    report = render_report(context.require_session(), package)

    assert "carried over" not in report
    assert "#### F-001: " in report


# --- the two halves wired into the run ------------------------------------------------


def review(
    tmp_path: Any, out: str, script: list[ScriptedTurn] | None = None, **options: Any
) -> ReviewSession:
    """One scripted review of `carry_package()`, written under `tmp_path / out`."""
    package_dir = tmp_path / "package"
    if not package_dir.exists():
        save_package(carry_package(), package_dir)
    return run_review(
        package_dir,
        tmp_path / out,
        provider=FakeProvider(
            script=script if script is not None else [ScriptedTurn(text="done")],
            model="fake-scripted",
        ),
        **options,
    )


def stamped_previous(session: ReviewSession, tmp_path: Any, out: str) -> Any:
    """`session` with one carryable finding stamped and written back to its run folder."""
    session.findings.append(rms_finding(carry_package()))
    stamp_carry_over_keys(session, carry_package(), efficiency=ON)
    return save_session(session, tmp_path / out / "session.json")


def test_a_review_stamps_keys_and_the_next_one_carries_what_did_not_move(
    tmp_path: Any,
) -> None:
    """The whole lever end to end through `start_review` and `finalize_session`: the first
    review leaves the keys, the second carries the verdict they justify."""
    first = review(tmp_path, "one", efficiency=ON)
    previous_path = stamped_previous(first, tmp_path, "one")

    second = review(tmp_path, "two", efficiency=ON, previous_session=previous_path)

    (carried,) = second.findings
    assert carried.carried_over_from == first.session_id
    assert second.coverage.checked[0].reason.startswith(CARRIED_REASON_PREFIX)


def test_a_previous_run_the_runner_itself_cut_short_carries_nothing(tmp_path: Any) -> None:
    """Guard 1 against the runner rather than against a hand-built session: the first
    review runs out of steps mid-turn, which `ReviewRun._closeout` records and nothing else
    does - `ended_at` is set, no coverage `failed`, and the findings it did reach are still
    there and still stamped. Every one of them is re-run.
    """
    first = review(
        tmp_path,
        "one",
        script=[
            ScriptedTurn(
                text="out of steps",
                tool_calls=(ScriptedToolCall("list_gaps"), ScriptedToolCall("list_gaps")),
            )
        ],
        efficiency=ON,
        max_steps=1,
    )
    assert first.ended_at is not None
    assert first.coverage.failed == []
    previous_path = stamped_previous(first, tmp_path, "one")
    assert first.findings[0].carry_over_key is not None

    second = review(tmp_path, "two", efficiency=ON, previous_session=previous_path)

    assert second.findings == []
    assert second.coverage.checked == []


def test_the_same_two_reviews_with_the_flag_off_carry_nothing(tmp_path: Any) -> None:
    first = review(tmp_path, "one", efficiency=OFF)
    first.findings.append(rms_finding(carry_package()))
    stamp_carry_over_keys(first, carry_package(), efficiency=OFF)
    save_session(first, tmp_path / "one" / "session.json")

    second = review(
        tmp_path, "two", efficiency=OFF, previous_session=tmp_path / "one" / "session.json"
    )

    assert second.findings == []
    assert first.findings[0].carry_over_key is None


# --- the scorecard reads a session with carried findings ------------------------------


def test_the_scorecard_scores_a_carried_finding_exactly_as_a_computed_one(
    tmp_path: Any,
) -> None:
    """Why `Finding.status` is not touched: the scorecard matches on check, components and
    status, so a carried `demonstrated` finding must still match its known defect. A sixth
    status, or a `carried` status, would have moved it into the missed column."""
    package = carry_package()
    previous_path = written_previous(package, [rms_finding(package)], tmp_path)
    context, _ = run_context(package, tmp_path)
    carry_over_findings(context, previous_session=previous_path, efficiency=ON, at=CARRIED_AT)
    session = context.require_session()
    session.started_at = CARRIED_AT
    session.ended_at = datetime(2026, 9, 16, 9, 12, 0, tzinfo=UTC)

    run_dir = tmp_path / "run"
    save_session(session, run_dir / "pkg-a" / "session.json")
    keys_dir = tmp_path / "answer_keys"
    keys_dir.mkdir()
    (keys_dir / "pkg-a.json").write_text(
        json.dumps(
            {
                "package_id": "pkg-a",
                "known_defects": [
                    {
                        "id": "KD-1",
                        "check": RMS_CHECK,
                        "component_ids": [COMPONENT],
                        "description": "the sketch is not fully defined",
                    }
                ],
                "correct_conditions": [],
            }
        ),
        encoding="utf-8",
    )
    benchmark_set = BenchmarkSet(
        name="carry-over",
        packages=[BenchmarkPackageRef(package_id="pkg-a", path=tmp_path, held_out=True)],
    )

    (score,) = score_run(run_dir, keys_dir, benchmark_set).per_package

    assert score.matched_defect_ids == ["KD-1"]
    assert score.missed_defect_ids == []
    assert score.carried_findings == 1
