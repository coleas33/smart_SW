"""The three Model check routes against `contracts/model-check.md` (T072).

Driven through Starlette's in-process client, exactly as `test_chat_server.py` drives the
chat routes, so every assertion here is about the real application: the same middleware,
the same path rule, the same error body. What the contract makes this module responsible
for:

- **`POST /checks/rms` is the tab's whole evaluation.** It calls `run_rms_check` - the one
  no-language-model entry point `swreview check rms` also calls (FR-024) - and answers the
  `CheckResult` of `contracts/model-check.md`: the grade with its unresolved rule ids
  beside the counts, the findings with the rule's statement and whether the rule is
  acceptable at all, the aggregated coverage, the structured subjects keyed by finding id,
  and what the carry-forward did.
- **the run folder is what makes a check addressable.** `GET /checks/{check_id}` resolves
  the folder name under the run root through the same path rule and answers the same
  result, so a pane that was restarted can read its last check back without any
  server-side registry. It is a **read**: it rebuilds the result from `session.json` and
  `check.json` and writes nothing, because re-evaluating a folder to answer a `GET` would
  hand back a new session id and overwrite the disposition an engineer recorded on a
  finding.
- **Accept is the exception store, not a second one.** `POST /checks/{check_id}/exceptions/
  {finding_id}` goes through the helpers `swreview exceptions accept-rms` uses, so a
  waiver written from the tab and one written from the command line are the same record:
  a note is required, a `warn` rule is refused (FR-016), a condition an active exception
  already covers is refused, and the finding comes back re-rendered as checked within
  scope carrying the exception id.
- **the door is the same door.** The token, the preflight and the origin rules hold on
  these three routes because they are middleware and not a decorator, and this module
  proves it on the new paths rather than assuming it.
- **no provider, no key, no network on any of these paths** (SC-011). The application is
  built with a provider factory that raises, and `TestNoLanguageModel` additionally makes
  the adapter lookup and the command line's factory raise while driving all three routes.
  The one exception is `review_app`, used by the last class here: handing a check folder
  to a review (User Story 6 scenario 11) starts a review, and a review does construct an
  adapter.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic_core import to_jsonable_python
from starlette.testclient import TestClient

from swreview.agent import providers
from swreview.agent.providers import AgentProvider
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.settings import ProviderSettings
from swreview.chat.server import create_app
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention import rank
from swreview.report.attention_record import read_attention_record
from swreview.report.dispositions import apply_disposition, find_finding
from swreview.report.session import load_session
from tests.support.features import AssemblySpec, PartSpec, equation, feature, folder, rms_package
from tests.support.packages import CREATED_AT

ORIGIN = "https://swreview.invalid"
OTHER_ORIGIN = "https://evil.example"
TOKEN = "the-per-launch-token"

CHECK_ID = "20260916-101532-cover-check"
"""The check run folder's name, which is also its `check_id` (`contracts/model-check.md`)."""

FRAME = "doc:2"
"""The compliant part."""

COVER = "doc:3"
"""The part that fails a `fail` rule and trips a `warn` rule."""

ASSEMBLY = "doc:1"

FAIL_RULE = "rms.intent.every_feature_described"
WARN_RULE = "rms.folders.present"

SESSION_FILE = "session.json"
REPORT_FILE = "report.md"
ATTENTION_FILE = "attention.json"
CHECK_FILE = "check.json"
"""What the check records beside its session: the scope, the documents it graded, the
subjects of each finding and what the carry-forward did - everything a `GET` needs that
`session.json` does not hold, so the read evaluates nothing."""


# --- the package under the check folder -------------------------------------------


def evidence() -> EvidencePackage:
    """One compliant part, one part that trips a `fail` and a `warn` rule, an assembly."""
    return rms_package(
        parts=[
            PartSpec(
                document_id=FRAME,
                name="frame",
                equations=(equation('"thickness" = 3mm', is_global=True, value=0.003),),
                features=(
                    folder("1-Ref", feature("Plane1", "RefPlane")),
                    folder("2-Construction", feature("Surface1", "SurfaceExtrude")),
                    folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
                    folder("4-Detail", feature("Hole1", "HoleWzd")),
                    folder("5-Modify", feature("Draft1", "Draft")),
                    folder("6-Quarantine", feature("Chamfer1", "Chamfer")),
                ),
            ),
            PartSpec(
                document_id=COVER,
                name="cover",
                features=(
                    folder("3-Core", feature("Boss-Extrude2", "Extrusion", description="")),
                    folder("4-Detail", feature("Hole2", "HoleWzd")),
                ),
            ),
        ],
        assembly=AssemblySpec(document_id=ASSEMBLY, name="cover-assy"),
    )


def model_check_package() -> EvidencePackage:
    """The evidence as the `ModelCheck` dump profile writes it (`extractor.profile`)."""
    package = evidence()
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"profile": "model_check"})}
    )


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def check_dir(run_root: Path) -> Path:
    """The check run folder the pane dumped into: a package and nothing else yet."""
    directory = run_root / CHECK_ID
    save_package(model_check_package(), directory)
    return directory


def refuse_provider(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("a Model check route must never construct a provider")


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
def review_app(run_root: Path) -> Any:
    """The same backend with a scripted adapter, for the one test that starts a review."""

    def factory(settings: ProviderSettings) -> AgentProvider:
        return FakeProvider(
            script=[ScriptedTurn(text="nothing to add", tool_calls=())],
            model=settings.model,
        )

    return create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=factory,
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


def check_body(run_dir: Path | str, **overrides: Any) -> dict[str, Any]:
    """The body the Model check page posts to `/checks/rms`."""
    body: dict[str, Any] = {"run_dir": str(run_dir), "scope": "part", "document_id": COVER}
    body.update(overrides)
    return body


def start_check(client: TestClient, run_dir: Path, **overrides: Any) -> dict[str, Any]:
    response = client.post("/checks/rms", json=check_body(run_dir, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def rows_by_rule(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["rule_id"]: row for row in result["findings"]}


def finding_id_of(result: dict[str, Any], rule_id: str) -> str:
    return str(rows_by_rule(result)[rule_id]["finding"]["id"])


def accept(
    client: TestClient, check_id: str, finding_id: str, **overrides: Any
) -> Any:
    body: dict[str, Any] = {"note": "legacy tree, accepted by the owner", "by": "a.engineer"}
    body.update(overrides)
    return client.post(f"/checks/{check_id}/exceptions/{finding_id}", json=body)


def sibling_run(run_root: Path, name: str, *, exceptions: str | None = None) -> Path:
    """Another run folder under the same run root, optionally holding an exception file."""
    directory = run_root / name
    save_package(model_check_package(), directory)
    if exceptions is not None:
        (directory / EXCEPTIONS_FILE_NAME).write_text(exceptions, encoding="utf-8")
    return directory


# --- 1. POST /checks/rms ----------------------------------------------------------


class TestRunCheck:
    def test_the_check_result_carries_exactly_the_keys_the_contract_names(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """The mirror image of `test_chat_standards_routes.py`'s strict set (T033).

        Strict on both sides, so a key added to one family's body and forgotten on the
        other's is a failure and not a difference nobody wrote down: the two bodies share
        `attention`, which is why `contracts/standards-check.md` adds no difference row
        for it.
        """
        result = start_check(client, check_dir)

        assert set(result) == {
            "check_id",
            "run_dir",
            "document",
            "extracted_at",
            "profile",
            "grade",
            "findings",
            "coverage",
            "subjects",
            "exceptions_carried_forward",
            "attention",
        }

    def test_the_check_result_carries_everything_the_contract_names(
        self, client: TestClient, check_dir: Path
    ) -> None:
        result = start_check(client, check_dir)

        assert result["check_id"] == CHECK_ID
        assert Path(result["run_dir"]) == check_dir
        assert result["profile"] == "model_check"
        assert datetime.fromisoformat(result["extracted_at"]) == CREATED_AT
        assert result["document"] == {
            "id": COVER,
            "path": "native/cover.SLDPRT",
            "configuration": "Default",
            "kind": "part",
        }

    def test_the_grade_carries_its_unresolved_rule_ids_and_never_a_letter(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """Key point 10: a page cannot render a score from this without the rules
        nobody could evaluate, because they travel in the same object as the counts."""
        grade = start_check(client, check_dir)["grade"]

        assert set(grade) == {
            "failed",
            "warned",
            "checked",
            "skipped",
            "unresolved",
            "out_of_scope",
            "fraction",
            "unresolved_rule_ids",
        }
        assert grade["failed"] >= 1
        assert grade["warned"] >= 1
        assert grade["unresolved_rule_ids"]
        assert 0.0 <= grade["fraction"] <= 1.0

    def test_a_fail_rule_finding_is_acceptable_and_states_the_rule(
        self, client: TestClient, check_dir: Path
    ) -> None:
        row = rows_by_rule(start_check(client, check_dir))[FAIL_RULE]

        assert row["severity"] == "fail"
        assert row["acceptable"] is True
        assert row["statement"]
        assert row["observed"] == row["finding"]["observed"]
        assert row["finding"]["status"] == "demonstrated"
        assert "exception" not in row

    def test_a_warn_rule_finding_is_not_acceptable(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """FR-016: the Accept button is absent on a `warn` rule, so the flag that
        decides whether it is drawn at all is part of the response."""
        row = rows_by_rule(start_check(client, check_dir))[WARN_RULE]

        assert row["severity"] == "warn"
        assert row["acceptable"] is False

    def test_subjects_are_keyed_by_finding_id_beside_the_findings(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """FR-026: the feature 001 finding contract does not move, so the structured
        subjects travel beside the finding and never as a field on it."""
        result = start_check(client, check_dir)

        assert set(result["subjects"]) == {row["finding"]["id"] for row in result["findings"]}
        [subject] = result["subjects"][finding_id_of(result, FAIL_RULE)]
        assert subject["name"] == "Boss-Extrude2"
        assert subject["group"] == "3-Core"
        assert subject["persist_ref_scope"] == COVER
        assert subject["component_ids"]
        for row in result["findings"]:
            assert "subjects" not in row["finding"]

    def test_the_finding_also_carries_the_subject_as_a_source_reference(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """What makes Show work: the page reads the reference off the finding and never
        parses the display string in `inputs`."""
        result = start_check(client, check_dir)
        finding = rows_by_rule(result)[FAIL_RULE]["finding"]

        [location] = finding["drawing_locations"]
        assert location["document_id"] == COVER
        assert location["persist_ref"]

    def test_the_aggregated_coverage_comes_back_with_its_buckets(
        self, client: TestClient, check_dir: Path
    ) -> None:
        coverage = start_check(client, check_dir)["coverage"]

        assert {"checked", "unresolved", "out_of_scope"} <= {row["bucket"] for row in coverage}
        assert all("check" in row for row in coverage)

    def test_the_run_folder_gets_its_session_and_report(
        self, client: TestClient, check_dir: Path
    ) -> None:
        start_check(client, check_dir)

        session = load_session(check_dir / SESSION_FILE)
        assert session.ended_at is not None
        assert [step.tool for step in session.steps] == ["check_rms_part"]
        assert FAIL_RULE in (check_dir / REPORT_FILE).read_text(encoding="utf-8")

    def test_no_document_id_grades_every_part_document(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """`document` is null rather than one of two: a check that graded several part
        documents has no single document to name, and naming the first would be a claim
        about which one the page is showing."""
        result = start_check(client, check_dir, document_id=None)

        assert result["document"] is None
        assert result["findings"]

    def test_the_all_scope_runs_no_uncalibrated_assembly_rule(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """`all` is the families this tab offers, and nothing else.

        The route refuses `assembly` by name because those rules have not been calibrated
        (`ScopeNotAvailable`); running them under an alias would fold exactly the verdict
        it refuses to give into the grade, where it would read as a clean one.
        """
        result = start_check(client, check_dir, scope="all", document_id=None)

        session = load_session(check_dir / SESSION_FILE)
        assert [step.tool for step in session.steps] == [
            "check_rms_part",
            "check_rms_equations",
        ]
        assert not [
            row
            for row in result["coverage"]
            if str(row["check"]).startswith("rms.assembly.")
            and row["bucket"] in {"checked", "failed", "warned"}
        ]
        assert not [
            row for row in result["findings"] if str(row["rule_id"]).startswith("rms.assembly.")
        ]
        # The four assembly rules whose data is not extracted stay unresolved coverage, as
        # they are for `part` (US2): "this was not evaluated" is not a verdict about mates.
        assert {
            row["check"]
            for row in result["coverage"]
            if str(row["check"]).startswith("rms.assembly.")
        } == {
            row["check"]
            for row in start_check(client, check_dir, document_id=None)["coverage"]
            if str(row["check"]).startswith("rms.assembly.")
        }

    def test_an_earlier_run_s_exceptions_are_carried_forward(
        self, client: TestClient, check_dir: Path, run_root: Path
    ) -> None:
        """FR-029: an acceptance survives the next check without an engineer copying a
        file, and what the carry-forward did is reported either way."""
        sibling_run(run_root, "20260915-173001-cover-check", exceptions=accepted_store(check_dir))

        result = start_check(client, check_dir)

        assert result["exceptions_carried_forward"]["from_run"] == "20260915-173001-cover-check"
        assert result["exceptions_carried_forward"]["count"] == 1
        assert result["exceptions_carried_forward"]["reason"] is None
        assert rows_by_rule(result)[FAIL_RULE]["finding"]["status"] == "checked_within_scope"

    def test_nothing_carried_forward_is_reported_and_is_not_an_error(
        self, client: TestClient, check_dir: Path
    ) -> None:
        carried = start_check(client, check_dir)["exceptions_carried_forward"]

        assert carried["from_run"] is None
        assert carried["count"] == 0
        assert "no earlier run" in carried["reason"]

    def test_attention_is_the_ranking_of_the_run_s_own_session(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """FR-022: the tab renders the ranking from the body it already holds.

        The value is `rank()` over the session the run just wrote, minus `session_id` -
        the body already names the check - which is the same block `attention.json` holds
        and the same block the Standards body carries (`contracts/attention.md` section 5).
        """
        result = start_check(client, check_dir)

        assert result["attention"] == to_jsonable_python(
            rank(load_session(check_dir / SESSION_FILE))
        )
        assert result["attention"]["policy_version"] == "attention_policy_v1"
        assert "session_id" not in result["attention"]
        assert [row["finding_id"] for row in result["attention"]["rows"]] == [
            row.finding_id for row in read_attention_record(check_dir).rows
        ]

    def test_every_amplified_row_names_a_finding_the_body_carries(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """Amplify, never filter: the rows are an index into `findings`, not a selection."""
        result = start_check(client, check_dir)

        known = {row["finding"]["id"] for row in result["findings"]}
        assert known
        for row in result["attention"]["rows"]:
            assert set(row["member_finding_ids"]) <= known
            assert row["reason"]
            assert "%" not in row["reason"]


# --- 2. what POST /checks/rms refuses ---------------------------------------------


def error_of(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error_class", "message", "retryable"}
    return dict(body)


class TestRunCheckRefusals:
    def test_a_run_dir_outside_the_run_root_is_refused(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere"
        outside.mkdir()

        response = client.post("/checks/rms", json=check_body(outside))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidRunDir"

    @pytest.mark.parametrize(
        "raw",
        [
            "\\\\server\\share\\20260916-101532-cover-check",
            "\\\\?\\C:\\runs\\20260916-101532-cover-check",
            "\\\\.\\pipe\\20260916-101532-cover-check",
        ],
        ids=["unc", "device-question", "device-dot"],
    )
    def test_a_unc_or_device_path_is_refused_before_the_filesystem_is_touched(
        self, client: TestClient, raw: str
    ) -> None:
        response = client.post("/checks/rms", json=check_body(raw))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidRunDir"

    def test_a_parent_segment_is_refused_rather_than_normalized(
        self, client: TestClient, check_dir: Path
    ) -> None:
        response = client.post("/checks/rms", json=check_body(check_dir / ".." / CHECK_ID))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidRunDir"

    def test_a_missing_package_is_refused(self, client: TestClient, run_root: Path) -> None:
        empty = run_root / "20260916-120000-empty-check"
        empty.mkdir()

        response = client.post("/checks/rms", json=check_body(empty))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidPackage"

    def test_an_unreadable_package_is_refused(
        self, client: TestClient, check_dir: Path
    ) -> None:
        (check_dir / PACKAGE_FILE_NAME).write_text("{not a package", encoding="utf-8")

        response = client.post("/checks/rms", json=check_body(check_dir))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidPackage"

    def test_an_empty_feature_tree_is_refused_naming_the_profile(
        self, client: TestClient, run_root: Path
    ) -> None:
        """FR-022: 34 unresolved rules read as a broken part; "this package carries no
        feature tree" reads as the missing extract it is."""
        directory = run_root / "20260916-130000-bare-check"
        save_package(
            model_check_package().model_copy(update={"features": [], "equations": []}),
            directory,
        )

        response = client.post("/checks/rms", json=check_body(directory, document_id=None))

        assert response.status_code == 400
        error = error_of(response)
        assert error["error_class"] == "EmptyFeatureTree"
        assert "model_check" in error["message"]

    def test_an_empty_feature_tree_is_refused_in_the_equations_scope_too(
        self, client: TestClient, run_root: Path
    ) -> None:
        """The route row of `contracts/model-check.md` qualifies the refusal by no scope,
        and the equation rules grade part documents: answering `rms.params.*` over a tree
        nobody read would claim the equation manager is empty on the strength of an
        extract that never opened it."""
        directory = run_root / "20260916-140000-bare-check"
        save_package(
            model_check_package().model_copy(update={"features": [], "equations": []}),
            directory,
        )

        response = client.post(
            "/checks/rms",
            json=check_body(directory, scope="equations", document_id=None),
        )

        assert response.status_code == 400
        error = error_of(response)
        assert error["error_class"] == "EmptyFeatureTree"
        assert "model_check" in error["message"]

    def test_an_unreadable_carry_forward_candidate_refuses_the_run(
        self, client: TestClient, check_dir: Path, run_root: Path
    ) -> None:
        """RK-18: an exception store nobody can read must never be read as an empty one,
        which would silently re-raise a condition somebody already accepted."""
        sibling_run(run_root, "20260915-173001-cover-check", exceptions="{not json")

        response = client.post("/checks/rms", json=check_body(check_dir))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "UnreadableExceptions"

    def test_the_assembly_scope_is_refused_rather_than_silently_evaluating_nothing(
        self, client: TestClient, check_dir: Path
    ) -> None:
        response = client.post("/checks/rms", json=check_body(check_dir, scope="assembly"))

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "ScopeNotAvailable"

    def test_an_unknown_scope_is_refused_naming_what_is_offered(
        self, client: TestClient, check_dir: Path
    ) -> None:
        response = client.post("/checks/rms", json=check_body(check_dir, scope="sketches"))

        assert response.status_code == 400
        assert "part" in error_of(response)["message"]

    def test_a_missing_scope_is_refused_rather_than_guessed(
        self, client: TestClient, check_dir: Path
    ) -> None:
        body = check_body(check_dir)
        del body["scope"]

        response = client.post("/checks/rms", json=body)

        assert response.status_code == 400

    def test_a_document_the_package_does_not_carry_is_refused(
        self, client: TestClient, check_dir: Path
    ) -> None:
        response = client.post("/checks/rms", json=check_body(check_dir, document_id="doc:99"))

        assert response.status_code == 400
        assert "doc:99" in error_of(response)["message"]

    def test_the_equations_scope_runs_its_own_family(
        self, client: TestClient, check_dir: Path
    ) -> None:
        start_check(client, check_dir, scope="equations", document_id=None)

        session = load_session(check_dir / SESSION_FILE)
        assert [step.tool for step in session.steps] == ["check_rms_equations"]


# --- 3. the door, on the new routes -----------------------------------------------


CHECK_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", "/checks/rms"),
    ("GET", f"/checks/{CHECK_ID}"),
    ("POST", f"/checks/{CHECK_ID}/exceptions/F-002"),
)


class TestTheDoor:
    @pytest.mark.parametrize(("method", "path"), CHECK_ROUTES)
    def test_no_token_is_401(self, app: Any, method: str, path: str) -> None:
        with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
            response = anonymous.request(method, path, json={})

        assert response.status_code == 401
        assert error_of(response)["error_class"] == "Unauthorized"

    @pytest.mark.parametrize(("method", "path"), CHECK_ROUTES)
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

    @pytest.mark.parametrize(("_method", "path"), CHECK_ROUTES)
    def test_the_preflight_is_answered_without_a_token(
        self, app: Any, _method: str, path: str
    ) -> None:
        """A preflight never carries author headers, so asking for one would make every
        call from the page fail before it was made."""
        with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
            response = anonymous.options(path)

        assert response.status_code == 204
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["access-control-allow-private-network"] == "true"

    def test_the_exact_origin_is_echoed_on_a_check(
        self, client: TestClient, check_dir: Path
    ) -> None:
        response = client.post("/checks/rms", json=check_body(check_dir))

        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["vary"] == "Origin"


# --- 4. GET /checks/{check_id} ----------------------------------------------------


class TestReadCheck:
    def test_the_same_result_comes_back_from_the_folder(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """The folder name is the whole registry: a restarted pane reads its last check
        back by name, and gets the evaluation of what is in the folder now."""
        posted = start_check(client, check_dir)

        response = client.get(f"/checks/{CHECK_ID}")

        assert response.status_code == 200, response.text
        got = response.json()
        for field in ("check_id", "run_dir", "document", "profile", "extracted_at", "grade"):
            assert got[field] == posted[field]
        assert rows_by_rule(got).keys() == rows_by_rule(posted).keys()
        assert got["subjects"] == posted["subjects"]
        assert got["coverage"] == posted["coverage"]
        assert got["attention"] == posted["attention"]

    def test_the_carry_forward_reports_the_folder_s_own_store_on_a_re_read(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """A re-read carries nothing forward, and says so: the folder already holds this
        check's own evidence, which is a different statement from "there was none"."""
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)
        assert accept(client, CHECK_ID, finding_id).status_code == 200

        carried = client.get(f"/checks/{CHECK_ID}").json()["exceptions_carried_forward"]

        assert carried["from_run"] is None
        assert "already carries" in carried["reason"]

    def test_a_re_read_does_not_rewrite_the_folder(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """`GET` answers from the folder (`contracts/model-check.md` section 1).

        A re-evaluation would write a new `session.json` - a new session id, a new
        `report.md` - every time a page was refreshed, over evidence `swreview exceptions
        accept` reads by name. `attention.json` is in the list for the same reason and one
        more: the ranking a `GET` answers with is recomputed in memory, so a read must not
        refresh the record of the order the engineer was actually shown (FR-022, R2.7).
        """
        posted = start_check(client, check_dir)
        before = {
            name: (check_dir / name).read_bytes()
            for name in (SESSION_FILE, REPORT_FILE, CHECK_FILE, ATTENTION_FILE)
        }

        response = client.get(f"/checks/{CHECK_ID}")

        assert response.status_code == 200, response.text
        assert response.json() == posted
        assert {name: (check_dir / name).read_bytes() for name in before} == before

    def test_a_disposition_recorded_on_the_check_survives_a_re_read(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """The decision an engineer recorded on a finding is in `session.json` and nowhere
        else; a read that re-ran the rules would silently destroy it."""
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)
        apply_disposition(
            check_dir,
            finding_id,
            decision="accepted",
            note="the owner accepted this at the desk",
            by="a.engineer",
        )

        assert client.get(f"/checks/{CHECK_ID}").status_code == 200

        finding = find_finding(load_session(check_dir / SESSION_FILE), finding_id)
        assert finding.disposition is not None
        assert finding.disposition.decision == "accepted"

    def test_an_unknown_check_is_404(self, client: TestClient, check_dir: Path) -> None:
        response = client.get("/checks/20260916-999999-nothing-check")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"

    def test_a_folder_no_check_ever_wrote_is_404(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """A dumped folder is not a check: reading it would run one, and "no such check"
        is what the caller asked about."""
        response = client.get(f"/checks/{CHECK_ID}")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"


# --- 5. POST /checks/{check_id}/exceptions/{finding_id} ---------------------------


def accepted_store(check_dir: Path) -> str:
    """The text of an `exceptions.json` accepting `FAIL_RULE` on the cover."""
    package = load_package(check_dir).package
    store = ExceptionStore(check_dir.parent.parent / "scratch" / EXCEPTIONS_FILE_NAME)
    store.accept(
        _AcceptedFinding(
            check=FAIL_RULE,
            component_ids=[
                component.id
                for component in package.components
                if component.document_id == COVER
            ],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note="legacy tree, accepted by the owner",
    )
    return store.save().read_text(encoding="utf-8")


class _AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    def __init__(self, check: str, component_ids: list[str], configuration: str) -> None:
        self.check = check
        self.component_ids = component_ids
        self.configuration = configuration


class TestAcceptException:
    def test_accepting_re_renders_the_finding_as_checked_within_scope(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """Never hidden (Principle VI): the rule keeps its row and carries the exception
        id and the note that silenced it."""
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)

        response = accept(client, CHECK_ID, finding_id)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["exception_id"].startswith("EX-")
        assert body["finding"]["finding"]["id"] == finding_id
        assert body["finding"]["finding"]["status"] == "checked_within_scope"
        assert body["finding"]["finding"]["exception_id"] == body["exception_id"]
        assert body["finding"]["exception"]["state"] == "active"
        assert body["finding"]["exception"]["note"] == "legacy tree, accepted by the owner"

    def test_the_exception_is_written_beside_the_package_bound_to_the_feature_tree(
        self, client: TestClient, check_dir: Path
    ) -> None:
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)

        accept(client, CHECK_ID, finding_id)

        store = ExceptionStore(check_dir / EXCEPTIONS_FILE_NAME).load()
        [exception] = store.exceptions
        assert exception.check == FAIL_RULE
        assert exception.fingerprint_kind == "feature_tree"
        assert exception.accepted_by == "a.engineer"
        assert exception.note == "legacy tree, accepted by the owner"

    def test_the_report_is_re_rendered(self, client: TestClient, check_dir: Path) -> None:
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)

        exception_id = accept(client, CHECK_ID, finding_id).json()["exception_id"]

        assert exception_id in (check_dir / REPORT_FILE).read_text(encoding="utf-8")
        session = load_session(check_dir / SESSION_FILE)
        assert {item.exception_id for item in session.findings} == {None, exception_id}

    def test_the_re_read_after_an_accept_carries_the_re_ranked_attention(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """Accept re-runs the whole check, so it lands back on `write_report` and the
        record is rewritten with it; the waived rule now sorts last as checked within
        scope, and the body a page re-reads says so (FR-022)."""
        before = start_check(client, check_dir)
        finding_id = finding_id_of(before, FAIL_RULE)

        accept(client, CHECK_ID, finding_id)

        after = client.get(f"/checks/{CHECK_ID}").json()["attention"]
        assert after == to_jsonable_python(rank(load_session(check_dir / SESSION_FILE)))
        assert after != before["attention"]
        waived = next(row for row in after["rows"] if row["check"] == FAIL_RULE)
        assert waived["status"] == "checked_within_scope"
        assert waived["key"]["suppressed"] == 1, "a waived rule sorts into the last bucket"
        assert after["rows"][-1]["check"] == FAIL_RULE
        assert (
            next(row for row in before["attention"]["rows"] if row["check"] == FAIL_RULE)["key"][
                "suppressed"
            ]
            == 0
        )

    def test_the_by_defaults_to_the_workstation_user(
        self, client: TestClient, check_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same fallback `swreview exceptions accept` uses; never an empty acceptor."""
        monkeypatch.setenv("USERNAME", "workstation.user")
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)

        accept(client, CHECK_ID, finding_id, by="")

        [exception] = ExceptionStore(check_dir / EXCEPTIONS_FILE_NAME).load().exceptions
        assert exception.accepted_by == "workstation.user"

    def test_a_blank_note_is_refused(self, client: TestClient, check_dir: Path) -> None:
        """An empty note is how waivers rot (`contracts/model-check.md`, section 5)."""
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)

        response = accept(client, CHECK_ID, finding_id, note="   ")

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "EmptyNote"
        assert not (check_dir / EXCEPTIONS_FILE_NAME).exists()

    def test_a_warn_rule_is_refused(self, client: TestClient, check_dir: Path) -> None:
        """FR-016. The page draws no button for one; the route refuses it anyway, because
        a rule that is not waivable must not become waivable through the network."""
        finding_id = finding_id_of(start_check(client, check_dir), WARN_RULE)

        response = accept(client, CHECK_ID, finding_id)

        assert response.status_code == 409
        error = error_of(response)
        assert error["error_class"] == "RuleNotAcceptable"
        assert WARN_RULE in error["message"]

    def test_a_condition_an_active_exception_already_covers_is_refused(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """One condition, one record: `ExceptionStore.match` returns the first non-retired
        match, so a second record for it would be dead as well as untrue."""
        finding_id = finding_id_of(start_check(client, check_dir), FAIL_RULE)
        assert accept(client, CHECK_ID, finding_id).status_code == 200

        response = accept(client, CHECK_ID, finding_id)

        assert response.status_code == 409
        assert error_of(response)["error_class"] == "AlreadyAccepted"
        assert len(ExceptionStore(check_dir / EXCEPTIONS_FILE_NAME).load().exceptions) == 1

    def test_an_unknown_finding_is_404(self, client: TestClient, check_dir: Path) -> None:
        start_check(client, check_dir)

        response = accept(client, CHECK_ID, "F-404")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownFinding"

    def test_an_unknown_check_is_404(self, client: TestClient, check_dir: Path) -> None:
        response = accept(client, "20260916-999999-nothing-check", "F-002")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"

    def test_a_check_folder_with_no_session_is_404(
        self, client: TestClient, check_dir: Path
    ) -> None:
        response = accept(client, CHECK_ID, "F-002")

        assert response.status_code == 404
        assert error_of(response)["error_class"] == "UnknownCheck"


# --- 6. no provider, no key, no network (SC-011) ----------------------------------


class TestNoLanguageModel:
    def test_every_check_route_runs_with_the_provider_factories_raising(
        self, client: TestClient, check_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RK-21: the tab has to work on a workstation with no key at all, so a check
        must not so much as look one up."""
        import swreview.cli as cli_module

        monkeypatch.setattr(providers, "get", refuse_provider)
        monkeypatch.setattr(providers, "call_tool", refuse_provider)
        monkeypatch.setattr(cli_module, "provider_factory", refuse_provider)
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        posted = start_check(client, check_dir)
        assert posted["attention"]["rows"], "the ranking is computed on this keyless path"
        finding_id = finding_id_of(posted, FAIL_RULE)
        assert accept(client, CHECK_ID, finding_id).status_code == 200
        assert client.get(f"/checks/{CHECK_ID}").status_code == 200

    def test_a_check_opens_no_chat_session(
        self, client: TestClient, check_dir: Path, app: Any
    ) -> None:
        """A check has no chat: nothing is registered, so nothing has to be finalized and
        the folder stays available to a review that wants it."""
        start_check(client, check_dir)

        assert app.state.server.chats == {}

    def test_the_run_folder_is_not_claimed_by_the_check(
        self, client: TestClient, check_dir: Path
    ) -> None:
        """`_claim_run_dir` is a chat's rule, not a check's: a check writes `session.json`
        and a second check of the same part must still be able to run."""
        first = start_check(client, check_dir)

        second = start_check(client, check_dir)

        assert rows_by_rule(second).keys() == rows_by_rule(first).keys()


# --- 7. handing the check folder to a review (User Story 6 scenario 11) -----------


class TestAReviewOfACheckFolder:
    def test_a_review_may_claim_the_folder_a_check_wrote(
        self, review_app: Any, check_dir: Path
    ) -> None:
        """The story's last step: the check package is handed to a review.

        One session per run folder exists because two sessions cannot share one
        `events.jsonl` (`_claim_run_dir`), and a check writes no event stream at all - so
        a folder whose only session is a check's own record is claimable, and the review's
        rotation keeps that record as `session.1.json` rather than writing over it.
        """
        with TestClient(
            review_app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        ) as client:
            start_check(client, check_dir)

            response = client.post(
                "/sessions",
                json={
                    "run_dir": str(check_dir),
                    "provider": "fake",
                    "model": "fake-1",
                    "effort": "high",
                    "bridge": None,
                    "engineer": "a.engineer",
                    "retry_of": None,
                },
            )

            assert response.status_code == 201, response.text

        assert (check_dir / "session.1.json").is_file()

    def test_a_folder_a_review_already_holds_is_still_refused(
        self, review_app: Any, check_dir: Path
    ) -> None:
        """The rule the last test relaxes is not removed: a folder holding a review's own
        session is still a 400, because that pair really cannot be shared."""
        (check_dir / SESSION_FILE).write_text("{}", encoding="utf-8")

        with TestClient(
            review_app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        ) as client:
            response = client.post(
                "/sessions",
                json={
                    "run_dir": str(check_dir),
                    "provider": "fake",
                    "model": "fake-1",
                    "effort": "high",
                    "bridge": None,
                    "engineer": "a.engineer",
                    "retry_of": None,
                },
            )

        assert response.status_code == 400
        assert error_of(response)["error_class"] == "InvalidRunDir"


def test_the_error_body_is_the_contract_s(client: TestClient, tmp_path: Path) -> None:
    """Every refusal on these routes is `{error_class, message, retryable}`, so the page
    switches on the class rather than on prose."""
    response = client.post("/checks/rms", json=check_body(tmp_path / "elsewhere"))

    body = json.loads(response.text)
    assert set(body) == {"error_class", "message", "retryable"}
    assert body["retryable"] is False
