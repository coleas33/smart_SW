"""The dump and grade artifacts of one re-model run (T090).

`remodel/artifacts.py` writes five of the files in `contracts/run-artifacts.md`:
`package-before.json` and `package-after.json` (the `ModelCheck`-profile dumps of the
**copy**, handed in by the caller that took them), `rms-before.json` and `rms-after.json`
(feature 003's `run_rms_check` over each of them), and `grades.json` (feature 003's
`RmsGrade` before and after, plus the per-rule delta).

Nothing here re-implements feature 003. What is pinned is what feature 004 adds around it,
and every claim below is one a run could get silently wrong:

- **no provider is constructed on any path** (SC-011 for the re-modeler, FR-024). The
  adapter lookup is made to raise for every test in this module, not just one, so a grade
  that reached a model would fail the whole file;
- **the grade is 003's**, rendered through `RmsGrade.as_dict`: counts per bucket as the
  headline, the fraction secondary, the unresolved rule ids always named beside it, and
  **no letter grade** anywhere in the artifact;
- **the exceptions carry-forward matches on the source's `design_id`, never on this run's
  own.** This run's packages are dumps of the copy, whose path - and so whose path-derived
  `design_id` - is unique to the run, so matching on the package's own id would select no
  candidate, ever. The two candidate kinds are read differently: a feature 003 `-check`
  folder from its `package.json`, a prior `-remodel` folder from its
  `source-attestation.json`;
- **rebind, then freeze.** A carried exception is bound to `(persist_ref, persist_ref_scope)`
  pairs and the scope is a path-derived `document_id`, so a carried exception still naming
  the source resolves to nothing against a dump of the copy. The scopes are rewritten to
  the copy's document before the rules run, and `ExceptionStore.refresh` runs **once**,
  against `package-before.json`, with the resulting store handed unchanged to **both**
  grades. The teeth of that last claim are here: a second refresh against
  `package-after.json` is shown to re-open the waiver, which is exactly the delta moving
  for the wrong reason.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import providers
from swreview.checks.rms.grade import BUCKETS
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import PACKAGE_FILE_NAME, save_package
from swreview.ir.models import EvidencePackage
from swreview.remodel.artifacts import (
    ATTESTATION_FILE_NAME,
    GRADES_FILE_NAME,
    PACKAGE_AFTER,
    RMS_AFTER_FILE_NAME,
    RMS_BEFORE_FILE_NAME,
    NotAModelCheckDumpError,
    carry_forward_exceptions,
    grade_remodel_run,
    write_package,
)
from swreview.remodel.plan import PACKAGE_BEFORE
from tests.support.features import FeatureSpec, feature, folder
from tests.support.remodel import remodel_package

COPY_DOCUMENT = "doc:copy"
"""The copy's path-derived document id: the only document this run ever dumps."""

SOURCE_DOCUMENT = "doc:source"
SOURCE_DESIGN = "dsn:source"
COPY_DESIGN = "dsn:copy"
OTHER_DESIGN = "dsn:other"

RUN_NAME = "20260916-142201-bracket-remodel"
DESCRIBED_RULE = "rms.intent.every_feature_described"
"""The rule the carried waiver was granted for: one feature with a blank description."""


# --- the trees -------------------------------------------------------------------


def before_features() -> list[FeatureSpec]:
    """The copy at open: one undescribed core feature, which fails `DESCRIBED_RULE`."""
    return [
        folder("3-Core", feature("Boss-Extrude1", "Extrusion", description="")),
        folder("4-Detail", feature("Hole1", "HoleWzd")),
    ]


def after_features() -> list[FeatureSpec]:
    """The copy at end: the waived feature renamed and reordered, still undescribed.

    Renamed *and* moved on purpose. `fingerprint_kind_for` makes every `rms.*` exception a
    `feature_tree` fingerprint whose digest covers every feature row in index order, so
    this tree is precisely the one a second `refresh` would re-open the waiver over.
    """
    return [
        folder("4-Detail", feature("Hole1", "HoleWzd")),
        folder("3-Core", feature("Boss-Extrude1_2", "Extrusion", description="")),
    ]


def package_of(features: Sequence[FeatureSpec], document_id: str) -> EvidencePackage:
    return remodel_package(list(features), document_id=document_id, name="bracket-RMS")


def before_package() -> EvidencePackage:
    return package_of(before_features(), COPY_DOCUMENT)


def after_package() -> EvidencePackage:
    return package_of(after_features(), COPY_DOCUMENT)


def source_package() -> EvidencePackage:
    """The dump of the engineer's own file an earlier Model check graded."""
    return package_of(before_features(), SOURCE_DOCUMENT)


# --- the run folder and its neighbours --------------------------------------------


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def run_dir(run_root: Path) -> Path:
    directory = run_root / RUN_NAME
    directory.mkdir()
    return directory


@pytest.fixture(autouse=True)
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-011 for every test in this file: the grade reaches no model, ever."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the grade artifacts must never construct a provider")

    monkeypatch.setattr(providers, "get", refuse)
    monkeypatch.setattr(providers, "call_tool", refuse)


def accepted_store(path: Path, package: EvidencePackage) -> ExceptionStore:
    """A store waiving `DESCRIBED_RULE` on `package`, saved at `path`."""
    store = ExceptionStore(path)
    store.accept(
        _AcceptedFinding(
            check=DESCRIBED_RULE,
            component_ids=[component.id for component in package.components],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note="legacy tree, accepted by the owner",
        at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store.save()
    return store


class _AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    def __init__(self, check: str, component_ids: list[str], configuration: str) -> None:
        self.check = check
        self.component_ids = component_ids
        self.configuration = configuration


def check_run(
    run_root: Path,
    name: str,
    *,
    design_id: str,
    exceptions: Path | None = None,
    at: datetime | None = None,
) -> Path:
    """An earlier feature 003 `-check` folder: a dump of the source, and a store."""
    directory = run_root / name
    save_package(source_package(), directory)
    _stamp_design_id(directory / PACKAGE_FILE_NAME, design_id)
    if exceptions is not None:
        _place(exceptions, directory / EXCEPTIONS_FILE_NAME, at)
    return directory


def remodel_run(
    run_root: Path,
    name: str,
    *,
    source_design_id: str,
    exceptions: Path | None = None,
    at: datetime | None = None,
) -> Path:
    """An earlier `-remodel` folder: its packages are dumps of *its* copy, and its
    source's design id is in `source-attestation.json` and nowhere else."""
    directory = run_root / name
    directory.mkdir(parents=True, exist_ok=True)
    save_package(before_package(), directory)
    _stamp_design_id(directory / PACKAGE_FILE_NAME, COPY_DESIGN)
    (directory / ATTESTATION_FILE_NAME).write_text(
        json.dumps({"path": "C:\\work\\bracket.SLDPRT", "source_design_id": source_design_id}),
        encoding="utf-8",
    )
    if exceptions is not None:
        _place(exceptions, directory / EXCEPTIONS_FILE_NAME, at)
    return directory


def _stamp_design_id(package_file: Path, design_id: str) -> None:
    body = json.loads(package_file.read_text(encoding="utf-8"))
    body["design"]["design_id"] = design_id
    package_file.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def _place(source: Path, target: Path, at: datetime | None) -> None:
    target.write_bytes(source.read_bytes())
    if at is not None:
        os.utime(target, (at.timestamp(), at.timestamp()))


def graded(run_dir: Path, run_root: Path | None = None, **overrides: Any) -> Any:
    """One graded run over the two trees, with the usual arguments."""
    return grade_remodel_run(
        run_dir,
        before=overrides.pop("before", before_package()),
        after=overrides.pop("after", after_package()),
        source_design_id=overrides.pop("source_design_id", SOURCE_DESIGN),
        run_root=run_root,
        **overrides,
    )


# --- 1. the two dumps -------------------------------------------------------------


class TestPackages:
    def test_both_dumps_are_written_under_their_contract_names(self, run_dir: Path) -> None:
        run = graded(run_dir)

        assert run.package_before == run_dir / PACKAGE_BEFORE
        assert run.package_after == run_dir / PACKAGE_AFTER
        assert json.loads(run.package_before.read_text(encoding="utf-8")) == json.loads(
            before_package().model_dump_json()
        )
        assert json.loads(run.package_after.read_text(encoding="utf-8")) == json.loads(
            after_package().model_dump_json()
        )

    def test_the_dumps_are_model_check_profile(self, run_dir: Path) -> None:
        run = graded(run_dir)

        for path in (run.package_before, run.package_after):
            body = json.loads(path.read_text(encoding="utf-8"))
            assert body["extractor"]["profile"] == "model_check"

    def test_a_dump_from_another_profile_is_refused_naming_it(self, run_dir: Path) -> None:
        """The re-modeler's packages are the Model check profile 003 US6 produces. A
        `full` dump is refused rather than filed as one: the two carry different evidence
        and the file name would then say something untrue about what was graded."""
        package = before_package()
        full = package.model_copy(
            update={"extractor": package.extractor.model_copy(update={"profile": "full"})}
        )

        with pytest.raises(NotAModelCheckDumpError, match="full"):
            write_package(run_dir, full, side="before")


# --- 2. no provider, no key, no network -------------------------------------------


def test_every_artifact_is_produced_with_every_provider_adapter_raising(
    run_dir: Path,
) -> None:
    run = graded(run_dir)

    assert run.grades_file.is_file()
    assert run.rms_before.is_file()
    assert run.rms_after.is_file()


# --- 3. the rule runs -------------------------------------------------------------


class TestRmsRuns:
    def test_each_side_is_graded_by_003s_entry_point_over_its_own_dump(
        self, run_dir: Path
    ) -> None:
        run = graded(run_dir)

        assert run.rms_before == run_dir / RMS_BEFORE_FILE_NAME
        assert run.rms_after == run_dir / RMS_AFTER_FILE_NAME
        before = json.loads(run.rms_before.read_text(encoding="utf-8"))
        after = json.loads(run.rms_after.read_text(encoding="utf-8"))
        assert before["package"] == PACKAGE_BEFORE
        assert after["package"] == PACKAGE_AFTER
        assert before["documents"] == [COPY_DOCUMENT]
        assert after["documents"] == [COPY_DOCUMENT]

    def test_each_side_carries_the_findings_coverage_and_grade_it_reached(
        self, run_dir: Path
    ) -> None:
        run = graded(run_dir)

        before = json.loads(run.rms_before.read_text(encoding="utf-8"))
        assert DESCRIBED_RULE in [item["check"] for item in before["findings"]]
        assert before["coverage"]
        assert before["grade"] == run.before.grade.as_dict()

    def test_the_uncalibrated_assembly_rules_are_not_run_over_a_part_alone(
        self, run_dir: Path
    ) -> None:
        """The subject is a part opened alone. Running the assembly family over it would
        report four rules unresolved about a document that is not in the package, which
        reads as missing evidence rather than as a family nobody asked for."""
        run = graded(run_dir)

        assert [step.tool for step in run.before.session.steps] == [
            "check_rms_part",
            "check_rms_equations",
        ]
        assert run.before.assembly_document is None


# --- 4. grades.json ---------------------------------------------------------------


class TestGrades:
    def test_the_artifact_carries_before_after_and_the_per_rule_delta(
        self, run_dir: Path
    ) -> None:
        run = graded(run_dir)

        assert run.grades_file == run_dir / GRADES_FILE_NAME
        body = json.loads(run.grades_file.read_text(encoding="utf-8"))
        assert set(body) == {"before", "after", "per_rule"}

    def test_the_counts_are_the_headline_and_the_fraction_is_secondary(
        self, run_dir: Path
    ) -> None:
        run = graded(run_dir)
        body = json.loads(run.grades_file.read_text(encoding="utf-8"))

        for side, check in (("before", run.before), ("after", run.after)):
            assert set(body[side]) == {*BUCKETS, "fraction", "unresolved_rule_ids"}
            assert body[side] == check.grade.as_dict()

    def test_the_unresolved_rule_ids_are_named_beside_the_counts(
        self, run_dir: Path
    ) -> None:
        run = graded(run_dir)
        body = json.loads(run.grades_file.read_text(encoding="utf-8"))

        for side, check in (("before", run.before), ("after", run.after)):
            named = body[side]["unresolved_rule_ids"]
            assert named == sorted(set(named))
            assert bool(named) == bool(body[side]["unresolved"])
            assert named == list(check.grade.unresolved_rule_ids)

    def test_there_is_no_letter_grade_anywhere_in_the_artifact(self, run_dir: Path) -> None:
        """A letter compresses six honest numbers and a list of rules nobody could
        evaluate into one confident character (`grade.py`, Principle I)."""
        graded(run_dir)
        body = json.loads((run_dir / GRADES_FILE_NAME).read_text(encoding="utf-8"))

        letter = re.compile(r"^[A-F][+-]?$")
        assert not [key for key in _keys(body) if "letter" in key]
        assert not [value for value in _strings(body) if letter.match(value)]

    def test_the_per_rule_delta_names_the_rule_that_changed_and_its_subjects(
        self, run_dir: Path
    ) -> None:
        """The described rule fails before and passes after, because the after tree
        describes the feature the before tree left blank."""
        described = folder("3-Core", feature("Boss-Extrude1", "Extrusion"))
        run = graded(
            run_dir,
            after=package_of([described, folder("4-Detail", feature("Hole1", "HoleWzd"))],
                             COPY_DOCUMENT),
        )
        body = json.loads(run.grades_file.read_text(encoding="utf-8"))

        row = next(item for item in body["per_rule"] if item["rule_id"] == DESCRIBED_RULE)
        assert set(row) == {
            "rule_id",
            "before_outcome",
            "after_outcome",
            "subjects_before",
            "subjects_after",
        }
        assert (row["before_outcome"], row["after_outcome"]) == ("fail", "pass")
        assert row["subjects_before"]
        assert row["subjects_after"] == []

    def test_only_the_rules_that_moved_are_listed(self, run_dir: Path) -> None:
        """A part whose tree did not change in any way a rule reads has an empty
        `per_rule`: the delta is what moved, and a row per rule that did not would bury
        it."""
        run = graded(run_dir, after=before_package())

        assert run.per_rule == ()
        assert json.loads(run.grades_file.read_text(encoding="utf-8"))["per_rule"] == []

    def test_the_delta_is_003s_and_is_taken_between_the_two_grades(
        self, run_dir: Path
    ) -> None:
        run = graded(run_dir)

        assert run.delta.before == run.before.grade
        assert run.delta.after == run.after.grade
        assert set(run.delta.counts) == set(BUCKETS)


# --- 5. the exceptions carry-forward ----------------------------------------------


class TestCarryForward:
    def test_a_check_run_whose_source_design_id_matches_is_copied_byte_identically(
        self, run_dir: Path, run_root: Path, tmp_path: Path
    ) -> None:
        store = accepted_store(tmp_path / "accepted.json", source_package())
        check_run(run_root, "20260915-090000-bracket-check", design_id=SOURCE_DESIGN,
                  exceptions=store.path)

        carried = carry_forward_exceptions(
            run_dir, source_design_id=SOURCE_DESIGN, run_root=run_root
        )

        assert carried.from_run == "20260915-090000-bracket-check"
        assert carried.count == 1
        assert carried.reason is None
        assert (run_dir / EXCEPTIONS_FILE_NAME).read_bytes() == store.path.read_bytes()

    def test_a_prior_remodel_run_is_matched_on_its_source_attestation(
        self, run_dir: Path, run_root: Path, tmp_path: Path
    ) -> None:
        """Its own `package-before.json` carries the *copy's* design id, which matches
        nothing. `source-attestation.json` is the only place its source's id is written."""
        store = accepted_store(tmp_path / "accepted.json", source_package())
        remodel_run(run_root, "20260915-110000-bracket-remodel",
                    source_design_id=SOURCE_DESIGN, exceptions=store.path)

        carried = carry_forward_exceptions(
            run_dir, source_design_id=SOURCE_DESIGN, run_root=run_root
        )

        assert carried.from_run == "20260915-110000-bracket-remodel"
        assert carried.count == 1

    def test_a_candidate_for_another_source_design_is_not_copied(
        self, run_dir: Path, run_root: Path, tmp_path: Path
    ) -> None:
        store = accepted_store(tmp_path / "accepted.json", source_package())
        check_run(run_root, "20260915-090000-other-check", design_id=OTHER_DESIGN,
                  exceptions=store.path)
        remodel_run(run_root, "20260915-110000-other-remodel",
                    source_design_id=OTHER_DESIGN, exceptions=store.path)

        carried = carry_forward_exceptions(
            run_dir, source_design_id=SOURCE_DESIGN, run_root=run_root
        )

        assert carried.from_run is None
        assert carried.count == 0
        assert SOURCE_DESIGN in (carried.reason or "")
        assert not (run_dir / EXCEPTIONS_FILE_NAME).exists()

    def test_this_runs_own_design_id_would_select_nothing(
        self, run_dir: Path, run_root: Path, tmp_path: Path
    ) -> None:
        """The reason the match is on the source's id: every candidate that carries this
        run's own id is a dump of some copy, and no copy's path is ever this copy's."""
        store = accepted_store(tmp_path / "accepted.json", source_package())
        check_run(run_root, "20260915-090000-bracket-check", design_id=SOURCE_DESIGN,
                  exceptions=store.path)

        carried = carry_forward_exceptions(
            run_dir, source_design_id=COPY_DESIGN, run_root=run_root
        )

        assert carried.from_run is None

    def test_the_newest_matching_candidate_wins_across_both_kinds(
        self, run_dir: Path, run_root: Path, tmp_path: Path
    ) -> None:
        store = accepted_store(tmp_path / "accepted.json", source_package())
        check_run(run_root, "20260915-090000-bracket-check", design_id=SOURCE_DESIGN,
                  exceptions=store.path, at=datetime(2026, 9, 15, 9, tzinfo=UTC))
        remodel_run(run_root, "20260915-110000-bracket-remodel",
                    source_design_id=SOURCE_DESIGN, exceptions=store.path,
                    at=datetime(2026, 9, 15, 11, tzinfo=UTC))

        carried = carry_forward_exceptions(
            run_dir, source_design_id=SOURCE_DESIGN, run_root=run_root
        )

        assert carried.from_run == "20260915-110000-bracket-remodel"

    def test_no_candidate_at_all_is_reported_and_is_not_an_error(
        self, run_dir: Path, run_root: Path
    ) -> None:
        run = graded(run_dir, run_root)

        assert run.carried_forward.from_run is None
        assert run.carried_forward.reason
        assert run.exceptions is None
        assert run.before.grade.failed >= 1

    def test_no_run_root_carries_nothing_forward_and_says_so(self, run_dir: Path) -> None:
        carried = carry_forward_exceptions(
            run_dir, source_design_id=SOURCE_DESIGN, run_root=None
        )

        assert carried.from_run is None
        assert carried.reason

    def test_a_candidate_that_cannot_be_read_refuses_the_run(
        self, run_dir: Path, run_root: Path, tmp_path: Path
    ) -> None:
        """A silently empty store turns a waived finding back into a failure and moves
        the grade for the wrong reason (RK-18)."""
        broken = tmp_path / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        check_run(run_root, "20260915-090000-bracket-check", design_id=SOURCE_DESIGN,
                  exceptions=broken)

        with pytest.raises(ValueError, match="exception store"):
            carry_forward_exceptions(
                run_dir, source_design_id=SOURCE_DESIGN, run_root=run_root
            )

    def test_a_folder_carrying_neither_field_is_skipped_rather_than_guessed_at(
        self, run_dir: Path, run_root: Path, tmp_path: Path
    ) -> None:
        store = accepted_store(tmp_path / "accepted.json", source_package())
        bare = run_root / "20260915-120000-notes"
        bare.mkdir()
        (bare / EXCEPTIONS_FILE_NAME).write_bytes(store.path.read_bytes())

        carried = carry_forward_exceptions(
            run_dir, source_design_id=SOURCE_DESIGN, run_root=run_root
        )

        assert carried.from_run is None


# --- 6. rebind, then freeze -------------------------------------------------------


class TestRebindAndFreeze:
    @pytest.fixture
    def carried(self, run_dir: Path, run_root: Path, tmp_path: Path) -> Path:
        """A `-check` run of the source whose waiver this run inherits."""
        store = accepted_store(tmp_path / "accepted.json", source_package())
        check_run(run_root, "20260915-090000-bracket-check", design_id=SOURCE_DESIGN,
                  exceptions=store.path)
        return store.path

    def test_a_scope_that_still_names_the_source_would_resolve_to_nothing(
        self, carried: Path
    ) -> None:
        """The failure the rebind exists to prevent, measured before it is prevented: the
        carried store, untouched, resolves against a dump of the copy to nothing."""
        store = ExceptionStore(carried).load()
        assert [scope for item in store.exceptions for scope in item.persist_ref_scopes] == [
            SOURCE_DOCUMENT
        ]

        flagged = store.refresh(before_package())

        assert [item.id for item in flagged] == [item.id for item in store.exceptions]

    def test_the_scopes_are_rebound_to_the_copy_before_the_rules_run(
        self, run_dir: Path, run_root: Path, carried: Path
    ) -> None:
        run = graded(run_dir, run_root)

        assert run.exceptions is not None
        scopes = {
            scope for item in run.exceptions.exceptions for scope in item.persist_ref_scopes
        }
        assert scopes == {COPY_DOCUMENT}
        assert run.rebound == tuple(item.id for item in run.exceptions.exceptions)

    def test_the_rebound_waiver_is_active_and_waives_the_rule_on_both_sides(
        self, run_dir: Path, run_root: Path, carried: Path
    ) -> None:
        run = graded(run_dir, run_root)

        assert run.exceptions is not None
        assert [item.status for item in run.exceptions.exceptions] == ["active"]
        assert run.rebound == ("EX-001",)
        assert run.flagged == ()
        for check in (run.before, run.after):
            waived = next(
                item for item in check.findings if item["check"] == DESCRIBED_RULE
            )
            assert waived["status"] == "checked_within_scope"

    def test_the_waived_rule_does_not_move_the_delta(
        self, run_dir: Path, run_root: Path, carried: Path
    ) -> None:
        run = graded(run_dir, run_root)

        assert DESCRIBED_RULE not in [row.rule_id for row in run.per_rule]

    def test_refresh_runs_once_and_against_the_before_dump(
        self, run_dir: Path, run_root: Path, carried: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once, and against `package-before.json`. A second refresh against the after
        dump is what re-opens a `feature_tree` waiver over this run's own rename and
        reorder, which is the delta moving for exactly the wrong reason."""
        seen: list[EvidencePackage] = []
        original = ExceptionStore.refresh

        def record(self: ExceptionStore, package: EvidencePackage) -> Any:
            seen.append(package)
            return original(self, package)

        monkeypatch.setattr(ExceptionStore, "refresh", record)
        graded(run_dir, run_root)

        assert len(seen) == 1
        assert [row.name for row in seen[0].features] == [
            row.name for row in before_package().features
        ]

    def test_a_second_refresh_against_the_after_dump_would_re_open_the_waiver(
        self, run_dir: Path, run_root: Path, carried: Path
    ) -> None:
        """The teeth of the freeze: the store handed to the after grade is the one the
        before dump refreshed, and refreshing it again would flag the waiver."""
        run = graded(run_dir, run_root)
        assert run.exceptions is not None

        flagged = run.exceptions.refresh(after_package())

        assert [item.id for item in flagged] == [item.id for item in run.exceptions.exceptions]


# --- helpers ----------------------------------------------------------------------


def _keys(body: Any) -> list[str]:
    if isinstance(body, dict):
        return [key for item in body.items() for key in (item[0], *_keys(item[1]))]
    if isinstance(body, list):
        return [key for item in body for key in _keys(item)]
    return []


def _strings(body: Any) -> list[str]:
    if isinstance(body, dict):
        return _strings(list(body.values()))
    if isinstance(body, list):
        return [value for item in body for value in _strings(item)]
    return [body] if isinstance(body, str) else []
