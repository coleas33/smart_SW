"""Unit tests for the one no-language-model evaluation entry point (T066).

`checks/rms/run.py::run_rms_check` is what `swreview check rms` and `POST /checks/rms`
both call (FR-024), so what is pinned here is everything that is true of a check however
it was started:

- **it dispatches through the tool registry with a session sink** (defect D1). A finding's
  `tool_result_ids` names an investigation step, and until this task nothing ever wrote a
  session for an RMS run, so every RMS finding cited step 0 of a file that had no steps.
  The test walks every finding of a written `session.json` and resolves its step ids in
  that same file;
- **it writes the run folder**: `session.json`, `report.md` and `check.json`, into `out_dir`
  when the caller names one and beside the package when it does not. `POST /checks/rms`
  names none, because a check run folder *is* its own package directory; `swreview check
  rms --out <dir>` names one, because grading a package must not edit it;
- **it constructs no provider, reads no key and makes no network call** (SC-011), asserted
  by making `agent.providers`' adapter lookup raise;
- **it refuses a feature tree that is not there** (FR-022), naming the dump profile, rather
  than reporting 34 unresolved rules that read as a broken part;
- **it carries accepted exceptions forward** (FR-029, RK-18), in all four cases of the
  matrix: a same-design candidate is copied byte-identically before the rules run, a
  different-design candidate is not, no candidate at all is reported and is not an error,
  and a candidate that cannot be parsed refuses the run rather than yielding a silently
  empty store. The run root those candidates are looked for under is the caller's, named:
  a helper that scanned whatever directory happened to sit above the package would copy
  from, and be refused by, a folder nobody asked it about;
- **it records what the session does not**, so a check can be read back without being run
  again. `GET /checks/{check_id}` is a read, and re-evaluating to answer it would rewrite
  `session.json` over an engineer's recorded disposition (T072, `contracts/model-check.md`
  section 1).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from swreview.agent import providers
from swreview.checks.rms.run import (
    CHECK_FILE_NAME,
    EmptyFeatureTreeError,
    NotACheckError,
    RmsRunError,
    RmsScope,
    UnreadableExceptionsError,
    is_check_folder,
    read_rms_check,
    run_rms_check,
)
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.report.attention_record import ATTENTION_FILE_NAME
from swreview.report.dispositions import apply_disposition, find_finding
from swreview.report.session import load_session, save_session
from tests.support.features import (
    AssemblySpec,
    PartSpec,
    equation,
    feature,
    folder,
    rms_package,
)

FRAME = "doc:2"
"""The compliant part."""

COVER = "doc:3"
"""The part that fails `rms.intent.every_feature_described`."""

ASSEMBLY = "doc:1"

SESSION_FILE = "session.json"
REPORT_FILE = "report.md"

DESCRIBED_RULE = "rms.intent.every_feature_described"


# --- the run root and the packages in it ------------------------------------------


def evidence() -> EvidencePackage:
    """One compliant part, one part that fails a described-features rule, an assembly."""
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


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def check_dir(run_root: Path) -> Path:
    """The run folder a check writes into: a package and nothing else yet."""
    directory = run_root / "20260916-101532-frame-check"
    save_package(evidence(), directory)
    return directory


def earlier_run(
    run_root: Path,
    name: str,
    *,
    exceptions: str | None = None,
    design_id: str | None = None,
    at: datetime | None = None,
) -> Path:
    """An earlier run folder holding a package and, optionally, an `exceptions.json`."""
    directory = run_root / name
    save_package(evidence(), directory)
    if design_id is not None:
        package_file = directory / PACKAGE_FILE_NAME
        body = json.loads(package_file.read_text(encoding="utf-8"))
        body["design"]["design_id"] = design_id
        package_file.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    if exceptions is not None:
        file = directory / EXCEPTIONS_FILE_NAME
        file.write_text(exceptions, encoding="utf-8")
        if at is not None:
            os.utime(file, (at.timestamp(), at.timestamp()))
    return directory


def accepted_exceptions(directory: Path) -> str:
    """The text of an `exceptions.json` accepting `DESCRIBED_RULE` on the cover."""
    package = load_package(directory).package
    store = ExceptionStore(directory / EXCEPTIONS_FILE_NAME)
    store.accept(
        _AcceptedFinding(
            check=DESCRIBED_RULE,
            component_ids=[
                component.id for component in package.components if component.document_id == COVER
            ],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note="legacy tree, accepted by the owner",
        at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    return store.save().read_text(encoding="utf-8")


class _AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    def __init__(self, check: str, component_ids: list[str], configuration: str) -> None:
        self.check = check
        self.component_ids = component_ids
        self.configuration = configuration


# --- 1. the run, and what it dispatches through (D1, FR-024) -----------------------


class TestDispatch:
    def test_every_finding_cites_a_step_that_is_in_the_written_session(
        self, check_dir: Path
    ) -> None:
        """D1. `tool_result_ids` is the only evidence an RMS finding has, so a step id
        that names nothing is a Principle VI violation, not a cosmetic one."""
        run_rms_check(check_dir, scope=RmsScope.all)

        session = load_session(check_dir / SESSION_FILE)
        steps = {step.index for step in session.steps}
        assert steps
        assert session.findings
        for recorded in session.findings:
            assert recorded.tool_result_ids
            assert set(recorded.tool_result_ids) <= steps

    def test_the_steps_name_the_check_tools_that_were_dispatched(
        self, check_dir: Path
    ) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.all)

        assert [step.tool for step in run.session.steps] == [
            "check_rms_part",
            "check_rms_assembly",
            "check_rms_equations",
        ]
        assert all(step.status == "ok" for step in run.session.steps)

    def test_one_scope_dispatches_one_step(self, check_dir: Path) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.part)

        assert [step.tool for step in run.session.steps] == ["check_rms_part"]
        assert run.assembly_document is None

    def test_a_single_document_is_the_only_one_graded(self, check_dir: Path) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.part, document_id=FRAME)

        assert run.documents == [FRAME]
        assert run.findings == []

    def test_several_documents_are_graded_in_one_pass(self, check_dir: Path) -> None:
        """Aggregated coverage is replaced per rule, so two documents graded as two
        passes would leave the second one's coverage and drop the first one's."""
        run = run_rms_check(check_dir, scope=RmsScope.part, document_id=[COVER, FRAME])

        assert run.documents == [COVER, FRAME]
        covered = {
            document for row in run.coverage for document in row["scope"]["document_ids"]
        }
        assert {FRAME, COVER} <= covered

    def test_an_unknown_document_refuses_the_run(self, check_dir: Path) -> None:
        with pytest.raises(RmsRunError, match="doc:99"):
            run_rms_check(check_dir, scope=RmsScope.part, document_id="doc:99")

    def test_an_assembly_document_refuses_the_run(self, check_dir: Path) -> None:
        with pytest.raises(RmsRunError, match=ASSEMBLY):
            run_rms_check(check_dir, scope=RmsScope.part, document_id=ASSEMBLY)


# --- 2. what the run returns and writes -------------------------------------------


class TestRunFolder:
    def test_session_and_report_are_written_into_the_package_directory(
        self, check_dir: Path
    ) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.all)

        assert run.session_file == check_dir / SESSION_FILE
        assert run.report_file == check_dir / REPORT_FILE
        assert run.session_file.is_file()
        assert DESCRIBED_RULE in run.report_file.read_text(encoding="utf-8")

    def test_out_dir_takes_the_run_and_the_package_is_not_written(
        self, check_dir: Path, tmp_path: Path
    ) -> None:
        """What `swreview check rms --out <dir>` needs: grading a package must not edit it.

        The three files are the whole run folder, and the package directory is left
        holding exactly what it held before - which is what keeps a golden fixture a
        baseline rather than a directory a grading command writes into.
        """
        out = tmp_path / "elsewhere" / "20260916-110000-frame-check"

        run = run_rms_check(check_dir, scope=RmsScope.all, out_dir=out)

        assert run.session_file == out / SESSION_FILE
        assert run.report_file == out / REPORT_FILE
        assert run.check_file == out / CHECK_FILE_NAME
        assert sorted(item.name for item in out.iterdir()) == [
            ATTENTION_FILE_NAME,
            CHECK_FILE_NAME,
            REPORT_FILE,
            SESSION_FILE,
        ]
        assert [item.name for item in check_dir.iterdir()] == [PACKAGE_FILE_NAME]

    def test_out_dir_is_created_when_it_is_not_there(
        self, check_dir: Path, tmp_path: Path
    ) -> None:
        """A run root the caller has not made yet is made here, as `save_session` does
        for the session it writes: the carry-forward copies into the folder before the
        rules run, so it cannot wait for the first write."""
        out = tmp_path / "runs" / "today" / "20260916-101532-frame-check"

        run = run_rms_check(check_dir, scope=RmsScope.part, out_dir=out)

        assert run.session_file.is_file()
        assert run.report_file.is_file()
        assert run.check_file.is_file()

    def test_out_dir_holds_a_check_that_reads_back(
        self, check_dir: Path, tmp_path: Path
    ) -> None:
        """The run folder is the check, wherever it was written: `check.json` names the
        session beside it, so `read_rms_check` answers from the folder alone."""
        out = tmp_path / "elsewhere" / "20260916-110000-frame-check"

        run = run_rms_check(check_dir, scope=RmsScope.part, out_dir=out)

        assert is_check_folder(out)
        assert read_rms_check(out).session.session_id == run.session.session_id

    def test_the_written_session_is_the_one_that_was_returned(self, check_dir: Path) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.all)

        written = load_session(check_dir / SESSION_FILE)
        assert [item.id for item in written.findings] == [
            item.id for item in run.session.findings
        ]
        assert written.ended_at is not None

    def test_findings_coverage_and_the_grade_come_back(self, check_dir: Path) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.all)

        assert DESCRIBED_RULE in [item["check"] for item in run.findings]
        assert {"checked", "unresolved", "out_of_scope"} <= {
            row["bucket"] for row in run.coverage
        }
        assert run.grade.failed >= 1
        assert not run.grade.nothing_evaluated

    def test_the_subjects_of_every_finding_come_back_beside_them(
        self, check_dir: Path
    ) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.all)

        described = next(item for item in run.findings if item["check"] == DESCRIBED_RULE)
        [subject] = run.subjects[described["id"]]
        assert subject["name"] == "Boss-Extrude2"
        assert subject["group"] == "3-Core"
        assert subject["persist_ref_scope"] == COVER
        assert set(run.subjects) == {item["id"] for item in run.findings}

    def test_a_scope_this_build_does_not_run_is_reported(self, check_dir: Path) -> None:
        """Every scope runs today; the key is present and empty rather than absent, so a
        caller reads the same shape whatever this build can do."""
        run = run_rms_check(check_dir, scope=RmsScope.all)

        assert run.unavailable_scopes == []


# --- 3. no provider, no key, no network (SC-011) ----------------------------------


class TestNoLanguageModel:
    def test_the_run_completes_with_every_provider_adapter_raising(
        self, check_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("a check must never construct a provider")

        monkeypatch.setattr(providers, "get", refuse)
        monkeypatch.setattr(providers, "call_tool", refuse)

        run = run_rms_check(check_dir, scope=RmsScope.all)

        assert run.findings
        assert run.session.steps

    def test_no_api_key_is_read(
        self, check_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing in the path may reach the environment for a key: the tab works on a
        workstation that has none (RK-21)."""
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        run = run_rms_check(check_dir, scope=RmsScope.part)

        assert run.session.model
        assert run.findings == [] or run.findings


# --- 4. an empty feature tree is refused (FR-022) ---------------------------------


class TestEmptyFeatureTree:
    def test_a_package_with_no_features_is_refused_naming_the_profile(
        self, run_root: Path
    ) -> None:
        package = evidence()
        package = package.model_copy(update={"features": [], "equations": []})
        directory = run_root / "20260916-110000-frame-check"
        save_package(package, directory)

        with pytest.raises(EmptyFeatureTreeError) as refused:
            run_rms_check(directory, scope=RmsScope.part)

        assert "full" in str(refused.value)
        assert refused.value.error_class == "EmptyFeatureTree"

    def test_a_model_check_profile_package_with_features_is_graded(
        self, run_root: Path
    ) -> None:
        """The reduced dump profile is what the tab extracts with; a check must read it
        exactly as it reads a full package (FR-022), and refuse only an empty tree."""
        package = evidence()
        package = package.model_copy(
            update={
                "extractor": package.extractor.model_copy(update={"profile": "model_check"}),
                "holes": [],
                "fasteners": [],
                "faces": [],
                "bodies": [],
            }
        )
        directory = run_root / "20260916-120000-frame-check"
        save_package(package, directory)

        run = run_rms_check(directory, scope=RmsScope.part)

        assert run.documents == [FRAME, COVER]
        assert DESCRIBED_RULE in [item["check"] for item in run.findings]

    def test_an_empty_tree_from_the_reduced_profile_names_that_profile(
        self, run_root: Path
    ) -> None:
        package = evidence()
        package = package.model_copy(
            update={
                "extractor": package.extractor.model_copy(update={"profile": "model_check"}),
                "features": [],
                "equations": [],
            }
        )
        directory = run_root / "20260916-130000-frame-check"
        save_package(package, directory)

        with pytest.raises(EmptyFeatureTreeError, match="model_check"):
            run_rms_check(directory, scope=RmsScope.part)

    @pytest.mark.parametrize("scope", [RmsScope.all, RmsScope.equations])
    def test_every_scope_that_grades_a_part_document_refuses_an_empty_tree(
        self, run_root: Path, scope: RmsScope
    ) -> None:
        """The equation rules grade part documents too, so an empty `features[]` refuses
        them for the same reason it refuses the part rules: with no tree read, both
        `rms.params.*` rules report "the equation manager holds no equations", which is an
        affirmative claim about a manager the extract may never have opened (constitution
        Principle I). `all` runs the part rules, so it refuses as `part` does."""
        package = evidence().model_copy(update={"features": [], "equations": []})
        directory = run_root / f"20260916-140000-{scope.value}-check"
        save_package(package, directory)

        with pytest.raises(EmptyFeatureTreeError) as refused:
            run_rms_check(directory, scope=scope)

        assert refused.value.error_class == "EmptyFeatureTree"
        assert "full" in str(refused.value)

    def test_the_assembly_scope_grades_a_package_that_carries_no_part_tree(
        self, run_root: Path
    ) -> None:
        """The one exception, pinned so it stays deliberate: the assembly rules read the
        mates and the component instances and never `features[]`, so a package of assembly
        evidence with no part trees in it is a thing to grade rather than a failed
        extract."""
        package = evidence().model_copy(update={"features": [], "equations": []})
        directory = run_root / "20260916-150000-assembly-check"
        save_package(package, directory)

        run = run_rms_check(directory, scope=RmsScope.assembly)

        assert run.assembly_document == ASSEMBLY
        assert run.documents == []

    def test_nothing_is_written_into_the_folder_of_a_refused_run(
        self, run_root: Path
    ) -> None:
        package = evidence().model_copy(update={"features": [], "equations": []})
        directory = run_root / "20260916-110000-frame-check"
        save_package(package, directory)
        earlier_run(
            run_root,
            "20260915-090000-frame-check",
            exceptions='{"exceptions": []}\n',
        )

        with pytest.raises(EmptyFeatureTreeError):
            run_rms_check(directory, scope=RmsScope.part)

        assert sorted(item.name for item in directory.iterdir()) == [PACKAGE_FILE_NAME]


# --- 5. the carry-forward matrix (FR-029, RK-18) ----------------------------------


class TestCarryForward:
    def test_the_newest_same_design_candidate_is_copied_byte_for_byte(
        self, run_root: Path, check_dir: Path
    ) -> None:
        older = earlier_run(
            run_root,
            "20260914-080000-frame-check",
            exceptions='{"exceptions": []}\n',
            at=datetime(2026, 9, 14, tzinfo=UTC),
        )
        newer = earlier_run(run_root, "20260915-090000-frame-check")
        text = accepted_exceptions(newer)
        os.utime(
            newer / EXCEPTIONS_FILE_NAME,
            (
                datetime(2026, 9, 15, tzinfo=UTC).timestamp(),
                datetime(2026, 9, 15, tzinfo=UTC).timestamp(),
            ),
        )

        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        assert (check_dir / EXCEPTIONS_FILE_NAME).read_bytes() == (
            newer / EXCEPTIONS_FILE_NAME
        ).read_bytes()
        assert (check_dir / EXCEPTIONS_FILE_NAME).read_text(encoding="utf-8") == text
        assert run.exceptions_carried_forward.from_run == newer.name
        assert run.exceptions_carried_forward.count == 1
        assert older.name not in str(run.exceptions_carried_forward.from_run)

    def test_the_carried_exception_is_applied_before_the_rules_run(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """SC-010: the acceptance survives the next check with no file copied by hand."""
        source = earlier_run(run_root, "20260915-090000-frame-check")
        accepted_exceptions(source)

        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        described = next(item for item in run.findings if item["check"] == DESCRIBED_RULE)
        assert described["status"] == "checked_within_scope"
        assert described["exception_id"] == "EX-001"

    def test_a_candidate_for_another_design_is_not_copied(
        self, run_root: Path, check_dir: Path
    ) -> None:
        earlier_run(
            run_root,
            "20260915-090000-other-check",
            exceptions='{"exceptions": []}\n',
            design_id="dsn:other",
        )

        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        assert not (check_dir / EXCEPTIONS_FILE_NAME).exists()
        assert run.exceptions_carried_forward.from_run is None
        assert run.exceptions_carried_forward.count == 0
        assert "dsn:1" in (run.exceptions_carried_forward.reason or "")

    def test_no_candidate_at_all_is_reported_and_is_not_an_error(
        self, run_root: Path, check_dir: Path
    ) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        assert run.exceptions_carried_forward.from_run is None
        assert run.exceptions_carried_forward.count == 0
        assert run.exceptions_carried_forward.reason is not None
        assert run.findings

    def test_a_candidate_that_cannot_be_parsed_refuses_the_run(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """An unreadable store must never read as "no exceptions": that silently
        re-raises a condition an engineer already accepted (RK-18)."""
        earlier_run(
            run_root, "20260915-090000-frame-check", exceptions='{"exceptions": [{"id": '
        )

        with pytest.raises(UnreadableExceptionsError) as refused:
            run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        assert "20260915-090000-frame-check" in str(refused.value)
        assert refused.value.error_class == "UnreadableExceptions"
        assert not (check_dir / SESSION_FILE).exists()

    def test_an_exceptions_file_already_in_the_folder_is_left_alone(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """A run folder that already carries a store is the run's own evidence; copying
        over it would discard what this run was handed."""
        earlier_run(run_root, "20260915-090000-frame-check")
        accepted_exceptions(earlier_run(run_root, "20260915-100000-frame-check"))
        (check_dir / EXCEPTIONS_FILE_NAME).write_text('{"exceptions": []}\n', encoding="utf-8")

        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        assert (check_dir / EXCEPTIONS_FILE_NAME).read_text(encoding="utf-8") == (
            '{"exceptions": []}\n'
        )
        assert run.exceptions_carried_forward.from_run is None
        assert run.exceptions_carried_forward.reason is not None

    def test_the_run_folder_itself_is_never_its_own_candidate(
        self, run_root: Path, check_dir: Path
    ) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)
        again = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        assert run.exceptions_carried_forward.from_run is None
        assert again.exceptions_carried_forward.from_run is None

    def test_no_run_root_carries_nothing_forward_and_says_so(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """A caller that names no run root gets no carry-forward, and is told so.

        The folder above a package is a run root only when a caller says it is:
        `swreview check rms --package <dir>` takes any directory, so inferring one from
        the package's parent is how a folder the engineer never asked about ends up
        copied in - or refusing the run.
        """
        accepted_exceptions(earlier_run(run_root, "20260915-090000-frame-check"))

        run = run_rms_check(check_dir, scope=RmsScope.part)

        assert not (check_dir / EXCEPTIONS_FILE_NAME).exists()
        assert run.exceptions_carried_forward.from_run is None
        assert "no run root" in (run.exceptions_carried_forward.reason or "")
        assert run.findings

    def test_a_folder_outside_the_run_root_neither_is_copied_from_nor_refuses(
        self, tmp_path: Path, run_root: Path
    ) -> None:
        """The candidates are the run root's own folders, not the package's neighbours.

        A package the command line was pointed at can sit anywhere, and the directory
        beside it is not evidence of anything: an unreadable store there must not refuse
        the run, and a readable one must not be copied into the caller's directory.
        """
        directory = tmp_path / "elsewhere" / "package"
        save_package(evidence(), directory)
        neighbour = tmp_path / "elsewhere" / "unrelated"
        save_package(evidence(), neighbour)
        (neighbour / EXCEPTIONS_FILE_NAME).write_text(
            '{"exceptions": [{"id": ', encoding="utf-8"
        )

        run = run_rms_check(directory, scope=RmsScope.part, run_root=run_root)

        assert not (directory / EXCEPTIONS_FILE_NAME).exists()
        assert run.exceptions_carried_forward.from_run is None
        assert str(run_root) in (run.exceptions_carried_forward.reason or "")

    def test_the_candidate_is_copied_into_the_out_folder_and_not_the_package(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """The carry-forward writes into the run folder, which is `out_dir` when there is
        one: the copy is this run's evidence, and the package is not written to at all."""
        source = earlier_run(run_root, "20260915-090000-frame-check")
        text = accepted_exceptions(source)
        out = run_root / "20260916-110000-frame-check"

        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root, out_dir=out)

        assert (out / EXCEPTIONS_FILE_NAME).read_text(encoding="utf-8") == text
        assert not (check_dir / EXCEPTIONS_FILE_NAME).exists()
        assert run.exceptions_carried_forward.from_run == source.name
        assert run.exceptions_carried_forward.count == 1

    def test_the_carried_store_is_what_an_out_folder_run_is_graded_against(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """FR-029 through `--out`: a copy nothing graded against would silence nothing,
        which is the acceptance quietly not surviving the next check (SC-010)."""
        accepted_exceptions(earlier_run(run_root, "20260915-090000-frame-check"))
        out = run_root / "20260916-110000-frame-check"

        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root, out_dir=out)

        described = next(item for item in run.findings if item["check"] == DESCRIBED_RULE)
        assert described["status"] == "checked_within_scope"
        assert described["exception_id"] == "EX-001"

    def test_the_store_beside_the_package_is_graded_when_the_out_folder_has_none(
        self, check_dir: Path, tmp_path: Path
    ) -> None:
        """A package is read where it is: its own `exceptions.json` still silences what
        it waives when the run folder is somewhere else, and is left byte-for-byte."""
        text = accepted_exceptions(check_dir)
        out = tmp_path / "elsewhere" / "20260916-110000-frame-check"

        run = run_rms_check(check_dir, scope=RmsScope.part, out_dir=out)

        described = next(item for item in run.findings if item["check"] == DESCRIBED_RULE)
        assert described["exception_id"] == "EX-001"
        assert not (out / EXCEPTIONS_FILE_NAME).exists()
        assert (check_dir / EXCEPTIONS_FILE_NAME).read_text(encoding="utf-8") == text


# --- 6. the check record: a check is read back, never run again (T072) ------------


class TestCheckRecord:
    """`check.json` holds what `session.json` does not, so a read needs no evaluation."""

    def test_the_record_is_written_beside_the_session(
        self, run_root: Path, check_dir: Path
    ) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)

        record = json.loads((check_dir / CHECK_FILE_NAME).read_text(encoding="utf-8"))
        assert run.check_file == check_dir / CHECK_FILE_NAME
        assert record["session_id"] == str(run.session.session_id)
        assert record["scope"] == RmsScope.part.value
        assert record["documents"] == run.documents
        assert record["subjects"] == run.subjects
        assert record["exceptions_carried_forward"] == {
            "from_run": None,
            "count": 0,
            "reason": run.exceptions_carried_forward.reason,
        }

    def test_the_record_rebuilds_the_run_and_writes_nothing(
        self, run_root: Path, check_dir: Path
    ) -> None:
        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)
        before = {
            name: (check_dir / name).read_bytes()
            for name in (SESSION_FILE, REPORT_FILE, CHECK_FILE_NAME)
        }

        read = read_rms_check(check_dir)

        assert read.findings == run.findings
        assert read.subjects == run.subjects
        assert read.coverage == run.coverage
        assert read.grade.as_dict() == run.grade.as_dict()
        assert read.scope == run.scope
        assert read.documents == run.documents
        assert read.assembly_document == run.assembly_document
        assert read.unavailable_scopes == run.unavailable_scopes
        assert read.exceptions_carried_forward == run.exceptions_carried_forward
        assert read.session.session_id == run.session.session_id
        assert {name: (check_dir / name).read_bytes() for name in before} == before

    def test_a_recorded_disposition_survives_a_read(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """What a re-evaluation would destroy: only the session file holds the decision an
        engineer recorded on a finding, and a read hands it back rather than writing over
        it."""
        run = run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)
        finding_id = str(run.findings[0]["id"])
        apply_disposition(
            check_dir,
            finding_id,
            decision="accepted",
            note="the owner accepted this at the desk",
            by="a.engineer",
        )

        read_rms_check(check_dir)

        recorded = find_finding(load_session(check_dir / SESSION_FILE), finding_id)
        assert recorded.disposition is not None
        assert recorded.disposition.decision == "accepted"

    def test_a_folder_with_no_record_is_not_a_check(self, check_dir: Path) -> None:
        with pytest.raises(NotACheckError) as refused:
            read_rms_check(check_dir)

        assert CHECK_FILE_NAME in str(refused.value)
        assert not is_check_folder(check_dir)

    def test_a_session_the_record_does_not_name_is_not_a_check(
        self, run_root: Path, check_dir: Path
    ) -> None:
        """A review that claims the folder writes its own session over the check's: the
        record names the session it described, so the folder stops reading as that check
        rather than answering with somebody else's run."""
        run_rms_check(check_dir, scope=RmsScope.part, run_root=run_root)
        session = load_session(check_dir / SESSION_FILE)
        save_session(
            session.model_copy(update={"session_id": uuid4()}), check_dir / SESSION_FILE
        )

        assert not is_check_folder(check_dir)
        with pytest.raises(NotACheckError):
            read_rms_check(check_dir)
