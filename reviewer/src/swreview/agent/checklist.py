"""The mandatory review checklist and the bucket each item currently sits in.

`checklist_v1.yaml` (T040) lists the items every review has to close out. An item is
closed either by a finding whose `check` starts with the item's `check_prefix`, or by a
coverage entry whose `check` equals the item id (FR-010, FR-019). Everything else is
still `open`, and the runner turns what is still open at the end of a run into
`unresolved` coverage rather than letting it disappear.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from swreview.report.session import ReviewSession

CHECKLIST_FILE = Path(__file__).parent / "checklist_v1.yaml"

COVERAGE_BUCKETS: tuple[str, ...] = ("checked", "skipped", "unresolved", "out_of_scope")
"""Coverage buckets an item may be closed out in, in the order they are searched.

`failed` is deliberately absent: it is written by the tool layer against a tool name, not
against a checklist item, so it never counts as closing an item out.
"""

FINDING_BUCKET = "finding"
OPEN_BUCKET = "open"


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    title: str
    check_prefix: str
    description: str


@dataclass(frozen=True)
class Checklist:
    version: int
    items: tuple[ChecklistItem, ...]

    def bucket_of(self, item: ChecklistItem, session: ReviewSession) -> str:
        """Where `item` stands in `session`: `finding`, a coverage bucket, or `open`."""
        if any(finding.check.startswith(item.check_prefix) for finding in session.findings):
            return FINDING_BUCKET
        for bucket in COVERAGE_BUCKETS:
            entries = getattr(session.coverage, bucket)
            if any(entry.check == item.id for entry in entries):
                return bucket
        return OPEN_BUCKET

    def buckets(self, session: ReviewSession) -> list[dict[str, str]]:
        """Every item with its current bucket; the payload of `get_review_checklist`."""
        return [
            {
                "id": item.id,
                "title": item.title,
                "check_prefix": item.check_prefix,
                "description": item.description,
                "bucket": self.bucket_of(item, session),
            }
            for item in self.items
        ]

    def open_items(self, session: ReviewSession) -> list[ChecklistItem]:
        """The items neither a finding nor a coverage entry has closed out."""
        return [item for item in self.items if self.bucket_of(item, session) == OPEN_BUCKET]

    def render(self) -> str:
        """The checklist as prompt text, one block per item."""
        lines = [f"Review checklist version {self.version}. Every item must be closed out."]
        for item in self.items:
            lines.append("")
            lines.append(f"- `{item.id}` - {item.title}")
            lines.append(f"  Closed by a finding whose check starts with `{item.check_prefix}`")
            lines.append(f"  or by `mark_coverage(check=\"{item.id}\", ...)`.")
            lines.append(f"  {item.description}")
        return "\n".join(lines)


def load_checklist(path: Path | str = CHECKLIST_FILE) -> Checklist:
    """Read a checklist YAML file. Raises `ValueError` when an item is incomplete."""
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    items: list[ChecklistItem] = []
    for raw in document["items"]:
        missing = [key for key in ("id", "title", "check_prefix", "description") if key not in raw]
        if missing:
            raise ValueError(f"checklist item {raw.get('id', raw)!r} is missing {missing}")
        items.append(
            ChecklistItem(
                id=raw["id"],
                title=raw["title"],
                check_prefix=raw["check_prefix"],
                description=" ".join(raw["description"].split()),
            )
        )
    return Checklist(version=int(document["version"]), items=tuple(items))
