"""The review session: one run of the reviewer over one evidence package.

`session.json` is the only source of truth; `report.md` is rendered from it (research
R10). Shapes follow data-model.md section 3 and `contracts/review-session.schema.json`.

Timestamps and ids are the one place strict mode is relaxed: a session is assembled from
plain dictionaries by the tools and the runner, so ISO strings are accepted for
`datetime` and `UUID` fields. Engineering values stay strict.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from annotated_types import Len
from pydantic import Field, StringConstraints, model_validator

from swreview.agent.providers import EffortMapping
from swreview.findings import Finding, ReviewModel
from swreview.ids import SequentialIdAllocator

KeySource = Literal["settings", "env", "none"]
"""Where the API key for this run came from, or `none` when the run needed no key."""


class ProviderInfo(ReviewModel):
    """Which provider ran this review and how its effort control was set (feature 002).

    Optional in `contracts/review-session.schema.json`: a session written before the
    provider port has none, and `ReviewSession.model` remains the single field every
    consumer can rely on. `EffortMapping` is reused from `agent.providers` rather than
    restated, so the value recorded here and the value the adapter sent are one shape.
    """

    provider: str
    model: str
    effort_mapping: EffortMapping
    key_source: KeySource


class InvestigationStep(ReviewModel):
    """One tool call in the trace (FR-004)."""

    index: int = Field(ge=0)
    tool: str
    arguments: dict[str, Any]
    result_summary: str
    status: Literal["ok", "error"]
    error: str | None
    elapsed_s: float = Field(ge=0)


class EvidenceRequest(ReviewModel):
    """Something the reviewer needed and could not find; open until answered (FR-007)."""

    id: Annotated[str, StringConstraints(pattern=r"^ER-[0-9]{3,}$")]
    what: str
    why: str
    entity_ids: list[str]
    status: Literal["open", "answered"]
    answer: str | None
    answered_at: datetime | None = Field(strict=False)


class EvidenceRequestIdAllocator(SequentialIdAllocator):
    """Yields `ER-001`, `ER-002`, ... within one session."""

    def __init__(self, start: int = 1) -> None:
        super().__init__(prefix="ER", start=start)


class CoverageScope(ReviewModel):
    """What a coverage item covers: instances, pairs, configuration, positions."""

    component_ids: list[str] = Field(default_factory=list)
    pairs: list[Annotated[list[str], Len(2, 2)]] = Field(default_factory=list)
    configuration: str | None = None
    positions: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)


class CoverageItem(ReviewModel):
    check: str
    scope: CoverageScope
    reason: str
    error: str | None


class Coverage(ReviewModel):
    """Five buckets; nothing a check touched may go unrecorded (FR-010, FR-019, FR-020)."""

    checked: list[CoverageItem] = Field(default_factory=list)
    skipped: list[CoverageItem] = Field(default_factory=list)
    unresolved: list[CoverageItem] = Field(default_factory=list)
    failed: list[CoverageItem] = Field(default_factory=list)
    out_of_scope: list[CoverageItem] = Field(default_factory=list)


CoverageBucket = Literal["checked", "skipped", "unresolved", "failed", "out_of_scope"]
"""One of `Coverage`'s five buckets, as an argument type.

Named here, beside the model whose fields it mirrors, so a caller that has to say which
bucket an item went into - `ToolContext.record_coverage`, and the `coverage` event body -
does not restate the list. `tools/session.py` narrows it further for `mark_coverage`,
which may not write `failed`.
"""


class Timing(ReviewModel):
    """Minutes per design. `net_saved_minutes` is always derived, never supplied.

    Unattended runtime is excluded on purpose: it costs no engineering effort (FR-026).
    """

    baseline_minutes: float | None
    assisted_supervision_minutes: float = Field(ge=0)
    assisted_verification_minutes: float = Field(ge=0)
    false_alarm_handling_minutes: float = Field(ge=0)
    unattended_runtime_minutes: float = Field(ge=0)
    net_saved_minutes: float | None = None

    def replace(self, **changes: float | None) -> Timing:
        """A copy with `changes` applied and `net_saved_minutes` derived again.

        `model_copy` would carry the old `net_saved_minutes` through untouched, so every
        update goes back through the constructor and the validator below. The three
        callers that move a timing forward - the agent loop, the benchmark runner and
        `swreview.benchmark.timing` - all come through here, so none of them can leave a
        stale net saving behind (FR-026). An unknown field name raises.
        """
        fields = self.model_dump(exclude={"net_saved_minutes"})
        unknown = sorted(set(changes) - set(fields))
        if unknown:
            raise ValueError(f"Timing has no field(s) {unknown}")
        return Timing(**{**fields, **changes})

    @model_validator(mode="after")
    def _derive_net_saved_minutes(self) -> Timing:
        if self.baseline_minutes is None:
            self.net_saved_minutes = None
        else:
            self.net_saved_minutes = self.baseline_minutes - (
                self.assisted_supervision_minutes
                + self.assisted_verification_minutes
                + self.false_alarm_handling_minutes
            )
        return self


class ReviewSession(ReviewModel):
    session_id: UUID = Field(strict=False)
    package_id: UUID = Field(strict=False)
    design_id: str
    started_at: datetime = Field(strict=False)
    ended_at: datetime | None = Field(default=None, strict=False)
    model: str
    provider_info: ProviderInfo | None = None
    retry_of: UUID | None = Field(default=None, strict=False)
    steps: list[InvestigationStep] = Field(default_factory=list)
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    timing: Timing


def load_session(path: Path | str) -> ReviewSession:
    """Read a `session.json` file."""
    return ReviewSession.model_validate_json(Path(path).read_bytes())


def save_session(session: ReviewSession, path: Path | str) -> Path:
    """Write a `session.json` file, creating its directory when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(session.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target
