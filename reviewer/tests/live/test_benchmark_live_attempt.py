"""One real benchmark attempt, driven end to end (feature 014 T171; owner decision 35A).

The offline suite proves each piece of a benchmark row against the scripted provider and recorded
response shapes; only a real attempt proves they are wired together against the real service: the
served model each round reports, non-zero usage, a priced cost, the run status, the prompts record,
the answer log and the report's transcript (`contracts/benchmark-run.md` 15; FR-007, FR-023,
FR-034, FR-039, FR-042, FR-057; SC-008; plan decision RF-89).

The test writes a one-entry set under `tmp_path`, `kalo-fit-1` (the anchor with a case file, so the
answer driver runs) copied from `benchmarks/sets/pane-smoke.json` with its package, key and case
file named by absolute path, as a set file outside the repository must (`contracts/cases.md` 4.2).
It runs `benchmark run`, `benchmark score` and `benchmark report` through `cli.app` and reads the
row's fields as the contracts name them: `run-status.json` (`benchmark-run.md` 10), the
scorecard's `run_status`, `cost`, `served_models` and `price_table` (`scoring.md` 7),
`prompts.json` (`benchmark-run.md` 12) and the report's index and transcript (`report.md` 5).

OpenAI only (owner decision 94A, 2026-10-15): skipped when `OPENAI_API_KEY` is not set, and never
falls back to Gemini, whatever Gemini key the environment holds. The model is `SWREVIEW_LIVE_MODEL`
when set, else `gpt-5.6-sol` (`agent/settings.py`, `PAID_TEST_MODEL`; owner decision 174A): the
default `gpt-5.6` has no price row (102A) and its served variants are not its aliases. A model with
no price row fails before anything is sent (014 T270).

**Never run by accident.** `pytestmark = pytest.mark.live`, so the gate's `-m "not live"` deselects
it, and `tests/conftest.py` skips every live test when no provider key is set at all. It spends
money (about one real review), so it runs only on demand:

    uv run pytest -q -m live -rs tests/live/test_benchmark_live_attempt.py

An infrastructure outcome fails naming its class and `run-status.json`'s message, but for an
authentication or rate-limit refusal or a 5xx (read from the attempt's `error_class`), which skips
naming it, as the other live tests treat an environment problem. A skip proves nothing, so a run on
demand is recorded green only on `1 passed, 0 skipped` (the convention of
`test_gemini_live_function_response.py`).

**Written first in slice 6, against the contract.** It reads fields the slice adds (the
scorecard's run fields, `benchmark.served`, `benchmark.prices`), so it is red until the slice
lands; it can never go red in a gate, which never runs it. At module level it imports only what
existed at the slice's start; the slice's own modules are imported inside the test, so every gate
collects it cleanly. It first runs green at quickstart P0 (T244).
"""

from __future__ import annotations

import json
import os
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, NoReturn

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.providers import ProviderName
from swreview.agent.settings import PAID_TEST_MODEL
from swreview.benchmark import sets
from swreview.benchmark.answers import ANSWER_LOG_FILE_NAME
from swreview.benchmark.report_page import INDEX_FILE, PROMPTS_FILE, TRANSCRIPTS_DIR
from swreview.benchmark.scorecard import SCORECARD_FILE, final_state_origins, read_scorecard
from swreview.report.session import load_session

pytestmark = pytest.mark.live

PROVIDER = ProviderName.OPENAI
"""The one provider this test drives (owner decision 94A); never Gemini, as a fallback or not."""

KEY_NAME = "OPENAI_API_KEY"

MODEL = os.environ.get("SWREVIEW_LIVE_MODEL") or PAID_TEST_MODEL

PACKAGE_ID = "kalo-fit-1"
"""The anchor with a case file, so the answer driver runs (`benchmarks/sets/pane-smoke.json`)."""

SMOKE_SET = Path("benchmarks") / "sets" / "pane-smoke.json"

RUN_STATUS_FILE = "run-status.json"
"""`benchmark-run.md` 10; the slice names its constant, so the test spells the contract's name."""

ENVIRONMENT = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "RateLimitError",
        "InternalServerError",
    }
)
"""The `error_class` values T171 reads as an environment problem and skips: an authentication
refusal (401, 403), a rate-limit or quota refusal (429) and a 5xx, each named by the `openai`
exception the adapter's `OpenAIProviderError` came from. Anything else fails."""

runner = CliRunner()


@pytest.fixture(scope="module")
def openai_key() -> str:
    key = os.environ.get(KEY_NAME)
    if not key:  # a Gemini key alone still collects this module; 94A never falls back to it
        pytest.skip(f"no provider key set: {KEY_NAME} (OpenAI only, owner decision 94A)")
    return key


class _Links(HTMLParser):
    """A page's links, and the text of each `h2` and `pre` block in document order."""

    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.blocks: list[tuple[str, str]] = []
        self._open: str | None = None
        self.feed(path.read_bytes().decode("utf-8"))
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag == "a" and href is not None:
            self.hrefs.append(href)
        if tag in ("h2", "pre"):
            self._open = tag
            self.blocks.append((tag, ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == self._open:
            self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            tag, text = self.blocks[-1]
            self.blocks[-1] = (tag, text + data)


def _one_entry_set(tmp_path: Path) -> Path:
    """`kalo-fit-1`'s entry of the committed smoke set, its files named absolutely."""
    root = sets.REPO_ROOT
    smoke = json.loads((root / SMOKE_SET).read_bytes())
    [entry] = [ref for ref in smoke["packages"] if ref["package_id"] == PACKAGE_ID]
    for field in ("path", "key", "case_file"):
        entry[field] = str((root / entry[field]).resolve())
    set_file = tmp_path / "live-attempt.json"
    set_file.write_text(json.dumps({"name": "live-attempt", "packages": [entry]}), encoding="utf-8")
    return set_file


def _invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


def _settle_infrastructure(run: Path, output: str) -> NoReturn:
    """Skip an environment refusal, fail anything else, each naming what the run recorded."""
    status_path = run / RUN_STATUS_FILE
    if not status_path.is_file():
        pytest.fail(f"benchmark run wrote no {RUN_STATUS_FILE}:\n{output}")
    attempts = json.loads(status_path.read_bytes())["packages"][PACKAGE_ID]["attempts"]
    last = attempts[-1]
    named = f"{last['class']} ({last['error_class']}): {last['message']}"
    if last["error_class"] in ENVIRONMENT:
        pytest.skip(f"API unavailable, {named}; the attempt is not proved")
    pytest.fail(f"the attempt ended an infrastructure failure, {named}\n{output}")


def test_one_real_benchmark_attempt_records_every_field_of_its_row(
    openai_key: str, tmp_path: Path
) -> None:
    # The slice's own modules, imported here so every gate collects this module cleanly.
    from swreview.benchmark import prices, served

    # No --study, so `benchmark run` has no price guard: a model the table cannot price would
    # spend a review and then fail on its cost (174A).
    if prices.price_entry(prices.load_prices(), PROVIDER, MODEL) is None:
        pytest.fail(
            f"no price for {PROVIDER.value} {MODEL} in benchmark/prices.yaml, so the attempt's "
            "cost could not be known; nothing was spent. Name a priced model, as "
            f"{PAID_TEST_MODEL} is (owner decision 174A)"
        )

    root = sets.REPO_ROOT
    run = tmp_path / "run"
    report = tmp_path / "report"

    ran = _invoke(
        "benchmark",
        "run",
        "--set",
        str(_one_entry_set(tmp_path)),
        "--out",
        str(run),
        "--provider",
        PROVIDER.value,
        "--model",
        MODEL,
        "--standards-profile",
        str(root / "config" / "standards.example.yaml"),
        "--no-explain-findings",
    )
    if ran.exit_code != 0:
        _settle_infrastructure(run, ran.output)

    # run-status.json: completed, one attempt, promoted (`benchmark-run.md` 4 and 10).
    status = json.loads((run / RUN_STATUS_FILE).read_bytes())
    assert list(status["packages"]) == [PACKAGE_ID]
    package = status["packages"][PACKAGE_ID]
    [attempt] = package["attempts"]
    if attempt["kind"] == "infrastructure":
        _settle_infrastructure(run, ran.output)
    assert attempt["kind"] == "completed", attempt
    assert package["kept_attempt"] == attempt["attempt"] == 1
    assert attempt["folder"] == PACKAGE_ID
    session_path = run / PACKAGE_ID / "session.json"
    assert session_path.is_file()
    assert not (run / "attempts" / PACKAGE_ID / "1").exists(), "the kept attempt was not promoted"

    # prompts.json: the system prompt and the opening message, as sent (`benchmark-run.md` 12).
    prompts = json.loads((run / PACKAGE_ID / PROMPTS_FILE).read_bytes())
    assert prompts["system"].strip()
    assert prompts["user_messages"] and prompts["user_messages"][0].strip()

    # The answer log beside the session, which `benchmark score` checks against it.
    assert (run / PACKAGE_ID / ANSWER_LOG_FILE_NAME).is_file()
    scored = _invoke("benchmark", "score", str(run))
    assert scored.exit_code == 0, scored.output

    # The scorecard's row (`scoring.md` 7), read as its JSON names the fields.
    card = read_scorecard(run)
    [score] = card.per_package
    dumped = json.loads((run / SCORECARD_FILE).read_bytes())
    [row] = dumped["per_package"]
    assert row["package_id"] == PACKAGE_ID
    assert row["run_status"]["kind"] == "completed", row["run_status"]

    served_models = row["served_models"]
    assert served_models, "no round reported the model that served it"
    for served_id in served_models:
        assert served.aliases(PROVIDER, MODEL, served_id), (
            f"served {served_id!r} is outside the aliases of the requested {MODEL!r}"
        )

    assert row["usage"]["input_tokens"] > 0
    assert row["usage"]["output_tokens"] > 0

    cost = row["cost"]
    assert cost["missing"] == [], cost
    assert cost["synthetic"] is False
    assert cost["amount"] is not None and cost["amount"] > 0, cost

    table = prices.load_prices()
    named = {(entry["provider"], entry["model"]) for entry in dumped["price_table"]["models"]}
    for served_id in served_models:
        entry = prices.price_entry(table, PROVIDER, served_id)
        assert entry is not None, f"no price entry covers the served {served_id!r}"
        assert (entry.provider, entry.model) in named, (served_id, named)

    final = {finding.id for finding in load_session(session_path).findings}
    assert final <= set(score.finding_origins), final - set(score.finding_origins)
    assert "unknown" not in final_state_origins(score), score.finding_origins

    # The report: the package's row links a transcript that opens with the recorded prompt.
    reported = _invoke("benchmark", "report", str(run), "--out", str(report))
    assert reported.exit_code == 0, reported.output
    links = [
        href
        for href in _Links(report / INDEX_FILE).hrefs
        if href.startswith(f"{TRANSCRIPTS_DIR}/") and href.endswith(f"/{PACKAGE_ID}.html")
    ]
    [link] = links
    transcript = report / Path(*link.split("/"))
    assert transcript.is_file()
    blocks = _Links(transcript).blocks
    assert blocks[0] == ("h2", "The system prompt as sent")
    assert blocks[1] == ("pre", prompts["system"])
