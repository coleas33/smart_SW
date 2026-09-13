"""Access to the committed JSON Schema contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "specs" / "001-agentic-design-review" / "contracts"


def load_contract(name: str) -> dict[str, Any]:
    """Read one contract, e.g. `load_contract("ir.schema.json")`."""
    return json.loads((CONTRACTS_DIR / name).read_text(encoding="utf-8"))
