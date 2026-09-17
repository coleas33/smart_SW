"""Unit tests for `swreview check standards` (T086).

`contracts/cli.md` says what this command is: a thin shell around `run_standards_check`,
the **single** no-language-model evaluation entry point that `POST /checks/standards` also
calls (FR-043), so the verdict a release gate reads on the command line and the verdict an
engineer reads in the Standards tab cannot be two different gradings of the same design.

What these tests pin:

- **the output shape**: findings and coverage in the same human and JSON shapes the other
  `check` commands print, headed by the release verdict, its counts in **every** bucket and
  the unresolved check ids;
- **where it writes**: `session.json`, `report.md` and `check.json` into `--out`, and
  **not one byte** into the package directory (SC-010) - grading a package must not edit it;
- **the seven exit-1 conditions** of `contracts/cli.md`, each naming what was wrong and
  what to do, and **none of them reported as a check result**;
- **exit 0 otherwise**, with violations in the output rather than in the exit code, so a
  continuous-integration job decides for itself what to do with the verdict;
- **the carry-forward**: the newest same-`design_id` `exceptions.json` under the run root,
  which is `--out`'s own parent, and never a run folder this command wrote itself;
- **the four flags it deliberately does not offer**: `--check`, `--scope`, `--fix`,
  `--rebuild`.

Every package here is built by `tests/support/standards.py` and graded against a
**fictional** fixture profile (T002): no company value enters a test (FR-001).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from swreview import cli
from swreview.checks.standards.profile import SETTING_NAME
from swreview.checks.standards.run import CHECK_FILE_NAME, run_standards_check
from swreview.exceptions import EXCEPTIONS_FILE_NAME, fingerprint
from swreview.ir.loader import PACKAGE_FILE_NAME, save_package
from swreview.ir.models import DumpPhase, EvidencePackage
from swreview.report.dispositions import REPORT_FILE_NAME, SESSION_FILE_NAME
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    DocumentSpec,
    DrawingSpec,
    PartSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)
from tests.unit.test_cli import invoke, payload

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE_PATH = FIXTURE_DIR / "profile-a.yaml"

NOT_EXPLODED = "standards.assembly.not_exploded"
"""The one check the package below fails, so the output is small enough to read."""


# --- the packages every test grades --------------------------------------------------------


def package_of(*documents: DocumentSpec) -> EvidencePackage:
    from swreview.checks.standards.profile import load_profile

    return standards_package(documents=list(documents), profile=load_profile(PROFILE_PATH))


def exploded_package() -> EvidencePackage:
    """A root assembly left exploded: exactly one error-severity check fails."""
    return package_of(
        AssemblySpec(
            name="top",
            folder="jobs/mr-400",
            is_exploded=True,
            components=[ComponentSpec(name="plate-1", document="plate")],
        ),
        PartSpec(name="plate", folder="jobs/mr-400"),
    )


def drawing_package() -> EvidencePackage:
    return package_of(
        DrawingSpec(
            name="MR-40012",
            folder="jobs/mr-400",
            active_sheet="Sheet1",
            sheets=[SheetSpec(name="Sheet1", was_active=True, views=[ViewSpec(name="View1")])],
        )
    )


def without_phase(package: EvidencePackage, name: str) -> EvidencePackage:
    """The same package with one phase recorded as never having run."""
    phases = [
        DumpPhase(name=row.name, status="skipped", elapsed_ms=None) if row.name == name else row
        for row in package.extractor.phases
    ]
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"phases": phases})}
    )


def written(tmp_path: Path, package: EvidencePackage, name: str = "package") -> Path:
    directory = tmp_path / name
    save_package(package, directory)
    return directory


def digest(directory: Path) -> dict[str, bytes]:
    """Every file under `directory`, by relative path, with its bytes."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# --- running the command -------------------------------------------------------------------


def run_standards(
    package_dir: Path,
    out_dir: Path,
    *extra: str,
    profile: Path | None = PROFILE_PATH,
) -> Any:
    """`swreview check standards --package <dir> --out <dir> [--profile <yaml>]`."""
    arguments = ["check", "standards", "--package", str(package_dir), "--out", str(out_dir)]
    if profile is not None:
        arguments += ["--profile", str(profile)]
    return invoke(*arguments, *extra)


@pytest.fixture
def graded(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """A written package and the `--out` folder beside it, both under one run root."""
    package_dir = written(tmp_path, exploded_package())
    yield package_dir, tmp_path / "run"


def stderr(result: Any) -> str:
    return result.stdout + getattr(result, "stderr", "")


# --- 1. the output: the verdict, its counts, the findings and the coverage ------------------


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def plain(text: str) -> str:
    """Typer renders help and usage errors through Rich, which under a colour-forcing
    terminal (CI sets one) wraps each dash of an option name in its own escape sequence,
    so `--package` is never a contiguous substring of the raw output. Strip the codes
    before asserting on the words."""
    return ANSI_ESCAPE.sub("", text)

def test_the_human_output_is_headed_by_the_verdict_and_its_counts(
    graded: tuple[Path, Path],
) -> None:
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir)

    assert result.exit_code == 0, stderr(result)
    lines = result.stdout.splitlines()
    assert lines[0] == "verdict: not_ready"
    assert lines[1].startswith("findings: 1 error, 0 warning, 0 waived")
    assert "checked" in lines[2] and "skipped" in lines[2]
    assert "unresolved" in lines[2] and "out of scope" in lines[2]
    assert lines[3].startswith("unresolved checks:")
    assert lines[4].startswith("notes:")


def test_the_human_output_names_the_unresolved_check_ids(tmp_path: Path) -> None:
    """A drawing package leaves checks unresolved, and the headline says which."""
    package_dir = written(tmp_path, drawing_package())

    result = run_standards(package_dir, tmp_path / "run")

    assert result.exit_code == 0, stderr(result)
    line = next(row for row in result.stdout.splitlines() if row.startswith("unresolved checks:"))
    body = payload(run_standards(package_dir, tmp_path / "run-json", "--json"))
    assert body["verdict"]["unresolved_check_ids"]
    for check in body["verdict"]["unresolved_check_ids"]:
        assert check in line


def test_the_human_output_prints_every_finding_as_the_other_check_commands_do(
    graded: tuple[Path, Path],
) -> None:
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir)

    assert f"{NOT_EXPLODED}: demonstrated" in result.stdout
    assert "observed: " in result.stdout
    assert "requirement: " in result.stdout
    assert "recommended action: " in result.stdout


def test_the_human_output_names_the_documents_it_graded(graded: tuple[Path, Path]) -> None:
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir)

    assert "2 document(s) graded" in result.stdout
    assert "assembly" in result.stdout and "part" in result.stdout


def test_the_human_output_names_the_files_it_wrote(graded: tuple[Path, Path]) -> None:
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir)

    assert str(out_dir.resolve() / SESSION_FILE_NAME) in result.stdout
    assert str(out_dir.resolve() / REPORT_FILE_NAME) in result.stdout
    assert str(out_dir.resolve() / CHECK_FILE_NAME) in result.stdout


def test_the_json_output_carries_the_verdict_the_findings_and_the_coverage(
    graded: tuple[Path, Path],
) -> None:
    package_dir, out_dir = graded

    body = payload(run_standards(package_dir, out_dir, "--json"))

    assert Path(body["package"]) == package_dir.resolve()
    assert Path(body["out_dir"]) == out_dir.resolve()
    assert body["verdict"]["state"] == "not_ready"
    assert body["verdict"]["counts"]["error"] == 1
    assert set(body["verdict"]["counts"]) == {
        "error",
        "warning",
        "checked",
        "skipped",
        "unresolved",
        "out_of_scope",
    }
    assert body["verdict"]["waived"] == 0
    assert [finding["check"] for finding in body["findings"]] == [NOT_EXPLODED]
    assert body["coverage"]
    assert body["documents"]


def test_the_json_output_carries_all_sixteen_check_rows(graded: tuple[Path, Path]) -> None:
    """A release gate says "all sixteen were accounted for" from one array (FR-033)."""
    package_dir, out_dir = graded

    body = payload(run_standards(package_dir, out_dir, "--json"))

    assert len(body["checks"]) == 16
    assert all(row["worst_bucket"] is not None for row in body["checks"])


def test_the_json_output_carries_the_profile_identity_and_no_profile_value(
    graded: tuple[Path, Path],
) -> None:
    """FR-034: the identity is what the payload carries, and it is a path and a hash.

    The whole-repository proof that no company value is compiled in anywhere is T001's
    (`test_standards_no_company_values.py`); what is pinned here is the one thing this
    command decides - that the profile reaches its payload as `{path, sha256}` and not as
    the loaded `StandardsProfile`. A value that is also in the *package* (a document's
    vault-relative path, the configuration a part was read in) is evidence about the
    design and is not this field's business.
    """
    package_dir, out_dir = graded

    body = payload(run_standards(package_dir, out_dir, "--json"))

    assert set(body["profile"]) == {"path", "sha256"}
    assert Path(body["profile"]["path"]) == PROFILE_PATH.resolve()
    assert len(body["profile"]["sha256"]) == 64
    assert "profile:" not in json.dumps(body["verdict"])


def test_the_json_output_reports_what_the_carry_forward_did(
    graded: tuple[Path, Path],
) -> None:
    package_dir, out_dir = graded

    body = payload(run_standards(package_dir, out_dir, "--json"))

    assert set(body["exceptions_carried_forward"]) == {"from_run", "count", "reason"}
    assert body["exceptions_carried_forward"]["count"] == 0


# --- 2. what it writes, and what it must not touch -----------------------------------------


def test_it_writes_the_three_run_files_into_out(graded: tuple[Path, Path]) -> None:
    package_dir, out_dir = graded

    run_standards(package_dir, out_dir)

    assert (out_dir / SESSION_FILE_NAME).is_file()
    assert (out_dir / REPORT_FILE_NAME).is_file()
    assert (out_dir / CHECK_FILE_NAME).is_file()


def test_the_report_is_headed_by_the_verdict_and_the_no_rebuild_sentence(
    graded: tuple[Path, Path],
) -> None:
    from swreview.checks.standards.run import NO_REBUILD_SENTENCE

    package_dir, out_dir = graded

    run_standards(package_dir, out_dir)

    report = (out_dir / REPORT_FILE_NAME).read_text(encoding="utf-8")
    assert report.startswith("# Standards Check:")
    assert NO_REBUILD_SENTENCE in report


def test_every_byte_of_the_package_directory_is_unchanged(graded: tuple[Path, Path]) -> None:
    """SC-010: grading a package must not edit it."""
    package_dir, out_dir = graded
    before = digest(package_dir)

    run_standards(package_dir, out_dir)

    assert digest(package_dir) == before


def test_the_check_record_carries_the_standards_family(graded: tuple[Path, Path]) -> None:
    package_dir, out_dir = graded

    run_standards(package_dir, out_dir)

    record = json.loads((out_dir / CHECK_FILE_NAME).read_text(encoding="utf-8"))
    assert record["family"] == "standards"


# --- 3. the one evaluation entry point ------------------------------------------------------


def test_the_command_is_a_shell_around_the_one_entry_point(
    graded: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-043: the command and the route grade through the same call, or they can drift."""
    package_dir, out_dir = graded
    calls: list[tuple[Any, ...]] = []

    def spy(package: Any, profile: Any, out: Any, **kwargs: Any) -> Any:
        calls.append((package, profile, out, kwargs))
        return run_standards_check(package, profile, out, **kwargs)

    monkeypatch.setattr(cli, "run_standards_check", spy)

    result = run_standards(package_dir, out_dir)

    assert result.exit_code == 0, stderr(result)
    [(package, profile, out, kwargs)] = calls
    assert Path(package) == package_dir.resolve()
    assert Path(profile) == PROFILE_PATH
    assert Path(out) == out_dir.resolve()
    assert Path(kwargs["run_root"]) == out_dir.resolve().parent


def test_the_command_grades_exactly_what_the_entry_point_grades(
    graded: tuple[Path, Path], tmp_path: Path
) -> None:
    package_dir, out_dir = graded

    body = payload(run_standards(package_dir, out_dir, "--json"))
    direct = run_standards_check(package_dir, PROFILE_PATH, tmp_path / "direct")

    assert [finding["check"] for finding in body["findings"]] == [
        finding["check"] for finding in direct.findings
    ]
    assert body["verdict"]["state"] == direct.verdict.state
    assert body["documents"] == direct.documents


# --- 4. exit 1: the seven conditions, and nothing else --------------------------------------


def test_a_missing_package_directory_exits_1(tmp_path: Path) -> None:
    result = run_standards(tmp_path / "nowhere", tmp_path / "run")

    assert result.exit_code == 1
    assert "nowhere" in stderr(result)


def test_a_directory_that_is_not_a_package_exits_1(tmp_path: Path) -> None:
    directory = tmp_path / "empty"
    directory.mkdir()

    result = run_standards(directory, tmp_path / "run")

    assert result.exit_code == 1
    assert "error" in stderr(result)


def test_a_package_that_never_ran_the_cutlist_phase_exits_1_naming_the_phase(
    tmp_path: Path,
) -> None:
    package_dir = written(tmp_path, without_phase(exploded_package(), "cutlist"))

    result = run_standards(package_dir, tmp_path / "run")

    assert result.exit_code == 1
    message = stderr(result)
    assert "cutlist" in message
    assert "--profile standards" in message
    assert "standards" in message


def test_a_drawing_package_that_never_ran_the_drawing_phase_exits_1(tmp_path: Path) -> None:
    package_dir = written(tmp_path, without_phase(drawing_package(), "drawing"))

    result = run_standards(package_dir, tmp_path / "run")

    assert result.exit_code == 1
    assert "drawing" in stderr(result)


def test_no_profile_at_all_exits_1_naming_the_setting_and_the_documented_default(
    graded: tuple[Path, Path],
) -> None:
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir, profile=None)

    assert result.exit_code == 1
    message = stderr(result)
    assert SETTING_NAME in message
    assert "standards.yaml" in message
    assert not out_dir.exists()


def test_an_absent_profile_file_exits_1_naming_the_path(graded: tuple[Path, Path]) -> None:
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir, profile=out_dir / "not-here.yaml")

    assert result.exit_code == 1
    assert "not-here.yaml" in stderr(result)
    assert not (out_dir / SESSION_FILE_NAME).exists()


def test_a_schema_invalid_profile_exits_1_naming_the_path_and_the_field(
    graded: tuple[Path, Path], tmp_path: Path
) -> None:
    package_dir, out_dir = graded
    broken = tmp_path / "broken.yaml"
    broken.write_text("version: 1\n", encoding="utf-8")

    result = run_standards(package_dir, out_dir, profile=broken)

    assert result.exit_code == 1
    message = stderr(result)
    assert "broken.yaml" in message
    assert "vault_root" in message


def test_an_out_inside_the_package_directory_exits_1_naming_both_paths(
    graded: tuple[Path, Path],
) -> None:
    package_dir, _ = graded
    inside = package_dir / "run"

    result = run_standards(package_dir, inside)

    assert result.exit_code == 1
    message = stderr(result)
    assert str(inside.resolve()) in message
    assert str(package_dir.resolve()) in message
    assert "must not edit it" in message
    assert not inside.exists()


def test_an_out_equal_to_the_package_directory_exits_1(graded: tuple[Path, Path]) -> None:
    """The pane grades in place; a command line must not, and says why."""
    package_dir, _ = graded
    before = digest(package_dir)

    result = run_standards(package_dir, package_dir)

    assert result.exit_code == 1
    assert digest(package_dir) == before


def test_an_unwritable_out_exits_1(graded: tuple[Path, Path], tmp_path: Path) -> None:
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")
    package_dir, _ = graded

    result = run_standards(package_dir, blocked / "run")

    assert result.exit_code == 1
    assert "error" in stderr(result)


def test_an_unparseable_carry_forward_candidate_exits_1(tmp_path: Path) -> None:
    package_dir = written(tmp_path, exploded_package())
    earlier = written(tmp_path, exploded_package(), name="earlier")
    (earlier / EXCEPTIONS_FILE_NAME).write_text("{not json", encoding="utf-8")

    result = run_standards(package_dir, tmp_path / "run")

    assert result.exit_code == 1
    message = stderr(result)
    assert EXCEPTIONS_FILE_NAME in message


def test_a_refusal_is_never_reported_as_a_check_result(graded: tuple[Path, Path]) -> None:
    """None of the seven is a finding: stdout carries no verdict at all."""
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir, profile=None)

    assert "verdict:" not in result.stdout


# --- 5. exit 0: violations are output, not an exit code -------------------------------------


def test_a_design_with_violations_exits_0(graded: tuple[Path, Path]) -> None:
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir)

    assert result.exit_code == 0
    assert "verdict: not_ready" in result.stdout


def test_a_design_with_unresolved_coverage_exits_0(tmp_path: Path) -> None:
    package_dir = written(tmp_path, drawing_package())

    result = run_standards(package_dir, tmp_path / "run")

    assert result.exit_code == 0, stderr(result)


# --- 6. the carry-forward ------------------------------------------------------------------


def store_body(package: EvidencePackage, component_id: str = "cmp:0001") -> str:
    """An accepted exception on the root assembly of `package`, as `accept` writes one.

    The `standards` fingerprint kind and the `document_id` that names what it was accepted
    on: a standards waiver waives a check **on a document** (FR-041), so that is what the
    store is asked with and what a carried-forward record has to carry to be found.
    """
    return json.dumps(
        {
            "exceptions": [
                {
                    "id": "EX-001",
                    "check": NOT_EXPLODED,
                    "component_persist_refs": [
                        next(item.persist_ref for item in package.components)
                    ],
                    "persist_ref_scopes": [
                        next(item.persist_ref_scope for item in package.components)
                    ],
                    "configuration": package.design.active_configuration,
                    "geometry_fingerprint": fingerprint(
                        package, [component_id], "standards", document_id="doc:1"
                    ),
                    "fingerprint_kind": "standards",
                    "document_id": "doc:1",
                    "accepted_by": "a.engineer",
                    "accepted_at": "2026-09-17T10:00:00Z",
                    "note": "accepted for this release",
                    "status": "active",
                }
            ]
        },
        indent=2,
    )


def test_the_newest_same_design_store_under_the_run_root_is_carried_forward(
    tmp_path: Path,
) -> None:
    package = exploded_package()
    package_dir = written(tmp_path, package)
    earlier = written(tmp_path, package, name="earlier")
    (earlier / EXCEPTIONS_FILE_NAME).write_text(store_body(package), encoding="utf-8")

    body = payload(run_standards(package_dir, tmp_path / "run", "--json"))

    assert body["exceptions_carried_forward"]["from_run"] == "earlier"
    assert body["exceptions_carried_forward"]["count"] == 1
    assert (tmp_path / "run" / EXCEPTIONS_FILE_NAME).read_bytes() == (
        earlier / EXCEPTIONS_FILE_NAME
    ).read_bytes()
    assert body["verdict"]["waived"] == 1


def test_a_run_folder_this_command_wrote_is_never_a_carry_forward_candidate(
    tmp_path: Path,
) -> None:
    """It holds `session.json`, `report.md` and `check.json` and no `package.json`."""
    package = exploded_package()
    package_dir = written(tmp_path, package)
    first = tmp_path / "run-1"
    run_standards(package_dir, first)
    (first / EXCEPTIONS_FILE_NAME).write_text(store_body(package), encoding="utf-8")

    body = payload(run_standards(package_dir, tmp_path / "run-2", "--json"))

    assert not (first / PACKAGE_FILE_NAME).exists()
    assert body["exceptions_carried_forward"]["from_run"] is None
    assert body["exceptions_carried_forward"]["count"] == 0


def test_a_store_from_another_design_is_not_carried_forward(tmp_path: Path) -> None:
    package = exploded_package()
    package_dir = written(tmp_path, package)
    other = package.model_copy(
        update={"design": package.design.model_copy(update={"design_id": "dsn:other"})}
    )
    earlier = written(tmp_path, other, name="earlier")
    (earlier / EXCEPTIONS_FILE_NAME).write_text(store_body(other), encoding="utf-8")

    body = payload(run_standards(package_dir, tmp_path / "run", "--json"))

    assert body["exceptions_carried_forward"]["from_run"] is None


# --- 7. what this command deliberately does not offer --------------------------------------


@pytest.mark.parametrize("flag", ["--check", "--scope", "--fix", "--rebuild"])
def test_the_command_offers_no_filter_and_no_repair_flag(
    graded: tuple[Path, Path], flag: str
) -> None:
    """`contracts/cli.md`: all sixteen run on every run, and this feature never repairs."""
    package_dir, out_dir = graded

    result = run_standards(package_dir, out_dir, flag, "anything")

    assert result.exit_code != 0
    assert flag in plain(stderr(result))


def test_the_help_names_the_three_options_it_does_offer(graded: tuple[Path, Path]) -> None:
    result = invoke("check", "standards", "--help")

    assert result.exit_code == 0
    text = plain(result.stdout)
    assert "--package" in text
    assert "--out" in text
    assert "--profile" in text
    assert "--json" in text
