"""Generate `contracts/ir.schema.json` from the IR models.

The C# extractor validates against the committed contract, so the contract is generated,
never hand-edited: `python -m swreview.ir.schema --write <path>` rewrites it and
`tests/unit/test_schema_sync.py` fails when the two drift apart (T105, research R5).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from swreview.ir.models import EvidencePackage

SCHEMA_ID = "https://smart-sw.local/contracts/ir.schema.json"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_TITLE = "EvidencePackage"
SCHEMA_DESCRIPTION = (
    "Intermediate representation of one SOLIDWORKS design dumped by the extractor "
    "and/or assembled from exported files. Field rules: "
    "specs/001-agentic-design-review/data-model.md section 2."
)


def export_schema() -> dict[str, Any]:
    """Return the JSON Schema for `EvidencePackage`, with the contract's identity."""
    schema = EvidencePackage.model_json_schema(ref_template="#/$defs/{model}")
    schema["title"] = SCHEMA_TITLE
    schema["description"] = SCHEMA_DESCRIPTION
    return {"$schema": JSON_SCHEMA_DIALECT, "$id": SCHEMA_ID, **schema}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m swreview.ir.schema",
        description="Print the generated IR JSON Schema, or write it to a file.",
    )
    parser.add_argument(
        "--write",
        metavar="PATH",
        type=Path,
        help="write the schema to PATH instead of stdout",
    )
    arguments = parser.parse_args(argv)

    text = json.dumps(export_schema(), indent=2) + "\n"
    if arguments.write is None:
        sys.stdout.write(text)
    else:
        arguments.write.write_text(text, encoding="utf-8")
        sys.stderr.write(f"wrote {arguments.write}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
