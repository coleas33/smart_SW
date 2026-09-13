"""The models and `contracts/ir.schema.json` must describe the same package (T013).

The two are compared semantically, not byte for byte: pydantic and the hand-written
contract disagree about layout (`$defs` naming, `title`, `default`, nullable spelled as
`type: [..., "null"]` versus `anyOf`) while describing identical documents. Both sides
are canonicalised - references resolved, layout-only keys dropped - and the first real
difference is reported with its JSON path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from swreview.ir.schema import SCHEMA_ID, export_schema
from tests.support.contracts import CONTRACTS_DIR, load_contract
from tests.support.packages import build_package

LAYOUT_ONLY_KEYS = {"title", "description", "default", "$schema", "$id", "$comment", "examples"}


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def canonicalise(node: Any, defs: dict[str, Any]) -> Any:
    """Resolve `$ref`s and normalise the spellings the two generators differ on."""
    if isinstance(node, list):
        return [canonicalise(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        target = defs[node["$ref"].rsplit("/", 1)[-1]]
        siblings = {key: value for key, value in node.items() if key != "$ref"}
        node = {**target, **siblings}

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in LAYOUT_ONLY_KEYS or key == "$defs":
            continue
        out[key] = canonicalise(value, defs)

    if "enum" in out:
        # pydantic writes `type: string` next to an enum; the contract writes the enum alone.
        out.pop("type", None)
        out["enum"] = sorted(out["enum"], key=_sort_key)
    if "required" in out:
        out["required"] = sorted(out["required"])

    declared_type = out.get("type")
    if isinstance(declared_type, list):
        siblings = {key: value for key, value in out.items() if key != "type"}
        out = {
            "anyOf": [
                {"type": name} if name == "null" else {"type": name, **siblings}
                for name in declared_type
            ]
        }
    if "anyOf" in out:
        out["anyOf"] = sorted(out["anyOf"], key=_sort_key)
    return out


def first_difference(generated: Any, contract: Any, path: str = "$") -> str | None:
    """Return a description of the first difference, or None when the two agree."""
    if isinstance(contract, dict):
        if not isinstance(generated, dict):
            return f"{path}: the contract has an object, the models produced {generated!r}"
        for key in sorted(set(contract) | set(generated)):
            if key not in generated:
                return f"{path}.{key}: in the contract ({contract[key]!r}), not in the models"
            if key not in contract:
                return f"{path}.{key}: in the models ({generated[key]!r}), not in the contract"
            difference = first_difference(generated[key], contract[key], f"{path}.{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(contract, list):
        if not isinstance(generated, list):
            return f"{path}: the contract has an array, the models produced {generated!r}"
        if len(generated) != len(contract):
            return (
                f"{path}: the models produced {len(generated)} items "
                f"{generated!r}, the contract has {len(contract)} {contract!r}"
            )
        for index, (left, right) in enumerate(zip(generated, contract, strict=True)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    if generated != contract:
        return f"{path}: the models produced {generated!r}, the contract has {contract!r}"
    return None


def test_export_schema_matches_the_committed_contract() -> None:
    generated = export_schema()
    contract = load_contract("ir.schema.json")

    difference = first_difference(
        canonicalise(generated, generated.get("$defs", {})),
        canonicalise(contract, contract.get("$defs", {})),
    )

    assert difference is None, difference


def test_export_schema_keeps_the_contract_identity() -> None:
    generated = export_schema()
    contract = load_contract("ir.schema.json")

    assert generated["$id"] == SCHEMA_ID == contract["$id"]
    assert generated["$schema"] == contract["$schema"]
    assert generated["title"] == contract["title"]


def test_a_sample_package_validates_against_the_contract() -> None:
    sample = build_package().model_dump(mode="json")

    validator = Draft202012Validator(
        load_contract("ir.schema.json"),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(sample), key=lambda error: list(error.absolute_path))

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_a_sample_package_validates_against_the_generated_schema() -> None:
    sample = build_package().model_dump(mode="json")

    Draft202012Validator(export_schema()).validate(sample)


def test_module_main_writes_the_schema(tmp_path: Path) -> None:
    target = tmp_path / "ir.schema.json"

    completed = subprocess.run(
        [sys.executable, "-m", "swreview.ir.schema", "--write", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(target.read_text(encoding="utf-8")) == export_schema()


@pytest.mark.parametrize("name", ["ir.schema.json", "review-session.schema.json"])
def test_contract_files_are_valid_json_schema(name: str) -> None:
    Draft202012Validator.check_schema(load_contract(name))
    assert (CONTRACTS_DIR / name).exists()
