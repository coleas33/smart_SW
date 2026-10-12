"""`check_threads`, the argument-free thread pitch tool (feature 010 amendment 2026-10-08, T119).

`contracts/fasteners.md` sections 8.4 and 8.7 are normative; research R2.26 records the owner's
decisions 50A to 53A, 57A, 58A and 63A and the defaults D10 and D14 this module pins. The tool
is a thin wrapper over `checks/thread_pitch.run_thread_checks`: it takes no argument, reads the
part roles the review attached, and is the fourth name in `CODE_FIRST_CHECKS`, so the pre-run
calls it after `check_hygiene` at no model round and lever 13 withholds it once it completed.

Its rows restate, never add (D14): a call withdraws every `thread.pitch` row before it records
its own, because the answer to the part-roles question restates the check through the dispatch
(D10, `runner.ROLES_RESTATED`) - a real call the re-call guard does not answer - and appended
rows would count a newly bought part's tapped holes twice. Its two finding ids are needs
judgement and `interface`, land in the Review tab's Decide group and the Fasteners type group,
and move no goal line (63A): the Fasteners goal owns the two ids by name, in its `items`, and the
coverage-only `thread.pitch` belongs to no goal. No checklist item closes on them.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.checklist import load_checklist
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.providers.schema import tool_spec
from swreview.agent.settings import EfficiencySettings
from swreview.checks.part_roles import classify_parts
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.thread_pitch import (
    CHECK_FINE_PITCH,
    CHECK_NONSTANDARD_PITCH,
    COVERAGE_CHECK,
    DRAWINGS_LIMIT,
    NOTHING_AT_ALL,
    ThreadChecks,
    run_thread_checks,
)
from swreview.findings import Finding
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import prerun_checks, repeat_key
from swreview.report.attention import load_policy
from swreview.report.session import CoverageItem, CoverageScope, ReviewSession
from swreview.report.summary import GoalLine, goal_lines, goal_of, load_words, review_ranking
from swreview.tools import checks_mechanical
from swreview.tools.checks_mechanical import attach_part_roles, review_roles
from swreview.tools.context import ToolContext, build_context, context_for
from swreview.tools.registry import ToolDispatch, ToolRegistry, check_tools
from tests.support.attention import CoverageRow, CoverageSpec
from tests.support.coverage_stream import Event, held, mirror
from tests.support.mechanical import PackageBuilder
from tests.support.prerun import ON
from tests.support.roles_review import PIN_STEM, PLATE_STEM, ROOT_STEM, write_profile
from tests.unit.test_attention import disposition, spec
from tests.unit.test_review_summary import session_of
from tests.unit.test_thread_pitch import SUPPLIER, examples_package, roles_package, tapped

TOOL = "check_threads"
REVIEWER = Path(__file__).resolve().parents[1].parent
PROFILE_A = REVIEWER / "tests" / "fixtures" / "standards" / "profile-a.yaml"
GOLDEN = REVIEWER / "tests" / "golden" / "fixtures"
MECHANICAL = REVIEWER / "tests" / "fixtures" / "mechanical"
BUCKETS: tuple[str, ...] = ("checked", "skipped", "unresolved", "failed", "out_of_scope")
RESTATED_BUCKETS: list[str] = ["checked", "skipped", "unresolved"]
"""The buckets a call withdraws `thread.pitch` rows from, in the order section 8.7 names them."""

Events = list[Event]


def check_threads() -> Any:
    """The tool, imported where it is used, so this module's red run names what is missing
    rather than failing at collection."""
    return checks_mechanical.check_threads  # type: ignore[attr-defined]


def golden(name: str) -> EvidencePackage:
    """One of T118's two golden packages: the flags, and every row that is not a finding."""
    return load_package(GOLDEN / name).package


def dispatch(context: ToolContext) -> ToolDispatch:
    return ToolRegistry().dispatch(context)


def listening(package: EvidencePackage) -> tuple[ToolContext, Events]:
    """A context over `package` whose events are kept, in order."""
    events: Events = []
    context = context_for(package)
    context.emit = lambda kind, body: events.append((kind, dict(body)))
    return context, events


def thread_rows(session: ReviewSession) -> dict[str, list[CoverageItem]]:
    """Every `thread.pitch` row the session holds, by bucket."""
    return {
        bucket: [item for item in getattr(session.coverage, bucket) if item.check == COVERAGE_CHECK]
        for bucket in BUCKETS
    }


def rows_of(checks: ThreadChecks) -> dict[str, list[CoverageItem]]:
    """The rows `run_thread_checks` returns, by the bucket section 8.6 puts them in."""
    return {
        "checked": list(checks.checked),
        "skipped": list(checks.skipped),
        "unresolved": list(checks.unresolved),
        "failed": [],
        "out_of_scope": [],
    }


def thread_findings(session: ReviewSession) -> list[Finding]:
    return [
        finding
        for finding in session.findings
        if finding.check in (CHECK_FINE_PITCH, CHECK_NONSTANDARD_PITCH)
    ]


@pytest.fixture(scope="module")
def profile() -> StandardsProfile:
    return load_profile(PROFILE_A)


# --- the tool's shape -----------------------------------------------------------------------


def test_the_tool_takes_no_argument_and_is_a_check_tool() -> None:
    assert inspect.signature(check_threads()).parameters == {}
    assert check_threads() in check_tools()


def test_it_is_the_fourth_code_first_check_after_check_hygiene() -> None:
    assert checks_mechanical.CODE_FIRST_CHECKS == (
        "check_joints",
        "check_mass_material",
        "check_hygiene",
        "check_threads",
    )
    assert TOOL in checks_mechanical.__all__


def test_the_re_call_guard_keys_it_by_its_name_alone() -> None:
    assert repeat_key(TOOL, {}) == (TOOL,)


def test_its_description_is_under_the_160_character_cap() -> None:
    assert len(tool_spec(check_threads()).description) < 160


def test_through_the_registry_it_is_one_real_step_and_refuses_an_argument() -> None:
    context = context_for(golden("thread-pitch-flags"))
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}

    assert tools[TOOL].call({}).is_error is False
    assert [step.tool for step in context.require_session().steps] == [TOOL]
    assert tools[TOOL].call({"document_id": "doc:0002"}).is_error is True


# --- what it records: T116's cases, through the dispatch -------------------------------------


@pytest.mark.parametrize("name", ["thread-pitch-flags", "thread-pitch-not-checked"])
def test_it_records_the_findings_and_the_rows_run_thread_checks_gives(name: str) -> None:
    """Each finding bound to its documents and components, each row in its bucket."""
    package = golden(name)
    checks = run_thread_checks(package)
    context = context_for(package)

    payload = dispatch(context).call(TOOL, {}).payload

    session = context.require_session()
    findings = thread_findings(session)
    assert len(findings) == len(session.findings) == len(checks.findings)
    for finding, item in zip(findings, checks.findings, strict=True):
        result = item.result
        assert (finding.check, finding.status, finding.severity) == (
            result.check,
            result.status,
            result.severity,
        )
        assert (finding.observed, finding.requirement, finding.recommended_action) == (
            result.observed,
            result.requirement,
            result.recommended_action,
        )
        assert finding.inputs == list(result.inputs)
        assert finding.coverage_limits == list(result.coverage_limits)
        assert finding.calculation is None
        assert finding.component_ids == list(item.component_ids)
        assert [entry.document_id for entry in finding.provenance] == list(item.documents)
        assert finding.tool_result_ids == [0]
    assert thread_rows(session) == rows_of(checks)
    assert payload == {
        "status": "recorded",
        "findings": len(findings),
        "by_status": {"suspected": len(findings)} if findings else {},
        "finding_ids": [finding.id for finding in findings],
        "coverage": {
            "checked": len(checks.checked),
            "skipped": len(checks.skipped),
            "unresolved": len(checks.unresolved),
        },
        "threads": checks.threads,
        "coarse": checks.coarse,
    }


def test_the_two_goldens_between_them_reach_every_bucket_and_both_ids() -> None:
    """A sanity line on the parametrized test above, so it cannot pass over empty packages."""
    flags = run_thread_checks(golden("thread-pitch-flags"))
    rows = run_thread_checks(golden("thread-pitch-not-checked"))

    assert {item.result.check for item in flags.findings} == {
        CHECK_FINE_PITCH,
        CHECK_NONSTANDARD_PITCH,
    }
    assert rows.checked and rows.skipped and rows.unresolved
    assert (flags.threads, flags.coarse) != (0, 0)


def test_it_reads_the_roles_attached_and_with_none_grades_every_part(
    profile: StandardsProfile,
) -> None:
    package, ids = roles_package()
    roles = classify_parts(package, profile)
    with_roles, without = context_for(package), context_for(package)
    attach_part_roles(with_roles, roles)

    for context in (with_roles, without):
        dispatch(context).call(TOOL, {})

    def flagged_parts(context: ToolContext) -> set[str]:
        return {
            entry.document_id
            for finding in context.require_session().findings
            for entry in finding.provenance
        }

    assert thread_rows(with_roles.require_session()) == rows_of(run_thread_checks(package, roles))
    assert thread_rows(without.require_session()) == rows_of(run_thread_checks(package))
    assert ids["bought"] not in flagged_parts(with_roles)
    assert ids["bought"] in flagged_parts(without)
    assert ids["bought_screw"] in flagged_parts(with_roles), "a bought fastener is still flagged"


# --- its rows restate, never add (D14) --------------------------------------------------------


def test_a_second_call_leaves_one_set_of_rows_the_first_withdrawn_in_one_event() -> None:
    context, events = listening(golden("thread-pitch-not-checked"))
    tools = dispatch(context)
    tools.call(TOOL, {})
    first = thread_rows(context.require_session())
    assert not [kind for kind, _ in events if kind == "coverage.withdrawn"]
    mark = len(events)

    tools.call(TOOL, {})

    assert thread_rows(context.require_session()) == first
    assert [body for kind, body in events[mark:] if kind == "coverage.withdrawn"] == [
        {"checks": [COVERAGE_CHECK], "buckets": RESTATED_BUCKETS}
    ]
    assert mirror(events) == held(context.require_session())


def test_a_second_call_leaves_every_other_checks_rows_alone() -> None:
    context = context_for(golden("thread-pitch-not-checked"))
    other = CoverageItem(
        check="fasteners", scope=CoverageScope(), reason="the model's own row", error=None
    )
    context.record_coverage("skipped", other)
    tools = dispatch(context)

    tools.call(TOOL, {})
    tools.call(TOOL, {})

    assert other in context.require_session().coverage.skipped


# --- the part-roles answer restates it (D10), and a restated finding keeps its id (57A, 58A) --

FASTENER_STEM = "FICT-KALO-SCREW"
"""A second part no rule decides, holding the `M10x1.25` fastener row. Fictional."""

PIN_THREADS: tuple[tuple[str, str], ...] = (
    ("Tapped Hole1", "M8x1"),
    ("Tapped Hole2", "M6x0.75"),
    ("Tapped Hole3", "M5x0.8"),
)


def threads_review(tmp_path: Path, events: Events) -> runner.ReviewRun:
    """`roles_review`'s shape - an assembly, the custom plate, the unclear pin and the version
    3 profile - with the pin's three tapped holes, `M8x1`, `M6x0.75` and a coarse `M5x0.8`, and
    a second unclear part carrying an `M10x1.25` fastener row; checks first on, so the pre-run
    runs `check_threads` and the answer's restate restates it. The pin has one instance, so
    its coarse hole counts once."""
    builder = PackageBuilder(design_stem=ROOT_STEM)
    builder.component(builder.document(PLATE_STEM, "part"))
    pin = builder.component(builder.document(PIN_STEM, "part"))
    for name, thread in PIN_THREADS:
        tapped(builder, pin, thread, name)
    screw = builder.component(builder.document(FASTENER_STEM, "part"))
    builder.fastener_row(screw, designation="M10x1.25")
    folder = tmp_path / "run-0001"
    builder.build().write(folder)
    run = runner.start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[ScriptedTurn(text="graded"), ScriptedTurn(text="resumed")],
            model="fake-scripted",
        ),
        standards_profile=write_profile(tmp_path),
        callbacks=[lambda event: events.append((event.type, dict(event.body)))],
        efficiency=EfficiencySettings(prerun_checks=True),
    )
    run.start()
    return run


def component_of(run: runner.ReviewRun, stem: str) -> str:
    [component] = [
        item.id
        for item in run.context.ir.components
        if any(
            document.document_id == item.document_id and document.file_name.startswith(stem)
            for document in run.context.ir.documents
        )
    ]
    return component


def fine_on(run: runner.ReviewRun, stem: str) -> list[Finding]:
    """The `thread.fine_pitch` findings whose components are `stem`'s one instance."""
    component = component_of(run, stem)
    return [
        finding
        for finding in run.session.findings
        if finding.check == CHECK_FINE_PITCH and finding.component_ids == [component]
    ]


def one_set(run: runner.ReviewRun) -> dict[str, list[CoverageItem]]:
    """The rows the check gives now, with the roles the review holds now: what the session must
    hold, and nothing beside it."""
    return rows_of(run_thread_checks(run.context.ir, review_roles(run.context)))


def withdrawn(events: Events) -> list[dict[str, Any]]:
    return [body for kind, body in events if kind == "finding.withdrawn"]


def test_the_review_starts_with_one_pin_finding_listing_both_designations(
    tmp_path: Path,
) -> None:
    events: Events = []
    run = threads_review(tmp_path, events)

    roles = review_roles(run.context)
    assert roles is not None
    assert {
        document.file_name: roles.by_document[document.document_id].role
        for document in run.context.ir.documents
        if document.kind == "part"
    } == {
        f"{PLATE_STEM}.SLDPRT": "custom",
        f"{PIN_STEM}.SLDPRT": "unclear",
        f"{FASTENER_STEM}.SLDPRT": "unclear",
    }
    [pin] = fine_on(run, PIN_STEM)
    assert pin.observed.startswith("M8x1 is fine pitch (M8's coarse pitch is 1.25) on 1 tapped")
    assert "; M6x0.75 is fine pitch (M6's coarse pitch is 1) on 1 tapped hole" in pin.observed
    [fastener] = fine_on(run, FASTENER_STEM)
    assert fastener.coverage_limits == [DRAWINGS_LIMIT], "a fastener's finding has no note (D21)"
    assert TOOL in [step.tool for step in run.session.steps]
    assert thread_rows(run.session) == one_set(run)


def test_all_bought_withdraws_the_pins_finding_and_keeps_the_fasteners(tmp_path: Path) -> None:
    events: Events = []
    run = threads_review(tmp_path, events)
    [pin] = fine_on(run, PIN_STEM)
    [fastener] = fine_on(run, FASTENER_STEM)
    before = len(run.session.steps)
    mark = len(events)

    run.answer_evidence_batch([("ER-001", "All bought")])

    restated = [step.tool for step in run.session.steps[before:]]
    assert restated.index(TOOL) == restated.index("check_hygiene") + 1
    assert fine_on(run, PIN_STEM) == []
    # The other restated checks withdraw the pin's own findings beside it; this one's once.
    reason = runner.BOUGHT_WITHDRAWAL.format(request_id="ER-001")
    assert withdrawn(events[mark:]).count({"finding_id": pin.id, "reason": reason}) == 1
    assert fastener.id not in [body["finding_id"] for body in withdrawn(events[mark:])]
    [row] = [
        item
        for item in run.session.coverage.skipped
        if item.check == "coverage.prerun.bought_parts"
    ]
    assert pin.id in row.reason
    assert [finding.id for finding in fine_on(run, FASTENER_STEM)] == [fastener.id]


def test_all_bought_leaves_one_set_of_rows_the_bought_row_listing_the_pins_three_holes(
    tmp_path: Path,
) -> None:
    events: Events = []
    run = threads_review(tmp_path, events)
    holes = [hole.id for hole in run.context.ir.holes]

    run.answer_evidence_batch([("ER-001", "All bought")])

    rows = thread_rows(run.session)
    assert rows == one_set(run)
    assert rows["checked"] == [], "no checked row counts the pin's M5x0.8 hole"
    assert [item.reason for item in rows["skipped"]] == [
        f"3 threads in bought parts were not checked for pitch: {PIN_STEM}.SLDPRT "
        f"({', '.join(holes)})"
    ]


def test_none_bought_keeps_the_pins_finding_its_id_and_its_accepted_disposition(
    tmp_path: Path,
) -> None:
    from swreview.chat.sessions import record_disposition

    events: Events = []
    run = threads_review(tmp_path, events)
    [pin] = fine_on(run, PIN_STEM)
    note = review_roles(run.context).note_for(pin.provenance[0].document_id)  # type: ignore[union-attr]
    assert note is not None and note in pin.coverage_limits
    record_disposition(
        run, pin.id, decision="accepted", note="the fine pitch is meant", by="a.engineer"
    )
    [accepted] = fine_on(run, PIN_STEM)
    assert accepted.disposition is not None
    mark = len(events)

    run.answer_evidence_batch([("ER-001", "None bought")])

    [kept] = fine_on(run, PIN_STEM)
    assert kept.id == pin.id
    assert kept.observed == pin.observed, "both designations, one finding (57A)"
    assert kept.disposition == accepted.disposition, "the engineer's Accept stands (58A)"
    assert kept.coverage_limits == [limit for limit in pin.coverage_limits if limit != note]
    assert withdrawn(events[mark:]) == []


def test_none_bought_leaves_one_checked_row_counting_the_coarse_hole_once(
    tmp_path: Path,
) -> None:
    events: Events = []
    run = threads_review(tmp_path, events)
    coarse = run.context.ir.holes[2].id

    run.answer_evidence_batch([("ER-001", "None bought")])

    rows = thread_rows(run.session)
    assert rows == one_set(run)
    assert [item.reason for item in rows["checked"]] == [
        f"1 thread has the coarse pitch: M5x0.8 ({coarse})"
    ]


def test_the_part_roles_answer_restates_it_after_check_hygiene() -> None:
    restated = runner.ROLES_RESTATED
    assert restated.index(TOOL) == restated.index("check_hygiene") + 1


# --- checks first: the pre-run calls it after check_hygiene ----------------------------------


def test_with_lever_5_on_the_small_mechanical_fixture_s_pre_run_calls_it_after_hygiene() -> None:
    context = build_context(load_package(MECHANICAL / "small-assembly"))

    result = prerun_checks(context, dispatch(context), efficiency=ON)

    assert result is not None
    tools = [call.tool for call in result.calls]
    assert tools.index(TOOL) == tools.index("check_hygiene") + 1
    [step] = [step for step in context.require_session().steps if step.tool == TOOL]
    assert (step.status, step.error) == ("ok", None)


# --- no checklist item closes on a thread finding --------------------------------------------


def test_a_thread_finding_closes_no_checklist_item() -> None:
    context = context_for(examples_package())
    session = context.require_session()
    before = load_checklist().buckets(session)

    dispatch(context).call(TOOL, {})

    assert thread_findings(session), "the examples package gives thread findings"
    assert load_checklist().buckets(session) == before
    [fasteners] = [item for item in before if item["id"] == "fasteners"]
    assert fasteners["bucket"] == "open"


# --- the attention policy, the goals and the groups (section 8.4, 63A) ------------------------


@pytest.mark.parametrize("check", [CHECK_FINE_PITCH, CHECK_NONSTANDARD_PITCH])
def test_both_ids_are_interface_and_need_the_engineer_s_judgement(check: str) -> None:
    policy = load_policy()

    assert policy.classes[check] == "interface"
    assert policy.needs_judgement_of(check)


@pytest.mark.parametrize("check", [CHECK_FINE_PITCH, CHECK_NONSTANDARD_PITCH])
def test_the_fasteners_goal_owns_both_ids_by_its_items(check: str) -> None:
    goal = goal_of(check, load_words().goals)

    assert goal is not None and goal.id == "fasteners"
    assert check in goal.items


def test_the_thread_pitch_rows_belong_to_no_goal() -> None:
    goals = load_words().goals

    assert goal_of(COVERAGE_CHECK, goals) is None
    assert not [goal.id for goal in goals if any(p.startswith("thread") for p in goal.prefixes)]


def test_an_undecided_thread_finding_is_in_decide_and_in_the_fasteners_type_group() -> None:
    package = examples_package()
    context = context_for(package)
    dispatch(context).call(TOOL, {})
    session = context.require_session()
    findings = thread_findings(session)
    assert findings and all(finding.disposition is None for finding in findings)

    ranking = review_ranking(session, package)

    counts = {group.kind: group.count for group in ranking.summary.groups}
    assert counts["decide"] == len(findings)
    assert (counts["fix"], counts["verify"]) == (0, 0)
    [fasteners] = [group for group in ranking.groups.groups if group.id == "fasteners"]
    assert sorted(row.finding_id for row in fasteners.rows) == sorted(f.id for f in findings)


# --- no Fasteners goal line moves (63A) --------------------------------------------------------


Rows = dict[str, list[CoverageRow]]
"""Coverage rows by bucket, the buckets not named empty."""


def fasteners_line(name: str, specs: Sequence[Any], rows: Rows) -> GoalLine:
    """The Fasteners goal line of a finished session over `specs` and `rows`."""
    session = session_of(name, list(specs), CoverageSpec(**rows))  # type: ignore[arg-type]
    [line] = [one for one in goal_lines(session, load_words()) if one.goal == "fasteners"]
    return line


def as_row(item: CoverageItem) -> CoverageRow:
    return CoverageRow(
        check=item.check,
        reason=item.reason,
        component_ids=tuple(item.scope.component_ids),
        document_ids=tuple(item.scope.document_ids),
    )


def thread_row(package: EvidencePackage, bucket: str, roles: Any = None) -> CoverageRow:
    """The one row `run_thread_checks` writes in `bucket` over `package`, as a session row."""
    [item] = rows_of(run_thread_checks(package, roles))[bucket]
    return as_row(item)


def nothing_row() -> CoverageRow:
    row = thread_row(PackageBuilder(design_stem="FICT-KALO-0000").build().package, "skipped")
    assert row.reason == NOTHING_AT_ALL
    return row


def bought_row(profile: StandardsProfile) -> CoverageRow:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    bought = builder.component(builder.document("FICT-VEN-0001", "part", properties=SUPPLIER))
    tapped(builder, bought, "M8x1")
    package = builder.build().package
    row = thread_row(package, "skipped", classify_parts(package, profile))
    assert " in bought parts " in row.reason
    return row


def checked_row() -> CoverageRow:
    builder = PackageBuilder(design_stem="FICT-KALO-0000")
    plate = builder.component(builder.document("PLATE_FICT", "part"))
    tapped(builder, plate, "M8x1.25")
    return thread_row(builder.build().package, "checked")


FASTENERS_OUT_OF_SCOPE = CoverageRow(
    check="fasteners", reason="The design holds no fastener joint, so this item is out of scope."
)
UNRESOLVED_RULE_ROWS = (
    CoverageRow(check="fastener.engagement", reason="The tapped depth of hol:0001 was not read."),
    CoverageRow(check="fastener.bottoming", reason="The screw length of cmp:0002 was not read."),
)


def assert_unmoved(name: str, base: Rows, pitch_rows: Rows) -> GoalLine:
    """The Fasteners line of `base` with `pitch_rows` added equals, field by field, the line
    of `base` alone: the same session without its `thread.pitch` rows."""
    without = fasteners_line(f"{name}-without", [], base)
    added = {
        bucket: [*base.get(bucket, []), *pitch_rows.get(bucket, [])]
        for bucket in {*base, *pitch_rows}
    }
    with_rows = fasteners_line(f"{name}-with", [], added)
    assert with_rows.model_dump() == without.model_dump()
    return with_rows


def test_a_thread_less_review_stays_not_applicable() -> None:
    line = assert_unmoved(
        "thread-less", {"out_of_scope": [FASTENERS_OUT_OF_SCOPE]}, {"skipped": [nothing_row()]}
    )
    assert (line.state, line.reason) == ("not_applicable", "out of scope")


def test_a_bought_only_review_stays_not_applicable(profile: StandardsProfile) -> None:
    line = assert_unmoved(
        "bought-only",
        {"out_of_scope": [FASTENERS_OUT_OF_SCOPE]},
        {"skipped": [bought_row(profile)]},
    )
    assert (line.state, line.reason) == ("not_applicable", "out of scope")


def test_a_joint_less_review_with_coarse_holes_stays_not_applicable() -> None:
    line = assert_unmoved(
        "joint-less", {"out_of_scope": [FASTENERS_OUT_OF_SCOPE]}, {"checked": [checked_row()]}
    )
    assert (line.state, line.reason) == ("not_applicable", "out of scope")


def test_unresolved_fastener_rule_rows_beside_a_checked_thread_row_stay_not_reached() -> None:
    line = assert_unmoved(
        "rule-rows", {"unresolved": list(UNRESOLVED_RULE_ROWS)}, {"checked": [checked_row()]}
    )
    assert (line.state, line.reason) == ("not_reached", "evidence missing")


@pytest.mark.parametrize("decision", [None, "accepted"])
def test_a_thread_finding_accepted_or_not_makes_the_line_issues(decision: str | None) -> None:
    """The goal line reads the finding's status, never its disposition."""
    finding = spec(
        CHECK_FINE_PITCH,
        status="suspected",
        disposition=None if decision is None else disposition(decision),
    )

    line = fasteners_line(
        f"issues-{decision}",
        [finding],
        {"out_of_scope": [FASTENERS_OUT_OF_SCOPE], "checked": [checked_row()]},
    )

    assert (line.state, line.findings) == ("issues", 1)
