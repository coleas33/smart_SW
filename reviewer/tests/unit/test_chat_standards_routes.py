"""The three Standards routes against `contracts/standards-check.md` section 1 (T073).

Driven through Starlette's in-process client, exactly as `test_chat_checks_routes.py`
drives the Model check routes, so every assertion here is about the real application: the
same middleware, the same path rule, the same error body. This module mirrors that one row
for row, because the contract does; what it is responsible for on top of it:

- **`POST /checks/standards` is the tab's whole evaluation.** It calls
  `run_standards_check` - the one no-language-model entry point `swreview check standards`
  also calls (FR-043) - and answers the `StandardsResult` of `contracts/standards-check.md`:
  the verdict with its unresolved check ids beside the counts, the required sixteen-row
  `checks[]`, the findings, the aggregated coverage with the documents in each row's
  `scope`, the structured subjects keyed by finding id, what the carry-forward did, and
  `rebuilt: false`.
- **the profile is a path on the request and a `{path, sha256}` on the reply, and never a
  value** (FR-001, FR-034). The page relays the path the host gave it in `init`; the
  backend reads and validates the file, because the reasoning side owns the schema. No
  profile *value* travels in either direction, which the leak test measures by grading a
  package against `profile-b.yaml`, whose every value is absent from that package.
- **there is no `scope` field.** Every standards check runs on every run, and a body that
  names one is refused rather than quietly answered: a verdict whose coverage depended on a
  control nobody recorded is exactly what a release gate must not produce.
- **one route, two families.** `GET /checks/{check_id}` and the accept route dispatch on the
  record's own `family`: a folder stamped `standards` answers the `StandardsResult`, one
  stamped `rms` - or one written before the field existed - answers the feature 003
  `CheckResult`, and neither ever answers for the other.
- **no provider, no key, no network on any path** (FR-045). The application is built with a
  provider factory that raises, and `TestNoLanguageModel` additionally makes the adapter
  lookup and the command line's factory raise while driving all three routes.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic_core import to_jsonable_python
from starlette.testclient import TestClient

from swreview.agent import providers
from swreview.chat.server import create_app
from swreview.checks.standards.registry import RULES as STANDARDS_RULES
from swreview.checks.standards.registry import STANDARDS_FAMILY
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import DumpPhase, EvidencePackage
from swreview.report.attention import rank
from swreview.report.attention_record import read_attention_record
from swreview.report.session import load_session
from tests.support.features import AssemblySpec, PartSpec, feature, folder, rms_package

ORIGIN = "https://swreview.invalid"
OTHER_ORIGIN = "https://evil.example"
TOKEN = "the-per-launch-token"

FIXTURES = Path(__file__).resolve().parents[1]
SEEDED_PACKAGE = FIXTURES / "golden" / "fixtures" / "standards-seeded" / PACKAGE_FILE_NAME
"""The T053 golden: one seeded violation of each of the sixteen checks, over a drawing
root that references the assembly the model checks grade. It is the fixture this module
grades, so what the route answers and what the golden pins are the same evaluation."""

PROFILE_DIR = FIXTURES / "fixtures" / "standards"
PROFILE_A = PROFILE_DIR / "profile-a.yaml"
PROFILE_B = PROFILE_DIR / "profile-b.yaml"
"""The two fictional profiles (T002). No company value enters a test (FR-001)."""

STANDARDS_CHECK_ID = "20260917-101532-mr-90001-standards"
"""The standards run folder's name, which is also its `check_id`."""

RMS_CHECK_ID = "20260916-101532-cover-check"
"""A Model check run folder under the same run root, for the dispatch tests."""

ROOT = "doc:1"
"""The drawing the seeded package is rooted at."""

ERROR_CHECK = "standards.part.material_assigned"
"""An `error`-severity check the seeded package fails: waivable (FR-041)."""

WARNING_CHECK = "standards.drawing.revision_matches"
"""A `warning`-severity check the seeded package trips: never waivable."""

SUMMARY_CHECK = "standards.release"

SESSION_FILE = "session.json"
REPORT_FILE = "report.md"
ATTENTION_FILE = "attention.json"
CHECK_FILE = "check.json"

PROFILE_B_VALUES: tuple[str, ...] = (
    "K:/kestrel-store",
    "stock/foams/",
    "stock/",
    "parts/hardware/",
    "parts/hardware/dowels/",
    "builds/shared/KS-7.SLDPRT",
    "Kestrel Catalog Ref",
    "Surface Treatment",
    "??#####-KS.SLD???",
    "KestrelRevision",
    "REVISIONS TABLE",
    "KESTREL-CONTROLLED",
)
"""Every distinctive value of `profile-b.yaml`, none of which appears in the seeded
package. A run graded against it may say which *field* it read; saying what the field
*held* is the leak FR-001 exists to prevent.

`material.configuration` is deliberately **not** in this list. The landed report layer
names it in a coverage reason - "has no configuration 'Machined', which is the profile's
material configuration" - because the configuration a part was read in is evidence about
that part, and the wording is pinned by `standards-seeded.yml`. It is the one profile value
that reaches a reply, and it is excluded here by name rather than by a scan that happened
not to look for it."""


# --- the packages under the run folders -------------------------------------------


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


def seeded_run(run_root: Path, name: str) -> Path:
    """A standards run folder holding the seeded golden's package and nothing else yet."""
    directory = run_root / name
    directory.mkdir(parents=True)
    shutil.copy2(SEEDED_PACKAGE, directory / PACKAGE_FILE_NAME)
    return directory


@pytest.fixture
def standards_dir(run_root: Path) -> Path:
    """The run folder the pane dumped the `standards` profile into."""
    return seeded_run(run_root, STANDARDS_CHECK_ID)


def rms_evidence() -> EvidencePackage:
    """The Model check fixture of `test_chat_checks_routes.py`, in its model-check dump."""
    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:3",
                name="cover",
                features=(
                    folder("3-Core", feature("Boss-Extrude2", "Extrusion", description="")),
                    folder("4-Detail", feature("Hole2", "HoleWzd")),
                ),
            )
        ],
        assembly=AssemblySpec(document_id="doc:1", name="cover-assy"),
    )
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"profile": "model_check"})}
    )


@pytest.fixture
def rms_dir(run_root: Path) -> Path:
    directory = run_root / RMS_CHECK_ID
    save_package(rms_evidence(), directory)
    return directory


def refuse_provider(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("a Standards route must never construct a provider")


@pytest.fixture
def app(run_root: Path) -> Any:
    """The backend with a provider factory that raises: no check path may reach one."""
    return create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=refuse_provider,
        list_models=refuse_provider,
    )


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    """The page's client: the launch token and the virtual-host origin on every call."""
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as test_client:
        yield test_client


# --- talking to the routes --------------------------------------------------------


def standards_body(
    run_dir: Path | str, profile: Path | str = PROFILE_A, **overrides: Any
) -> dict[str, Any]:
    """The body the Standards page posts to `/checks/standards`: two fields, no scope."""
    body: dict[str, Any] = {"run_dir": str(run_dir), "profile_path": str(profile)}
    body.update(overrides)
    return body


def start_standards(
    client: TestClient, run_dir: Path, profile: Path | str = PROFILE_A, **overrides: Any
) -> dict[str, Any]:
    response = client.post("/checks/standards", json=standards_body(run_dir, profile, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def start_rms(client: TestClient, run_dir: Path) -> dict[str, Any]:
    response = client.post(
        "/checks/rms",
        json={"run_dir": str(run_dir), "scope": "part", "document_id": "doc:3"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def rows_by_check(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["check"]: row for row in result["findings"]}


def finding_id_of(result: dict[str, Any], check: str) -> str:
    return str(rows_by_check(result)[check]["finding"]["id"])


def accept(client: TestClient, check_id: str, finding_id: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {"note": "accepted by the release owner", "by": "a.engineer"}
    body.update(overrides)
    return client.post(f"/checks/{check_id}/exceptions/{finding_id}", json=body)


def error_of(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error_class", "message", "retryable"}
    return dict(body)


def without_phase(package: EvidencePackage, *names: str) -> EvidencePackage:
    """The same package with the named phases recorded as never having run."""
    phases = [
        DumpPhase(name=row.name, status="skipped", elapsed_ms=None)
        if row.name in names
        else row
        for row in package.extractor.phases
    ]
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"phases": phases})}
    )


# --- 1. POST /checks/standards ----------------------------------------------------


class TestRunStandardsCheck:
    def test_the_result_carries_everything_the_contract_names(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        result = start_standards(client, standards_dir)

        assert set(result) == {
            "check_id",
            "run_dir",
            "family",
            "document",
            "extracted_at",
            "profile",
            "extractor_profile",
            "documents_graded",
            "verdict",
            "checks",
            "findings",
            "coverage",
            "subjects",
            "exceptions_carried_forward",
            "rebuilt",
            "attention",
            "not_examined",
        }
        assert result["check_id"] == STANDARDS_CHECK_ID
        assert Path(result["run_dir"]) == standards_dir
        assert result["family"] == "standards"
        assert result["extractor_profile"] == "standards"
        assert datetime.fromisoformat(result["extracted_at"]).year == 2026

    def test_the_document_is_the_root_of_the_run(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """A standards run grades several documents, so `document` names the **root** and
        `documents_graded` carries the rest; a page that read the ids anywhere else would
        lose every coverage row of a multi-document check."""
        result = start_standards(client, standards_dir)

        assert result["document"]["id"] == ROOT
        assert result["document"]["kind"] == "drawing"
        assert result["document"]["path"].endswith("MR-90001.SLDDRW")
        assert set(result["document"]) == {"id", "path", "configuration", "kind"}

    def test_every_graded_document_travels_with_its_kind_and_how_it_was_reached(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """All three members the contract names on every row, and `reached_by` is the one
        that tells the page a document was pulled in by a drawing view rather than by a
        component tree, so a drawing-rooted fan-out is readable rather than surprising."""
        result = start_standards(client, standards_dir)

        assert [set(row) for row in result["documents_graded"]] == [
            {"id", "kind", "reached_by"}
        ] * 5
        graded = {
            row["id"]: (row["kind"], row["reached_by"])
            for row in result["documents_graded"]
        }
        assert graded == {
            "doc:1": ("drawing", "root"),
            "doc:2": ("assembly", "drawing_reference"),
            "doc:3": ("part", "component_tree"),
            "doc:4": ("part", "component_tree"),
            "doc:5": ("part", "component_tree"),
        }

    def test_the_verdict_carries_its_counts_and_unresolved_ids_and_never_a_grade(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-032: no letter grade and no single number, in any state. The unresolved check
        ids travel in the same object as the counts, so a page cannot render a headline
        without what the run does not cover."""
        result = start_standards(client, standards_dir)
        verdict = result["verdict"]

        assert set(verdict) == {
            "state",
            "counts",
            "waived",
            "unresolved_check_ids",
            "notes",
        }
        assert set(verdict["counts"]) == {
            "error",
            "warning",
            "checked",
            "skipped",
            "unresolved",
            "out_of_scope",
        }
        assert verdict["state"] == "not_ready"
        assert verdict["counts"]["error"] == 13
        assert verdict["counts"]["warning"] == 2
        assert verdict["unresolved_check_ids"] == ["standards.assembly.not_transparent"]
        assert "grade" not in result
        assert "fraction" not in verdict and "fraction" not in verdict["counts"]

    def test_all_sixteen_checks_are_rendered_with_their_worst_bucket(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-033: a release gate says "all sixteen were accounted for" from one array, so a
        check that did not apply is present with an `out_of_scope` bucket, never absent."""
        checks = start_standards(client, standards_dir)["checks"]

        assert [row["check"] for row in checks] == list(STANDARDS_RULES)
        assert len(checks) == 16
        assert SUMMARY_CHECK not in {row["check"] for row in checks}
        for row in checks:
            assert row["severity"] in STANDARDS_FAMILY.severities
            assert row["statement"]
            assert row["worst_bucket"] == row["buckets"][0]["bucket"]
            for bucket in row["buckets"]:
                assert bucket["document_ids"]
                assert bucket["reason"]

    def test_the_findings_are_one_per_seeded_violation_with_the_check_beside_them(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        result = start_standards(client, standards_dir)

        assert len(result["findings"]) == 15
        row = rows_by_check(result)[ERROR_CHECK]
        assert row["severity"] == "error"
        assert row["acceptable"] is True
        assert row["statement"] == STANDARDS_RULES[ERROR_CHECK].statement
        assert row["observed"] == row["finding"]["observed"]
        assert row["finding"]["status"] == "demonstrated"
        assert "exception" not in row

    def test_a_warning_check_is_not_acceptable(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-041: the Accept control is absent on a `warning` check, so the flag that
        decides whether it is drawn at all is part of the response."""
        row = rows_by_check(start_standards(client, standards_dir))[WARNING_CHECK]

        assert row["severity"] == "warning"
        assert row["acceptable"] is False

    def test_the_coverage_carries_its_documents_in_the_row_s_scope(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """A coverage item is the session's `CoverageItem` with its bucket in front of it,
        so the documents it covers are in `scope` and not at the top level."""
        coverage = start_standards(client, standards_dir)["coverage"]

        assert {"checked", "skipped", "unresolved", "out_of_scope"} >= {
            row["bucket"] for row in coverage
        }
        assert all("document_ids" in row["scope"] for row in coverage)
        assert [row for row in coverage if row["check"] == SUMMARY_CHECK]
        unresolved = [
            (row["check"], row["scope"]["document_ids"])
            for row in coverage
            if row["bucket"] == "unresolved" and row["check"] != SUMMARY_CHECK
        ]
        assert unresolved == [("standards.assembly.not_transparent", ["doc:2"])]

    def test_subjects_are_keyed_by_finding_id_beside_the_findings(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-026: the feature 001 finding contract does not move, so the structured
        subjects travel beside the finding and never as a field on it."""
        result = start_standards(client, standards_dir)

        assert set(result["subjects"]) <= {row["finding"]["id"] for row in result["findings"]}
        entries = [entry for group in result["subjects"].values() for entry in group]
        assert entries
        assert all("showable" in entry for entry in entries)
        for row in result["findings"]:
            assert "subjects" not in row["finding"]

    def test_a_drawing_subject_is_never_showable(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-031: the shared resolver reads model entities only, so the page renders no
        Show control at all rather than one that reports `ok: false` every time."""
        result = start_standards(client, standards_dir)
        drawing_findings = [
            row["finding"]["id"]
            for row in result["findings"]
            if str(row["check"]).startswith("standards.drawing.")
        ]

        shown = [
            entry["showable"]
            for finding_id in drawing_findings
            for entry in result["subjects"].get(finding_id, [])
        ]
        assert shown and not any(shown)

    def test_the_profile_comes_back_as_a_path_and_a_hash_and_nothing_else(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        result = start_standards(client, standards_dir)

        assert set(result["profile"]) == {"path", "sha256"}
        assert Path(result["profile"]["path"]) == PROFILE_A
        assert result["profile"]["sha256"] == hashlib.sha256(PROFILE_A.read_bytes()).hexdigest()

    def test_no_profile_value_appears_anywhere_in_the_reply(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-001. Graded against `profile-b.yaml`, whose every value is absent from the
        seeded package, so any occurrence in the reply came from the profile itself. The
        findings may name the *field* they read; naming what it held is the leak."""
        result = start_standards(client, standards_dir, PROFILE_B)

        rendered = json.dumps(result)
        assert [value for value in PROFILE_B_VALUES if value in rendered] == []

    def test_the_run_folder_gets_its_session_report_and_record(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        start_standards(client, standards_dir)

        session = load_session(standards_dir / SESSION_FILE)
        assert session.ended_at is not None
        assert [step.tool for step in session.steps] == ["check_standards"]
        report = (standards_dir / REPORT_FILE).read_text(encoding="utf-8")
        assert "Nothing was rebuilt" in report
        assert json.loads((standards_dir / CHECK_FILE).read_text(encoding="utf-8"))[
            "family"
        ] == "standards"

    def test_rebuilt_is_always_false(self, client: TestClient, standards_dir: Path) -> None:
        """FR-033 difference g: the two rebuild-error checks report counts the macro would
        have refreshed, so which claim is being made is said out loud in the payload."""
        assert start_standards(client, standards_dir)["rebuilt"] is False

    def test_an_earlier_run_s_exceptions_are_carried_forward(
        self, client: TestClient, standards_dir: Path, run_root: Path
    ) -> None:
        """FR-041: an acceptance survives the next check without an engineer copying a
        file, and what the carry-forward did is reported either way.

        What the *waiver* then does to the finding and to the verdict's `waived` count is
        `checks/standards/report.py`'s answer and is pinned by T090/T091; this route's
        contract point is that the store travelled and that the run says so.
        """
        earlier = seeded_run(run_root, "20260916-173001-mr-90001-standards")
        (earlier / EXCEPTIONS_FILE_NAME).write_text(
            accepted_store(standards_dir), encoding="utf-8"
        )

        result = start_standards(client, standards_dir)

        carried = result["exceptions_carried_forward"]
        assert carried["from_run"] == "20260916-173001-mr-90001-standards"
        assert carried["count"] == 1
        assert (standards_dir / EXCEPTIONS_FILE_NAME).read_bytes() == (
            earlier / EXCEPTIONS_FILE_NAME
        ).read_bytes()

    def test_nothing_carried_forward_is_reported_and_is_not_an_error(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        carried = start_standards(client, standards_dir)["exceptions_carried_forward"]

        assert carried["from_run"] is None
        assert carried["count"] == 0
        assert "no earlier run" in carried["reason"]

    def test_attention_is_the_ranking_of_the_run_s_own_session(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-022. Byte-identical in shape to the Model check body's `attention`, which is
        why `contracts/standards-check.md` adds no difference row for it: one block, one
        rule, two tabs (`contracts/attention.md` section 5)."""
        result = start_standards(client, standards_dir)

        assert result["attention"] == to_jsonable_python(
            rank(load_session(standards_dir / SESSION_FILE))
        )
        assert result["attention"]["policy_version"] == "attention_policy_v1"
        assert "session_id" not in result["attention"]
        assert [row["finding_id"] for row in result["attention"]["rows"]] == [
            row.finding_id for row in read_attention_record(standards_dir).rows
        ]

    def test_every_amplified_row_names_a_finding_the_body_carries(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """Amplify, never filter, and no percent sign: the Standards page's body scan
        forbids one and the rows are rendered straight into it (research R2.14)."""
        result = start_standards(client, standards_dir)

        known = {row["finding"]["id"] for row in result["findings"]}
        assert known
        for row in result["attention"]["rows"]:
            assert set(row["member_finding_ids"]) <= known
            assert row["reason"]
            assert "%" not in row["reason"]


# --- 2. what POST /checks/standards refuses ---------------------------------------


class TestRunStandardsRefusals:
    def test_a_run_dir_outside_the_run_root_is_refused(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere"
        outside.mkdir()

        response = client.post("/checks/standards", json=standards_body(outside))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidRunDir"

    @pytest.mark.parametrize(
        "raw",
        [
            f"\\\\server\\share\\{STANDARDS_CHECK_ID}",
            f"\\\\?\\C:\\runs\\{STANDARDS_CHECK_ID}",
            f"\\\\.\\pipe\\{STANDARDS_CHECK_ID}",
        ],
        ids=["unc", "device-question", "device-dot"],
    )
    def test_a_unc_or_device_path_is_refused_before_the_filesystem_is_touched(
        self, client: TestClient, raw: str
    ) -> None:
        response = client.post("/checks/standards", json=standards_body(raw))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidRunDir"

    def test_a_parent_segment_is_refused_rather_than_normalized(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        response = client.post(
            "/checks/standards",
            json=standards_body(standards_dir / ".." / STANDARDS_CHECK_ID),
        )

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidRunDir"

    def test_a_missing_package_is_refused(self, client: TestClient, run_root: Path) -> None:
        empty = run_root / "20260917-120000-empty-standards"
        empty.mkdir()

        response = client.post("/checks/standards", json=standards_body(empty))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidPackage"

    def test_an_unreadable_package_is_refused(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        (standards_dir / PACKAGE_FILE_NAME).write_text("{not a package", encoding="utf-8")

        response = client.post("/checks/standards", json=standards_body(standards_dir))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidPackage"

    def test_a_package_without_the_standards_phases_is_refused_naming_them(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-043: sixteen unresolved checks read as a broken model rather than as the
        missing extract they are, so the refusal names the phase rows and the profile that
        produced this package."""
        save_package(
            without_phase(load_package(standards_dir).package, "cutlist", "drawing"),
            standards_dir,
        )

        response = client.post("/checks/standards", json=standards_body(standards_dir))

        assert response.status_code == 400
        error = error_of(response)
        assert error["error_class"] == "MissingStandardsPhases"
        assert "cutlist" in error["message"]
        assert "drawing" in error["message"]
        assert "standards" in error["message"]

    def test_a_missing_profile_path_is_refused(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-002: there is no default and no fallback. A profile nobody configured would
        grade the design against the wrong standard and report a clean result."""
        body = standards_body(standards_dir)
        del body["profile_path"]

        response = client.post("/checks/standards", json=body)

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "ProfileUnreadable"

    def test_a_profile_that_is_not_on_this_machine_is_refused(
        self, client: TestClient, standards_dir: Path, tmp_path: Path
    ) -> None:
        response = client.post(
            "/checks/standards",
            json=standards_body(standards_dir, tmp_path / "nowhere" / "standards.yaml"),
        )

        assert response.status_code == 400
        error = error_of(response)
        assert error["error_class"] == "ProfileUnreadable"
        assert "StandardsProfilePath" in error["message"]

    def test_a_profile_that_fails_the_schema_is_refused_carrying_the_error(
        self, client: TestClient, standards_dir: Path, tmp_path: Path
    ) -> None:
        broken = tmp_path / "half-written.yaml"
        broken.write_text(
            PROFILE_A.read_text(encoding="utf-8").replace("material:", "materials:"),
            encoding="utf-8",
        )

        response = client.post("/checks/standards", json=standards_body(standards_dir, broken))

        assert response.status_code == 400
        error = error_of(response)
        assert error["error_class"] == "ProfileInvalid"
        assert "material" in error["message"]

    def test_a_refused_profile_writes_nothing_into_the_run_folder(
        self, client: TestClient, standards_dir: Path, tmp_path: Path
    ) -> None:
        """Spec US3 acceptance scenario 12: a folder created before the refusal renders as
        an empty run, so the refusal must not leave a session or a report in it."""
        before = sorted(path.name for path in standards_dir.iterdir())

        client.post(
            "/checks/standards", json=standards_body(standards_dir, tmp_path / "gone.yaml")
        )

        assert sorted(path.name for path in standards_dir.iterdir()) == before

    def test_an_unreadable_carry_forward_candidate_refuses_the_run(
        self, client: TestClient, standards_dir: Path, run_root: Path
    ) -> None:
        """An exception store nobody can read must never be read as an empty one, which
        would silently re-raise a condition somebody already accepted."""
        earlier = seeded_run(run_root, "20260916-173001-mr-90001-standards")
        (earlier / EXCEPTIONS_FILE_NAME).write_text("{not json", encoding="utf-8")

        response = client.post("/checks/standards", json=standards_body(standards_dir))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "UnreadableExceptions"

    def test_no_scope_field_is_accepted(self, client: TestClient, standards_dir: Path) -> None:
        """Every standards check runs on every run (`contracts/standards-check.md`
        section 1). A run that let an engineer switch checks off would produce a verdict
        whose coverage depended on a control nobody recorded."""
        response = client.post(
            "/checks/standards", json=standards_body(standards_dir, scope="part")
        )

        assert response.status_code == 400
        error = error_of(response)
        assert error["error_class"] == "InvalidRequest"
        assert "scope" in error["message"]


# --- 3. the door, on the standards route ------------------------------------------


STANDARDS_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", "/checks/standards"),
    ("GET", f"/checks/{STANDARDS_CHECK_ID}"),
    ("POST", f"/checks/{STANDARDS_CHECK_ID}/exceptions/F-013"),
)


class TestTheDoor:
    @pytest.mark.parametrize(("method", "path"), STANDARDS_ROUTES)
    def test_no_token_is_401(self, app: Any, method: str, path: str) -> None:
        with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
            response = anonymous.request(method, path, json={})

        assert response.status_code == 401
        assert error_of(response)["error_class"] == "Unauthorized"

    @pytest.mark.parametrize(("method", "path"), STANDARDS_ROUTES)
    def test_a_foreign_origin_is_403_before_authentication(
        self, app: Any, method: str, path: str
    ) -> None:
        with TestClient(
            app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": OTHER_ORIGIN}
        ) as stranger:
            response = stranger.request(method, path, json={})

        assert response.status_code == 403
        assert error_of(response)["error_class"] == "ForbiddenOrigin"
        assert "access-control-allow-origin" not in response.headers

    @pytest.mark.parametrize(("_method", "path"), STANDARDS_ROUTES)
    def test_the_preflight_is_answered_without_a_token(
        self, app: Any, _method: str, path: str
    ) -> None:
        with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
            response = anonymous.options(path)

        assert response.status_code == 204
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["access-control-allow-private-network"] == "true"

    def test_the_exact_origin_is_echoed_on_a_standards_check(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        response = client.post("/checks/standards", json=standards_body(standards_dir))

        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["vary"] == "Origin"


# --- 4. GET /checks/{check_id}, dispatching on the record's family ----------------


class TestReadCheck:
    def test_the_same_standards_result_comes_back_from_the_folder(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """The folder name is the whole registry: a restarted pane reads its last check
        back by name, and a read evaluates nothing.

        `attention.json` is in the unchanged list because the ranking a `GET` answers with
        is recomputed in memory: a read must not refresh the record of the order the
        engineer was shown (FR-022, research R2.7).
        """
        posted = start_standards(client, standards_dir)
        before = {
            name: (standards_dir / name).read_bytes()
            for name in (SESSION_FILE, REPORT_FILE, CHECK_FILE, ATTENTION_FILE)
        }

        response = client.get(f"/checks/{STANDARDS_CHECK_ID}")

        assert response.status_code == 200, response.text
        assert response.json() == posted
        assert response.json()["attention"] == posted["attention"]
        assert {name: (standards_dir / name).read_bytes() for name in before} == before

    def test_an_rms_folder_answers_the_model_check_shape(
        self, client: TestClient, rms_dir: Path
    ) -> None:
        """One route, two families, and neither answers for the other: a `check_id` naming
        an rms folder comes back as the feature 003 `CheckResult`, so the Standards page
        reports that the id is not a standards check rather than rendering it."""
        start_rms(client, rms_dir)

        got = client.get(f"/checks/{RMS_CHECK_ID}").json()

        assert "grade" in got
        assert "verdict" not in got
        assert "checks" not in got
        assert "family" not in got

    def test_a_record_written_before_the_family_field_is_a_model_check(
        self, client: TestClient, rms_dir: Path
    ) -> None:
        """A feature 003 run folder carries no `family`, and a build that refused to read
        one would make every check written before this feature unreadable."""
        start_rms(client, rms_dir)
        record = json.loads((rms_dir / CHECK_FILE).read_text(encoding="utf-8"))
        del record["family"]
        (rms_dir / CHECK_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")

        response = client.get(f"/checks/{RMS_CHECK_ID}")

        assert response.status_code == 200, response.text
        assert "grade" in response.json()

    def test_both_families_are_answered_by_the_one_route(
        self, client: TestClient, standards_dir: Path, rms_dir: Path
    ) -> None:
        start_standards(client, standards_dir)
        start_rms(client, rms_dir)

        standards = client.get(f"/checks/{STANDARDS_CHECK_ID}").json()
        rms = client.get(f"/checks/{RMS_CHECK_ID}").json()

        assert standards["family"] == "standards"
        assert len(standards["checks"]) == 16
        assert "grade" in rms

    def test_an_unknown_check_is_404(self, client: TestClient, run_root: Path) -> None:
        response = client.get("/checks/20260917-999999-nothing-standards")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"

    def test_a_folder_no_check_ever_wrote_is_404(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """A dumped folder is not a check: reading it would run one, and "no such check" is
        what the caller asked about."""
        response = client.get(f"/checks/{STANDARDS_CHECK_ID}")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"


# --- 5. POST /checks/{check_id}/exceptions/{finding_id} ---------------------------


def accepted_store(package_dir: Path) -> str:
    """The text of an `exceptions.json` accepting `ERROR_CHECK` on the failing part.

    A standards waiver names the **document** it was accepted on as well as the instances
    that reach it: a drawing finding has no instances, so without it two drawings' waivers
    would be indistinguishable (FR-041, RK-11).
    """
    package = load_package(package_dir).package
    store = ExceptionStore(package_dir.parent.parent / "scratch" / EXCEPTIONS_FILE_NAME)
    store.accept(
        _AcceptedFinding(
            check=ERROR_CHECK,
            component_ids=[
                component.id
                for component in package.components
                if component.document_id == "doc:3"
            ],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note="accepted by the release owner",
        document_id="doc:3",
    )
    return store.save().read_text(encoding="utf-8")


class _AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    def __init__(self, check: str, component_ids: list[str], configuration: str) -> None:
        self.check = check
        self.component_ids = component_ids
        self.configuration = configuration


class TestAcceptException:
    def test_accepting_answers_the_re_rendered_finding_and_the_exception_id(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """Never hidden (Principle VI): the check keeps its row, and the row that comes
        back is the one the re-run produced rather than the one the page already had.

        What that row's *status* becomes once the waived-outcome path exists is
        `checks/standards/report.py`'s answer and is T091's, which is why this asserts the
        row and the id and not the wording of the waiver.
        """
        finding_id = finding_id_of(start_standards(client, standards_dir), ERROR_CHECK)

        response = accept(client, STANDARDS_CHECK_ID, finding_id)

        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"finding", "exception_id"}
        assert body["exception_id"].startswith("EX-")
        assert body["finding"]["finding"]["id"] == finding_id
        assert body["finding"]["check"] == ERROR_CHECK

    def test_the_exception_is_written_beside_the_package_bound_to_its_document(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-041, RK-11: a standards waiver names the document it was accepted on, because
        a drawing finding has no component instances and an exception bound to nothing is
        the blanket exclusion the constitution prohibits."""
        finding_id = finding_id_of(start_standards(client, standards_dir), ERROR_CHECK)

        accept(client, STANDARDS_CHECK_ID, finding_id)

        [exception] = ExceptionStore(standards_dir / EXCEPTIONS_FILE_NAME).load().exceptions
        assert exception.check == ERROR_CHECK
        assert exception.fingerprint_kind == "standards"
        assert exception.document_id == "doc:3"
        assert exception.accepted_by == "a.engineer"
        assert exception.note == "accepted by the release owner"

    def test_the_folder_is_re_rendered_over_the_store_that_was_just_written(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """Accept re-runs the checks over the store it wrote, which is what re-renders
        `report.md`; a route that edited the finding in place would leave the report saying
        what the run said before the waiver existed."""
        posted = start_standards(client, standards_dir)
        finding_id = finding_id_of(posted, ERROR_CHECK)
        before = load_session(standards_dir / SESSION_FILE).session_id

        accept(client, STANDARDS_CHECK_ID, finding_id)

        assert load_session(standards_dir / SESSION_FILE).session_id != before
        report = (standards_dir / REPORT_FILE).read_text(encoding="utf-8")
        assert "Nothing was rebuilt" in report
        assert ERROR_CHECK in report
        assert client.get(f"/checks/{STANDARDS_CHECK_ID}").json()["check_id"] == (
            STANDARDS_CHECK_ID
        )
        assert client.get(f"/checks/{STANDARDS_CHECK_ID}").json()["attention"] == (
            to_jsonable_python(rank(load_session(standards_dir / SESSION_FILE)))
        )

    def test_a_blank_note_is_refused(self, client: TestClient, standards_dir: Path) -> None:
        finding_id = finding_id_of(start_standards(client, standards_dir), ERROR_CHECK)

        response = accept(client, STANDARDS_CHECK_ID, finding_id, note="   ")

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "EmptyNote"
        assert not (standards_dir / EXCEPTIONS_FILE_NAME).exists()

    def test_a_warning_check_is_refused(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """FR-041. The page draws no button for one; the route refuses it anyway, because a
        check that is not waivable must not become waivable through the network."""
        finding_id = finding_id_of(start_standards(client, standards_dir), WARNING_CHECK)

        response = accept(client, STANDARDS_CHECK_ID, finding_id)

        assert response.status_code == 409
        error = error_of(response)
        assert error["error_class"] == "RuleNotAcceptable"
        assert WARNING_CHECK in error["message"]
        assert STANDARDS_FAMILY.waiver_labels["warning"] in error["message"]
        assert not (standards_dir / EXCEPTIONS_FILE_NAME).exists()

    def test_a_condition_an_active_exception_already_covers_is_refused(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """One condition, one record: `ExceptionStore.match` returns the first non-retired
        match, so a second record for it would be dead as well as untrue."""
        finding_id = finding_id_of(start_standards(client, standards_dir), ERROR_CHECK)
        assert accept(client, STANDARDS_CHECK_ID, finding_id).status_code == 200

        response = accept(client, STANDARDS_CHECK_ID, finding_id)

        assert response.status_code == 409
        assert error_of(response)["error_class"] == "AlreadyAccepted"
        assert len(ExceptionStore(standards_dir / EXCEPTIONS_FILE_NAME).load().exceptions) == 1

    def test_an_unknown_finding_is_404(self, client: TestClient, standards_dir: Path) -> None:
        start_standards(client, standards_dir)

        response = accept(client, STANDARDS_CHECK_ID, "F-404")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownFinding"

    def test_an_unknown_check_is_404(self, client: TestClient, standards_dir: Path) -> None:
        response = accept(client, "20260917-999999-nothing-standards", "F-013")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"

    def test_a_folder_with_no_check_is_404(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        response = accept(client, STANDARDS_CHECK_ID, "F-013")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"

    def test_the_one_route_accepts_for_either_family(
        self, client: TestClient, standards_dir: Path, rms_dir: Path
    ) -> None:
        """The accept route dispatches on the record's family, so the rms folder keeps its
        own catalogue's answer to "which rules may be waived"."""
        standards_finding = finding_id_of(start_standards(client, standards_dir), ERROR_CHECK)
        rms_result = start_rms(client, rms_dir)
        rms_finding = next(
            str(row["finding"]["id"])
            for row in rms_result["findings"]
            if row["severity"] == "fail"
        )

        assert accept(client, STANDARDS_CHECK_ID, standards_finding).status_code == 200
        assert accept(client, RMS_CHECK_ID, rms_finding).status_code == 200

        assert ExceptionStore(standards_dir / EXCEPTIONS_FILE_NAME).load().exceptions
        assert ExceptionStore(rms_dir / EXCEPTIONS_FILE_NAME).load().exceptions


# --- 6. no provider, no key, no network (FR-045) ----------------------------------


class TestNoLanguageModel:
    def test_every_standards_route_runs_with_the_provider_factories_raising(
        self, client: TestClient, standards_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The tab has to work on a workstation with no key at all, so a standards check
        must not so much as look one up."""
        import swreview.cli as cli_module

        monkeypatch.setattr(providers, "get", refuse_provider)
        monkeypatch.setattr(providers, "call_tool", refuse_provider)
        monkeypatch.setattr(cli_module, "provider_factory", refuse_provider)
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        posted = start_standards(client, standards_dir)
        assert posted["attention"]["rows"], "the ranking is computed on this keyless path"
        finding_id = finding_id_of(posted, ERROR_CHECK)
        assert accept(client, STANDARDS_CHECK_ID, finding_id).status_code == 200
        assert client.get(f"/checks/{STANDARDS_CHECK_ID}").status_code == 200

    def test_a_standards_check_opens_no_chat_session(
        self, client: TestClient, standards_dir: Path, app: Any
    ) -> None:
        start_standards(client, standards_dir)

        assert app.state.server.chats == {}

    def test_the_run_folder_is_not_claimed_by_the_check(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        first = start_standards(client, standards_dir)

        second = start_standards(client, standards_dir)

        assert rows_by_check(second).keys() == rows_by_check(first).keys()


def test_the_error_body_is_the_contract_s(client: TestClient, tmp_path: Path) -> None:
    """Every refusal on this route is `{error_class, message, retryable}`, so the page
    switches on the class rather than on prose."""
    response = client.post("/checks/standards", json=standards_body(tmp_path / "elsewhere"))

    body = json.loads(response.text)
    assert set(body) == {"error_class", "message", "retryable"}
    assert body["retryable"] is False
