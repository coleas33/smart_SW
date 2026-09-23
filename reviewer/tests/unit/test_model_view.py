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
from swreview.prerun import attach_standards
from swreview.tools.checks_interference import groups_of
from swreview.tools.context import build_context
from swreview.tools.model_view import (
    FINDING_DETAIL,
    ID_CAP,
    MODEL_VIEWS,
    ROW_CAP,
    FindingCounts,
    check_digest,
    count_findings,
    grouped_gaps,
    model_view,
    strip_references,
)
from swreview.tools.registry import TOOL_FUNCTIONS, ToolRegistry, check_tools, standards_tools
from tests.support.prerun import (
    GROUP_KEY,
    STANDARDS_PROFILE,
    prerun_package,
    standards_prerun_package,
)

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


# --- User Story 3: stripping, grouped gaps, the view table (feature 008 T060) ---------------

REF = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="
"""A base64 persistent reference, as the package records one."""


def test_strip_references_removes_the_four_keys_at_any_depth() -> None:
    payload = {
        "persist_ref": REF,
        "id": "cmp:0001",
        "nested": [
            {"persist_ref_scope": "doc:1", "persist_ref_scopes": ["doc:1"], "name": "boss"},
            {"component_persist_refs": [REF], "kept": {"persist_ref": REF, "value": 3}},
        ],
    }

    assert strip_references(payload) == {
        "id": "cmp:0001",
        "nested": [{"name": "boss"}, {"kept": {"value": 3}}],
    }


def test_strip_references_removes_the_inline_token_and_keeps_the_scope() -> None:
    inputs = [
        f"feature feat:0001 Boss-Extrude1 persist_ref={REF} scope=doc:3",
        "sketch feat:0002 Sketch1 persist_ref=none scope=doc:3",
        "a plain sentence with no reference",
    ]

    assert strip_references({"inputs": inputs}) == {
        "inputs": [
            "feature feat:0001 Boss-Extrude1 scope=doc:3",
            "sketch feat:0002 Sketch1 scope=doc:3",
            "a plain sentence with no reference",
        ]
    }


def test_strip_references_never_mutates_its_input() -> None:
    payload = {
        "persist_ref": REF,
        "rows": [{"persist_ref": REF, "inputs": [f"x persist_ref={REF}"]}],
    }
    before = copy.deepcopy(payload)

    strip_references(payload)

    assert payload == before


def gap(kind: str, entity_kind: str, entity_id: str | None, reason: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "reason": reason,
        "error": None,
    }


def test_grouped_gaps_groups_by_reason_template_in_first_appearance_order() -> None:
    gaps = [
        gap("not_extracted", "component", "cmp:0001", "'bolt A' has no loaded model document"),
        gap("tool_error", "mass_override", "doc:1", "read OverrideMass for 'a.SLDPRT'"),
        gap("not_extracted", "component", "cmp:0002", "'bolt B' has no loaded model document"),
        gap("tool_error", "mass_override", None, "read OverrideMass for 'b.SLDPRT'"),
    ]

    grouped = grouped_gaps(gaps)

    assert grouped["rows"] == 4
    assert [(g["kind"], g["entity_kind"], g["rows"]) for g in grouped["groups"]] == [
        ("not_extracted", "component", 2),
        ("tool_error", "mass_override", 2),
    ]
    first = grouped["groups"][0]
    assert first["reason"] == "'bolt A' has no loaded model document", "the first row, in full"
    assert first["entity_ids"] == ["cmp:0001", "cmp:0002"]
    assert first["entity_ids_omitted"] == 0
    second = grouped["groups"][1]
    assert second["entity_ids"] == ["doc:1"], "a None entity id is counted, not listed"
    assert second["entity_ids_omitted"] == 0


def test_grouped_gaps_keeps_five_ids_and_counts_the_rest() -> None:
    gaps = [
        gap("not_extracted", "face", f"fac:{n:04d}", f"'face {n}' was not read")
        for n in range(1, 9)
    ]

    [group] = grouped_gaps(gaps)["groups"]

    assert group["rows"] == 8
    assert group["entity_ids"] == [f"fac:{n:04d}" for n in range(1, 6)]
    assert group["entity_ids_omitted"] == 3


def test_grouped_gaps_of_nothing() -> None:
    assert grouped_gaps([]) == {"groups": [], "rows": 0}


def test_the_view_of_an_unlisted_tool_is_its_payload_stripped() -> None:
    payload = {"result": [{"id": "cmp:0001", "persist_ref": REF}]}

    assert model_view("list_components", payload) == strip_references(payload)
    assert "list_components" not in MODEL_VIEWS


def test_the_view_of_list_gaps_is_the_grouped_gaps() -> None:
    rows = [gap("not_extracted", "face", "fac:0001", "'f' was not read")]

    assert model_view("list_gaps", {"result": rows}) == grouped_gaps(rows)


def test_every_check_tool_is_in_the_view_table_with_the_detail_sentence(
    real_payloads: dict[str, dict[str, Any]],
) -> None:
    names = {f.__name__ for f in (*check_tools(), *standards_tools())}

    assert names <= set(MODEL_VIEWS)
    for name, payload in real_payloads.items():
        view = model_view(name, payload)
        assert view["detail"] == FINDING_DETAIL
        assert view == strip_references({**check_digest(payload), "detail": FINDING_DETAIL})


def test_an_error_from_a_check_tool_passes_through_stripped_with_no_detail() -> None:
    payload = {"error": "no interference group 'x' in this package"}

    assert model_view("check_interference_group", payload) == payload


# --- the value sweep: no reference value of the package reaches any view -------------------

SWEEP_PACKAGE = REVIEWER / "tests" / "fixtures" / "replay" / "big-assembly"


def package_refs(folder: Path) -> set[str]:
    """Every persistent-reference value the package carries, read from its raw JSON."""
    refs: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "persist_ref" and isinstance(item, str) and item:
                    refs.add(item)
                elif key == "component_persist_refs" and isinstance(item, list):
                    refs.update(ref for ref in item if isinstance(ref, str) and ref)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(json.loads((folder / "package.json").read_text(encoding="utf-8")))
    return refs


def sweep_arguments(package: Any) -> dict[str, dict[str, Any]]:
    """One call per tool, with ids from the package. A call that errors is still swept:
    an error message must not quote a reference either."""
    part_doc = next(d.document_id for d in package.documents if d.kind == "part")
    component = next(c.id for c in package.components if c.document_id == part_doc)
    hole_a, hole_b = package.holes[0].id, package.holes[1].id
    face_a, face_b = package.faces[0].id, package.faces[1].id
    group_key = groups_of(package)[0].group_key
    dimension = {"document_id": part_doc, "sheet": "Sheet1", "annotation": "D1"}
    return {
        "get_package_summary": {},
        "list_components": {"parent_id": None, "include_suppressed": True},
        "get_component": {"component_id": component},
        "find_components": {"name_pattern": ".", "document_id": None},
        "list_mates": {"component_id": None},
        "list_holes": {"component_id": None, "hole_type": None},
        "list_fasteners": {"component_id": None, "kind": None},
        "list_interferences": {"configuration": None, "component_id": None},
        "get_drawing_sheet": {"document_id": part_doc, "sheet_name": None},
        "find_dimensions": {"document_id": None, "text_regex": None, "near_view": None},
        "list_gaps": {},
        "get_exceptions": {"check": None},
        "list_features": {"document_id": part_doc, "folder": None, "include_suppressed": True},
        "get_feature": {"feature_id": package.features[0].id},
        "list_equations": {"document_id": part_doc},
        "measure_axis_distance": {"hole_id_a": hole_a, "hole_id_b": hole_b},
        "measure_face_gap": {"face_id_a": face_a, "face_id_b": face_b},
        "check_tool_envelope": {
            "fastener_id": "fst:0001",
            "tool": "hex_key",
            "length": {"value": 100.0, "unit": "mm"},
        },
        "bounding_box": {"component_id": component},
        "check_fit": {"bore_dimension_ref": dimension, "shaft_dimension_ref": dimension},
        "check_axial_stack": {"dimension_refs": [dimension], "signs": [1], "target_gap": None},
        "check_fastener_joint": {
            "fastener_id": "fst:0001",
            "hole_id": hole_a,
            "clamped_component_ids": [component],
        },
        "check_hole_alignment": {"hole_id_a": hole_a, "hole_id_b": hole_b, "tolerance": None},
        "check_interference_group": {"group_key": group_key},
        "check_rms_part": {"document_id": None},
        "check_rms_assembly": {},
        "check_rms_equations": {"document_id": None},
        "check_joints": {},
        "check_mass_material": {},
        "check_hygiene": {},
        "request_evidence": {
            "what": "the tapped depth of the first hole",
            "why": "fastener.engagement",
            "entity_ids": [hole_a],
        },
        "mark_coverage": {
            "check": "interfaces.fit",
            "bucket": "skipped",
            "scope": {"component_ids": [component]},
            "reason": "no drawing dimensions were extracted",
        },
        "record_drawing_finding": {
            "document_id": part_doc,
            "sheet": "Sheet1",
            "observed": "the callout has no thread depth",
            "requirement": "the callout states the thread depth",
            "source_refs": [dimension],
            "status": "suspected",
            "recommended_action": "add the thread depth",
        },
        "get_review_checklist": {},
        "request_capture": {"entity_id": component, "view": "iso"},
    }


def test_no_reference_value_of_the_package_reaches_the_view_of_any_tool() -> None:
    loaded = load_package(SWEEP_PACKAGE)
    refs = package_refs(SWEEP_PACKAGE)
    context = build_context(loaded)
    dispatch = ToolRegistry().dispatch(context)
    arguments = sweep_arguments(loaded.package)
    assert refs
    assert {f.__name__ for f in TOOL_FUNCTIONS} == set(arguments), "a new tool needs a sweep row"

    leaks: dict[str, int] = {}
    for name, call_arguments in arguments.items():
        payload = dispatch.call(name, call_arguments).payload
        text = json.dumps(model_view(name, payload))
        found = sum(1 for ref in refs if ref in text)
        if found:
            leaks[name] = found
    assert leaks == {}


def test_check_standards_views_carry_no_reference_either(tmp_path: Path) -> None:
    folder = tmp_path / "package"
    save_package(standards_prerun_package(), folder)
    loaded = load_package(folder)
    context = build_context(loaded)
    assert attach_standards(context, STANDARDS_PROFILE) is None
    dispatch = ToolRegistry().dispatch(context)

    payload = dispatch.call("check_standards", {}).payload
    view = json.dumps(model_view("check_standards", payload))

    refs = package_refs(folder)
    assert payload["findings"], "the standards run graded something"
    assert refs
    assert not [ref for ref in refs if ref in view]
    assert json.loads(view)["detail"] == FINDING_DETAIL
