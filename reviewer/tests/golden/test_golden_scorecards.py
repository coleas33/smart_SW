"""Feature 014 T153: every case and each single-behaviour scoring probe under version 3.

The snapshots pin the whole scoring view; independently declared deltas keep a snapshot
regeneration from accepting double counting or changes to unrelated columns.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pytest_regressions.data_regression import DataRegressionFixture

from swreview.agent.checklist import load_checklist
from swreview.benchmark import scorecard
from swreview.benchmark.answer_key import load_answer_key
from swreview.benchmark.sets import REPO_ROOT, BenchmarkPackageRef, load_set
from swreview.checks.standards.profile import load_profile
from swreview.ir.loader import load_package
from swreview.report.summary import load_words
from tests.support import scoring_probes

GOLDENS = Path(__file__).with_suffix("")
VERSION_RECORD = Path(__file__).with_name("scoring_rules_versions.json")
ENTRIES = {
    entry.package_id: entry
    for filename in ("committed.json", "pilot.json")
    for entry in load_set(REPO_ROOT / "benchmarks" / "sets" / filename).packages
}
OVERLAY_BASES = tuple(
    {
        (probe.case, probe.overlay, probe.base): probe
        for probe in scoring_probes.PROBES
        if probe.overlay is not None
    }.values()
)


def case(entry: BenchmarkPackageRef):
    package = load_package(entry.path).package
    assert entry.key is not None, entry.package_id
    key = load_answer_key(
        entry.key, package=package, checklist=load_checklist(), words=load_words()
    )
    return key, package


@pytest.mark.parametrize("entry", ENTRIES.values(), ids=lambda entry: entry.package_id)
@pytest.mark.parametrize("review", ("oracle", "null"))
def test_each_case_has_oracle_and_null_goldens(
    entry: BenchmarkPackageRef,
    review: str,
    tmp_path: Path,
    data_regression: DataRegressionFixture,
) -> None:
    key, package = case(entry)
    scores = scoring_probes.assert_oracle_and_null(
        key,
        package,
        tmp_path,
        profile=load_profile(REPO_ROOT / "config" / "standards.example.yaml"),
    )
    result = scores[0 if review == "oracle" else 1]
    data_regression.check(
        scoring_probes.golden_view(result), basename=f"{entry.package_id}--{review}"
    )


@pytest.mark.parametrize("probe", OVERLAY_BASES, ids=lambda probe: probe.overlay)
def test_each_disclosed_overlay_base_has_its_own_golden(
    probe, tmp_path: Path, data_regression: DataRegressionFixture
) -> None:
    scoring_probes.validate_probe(probe, ENTRIES)
    base, _ = scoring_probes.probe_scores(probe, ENTRIES[probe.case], tmp_path)
    data_regression.check(base, basename=f"{probe.case}--{probe.overlay}--{probe.base}")


@pytest.mark.parametrize(
    "probe",
    getattr(scoring_probes, "PROBES", (None,)),
    ids=lambda probe: probe.name if probe else "missing",
)
def test_each_probe_has_a_golden_and_moves_only_its_declared_columns(
    probe, tmp_path: Path, data_regression: DataRegressionFixture
) -> None:
    assert probe is not None, "T155 must supply PROBES"
    scoring_probes.validate_probe(probe, ENTRIES)
    base, changed = scoring_probes.probe_scores(probe, ENTRIES[probe.case], tmp_path)
    scoring_probes.assert_probe_delta(probe, base, changed)
    data_regression.check(changed, basename=f"{probe.case}--{probe.name}")


def test_a_probe_counting_its_behaviour_twice_fails(tmp_path: Path) -> None:
    probe = next(one for one in scoring_probes.PROBES if one.name == "plain-false-alarm")
    base, changed = scoring_probes.probe_scores(probe, ENTRIES[probe.case], tmp_path)
    changed["false_alarms"] += 1
    with pytest.raises(AssertionError, match="false_alarms"):
        scoring_probes.assert_probe_delta(probe, base, changed)


def test_every_package_score_field_is_in_the_view_or_excluded(tmp_path: Path) -> None:
    key, package = case(next(iter(ENTRIES.values())))
    result, _ = scoring_probes.assert_oracle_and_null(key, package, tmp_path)
    view = scoring_probes.golden_view(result)
    assert set(view).isdisjoint(scoring_probes.GOLDEN_EXCLUDED)
    assert set(view) | set(scoring_probes.GOLDEN_EXCLUDED) == set(
        scorecard.PackageScore.model_fields
    )


def test_every_mutable_view_field_and_matching_rule_has_a_probe() -> None:
    declared = {column for probe in scoring_probes.PROBES for column in probe.moves}
    required = set(scorecard.PackageScore.model_fields) - set(scoring_probes.GOLDEN_EXCLUDED)
    required -= set(scoring_probes.GOLDEN_IDENTITY)
    assert required <= declared, f"fields without probes: {sorted(required - declared)}"
    rules = {probe.rule for probe in scoring_probes.PROBES if probe.rule is not None}
    assert rules == set(scoring_probes.MATCHING_RULES)
    names = [probe.name for probe in scoring_probes.PROBES]
    assert len(names) == len(set(names)), "probe names must be unique"


def test_a_probe_whose_case_or_entry_has_gone_names_both() -> None:
    probe = next(one for one in scoring_probes.PROBES if one.entry is not None)
    with pytest.raises(ValueError, match=f"missing-case.*{probe.entry}"):
        scoring_probes.validate_probe(replace(probe, case="missing-case"), ENTRIES)
    with pytest.raises(ValueError, match=f"{probe.case}.*missing-entry"):
        scoring_probes.validate_probe(replace(probe, entry="missing-entry"), ENTRIES)


def test_every_disclosed_overlay_has_a_probe_and_a_real_entry_reference() -> None:
    overlaid = [probe for probe in scoring_probes.PROBES if probe.overlay is not None]
    assert {probe.overlay for probe in overlaid} == set(scoring_probes.PROBE_KEY_OVERLAYS)
    for probe in overlaid:
        assert probe.entry is not None
        scoring_probes.validate_probe(probe, ENTRIES)


@pytest.mark.parametrize(
    "probe",
    getattr(scoring_probes, "PROBES", (None,)),
    ids=lambda probe: probe.name if probe else "missing",
)
def test_golden_identity_never_moves(probe, tmp_path: Path) -> None:
    assert probe is not None, "T155 must supply PROBES"
    base, changed = scoring_probes.probe_scores(probe, ENTRIES[probe.case], tmp_path)
    assert {name: changed[name] for name in scoring_probes.GOLDEN_IDENTITY} == {
        name: base[name] for name in scoring_probes.GOLDEN_IDENTITY
    }


def test_the_version_record_matches_this_version_and_the_golden_digest() -> None:
    assert VERSION_RECORD.is_file(), "T157 must write scoring_rules_versions.json"
    rows = json.loads(VERSION_RECORD.read_text(encoding="utf-8"))
    digest = scoring_probes.goldens_sha256(GOLDENS)
    failures = scoring_probes.version_record_failures(rows, digest, scorecard.SCORING_RULES_VERSION)
    assert not failures, f"{failures}; current golden digest: {digest}"


@pytest.mark.parametrize(
    ("rows", "digest", "version", "valid"),
    [
        ([{"version": 3, "goldens_sha256": "a", "reason": "first"}], "a", 3, True),
        ([{"version": 3, "goldens_sha256": "a", "reason": "first"}], "b", 3, False),
        ([{"version": 3, "goldens_sha256": "a", "reason": "first"}], "a", 4, False),
        (
            [{"version": 3, "goldens_sha256": "a"}, {"version": 5, "goldens_sha256": "b"}],
            "b",
            5,
            False,
        ),
        (
            [{"version": 3, "goldens_sha256": "a"}, {"version": 4, "goldens_sha256": "a"}],
            "a",
            4,
            False,
        ),
        (
            [
                {"version": 3, "goldens_sha256": "a"},
                {
                    "version": 4,
                    "goldens_sha256": "a",
                    "goldens_unchanged": True,
                    "reason": "excluded field",
                },
            ],
            "a",
            4,
            True,
        ),
        (
            [
                {"version": 3, "goldens_sha256": "a"},
                {
                    "version": 4,
                    "goldens_sha256": "b",
                    "goldens_unchanged": True,
                    "reason": "excluded field",
                },
            ],
            "b",
            4,
            False,
        ),
        (
            [
                {"version": 3, "goldens_sha256": "a"},
                {"version": 4, "goldens_sha256": "a", "goldens_unchanged": True, "reason": " "},
            ],
            "a",
            4,
            False,
        ),
    ],
)
def test_the_version_record_rejects_each_inconsistent_transition(
    rows, digest, version, valid
) -> None:
    assert (not scoring_probes.version_record_failures(rows, digest, version)) is valid


def test_the_golden_digest_normalizes_checkout_line_endings_and_includes_paths(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a.yml"
    first.write_bytes(b"field: 1\r\n")
    crlf = scoring_probes.goldens_sha256(tmp_path)
    first.write_bytes(b"field: 1\n")
    assert scoring_probes.goldens_sha256(tmp_path) == crlf
    first.rename(tmp_path / "b.yml")
    assert scoring_probes.goldens_sha256(tmp_path) != crlf
