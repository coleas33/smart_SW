"""The engineer's plan for the next seat sitting holds to the tasks and to the product (011 T100).

`docs/workstation-test-plan-2026-09-23.md` is the sitting of
`docs/workstation-handover-2026-09-23.md` in plain, numbered steps for the engineer who runs it,
who is not a developer. It cannot be run here (every step needs the licensed seat), so what it
promises is held in its text:

- every open `[W]` task of features 008 to 011 is named with its package (`011 T062`), so each
  result maps back to its row of a `tasks.md` - ids repeat across packages, so a bare id is not
  enough;
- the runbook and the README link it;
- every PowerShell block parses in Windows PowerShell, so a pasted step cannot fail on its syntax,
  and a placeholder outside quotes (`<run folder>`) is a parse error, so every one is quoted;
- every `uv run python -c "..."` one-liner compiles and holds no double quote, which Windows
  PowerShell 5.1 does not pass to a native program intact; the dump check is feature 010's own
  (its Phase 13 note), character for character; and each runs against a committed fixture and
  prints the lines the plan tells the engineer to read;
- every product sentence the plan quotes, for the engineer to compare with the screen, is still
  the product's.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from swreview.ir.loader import load_package
from swreview.report.session import load_session
from swreview.tools.checks_interference import groups_of
from tests.support.seat_tasks import (
    PACKAGES,
    REPO,
    open_seat_tasks,
    qualified_tasks,
)

PLAN = REPO / "docs" / "workstation-test-plan-2026-09-23.md"
REVIEWER = REPO / "reviewer"
FIXTURES = REVIEWER / "tests" / "fixtures"
REVIEW_RUN = FIXTURES / "replay" / "big-assembly"
DUMP = FIXTURES / "mechanical" / "big-assembly"
DRAWINGS = FIXTURES / "drawings" / "plate-drawing"

ONE_LINER = re.compile(r'uv run python -c "([^"\n]*)" (\S+)')
"""A one-liner and the argument after it. The code stops at the first double quote, so a double
quote inside it leaves the argument unmatched and the one-liner uncounted."""
ONE_LINER_START = "uv run python -c \""
POWERSHELL_BLOCK = re.compile(r"^```powershell\n(.*?)^```", re.MULTILINE | re.DOTALL)

QUOTED: tuple[tuple[str, str], ...] = (
    # The update script and the registration.
    ("failed with exit code", "extractor/tools/update-workstation.ps1"),
    ("standards profile: present at", "extractor/tools/update-workstation.ps1"),
    ("registered SwReview.AddIn, and enabled it for", "extractor/tools/register-addin.ps1"),
    # The probe report's lines.
    ("mutating members: ", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("refusals: ", "extractor/SwReview.Extractor.Console/Program.cs"),
    (
        "gate log: the confirmed open's guard (DrawingOpenGuard, D14 only): ",
        "extractor/SwReview.Extractor.Console/Program.cs",
    ),
    (
        "refused: the named document is not open in SOLIDWORKS, so nothing was read and nothing "
        "was opened",
        "extractor/SwReview.Extractor.Console/Program.cs",
    ),
    ("is not open, so it was not read (nothing is opened)",
     "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("no face the part's face phase described has this reference",
     "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("FullName equal ", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("active sheet:", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("detailing mode ", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("IsModelOutOfDate ", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("the local copy changed across the check: ",
     "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("; agree ", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("no same-name drawing beside the document (File.Exists false), so nothing was opened",
     "extractor/SwReview.Extractor/Probes/DrawingOpenProbe.cs"),
    ("against confirmed-open.md: ", "extractor/SwReview.Extractor/Probes/DrawingOpenProbe.cs"),
    ("every answer as required", "extractor/SwReview.Extractor/Probes/DrawingOpenProbe.cs"),
    ("opened by the probe and closed", "extractor/SwReview.Extractor/Probes/DrawingOpenProbe.cs"),
    ("already open, read as it stood and left open",
     "extractor/SwReview.Extractor/Probes/DrawingOpenProbe.cs"),
    ("with the drawing already open, no visibility, open or close key was gated: ",
     "extractor/SwReview.Extractor/Probes/DrawingOpenProbe.cs"),
    ("seam keys gated: ISldWorks.DocumentVisible, ISldWorks.OpenDoc6, ISldWorks.CloseDoc",
     "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
    ("OpenDoc6: type 3, options 3 (ReadOnly 2 yes, Silent 1 yes, ViewOnly 4 no, RapidDraft 8 no, ",
     "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
    ("DocumentVisible: false (type 3), then true (type 3)",
     "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
    ("drawing file: size unchanged true, write time unchanged true, SHA-256 unchanged true",
     "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
    ("afterwards: GetOpenDocumentByName answers false; an exclusive read open succeeded",
     "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
    # The confirmed open and the drawing check.
    ("the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 probe "
     "D14)", "extractor/SwReview.Extractor/Sw/DrawingOpenScope.cs"),
    ("public static bool SeatValidated => false;",
     "extractor/SwReview.Extractor/Sw/DrawingOpenScope.cs"),
    ("TheSeamShipsOffUntilTheSeatConfirmsIt",
     "extractor/SwReview.Extractor.Tests/DrawingOpenTests.cs"),
    ("DRAWING_BINDING_VALIDATED: bool = False", "reviewer/src/swreview/drawings/binding.py"),
    ("test_the_switch_ships_off", "reviewer/tests/unit/test_drawing_binding.py"),
    ("read as it stood; it was already open, so it was left open",
     "reviewer/src/swreview/tools/drawings.py"),
    ("Yes, open it read-only and read it", "reviewer/src/swreview/checks/drawing_context.py"),
    ("Review without it", "reviewer/src/swreview/checks/drawing_context.py"),
    ("They all apply", "reviewer/src/swreview/checks/drawing_context.py"),
    ("a drawing with its name sits beside it (candidate)",
     "reviewer/src/swreview/checks/drawing_context.py"),
    ("differs from the company's drawing standard",
     "reviewer/src/swreview/checks/drawing_context.py"),
    ("agrees with the profile's drawing standard in",
     "reviewer/src/swreview/checks/drawing_context.py"),
    ("which has no drawing section", "reviewer/src/swreview/checks/drawing_context.py"),
    ("drawing callouts are read but not yet validated on a seat",
     "reviewer/src/swreview/drawings/binding.py"),
    ("nothing was rebuilt", "reviewer/src/swreview/checks/standards/results.py"),
    ("no drawing graded", "reviewer/src/swreview/checks/standards/verdict.py"),
    # The summary's words.
    ("Same-name drawing found but not open: ", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("Drawing read: ", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("need your decision", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("not reached", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("size-for-size contacts", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("Sending resumes the review once.", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("The backend restarted, so this review is shown from its run folder. Follow-ups, decisions "
     "and answers are off.", "reviewer/src/swreview/report/review_words_v1.yaml"),
    # The page's own words.
    ("The review has finished.", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("Waiting for your answers.", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("This review is of ", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("Send answers", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("This review can no longer be restored.",
     "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("The review stopped", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("uncached + ", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("Remodel is not in this build yet. This tab will not change the open part.",
     "extractor/SwReview.AddIn/Remodel/RemodelHost.cs"),
    # The handoff's two commands.
    ("Missing artifacts: ", "reviewer/src/swreview/cli.py"),
    ("none: no configured secret appears in", "reviewer/src/swreview/cli.py"),
)
"""Every product sentence the plan quotes, with the file that says it."""


@pytest.fixture(scope="module")
def plan() -> str:
    return PLAN.read_text(encoding="utf-8")


def one_liners(text: str) -> list[tuple[str, str]]:
    """`(code, argument)` of every one-liner in `text`, in order."""
    return ONE_LINER.findall(text)


def one_liner_of(text: str, function: str) -> str:
    """The code of the one-liner inside the plan's PowerShell function `function`."""
    body = text[text.index(f"function {function} ") :]
    body = body[: body.index("\n}\n")]
    [(code, _)] = one_liners(body)
    return code


def run_one_liner(code: str, folder: Path) -> list[str]:
    """Run `code` as the plan's function does - from `reviewer`, the folder its one argument - and
    answer the lines it printed."""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(folder)],
        cwd=REVIEWER,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.splitlines()


def line_starting(lines: list[str], label: str) -> str:
    [line] = [line for line in lines if line.startswith(label)]
    return line


def test_the_runbook_and_the_readme_link_the_plan() -> None:
    link = "docs/workstation-test-plan-2026-09-23.md"
    runbook = (REPO / "docs" / "workstation-runbook.md").read_text(encoding="utf-8")
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    handover = (REPO / "docs" / "workstation-handover-2026-09-23.md").read_text(encoding="utf-8")

    assert f"`{link}`" in runbook
    assert f"({link})" in readme
    assert f"`{link}`" in handover


def test_the_plan_names_every_open_seat_task_with_its_package(plan: str) -> None:
    named = qualified_tasks(plan)

    for package in PACKAGES:
        tasks = open_seat_tasks(package)
        assert tasks, package
        missing = [task for task in tasks if (package[:3], task) not in named]
        assert missing == [], f"{package}: {missing}"
    assert {("006", "T103"), ("006", "T105"), ("006", "T107")} <= named


def test_a_qualified_range_names_each_task_in_it_and_a_bare_id_names_nothing() -> None:
    assert qualified_tasks("[010 T103 to T106; 009 T080] and T077") == {
        ("010", "T103"), ("010", "T104"), ("010", "T105"), ("010", "T106"), ("009", "T080"),
    }


def test_the_plan_says_what_allows_each_switch_and_names_every_probe(plan: str) -> None:
    for switch in ("DrawingOpenScope.SeatValidated", "DRAWING_BINDING_VALIDATED"):
        assert switch in plan
    for probe in range(1, 15):
        assert re.search(rf"\bD{probe}\b", plan), f"D{probe}"


@pytest.mark.parametrize(("sentence", "source"), QUOTED, ids=[source for _, source in QUOTED])
def test_every_sentence_the_plan_quotes_is_the_products(
    plan: str, sentence: str, source: str
) -> None:
    assert sentence in plan
    assert sentence in (REPO / source).read_text(encoding="utf-8")


def test_every_one_liner_compiles_and_holds_no_double_quote(plan: str) -> None:
    found = one_liners(plan)

    assert len(found) == plan.count(ONE_LINER_START) == 3
    for code, argument in found:
        compile(code, "<the plan's one-liner>", "exec")
        assert argument.startswith("$"), argument


def test_the_dump_check_is_feature_010s_own(plan: str) -> None:
    tasks = (REPO / "specs" / "010-mechanical-checks" / "tasks.md").read_text(encoding="utf-8")
    [phase_13] = re.findall(r'uv run python -c "([^"\n]*)" <the dump folder>', tasks)

    assert one_liner_of(plan, "Show-DumpFacts") == phase_13


def test_the_dump_check_runs_against_a_committed_package(plan: str) -> None:
    lines = run_one_liner(one_liner_of(plan, "Show-DumpFacts"), DUMP)
    package = load_package(DUMP).package

    assert line_starting(lines, "documents ").startswith(f"documents {len(package.documents)} |")
    for label in ("holes ", "model_dimensions ", "fasteners "):
        line_starting(lines, label)


def test_the_review_facts_run_against_a_committed_review(plan: str) -> None:
    lines = run_one_liner(one_liner_of(plan, "Show-ReviewFacts"), REVIEW_RUN)
    session = load_session(REVIEW_RUN / "session.json")
    package = load_package(REVIEW_RUN).package
    keys = {group.group_key for group in groups_of(package)}
    judged = {
        step.arguments.get("group_key") for step in session.steps
        if step.tool == "check_interference_group"
    }
    totals = session.usage.totals

    assert line_starting(lines, "tokens: input ").startswith(
        f"tokens: input {totals.input_tokens} | cached {totals.cached_input_tokens} | "
        f"uncached {totals.uncached_input_tokens} | rounds {session.usage.rounds} | "
        f"turns {session.usage.turns}"
    )
    assert line_starting(lines, "findings ") == (
        f"findings {len(session.findings)} | contacts {len(session.contacts or [])} | "
        f"interference rows in package.json {len(package.interferences)} | gaps "
        f"{len(package.gaps)}"
    )
    assert line_starting(lines, "interference groups ") == (
        f"interference groups {len(keys)} | judged {len(keys & judged)} | not judged "
        f"{len(keys - judged)}"
    )
    for label in (
        "pre-run tools: ",
        "pre-run tools called again after the first model round: ",
        "drawing phase: ",
        "drawings line: ",
        "questions: asked ",
        "answers sent ",
        "seconds from session.started to the first text.delta: ",
    ):
        line_starting(lines, label)


def test_the_review_facts_count_answers_sent_together_and_the_one_turn_they_resume(
    plan: str, tmp_path: Path
) -> None:
    """009 T084's reading: three answers in one send, no turn ending between them, one resumed
    turn after them, and the first round's input after the last answer."""
    run = tmp_path / "run"
    shutil.copytree(REVIEW_RUN, run)
    events = run / "events.jsonl"
    last = json.loads(events.read_text(encoding="utf-8").splitlines()[-1])
    at, seq = last["at"], last["seq"]
    appended = [
        {"type": "evidence.answered", "body": {"request_id": "ER-001"}},
        {"type": "evidence.answered", "body": {"request_id": "ER-002"}},
        {"type": "evidence.answered", "body": {"request_id": "ER-003"}},
        {"type": "usage", "body": {"round_index": 41, "input_tokens": 23456}},
        {"type": "usage", "body": {"round_index": 42, "input_tokens": 34567}},
        {"type": "turn.ended", "body": {"reason": "completed"}},
    ]
    with events.open("a", encoding="utf-8") as handle:
        for offset, event in enumerate(appended, start=1):
            handle.write(json.dumps({"seq": seq + offset, "at": at, **event}) + "\n")

    lines = run_one_liner(one_liner_of(plan, "Show-ReviewFacts"), run)

    assert line_starting(lines, "answers sent ") == (
        "answers sent 3 | turns ended between the first and last answer 0 | turns ended after "
        "the last answer 1 | first round input after the answers 23456"
    )


def test_the_documents_list_names_each_document_by_its_id(plan: str) -> None:
    lines = run_one_liner(one_liner_of(plan, "Show-Documents"), DRAWINGS)
    package = load_package(DRAWINGS).package

    assert [line.split()[0] for line in lines] == [
        document.document_id for document in package.documents
    ]
    assert f"{package.documents[-1].document_id} drawing " in lines[-1] + " "


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_every_powershell_block_parses(plan: str, tmp_path: Path) -> None:
    blocks = POWERSHELL_BLOCK.findall(plan)
    assert len(blocks) >= 20
    for index, block in enumerate(blocks):
        (tmp_path / f"block-{index:02d}.ps1").write_text(block, encoding="utf-8-sig")
    command = (
        f"Get-ChildItem '{tmp_path}' -Filter block-*.ps1 | Sort-Object Name | ForEach-Object {{ "
        "$errors = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, "
        "[ref]$null, [ref]$errors); "
        "$errors | ForEach-Object { \"$($_.Extent.File | Split-Path -Leaf) line "
        "$($_.Extent.StartLineNumber): $($_.Message)\" } }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == ""
