# Contract: Cost Reported Honestly

Normative for step sizes, the report's two additions and the pane's usage line (FR-026, FR-027,
SC-009).

## 1. Step sizes

Every `InvestigationStep` a review, a check run or MCP records carries:

| Field | Value |
|---|---|
| `result_bytes` | `len(tool_result_text(payload).encode("utf-8"))` - the full payload in the pre-008 serialization, so sizes compare across settings and with the recorded runs |
| `result_tokens` | `tokens.count_tokens` of the same text, estimated with o200k_base; `null` when the tokenizer is unavailable |

Measured in `record_call`, the one funnel every step passes through; `SessionSink.record` copies
them onto the step. Both optional, `minimum: 0`, omitted from `session.json` when null, so older
sessions and every committed fixture keep their bytes. The chat log's lines do not change (its
fields are explicit). The review-session contract lists both in `InvestigationStep.properties`,
never in `required`, landed before the model writes them.

*Landed as (T088 to T090).* `registry.result_size(payload)` returns the pair, catching only
`TokenizerUnavailable` (the text is `json.dumps` of the payload, ASCII-escaped, so encoding it
cannot fail otherwise). `ToolCallRecord` carries both; `InvestigationStep` declares both with
`ge=0` and drops them from its dump through `omit_when_null` when null.

## 2. The report's Tokens section

Unchanged, byte for byte, when the provider reported cached input: the existing `Cached input
tokens` and `Uncached input tokens` lines are the two numbers. One line is added, only when the
cached total is null:

```
- Cache split not reported: the provider sent no cached-input count
```

## 3. The report's largest results

Only when `session.usage` is present and at least one step carries sizes, between `## Tokens` and
the Investigation Trace:

```
## Largest tool results

Estimated with o200k_base from each step's full result.

| Step | Tool | Bytes | Tokens |
|---|---|---|---|
| 3 | check_rms_part | 612,418 | 204,857 |
```

At most five rows, ordered by tokens descending, then bytes descending, then step index; a null
token count prints `unknown` and sorts after every known one. Check folders (no usage) and every
existing golden (no sizes) render no such section.

## 4. The pane's usage line

`usageLine(rounds)` in `extractor/SwReview.AddIn/Review/ReviewPage/render.js` reads only
`input_tokens`, `cached_input_tokens`, `total_tokens` and `latency_s` from the usage events, and
nothing else in the page changes:

| Case | Line |
|---|---|
| no round yet | `No model round trips yet.` (unchanged) |
| every round reported input and cached input, and summed cached <= summed input | `<U> uncached + <C> cached input - <T> tokens in all - <K> round trips - last round <S>` with `U = Σinput - Σcached` |
| any round without a cached count, any without an input count, or summed cached > summed input | `<I> input (cache split not reported) - <T> tokens in all - <K> round trips - last round <S>`, or `input unknown (cache split not reported)` when an input count is missing |
| a total not reported by every round | `tokens unknown` in place of `<T> tokens in all` (unchanged rule: a partial sum is never shown) |

No percentage. The words are the report's (research R2.46). The change is confined to
`usageLine` and its doc comment, and lands after the feature 009 page work it must be rebased
onto.
