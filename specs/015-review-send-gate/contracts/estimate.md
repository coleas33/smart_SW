# Contract: The Size of the First Request

Normative for the estimate beside Send to model, its sentence, its record, and the check against
real recordings (FR-012, FR-013, SC-006). Amends 008 `contracts/cost.md` (a new surface) and
`contracts/tokenizer.md` section 1 (the pane sentence names no encoding; a Gemini figure is called
approximate - recorded departures, spec FR-012 and FR-013).

## 1. What is counted

Exactly the fixed text of the model's first request, as Send would send it:

```python
def request_prefix(system: str, tools: Iterable[ProviderTool], opening: str) -> str:
    """What every request of a review starts with: the system prompt, the tools, the opening."""
    return system + json.dumps(
        [{"name": t.name, "description": t.description, "parameters": t.schema} for t in tools]
    ) + opening
```

in `agent/runner.py`, the replay's `_prefix(run)` (`benchmark/replay.py:350-361`) moved and called by
it as `request_prefix(run.system, run.tools, run.opening_message)` - byte for byte, which a
characterization committed before the move proves (section 7). The estimate is

```python
ReviewRun.first_request_estimate() -> int | None
    = count_tokens(request_prefix(self.system, self.tools, self.opening_at_send()))
```

with feature 008's one encoding (`tokens.count_tokens`, `o200k_base`), on this machine, with no
network and no model call. `self.tools` is what the adapter would be handed - the offered tools,
less what lever 13 withheld - so the count covers the tool list the request carries. The per-result
framing an adapter adds (`FRAMING_TOKENS`) does not apply: the first request carries no tool result.

## 2. When it is counted

Only in the run's Send cache (`ReviewRun.build_send_cache()`, `review-flow.md` section 5), on a
worker thread, at the three points where the opening can change: the unticked start and a re-run
(after `start_review` and the carry, before the finalization) and an apply while waiting (after the
regrade, before its finalization). A failure there is the start's error body or an apply failure,
both already defined (*second review, 2026-10-09*). The attention and snapshot routes compute on the
event loop and never write, so they only read the cache, and Send reads the same cached figure and
records it. No route counts a token. A review restored from its folder is not counted until its
re-run (the text is not in memory). The vocabulary loads once per process (about 0.13 s,
`tokens.py`), on the first count.

## 3. When there is no number

| Case | `input_tokens` | Sentence |
|---|---|---|
| counted | the count | `send.first_request` |
| counted, provider Gemini | the count | `send.first_request_approximate` |
| the vocabulary is not on this machine (`TokenizerUnavailable`) | `None` | `send.without` |
| restored from its run folder, not yet re-run | `None` | `send.restored` |

The words are `words.md` section 1. A `None` is never shown as zero (Principle I). The pane sentence
names no encoding: an engineer reads a size, not an encoding (FR-013). Cost is in tokens, never
currency (feature 008).

## 4. Gemini

Gemini is counted with the same encoding (008 `tokenizer.md` section 1 prices a Gemini recording the
same way) and the number is shown, called approximate, because Gemini counts tokens its own way
(FR-012, the spec's default). `approximate` is `provider == "gemini"`; the scripted provider is counted
and not approximate.

## 5. Where it is recorded

At Send: `model_status.estimate {input_tokens, encoding: "o200k_base", approximate}` once the first
round completes (`records.md` section 1), and the same object on the `session.sent` event. The
transcript's Send line may print it (the Transcript is where token counts live, 009 `views.md`
section 2).

## 6. SC-006: against real recordings

`test_send_estimate.py::test_the_estimate_bounds_each_recordings_billed_first_round`: for each real
OpenAI recording the replay reads - outside the repository, through the owner's recording mapping
(008 `replay.md` section 8) - the replay's first pass rebuilds the first request (`request_prefix` of
its run) and the test counts it; the count must be at least the recording's billed first-round
`input_tokens` and at most 25% above it. Each recording's gap is printed as a percentage only - no
size, no name. The test finds each recording through `tests/support/recordings.recording_folder`,
which skips, naming why, when the mapping or the folder is absent - as the replay's real-recording
tests do - and needs the vocabulary fixture; it adds no pytest marker (`pyproject.toml` registers
none for recordings). Feature 008 measured one recording at 19.5% high (13,151 counted against 11,006
billed; its research R2.5).

## 7. Tests

`test_send_estimate.py` (research R4.1):

- **the move is byte for byte**, proven by a characterization committed before it, never by
  comparing `request_prefix` with the `_prefix` that now calls it:
  `test_request_prefix_characterization.py` (research R2.28) holds, for each of the three committed
  replay fixtures under the pane defaults, the sha256 and the length of the first pass's
  `PlayedReview.prefix` (`benchmark/replay.py:244`, filled from `_prefix(run)` at `:368`), and the
  commit that moves the function keeps it green. `test_replay_fixtures.py`'s committed counts prove
  nothing here (*second review, 2026-10-09*): `BIG_RECORDED_TOTAL` and `BIG_FOLLOW_UP_RECORDED` are
  sums of the fixtures' recorded usage (`replay.py:1320`, `:1595-1597`; the test's docstring,
  `test_replay_fixtures.py:236-238`), the as-recorded input never reads the prefix (`:1352-1356`), and
  the requested pass reads only the difference of two prefixes' counts (`:922`), which a change both
  passes share cancels;
- the count follows an apply, and is made in the cache, never by a route (a builder patched to raise
  once the cache exists leaves the attention and snapshot routes answering);
- `None` with the vocabulary absent, by `monkeypatch.setattr(tokens, "encoding", <a function raising
  TokenizerUnavailable>)` - the precedent `test_step_sizes.py:166-171`. `tokens.encoding` is cached
  once per process (`tokens.py:150-153`) and the gate runs with `SWREVIEW_REQUIRE_TOKENIZER=1`, so
  pointing `SWREVIEW_TOKENIZER_DIR` at an empty folder would meet a warm cache and see a number;
- Gemini approximate; the four sentences; SC-006 as above.
