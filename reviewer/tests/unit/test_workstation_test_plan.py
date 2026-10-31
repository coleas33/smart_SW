"""The engineer's plan for the next seat sitting holds to the tasks and to the product (011 T100).

`docs/test-plan-2026-09-27/workstation-test-plan.md` is the sitting of
`docs/test-plan-2026-09-27/workstation-handover.md` in plain, numbered steps for the engineer who
runs it, who is not a developer. It cannot be run here (every step needs the licensed seat), so
what it promises is held in its text:

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
- the results sheet (`docs/test-plan-2026-09-27/workstation-results.md`), which the plan copies
  into the handover folder as the findings document, has a row for every step and task id a
  step heading names, every row names a step the plan has, every open seat task the plan does
  not set aside under "Not in this sitting" has a row, and it ships blank;
- the four earlier seat tasks the owner added (decision 15A: 006 T101 and T102, 007 T059 and
  T060) each have a step where their documents are already open and a row, and are gone from
  the table of earlier tasks not asked; `Show-FindingsByType` prints a committed report's
  Findings by type, group by group, the timing line passes `swreview timing`'s four inputs, and
  the headline
  time is the steps' sum;
- feature 004's three items the owner added (decision 18A, 2026-09-25) do the same: the
  FeatureWorks record (004 T164, dated in 004's `tasks.md`) at step 1.7 is read only and prints
  one line; the owner's parts at step 5.1 give 004 T003 its packages and no name; the probes
  004 T033 to T039 are step 5.6, the last before the handoff, in three runs into three folders -
  every other probe whose body never reorders first, Start's five together last with PROBE-1
  last of all - that cover the probe catalog once; `Show-RemodelLedger` reads a ledger in
  `RemodelProbeLedger.Render`'s shape; a message box waits out PROBE-1's watchdog; and the lines
  step 5.6 reads are the console's;
- and since feature 004's seat adapter is in the build (2026-09-27), step 5.3 plans on a copy with
  Start refused by the switch, checks the settings after Plan (004 T176) and times it (004 T182),
  and the plan, the development machine's table and the handover say what the Start switch waits
  on: step 5.6's blocking probes in one answers file, then a Plan on one real part's copy, and the
  rest of 004 research R25.9's list.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from swreview.chat.remodel import OPEN_DIAGNOSTICS_FILE, _open_phase
from swreview.cli import app
from swreview.ir.loader import load_package
from swreview.remodel.ledger import START_PROBES, load_ledger, summary, summary_lines
from swreview.report.attention import load_policy, rank
from swreview.report.attention_record import StaleAttentionRecord, write_attention_record
from swreview.report.finding_groups import findings_by_type
from swreview.report.rerender import rerender_run_folder
from swreview.report.session import load_session
from swreview.report.summary import load_words
from swreview.tools.checks_interference import groups_of
from tests.support.console import plain_one_line
from tests.support.remodel_ledger import rendered_ledger
from tests.support.seat_tasks import (
    PACKAGES,
    REPO,
    open_seat_tasks,
    qualified_tasks,
    seat_tasks_in,
)

PLAN = REPO / "docs" / "test-plan-2026-09-27" / "workstation-test-plan.md"
RESULTS = REPO / "docs" / "test-plan-2026-09-27" / "workstation-results.md"
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

READ_ONLY_SENTENCE = (
    "The backend restarted, so this review is shown from its run folder. Follow-ups, decisions "
    "and answers are off."
)
"""The same literal product sentence, now composed from two words-file keys by feature 015."""

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
    # The read-only check D14 records (011 decision 136A, 2026-10-19).
    ("IsOpenedReadOnly: true", "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
    ("IsOpenedReadOnly: not called", "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
    # The open's load errors and warnings, the end of D14's OpenDoc6 line (its second review).
    ("; answered error ", "extractor/SwReview.Extractor.Tests/DrawingProbeTests.cs"),
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
    ("Not reached: ", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("not reached", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("size-for-size contacts", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("Sending resumes the review once.", "reviewer/src/swreview/report/review_words_v1.yaml"),
    (READ_ONLY_SENTENCE, "reviewer/src/swreview/report/review_words_v1.yaml"),
    # The page's own words.
    ("Checked by code. Not sent to the model.",
     "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("Send to the model when the checks finish",
     "extractor/SwReview.AddIn/Review/ReviewPage/index.html"),
    ("Send to model", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("The review has finished.", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("Waiting for your answers.", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("This review is of ", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("Send answers", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("This review can no longer be restored.",
     "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("The review stopped", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    ("uncached + ", "extractor/SwReview.AddIn/Review/ReviewPage/render.js"),
    # Step 5.3, since 004 T157 seats the add-in and T172 keeps Start switched off; and, since
    # 004 T176 ends a plan's session as it is made, the first words of T167's failure status,
    # which the step calls a fail.
    ("Planned. Press Start to apply the plan to the copy.",
     "extractor/SwReview.AddIn/Remodel/RemodelHost.cs"),
    ("Start is not switched on in this build yet, so this plan cannot be applied to the copy.",
     "extractor/SwReview.AddIn/Remodel/RemodelHost.cs"),
    ("Not everything the plan changed in SOLIDWORKS could be put back",
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
    ("Remodel a copy", "extractor/SwReview.AddIn/Remodel/RemodelPage/index.html"),
    ("Discard copy", "extractor/SwReview.AddIn/Remodel/RemodelPage/index.html"),
    # Step 5.3's item B presses it for 011 T171 (decision 144A, 2026-10-19).
    ("Open copy", "extractor/SwReview.AddIn/Remodel/RemodelPage/index.html"),
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
    # The check tabs' Start here rows, the report's Findings by type and the timing, which
    # steps 4.1, 4.5, 5.1 and 5.2 read (007; 013 T057).
    ("Start here", "extractor/SwReview.AddIn/web/shared/attention.js"),
    ("Findings by type", "reviewer/src/swreview/report/markdown.py"),
    ("Checked, no issue", "reviewer/src/swreview/report/review_words_v1.yaml"),
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
    # Feature 013's words, which steps 2.6, 4.6 to 4.8 and 5.2 read (013 T138, T094, T141 to T144).
    ("sha256:", "reviewer/src/swreview/cli.py"),
    ("in SOLIDWORKS, then press Review again with",
     "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("not graded for modelling practice or hygiene (bought)",
     "reviewer/src/swreview/checks/part_roles.py"),
    ("Checked by code", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("AI guidance", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("results read for this answer.", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("No evidence was read for this answer: this is general guidance.",
     "reviewer/src/swreview/report/review_words_v1.yaml"),
    (" No drawing was read in this review.", "reviewer/src/swreview/report/review_words_v1.yaml"),
    ("no revision table was found", "reviewer/src/swreview/checks/standards/drawing.py"),
    # The retest of 2026-09-28's U25 to U27, which steps 4.9 and 5.3 read first (011 T110;
    # 004 T185 and T186).
    ("Review reads open drawings whose views show the model.",
     "extractor/SwReview.AddIn/Review/ReviewHost.cs"),
    (" is a drawing of ", "extractor/SwReview.AddIn/Review/ReviewHost.cs"),
    ("Press Review to review", "extractor/SwReview.AddIn/Review/ReviewPage/app.js"),
    ("The models a drawing shows could not be read: ", "extractor/SwReview.AddIn/SwReviewAddIn.cs"),
    ("Don't prompt to save read-only referenced documents",
     "extractor/SwReview.AddIn/Remodel/RemodelHost.cs"),
    ("open_record.written", "reviewer/src/swreview/chat/remodel.py"),
    ("baseline_geometry.begin", "reviewer/src/swreview/chat/remodel.py"),
    ("stage=", "extractor/SwReview.AddIn/ToolService/ToolServiceHost.cs"),
    ("get_Density", "extractor/SwReview.Extractor/Rms/RemodelGeometry.cs"),
    # S1 (decisions 167A and 169A; 004 T365): the backend's number, the close in process, 004
    # T140's test and PROBE-15's line.
    ("backend healthy on ", "extractor/SwReview.AddIn/Review/BackendProcess.cs"),
    ("remodel close in process thread=", "extractor/SwReview.AddIn/ToolService/ToolServiceHost.cs"),
    ("nothing closed: this bridge holds no session of that run",
     "extractor/SwReview.AddIn/ToolService/ToolServiceHost.cs"),
    ("InstalledAssemblyMatchesManifest",
     "extractor/SwReview.Extractor.Tests/RemodelInteropManifestTests.cs"),
    ("root_component: ", "extractor/SwReview.Extractor.Console/Program.cs"),
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
    link = "docs/test-plan-2026-09-27/workstation-test-plan.md"
    runbook = (REPO / "docs" / "workstation-runbook.md").read_text(encoding="utf-8")
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    handover = (REPO / "docs" / "test-plan-2026-09-27" / "workstation-handover.md").read_text(
        encoding="utf-8"
    )

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
    copy = r'Copy-Item "$R\docs\test-plan-2026-09-27\workstation-results.md" $findings'
    step_1_4 = step(plan, "1.4")
    step_1 = plan[plan.index("## Step 1.") : plan.index("### 1.1 ")]

    assert '$findings = "$H\\pane-findings-$(Split-Path $H -Leaf).md"' in plan
    assert plan.count(copy) == 1
    assert copy in step_1_4
    sheet_check = r"Test-Path docs\test-plan-2026-09-27\workstation-results.md"
    assert step_1_4.index(sheet_check) < step_1_4.index(copy)
    assert r"Test-Path docs\test-plan-2026-09-27\workstation-test-plan.md" not in plan
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
    that presses Review says the owner's answer itself, and step 5.5 opens A resolved, as step
    4.1 does. *Changed 2026-10-31 on purpose (decision 175A; 004 T363):* step 5.5 kept 009
    T082's "after" half only, so it opens A once, on the current build, where it opened it on
    each of two builds."""
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
    assert flat["5.5"].count("open A resolved and part J") == 1
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
    # The results sheet as that commit held it, before the 2026-09-27 move into the dated folder.
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
    line, before it, so the script that runs is the one that arrived. *Changed 2026-10-31 on
    purpose (decision 175A; 004 T363):* step 5.5's four runs, to the older build and back, left
    with its "before" half, so three runs remain: step 1.3's two spellings and the way back to the
    build the seat had."""
    runs = re.findall(r"\.\\extractor\\tools\\update-workstation\.ps1[^`\n]*", plan)

    assert len(runs) >= 3
    assert [run for run in runs if " -NoPull" not in run] == []


def test_no_document_of_the_sitting_asks_for_a_gemini_key(plan: str, results: str) -> None:
    """Decision 94A defers Gemini's own behaviour and 004 T361 closed 008 T106, the live Gemini
    test, under it (decision 173A), so no step runs that test and no document of the sitting asks
    for a Gemini key or names `GEMINI_API_KEY` (004 T363)."""
    documents = {
        "plan": plan,
        "results": results,
        "handover": HANDOVER.read_text(encoding="utf-8"),
        "runbook": RUNBOOK.read_text(encoding="utf-8"),
    }
    tasks = (REPO / "specs" / "008-checks-first-review" / "tasks.md").read_text(encoding="utf-8")
    [t106] = [line for line in tasks.splitlines() if re.match(r"- \[[ x]\] T106 ", line)]

    for name, text in documents.items():
        for words in ("GEMINI_API_KEY", "test_gemini_live_function_response", "Gemini key"):
            assert words not in text, (name, words)
    assert ("008", "T106") not in tagged_tasks(plan)
    assert ("008", "T106") not in rowed_tasks(results)
    assert t106.startswith("- [x] T106 ") and "94A" in t106


def test_step_5_5_is_009_t082s_after_half_on_the_current_build(plan: str) -> None:
    """Decision 175A drops 009 T082's "before" half, a one-hour swap to an older build to show a
    bug already fixed, and keeps its "after" half: on the build of step 1.4, Show in SOLIDWORKS
    on one of A's findings selects A's own entity (004 T363). Nothing checks out another commit,
    builds without the gates, or copies the settings aside for a way back."""
    show = re.sub(r"\s+", " ", step(plan, "5.5"))
    handover = HANDOVER.read_text(encoding="utf-8")
    tasks = (REPO / "specs" / "009-engineer-workspace" / "tasks.md").read_text(encoding="utf-8")
    [t082] = [line for line in tasks.splitlines() if line.startswith("- [ ] T082 ")]

    assert "Show in SOLIDWORKS selects A's own entity" in show
    for words in ("git checkout", "-SkipTests", "settings.json.before-5.5", "update-workstation"):
        assert words not in show, words
    for text in (plan, handover):
        assert "69fbb4a" not in text
        assert "settings.json.before-5.5" not in text
    assert "175A" in t082


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


HANDOVER = REPO / "docs" / "test-plan-2026-09-27" / "workstation-handover.md"
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


def test_a_seat_task_is_tagged_w_or_says_workstation_and_its_id_is_read_whole() -> None:
    """Decision 166A (004 T360): a seat task is open and tagged `[W]` among its leading tags, as
    005 tags `[P] [W]`, or says `Workstation` first after them, as 003 and 004 do; a task tagged
    only `[K]`, or saying so later in its text, is not one. An id ending in a letter is that task,
    not the one without it: `004 T303a` is not `004 T303`."""
    tasks = "\n".join([
        "- [ ] T001 [W] On the seat.",
        "- [ ] T002 [P] [W] [L9] Probe P3.",
        "- [ ] T003 [US6] Workstation: probes 14 and 15.",
        "- [ ] T004 Workstation, read only: the record.",
        "- [ ] T085a [W] The harness.",
        "- [x] T005 [W] Done already.",
        "- [ ] T006 [P] [K] A live probe.",
        "- [ ] T007 Run it on the workstation later.",
        "- [ ] T008 [WK] Not the tag.",
    ])

    assert seat_tasks_in(tasks) == ["T001", "T002", "T003", "T004", "T085a"]
    assert qualified_tasks("004 T303a and 004 T303b, then 005 T085a; 004 T303") == {
        ("004", "T303a"), ("004", "T303b"), ("005", "T085a"), ("004", "T303"),
    }
    assert qualified_tasks("004 T303ab") == set()


def test_every_feature_with_an_open_seat_task_is_one_the_plan_is_held_to() -> None:
    """Decision 166A: the pins read every feature package with an open seat task, so a seat task
    cannot drift out of the plan as 004 T303 did while 004 was not among the packages read.
    *Corrected 2026-10-31 on review (004 T370):* a feature whose last seat task is ticked, as 014
    and 015 will be after S3, leaves `PACKAGES`, whose every package must still have one (`assert
    tasks, package` in the plan's and the handover's pins), so only the features that have one
    are held here. 002 T044, quickstart Scenario 1 in the pane on the native bracket assembly,
    needs the seat though its provider is the fake, so it is read as one too."""
    tasks = sorted((REPO / "specs").glob("*/tasks.md"))
    features = [path.parent.name for path in tasks]
    seated = [path.parent.name for path in tasks if seat_tasks_in(path.read_text(encoding="utf-8"))]

    assert len(features) >= 15
    assert [feature for feature in seated if feature not in PACKAGES] == []
    assert [package for package in PACKAGES if package not in features] == []
    assert "002-task-pane-assistant" in seated
    assert "T044" in open_seat_tasks("002-task-pane-assistant")


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
    if (
        source == "reviewer/src/swreview/report/review_words_v1.yaml"
        and sentence == READ_ONLY_SENTENCE
    ):
        assert load_words().read_only == sentence
    else:
        assert sentence in (REPO / source).read_text(encoding="utf-8")


def test_every_one_liner_compiles_and_holds_no_double_quote(plan: str) -> None:
    found = one_liners(plan)

    # Five since feature 014 (014 T221, 2026-10-17): `Show-SmokeFacts` joins
    # `Show-ReviewFacts`, `Show-DumpFacts`, `Show-Documents` and `Show-DrawingTables`,
    # edited deliberately.
    assert len(found) == plan.count(ONE_LINER_START) == 5
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


def _smoke_run(tmp_path: Path) -> Path:
    """A fictional passing smoke run, copied from the same replay as Show-ReviewFacts."""
    from swreview.checks.standards.registry import RULES
    from swreview.checks.standards.report import PROFILE_LIMIT

    run = tmp_path / "run"
    shutil.copytree(REVIEW_RUN, run)
    events = [
        json.loads(line)
        for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    usage = [event["body"] for event in events if event["type"] == "usage"]
    for index, body in enumerate(usage):
        body["served_model"] = ("fictional-zeta", "fictional-alpha")[index % 2]
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    session_file = run / "session.json"
    session = json.loads(session_file.read_text(encoding="utf-8"))
    session["origin_marks"] = 1
    for finding in session["findings"]:
        if finding["check"] in RULES:
            finding["coverage_limits"] = [
                "unrelated folder /fictional",
                PROFILE_LIMIT.format(name="fictional profile.yaml", sha256="a" * 64),
            ]
    session_file.write_text(json.dumps(session), encoding="utf-8")
    saved = load_session(session_file)
    write_attention_record(run, rank(saved), saved.session_id)
    return run


def test_the_smoke_facts_run_against_a_committed_review(plan: str) -> None:
    """The older replay honestly reports its missing served models and attention record."""
    before = {path.name: path.read_bytes() for path in REVIEW_RUN.iterdir() if path.is_file()}

    lines = run_one_liner(one_liner_of(plan, "Show-SmokeFacts"), REVIEW_RUN)

    assert lines == [
        "usage events 41 | with served_model 0 | served models []",
        "bodies with a retries field 0",
        "origin_marks 1",
        "standards findings 5 | with a profile stamp 5 | stamps naming a folder 0",
        "attention.json: missing | unreadable | rows - | FileNotFoundError",
        "prompts.json: absent",
    ]
    assert {
        path.name: path.read_bytes() for path in REVIEW_RUN.iterdir() if path.is_file()
    } == before


def test_the_smoke_facts_read_a_passing_run_without_writing_it(plan: str, tmp_path: Path) -> None:
    """Profile files may contain spaces; served ids are sorted and distinct."""
    run = _smoke_run(tmp_path)
    before = {path.name: path.read_bytes() for path in run.iterdir() if path.is_file()}

    lines = run_one_liner(one_liner_of(plan, "Show-SmokeFacts"), run)

    assert lines == [
        "usage events 41 | with served_model 41 | served models "
        "['fictional-alpha', 'fictional-zeta']",
        "bodies with a retries field 0",
        "origin_marks 1",
        "standards findings 5 | with a profile stamp 5 | stamps naming a folder 0",
        "attention.json: LF | reads as this session's record | rows 15",
        "prompts.json: absent",
    ]
    assert {path.name: path.read_bytes() for path in run.iterdir() if path.is_file()} == before


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        (
            "missing served model",
            "usage events 41 | with served_model 40 | served models "
            "['fictional-alpha', 'fictional-zeta']",
        ),
        ("retries on a non-usage body", "bodies with a retries field 1"),
        ("missing origin marks", "origin_marks absent"),
        (
            "missing profile stamp",
            "standards findings 5 | with a profile stamp 4 | stamps naming a folder 0",
        ),
        (
            "empty profile file",
            "standards findings 5 | with a profile stamp 4 | stamps naming a folder 0",
        ),
        (
            "invalid profile stamp",
            "standards findings 5 | with a profile stamp 4 | stamps naming a folder 0",
        ),
        (
            "profile stamp with slash",
            "standards findings 5 | with a profile stamp 5 | stamps naming a folder 1",
        ),
        (
            "profile stamp with backslash",
            "standards findings 5 | with a profile stamp 5 | stamps naming a folder 1",
        ),
        ("prompts present", "prompts.json: present"),
    ],
)
def test_the_smoke_facts_expose_each_broken_check(
    plan: str, tmp_path: Path, broken: str, expected: str
) -> None:
    from swreview.checks.standards.registry import RULES
    from swreview.checks.standards.report import PROFILE_LIMIT

    run = _smoke_run(tmp_path)
    if broken in {"missing served model", "retries on a non-usage body"}:
        event_file = run / "events.jsonl"
        events = [
            json.loads(line)
            for line in event_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if broken == "missing served model":
            next(event["body"] for event in events if event["type"] == "usage").pop("served_model")
        else:
            next(event["body"] for event in events if event["type"] != "usage")["retries"] = 0
        event_file.write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
    elif (
        broken == "missing origin marks"
        or "profile stamp" in broken
        or broken == "empty profile file"
    ):
        session_file = run / "session.json"
        session = json.loads(session_file.read_text(encoding="utf-8"))
        if broken == "missing origin marks":
            session.pop("origin_marks")
        else:
            finding = next(finding for finding in session["findings"] if finding["check"] in RULES)
            name = "fictional profile.yaml"
            if broken == "missing profile stamp":
                finding["coverage_limits"] = ["unrelated folder /fictional"]
            elif broken == "empty profile file":
                finding["coverage_limits"] = [PROFILE_LIMIT.format(name="", sha256="a" * 64)]
            elif broken == "invalid profile stamp":
                finding["coverage_limits"] = [
                    PROFILE_LIMIT.format(name=name, sha256="not-a-digest")
                ]
            else:
                separator = "/" if broken.endswith("with slash") else chr(92)
                finding["coverage_limits"] = [
                    PROFILE_LIMIT.format(name="fictional" + separator + name, sha256="a" * 64)
                ]
        session_file.write_text(json.dumps(session), encoding="utf-8")
    else:
        (run / "prompts.json").write_bytes(b"{}\n")
    before = {path.name: path.read_bytes() for path in run.iterdir() if path.is_file()}

    lines = run_one_liner(one_liner_of(plan, "Show-SmokeFacts"), run)

    assert expected in lines
    assert {path.name: path.read_bytes() for path in run.iterdir() if path.is_file()} == before


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("reads", "attention.json: LF | reads as this session's record | rows 15"),
        ("stale", "attention.json: LF | stale | rows - | StaleAttentionRecord"),
        ("unreadable", "attention.json: LF | unreadable | rows - | ValueError"),
        ("CRLF", "attention.json: CRLF lines 2 | reads as this session's record | rows 15"),
        ("missing", "attention.json: missing | unreadable | rows - | FileNotFoundError"),
    ],
)
def test_the_smoke_attention_line_reads_the_runs_record(
    plan: str, tmp_path: Path, state: str, expected: str
) -> None:
    run = _smoke_run(tmp_path)
    attention = run / "attention.json"
    if state == "stale":
        record = json.loads(attention.read_text(encoding="utf-8"))
        record["session_id"] = "00000000-0000-4000-8000-000000000001"
        attention.write_bytes((json.dumps(record) + "\n").encode("utf-8"))
    elif state == "unreadable":
        attention.write_bytes(b"{}\n")
    elif state == "CRLF":
        record = json.loads(attention.read_text(encoding="utf-8"))
        attention.write_bytes((json.dumps(record) + "\r\n\r\n").encode("utf-8"))
    elif state == "missing":
        attention.unlink()
    before = {path.name: path.read_bytes() for path in run.iterdir() if path.is_file()}

    lines = run_one_liner(one_liner_of(plan, "Show-SmokeFacts"), run)

    assert line_starting(lines, "attention.json:") == expected
    assert {path.name: path.read_bytes() for path in run.iterdir() if path.is_file()} == before


@pytest.mark.parametrize("failure", [OSError, ValueError, StaleAttentionRecord, RuntimeError])
def test_the_smoke_attention_failures_print_only_the_class_and_catch_only_reader_errors(
    plan: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    failure: type[Exception],
) -> None:
    from swreview.report import attention_record

    run = _smoke_run(tmp_path)

    def fail_reader(directory: Path) -> None:
        assert directory == run
        raise failure("/fictional/private/record-path must never be printed")

    monkeypatch.setattr(attention_record, "read_attention_record", fail_reader)
    monkeypatch.setattr(sys, "argv", ["smoke", str(run)])
    code = one_liner_of(plan, "Show-SmokeFacts")
    if failure is RuntimeError:
        with pytest.raises(RuntimeError, match="must never be printed"):
            exec(code, {})
    else:
        exec(code, {})
    lines = capsys.readouterr().out.splitlines()

    assert not any("/fictional/private/record-path" in line for line in lines)
    if failure is not RuntimeError:
        state = "stale" if failure is StaleAttentionRecord else "unreadable"
        assert line_starting(lines, "attention.json:") == (
            f"attention.json: LF | {state} | rows - | {failure.__name__}"
        )


def test_the_smoke_instructions_check_the_record_and_the_review_findings_by_type(
    plan: str, results: str
) -> None:
    smoke = step(plan, "4.11")
    assert "`attention.json: LF | reads as this session's record`" in smoke
    assert "FR-020" in smoke
    assert "since feature 013" in smoke.lower()
    assert "findings by type" in smoke
    assert "Get-Content" not in smoke
    assert "on-screen summary, findings, questions and ranking checks" not in plan
    assert "compare the file's ranking with the Review page" not in plan
    assert "attention.json's line endings and that it reads as the run's record" in results
    assert "the Start here panel" not in results


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


def test_the_drawing_tables_line_counts_each_sheets_tables_by_id(plan: str) -> None:
    """013 T144 (step 5.2) reads A-plate's drawing's tables from its `-standards` folder:
    `Show-DrawingTables` prints one line per native sheet - the drawing's id, the sheet's number,
    and its revision tables, other tables and bills of materials, counts only - and no name."""
    folder = FIXTURES / "drawings" / "drawing-root"
    package = load_package(folder).package

    lines = run_one_liner(one_liner_of(plan, "Show-DrawingTables"), folder)

    expected = [
        f"{record.document_id} sheet {sheet.index + 1} | revision tables "
        f"{len(sheet.revision_tables)} | other tables {len(sheet.tables)} | bills of materials "
        f"{sum(1 for table in sheet.tables if table.bom_rows)}"
        for record in package.drawing_records
        for sheet in record.sheets
    ]
    assert lines == expected
    assert any("revision tables 1" in line for line in lines)
    assert any("bills of materials 1" in line for line in lines)
    for record in package.drawing_records:
        for sheet in record.sheets:
            assert all(sheet.name not in line for line in lines)


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
    after everything but the handoff, with no document open, and 5.5 no longer calls itself
    last. *Changed 2026-10-31 on purpose (decision 175A; 004 T363):* step 5.5 no longer builds
    an older commit, so step 5.6 waits on no return to the current build and is never `blocked
    by 5.5`."""
    numbers = STEP_HEADING.findall(plan)
    headings = re.findall(r"^### (5\.[56]) (.*)$", plan, re.MULTILINE)
    probes = re.sub(r"\s+", " ", step(plan, "5.6"))

    assert numbers[numbers.index("6.0") - 1] == "5.6"
    assert dict(headings)["5.6"].startswith("The re-modeler probes, with no document open: last ")
    assert "last" not in dict(headings)["5.5"]
    assert "blocked by 5.5" not in plan
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


def test_the_three_runs_cover_the_catalog_once_with_starts_five_last_and_probe_1_last_of_all(
    plan: str,
) -> None:
    """Each run writes `capabilities/remodel-<version>.yaml` in its own `--out` folder and a
    second run into the same folder would overwrite it, so the three folders differ; together the
    runs are the catalog, once each, and each is read back from its own folder.

    *Changed 2026-10-31 on purpose (004 T377, review finding RR1; research R27.4):* this pinned
    PROBE-1 alone in the third run, which split the five probes Start waits on over three answers
    files, while `swreview remodel ledger` judges Start from one file and the switch's pin wants
    one committed file judged ready, so no run of the plan could give it. Now the third run holds
    exactly the reader's own `START_PROBES`: those whose bodies never reorder first, in the
    catalog's order, then PROBE-3, then PROBE-1, which asks for a box, last of all - the answers
    file is rewritten as each probe finishes (R27.2), so a hang keeps every earlier row. The
    first run holds every other probe whose body never reorders (read from the executors, so a
    body that starts reordering moves this pin) and the second every other reorder, each in the
    catalog's order."""
    probes = step(plan, "5.6")
    runs = [(ids.split(","), folder) for ids, folder in REMODEL_RUN.findall(probes)]
    catalog = catalog_probes()
    reorders = reordering_probes()
    start = set(START_PROBES)
    ledger = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")

    assert plan.count("swreview-extract probe remodel --") == len(runs) == 3
    assert len({folder for _, folder in runs}) == 3
    assert sorted(probe for ids, _ in runs for probe in ids) == sorted(catalog)
    for _, folder in runs:
        assert f'Show-RemodelLedger "$H\\probes\\{folder}"' in probes, folder
    for ids, folder in runs[:2]:
        assert ids == [probe for probe in catalog if probe in ids], folder
    assert set(runs[0][0]) == set(catalog) - reorders - start
    assert set(runs[1][0]) == reorders - start
    assert runs[2][0] == (
        [probe for probe in catalog if probe in start - reorders]
        + [probe for probe in catalog if probe in (start & reorders) - {"PROBE-1"}]
        + ["PROBE-1"]
    )
    assert "PROBE-1" in reorders and "PROBE-1" in start
    assert "so that one answers file holds all five" in re.sub(r"\s+", " ", probes)
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
    """PROBE-1 runs its flag-set try first and its flag-clear try second, and decides "blocked"
    from a watchdog that gives each try `DefaultTimeout`, counted from the moment that try begins
    (013 T137, 004 T171); a box answered before both tries have timed out lets a call return
    inside its deadline and reads as no box, and a box the first try raised holds the second. So
    the wait step 5.6 asks for is longer than both tries, the plan states the watchdog's own
    figure and when it starts, and it names the tries in the order the probe runs them."""
    watchdog = (RMS / "RemodelProbeWatchdog.cs").read_text(encoding="utf-8")
    [timeout] = re.findall(r"DefaultTimeout = TimeSpan\.FromSeconds\((\d+)\)", watchdog)
    probe_1 = probe_bodies()["PROBE-1"]
    probes = re.sub(r"\s+", " ", step(plan, "5.6"))
    [wait] = re.findall(r"wait until \*\*(\d+) seconds\*\* have passed since it appeared", probes)

    assert probe_1.index("Attempt(commandInProgress: true)") < probe_1.index(
        "Attempt(commandInProgress: false)"
    )
    assert (
        "flag set first, which should raise no box, then the same reorder with the flag clear, "
        'which should raise a "Cannot reorder" box'
    ) in probes
    assert (
        f"times each of its two tries for {timeout} seconds, counted from the moment that try "
        "begins"
    ) in probes
    assert f"whose own {timeout} seconds start only once it has begun" in probes
    assert int(wait) > 2 * int(timeout)
    assert "rule 6's one exception" in probes
    assert "step 5.6" in re.sub(r"\s+", " ", plan[plan.index("6. **Do not click") :][:400])


def test_the_lines_step_5_6_reads_are_the_consoles(plan: str) -> None:
    """The run refuses while a document is open, starts its ledger before the part is built,
    rewrites it as each probe finishes and puts each log line on disk as it is written (004 T330,
    T332 and T342, decision 166A: a run stopped with Ctrl+C keeps its log and every finished
    probe's row, and an earlier run's ledger never stands for it), logs a thrown probe's exception
    to the log alone (T342: the ledger keeps its type only, 171A), and ends with the count line
    and one BLOCKING line per blocking probe not verified; and it turns off the three options step
    5.6 notes before the runs and checks after. *Changed on purpose by 004 T342 (review findings
    F2 and F3)*: the recorder is made before the toggles, no longer inside `RunAll`'s call."""
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
    assert (
        run.index("RemodelProbe.AssertPartSavePath(")
        < run.index("= RemodelProbeLedger.Recorder(")
        < run.index("RemodelSystemToggles.Within(")
        < run.index("host.BuildPart(")
        < run.index("RemodelProbeRunner.RunAll(")
        < run.index("finished: recorder,")
        < run.index("threw: (probe, error) => log.WriteError(")
        < run.index("host.ClosePart(")
    )
    assert "RemodelProbeLedger.Write(" not in run
    write = log[log.index("public void Write(") : log.index("public void WriteError(")]
    assert "File.AppendAllText(" not in log and "AutoFlush = true" in log
    assert "FileShare.ReadWrite" in log and "ToFile(line)" in write
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


def test_every_run_reads_start_not_ready_in_s1_and_the_line_is_recorded_not_judged(
    plan: str, tmp_path: Path
) -> None:
    """`swreview remodel ledger` ends with one line per switch, `RemodelStart.SeatValidated:` and
    `ready` or `not ready - ` with every reason; in S1 it reads `not ready` after every run, by
    design: only the third run holds Start's five probes, and IDENTITY is calibrated only after
    S1, by 004 T138 (decision 170A). Step 5.6's item 4 and the handover's step 21 say so and have
    the line recorded, not judged (004 T377, review finding RR1). Here the reader reads the third
    run's best case, all five verified with a reason: its one reason is IDENTITY's. Once T138
    calibrates IDENTITY this fails, and the plan's sentence is changed with it."""
    ledger = tmp_path / "remodel-32.5.0.yaml"
    ledger.write_text(
        rendered_ledger(
            [(probe, True, "verified", {"reason": "answered as asked"}) for probe in START_PROBES]
        ),
        encoding="utf-8-sig",
    )
    payload = summary(load_ledger(ledger), ledger.name)
    probes = re.sub(r"\s+", " ", step(plan, "5.6"))
    handover = re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))
    probe_step = handover[handover.index("21. **004 T033 to T039") :]
    probe_step = probe_step[: probe_step.index("22. **015 T119")]

    assert [switch["reasons"] for switch in payload["switches"]] == [
        ["the IDENTITY tolerance profile is not calibrated: T138 freezes it against PROBE-8's "
         "numbers (decision 170A)"]
    ]
    assert summary_lines(payload)[-1].startswith("RemodelStart.SeatValidated: not ready - ")
    for text in (probes, probe_step):
        assert "`RemodelStart.SeatValidated: not ready - `" in text
        assert "recorded, not judged" in text
    assert "`only IDENTITY`" in probes


def test_a_hung_run_keeps_its_finished_probes_and_probe_12s_error_is_read_on_the_console(
    plan: str, results: str
) -> None:
    """Since 004 T330 to T343 the probe log is written line by line, and the answers file is
    started before anything is built and rewritten as each probe finishes, so after a hang or
    Ctrl+C both hold every finished probe: item 6 keeps their verdicts and writes `blocked: hung
    in run <n>` only for those the reader prints `not finished` (004 T377, review finding RR4).
    And a thrown probe's row keeps only its type and code (decision 171A), so decision 148A's
    question, whether PROBE-12's error names `OpenDoc7`, is read from the console: `probe remodel`
    writes its line, then the exception's message on the line after it (R27.9.3), never from the
    reader's `threw <type> 0x<code>` (review finding RR5)."""
    console = REPO / "extractor" / "SwReview.Extractor.Console"
    program = (console / "Program.cs").read_text(encoding="utf-8")
    log = (console / "ExtractLog.cs").read_text(encoding="utf-8")
    reader = (REVIEWER / "src" / "swreview" / "remodel" / "ledger.py").read_text(encoding="utf-8")
    probes = re.sub(r"\s+", " ", step(plan, "5.6"))
    handover = re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))
    probe_step = handover[handover.index("21. **004 T033 to T039") :]
    probe_step = probe_step[: probe_step.index("22. **015 T119")]
    write_error = log[log.index("public void WriteError(") : log.index("public void Dispose(")]
    threw = "`PROBE-12 threw; its message is kept in this log, never the ledger:`"
    [row] = [line for line in results.splitlines() if line.startswith("| 5.6 | 011 T171: ")]

    gone = "writes its answers file and its log only when it ends"
    assert gone not in probes and gone not in handover
    assert 'f"{probe}: not finished - the run stopped before this probe ended"' in reader
    assert "`blocked: hung in run <n>` only for the probes it prints `not finished`" in probes
    assert "`not finished`" in probe_step

    assert '$"{probe} threw; its message is kept in this log, never the ledger:", error));' in (
        program
    )
    assert write_error.index("Write(message);") < write_error.index(
        "System.Console.Error.WriteLine(error.Message);"
    )
    assert threw in probes and threw in handover and "PROBE-12 threw;" in row
    assert "whether the line after it contains `OpenDoc7`" in probes
    assert "whether it names `OpenDoc7`" not in probes


def test_the_fixture_ledger_has_the_shape_render_writes() -> None:
    """`Show-RemodelLedger` matches lines by their indentation and key, so the fixture's
    prefixes are the ones `RemodelProbeLedger.Render` appends, and the two raw_result keys it
    prints are the runner's error key and the reason key every probe body files. *Changed on
    purpose by 004 T332 (decision 166A)*: a top-level `requested:` list comes before `probes:`,
    its items indented two spaces, so no `Show-RemodelLedger` pattern reads one."""
    ledger = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")

    for prefix in ('text.Append("  - probe_id: ")', 'text.Append("    blocking: ")',
                   'text.Append("    verdict: ")',
                   'text.Append("      ").Append(Quote(entry.Key)).Append(": ")',
                   'AppendStringList(text, "requested", requested ?? ', '"  - "',
                   "Encoding.UTF8"):
        assert prefix in ledger, prefix
    assert ledger.index('AppendStringList(text, "requested", ') < ledger.index(
        'text.Append("probes:\\n")'
    )
    assert 'public const string ErrorKey = "error";' in ledger
    assert [probe for probe, body in probe_bodies().items() if '["reason"]' not in body] == []


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_show_remodel_ledger_hands_each_answers_file_to_swreview_remodel_ledger(
    plan: str, tmp_path: Path
) -> None:
    """*Changed 2026-10-31 on purpose (decision 166A; 004 T365):* `Show-RemodelLedger` no longer
    reads the answers file line by line itself; it hands each file to `swreview remodel ledger`,
    the reader another lane builds, from `$R\reviewer` as every `uv run` of the plan runs, and
    still says when a run wrote none. That command is not this test's: `uv` is stood in for by a
    function that prints what it was asked, so nothing of that lane's runs here."""
    run = tmp_path / "remodel-no-reorder"
    (run / "capabilities").mkdir(parents=True)
    ledger = run / "capabilities" / "remodel-32.5.0.48.yaml"
    ledger.write_text(
        rendered_ledger(
            [
                ("PROBE-2", True, "verified", {"reason": "get_Value returned 120."}),
                ("PROBE-13", False, "unresolved", {"error": "the call threw"}),
            ]
        ),
        encoding="utf-8-sig",
    )
    empty = tmp_path / "remodel-probe-1"
    empty.mkdir()
    reviewer = tmp_path / "checkout" / "reviewer"
    reviewer.mkdir(parents=True)
    function = plan_function(plan, "Show-RemodelLedger")
    quoted, quoted_empty, checkout = (
        str(folder).replace("'", "''") for folder in (run, empty, reviewer.parent)
    )
    stub = "function uv { \"uv $($args -join ' ') | from $((Get-Location).Path)\" }"

    lines = run_powershell(
        f"$R = '{checkout}'\n{stub}\n{function}\nShow-RemodelLedger '{quoted}'\n"
        f"Show-RemodelLedger '{quoted_empty}\\'\n",
        tmp_path,
    )

    assert lines == [
        f"uv run swreview remodel ledger {ledger} | from {reviewer}",
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
    packages replace 004 T148's provisional counts; and the stage-1 runs name 004 T152 to T160, the
    production seat adapter. *Amended 2026-09-27:* the adapter is in this build (step 5.3 plans
    through it), so the stage-1 runs' row names it as built and says they wait on the Start switch
    (004 T172)."""
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
    [stage_1] = [
        line for line in plan.splitlines() if line.startswith("| 004 | 004 T135 to T141 |")
    ]
    assert ("004", "T172") in qualified_tasks(stage_1)
    assert "not built" not in stage_1 and "are in this build" in stage_1


SWITCH_PROBES = "PROBE-1, 2, 3, 4 and 12"
"""The probes 004 T172's switch waits on, as `RemodelStart.cs` and T172 name them."""


def probe_tasks(plan: str) -> dict[str, tuple[str, str]]:
    """Each probe's task, from step 5.6's table (`| PROBE-3 | 004 T034 | ...`)."""
    return {
        probe: (package, task)
        for probe, package, task in re.findall(
            r"^\s*\| (PROBE-\d+) \| (\d{3}) (T\d{3}) \|", step(plan, "5.6"), re.MULTILINE
        )
    }


def test_step_5_3_plans_on_a_copy_and_start_is_refused_by_the_switch(plan: str) -> None:
    """004 T157 seats the Remodel tab and T172 keeps Start switched off, so step 5.3's pass line is
    a plan made on a copy - one `-RMS` copy in the newest remodel folder, part J only read - and a
    Start refused by the switch. Since 004 T176 a plan made while Start is off lets go of its copy
    at once, so the three settings are checked after Plan and before Start, the Window menu shows
    no copy, and Discard leaves none; the step records how long Plan took, for 004 T182. The copy
    check's two suffixes are the product's."""
    task = re.sub(r"\s+", " ", step(plan, "5.3"))
    copy_suffix = re.search(
        r'CopySuffix = "([^"]+)"', (RMS / "RemodelCopy.cs").read_text(encoding="utf-8")
    ).group(1)
    run_suffix = re.search(
        r'RemodelSuffix = "([^"]+)"',
        (REPO / "extractor" / "SwReview.AddIn" / "Review" / "RunFolders.cs").read_text(
            encoding="utf-8"
        ),
    ).group(1)

    for phrase in (
        "**Remodel a copy plans on a copy**",
        "**Start is switched off**",
        "`copies in it: 1`",
        "`copies in it: 0`",
        "no document whose name ends in `-RMS`",
        "Open the three settings again, before Start",
        "how long the plan took, in seconds",
        "the hash, size and time are unchanged",
    ):
        assert phrase in task, phrase
    assert f"'*{run_suffix}'" in task and f"'*{copy_suffix}.SLDPRT'" in task
    assert task.index("before Start") < task.index("Press **Start**")
    assert task.index("Press **Start**") < task.index("press **Discard copy**")
    assert {("004", "T172"), ("004", "T176"), ("004", "T182")} <= qualified_tasks(task)


def test_the_start_switch_waits_on_the_blocking_probes_then_a_real_plan(plan: str) -> None:
    """What the next sitting must prove before the development machine sets
    `RemodelStart.SeatValidated`, in this order: step 5.6's blocking probes, the ones 004 T172 and
    `RemodelStart.cs` name, each `verified` - their tasks read off step 5.6's own table - then step
    5.3's Plan on one real part's copy with that part's hash unchanged. The development machine's
    table and the handover say the same. *Changed 2026-10-31 on purpose (004 T377, review finding
    RR3):* this asked for 004 T180 among what is decided before the switch; decision 168A closed
    T180 (004 research R25.9, R26.5), so each of the three now says it is done, and none says it
    is still to be decided."""
    waits = re.sub(r"\s+", " ", step(plan, "5.3"))
    waits = waits[waits.index("**What the Start switch waits on.**") :]
    tasks = (FEATURE_004 / "tasks.md").read_text(encoding="utf-8")
    start = (RMS / "RemodelStart.cs").read_text(encoding="utf-8")
    probes = probe_tasks(plan)
    blocking = {probes[f"PROBE-{number}"] for number in (1, 2, 3, 4, 12)}
    [row] = [
        line for line in plan[plan.index("## Not in this sitting") :].splitlines()
        if "`RemodelStart.SeatValidated`" in line
    ]
    handover = re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))

    assert SWITCH_PROBES in start and SWITCH_PROBES in tasks
    assert SWITCH_PROBES in waits
    assert blocking == {("004", "T033"), ("004", "T034"), ("004", "T035"), ("004", "T037")}
    assert blocking <= qualified_tasks(waits)
    assert "`RemodelStart.SeatValidated`" in waits
    assert waits.index("step 5.6's blocking probes") < waits.index(
        "this step's Plan on one real part's copy"
    )
    assert "hash, size and time unchanged" in waits
    assert blocking | {("004", "T172"), ("004", "T182")} <= qualified_tasks(row)
    assert "step 5.3" in row and "hash" in row
    assert blocking | {("004", "T172")} <= qualified_tasks(handover)
    assert "Done already: 004 T180" in waits
    assert "004 T180 is done (decision 168A)" in row
    assert "004 T180 is done (decision 168A)" in handover
    for text in (waits, row, handover):
        assert re.search(r"004 T180\b[^.;]*\bdecided\b", text) is None
    assert handover.index("first step 21's blocking probes") < handover.index(
        "then step 5.3's Plan on one real part's copy"
    )
    # Owner decision 168A (2026-10-31; 004 research R26.5): T180 is closed on its brief; 170A
    # (R26.7) has T138 and T187 block the switch.
    assert "- [x] T180 " in tasks
    assert "*Closed 2026-10-31 (owner decision 168A; research R26.5):*" in tasks
    blocks = "**Blocks setting T172's switch**"
    assert blocks in tasks
    for task_id in ("T138", "T187"):
        assert blocks in line_starting(tasks.splitlines(), f"- [ ] {task_id} "), task_id


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
    assert "Invalid value for '--baseline'" in plain_one_line(refused.output)
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


def show_findings_by_type(plan: str, run: Path, folder: Path) -> list[str]:
    """What the plan's `Show-FindingsByType` prints for the run folder `run`."""
    quoted = str(run).replace("'", "''")
    helper = plan_function(plan, "Show-FindingsByType")
    return run_powershell(f"{helper}\nShow-FindingsByType '{quoted}'\n", folder)


def expected_groups(run: Path) -> list[str]:
    """One line per group of the folder's findings by type, as the report lists them: the
    group's title and its rows' ids, or `no row`, the checked fold last (013 T057)."""
    session = load_session(run / "session.json")
    package = load_package(run).package if (run / "package.json").is_file() else None
    view = findings_by_type(session, package, load_words(), load_policy())
    shapes = [(group.title, group.rows) for group in view.groups]
    if view.checked is not None:
        shapes.append((view.checked.title, view.checked.rows))
    return [
        f"{title}: " + (", ".join(row.finding_id for row in rows) if rows else "no row")
        for title, rows in shapes
    ]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
@pytest.mark.parametrize("fixture", ["review-folder", "check-folder"])
def test_show_findings_by_type_prints_each_groups_rows_in_the_reports_order(
    plan: str, tmp_path: Path, fixture: str
) -> None:
    """Feature 013 T057 (007 T059 as 013 changed it): the pane's grouped list and the check
    tabs' Start here rows are compared with `report.md`'s Findings by type, so the helper
    prints each group of that section and its rows' ids in its order, for a review's folder
    and a check folder alike."""
    run = tmp_path / fixture
    shutil.copytree(FIXTURES / "attention" / fixture, run)
    rerender_run_folder(run)

    lines = show_findings_by_type(plan, run, tmp_path)

    assert lines == expected_groups(run)
    assert any(line.split(": ", 1)[1] != "no row" for line in lines)
    assert plan.index("function Show-FindingsByType ") < plan.index("Set-Location $R")


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_show_findings_by_type_prints_no_row_for_every_group_of_an_empty_review(
    plan: str, tmp_path: Path
) -> None:
    run = tmp_path / "run"
    shutil.copytree(FIXTURES / "attention" / "review-folder", run)
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    session["findings"] = []
    (run / "session.json").write_text(json.dumps(session), encoding="utf-8")
    rerender_run_folder(run)

    lines = show_findings_by_type(plan, run, tmp_path)

    assert lines == [f"{group.title}: no row" for group in load_words().finding_groups]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_show_findings_by_type_prints_the_checked_fold_last(plan: str, tmp_path: Path) -> None:
    run = tmp_path / "run"
    shutil.copytree(FIXTURES / "attention" / "review-folder", run)
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    session["findings"][0]["status"] = "checked_within_scope"
    (run / "session.json").write_text(json.dumps(session), encoding="utf-8")
    rerender_run_folder(run)

    lines = show_findings_by_type(plan, run, tmp_path)

    assert lines == expected_groups(run)
    assert lines[-1] == f"Checked, no issue: {session['findings'][0]['id']}"


TIME = re.compile(r"(?:(\d+) h)?\s*(?:(\d+) min)?")
FEATURE_013_IN_STEP_5 = 20
"""The census's four Model checks (step 5.1) and 013 T144 (step 5.2), 10 minutes each."""

RETEST_2026_09_28_IN_STEP_5 = 20
"""Step 5.3's retest items A to C and the read-only option (2026-09-28): crash capture, the box
and its markers, 20 minutes."""

DECISION_144A_IN_STEP_5 = 5
"""Step 5.3's item B for 011 T171 (decision 144A, 2026-10-19): the box's Open copy, then Start,
and the run's four `seat=` lines, 5 minutes."""

DECISION_169A_IN_STEP_5 = 25
"""Step 5.3's close in process, 004 T303a, idle and with a dialog open (decision 169A, 2026-10-31;
004 T365), 25 minutes."""

GEMINI_TEST_IN_STEP_5 = 5
"""Step 5.4's live Gemini test (008 T106), part of step 5.1 to 5.4's first 35 minutes, withdrawn
when decision 173A closed 008 T106 under decision 94A (004 T363), 5 minutes."""


def minutes(estimate: str) -> int:
    """`3 h 55 min`, `3 h` or `50 min` as minutes."""
    match = TIME.fullmatch(estimate.strip())
    assert match, estimate
    hours, mins = match.groups()
    return int(hours or 0) * 60 + int(mins or 0)


def test_the_time_estimate_is_the_sum_of_its_steps(plan: str) -> None:
    """The headline figure is within seven minutes of the table's steps added up, so a
    step that grows (decision 15A added about 25 minutes) moves the headline too. Decision 18A
    adds about 40: step 1 and step 5.1's row grow, and step 5.6 has a row of its own. Feature 013
    (2026-09-27, edited deliberately) adds about 95 more: step 2's row by 20 minutes (013 T153's
    live test at step 2.7 is 5 of them, edited deliberately with its follow-ups), step 4's by 50
    and step 5.1 to 5.4's by `FEATURE_013_IN_STEP_5`, which the decision 18A range leaves out.
    The retest of 2026-09-28's U25 to U27 (edited deliberately) adds about 35 more: step 4's row by
    15 minutes (step 4.9) and step 5.1 to 5.4's by `RETEST_2026_09_28_IN_STEP_5`. Feature 015
    (015 T114, decision 4A, 2026-10-14, edited deliberately) adds 35 minutes to step 4's row
    for the unticked review, Send, restarts and timings at step 4.10. Feature 014
    (014 T221, 2026-10-17, edited deliberately) adds 10 minutes to step 4's row for the
    smoke checks at step 4.11, reading step 4.1's review without another paid review. Decision
    144A (011 T171, 2026-10-19, edited deliberately) adds `DECISION_144A_IN_STEP_5` to step 5.1
    to 5.4's row, for the pane seat's gate at step 5.3's item B, which the decision 18A range
    leaves out too. *Changed 2026-10-31 on purpose (004 T363):* step 5.1 to 5.4's row loses
    `GEMINI_TEST_IN_STEP_5` with step 5.4's Gemini test (decisions 94A and 173A), and step 5.5's
    row falls from an hour to 15 minutes with 009 T082's "before" half (decision 175A). *Changed
    2026-10-31 on purpose (004 T365):* step 5.1 to 5.4's row gains `DECISION_169A_IN_STEP_5` for
    004 T303a in step 5.3, and step 3's row 10 minutes for PROBE-15 at step 3.9 (003 T088)."""
    section = plan[plan.index("## How long it takes") : plan.index("## 0. Before the sitting")]
    rows = re.findall(r"^\| ([^|]+) \| [^|]+ \| ([^|]+) \|$", section, re.MULTILINE)[1:]
    [(hours, mins)] = re.findall(r"About \*\*(\d+) hours(?: (\d+) minutes)? at the seat", section)
    estimates = {name.strip(): minutes(estimate) for name, estimate in rows}

    assert len(rows) == 8
    assert abs(sum(estimates.values()) - (int(hours) * 60 + int(mins or 0))) <= 7
    assert estimates["5.6"] == 25 and estimates["1"] == 55 and estimates["5.1 to 5.4"] == 110
    assert estimates["5.5"] == 15
    decision_18a_in_step_5 = (
        estimates["5.1 to 5.4"]
        - (35 - GEMINI_TEST_IN_STEP_5)
        - FEATURE_013_IN_STEP_5
        - RETEST_2026_09_28_IN_STEP_5
        - DECISION_144A_IN_STEP_5
        - DECISION_169A_IN_STEP_5
    )
    assert 30 <= estimates["5.6"] + (estimates["1"] - 50) + decision_18a_in_step_5 <= 45
    assert (estimates["2"], estimates["4"]) == (40, 300)


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


SITTING_ROW = re.compile(r"^\| (S\d) \| ([^|]+) \| ([^|]+) \| [^|]+ \|$", re.MULTILINE)
"""A row of the plan's Sittings table: the sitting, its theme and its length."""
S1_ROW = re.compile(r"^\| (\d+) \| ([^|]+) \| ([^|]*) \| ([^|]+) \|$", re.MULTILINE)
"""A row of S1's table: its order, the steps it runs, their task ids and its estimate."""
STEP_NUMBER = re.compile(r"\b(\d\.\d{1,2})\b")
PAID_STEPS = frozenset({"2.5", "2.7", "3.4", "5.5"})
"""The steps outside step 4 that use the key: it is saved (2.5), lever 14's live test reads it
(2.7), and a pane review sends to the model (3.4, 5.5); every step of step 4 is a review too."""
S1_TASKS = frozenset({
    ("004", "T140"), ("004", "T164"), ("004", "T187"), ("011", "T077"), ("013", "T142"),
    ("003", "T088"), ("004", "T185"), ("004", "T186"), ("011", "T171"), ("004", "T182"),
    ("004", "T303a"), ("006", "T102"), ("001", "T076"), ("004", "T353"),
})
"""What S1 answers, as decisions 167A, 169A and 172A put it, besides the probes of step 5.6."""


def section(plan: str, heading: str) -> str:
    """The plan's section `## <heading>`, to the next heading of its level."""
    start = plan.index(f"## {heading}\n")
    end = plan.find("\n## ", start + 1)
    return plan[start : end if end >= 0 else len(plan)]


def s1_rows(plan: str) -> list[tuple[int, str, str, int]]:
    """`(order, steps, tasks, minutes)` of each row of S1's table."""
    return [
        (int(order), steps.strip(), tasks, minutes(estimate))
        for order, steps, tasks, estimate in S1_ROW.findall(section(plan, "S1: Start readiness"))
    ]


def t303a(plan: str) -> str:
    """Step 5.3's part for 004 T303a, the close in process (decision 169A)."""
    remodel = step(plan, "5.3")
    end = remodel.index("**What the Start switch waits on.**")
    return remodel[remodel.index("**004 T303a") : end]


def test_the_plan_is_run_in_short_themed_sittings_s1_first(plan: str) -> None:
    """Decision 167A: the next sitting is S1, about three hours, and later sittings are short and
    themed, each 3.5 hours or less, in place of the two-day plan (004 T365)."""
    sittings = section(plan, "Sittings")
    rows = SITTING_ROW.findall(sittings)
    lengths = {sitting: length.strip() for sitting, _, length in rows}

    assert [(sitting, theme.strip()) for sitting, theme, _ in rows] == [
        ("S1", "Start readiness"), ("S2", "Start on"), ("S3", "paid review"),
        ("S4", "drawings"), ("S5", "fixtures"),
    ]
    assert lengths["S1"] == "3 h 10 min, and an optional 25 min"
    assert [lengths[sitting] for sitting in ("S2", "S3", "S4", "S5")] == ["3 h 30 min at most"] * 4
    assert "decision 167A" in re.sub(r"\s+", " ", sittings)
    assert ("004", "T303b") in qualified_tasks(sittings)
    assert (
        plan.index("## Sittings\n")
        < plan.index("## S1: Start readiness\n")
        < plan.index("## The next sitting: where 2026-09-26 stopped")
    )


def test_s1_is_a_selection_of_the_plans_steps_whose_minutes_are_its_headline(plan: str) -> None:
    """S1 runs steps the plan already has, none that uses the key, and its estimates add up to its
    headline, 3 h 10 min, the optional block's 25 minutes apart; together they answer what
    decisions 167A, 169A and 172A put in it (004 T365)."""
    flat = re.sub(r"\s+", " ", section(plan, "S1: Start readiness"))
    rows = s1_rows(plan)
    [(hours, mins, optional)] = re.findall(
        r"about \*\*(\d+) hours (\d+) minutes\*\* at the seat, plus an optional (\d+) minutes", flat
    )
    steps = set(STEP_HEADING.findall(plan))
    named = [set(STEP_NUMBER.findall(cell)) for _, cell, _, _ in rows]
    used = set().union(*named)
    tasks = set().union(*(qualified_tasks(cell) for _, _, cell, _ in rows))

    assert [order for order, *_ in rows] == list(range(1, len(rows) + 1))
    assert sum(m for _, cell, _, m in rows if "optional" not in cell) == 190
    assert int(hours) * 60 + int(mins) == 190
    assert [m for _, cell, _, m in rows if "optional" in cell] == [int(optional)] == [25]
    assert [cell for (_, cell, _, _), numbers in zip(rows, named, strict=True)
            if not numbers and "optional" not in cell] == []
    assert used <= steps, sorted(used - steps)
    assert sorted(n for n in used if n.startswith("4.") or n in PAID_STEPS) == []
    assert "no key and no paid call" in flat
    assert S1_TASKS | set(PROBE_RUNS) <= tasks


def test_s1_runs_the_probes_that_never_reorder_early_and_the_reorders_last(plan: str) -> None:
    """Step 5.6's first run asks SOLIDWORKS for no reorder, so no "Cannot reorder" box can hold
    it, and it comes early; its second and third runs stay last before the handoff. If SOLIDWORKS
    closes during step 5.3, the close in process is skipped; the optional block is the first thing
    cut; and after S1 the development machine's three switches each go in a pull request of their
    own (decision 167A; 004 T365)."""
    cells = [cell for _, cell, _, _ in s1_rows(plan)]
    flat = re.sub(r"\s+", " ", section(plan, "S1: Start readiness"))

    def at(words: str) -> int:
        [index] = [index for index, cell in enumerate(cells) if words in cell]
        return index

    assert (
        at("first run")
        < at("3.9")
        < at("5.3: items")
        < at("close in process")
        < at("optional")
        < at("second and third runs")
        == len(cells) - 2
    )
    assert set(STEP_NUMBER.findall(cells[-1])) == {"6.0", "6.1", "6.3", "6.5"}
    assert "If SOLIDWORKS closes during step 5.3" in flat
    assert "go straight to 5.6's second and third runs" in flat
    assert "2 h 30" in flat
    assert ("004", "T138") in qualified_tasks(flat)
    for words in ("`RemodelStart.SeatValidated`", "`DrawingOpenScope.SeatValidated`",
                  "each as its own pull request"):
        assert words in flat, words
    assert "In S1 the first run comes early" in re.sub(r"\s+", " ", step(plan, "5.6"))


def test_s1s_steps_hold_what_s1_asks_of_them(plan: str) -> None:
    """Step 1.3 names 004 T140's one test, which the C# gate runs unnamed; step 1.6 runs
    `swreview seat health` (decision 166A, another lane's command, only pasted here); step 1.7
    keeps the product name 004 T164 still needs; step 3.9 runs PROBE-15 on part J (003 T088); and
    004's tasks say what is left of T140 and T164 (004 T365)."""
    tasks = (FEATURE_004 / "tasks.md").read_text(encoding="utf-8")
    [t140] = [line for line in tasks.splitlines() if line.startswith("- [ ] T140 ")]
    [t164] = [line for line in tasks.splitlines() if line.startswith("- [ ] T164 ")]
    manifest_tests = (
        REPO / "extractor" / "SwReview.Extractor.Tests" / "RemodelInteropManifestTests.cs"
    )

    assert (
        'dotnet test extractor\\SwReview.Extractor.Tests\\SwReview.Extractor.Tests.csproj '
        '-c Release --no-build --filter "FullyQualifiedName~InstalledAssemblyMatchesManifest" '
        '--logger "console;verbosity=normal"'
    ) in step(plan, "1.3")
    assert "public void InstalledAssemblyMatchesManifest()" in manifest_tests.read_text(
        encoding="utf-8"
    )
    assert ("004", "T140") in qualified_tasks(step(plan, "1.3"))
    assert 'cd "$R\\reviewer"; uv run swreview seat health; "exit code: $LASTEXITCODE"; cd $R' in (
        step(plan, "1.6")
    )
    assert "In S1 only the product" in re.sub(r"\s+", " ", step(plan, "1.7"))
    assert (
        'swreview-extract probe rms --doc "<full path of part J>" | Out-File -FilePath '
        '"$H\\probes\\probe-rms-J.txt" -Encoding utf8; "exit code: $LASTEXITCODE"'
    ) in step(plan, "3.9")
    assert {("003", "T088"), ("011", "T077")} <= qualified_tasks(step(plan, "3.9"))
    rms = re.sub(r"\s+", " ", step(plan, "3.9"))
    assert "the `root_component:` line whole" not in rms
    assert "write only `a component name`, never the name" in rms
    assert "`InstalledAssemblyMatchesManifest`" in t140 and "passed, not skipped" in t140
    assert "*Amended 2026-10-31" in t164 and "the product Help > About names" in t164


def test_t303a_ends_only_the_backend_the_add_in_started_and_only_by_its_pid(plan: str) -> None:
    """004 T303a ends the review backend the add-in started, by the number its own log gives
    (`BackendProcess`), and only once that number is still a backend's process; no document of
    the sitting ends a process by its name. The close it reads for is the tool service's own line,
    and what cannot be made by hand stays the fakes' (decision 169A; 004 T365)."""
    part = t303a(plan)
    flat = re.sub(r"\s+", " ", part)
    backend = (REPO / "extractor" / "SwReview.AddIn" / "Review" / "BackendProcess.cs").read_text(
        encoding="utf-8"
    )

    for path in (PLAN, HANDOVER, RUNBOOK):
        text = path.read_text(encoding="utf-8")
        assert re.findall(r"Stop-Process(?! -Id \$backend\b)", text) == [], path.name
        assert "taskkill" not in text.lower(), path.name
    assert "Stop-Process -Id $backend" in part
    assert "$p.ProcessName -in 'uv', 'swreview', 'python'" in part
    assert '$"backend healthy on {Origin} (pid {ProcessId})"' in backend
    assert (
        "remodel close in process thread=posted reason=remodel.close verified=true "
        "tag_removed=true copy_closed=true"
    ) in flat
    assert "decision 169A" in flat and "the fakes" in flat
    assert "Of the barrier, which decision 169A puts here," in flat
    assert "which items 2 to 4 check" in flat
    assert ("004", "T303a") in qualified_tasks(part)
    assert ("004", "T303a") in tagged_tasks(plan)


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_t303a_reads_the_newest_backend_logs_pid_and_ends_that_process_once_the_copy_is_open(
    plan: str, tmp_path: Path
) -> None:
    """T303a's first two blocks, pasted as they stand, over a stand-in `LOCALAPPDATA` and run
    root: the number is the newest backend log's, and the process is ended only once a remodel
    folder made after the wait began holds `open_record.written` - here a sleeping Python this
    test started, the backend's stand-in (004 T365). *Strengthened 2026-10-31 on review (004
    T370):* the older log takes the later name, so only the sort by write time finds the newer;
    an older remodel folder already holds `open_record.written`, so only the folder's creation
    time keeps the block waiting; and the copy's open begins a second before it is written, the
    backend still running then, so a block that ended it at `copy_open.begin` - inside the open,
    the barrier's case the plan leaves to the fakes - fails here."""
    [number, wait, *_] = POWERSHELL_BLOCK.findall(t303a(plan))
    logs = tmp_path / "local" / "SwReview" / "logs"
    logs.mkdir(parents=True)
    runs = tmp_path / "runs"
    runs.mkdir()
    earlier = runs / "20261031-080000-J-remodel"
    earlier.mkdir()
    (earlier / "remodel-open.jsonl").write_text(
        '{"at": "2026-10-31T08:00:09+00:00", "phase": "open_record.written"}\n', encoding="utf-8"
    )
    marker = tmp_path / "waiting"
    alive_inside_the_open: list[bool] = []
    sleeper = subprocess.Popen([sys._base_executable, "-c", "import time; time.sleep(90)"])
    try:
        older = logs / "backend-20261031-110000.log"
        older.write_text(
            "[2026-10-31T09:00:01+00:00] backend healthy on http://127.0.0.1:50001 (pid 4)\n",
            encoding="utf-8",
        )
        os.utime(older, (1_000_000_000, 1_000_000_000))
        (logs / "backend-20261031-100000.log").write_text(
            "[2026-10-31T10:00:00+00:00] starting\n"
            f"[2026-10-31T10:00:01+00:00] backend healthy on http://127.0.0.1:50002 "
            f"(pid {sleeper.pid})\n",
            encoding="utf-8",
        )

        def open_a_copy() -> None:
            deadline = time.monotonic() + 120
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            time.sleep(1)
            run = runs / "20261031-100500-J-remodel"
            run.mkdir()
            record = run / "remodel-open.jsonl"
            record.write_text(
                '{"at": "2026-10-31T10:05:01+00:00", "phase": "copy_open.begin"}\n',
                encoding="utf-8",
            )
            time.sleep(1)
            alive_inside_the_open.append(sleeper.poll() is None)
            with record.open("a", encoding="utf-8") as appended:
                appended.write(
                    '{"at": "2026-10-31T10:05:09+00:00", "phase": "open_record.written"}\n'
                )

        writer = threading.Thread(target=open_a_copy, daemon=True)
        writer.start()
        local, root, waiting, handover = (
            str(path).replace("'", "''")
            for path in (tmp_path / "local", runs, marker, tmp_path / "handover")
        )
        lines = run_powershell(
            f"$env:LOCALAPPDATA = '{local}'\n$runs = '{root}'\n$H = '{handover}'\n{number}\n"
            f"New-Item -ItemType File '{waiting}' | Out-Null\n{wait}\n",
            tmp_path,
        )
        writer.join(timeout=150)

        assert lines == [
            f"backend pid {sleeper.pid} | running: True",
            f"ended the backend, pid {sleeper.pid}",
        ]
        assert alive_inside_the_open == [True]
        assert sleeper.wait(timeout=30) is not None
    finally:
        if sleeper.poll() is None:
            sleeper.kill()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_t303a_times_the_close_from_save_and_reads_it_before_the_new_backends_start(
    plan: str, tmp_path: Path
) -> None:
    """004 T303 asks for the close's line before the new backend's start, within 30 seconds of
    Save, and the Windows clock shows minutes only: Save's time is taken from a line pasted just
    before it, and T303a's reading block, pasted as it stands over a stand-in `LOCALAPPDATA`,
    prints the seconds from Save to the close and whether the newest backend log began after it -
    `False` when that backend began first (004 T370, on review)."""
    blocks = POWERSHELL_BLOCK.findall(t303a(plan))
    [save] = [block for block in blocks if "$save = " in block]
    [read] = [block for block in blocks if "$started" in block]
    logs = tmp_path / "local" / "SwReview" / "logs"
    logs.mkdir(parents=True)
    run = tmp_path / "runs" / "20261031-100500-J-remodel"
    run.mkdir(parents=True)
    close = (
        "[2026-10-31T10:06:12.5000000+00:00] remodel close in process thread=posted "
        "reason=remodel.close verified=true tag_removed=true copy_closed=true "
        "gated=ISldWorks.CloseDoc"
    )
    (logs / "tool-service-20261031-090000.log").write_text(
        "[2026-10-31T09:30:00.0000000+00:00] remodel close in process thread=posted run=x "
        "nothing closed: this bridge holds no session of that run\n" + close + "\n",
        encoding="utf-8",
    )
    (run / "remodel.log").write_text(close + "\n", encoding="utf-8")
    older = logs / "backend-20261031-100000.log"
    older.write_text(
        "[2026-10-31T10:00:00.0000000+00:00] starting uv run swreview serve\n"
        "[2026-10-31T10:06:10.0000000+00:00] backend stopped\n",
        encoding="utf-8",
    )
    os.utime(older, (1_000_000_000, 1_000_000_000))
    newest = logs / "backend-20261031-100613.log"
    local, folder = (str(path).replace("'", "''") for path in (tmp_path / "local", run))
    setup = (
        f"$env:LOCALAPPDATA = '{local}'\n$open = Get-Item -LiteralPath '{folder}'\n"
        "$save = [DateTimeOffset]'2026-10-31T10:06:00+00:00'\n"
    )

    def reading(started: str) -> list[str]:
        newest.write_text(f"[{started}] starting uv run swreview serve\n", encoding="utf-8")
        return run_powershell(f"{setup}{read}\n", tmp_path)

    assert "$save = [DateTimeOffset]::Now" in save and "'HH:mm:ss.fff'" in save
    assert reading("2026-10-31T10:06:13.1000000+00:00") == [
        close, close, "close 12.5 s after Save | before the new backend's start: True",
    ]
    assert reading("2026-10-31T10:06:05.0000000+00:00")[-1] == (
        "close 12.5 s after Save | before the new backend's start: False"
    )


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_t303a_leaves_the_folder_for_runs_outside_the_handover_folder(
    plan: str, tmp_path: Path
) -> None:
    """T303a moves the folder for runs into the handover folder and back. Item 2 can end nothing,
    after which item 3 never moved it, so item 4 moves it to the other of the two; whatever
    happened, step 5.3 ends with it at `$runs`; and step 6.0's line, pasted as it stands over a
    stand-in `APPDATA`, says whether the saved folder for runs is outside the handover folder, so
    the seat is not left writing its runs into it (004 T370, on review)."""
    part = re.sub(r"\s+", " ", t303a(plan))
    [line] = [
        line for block in POWERSHELL_BLOCK.findall(step(plan, "6.0"))
        for line in block.splitlines() if "folder for runs outside the handover folder" in line
    ]
    appdata = tmp_path / "roaming"
    (appdata / "SwReview").mkdir(parents=True)
    settings = appdata / "SwReview" / "settings.json"
    handover = tmp_path / "handover" / "2026-10-31"
    roaming, quoted = (str(path).replace("'", "''") for path in (appdata, handover))

    def check(run_root: Path | None) -> list[str]:
        if run_root is None:
            settings.unlink(missing_ok=True)
        else:
            settings.write_text(json.dumps({"run_root": str(run_root)}), encoding="utf-8")
        return run_powershell(f"$env:APPDATA = '{roaming}'\n$H = '{quoted}'\n{line}\n", tmp_path)

    assert "set the folder for runs to the other of the two" in part
    assert "**Before leaving step 5.3, whatever happened above**" in part
    assert check(handover / "runs-t303a") == ["folder for runs outside the handover folder: False"]
    assert check(Path(str(handover).upper())) == [
        "folder for runs outside the handover folder: False"
    ]
    assert check(tmp_path / "handover" / "2026-10-31-other") == [
        "folder for runs outside the handover folder: True"
    ]
    assert check(tmp_path / "runs") == ["folder for runs outside the handover folder: True"]
    assert check(None) == ["folder for runs outside the handover folder: True"]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell is not on PATH")
def test_the_opens_seconds_are_read_from_the_runs_remodel_open_record(
    plan: str, tmp_path: Path
) -> None:
    """004 T182 sets the open route's wait from the time the open takes on a real part, so step
    5.3 reads it from the run's own `remodel-open.jsonl`, in the shape the backend writes it, from
    the first phase to the last (004 T365)."""
    [block] = [
        found for found in POWERSHELL_BLOCK.findall(step(plan, "5.3")) if "$phases" in found
    ]
    run = tmp_path / "20261031-101112-J-remodel"
    run.mkdir()
    _open_phase(run, "copy_open.begin")
    [written] = (run / OPEN_DIAGNOSTICS_FILE).read_text(encoding="utf-8").splitlines()
    assert set(json.loads(written)) == {"at", "phase"}
    began = datetime(2026, 10, 31, 10, 11, 12, 345678, tzinfo=UTC)
    phases = ((0, "copy_open.begin"), (4.5, "baseline_geometry.begin"),
              (12.34, "open_record.written"))
    (run / OPEN_DIAGNOSTICS_FILE).write_text(
        "".join(
            json.dumps({"at": (began + timedelta(seconds=at)).isoformat(), "phase": phase}) + "\n"
            for at, phase in phases
        ),
        encoding="utf-8",
    )
    quoted = str(run).replace("'", "''")

    lines = run_powershell(f"$run = Get-Item -LiteralPath '{quoted}'\n{block}\n", tmp_path)

    assert lines == ["open: 12.3 s, from copy_open.begin to open_record.written"]


def test_the_handover_says_the_next_sitting_is_s1(plan: str) -> None:
    """The handover gives the assistant S1's order and points at the plan's table, which wins
    (decision 167A; 004 T365)."""
    handover = HANDOVER.read_text(encoding="utf-8")
    s1 = handover[handover.index("## The next sitting is S1") :]
    s1 = s1[: s1.index("\n## ")]

    assert "the test plan's section \"S1: Start readiness\"" in re.sub(r"\s+", " ", s1)
    assert S1_TASKS <= qualified_tasks(s1) | qualified_tasks(section(plan, "S1: Start readiness"))
    assert ("004", "T303a") in qualified_tasks(s1)


START_WAITS_ON = frozenset({("004", "T303a"), ("004", "T303b"), ("004", "T138"), ("004", "T187")})
"""What Start waits on besides the blocking probes and a real Plan: the close in process's two
halves (decision 169A) and IDENTITY's calibration (decision 170A: Start refuses every change while
it is uncalibrated); with R22.14 and R25.13, fixed under decision 165A. *Changed 2026-10-31 on
purpose (004 T377, review finding RR3):* 004 T180 is no longer here, since decision 168A closed it;
the Start test asserts that the plan says it is done."""


def test_what_the_start_switch_waits_on_is_what_004_research_lists(plan: str) -> None:
    """004 research R25.9 lists what Start (T172) waits on: T303, R22.14, T180, the blocking probes,
    a real Plan and R25.13; decision 169A splits T303 and decision 170A adds T138 and T187. Step
    5.3's paragraph and the development machine's row say all of it (004 T367). *Since 2026-10-31*
    (004 T377, review finding RR3) also the two that R25.9 and R27.8 add: the owner's call on the
    no-handle unwind (Codex's CX1, R26.10), and the blocking probes' answers file committed under
    `benchmarks/native/capabilities/` and judged ready by `swreview remodel ledger`, which
    `test_seat_switch_evidence.py` holds the switch to; "After S1" and the handover say both."""
    waits = re.sub(r"\s+", " ", step(plan, "5.3"))
    waits = waits[waits.index("**What the Start switch waits on.**") :]
    [row] = [
        line for line in plan[plan.index("## Not in this sitting") :].splitlines()
        if "`RemodelStart.SeatValidated`" in line
    ]
    research = (FEATURE_004 / "research.md").read_text(encoding="utf-8")
    listed = research[research.index("### R25.9 ") : research.index("### R25.10 ")]

    for reference in ("R22.14", "R25.13"):
        assert reference in listed, reference
    after = re.sub(r"\s+", " ", section(plan, "S1: Start readiness"))
    after = after[after.index("### After S1") :]
    handover = re.sub(r"\s+", " ", HANDOVER.read_text(encoding="utf-8"))
    evidence = (REVIEWER / "tests" / "unit" / "test_seat_switch_evidence.py").read_text(
        encoding="utf-8"
    )

    assert "no-handle unwind" in listed and "R26.10" in listed
    assert "*Done (168A; R26.5):* T180" in listed
    assert "`benchmarks/native/capabilities/` is one `swreview remodel ledger` judges ready" in (
        evidence
    )
    for text in (waits, row):
        missing = START_WAITS_ON - qualified_tasks(text)
        assert missing == set(), sorted(missing)
        assert "R22.14" in text and "R25.13" in text
        assert "decision 170A" in text
    for text in (waits, row, after, handover):
        assert "no-handle unwind" in text and "R26.10" in text
        assert "`benchmarks/native/capabilities/`" in text and "R27.8" in text
        assert "judged ready by `swreview remodel ledger`" in text


def test_the_plan_says_001_t076s_buttons_are_built(plan: str) -> None:
    """001 T076's Interference and Capture selection buttons are on the Extract tab
    (`TaskPaneControl`), so no row says they are not built; S1's optional block settles the
    volume unit T076 reads (decision 172A; 004 T367)."""
    pane = (REPO / "extractor" / "SwReview.AddIn" / "TaskPaneControl.cs").read_text(
        encoding="utf-8"
    )
    [row] = [line for line in plan.splitlines() if line.startswith("| 001 | 001 T061, 001 T076 |")]

    assert 'Text = "Interference",' in pane and 'Text = "Capture selection",' in pane
    assert "not built" not in row
    assert "**Interference**" in row and "**Capture selection**" in row
    assert "decision 172A" in row


def test_the_specs_readme_says_which_features_mark_seat_tasks_and_how() -> None:
    """`specs/README.md` said features 001 to 004 and 016 use no `[W]`; 004 T303 carried it, and
    since decision 166A the workstation tasks of 001, 002 and 016 are tagged too, while 003 and 004
    also say `Workstation` first. The pins read both (004 T367)."""
    readme = re.sub(r"\s+", " ", (REPO / "specs" / "README.md").read_text(encoding="utf-8"))

    assert "Features 001 to 004 and 016 do not use `[W]`" not in readme
    assert "begins `Workstation`" in readme
    assert "`reviewer/tests/support/seat_tasks.py`" in readme
    assert "decision 166A" in readme


def test_the_seat_work_found_after_the_plan_has_a_place(plan: str) -> None:
    """Work for the seat found after the plan was written has a place in it: 004 T188's native
    configuration-watch timing (`docs/development-handoff-2026-10-23.md`), 004 T187 (step 5.6)
    and the focused retest of 2026-10-13 (`docs/history/testing-feedback-2026-10-13.md`), whose
    Review half waits on the owner (004 T367)."""
    aside = plan[plan.index("## Not in this sitting") :]
    flat = re.sub(r"\s+", " ", aside)

    assert ("004", "T188") in qualified_tasks(aside)
    assert "`docs/development-handoff-2026-10-23.md`" in flat
    assert "`docs/history/testing-feedback-2026-10-13.md`" in flat
    assert ("004", "T187") in tagged_tasks(plan)
    # On review (004 T370): neither the watch nor its start writes a log line, so S1's logs
    # cannot show the timing.
    [watch] = [line for line in aside.splitlines() if "004 T188" in line]
    assert "S1 cannot show it" in watch and "at S2" in watch
    assert "reads it from S1's" not in watch


def test_011_t101_is_its_screenshot_and_its_live_checks_are_011_t095s(
    plan: str, results: str
) -> None:
    """011 T101 could not pass as written: since 013 T142 no same-name question is asked while the
    read-only open's switch is off, and with it on, its part 1's refusal cannot happen. Its part 1
    is dropped, its parts 2 and 3 are 011 T095's, at the sitting after the switch, and its part 4,
    the screenshot, stays at step 4.7 (004 T368)."""
    tasks = (REPO / "specs" / "011-drawing-context" / "tasks.md").read_text(encoding="utf-8")
    [t101] = [line for line in tasks.splitlines() if line.startswith("- [ ] T101 ")]
    [t095] = [line for line in tasks.splitlines() if line.startswith("- [ ] T095 ")]

    assert_named_only_at({("011", "T101"): {"4.7"}}, plan, results)
    assert "*Rewritten 2026-10-31" in t101 and "300 by 600" in t101
    assert "011 T101's parts 2 and 3" in t095


STEP_RANGE = re.compile(r"\b(\d)\.(\d{1,2}) to \1\.(\d{1,2})\b")
"""A range of one step's parts: `2.5 to 2.7`."""
WHOLE_STEP = re.compile(r"\bsteps? (\d)\b(?!\.\d)")
"""A whole step: `step 4`, `step 6's handoff`."""


def steps_named(text: str, steps: set[str]) -> set[str]:
    """Which of the plan's `steps` the text names: `5.5`, a range `2.5 to 2.7`, or a whole step,
    `step 4`."""
    named = set(STEP_NUMBER.findall(text))
    for major, first, last in STEP_RANGE.findall(text):
        named |= {f"{major}.{minor}" for minor in range(int(first), int(last) + 1)}
    for major in WHOLE_STEP.findall(text):
        named |= {number for number in steps if number.startswith(f"{major}.")}
    return named & steps


def test_every_step_has_a_sitting_or_is_named_as_not_yet_placed(plan: str) -> None:
    """Every step of steps 1 to 6 is S1's, or the Sittings section names it: in a later
    sitting's row, as opening or closing every sitting, as not yet placed, or as withdrawn. Step
    5.5, a paid review, is S3's (decision 167A; 004 T370, on review)."""
    steps = {number for number in STEP_HEADING.findall(plan) if not number.startswith("0.")}
    sittings = section(plan, "Sittings")
    s1 = set().union(*(steps_named(cell, steps) for _, cell, _, _ in s1_rows(plan)))
    [s3] = [line for line in sittings.splitlines() if line.startswith("| S3 |")]

    assert steps_named("steps 2.5 to 2.7, 3.4, step 4 and 5.5", steps) >= {
        "2.5", "2.6", "2.7", "3.4", "4.1", "4.11", "5.5",
    }
    assert len(steps) >= 40
    assert sorted(steps - s1 - steps_named(sittings, steps)) == []
    assert "5.5" in steps_named(s3, steps)
    assert "not yet placed" in re.sub(r"\s+", " ", sittings)


def test_s1_with_its_optional_block_still_ends_within_3_h_30(plan: str) -> None:
    """Every sitting is 3 h 30 min or less (decision 167A), S1 with its optional block too: the
    block starts only when its 25 minutes and every row after it still end by then. S1's rows
    before it end at 2 h 30 on their estimates, so it runs only when S1 is ahead (004 T370, on
    review)."""
    flat = re.sub(r"\s+", " ", section(plan, "S1: Start readiness"))
    rows = s1_rows(plan)
    [optional] = [index for index, (_, cell, _, _) in enumerate(rows) if "optional" in cell]
    [(hours, mins)] = re.findall(
        r"\*\*The optional block\*\* starts only by (\d) h (\d+) on the sitting's clock", flat
    )

    assert "each 3 hours 30 minutes or less, S1 first" in re.sub(
        r"\s+", " ", section(plan, "Sittings")
    )
    assert int(hours) * 60 + int(mins) + sum(m for *_, m in rows[optional:]) == 210
    assert sum(m for *_, m in rows[:optional]) == 150
    assert "at least five minutes ahead" in flat


def test_not_in_this_sitting_says_what_s1_runs_of_the_tasks_it_holds(plan: str) -> None:
    """003 T088's PROBE-15 runs at step 3.9 and 004 T140's manifest half at step 1.3, both in S1,
    so the rows that hold those tasks say so; and the section no longer says no step runs what it
    holds, since S2 and S5 name some of it (004 T370, on review)."""
    aside = plan[plan.index("## Not in this sitting") :]
    lines = aside.splitlines()
    [rms] = [line for line in lines if line.startswith("| 003 | 003 T062, 003 T088, 003 T089 |")]
    [stage] = [line for line in lines if line.startswith("| 004 | 004 T135 to T141 |")]
    head = re.sub(r"\s+", " ", aside[: aside.index("| Package |")])

    assert "step 3.9" in rms and "S1" in rms
    assert "step 1.3" in stage and "004 T140" in stage
    assert "what none of its steps runs" not in head
    assert "S2 and S5" in head


def test_the_specs_readme_counts_a_task_173a_closed_as_done() -> None:
    """Decision 173A closes a replaced or deferred task by ticking it with a dated note, so the
    README no longer counts an unticked `SUPERSEDED (127A)` task as superseded, and the rows of
    the four features whose tasks 004 T361 closed are recounted (004 T370, on review)."""
    readme = (REPO / "specs" / "README.md").read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", readme)
    rows = {line[2:5]: line for line in readme.splitlines() if re.match(r"^\| \d{3} \|", line)}

    assert "is counted as superseded, not open" not in flat
    assert "decision 173A" in flat
    for number, counts, closed in (
        ("001", "102 / 3 / 0", "T098"),
        ("002", "298 / 4 / 0", "T055a"),
        ("005", "86 / 27 / 0", "T073"),
        ("008", "124 / 5 / 0", "T106"),
    ):
        assert f"| {counts} |" in rows[number], number
        assert "Closed on 2026-10-31 (decision 173A)" in rows[number], number
        assert closed in rows[number].split("Closed on 2026-10-31")[1], number


def test_swreview_remodel_ledger_prints_what_step_5_6_reads(tmp_path: Path) -> None:
    """`Show-RemodelLedger` hands each answers file to `swreview remodel ledger` (decision 166A),
    and step 5.6 reads from it each probe's id, verdict and reason. That reader is another lane's,
    merged before this plan's: until it is in the checkout this skips; once it is, an answers
    file in `RemodelProbeLedger.Render`'s shape is read through it (004 T370, on review)."""
    if "ledger" not in get_command(app).commands["remodel"].commands:
        pytest.skip("`swreview remodel ledger`, decision 166A's reader, is not in this checkout")
    ledger = tmp_path / "remodel-32.5.0.48.yaml"
    ledger.write_text(
        rendered_ledger(
            [
                ("PROBE-2", True, "verified", {"reason": "get_Value returned 120."}),
                ("PROBE-13", False, "unresolved", {"error": "InvalidCastException"}),
            ]
        ),
        encoding="utf-8-sig",
    )

    result = CliRunner().invoke(app, ["remodel", "ledger", str(ledger)])
    output = plain_one_line(result.output)

    assert result.exit_code == 0, output
    for words in ("PROBE-2", "verified", "get_Value returned 120.", "PROBE-13", "unresolved"):
        assert words in output, words


SUPERSEDED_BY_S1 = "*Superseded 2026-10-31 by S1 (decision 167A):*"
"""How each older section that told the next sitting where to start opens since S1."""


def test_only_s1_says_what_the_next_sitting_runs(plan: str) -> None:
    """S1 is the next sitting and runs only its table's steps, with no key and no paid call
    (decision 167A). Two older sections told "the next sitting" where to start: at step 2.4, and
    with the retest of 2026-09-28, whose step 4.9 presses Review on a seat that has had the owner's
    key since then. Each now opens with a dated line saying S1 supersedes it, step 4.9's own
    header says it is S3's, and no section but S1's says what the next sitting runs or where it
    starts (004 T377, review finding RR2)."""
    for heading in (
        "The next sitting: where 2026-09-26 stopped, and what feature 013 adds",
        "First: the retest of 2026-09-28's findings U25 to U27",
    ):
        [_, opening, *_] = section(plan, heading).split("\n\n")
        assert opening.startswith(SUPERSEDED_BY_S1), heading
        assert "step 4.9 is S3's" in re.sub(r"\s+", " ", opening), heading
    header = re.sub(r"\s+", " ", step(plan, "4.9").split("\n\n")[1])
    assert "S3" in header and "decision 167A" in header and "not in S1" in header
    for part in re.split(r"(?m)^## ", plan)[1:]:
        if part.startswith("S1: Start readiness\n"):
            continue
        flat = re.sub(r"\s+", " ", part.replace("**", ""))
        assert re.search(r"\b[Tt]he next sitting (?:runs|starts)\b", flat) is None, part[:60]


def test_t303a_records_its_stuck_case_as_its_task_allows(plan: str, results: str) -> None:
    """004 T303a asks for the close once with the backend ended and once with it stuck, its
    process suspended by its PID, and, if the seat cannot suspend a process, for that to be
    recorded and the stuck case left to the fakes it names. The plan made only the first: Windows
    has no command that suspends a process, and when the backend runs through `uv` the number
    item 1 reads is uv's, whose server runs under it in the backend's job, so suspending that
    number leaves the server answering. The plan now says so and has the engineer write the
    task's own fallback in a row of its own (004 T377, review finding RR6)."""
    part = re.sub(r"\s+", " ", t303a(plan))
    tasks = (FEATURE_004 / "tasks.md").read_text(encoding="utf-8")
    task = line_starting(tasks.splitlines(), "- [ ] T303a ")
    backend = (REPO / "extractor" / "SwReview.AddIn" / "Review" / "BackendProcess.cs").read_text(
        encoding="utf-8"
    )
    record = "`stuck case: the seat cannot suspend a process; left to the fakes (169A)`"
    stuck_fake = (
        "RemodelHostTests.ARunRootChangeWhoseOldRunsCloseIsNotAnsweredStopsTheOldBackendThen"
        "ClosesItInProcess"
    )
    rows = [line for line in results.splitlines() if line.startswith("| 5.3 | 004 T303a")]

    assert (
        "once with it stuck (its process suspended by its PID; if the seat cannot suspend a "
        "process, record that and leave the stuck case to the fakes below)"
    ) in task
    assert stuck_fake in task
    assert "// grandchildren `uv run` leaves between us and the server." in backend
    assert record in part and "`ARunRootChangeWhoseOldRunsCloseIsNotAnswered" in part
    assert "Record in 004 T303a's three rows" in part
    assert len(rows) == 3 and "the stuck case" in rows[-1]
