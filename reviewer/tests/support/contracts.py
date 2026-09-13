"""Access to the committed JSON Schema contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "specs" / "001-agentic-design-review" / "contracts"
CONTRACTS_DIR_002 = REPO_ROOT / "specs" / "002-task-pane-assistant" / "contracts"

CONTRACT_DIRS: tuple[Path, ...] = (CONTRACTS_DIR, CONTRACTS_DIR_002)
"""Every directory holding committed schemas, in feature order."""


def load_contract(name: str) -> dict[str, Any]:
    """Read one contract, e.g. `load_contract("ir.schema.json")`."""
    return json.loads((CONTRACTS_DIR / name).read_text(encoding="utf-8"))


def contract_path(name: str) -> Path:
    """Locate one contract by file name across every feature's contract directory."""
    for directory in CONTRACT_DIRS:
        candidate = directory / name
        if candidate.exists():
            return candidate
    searched = ", ".join(str(directory) for directory in CONTRACT_DIRS)
    raise FileNotFoundError(f"no contract named {name!r} under: {searched}")


def load_any_contract(name: str) -> dict[str, Any]:
    """Read one contract from any feature, e.g. `"chat-events.schema.json"` (002)."""
    return json.loads(contract_path(name).read_text(encoding="utf-8"))


def contract_registry() -> Registry:
    """Every committed schema, registered by its `$id`.

    The feature 002 contracts `$ref` the feature 001 ones by absolute `$id`
    (`https://smart-sw.local/contracts/review-session.schema.json#/$defs/Finding`), and
    `review-session.schema.json` in turn refs `ir.schema.json` relatively, which resolves
    against that same `$id` base. Registration is therefore by `$id` and never by path.
    """
    resources: list[tuple[str, Resource]] = []
    for directory in CONTRACT_DIRS:
        for path in sorted(directory.glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema_id = schema.get("$id")
            if not schema_id:
                raise ValueError(f"contract without $id cannot be registered: {path}")
            resources.append((schema_id, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def contract_validator(name: str) -> Draft202012Validator:
    """A validator for one contract, with every other contract resolvable by `$id`."""
    return Draft202012Validator(
        load_any_contract(name),
        registry=contract_registry(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
