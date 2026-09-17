"""The accept flow, end to end (T090).

`contracts/standards-check.md` section 5 says what an acceptance *is* here: the store binds
an exception to the check id, the graded **document**, its component instances, the
configuration and a fingerprint of every input the check read, so an accepted exception
waives a check **on a document** and never a check on one subject.

What this module pins, and why each of them is the failure it exists to catch:

- **an accepted error-severity check renders as checked within scope carrying the exception
  id and the note, and is never hidden** (Principle VI), with the **waived count on the
  headline** - a `ready` verdict reached with waivers has to say so (FR-032);
- **a second, newly seeded subject of the same check on the same document re-opens it**:
  the fingerprint no longer matches, so the finding **stands** and names the exception as
  needing re-review rather than being silenced. That is the whole reason the fingerprint
  hashes the document's inputs, and it is graded over the
  `standards-seeded-second-subject` golden, which differs from `standards-seeded` by
  exactly that one subject;
- **one drawing's waiver never answers for another drawing** (SC-008). Two drawings both
  yield empty bindings, so without `ReviewException.document_id` one would silence the
  other - which is the blanket exclusion the constitution prohibits;
- **an empty note is refused** - an unexplained exception is how waivers rot;
- **the two warning checks offer no Accept control at all**, and a request for one is
  refused naming the severity, because a check that is not waivable must not become
  waivable through the network (FR-041);
- **the acceptance survives the next run by both halves of the rule**: the pane's
  run-folder carry-forward (a missing candidate is reported and is not an error, an
  unreadable one refuses the run) and `exceptions.json` **beside the package** for the
  command line.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.chat.server import create_app
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.registry import STANDARDS_FAMILY
from swreview.checks.standards.run import (
    StandardsCheckRun,
    UnreadableExceptionsError,
    run_standards_check,
)
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore, ReviewException
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.report.dispositions import REPORT_FILE_NAME
from tests.support.standards import (
    AnnotationSpec,
    DimensionSpec,
    DrawingSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)
from tests.unit.test_cli import invoke

FIXTURES = Path(__file__).resolve().parents[1]
PROFILE_PATH = FIXTURES / "fixtures" / "standards" / "profile-a.yaml"
GOLDEN = FIXTURES / "golden" / "fixtures"
SEEDED = GOLDEN / "standards-seeded"
SECOND_SUBJECT = GOLDEN / "standards-seeded-second-subject"

CUT_LIST = "standards.part.cut_list_excluded"
"""The error-severity check both goldens fail on `MR-10001`: once in `standards-seeded`,
twice - two cut-list items, one document - in `standards-seeded-second-subject`."""

DIMENSIONS = "standards.drawing.dimensions_not_overridden"
"""An error-severity **drawing** check: a finding with no component instances at all, which
is why the exception carries a document (FR-041)."""

WARNING_CHECKS: tuple[str, ...] = (
    "standards.drawing.revision_matches",
    "standards.drawing.no_itar_statement",
)
"""The two checks FR-041 makes unacceptable. The control is absent, not disabled."""

REASON = "legacy weldment; deviation accepted at release review"

ORIGIN = "https://swreview.invalid"
TOKEN = "the-per-launch-token"


# --- reading a run -------------------------------------------------------------------------


def finding_for(run: StandardsCheckRun, check: str) -> dict[str, Any]:
    [finding] = [item for item in run.findings if item["check"] == check]
    return finding


def check_row(run: StandardsCheckRun, check: str) -> dict[str, Any]:
    [row] = [item for item in run.checks if item["check"] == check]
    return row


def bucket_of(run: StandardsCheckRun, check: str, bucket: str) -> dict[str, Any] | None:
    return next(
        (item for item in check_row(run, check)["buckets"] if item["bucket"] == bucket), None
    )


def stored(package_dir: Path) -> list[ReviewException]:
    return ExceptionStore(package_dir / EXCEPTIONS_FILE_NAME).load().exceptions


# --- the accept, from the command line ------------------------------------------------------


def waiver_file(directory: Path, waivers: dict[str, str]) -> Path:
    path = directory / "waivers.json"
    path.write_text(json.dumps(waivers, indent=2), encoding="utf-8")
    return path


def accept_standards(run_dir: Path, package_dir: Path, file: Path) -> Any:
    result = invoke(
        "exceptions",
        "accept-standards",
        str(run_dir),
        "--package",
        str(package_dir),
        "--file",
        str(file),
        "--by",
        "release.owner",
    )
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    return result


@pytest.fixture
def accepted(tmp_path: Path) -> tuple[Path, StandardsCheckRun]:
    """The seeded golden with `CUT_LIST` accepted, and the run that graded it afterwards.

    The whole flow and not a hand-written store: what an engineer gets is what
    `accept-standards` writes, and a store assembled here could be one no command produces.
    """
    package_dir = tmp_path / "package"
    shutil.copytree(SEEDED, package_dir)
    run_standards_check(package_dir, PROFILE_PATH, tmp_path / "run-1")
    accept_standards(
        tmp_path / "run-1", package_dir, waiver_file(tmp_path, {CUT_LIST: REASON})
    )
    return package_dir, run_standards_check(package_dir, PROFILE_PATH, tmp_path / "run-2")


# --- 1. an accepted check is checked within scope, never hidden -----------------------------


def test_the_accepted_check_is_checked_within_scope_carrying_its_exception(
    accepted: tuple[Path, StandardsCheckRun],
) -> None:
    _, run = accepted

    finding = finding_for(run, CUT_LIST)

    assert finding["status"] == "checked_within_scope"
    assert finding["exception_id"] == "EX-001"


def test_the_accepted_check_carries_the_exception_id_and_the_note(
    accepted: tuple[Path, StandardsCheckRun],
) -> None:
    """Both, on the finding: an exception id with no reason beside it is a waiver nobody
    can review."""
    _, run = accepted

    finding = finding_for(run, CUT_LIST)

    assert "EX-001" in finding["observed"]
    assert REASON in finding["observed"]
    assert any("EX-001" in limit and REASON in limit for limit in finding["coverage_limits"])


def test_the_accepted_check_is_never_hidden(accepted: tuple[Path, StandardsCheckRun]) -> None:
    """Principle VI: the row stays, and the report still names the check."""
    package_dir, run = accepted

    assert [item["check"] for item in run.findings].count(CUT_LIST) == 1
    report = (run.report_file).read_text(encoding="utf-8")
    assert CUT_LIST in report
    assert "EX-001" in report
    assert package_dir.is_dir()


def test_the_accepted_check_renders_in_the_checked_bucket_naming_the_waiver(
    accepted: tuple[Path, StandardsCheckRun],
) -> None:
    _, run = accepted

    row = check_row(run, CUT_LIST)

    assert row["worst_bucket"] != "failed"
    checked = bucket_of(run, CUT_LIST, "checked")
    assert checked is not None
    assert "EX-001" in checked["reason"]
    assert bucket_of(run, CUT_LIST, "failed") is None


def test_the_waived_count_appears_on_the_headline(
    accepted: tuple[Path, StandardsCheckRun],
) -> None:
    """FR-032: a verdict reached with waivers says so, in the counts and in the notes."""
    _, run = accepted

    assert run.verdict.waived == 1
    assert any("waived" in note for note in run.verdict.notes)
    header = run.report_file.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("- Findings:") and "1 waived" in line for line in header)
    assert any(line.startswith("- Notes:") and "waived" in line for line in header)


def test_a_waived_finding_is_not_an_error(
    accepted: tuple[Path, StandardsCheckRun], tmp_path: Path
) -> None:
    """Which is what makes a `ready` verdict reachable with waivers at all.

    Measured against the same golden graded with no store at all, because the accepted
    package now carries one: an error count read back off the waived run alone could be
    anything and still look right.
    """
    _, run = accepted
    pristine = tmp_path / "pristine"
    shutil.copytree(SEEDED, pristine)
    before = run_standards_check(pristine, PROFILE_PATH, tmp_path / "pristine-run")

    assert run.verdict.counts.error == before.verdict.counts.error - 1
    assert before.verdict.waived == 0


def test_the_exception_is_written_beside_the_package_bound_to_its_document(
    accepted: tuple[Path, StandardsCheckRun],
) -> None:
    package_dir, _ = accepted

    [exception] = stored(package_dir)

    assert exception.check == CUT_LIST
    assert exception.fingerprint_kind == "standards"
    assert exception.document_id is not None
    assert exception.note == REASON
    assert exception.accepted_by == "release.owner"


# --- 2. a second subject re-opens the finding -----------------------------------------------


def test_the_second_subject_golden_differs_by_exactly_one_subject() -> None:
    """The fixture's whole claim, asserted rather than trusted: one more cut-list item on
    the same document, and nothing else about the design moved."""
    seeded = json.loads((SEEDED / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))
    second = json.loads((SECOND_SUBJECT / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))

    assert [key for key in seeded if seeded[key] != second.get(key)] == ["cut_list_items"]
    assert len(second["cut_list_items"]) == len(seeded["cut_list_items"]) + 1
    failing = [
        item for item in second["cut_list_items"] if not item["excluded_from_cut_list"]
    ]
    assert len(failing) == 2
    assert len({item["document_id"] for item in failing}) == 1


@pytest.fixture
def re_review(accepted: tuple[Path, StandardsCheckRun], tmp_path: Path) -> StandardsCheckRun:
    """The second-subject golden graded against the acceptance written for the first."""
    package_dir, _ = accepted
    second = tmp_path / "package-with-second-subject"
    shutil.copytree(SECOND_SUBJECT, second)
    shutil.copy2(package_dir / EXCEPTIONS_FILE_NAME, second / EXCEPTIONS_FILE_NAME)
    return run_standards_check(second, PROFILE_PATH, tmp_path / "run-3")


def test_a_second_subject_makes_the_finding_stand_rather_than_be_silenced(
    re_review: StandardsCheckRun,
) -> None:
    finding = finding_for(re_review, CUT_LIST)

    assert finding["status"] == "demonstrated"
    assert check_row(re_review, CUT_LIST)["worst_bucket"] == "failed"
    assert re_review.verdict.waived == 0


def test_the_standing_finding_names_the_exception_as_needing_re_review(
    re_review: StandardsCheckRun,
) -> None:
    """Naming it is the point: a finding that simply re-appeared would read as new, and the
    engineer would never learn that a waiver they wrote no longer holds."""
    finding = finding_for(re_review, CUT_LIST)

    assert "EX-001" in finding["observed"]
    assert "re-review" in finding["observed"].lower()
    assert "EX-001" in finding["recommended_action"]


def test_the_second_subject_is_named_in_the_finding(re_review: StandardsCheckRun) -> None:
    """Two subjects, one finding (FR-003): the check reports the document, not the item."""
    finding = finding_for(re_review, CUT_LIST)

    assert len(re_review.subjects[finding["id"]]) == 2


def test_the_store_records_the_exception_as_needing_review(
    re_review: StandardsCheckRun,
) -> None:
    """The store the run graded against says so, and the file beside the package does not:
    grading a package never edits it (SC-010), so the flag is what the run computed and the
    engineer's own record is left exactly as they wrote it."""
    store = ExceptionStore(re_review.package_dir / EXCEPTIONS_FILE_NAME).load()

    flagged = store.refresh(load_package(re_review.package_dir).package)

    assert [exception.status for exception in flagged] == ["needs_review"]
    assert [exception.status for exception in stored(re_review.package_dir)] == ["active"]


# --- 3. one drawing's waiver never answers for another (SC-008) -----------------------------


def two_drawings() -> EvidencePackage:
    """A package holding two drawings, each with one overridden dimension.

    The root is graded and the other is not - a standards run grades the drawing that was
    opened - so this package is how an exception can be bound to `doc:2` while `doc:1` is
    the document under grading, which is exactly the confusion SC-008 forbids.
    """
    profile = load_profile(PROFILE_PATH)

    def drawing(name: str) -> DrawingSpec:
        return DrawingSpec(
            name=name,
            folder="jobs/mr-400",
            active_sheet="Sheet1",
            sheets=[
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=[
                        ViewSpec(
                            name="Drawing View1",
                            dimensions=[
                                DimensionSpec(
                                    name="D1@Drawing View1",
                                    is_overridden=True,
                                    value_mm=10.0,
                                    override_mm=99.0,
                                )
                            ],
                            annotations=[AnnotationSpec(name="Note1", is_dangling=False)],
                        )
                    ],
                )
            ],
        )

    return standards_package(
        documents=[drawing("MR-40012"), drawing("MR-40013")], profile=profile
    )


@pytest.fixture
def drawings_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "drawings"
    save_package(two_drawings(), directory)
    return directory


def store_bound_to(directory: Path, document_id: str) -> ExceptionStore:
    """A store holding one `DIMENSIONS` exception bound to `document_id`.

    Written through `ExceptionStore.accept`, so the fingerprint is the one the store
    computes for that document rather than a number typed here.
    """
    package = load_package(directory).package
    store = ExceptionStore(directory / EXCEPTIONS_FILE_NAME)
    store.accept(
        _Accepted(DIMENSIONS, package.design.active_configuration),
        package,
        by="release.owner",
        note=REASON,
        document_id=document_id,
    )
    return store


class _Accepted:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads: a drawing finding
    carries no component instances at all."""

    def __init__(self, check: str, configuration: str) -> None:
        self.check = check
        self.component_ids: list[str] = []
        self.configuration = configuration


def test_a_waiver_on_another_drawing_does_not_silence_this_one(
    drawings_dir: Path, tmp_path: Path
) -> None:
    """The exception names `doc:2`; the run grades `doc:1`. Without `document_id` both
    would carry empty bindings and this waiver would answer for every drawing."""
    store = store_bound_to(drawings_dir, "doc:2")

    run = run_standards_check(
        drawings_dir, PROFILE_PATH, tmp_path / "run", exceptions=store
    )

    finding = finding_for(run, DIMENSIONS)
    assert finding["status"] == "demonstrated"
    assert finding["exception_id"] is None
    assert run.verdict.waived == 0


def test_a_waiver_on_this_drawing_does_silence_it(
    drawings_dir: Path, tmp_path: Path
) -> None:
    """The mirror of the test above, so that the one above is about the *document* and not
    about a fingerprint that happened not to match."""
    store = store_bound_to(drawings_dir, "doc:1")

    run = run_standards_check(
        drawings_dir, PROFILE_PATH, tmp_path / "run", exceptions=store
    )

    finding = finding_for(run, DIMENSIONS)
    assert finding["status"] == "checked_within_scope"
    assert finding["exception_id"] == "EX-001"
    assert run.verdict.waived == 1


def test_a_drawing_waiver_binds_by_document_alone(drawings_dir: Path) -> None:
    [exception] = store_bound_to(drawings_dir, "doc:1").exceptions

    assert exception.component_persist_refs == []
    assert exception.document_id == "doc:1"
    assert exception.fingerprint_kind == "standards"


# --- 4. and 5. the route: an empty note, and the two warning checks -------------------------


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def check_dir(run_root: Path) -> Path:
    """A standards run folder holding the seeded golden's package, as the pane dumps one."""
    directory = run_root / "20260917-101532-mr-90001-standards"
    directory.mkdir(parents=True)
    shutil.copy2(SEEDED / PACKAGE_FILE_NAME, directory / PACKAGE_FILE_NAME)
    return directory


def refuse_provider(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("the accept flow must never construct a provider")


@pytest.fixture
def client(run_root: Path) -> Iterator[TestClient]:
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=refuse_provider,
        list_models=refuse_provider,
    )
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as test_client:
        yield test_client


def graded(client: TestClient, check_dir: Path) -> dict[str, Any]:
    response = client.post(
        "/checks/standards",
        json={"run_dir": str(check_dir), "profile_path": str(PROFILE_PATH)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def row_for(result: dict[str, Any], check: str) -> dict[str, Any]:
    [row] = [item for item in result["findings"] if item["check"] == check]
    return row


def test_an_empty_note_is_refused(client: TestClient, check_dir: Path) -> None:
    """An unexplained exception is the blanket exclusion Principle VI does not allow."""
    finding_id = row_for(graded(client, check_dir), CUT_LIST)["finding"]["id"]

    response = client.post(
        f"/checks/{check_dir.name}/exceptions/{finding_id}", json={"note": "   "}
    )

    assert response.status_code == 400
    assert response.json()["error_class"] == "EmptyNote"
    assert not (check_dir / EXCEPTIONS_FILE_NAME).exists()


@pytest.mark.parametrize("check", WARNING_CHECKS)
def test_a_warning_check_offers_no_accept_control(
    client: TestClient, check_dir: Path, check: str
) -> None:
    """The control is **absent**, not disabled with a tooltip: a disabled control invites a
    request to enable it, and an absent one states the rule."""
    result = graded(client, check_dir)

    assert row_for(result, check)["acceptable"] is False
    assert row_for(result, CUT_LIST)["acceptable"] is True


@pytest.mark.parametrize("check", WARNING_CHECKS)
def test_an_accept_request_for_a_warning_check_is_refused_naming_the_severity(
    client: TestClient, check_dir: Path, check: str
) -> None:
    """A check that is not waivable must not become waivable through the network."""
    finding_id = row_for(graded(client, check_dir), check)["finding"]["id"]

    response = client.post(
        f"/checks/{check_dir.name}/exceptions/{finding_id}", json={"note": REASON}
    )

    assert response.status_code == 409
    error = response.json()
    assert error["error_class"] == "RuleNotAcceptable"
    assert STANDARDS_FAMILY.waiver_labels["warning"] in error["message"]
    assert not (check_dir / EXCEPTIONS_FILE_NAME).exists()


def test_the_route_re_renders_the_accepted_finding_as_checked_within_scope(
    client: TestClient, check_dir: Path
) -> None:
    """The route answers with the re-run's row, which is the only place the waived outcome
    is rendered; a route that edited the row in place would leave `report.md` saying what
    the run said before the waiver existed."""
    finding_id = row_for(graded(client, check_dir), CUT_LIST)["finding"]["id"]

    response = client.post(
        f"/checks/{check_dir.name}/exceptions/{finding_id}", json={"note": REASON}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["finding"]["finding"]["status"] == "checked_within_scope"
    assert body["finding"]["finding"]["exception_id"] == body["exception_id"]
    assert body["finding"]["exception"]["note"] == REASON
    report = (check_dir / REPORT_FILE_NAME).read_text(encoding="utf-8")
    assert body["exception_id"] in report


def test_the_re_rendered_verdict_carries_the_waived_count(
    client: TestClient, check_dir: Path
) -> None:
    finding_id = row_for(graded(client, check_dir), CUT_LIST)["finding"]["id"]
    client.post(f"/checks/{check_dir.name}/exceptions/{finding_id}", json={"note": REASON})

    result = client.get(f"/checks/{check_dir.name}").json()

    assert result["verdict"]["waived"] == 1
    assert any("waived" in note for note in result["verdict"]["notes"])


# --- 6. the acceptance survives the next run, by both halves of the rule ---------------------


def test_the_package_s_own_store_waives_the_next_command_line_run(
    accepted: tuple[Path, StandardsCheckRun], tmp_path: Path
) -> None:
    """The command line's half: `accept-standards` writes beside the package, and a run
    with no run root at all still grades against it."""
    package_dir, _ = accepted

    run = run_standards_check(package_dir, PROFILE_PATH, tmp_path / "later")

    assert finding_for(run, CUT_LIST)["status"] == "checked_within_scope"
    assert run.exceptions_carried_forward.from_run is None
    assert run.exceptions_carried_forward.reason


def test_an_earlier_run_folder_s_store_is_carried_forward_and_waives(
    accepted: tuple[Path, StandardsCheckRun], tmp_path: Path
) -> None:
    """The pane's half: the newest same-design `exceptions.json` under the run root is
    copied into the new run folder **before** the checks run."""
    package_dir, _ = accepted
    root = tmp_path / "runs"
    earlier = root / "20260917-101532-mr-90001-standards"
    shutil.copytree(package_dir, earlier)
    later = root / "20260918-090000-mr-90001-standards"
    shutil.copytree(SEEDED, later)

    run = run_standards_check(later, PROFILE_PATH, later, run_root=root)

    assert run.exceptions_carried_forward.from_run == earlier.name
    assert run.exceptions_carried_forward.count == 1
    assert finding_for(run, CUT_LIST)["status"] == "checked_within_scope"


def test_a_missing_candidate_is_reported_and_is_not_an_error(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    directory = root / "20260918-090000-mr-90001-standards"
    shutil.copytree(SEEDED, directory)

    run = run_standards_check(directory, PROFILE_PATH, directory, run_root=root)

    assert run.exceptions_carried_forward.from_run is None
    assert run.exceptions_carried_forward.count == 0
    assert run.exceptions_carried_forward.reason


def test_an_unreadable_candidate_refuses_the_run(tmp_path: Path) -> None:
    """An exception nobody can read is one an engineer accepted and would silently be
    raised again."""
    root = tmp_path / "runs"
    earlier = root / "20260917-101532-mr-90001-standards"
    shutil.copytree(SEEDED, earlier)
    (earlier / EXCEPTIONS_FILE_NAME).write_text("{not json", encoding="utf-8")
    directory = root / "20260918-090000-mr-90001-standards"
    shutil.copytree(SEEDED, directory)

    with pytest.raises(UnreadableExceptionsError):
        run_standards_check(directory, PROFILE_PATH, directory, run_root=root)
