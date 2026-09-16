"""The OpenAI adapter: one review turn on the Responses API (T018).

The Responses API is a stateless list of items. This adapter keeps the whole list on every
request - it never uses `previous_response_id` - and echoes `response.output` back
verbatim, reasoning items included, because a reasoning model is only allowed to see its
own earlier thinking if we hand it back. Those raw items ride the runner's
provider-neutral history under the adapter's own `"openai"` key (`providers/__init__.py`),
so a resumed session replays exactly the bytes the API sent us.

Four things are worth stating because they are easy to get subtly wrong:

**The output ceiling is passed in, never inherited.** Feature 001's runner carried
`max_tokens = 16000` with a comment saying it was the retired provider's non-streaming
ten-minute ceiling and should be raised only together with `stream=True`. This adapter
always streams, and on a reasoning model the thinking tokens come out of the same budget,
so that number is simply the wrong one. `agent/settings.py`'s `output_ceiling` owns the
per-provider, per-model number and this adapter asks it; there is no ceiling of its own
here, and `max_output_tokens` on the constructor only overrides it.

**A ceiling that is hit is not an end.** `status: "incomplete"` with
`incomplete_details.reason == "max_output_tokens"` is neither an exception nor a tool
error: the turn ends `truncated`, and the runner turns that into an `unresolved` coverage
item so a cut-short answer is never read as a finished one. A function call whose
arguments will not parse is the same event seen from the other side - the argument stream
was cut off mid-JSON - and ends the turn the same way.

**Effort fails fast.** `reasoning.effort` levels differ by model. `effort_mapping` raises
`EffortNotSupportedError` for a level the chosen model does not offer rather than quietly
sending a weaker one, and `run` maps the effort before it opens a connection, so an
unsupported level costs nothing. A model this table does not know is passed through
unchanged: refusing an id we have merely never heard of would be worse than letting the
API be the authority, and its `400` arrives as a named `OpenAIProviderError`.

**The key never leaves this module.** OpenAI echoes the offending key back in its
authentication errors, so every message this adapter raises or emits goes through
`agent/settings.py`'s `redact` first - the same masking the logging filter applies, called
here on the one string this adapter is about to hand upwards.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from time import perf_counter
from typing import Any

import openai
from openai import OpenAI
from openai.types.responses import Response

from swreview.agent.providers import (
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    ProviderTool,
    TokenUsage,
    ToolCallRequest,
    ToolCallResult,
    ToolSet,
    TurnResult,
    call_tool,
    error_body,
    register,
    usage_body,
)
from swreview.agent.providers.schema import strictify
from swreview.agent.settings import output_ceiling, redact

__all__ = [
    "EFFORT_BY_MODEL",
    "EFFORT_PARAM",
    "EffortNotSupportedError",
    "MalformedArgumentsError",
    "OpenAIProvider",
    "OpenAIProviderError",
    "tool_param",
    "usage_of",
]

EFFORT_PARAM = "reasoning.effort"
"""The request field an effort level maps to; recorded in `EffortMapping.provider_param`."""

EFFORT_BY_MODEL: dict[str, frozenset[str]] = {
    "gpt-5.6": frozenset({"low", "medium", "high", "xhigh"}),
    "gpt-5.5": frozenset({"low", "medium", "high", "xhigh"}),
    "gpt-5.1": frozenset({"low", "medium", "high", "xhigh"}),
    "gpt-5": frozenset({"low", "medium", "high"}),
    "o4-mini": frozenset({"low", "medium", "high"}),
    "o3": frozenset({"low", "medium", "high"}),
}
"""Which of our four levels each model family offers, matched by longest model-id prefix.

`gpt-5-mini` matches `gpt-5` and so has no `xhigh`; `gpt-5.6-sol` matches `gpt-5.6` and
does. A model id that matches nothing here is not in the table and its effort is passed
through - see the module docstring.
"""

TRUNCATED_ARGUMENTS = (
    "not run: the function call arguments were cut off mid-JSON and could not be parsed; "
    "the turn ended on the output ceiling"
)

TRUNCATED_CEILING = "not run: the turn ended on the output ceiling before the call was dispatched"

BUDGET_EXHAUSTED = (
    "not run: the per-turn step budget was already spent when the model asked for this call"
)
"""Why a call the model made has an output but no result: every `function_call` in the
echoed history needs a matching `function_call_output` or the next request is rejected."""

NOT_AN_OBJECT = "not run: the function call arguments were valid JSON but not a JSON object"

HISTORY_KEY = "openai"
"""Where the raw `response.output` items ride the provider-neutral history."""


class OpenAIProviderError(RuntimeError):
    """A provider failure, named and classified, with the key already redacted.

    `error_class` is the `openai` exception this came from, so a reader of `events.jsonl`
    sees the real cause; `retryable` is this adapter's judgement of whether spending
    another run could plausibly work (a rate limit or a dropped connection, yes; a bad key
    or a rejected schema, no).
    """

    def __init__(self, message: str, *, error_class: str, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.error_class = error_class
        self.retryable = retryable


class EffortNotSupportedError(ValueError):
    """The chosen model does not offer the requested effort level. Never downgraded."""


class MalformedArgumentsError(ValueError):
    """A `function_call` whose argument string did not survive the wire. Internal."""


def tool_param(tool: ProviderTool | Any) -> dict[str, Any]:
    """One tool in the Responses API's flat function shape, with strict mode on.

    Accepts anything with `name`, `description` and `schema`: a `RecordedTool` at run time
    and a bare `ToolSpec` in the key-gated schema test (T018a).
    """
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "strict": True,
        "parameters": strictify(tool.schema),
    }


def usage_of(response: Response, *, latency_s: float) -> TokenUsage:
    """What one round trip cost, from the `Response` the API finished on.

    Streaming and non-streaming read the same object: `ResponseCompletedEvent.response`
    and `ResponseIncompleteEvent.response` are both a `Response` (VERIFIED), which is
    exactly what `_respond` already captures as `final`, so no `stream_options` and no
    `include` flag is needed and there is no usage-only stream event to subscribe to.

    Every field is read with `getattr(..., None)` rather than by attribute access, because
    `Response.usage` is `Optional[ResponseUsage]` and because the SDK builds these models
    with `BaseModel.construct`, which leaves a field the server omitted at its default -
    `None` for a required field. `input_tokens_details` can therefore be `None` on a real
    response, and a newly added sub-count such as `cache_write_tokens` can be missing from
    an endpoint that does not report it yet. Those cases map to `None` and never to `0`:
    "the endpoint did not say" is not "it said zero" (Principle I).

    `tool_result_input_tokens` is `None` because OpenAI does not report it separately -
    the tokens our tool results cost are already inside `input_tokens`. Gemini reports the
    same quantity as its own field, and writing `0` here would make the two look
    comparable on a column only one of them has.

    `reasoning_tokens` is a **subset of** `output_tokens` here (the opposite of Gemini,
    where thoughts are a separate addend of the total), so the two are never summed.
    """
    usage = getattr(response, "usage", None)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        cached_input_tokens=getattr(input_details, "cached_tokens", None),
        cache_write_tokens=getattr(input_details, "cache_write_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        reasoning_tokens=getattr(output_details, "reasoning_tokens", None),
        tool_result_input_tokens=None,
        total_tokens=getattr(usage, "total_tokens", None),
        latency_s=latency_s,
    )


class OpenAIProvider:
    """One turn on the Responses API. `providers.get("openai")` returns this class."""

    name = ProviderName.OPENAI

    def __init__(
        self,
        *,
        model: str,
        max_output_tokens: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: OpenAI | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        """Build an adapter for one model.

        Args:
            model: The model id. No default here: `agent/settings.py` owns the per-provider
                default so no code path can write another vendor's model id into a session.
            max_output_tokens: The output ceiling for one turn; reasoning tokens are drawn
                from it too. Omitted, it is `agent/settings.py`'s ceiling for this provider
                and model, which is the one authority for it - never the `16000` feature
                001's runner carried for a non-streaming provider.
            api_key: The key, when this adapter builds its own client.
            base_url: An alternate endpoint (`OPENAI_BASE_URL`), when one is configured.
            client: A ready-made client, which is how the tests inject a recorded one.
            clock: Monotonic clock for `elapsed_s`; injectable so a test can freeze it.
        """
        ceiling = (
            output_ceiling(ProviderName.OPENAI, model)
            if max_output_tokens is None
            else max_output_tokens
        )
        if ceiling <= 0:
            raise ValueError(f"max_output_tokens must be positive, got {ceiling!r}")
        if client is None and not api_key:
            raise ValueError("an OpenAI adapter needs either an api_key or a ready-made client")
        self.model = model
        self.max_output_tokens = ceiling
        self._client = client if client is not None else OpenAI(api_key=api_key, base_url=base_url)
        self._api_key = api_key if api_key else str(getattr(self._client, "api_key", "") or "")
        self._clock = clock
        self._step_index = 0
        self.round_usage: list[TokenUsage] = []
        """This turn's round trips, one record each, in the order they were made.

        Reset by `run()`, because an adapter sees one turn - the convention `step_index`
        already follows. It is a per-round record and not a field on `TurnResult` because
        a turn that raises on its sixth round never builds a `TurnResult`, and the five
        rounds it already paid for are the ones worth the most.
        """

    # --- effort -----------------------------------------------------------------------

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        """What `effort` becomes for this model, or `EffortNotSupportedError`."""
        offered = self._offered_levels()
        if offered is not None and effort not in offered:
            available = ", ".join(sorted(offered))
            raise EffortNotSupportedError(
                f"model {self.model!r} does not offer {EFFORT_PARAM} {effort!r}; "
                f"it offers {available}. Choose one of those rather than accepting a "
                "silently weaker run."
            )
        return EffortMapping(requested=effort, provider_param=EFFORT_PARAM, provider_value=effort)

    def _offered_levels(self) -> frozenset[str] | None:
        """The levels this model offers, or `None` when the model is not in the table."""
        matches = [prefix for prefix in EFFORT_BY_MODEL if self.model.startswith(prefix)]
        if not matches:
            return None
        return EFFORT_BY_MODEL[max(matches, key=len)]

    # --- the turn ---------------------------------------------------------------------

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
        """Run one turn: stream, run the tool calls it asks for, stop on an end or a budget."""
        mapping = self.effort_mapping(effort)  # before the connection: never a silent downgrade
        tool_params = [tool_param(tool) for tool in tools]
        history = [dict(message) for message in messages]
        texts: list[str] = []
        steps = 0
        self.round_usage = []

        while True:
            started = self._clock()
            response = self._respond(
                system=system,
                history=history,
                tool_params=tool_params,
                effort_value=str(mapping.provider_value),
                on_event=on_event,
            )
            # Per round, not per turn: `_respond` is one HTTP request and this loop runs
            # once per request, so a turn with six serial tool calls records seven of
            # these. The clock is read around the request alone, so the local time the
            # tool calls take is outside the latency this records.
            recorded = usage_of(response, latency_s=max(self._clock() - started, 0.0))
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
            raw_output = [
                item.model_dump(mode="json", exclude_unset=True) for item in response.output
            ]
            round_text = _output_text(response)
            if round_text:
                texts.append(round_text)

            # The ceiling is checked before the calls are dispatched: a response that ran
            # out of budget mid-tool-call is cut short whatever else it contains, and
            # running those calls would spend the session on a request we already know is
            # incomplete.
            if self._hit_ceiling(response, on_event):
                _append_assistant(history, round_text, raw_output, calls=())
                _append_unrun(history, response, TRUNCATED_CEILING)
                return self._finish("truncated", texts, steps, history, on_event)

            try:
                requests = _tool_requests(response)
            except MalformedArgumentsError as malformed:
                # The argument stream did not survive the wire - cut off mid-JSON is the
                # same ceiling, seen from the other side. The turn is cut short, not ended,
                # and every call still gets an output so the history stays replayable.
                _append_assistant(history, round_text, raw_output, calls=())
                _append_unrun(history, response, str(malformed))
                return self._finish("truncated", texts, steps, history, on_event)

            _append_assistant(history, round_text, raw_output, calls=requests)

            if not requests:
                return self._finish("end", texts, steps, history, on_event)

            for request in requests:
                if steps >= max_steps:
                    history.append(_tool_message(request, {"error": BUDGET_EXHAUSTED}, True))
                    continue
                result = self._call(request, tools, on_event)
                history.append(_tool_message(request, result.payload, result.is_error))
                steps += 1

            if steps >= max_steps:
                return self._finish("max_steps", texts, steps, history, on_event)

    # --- internals --------------------------------------------------------------------

    def _respond(
        self,
        *,
        system: str,
        history: Sequence[Mapping[str, Any]],
        tool_params: Sequence[dict[str, Any]],
        effort_value: str,
        on_event: EventCallback,
    ) -> Response:
        """One streamed request; text deltas go out as they arrive."""
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": _encode_history(history),
            "reasoning": {"effort": effort_value},
            "max_output_tokens": self.max_output_tokens,
            "parallel_tool_calls": False,
            "stream": True,
        }
        if tool_params:
            request["tools"] = list(tool_params)

        final: Response | None = None
        try:
            with self._client.responses.create(**request) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        on_event("text.delta", {"text": event.delta})
                    elif event.type in ("response.completed", "response.incomplete"):
                        final = event.response
                    elif event.type == "response.failed":
                        raise self._failed(event.response, on_event)
        except openai.OpenAIError as exc:
            raise self._mapped(exc, on_event) from exc

        if final is None:
            raise self._raise_error(
                "the response stream ended without response.completed or response.incomplete",
                error_class="IncompleteStreamError",
                retryable=True,
                on_event=on_event,
            )
        return final

    def _hit_ceiling(self, response: Response, on_event: EventCallback) -> bool:
        """Whether this response ended on the output ceiling.

        `incomplete` for any other reason is a real failure - a content filter, a message
        cap - and is raised rather than quietly read as a short answer.
        """
        if response.status != "incomplete":
            return False
        reason = response.incomplete_details.reason if response.incomplete_details else None
        if reason == "max_output_tokens":
            return True
        raise self._raise_error(
            f"the response ended incomplete: {reason}",
            error_class="IncompleteResponseError",
            retryable=False,
            on_event=on_event,
        )

    def _finish(
        self,
        reason: str,
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

    # --- errors -----------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        """The key, masked. OpenAI quotes it back in authentication errors."""
        return redact(text, [self._api_key])

    def _mapped(self, exc: openai.OpenAIError, on_event: EventCallback) -> OpenAIProviderError:
        """One `openai` exception, named, classified, redacted, and announced."""
        if isinstance(exc, OpenAIProviderError):  # pragma: no cover - defensive
            return exc
        if isinstance(exc, openai.APIConnectionError | openai.RateLimitError):
            retryable = True
        elif isinstance(exc, openai.APIStatusError):
            retryable = exc.status_code >= 500
        else:
            retryable = False
        return self._raise_error(
            str(exc),
            error_class=type(exc).__name__,
            retryable=retryable,
            on_event=on_event,
        )

    def _failed(self, response: Response, on_event: EventCallback) -> OpenAIProviderError:
        message = response.error.message if response.error else "the response failed"
        return self._raise_error(
            message, error_class="ResponseFailedError", retryable=True, on_event=on_event
        )

    def _raise_error(
        self, message: str, *, error_class: str, retryable: bool, on_event: EventCallback
    ) -> OpenAIProviderError:
        """Build the error and emit it: the runner's own `error` event cannot classify it."""
        redacted = self._redact(message)
        on_event(
            "error",
            error_body(error_class=error_class, message=redacted, retryable=retryable),
        )
        return OpenAIProviderError(redacted, error_class=error_class, retryable=retryable)


# --- history encoding -------------------------------------------------------------------


def _encode_history(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The runner's neutral history as a Responses `input` list.

    An assistant turn this adapter produced carries its raw `response.output` items and is
    replayed verbatim; one from another adapter (or from the fake) is rebuilt from `content`
    and `tool_calls`, so a session can be resumed on a provider it did not start on.
    """
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "user":
            items.append({"role": "user", "content": message.get("content", "")})
        elif role == "assistant":
            items.extend(_encode_assistant(message))
        elif role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message["call_id"],
                    "output": json.dumps(message.get("content", {})),
                }
            )
        else:
            raise ValueError(f"history message with unknown role {role!r}")
    return items


def _encode_assistant(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = (message.get(HISTORY_KEY) or {}).get("output")
    if raw:
        return copy.deepcopy(list(raw))
    items: list[dict[str, Any]] = []
    if message.get("content"):
        items.append({"role": "assistant", "content": message["content"]})
    for call in message.get("tool_calls", ()):
        items.append(
            {
                "type": "function_call",
                "call_id": call["call_id"],
                "name": call["name"],
                "arguments": json.dumps(call.get("arguments", {})),
            }
        )
    return items


def _append_assistant(
    history: list[dict[str, Any]],
    text: str,
    raw_output: list[dict[str, Any]],
    *,
    calls: Sequence[ToolCallRequest],
) -> None:
    """Record one round of the model's own output, raw items and all."""
    if not raw_output:
        return
    message: dict[str, Any] = {
        "role": "assistant",
        "content": text,
        HISTORY_KEY: {"output": raw_output},
    }
    if calls:
        message["tool_calls"] = [
            {"call_id": call.call_id, "name": call.name, "arguments": dict(call.arguments)}
            for call in calls
        ]
    history.append(message)


def _append_unrun(history: list[dict[str, Any]], response: Response, error: str) -> None:
    """An output for every call we could not run, so the echoed history stays valid."""
    for item in response.output:
        if item.type == "function_call":
            history.append(
                {
                    "role": "tool",
                    "call_id": item.call_id,
                    "name": item.name,
                    "content": {"error": error},
                    "is_error": True,
                }
            )


def _tool_message(
    request: ToolCallRequest, payload: Mapping[str, Any], is_error: bool
) -> dict[str, Any]:
    return {
        "role": "tool",
        "call_id": request.call_id,
        "name": request.name,
        "content": dict(payload),
        "is_error": is_error,
    }


def _tool_requests(response: Response) -> list[ToolCallRequest]:
    """The calls this response asked for, arguments parsed.

    Raises `MalformedArgumentsError` when an argument string will not parse or is not an
    object. Strict mode makes both impossible from a complete response, so the caller reads
    either as the output ceiling rather than as something the model could correct.
    """
    requests: list[ToolCallRequest] = []
    for item in response.output:
        if item.type != "function_call":
            continue
        try:
            parsed = json.loads(item.arguments)
        except json.JSONDecodeError as broken:
            raise MalformedArgumentsError(f"{TRUNCATED_ARGUMENTS}: {broken}") from broken
        if not isinstance(parsed, dict):
            raise MalformedArgumentsError(f"{NOT_AN_OBJECT}: {item.arguments!r}")
        requests.append(ToolCallRequest(call_id=item.call_id, name=item.name, arguments=parsed))
    return requests


def _output_text(response: Response) -> str:
    """Everything the model said in this round, from the authoritative message items."""
    parts: list[str] = []
    for item in response.output:
        if item.type != "message":
            continue
        for content in item.content:
            if content.type == "output_text":
                parts.append(content.text)
    return "".join(parts)


register(ProviderName.OPENAI, OpenAIProvider)
