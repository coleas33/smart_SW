"""The runner classifies the parts once and attaches the roles (feature 013 T021, T031).

`contracts/part-roles.md` section 5: `start_review` loads the standards profile once,
classifies every part and assembly document right after `build_context` - before
`carry_over_findings` and before the pre-run - and attaches the roles to the context under
`PART_ROLES_ATTRIBUTE`, where every consumer reads them. `reload_package` keeps them: document
ids are stable across a confirmed drawing read.

The classifier is lane P's (`checks/part_roles.py`, T018); these tests read it through its
contract and record what the runner hands it rather than re-deciding what it answers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.settings import EfficiencySettings
from swreview.checks import part_roles
from swreview.checks.standards.profile import StandardsProfile
from swreview.report.session import QUESTION_MAX_LENGTH, EvidenceRequest
from swreview.tools.registry import PART_ROLES_ATTRIBUTE
from tests.support.roles_review import (
    PIN_ID,
    PIN_STEM,
    PLATE_ID,
    ROOT_ID,
    review_brief,
    roles_review,
    write_profile,
)


class Recorder:
    """Wraps `classify_parts`, recording each call's profile and refusal."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.real = part_roles.classify_parts

    def __call__(self, package: Any, profile: Any, answers: Any = None, **options: Any) -> Any:
        self.calls.append({"profile": profile, "answers": answers, **options})
        return self.real(package, profile, answers, **options)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recording = Recorder()
    monkeypatch.setattr(part_roles, "classify_parts", recording)
    return recording


def roles_of(run: runner.ReviewRun) -> Any:
    return getattr(run.context, PART_ROLES_ATTRIBUTE)


# --- 1. classified once, with the loaded profile -------------------------------------------------


def test_a_configured_profile_is_loaded_and_handed_to_the_classifier(
    tmp_path: Path, recorder: Recorder
) -> None:
    run = roles_review(tmp_path)

    [call] = recorder.calls
    assert isinstance(call["profile"], StandardsProfile)
    assert call.get("profile_refusal") is None
    assert call["answers"] is None
    assert roles_of(run).state == "convention_only"


def broken_profile(tmp_path: Path) -> Path:
    """A version this build does not know, in a folder standing for a local user folder."""
    folder = tmp_path / "private-owner-folder"
    folder.mkdir()
    broken = folder / "broken.yaml"
    broken.write_text("version: 99\n", encoding="utf-8")
    return broken


def test_a_refused_profile_hands_the_classifier_the_loaders_reason(
    tmp_path: Path, recorder: Recorder
) -> None:
    """Edited deliberately (013 T154): the loader's reason, which names no path - not the
    profile's, not its folder, not its file name."""
    broken = broken_profile(tmp_path)

    run = roles_review(tmp_path, profile=broken)

    [call] = recorder.calls
    assert call["profile"] is None
    assert "version 99" in call["profile_refusal"]
    for where in (str(broken), str(broken.parent), broken.name, "private-owner-folder"):
        assert where not in call["profile_refusal"], where
    assert roles_of(run).state == "absent"


def test_no_path_rides_the_bought_parts_line(tmp_path: Path) -> None:
    """The bought-parts row and its digest line say the profile was refused and why, and neither
    they nor the brief name a path (013 research R2.45). The standards family's own line still
    names the file: it is what the engineer changes, and it is not this sentence."""
    broken = broken_profile(tmp_path)
    run = roles_review(tmp_path, profile=broken, efficiency=CHECKS_FIRST)
    run.start()

    [(_, row)] = rows_of(run, part_roles.BOUGHT_PARTS_CHECK)
    opening = str(run.messages[0]["content"])
    [line] = [line for line in opening.splitlines() if "Bought parts were not told apart" in line]
    assert "the standards profile was refused (" in row.reason
    assert "the standards profile was refused (" in line
    for text in (row.reason, line, review_brief(run)):
        for where in (str(tmp_path), broken.name, "private-owner-folder"):
            assert where not in text, (where, text)


def test_a_review_without_a_profile_classifies_in_the_absent_state(
    tmp_path: Path, recorder: Recorder
) -> None:
    run = roles_review(tmp_path, profile=None)

    [call] = recorder.calls
    assert call["profile"] is None and call.get("profile_refusal") is None
    assert roles_of(run).state == "absent"


def test_every_part_and_assembly_document_is_classified(tmp_path: Path) -> None:
    roles = roles_of(roles_review(tmp_path))

    assert set(roles.by_document) == {ROOT_ID, PLATE_ID, PIN_ID}
    assert roles.by_document[PLATE_ID].role == "custom"
    assert roles.by_document[PIN_ID].role == "unclear"
    assert roles.graded(ROOT_ID)


def test_the_profile_is_loaded_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from swreview.checks.standards import profile as profile_module

    loads: list[Any] = []
    real = profile_module.load_profile

    def counting(path: Any) -> Any:
        loads.append(path)
        return real(path)

    monkeypatch.setattr(profile_module, "load_profile", counting)

    roles_review(tmp_path)

    assert len(loads) == 1


# --- 2. where: after the context, before the carry-over and the pre-run -------------------------


def test_the_roles_are_attached_before_the_carry_over_and_the_pre_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    real_carry, real_prerun = runner.carry_over_findings, runner.prerun_checks

    def carry(context: Any, **options: Any) -> Any:
        seen["carry"] = getattr(context, PART_ROLES_ATTRIBUTE, None)
        return real_carry(context, **options)

    def prerun(context: Any, *arguments: Any, **options: Any) -> Any:
        seen["prerun"] = getattr(context, PART_ROLES_ATTRIBUTE, None)
        return real_prerun(context, *arguments, **options)

    monkeypatch.setattr(runner, "carry_over_findings", carry)
    monkeypatch.setattr(runner, "prerun_checks", prerun)

    run = roles_review(tmp_path)

    assert seen["carry"] is not None and seen["prerun"] is not None
    assert seen["carry"].by_document == roles_of(run).by_document


def test_reloading_the_package_keeps_the_roles(tmp_path: Path) -> None:
    run = roles_review(tmp_path)
    before = roles_of(run)

    run.context.reload_package(run.context.package)

    assert roles_of(run) is before


def test_the_attribute_is_named_beside_the_standards_run() -> None:
    from swreview.tools import registry

    assert PART_ROLES_ATTRIBUTE == "part_roles"
    assert PART_ROLES_ATTRIBUTE != registry.STANDARDS_RUN_ATTRIBUTE


# --- 3. the one question (T031, contracts/part-roles.md section 8) -----------------------------

QUESTION = (
    "Are these bought parts? Until you answer, they are graded for modelling practice and "
    "hygiene."
)
WHY = (
    "Bought parts are not graded for modelling practice or hygiene. Answer to regrade this "
    "review now."
)
CHECKS_FIRST = EfficiencySettings(prerun_checks=True)


def questions_of(run: runner.ReviewRun) -> list[EvidenceRequest]:
    return [
        request for request in run.session.evidence_requests if request.question == QUESTION
    ]


@pytest.mark.parametrize("efficiency", [None, CHECKS_FIRST], ids=["plain", "checks-first"])
def test_the_question_is_recorded_once_during_setup(
    tmp_path: Path, efficiency: EfficiencySettings | None
) -> None:
    run = roles_review(tmp_path, efficiency=efficiency)

    [request] = questions_of(run)
    assert request.id == "ER-001"
    assert run.turns == 0


def test_the_question_carries_exactly_section_8s_fields(tmp_path: Path) -> None:
    [request] = questions_of(roles_review(tmp_path))

    assert request.model_dump(mode="json") == {
        "id": "ER-001",
        "what": f"Parts no rule tells apart: {PIN_STEM}.SLDPRT",
        "why": WHY,
        "entity_ids": [PIN_ID],
        "status": "open",
        "answer": None,
        "answered_at": None,
        "question": QUESTION,
        "options": ["All bought", "None bought"],
        "allow_text": True,
        "source": "code",
    }
    assert len(QUESTION) <= QUESTION_MAX_LENGTH


def test_the_question_is_asked_before_the_pre_run_runs_a_check(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    roles_review(tmp_path, efficiency=CHECKS_FIRST, events=events)

    kinds = [kind for kind, _ in events]
    asked = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "evidence.requested" and body.get("question") == QUESTION
    )
    assert "tool.started" in kinds
    assert asked < kinds.index("tool.started")
    assert events[asked][1]["source"] == "code" and events[asked][1]["allow_text"] is True


def test_the_roles_cite_the_question_so_each_unclear_finding_can_say_so(tmp_path: Path) -> None:
    roles = roles_of(roles_review(tmp_path))

    note = roles.note_for(PIN_ID)
    assert note is not None and note.endswith("asked in ER-001")
    assert roles.note_for(PLATE_ID) is None


def test_no_question_without_a_profile(tmp_path: Path) -> None:
    run = roles_review(tmp_path, profile=None)

    assert questions_of(run) == []
    assert roles_of(run).note_for(PIN_ID) is None


def test_no_question_when_nothing_is_unclear(tmp_path: Path) -> None:
    assert questions_of(roles_review(tmp_path, pin=False)) == []


def test_no_question_when_the_convention_matches_nothing(tmp_path: Path) -> None:
    """The zero-match guard: a pattern that decides nothing would ask about every part."""
    run = roles_review(tmp_path, profile=write_profile(tmp_path, pattern="FICT-ZZ-####.SLDPRT"))

    assert roles_of(run).guard_fired
    assert questions_of(run) == []


def test_a_retry_asks_once_in_its_own_session(tmp_path: Path) -> None:
    first = roles_review(tmp_path / "first")
    retried = roles_review(tmp_path / "retry", retry_of=first.session.session_id)

    assert len(questions_of(first)) == 1
    assert len(questions_of(retried)) == 1


def test_the_question_names_ten_files_then_counts_the_rest(tmp_path: Path) -> None:
    from swreview.agent.providers.fake import FakeProvider
    from tests.support.mechanical import PackageBuilder
    from tests.support.roles_review import ROOT_STEM

    builder = PackageBuilder(design_stem=ROOT_STEM)
    for number in range(12):
        builder.component(builder.document(f"FICT-SORN-{number:02d}", "part"))
    folder = tmp_path / "run-0001"
    builder.build().write(folder)

    run = runner.start_review(
        folder,
        folder,
        provider=FakeProvider(script=[], model="fake-scripted"),
        standards_profile=write_profile(tmp_path),
    )

    [request] = questions_of(run)
    assert len(request.entity_ids) == 12
    # The classifier's own list words (`checks/part_roles._listed`, lane P): the tenth name,
    # then ", and 2 more" (integration of lanes P and S, 2026-09-27, edited deliberately).
    assert request.what.endswith("FICT-SORN-09.SLDPRT, and 2 more")
    assert "FICT-SORN-10" not in request.what


# --- 4. the bought-parts rows with no pre-run (section 7) -----------------------------------------


def rows_of(run: runner.ReviewRun, check: str) -> list[tuple[str, Any]]:
    return [
        (bucket, item)
        for bucket in ("skipped", "unresolved")
        for item in getattr(run.session.coverage, bucket)
        if item.check == check
    ]


def test_with_no_pre_run_the_maybe_bought_row_is_recorded_directly(tmp_path: Path) -> None:
    run = roles_review(tmp_path)

    [(bucket, item)] = rows_of(run, "coverage.prerun.maybe_bought")
    assert bucket == "unresolved"
    assert item.scope.document_ids == [PIN_ID]
    assert "asked in ER-001" in item.reason


def test_with_checks_first_the_rows_are_the_pre_runs_once(tmp_path: Path) -> None:
    run = roles_review(tmp_path, efficiency=CHECKS_FIRST)

    assert len(rows_of(run, "coverage.prerun.maybe_bought")) == 1
