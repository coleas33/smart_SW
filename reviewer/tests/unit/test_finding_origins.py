"""Origin marks: the step mark and the session record a finding's origin is read from (T029).

`scoring.md` section 5.2 (FR-007; plan decisions SR-13, SR-14, RF-27). Code marks the steps it
made itself, and only those: `prerun.recorded_call` takes a required keyword `mark`, the
pre-run's calls pass `prerun` and the calls `ReviewRun._restate` makes after an answer pass
`regrade`; the model's calls stay unmarked. `start_review` writes `origin_marks: 1` on every
new session, the pane's included, whatever the levers, so a session written before this
feature, which has no record, reads its code findings' origins as unknown. Both fields are
omitted when `None`, so such a session round-trips to its own bytes; only `session.json` gains
them, never an event body or a stored tool result.

This is the product half of `scoring.md` 11's `test_finding_origins.py` tests 5, 6 and 7, over
the same scripted reviews the origin derivation's tests read (T032 adds tests 1 to 4 and the
origin halves of 5 and 6 when `benchmark/origins.py` lands, T033):

5. on `tests/support/prerun.py`'s scripted checks-first review, every pre-run step is marked
   `prerun`, the model's scripted calls are unmarked, and the session records the version;
6. on the scripted "All bought" batch `test_answer_batch_roles.py` plays, the steps `_restate`
   records are marked `regrade`;
7. a session written before this feature loads with neither field and keeps its bytes, and
   feature 001's session schema accepts both fields.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from swreview import prerun
from swreview.agent.events import EVENTS_FILE_NAME
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import run_review
from swreview.agent.settings import EfficiencySettings, ModelViewSettings, pane_defaults
from swreview.report.session import (
    SESSION_FILE_NAME,
    InvestigationStep,
    ReviewSession,
    load_session,
)
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME
from tests.support.attention import REVIEW_FOLDER
from tests.support.contracts import contract_validator
from tests.support.prerun import CHECKS_FIRST, GATE_ON, MODEL_DRIVEN_CALLS, OFF, review
from tests.unit import test_answer_batch_roles as roles
from tests.unit import test_chat_server as chat

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root
run_dir = chat.run_dir
scripted_registry = roles.scripted_registry

SCRIPTED_CALLS: tuple[ScriptedToolCall, ...] = (
    ScriptedToolCall("check_hygiene"),
    ScriptedToolCall("check_hole_alignment", {"hole_id_a": "hole:1", "hole_id_b": "hole:2"}),
)
"""What the scripted model calls after the pre-run: a check the pre-run already ran, which its
guard answers, and the package's coaxial pair, as `test_runner_model_view.py` scripts it."""

PRERUN_TOOLS_CALLED = [call.name for call in MODEL_DRIVEN_CALLS]
"""The pre-run's calls on `prerun_package()`, in order: the list a model has to ask for to reach
the state the pre-run reaches on its own (`tests/support/prerun.py`)."""

STORED_RESULT_KEYS = {"session_id", "step", "tool", "arguments", "status", "payload"}
"""Every member `SessionSink._store` writes into `tool-results/step-<n>.json`."""

TOOL_EVENT_KEYS = {
    "tool.started": {"step_index", "tool", "arguments"},
    "tool.finished": {"step_index", "status", "result_summary", "elapsed_s", "error"},
}
"""The two tool events' bodies, as feature 002's `chat-events.schema.json` lists them."""

ALL_BOUGHT = [("ER-001", "All bought")]


def written(folder: Path) -> dict[str, Any]:
    """The `session.json` a review wrote into `folder`, as JSON."""
    return json.loads((folder / SESSION_FILE_NAME).read_text(encoding="utf-8"))


def stream(folder: Path) -> list[dict[str, Any]]:
    """Every event of the `events.jsonl` a review wrote into `folder`, as JSON."""
    lines = (folder / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def marks_of(session: ReviewSession) -> list[tuple[str, str | None]]:
    """Each step's tool and origin mark, in step order."""
    return [(step.tool, step.origin_mark) for step in session.steps]


def checks_first_review(tmp_path: Path) -> ReviewSession:
    """`tests/support/prerun.py`'s scripted checks-first review, the model calling
    `SCRIPTED_CALLS`."""
    return review(tmp_path, "checks-first", calls=SCRIPTED_CALLS, efficiency=CHECKS_FIRST)


# --- the keyword ---------------------------------------------------------------------------------


def test_recorded_call_takes_a_required_keyword_mark() -> None:
    parameter = inspect.signature(prerun.recorded_call).parameters["mark"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_a_recorded_call_without_a_mark_is_a_type_error() -> None:
    """Refused before the call runs, so no context or dispatch is needed to see it."""
    with pytest.raises(TypeError, match="mark"):
        prerun.recorded_call(  # type: ignore[call-arg]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            "check_hygiene",
            {},
            call_id="unmarked",
        )


# --- 5. the pre-run's steps ----------------------------------------------------------------------


def test_every_pre_run_step_is_marked_prerun_and_the_models_calls_are_not(
    tmp_path: Path,
) -> None:
    session = checks_first_review(tmp_path)

    assert marks_of(session) == [
        *((tool, "prerun") for tool in PRERUN_TOOLS_CALLED),
        *((call.name, None) for call in SCRIPTED_CALLS),
    ]


def test_the_checks_first_session_records_the_version_and_writes_the_marks(
    tmp_path: Path,
) -> None:
    session = checks_first_review(tmp_path)

    assert session.origin_marks == 1
    on_disk = written(tmp_path / "checks-first")
    assert on_disk["origin_marks"] == 1
    prerun_steps = on_disk["steps"][: len(PRERUN_TOOLS_CALLED)]
    model_steps = on_disk["steps"][len(PRERUN_TOOLS_CALLED) :]
    assert [step["origin_mark"] for step in prerun_steps] == ["prerun"] * len(prerun_steps)
    assert len(model_steps) == len(SCRIPTED_CALLS)
    assert all("origin_mark" not in step for step in model_steps), "an unmarked step omits it"


def test_with_checks_first_off_no_step_is_marked_and_the_version_is_still_recorded(
    tmp_path: Path,
) -> None:
    """The off arm: the model makes every call, so nothing is marked, and the record says the
    marks were kept (US1-12: its code findings read as checks the model called)."""
    session = review(tmp_path, "off", calls=SCRIPTED_CALLS, efficiency=OFF)

    assert marks_of(session) == [(call.name, None) for call in SCRIPTED_CALLS]
    assert session.origin_marks == 1
    assert written(tmp_path / "off")["origin_marks"] == 1


# --- 6. the regrade's steps ----------------------------------------------------------------------


def test_after_all_bought_the_restated_steps_are_marked_regrade(
    tmp_path: Path, scripted_registry: None
) -> None:
    """Checks off: the model ran the part and hygiene checks; the answer restates both."""
    run = roles.graded(tmp_path)
    assert marks_of(run.session) == [("check_rms_part", None), ("check_hygiene", None)]

    run.answer_evidence_batch(ALL_BOUGHT)

    assert marks_of(run.session) == [
        ("check_rms_part", None),
        ("check_hygiene", None),
        ("check_rms_part", "regrade"),
        ("check_hygiene", "regrade"),
    ]
    assert [step.get("origin_mark") for step in written(run.out_dir)["steps"]] == [
        None,
        None,
        "regrade",
        "regrade",
    ]


def test_with_checks_first_the_pre_run_the_regrade_and_the_model_each_mark_their_own(
    tmp_path: Path, scripted_registry: None
) -> None:
    """The pre-run's steps `prerun`, the restated ones `regrade`, and the model's repeat after
    the answer, which the guard answers from the restated call, unmarked."""
    run = roles.graded(
        tmp_path,
        efficiency=CHECKS_FIRST,
        resumed=(ScriptedTurn(text="again", tool_calls=(ScriptedToolCall("check_rms_part"),)),),
    )
    prerun_steps = list(run.session.steps)
    assert prerun_steps and {step.origin_mark for step in prerun_steps} == {"prerun"}

    run.answer_evidence_batch(ALL_BOUGHT)

    after = marks_of(run.session)[len(prerun_steps) :]
    assert after == [
        ("check_rms_part", "regrade"),
        ("check_rms_equations", "regrade"),
        ("check_rms_assembly", "regrade"),
        ("check_hygiene", "regrade"),
        ("check_rms_part", None),
    ]


# --- the record on every new session -------------------------------------------------------------

LEVERS: dict[str, tuple[EfficiencySettings | None, ModelViewSettings | None]] = {
    "the-default": (None, None),
    "every-lever-off": (OFF, None),
    "the-gate": (GATE_ON, None),
    **{
        f"pane-defaults-{provider.value}": (
            pane_defaults(provider).efficiency,
            pane_defaults(provider).model_view,
        )
        for provider in ProviderName
    },
}


@pytest.mark.parametrize("levers", LEVERS.values(), ids=LEVERS.keys())
def test_start_review_writes_the_record_on_every_new_session_whatever_the_levers(
    tmp_path: Path,
    tmp_package_dir: Path,
    levers: tuple[EfficiencySettings | None, ModelViewSettings | None],
) -> None:
    efficiency, model_view = levers
    out = tmp_path / "out"

    session = run_review(
        tmp_package_dir,
        out,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=efficiency,
        model_view=model_view,
    )

    assert session.origin_marks == 1
    assert written(out)["origin_marks"] == 1


def test_the_panes_start_writes_the_record_and_marks_its_pre_run(
    client: TestClient, run_dir: Path
) -> None:
    """`chat/server.py`'s `_start_review`, through `POST /sessions`: the pane's review runs
    checks first and its scripted model calls nothing, so every step is the pre-run's."""
    chat_id = chat.start_session(client, run_dir)["chat_id"]
    chat.settle(client, chat_id)

    on_disk = written(run_dir)
    assert on_disk["origin_marks"] == 1
    assert on_disk["steps"]
    assert {step.get("origin_mark") for step in on_disk["steps"]} == {"prerun"}


# --- only session.json carries them --------------------------------------------------------------


def test_no_tool_event_body_and_no_stored_result_carries_a_mark(
    tmp_path: Path, scripted_registry: None
) -> None:
    """Over a stream holding all three kinds of step: the pre-run's, the regrade's and the
    model's. Each tool event validates against feature 002's schema and carries exactly the
    members it always did; each stored result carries exactly the envelope `_store` writes."""
    run = roles.graded(
        tmp_path,
        efficiency=CHECKS_FIRST,
        resumed=(ScriptedTurn(text="again", tool_calls=(ScriptedToolCall("check_rms_part"),)),),
    )
    run.answer_evidence_batch(ALL_BOUGHT)
    assert {step.origin_mark for step in run.session.steps} == {"prerun", "regrade", None}

    validator = contract_validator("chat-events.schema.json")
    tool_events = [event for event in stream(run.out_dir) if event["type"] in TOOL_EVENT_KEYS]
    assert len(tool_events) == 2 * len(run.session.steps)
    for event in tool_events:
        validator.validate(event)
        assert set(event["body"]) == TOOL_EVENT_KEYS[event["type"]], event
    stored = sorted((run.out_dir / TOOL_RESULTS_DIR_NAME).glob("step-*.json"))
    assert len(stored) == len(run.session.steps)
    for path in stored:
        assert set(json.loads(path.read_text(encoding="utf-8"))) == STORED_RESULT_KEYS, path.name


# --- 7. older sessions, and feature 001's schema -------------------------------------------------


def test_a_session_written_before_the_marks_loads_without_them_and_keeps_its_bytes() -> None:
    path = REVIEW_FOLDER / SESSION_FILE_NAME
    raw = path.read_bytes()

    session = load_session(path)

    assert session.origin_marks is None
    assert session.steps and all(step.origin_mark is None for step in session.steps)
    assert (session.model_dump_json(indent=2) + "\n").encode("utf-8") == raw.replace(
        b"\r\n", b"\n"
    )


def test_the_session_schema_accepts_both_fields(tmp_path: Path, scripted_registry: None) -> None:
    """A session carrying the record, `prerun` steps and `regrade` steps validates."""
    run = roles.graded(tmp_path, efficiency=CHECKS_FIRST)
    run.answer_evidence_batch(ALL_BOUGHT)
    on_disk = written(run.out_dir)
    assert on_disk["origin_marks"] == 1
    assert {step.get("origin_mark") for step in on_disk["steps"]} == {"prerun", "regrade"}

    contract_validator("review-session.schema.json").validate(on_disk)


@pytest.mark.parametrize("value", ["1", 1.5, None])
def test_the_session_schema_refuses_a_record_that_is_not_an_integer(
    tmp_path: Path, value: Any
) -> None:
    """Absent means origins unknown; when present the record is a version number, never a
    string, a fraction or a null (the session omits it when `None`)."""
    checks_first_review(tmp_path)
    on_disk = written(tmp_path / "checks-first")
    validator = contract_validator("review-session.schema.json")
    assert on_disk["origin_marks"] == 1 and validator.is_valid(on_disk)

    on_disk["origin_marks"] = value

    assert not validator.is_valid(on_disk)


@pytest.mark.parametrize("mark", ["model", "code", "", None])
def test_the_session_schema_and_the_model_refuse_a_mark_they_do_not_name(
    tmp_path: Path, mark: Any
) -> None:
    """Two marks only; an unmarked step omits the field rather than writing a null."""
    checks_first_review(tmp_path)
    on_disk = written(tmp_path / "checks-first")
    validator = contract_validator("review-session.schema.json")
    step = on_disk["steps"][0]
    assert step["origin_mark"] == "prerun" and validator.is_valid(on_disk)
    InvestigationStep.model_validate(step)

    step["origin_mark"] = mark

    assert not validator.is_valid(on_disk)
    if mark is not None:
        with pytest.raises(ValidationError):
            InvestigationStep.model_validate(step)
