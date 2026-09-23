"""The check digest: what the model reads of a check result (feature 008 T035, FR-018).

`check_digest` is the one renderer of a check tool's payload for the model: the re-call
guard answers a repeated check with it (User Story 2), and User Story 3 makes it the view
of every check tool. It counts - findings, rules, statuses, severities, subjects, coverage -
and names at most `ROW_CAP` rows and `ID_CAP` ids, each with the count it left out, because
an omission the model is not told about is the evidence-before-conclusions failure in
miniature (Principle I). It never mutates what it reads, and the same payload gives the
same bytes in any process.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from swreview.ir.loader import load_package, save_package
from swreview.tools.context import build_context
from swreview.tools.model_view import (
    ID_CAP,
    ROW_CAP,
    FindingCounts,
    check_digest,
    count_findings,
)
from swreview.tools.registry import ToolRegistry
from tests.support.prerun import GROUP_KEY, prerun_package

REVIEWER = Path(__file__).resolve().parents[2]


def finding(number: int, check: str = "rms.folders.present", **fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": f"F-{number:03d}",
        "check": check,
        "status": "suspected",
        "severity": "low",
        "title": f"title {number}",
        "component_ids": ["cmp:0002"],
        "inputs": ["feature feat:0001 Boss persist_ref=QUJD scope=doc:3"],
        "drawing_locations": [],
    }
    body.update(fields)
    return body


def envelope(findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"status": "recorded", "findings": findings, **extra}


@pytest.fixture(scope="module")
def real_payloads(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """`check_rms_part` and `check_interference_group` called through the real dispatch."""
    folder = tmp_path_factory.mktemp("package")
    save_package(prerun_package(), folder)
    context = build_context(load_package(folder))
    tools = ToolRegistry().dispatch(context)
    return {
        "check_rms_part": tools.call("check_rms_part", {}).payload,
        "check_interference_group": tools.call(
            "check_interference_group", {"group_key": GROUP_KEY}
        ).payload,
    }


# --- the report_results envelope --------------------------------------------------------


def test_the_rms_envelope_digest_counts_everything_and_keeps_no_payload_key(
    real_payloads: dict[str, dict[str, Any]],
) -> None:
    payload = real_payloads["check_rms_part"]
    findings = payload["findings"]
    digest = check_digest(payload)

    assert digest["status"] == "recorded"
    assert digest["findings"] == len(findings)
    assert digest["rules"] == len({f["check"] for f in findings})
    assert digest["finding_ids"] == [f["id"] for f in findings]
    assert digest["finding_ids_omitted"] == 0
    assert digest["rows"][0] == {
        key: findings[0][key] for key in ("id", "check", "status", "severity", "title")
    }
    assert digest["subjects"] == sum(len(rows) for rows in payload["subjects"].values())
    assert isinstance(digest["coverage"], dict)
    assert sum(digest["coverage"].values()) == len(payload["coverage"])
    assert "inputs" not in json.dumps(digest)


def test_the_by_status_and_by_severity_keys_are_sorted() -> None:
    digest = check_digest(
        envelope(
            [
                finding(1, status="suspected", severity="low"),
                finding(2, status="demonstrated", severity="medium"),
                finding(3, check="rms.sketches.fully_defined", status="demonstrated"),
            ]
        )
    )

    assert list(digest["by_status"]) == ["demonstrated", "suspected"]
    assert digest["by_status"] == {"demonstrated": 2, "suspected": 1}
    assert list(digest["by_severity"]) == ["low", "medium"]
    assert digest["rules"] == 2


def test_coverage_rows_are_counted_by_bucket_in_sorted_order() -> None:
    digest = check_digest(
        envelope(
            [finding(1)],
            coverage=[
                {"bucket": "skipped", "check": "a"},
                {"bucket": "checked", "check": "b"},
                {"bucket": "skipped", "check": "c"},
            ],
        )
    )

    assert digest["coverage"] == {"checked": 1, "skipped": 2}
    assert list(digest["coverage"]) == ["checked", "skipped"]


# --- one finding, four findings, an interference group ----------------------------------


def test_a_record_result_payload_is_one_finding() -> None:
    digest = check_digest({"status": "recorded", "finding": finding(7)})

    assert digest["findings"] == 1
    assert digest["finding_ids"] == ["F-007"]
    assert digest["subjects"] == 1
    assert "coverage" not in digest


def test_a_record_results_payload_of_four_findings() -> None:
    four = [
        finding(n, check=f"fastener.{name}", component_ids=[f"cmp:000{n}"])
        for n, name in enumerate(("engagement", "clamp", "head", "length"), start=1)
    ]
    digest = check_digest(envelope(four))

    assert digest["findings"] == 4
    assert digest["rules"] == 4
    assert digest["subjects"] == 4, "distinct component ids when no subjects map"


def test_the_interference_digest_keeps_its_scalars_and_drops_pairs_and_exception(
    real_payloads: dict[str, dict[str, Any]],
) -> None:
    payload = real_payloads["check_interference_group"]
    digest = check_digest(payload)

    assert digest["group_key"] == payload["group_key"]
    assert digest["configuration"] == payload["configuration"]
    assert digest["members"] == payload["members"]
    assert digest["coverage"] == payload["coverage"], "an integer coverage is kept as given"
    assert "pairs" not in digest
    assert "exception" not in digest
    assert digest["finding_ids"] == [payload["finding"]["id"]]


def test_subjects_count_distinct_components_across_findings() -> None:
    digest = check_digest(
        envelope(
            [
                finding(1, component_ids=["cmp:0001", "cmp:0002"]),
                finding(2, component_ids=["cmp:0002", "cmp:0003"]),
            ]
        )
    )

    assert digest["subjects"] == 3


# --- the caps, at their boundaries -------------------------------------------------------


@pytest.mark.parametrize(("count", "omitted"), [(ROW_CAP, 0), (ROW_CAP + 1, 1)])
def test_rows_are_capped_with_the_omitted_count(count: int, omitted: int) -> None:
    digest = check_digest(envelope([finding(n) for n in range(1, count + 1)]))

    assert len(digest["rows"]) == min(count, ROW_CAP)
    assert digest["rows_omitted"] == omitted
    assert [row["id"] for row in digest["rows"]] == [f"F-{n:03d}" for n in range(1, ROW_CAP + 1)]


@pytest.mark.parametrize(("count", "omitted"), [(ID_CAP, 0), (ID_CAP + 1, 1)])
def test_ids_are_capped_with_the_omitted_count(count: int, omitted: int) -> None:
    digest = check_digest(envelope([finding(n) for n in range(1, count + 1)]))

    assert len(digest["finding_ids"]) == min(count, ID_CAP)
    assert digest["finding_ids_omitted"] == omitted
    assert digest["findings"] == count


def test_the_caps_are_the_contracts() -> None:
    assert (ROW_CAP, ID_CAP) == (25, 200)


def test_counts_only_names_no_row_and_no_id() -> None:
    digest = check_digest(envelope([finding(n) for n in range(1, 30)]), counts_only=True)

    for key in ("rows", "rows_omitted", "finding_ids", "finding_ids_omitted"):
        assert key not in digest
    assert "F-0" not in json.dumps(digest)
    assert digest["findings"] == 29


# --- what passes through, and what is never touched --------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "out_of_scope", "coverage_item": {"check": "fastener.joint"}},
        {"error": "no component 'cmp:9999' in this package"},
        {"status": "contact", "contact": {"id": "C-001"}, "group_key": "k"},
        {"status": "recorded", "findings": 3, "finding_ids": ["F-001"], "coverage": {"a": 1}},
    ],
    ids=["out-of-scope", "error", "contact", "already-a-summary"],
)
def test_a_payload_that_is_not_a_findings_envelope_passes_through(
    payload: dict[str, Any],
) -> None:
    assert check_digest(payload) == payload


def test_the_input_is_never_mutated(real_payloads: dict[str, dict[str, Any]]) -> None:
    for payload in real_payloads.values():
        before = copy.deepcopy(payload)
        check_digest(payload)
        check_digest(payload, counts_only=True)
        assert payload == before


def test_the_bytes_are_identical_across_hash_seeds() -> None:
    script = (
        "import json; from swreview.tools.model_view import check_digest; "
        "from tests.unit.test_model_view import envelope, finding; "
        "print(json.dumps(check_digest(envelope("
        "[finding(n, check=f'rms.rule{n % 7}', status=('a','b','c')[n % 3], "
        "severity=('x','y')[n % 2], component_ids=[f'cmp:{n:04d}']) for n in range(1, 60)],"
        " coverage=[{'bucket': b, 'check': 'c'} for b in ('u','s','c','s')]))))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            cwd=REVIEWER,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("0", "12345")
    }
    assert len(outputs) == 1


# --- count_findings ----------------------------------------------------------------------


def test_count_findings_over_triples() -> None:
    counts = count_findings(
        [
            ("rms.a", "demonstrated", "medium"),
            ("rms.a", "suspected", "low"),
            ("rms.b", "demonstrated", "medium"),
        ]
    )

    assert counts == FindingCounts(
        findings=3,
        rules=2,
        by_status={"demonstrated": 2, "suspected": 1},
        by_severity={"low": 1, "medium": 2},
    )
    assert list(counts.by_status) == ["demonstrated", "suspected"]


def test_count_findings_of_nothing_is_zeros() -> None:
    assert count_findings([]) == FindingCounts(
        findings=0, rules=0, by_status={}, by_severity={}
    )
