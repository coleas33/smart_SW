# Contract: Answer Turns That Cost Only What They Need, and the Replay Gate

Normative for FR-045 to FR-048 and User Story 6. Research R2.32 to R2.36, R3 C12, C13, R5. Amends
feature 005's `contracts/levers.md` (lever 14), feature 008's `contracts/model-view.md` section 7
(lever 14 beside pruning) and `contracts/replay.md` section 9 (a re-measured row per regeneration),
and feature 001's `contracts/agent-tools.md` (`mark_coverage`'s result).

## 1. The close-out, closed by code

`coverage.closeout` is code-owned (`re-ask-guard.md` section 1). `finalize_session`
(`agent/runner.py:436`) writes exactly one row for it, check `coverage.closeout`, bucket `checked`,
withdrawn by identity and rewritten on a second finalization (rule 1, like its other rows):

> Closed by code when the review ended: {r} open evidence requests are listed as unresolved coverage
> (coverage.evidence_request); the package records {g} gaps: {n1} {kind1}, {n2} {kind2}, …

`{kind}` is each gap kind's word, in the order the package lists kinds; "no gaps" when there are none.
`was_cut_short`'s two reasons (`report/session.py:201-215`) and `_closeout`'s unresolved row for a turn
cut short are untouched, so a cut-short turn still reads as one. `attention.CLOSEOUT_ITEM_ID`'s
exclusion is unchanged.

## 2. `open_items` on coverage results

`mark_coverage`'s recorded result and `request_evidence`'s recorded result gain:

```json
{"status": "recorded", "bucket": "checked", "coverage_item": {…},
 "open_items": ["interfaces.stack", "fasteners"]}
```

`open_items`: the model-owned checklist item ids still open after this call
(`context.checklist.open_items(review)`, less code-owned items), in checklist order; `[]` when none.
Non-error answers (`closed_by_code`, `already_answered`, `already_asked`) carry it too. The tool
docstrings do not change.

## 3. Refusal reasons reach the model

`drawing-capability.md` section 6. Counted here because the sitting's answer turn after a refused
read spent four rounds re-reading unchanged evidence.

## 4. Lever 14: earlier turns' reasoning items leave the request view

```python
# reviewer/src/swreview/agent/settings.py
class EfficiencySettings(BaseModel):
    ...
    drop_prior_reasoning: bool = False
    """Lever 14: at a turn boundary, the OpenAI request view leaves out the reasoning items of
    earlier turns and keeps the current turn's; the stored history is unchanged. Appended last."""
```

- **Where**: `agent/providers/openai_provider.py`, where the request's input items are built from the
  history (`_encode_assistant`, `:697-713`). A turn is the span between two user messages of the
  runner's history; an assistant message's raw `output` items of `type == "reasoning"` from any turn
  before the current one are left out of the request; every other item, and every item of the current
  turn, is sent byte for byte. The runner's history and `session.json` keep every item.
  *Amended 2026-09-27 (the review of that day):* the other items of an earlier message that lost a
  reasoning item are sent without their item ids - a call without `id` (its `call_id` kept), an
  answer in the easy form - because the Responses API refuses a stored item sent back without the
  reasoning item that preceded it; 005 `contracts/levers.md`, lever 14, and the key-gated
  `tests/live/test_openai_live_prior_reasoning.py`.
- **Gemini** sends no reasoning items; the lever is inert there and the session records it as set.
- **Off by default**, and off on the command line and in `benchmark run`. `LEVER_NAMES` and every
  lever-count pin gain one ("the fourteen levers"); `GATED_ALONE` gains nothing.
- **Adoption rule** (default taken 2026-09-26, the owner may revise): the replay (section 5) prices the lever off and
  on over every fixture; when no recorded finding is lost and the requested input falls, a commit of
  its own adds it to `pane_efficiency` and records the ledger row in `levers.md`; otherwise it stays
  off and the figures and the reason are recorded there.
- **Pricing** (research R3 C13): the replay has no reasoning items, only the recorded usage; for lever
  14 on, each round of a turn after the first is priced lower by the sum of the recorded reasoning
  output tokens of every earlier turn's rounds (their `usage` events), which the as-recorded pass
  carries in that round's input. The figure is an estimate and is reported as one.
- **Interaction**: none with lever 3 beyond a prefix break at each turn boundary, which pruning already
  causes; recorded in `levers.md`'s interaction matrix.
- **The fallback** (*amended 2026-09-27, T151-T152; default taken 2026-09-27, the owner may revise;
  research R2.44*): when the endpoint refuses a request that left earlier reasoning out with an
  invalid-request error (`400`) about a missing reasoning item, an item not found or a linked item,
  the OpenAI adapter sends that same request again at once with every reasoning item kept, turns the
  lever off for the rest of that adapter's session, and logs one plain line (the key redacted); the
  refused request emits no `error` event. Any other refusal, a refusal of a request that left nothing
  out, a server or connection error, and a refusal of the resent request are raised as before.
  `session.efficiency` keeps the lever as requested. The key-gated live test fails when the adapter
  fell back, and the next sitting runs it with the key the pane stores (T153, test-plan step 2.7).
  005 `contracts/levers.md`, lever 14.

## 5. The replay gate

Every change of this feature that moves what a tool returns, the system prompt, the checklist, the
opening message or a resumed message passes this gate, on the machine that holds the recordings (the
owner's mapping, 008 `replay.md` section 8).

**When** (settled on review, 2026-09-26, where this section said "before it merges" and the tasks
said "after"): one gate per story, run on `main` after that story's last lane merges, in merge
order, **with a freeze**. From a story's last merge until its gate commit, no other change that moves
what the model reads (research R5's table) may merge; changes that move nothing the model reads may.
The gate's commit follows that story's merges with no such change between them, so a fixture that
moves is attributed to one story. A lane whose queue holds tasks of several stories (lane S holds
US1, US3, US4, US5 and US6) merges a later story's model-read change only after the earlier story's
gate has landed.

The gate's steps:

1. **Regenerate** the three fixtures with section 8's commands and then the pane fixture
   (`tests/fixtures/pane/generate_pane_fixture.py --write`), in a commit of its own (decision 3A: the
   fixtures follow the code; a fixture is never edited by hand).
2. **Replay** under every configuration of section 9's latest row, with
   `--standards-profile ../config/standards.example.yaml`.
3. **Hold**: no recorded finding lost and none unreplayable (absolute); each fixture's recorded contact
   groups (3, 2 and 0) reproduced exactly, none reclassified; pass A within 1% on every round of every
   regenerated fixture; the real recordings' residual zero on every round (section 10).
4. **Record** one "re-measured" row in section 9 naming the change, every figure that moved and why.
5. **Payload pins**: no tool signature or docstring changes (research R3 C14); if a tool array's bytes
   move, `python -m tests.unit.test_tool_payload --write` in a commit of its own, with the reason.

Stories and what each moves are research R5's table. A story that moves nothing the model reads (User
Story 5) runs steps 2 and 3 to prove it.

## 6. Tests

`test_finalize_closeout.py`: the close-out row written once; a second finalization gives one row; the
reason's counts; `mark_coverage(coverage.closeout)` answers `closed_by_code`; a cut-short turn still
reads as cut short. `test_tools_session.py`: `open_items` on every result kind, less code-owned items,
in checklist order. `test_openai_prior_reasoning.py`: with the lever on, earlier turns' reasoning items
are absent from the request and the current turn's present; with it off, the request is byte-identical
to today's; the stored history unchanged. `test_efficiency_settings.py` and the lever-count pins (fourteen).
`test_replay_lever_14.py`: the pricing over a scripted two-turn recording; no finding lost.
