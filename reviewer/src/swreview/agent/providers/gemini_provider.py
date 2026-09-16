"""The Gemini adapter: `generate_content_stream`, our own tool loop, uniform events.

`google-genai` will happily run the tool loop itself - that is what automatic function
calling is - and that is exactly what this adapter must not let it do: every call has to go
through `tools/registry.py`'s `RecordedTool` so it is validated, recorded as an
`InvestigationStep` and turned into an error payload rather than an exception. So
`automatic_function_calling.disable=True` is mandatory, and the loop below is ours.

Four provider details are worth stating, because each one is a trap:

- **Schema.** Tools are declared with `parameters_json_schema`, the standard-JSON-Schema
  field, never the OpenAPI-flavoured `parameters` (the two are mutually exclusive). The
  schema is `providers/schema.py`'s canonical form run through `gemini_adapt`.
- **Thinking.** 3.x models take `thinking_config.thinking_level` (`MINIMAL`..`HIGH`); 2.5
  models take the integer `thinking_config.thinking_budget`, whose allowed range is
  per-model. A level this model cannot express is an error, never a quiet downgrade: an
  engineer who asked for `xhigh` and silently got `high` would read the resulting review as
  something it is not.
- **Call ids.** A `function_call` on 3.5+ carries an `id`, and the matching
  `function_response` must carry it back. Older models send none; this adapter then sends
  none back, rather than inventing one the model never issued.
- **Thought signatures.** Gemini 3 rejects a function-calling history whose thought
  signatures were dropped, and they live on the `Part`, not in any provider-neutral field.
  So each assistant turn keeps the model's own `Content` on its history message under the
  `"gemini"` key (the namespaced provider-state key the `providers` docstring describes),
  and a replayed turn is rebuilt from that rather than reconstructed from text.

- **Finish reasons.** Gemini has eighteen of them and only two mean "the model finished".
  The mapping below is explicit and its default is `error`, never `end`: a turn the
  service refused, filtered or cut off must reach the report as incomplete (constitution
  Principle I), and a reason added to the enum after this was written must not quietly
  read as a completed answer. The reason is consulted *before* the round's tool calls are
  dispatched, because a `function_call` whose arguments were cut off mid-stream is not a
  call worth running.

`generate_content_stream` emits no lifecycle events of its own - just chunks - so the
contract's events are synthesized here: one `text.delta` per streamed text part, one
`text.done` per *turn* carrying everything the turn said (`data-model.md` defines it as
the full turn text, and the pane and `events.jsonl` would lose the first half of a
two-round answer otherwise), and the `tool.started`/`tool.finished` pair around each call.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, ClassVar, Protocol

from google.genai import errors, types
from pydantic import SecretStr

from swreview.agent.providers import (
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    TokenUsage,
    ToolCallRequest,
    ToolCallResult,
    ToolSet,
    TurnEndReason,
    TurnResult,
    call_tool,
    error_body,
    register,
    usage_body,
)
from swreview.agent.providers.schema import gemini_adapt
from swreview.agent.settings import redact

__all__ = [
    "AUTOMATIC_FUNCTION_CALLING_DISABLED",
    "BUDGET_MODEL_PREFIX",
    "BUDGET_PARAM",
    "FINISH_REASONS",
    "LEVEL_PARAM",
    "NATIVE_CONTENT_KEY",
    "THINKING_BUDGETS",
    "THINKING_LEVELS",
    "GeminiAuthError",
    "GeminiBlockedTurnError",
    "GeminiProvider",
    "GeminiProviderError",
    "GeminiRateLimitError",
    "GeminiRequestError",
    "GeminiServerError",
    "UnsupportedEffortError",
    "usage_of",
]

LEVEL_PARAM = "thinking_config.thinking_level"
BUDGET_PARAM = "thinking_config.thinking_budget"

THINKING_LEVELS: dict[str, str] = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
"""Effort to `ThinkingLevel` on the models that have one.

Gemini's levels stop at `HIGH`, so `xhigh` has no Gemini meaning at all and is refused.
`MINIMAL` is deliberately unused: the product's lowest level still wants some reasoning.
"""

BUDGET_MODEL_PREFIX = "gemini-2.5"
"""The one family whose thinking control is the integer budget rather than the level."""

THINKING_BUDGETS: dict[str, dict[str, int]] = {
    "gemini-2.5-pro": {"low": 1024, "medium": 8192, "high": 24576, "xhigh": 32768},
    "gemini-2.5-flash": {"low": 1024, "medium": 8192, "high": 24576},
    "gemini-2.5-flash-lite": {"low": 512, "medium": 8192, "high": 24576},
}
"""Effort to `thinking_budget`, per 2.5 model, longest prefix wins.

The ranges are model-specific (pro reaches 32768; the flash models stop at 24576), so the
top level of each model is its documented maximum and an effort the model cannot reach is
absent rather than clamped. A 2.5 model with no row here is refused too: guessing a budget
for an unknown model is how a run silently gets a thinking level nobody chose.
"""

AUTOMATIC_FUNCTION_CALLING_DISABLED = types.AutomaticFunctionCallingConfig(disable=True)
"""Mandatory: our loop runs every tool call, so the SDK must not run any."""

NATIVE_CONTENT_KEY = "gemini"
"""Where an assistant history message keeps the model's own `Content` (thought signatures)."""

FINISH_REASONS: dict[types.FinishReason, TurnEndReason] = {
    types.FinishReason.FINISH_REASON_UNSPECIFIED: "end",
    types.FinishReason.STOP: "end",
    types.FinishReason.MAX_TOKENS: "truncated",
    types.FinishReason.MALFORMED_FUNCTION_CALL: "truncated",
    types.FinishReason.UNEXPECTED_TOOL_CALL: "truncated",
}
"""`FinishReason` to `turn.ended` reason. Anything absent is an `error`, deliberately.

Only `STOP` (and the unset placeholder) mean the model finished. `MAX_TOKENS` is the
output ceiling; `MALFORMED_FUNCTION_CALL` and `UNEXPECTED_TOOL_CALL` are Gemini's side of
OpenAI's unparseable-arguments path - the model meant to call a tool and the call did not
survive - so all three are `truncated`: cut short, not done.

Every other reason the enum carries (`SAFETY`, `RECITATION`, `BLOCKLIST`,
`PROHIBITED_CONTENT`, `SPII`, `LANGUAGE`, `TOO_MANY_TOOL_CALLS`, `OTHER`, and the image
ones) is a turn the service stopped, and so is any reason added to the enum after this was
written. Defaulting those to `end` would report a refused turn as a completed review.
"""


class UnsupportedEffortError(ValueError):
    """The requested effort has no representation on this model. Never downgraded."""


class GeminiProviderError(RuntimeError):
    """A Gemini API failure, mapped and redacted. `retryable` is what the pane offers."""

    retryable: ClassVar[bool] = True


class GeminiAuthError(GeminiProviderError):
    """401/403: the key is missing, wrong, or not entitled to this model."""

    retryable: ClassVar[bool] = False


class GeminiRateLimitError(GeminiProviderError):
    """429: quota or rate limit. Worth another run."""

    retryable: ClassVar[bool] = True


class GeminiRequestError(GeminiProviderError):
    """Any other 4xx: the request itself is wrong, so retrying it changes nothing."""

    retryable: ClassVar[bool] = False


class GeminiServerError(GeminiProviderError):
    """5xx: the model or the service, not us."""

    retryable: ClassVar[bool] = True


class GeminiBlockedTurnError(GeminiProviderError):
    """The turn was stopped by the service: refused, filtered, or cut off.

    Reported through the `error` event and *not* raised: the text already streamed and the
    history built so far are still worth keeping, and the runner turns a turn that ended
    `error` into unresolved coverage rather than a lost session.
    """

    retryable: ClassVar[bool] = False


class _Models(Protocol):
    """The one client method this adapter uses (so a stub is a whole client)."""

    def generate_content_stream(
        self, *, model: str, contents: Any, config: Any
    ) -> Iterable[types.GenerateContentResponse]: ...


class _Client(Protocol):
    models: _Models


@dataclass
class _Round:
    """One `generate_content_stream` call: what the model said, asked for, and why it stopped."""

    text: str
    calls: list[ToolCallRequest]
    parts: list[types.Part]
    finish_reason: types.FinishReason | None
    usage: types.GenerateContentResponseUsageMetadata | None = None
    """The provider's own usage object, unmapped, or `None` when no chunk carried one.

    Kept raw here and mapped once in `run()`, so the arithmetic lives in `usage_of` and
    not in the stream loop.
    """

    def content(self, keep_calls: int) -> types.Content:
        """The model's own `Content`, keeping only the first `keep_calls` function calls.

        The step budget can cut a round short mid-way through its calls. An unanswered
        `function_call` left in the history is rejected on the next request, so the calls
        that were not run are dropped from the turn the history records.
        """
        parts: list[types.Part] = []
        seen = 0
        for part in self.parts:
            if part.function_call is not None:
                seen += 1
                if seen > keep_calls:
                    continue
            parts.append(part)
        return types.Content(role="model", parts=parts)


def usage_of(
    metadata: types.GenerateContentResponseUsageMetadata | None, *, latency_s: float
) -> TokenUsage:
    """What one round trip cost, from the `usage_metadata` the stream carried.

    Every field of `GenerateContentResponseUsageMetadata` is `Optional[int] = None` by
    declaration (VERIFIED, `google/genai/types.py:8445-8496`), and a stream may carry no
    usage at all, so `metadata` itself is nullable and every field is read with
    `getattr(..., None)`. An unreported count maps to `None` and never to `0`: "the
    service did not say" is not "it said zero" (Principle I).

    **The two arithmetic facts this mapping must not get wrong are opposites of each
    other**, both VERIFIED from the package's own field descriptions:

    - `cached_content_token_count` is **inside** `prompt_token_count` (`types.py:8468-
      8471`: "When `cached_content` is set, this also includes the number of tokens in the
      cached content"). Adding them double counts, so `input_tokens` is the prompt count
      unchanged and cached input is recorded beside it, contained in it.
    - `tool_use_prompt_token_count` is **outside** `prompt_token_count` and is a separate
      addend of `total_token_count` (`types.py:8488-8491`). It is therefore kept in its
      own field rather than folded into `input_tokens`, which would make the parts stop
      adding up to the provider's total. It is a first-class number for us because our
      reviewer feeds every tool result back as input, and dropping it would understate
      our input cost by whatever sixty-odd tool results weigh.

    The same asymmetry runs the other way on output: `thoughts_token_count` is a separate
    addend of the total here, while OpenAI's `reasoning_tokens` is a subset of its output
    count. Nothing is derived; `total_tokens` is the service's own number.

    `cache_write_tokens` is `None` because Gemini reports no cache-write count at all.
    """
    return TokenUsage(
        input_tokens=getattr(metadata, "prompt_token_count", None),
        cached_input_tokens=getattr(metadata, "cached_content_token_count", None),
        cache_write_tokens=None,
        output_tokens=getattr(metadata, "candidates_token_count", None),
        reasoning_tokens=getattr(metadata, "thoughts_token_count", None),
        tool_result_input_tokens=getattr(metadata, "tool_use_prompt_token_count", None),
        total_tokens=getattr(metadata, "total_token_count", None),
        latency_s=latency_s,
    )


class GeminiProvider:
    """The Gemini adapter. `providers.get("gemini")` returns this class."""

    name = ProviderName.GEMINI

    def __init__(
        self,
        *,
        client: _Client,
        model: str,
        secrets: Iterable[str | SecretStr | None],
        max_output_tokens: int | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        """Bind a configured client to a model.

        Args:
            client: A `genai.Client`, built by the caller so this module needs no key and
                no knowledge of Gemini's enterprise wiring.
            model: The model id. Never defaulted here; `agent/settings.py` owns defaults.
            secrets: Everything that must never appear in a reported message - normally
                `ProviderSettings.secrets`. Required, with no default: FR-015 makes
                redaction a MUST, and an optional redactor means a constructible adapter
                that reports the key back through the `error` event the pane renders and
                `events.jsonl` keeps. An enterprise run authenticating through ADC passes
                `[]`, which states there is no key here rather than leaving it unsaid.
            max_output_tokens: The per-provider output ceiling, from settings. Omitted
                from the request when `None`, which leaves the model's own default.
            clock: Injectable so `elapsed_s` is comparable in tests.
        """
        self.model = model
        self._client = client
        self._secrets = tuple(secrets)
        self._max_output_tokens = max_output_tokens
        self._clock = clock
        self._step_index = 0
        self.round_usage: list[TokenUsage] = []
        """This turn's round trips, one record each, in the order they were made.

        Reset by `run()`, because an adapter sees one turn - the convention `step_index`
        already follows. Per round and not a field on `TurnResult`, because a turn that
        raises on its sixth round never builds a `TurnResult` and the five rounds it
        already paid for are the ones worth the most.
        """

    # --- effort ------------------------------------------------------------------------

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        """What `effort` becomes on this model, or `UnsupportedEffortError`."""
        if self.model.startswith(BUDGET_MODEL_PREFIX):
            budgets = self._budget_table()
            if effort not in budgets:
                raise UnsupportedEffortError(
                    f"effort {effort!r} has no thinking budget on model {self.model!r}; "
                    f"it offers {_listed(budgets)}"
                )
            return EffortMapping(
                requested=effort, provider_param=BUDGET_PARAM, provider_value=budgets[effort]
            )
        if effort not in THINKING_LEVELS:
            raise UnsupportedEffortError(
                f"effort {effort!r} has no thinking level on model {self.model!r}; "
                f"Gemini offers {_listed(THINKING_LEVELS)}"
            )
        return EffortMapping(
            requested=effort, provider_param=LEVEL_PARAM, provider_value=THINKING_LEVELS[effort]
        )

    def _budget_table(self) -> dict[str, int]:
        """The budget row for this 2.5 model, longest prefix first. No row is an error."""
        matches = [name for name in THINKING_BUDGETS if self.model.startswith(name)]
        if not matches:
            raise UnsupportedEffortError(
                f"no thinking budget table for model {self.model!r}; "
                f"known 2.5 models are {_listed(THINKING_BUDGETS)}"
            )
        return THINKING_BUDGETS[max(matches, key=len)]

    # --- one turn ----------------------------------------------------------------------

    def run(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: ToolSet,
        effort: EffortLevel,
        max_steps: int,
        on_event: EventCallback,
    ) -> TurnResult:
        """Stream rounds until the model stops asking for tools or the budget runs out."""
        mapping = self.effort_mapping(effort)
        config = self._config(system=system, tools=tools, mapping=mapping)
        history = [dict(message) for message in messages]
        contents = _to_contents(history)
        texts: list[str] = []
        steps = 0
        self.round_usage = []

        while True:
            started = self._clock()
            round_ = self._stream(contents, config, on_event)
            # Per round, not per turn: one `generate_content_stream` is one round trip, so
            # a turn with six serial tool calls records seven of these. The clock is read
            # around the stream alone, so local tool time is outside this latency.
            recorded = usage_of(round_.usage, latency_s=max(self._clock() - started, 0.0))
            self.round_usage.append(recorded)
            # Straight onto the stream, before this round's tool calls are dispatched. The
            # sink appends and closes per event, so a round that is paid for is on disk
            # even if the next one raises and no `TurnResult` is ever built.
            on_event(
                "usage",
                usage_body(
                    recorded,
                    round_index=len(self.round_usage) - 1,
                    provider=self.name,
                    model=self.model,
                ),
            )
            if round_.text:
                texts.append(round_.text)

            reason = _end_reason(round_.finish_reason)
            if reason != "end":
                # Checked before any call of this round is dispatched. A round that hit
                # the ceiling or was stopped by the service is incomplete whatever else
                # it carries, and its `function_call` arguments may have been cut off
                # mid-stream, so those calls are not run - and not kept in the history
                # either, because an unanswered `function_call` is rejected on the next
                # request.
                _record_round(history, contents, round_, requests=())
                if reason == "error":
                    self._blocked(round_.finish_reason, on_event)
                return self._finish(reason, texts, steps, history, on_event)

            requests = round_.calls[: max(max_steps - steps, 0)]
            over_budget = len(requests) < len(round_.calls)
            _record_round(history, contents, round_, requests=requests)

            results = [
                self._call(request, tools, on_event) for request in requests
            ]
            for request, result in zip(requests, results, strict=True):
                history.append(
                    {
                        "role": "tool",
                        "call_id": result.call_id,
                        "name": request.name,
                        "content": result.payload,
                        "is_error": result.is_error,
                    }
                )
            if results:
                contents.append(_tool_content(requests, results))
            steps += len(results)

            if over_budget:
                return self._finish("max_steps", texts, steps, history, on_event)
            if not round_.calls:
                return self._finish("end", texts, steps, history, on_event)

    def _finish(
        self,
        reason: TurnEndReason,
        texts: Sequence[str],
        steps: int,
        history: list[dict[str, Any]],
        on_event: EventCallback,
    ) -> TurnResult:
        """Close the turn: one `text.done` carrying everything the turn said."""
        text = "".join(texts)
        if text:
            on_event("text.done", {"text": text})
        return TurnResult(reason=reason, text=text, steps=steps, messages=history)

    # --- the stream --------------------------------------------------------------------

    def _stream(
        self,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
        on_event: EventCallback,
    ) -> _Round:
        """One `generate_content_stream`, turned into deltas, calls and a finish reason."""
        texts: list[str] = []
        calls: list[ToolCallRequest] = []
        parts: list[types.Part] = []
        finish_reason: types.FinishReason | None = None
        usage: types.GenerateContentResponseUsageMetadata | None = None
        try:
            stream = self._client.models.generate_content_stream(
                model=self.model,
                contents=list(contents),
                config=config,
            )
            for chunk in stream:
                # Outside the candidates loop, and last chunk that carries usage wins.
                # The loop below runs per candidate and a final chunk can carry usage and
                # no candidate at all, so a read inside it drops that whole round's cost.
                # The SDK does not aggregate chunk usage (VERIFIED: `google/genai/
                # models.py:1718` and `:1757` copy `usageMetadata` straight through per
                # chunk and nothing under `google/genai/` merges it), so the adapter has
                # to choose. Last-carrying-chunk-wins is right under both "cumulative"
                # and "only the final chunk carries it", and wrong only under "each chunk
                # is a delta", which is UNVERIFIED and is settled by probe G3.
                if chunk.usage_metadata is not None:
                    usage = chunk.usage_metadata
                for candidate in chunk.candidates or []:
                    if candidate.finish_reason is not None:
                        finish_reason = candidate.finish_reason
                    content = candidate.content
                    for part in (content.parts or []) if content is not None else []:
                        parts.append(part)
                        if part.function_call is not None:
                            calls.append(_request(part.function_call))
                        elif part.text and not part.thought:
                            texts.append(part.text)
                            on_event("text.delta", {"text": part.text})
        except errors.APIError as exc:
            raise self._report(exc, on_event) from exc
        return _Round(
            text="".join(texts),
            calls=calls,
            parts=parts,
            finish_reason=finish_reason,
            usage=usage,
        )

    def _report(self, exc: errors.APIError, on_event: EventCallback) -> GeminiProviderError:
        """Map, redact, report and return the failure the caller should raise."""
        return self._emit(_map_error(exc, self._redact), on_event)

    def _blocked(self, finish_reason: types.FinishReason | None, on_event: EventCallback) -> None:
        """Report - never raise - a turn the service refused, filtered or cut off."""
        named = finish_reason.value if finish_reason is not None else "unset"
        self._emit(
            GeminiBlockedTurnError(
                self._redact(
                    f"gemini stopped the turn on finish reason {named}; the answer is "
                    "incomplete and whatever it was checking is unresolved"
                )
            ),
            on_event,
        )

    def _emit(self, error: GeminiProviderError, on_event: EventCallback) -> GeminiProviderError:
        """Announce one mapped failure on the contract's `error` event and hand it back."""
        on_event(
            "error",
            error_body(
                error_class=type(error).__name__,
                message=str(error),
                retryable=type(error).retryable,
            ),
        )
        return error

    def _redact(self, text: str) -> str:
        """The key, masked. Gemini quotes it back in authentication errors."""
        return redact(text, self._secrets)

    # --- the request -------------------------------------------------------------------

    def _config(
        self,
        *,
        system: str,
        tools: ToolSet,
        mapping: EffortMapping,
    ) -> types.GenerateContentConfig:
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=gemini_adapt(tool.schema),
            )
            for tool in tools
        ]
        return types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            automatic_function_calling=AUTOMATIC_FUNCTION_CALLING_DISABLED,
            thinking_config=_thinking_config(mapping),
            max_output_tokens=self._max_output_tokens,
        )

    # --- one tool call -----------------------------------------------------------------

    def _call(
        self,
        request: ToolCallRequest,
        tools: ToolSet,
        on_event: EventCallback,
    ) -> ToolCallResult:
        """Run one call and emit its two events, through the port's own shaper.

        The counter is this turn's; everything after it is identical for every adapter and
        lives in `providers.call_tool`.
        """
        step_index = self._step_index
        self._step_index += 1
        return call_tool(
            request=request,
            tools=tools,
            on_event=on_event,
            step_index=step_index,
            clock=self._clock,
        )


# --- module helpers ----------------------------------------------------------------------


def _listed(table: Mapping[str, Any]) -> str:
    return ", ".join(repr(key) for key in table)


def _thinking_config(mapping: EffortMapping) -> types.ThinkingConfig:
    if mapping.provider_param == BUDGET_PARAM:
        return types.ThinkingConfig(thinking_budget=int(mapping.provider_value))
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel(mapping.provider_value))


def _request(call: types.FunctionCall) -> ToolCallRequest:
    """One `function_call` part as a provider-neutral request.

    A model that sends no `id` gets no id back (`""` here, omitted on the response part):
    inventing one would pair a response to a call the model never made.
    """
    return ToolCallRequest(
        call_id=call.id or "",
        name=call.name or "",
        arguments=dict(call.args or {}),
    )


def _end_reason(finish_reason: types.FinishReason | None) -> TurnEndReason:
    """One `FinishReason` as a `turn.ended` reason, through `FINISH_REASONS`.

    An absent reason is `end`: a stream carries its content in chunks and only the last
    one is required to name a reason. A reason the table does not know is `error`, which
    is the whole point of the table - see `FINISH_REASONS`.
    """
    if finish_reason is None:
        return "end"
    return FINISH_REASONS.get(finish_reason, "error")


def _record_round(
    history: list[dict[str, Any]],
    contents: list[types.Content],
    round_: _Round,
    *,
    requests: Sequence[ToolCallRequest],
) -> None:
    """Append the model's own turn to both histories, keeping only the calls that ran.

    `requests` is the prefix of the round's calls this turn will actually answer: the step
    budget and a terminal finish reason each cut a round short, and a `function_call` with
    no matching `function_response` is rejected on the next request.
    """
    native = round_.content(keep_calls=len(requests))
    if not native.parts:
        return
    message: dict[str, Any] = {
        "role": "assistant",
        "content": round_.text,
        NATIVE_CONTENT_KEY: native.model_dump(mode="json", exclude_none=True),
    }
    if requests:
        message["tool_calls"] = [
            {
                "call_id": request.call_id,
                "name": request.name,
                "arguments": dict(request.arguments),
            }
            for request in requests
        ]
    history.append(message)
    contents.append(native)


def _response_payload(payload: Mapping[str, Any], is_error: bool) -> dict[str, Any]:
    """Gemini reads `output` as the result and `error` as the failure (FunctionResponse)."""
    return {"error": dict(payload)} if is_error else {"output": dict(payload)}


def _response_part(
    name: str, call_id: str, payload: Mapping[str, Any], is_error: bool
) -> types.Part:
    part = types.Part.from_function_response(
        name=name, response=_response_payload(payload, is_error)
    )
    if call_id and part.function_response is not None:
        part.function_response.id = call_id
    return part


def _tool_content(
    requests: Sequence[ToolCallRequest], results: Sequence[ToolCallResult]
) -> types.Content:
    """One `role="tool"` content answering every call of the round, in order."""
    return types.Content(
        role="tool",
        parts=[
            _response_part(request.name, result.call_id, result.payload, result.is_error)
            for request, result in zip(requests, results, strict=True)
        ],
    )


def _to_contents(messages: Sequence[Mapping[str, Any]]) -> list[types.Content]:
    """The provider-neutral history as Gemini contents.

    Consecutive `tool` messages answer one round of parallel calls and become one
    `role="tool"` content, which is the shape the API documents.
    """
    contents: list[types.Content] = []
    answers: list[types.Part] = []

    def flush() -> None:
        if answers:
            contents.append(types.Content(role="tool", parts=list(answers)))
            answers.clear()

    for message in messages:
        role = message.get("role")
        if role == "tool":
            answers.append(
                _response_part(
                    str(message.get("name", "")),
                    str(message.get("call_id", "")),
                    message.get("content") or {},
                    bool(message.get("is_error")),
                )
            )
            continue
        flush()
        if role == "user":
            contents.append(
                types.Content(role="user", parts=[types.Part(text=str(message.get("content", "")))])
            )
        elif role == "assistant":
            contents.append(_model_content(message))
        else:
            raise ValueError(f"history message with unknown role {role!r}")
    flush()
    return contents


def _model_content(message: Mapping[str, Any]) -> types.Content:
    """An assistant turn, replayed from the model's own parts when this adapter wrote it.

    The `"gemini"` key holds the `Content` the model actually produced, thought signatures
    included; Gemini 3 rejects a function-calling history that lost them.
    """
    native = message.get(NATIVE_CONTENT_KEY)
    if native is not None:
        return types.Content.model_validate(native)
    parts: list[types.Part] = []
    text = message.get("content")
    if text:
        parts.append(types.Part(text=str(text)))
    for call in message.get("tool_calls") or []:
        parts.append(
            types.Part(
                function_call=types.FunctionCall(
                    id=call.get("call_id") or None,
                    name=call["name"],
                    args=dict(call.get("arguments") or {}),
                )
            )
        )
    return types.Content(role="model", parts=parts)


def _map_error(exc: errors.APIError, mask: Callable[[str], str]) -> GeminiProviderError:
    """One mapping for every `APIError`, by status code: the class carries `retryable`."""
    code = getattr(exc, "code", None) or 0
    if code in (401, 403):
        failure: type[GeminiProviderError] = GeminiAuthError
    elif code == 429:
        failure = GeminiRateLimitError
    elif isinstance(exc, errors.ServerError) or code >= 500:
        failure = GeminiServerError
    else:
        failure = GeminiRequestError
    return failure(mask(f"gemini {exc}"))


register(ProviderName.GEMINI, GeminiProvider)
