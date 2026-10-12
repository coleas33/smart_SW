"""The shared fictional package asks the two questions needed by feature 015's fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import pane_defaults
from swreview.checks.drawing_context import CANDIDATE_CONFIRM
from swreview.checks.rms.registry import RULES
from swreview.ir.loader import load_package
from swreview.tools.registry import PART_ROLES_ATTRIBUTE
from tests.support.fixture_denylist import (
    DENYLIST_PATH,
    load_denylist,
    offending_tokens,
)
from tests.support.mechanical import FICTIONAL_ROOT
from tests.support.questions_package import QuestionsPackage, build_questions_package
from tests.support.review_bridge import ScriptedReviewBridge
from tests.support.roles_review import CONVENTION, PIN_ID, PLATE_ID, write_profile
from tests.unit.test_mechanical_fixtures_are_fictional import carried_strings


def reviewed(
    fixture: QuestionsPackage, events: list[tuple[str, dict[str, Any]]] | None = None
) -> ReviewRun:
    """Real checks under the pane defaults, with two model turns for an answer."""
    provider = FakeProvider(
        script=(ScriptedTurn(text="asked"), ScriptedTurn(text="resumed")),
        model="fake-scripted",
    )
    defaults = pane_defaults(provider.name)
    callbacks = []
    if events is not None:
        callbacks.append(lambda event: events.append((event.type, dict(event.body))))
    run = start_review(
        fixture.folder,
        fixture.folder,
        provider=provider,
        standards_profile=fixture.profile,
        bridge=True,
        bridge_factory=lambda pipe, secret: fixture.bridge,
        efficiency=defaults.efficiency,
        model_view=defaults.model_view,
        callbacks=callbacks,
    )
    run.start()
    return run


def test_it_uses_the_fictional_profile_a_at_version_three(tmp_path: Path) -> None:
    fixture = build_questions_package(tmp_path / "questions")
    expected_folder = tmp_path / "profile"
    expected_folder.mkdir()

    assert fixture.profile.read_bytes() == write_profile(expected_folder).read_bytes()
    profile = yaml.safe_load(fixture.profile.read_text(encoding="utf-8"))
    assert profile["version"] == 3
    assert "part_roles" not in profile
    assert profile["part_number"]["pattern"] == CONVENTION


def test_checks_first_asks_exactly_the_two_code_questions(tmp_path: Path) -> None:
    fixture = build_questions_package(tmp_path / "questions")
    run = reviewed(fixture)

    roles = getattr(run.context, PART_ROLES_ATTRIBUTE)
    assert roles.state == "convention_only"
    assert roles.by_document[PIN_ID].role == "unclear"
    questions = run.session.evidence_requests
    assert len(questions) == 2
    assert [question.source for question in questions] == ["code", "code"]
    roles_question, drawing_question = questions
    assert "All bought" in roles_question.options
    assert PIN_ID in roles_question.entity_ids
    assert CANDIDATE_CONFIRM in drawing_question.options
    assert PLATE_ID in drawing_question.entity_ids
    package = load_package(fixture.folder).package
    [candidate] = package.drawing_candidates
    assert candidate.document_id == PLATE_ID
    assert package.drawing_records == []


def test_the_scripted_seat_reads_a_confirmed_closed_drawing(tmp_path: Path) -> None:
    fixture = build_questions_package(tmp_path / "questions")
    run = reviewed(fixture)

    assert isinstance(fixture.bridge, ScriptedReviewBridge)
    assert run.session.drawing_read == "opens_closed"
    assert fixture.bridge.drawing_read_mode() == "opens_closed"
    assert [name for name, _ in fixture.bridge.calls].count("ping") == 1
    drawing_question = next(
        question
        for question in run.session.evidence_requests
        if CANDIDATE_CONFIRM in question.options
    )
    run.answer_evidence_batch([(drawing_question.id, CANDIDATE_CONFIRM)])

    assert [arguments for name, arguments in fixture.bridge.calls if name == "drawing_read"] == [
        {"run_id": fixture.folder.name, "document_id": PLATE_ID}
    ]
    assert drawing_question.status == "answered"
    assert any(item.check == "drawing.confirmed_open" for item in run.session.coverage.checked)


def test_all_bought_withdraws_named_hygiene_and_folded_rms_findings(tmp_path: Path) -> None:
    fixture = build_questions_package(tmp_path / "questions")
    events: list[tuple[str, dict[str, Any]]] = []
    run = reviewed(fixture, events)
    pin_components = {
        item.id for item in run.context.ir.components if item.document_id == PIN_ID
    }
    pin_findings = [
        finding
        for finding in run.session.findings
        if set(finding.component_ids) & pin_components
    ]
    hygiene = [finding for finding in pin_findings if finding.check.startswith("hygiene.")]
    rms = [finding for finding in pin_findings if finding.check in RULES]
    assert hygiene and rms
    opening = str(run.messages[0]["content"])
    assert any(finding.id in opening for finding in hygiene)
    assert all(finding.id not in opening for finding in rms)
    roles_question = next(
        question for question in run.session.evidence_requests if "All bought" in question.options
    )

    run.answer_evidence_batch([(roles_question.id, "All bought")])

    withdrawn = {
        body["finding_id"] for kind, body in events if kind == "finding.withdrawn"
    }
    assert {finding.id for finding in (*hygiene, *rms)} <= withdrawn
    remaining = {finding.id for finding in run.session.findings}
    assert not remaining & {finding.id for finding in (*hygiene, *rms)}
    resumed = str([message for message in run.messages if message["role"] == "user"][-1]["content"])
    assert "Checks first graded again after your answer: withdrew" in resumed
    assert any(finding.id in resumed for finding in hygiene)


def test_building_twice_gives_byte_identical_package_and_profile(tmp_path: Path) -> None:
    first = build_questions_package(tmp_path / "first")
    second = build_questions_package(tmp_path / "second")

    def contents(folder: Path) -> dict[str, bytes]:
        return {
            path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*")
            if path.is_file()
        }

    assert contents(first.folder) == contents(second.folder)
    assert first.profile.read_bytes() == second.profile.read_bytes()


def test_model_names_and_paths_are_fictional(tmp_path: Path) -> None:
    fixture = build_questions_package(tmp_path / "questions")
    package = load_package(fixture.folder).package

    assert package.design.name.startswith("FICT-")
    assert all(document.file_name.startswith("FICT-") for document in package.documents)
    assert all(component.name.startswith("FICT-") for component in package.components)
    paths = [document.path for document in package.documents]
    paths += [entry.vault_path for entry in package.manifest.entries]
    paths += [candidate.path for candidate in package.drawing_candidates]
    assert paths and all(path.startswith(FICTIONAL_ROOT) for path in paths)


def test_no_owner_denylisted_token_enters_the_generated_package(tmp_path: Path) -> None:
    denylist = load_denylist()
    if denylist is None:
        pytest.skip(f"the owner's denylist is not on this machine ({DENYLIST_PATH})")
    fixture = build_questions_package(tmp_path / "questions")
    package = load_package(fixture.folder).package
    strings = carried_strings(package)
    strings.extend(candidate.path for candidate in package.drawing_candidates)

    assert not any(offending_tokens(text, denylist) for text in strings), (
        "denylisted tokens occur in the fictional questions fixture"
    )
