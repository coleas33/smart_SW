"""The agent loop: one review of one evidence package, start to saved session.

The loop itself is the Anthropic SDK's tool runner (research R2): it owns the message
history, runs the curated tools, and resumes a `pause_turn` on its own. What this module
adds is everything the SDK has no opinion about:

- the system prompt: the versioned commitments in `prompts/system_v1.md`, the mandatory
  checklist rendered as text, and the package census, so the model starts oriented;
- a step budget. `max_steps` counts tool calls, not turns, and stopping on it is recorded
  as `coverage.closeout` unresolved rather than passed over in silence;
- a cap on `pause_turn` restarts, so a turn that keeps pausing cannot spin forever;
- finalization: every evidence request still open and every checklist item still open
  becomes `unresolved` coverage before the session is written (FR-010, FR-019);
- the two US3 hooks on the context: the `exceptions.json` beside the package, loaded when
  it is there, and the live SOLIDWORKS bridge when the run asked for one. Both are wired
  here and nowhere else, so the tools only ever see them through `ToolContext`.

`client` is injectable so the whole loop is testable without a network call or an API
key; `run_review` builds an `Anthropic()` only when no client is supplied. `bridge_factory`
is injectable for the same reason: `--bridge` needs a workstation, a unit test does not.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swreview.agent.checklist import Checklist, load_checklist
from swreview.bridge.client import DEFAULT_PIPE_NAME, BridgeClient
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ir.loader import LoadedPackage, load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import (
    CoverageItem,
    CoverageScope,
    ReviewSession,
    save_session,
)
from swreview.tools.context import DEFAULT_MODEL, ToolContext, build_context
from swreview.tools.query import package_summary
from swreview.tools.registry import build_tools

SYSTEM_PROMPT_FILE = Path(__file__).parent / "prompts" / "system_v1.md"
SESSION_FILE_NAME = "session.json"

# Non-streaming ceiling: the SDK refuses non-streaming requests whose max_tokens implies a
# turn longer than ten minutes ("Streaming is required for operations that may take
# longer than 10 minutes"). The tool runner is iterated turn by turn without streaming,
# so stay at the documented non-streaming default. Raise only together with stream=True.
MAX_TOKENS = 16000
MAX_PAUSE_RESTARTS = 5
"""How many times a turn may come back `pause_turn` before the run gives up."""

DEFAULT_MAX_STEPS = 200
CLOSEOUT_CHECK = "coverage.closeout"
EVIDENCE_CHECK = "coverage.evidence_request"

OPENING_MESSAGE = (
    "Review the evidence package described in the system prompt. Work through the "
    "checklist, gather evidence with the query tools before you judge anything, and "
    "close out every checklist item with a finding or a coverage entry. When you are "
    "done, summarize what you found and what is still unresolved."
)


def build_system_prompt(checklist: Checklist, package: EvidencePackage) -> str:
    """The versioned prompt, the checklist, and the package census as one system prompt."""
    return "\n\n".join(
        [
            SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip(),
            "## Review checklist\n\n" + checklist.render(),
            "## This package\n\n```json\n"
            + json.dumps(package_summary(package), indent=2)
            + "\n```",
        ]
    )


def _unresolved(
    session: ReviewSession,
    check: str,
    reason: str,
    *,
    component_ids: Iterable[str] = (),
    document_ids: Iterable[str] = (),
) -> None:
    session.coverage.unresolved.append(
        CoverageItem(
            check=check,
            scope=CoverageScope(
                component_ids=list(component_ids),
                document_ids=list(document_ids),
            ),
            reason=reason,
            error=None,
        )
    )


def load_exceptions(loaded: LoadedPackage) -> ExceptionStore | None:
    """The `exceptions.json` beside `package.json`, or `None` when there is none.

    Absent is the normal case and means "no condition has been accepted for this design";
    the check tools then report every condition they find. A file that is there but
    unreadable raises rather than being skipped: an exception the reviewer silently
    dropped would re-raise something an engineer already accepted (FR-013).
    """
    path = loaded.base_dir / EXCEPTIONS_FILE_NAME
    if not path.is_file():
        return None
    return ExceptionStore(path).load()


def finalize_session(context: ToolContext, started: datetime) -> ReviewSession:
    """Close out the session: open requests, open checklist items, timing, end time.

    Called whether the loop ended normally, ran out of steps, or stopped on a paused
    turn: a session is never written with an item that quietly went nowhere.
    """
    review = context.session
    for request in review.evidence_requests:
        if request.status != "open":
            continue
        _unresolved(
            review,
            EVIDENCE_CHECK,
            f"{request.id} is still open: {request.what}",
            component_ids=[
                entity_id
                for entity_id in request.entity_ids
                if context.component(entity_id) is not None
            ],
        )
    for item in context.checklist.open_items(review):
        _unresolved(
            review,
            item.id,
            f"{item.title}: the review ended without a finding or a coverage entry for it",
        )
    ended = datetime.now(UTC)
    review.ended_at = ended
    review.timing = review.timing.replace(
        unattended_runtime_minutes=(ended - started).total_seconds() / 60.0
    )
    return review


def drive(runner: Any, context: ToolContext, max_steps: int) -> None:
    """Consume the SDK tool runner, enforcing the step budget and the pause cap.

    The SDK resumes a `pause_turn` itself; counting them here only bounds how often it
    may. Tool results are generated eagerly on a `tool_use` turn (the SDK caches the
    response, so the tools run exactly once) so the budget is checked against steps that
    have actually been recorded before the next request goes out.
    """
    pauses = 0
    for message in runner:
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "pause_turn":
            pauses += 1
            if pauses > MAX_PAUSE_RESTARTS:
                _unresolved(
                    context.session,
                    CLOSEOUT_CHECK,
                    f"the review stopped after {MAX_PAUSE_RESTARTS} paused turns; "
                    "the model never finished a turn",
                )
                return
            continue
        if stop_reason == "tool_use":
            runner.generate_tool_call_response()
        if len(context.session.steps) >= max_steps:
            _unresolved(
                context.session,
                CLOSEOUT_CHECK,
                f"max_steps reached ({max_steps} tool calls); the review was cut short "
                "and the remaining checklist items were not investigated",
            )
            return


def run_review(
    package_dir: Path | str,
    out_dir: Path | str,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = "high",
    max_steps: int = DEFAULT_MAX_STEPS,
    fail_tool: Iterable[str] = (),
    bridge: bool = False,
    pipe_name: str = DEFAULT_PIPE_NAME,
    bridge_factory: Callable[[str], Any] | None = None,
    client: Any | None = None,
) -> ReviewSession:
    """Review the package in `package_dir` and write `session.json` into `out_dir`.

    Args:
        package_dir: Directory holding `package.json`.
        out_dir: Directory the session is written to.
        model: Model id; `claude-opus-5` by default (research R2).
        effort: `output_config.effort` for the run.
        max_steps: Tool-call budget. Hitting it is unresolved coverage, not a finish.
        fail_tool: Tool names forced to fail; the `--fail-tool` test hook.
        bridge: Open the live SOLIDWORKS bridge and add the three bridge tools (US3).
            Needs `SwReview.Extractor.Console.exe serve` running on this workstation.
        pipe_name: Named pipe the bridge listens on.
        bridge_factory: Builds the bridge client from the pipe name; defaults to
            `swreview.bridge.client.BridgeClient` and is injectable for tests.
        client: An Anthropic client, or None to build one from the environment.
    """
    loaded = load_package(package_dir)
    checklist = load_checklist()
    bridge_client = None
    if bridge:
        factory = bridge_factory if bridge_factory is not None else BridgeClient
        bridge_client = factory(pipe_name)
    context = build_context(
        loaded,
        model=model,
        checklist=checklist,
        exceptions=load_exceptions(loaded),
        bridge=bridge_client,
    )
    tools = build_tools(context, fail_tool=fail_tool)

    if client is None:
        from anthropic import Anthropic

        client = Anthropic()

    started = context.session.started_at
    try:
        runner = client.beta.messages.tool_runner(
            model=model,
            max_tokens=MAX_TOKENS,
            output_config={"effort": effort},
            tools=tools,
            system=build_system_prompt(checklist, loaded.package),
            messages=[{"role": "user", "content": OPENING_MESSAGE}],
        )
        drive(runner, context, max_steps)
    finally:
        if bridge_client is not None:
            bridge_client.close()

    review = finalize_session(context, started)
    save_session(review, Path(out_dir) / SESSION_FILE_NAME)
    return review
