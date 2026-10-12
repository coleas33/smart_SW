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
the same scripted reviews the origin derivation's tests read:

5. on `tests/support/prerun.py`'s scripted checks-first review, every pre-run step is marked
   `prerun`, the model's scripted calls are unmarked, and the session records the version;
6. on the scripted "All bought" batch `test_answer_batch_roles.py` plays, the steps `_restate`
   records are marked `regrade`;
7. a session written before this feature loads with neither field and keeps its bytes, and
   feature 001's session schema accepts both fields.

The derivation, `benchmark/origins.finding_origin` (T032, for T033; `scoring.md` 5.1, 5.3 and
5.4; FR-007), is tests 1 to 4 and the origin halves of 5 and 6:

1. each of the eight values from a session built as data, a cited step the session does not
   hold reading `unknown` and a finding citing two steps decided by the later;
2. a session without the record reads every code finding but a carried one `unknown`; with the
   record and no marked step, a code finding reads by its step's tool (US1-12);
3. S-5.4, structural, over every check tool: every code-only tool is a pre-run tool, one of the
   three named ones or takes no required parameter, the two interference tools are the only
   ones with a required parameter, and every other check takes one and is no pre-run tool;
4. every finding the pre-run writes cites its own step (SP-3, owner decision 40A); with every
   lever off and no model call, every finding `start_review` writes is `setup`;
5. the checks-first review's findings read `prerun` and `configured_check`, its guarded
   `check_hygiene` repeat adding none, and the same package's off arm, where the model calls
   the part and mass checks, gives the `code_only_call` findings (owner decision 41A);
6. a finding that survives the scripted "All bought" reads `regrade` (US1-13).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast, get_args
from uuid import UUID

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from swreview import prerun
from swreview.agent.events import EVENTS_FILE_NAME
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import run_review
from swreview.agent.settings import EfficiencySettings, ModelViewSettings, pane_defaults
from swreview.benchmark.origins import (
    CODE_ONLY_TOOLS,
    MODEL_ORIGINS,
    SETUP_CHECK_PREFIXES,
    Origin,
    finding_origin,
)
from swreview.checks.standards.registry import CHECK_TOOL
from swreview.findings import MODEL_FINDING_CHECK, Finding, Source
from swreview.ingest.manifest import DISCREPANCY_SEVERITY
from swreview.report.session import (
    ORIGIN_MARKS_VERSION,
    SESSION_FILE_NAME,
    InvestigationStep,
    ReviewSession,
    StepMark,
    load_session,
)
from swreview.tools import drawings
from swreview.tools.bridge import bridge_interference
from swreview.tools.context import new_session
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME, check_tools, standards_tools
from tests.support.attention import REVIEW_FOLDER
from tests.support.contracts import contract_validator
from tests.support.findings import make_finding
from tests.support.packages import build_package
from tests.support.prerun import (
    CHECKS_FIRST,
    GATE_ON,
    MODEL_DRIVEN_CALLS,
    OFF,
    STANDARDS_PROFILE,
    prerun_package,
    review,
    standards_prerun_package,
)
from tests.support.roles_review import PIN_ID, PLATE_ID
from tests.unit import test_answer_batch_roles as roles
from tests.unit import test_chat_server as chat
from tests.unit.test_provenance_closure import with_discrepancies

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


OFF_ARM_CALLS: tuple[ScriptedToolCall, ...] = (
    ScriptedToolCall("check_rms_part"),
    ScriptedToolCall("check_mass_material"),
)
"""What the scripted model calls on the off arm of the same package (owner decision 41A): two
code-only checks, each of which writes a finding on `prerun_package()`."""

# --- sessions built as data ----------------------------------------------------------------------

PACKAGE = build_package()
CARRIED_FROM = UUID("0e5a7c1d-2b4f-4c6e-8a9b-1c2d3e4f5a6b")
"""The fictional earlier session a carried finding names."""

SETUP_CHECK = "provenance.version_mismatch"
CONFIGURED_CHECK = "hole.coaxiality"
"""A set-up record's check, and a check an argument-taking check tool writes with no step."""


def step_at(index: int, tool: str, mark: StepMark | None = None) -> InvestigationStep:
    """One step of a session built as data: its index, its tool and its mark."""
    return InvestigationStep(
        index=index,
        tool=tool,
        arguments={},
        result_summary="ok",
        status="ok",
        error=None,
        elapsed_s=0.0,
        origin_mark=mark,
    )


STEPS: tuple[InvestigationStep, ...] = (
    step_at(0, "check_rms_part", "prerun"),
    step_at(1, "check_hygiene", "regrade"),
    step_at(2, "check_mass_material"),
    step_at(3, "check_fit"),
)
"""The four kinds of cited step: the pre-run's, the regrade's, an unmarked code-only call and an
unmarked configured check."""


def session_with(
    steps: Sequence[InvestigationStep] = STEPS, *, origin_marks: int | None = ORIGIN_MARKS_VERSION
) -> ReviewSession:
    """A new session over `PACKAGE` holding the two things `finding_origin` reads: the steps
    and the origin-marks record."""
    return new_session(PACKAGE, model="fake-scripted").model_copy(
        update={"origin_marks": origin_marks, "steps": list(steps)}
    )


def finding(
    *cites: int,
    check: str = "rms.folders.present",
    source: Source = "code",
    carried: bool = False,
) -> Finding:
    """A finding built as data, citing `cites`; `carried` names `CARRIED_FROM`."""
    built = cast(Finding, make_finding(check=check, tool_result_ids=cites, source=source))
    return built.model_copy(update={"carried_over_from": CARRIED_FROM}) if carried else built


def origins_of(session: ReviewSession) -> dict[str, Origin]:
    """Each of the session's findings by id, read by `finding_origin`."""
    return {item.id: finding_origin(item, session) for item in session.findings}


def cited_tools(session: ReviewSession) -> set[str]:
    """The tool of every step the session's findings cite."""
    tools = {one.index: one.tool for one in session.steps}
    return {tools[index] for item in session.findings for index in item.tool_result_ids}


def step_in_flight(folder: Path) -> dict[str, int | None]:
    """Each announced finding's id and the step it was announced inside, read off the stream:
    the last `tool.started` before its `finding` event, `None` when a `tool.finished` came
    between them or no step had started."""
    in_flight: int | None = None
    announced: dict[str, int | None] = {}
    for event in stream(folder):
        if event["type"] == "tool.started":
            in_flight = event["body"]["step_index"]
        elif event["type"] == "tool.finished":
            in_flight = None
        elif event["type"] == "finding":
            announced[event["body"]["id"]] = in_flight
    return announced


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


# --- 1. the eight values -------------------------------------------------------------------------


def test_origin_is_the_eight_values_of_5_1_in_order() -> None:
    assert get_args(Origin) == (
        "prerun",
        "regrade",
        "code_only_call",
        "configured_check",
        "model",
        "carried",
        "setup",
        "unknown",
    )


def test_a_set_up_record_is_named_by_the_provenance_prefix_alone() -> None:
    assert SETUP_CHECK_PREFIXES == ("provenance.",)


EACH_VALUE: dict[str, tuple[Callable[[], Finding], Origin]] = {
    "carried": (lambda: finding(0, carried=True), "carried"),
    "model": (lambda: finding(check=MODEL_FINDING_CHECK, source="model"), "model"),
    "prerun": (lambda: finding(0), "prerun"),
    "regrade": (lambda: finding(1), "regrade"),
    "code-only-call": (lambda: finding(2), "code_only_call"),
    "configured-check-by-tool": (lambda: finding(3), "configured_check"),
    "setup": (lambda: finding(check=SETUP_CHECK), "setup"),
    "configured-check-no-step": (lambda: finding(check=CONFIGURED_CHECK), "configured_check"),
}
"""Each value in a session with the record (`unknown` is the session without it, below): a
carried finding citing a pre-run step is still carried (rule 1); a model-written one is the
model's (rule 2); a cited step's mark, or an unmarked one's tool, decides (rule 4); a finding
citing no step is set-up by its check's prefix, else a configured check (rule 5)."""


@pytest.mark.parametrize("case", EACH_VALUE.values(), ids=EACH_VALUE.keys())
def test_each_value_from_a_session_built_as_data(
    case: tuple[Callable[[], Finding], Origin],
) -> None:
    build, expected = case

    assert finding_origin(build(), session_with()) == expected


def test_a_code_finding_in_a_session_without_the_record_reads_unknown() -> None:
    assert finding_origin(finding(0), session_with(origin_marks=None)) == "unknown"


def test_the_cases_and_the_session_without_the_record_cover_all_eight_values() -> None:
    assert {expected for _, expected in EACH_VALUE.values()} | {"unknown"} == set(get_args(Origin))


@pytest.mark.parametrize(
    "cites",
    [(4,), (7,), (-1,), (0, 9)],
    ids=["one-past-the-last", "far-past-the-last", "negative", "later-missing"],
)
def test_a_cited_step_the_session_does_not_hold_reads_unknown_with_the_record(
    cites: tuple[int, ...],
) -> None:
    """Never guessed (SR-25): the folder was altered or written by something other than the
    review. A negative id names no step, never the last one; with two cited, the later decides
    even when the earlier is held."""
    assert finding_origin(finding(*cites), session_with()) == "unknown"


@pytest.mark.parametrize(
    ("cites", "expected"),
    [
        ((0, 1), "regrade"),
        ((1, 0), "regrade"),
        ((0, 2), "code_only_call"),
        ((2, 0), "code_only_call"),
        ((1, 3), "configured_check"),
        ((3, 2), "configured_check"),
    ],
    ids=["prerun-then-regrade", "regrade-then-prerun", "prerun-then-code-only",
         "code-only-then-prerun", "regrade-then-configured", "configured-then-code-only"],
)
def test_a_finding_citing_two_steps_is_decided_by_the_later(
    cites: tuple[int, ...], expected: Origin
) -> None:
    """The highest index cited, wherever it stands in the list."""
    assert finding_origin(finding(*cites), session_with()) == expected


def test_steps_are_found_by_their_index_not_their_position() -> None:
    """A session's steps carry their own indices; the derivation reads the step whose index the
    finding cites, so a session holding steps 5 and 9 reads step 9 for a finding citing 9."""
    session = session_with((step_at(5, "check_fit"), step_at(9, "check_rms_part", "prerun")))

    assert finding_origin(finding(9), session) == "prerun"
    assert finding_origin(finding(5), session) == "configured_check"
    assert finding_origin(finding(1), session) == "unknown"


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (lambda: finding(0, check=MODEL_FINDING_CHECK, source="model", carried=True), "carried"),
        (lambda: finding(0, check=MODEL_FINDING_CHECK, source="model"), "model"),
        (lambda: finding(7, check=MODEL_FINDING_CHECK, source="model"), "model"),
        (lambda: finding(0, check=SETUP_CHECK), "prerun"),
        (lambda: finding(3, check=SETUP_CHECK), "configured_check"),
        (lambda: finding(check="hygiene.provenance"), "configured_check"),
        (lambda: finding(check="hygiene.provenance.x"), "configured_check"),
        (lambda: finding(check="provenance"), "configured_check"),
    ],
    ids=["carried-before-model", "model-before-its-step", "model-before-a-missing-step",
         "a-cited-step-before-the-prefix", "a-cited-tool-before-the-prefix",
         "provenance-not-a-prefix", "provenance-dot-inside-not-at-the-start",
         "provenance-without-the-dot"],
)
def test_the_first_rule_wins(build: Callable[[], Finding], expected: Origin) -> None:
    assert finding_origin(build(), session_with()) == expected


# --- 2. the record -------------------------------------------------------------------------------


def test_without_the_record_every_code_finding_but_a_carried_one_reads_unknown() -> None:
    """US1-12: a session written before the marks reads its code findings' origin as unknown,
    `setup` and `configured_check` included; a carried and a model-written finding are read
    from their own fields, and keep their origins."""
    session = session_with(origin_marks=None)
    code_findings = [
        finding(0),
        finding(1),
        finding(2),
        finding(3),
        finding(7),
        finding(check=SETUP_CHECK),
        finding(check=CONFIGURED_CHECK),
    ]

    assert [finding_origin(item, session) for item in code_findings] == ["unknown"] * 7
    assert finding_origin(finding(0, carried=True), session) == "carried"
    assert finding_origin(finding(check=MODEL_FINDING_CHECK, source="model"), session) == "model"


OFF_ARM_TOOLS: dict[str, Origin] = {
    "check_rms_part": "code_only_call",
    "check_interference_group": "code_only_call",
    "check_hygiene": "code_only_call",
    prerun.LIVE_INTERFERENCE_TOOL: "code_only_call",
    drawings.DRAWINGS_TOOL: "code_only_call",
    CHECK_TOOL: "code_only_call",
    "check_fit": "configured_check",
    "check_axial_stack": "configured_check",
    "check_fastener_joint": "configured_check",
    "check_hole_alignment": "configured_check",
}
"""An off-arm session's tools, one step each, and what a finding citing that step reads: the
model made every call, so none is marked, and a model-called interference finding (owner
decision 40A) is a code-only call."""

OFF_ARM_STEPS = tuple(step_at(index, tool) for index, tool in enumerate(OFF_ARM_TOOLS))


@pytest.mark.parametrize(("index", "tool"), list(enumerate(OFF_ARM_TOOLS)), ids=list(OFF_ARM_TOOLS))
def test_with_the_record_and_no_marked_step_a_code_finding_reads_by_its_tool(
    index: int, tool: str
) -> None:
    """US1-12's off arm: a code-only call the model made, or a check it configured."""
    assert finding_origin(finding(index), session_with(OFF_ARM_STEPS)) == OFF_ARM_TOOLS[tool]


def test_with_the_record_and_no_step_cited_a_code_finding_reads_by_its_check() -> None:
    session = session_with(OFF_ARM_STEPS)

    assert finding_origin(finding(check=SETUP_CHECK), session) == "setup"
    assert finding_origin(finding(check=CONFIGURED_CHECK), session) == "configured_check"


# --- 3. S-5.4: the code-only tool set ------------------------------------------------------------

CHECK_TOOLS: dict[str, Callable[..., Any]] = {
    tool.__name__: tool for tool in (*check_tools(), drawings.check_drawings, *standards_tools())
}
"""Every check tool a review can offer, by name: `tools/registry.check_tools()` and the two
offered on condition, `check_drawings` (drawing evidence) and `check_standards` (a standards
run)."""

CODE_ONLY_CANDIDATES: dict[str, Callable[..., Any]] = {
    **CHECK_TOOLS,
    prerun.LIVE_INTERFERENCE_TOOL: bridge_interference,
}
"""The check tools and the pre-run's live call, which is a bridge tool, not a check tool."""

INTERFERENCE_TOOLS = {"check_interference_group", "bridge_interference"}
"""The two pre-run tools that take arguments, named: one call per group, and the live call."""


def required_parameters(tool: Callable[..., Any]) -> list[str]:
    """The parameters a call of `tool` has to name, by its signature."""
    variadic = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    return [
        name
        for name, parameter in inspect.signature(tool).parameters.items()
        if parameter.default is inspect.Parameter.empty and parameter.kind not in variadic
    ]


def test_the_code_only_tools_are_built_from_the_constants_that_name_them() -> None:
    """RF-6: the pre-run's tools, its live call, the drawing check and the standards check, so
    a pre-run change moves the set with no second edit."""
    assert CODE_ONLY_TOOLS == frozenset(
        {*prerun.prerun_tools(), prerun.LIVE_INTERFERENCE_TOOL, drawings.DRAWINGS_TOOL, CHECK_TOOL}
    )
    assert {drawings.DRAWINGS_TOOL, CHECK_TOOL} < set(CHECK_TOOLS)


def test_every_code_only_tool_is_a_pre_run_tool_a_named_one_or_takes_no_required_parameter() -> (
    None
):
    named = {prerun.LIVE_INTERFERENCE_TOOL, drawings.DRAWINGS_TOOL, CHECK_TOOL}
    for name in sorted(CODE_ONLY_TOOLS):
        assert name in CODE_ONLY_CANDIDATES, f"{name} is code-only but is no tool a review offers"
        tool = CODE_ONLY_CANDIDATES[name]
        assert name in prerun.prerun_tools() or name in named or not required_parameters(tool), (
            f"{name} is code-only, is no pre-run tool and takes {required_parameters(tool)}"
        )


def test_every_other_check_tool_takes_a_required_parameter_and_is_no_pre_run_tool() -> None:
    """RF-68: a configured check is rule 4's "otherwise"; no second set names them."""
    configured = sorted(set(CHECK_TOOLS) - CODE_ONLY_TOOLS)

    assert configured, "every check tool is code-only, and this rule holds over nothing"
    for name in configured:
        assert required_parameters(CHECK_TOOLS[name]), f"{name} takes no required parameter"
        assert name not in prerun.prerun_tools(), f"{name} is a pre-run tool"


def test_the_two_interference_tools_are_exactly_the_code_only_tools_with_a_required_parameter() -> (
    None
):
    """RF-38: a check added to the pre-run, or given a required parameter, lands in the right
    set or fails here."""
    with_required = {
        name for name in CODE_ONLY_TOOLS if required_parameters(CODE_ONLY_CANDIDATES[name])
    }

    assert with_required == INTERFERENCE_TOOLS


def test_model_origin_is_the_model_and_a_configured_check() -> None:
    """17A and 20A: the two origins the pane study's deciding false alarms are read from."""
    assert MODEL_ORIGINS == frozenset({"model", "configured_check"})
    assert set(MODEL_ORIGINS) < set(get_args(Origin))


# --- 4. findings that cite their own step, and set-up --------------------------------------------

PRE_RUN_PACKAGES: dict[str, tuple[Callable[[], Any], dict[str, Any]]] = {
    "prerun-package": (prerun_package, {}),
    "standards-package": (standards_prerun_package, {"standards_profile": STANDARDS_PROFILE}),
}
"""Two checks-first reviews whose scripted model calls nothing: on the second the hygiene and
standards checks write findings too."""


@pytest.mark.parametrize("case", PRE_RUN_PACKAGES.values(), ids=PRE_RUN_PACKAGES.keys())
def test_every_finding_the_pre_run_writes_cites_its_own_step(
    tmp_path: Path, case: tuple[Callable[[], Any], dict[str, Any]]
) -> None:
    """SP-3: each finding names exactly the step it was announced inside, which is the
    pre-run's, so it reads `prerun`; the interference finding among them (owner decision 40A)."""
    package, options = case
    session = review(tmp_path, "pre-run", package=package(), efficiency=CHECKS_FIRST, **options)
    in_flight = step_in_flight(tmp_path / "pre-run")

    assert session.findings
    assert set(in_flight) == {item.id for item in session.findings}
    for item in session.findings:
        own = in_flight[item.id]
        assert own is not None and item.tool_result_ids == [own], item
        assert session.steps[own].origin_mark == "prerun"
    assert set(origins_of(session).values()) == {"prerun"}
    assert prerun.INTERFERENCE_TOOL in cited_tools(session)


def test_with_every_lever_off_and_no_model_call_every_finding_start_review_writes_is_setup(
    tmp_path: Path,
) -> None:
    """A package with a manifest discrepancy of each kind, so `record_provenance` writes a
    finding for each (`prerun_package()` holds none, which would leave this holding over
    nothing). No step runs, and each finding cites none."""
    session = review(
        tmp_path, "off", package=with_discrepancies(*DISCREPANCY_SEVERITY), efficiency=OFF
    )

    assert session.steps == []
    assert len(session.findings) == len(DISCREPANCY_SEVERITY)
    assert all(item.tool_result_ids == [] for item in session.findings)
    assert set(origins_of(session).values()) == {"setup"}


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


def test_on_the_checks_first_review_the_findings_read_prerun_and_configured_check(
    tmp_path: Path,
) -> None:
    """The scripted `check_hole_alignment` on the package's coaxial pair records its
    `hole.coaxiality` finding unresolved, with no tolerance drawn and no step cited: a check
    the model configured. Every other finding is the pre-run's (owner decision 41A)."""
    session = checks_first_review(tmp_path)
    origins = origins_of(session)

    [hole] = [item for item in session.findings if item.check == CONFIGURED_CHECK]
    assert (hole.status, hole.drawing_locations, hole.tool_result_ids) == ("unresolved", [], [])
    assert origins.pop(hole.id) == "configured_check"
    assert origins and set(origins.values()) == {"prerun"}


def test_the_scripted_check_hygiene_repeat_is_answered_already_run_and_adds_no_finding(
    tmp_path: Path,
) -> None:
    """The pre-run guard answers the model's repeat from the pre-run's call: the check does not
    run again, so no finding cites the repeat (owner decision 41A)."""
    session = checks_first_review(tmp_path)

    [ran, repeat] = [one for one in session.steps if one.tool == "check_hygiene"]
    assert (ran.origin_mark, repeat.origin_mark) == ("prerun", None)
    stored = json.loads(
        (tmp_path / "checks-first" / TOOL_RESULTS_DIR_NAME / f"step-{repeat.index}.json")
        .read_text(encoding="utf-8")
    )
    assert stored["payload"]["status"] == prerun.ALREADY_RUN
    assert stored["payload"]["ran_at_step"] == ran.index
    assert [item.id for item in session.findings if repeat.index in item.tool_result_ids] == []


def test_on_the_off_arm_the_models_code_only_calls_write_findings_that_read_code_only_call(
    tmp_path: Path,
) -> None:
    """The same package with every lever off: the model's scripted part and mass checks run
    unmarked in a session with the record, and every finding they write is a code-only call
    (owner decision 41A; US1-12)."""
    session = review(tmp_path, "off", calls=OFF_ARM_CALLS, efficiency=OFF)

    assert session.origin_marks == 1
    assert marks_of(session) == [(call.name, None) for call in OFF_ARM_CALLS]
    assert session.findings
    assert cited_tools(session) == {call.name for call in OFF_ARM_CALLS}
    assert set(origins_of(session).values()) == {"code_only_call"}


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
        ("check_threads", "regrade"),
        ("check_rms_part", None),
    ]


RESTATED_CHECKS = {f"{name}.scripted" for name in roles.ROLE_TOOLS}
"""What the scripted role-reading checks write: the checks "All bought" restates."""


@pytest.mark.parametrize(
    ("efficiency", "first", "kept"),
    [(None, "code_only_call", set()), (CHECKS_FIRST, "prerun", {"prerun"})],
    ids=["checks-off", "checks-first"],
)
def test_a_finding_that_survives_all_bought_reads_regrade(
    tmp_path: Path,
    scripted_registry: None,
    efficiency: EfficiencySettings | None,
    first: Origin,
    kept: set[Origin],
) -> None:
    """US1-13: the regrade re-produces each of the plate's role-read findings under its earlier
    id, citing the restated step, so each reads `regrade`, whether the model or the pre-run
    first wrote it; the pin's are withdrawn. On checks first the pre-run's standards finding on
    the plate survives too, and since no answer restates its check it keeps its origin."""
    run = roles.graded(tmp_path, efficiency=efficiency)
    before = origins_of(run.session)
    plate = roles.ids_on(run, PLATE_ID)
    assert roles.ids_on(run, PIN_ID) and plate and set(before.values()) == {first}

    run.answer_evidence_batch(ALL_BOUGHT)

    after = origins_of(run.session)
    regraded = {item.id for item in run.session.findings if item.check in RESTATED_CHECKS}
    assert list(after) == plate
    assert regraded and {after[finding_id] for finding_id in regraded} == {"regrade"}
    assert {after[finding_id] for finding_id in plate if finding_id not in regraded} == kept
    assert all(after[finding_id] == before[finding_id] for finding_id in set(plate) - regraded)


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
