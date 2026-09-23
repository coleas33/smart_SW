"""Checks first with SOLIDWORKS attached: live interference, every group judged, the rows kept
(feature 008 T041, FR-008 to FR-010, SC-006, `contracts/checks-first.md` sections 2 and 3).

On the recorded big assembly the model judged 6 of 113 detected groups. Under checks first the
pre-run calls `bridge_interference` once, through the same dispatch the model uses, before
anything else; every group the call found is then judged by `check_interference_group`; and
the detected rows are written into the run folder's `package.json`, so a re-render - and a
Retry - reads the same groups. Every way the call can fail is a coverage row and a digest
line, never a lost review, and a folder the command line was only asked to read is never
written.

The bridge here is `ScriptedReviewBridge`: it answers from a script, records every call and
refuses to be re-entered, which is all a unit test can ask of SOLIDWORKS.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers import TokenUsage
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.bridge.client import BridgeError, BridgeOpenError
from swreview.checks.interference import STATIC_SCOPE_LIMIT
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import (
    LIVE_INTERFERENCE_TOOL,
    PRERUN_INTERFERENCE_SETTINGS,
    PRERUN_TOOLS,
    RMS_PRERUN_TOOLS,
)
from swreview.report.rerender import rerender_run_folder
from swreview.report.session import ReviewSession, load_session
from swreview.tools import checks_mechanical
from swreview.tools.checks_interference import groups_of
from tests.support.prerun import (
    CHECKS_FIRST,
    GROUP_KEY,
    LIVE_OVERLAP_KEY,
    LIVE_ROWS,
    LIVE_ZERO_KEY,
    live_prerun_package,
    prerun_package,
)
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge

USAGE = TokenUsage(
    input_tokens=100,
    cached_input_tokens=0,
    cache_write_tokens=None,
    output_tokens=10,
    reasoning_tokens=None,
    tool_result_input_tokens=None,
    total_tokens=110,
    latency_s=0.1,
)


def live_answer(rows: tuple[dict[str, Any], ...] = LIVE_ROWS) -> dict[str, Any]:
    return {"interferences": [dict(row) for row in rows], "gaps": [dict(VOLUME_UNIT_GAP)]}


def bridge_answering(*answers: Any, supports: tuple[str, ...] | None = None) -> Any:
    options: dict[str, Any] = {"results": {"interference": list(answers)}}
    if supports is not None:
        options["supports"] = supports
    return ScriptedReviewBridge(**options)


def reviewed(
    folder: Path,
    out: Path,
    bridge: Any | None,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[ReviewRun, ReviewSession]:
    collected = events if events is not None else []
    options: dict[str, Any] = {}
    if bridge is not None:
        options = {"bridge": True, "bridge_factory": lambda pipe, secret: bridge}
    run = start_review(
        folder,
        out,
        provider=FakeProvider(
            script=[ScriptedTurn(text="done", usage=USAGE)], model="fake-scripted"
        ),
        efficiency=CHECKS_FIRST,
        callbacks=[lambda event: collected.append((event.type, dict(event.body)))],
        **options,
    )
    return run, run.start()


def package_folder(tmp_path: Path, package: EvidencePackage | None = None) -> Path:
    folder = tmp_path / "run"
    save_package(package if package is not None else live_prerun_package(), folder)
    return folder


def opening_of(run: ReviewRun) -> str:
    return str(run.messages[0]["content"])


def skipped_reason(session: ReviewSession, check: str) -> str:
    [reason] = [item.reason for item in session.coverage.skipped if item.check == check]
    return reason


# --- the happy path: one live call, every group judged, the rows kept -----------------------


@pytest.fixture
def live(tmp_path: Path) -> tuple[Path, ScriptedReviewBridge, ReviewRun, ReviewSession, list]:
    folder = package_folder(tmp_path)
    bridge = bridge_answering(live_answer())
    events: list[tuple[str, dict[str, Any]]] = []
    run, session = reviewed(folder, folder, bridge, events)
    return folder, bridge, run, session, events


def test_step_0_is_one_live_call_over_the_whole_assembly(live: Any) -> None:
    _, bridge, _, session, _ = live

    assert session.steps[0].tool == LIVE_INTERFERENCE_TOOL
    assert session.steps[0].arguments == {
        "component_ids": [],
        "configuration": "Default",
        "settings": PRERUN_INTERFERENCE_SETTINGS,
    }
    interference_calls = [args for name, args in bridge.calls if name == "interference"]
    assert len(interference_calls) == 1
    assert interference_calls[0]["component_ids"] == []
    assert interference_calls[0]["settings"] == PRERUN_INTERFERENCE_SETTINGS


def test_the_rms_calls_and_one_group_call_per_key_follow_it(live: Any) -> None:
    _, _, _, session, _ = live

    tools = [step.tool for step in session.steps]
    assert tools[:4] == [LIVE_INTERFERENCE_TOOL, *RMS_PRERUN_TOOLS]
    group_calls = [step for step in session.steps if step.tool == "check_interference_group"]
    assert [step.arguments["group_key"] for step in group_calls] == [
        LIVE_ZERO_KEY,
        LIVE_OVERLAP_KEY,
    ]
    assert tools[4 + len(group_calls) :] == list(checks_mechanical.CODE_FIRST_CHECKS)


def test_every_group_is_judged_one_finding_or_one_contact_each(live: Any) -> None:
    """Feature 010: the zero-volume group is a contact, the 42 mm³ overlap a finding."""
    _, _, _, session, _ = live

    group_steps = {
        step.index: step.arguments["group_key"]
        for step in session.steps
        if step.tool == "check_interference_group"
    }
    findings = [f for f in session.findings if f.check == "interference.static"]
    contacts = session.contacts
    assert [c.group_key for c in contacts] == [LIVE_ZERO_KEY]
    assert len(findings) == 1
    assert set(findings[0].tool_result_ids) <= set(group_steps)
    assert all(set(c.tool_result_ids) <= set(group_steps) for c in contacts)


def test_everything_happens_before_the_first_provider_round(live: Any) -> None:
    _, _, _, session, events = live

    first_usage = next(index for index, (kind, _) in enumerate(events) if kind == "usage")
    started = [index for index, (kind, _) in enumerate(events) if kind == "tool.started"]
    prerun_steps = [
        step
        for step in session.steps
        if step.tool in PRERUN_TOOLS or step.tool == LIVE_INTERFERENCE_TOOL
    ]
    assert len(started) >= len(prerun_steps)
    assert all(index < first_usage for index in started[: len(prerun_steps)])
    for finding in session.findings:
        assert set(finding.tool_result_ids) <= {step.index for step in session.steps}


def test_the_rows_and_the_gap_are_in_the_run_folders_package(live: Any) -> None:
    folder, _, run, session, _ = live

    on_disk = load_package(folder).package
    assert [row.id for row in on_disk.interferences] == [row["id"] for row in LIVE_ROWS]
    assert sum(1 for gap in on_disk.gaps if gap.entity_kind == VOLUME_UNIT_GAP["entity_kind"]) == 1
    assert [g.group_key for g in groups_of(on_disk)] == [LIVE_ZERO_KEY, LIVE_OVERLAP_KEY]
    assert on_disk.interferences == run.context.ir.interferences
    assert on_disk.gaps == run.context.ir.gaps


def test_a_re_render_from_the_run_folder_reproduces_the_finding_ids(live: Any) -> None:
    folder, _, _, session, _ = live

    report = rerender_run_folder(folder).read_text(encoding="utf-8")
    for finding in session.findings:
        assert f"#### {finding.id}:" in report


def test_the_opening_message_has_the_live_line_with_its_counts_and_settings(live: Any) -> None:
    _, _, run, _, _ = live
    opening = opening_of(run)

    [line] = [
        line for line in opening.splitlines() if line.startswith(f"  {LIVE_INTERFERENCE_TOOL}(")
    ]
    assert line.startswith(f"  {LIVE_INTERFERENCE_TOOL}(Default) -> 2 rows in 2 groups (")
    for name, value in PRERUN_INTERFERENCE_SETTINGS.items():
        assert f"{name}={str(value).lower() if isinstance(value, bool) else value}" in line
    assert "  check_interference_group x2 -> 2 ok, 1 finding, 1 contact" in opening.splitlines()


# --- Retry, and the command line's input folder ----------------------------------------------


def test_a_retry_in_the_same_folder_judges_the_same_groups_and_grows_nothing(
    tmp_path: Path,
) -> None:
    folder = package_folder(tmp_path)
    reviewed(folder, folder, bridge_answering(live_answer()))
    first = load_package(folder).package

    run, session = reviewed(folder, folder, bridge_answering(live_answer()))

    second = load_package(folder).package
    assert len(second.interferences) == len(first.interferences)
    assert len(second.gaps) == len(first.gaps)
    assert [g.group_key for g in groups_of(second)] == [LIVE_ZERO_KEY, LIVE_OVERLAP_KEY]
    assert "collide" not in opening_of(run)
    assert not [i for i in session.coverage.unresolved if "collide" in i.reason]


def test_a_command_line_run_never_writes_its_input_folder(tmp_path: Path) -> None:
    folder = package_folder(tmp_path)
    source = (folder / PACKAGE_FILE_NAME).read_bytes()
    out = tmp_path / "out"

    reviewed(folder, out, bridge_answering(live_answer()))

    assert (folder / PACKAGE_FILE_NAME).read_bytes() == source
    assert [row.id for row in load_package(out).package.interferences] == [
        row["id"] for row in LIVE_ROWS
    ]


# --- a clean detection -------------------------------------------------------------------


def test_zero_rows_is_a_checked_item_scoped_to_the_configuration(tmp_path: Path) -> None:
    folder = package_folder(tmp_path)

    run, session = reviewed(folder, folder, bridge_answering(live_answer(rows=())))

    [item] = [item for item in session.coverage.checked if item.check == "interference"]
    assert item.scope.configuration == "Default"
    assert STATIC_SCOPE_LIMIT in item.reason
    assert "treat_coincident_as_interference=true" in item.reason
    assert (
        "  interference: live detection over Default found no interference ("
        in opening_of(run)
    )
    assert "the package reports no interference" not in opening_of(run)
    assert not [s for s in session.steps if s.tool == "check_interference_group"]


# --- the failures: each a coverage row and a line, never a lost review -----------------------


FAILURES = {
    "bridge-error": lambda: bridge_answering(BridgeError("the host lost the document")),
    "circuit-open": lambda: bridge_answering(BridgeOpenError("the circuit is open")),
    "no-interference": lambda: bridge_answering(supports=("ping", "capture", "measure")),
}


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_a_failed_live_call_is_failed_and_skipped_coverage_and_the_review_starts(
    tmp_path: Path, case: str
) -> None:
    folder = package_folder(tmp_path, prerun_package())
    before = (folder / PACKAGE_FILE_NAME).read_bytes()

    run, session = reviewed(folder, folder, FAILURES[case]())

    [failed] = [
        item for item in session.coverage.failed if item.check == "tool.bridge_interference"
    ]
    assert failed.error
    reason = skipped_reason(session, "coverage.prerun.interference")
    assert reason.startswith("live detection failed: ")
    assert failed.error in reason
    assert reason.endswith("; it was not evaluated")
    assert f"  interference: {reason}" in opening_of(run).splitlines()
    assert session.ended_at is not None
    assert (folder / PACKAGE_FILE_NAME).read_bytes() == before
    assert run.context.ir.interferences == prerun_package().interferences
    group_steps = [s for s in session.steps if s.tool == "check_interference_group"]
    assert [s.arguments["group_key"] for s in group_steps] == [GROUP_KEY]


def test_a_persist_failure_is_unresolved_and_the_findings_still_stand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swreview.ir import loader

    folder = package_folder(tmp_path)
    before = (folder / PACKAGE_FILE_NAME).read_bytes()
    real_replace = loader.os.replace

    def refuse(source: Any, target: Any) -> None:
        if Path(target).name == PACKAGE_FILE_NAME:
            raise PermissionError("package.json is locked")
        real_replace(source, target)

    monkeypatch.setattr(loader.os, "replace", refuse)
    run, session = reviewed(folder, folder, bridge_answering(live_answer()))

    [item] = [
        item
        for item in session.coverage.unresolved
        if item.check == "coverage.prerun.interference_rows"
    ]
    assert "package.json is locked" in item.reason
    assert (
        "  interference: the detected rows could not be written to package.json: "
        in opening_of(run)
    )
    assert [f for f in session.findings if f.check == "interference.static"]
    assert (folder / PACKAGE_FILE_NAME).read_bytes() == before


def test_rows_colliding_with_another_configuration_are_counted_unresolved(
    tmp_path: Path,
) -> None:
    other = prerun_package().interferences[0].model_copy(
        update={"id": "int:0002", "configuration": "Other"}
    )
    package = live_prerun_package().model_copy(update={"interferences": [other]})
    folder = package_folder(tmp_path, package)

    run, session = reviewed(folder, folder, bridge_answering(live_answer()))

    [item] = [
        item for item in session.coverage.unresolved if item.check == "coverage.prerun.interference"
    ]
    assert item.reason.startswith("1 detected row was dropped") or item.reason.startswith(
        "1 detected rows were dropped"
    )
    assert "collide" in opening_of(run)
    on_disk = load_package(folder).package
    assert sorted(row.id for row in on_disk.interferences) == ["int:0001", "int:0002"]
    assert {row.configuration for row in on_disk.interferences} == {"Default", "Other"}


# --- when live detection does not run at all ---------------------------------------------


def test_no_bridge_and_rows_in_the_package_says_solidworks_is_not_attached(
    tmp_path: Path,
) -> None:
    folder = package_folder(tmp_path, prerun_package())

    run, session = reviewed(folder, folder, None)

    assert LIVE_INTERFERENCE_TOOL not in [step.tool for step in session.steps]
    reason = skipped_reason(session, "coverage.prerun.interference")
    assert reason == (
        "SOLIDWORKS is not attached, so live detection did not run; the 1 group the "
        "package already holds was judged"
    )
    assert f"  interference: {reason}" in opening_of(run).splitlines()


def test_no_bridge_and_no_rows_keeps_todays_sentence(tmp_path: Path) -> None:
    folder = package_folder(tmp_path)

    _, session = reviewed(folder, folder, None)

    assert skipped_reason(session, "coverage.prerun.interference").startswith(
        "the package reports no interference, so no group was checked."
    )


def single_component_package() -> EvidencePackage:
    package = live_prerun_package()
    return package.model_copy(
        update={
            "components": package.components[:1],
            "holes": [],
            "fasteners": [],
        }
    )


@pytest.mark.parametrize("shape", ["part-root", "single-component"])
def test_a_part_root_or_a_single_component_makes_no_live_call(
    tmp_path: Path, shape: str
) -> None:
    if shape == "part-root":
        package = live_prerun_package()
        root = package.design.root_assembly_document_id
        package = package.model_copy(
            update={
                "documents": [
                    d.model_copy(update={"kind": "part"}) if d.document_id == root else d
                    for d in package.documents
                ]
            }
        )
        kind, count = "a part", len(package.components)
    else:
        package = single_component_package()
        kind, count = "an assembly", 1
    folder = package_folder(tmp_path, package)
    bridge = bridge_answering()

    run, session = reviewed(folder, folder, bridge)

    assert not [name for name, _ in bridge.calls if name == "interference"]
    assert LIVE_INTERFERENCE_TOOL not in [step.tool for step in session.steps]
    reason = skipped_reason(session, "coverage.prerun.interference")
    assert reason == (
        f"live detection needs an assembly with two components or more; the root is {kind} "
        f"with {count} component{'s' if count != 1 else ''}"
    )
    assert f"  interference: {reason}" in opening_of(run).splitlines()


def test_the_settings_are_the_recorded_runs() -> None:
    """Research R2.17: the five settings the model chose on the recorded run, all stated."""
    assert PRERUN_INTERFERENCE_SETTINGS == {
        "treat_coincident_as_interference": True,
        "treat_subassemblies_as_components": True,
        "include_multibody": True,
        "ignore_hidden": False,
        "fastener_folder_treatment": "include",
    }


def test_the_session_on_disk_matches_the_session_in_memory(live: Any) -> None:
    folder, _, _, session, _ = live

    assert load_session(folder / "session.json").steps == session.steps
    assert json.loads((folder / "session.json").read_text(encoding="utf-8"))["folded_families"] == [
        "rms"
    ]
