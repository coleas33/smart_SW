"""The tool list handed to the model, and the recording wrapper around every call.

`ToolRegistry.build(context)` is the only way a tool reaches the runner. Each entry is a
`RecordedTool`, an SDK `BetaFunctionTool` with `strict: true` whose `call` is the single
choke point where four things happen for every tool call, in order (FR-004,
contracts/agent-tools.md):

1. the active `ToolContext` is bound, so the tool function itself takes only the
   arguments the model chose;
2. arguments are validated against the generated schema by the SDK's own
   `pydantic.validate_call`, on top of the id and enum checks the tool functions run;
3. an `InvestigationStep` is appended to the session with the arguments, a short result
   summary, the status and the elapsed time - whether the call succeeded or not;
4. a failure becomes a `tool_result` with `is_error: true` (the SDK's `ToolError`) and a
   `failed` coverage item, so it stays visible in the report instead of vanishing.

An error result the tool function returned itself (`{"error": ...}` for an unknown id,
say) is treated exactly like a raised exception: same `is_error`, same `failed` coverage.
The model never has to guess whether a result was a result.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from anthropic.lib.tools import BetaFunctionTool, ToolError
from pydantic_core import to_jsonable_python

from swreview.report.session import CoverageItem, CoverageScope, InvestigationStep
from swreview.tools import query, session
from swreview.tools.context import ToolContext, use_context

TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = (
    query.get_package_summary,
    query.list_components,
    query.get_component,
    query.find_components,
    query.list_mates,
    query.list_holes,
    query.list_fasteners,
    query.list_interferences,
    query.get_drawing_sheet,
    query.find_dimensions,
    query.list_gaps,
    query.get_exceptions,
    session.request_evidence,
    session.mark_coverage,
    session.record_drawing_finding,
    session.get_review_checklist,
    session.request_capture,
)
"""Every tool the model gets, in the order of contracts/agent-tools.md.

There is no code-execution tool, no file tool and no SOLIDWORKS call outside this list
(FR-006). The measurement and check tools of the contract arrive with their own tasks.
"""

SUMMARY_LENGTH = 200
"""`InvestigationStep.result_summary` is a trace line, not a second copy of the result."""


def summarize(payload: Any) -> str:
    """A one-line, bounded rendering of a tool result for the session trace."""
    if isinstance(payload, dict) and "error" in payload:
        text = str(payload["error"])
    elif isinstance(payload, list):
        text = f"{len(payload)} items: " + json.dumps(payload, separators=(",", ":"))
    else:
        text = json.dumps(payload, separators=(",", ":"))
    if len(text) <= SUMMARY_LENGTH:
        return text
    return text[: SUMMARY_LENGTH - 1] + "…"


class RecordedTool(BetaFunctionTool[Any]):
    """One curated tool: schema-strict, context-bound, and recorded in the session."""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        context: ToolContext,
        forced_failure: bool = False,
    ) -> None:
        super().__init__(func, strict=True)
        self.context = context
        self.forced_failure = forced_failure

    def call(self, input: object) -> str:
        """Run the tool, record the step, and hand back JSON text for the tool result."""
        arguments = dict(input) if isinstance(input, dict) else {"input": repr(input)}
        started = perf_counter()
        try:
            if self.forced_failure:
                raise RuntimeError(f"tool {self.name!r} was told to fail (--fail-tool)")
            with use_context(self.context):
                payload = to_jsonable_python(super().call(input))
        except Exception as exc:  # noqa: BLE001 - every failure becomes a tool result
            message = f"{type(exc).__name__}: {exc}"
            text = json.dumps({"error": message})
            elapsed = perf_counter() - started
            self._record(arguments, summarize({"error": message}), elapsed, message)
            raise ToolError(text) from exc

        error = payload.get("error") if isinstance(payload, dict) else None
        text = json.dumps(payload)
        self._record(arguments, summarize(payload), perf_counter() - started, error)
        if error is not None:
            raise ToolError(text)
        return text

    def _record(
        self,
        arguments: dict[str, Any],
        result_summary: str,
        elapsed_s: float,
        error: str | None,
    ) -> None:
        review = self.context.session
        review.steps.append(
            InvestigationStep(
                index=len(review.steps),
                tool=self.name,
                arguments=to_jsonable_python(arguments),
                result_summary=result_summary,
                status="error" if error is not None else "ok",
                elapsed_s=max(elapsed_s, 0.0),
                error=error,
            )
        )
        if error is None:
            return
        review.coverage.failed.append(
            CoverageItem(
                check=f"tool.{self.name}",
                scope=CoverageScope(),
                reason=f"tool {self.name} failed; whatever it was called for is not covered",
                error=error,
            )
        )


@dataclass(frozen=True)
class ToolRegistry:
    """The curated tool surface. `build` is the only entry point callers need."""

    functions: tuple[Callable[..., Any], ...] = TOOL_FUNCTIONS

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(function.__name__ for function in self.functions)

    def build(
        self,
        context: ToolContext,
        fail_tool: Iterable[str] = (),
    ) -> list[RecordedTool]:
        """The runner-ready tools bound to `context`.

        `fail_tool` names tools that must raise instead of running - the `--fail-tool`
        test hook that proves a failed tool ends up in `failed` coverage rather than
        stopping the review. An unknown name is a caller mistake and raises.
        """
        forced = set(fail_tool)
        unknown = sorted(forced - set(self.names))
        if unknown:
            raise ValueError(f"fail_tool names no such tool: {unknown}; known: {list(self.names)}")
        return [
            RecordedTool(function, context=context, forced_failure=function.__name__ in forced)
            for function in self.functions
        ]


def build_tools(context: ToolContext, fail_tool: Iterable[str] = ()) -> list[RecordedTool]:
    """The default curated tool list, bound to `context`."""
    return ToolRegistry().build(context, fail_tool=fail_tool)
