"""The report page and the reader it shares with the replay (feature 014 `contracts/report.md`).

`report.md` 9's rows, each named where it is pinned, over run folders the commands write: a
module builder, `scored_report_runs`, writes a keyless set of three fictional packages, runs it
twice with the scripted provider as a lever study's off and on arms, and scores each run.

- R-17 (T159): `read_recording`, the replay's view of a recorded review, reads its event log
  through the product's one event-line reader, `agent/events.replay_events` (plan decision
  RF-29), which is stricter than the line reader it replaces.
- R-1 and R-2 (T163): the index page, its counts the scorecards', its rows linking to transcripts
  that open with the recorded system prompt, and both run folders shown in study order.
- R-5, R-6, R-15 and R-16 (T164): a transcript, in the log's order, with what was sent.
- R-7 to R-14 (T165): packages through the saved set, no key read, no local path, the output
  folder, refusals, stored results and damaged streams, escaping and determinism.

The status and cost columns, failed attempts and R-3, R-4 and R-19 are the robustness slice's.
Every package, key, answer and name is fictional.
"""

from __future__ import annotations

import builtins
import gzip
import json
import os
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent import events
from swreview.agent.events import EVENTS_FILE_NAME, PACKED_EVENTS_FILE_NAME
from swreview.agent.providers import AgentEvent
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import REGRADED_LINE
from swreview.benchmark import compare, recording, report_page, scorecard
from swreview.benchmark.answers import ANSWER_LOG_FILE_NAME
from swreview.benchmark.origins import MODEL_ORIGINS
from swreview.benchmark.recording import RecordingRefused, read_recording
from swreview.benchmark.replay import TurnPlan
from swreview.benchmark.report_page import PROMPTS_FILE, build_report
from swreview.benchmark.runner import SAVED_SET_FILE
from swreview.benchmark.scorecard import PackageScore, read_scorecard
from swreview.checks.standards.profile import load_profile
from swreview.ir.loader import PACKAGE_FILE_NAME, AnswerKeyAccessError, load_package, save_package
from swreview.report.names import component_names
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME
from tests.support import local_paths, roles_review
from tests.support.answer_keys import write_key
from tests.support.packages import build_package
from tests.support.prerun import prerun_package
from tests.support.replay import record_scripted_review
from tests.support.scripted_answers import FIT, ask, case_file, turn
from tests.unit.test_benchmark_answers_roles import ALL_BOUGHT, FIT_ANSWER, PIN_1, PLATE_1
from tests.unit.test_replay_recording import SUMMARY

TESTS = Path(__file__).resolve().parents[1]
REPLAY_FIXTURES = sorted(
    path.parent for path in (TESTS / "fixtures" / "replay").glob("*/events.jsonl")
)


def recorded_run(tmp_path: Path) -> Path:
    """A scripted recorded review of one round, as `test_replay_recording.py` records one."""
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    return record_scripted_review(tmp_path / "run", package_dir, [TurnPlan(rounds=((SUMMARY,),))])


class ReaderSpy:
    """Wraps `replay_events` as `recording` calls it: each path it is given, and each number
    the reader reports to the hook `read_recording` passed."""

    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.reported: list[int] = []

    def __call__(self, path: Path | str, after: int = 0, **hooks: Any) -> Iterator[AgentEvent]:
        self.paths.append(Path(path))
        hook: Callable[[int], None] | None = hooks.get("on_unreadable")
        assert hook is not None, "read_recording passed no on_unreadable hook"

        def reported(number: int) -> None:
            self.reported.append(number)
            hook(number)

        return events.replay_events(path, after, on_unreadable=reported)


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> ReaderSpy:
    spy = ReaderSpy()
    monkeypatch.setattr(recording, "replay_events", spy)
    return spy


def refusal(folder: Path) -> str:
    with pytest.raises(RecordingRefused) as raised:
        read_recording(folder)
    message = str(raised.value)
    assert "\n" not in message
    return message


def _lines(folder: Path) -> int:
    """How many lines the folder's event log holds, its last line ended."""
    return len((folder / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines())


def _unreadable_sentence(folder: Path, number: int) -> str:
    return (
        f"{folder / EVENTS_FILE_NAME} line {number} is not a readable event (not JSON, or not an "
        "event of the chat-events schema), so the recorded rounds cannot be read"
    )


# --- R-17: read_recording on the one reader (T159) ------------------------------------------


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize(
    "line",
    ["{not json", '{"type": "usage", "body": {}}'],
    ids=["not-json", "not-an-agent-event"],
)
def test_r17_a_line_the_reader_cannot_read_is_refused_naming_the_log_and_its_line(
    tmp_path: Path, reader: ReaderSpy, line: str
) -> None:
    """The second line is JSON with a body object, which the old line reader accepted; it has no
    `seq` and no `at`, so it is no `AgentEvent`, and the stricter reader refuses it (`report.md`
    5). The number is the offending line's, 1-based, as the hook reports it."""
    folder = tmp_path / "broken"
    shutil.copytree(recorded_run(tmp_path), folder)
    number = _lines(folder) + 1
    with (folder / EVENTS_FILE_NAME).open("a", encoding="utf-8") as log:
        log.write(line + "\n")

    message = refusal(folder)

    assert message == _unreadable_sentence(folder, number)
    assert re.search(rf"\bline {number}\b", message)
    assert reader.paths == [folder / EVENTS_FILE_NAME]
    assert reader.reported == [number]


@pytest.mark.usefixtures("vocabulary")
def test_r17_a_log_with_no_usage_event_is_refused_in_its_sentence(
    tmp_path: Path, reader: ReaderSpy
) -> None:
    folder = tmp_path / "quiet"
    shutil.copytree(recorded_run(tmp_path), folder)
    log = folder / EVENTS_FILE_NAME
    kept = [
        line
        for line in log.read_text(encoding="utf-8").splitlines()
        if AgentEvent.model_validate_json(line).type != "usage"
    ]
    log.write_text("\n".join(kept) + "\n", encoding="utf-8")

    message = refusal(folder)

    assert message == (
        f"{log} records no usage event: no provider round was recorded, so there is nothing "
        "to price"
    )
    assert reader.paths == [log]
    assert reader.reported == []


@pytest.mark.usefixtures("vocabulary")
def test_r17_a_folder_with_no_package_is_refused_in_its_sentence(
    tmp_path: Path, reader: ReaderSpy
) -> None:
    folder = tmp_path / "nopackage"
    shutil.copytree(recorded_run(tmp_path), folder)
    (folder / PACKAGE_FILE_NAME).unlink()

    message = refusal(folder)

    assert message == (
        f"{folder} holds no {PACKAGE_FILE_NAME}: the replay re-runs the recorded calls against "
        "the package and cannot without it"
    )
    assert reader.paths == [folder / EVENTS_FILE_NAME]
    assert reader.reported == []


def test_there_are_committed_replay_fixtures_to_read() -> None:
    assert REPLAY_FIXTURES, "no tests/fixtures/replay/*/events.jsonl was found"


@pytest.mark.parametrize("folder", REPLAY_FIXTURES, ids=lambda folder: folder.name)
def test_r17_every_committed_replay_fixture_reads_through_the_one_reader_whole(
    folder: Path, reader: ReaderSpy
) -> None:
    read = read_recording(folder)

    assert reader.paths == [folder / EVENTS_FILE_NAME]
    assert reader.reported == []
    assert read.turns


# --- the shared builder: three scripted packages, a study's two arms, scored (T163) ----------

MARKUP = "<script>alert(1)</script>"
"""What a model text, a question and a tool result hold, to be shown as text (R-13)."""
FINDING_MARKUP = "<script>alert(x)</script>"
"""A drawing finding's markup: a drawing finding may carry no number the cited drawing does not
state (feature 007 FR-033), so its script holds none."""

ROLES = "fict-roles"
CASE_A, CASE_B = "fict-a", "fict-b"
PACKAGES = (CASE_A, CASE_B, ROLES)
LEVER = "trim_tool_descriptions"
"""The study the two arms are: a lever with no effect on what a scripted review does."""

DRAWING_FINDING = ScriptedToolCall(
    "record_drawing_finding",
    {
        "document_id": "doc:2",
        "sheet": "Sheet",
        "observed": f"The callout reads {FINDING_MARKUP}",
        "requirement": "A tapped hole callout states the usable thread depth",
        "source_refs": [{"document_id": "doc:2", "sheet": "Sheet"}],
        "status": "suspected",
        "recommended_action": "Add the tapped depth to the hole callout",
    },
)


def scripts() -> dict[str, list[ScriptedTurn]]:
    """Each package's scripted model: calls whose results are stored, a question per request,
    text, and in `fict-a` a tool result and a text holding markup. The roles package's model
    asks two questions in its first answer turn; the case file answers the first."""
    return {
        CASE_A: [
            turn(
                ScriptedToolCall("get_package_summary"),
                DRAWING_FINDING,
                ask("cmp:0001", what=f"What does {MARKUP} mean?"),
                text=f"Reviewed {MARKUP}.",
            )
        ],
        CASE_B: [turn(ScriptedToolCall("get_package_summary"), text="Reviewed.")],
        ROLES: [
            turn(
                ScriptedToolCall("check_rms_part"), ScriptedToolCall("check_hygiene"), text="Read."
            ),
            turn(ask(PLATE_1, PIN_1, item=FIT), ask(PIN_1), text="Two questions."),
            turn(text="Noted."),
        ],
    }


@dataclass(frozen=True)
class Runs:
    """What `scored_report_runs` wrote: the off and on run folders and their inputs."""

    off: Path
    on: Path
    packages: Path
    keys: Path
    profile: Path


def write_keys(keys: Path) -> None:
    """A held-out model-produced defect the drawing finding credits and a code-produced one it
    misses (`fict-a`); a tuned-on model-produced defect a restated check credits, a correct
    condition, and forbidden entries a scripted finding hits and a withdrawn one hits (roles);
    `fict-b`'s key grades no held-out item."""
    write_key(
        keys,
        CASE_A,
        known_defects=[
            {"check": "drawing.manufacturing_inputs", "document_ids": ["doc:2"], "tag": "held_out"},
            {
                "check": "rms.folders.present",
                "document_ids": ["doc:1"],
                "producer": "code",
                "expected_status": "unresolved",
            },
        ],
    )
    write_key(
        keys,
        CASE_B,
        known_defects=[{"check": "hygiene.revision_present", "document_ids": ["doc:1"]}],
    )
    write_key(
        keys,
        ROLES,
        known_defects=[{"check": "rms.folders.present", "component_ids": [PLATE_1]}],
        correct_conditions=[{"check": "hygiene.revision_present", "document_ids": ["doc:0003"]}],
        forbidden=[
            {"checks": ["hygiene.part_number_matches_file"], "component_ids": [PLATE_1]},
            {"checks": ["hygiene.*"], "component_ids": [PIN_1]},
        ],
    )


def scored_report_runs(folder: Path) -> Runs:
    """Write the set, run it with `CliRunner` as the lever study's off and on arms with the
    scripted provider, and score each run with `--answer-keys`."""
    packages = folder / "packages"
    for package_id in (CASE_A, CASE_B):
        save_package(build_package(), packages / package_id)
    roles_dir = roles_review.write_package(packages / ROLES)
    profile = roles_review.write_profile(folder)
    case_file(
        folder / "case_files",
        ROLES,
        ALL_BOUGHT,
        FIT_ANSWER,
        package=load_package(roles_dir).package,
        profile=load_profile(profile),
    )
    set_path = folder / "set.json"
    entries = [
        {"package_id": CASE_A, "path": str(packages / CASE_A), "held_out": True},
        {"package_id": CASE_B, "path": str(packages / CASE_B)},
        {
            "package_id": ROLES,
            "path": str(roles_dir),
            "case_file": str(folder / "case_files" / f"{ROLES}.json"),
        },
    ]
    set_path.write_text(json.dumps({"name": "report", "packages": entries}), encoding="utf-8")
    keys = folder / "answer_keys"
    write_keys(keys)
    runs: dict[str, Path] = {}
    with pytest.MonkeyPatch.context() as patch:
        queue: list[list[ScriptedTurn]] = []

        def factory(settings: Any, efficiency: Any = None) -> FakeProvider:
            return FakeProvider(script=queue.pop(0), model=settings.model)

        patch.setattr(cli, "provider_factory", factory)
        for arm in ("off", "on"):
            queue[:] = [scripts()[package_id] for package_id in PACKAGES]
            run = folder / "runs" / arm
            options = ["--lever", LEVER] if arm == "on" else []
            result = CliRunner().invoke(
                cli.app,
                [
                    "benchmark",
                    "run",
                    "--set",
                    str(set_path),
                    "--out",
                    str(run),
                    "--provider",
                    "fake",
                    "--standards-profile",
                    str(profile),
                    "--study",
                    LEVER,
                    "--arm",
                    arm,
                    "--rep",
                    "1",
                    *options,
                ],
            )
            assert result.exit_code == 0, result.stdout + result.stderr
            scored = CliRunner().invoke(
                cli.app, ["benchmark", "score", str(run), "--answer-keys", str(keys)]
            )
            assert scored.exit_code == 0, scored.stdout + scored.stderr
            runs[arm] = run
    return Runs(off=runs["off"], on=runs["on"], packages=packages, keys=keys, profile=profile)


@pytest.fixture(scope="module")
def report_runs(tmp_path_factory: pytest.TempPathFactory) -> Runs:
    return scored_report_runs(tmp_path_factory.mktemp("report"))


def copy_run(run: Path, to: Path) -> Path:
    shutil.copytree(run, to)
    return to


# --- reading a page back -------------------------------------------------------------------

BLOCKS = frozenset({"h1", "h2", "h3", "h4", "p", "pre", "li", "summary", "td", "th"})


@dataclass
class Table:
    heading: str
    rows: list[list[str]] = field(default_factory=list)
    links: list[list[str]] = field(default_factory=list)
    """Each row's hrefs."""


class Page(HTMLParser):
    """A page as the standard library's parser reads it: its tags, its metadata, its links, its
    text blocks in document order, and its tables under the heading before them."""

    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.raw = path.read_bytes().decode("utf-8")
        self.tags: list[str] = []
        self.meta: dict[str, str] = {}
        self.hrefs: list[str] = []
        self.blocks: list[tuple[str, str]] = []
        self.tables: list[Table] = []
        self._open: list[tuple[str, int]] = []
        self._heading = ""
        self._row: list[str] | None = None
        self._row_links: list[str] = []
        self.feed(self.raw)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        values = dict(attrs)
        if tag == "meta" and values.get("name"):
            self.meta[str(values["name"])] = str(values.get("content"))
        if tag == "a" and values.get("href") is not None:
            self.hrefs.append(str(values["href"]))
            self._row_links.append(str(values["href"]))
        if tag == "table":
            self.tables.append(Table(heading=self._heading))
        if tag == "tr":
            self._row, self._row_links = [], []
        if tag in BLOCKS:
            self.blocks.append((tag, ""))
            self._open.append((tag, len(self.blocks) - 1))

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCKS and self._open and self._open[-1][0] == tag:
            _, index = self._open.pop()
            text = self.blocks[index][1]
            if tag in ("h2", "h3"):
                self._heading = text
            if tag in ("td", "th") and self._row is not None:
                self._row.append(text)
        if tag == "tr" and self._row is not None:
            self.tables[-1].rows.append(self._row)
            self.tables[-1].links.append(self._row_links)
            self._row = None

    def handle_data(self, data: str) -> None:
        for _, index in self._open:
            tag, text = self.blocks[index]
            self.blocks[index] = (tag, text + data)

    def texts(self, tag: str) -> list[str]:
        return [text for name, text in self.blocks if name == tag]

    def table(self, heading: str) -> Table:
        [table] = [table for table in self.tables if table.heading == heading]
        return table

    def index_of(self, tag: str, text: str, start: int = 0) -> int:
        """The first block at or after `start` with this tag and exactly this text."""
        for index in range(start, len(self.blocks)):
            if self.blocks[index] == (tag, text):
                return index
        raise AssertionError(f"no <{tag}> {text!r} after block {start} in {self.path}")


def assert_static(page: Page) -> None:
    """No script, no external resource, one style block, the generator tag."""
    assert "script" not in page.tags
    assert "http:" not in page.raw and "https:" not in page.raw
    assert page.tags.count("style") == 1
    assert page.meta.get("generator") == "swreview benchmark report"


# --- R-1 and R-2: the index page (T163) ----------------------------------------------------


def _keyed(score: PackageScore, tag: str | None, producer: str) -> list[str]:
    return [
        item.id
        for item in score.graded_items
        if item.kind == "known_defect"
        and item.producer == producer
        and (tag is None or item.tag == tag)
    ]


def _detected_of(score: PackageScore, keyed: list[str]) -> str:
    count = compare.format_count
    detected = [item for item in keyed if item in score.matched_defect_ids]
    return f"{count(len(detected))} of {count(len(keyed))} detected"


def expected_cells(score: PackageScore, reasoning: str) -> list[str]:
    """A case row's outcome, false-alarm, token and wall-clock cells, counted from the score's
    own id lists and `graded_items` (SP-14)."""
    count = compare.format_count
    held = _keyed(score, "held_out", "model")
    if held:
        below = [item for item in held if item in score.flagged_below_expected_defect_ids]
        cleared = [item for item in held if item in score.cleared_defect_ids]
        held_cell = (
            f"{_detected_of(score, held)}; {count(len(below))} flagged below expected; "
            f"{count(len(cleared))} cleared"
        )
    else:
        held_cell = "not assessed"
    code, tuned = _keyed(score, None, "code"), _keyed(score, "tuned_on", "model")
    deciding = [
        finding
        for finding in score.false_alarm_finding_ids
        if score.finding_origins[finding] in MODEL_ORIGINS
        and finding not in score.tuned_on_false_alarm_finding_ids
    ]
    others: dict[str, int] = {}
    for finding in score.false_alarm_finding_ids:
        if finding not in deciding:
            label = score.finding_origins[finding]
            if finding in score.tuned_on_false_alarm_finding_ids:
                label += ", tuned-on"
            others[label] = others.get(label, 0) + 1
    alarms = f"{count(len(deciding))} deciding; " + (
        "others: " + ", ".join(f"{label} {count(n)}" for label, n in sorted(others.items()))
        if others
        else "no others"
    )
    usage = score.usage
    assert usage is not None
    tokens = (
        f"input {count(usage.input_tokens)}; cached input {count(usage.cached_input_tokens)}; "
        f"output {count(usage.output_tokens)}; {reasoning} {count(usage.reasoning_tokens)}; "
        f"cache-write {count(usage.cache_write_tokens)}"
    )
    return [
        held_cell,
        _detected_of(score, code) if code else "not assessed",
        _detected_of(score, tuned) if tuned else "not assessed",
        alarms,
        tokens,
        count(score.wall_clock_s),
    ]


@pytest.fixture(scope="module")
def off_report(report_runs: Runs, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("off-report") / "report"
    build_report([report_runs.off], out)
    return out


def test_r1_the_page_is_static_and_every_count_is_the_scorecard_s(
    report_runs: Runs, off_report: Path
) -> None:
    """User Story 6's independent test: three cases, every count its scorecard's, no cell 0 or
    blank unless measured, a column the key does not grade `not assessed`."""
    page = Page(off_report / "index.html")
    assert_static(page)
    card = read_scorecard(report_runs.off)
    assert [score.package_id for score in card.per_package] == list(PACKAGES)
    for score in card.per_package:
        [row] = page.table(score.package_id).rows[1:]
        assert row[0] == "off, arm off, repetition 1"
        assert row[1:7] == expected_cells(score, "reasoning")
        assert row[7] == "transcript"
        assert all(cell.strip() for cell in row)
    by_id = {score.package_id: score for score in card.per_package}
    assert page.table(CASE_A).rows[1][1:4] == [
        "1 of 1 detected; 0 flagged below expected; 0 cleared",
        "0 of 1 detected",
        "not assessed",
    ]
    assert page.table(CASE_B).rows[1][1] == "not assessed"
    assert by_id[ROLES].forbidden_hit_finding_ids, "the roles key's forbidden entry is hit"


def test_r1_the_totals_are_the_scorer_s_sums(report_runs: Runs, off_report: Path) -> None:
    card = read_scorecard(report_runs.off)
    page = Page(off_report / "index.html")
    seconds = scorecard.sum_or_none([score.wall_clock_s for score in card.per_package])

    assert page.table("Totals").rows[1] == [
        "off",
        "3",
        compare.format_count(card.aggregate.total_tokens),
        compare.format_count(seconds),
    ]


def test_r1_every_row_links_to_a_transcript_that_opens_with_the_recorded_system_prompt(
    report_runs: Runs, off_report: Path
) -> None:
    page = Page(off_report / "index.html")
    links = [href for href in page.hrefs if href.startswith("transcripts/")]
    assert links == [f"transcripts/off/{package_id}.html" for package_id in PACKAGES]
    for package_id, href in zip(PACKAGES, links, strict=True):
        transcript = Page(off_report / href)
        record = json.loads((report_runs.off / package_id / PROMPTS_FILE).read_bytes())
        first = transcript.texts("h2")[0]
        assert first == "The system prompt as sent"
        assert transcript.texts("pre")[0] == record["system"]
        assert_static(transcript)


def test_r1_the_report_shares_the_ledger_s_number_rule_and_the_scorer_s_sum() -> None:
    """Imported, never restated (`report.md` 4)."""
    assert report_page.format_count is compare.format_count
    assert report_page.sum_or_none is scorecard.sum_or_none


def _head(page: Page) -> list[list[str]]:
    return page.table("Run folders").rows[1:]


def test_r2_both_arms_appear_in_the_head_and_in_each_case_in_study_order(
    report_runs: Runs, tmp_path: Path
) -> None:
    """US6-1: the on arm named first still lists after the off arm in each case."""
    out = tmp_path / "report"
    build_report([report_runs.on, report_runs.off], out)

    page = Page(out / "index.html")
    on, off = (
        json.loads((run / "run-provenance.json").read_bytes())
        for run in (
            report_runs.on,
            report_runs.off,
        )
    )
    assert _head(page) == [
        [
            name,
            LEVER,
            record["arm"],
            "1",
            "fake",
            record["model"],
            str(record["commit"]) if record["commit"] is not None else "unknown",
            record["started_at"].replace("Z", "+00:00"),
        ]
        for name, record in (("on", on), ("off", off))
    ]
    assert page.texts("h2")[2:] == list(PACKAGES)
    for package_id in PACKAGES:
        rows = page.table(package_id).rows[1:]
        assert [row[0] for row in rows] == [
            "off, arm off, repetition 1",
            "on, arm on, repetition 1",
        ]


def test_r2_a_run_folder_with_no_provenance_reads_unknown_and_is_not_refused(
    report_runs: Runs, tmp_path: Path
) -> None:
    bare = copy_run(report_runs.off, tmp_path / "runs" / "bare")
    (bare / "run-provenance.json").unlink()
    out = tmp_path / "report"

    build_report([bare], out)

    page = Page(out / "index.html")
    assert _head(page) == [["bare", *["unknown"] * 7]]
    assert page.table(CASE_A).rows[1][0] == "bare, arm unknown, repetition unknown"


def test_r2_cases_follow_the_first_saved_set_then_a_later_one(
    report_runs: Runs, tmp_path: Path
) -> None:
    """The first run folder's saved set names `fict-a` no more: its case comes after the cases
    it does name, from the later folder's saved set."""
    first = copy_run(report_runs.off, tmp_path / "runs" / "first")
    saved = json.loads((first / SAVED_SET_FILE).read_bytes())
    saved["packages"] = [entry for entry in saved["packages"] if entry["package_id"] != CASE_A]
    (first / SAVED_SET_FILE).write_text(json.dumps(saved), encoding="utf-8")
    out = tmp_path / "report"

    build_report([first, report_runs.on], out)

    assert Page(out / "index.html").texts("h2")[2:] == [CASE_B, ROLES, CASE_A]


# --- R-5, R-6, R-15 and R-16: a transcript (T164) ------------------------------------------


def transcript(out: Path, run: str, package_id: str) -> Page:
    return Page(out / "transcripts" / run / f"{package_id}.html")


def stream(run: Path, package_id: str) -> list[AgentEvent]:
    return list(events.replay_events(run / package_id / EVENTS_FILE_NAME))


def prompts(run: Path, package_id: str) -> dict[str, Any]:
    return json.loads((run / package_id / PROMPTS_FILE).read_bytes())


def question(run: Path, request_id: str) -> str:
    session = json.loads((run / ROLES / "session.json").read_bytes())
    [request] = [item for item in session["evidence_requests"] if item["id"] == request_id]
    return request.get("question") or request["what"]


def test_r5_the_roles_transcript_reads_in_the_log_s_order(
    report_runs: Runs, off_report: Path
) -> None:
    """US6-2: the system prompt, the legend, the code before the first turn, then each turn
    opening with its message as sent; each answer turn's engineer's turn, its answers and the
    request given nothing at its point; the regrade's restated calls before the turn's first
    round; and the third point's request on its own after the last turn."""
    page = transcript(off_report, "off", ROLES)
    sent = prompts(report_runs.off, ROLES)
    run = report_runs.off

    system = page.index_of("pre", sent["system"])
    legend = page.index_of("h2", "Component names", system)
    code = page.index_of("h3", "Code before the first turn", legend)
    turns = [page.index_of("h3", f"Turn {number}", code) for number in range(3)]
    assert system < legend < code < turns[0] < turns[1] < turns[2]
    for number, start in enumerate(turns):
        assert page.blocks[start + 1] == ("pre", sent["user_messages"][number])

    engineer_1 = page.index_of("h4", "The engineer's turn", turns[1])
    answered_1 = page.index_of(
        "p", f"ER-001 ({question(run, 'ER-001')}): answered All bought", engineer_1
    )
    restated = next(
        index
        for index in range(answered_1, turns[2])
        if page.blocks[index][0] == "p" and page.blocks[index][1].startswith("Step ")
    )
    first_round_1 = page.index_of("h4", "Round 1", turns[1])
    assert turns[1] < engineer_1 < answered_1 < restated < first_round_1 < turns[2]
    assert page.blocks[restated][1].startswith("Step 2: check_rms_part ")

    engineer_2 = page.index_of("h4", "The engineer's turn", turns[2])
    answered_2 = page.index_of(
        "p", f"ER-002 ({question(run, 'ER-002')}): answered press fit", engineer_2
    )
    unscripted = f"ER-003 ({question(run, 'ER-003')}): given nothing, no_answer"
    given_nothing_2 = page.index_of("li", unscripted, answered_2)
    assert given_nothing_2 < page.index_of("h4", "Round 1", turns[2])
    after = page.index_of("h4", "After turn 2: given nothing", given_nothing_2)
    assert page.index_of("li", unscripted, after) > after


def test_r5_each_call_shows_its_tool_arguments_status_summary_and_full_result(
    report_runs: Runs, off_report: Path
) -> None:
    page = transcript(off_report, "off", ROLES)
    log = stream(report_runs.off, ROLES)
    finished = {
        event.body["step_index"]: event.body for event in log if event.type == "tool.finished"
    }
    started = [event.body for event in log if event.type == "tool.started"]
    steps = [text for tag, text in page.blocks if tag == "p" and text.startswith("Step ")]
    expected = []
    for body in started:
        end = finished[body["step_index"]]
        arguments = json.dumps(body.get("arguments") or {}, ensure_ascii=False)
        expected.append(
            f"Step {body['step_index']}: {body['tool']} {arguments}: "
            f"{end['status']}: {end['result_summary']}"
        )
    assert steps == expected
    assert page.texts("summary").count("full result") == len(started)
    findings = [event.body for event in log if event.type == "finding"]
    first = findings[0]
    assert (
        f"finding {first['id']} ({first['check']}, {first['status']}): {first['title']}"
        in page.texts("li")
    )


def test_r5_rounds_texts_questions_coverage_ends_and_other_events(
    report_runs: Runs, off_report: Path
) -> None:
    """Each `usage` a round marker with its tokens; `text.done` shown once and `text.delta`
    never; `evidence.requested` shown; coverage rows collapsed per turn; each turn's end; and
    every other event type one line where the log puts it."""
    page = transcript(off_report, "off", ROLES)
    log = stream(report_runs.off, ROLES)

    rounds = [
        index
        for index, block in enumerate(page.blocks)
        if block[0] == "h4" and block[1].startswith("Round ")
    ]
    assert len(rounds) == sum(1 for event in log if event.type == "usage")
    assert all(page.blocks[index + 1][1].startswith("input ") for index in rounds)
    assert page.texts("pre").count("Two questions.") == 1
    assert any(text.startswith("Question ER-002: ") for text in page.texts("p"))
    turns_with_coverage = 0
    segment: list[str] = []
    for event in log:
        segment.append(event.type)
        if event.type == "turn.ended":
            turns_with_coverage += "coverage" in segment
            segment = []
    turns_with_coverage += "coverage" in segment
    summaries = [text for text in page.texts("summary") if text.startswith("coverage rows (")]
    assert len(summaries) == turns_with_coverage
    assert page.texts("p").count("The turn ended: end") == 3
    for kind in ("session.started", "session.ended", "coverage.withdrawn"):
        assert any(text.startswith(f"{kind}: ") for text in page.texts("p")), kind


def test_r5_an_explanation_pass_round_is_named_so(report_runs: Runs, tmp_path: Path) -> None:
    """A `usage` after the turn's `text.done` is the explanation pass (the rule
    `_EventReader._usage` applies); the copy's log gains one after turn 0's text."""
    run = copy_run(report_runs.off, tmp_path / "runs" / "explained")
    log = run / ROLES / EVENTS_FILE_NAME
    lines = log.read_text(encoding="utf-8").splitlines()
    usage = next(line for line in lines if AgentEvent.model_validate_json(line).type == "usage")
    text_done = next(
        index
        for index, line in enumerate(lines)
        if AgentEvent.model_validate_json(line).type == "text.done"
    )
    lines.insert(text_done + 1, usage)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "report"

    build_report([run], out)

    page = transcript(out, "explained", ROLES)
    turn_1 = page.index_of("h3", "Turn 1")
    named = page.index_of("h4", "Round 2: explanation pass")
    assert named < turn_1


def test_r5_the_final_state_grades_every_finding_from_the_scorecard_s_lists(
    report_runs: Runs, off_report: Path
) -> None:
    page = transcript(off_report, "off", ROLES)
    [score] = [s for s in read_scorecard(report_runs.off).per_package if s.package_id == ROLES]
    session = json.loads((report_runs.off / ROLES / "session.json").read_bytes())

    rows = page.table("Findings").rows[1:]
    assert [row[0] for row in rows] == [finding["id"] for finding in session["findings"]]
    for row in rows:
        finding = row[0]
        grading = []
        if finding in score.false_alarm_finding_ids:
            deciding = (
                score.finding_origins[finding] in MODEL_ORIGINS
                and finding not in score.tuned_on_false_alarm_finding_ids
            )
            grading.append("false alarm, deciding" if deciding else "false alarm")
        if finding in (score.forbidden_hit_finding_ids or []):
            grading.append("forbidden hit")
        if finding in score.tuned_on_false_alarm_finding_ids:
            grading.append("tuned-on")
        assert row[3] == score.finding_origins[finding]
        assert row[4] == ("; ".join(grading) or "none")
    assert "forbidden hit" in " ".join(row[4] for row in rows)

    assert page.table("Known defects").rows[1:] == [
        ["D-1", "tuned_on", "model", "suspected", "credited"]
    ]
    assert page.table("Correct conditions").rows[1:] == [["C-1", "neither"]]
    withdrawn = [
        event.body for event in stream(report_runs.off, ROLES) if event.type == "finding.withdrawn"
    ]
    hits = score.withdrawn_forbidden_hit_finding_ids
    assert hits, "the roles key's pin entry is hit by a withdrawn finding"
    assert page.table("Withdrawn findings").rows[1:] == [
        [body["finding_id"], body["reason"], "yes" if body["finding_id"] in hits else "no"]
        for body in withdrawn
    ]


def test_r15_a_transcript_places_each_recorded_message_at_its_turn_byte_for_byte(
    report_runs: Runs, off_report: Path
) -> None:
    """The answer turn's message as composed by code, the regrade line included."""
    page = transcript(off_report, "off", ROLES)
    sent = prompts(report_runs.off, ROLES)

    assert page.texts("pre")[0] == sent["system"]
    messages = [page.blocks[page.index_of("h3", f"Turn {k}") + 1][1] for k in range(3)]
    assert messages == sent["user_messages"]
    assert REGRADED_LINE.split("{", 1)[0] in messages[1]


def test_r6_a_folder_written_before_the_record_reads_not_recorded(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "runs" / "older")
    for record in run.rglob(PROMPTS_FILE):
        record.unlink()
    out = tmp_path / "report"

    build_report([run], out)

    page = transcript(out, "older", ROLES)
    assert page.blocks[page.index_of("h2", "The system prompt as sent") + 1] == (
        "p",
        "not recorded",
    )
    for number in range(3):
        assert page.blocks[page.index_of("h3", f"Turn {number}") + 1] == ("pre", "not recorded")


def test_r6_a_record_that_does_not_validate_reads_unreadable_and_is_not_refused(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "runs" / "damaged")
    (run / ROLES / PROMPTS_FILE).write_bytes(b'{"prompts_version": 1, "system": "S"}\n')
    out = tmp_path / "report"

    build_report([run], out)

    page = transcript(out, "damaged", ROLES)
    unreadable = "the prompts record is unreadable"
    assert page.blocks[page.index_of("h2", "The system prompt as sent") + 1] == ("p", unreadable)
    for number in range(3):
        assert page.blocks[page.index_of("h3", f"Turn {number}") + 1] == ("pre", unreadable)


def test_r16_an_abandoned_attempt_s_record_shows_its_opening_and_nothing_after(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "runs" / "abandoned")
    sent = prompts(run, ROLES)
    sent["user_messages"] = sent["user_messages"][:1]
    (run / ROLES / PROMPTS_FILE).write_text(json.dumps(sent), encoding="utf-8")
    out = tmp_path / "report"

    build_report([run], out)

    page = transcript(out, "abandoned", ROLES)
    assert page.blocks[page.index_of("h3", "Turn 0") + 1] == ("pre", sent["user_messages"][0])
    for number in (1, 2):
        assert page.blocks[page.index_of("h3", f"Turn {number}") + 1] == ("pre", "not recorded")


# --- R-7 to R-14: paths, refusals, stored results, escaping, determinism (T165) -------------


def legend(page: Page) -> list[list[str]] | str:
    """The legend's rows, or the one line saying why there is none."""
    start = page.index_of("h2", "Component names")
    tag, text = page.blocks[start + 1]
    if tag == "p":
        return text
    return page.table("Component names").rows[1:]


def names_of(package_dir: Path) -> list[list[str]]:
    return [[k, v] for k, v in component_names(load_package(package_dir).package).items()]


def checkout_with(report_runs: Runs, tmp_path: Path) -> tuple[Path, Path]:
    """A temporary checkout holding `fict-a` at `benchmarks/packages/fict-a`, and a copy of the
    off run whose saved set names it repository-relative."""
    root = tmp_path / "checkout"
    shutil.copytree(report_runs.packages / CASE_A, root / "benchmarks" / "packages" / CASE_A)
    run = copy_run(report_runs.off, tmp_path / "runs" / "relative")
    saved = json.loads((run / SAVED_SET_FILE).read_bytes())
    for entry in saved["packages"]:
        if entry["package_id"] == CASE_A:
            entry["path"] = f"benchmarks/packages/{CASE_A}"
    (run / SAVED_SET_FILE).write_text(json.dumps(saved), encoding="utf-8")
    return root, run


def test_r7_a_repository_relative_entry_resolves_against_the_checkout_from_any_copy(
    report_runs: Runs, tmp_path: Path
) -> None:
    root, run = checkout_with(report_runs, tmp_path)
    moved = copy_run(run, tmp_path / "elsewhere" / "moved")
    expected = names_of(root / "benchmarks" / "packages" / CASE_A)
    assert expected

    for folder in (run, moved):
        out = tmp_path / "reports" / folder.name
        build_report([folder], out, root=root)
        assert legend(transcript(out, folder.name, CASE_A)) == expected


def test_r7_an_absolute_entry_is_used_as_written(report_runs: Runs, off_report: Path) -> None:
    assert legend(transcript(off_report, "off", ROLES)) == names_of(report_runs.packages / ROLES)


def test_r7_a_missing_package_leaves_the_legend_out_naming_the_path_as_saved(
    report_runs: Runs, tmp_path: Path
) -> None:
    root, run = checkout_with(report_runs, tmp_path)
    shutil.rmtree(root / "benchmarks" / "packages" / CASE_A)
    out = tmp_path / "report"

    build_report([run], out, root=root)

    assert legend(transcript(out, "relative", CASE_A)) == (
        f"the package at benchmarks/packages/{CASE_A} does not load, so no component names "
        "are shown"
    )
    assert legend(transcript(out, "relative", CASE_B)) == names_of(report_runs.packages / CASE_B)


def test_r7_a_run_folder_with_no_saved_set_shows_no_legend_and_says_why(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "runs" / "unsaved")
    (run / SAVED_SET_FILE).unlink()
    out = tmp_path / "report"

    build_report([run], out)

    for package_id in PACKAGES:
        assert legend(transcript(out, "unsaved", package_id)) == (
            "the run folder holds no saved set, so no component names are shown"
        )


def test_r7_a_saved_set_naming_a_key_path_is_refused_with_the_key_guard_s_message(
    report_runs: Runs, tmp_path: Path
) -> None:
    root, run = checkout_with(report_runs, tmp_path)
    saved = json.loads((run / SAVED_SET_FILE).read_bytes())
    saved["packages"][0]["path"] = f"benchmarks/answer_keys/{CASE_A}"
    (run / SAVED_SET_FILE).write_text(json.dumps(saved), encoding="utf-8")
    out = tmp_path / "report"

    with pytest.raises(AnswerKeyAccessError, match="answer_keys"):
        build_report([run], out, root=root)
    assert not out.exists()


class Opened:
    """Every path opened through `Path.open`, `Path.read_text`, `Path.read_bytes`,
    `builtins.open` and `gzip.open`, resolved."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.paths: list[Path] = []
        for owner, name in (
            (Path, "open"),
            (Path, "read_text"),
            (Path, "read_bytes"),
            (builtins, "open"),
            (gzip, "open"),
        ):
            monkeypatch.setattr(owner, name, self._spy(getattr(owner, name)))

    def _spy(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def spied(file: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(file, str | os.PathLike):
                self.paths.append(Path(file).resolve())
            return real(file, *args, **kwargs)

        return spied


def test_r8_the_report_opens_no_key_and_no_case_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over its own one-package keyed run, scored with no `--answer-keys` (T120, T121)."""
    profile = roles_review.write_profile(tmp_path)
    package_dir = roles_review.write_package(tmp_path / "packages" / ROLES)
    case = tmp_path / "private" / "case_files" / f"{ROLES}.json"
    case_file(
        case.parent,
        ROLES,
        ALL_BOUGHT,
        package=load_package(package_dir).package,
        profile=load_profile(profile),
    )
    keys = tmp_path / "private" / "keys"
    write_key(
        keys, ROLES, known_defects=[{"check": "rms.folders.present", "component_ids": [PLATE_1]}]
    )
    key = keys / f"{ROLES}.json"
    set_path = tmp_path / "keyed.json"
    entry = {"package_id": ROLES, "path": str(package_dir), "key": str(key), "case_file": str(case)}
    set_path.write_text(json.dumps({"name": "keyed", "packages": [entry]}), encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "provider_factory",
        lambda settings, efficiency=None: FakeProvider(
            script=[turn(ScriptedToolCall("check_rms_part")), turn(text="Noted.")],
            model=settings.model,
        ),
    )
    run = tmp_path / "runs" / "keyed"
    result = CliRunner().invoke(
        cli.app,
        [
            "benchmark",
            "run",
            "--set",
            str(set_path),
            "--out",
            str(run),
            "--provider",
            "fake",
            "--standards-profile",
            str(profile),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    scored = CliRunner().invoke(cli.app, ["benchmark", "score", str(run)])
    assert scored.exit_code == 0, scored.stdout + scored.stderr
    opened = Opened(monkeypatch)

    build_report([run], tmp_path / "report")

    assert opened.paths
    withheld = [
        path for path in opened.paths if "answer_keys" in path.parts or "case_files" in path.parts
    ]
    assert withheld == []
    assert key.resolve() not in opened.paths and case.resolve() not in opened.paths


def test_r9_the_output_holds_no_local_path_and_every_link_is_relative(off_report: Path) -> None:
    """FR-051's test, over every file the build wrote. The scanner reads one thing that is no
    path as a rooted one: the closing tag of R-13's planted markup, escaped (`&lt;/script&gt;`),
    which names no folder; every other offence fails the test."""
    offences = local_paths.scan_folder(off_report)
    markup = [
        offence
        for offence in offences
        if offence.reason == local_paths.ROOTED_PATH and offence.text.startswith("/script&gt")
    ]
    assert markup, "the planted markup is in the transcripts"
    assert [offence for offence in offences if offence not in markup] == []
    for page_path in off_report.rglob("*.html"):
        for href in Page(page_path).hrefs:
            assert not href.startswith("/") and ":" not in href, (page_path, href)


def report(*arguments: str) -> Any:
    return CliRunner().invoke(cli.app, ["benchmark", "report", *arguments])


def snapshot(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }


def one_line(result: Any) -> str:
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1, result.stderr
    return lines[0]


def test_r10_out_and_a_run_folder_are_required(report_runs: Runs, tmp_path: Path) -> None:
    assert report(str(report_runs.off)).exit_code == 2
    assert report("--out", str(tmp_path / "report")).exit_code == 2
    assert not (tmp_path / "report").exists()


def test_r10_an_absent_or_empty_folder_is_written_and_no_run_folder_changes(
    report_runs: Runs, tmp_path: Path
) -> None:
    before = snapshot(report_runs.off)
    empty = tmp_path / "empty"
    empty.mkdir()

    for out in (tmp_path / "absent" / "report", empty):
        result = report(str(report_runs.off), "--out", str(out))
        assert result.exit_code == 0, result.stdout + result.stderr
        assert result.stdout.strip() == f"wrote {out / 'index.html'} (3 transcripts)"
        assert (out / "transcripts" / "off" / f"{CASE_A}.html").is_file()

    assert snapshot(report_runs.off) == before


def test_r10_a_previous_report_is_replaced_and_its_stale_transcripts_are_gone(
    report_runs: Runs, tmp_path: Path
) -> None:
    out = tmp_path / "report"
    assert report(str(report_runs.off), "--out", str(out)).exit_code == 0
    stale = out / "transcripts" / "gone" / "old.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    result = report(str(report_runs.on), "--out", str(out))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert not stale.exists()
    assert not (out / "transcripts" / "off").exists()
    assert (out / "transcripts" / "on" / f"{CASE_A}.html").is_file()

    shutil.rmtree(out / "transcripts")
    assert report(str(report_runs.off), "--out", str(out)).exit_code == 0, "index alone"


@pytest.mark.parametrize("beside_a_report", [False, True], ids=["alone", "beside-a-report"])
def test_r10_a_folder_holding_anything_else_is_refused_and_left_as_it_was(
    report_runs: Runs, tmp_path: Path, beside_a_report: bool
) -> None:
    out = tmp_path / "report"
    if beside_a_report:
        assert report(str(report_runs.off), "--out", str(out)).exit_code == 0
    out.mkdir(exist_ok=True)
    (out / "notes.txt").write_text("the engineer's notes", encoding="utf-8")
    before = snapshot(out)

    result = report(str(report_runs.off), "--out", str(out))

    assert result.exit_code == 1
    assert one_line(result) == (
        f"error: ReportError: {out} holds files this command did not write; choose an empty folder"
    )
    assert snapshot(out) == before


def test_r11_a_run_folder_with_no_scorecard_is_refused_naming_benchmark_score(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "unscored")
    (run / "scorecard.json").unlink()
    out = tmp_path / "report"

    result = report(str(run), "--out", str(out))

    assert result.exit_code == 1
    assert one_line(result) == (
        f"error: ReportError: {run}: no scorecard.json; run `swreview benchmark score` on it first"
    )
    assert not out.exists()


def test_r11_a_scorecard_under_older_rules_meets_the_re_score_line(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "older")
    card = json.loads((run / "scorecard.json").read_bytes())
    card["scoring_rules_version"] = 1
    (run / "scorecard.json").write_text(json.dumps(card), encoding="utf-8")
    out = tmp_path / "report"
    with pytest.raises(ValueError) as expected:
        read_scorecard(run)

    result = report(str(run), "--out", str(out))

    assert result.exit_code == 1
    assert one_line(result) == f"error: {cli._one_line(expected.value)}"
    assert "Re-score it: swreview benchmark score" in one_line(result)
    assert not out.exists()


def test_r11_a_folder_named_twice_meets_compare_s_refusal(
    report_runs: Runs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = copy_run(report_runs.off, tmp_path / "x")
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "report"

    for named in ((str(run), str(run)), ("x", "./x")):
        with pytest.raises(compare.CompareError) as expected:
            compare.distinct_run_dirs(list(named))
        result = report(*named, "--out", str(out))
        assert result.exit_code == 1
        assert one_line(result) == f"error: {cli._one_line(expected.value)}"
    assert not out.exists()


def test_r11_a_run_folder_under_a_key_path_meets_the_key_guard(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "benchmarks" / "answer_keys" / "run")
    out = tmp_path / "report"

    result = report(str(run), "--out", str(out))

    assert result.exit_code == 1
    assert "benchmarks/answer_keys" in one_line(result)
    assert not out.exists()


def built(run: Path, tmp_path: Path, package_id: str) -> Page:
    out = tmp_path / f"report-{run.name}"
    build_report([run], out)
    return transcript(out, run.name, package_id)


def notes(page: Page) -> list[str]:
    return [text for tag, text in page.blocks if tag == "p"]


def test_r12_each_call_s_result_is_read_through_read_stored_result(
    report_runs: Runs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = report_page.read_stored_result

    def spy(run_dir: Path, session_id: Any, step: int, **kwargs: Any) -> Any:
        calls.append(step)
        return real(run_dir, session_id, step, **kwargs)

    monkeypatch.setattr(report_page, "read_stored_result", spy)

    build_report([report_runs.off], tmp_path / "report")

    started = [
        event.body["step_index"]
        for package_id in PACKAGES
        for event in stream(report_runs.off, package_id)
        if event.type == "tool.started"
    ]
    assert calls == started


def test_r12_a_result_that_is_not_this_call_s_is_named_never_embedded(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "results")
    results = run / CASE_A / TOOL_RESULTS_DIR_NAME
    stale = json.loads((results / "step-0.json").read_bytes())
    stale["session_id"] = "00000000-0000-4000-8000-000000000000"
    stale["payload"] = {"marker": "a fictional stale payload"}
    (results / "step-0.json").write_text(json.dumps(stale), encoding="utf-8")
    (results / "step-1.json").unlink()
    (results / "step-2.json").write_bytes(b"{not json")
    other = run / CASE_B / TOOL_RESULTS_DIR_NAME / "step-0.json"
    moved = json.loads(other.read_bytes())
    moved["step"] = 7
    other.write_text(json.dumps(moved), encoding="utf-8")

    page_a, page_b = (
        built(run, tmp_path, CASE_A),
        Page(tmp_path / "report-results" / "transcripts" / "results" / f"{CASE_B}.html"),
    )

    assert "a fictional stale payload" not in page_a.raw
    assert "a stale result from another session in this folder" in notes(page_a)
    assert "full result not stored" in notes(page_a)
    assert "the stored result is unreadable" in notes(page_a)
    assert "a result recorded for another call" in notes(page_b)


def test_r12_a_truncated_last_line_shows_everything_before_it_and_names_its_line(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "cut")
    log = run / CASE_A / EVENTS_FILE_NAME
    data = log.read_bytes()
    last = data.rstrip(b"\n").rfind(b"\n") + 1
    log.write_bytes(data[: last + (len(data) - last) // 2])
    lines = len(data.splitlines())

    page = built(run, tmp_path, CASE_A)

    assert f"the event log is unreadable from line {lines}" in notes(page)
    assert page.texts("pre").count(f"Reviewed {MARKUP}.") == 1


def _pack(folder: Path) -> Path:
    plain = folder / EVENTS_FILE_NAME
    packed = folder / PACKED_EVENTS_FILE_NAME
    packed.write_bytes(gzip.compress(plain.read_bytes(), compresslevel=9, mtime=0))
    plain.unlink()
    return packed


def test_r12_a_packed_stream_truncated_mid_archive_is_named_as_a_cut_line_is(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "packed-cut")
    packed = _pack(run / ROLES)
    data = packed.read_bytes()
    packed.write_bytes(data[: len(data) // 2])
    numbers: list[int] = []
    kept = list(events.replay_events(packed, on_unreadable=numbers.append))
    assert kept and numbers

    page = built(run, tmp_path, ROLES)

    assert f"the event log is unreadable from line {numbers[0]}" in notes(page)
    assert page.index_of("h3", "Turn 0") > 0


def test_r12_an_intact_packed_stream_renders_its_plain_form_s_bytes(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "runs" / "packable")
    plain_out, packed_out = tmp_path / "plain", tmp_path / "packed"
    build_report([run], plain_out)
    for package_id in PACKAGES:
        _pack(run / package_id)

    build_report([run], packed_out)

    assert snapshot(packed_out) == snapshot(plain_out)


def test_r12_missing_and_damaged_files_are_named_and_nothing_is_refused(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "damaged")
    (run / CASE_A / EVENTS_FILE_NAME).unlink()
    (run / CASE_B / "session.json").unlink()
    (run / ROLES / ANSWER_LOG_FILE_NAME).write_bytes(b'{"answer_log_version": 1}\n')
    out = tmp_path / "report"

    build_report([run], out)

    assert "no events were recorded" in notes(transcript(out, "damaged", CASE_A))
    assert "no session was recorded" in notes(transcript(out, "damaged", CASE_B))
    assert "the answer log is unreadable" in notes(transcript(out, "damaged", ROLES))

    (run / CASE_B / "session.json").write_text("{}", encoding="utf-8")
    build_report([run], out)
    assert "the session is unreadable" in notes(transcript(out, "damaged", CASE_B))


def test_r13_markup_in_a_finding_and_a_model_text_renders_as_text(off_report: Path) -> None:
    pages = [Page(path) for path in sorted(off_report.rglob("*.html"))]
    assert all("script" not in page.tags for page in pages)
    page = transcript(off_report, "off", CASE_A)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.raw
    assert "&lt;script&gt;alert(x)&lt;/script&gt;" in page.raw
    assert f"Reviewed {MARKUP}." in page.texts("pre")
    assert any(
        row[5] == f"The callout reads {FINDING_MARKUP}" for row in page.table("Findings").rows[1:]
    )


def test_r14_builds_over_the_same_folders_are_byte_identical(
    report_runs: Runs, tmp_path: Path
) -> None:
    out, other = tmp_path / "report", tmp_path / "other"
    build_report([report_runs.off, report_runs.on], out)
    first = snapshot(out)
    build_report([report_runs.off, report_runs.on], out)
    build_report([report_runs.off, report_runs.on], other)

    assert snapshot(out) == first == snapshot(other)


# --- owner decision 83A: a damaged body, a failed build, and every message sent --------------


def _rewrite_event(log: Path, kind: str, edit: Callable[[dict[str, Any]], None]) -> int:
    """Apply `edit` to the body of the log's first `kind` event; its `seq`."""
    lines = log.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        event = json.loads(line)
        if event["type"] == kind:
            edit(event["body"])
            lines[index] = json.dumps(event)
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return int(event["seq"])
    raise AssertionError(f"no {kind} event in {log}")


@pytest.mark.parametrize(
    ("package_id", "kind", "field"),
    [(CASE_A, "tool.started", "step_index"), (ROLES, "usage", "input_tokens")],
    ids=["a-call-with-no-step", "a-round-missing-a-count"],
)
def test_83a_a_malformed_body_reads_unreadable_from_its_seq_naming_the_run_and_package(
    report_runs: Runs, tmp_path: Path, package_id: str, kind: str, field: str
) -> None:
    """A body the walk cannot read is an unreadable line: what precedes it is shown, the log
    stops there, and nothing raises."""
    run = copy_run(report_runs.off, tmp_path / "runs" / "malformed")
    seq = _rewrite_event(run / package_id / EVENTS_FILE_NAME, kind, lambda body: body.pop(field))
    out = tmp_path / "report"

    build_report([run], out)

    page = transcript(out, "malformed", package_id)
    assert f"malformed/{package_id}: the event log is unreadable from seq {seq}" in notes(page)
    assert page.index_of("h3", "Turn 0") > 0


def _snapshot_tree(folder: Path) -> dict[str, bytes | None]:
    """Every file's bytes and every folder, by relative path."""
    return {
        path.relative_to(folder).as_posix(): (path.read_bytes() if path.is_file() else None)
        for path in folder.rglob("*")
    }


def test_83a_a_build_that_fails_part_way_leaves_the_previous_report_as_it_was(
    report_runs: Runs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The build writes into a sibling folder and swaps it in, so an `OSError` part-way (a path
    too long, say) leaves the previous report whole and no sibling behind."""
    parent = tmp_path / "reports"
    out = parent / "report"
    build_report([report_runs.off], out)
    before = _snapshot_tree(parent)
    real = report_page._write_page
    written: list[Path] = []

    def fail_on_the_third(path: Path, lines: list[str]) -> None:
        written.append(path)
        if len(written) == 3:
            raise OSError(f"{path}: the file name is too long")
        real(path, lines)

    monkeypatch.setattr(report_page, "_write_page", fail_on_the_third)

    with pytest.raises(OSError, match="too long"):
        build_report([report_runs.on], out)

    assert _snapshot_tree(parent) == before
    assert all(out not in path.parents for path in written)


def test_83a_a_first_build_that_fails_leaves_no_folder(
    report_runs: Runs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "reports"
    parent.mkdir()

    def fail(path: Path, lines: list[str]) -> None:
        raise OSError(f"{path}: the file name is too long")

    monkeypatch.setattr(report_page, "_write_page", fail)

    with pytest.raises(OSError):
        build_report([report_runs.off], parent / "report")

    assert list(parent.iterdir()) == []


def _turn_message(page: Page, number: int) -> tuple[str, str]:
    return page.blocks[page.index_of("h3", f"Turn {number}") + 1]


def test_83a_turn_0_s_message_is_shown_when_no_event_was_recorded(
    report_runs: Runs, tmp_path: Path
) -> None:
    run = copy_run(report_runs.off, tmp_path / "runs" / "silent")
    (run / CASE_A / EVENTS_FILE_NAME).unlink()
    out = tmp_path / "report"

    build_report([run], out)

    page = transcript(out, "silent", CASE_A)
    assert _turn_message(page, 0) == ("pre", prompts(run, CASE_A)["user_messages"][0])
    assert "no events were recorded" in notes(page)


def test_83a_messages_sent_past_the_last_logged_turn_are_listed(
    report_runs: Runs, tmp_path: Path
) -> None:
    """The log stops after turn 0; the record holds the two answer turns' messages too."""
    run = copy_run(report_runs.off, tmp_path / "runs" / "short")
    log = run / ROLES / EVENTS_FILE_NAME
    lines = log.read_text(encoding="utf-8").splitlines()
    first_end = next(i for i, line in enumerate(lines) if json.loads(line)["type"] == "turn.ended")
    log.write_text("\n".join(lines[: first_end + 1]) + "\n", encoding="utf-8")
    sent = prompts(run, ROLES)["user_messages"]
    out = tmp_path / "report"

    build_report([run], out)

    page = transcript(out, "short", ROLES)
    assert [_turn_message(page, number)[1] for number in range(3)] == sent
    for number in (1, 2):
        heading = page.index_of("h3", f"Turn {number}")
        assert page.blocks[heading + 2] == ("p", "this turn is not in the event log")
