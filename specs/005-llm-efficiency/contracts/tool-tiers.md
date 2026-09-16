# Contract: tool tiers and the withheld tool

Which tools sit in which tier, which tiers are decidable before the first turn, and **how a tool
this run did not offer is reported** to the model, to the session, to the checklist and to the
engineer.

**Flag**: `EfficiencySettings.tool_tiers`, default `False`, read **once at `start_review`** and
**fixed for the whole session**.

A withheld tool is **unresolved coverage with a sentence an engineer can read**, never a silent
miss and never `failed`. That is the whole point of this contract, and today's behaviour is wrong
for it (section 4).

## 1. What already exists, and it is more than the source document assumes

VERIFIED by reading `tools/registry.py`:

- **The registry is already grouped by tier**, in five registration functions named after the
  tables in feature 001 `contracts/agent-tools.md`: `query_tools()` (`:71`),
  `measurement_tools()` (`:92`), `check_tools()` (`:102`), `session_tools()` (`:116`),
  `bridge_tools()` (`:127`). **No new taxonomy is needed.**
- **One tier is already conditional.** `ToolRegistry.functions_for(context)` (`:485-489`) adds
  bridge tools only when `context.bridge is not None`. So "bridge tools only on the workstation" is
  **already implemented**, and the 32-tool number below is the no-bridge number.
- **A per-turn `ToolSet` wrapper is already a shipped pattern.** `StoppableTools`
  (`chat/server.py:355-379`) implements `__iter__`, `__len__` and `call`, which is the whole
  `ToolSet` protocol.

## 2. The tools, by group

32 tools with no bridge (VERIFIED: 15 + 4 + 8 + 5, `TOOL_FUNCTIONS` at `registry.py:145-155`),
35 with `--bridge`.

| Group | Count | As-is bytes | Trimmed at 160/90 | Withholdable |
|---|---|---|---|---|
| Package query | 15 | 10,410 | 8,083 | **partly**: the three RMS query tools only |
| Measurement | 4 | 3,706 | 2,367 | no |
| Check | 8 | **14,182** | 8,203 | **partly**: the three RMS check tools only |
| Session | 5 | 5,770 | 5,184 | **never** |
| Bridge | 3 | 3,648 | 2,589 | **already conditional today** |

Totals: **34,065 bytes** of OpenAI `tools` array (compact JSON), 34,248 bytes of Gemini function
declarations, 37,709 bytes with the bridge (VERIFIED, measured on this tree 2026-09-16 by the
script committed as `tests/unit/test_tool_payload.py`).

**Package query** (`query.py`, `rms_query.py`): `get_package_summary`, `list_components`,
`get_component`, `find_components`, `list_mates`, `list_holes`, `list_fasteners`,
`list_interferences`, `get_drawing_sheet`, `find_dimensions`, `list_gaps`, `get_exceptions`,
**`list_features`**, **`get_feature`**, **`list_equations`**.

**Measurement** (`measure.py`): `measure_axis_distance`, `measure_face_gap`, `check_tool_envelope`,
`bounding_box`.

**Check** (`checks_fit.py`, `checks_fastener.py`, `checks_interference.py`, `rms_checks.py`):
`check_fit`, `check_axial_stack`, `check_fastener_joint`, `check_hole_alignment`,
`check_interference_group`, **`check_rms_part`**, **`check_rms_assembly`**,
**`check_rms_equations`**.

**Session** (`session.py`): `request_evidence`, `mark_coverage`, `record_drawing_finding`,
`get_review_checklist`, `request_capture`.

**Bridge** (`bridge.py`, only with `--bridge`): `bridge_capture`, `bridge_measure`,
`bridge_interference`.

The **check group alone is 42 percent of the payload** and is also the most trimmable, so levers 2
and 4 point at the same eight tools. The **session group barely trims** (10 percent): it is
`CoverageScope` and `SourceRef` structure, and it can **never** be withheld, because
`mark_coverage` is how coverage stays honest and `get_review_checklist` is how the model knows what
is still open.

## 3. The tiers, and the one that is dropped

**Scope: package-decidable tiers only.** A tier rule must be decidable from the package before the
first turn, and must not change for the life of the session.

### Tier R: the RMS tier

**Rule**: withhold when `package.features` is empty (`ir/models.py:662`) **or** when
`extractor.profile` (`:619`) says the feature tree was never dumped. This is exactly the condition
`POST /checks/rms` already refuses with `EmptyFeatureTree`, so the rule is already written down and
is **reused, not restated**.

**Withheld**: `check_rms_part`, `check_rms_assembly`, `check_rms_equations`, `list_features`,
`get_feature`, `list_equations`. **8,093 bytes, 23.8 percent of the payload** (VERIFIED: 8,087
bytes of tool objects, 8,093 with the six array separators the objects take with them; the payload
delta is the 8,093 figure and it is the one the ledger row and `test_tool_tiers.py` state).

**Checklist item**: `modeling.resilience`.

### Tier B: the bridge tier

**Rule**: `context.bridge is None`. **Already implemented** and unchanged by this feature. A
package reviewed from exported files cannot see the three bridge tools at all, which is what
`bridge_tools()`'s own docstring says. Lever 4 adds nothing here; it is listed so the tier table is
complete and so nobody re-implements it.

### Dropped: "check tools once evidence exists"

**Not in lever 4 and not deferred to a later increment: dropped** (brief Q3). It is a claim about
the conversation, not the package. Four reasons:

1. **It invalidates the OpenAI prefix mid-session.** A tool array that changes between turn 1 and
   turn 2 is a `tools_changed` cache miss for the rest of the session (VERIFIED, the miss `reason`
   enum at `openai/types/responses/response.py:202-213`).
2. It makes two turns structurally different in a way the step log does not record.
3. It conflicts with how a review actually runs: `start()` (`runner.py:443-460`) plays **one**
   opening turn that does the whole review, and **there is no turn 2 unless the engineer types
   something**.
4. The waste it bets against, the model flailing early, is attacked far better by lever 5.

### Also considered and rejected for this lever: narrowing without removing

OpenAI has `tool_choice: {"type": "allowed_tools", ...}` (VERIFIED,
`openai/types/responses/tool_choice_allowed.py`) and Gemini has
`FunctionCallingConfig(mode=ANY, allowed_function_names=[...])` (VERIFIED,
`google/genai/types.py:6224-6237, 6258-6273`). Both narrow what the model may call **without
removing the schemas from the request**: perfect for the prompt cache, **zero tokens saved**. That
is the right mechanism for a future "focus the model" lever and the wrong one for lever 4, whose
whole purpose is bytes. Named here so the choice is deliberate rather than an oversight.

## 4. Why today's behaviour is wrong for a withheld tool

VERIFIED by reading. A call to an unregistered name goes to `ToolDispatch.call`
(`registry.py:450-478`), which returns

```json
{"error": "no tool named 'check_rms_part'; the tools available are ['bounding_box', ...]"}
```

and records it through `SessionSink.record` (`:226-253`), which writes a **`failed`** coverage
item whose reason is "tool `check_rms_part` failed; whatever it was called for is not covered".

Three things are wrong with that as the answer for a tool **we** declined to offer:

1. **`failed` says the tool broke.** It did not. We chose not to offer it. An engineer reading the
   report cannot tell those apart, and they call for opposite actions.
2. **`failed` never closes a checklist item.** `COVERAGE_BUCKETS` is
   `("checked", "skipped", "unresolved", "out_of_scope")` and `failed` is **deliberately absent**
   (VERIFIED, `agent/checklist.py:21-27`, whose comment says so). So `modeling.resilience` ends
   `open`, finalization turns it into a second, vaguer `unresolved` item with the generic reason
   "the review ended without a finding or a coverage entry for it", **and the engineer never learns
   we withheld the tool** (RK-5).
3. **The error message hands the model a 32-name list in a tool result**, which is the opposite of
   what a lever whose purpose is bytes should do.

## 5. The design: a withheld tool is registered, not absent

```python
@dataclass(frozen=True)
class WithheldTool:
    """A tool this run did not expose. Not on the wire; still in the dispatch, so a model
    that asks for it is told why, and the report says the same thing."""

    name: str
    reason: str                 # "this package carries no feature rows, so RMS tools were not offered"
    checklist_item: str | None  # "modeling.resilience"
```

**It is not in `__iter__`**, which is the entire point: no schema reaches the wire, and that is
where the bytes are saved. **`ToolDispatch.by_name` resolves it**, and its `call`:

1. returns an error result whose message is `reason`, and **not** the list of available tools;
2. writes an **`unresolved`** coverage item through the existing `ToolContext.record_coverage`
   (`tools/context.py:165-171`) with `check = checklist_item or f"tool.{name}"` and
   `reason = <the tier rule sentence>`, so it lands in the bucket `Checklist.bucket_of` searches
   and closes the item **as unresolved with a sentence an engineer can read**;
3. still produces the `tool.started` and `tool.finished` pair and the `InvestigationStep`, so the
   pane and the step log show the attempt.

That is the difference between "not covered" and "not covered because".

`ToolDispatch.tools` then holds two kinds of entry: **`__iter__` filters, `by_name` does not.** A
small explicit split inside one dataclass, not a new layer.

**A hallucinated name is unchanged.** A name that is neither registered nor withheld still gets the
existing error and the existing `failed` coverage item. That path is load-bearing (a hallucinated
name is routine, not exceptional, as `ToolDispatch`'s own docstring says) and a regression test
guards it.

### The coverage item a withheld RMS tier writes

```json
{"bucket": "unresolved",
 "item": {"check": "modeling.resilience",
          "scope": {"...": "..."},
          "reason": "RMS tools were not offered for this review: the package carries no feature rows (extractor profile 'full', features[] empty), so no part, assembly or equation rule could be graded. Re-dump with --features tree to grade them.",
          "error": null}}
```

**The reason names the rule, the evidence for it and what to do about it.** It is the same sentence
the report renders and the same sentence the model was given, because there is **one writer**.

### One reason, one writer, shared with lever 5

When lever 5 (`prerun_checks`) is also on and the RMS tier is withheld, lever 5 has nothing to
pre-run for RMS either (levers.md section 3, pair "4 and 5"). **One function decides "this package
cannot be graded for RMS, and here is the sentence saying why"**, and both the withheld tool's
coverage item and the pre-run digest's "NOT evaluated, and why" line come from it. Two renderings,
one source. Duplicating the sentence is the DRY violation this contract exists to prevent.

## 6. Per-turn subsets only, never per-round

Both adapters build their tool encoding **once per turn before the loop** (VERIFIED,
`openai_provider.py:235`, `gemini_provider.py:310`), so a per-turn subset needs **no adapter change
at all**: the wrapper's `__iter__` yields fewer tools and everything downstream is unchanged.

A per-round subset would need both adapters to rebuild their encoding each round, and on Gemini to
rebuild `GenerateContentConfig` per round, for a small marginal saving plus a new axis of
non-determinism in the step log. Lever 7 does force exactly one per-round rebuild (for
`tool_choice`), and that is the seam a per-round lever 4 would have reused; it is built once, if
ever, and not by this lever.

## 7. Tests

1. **Tier selection with no provider**: the exact tool names for a `model_check` fixture and for a
   full fixture, flag off and flag on. Deterministic, exact, no API call.
2. **The withheld path, with `FakeProvider`**: script a `check_rms_part` call against a package
   with no feature rows, and assert all five:
   - the tool was **absent** from the iterated `ToolSet`;
   - the call still produced a `tool.started` and `tool.finished` pair and one
     `InvestigationStep`;
   - the result message names the tier rule and **does not** contain the list of available tools;
   - `session.coverage.unresolved` holds an item whose `check` is `modeling.resilience` with a
     reason naming the missing feature rows;
   - **`session.coverage.failed` is empty.** This last assertion is the one that fails today.
3. **The checklist consequence**: `Checklist.bucket_of(modeling.resilience, session)` is
   `unresolved`, not `open`, so finalization does **not** add a second, vaguer item.
4. **Regression guard**: a hallucinated tool name still goes to `failed` with the existing message.
5. **Byte assertion**: the encoded array for a `model_check` package is smaller than for a full
   package by the measured RMS-tier figure, and the per-tool ceiling still holds.
6. **No mid-session change**: two turns of one session encode a byte-identical tool array with the
   flag on, which is what makes the OpenAI cache-diagnostic assertion in section 8 possible.
7. **Session tools are never withheld**, asserted directly over every tier rule.

## 8. Measurement and the adoption rule

**The headline is an asymmetry and it must be stated rather than averaged away: 24 percent off a
`model_check` package, 0 percent off a full assembly package.** Lever 4 does nothing for the main
case and a lot for the Model check tab's case. A single averaged number across package classes
would hide both facts.

**Primary metric**: tool count and encoded bytes per package class (full, `model_check`,
part-only), off and on. Deterministic, exact, runs in CI, needs no key.

**Quality metric**: the unresolved count read as **two numbers**, `unresolved_because_withheld` and
`unresolved_other`. A lever that raises the first and leaves the second flat is behaving as
designed.

**Adoption rule** (on top of the general gate in levers.md section 7):

1. `unresolved_other` must not rise.
2. The OpenAI cache diagnostics must show **no mid-session `tools_changed`**, which the
   package-decidable scope guarantees by construction and test 6 asserts.
3. The row states the per-package-class numbers separately.

**Priced before it is written**: probe L3 removes one tool between two otherwise identical requests
with `prompt_cache_options.comparison_response_id` set, and records
`cache_miss / tools_changed / cache_missed_tokens`. That number says what a tool-list change costs
in cache terms **before any of lever 4 exists**.
