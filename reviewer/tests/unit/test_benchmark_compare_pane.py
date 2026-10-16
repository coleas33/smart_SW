"""T232/T233: pane verdict routing and its command over fictional saved runs."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import get_args

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.settings import PANE_STUDY, PRIVATE_PANE_STUDY
from swreview.benchmark import compare, digest, origins, simulate, verdict
from swreview.benchmark.prices import SYNTHETIC_COST
from swreview.benchmark.scorecard import FailedAttempt
from swreview.report.session import load_session
from tests.support.findings import make_finding
from tests.support.studies import (
    PanePackage,
    RunSpec,
    pane_baseline_spec,
    pane_run,
    write_measurement,
    write_noise_floor,
    write_pane_study,
    write_run,
)

runner = CliRunner()
PRIVATE_REASON = "private slice (23A): shown beside the pane study's verdict, never deciding"


def study(*, count=18, reps=3, edit=None):
    runs = []
    for rep in range(1, reps + 1):
        for arm in ("off", "on"):
            packages = []
            for index in range(count):
                matched = ("D-1",)
                if arm == "on" and index == 0:
                    matched = ("D-1", "D-2")
                elif arm == "on" and index == 1:
                    matched = ()
                package = PanePackage(package_id=f"case-{index:02d}", matched=matched)
                packages.append(edit(arm, rep, index, package) if edit else package)
            runs.append(pane_run(f"{arm}-{rep}", arm, packages))
    return runs


def edit_json(path, edit):
    record = json.loads(path.read_bytes())
    edit(record)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def edit_saved_sets(runs, edit):
    for run in runs:
        path = run / "benchmark-set.json"
        edit_json(path, edit)
        edit_json(run / "run-provenance.json", lambda record, saved=path: record.update(
            set_digest=digest.sha256_of(saved),
        ))


def invoke(runs, out, *, pilots=(), noise_floors=()):
    args = ["benchmark", "compare", *map(str, runs), "--out", str(out)]
    for path in pilots:
        args.extend(("--pilot", str(path)))
    for path in noise_floors:
        args.extend(("--noise-floor", str(path)))
    return runner.invoke(cli.app, args, catch_exceptions=False)


def block_from(out):
    return json.loads((out / "ledger.json").read_bytes())["pane_studies"][0]


def assert_refusal(result, out, runs, *tokens):
    assert result.exit_code == 1, result.output
    assert (out / "ledger.json").is_file(), result.output
    payload = json.loads((out / "ledger.json").read_bytes())
    assert len(payload["runs"]) == sum(
        len(json.loads((run / "scorecard.json").read_bytes())["per_package"])
        for run in runs
    )
    block = payload["pane_studies"][0]
    assert block["verdict"] is None
    assert block["refusal"]
    assert block["figures"] is block["code_guard"] is block["cleared_guard"] is None
    assert block["study"] in {PANE_STUDY, PRIVATE_PANE_STUDY}
    assert len(block["run_dirs"]) == len(runs)
    provenance = [json.loads((run / "run-provenance.json").read_bytes()) for run in runs]
    assert block["reps"] == {
        arm: len({record["rep"] for record in provenance if record["arm"] == arm})
        for arm in ("off", "on")
    }
    assert "no verdict for " + block["study"] in result.output
    for token in tokens:
        assert token in block["refusal"], block["refusal"]
        assert token in result.output, result.output
    return block


@pytest.mark.parametrize("arm", ["off", "on"])
@pytest.mark.parametrize("private", [False, True])
def test_c1_and_c16_a_missing_arm_refuses_the_verdict_but_keeps_raw_rows(tmp_path, arm, private):
    runs = write_pane_study(
        tmp_path / "runs", [run for run in study() if run.arm == arm],
        study=PRIVATE_PANE_STUDY if private else PANE_STUDY,
    )
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out), out, runs, arm, "on" if arm == "off" else "off")


def test_c2_committed_pane_study_refuses_private_saved_set_entries(tmp_path):
    runs = write_pane_study(tmp_path / "runs", study())
    edit_saved_sets(runs, lambda record: record["packages"][0].update(
        path="C:/Fictional/private/case-00",
    ))
    out = tmp_path / "out"
    assert_refusal(
        invoke(runs, out), out, runs, "case-00",
        "a pane study's set holds committed cases only; the private slice is its own study",
        PRIVATE_PANE_STUDY,
    )


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("cause", ["origin_marks", "unknown", "not_recorded"])
def test_c3_and_c16_unrecorded_origins_or_outcomes_name_the_rerun(tmp_path, private, cause):
    runs = write_pane_study(
        tmp_path / "runs", study(), study=PRIVATE_PANE_STUDY if private else PANE_STUDY,
    )
    first = runs[0]
    tokens = ["off-1", "case-00", "swreview benchmark run"]
    if cause == "origin_marks":
        edit_json(first / "case-00/session.json", lambda record: record.pop("origin_marks"))
    elif cause == "unknown":
        edit_json(first / "scorecard.json", lambda record: record["per_package"][0].update(
            false_alarm_finding_ids=["F-999"], finding_origins={"F-999": "unknown"},
            false_alarms=1,
        ))
        finding = make_finding(finding_id="F-999", tool_result_ids=[999])
        edit_json(first / "case-00/session.json", lambda record: record.update(
            findings=[finding.model_dump(mode="json")],
        ))
        session = load_session(first / "case-00/session.json")
        assert session.origin_marks == 1
        assert origins.finding_origin(finding, session) == "unknown"
        tokens.append("F-999")
    else:
        edit_json(first / "scorecard.json", lambda record: record["per_package"][0].update(
            run_status={"kind": "not_recorded", "class": None, "stop_reason": None},
        ))
        tokens.append("not_recorded")
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out), out, runs, *tokens)


def test_c4_keys_below_34_held_out_model_defects_refuse_before_measurement(tmp_path):
    def edit(arm, rep, index, package):
        return replace(package, model_held_out=("D-1",)) if index == 16 else package

    runs = write_pane_study(tmp_path / "runs", study(count=17, edit=edit))
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out), out, runs, "33", "34")


def test_c10_private_study_has_all_intervals_and_no_verdict_or_measurement_refusal(tmp_path):
    runs = write_pane_study(tmp_path / "runs", study(count=2), study=PRIVATE_PANE_STUDY)
    # Private rows skip committed-only and sizing refusals, even for private paths and <34 defects.
    edit_saved_sets(runs, lambda record: record["packages"][0].update(
        path="C:/Fictional/private/case-00",
    ))
    out = tmp_path / "out"
    result = invoke(runs, out)
    assert result.exit_code == 0, result.output
    block = block_from(out)
    assert block["slice"] == "private"
    assert block["verdict"] is block["refusal"] is None
    assert block["reasons"] == [PRIVATE_REASON]
    assert block["figures"]["main"]["recall"]["estimate"] == pytest.approx(0)
    assert block["figures"]["sensitivity"]
    assert block["code_guard"] is not None and block["cleared_guard"] is not None
    assert block["shown"]
    assert json.loads((out / "ledger.json").read_bytes())["levers"] == []


def test_c12_identical_folders_measurement_and_record_give_identical_bytes(tmp_path):
    runs = write_pane_study(tmp_path / "runs", study())
    measurement = write_measurement(tmp_path / "pilot")
    noise = write_noise_floor(tmp_path / "noise", runs)
    for suffix in ("a", "b"):
        result = invoke(runs, tmp_path / suffix, pilots=[measurement], noise_floors=[noise])
        assert result.exit_code == 0, result.output
    assert (tmp_path / "a/ledger.json").read_bytes() == (tmp_path / "b/ledger.json").read_bytes()


def test_c13_compare_never_opens_a_key_named_by_a_saved_set(tmp_path, monkeypatch):
    runs = write_pane_study(tmp_path / "runs", study())
    edit_saved_sets(runs, lambda record: [
        entry.update(key=f"benchmarks/answer_keys/{entry['package_id']}.json")
        for entry in record["packages"]
    ])
    measurement = write_measurement(tmp_path / "pilot")
    noise = write_noise_floor(tmp_path / "noise", runs)
    for method in ("open", "read_bytes", "read_text"):
        original = getattr(Path, method)

        def guarded(path, *args, _original=original, **kwargs):
            assert "answer_keys" not in path.parts, f"compare opened an answer key: {path}"
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(Path, method, guarded)
    out = tmp_path / "out"
    result = invoke(runs, out, pilots=[measurement], noise_floors=[noise])
    assert result.exit_code == 0, result.output
    assert block_from(out)["refusal"] is None


SHOWN_NAMES = [
    "recall on tuned-on model-produced defects", "detection of code-produced defects",
    "hits on tuned-on forbidden entries", "contradicted correct conditions",
    "confirmed correct conditions",
    *[f"false alarms: {origin}" for origin in get_args(origins.Origin)],
    "false alarms", *[f"findings: {origin}" for origin in get_args(origins.Origin)],
    "valid findings", "detected defects", "flagged defects", "missed known defects",
    "carried findings",
    "flagged below expected", "status mismatches", "forbidden hits", "withdrawn forbidden hits",
    "coverage mismatches", "unresolved findings", "unresolved coverage",
    "unresolved because withheld", "unresolved other", "unanswerable requests", "re-asks seen",
    "re-asks refused", "repeats of open questions", "unmatched requests", "question-count misses",
    "unscripted questions", "bound-reached reviews", "fit and axial-stack calls per run",
    "failures: infrastructure/provider_error", "behavioural stops: max_steps",
    "code-produced defects detected only sometimes by off arm", "cleared defects",
    "held-out model-produced defects detected on every counted run of both arms",
    "held-out model-produced defects detected on no counted run",
]


def shown_study():
    def edit(arm, rep, index, package):
        n = index if arm == "on" else 0
        call = {"step": 0, "outcome": "recorded", "request_id": "Q-1"}
        repeat = {**call, "of": "Q-0"}
        return replace(
            package, bound_reached=arm == "on" and index < 9,
            status="behavioural" if arm == "on" and index < 9 else "completed",
            code_held_out=("C-1",),
            matched=package.matched + (("C-1",) if index != 2 or rep == 1 else ()),
            cleared=("D-2",) if arm == "on" and index == 2 else (),
            score_overrides={
                "flagged_below_expected_defect_ids": [f"below-{j}" for j in range(n)],
                "status_mismatch_defect_ids": [f"status-{j}" for j in range(n)],
                "coverage_mismatches": [{"entry": f"E-{j}", "item": "hygiene", "read": "unresolved"}
                                        for j in range(n)],
                "unresolved_other": n, "unresolved_because_withheld": 0,
                "unanswerable_requests": [{**call, "entry": "U-1"} for _ in range(n)],
                "re_asks": [repeat for _ in range(n)] + [
                    {**repeat, "outcome": "already_answered"} for _ in range(n)
                ],
                "open_repeats": [repeat for _ in range(n)],
                "unmatched_requests": [call for _ in range(n)],
                "question_counts": [{"entry": f"Q-{j}", "min": 1, "max": 1, "count": 0}
                                    for j in range(n)],
                "unscripted_questions": [{"request_id": "Q-1", "reason": "no_answer"}
                                         for _ in range(n)],
                "not_assessed": {},
            },
        )

    runs = study(edit=edit)
    for run in runs:
        if run.arm == "on":
            run.scorecard.failed_attempts = [FailedAttempt(
                package_id=f"case-{index:02d}", attempt=1, retries=0,
                cost=SYNTHETIC_COST, class_="provider_error", folder=f"attempts/case-{index:02d}/1",
            ) for index in range(9)]
    return runs


def test_the_shown_table_holds_section_6s_measures_in_order(tmp_path):
    runs = write_pane_study(tmp_path / "runs", shown_study())
    measurement = write_measurement(tmp_path / "pilot")
    block = compare.compare_runs(runs, pilots=[measurement]).pane_studies[0]
    assert [row.name for row in block.shown][:len(SHOWN_NAMES)] == SHOWN_NAMES
    rows = {row.name: row for row in block.shown}
    # For 0..17, mean=8.5, sample variance=28.5, SE=sqrt(28.5/18), t(.975,17)=2.109815578.
    half_width = 2.109815578 * math.sqrt(28.5 / 18)
    for name in (
        "flagged below expected", "status mismatches", "coverage mismatches", "unresolved coverage",
        "unanswerable requests", "re-asks seen", "re-asks refused", "repeats of open questions",
        "unmatched requests", "question-count misses", "unscripted questions",
    ):
        row = rows[name]
        assert row.off == 0
        assert row.on == row.estimate == pytest.approx(8.5)
        assert row.lower == pytest.approx(8.5 - half_width, abs=1e-7)
        assert row.upper == pytest.approx(8.5 + half_width, abs=1e-7)
        assert row.excludes_zero is True
    # Nine of eighteen package runs stop or reach the bound; Bernoulli sample variance=9/34.
    for name in ("bound-reached reviews", "failures: infrastructure/provider_error",
                 "behavioural stops: max_steps"):
        row = rows[name]
        assert row.off == 0 and row.on == pytest.approx(0.5)
        assert row.lower == pytest.approx(0.5 - 2.109815578 / math.sqrt(68), abs=1e-7)
        assert row.excludes_zero is True
    sometimes = rows["code-produced defects detected only sometimes by off arm"]
    assert sometimes.off == pytest.approx(1/54)
    assert sometimes.on == 0 and sometimes.excludes_zero is False
    assert rows["cleared defects"].off == 0
    assert rows["cleared defects"].on == pytest.approx(1/18)
    assert rows["cleared defects"].excludes_zero is False
    every = rows["held-out model-produced defects detected on every counted run of both arms"]
    never = rows["held-out model-produced defects detected on no counted run"]
    assert every.off == every.on == pytest.approx(9/18)
    assert never.off == never.on == pytest.approx(9/18)
    assert every.excludes_zero is never.excludes_zero is False
    rendered = compare.render_ledger_md(compare.compare_runs(runs, pilots=[measurement]))
    assert "case-02" in rendered and "D-2" in rendered and "on-1" in rendered


def test_only_the_studys_own_arms_feed_its_verdict(tmp_path, monkeypatch):
    pane = write_pane_study(tmp_path / "pane", study())
    private = write_pane_study(
        tmp_path / "private", [replace(run, run="private-" + run.run) for run in study(count=2)],
        study=PRIVATE_PANE_STUDY,
    )
    pane_baseline = pane_baseline_spec("pane-baseline", 1)
    baseline_pane = write_run(tmp_path, pane_baseline)
    baseline_plain = write_run(
        tmp_path, RunSpec(run="plain-baseline", lever="none", arm="baseline",
                          model=pane_baseline.model),
    )
    measurement = write_measurement(tmp_path / "pilot")
    alone = compare.compare_runs(pane, pilots=[measurement]).pane_studies[0]
    converted = []
    original = verdict.study_stats

    def capture(runs):
        converted.append({run.run for run in runs})
        return original(runs)

    monkeypatch.setattr(verdict, "study_stats", capture)
    together = compare.compare_runs(
        [*pane, baseline_pane, baseline_plain, *private], pilots=[measurement],
    )
    committed = next(block for block in together.pane_studies if block.study == PANE_STUDY)
    assert committed == alone
    assert committed.reps.off == committed.reps.on == 3
    assert set(committed.run_dirs) == {
        row.run_dir for row in together.runs if row.lever == PANE_STUDY
    }
    assert converted == [{folder.name for folder in pane}, {folder.name for folder in private}]
    assert len(together.runs) == 108 + 12 + 2
    assert {row.lever for row in together.levers} == {"none", "none (pane defaults)"}
    private_block = next(row for row in together.pane_studies if row.study == PRIVATE_PANE_STUDY)
    assert private_block.verdict is None
    assert {row.run for row in together.runs} >= {"pane-baseline", "plain-baseline"}


def test_markdown_pane_section_holds_the_contracts_order_points_and_unknowns(tmp_path):
    runs = write_pane_study(tmp_path / "runs", study())
    measurement = write_measurement(tmp_path / "pilot")
    noise = write_noise_floor(tmp_path / "noise", runs)
    ledger = compare.compare_runs(runs, pilots=[measurement], noise_floors=[noise])
    text = compare.render_ledger_md(ledger)
    section = text.split("### Pane study\n", 1)[1]
    tokens = [
        "no 10-point loss", "main recall", "main false alarms", "sensitivity recall",
        "sensitivity false alarms", "Code guard", "Cleared guard", "Dropped", "Approval",
        "Noise floor", "Settings the arms differed in", "Recorded inert",
        "Settings the verdict does not test", "Shown",
    ]
    positions = [section.lower().index(token.lower()) for token in tokens]
    assert positions == sorted(positions)
    for token in ("estimate", "interval", "level", "packages", "retained defects", "result",
                  "2026-09-14", "36", "3", "0.025", "140514", "0.83", "0.87", "0.036",
                  "0.041", "0.021", "0.025", "8.5", "unknown", "points"):
        assert token.lower() in section.lower()
    lower = ledger.pane_studies[0].figures.main.recall.lower
    assert f"{lower * 100:.1f}" in section
    assert "### Pane study" not in compare.render_ledger_md(compare.compare_runs([]))


# T233: pilot approvals, saved noise floors and discovery, all through stored records.


@pytest.mark.parametrize("count", [0, 2])
def test_c5_missing_or_duplicate_measurements_name_the_study_key_and_option(tmp_path, count):
    runs = write_pane_study(tmp_path / "runs", study())
    measurements = [write_measurement(tmp_path / f"pilot-{index}") for index in range(count)]
    out = tmp_path / "out"
    block = assert_refusal(invoke(runs, out, pilots=measurements), out, runs,
                           PANE_STUDY, "openai", "--pilot")
    assert block["model"] in block["refusal"]


@pytest.mark.parametrize("edited", ["sizing", "pilot_runs"])
def test_c6_editing_either_computed_block_refuses_the_sizing_digest(tmp_path, edited):
    runs = write_pane_study(tmp_path / "runs", study())
    measurement = write_measurement(tmp_path / "pilot")
    if edited == "sizing":
        edit_json(measurement, lambda record: record["sizing"].update(seed=999))
    else:
        edit_json(measurement, lambda record: record["pilot_runs"].append({
            "folder": "off-previous", "arm": "off", "repetition": 1,
            "started_at": "2026-09-10T09:00:00Z", "commit": "earlier-fictional",
        }))
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out, pilots=[measurement]), out, runs,
                   "the sizing was edited by hand; re-run `swreview benchmark pilot`")


@pytest.mark.parametrize("field,value", [("approved", False), ("approved_at", "")])
def test_c7_unapproved_measurement_names_the_file_and_field(tmp_path, field, value):
    runs = write_pane_study(tmp_path / "runs", study())
    measurement = write_measurement(tmp_path / "pilot")
    edit_json(measurement, lambda record: record["approval"].update({field: value}))
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out, pilots=[measurement]), out, runs, measurement.name, field)


def test_c8_levels_chosen_after_first_paid_run_name_both_dates(tmp_path):
    runs = write_pane_study(tmp_path / "runs", study())
    measurement = write_measurement(tmp_path / "pilot", approved_at="2026-09-17")
    out = tmp_path / "out"
    assert_refusal(
        invoke(runs, out, pilots=[measurement]), out, runs,
        "2026-09-17", "2026-09-16", "levels chosen after the paid runs void the 5% bounds",
    )


@pytest.mark.parametrize("shortfall", ["defects", "reps", "pilot_packages", "growth_units"])
def test_c9_study_must_reach_the_approved_size_repetitions_and_growth(tmp_path, shortfall):
    runs = write_pane_study(tmp_path / "runs", study())
    options = {}
    expected = []
    if shortfall == "defects":
        options["held_out_model_defects"] = 40
        expected = ["36", "40"]
    elif shortfall == "reps":
        runs = [run for run in runs if run.name != "on-3"]
        expected = ["on", "2", "3"]
    elif shortfall == "pilot_packages":
        options["pilot_packages"] = ["missing-pilot-package"]
        expected = ["missing-pilot-package"]
    else:
        options.update(pilot_packages=[f"case-{index:02d}" for index in range(18)], growth_units=2)
        expected = ["0", "2"]
    measurement = write_measurement(tmp_path / "pilot", **options)
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out, pilots=[measurement]), out, runs, *expected)


def test_c9_one_core_case_and_its_twin_are_one_growth_unit_not_two(tmp_path):
    def edit(arm, rep, index, package):
        if index == 17:
            return replace(package, model_held_out=(), matched=(), score_overrides={
                "held_out": True,
                "graded_items": [{"id": "C-clean", "kind": "correct_condition", "tag": "held_out",
                                  "producer": None, "expected_status": None}],
            })
        return package

    runs = write_pane_study(tmp_path / "runs", study(edit=edit))
    measurement = write_measurement(
        tmp_path / "pilot", held_out_model_defects=34,
        pilot_packages=[f"case-{index:02d}" for index in range(16)], growth_units=2,
    )
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out, pilots=[measurement]), out, runs, "1", "2")


def test_c9_missing_saved_set_cannot_prove_the_approved_pilot_layout(tmp_path):
    runs = write_pane_study(tmp_path / "runs", study())
    (runs[0] / "benchmark-set.json").unlink()
    measurement = write_measurement(tmp_path / "pilot", pilot_packages=["case-00"])
    out = tmp_path / "out"
    assert_refusal(invoke(runs, out, pilots=[measurement]), out, runs,
                   "off-1", "saved set", "approval")


def test_c11_pilot_folders_are_raw_rows_without_entering_study_checks_or_counts(tmp_path):
    checkout = tmp_path / "checkout"
    studies = checkout / "benchmarks/studies"
    pilots = checkout / "benchmarks/pilots/pane"
    runs = write_pane_study(studies / "pane", study())
    pilot_folders = write_pane_study(pilots, [run for run in study() if run.arm == "off"])
    for folder in pilot_folders:
        edit_json(folder / "run-provenance.json", lambda record: record.update(
            commit="earlier-fictional",
        ))
    pilot_rows = [{
        "folder": folder.name, "arm": "off", "repetition": rep,
        "started_at": "2026-09-10T09:00:00Z", "commit": "earlier-fictional",
    } for rep, folder in enumerate(pilot_folders, start=1)]
    pilot_rows.append({**pilot_rows[0], "folder": "missing-listed-pilot", "repetition": 4})
    measurement = write_measurement(pilots, pilot_runs=pilot_rows)
    discovered = compare.recorded_runs(studies)
    assert set(discovered) == set(runs)
    assert not set(discovered) & set(pilot_folders)
    assert compare.recorded_pilots(checkout / "benchmarks/pilots") == [measurement]
    out = tmp_path / "out"
    result = invoke(runs, out, pilots=[measurement])
    assert result.exit_code == 0, result.output
    block = block_from(out)
    assert block["reps"] == {"off": 3, "on": 3}
    assert len(block["run_dirs"]) == 6 and block["refusal"] is None
    payload = json.loads((out / "ledger.json").read_bytes())
    pilot_raw = [row for row in payload["runs"] if row["arm"] == "off (pilot)"]
    assert len(pilot_raw) == 54
    assert all(row["commit"] == "earlier-fictional" for row in pilot_raw)
    assert "off (pilot)" in (out / "ledger.md").read_text(encoding="utf-8")
    assert sum("missing-listed-pilot" in line for line in result.output.splitlines()) == 1
    assert "missing-listed-pilot" not in (out / "ledger.json").read_text(encoding="utf-8")


def test_c14_empty_ledger_markdown_remains_the_committed_block():
    document = (compare.REPO_ROOT / "docs/llm-efficiency-options.md").read_text(encoding="utf-8")
    after_marker = document.split(compare.LEDGER_BEGIN + "\n", 1)[1]
    committed = after_marker.split(compare.LEDGER_END, 1)[0].strip()
    assert compare.render_ledger_md(compare.compare_runs([])).strip() == committed
    assert "pane_studies" not in compare.compare_runs([]).model_dump(mode="json")


def test_c15_unmatched_measurement_is_one_note_and_never_a_refusal(tmp_path):
    runs = write_pane_study(tmp_path / "runs", study())
    matching = write_measurement(tmp_path / "pilot")
    unmatched = write_measurement(tmp_path / "unmatched", model="fictional-unmatched-model")
    out = tmp_path / "out"
    result = invoke(runs, out, pilots=[matching, unmatched])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if str(unmatched) in line]
    assert len(lines) == 1, result.output
    assert all(token in lines[0] for token in (PANE_STUDY, "openai", "fictional-unmatched-model"))
    assert block_from(out)["refusal"] is None


@pytest.mark.parametrize("state", ["computed", "missing", "stale", "duplicate"])
def test_c17_saved_noise_floor_is_read_without_search_and_never_refuses(
    tmp_path, monkeypatch, state,
):
    runs = write_pane_study(tmp_path / "runs", study())
    measurement = write_measurement(tmp_path / "pilot")
    records = []
    if state != "missing":
        records.append(write_noise_floor(tmp_path / "noise", runs,
                                        runs_digest="0" * 64 if state == "stale" else None))
    if state == "duplicate":
        records.append(write_noise_floor(tmp_path / "noise-2", runs))

    def no_search(*args, **kwargs):
        pytest.fail("compare called the simulator's search")

    monkeypatch.setattr(simulate, "search", no_search)
    assert compare.recorded_noise_floors(tmp_path) == sorted(records)
    out = tmp_path / "out"
    result = invoke(runs, out, pilots=[measurement], noise_floors=records)
    assert result.exit_code == 0, result.output
    block = block_from(out)
    assert block["refusal"] is None
    noise = block["noise_floor"]
    text = (out / "ledger.md").read_text(encoding="utf-8")
    if state == "computed":
        assert noise == {"state": "computed", "points": 8.5, "seed": 140514, "numpy": "2.4.6"}
        assert all(token in text for token in ("8.5", "140514", "2.4.6"))
    elif state == "stale":
        assert noise["state"] == "stale"
        assert "stale: computed over other runs" in text
    else:
        assert noise["state"] == "not_computed" and noise["points"] is None
        assert "not computed: run swreview benchmark noise-floor" in text
    if state == "duplicate":
        lines = [
            line for line in result.output.splitlines()
            if all(str(path) in line for path in records)
        ]
        assert len(lines) == 1, result.output
    second = tmp_path / "out-2"
    assert invoke(runs, second, pilots=[measurement], noise_floors=records).exit_code == 0
    assert (out / "ledger.json").read_bytes() == (second / "ledger.json").read_bytes()
