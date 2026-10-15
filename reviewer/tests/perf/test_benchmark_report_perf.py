"""R-18: the report over the committed set's worst case stays inside its budget (feature 014 T167).

`contracts/report.md` 8 (SC-009; plan decision RF-46; owner decision 28A): the committed set's
47 packages at 10 repetitions in both arms, 20 run folders and 940 transcripts, each pilot-size
and each stream packed, build in under 60 seconds on the development machine, and every link on
the index resolves to a page. Pilot-size is fixed here as the contract fixes it: a 30 KB system
prompt and four user messages, 40 calls over the rounds of an opening turn and 3 answer turns,
and a 16 KB full result per call, about 0.7 MB per transcript and about 660 MB in all. Every
string is fictional.

The fixture, which is not timed, writes each run folder through `tests/support/studies.py`'s
`write_run` (scorecard, provenance, saved set, sessions), then gives each package folder its
`prompts.json` through `report_page.PromptsRecord`, its stream packed with
`gzip.compress(data, compresslevel=9, mtime=0)` (`provenance.md` 6.7's rule; `benchmark pack`
lands with the robustness slice), no plain stream remaining, and its 40 stored results in
`_store`'s envelope, carrying the session's id. It then opens each stored result once (owner
decision 82A): on the development machine the first open of each freshly written file costs about
6.6 ms under Windows Defender real-time scanning, about 37,600 files and 242.7 s in all, which is
the machine's and not the report's, so the budget measures the report's own work.

Collected only with `-m perf` (`tests/conftest.py`). Run from `reviewer/`:

    SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts="" -m perf -s \\
        tests/perf/test_benchmark_report_perf.py
"""

from __future__ import annotations

import gzip
import json
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.events import EVENTS_FILE_NAME, PACKED_EVENTS_FILE_NAME
from swreview.benchmark.report_page import (
    PROMPTS_FILE,
    PROMPTS_VERSION,
    PromptsRecord,
    build_report,
)
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME
from tests.support.studies import PackageSpec, RunSpec, write_run

pytestmark = pytest.mark.perf

PERF_BUDGET_S = 60.0
CASES = 47
REPETITIONS = 10
ARMS = ("off", "on")
CALLS = 40
ANSWER_TURNS = 3
SYSTEM_BYTES = 30_000
RESULT_BYTES = 16_000
AT = datetime(2026, 10, 14, 9, 0, tzinfo=UTC).isoformat()


def _system_prompt() -> str:
    line = "Review the fictional evidence package and record each finding with its evidence.\n"
    return (line * (SYSTEM_BYTES // len(line) + 1))[:SYSTEM_BYTES]


def _record() -> bytes:
    record = PromptsRecord(
        prompts_version=PROMPTS_VERSION,
        system=_system_prompt(),
        user_messages=[
            "Pre-run digest of a fictional bracket.\n\nReview the evidence package described.",
            *(f"The engineer answered ER-{n:03d}: a fictional answer." for n in range(1, 4)),
        ],
    )
    return (record.model_dump_json(indent=2) + "\n").encode("utf-8")


def _stream() -> bytes:
    """An opening turn and three answer turns, 40 calls over their rounds, packed."""
    lines: list[dict[str, Any]] = [{"type": "session.started", "body": {}}]
    per_turn = CALLS // (ANSWER_TURNS + 1)
    step = 0
    for turn in range(ANSWER_TURNS + 1):
        if turn > 0:
            answer = {"request_id": f"ER-{turn:03d}", "answer": "a fictional answer"}
            lines.append({"type": "evidence.answered", "body": answer})
        for round_index in range(2):
            usage = {
                "round_index": round_index,
                "provider": "openai",
                "model": "gpt-5.6",
                "input_tokens": 40_000 + step,
                "cached_input_tokens": 30_000,
                "cache_write_tokens": 0,
                "output_tokens": 900,
                "reasoning_tokens": 400,
                "tool_result_input_tokens": None,
                "total_tokens": 40_900 + step,
                "latency_s": 2.5,
            }
            lines.append({"type": "usage", "body": usage})
            for _ in range(per_turn // 2):
                arguments = {"component_id": f"cmp:{step + 1:04d}"}
                lines.append(
                    {
                        "type": "tool.started",
                        "body": {"step_index": step, "tool": "list_holes", "arguments": arguments},
                    }
                )
                summary = "a fictional summary of the holes of one bracket " * 4
                lines.append(
                    {
                        "type": "tool.finished",
                        "body": {
                            "step_index": step,
                            "status": "ok",
                            "result_summary": summary[:200],
                            "elapsed_s": 0.1,
                        },
                    }
                )
                step += 1
        lines.append({"type": "text.done", "body": {"text": "A fictional review text."}})
        lines.append({"type": "turn.ended", "body": {"reason": "end"}})
    data = "".join(
        json.dumps({"seq": seq, "at": AT, **line}) + "\n" for seq, line in enumerate(lines, 1)
    )
    return gzip.compress(data.encode("utf-8"), compresslevel=9, mtime=0)


def _payload() -> str:
    """A 16 KB fictional payload, as JSON."""
    row = {"hole_id": "hole:0001", "diameter_mm": 6.6, "note": "a fictional <counterbore> & bore"}
    rows: list[dict[str, Any]] = []
    while len(json.dumps(rows)) < RESULT_BYTES:
        rows.append(row)
    return json.dumps({"status": "ok", "holes": rows})


def _envelope(session_id: str, step: int, payload: str) -> bytes:
    """`_store`'s envelope around `payload`, carrying the session's id."""
    head = json.dumps(
        {"session_id": session_id, "step": step, "tool": "list_holes", "arguments": {}}
    )
    return f'{head[:-1]}, "status": "ok", "payload": {payload}}}'.encode()


@pytest.fixture(scope="module")
def worst_case(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    root = tmp_path_factory.mktemp("report-perf") / "runs"
    packages = tuple(PackageSpec(package_id=f"case-{n:02d}") for n in range(1, CASES + 1))
    record, stream, payload = _record(), _stream(), _payload()
    runs = []
    for arm in ARMS:
        for rep in range(1, REPETITIONS + 1):
            run = write_run(root, RunSpec(run=f"{arm}-{rep}", arm=arm, rep=rep, packages=packages))
            for package in packages:
                folder = run / package.package_id
                session_id = json.loads((folder / "session.json").read_bytes())["session_id"]
                (folder / PROMPTS_FILE).write_bytes(record)
                (folder / EVENTS_FILE_NAME).unlink()
                (folder / PACKED_EVENTS_FILE_NAME).write_bytes(stream)
                results = folder / TOOL_RESULTS_DIR_NAME
                results.mkdir()
                for step in range(CALLS):
                    envelope = _envelope(session_id, step, payload)
                    (results / f"step-{step}.json").write_bytes(envelope)
            runs.append(run)
    for result in sorted(root.rglob(f"{TOOL_RESULTS_DIR_NAME}/step-*.json")):
        result.read_bytes()
    return runs


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag == "a" and href is not None:
            self.hrefs.append(href)


def test_the_report_over_940_pilot_size_transcripts_stays_inside_its_budget(
    worst_case: list[Path], tmp_path: Path
) -> None:
    out = tmp_path / "report"

    started = time.perf_counter()
    built = build_report(worst_case, out)
    elapsed = time.perf_counter() - started
    print(
        f"report over {built.transcripts} transcripts: {elapsed:.3f}s (budget {PERF_BUDGET_S:.3f}s)"
    )

    assert elapsed < PERF_BUDGET_S, f"the report took {elapsed:.3f}s"
    assert built.transcripts == CASES * REPETITIONS * len(ARMS) == 940
    links = Links()
    links.feed(built.index.read_text(encoding="utf-8"))
    transcripts = [href for href in links.hrefs if href.startswith("transcripts/")]
    assert len(transcripts) == 940
    assert all((out / href).is_file() for href in links.hrefs)
