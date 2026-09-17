"""Unit tests for `swreview exceptions accept-rms` (T044).

The checker's own waiver file is flat - `{ "<rule_id>": "<reason>" }` - and a flat file is
exactly what the constitution (Principle VI) does not let this reviewer keep: a rule id is
not a condition, and "rms.core.shell_last: legacy part" would silence that rule on every
document forever. So the file is an *import*, never a store: `accept-rms` reads it against
one `check rms` run and turns each listed `fail` rule into one `ReviewException` per
demonstrated finding of that rule, bound to that finding's component instances, its
configuration and a `feature_tree` fingerprint, with the reason as the note.

What these tests pin, from `contracts/cli.md` and `data-model.md` section 3:

- the four per-id statuses, printed and carried in `--json`: `accepted <n>`,
  `would accept <n>`, `unused`, and invalid (unknown, or a rule that is not `fail`);
- only `demonstrated` findings of `fail` rules are accepted, so a `warn` rule, a rule that
  went unresolved, and a finding an exception already waives all come back untouched;
- any invalid id makes the run exit 1 and write *nothing* - no `exceptions.json`, no
  `exception_id` on any finding, no re-rendered report - because a half-applied import is
  worse than a refused one;
- what is written is what `exceptions accept` writes: the store, the session and the
  report, through the same helpers.

The package under test is the rms-part golden fixture, which seeds one violation of every
reachable part rule, and the run directory is the session `swreview check rms` builds over
it (`rms_run` below).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.runner import SESSION_FILE_NAME
from swreview.checks.rms.run import RmsScope, run_rms_check
from swreview.exceptions import EXCEPTIONS_FILE_NAME
from swreview.report.dispositions import REPORT_FILE_NAME
from tests.unit.test_cli import invoke, payload

RMS_PART_FIXTURE = Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "rms-part"
RMS_EXCEPTIONS_FIXTURE = (
    Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "rms-exceptions"
)

SHELL_LAST = "rms.core.shell_last"
"""A `fail` rule the fixture demonstrates once."""

REFS_DIRECTION = "rms.refs.direction"
"""A second `fail` rule the fixture demonstrates once."""

GLOBAL_VARIABLES = "rms.params.global_variables_present"
"""A `fail` rule that reports no finding in this run: it is equation-scope and the run
under test grades the part scope, so a waiver for it is unused rather than invalid.
(`rms.detail.individually_suppressible` held this role until T057 gave the fixture a
suppress-test run, and with it a finding.)"""

HOLES_LAST = "rms.detail.holes_last"
"""A `warn` rule: never waivable (`contracts/rules.md`, "Waivable rules")."""

MATES_DESCRIBED = "rms.assembly.mates_described"
"""A rule whose data is not extracted: coverage, never a finding, never waivable."""

CORE_SHAPING_CUTS = "rms.advisory.core_shaping_cuts"
"""A rule this version has decided not to decide: out of scope, never waivable."""

ONLY_FILLETS = "rms.quarantine.only_fillets_and_chamfers"
"""The rule the fixture's own `exceptions.json` already waives."""

CHAMFERS_BEFORE_FILLETS = "rms.quarantine.chamfers_before_fillets"
"""The rule the rms-exceptions fixture's `EX-002` was accepted for against an earlier
revision of the part: `refresh` flags it `needs_review`, so the finding stands and the
import has to re-accept that exception rather than write a second one for the condition."""

REASON = "legacy bracket; scheduled for the next revision"


def rms_run(package_dir: Path, run_dir: Path) -> Path:
    """The run directory `swreview check rms --package <pkg> --out <run_dir> --scope part`
    leaves, built through `run_rms_check` - the entry point the command itself calls.

    Not a second evaluation assembled here: a session no command produces is not the
    session `accept-rms` is read against in the field. `--out` is what makes it the same
    call, and it is also why every package these fixtures copy is left as it was copied.
    """
    run_rms_check(package_dir, out_dir=run_dir, scope=RmsScope.part)
    return run_dir


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    """The rms-part golden package with no waivers yet, copied out of the fixture tree."""
    directory = tmp_path / "package"
    shutil.copytree(RMS_PART_FIXTURE, directory)
    (directory / EXCEPTIONS_FILE_NAME).unlink()
    return directory


@pytest.fixture
def run_dir(package_dir: Path, tmp_path: Path) -> Path:
    return rms_run(package_dir, tmp_path / "run")


@pytest.fixture
def waived_package_dir(tmp_path: Path) -> Path:
    """The same package with the fixture's `exceptions.json`: one active waiver."""
    directory = tmp_path / "waived-package"
    shutil.copytree(RMS_PART_FIXTURE, directory)
    return directory


@pytest.fixture
def waived_run_dir(waived_package_dir: Path, tmp_path: Path) -> Path:
    return rms_run(waived_package_dir, tmp_path / "waived-run")


@pytest.fixture
def stale_package_dir(tmp_path: Path) -> Path:
    """The rms-exceptions golden package: one `active` waiver and one the tree outgrew.

    `EX-002` was accepted against an earlier revision of `cover`, so `refresh` flags it
    `needs_review` and its finding comes back `demonstrated` carrying the re-review marker
    - the state quickstart Scenario 5 is written over.
    """
    directory = tmp_path / "stale-package"
    shutil.copytree(RMS_EXCEPTIONS_FIXTURE, directory)
    return directory


@pytest.fixture
def stale_run_dir(stale_package_dir: Path, tmp_path: Path) -> Path:
    return rms_run(stale_package_dir, tmp_path / "stale-run")


@pytest.fixture
def two_shell_dir(tmp_path: Path) -> Path:
    """A package whose two part documents break `rms.core.shell_last`, one finding each.

    The rms-part fixture demonstrates every rule exactly once, so a plural rule - "every
    demonstrated finding of a listed `fail` rule" - cannot be exercised on it at all: an
    import that accepted only the first finding, or that counted the rule instead of its
    findings, would pass every other test in this file.
    """
    from swreview.ir.loader import save_package
    from tests.support.features import AssemblySpec, PartSpec, feature, folder, rms_package

    def shell_not_last(document_id: str, name: str) -> PartSpec:
        return PartSpec(
            document_id=document_id,
            name=name,
            features=(
                folder(
                    "3-Core",
                    feature("Boss-Extrude1", "Extrusion"),
                    feature("Shell1", "Shell"),
                    feature("Boss-Extrude2", "Extrusion"),
                ),
                folder("4-Detail", feature("Hole1", "HoleWzd")),
            ),
        )

    package = rms_package(
        parts=[shell_not_last("doc:2", "housing"), shell_not_last("doc:3", "cover")],
        assembly=AssemblySpec(document_id="doc:1", name="two-shell-assy"),
    )
    directory = tmp_path / "two-shell"
    save_package(package, directory)
    return directory


def persist_refs(package_dir: Path) -> dict[str, str]:
    """Each component instance id in the package, and the persist reference it binds by."""
    document = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
    return {item["id"]: item["persist_ref"] for item in document["components"]}


@pytest.fixture
def waiver_file(tmp_path: Path) -> Callable[[object], Path]:
    """Write the checker's flat file and return its path."""

    def write(waivers: object) -> Path:
        path = tmp_path / "rms_exceptions.json"
        path.write_text(json.dumps(waivers, indent=2), encoding="utf-8")
        return path

    return write


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


def session_of(run_dir: Path) -> Any:
    return json.loads((run_dir / SESSION_FILE_NAME).read_text(encoding="utf-8"))


def stored_exceptions(package_dir: Path) -> list[Any]:
    path = package_dir / EXCEPTIONS_FILE_NAME
    return json.loads(path.read_text(encoding="utf-8"))["exceptions"]


# --- what an accepted id writes ---------------------------------------------------


def test_accept_rms_writes_one_exception_per_demonstrated_finding(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    body = payload(accept_rms(run_dir, package_dir, waiver_file({SHELL_LAST: REASON}), "--json"))

    assert statuses(body) == {SHELL_LAST: "accepted 1"}
    stored = stored_exceptions(package_dir)
    assert [item["id"] for item in stored] == ["EX-001"]
    assert stored[0]["check"] == SHELL_LAST
    assert stored[0]["note"] == REASON
    assert stored[0]["accepted_by"] == "engineer"
    assert stored[0]["fingerprint_kind"] == "feature_tree"
    assert stored[0]["status"] == "active"
    assert stored[0]["component_persist_refs"]


def test_accept_rms_records_the_exception_on_the_finding_and_re_renders_the_report(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    accept_rms(run_dir, package_dir, waiver_file({SHELL_LAST: REASON}))

    session = session_of(run_dir)
    accepted = [item for item in session["findings"] if item["check"] == SHELL_LAST]
    assert [item["exception_id"] for item in accepted] == ["EX-001"]
    assert all(
        item["exception_id"] is None
        for item in session["findings"]
        if item["check"] != SHELL_LAST
    )
    assert "Exception: EX-001" in (run_dir / REPORT_FILE_NAME).read_text(encoding="utf-8")


def test_accept_rms_reports_the_files_it_wrote(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    body = payload(accept_rms(run_dir, package_dir, waiver_file({SHELL_LAST: REASON}), "--json"))

    assert Path(body["run_dir"]) == run_dir.resolve()
    assert Path(body["package_dir"]) == package_dir.resolve()
    assert Path(body["exceptions_file"]) == package_dir / EXCEPTIONS_FILE_NAME
    assert Path(body["report_file"]) == run_dir.resolve() / REPORT_FILE_NAME
    assert body["accepted_by"] == "engineer"
    assert [item["id"] for item in body["exceptions"]] == ["EX-001"]
    assert body["rules"][0]["exception_ids"] == ["EX-001"]
    assert body["rules"][0]["reason"] == REASON


def test_accept_rms_accepts_every_listed_id_in_file_order(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({SHELL_LAST: REASON, REFS_DIRECTION: "in-context reference, by design"})

    body = payload(accept_rms(run_dir, package_dir, file, "--json"))

    assert [row["rule_id"] for row in body["rules"]] == [SHELL_LAST, REFS_DIRECTION]
    assert statuses(body) == {SHELL_LAST: "accepted 1", REFS_DIRECTION: "accepted 1"}
    stored = stored_exceptions(package_dir)
    assert [(item["id"], item["check"]) for item in stored] == [
        ("EX-001", SHELL_LAST),
        ("EX-002", REFS_DIRECTION),
    ]
    assert stored[1]["note"] == "in-context reference, by design"


def test_accept_rms_human_output_prints_one_line_per_rule_id(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    result = accept_rms(run_dir, package_dir, waiver_file({SHELL_LAST: REASON}))

    assert result.exit_code == 0
    assert f"{SHELL_LAST}: accepted 1" in result.stdout
    assert str(package_dir / EXCEPTIONS_FILE_NAME) in result.stdout


def test_accept_rms_defaults_the_acceptor_to_the_current_user(
    run_dir: Path,
    package_dir: Path,
    waiver_file: Callable[[object], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USERNAME", "sw-engineer")
    file = waiver_file({SHELL_LAST: REASON})

    body = payload(
        invoke(
            "exceptions",
            "accept-rms",
            str(run_dir),
            "--package",
            str(package_dir),
            "--file",
            str(file),
            "--json",
        )
    )

    assert body["accepted_by"] == "sw-engineer"
    assert stored_exceptions(package_dir)[0]["accepted_by"] == "sw-engineer"


# --- unused ------------------------------------------------------------------------


def test_accept_rms_reports_a_fail_rule_with_no_finding_unused(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """`rms.params.global_variables_present` is not graded by this run, so it has none."""
    file = waiver_file({SHELL_LAST: REASON, GLOBAL_VARIABLES: "equations reviewed by hand"})

    body = payload(accept_rms(run_dir, package_dir, file, "--json"))

    assert statuses(body) == {SHELL_LAST: "accepted 1", GLOBAL_VARIABLES: "unused"}
    assert [item["check"] for item in stored_exceptions(package_dir)] == [SHELL_LAST]


def test_accept_rms_reports_an_already_waived_finding_unused(
    waived_run_dir: Path, waived_package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """A waived finding is `checked_within_scope`; only `demonstrated` is accepted, so a
    second exception for the same condition is never written."""
    before = (waived_package_dir / EXCEPTIONS_FILE_NAME).read_bytes()

    file = waiver_file({ONLY_FILLETS: REASON})

    body = payload(accept_rms(waived_run_dir, waived_package_dir, file, "--json"))

    assert statuses(body) == {ONLY_FILLETS: "unused"}
    assert (waived_package_dir / EXCEPTIONS_FILE_NAME).read_bytes() == before


def test_accept_rms_writes_nothing_when_no_listed_rule_has_a_finding(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({GLOBAL_VARIABLES: REASON})
    report = (run_dir / REPORT_FILE_NAME).read_bytes()

    body = payload(accept_rms(run_dir, package_dir, file, "--json"))

    assert statuses(body) == {GLOBAL_VARIABLES: "unused"}
    assert body["report_file"] is None
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()
    # The report in the run folder is the check's own; an import that accepted nothing
    # re-renders nothing over it.
    assert (run_dir / REPORT_FILE_NAME).read_bytes() == report


def test_accept_rms_on_an_empty_waiver_file_accepts_nothing(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    body = payload(accept_rms(run_dir, package_dir, waiver_file({}), "--json"))

    assert body["rules"] == []
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


# --- invalid ids: exit 1, nothing written ------------------------------------------


def test_accept_rms_refuses_a_warn_rule_and_writes_nothing(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({SHELL_LAST: REASON, HOLES_LAST: "holes are last enough"})
    report = (run_dir / REPORT_FILE_NAME).read_bytes()

    result = accept_rms(run_dir, package_dir, file, "--json")

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert statuses(body) == {SHELL_LAST: "would accept 1", HOLES_LAST: "invalid (warn rule)"}
    assert body["exceptions"] == []
    assert body["report_file"] is None
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()
    # The check's own report, untouched: a refused import re-renders nothing over it.
    assert (run_dir / REPORT_FILE_NAME).read_bytes() == report
    assert all(item["exception_id"] is None for item in session_of(run_dir)["findings"])
    assert HOLES_LAST in result.stderr


def test_accept_rms_refuses_an_unknown_rule_id(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({SHELL_LAST: REASON, "rms.core.shel_last": "typo"})

    result = accept_rms(run_dir, package_dir, file, "--json")

    assert result.exit_code == 1
    assert statuses(json.loads(result.stdout)) == {
        SHELL_LAST: "would accept 1",
        "rms.core.shel_last": "invalid (unknown rule)",
    }
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_accept_rms_refuses_a_rule_whose_data_is_not_extracted(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """A data-gap rule reports coverage, never a finding; waiving it would hide the gap."""
    result = accept_rms(run_dir, package_dir, waiver_file({MATES_DESCRIBED: REASON}), "--json")

    assert result.exit_code == 1
    assert statuses(json.loads(result.stdout)) == {MATES_DESCRIBED: "invalid (data-gap rule)"}


def test_accept_rms_refuses_an_out_of_scope_rule(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    result = accept_rms(run_dir, package_dir, waiver_file({CORE_SHAPING_CUTS: REASON}), "--json")

    assert result.exit_code == 1
    assert statuses(json.loads(result.stdout)) == {
        CORE_SHAPING_CUTS: "invalid (out-of-scope rule)"
    }


def test_accept_rms_human_output_of_a_refused_run_names_every_status(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    file = waiver_file({SHELL_LAST: REASON, HOLES_LAST: "holes are last enough"})

    result = accept_rms(run_dir, package_dir, file)

    assert result.exit_code == 1
    assert f"{SHELL_LAST}: would accept 1" in result.stdout
    assert f"{HOLES_LAST}: invalid (warn rule)" in result.stdout
    assert "Traceback" not in result.stderr


# --- a file this command cannot read -----------------------------------------------


def test_accept_rms_refuses_a_waiver_with_no_reason(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """An unexplained waiver is a blanket exclusion by another name (Principle VI)."""
    result = accept_rms(run_dir, package_dir, waiver_file({SHELL_LAST: "  "}), "--json")

    assert result.exit_code == 1
    assert SHELL_LAST in result.stderr
    assert result.stdout == ""
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_accept_rms_refuses_a_file_that_is_not_an_object(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    result = accept_rms(run_dir, package_dir, waiver_file([SHELL_LAST]))

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


def test_accept_rms_on_a_missing_file_exits_1(run_dir: Path, package_dir: Path) -> None:
    result = accept_rms(run_dir, package_dir, package_dir / "nowhere.json")

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert result.stdout == ""


def test_accept_rms_on_a_run_directory_with_no_session_exits_1(
    tmp_path: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    result = accept_rms(tmp_path / "empty", package_dir, waiver_file({SHELL_LAST: REASON}))

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert not (package_dir / EXCEPTIONS_FILE_NAME).exists()


def test_accept_rms_without_a_file_is_a_usage_error(run_dir: Path, package_dir: Path) -> None:
    result = invoke(
        "exceptions", "accept-rms", str(run_dir), "--package", str(package_dir)
    )

    assert result.exit_code == 2


# --- a rule two documents break ----------------------------------------------------


def test_accept_rms_accepts_every_finding_of_a_rule_two_documents_break(
    two_shell_dir: Path, tmp_path: Path, waiver_file: Callable[[object], Path]
) -> None:
    """One exception per finding, each bound to its own finding's component instance."""
    run_dir = rms_run(two_shell_dir, tmp_path / "two-shell-run")

    body = payload(accept_rms(run_dir, two_shell_dir, waiver_file({SHELL_LAST: REASON}), "--json"))

    assert statuses(body) == {SHELL_LAST: "accepted 2"}
    assert body["rules"][0]["exception_ids"] == ["EX-001", "EX-002"]
    session = session_of(run_dir)
    accepted = [item for item in session["findings"] if item["check"] == SHELL_LAST]
    assert [item["exception_id"] for item in accepted] == ["EX-001", "EX-002"]
    assert body["rules"][0]["finding_ids"] == [item["id"] for item in accepted]

    refs = persist_refs(two_shell_dir)
    stored = stored_exceptions(two_shell_dir)
    assert [item["check"] for item in stored] == [SHELL_LAST, SHELL_LAST]
    assert [item["component_persist_refs"] for item in stored] == [
        [refs[component_id] for component_id in finding["component_ids"]]
        for finding in accepted
    ]
    assert stored[0]["component_persist_refs"] != stored[1]["component_persist_refs"]


def test_accept_rms_would_accept_names_every_finding_of_a_plural_rule(
    two_shell_dir: Path, tmp_path: Path, waiver_file: Callable[[object], Path]
) -> None:
    run_dir = rms_run(two_shell_dir, tmp_path / "two-shell-run")
    file = waiver_file({SHELL_LAST: REASON, HOLES_LAST: "holes are last enough"})

    result = accept_rms(run_dir, two_shell_dir, file, "--json")

    assert result.exit_code == 1
    assert statuses(json.loads(result.stdout)) == {
        SHELL_LAST: "would accept 2",
        HOLES_LAST: "invalid (warn rule)",
    }
    assert not (two_shell_dir / EXCEPTIONS_FILE_NAME).exists()


# --- a condition an exception already covers ---------------------------------------


def test_accept_rms_run_twice_writes_no_second_exception(
    run_dir: Path, package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """The import is idempotent: the session it writes back still reads `demonstrated`
    (only a fresh `check rms` reclassifies it), so the second run has to recognise the
    exception it wrote itself rather than accept the same condition twice."""
    file = waiver_file({SHELL_LAST: REASON})
    accept_rms(run_dir, package_dir, file)
    before = (package_dir / EXCEPTIONS_FILE_NAME).read_bytes()

    body = payload(accept_rms(run_dir, package_dir, file, "--json"))

    assert statuses(body) == {SHELL_LAST: "unused"}
    assert body["exceptions"] == []
    assert body["report_file"] is None
    assert (package_dir / EXCEPTIONS_FILE_NAME).read_bytes() == before
    assert [item["id"] for item in stored_exceptions(package_dir)] == ["EX-001"]
    session = session_of(run_dir)
    accepted = [item for item in session["findings"] if item["check"] == SHELL_LAST]
    assert [item["exception_id"] for item in accepted] == ["EX-001"]


def test_accept_rms_re_accepts_the_exception_a_moved_tree_flagged(
    stale_run_dir: Path, stale_package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """A `needs_review` exception is re-bound, not duplicated.

    `ExceptionStore.match` returns the first record bound to the condition, so a second
    exception written beside a flagged one is unreachable for ever: it would silence
    nothing and the finding would keep naming the stale id.
    """
    before = {item["id"]: item for item in stored_exceptions(stale_package_dir)}
    file = waiver_file({CHAMFERS_BEFORE_FILLETS: REASON})

    body = payload(accept_rms(stale_run_dir, stale_package_dir, file, "--json"))

    assert statuses(body) == {CHAMFERS_BEFORE_FILLETS: "accepted 1"}
    assert body["rules"][0]["exception_ids"] == ["EX-002"]
    stored = {item["id"]: item for item in stored_exceptions(stale_package_dir)}
    assert list(stored) == ["EX-001", "EX-002"]
    assert stored["EX-002"]["status"] == "active"
    assert (
        stored["EX-002"]["geometry_fingerprint"] != before["EX-002"]["geometry_fingerprint"]
    )
    assert stored["EX-002"]["note"] == REASON
    assert stored["EX-002"]["accepted_by"] == "engineer"
    assert stored["EX-002"]["accepted_at"] != before["EX-002"]["accepted_at"]
    assert stored["EX-001"] == before["EX-001"]
    session = session_of(stale_run_dir)
    flagged = [
        item for item in session["findings"] if item["check"] == CHAMFERS_BEFORE_FILLETS
    ]
    assert [item["exception_id"] for item in flagged] == ["EX-002"]


def test_check_rms_clears_the_finding_the_import_re_accepted(
    stale_run_dir: Path, stale_package_dir: Path, waiver_file: Callable[[object], Path]
) -> None:
    """The point of the whole command: the next run reports the condition as covered."""
    accept_rms(stale_run_dir, stale_package_dir, waiver_file({CHAMFERS_BEFORE_FILLETS: REASON}))

    body = payload(
        invoke(
            "check",
            "rms",
            "--package",
            str(stale_package_dir),
            "--out",
            str(stale_run_dir),
            "--scope",
            "part",
            "--json",
        )
    )

    graded = [item for item in body["findings"] if item["check"] == CHAMFERS_BEFORE_FILLETS]
    assert [item["status"] for item in graded] == ["checked_within_scope"]
    assert [item["exception_id"] for item in graded] == ["EX-002"]
