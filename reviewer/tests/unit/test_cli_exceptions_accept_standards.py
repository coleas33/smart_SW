"""Unit tests for `swreview exceptions accept-standards` (T088).

`contracts/cli.md`: this is **the existing `accept-rms` command generalized over the
family, not a second implementation** - one command body, two names. The checker's flat
`{ "<check_id>": "<reason>" }` file is an *import* and never a store: a check id is not a
condition, and keeping the file would silence that check on every document forever. Read
against one `check standards` run it says enough - every `demonstrated` finding of a listed
**error**-severity check becomes one `ReviewException` bound to that finding's document,
its component instances and its configuration, with the reason as the note.

What these tests pin:

- **what an accepted id writes**: one exception per demonstrated finding, each with
  `fingerprint_kind: "standards"` and `document_id` set, `exceptions.json` **beside the
  package**, `exception_id` on the findings and a re-rendered report;
- **the document binding**: two findings of one check on two documents become **two**
  exceptions naming two documents, because a standards waiver waives a check **on a
  document** (FR-041, SC-008);
- **the five status words** - `accepted <n>`, `would accept <n>`, `unused`,
  `invalid (warning check)` and `invalid (unknown check)` - in both the human and the
  `--json` shapes;
- **any invalid id makes exit 1 and writes nothing**; an all-valid file writes and exits 0;
- **the family guard**: the family comes from the run's `check.json`, and the command
  **name** is a guard on it, so `accept-standards` pointed at an rms run and `accept-rms`
  pointed at a standards run are both refused with exit 1 **naming both families**;
- **the rms labels do not move**: they are facts on `RMS_FAMILY`, read by the same
  generalized helper, so `test_cli_exceptions_accept_rms.py` passes unedited.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.rms.registry import RMS_FAMILY
from swreview.checks.rms.registry import RULES as RMS_RULES
from swreview.checks.rms.run import RmsScope, run_rms_check
from swreview.checks.rules.family import waiver_invalidity
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import RULES as STANDARDS_RULES
from swreview.checks.standards.registry import STANDARDS_FAMILY
from swreview.checks.standards.run import run_standards_check
from swreview.exceptions import EXCEPTIONS_FILE_NAME
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from swreview.report.dispositions import REPORT_FILE_NAME, SESSION_FILE_NAME
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    PartSpec,
    standards_package,
)
from tests.unit.test_cli import invoke, payload

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE_PATH = FIXTURE_DIR / "profile-a.yaml"
RMS_PART_FIXTURE = Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "rms-part"

MATERIAL_ASSIGNED = "standards.part.material_assigned"
"""An error check the package below fails **twice**, on two different part documents."""

NOT_EXPLODED = "standards.assembly.not_exploded"
"""A second error check, failing once, on the assembly."""

ONE_FIXED = "standards.assembly.one_fixed"
"""An error check this run reports no finding for: `unused`, never invalid."""

REVISION_MATCHES = "standards.drawing.revision_matches"
"""A warning check: never waivable (`contracts/rules.md`, "Waivable checks")."""

UNKNOWN_CHECK = "standards.not.a.check"

REASON = "legacy part; deviation accepted at release review"


# --- the package and the run every test reads ----------------------------------------------


def graded_package() -> EvidencePackage:
    """An exploded assembly over two parts with no material: three findings, two checks.

    Both parts are read in the configuration the profile names its material one, so
    `part.material_assigned` grades the material rather than reporting the configuration
    mismatch that is its own unresolved row.
    """
    profile = load_profile(PROFILE_PATH)
    return standards_package(
        documents=[
            AssemblySpec(
                name="top",
                folder="jobs/mr-400",
                is_exploded=True,
                components=[
                    ComponentSpec(name="plate-1", document="plate"),
                    ComponentSpec(name="bar-1", document="bar"),
                ],
            ),
            PartSpec(
                name="plate",
                folder="jobs/mr-400",
                configuration=profile.material.configuration,
                material=None,
            ),
            PartSpec(
                name="bar",
                folder="jobs/mr-400",
                configuration=profile.material.configuration,
                material=None,
            ),
        ],
        profile=profile,
    )


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "package"
    save_package(graded_package(), directory)
    return directory


@pytest.fixture
def run_dir(package_dir: Path, tmp_path: Path) -> Path:
    """The run folder `swreview check standards --out` leaves, built through the entry
    point the command itself calls."""
    directory = tmp_path / "run"
    run_standards_check(package_dir, PROFILE_PATH, directory)
    return directory


@pytest.fixture
def rms_run(tmp_path: Path) -> tuple[Path, Path]:
    """An **rms** package and run: what the family guard must refuse to grade here."""
    directory = tmp_path / "rms-package"
    shutil.copytree(RMS_PART_FIXTURE, directory)
    (directory / EXCEPTIONS_FILE_NAME).unlink()
    out = tmp_path / "rms-run"
    run_rms_check(directory, out_dir=out, scope=RmsScope.part)
    return directory, out


@pytest.fixture
def waiver_file(tmp_path: Path) -> Callable[[object], Path]:
    def write(waivers: object) -> Path:
        path = tmp_path / "waivers.json"
        path.write_text(json.dumps(waivers, indent=2), encoding="utf-8")
        return path

    return write


def accept_standards(run_dir: Path, package_dir: Path, file: Path, *extra: str) -> Any:
    return invoke(
        "exceptions",
        "accept-standards",
        str(run_dir),
        "--package",
        str(package_dir),
        "--file",
        str(file),
        "--by",
        "engineer",
        *extra,
    )


def accept_rms(run_dir: Path, package_dir: Path, file: Path, *extra: str) -> Any:
    return invoke(
        "exceptions",
        "accept-rms",
        str(run_dir),
        "--package",
        str(package_dir),
        "--file",
        str(file),
        "--by",
        "engineer",
        *extra,
    )


def statuses(body: Any) -> dict[str, str]:
    return {row["rule_id"]: row["status"] for row in body["rules"]}


def stored_exceptions(package_dir: Path) -> list[Any]:
    return json.loads(
        (package_dir / EXCEPTIONS_FILE_NAME).read_text(encoding="utf-8")
    )["exceptions"]


def session_of(run_dir: Path) -> Any:
    return json.loads((run_dir / SESSION_FILE_NAME).read_text(encoding="utf-8"))


def stderr(result: Any) -> str:
    return result.stdout + getattr(result, "stderr", "")


# --- 1. what an accepted id writes ----------------------------------------------------------


def test_it_writes_one_standards_exception_per_demonstrated_finding(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    body = payload(
        accept_standards(run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON}), "--json")
    )

    assert statuses(body) == {NOT_EXPLODED: "accepted 1"}
    [stored] = stored_exceptions(package_dir)
    assert stored["id"] == "EX-001"
    assert stored["check"] == NOT_EXPLODED
    assert stored["note"] == REASON
    assert stored["accepted_by"] == "engineer"
    assert stored["fingerprint_kind"] == "standards"
    assert stored["status"] == "active"
    assert stored["document_id"]


def test_the_exception_is_written_beside_the_package_and_not_in_the_run_folder(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """The other half of the rule that makes a command-line acceptance survive the next
    run: the run folder's own copy is what the *next* run carries forward."""
    body = payload(
        accept_standards(run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON}), "--json")
    )

    assert Path(body["exceptions_file"]) == package_dir / EXCEPTIONS_FILE_NAME
    assert (package_dir / EXCEPTIONS_FILE_NAME).is_file()


def test_two_findings_of_one_check_become_two_exceptions_naming_two_documents(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """A standards waiver waives a check **on a document** (FR-041, SC-008)."""
    body = payload(
        accept_standards(run_dir, package_dir, waiver_file({MATERIAL_ASSIGNED: REASON}), "--json")
    )

    assert statuses(body) == {MATERIAL_ASSIGNED: "accepted 2"}
    stored = stored_exceptions(package_dir)
    assert [item["check"] for item in stored] == [MATERIAL_ASSIGNED, MATERIAL_ASSIGNED]
    documents = [item["document_id"] for item in stored]
    assert len(set(documents)) == 2
    assert all(document for document in documents)


def test_it_records_the_exception_on_the_finding_and_re_renders_the_report(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    accept_standards(run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON}))

    session = session_of(run_dir)
    accepted = [item for item in session["findings"] if item["check"] == NOT_EXPLODED]
    assert [item["exception_id"] for item in accepted] == ["EX-001"]
    assert all(
        item["exception_id"] is None
        for item in session["findings"]
        if item["check"] != NOT_EXPLODED
    )
    assert "Exception: EX-001" in (run_dir / REPORT_FILE_NAME).read_text(encoding="utf-8")


def test_it_reports_the_files_it_wrote(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    body = payload(
        accept_standards(run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON}), "--json")
    )

    assert Path(body["run_dir"]) == run_dir.resolve()
    assert Path(body["package_dir"]) == package_dir.resolve()
    assert Path(body["report_file"]) == run_dir.resolve() / REPORT_FILE_NAME
    assert body["accepted_by"] == "engineer"
    assert [item["id"] for item in body["exceptions"]] == ["EX-001"]
    assert body["rules"][0]["reason"] == REASON


def test_the_human_output_prints_one_line_per_check_id(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    result = accept_standards(run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON}))

    assert result.exit_code == 0, stderr(result)
    assert f"{NOT_EXPLODED}: accepted 1" in result.stdout
    assert str(package_dir / EXCEPTIONS_FILE_NAME) in result.stdout


def test_it_defaults_the_acceptor_to_the_current_user(
    run_dir: Path,
    package_dir: Path,
    waiver_file: Callable[[object], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USERNAME", "sw-engineer")
    file = waiver_file({NOT_EXPLODED: REASON})

    body = payload(
        invoke(
            "exceptions",
            "accept-standards",
            str(run_dir),
            "--package",
            str(package_dir),
            "--file",
            str(file),
            "--json",
        )
    )

    assert body["accepted_by"] == "sw-engineer"


# --- 2. the five status words ---------------------------------------------------------------


def test_an_error_check_with_no_finding_is_unused(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({NOT_EXPLODED: REASON, ONE_FIXED: "no fixed component by design"})

    body = payload(accept_standards(run_dir, package_dir, file, "--json"))

    assert statuses(body) == {NOT_EXPLODED: "accepted 1", ONE_FIXED: "unused"}


def test_a_check_an_active_exception_already_covers_is_unused(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """One condition keeps one record: a second import writes no second exception."""
    file = waiver_file({NOT_EXPLODED: REASON})
    accept_standards(run_dir, package_dir, file)

    body = payload(accept_standards(run_dir, package_dir, file, "--json"))

    assert statuses(body) == {NOT_EXPLODED: "unused"}
    assert len(stored_exceptions(package_dir)) == 1


def test_a_warning_check_is_invalid_and_writes_nothing(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({NOT_EXPLODED: REASON, REVISION_MATCHES: "advisory only"})

    result = accept_standards(run_dir, package_dir, file, "--json")

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert statuses(body) == {
        NOT_EXPLODED: "would accept 1",
        REVISION_MATCHES: "invalid (warning check)",
    }
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_an_unknown_check_id_is_invalid_and_writes_nothing(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({NOT_EXPLODED: REASON, UNKNOWN_CHECK: "typo"})

    result = accept_standards(run_dir, package_dir, file, "--json")

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert statuses(body) == {
        NOT_EXPLODED: "would accept 1",
        UNKNOWN_CHECK: "invalid (unknown check)",
    }
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_an_invalid_id_leaves_the_session_and_the_report_untouched(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    before = (run_dir / SESSION_FILE_NAME).read_bytes()
    report = (run_dir / REPORT_FILE_NAME).read_bytes()
    file = waiver_file({NOT_EXPLODED: REASON, UNKNOWN_CHECK: "typo"})

    accept_standards(run_dir, package_dir, file)

    assert (run_dir / SESSION_FILE_NAME).read_bytes() == before
    assert (run_dir / REPORT_FILE_NAME).read_bytes() == report


def test_the_refusal_names_every_invalid_id_on_stderr(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({REVISION_MATCHES: "advisory", UNKNOWN_CHECK: "typo"})

    result = accept_standards(run_dir, package_dir, file)

    assert result.exit_code == 1
    message = stderr(result)
    assert REVISION_MATCHES in message
    assert UNKNOWN_CHECK in message
    assert "nothing was written" in message


def test_an_all_valid_file_writes_and_exits_0(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({NOT_EXPLODED: REASON, MATERIAL_ASSIGNED: REASON})

    result = accept_standards(run_dir, package_dir, file)

    assert result.exit_code == 0, stderr(result)
    assert len(stored_exceptions(package_dir)) == 3


def test_a_waiver_with_no_reason_is_refused(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """An unexplained exception is the blanket exclusion Principle VI does not allow."""
    file = waiver_file({NOT_EXPLODED: "  "})

    result = accept_standards(run_dir, package_dir, file)

    assert result.exit_code == 1
    assert NOT_EXPLODED in stderr(result)
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_the_five_status_words_are_the_contract_s(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """All five in one run: four from a refused import, `accepted <n>` from an applied one."""
    refused = waiver_file(
        {
            NOT_EXPLODED: REASON,
            ONE_FIXED: "none fixed",
            REVISION_MATCHES: "advisory",
            UNKNOWN_CHECK: "typo",
        }
    )
    body = json.loads(accept_standards(run_dir, package_dir, refused, "--json").stdout)
    applied = payload(
        accept_standards(run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON}), "--json")
    )

    assert sorted(statuses(body).values()) == sorted(
        ["would accept 1", "unused", "invalid (warning check)", "invalid (unknown check)"]
    )
    assert statuses(applied) == {NOT_EXPLODED: "accepted 1"}


# --- 3. the family guard --------------------------------------------------------------------


def test_accept_standards_pointed_at_an_rms_run_is_refused_naming_both_families(
    rms_run: tuple[Path, Path], waiver_file: Callable[[object], Path]
) -> None:
    rms_package_dir, rms_run_dir = rms_run
    file = waiver_file({"rms.core.shell_last": REASON})

    result = accept_standards(rms_run_dir, rms_package_dir, file)

    assert result.exit_code == 1
    message = stderr(result)
    assert "rms" in message
    assert "standards" in message
    assert not (rms_package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_accept_rms_pointed_at_a_standards_run_is_refused_naming_both_families(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({NOT_EXPLODED: REASON})

    result = accept_rms(run_dir, package_dir, file)

    assert result.exit_code == 1
    message = stderr(result)
    assert "rms" in message
    assert "standards" in message
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_the_family_comes_from_the_run_s_check_record(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """Not from the folder's name and not from the ids in the file: the record says so."""
    record = json.loads((run_dir / "check.json").read_text(encoding="utf-8"))

    assert record["family"] == STANDARDS_FAMILY.check_file_family
    result = accept_standards(
        run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON})
    )
    assert result.exit_code == 0, stderr(result)


def test_a_run_folder_with_no_check_record_is_the_rms_family(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """A record written before the field existed is a feature 003 model check."""
    (run_dir / "check.json").unlink()

    result = accept_standards(run_dir, package_dir, waiver_file({NOT_EXPLODED: REASON}))

    assert result.exit_code == 1
    assert "rms" in stderr(result)


# --- 4. one body, two names -----------------------------------------------------------------


def test_the_two_commands_share_one_body() -> None:
    """FR-042: generalized over the family, not a second implementation."""
    from swreview import cli

    rms_command = cli.exceptions_accept_rms
    standards_command = cli.exceptions_accept_standards

    assert rms_command.__doc__ != standards_command.__doc__
    assert cli._accept_waiver_file.__module__ == cli.__name__


def test_the_rms_waiver_labels_are_byte_identical_to_today_s() -> None:
    """The labels are facts on the family, read by the same generalized helper."""
    assert waiver_invalidity(RMS_FAMILY, RMS_RULES, "not.a.rule") == "invalid (unknown rule)"
    assert waiver_invalidity(RMS_FAMILY, RMS_RULES, "rms.detail.holes_last") == (
        "invalid (warn rule)"
    )
    assert waiver_invalidity(RMS_FAMILY, RMS_RULES, "rms.assembly.mates_described") == (
        "invalid (data-gap rule)"
    )
    assert waiver_invalidity(RMS_FAMILY, RMS_RULES, "rms.advisory.core_shaping_cuts") == (
        "invalid (out-of-scope rule)"
    )
    assert waiver_invalidity(RMS_FAMILY, RMS_RULES, "rms.core.shell_last") is None


def test_the_standards_waiver_labels_are_the_two_this_family_needs() -> None:
    assert waiver_invalidity(STANDARDS_FAMILY, STANDARDS_RULES, UNKNOWN_CHECK) == (
        "invalid (unknown check)"
    )
    assert waiver_invalidity(STANDARDS_FAMILY, STANDARDS_RULES, REVISION_MATCHES) == (
        "invalid (warning check)"
    )
    assert waiver_invalidity(STANDARDS_FAMILY, STANDARDS_RULES, NOT_EXPLODED) is None
