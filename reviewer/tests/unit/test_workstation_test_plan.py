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
  the product's;
- the results sheet (`docs/workstation-results-2026-09-23.md`), which the plan copies into the
  handover folder as the findings document, has a row for every step and task id a step heading
  names, every row names a step the plan has, every open seat task the plan does not set aside
  under "Not in this sitting" has a row, and it ships blank;
- the four earlier seat tasks the owner added (decision 15A: 006 T101 and T102, 007 T059 and
  T060) each have a step where their documents are already open and a row, and are gone from
  the table of earlier tasks not asked; `Show-StartHere` prints a committed report's Start here
  rows in their order, the timing line passes `swreview timing`'s four inputs, and the headline
  time is the steps' sum;
- feature 004's three items the owner added (decision 18A, 2026-09-25) do the same: the
  FeatureWorks record (004 T164, dated in 004's `tasks.md`) at step 1.7 is read only and prints
  one line; the owner's parts at step 5.1 give 004 T003 its packages and no name; the probes
  004 T033 to T039 are step 5.6, the last before the handoff, in three runs into three folders -
  every probe whose body never reorders first, PROBE-1 alone last - that cover the probe
  catalog once; `Show-RemodelLedger` reads a ledger in `RemodelProbeLedger.Render`'s shape; a
  message box waits out PROBE-1's watchdog; and the lines step 5.6 reads are the console's.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from swreview.cli import app
from swreview.ir.loader import load_package
from swreview.report.attention import rank
from swreview.report.rerender import rerender_run_folder
from swreview.report.session import load_session
from swreview.tools.checks_interference import groups_of
from tests.support.seat_tasks import (
    PACKAGES,
    REPO,
    open_seat_tasks,
    qualified_tasks,
)

PLAN = REPO / "docs" / "workstation-test-plan-2026-09-23.md"
RESULTS = REPO / "docs" / "workstation-results-2026-09-23.md"
REVIEWER = REPO / "reviewer"
FIXTURES = REVIEWER / "tests" / "fixtures"
REVIEW_RUN = FIXTURES / "replay" / "big-assembly"
DUMP = FIXTURES / "mechanical" / "big-assembly"
DRAWINGS = FIXTURES / "drawings" / "plate-drawing"

ONE_LINER = re.compile(r'uv run python -c "([^"\n]*)" (\S+)')
"""A one-liner and the argument after it. The code stops at the first double quote, so a double
quote inside it leaves the argument unmatched and the one-liner uncounted."""
ONE_LINER_START = "uv run python -c \""
POWERSHELL_BLOCK = re.compile(r"^\s*```powershell\n(.*?)^\s*```", re.MULTILINE | re.DOTALL)
TAGGED_STEP = re.compile(r"^### (\d+\.\d+) .*\[([^\]]+)\]\s*$", re.MULTILINE)
"""A step heading with its task ids in brackets: `### 3.4 The pane review ... [011 T063; ...]`."""
STEP_HEADING = re.compile(r"^### (\d+\.\d+) ", re.MULTILINE)
RESULT_ROW = re.compile(
    r"^\| (\d+\.\d+) \| ([^|]*) \|([^|]*)\|([^|]*)\|([^|]*)\|\s*$", re.MULTILINE
)
"""A row of the results sheet: step, task, and the three cells the engineer fills in."""

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
    ("could not read ", "reviewer/src/swreview/cli.py"),
    # The update script's refusals and health lines, which step 1.3 tells apart.
    ("SOLIDWORKS is running and holds SwReview.AddIn.dll open",
     "extractor/tools/update-workstation.ps1"),
    ("No SOLIDWORKS interops at", "extractor/tools/update-workstation.ps1"),
    ("The checkout has local changes", "extractor/tools/update-workstation.ps1"),
    ("git status failed", "extractor/tools/update-workstation.ps1"),
    ("uv on PATH: ", "extractor/tools/update-workstation.ps1"),
    ("swreview-extract: ", "extractor/tools/update-workstation.ps1"),
    ("-NoPull: building what is checked out", "extractor/tools/update-workstation.ps1"),
    (" with -NoPull: building what is checked out", "extractor/tools/update-workstation.ps1"),
    ("If the box is clear there", "extractor/tools/register-addin.ps1"),
    # Where the pane is, and the buttons and badge the steps name.
    ("SwReview evidence extractor (read-only)", "extractor/SwReview.AddIn/SwReviewAddIn.cs"),
    ("Open check folder", "extractor/SwReview.AddIn/Standards/StandardsPage/index.html"),
    ("Open check folder", "extractor/SwReview.AddIn/Model/ModelCheckPage/index.html"),
    ("Standards check", "extractor/SwReview.AddIn/Standards/StandardsPage/index.html"),
    ("Clear review", "extractor/SwReview.AddIn/Review/ReviewPage/index.html"),
    ("Before this review", "extractor/SwReview.AddIn/Review/ReviewPage/index.html"),
    ("Review available evidence", "extractor/SwReview.AddIn/Review/ReviewPage/index.html"),
    ("component instances are not resolved.",
     "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("No review tokens have been used.", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("The review is running.", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("Backend ready", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("No model list yet. Press Refresh.", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("A key is stored for this Windows account. Leave this blank to keep it.",
     "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("Show in SOLIDWORKS", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("Grade: ", "extractor/SwReview.AddIn/Model/ModelCheckPage/check.js"),
    ("Every rule reached a verdict.", "extractor/SwReview.AddIn/Model/ModelCheckPage/check.js"),
    ("Not graded, evidence missing:", "extractor/SwReview.AddIn/Model/ModelCheckPage/check.js"),
    ("Rule ids", "extractor/SwReview.AddIn/Model/ModelCheckPage/check.js"),
    # The console's own lines, and the probe lines the steps count.
    ("Attached to the running SOLIDWORKS session.",
     "extractor/SwReview.Extractor.Console/Program.cs"),
    ("dump failed.", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("completed in ", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("hole callouts in the extraction: ",
     "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("(swDetailingLinearDimPrecision)",
     "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("(swUnitsLinearDecimalPlaces)", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    ("(swUnitsLinear)", "extractor/SwReview.Extractor/Probes/DrawingProbeRunner.cs"),
    # The review's words the steps search for.
    ("A drawing with the same name sits beside",
     "reviewer/src/swreview/checks/drawing_context.py"),
    ("Which one governs it?", "reviewer/src/swreview/checks/drawing_context.py"),
    ("It is not the right drawing", "reviewer/src/swreview/checks/drawing_context.py"),
    ("no tolerance source is read for this package",
     "reviewer/src/swreview/checks/joint_alignment.py"),
    ("standards.release", "reviewer/src/swreview/checks/standards/registry.py"),
    ("the bridge returned status 'error': the read-only open of a confirmed drawing is not yet "
     "validated on a seat (feature 011 probe D14)",
     "extractor/SwReview.AddIn.Tests/Fixtures/review-drawing-questions.json"),
    # The Standards probe's first three sections, which step 3.1 reads (006 T101 and T102).
    ("probe-1 exploded_state:", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("open document:", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("IModelDoc2.IsExploded()=", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("IModelDocExtension.IsExploded(out name)=", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("explode_steps=", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("sub-assembly documents:", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("(no loaded document", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("probe-2 appearance_overrides:", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("HasMaterialPropertyValues=", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("GetMaterialPropertyValues2(1, null)=", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("probe-3 component_visibility:", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("Visible=", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("GetVisibility(1, null)=", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("suppression=", "extractor/SwReview.Extractor.Console/Program.cs"),
    # The Start here rows and the timing, which steps 4.1, 4.5, 5.1 and 5.2 read (007).
    ("Start here", "extractor/SwReview.AddIn/web/shared/attention.js"),
    ("Show all", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("Nothing to start with", "reviewer/src/swreview/report/attention.py"),
    ("net saved: ", "reviewer/src/swreview/cli.py"),
    ("report: ", "reviewer/src/swreview/cli.py"),
    ("Net saved minutes: ", "reviewer/src/swreview/report/markdown.py"),
    # The re-modeler probe's own lines, which step 5.6 reads (004, decision 18A).
    ("--acknowledge-throwaway-part", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("probe remodel refused, and nothing was built.",
     "extractor/SwReview.Extractor.Console/Program.cs"),
    ("probe remodel failed.", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("remodel-probe.log", "extractor/SwReview.Extractor.Console/Program.cs"),
    ("SOLIDWORKS already has a document open.", "extractor/SwReview.Extractor/Rms/RemodelProbe.cs"),
    ("interop members: ", "extractor/SwReview.Extractor/Rms/RemodelProbe.cs"),
    ("BLOCKING ", "extractor/SwReview.Extractor/Rms/RemodelProbe.cs"),
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


@pytest.fixture(scope="module")
def results() -> str:
    return RESULTS.read_text(encoding="utf-8")


def result_rows(text: str) -> list[tuple[str, str, str, str, str]]:
    """`(step, task, result, observed, notes)` of every row of the results table, stripped."""
    return [tuple(cell.strip() for cell in row) for row in RESULT_ROW.findall(text)]


def not_in_this_sitting(plan: str) -> set[tuple[str, str]]:
    """The task ids the plan sets aside, from its last section on."""
    return qualified_tasks(plan[plan.index("## Not in this sitting") :])


def step(plan: str, number: str) -> str:
    """The text of step `number` (`1.4`), from its heading to the next heading of its level or
    above."""
    start = plan.index(f"### {number} ")
    ends = [plan.find(heading, start + 1) for heading in ("\n### ", "\n## ")]
    return plan[start : min(end for end in ends if end >= 0)]


def test_the_plan_starts_the_findings_document_once_the_update_has_brought_the_sheet(
    plan: str,
) -> None:
    """The engineer copies the sheet into the handover folder on day 1, under the name step 6
    hands over, and fills it in as each step ends. A checkout older than the sheet has none
    until step 1.3's pull brings it, so the copy is made at step 1.4, after the check that the
    checkout holds the sheet itself - the plan came first, so a checkout can hold the plan and
    not the sheet; until then step 1 records in `notes\\update.txt`."""
    copy = r'Copy-Item "$R\docs\workstation-results-2026-09-23.md" $findings'
    step_1_4 = step(plan, "1.4")
    step_1 = plan[plan.index("## Step 1.") : plan.index("### 1.1 ")]

    assert '$findings = "$H\\pane-findings-$(Split-Path $H -Leaf).md"' in plan
    assert plan.count(copy) == 1
    assert copy in step_1_4
    assert step_1_4.index(r"Test-Path docs\workstation-results-2026-09-23.md") < step_1_4.index(
        copy
    )
    assert r"Test-Path docs\workstation-test-plan-2026-09-23.md" not in plan
    assert plan.index("git pull --ff-only origin main") < plan.index(copy)
    assert plan.index("notepad $findings") > plan.index("### 1.4 ")
    assert r"notes\update.txt" in step_1
    assert "## Start the findings document" not in plan


def test_steps_before_the_findings_document_record_in_the_update_notes(plan: str) -> None:
    """Until step 1.4 starts the findings document there is no Results table to write in, so
    what steps 1.1 to 1.3 record, a network refusal included, goes to `notes\\update.txt`."""
    before = re.sub(r"\s+", " ", plan[plan.index("### 1.1 ") : plan.index("### 1.4 ")])

    assert "Results table" not in before
    assert r"`$H\notes\update.txt`, write `blocked by 1.3: network` under them" in before


def test_the_answer_to_a_before_this_review_panel_is_the_owners_decision(plan: str) -> None:
    """Decision 14A (2026-09-24): when the panel appears, the engineer writes down its first
    line, presses Review available evidence, and never resolves or unsuppresses a part. It is
    the owner's decision, no longer a default the owner may override in `notes\\documents.txt`,
    in each place that says what to do: section 0.1, step 3.4, step 4's box, step 5.5 (which
    presses Review on A outside step 4, on both builds) and the handover."""
    box = plan[plan.index("## Step 4.") : plan.index("### 4.1 ")]
    places = {
        "0.1": step(plan, "0.1"),
        "3.4": step(plan, "3.4"),
        "step 4's box": box,
        "5.5": step(plan, "5.5"),
        "the handover": HANDOVER.read_text(encoding="utf-8"),
    }

    for name, text in places.items():
        flat = re.sub(r"\s+", " ", text)
        assert "decision 14A" in flat, name
        assert "first line" in flat, name
        assert "Review available evidence" in flat, name
        assert "never resolve or unsuppress a part" in flat, name
    assert "unless the owner wrote otherwise" not in plan
    assert "the default is **Review available evidence**" not in plan
    assert "Two decisions" not in step(plan, "0.1")


PRESS_REVIEW = re.compile(
    r"(?<!not )(?<!not\*\* )\bpress (?:\*\*)?Review\b(?:\*\*)?(?! to | available)", re.IGNORECASE
)
"""A press of the Review button (`press Review`, `press **Review**`), not a `do **not** press
Review`, the pane's own quoted `Press Review to review ...` or the panel's **Review available
evidence**."""


def test_every_step_outside_step_4_that_presses_review_answers_the_panel(plan: str) -> None:
    """Step 4's box answers a Before this review panel for the steps under it; a step elsewhere
    that presses Review says the owner's answer itself, and step 5.5 opens A resolved both
    times, as step 4.1 does."""
    flat = {
        number: re.sub(r"\s+", " ", step(plan, number)) for number in STEP_HEADING.findall(plan)
    }
    outside = [
        number
        for number, text in flat.items()
        if not number.startswith("4.") and PRESS_REVIEW.search(text)
    ]

    assert outside == ["3.4", "5.5"]
    for number in outside:
        assert "decision 14A" in flat[number], number
        assert "never resolve or unsuppress a part" in flat[number], number
    assert flat["5.5"].count("open A resolved and part J") == 2
    assert [
        match.group(0)
        for match in PRESS_REVIEW.finditer(
            "press Review; Press **Review** with; do **not** press Review; do not press Review;"
            " `Press Review to review <document>.`; press **Review available evidence**"
        )
    ] == ["press Review", "Press **Review**"]


PROBE_NAMES_COMMIT = re.compile(r'git merge-base --is-ancestor ([0-9a-f]{7,40}) HEAD; "holds \1: ')
"""Step 1.4's check that the build holds the commit from which the probe names each dimension."""


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """`git` with `args`, run in the repository, its output captured."""
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=60, check=False
    )


def named_dimension_line(probe_tests: str) -> list[str]:
    """The D8 line of the fictional 10 mm hole that the extractor's probe tests expect, up to its
    first `;`, as the report prints it; none before the probe named each dimension."""
    expected = re.findall(
        r'"(  ddm:0001 \(sheet 1, dvw:0002\): name \\"[^"\\]+\\", view \\"[^"\\]+\\", value '
        r'10\.0000 mm;) "',
        probe_tests,
    )
    return [line.replace('\\"', '"') for line in expected]


PROBE_TESTS = "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"


def test_step_1_4_checks_for_the_first_build_whose_probe_names_each_dimension(
    plan: str,
) -> None:
    """Step 3.8 finds a named callout by the name and value D6 and D8 print, and step 1.4
    copies the results sheet; a build without either wastes the sitting. Section 0.1 names the
    commit that has to be pushed, step 1.4 checks the seat's build holds it, and that commit is
    the first to hold the named line, the sheet already there."""
    [commit] = PROBE_NAMES_COMMIT.findall(step(plan, "1.4"))
    handover = HANDOVER.read_text(encoding="utf-8")

    assert f"`{commit}`" in step(plan, "0.1")
    assert PROBE_NAMES_COMMIT.search(handover), "the handover's step 1 runs the same check"
    if not (REPO / ".git").exists():
        pytest.skip(f"{REPO} is not a git checkout, so {commit} cannot be read")
    if git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        shallow = git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
        if shallow:
            pytest.skip(f"the checkout is shallow and does not hold {commit}")
        pytest.fail(f"step 1.4 names {commit}, which this checkout does not hold")

    assert git("merge-base", "--is-ancestor", commit, "HEAD").returncode == 0
    assert git("cat-file", "-e", f"{commit}:docs/workstation-results-2026-09-23.md").returncode == 0
    assert named_dimension_line(git("show", f"{commit}:{PROBE_TESTS}").stdout) != []
    assert named_dimension_line(git("show", f"{commit}^:{PROBE_TESTS}").stdout) == []


def test_a_blocked_item_3_at_step_3_5_costs_only_its_own_rows(plan: str, results: str) -> None:
    """3.5's item 3 needs D-1 saved with detailing data; when it cannot run, only the two rows it
    feeds are blocked, and 011 T063's items 1 and 2 keep the row that holds their result."""
    rows = [cell for step, cell, *_ in result_rows(results) if step == "3.5"]
    item_3 = [cell for cell in rows if cell.endswith("(item 3)")]
    t063 = [cell for cell in rows if ("011", "T063") in qualified_tasks(cell)]

    assert set().union(*(qualified_tasks(cell) for cell in item_3)) == {
        ("011", "T063"), ("006", "T107"),
    }
    assert [cell for cell in t063 if cell not in item_3] != []
    assert "the two item 3 rows of 3.5" in step(plan, "3.5")
    assert "both rows of this item" not in plan


def test_the_named_callouts_are_found_by_name_and_value_and_otherwise_not_decidable(
    plan: str,
) -> None:
    """011 T066 is decidable only if the engineer can find the callout named in advance: row H
    asks for its name as SOLIDWORKS shows it, and step 3.8 finds its line by that name and its
    value, keeping "record every line and write not decidable" for a callout still not found."""
    row_h = next(line for line in plan.splitlines() if line.startswith("| H |"))
    named = re.sub(r"\s+", " ", step(plan, "3.8"))

    assert "Primary Value" in row_h and "D1@Sketch2" in row_h
    assert "name and value" in named
    assert "not decidable: <n> lines for callout" in named
    assert "Never pick one by its radius" in named
    assert "the only display dimension on their sheet" not in plan
    assert "No probe prints a dimension's value" not in plan


def test_the_plans_named_dimension_line_is_the_probes_own(plan: str) -> None:
    """The line step 3.8 shows the engineer is D8's own line for the fictional 10 mm hole, as the
    extractor's tests expect it, up to the first `;`; rule 5 keeps its name, view and value out
    of the findings document."""
    [line] = named_dimension_line((REPO / PROBE_TESTS).read_text(encoding="utf-8"))

    assert line in step(plan, "3.8")
    assert 'never copy its `name "..."`, `view "..."` or `value`' in re.sub(r"\s+", " ", plan)


def test_no_value_of_a_named_dimension_goes_into_the_findings_document(plan: str) -> None:
    """The owner commits the findings document to the public repository, and
    `contracts/probes.md` section 1 lets no name or value from a D6 or D8 report into a tracked
    file. So step 3.8 records a callout by its id and its answers as true or false - never its
    value, nor its face's radius, which is half the value - and the handover says the same; the
    report keeps them, in the handover folder."""
    named = re.sub(r"\s+", " ", step(plan, "3.8"))
    handover = re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))
    sheet = re.sub(r"\s+", " ", RESULTS.read_text(encoding="utf-8"))

    assert "Record its value" not in named
    assert "each by its id and value" not in named
    assert "Never its name, view, value or radius (rule 5)" in named
    assert "never a dimension's name, view, value or radius" in handover
    assert "never a dimension's name, view, value or radius" in sheet


def test_the_plan_never_lets_the_update_script_pull(plan: str) -> None:
    """Every run of the script in the plan builds what is checked out: the pull is step 1.3's own
    line, before it, so the script that runs is the one that arrived."""
    runs = re.findall(r"\.\\extractor\\tools\\update-workstation\.ps1[^`\n]*", plan)

    assert len(runs) >= 6
    assert [run for run in runs if " -NoPull" not in run] == []


def test_the_update_script_fetches_before_it_decides_not_to_pull() -> None:
    """The plan says every run of the script, `-NoPull` included, starts at `== git fetch origin`,
    and that `-NoPull` on a branch other than main - a detached checkout included - builds rather
    than refuses. Both are the script's order."""
    script = (REPO / "extractor" / "tools" / "update-workstation.ps1").read_text(encoding="utf-8")
    fetch = script.index('Invoke-Step "git fetch origin"')
    not_main = script.index("if ($branch -ne 'main')")
    refusal = script.index("if (-not $NoPull)", not_main)
    builds = script.index("with -NoPull: building what is checked out", not_main)

    assert fetch < not_main < refusal < builds


HANDOVER = REPO / "docs" / "workstation-handover-2026-09-23.md"
FENCED = re.compile(r"^\s*```[a-z]*\n(.*?)^\s*```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`([^`]+)`")
COMMAND = re.compile(
    r"^(?:swreview-extract |uv run |cmd /c |dotnet |git |\.\\extractor\\|New-Item |\(Get-Item |"
    r"Get-Content |Select-String |Show-|Set-Alias |Copy-Item |Remove-Item |\$env:|if \(|"
    r"powershell -|update-workstation\.ps1 -|register-addin\.ps1 -)"
)
PROBES = re.compile(r"--probe (D[0-9]+(?:,D[0-9]+)*)")


def as_command(text: str) -> str:
    """A command with its placeholders made alike: the handover's `"<handover folder>` is the
    plan's `"$H`, and any other quoted placeholder (`"<full path of C>"`, `"<drawing>"`) is
    `"<>"`; runs of spaces are one."""
    text = text.replace('"<handover folder>', '"$H')
    text = re.sub(r'"<[^"<>]*>"', '"<>"', text)
    return re.sub(r"\s+", " ", text).strip()


def code_lines(text: str) -> list[str]:
    """Each line of the code blocks of `text`, less a trailing comment, blank and comment lines
    left out."""
    lines = []
    for block in FENCED.findall(text):
        for line in block.splitlines():
            line = re.sub(r"\s{2,}#.*$", "", line).strip()
            if line and not line.startswith("#"):
                lines.append(line)
    return lines


def inline_commands(text: str) -> list[str]:
    """Each inline code span outside the code blocks that starts as a command does."""
    spans = (re.sub(r"\s*\n\s*", " ", span) for span in INLINE_CODE.findall(FENCED.sub("", text)))
    return [span for span in spans if COMMAND.match(span)]


def test_the_handover_gives_only_commands_the_plan_gives() -> None:
    """The handover is the same sitting for the assistant; where the two differ the plan is what
    the seat follows, so every command the handover gives is the plan's, placeholders aside: a
    line of a handover block is a whole line of a plan block, and a command written in the text
    is written so in the plan."""
    handover = HANDOVER.read_text(encoding="utf-8")
    plan_text = PLAN.read_text(encoding="utf-8")
    plan_lines = {as_command(line) for line in code_lines(plan_text)}
    plan = as_command(plan_text)
    lines = code_lines(handover)
    spans = inline_commands(handover)

    assert len(lines) >= 15
    assert len(spans) >= 12
    assert [line for line in lines if as_command(line) not in plan_lines] == []
    assert [span for span in spans if as_command(span) not in plan] == []


def test_the_handovers_no_push_rule_cites_the_runbook_section_that_holds_it() -> None:
    """The seat pushes nothing at this sitting. The runbook's rule 2 lets a seat push a
    `workstation/<date>` branch; the rule for a sitting run from the test plan is the last
    bullet of its section 8, which is the one the handover cites."""
    handover = re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))
    runbook = RUNBOOK.read_text(encoding="utf-8")
    section_8 = re.sub(r"\s+", " ", runbook[runbook.index("## 8. ") : runbook.index("## 9. ")])

    assert "from the development machine (runbook section 8, the test plan's step 6.5)" in handover
    assert "runbook rule 2" not in handover
    assert "A sitting run by an engineer from the test plan pushes nothing** (its step 6.5)" in (
        section_8
    )


def test_every_probe_selection_the_handover_names_is_one_the_plan_runs() -> None:
    plan = set(PROBES.findall(PLAN.read_text(encoding="utf-8")))
    named = PROBES.findall(HANDOVER.read_text(encoding="utf-8"))

    assert len(named) >= 10
    assert [probes for probes in named if probes not in plan] == []
    assert {"D1,D6,D7,D9,D10", "D4,D5,D6,D8"} <= set(named)


def test_the_runbooks_quick_reference_pulls_before_it_runs_the_script() -> None:
    runbook = (REPO / "docs" / "workstation-runbook.md").read_text(encoding="utf-8")
    quick = runbook[runbook.index("## 9. Quick reference") :]
    [run] = [line for line in quick.splitlines() if "update-workstation.ps1" in line]

    assert quick.index("git pull --ff-only origin main") < quick.index(run)
    assert "-NoPull" in run


def test_the_results_sheet_has_a_row_for_every_step_and_task_a_heading_names(
    plan: str, results: str
) -> None:
    rows = {(step, task) for step, cell, *_ in result_rows(results)
            for task in qualified_tasks(cell)}
    tagged = [(step, qualified_tasks(tags)) for step, tags in TAGGED_STEP.findall(plan)]

    assert len(tagged) >= 20
    missing = [(step, f"{package} {task}") for step, tasks in tagged
               for package, task in sorted(tasks) if (step, (package, task)) not in rows]
    assert missing == []


def test_every_row_of_the_results_sheet_names_a_step_of_the_plan(
    plan: str, results: str
) -> None:
    steps = set(STEP_HEADING.findall(plan))

    assert [step for step, *_ in result_rows(results) if step not in steps] == []


def test_every_open_seat_task_not_set_aside_has_a_row(plan: str, results: str) -> None:
    rowed = set().union(*(qualified_tasks(cell) for _, cell, *_ in result_rows(results)))
    aside = not_in_this_sitting(plan)

    for package in PACKAGES:
        number = package[:3]
        missing = [task for task in open_seat_tasks(package)
                   if (number, task) not in aside and (number, task) not in rowed]
        assert missing == [], f"{package}: {missing}"
    assert {("011", "T095"), ("008", "T105"), ("009", "T085")} <= aside
    assert {("006", "T100"), ("006", "T103"), ("006", "T105"), ("006", "T107")} <= rowed


def test_the_results_sheet_ships_blank(results: str) -> None:
    rows = result_rows(results)

    assert len(rows) >= 50
    assert [row for row in rows if any(row[2:])] == []


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


EARLIER_TASKS = frozenset({("006", "T101"), ("006", "T102"), ("007", "T059"), ("007", "T060")})
"""The four seat tasks of features 006 and 007 the owner added to this sitting (decision 15A,
2026-09-24)."""
EARLIER_PACKAGES = {"006": "006-standards-check", "007": "007-attention-policy-gate"}


def tagged_tasks(plan: str) -> set[tuple[str, str]]:
    """Every task id a step heading of the plan names in its brackets."""
    return set().union(*(qualified_tasks(tags) for _, tags in TAGGED_STEP.findall(plan)))


def rowed_tasks(results: str) -> set[tuple[str, str]]:
    """Every task id a row of the results sheet names."""
    return set().union(*(qualified_tasks(cell) for _, cell, *_ in result_rows(results)))


def earlier_tasks_not_asked(plan: str) -> set[tuple[str, str]]:
    """The task ids of the plan's last table, the earlier features' tasks not asked this time."""
    return qualified_tasks(plan[plan.index("Open seat or key tasks of earlier features") :])


def assert_named_only_at(
    places: dict[tuple[str, str], set[str]], plan: str, results: str
) -> None:
    """Each task is named by exactly the step headings `places` gives it, and rowed at exactly
    those steps of the results sheet."""
    headings = {number: qualified_tasks(tags) for number, tags in TAGGED_STEP.findall(plan)}
    rows = [(number, qualified_tasks(cell)) for number, cell, *_ in result_rows(results)]

    for task, steps in places.items():
        assert {number for number, tasks in headings.items() if task in tasks} == steps, task
        assert {number for number, tasks in rows if task in tasks} == steps, task


def test_the_four_earlier_seat_tasks_the_owner_added_are_in_this_sitting(
    plan: str, results: str
) -> None:
    """Decision 15A: 006 T101 and T102 and 007 T059 and T060 each have a step that names them,
    a row of the results sheet, and are gone from the table of earlier tasks not asked; each is
    still an open seat task of its package, so the plan asks for work that is there to do."""
    assert EARLIER_TASKS <= tagged_tasks(plan)
    assert EARLIER_TASKS <= rowed_tasks(results)
    assert EARLIER_TASKS.isdisjoint(earlier_tasks_not_asked(plan))
    for number, task in EARLIER_TASKS:
        assert task in open_seat_tasks(EARLIER_PACKAGES[number]), f"{number} {task}"
    assert "decision 15A" in re.sub(r"\s+", " ", plan[: plan.index("## The rules")])


def test_each_earlier_task_is_read_where_its_documents_are_already_open(
    plan: str, results: str
) -> None:
    """006 T101 and T102 read A and B while step 3.1 has them open; 007 T059 reads the review
    of A (step 4.1) and the Model check and Standards results of part J (steps 5.1 and 5.2);
    007 T060 times A's review (step 4.5)."""
    assert_named_only_at(
        {
            ("006", "T101"): {"3.1"},
            ("006", "T102"): {"3.1"},
            ("007", "T059"): {"4.1", "5.1", "5.2"},
            ("007", "T060"): {"4.5"},
        },
        plan,
        results,
    )


FEATURE_004 = REPO / "specs" / "004-resilient-remodeler"
RMS = REPO / "extractor" / "SwReview.Extractor" / "Rms"
PROBE_RUNS = tuple(("004", f"T{number:03d}") for number in range(33, 40))
"""004 T033 to T039, the re-modeler probes step 5.6 runs."""
DECISION_18A_TASKS = frozenset({("004", "T003"), ("004", "T164"), *PROBE_RUNS})
"""Feature 004's items the owner added to this sitting (decision 18A, 2026-09-25)."""
OPEN_TASK = re.compile(r"^- \[ \] (T\d{3})\b", re.MULTILINE)
"""An open task of any kind; feature 004 marks its seat tasks `Workstation`, not `[W]`."""
TASK_LINE = re.compile(r"^- \[[ xX]\] (T\d{3}[a-z]?)\b", re.MULTILINE)
"""A task of any kind, open or done, by the id it is defined under."""


def test_every_tasks_list_defines_each_task_id_once() -> None:
    """A results row's `004 T164` must name one task. Two lanes that each add a task on the same
    day can take the same next number, as decision 17A's T142 and decision 18A's FeatureWorks
    record did before they met on main."""
    lists = sorted((REPO / "specs").glob("*/tasks.md"))

    assert len(lists) >= 11
    for tasks in lists:
        ids = TASK_LINE.findall(tasks.read_text(encoding="utf-8"))
        assert ids, tasks.parent.name
        assert sorted({task for task in ids if ids.count(task) > 1}) == [], tasks.parent.name


def test_decision_18a_puts_feature_004s_three_items_in_the_sitting(
    plan: str, results: str
) -> None:
    """Decision 18A: the FeatureWorks record (004 T164), the packages 004 T003 reads and the
    probes 004 T033 to T039 each have a step that names them and a row, and are gone from the
    table of earlier tasks not asked, which keeps the stage-1 runs T135 to T141. Each is still
    open in 004's `tasks.md`, and T164, which no task described before, is dated there with the
    decision that added it."""
    tasks = (FEATURE_004 / "tasks.md").read_text(encoding="utf-8")
    [t164] = [line for line in tasks.splitlines() if line.startswith("- [ ] T164 ")]

    assert DECISION_18A_TASKS <= tagged_tasks(plan)
    assert DECISION_18A_TASKS <= rowed_tasks(results)
    assert DECISION_18A_TASKS.isdisjoint(earlier_tasks_not_asked(plan))
    assert {("004", f"T{number}") for number in range(135, 142)} <= earlier_tasks_not_asked(plan)
    assert {task for _, task in DECISION_18A_TASKS} <= set(OPEN_TASK.findall(tasks))
    assert "added 2026-09-25, the owner's decision 18A" in t164
    assert "FeatureWorks" in t164 and "step 1.7" in t164
    for document in (plan, results, HANDOVER.read_text(encoding="utf-8")):
        assert ("004", "T142") not in qualified_tasks(document), (
            "004 T142 is decision 17A's node test; the FeatureWorks record is T164"
        )
    assert "decision 18A" in re.sub(r"\s+", " ", plan[: plan.index("## The rules")])
    assert "decision 18A" in re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))
    assert ("004", "T003") in qualified_tasks(
        plan[plan.index("## Not in this sitting") : plan.index("Open seat or key tasks")]
    ), "the development machine's table says who runs T003's dry run"


def test_each_decision_18a_item_has_its_one_place(plan: str, results: str) -> None:
    """The FeatureWorks record at step 1.7, beside the health checks' Tools > Add-ins; the
    owner's parts at step 5.1, on the Model check tab; the probes at step 5.6."""
    assert_named_only_at(
        {
            ("004", "T164"): {"1.7"},
            ("004", "T003"): {"5.1"},
            **{task: {"5.6"} for task in PROBE_RUNS},
        },
        plan,
        results,
    )


def test_the_remodel_probes_are_the_last_step_before_the_handoff(plan: str) -> None:
    """A "Cannot reorder" box can hold SOLIDWORKS, and PROBE-1 asks for one, so step 5.6 comes
    after everything but the handoff - after 5.5's return to the current build - with no
    document open, and 5.5 no longer calls itself last."""
    numbers = STEP_HEADING.findall(plan)
    headings = re.findall(r"^### (5\.[56]) (.*)$", plan, re.MULTILINE)
    probes = re.sub(r"\s+", " ", step(plan, "5.6"))

    assert numbers[numbers.index("6.0") - 1] == "5.6"
    assert dict(headings)["5.6"].startswith("The re-modeler probes, with no document open: last ")
    assert "last" not in dict(headings)["5.5"]
    assert "blocked by 5.5" in probes
    assert "Window > Close All, **Don't Save**, so that no document is open" in probes
    assert "--allow-start" not in probes and "--keep-part" not in probes


def catalog_probes() -> list[str]:
    """The probe ids of `RemodelProbeCatalog`, in its order (the default `--probe` list)."""
    source = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")
    return re.findall(r'new RemodelProbeDefinition\(\s*"(PROBE-\d+)"', source)


PROBE_BODY = re.compile(
    r"private static RemodelProbeReading Probe(\d+)\(RemodelProbeContext context\)"
)


def probe_bodies() -> dict[str, str]:
    """Each probe's body in `RemodelProbeExecutors.cs`, by probe id, from its signature to the
    next probe's; every catalog probe has one, so reading bodies misses none."""
    source = (RMS / "RemodelProbeExecutors.cs").read_text(encoding="utf-8")
    starts = [(match.start(), f"PROBE-{match.group(1)}") for match in PROBE_BODY.finditer(source)]
    ends = [start for start, _ in starts[1:]] + [len(source)]
    bodies = {probe: source[start:end] for (start, probe), end in zip(starts, ends, strict=True)}

    assert set(bodies) == set(catalog_probes())
    return bodies


def reordering_probes() -> set[str]:
    """The probes whose body calls `ReorderFeature`: the ones a "Cannot reorder" box can hold."""
    return {probe for probe, body in probe_bodies().items() if "ReorderFeature(" in body}


REMODEL_RUN = re.compile(
    r'^\s*swreview-extract probe remodel --probe (\S+) --out "\$H\\probes\\([\w-]+)" '
    r'--acknowledge-throwaway-part; "exit code: \$LASTEXITCODE"$',
    re.MULTILINE,
)
"""One run of step 5.6: its probe list and its folder under the handover folder's probes."""


def test_the_three_runs_cover_the_catalog_once_with_probe_1_alone_and_last(plan: str) -> None:
    """Each run writes `capabilities/remodel-<version>.yaml` in its own `--out` folder and a
    second run into the same folder would overwrite it, so the three folders differ. A run that
    hangs never writes its ledger, so the first run holds exactly the probes whose bodies never
    reorder (read from the executors, so a body that starts reordering moves this pin), the
    second the remaining reorders, and the third PROBE-1 alone; together they are the catalog,
    once each, each run in the catalog's order. Each run is read back from its own folder."""
    probes = step(plan, "5.6")
    runs = [(ids.split(","), folder) for ids, folder in REMODEL_RUN.findall(probes)]
    catalog = catalog_probes()
    reorders = reordering_probes()
    ledger = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")

    assert plan.count("swreview-extract probe remodel --") == len(runs) == 3
    assert len({folder for _, folder in runs}) == 3
    assert sorted(probe for ids, _ in runs for probe in ids) == sorted(catalog)
    for ids, folder in runs:
        assert ids == [probe for probe in catalog if probe in ids], folder
        assert f'Show-RemodelLedger "$H\\probes\\{folder}"' in probes, folder
    assert set(runs[0][0]) == set(catalog) - reorders
    assert set(runs[1][0]) == reorders - {"PROBE-1"}
    assert runs[2][0] == ["PROBE-1"]
    assert "PROBE-1" in reorders
    for constant in ('DirectoryName = "capabilities"', 'FileNamePrefix = "remodel-"',
                     'FileNameExtension = ".yaml"'):
        assert constant in ledger
    assert "`capabilities\\remodel-<SOLIDWORKS version>.yaml`" in probes


def test_the_handover_runs_the_same_three_probe_runs() -> None:
    handover = HANDOVER.read_text(encoding="utf-8")
    plan_runs = REMODEL_RUN.findall(step(PLAN.read_text(encoding="utf-8"), "5.6"))

    assert REMODEL_RUN.findall(handover) == plan_runs
    assert "step 21 (004 T033 to T039), then only the handoff" in handover


def test_a_message_box_is_answered_only_after_probe_1s_watchdog_has_timed_both_tries(
    plan: str,
) -> None:
    """PROBE-1 decides "blocked" from a watchdog that waits `DefaultTimeout` for each of its two
    illegal reorders; a box answered before both have timed out lets the call return inside the
    timeout and reads as no box. So the wait step 5.6 asks for is longer than both tries, and
    the plan states the watchdog's own figure."""
    watchdog = (RMS / "RemodelProbeWatchdog.cs").read_text(encoding="utf-8")
    [timeout] = re.findall(r"DefaultTimeout = TimeSpan\.FromSeconds\((\d+)\)", watchdog)
    probes = re.sub(r"\s+", " ", step(plan, "5.6"))
    [wait] = re.findall(r"wait until \*\*(\d+) seconds\*\* have passed since it appeared", probes)

    assert f"times each of its two tries for {timeout} seconds" in probes
    assert int(wait) > 2 * int(timeout)
    assert "rule 6's one exception" in probes
    assert "step 5.6" in re.sub(r"\s+", " ", plan[plan.index("6. **Do not click") :][:400])


def test_the_lines_step_5_6_reads_are_the_consoles(plan: str) -> None:
    """The run refuses while a document is open, writes its ledger and its log only when it
    ends (so a run stopped with Ctrl+C leaves neither, as step 5.6 says), and ends with the
    count line and one BLOCKING line per blocking probe not verified; and it turns off the three
    options step 5.6 notes before the runs and checks after."""
    program = (REPO / "extractor" / "SwReview.Extractor.Console" / "Program.cs").read_text(
        encoding="utf-8"
    )
    run = program[program.index("private static int ExecuteProbeRemodel(") :]
    run = run[: run.index("private static void TryDeleteProbePart(")]
    log = (REPO / "extractor" / "SwReview.Extractor.Console" / "ExtractLog.cs").read_text(
        encoding="utf-8"
    )
    lines = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")
    toggles = (RMS / "RemodelSystemToggles.cs").read_text(encoding="utf-8")
    probes = re.sub(r"\s+", " ", step(plan, "5.6"))

    assert run.index("host.AnyDocumentOpen()") < run.index("host.BuildPart(")
    assert run.index("RemodelSystemToggles.Within(") < run.index("RemodelProbeLedger.Write(")
    assert log.count("File.AppendAllText(") == 1
    assert log.index("public void Dispose()") < log.index("File.AppendAllText(")
    assert "only when it ends, so after Ctrl+C neither exists" in probes
    fragments = [
        '"probes: {records.Count} run "',
        '"({Count(records, RemodelProbeVerdict.Verified)} verified, "',
        '"{Count(records, RemodelProbeVerdict.Refuted)} refuted, "',
        '"{Count(records, RemodelProbeVerdict.Unresolved)} unresolved)"',
        '$"BLOCKING {record.ProbeId} is {record.Verdict.CliName()}: {record.Fallback}"',
    ]
    places = [lines.index(fragment) for fragment in fragments]
    assert places == sorted(places)
    assert "`probes: <n> run (<n> verified, <n> refuted, <n> unresolved)`" in probes
    assert "`BLOCKING PROBE-<n> is <verdict>: ...`" in probes
    toggled = re.search(r"ToggleArray =\s*\{([^}]*)\}", toggles).group(1)
    assert [name.strip() for name in toggled.split(",") if name.strip()] == [
        "InputDimValOnCreate", "ShowErrorsEveryRebuild", "WarnSaveUpdateErrors",
    ]
    for option in ("**Input dimension value**", "**Show errors every rebuild**",
                   "**Warn before saving documents with update errors**"):
        assert option in probes, option
    assert "the three boxes are as item 1 noted" in probes


def rendered_ledger(records: list[tuple[str, bool, str, dict[str, str]]]) -> str:
    """A ledger in `RemodelProbeLedger.Render`'s shape (the test below pins the prefixes it
    relies on against the C# source): `(probe id, blocking, verdict, raw_result)` per probe."""
    lines = ['sw_version: "32.5.0.48"', 'generated_at: "2026-10-02T12:00:00.0000000+00:00"',
             "probes:"]
    for probe, blocking, verdict, raw in records:
        lines += [
            f'  - probe_id: "{probe}"',
            '    question: "a question"',
            '    method: "a method"',
            f"    blocking: {'true' if blocking else 'false'}",
            '    fallback: "a fallback"',
            f"    verdict: {verdict}",
            '    sw_version: "32.5.0.48"',
            "    duration_ms: 12",
            "    interop_members: []",
        ]
        if raw:
            lines.append("    raw_result:")
            lines += [f'      "{key}": "{value}"' for key, value in raw.items()]
        else:
            lines.append("    raw_result: {}")
    return "\n".join(lines) + "\n"


def test_the_fixture_ledger_has_the_shape_render_writes() -> None:
    """`Show-RemodelLedger` matches lines by their indentation and key, so the fixture's
    prefixes are the ones `RemodelProbeLedger.Render` appends, and the two raw_result keys it
    prints are the runner's error key and the reason key every probe body files."""
    ledger = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")

    for prefix in ('text.Append("  - probe_id: ")', 'text.Append("    blocking: ")',
                   'text.Append("    verdict: ")',
                   'text.Append("      ").Append(Quote(entry.Key)).Append(": ")',
                   "Encoding.UTF8"):
        assert prefix in ledger, prefix
    assert 'public const string ErrorKey = "error";' in ledger
    assert [probe for probe, body in probe_bodies().items() if '["reason"]' not in body] == []


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_show_remodel_ledger_prints_each_probes_verdict_and_reason(
    plan: str, tmp_path: Path
) -> None:
    run = tmp_path / "remodel-no-reorder"
    (run / "capabilities").mkdir(parents=True)
    (run / "capabilities" / "remodel-32.5.0.48.yaml").write_text(
        rendered_ledger(
            [
                ("PROBE-2", True, "verified", {
                    "equation_count": "1",
                    "equation_text": '\\"w\\" = 120',
                    "reason": "get_Value returned 120.",
                }),
                ("PROBE-13", False, "unresolved", {"error": "the call threw"}),
                ("PROBE-21", False, "refuted", {}),
            ]
        ),
        encoding="utf-8-sig",
    )
    empty = tmp_path / "remodel-probe-1"
    empty.mkdir()
    function = plan_function(plan, "Show-RemodelLedger")
    quoted, quoted_empty = (str(folder).replace("'", "''") for folder in (run, empty))

    lines = run_powershell(
        f"{function}\nShow-RemodelLedger '{quoted}'\nShow-RemodelLedger '{quoted_empty}\\'\n",
        tmp_path,
    )

    assert lines == [
        '- probe_id: "PROBE-2"',
        "blocking: true",
        "verdict: verified",
        '"reason": "get_Value returned 120."',
        '- probe_id: "PROBE-13"',
        "blocking: false",
        "verdict: unresolved",
        '"error": "the call threw"',
        '- probe_id: "PROBE-21"',
        "blocking: false",
        "verdict: refuted",
        "no answers file in this folder: the run did not finish",
    ]
    assert plan.index("function Show-RemodelLedger ") < plan.index("Set-Location $R")


FEATUREWORKS_LINE = re.compile(
    r"^FeatureWorks: installed (True|False) \| listed as an add-in (True|False) \| "
    r"start-up flag (\S+)$"
)
WRITING_COMMAND = re.compile(
    r"\b(Set-Item|Set-ItemProperty|New-Item|New-ItemProperty|Remove-Item|Remove-ItemProperty|"
    r"Rename-Item|Copy-Item|Move-Item|reg(?:\.exe)? (?:add|delete|import))\b",
    re.IGNORECASE,
)


def test_the_featureworks_record_only_reads(plan: str) -> None:
    """004 T164 is a record: the registry block writes nothing, the dialog is closed with Cancel
    with no box changed, and any answer passes."""
    record = step(plan, "1.7")
    flat = re.sub(r"\s+", " ", record)
    [block] = POWERSHELL_BLOCK.findall(record)

    assert WRITING_COMMAND.findall(block) == []
    assert WRITING_COMMAND.findall("Set-ItemProperty; reg add; New-Item") != []
    assert "**Change no box**" in flat and "close the dialog with **Cancel**, never OK" in flat
    assert "Any answer passes" in flat
    assert "Standard, Professional or Premium" in flat


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_the_featureworks_block_prints_its_one_line_on_any_machine(
    plan: str, tmp_path: Path
) -> None:
    """Run as pasted, it reads the registry only and prints one line in the shape step 1.7
    explains, whatever this machine has installed."""
    [block] = POWERSHELL_BLOCK.findall(step(plan, "1.7"))

    [line] = run_powershell(block, tmp_path)

    assert FEATUREWORKS_LINE.match(line), line
    assert FEATUREWORKS_LINE.match(
        "FeatureWorks: installed True | listed as an add-in False | start-up flag none"
    )


def test_the_featureworks_line_does_not_stand_in_for_the_dialog(plan: str) -> None:
    """`listed as an add-in` reads only the two `AddIns` keys the block names, and SOLIDWORKS's own
    add-ins need not be under either: on the development machine's SOLIDWORKS 2024 SP5, the seat's
    version, FeatureWorks's id resolves to its program and is under neither key, and the account's
    start-up flags name two more of SOLIDWORKS's own add-ins that are under neither. So `False` is
    not an absence from Tools > Add-ins; step 1.7 says so, names the keys it read, and leaves the
    answer to the dialog (004 T164, the review of 2026-09-25)."""
    record = re.sub(r"\s+", " ", step(plan, "1.7"))
    [block] = POWERSHELL_BLOCK.findall(step(plan, "1.7"))
    [keys] = re.findall(r"\$listed = @\(Get-Item ('[^)]*') -ErrorAction", block)
    read = re.findall(r"'HKLM:\\([^']+)'", keys)

    assert read == ["SOFTWARE\\SolidWorks\\AddIns", "SOFTWARE\\SolidWorks\\SOLIDWORKS 20*\\AddIns"]
    for key in read:
        assert f"`HKLM\\{key}`" in record, key
    assert "`listed as an add-in True` when SOLIDWORKS offers it" not in record
    assert "`listed as an add-in False` does not mean Tools > Add-ins lacks FeatureWorks" in record
    assert "so the dialog is the answer" in record


def test_the_seat_plan_names_decision_17as_tasks_where_they_meet_the_sitting(plan: str) -> None:
    """Decision 17A's tasks landed on main the same day as 18A's seat plan and meet the sitting in
    four places, where the plan and the handover name them by id. FeatureWorks ships with every
    seat tier (004 T149), so step 1.7 records whether the add-in is there, not which tier has it;
    the planner refuses a derived or mirrored part (004 T147), so row P asks for neither; T003's
    packages replace 004 T148's provisional counts; and the stage-1 runs also wait on 004 T152 to
    T160, the production seat adapter, which is not built."""
    record = re.sub(r"\s+", " ", step(plan, "1.7"))
    row_p = next(line for line in plan.splitlines() if line.startswith("| P |"))
    later = plan[plan.index("## Not in this sitting") : plan.index("Open seat or key tasks")]
    handover = re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))
    featureworks = handover[handover.index("19. **004 T164") : handover.index("20. **004 T003")]
    adapter = {("004", f"T{number}") for number in range(152, 161)}

    for text in (record, featureworks):
        assert ("004", "T149") in qualified_tasks(text)
        assert "the last two" not in text and "Professional or Premium seat" not in text
    assert ("004", "T147") in qualified_tasks(row_p) and "mirrored" in row_p
    assert ("004", "T148") in qualified_tasks(later)
    assert adapter <= earlier_tasks_not_asked(plan)
    assert {("004", "T148"), *adapter} <= qualified_tasks(handover)


def test_the_owners_parts_give_004_t003_its_packages_and_no_name(plan: str) -> None:
    """Row P asks the owner for three to five parts, one with a long feature tree; step 5.1
    presses Model check on each, checks the folder holds the package the dry run reads, says
    where the folders go and keeps every part's name out of the findings document."""
    row_p = next(line for line in plan.splitlines() if line.startswith("| P |"))
    parts = re.sub(r"\s+", " ", step(plan, "5.1"))

    assert "three to five real parts **the owner names**" in row_p
    assert "long feature tree" in row_p and row_p.endswith("| step 5.1 |")
    assert "`notes\\paths.txt`" in row_p
    for phrase in ("holds `package.json` beside", "`run-folders.zip`",
                   "No part name, number or feature name goes in the findings document",
                   "They never enter the repository: only counts do",
                   "`swreview remodel plan`", "`blocked: <n> parts named`"):
        assert phrase in parts, phrase
    assert "step 5.1's P folders" in re.sub(r"\s+", " ", step(plan, "6.3"))


def test_the_standards_probe_reads_each_recorded_assembly_right_after_its_dump(plan: str) -> None:
    """Step 3.1 runs `probe standards` on the active assembly, as its dump does (no `--doc`),
    into its own report in the probe folder, after the dump and before the fingerprint, so the
    fingerprint also covers whatever the probe might have touched; the report is read by
    component id and never copied by name."""
    dumps = step(plan, "3.1")
    flat = re.sub(r"\s+", " ", dumps)
    [probe] = [line for line in dumps.splitlines() if "swreview-extract probe standards" in line]

    assert "--doc" not in probe
    assert '"$H\\probes\\probe-standards-A.txt"' in probe
    assert "the same three lines with `B` in place of `A`" in flat
    assert dumps.index("swreview-extract dump") < dumps.index(probe)
    assert dumps.index(probe) < dumps.index("Save-Fingerprint 'before'")
    for section in ("probe-1 exploded_state:", "probe-2 appearance_overrides:",
                    "probe-3 component_visibility:"):
        assert section in dumps
    for gate in ("mutating members: none", "refusals: none", "sheet activation: none",
                 "document opening: none", "display state: none"):
        assert gate in flat
    assert "blocked: no <kind> in A or B" in flat
    assert "Never a component's, configuration's or view's name (rule 5)" in flat
    assert "a component is its id (`cmp:` and four digits), never its name" in re.sub(
        r"\s+", " ", plan[plan.index("## The rules") : plan.index("## When a step fails")]
    )


def test_the_components_step_3_1_reads_are_noted_before_the_sitting(plan: str) -> None:
    """The engineer finds the kinds PROBE-1 to PROBE-3 ask about in A and B beforehand, and
    changes nothing to make a missing one."""
    documents = re.sub(r"\s+", " ", step(plan, "0.2"))

    for kind in ("hidden", "suppressed", "hidden only in a display state", "transparent",
                 "appearance override", "exploded view", "sub-assemblies"):
        assert kind in documents, kind
    assert "Change nothing to make one" in documents


def test_step_3_1_finds_each_component_by_the_path_the_probe_prints(plan: str) -> None:
    """PROBE-2 and PROBE-3 print a component as its id, a space, `IComponent2.Name2` and a space
    - the full instance path, `sub-2/bracket-3`, never the tree's `bracket<3>` - so section 0.2
    notes each sub-assembly above a component, and step 3.1 says how the tree's name becomes the
    path and searches for it between spaces, so that neither a longer name (`bracket-30`) nor
    another sub-assembly's instance matches. The handover says the same."""
    program = re.sub(
        r"\s+",
        " ",
        (REPO / "extractor" / "SwReview.Extractor.Console" / "Program.cs").read_text(
            encoding="utf-8"
        ),
    )
    dump = REPO / "extractor" / "SwReview.Extractor" / "Dump"
    contracts = (dump / "DumpContracts.cs").read_text(encoding="utf-8")
    dumper = (dump / "ComponentTreeDumper.cs").read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", step(plan, "3.1"))

    assert '{component.Id} {component.Node.Key}" + " HasMaterialPropertyValues="' in program
    assert '{component.Id} {node.Key}" + " Visible="' in program
    assert 'Full instance path, e.g. "sub-2/bracket-3"' in contracts
    assert 'string key = gate.Call("Name2", () => component.Name2)' in dumper
    assert "the name of each sub-assembly above it" in re.sub(r"\s+", " ", step(plan, "0.2"))
    assert "by its name (Ctrl+F)" not in plan
    assert "writes the instance number `<3>` as `-3`" in flat
    assert "`sub-2/bracket-3` inside sub-assembly `sub<2>`" in flat
    assert "type a space, the path and a space in the search box" in flat
    assert "`sub<2>` is `sub-2/bracket-3`" in re.sub(
        r"\s+", " ", HANDOVER.read_text(encoding="utf-8")
    )


def test_the_timing_is_recorded_once_the_backend_no_longer_holds_the_review(plan: str) -> None:
    """007 T060. A live review's session is saved again at the end of every turn
    (`chat.sessions.record_timing_live`), so minutes written to its folder while the backend
    holds it can be lost to a later turn - step 4.4 sends one. Step 4.1 takes the minutes; the
    command runs in step 4.5 after the restart that leaves A's review read-only, and only
    there."""
    chips = step(plan, "4.5")
    restart = chips.index("The backend restarted, so this review is shown from its run folder.")

    assert plan.count("uv run swreview timing") == 1
    assert restart < chips.index("uv run swreview timing")
    assert "baseline" in step(plan, "4.1") and "uv run swreview timing" not in step(plan, "4.1")
    sessions = (REVIEWER / "src" / "swreview" / "chat" / "sessions.py").read_text(encoding="utf-8")
    assert "minutes written only to disk would be gone" in re.sub(r"\s+", " ", sessions)


def test_the_timing_line_passes_the_four_inputs_swreview_timing_takes(
    plan: str, tmp_path: Path
) -> None:
    """The line step 4.5 pastes names each of the command's four inputs once, each a quoted
    placeholder, and a placeholder left unreplaced is refused with the message the step
    quotes, writing nothing."""
    [line] = [line for line in plan.splitlines() if "uv run swreview timing" in line]
    given = re.findall(r"(--[a-z-]+) '<[^'<>]+>'", line)
    timing = get_command(app).commands["timing"]
    inputs = {opt for param in timing.params for opt in param.opts if opt.startswith("--")}

    assert sorted(given) == sorted(inputs - {"--json"})
    run = tmp_path / "run"
    shutil.copytree(FIXTURES / "attention" / "review-folder", run)
    before = (run / "session.json").read_bytes()
    refused = CliRunner().invoke(app, ["timing", str(run), "--baseline", "<baseline minutes>"])

    assert refused.exit_code == 2
    assert "Invalid value for '--baseline'" in refused.output
    assert "Invalid value for '--baseline'" in step(plan, "4.5")
    assert (run / "session.json").read_bytes() == before


def plan_function(text: str, name: str) -> str:
    """The whole PowerShell function `name` as the plan's setup block defines it."""
    start = text.index(f"function {name} ")
    return text[start : text.index("\n}\n", start) + 2]


def run_powershell(script: str, folder: Path) -> list[str]:
    """Run `script` in Windows PowerShell and answer the lines it printed."""
    path = folder / "run.ps1"
    path.write_text(script, encoding="utf-8-sig")
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == "", completed.stderr
    return completed.stdout.splitlines()


def show_start_here(plan: str, run: Path, folder: Path) -> list[str]:
    """What the plan's `Show-StartHere` prints for the run folder `run`."""
    quoted = str(run).replace("'", "''")
    return run_powershell(f"{plan_function(plan, 'Show-StartHere')}\nShow-StartHere '{quoted}'\n",
                          folder)


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
@pytest.mark.parametrize("fixture", ["review-folder", "check-folder"])
def test_show_start_here_prints_the_reports_rows_in_its_order(
    plan: str, tmp_path: Path, fixture: str
) -> None:
    """007 T059 compares the pane's Start here rows with `report.md`'s: the helper prints the
    finding ids the report's own section lists, in its order and no more (the first `top_n` of
    the ranking), for a review's folder and a check folder alike."""
    run = tmp_path / fixture
    shutil.copytree(FIXTURES / "attention" / fixture, run)
    rerender_run_folder(run)
    ranking = rank(load_session(run / "session.json"))
    expected = [row.finding_id for row in ranking.rows[: ranking.top_n]]

    lines = show_start_here(plan, run, tmp_path)

    assert expected
    assert lines == ["Start here in report.md: " + ", ".join(expected)]
    assert plan.index("function Show-StartHere ") < plan.index("Set-Location $R")


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_show_start_here_prints_the_nothing_to_start_with_line(plan: str, tmp_path: Path) -> None:
    run = tmp_path / "run"
    shutil.copytree(FIXTURES / "attention" / "review-folder", run)
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    session["findings"] = []
    (run / "session.json").write_text(json.dumps(session), encoding="utf-8")
    rerender_run_folder(run)
    [nothing] = [line for line in (run / "report.md").read_text(encoding="utf-8").splitlines()
                 if line.startswith("Nothing to start with")]

    assert show_start_here(plan, run, tmp_path) == [nothing]


TIME = re.compile(r"(?:(\d+) h)?\s*(?:(\d+) min)?")


def minutes(estimate: str) -> int:
    """`3 h 55 min`, `3 h` or `50 min` as minutes."""
    match = TIME.fullmatch(estimate.strip())
    assert match, estimate
    hours, mins = match.groups()
    return int(hours or 0) * 60 + int(mins or 0)


def test_the_time_estimate_is_the_sum_of_its_steps(plan: str) -> None:
    """The headline figure is the table's steps added up, to the nearest quarter hour, so a
    step that grows (decision 15A added about 25 minutes) moves the headline too. Decision 18A
    adds about 40: step 1 and step 5.1's row grow, and step 5.6 has a row of its own."""
    section = plan[plan.index("## How long it takes") : plan.index("## 0. Before the sitting")]
    rows = re.findall(r"^\| ([^|]+) \| [^|]+ \| ([^|]+) \|$", section, re.MULTILINE)[1:]
    [(hours, mins)] = re.findall(r"About \*\*(\d+) hours(?: (\d+) minutes)? at the seat", section)
    estimates = {name.strip(): minutes(estimate) for name, estimate in rows}

    assert len(rows) == 8
    assert abs(sum(estimates.values()) - (int(hours) * 60 + int(mins or 0))) <= 7
    assert estimates["5.6"] == 25 and estimates["1"] == 55 and estimates["5.1 to 5.4"] == 45
    assert 30 <= estimates["5.6"] + (estimates["1"] - 50) + (estimates["5.1 to 5.4"] - 35) <= 45


def powershell_parse_errors(sources: dict[str, str], folder: Path) -> str:
    """Each parse error Windows PowerShell finds in `sources` (a file name to its script), as
    `<file name> line <n>: <message> :: <that line>`, one per line; empty when every one
    parses."""
    for name, source in sources.items():
        (folder / f"{name}.ps1").write_text(source, encoding="utf-8-sig")
    command = (
        f"Get-ChildItem '{folder}' -Filter *.ps1 | Sort-Object Name | ForEach-Object {{ "
        "$errors = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, "
        "[ref]$null, [ref]$errors); "
        "$errors | ForEach-Object { \"$($_.Extent.File | Split-Path -Leaf) line "
        "$($_.Extent.StartLineNumber): $($_.Message) :: $($_.Extent.StartScriptPosition.Line)\" "
        "} }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_every_powershell_block_parses(plan: str, tmp_path: Path) -> None:
    """Every fenced PowerShell block of the plan, the handover and the runbook is pasted as it
    stands; the handover's are otherwise only compared line by line with the plan's, and the
    runbook's were read by nothing."""
    blocks = {
        name: POWERSHELL_BLOCK.findall(text)
        for name, text in (
            ("plan", plan),
            ("handover", HANDOVER.read_text(encoding="utf-8")),
            ("runbook", RUNBOOK.read_text(encoding="utf-8")),
        )
    }
    assert len(blocks["plan"]) >= 20
    assert blocks["handover"] and blocks["runbook"]

    assert powershell_parse_errors(
        {
            f"{name}-{index:02d}": block
            for name, found in blocks.items()
            for index, block in enumerate(found)
        },
        tmp_path,
    ) == ""


RUNBOOK = REPO / "docs" / "workstation-runbook.md"
FLAG_WITH_BARE_PLACEHOLDER = re.compile(r"(?<![\w-])-{1,2}[A-Za-z][\w-]* <[^<>\n]+>")
"""A flag followed by a placeholder outside quotes: `--from <file>`, `-SolidWorksRoot <root>`."""


def test_no_flag_is_given_a_bare_placeholder_even_in_a_comment() -> None:
    """The plan's rule quotes every placeholder, since Windows PowerShell refuses `<` outside
    quotes. The parse tests read commands and code lines, not a block's comments or a table's
    hint, and an engineer copies from those too: the runbook's first-install and quick-reference
    comments and its `--out` hint kept `<file>`, `<root>` and `<new folder>` bare after the
    inline commands were quoted."""
    for path in (PLAN, HANDOVER, RUNBOOK):
        text = path.read_text(encoding="utf-8")

        assert FLAG_WITH_BARE_PLACEHOLDER.findall(text) == [], path.name
    assert FLAG_WITH_BARE_PLACEHOLDER.findall("# -TokenizerFrom <file>, --out <new folder>") == [
        "-TokenizerFrom <file>", "--out <new folder>"
    ]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_every_command_written_in_the_text_parses(tmp_path: Path) -> None:
    """A command written inline in the plan, the handover or the runbook is pasted as it stands,
    so it must parse too: a placeholder outside quotes (`--from <file>`) is a parse error."""
    documents = {
        "plan": PLAN,
        "handover": HANDOVER,
        "runbook": REPO / "docs" / "workstation-runbook.md",
    }
    spans = {
        f"{name}-{index:03d}": span
        for name, path in documents.items()
        for index, span in enumerate(inline_commands(path.read_text(encoding="utf-8")))
    }
    assert len(spans) >= 70

    assert powershell_parse_errors(spans, tmp_path) == ""
