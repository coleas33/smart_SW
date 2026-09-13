"""Read the exported bill of materials and reconcile it with the package (T033).

The BOM is the only exported file that states how many of each part the design uses.
It is evidence, not truth: when it disagrees with the component instances in the
package the disagreement is recorded as a `Gap` and both numbers are named, so a
reviewer sees the conflict instead of a silently chosen winner (constitution
Principle I).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from swreview.ir.models import EvidencePackage, Gap

__all__ = ["BOM_COLUMNS", "BomRow", "bom_gaps", "read_bom"]

BOM_COLUMNS: tuple[str, ...] = (
    "item",
    "part_number",
    "document_id",
    "description",
    "quantity",
    "configuration",
)
"""Required header of an exported `bom.csv`; every column must be present."""


@dataclass(frozen=True)
class BomRow:
    """One line of the exported BOM."""

    item: int
    part_number: str
    document_id: str
    description: str
    quantity: int
    configuration: str


def read_bom(path: Path | str) -> list[BomRow]:
    """Parse the `bom.csv` at `path` in file order.

    Raises `ValueError` for a missing column, an empty `document_id`, or an `item` or
    `quantity` that is not a non-negative whole number. Nothing is coerced or defaulted:
    a BOM that cannot be read exactly is a BOM that cannot be reconciled.
    """
    bom_file = Path(path)
    with bom_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = tuple(name.strip() for name in (reader.fieldnames or ()))
        missing = [column for column in BOM_COLUMNS if column not in header]
        if missing:
            raise ValueError(f"{bom_file} is missing BOM column(s): {', '.join(missing)}")
        return [_row(record, bom_file, line) for line, record in enumerate(reader, start=2)]


def _row(record: dict[str, str | None], bom_file: Path, line: int) -> BomRow:
    values = {key.strip(): (value or "").strip() for key, value in record.items() if key}
    document_id = values["document_id"]
    if not document_id:
        raise ValueError(f"{bom_file} line {line}: document_id is empty")
    return BomRow(
        item=_whole_number(values["item"], "item", bom_file, line),
        part_number=values["part_number"],
        document_id=document_id,
        description=values["description"],
        quantity=_whole_number(values["quantity"], "quantity", bom_file, line),
        configuration=values["configuration"],
    )


def _whole_number(value: str, column: str, bom_file: Path, line: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{bom_file} line {line}: {column} {value!r} is not a whole number"
        ) from exc
    if number < 0:
        raise ValueError(f"{bom_file} line {line}: {column} {number} is negative")
    return number


def bom_gaps(rows: list[BomRow], package: EvidencePackage) -> list[Gap]:
    """Gaps for BOM lines the package does not account for, in BOM order.

    Two cases, both `kind="not_extracted"`, `entity_kind="bom"`: the BOM names a
    document the package does not hold, or the BOM quantity differs from the number of
    component instances of that document in the package.
    """
    documents = {document.document_id for document in package.documents}
    instances: dict[str, int] = {}
    for component in package.components:
        instances[component.document_id] = instances.get(component.document_id, 0) + 1

    gaps: list[Gap] = []
    for row in rows:
        if row.document_id not in documents:
            gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="bom",
                    entity_id=row.document_id,
                    reason=(
                        f"BOM item {row.item} ({row.part_number}, {row.description}) names "
                        f"document {row.document_id}, which is not in the package; nothing "
                        "about it was reviewed"
                    ),
                    error=None,
                )
            )
            continue
        count = instances.get(row.document_id, 0)
        if count != row.quantity:
            gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="bom",
                    entity_id=row.document_id,
                    reason=(
                        f"BOM item {row.item} ({row.part_number}) calls for "
                        f"{row.quantity} of {row.document_id} in configuration "
                        f"{row.configuration!r}, but the package holds "
                        f"{count} component instance(s) of it"
                    ),
                    error=None,
                )
            )
    return gaps
