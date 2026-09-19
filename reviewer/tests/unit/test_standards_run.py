"""The one no-language-model evaluation entry point for the standards checks (T051).

`checks/standards/run.py::run_standards_check` is what `swreview check standards` and
`POST /checks/standards` both call (FR-043), so what is pinned here is everything that is
true of a standards check however it was started:

- **the profile is loaded and validated in one place** (FR-002). A missing, unreadable or
  schema-invalid profile refuses the run with its own named error, and **writes no run
  folder**: a refusal that left a folder behind would read as a check that ran;
- **a package without the evidence is refused by its phase rows, not by its profile name**
  (FR-043): the `cutlist` row, and the `drawing` row for a drawing root. Any package that
  actually ran them is accepted, whatever profile produced it, and the refusal names the
  profile that produced this one and the phases that are missing - because sixteen
  unresolved checks read as a broken model rather than as a missing extract;
- **it dispatches through the tool registry with a session sink**, so every finding's
  `tool_result_ids` names an investigation step that exists in the `session.json` it was
  written beside;
- **it writes the run folder and not one byte into the package** (SC-010): `session.json`,
  `report.md` and `check.json` go into `out_dir`, headed by the verdict and the no-rebuild
  sentence, and the package directory is read and never written;
- **it records what the session does not** - the documents and their kinds, the profile
  **identity only**, the verdict, the subjects, what the carry-forward did and which checks
  this build does not run - so `read_standards_check` is a read and evaluates nothing;
- **it carries accepted exceptions forward** (FR-041), in all four cases of the matrix;
- **it constructs no provider, reads no key and makes no network call** (FR-045), asserted
  by making `agent.providers`' adapter lookup raise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import providers
from swreview.checks.standards.profile import ProfileInvalid, ProfileUnreadable
from swreview.checks.standards.registry import RULES
from swreview.checks.standards.run import (
    CHECK_FILE_NAME,
    NO_REBUILD_SENTENCE,
    MissingStandardsPhasesError,
    StandardsCheckRun,
    StandardsRunError,
    UngradableRootError,
    UnreadableExceptionsError,
    read_standards_check,
    run_standards_check,
)
from swreview.exceptions import EXCEPTIONS_FILE_NAME, fingerprint
from swreview.ir.loader import PACKAGE_FILE_NAME, save_package
from swreview.ir.models import DumpPhase, EvidencePackage
from swreview.report.attention_record import ATTENTION_FILE_NAME
from swreview.report.dispositions import REPORT_FILE_NAME, SESSION_FILE_NAME
from swreview.report.session import load_session
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

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE_PATH = FIXTURE_DIR / "profile-a.yaml"
OTHER_PROFILE_PATH = FIXTURE_DIR / "profile-b.yaml"

NOT_EXPLODED = "standards.assembly.not_exploded"


# --- the packages every test grades --------------------------------------------------------


def package_of(*documents: DocumentSpec) -> EvidencePackage:
    from swreview.checks.standards.profile import load_profile

    return standards_package(documents=list(documents), profile=load_profile(PROFILE_PATH))


def exploded_package() -> EvidencePackage:
    """A root assembly left exploded, so exactly one check fails."""
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
        DumpPhase(name=row.name, status="skipped", elapsed_ms=None)
        if row.name == name
        else row
        for row in package.extractor.phases
    ]
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"phases": phases})}
    )


def as_profile(package: EvidencePackage, profile: str) -> EvidencePackage:
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"profile": profile})}
    )


def written(tmp_path: Path, package: EvidencePackage, name: str = "package") -> Path:
    directory = tmp_path / name
    save_package(package, directory)
    return directory


def check(
    tmp_path: Path,
    package: EvidencePackage | None = None,
    *,
    out: str = "run",
    profile_path: Path = PROFILE_PATH,
    run_root: Path | None = None,
) -> StandardsCheckRun:
    directory = written(tmp_path, package if package is not None else exploded_package())
    return run_standards_check(
        directory, profile_path, tmp_path / out, run_root=run_root
    )


def record_of(run: StandardsCheckRun) -> dict[str, Any]:
    return dict(json.loads(run.check_file.read_text(encoding="utf-8")))


# --- 1. the profile (FR-002) ---------------------------------------------------------------


def test_a_missing_profile_refuses_the_run_naming_the_path_and_the_setting(
    tmp_path: Path,
) -> None:
    directory = written(tmp_path, exploded_package())
    missing = tmp_path / "nowhere.yaml"

    with pytest.raises(ProfileUnreadable) as raised:
        run_standards_check(directory, missing, tmp_path / "run")

    assert str(missing) in str(raised.value)
    assert "StandardsProfilePath" in str(raised.value)
    assert not (tmp_path / "run").exists()


def test_a_schema_invalid_profile_refuses_the_run_and_writes_no_folder(
    tmp_path: Path,
) -> None:
    directory = written(tmp_path, exploded_package())
    broken = tmp_path / "broken.yaml"
    broken.write_text("version: 1\nvault_root: 3\n", encoding="utf-8")

    with pytest.raises(ProfileInvalid):
        run_standards_check(directory, broken, tmp_path / "run")

    assert not (tmp_path / "run").exists()


def test_the_profile_is_read_once_and_only_its_identity_leaves_the_run(
    tmp_path: Path,
) -> None:
    run = check(tmp_path)

    assert run.profile.path == str(PROFILE_PATH)
    assert len(run.profile.sha256) == 64
    record = record_of(run)
    assert record["profile"] == {"path": str(PROFILE_PATH), "sha256": run.profile.sha256}
    body = run.check_file.read_text(encoding="utf-8") + run.report_file.read_text(
        encoding="utf-8"
    )
    body += run.session_file.read_text(encoding="utf-8")
    # The export-control phrase, the part-number pattern and the data-card property names
    # are profile *values*: a document path is the package's own evidence and is not one.
    assert "MERIDIAN-EMBARGO" not in body
    assert "MR-#####" not in body
    assert "Plating Spec" not in body


# --- 2. the phase rows (FR-043) ------------------------------------------------------------


def test_a_package_whose_cutlist_phase_never_ran_is_refused_naming_it(tmp_path: Path) -> None:
    directory = written(tmp_path, without_phase(exploded_package(), "cutlist"))

    with pytest.raises(MissingStandardsPhasesError) as raised:
        run_standards_check(directory, PROFILE_PATH, tmp_path / "run")

    message = str(raised.value)
    assert "cutlist" in message
    assert "standards" in message
    assert "--profile standards" in message
    assert not (tmp_path / "run").exists()


def test_a_drawing_package_whose_drawing_phase_never_ran_is_refused_naming_it(
    tmp_path: Path,
) -> None:
    directory = written(tmp_path, without_phase(drawing_package(), "drawing"))

    with pytest.raises(MissingStandardsPhasesError) as raised:
        run_standards_check(directory, PROFILE_PATH, tmp_path / "run")

    assert "drawing" in str(raised.value)


def test_a_model_package_is_not_asked_for_the_drawing_phase(tmp_path: Path) -> None:
    """A standards dump of a part or an assembly records `drawing` as skipped by design."""
    package = exploded_package()
    assert any(
        row.name == "drawing" and row.status == "skipped" for row in package.extractor.phases
    )

    assert check(tmp_path, package).documents


def test_any_package_that_ran_the_phases_is_accepted_whatever_profile_produced_it(
    tmp_path: Path,
) -> None:
    run = check(tmp_path, as_profile(exploded_package(), "full"))

    assert [finding["check"] for finding in run.findings] == [NOT_EXPLODED]


def test_a_root_the_package_records_no_path_for_refuses_the_run(tmp_path: Path) -> None:
    package = exploded_package()
    documents = [
        row.model_copy(update={"path": ""})
        if row.document_id == package.design.root_assembly_document_id
        else row
        for row in package.documents
    ]
    directory = written(tmp_path, package.model_copy(update={"documents": documents}))

    with pytest.raises(UngradableRootError):
        run_standards_check(directory, PROFILE_PATH, tmp_path / "run")

    assert not (tmp_path / "run").exists()


# --- 3. what one run writes, and where -----------------------------------------------------


def test_it_writes_the_run_folder_and_not_one_byte_into_the_package(tmp_path: Path) -> None:
    directory = written(tmp_path, exploded_package())
    before = {
        path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()
    }

    run = run_standards_check(directory, PROFILE_PATH, tmp_path / "run")

    after = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    assert after == before
    assert sorted(path.name for path in run.session_file.parent.iterdir()) == sorted(
        [SESSION_FILE_NAME, REPORT_FILE_NAME, CHECK_FILE_NAME, ATTENTION_FILE_NAME]
    )
    assert run.session_file.parent == tmp_path / "run"
    assert PACKAGE_FILE_NAME not in {path.name for path in (tmp_path / "run").iterdir()}


def test_every_finding_cites_a_step_that_exists_in_the_written_session(tmp_path: Path) -> None:
    run = check(tmp_path)

    session = load_session(run.session_file)
    steps = {step.index for step in session.steps}
    assert steps
    assert session.findings
    for finding in session.findings:
        assert finding.tool_result_ids
        assert set(finding.tool_result_ids) <= steps


def test_the_report_header_carries_the_verdict_and_the_no_rebuild_sentence(
    tmp_path: Path,
) -> None:
    run = check(tmp_path)

    report = run.report_file.read_text(encoding="utf-8")
    assert run.verdict.state == "not_ready"
    assert "not_ready" in report.split("# Design Review Report")[0]
    assert NO_REBUILD_SENTENCE in report


def test_the_check_record_carries_what_the_session_does_not(tmp_path: Path) -> None:
    run = check(tmp_path)
    record = record_of(run)

    assert record["family"] == "standards"
    assert record["session_id"] == str(run.session.session_id)
    assert record["documents"] == run.documents
    assert record["document_kinds"] == {"doc:1": "assembly", "doc:2": "part"}
    assert record["verdict"]["state"] == "not_ready"
    assert record["verdict"]["counts"]["error"] == 1
    assert set(record["subjects"]) == {finding["id"] for finding in run.findings}
    assert record["exceptions_carried_forward"]["from_run"] is None
    assert record["unavailable_checks"] == run.unavailable_checks == []


def test_the_result_lists_all_sixteen_checks_with_a_worst_bucket(tmp_path: Path) -> None:
    run = check(tmp_path)

    assert [row["check"] for row in run.checks] == list(RULES)
    assert all(row["worst_bucket"] is not None for row in run.checks)
    assert "standards.release" not in {row["check"] for row in run.checks}


def test_no_provider_is_constructed_on_any_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two factories `agent.providers` actually has, patched unconditionally.

    `monkeypatch.setattr` without `raising=False` is the guard on the guard: if either
    name is renamed the test fails loudly rather than patching nothing and passing
    whatever the run does. The names are feature 003's - `tests/unit/test_rms_run.py`
    patches exactly these two (FR-045, SC-010).
    """

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a standards check constructs no provider (FR-045)")

    monkeypatch.setattr(providers, "get", refuse)
    monkeypatch.setattr(providers, "call_tool", refuse)

    run = check(tmp_path)

    assert run.findings
    assert run.session.steps


# --- 4. the carry-forward matrix (FR-041) --------------------------------------------------


def earlier_run(tmp_path: Path, package: EvidencePackage, name: str, body: str) -> Path:
    """A sibling run folder that is its own package, as a pane's check folder is."""
    directory = written(tmp_path, package, name=name)
    (directory / EXCEPTIONS_FILE_NAME).write_text(body, encoding="utf-8")
    return directory


def store_body(check_id: str = NOT_EXPLODED) -> str:
    """An accepted exception bound to the root assembly instance of `exploded_package`.

    The fingerprint is computed rather than typed, because a fingerprint that does not
    match is `needs_review` by design - the finding stands and says so - and the case this
    body exists for is the one where the acceptance still holds.

    The record is the one `ExceptionStore.accept` writes for a `standards.*` check (T085):
    the `standards` fingerprint kind, hashing the **document** it was accepted on, with
    `document_id` naming it. A standards waiver waives a check on a document, so the
    lookup asks with that document and a record that carried another kind would neither be
    written by any command nor found by any run (FR-041).
    """
    return json.dumps(
        {
            "exceptions": [
                {
                    "id": "EX-001",
                    "check": check_id,
                    "component_persist_refs": ["Y21wOjAwMDE="],
                    "persist_ref_scopes": ["doc:1"],
                    "configuration": "Default",
                    "geometry_fingerprint": fingerprint(
                        exploded_package(), ["cmp:0001"], "standards", document_id="doc:1"
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


def test_the_newest_same_design_store_is_copied_in_byte_identically(tmp_path: Path) -> None:
    body = store_body()
    earlier = earlier_run(tmp_path, exploded_package(), "earlier", body)

    run = check(tmp_path, run_root=tmp_path)

    carried = run.session_file.parent / EXCEPTIONS_FILE_NAME
    assert carried.read_bytes() == (earlier / EXCEPTIONS_FILE_NAME).read_bytes()
    assert run.exceptions_carried_forward.from_run == "earlier"
    assert run.exceptions_carried_forward.count == 1


def test_a_store_carried_forward_is_graded_against_before_the_checks_run(
    tmp_path: Path,
) -> None:
    earlier_run(tmp_path, exploded_package(), "earlier", store_body())

    run = check(tmp_path, run_root=tmp_path)

    assert run.verdict.waived == 1
    assert run.verdict.counts.error == 0


def test_a_store_from_another_design_is_not_carried_forward(tmp_path: Path) -> None:
    other = exploded_package().model_copy(
        update={
            "design": exploded_package().design.model_copy(update={"design_id": "dsn:other"})
        }
    )
    earlier_run(tmp_path, other, "earlier", store_body())

    run = check(tmp_path, run_root=tmp_path)

    assert run.exceptions_carried_forward.from_run is None
    assert not (run.session_file.parent / EXCEPTIONS_FILE_NAME).exists()


def test_no_candidate_at_all_is_reported_and_is_not_an_error(tmp_path: Path) -> None:
    run = check(tmp_path, run_root=tmp_path)

    assert run.exceptions_carried_forward.from_run is None
    assert run.exceptions_carried_forward.count == 0
    assert run.exceptions_carried_forward.reason


def test_a_candidate_that_cannot_be_parsed_refuses_the_run(tmp_path: Path) -> None:
    earlier_run(tmp_path, exploded_package(), "earlier", "{not json")
    directory = written(tmp_path, exploded_package())

    with pytest.raises(UnreadableExceptionsError):
        run_standards_check(directory, PROFILE_PATH, tmp_path / "run", run_root=tmp_path)


# --- 5. reading a run folder back ----------------------------------------------------------


def test_reading_a_check_back_evaluates_nothing(tmp_path: Path) -> None:
    run = check(tmp_path)
    before = {
        path.name: path.read_bytes() for path in run.session_file.parent.iterdir()
    }

    read = read_standards_check(run.session_file.parent)

    assert {
        path.name: path.read_bytes() for path in run.session_file.parent.iterdir()
    } == before
    assert read.session.session_id == run.session.session_id
    assert read.documents == run.documents
    assert read.document_kinds == run.document_kinds
    assert read.profile == run.profile
    assert read.verdict == run.verdict
    assert read.subjects == run.subjects
    assert [finding["check"] for finding in read.findings] == [
        finding["check"] for finding in run.findings
    ]
    assert read.checks == run.checks
    assert read.unavailable_checks == run.unavailable_checks


def test_reading_a_folder_that_holds_no_check_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StandardsRunError):
        read_standards_check(written(tmp_path, exploded_package()))


def test_reading_an_rms_folder_as_a_standards_check_is_refused_naming_both(
    tmp_path: Path,
) -> None:
    run = check(tmp_path)
    record = record_of(run)
    record["family"] = "rms"
    run.check_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(StandardsRunError) as raised:
        read_standards_check(run.session_file.parent)

    assert "rms" in str(raised.value)
    assert "standards" in str(raised.value)
