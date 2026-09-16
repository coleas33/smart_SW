"""The review session: one run of the reviewer over one evidence package.

`session.json` is the only source of truth; `report.md` is rendered from it (research
R10). Shapes follow data-model.md section 3 and `contracts/review-session.schema.json`.

Timestamps and ids are the one place strict mode is relaxed: a session is assembled from
plain dictionaries by the tools and the runner, so ISO strings are accepted for
`datetime` and `UUID` fields. Engineering values stay strict.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from annotated_types import Len
from pydantic import Field, StringConstraints, model_validator

from swreview.agent.providers import EffortMapping, TokenUsage, TurnEndReason
from swreview.agent.settings import EfficiencySettings
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


CLOSEOUT_CHECK = "coverage.closeout"
"""The check a turn cut short closes out under, and the checklist item id it shares.

Three different facts are written under this one check, which is why `was_cut_short` reads
the reason as well: `ReviewRun._closeout` writes one `unresolved` item when a turn ended on
`max_steps` or on the provider's output ceiling; finalization writes one when the
`coverage.closeout` **checklist item** was left open; and the model itself may close that
item out through `mark_coverage` into any bucket it likes.
"""

MAX_STEPS_CLOSEOUT_PREFIX = "max_steps reached ("
"""The fixed head of `MAX_STEPS_CLOSEOUT`, which the step count makes per-run."""

MAX_STEPS_CLOSEOUT = (
    MAX_STEPS_CLOSEOUT_PREFIX + "{max_steps} tool calls); the turn was cut short "
    "and what it was still investigating was not finished"
)

TRUNCATED_CLOSEOUT = (
    "the provider ended the turn on its output ceiling; the answer was cut short and "
    "whatever it was still working on was not investigated"
)


def cut_short_reason(reason: TurnEndReason, max_steps: int) -> str | None:
    """Why a turn that ended on `reason` stopped short, or `None` if it did not.

    The one reading of a `TurnEndReason` both runs share (004 T106). A review records the
    sentence as an `unresolved` closeout item and a re-model as a `PlanCoverage` row - two
    different places, one rule about which ends were cut short and how each is worded - and
    a run that read the reason itself would be a second rule, free to word a truncation
    differently or to drop one of the two ends the way a copy of this branch already did.

    `error` and `stopped` are not cut short in this sense: an error is reported as an
    `error` event by whoever caught it, and a cancelled turn was ended deliberately by the
    engineer who cancelled it.
    """
    if reason == "max_steps":
        return MAX_STEPS_CLOSEOUT.format(max_steps=max_steps)
    if reason == "truncated":
        return TRUNCATED_CLOSEOUT
    return None


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


TOKEN_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
    "tool_result_input_tokens",
    "total_tokens",
)
"""The nullable counts of `TokenUsage`, in declaration order. Named once, because
`summed` walks them and naming them seven times is seven chances to omit one."""


class SessionUsage(ReviewModel):
    """What this whole run cost, summed from the `usage` events of every round trip.

    Lives here rather than in the provider package because the session is what is written
    and read back, and because the usage ledger, the report and the scorecard all call
    the same `summed` rule. `TokenUsage` is provider-neutral and stays with the adapters
    that produce it; `report/session.py` already imports across that boundary.
    """

    rounds: int = Field(ge=0)
    """Model round trips across the session. **Not** `len(steps)`, which counts tool
    calls: the two diverge by exactly the amount lever 6 is trying to save."""

    turns: int = Field(ge=0)
    """Turns that produced at least one round, delimited by the `turn.ended` events."""

    totals: TokenUsage
    by_turn: list[TokenUsage] = Field(default_factory=list)

    @classmethod
    def summed(cls, rounds: Sequence[TokenUsage], turn_boundaries: Sequence[int]) -> SessionUsage:
        """The one place token counts are added. Any null in a field makes that total null.

        A sum over rounds where **any** round reported `None` for a field is `None` for
        that field, not a partial sum: a partial sum silently understates and no reader
        of the number can tell it happened. The rule is per field, so a provider that
        stops reporting one sub-count does not erase the rest. `latency_s` is never null,
        because we timed every request we made, so it always sums.

        Args:
            rounds: Every round trip's usage, in the order the `usage` events arrived.
            turn_boundaries: How many rounds had been recorded when each turn ended - one
                entry per `turn.ended` event, ascending. Rounds after the last boundary
                are the turn that never ended, which is the failure path this whole
                design exists for: a turn that raises on its third round emits no
                `turn.ended`, and the two rounds it already paid for still count.
        """
        segments = cls._segments(len(rounds), turn_boundaries)
        by_turn = [cls._sum(rounds[start:end]) for start, end in segments if end > start]
        return cls(
            rounds=len(rounds),
            turns=len(by_turn),
            totals=cls._sum(rounds),
            by_turn=by_turn,
        )

    @staticmethod
    def _segments(count: int, turn_boundaries: Sequence[int]) -> list[tuple[int, int]]:
        """`(start, end)` per turn, with any trailing rounds as a final unended turn."""
        previous = 0
        for boundary in turn_boundaries:
            if not 0 <= boundary <= count:
                raise ValueError(
                    f"turn boundary {boundary} is outside the {count} round(s) recorded"
                )
            if boundary < previous:
                raise ValueError(f"turn boundaries must ascend; {boundary} follows {previous}")
            previous = boundary
        edges = [0, *turn_boundaries]
        if previous < count:
            edges.append(count)
        return list(pairwise(edges))

    @staticmethod
    def _sum(rounds: Sequence[TokenUsage]) -> TokenUsage:
        """Field by field, with `None` swallowing the whole field."""
        counts: dict[str, int | None] = {}
        for field in TOKEN_FIELDS:
            values = [getattr(one, field) for one in rounds]
            counts[field] = None if any(value is None for value in values) else sum(values)
        return TokenUsage(
            **counts,
            latency_s=sum(one.latency_s for one in rounds),
        )


class ReviewSession(ReviewModel):
    session_id: UUID = Field(strict=False)
    package_id: UUID = Field(strict=False)
    design_id: str
    started_at: datetime = Field(strict=False)
    ended_at: datetime | None = Field(default=None, strict=False)
    model: str
    provider_info: ProviderInfo | None = None
    retry_of: UUID | None = Field(default=None, strict=False)
    reused_from: str | None = None
    """The run folder this run's evidence was copied from, mirrored off the package.

    `None` means the package was dumped for this run, which is every run with lever 9 off.
    Reuse is stated, never silent: the package carries it, the pane's status line says it,
    the report header states it and this is the copy an engineer reads back out of
    `session.json` weeks later (feature 005 lever 9, data-model.md 9.5).
    """

    efficiency: EfficiencySettings | None = None
    """Which efficiency levers this run had on (feature 005).

    Optional for the same reason `provider_info` is: a session written before the field
    existed has none, and it loads unchanged. Every run this build makes records it, even
    with every lever off, because `benchmark compare` cannot attribute a results row to a
    configuration without it and refuses a run that carries none.
    """

    usage: SessionUsage | None = None
    """What this run cost, summed from the `usage` events (feature 005).

    Optional for the same reason `efficiency` is, and `None` rather than an all-zero
    record when the adapter reported nothing: a run whose provider sent no counts cost
    something we did not measure, which is not zero (Principle I).
    """

    withheld_checks: list[str] = Field(default_factory=list)
    """The coverage checks a tool this run declined to offer closed out (feature 005 lever 4).

    Empty for every run with `tool_tiers` off, which is every shipped run. A withheld tool
    writes an `unresolved` coverage item naming its checklist item and records that check
    here, which is what lets the scorecard read the unresolved count as the two numbers
    FR-054 requires - the items withholding caused, and everything else - **without**
    substring-matching the reason sentence. One rewording of that sentence would otherwise
    silently change a measured number.
    """

    steps: list[InvestigationStep] = Field(default_factory=list)
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    timing: Timing


def was_cut_short(session: ReviewSession) -> bool:
    """Whether a turn of `session` stopped rather than finished (`ReviewRun._closeout`).

    `ended_at` does not say it: a run out of steps, or ended on the provider's output
    ceiling, is finalized and timestamped exactly like a run that finished, and records no
    `failed` item either, because nothing failed. The `unresolved` closeout item is the only
    trace - but `CLOSEOUT_CHECK` is also a checklist item id, so the check alone would call
    every review that left `coverage.closeout` open a review that was cut short. The two
    reasons `_closeout` writes are therefore constants **here**, written by the runner and
    read by this predicate, so neither side can reword the sentence out from under the
    other.

    The one reader is `carry_over.select_carry_over`, whose guard 1 refuses to carry a
    verdict out of a run that gave up half way (feature 005 lever 11a); it lives beside the
    session model rather than in `agent/runner.py` because `carry_over` cannot import the
    runner - the runner imports `carry_over`.
    """
    return any(
        item.check == CLOSEOUT_CHECK
        and (
            item.reason.startswith(MAX_STEPS_CLOSEOUT_PREFIX)
            or item.reason == TRUNCATED_CLOSEOUT
        )
        for item in session.coverage.unresolved
    )


def load_session(path: Path | str) -> ReviewSession:
    """Read a `session.json` file."""
    return ReviewSession.model_validate_json(Path(path).read_bytes())


def save_session(session: ReviewSession, path: Path | str) -> Path:
    """Write a `session.json` file, creating its directory when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(session.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target
