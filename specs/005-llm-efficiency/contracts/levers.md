# Contract: the lever flags

Every efficiency lever this feature designs, with its flag, its default, its scope, what reads it
and when, how it is measured, and the rule under which it may be adopted.

**Every flag defaults to `False`. Nothing in this contract proposes turning anything on.** A
lever is adopted only on a recorded ledger row with no quality regression, and the decision is the
owner's. A lever that fails its gate stays off and keeps its row.

## 1. The flag carrier

One frozen model in `agent/settings.py`, beside `ProviderSettings` (`settings.py:176-192`), which
is already the single place per-provider defaults live.

```python
class EfficiencySettings(BaseModel):
    """Which efficiency levers this run has on. Every field defaults to off."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    trim_tool_descriptions: bool = False   # lever 2
    tool_tiers: bool = False               # lever 4
    prompt_cache_key: bool = False         # lever 3, OpenAI
    gemini_explicit_cache: bool = False    # lever 3, Gemini; gated on probe G4
    prerun_checks: bool = False            # lever 5
    parallel_tool_calls: bool = False      # lever 6
    coverage_stop: bool = False            # lever 7
    package_reuse: bool = False            # lever 9
    lazy_meshes: bool = False              # lever 10a
    carry_over_rms: bool = False           # lever 11a
    procedural_gate: bool = False          # lever 11
    compact_queries: bool = False          # experimental bounded discovery pages
```

**Threading**: one keyword argument through `start_review` (`agent/runner.py:595-651`), held on
`ReviewRun` (`:394-424`) exactly as `effort` and `max_steps` already are; one argument through
`run_benchmark` (`benchmark/runner.py:69-76`) and one through `cli._review_fn`
(`cli.py:1341-1364`). The alternative, one plumbed parameter per lever, is twelve signature
changes across three call sites and twelve separate contract edits (brief Q1).

**Recording**: `ReviewSession.efficiency: EfficiencySettings | None = None`, modelled on
`provider_info`, which is optional for the same reason: a session written before the field existed
has none. **Without it no ledger row can be attributed to a configuration and the A/B table cannot
be rebuilt from the run folder.**

**CLI**: `--lever <name>` on `swreview benchmark run` and `swreview review`, repeatable, an unknown
name raising rather than being ignored. **No lever flag reaches the pane's `settings.schema.json`
while it is being measured**: an engineer toggling an experiment flag mid-pilot makes the pilot's
own numbers unreadable, and an adopted lever becomes a default in code, not a checkbox.

**When each flag is read** matters and is stated per lever below. Two rules hold for all of them:

- **Read once at `start_review`, never per round.** A flag read mid-session changes the request
  shape mid-session, which on OpenAI invalidates the prompt prefix from that point.
- **Never read inside `spec_for`.** `_SPECS` is a process-global cache keyed by function
  (VERIFIED, `tools/registry.py:256-261`), so a flag read there means two runs in one process (the
  benchmark runner, the test suite) silently share the first run's setting. A flag that changes a
  tool spec is applied **after** `spec_for`, in the `RecordedTool` wrapper or in
  `ToolRegistry.dispatch` (`:491-525`), where the run's settings are already in scope.

## 2. Flag summary

| Lever | Flag | Default | Scope | Read at | Measured by |
|---|---|---|---|---|---|
| 2 | `trim_tool_descriptions` | `False` | Both providers; the tool schema and the system prompt | `start_review`, applied after `spec_for` | Bytes and tool count per encoding (exact, no API call), then the scorecard and a tool-name histogram |
| 3 | `prompt_cache_key` | `False` | **OpenAI only**; the request | `start_review` | `cached_input_share`, plus recorded miss reasons and `cache_missed_tokens` |
| 3 | `gemini_explicit_cache` | `False` | **Gemini only**; the cache lifecycle and the config shape | `start_review` | `cached_content_token_count`; **written at all only if probe G4 says implicit caching is not already delivering** |
| 4 | `tool_tiers` | `False` | Both providers; `ToolRegistry.functions_for` | `start_review`, fixed for the session | Tool count and bytes **per package class**, and unresolved split into two numbers |
| 5 | `prerun_checks` | `False` | Provider-neutral; `start_review` before the first turn | `start_review` | Round trips, input tokens, seconds to first finding, plus the `check_fit` and `check_axial_stack` call counts |
| 6 | `parallel_tool_calls` | `False` | **OpenAI only** as an A/B; Gemini is already on and has no off switch | Adapter construction in `cli.provider_factory` | Round trips primary; step count must be read beside it |
| 7 | `coverage_stop` | `False` | Both providers; a `ToolSet` wrapper plus a per-round `tool_choice` | `start_review` | Tokens, steps, the coverage bucket mix, and **how often the stop fired** |
| 9 | `package_reuse` | `False` | Extraction, not the review; needs `swreview-extract dump --reuse` | Dump time | **Invisible to `swreview benchmark run`**; a workstation harness comparing dump wall clock, gated first on byte-identity |
| 10a | `lazy_meshes` | `False` | Extraction plus a bridge fetch during review | Dump time and `start_review` | Dump wall clock, bridge `elapsed_ms` per `tessellate`, review wall clock; gated on identical `bodies_swept` |
| 11a | `carry_over_rms` | `False` | Provider-neutral; the second and later reviews of one design | `start_review` | Tokens and tool calls on the second review; gated on every finding touching an edited part being re-run |
| 11 | `procedural_gate` | `False` | Provider-neutral; the pre-run and the first user message (feature 007, `contracts/gate.md`) | `start_review`; implies lever 5, and never shares an arm with lever 5 or lever 7 | Tokens, round trips and seconds to first finding; **gated on the per-run `check_fit` and `check_axial_stack` call counts not falling** |
| 12 | `compact_queries` | `False` | Provider-neutral; optional bounded package discovery tool surface | `ToolRegistry` build/dispatch when explicitly enabled | Compact discovery page size and follow-up detail retrieval; gated on complete pagination and unchanged default tool schemas |

## 3. The interaction matrix

**Levers are not independent in effect.** These couplings cause trouble if the levers are
implemented separately and then combined without thought. "Other levers on" is a required ledger
column because of this table.

| Pair | Interaction | What the design does about it |
|---|---|---|
| 2 and 3 | Lever 2 moves about 10 KB from the tool array into the system prompt. Both are in OpenAI's cacheable prefix, so lever 2's saving is partly already captured by lever 3 on the second and later requests | **Measure lever 2 with lever 3 off**, and record which other levers were on. `EfficiencySettings` on the session is what makes this auditable |
| 4 and 3 | A tool array that changes mid-session invalidates the OpenAI prefix from that point | **Package-decidable tiers only, fixed for the whole session** (see `tool-tiers.md`). Removes the interaction by construction, and the cache diagnostics assert it |
| 5 and 7 | Lever 5 closes checklist items before the first turn; with 7 also on, a package whose deterministic checks close every item stops the turn almost immediately, before the model looks at fit, stack or drawings | **Never run 5 and 7 in the same arm until each is gated alone.** When combined, the strict stop predicate is not optional; it is what stops a pre-run from ending the review |
| 5 and 2 | Lever 5 makes the RMS descriptions less load-bearing, and those are lever 2's biggest trims | If both are wanted, gate 5 first, then re-measure 2's quality risk against the post-5 baseline |
| 6 and 5 | Lever 5 removes the round trips lever 6 would have saved. Measured together, 6 looks worthless | **Measure 6 first, against the lever-5-off baseline**, and record it |
| 6 and 7 | With batching on, the round that closes the last checklist item may also contain three more calls; the stop withdraws tools for the **next** round, so those three still run | Correct and intended. Stated here so the measured saving is not read as a bug |
| 4 and 5 | If a tier withholds RMS tools because the package has no feature rows, lever 5 has nothing to pre-run for RMS either, and both write coverage saying so | **One function decides "this package cannot be graded for RMS, and here is the sentence saying why."** One reason, one writer |
| 9 and 3 | A Gemini explicit cache cannot be keyed to a package today because `PackageId = Guid.NewGuid()` on every dump (VERIFIED, `Dump/PackageWriter.cs:136`). If lever 9 introduces a content key, lever 3 gets cross-session cache reuse for free | Cross-referenced, not a reason to do 9 early |

## 4. Tier 1

### Lever 2: trim tool descriptions

**Flag**: `trim_tool_descriptions`. **Default**: off. **Scope**: both providers; the tool schema
and the system prompt. **Read**: once at `start_review`, applied **after** `spec_for`.

**The honest ceiling, measured on this tree (VERIFIED).** Of 35,844 bytes sent today, **16,042
(45 percent) is JSON structure** and lever 2 cannot reach it; only lever 4 or a schema change can.
19,802 bytes (55 percent) is prose. (Regenerated 2026-09-23 when feature 010 added
`check_joints` and reworded two docstrings, and again when feature 009 gave `request_evidence` its
three optional arguments, and again when feature 010 registered `check_mass_material` and
`check_hygiene`; the four cap rows below were measured on the 32-tool array of 2026-09-16.)

| Cap (tool / parameter description) | Bytes | Saved |
|---|---|---|
| none (today) | 35,844 | 0 |
| 300 / 120 | 27,158 | 20 percent |
| 200 / 100 | 25,020 | 27 percent |
| **160 / 90** | **23,834** | **30 percent** |
| 120 / 70 | 22,450 | 34 percent |
| everything stripped (floor) | 16,042 | 55 percent |

So about 30 percent of the tool payload, roughly 2,550 tokens per request, roughly 153,000 tokens
over a 60-call review. This is **below** the source document's "a third to a half" at the upper
end and the document is corrected. Note also that the three largest tool *objects* are not the
three longest *descriptions*: `record_drawing_finding` is 2,156 bytes carrying 268 characters of
description and `mark_coverage` is 1,576 carrying 244. Those are structure and no trimming touches
them.

**Design: split the docstring, do not copy it.** VERIFIED: there is exactly one path from
docstring to schema. `tool_spec(fn)` (`agent/providers/schema.py:402`) reads the docstring,
`parse_docstring` (`:99`) splits body from `Args:` entries, `canonical_schema` (`:150`) refuses a
parameter with no `Args:` entry, and both adapters read `tool.description` directly. **The
docstring is the schema and there is no second place a description is written.** That is the asset
this lever must not destroy.

`parse_docstring` already recognises Google-style section headers and already collects `Notes:`
into a `sections` dict and then throws it away. So:

- The tool description becomes the **first paragraph**. Everything from the second paragraph moves
  under a `Notes:` header **in the same docstring**.
- `parse_docstring` returns the `Notes:` text as a third value instead of discarding it.
- `ToolSpec` (`schema.py:389-397`) gains a `notes: str` field beside `description`.
- `build_system_prompt` (`runner.py:118-128`) gains a `## Tool notes` block rendered from the same
  `ToolSpec` objects the adapter is about to be handed.

Two properties make this right rather than clever. **Nothing is written twice**: the text still
lives in exactly one docstring, so a note that goes stale goes stale in one place. That is the
difference from "shorten the docstrings and paste the removed text into `system_v1.md`", which
would create the duplication this codebase has so far avoided. And **the system prompt is the
cacheable half**: moving 10 KB out of the tool array (which lever 4 wants to vary) into the system
prompt (which never varies) is the right direction for lever 3 as well.

The long descriptions are not padding. They are three kinds of text mixed together: **what the
tool is** (stays on the tool; it is what the model reads to choose among 32), **policy already in
the system prompt** (`check_fastener_joint`'s "drill depth is not thread depth" is in
`system_v1.md` under "Things you must not do"), and **call-protocol warnings that fire once per
session** (`check_rms_part` carries 1,296 characters for a tool with one optional parameter). Only
the second and third kinds move.

**Cap by construction, not by truncation.** A run-time cap that truncates mid-sentence produces
"...and never used as o" and the model reads the fragment as complete. Instead, **each docstring is
split at an existing paragraph boundary chosen so the first paragraph is already under the cap,
with no rewording**, and a unit test fails the build when a first paragraph is over **160
characters** or an `Args:` entry is over **90** - the caps the 23,834-byte / 30 percent row above
is measured at, so the ledger row and the commit message state a number the build enforces. Where a
docstring cannot be split under the cap without rewording, **that docstring is a named lever 2
exception recorded in the ledger row**, not a silent rewrite. The measured "on" arm is then a set of
descriptions a human wrote rather than a machine's amputation of them (brief Q2).

**The off arm is recoverable by flipping the flag, and that is a requirement, not a convenience.**
With `trim_tool_descriptions` **off**, the adapter and the MCP toolset are handed the **rejoined**
string - `description + "\n\n" + the dedented notes` - which FR-039 pins **byte-equal** to the
pre-split docstring body, and `build_system_prompt` renders no `## Tool notes` block. With it
**on**, they are handed the first paragraph only and the prompt carries the notes. So the
post-split commit with every flag off reproduces the pre-split wire bytes exactly, which is what
SC-007 asserts and what stops the split from being an unmeasured change shipped as the default.
**Both arms therefore run from one commit** and `compare` grants lever 2 no exception to its
same-commit refusal (ab-harness.md sections 1, 2, 3). Splitting at a paragraph boundary with no
rewording is what makes the rejoin byte-exact rather than "modulo whitespace"; a whitespace-only
tolerance is exactly the crack the two-commit exception would crawl back through.

**The Ask tab path is honoured too, or the claim is dropped.** `mcp/server.py:257,346` builds its
tool list from `spec_for`/`spec.description` and has **no system prompt** to render notes into
(`instructions` at `:496-499` is a fixed literal). The flag must be honoured there: with it off the
MCP toolset gets the rejoined string, which is the pre-split behaviour. What the **on** arm does
there is a stated choice and not an accident - either the notes render into the server
`instructions`, or the Ask tab always receives the rejoined description and is recorded as a
**non-A/B'd path**, in which case section 8's claim that lever 2 shrinks the Ask tab's payload is
withdrawn rather than assumed. See the UNVERIFIED note in section 8.

**Touch points**: `agent/providers/schema.py` (`parse_docstring`, `ToolSpec`, `tool_spec`),
`agent/runner.py` (`build_system_prompt`), `tools/registry.py` (the wrapper), 35 docstrings across
`tools/`.

**Tests**: the byte budget test, which also asserts the **160-character first-paragraph cap and
the 90-character parameter-description cap over all 35 docstrings**, so the 23,834-byte figure is
reproducible rather than aspirational; a **no-loss test** asserting the rejoin
`description + "\n\n" + dedented notes` is **byte-equal** to the old full description, **with the
old text pinned in the test file** so it is a diff against a known state rather than a tautology;
a prompt test (flag on contains every tool's notes exactly once, flag off contains none); a
`FakeProvider` test asserting two `session.json` files are identical except for the recorded
settings; adapter tests asserting the params carry the trimmed description with the flag on and
**the rejoined description with it off**; an MCP test asserting the same for `MCP_TOOL_FUNCTIONS`;
and the **SC-007 wire assertion**: the encoded tool array, in both provider encodings, built at the
post-split commit with **every flag off**, is byte-equal to the pinned pre-split encoding. That
pinned encoding is the artifact the static-baseline test of FR-015 and FR-016 already produces, so
this is one committed file rather than new machinery.

**Measurement**: bytes and tool count per provider encoding, off and on, which is deterministic,
exact, needs no API call and runs in CI; then the benchmark scorecard for quality.
**Lever-specific counter: a histogram of tool names from `session.steps` per run.** The token
count is arithmetic; the thing that actually needs watching is which tool the model picks. A trim
that changed the answer usually shows first as a call-pattern change ("the model stopped calling
`check_rms_part` with no argument and started calling it per document"), which the scorecard would
not catch (RK-4). UNVERIFIED whether this shows up at all.

**Adoption rule**: the general gate (section 7), **plus the tool-name histogram must not show a
check tool dropping out of the model's repertoire.**

### Lever 3: prompt caching

**Flags**: `prompt_cache_key` (OpenAI), `gemini_explicit_cache` (Gemini). **Default**: both off.
**Read**: once at `start_review`.

**The reframing**: our OpenAI prefix is **already stable**, so we are probably already getting
substantial implicit cache hits that we simply cannot see. Three facts, all VERIFIED by reading:

1. `system` is built once in `start_review` and never mutated; its three parts
   (`prompts/system_v1.md`, `checklist.render()`, `json.dumps(package_summary(package))`) are all
   deterministic.
2. `tool_params` is byte-identical every turn and across processes. `strictify`
   (`schema.py:216-259`) and `gemini_adapt` (`:353-382`) use no set iteration, and the sha256 was
   identical under `PYTHONHASHSEED` 0, 1 and 12345.
3. History is append-only. `_run_turn` does `self.messages = [dict(m) for m in result.messages]`,
   `_encode_assistant` deep-copies and replays raw output items verbatim, and `answer_evidence`
   mutates `session.findings` and never `self.messages`.

Every round trip inside a turn extends an append-only prefix, so rounds 2..n of a 7-request turn
should hit on everything rounds 1..n-1 sent. **So lever 3 on OpenAI is not "add caching"; it is
"name the cache, record the diagnostics, and stop the other levers from breaking what we already
have".**

**The cache key must survive a process restart**, because the pane restarts the backend on a
settings save and resumes the same run folder. Use `prompt_cache_key = str(session.session_id)`,
which is already persisted in `session.json`. A process-local random value would look identical
and silently drop every hit after a restart, which would show up as `prompt_cache_key_changed`,
which is precisely why the diagnostics are worth recording. The diagnostics shape is normative in
[usage.md](usage.md) section 7.

**What would break our prefix**, ranked by how likely we are to do it to ourselves: lever 4
changing the tool list mid-session (`tools_changed`, designed out by the package-decidable scope);
lever 2 toggled mid-session (safe because the flag is read once at `start_review`); **anything
per-turn put into `system`** (a coverage digest, open checklist items, a timestamp), which
invalidates the prefix for the whole session and is the reason lever 5's digest goes in the first
user message; effort changed mid-session (`reasoning_effort_changed`; the pane refuses a settings
save during a turn but not between turns); lever 8's two models meaning two prefixes.
`parallel_tool_calls` is a request field, not prompt content, and does not appear in the miss
enum, so flipping it should not break the prefix (**UNVERIFIED, probe L5**). The 1024-token
minimum cacheable prefix is **not stated anywhere in the installed package** (UNVERIFIED); our
prefix is far above any plausible threshold, so it is an unstated number rather than a risk.

**Gemini explicit caching, as installed** (all VERIFIED): `client.caches.create(model, config)`
returning `types.CachedContent` (`caches.py:1144-1166`); `CreateCachedContentConfig`
(`types.py:16434-16484`) carries `contents`, `system_instruction`, **`tools`**, `tool_config`,
`display_name`, `ttl`, `expire_time`; `ttl` is a duration string ending in `s`; the returned
`CachedContent.usage_metadata.total_token_count` is the denominator for "what fraction of the
prefix did we actually cache"; it is referenced with `types.GenerateContentConfig(cached_content=<name>)`
(`types.py:6612-6617`), a plain `str` on the same config `_config()` already builds; the lifecycle
is `caches.get`, `caches.update`, `caches.delete`, `caches.list`. **`tools` being cacheable is the
whole point**: 34,248 bytes of function declarations is the bulk of what we resend.

**The trap, and the highest-risk change in this lever**: when `cached_content` is set, the fields
that were cached must **not** also be sent on the request, and the SDK enforces nothing (VERIFIED
by grep: no validation anywhere in `google/genai/`), so the failure is a 400 at run time, not a
type error. Our `_config()` always sets `system_instruction`, `tools`,
`automatic_function_calling`, `thinking_config` and `max_output_tokens`, so a cached run needs a
second config shape:

```
cached:   system_instruction=None, tools=None, cached_content=cache.name
uncached: system_instruction=system, tools=[Tool(function_declarations=...)]
both:     automatic_function_calling, thinking_config, max_output_tokens
```

`AUTOMATIC_FUNCTION_CALLING_DISABLED` stays on the cached path for the reason the module docstring
gives: our loop runs every tool call, so the SDK must not. **A wrong branch does not degrade, it
400s the whole review** (RK-18), which argues for the flag being read once at `start_review` and
for **one function with a single `cache_name: str | None` argument building both shapes**, tested
both ways, rather than an `if` sprinkled through `_config`.

**TTL**: bound it (1800s) and delete on `ReviewRun.close()`. A crashed process leaks one entry
until the TTL expires, which makes the leak cheap and self-healing. A long TTL plus a missing
delete is a standing bill nobody sees.

**Gemini explicit caching may be pointless, and one measurement decides.** Gemini reports implicit
cache hits through the same `cached_content_token_count` field. If a plain instrumented run
already shows a healthy value, the entire explicit lifecycle (create, branch the config, extend,
delete, handle a leaked cache, handle the 400) buys little and costs real complexity. **Probe G4
gates whether any Gemini explicit-caching code is written at all**, and it is available the day
the instrumentation ships.

**Touch points**: `openai_provider.py` `_respond` (add `prompt_cache_key`, optionally
`prompt_cache_options`, read `prompt_cache_diagnostics` onto the `usage` event body);
`gemini_provider.py` `_config` (the two-shape function) plus a cache lifecycle owned by
`ReviewRun`.

**Tests**: a **prefix-stability regression test** that fails if `system` or the tool list changes
within a session (this is the real deliverable for OpenAI); the two-shape config function tested
both ways with no network; a cached-run test asserting `system_instruction` and `tools` are absent
from the request when `cached_content` is set; a cache-delete-on-close test; a test that a crashed
close still leaves a bounded TTL.

**Measurement**: `cached_input_share` per run. **Lever-specific counter: the recorded miss reasons
and `cache_missed_tokens`.**

**Adoption rule**: the general gate (section 7), **with no exception**. If neither the median
total-token nor the median wall-clock reduction reaches 20 percent, the row computes `keep off`
like any other. The observability case - the prefix is hitting, the key survives a restart, and we
can now see both - is carried in `decision_reason` beside the computed value and signed in
`owner_signed_off`; it is **not** a second path to `adopt`, because probe L2's answer lives in the
hand-written `probe-log.md` and FR-024 and SC-009 forbid a decision resting on a metric that is not
in the scorecards. The prefix-stability test is this half's deliverable either way (FR-042). Gemini
explicit caching is **written only if** G4 shows implicit caching is not already delivering, and
then gated normally.

**Probes**: L2 (our prefix actually hits: two identical requests in one process, same key, full
tool list, real system prompt; assert the second has `cached_tokens > 0`). L3 (a tool-list change
is a `tools_changed` miss and what it costs: a third request with one tool removed and
`comparison_response_id` set; **this prices lever 4 before lever 4 is written**). L5. G1
(`caches.create` accepts our system prompt plus 32 tool declarations and we are over the unstated
minimum). G2 (setting `cached_content` alongside `system_instruction` or `tools` is rejected, and
what the rejection says; confirms the two-shape config is mandatory rather than tidy). G4. G5 (the
explicit cache is used when referenced).

### Lever 4: tiered tool exposure

**Flag**: `tool_tiers`. **Default**: off. **Scope**: both providers; `ToolRegistry.functions_for`.
**Read**: once at `start_review`, **fixed for the whole session**.

Fully specified in [tool-tiers.md](tool-tiers.md), including the tool-by-tool tables, the
`WithheldTool` design, the coverage it writes and every test assertion. Summary here for the flag
table's sake:

- Scope is **package-decidable tiers only**. The RMS tier is withheld when `package.features` is
  empty or `extractor.profile` says the feature tree was never dumped, which is exactly the
  condition `POST /checks/rms` already refuses with `EmptyFeatureTree`. The bridge tier is
  **already implemented** (`functions_for` adds bridge tools only when `context.bridge is not
  None`, VERIFIED `registry.py:485-489`), and the 32-tool number is the no-bridge number.
- The dynamic "check tools once evidence exists" tier is **dropped entirely** (brief Q3): it is a
  claim about the conversation, not the package; it invalidates the OpenAI prefix mid-session; and
  `start()` plays **one** opening turn that does the whole review, so there is no turn 2 unless the
  engineer types something.
- **Measurement is an asymmetry that must be stated rather than averaged away: 24 percent off a
  `model_check` package, 0 percent off a full assembly package.** Lever 4 does nothing for the main
  case and a lot for the Model check tab's case.
- **Lever-specific counter: unresolved split into two numbers**, unresolved-because-withheld and
  unresolved-for-any-other-reason. A lever that raises the first and leaves the second flat is
  behaving as designed.
- **Adoption rule**: the general gate, plus unresolved-for-any-other-reason must not rise, plus
  the OpenAI cache diagnostics must show **no mid-session `tools_changed`**, which the
  package-decidable scope guarantees by construction and the test asserts.

## 5. Tier 2

### Lever 5: pre-run deterministic checks

**Flag**: `prerun_checks`. **Default**: off. **Scope**: provider-neutral; runs in `start_review`
before the first turn. **Read**: once at `start_review`.

**Adopted as the pane default on 2026-09-22 (feature 008, "checks first").** By the owner's
decision, gated by the offline replay of the recorded runs rather than by the ledger
(`specs/008-checks-first-review/contracts/checks-first.md`). `ChatServer._start_review` passes
`pane_efficiency(provider)` - the one function that decides the pane's levers - and every pane
review records it on `session.efficiency`. `EfficiencySettings.prerun_checks` itself still
defaults off, and so do `swreview review` and `swreview benchmark run`; `--lever prerun_checks`
(or 008's `--pane-defaults`) turns it on there. As adopted, lever 5 now also includes: live
interference detection first when SOLIDWORKS is attached (every detected group judged, the rows
persisted into the run folder's `package.json`), the re-call guard that answers a repeated check
with `already_run` instead of duplicating findings, the standards family's line when no profile
is configured, and the fold marker (`session.folded_families = ["rms"]`) that ranks and renders
the modelling-practice findings as one group. `checks_first(efficiency)` is lever 5 **or** lever
11; lever 11 stays a command-line study variant; `GATED_ALONE` and every lever-count pin are
unchanged; no pane control exists (`test_no_lever_in_pane_settings.py` unedited).

**The scope is smaller than the source document states, and saying so is the point.** Which checks
can be enumerated without a model (VERIFIED):

| Check | Enumerable? | Why |
|---|---|---|
| RMS part rules | **Yes, already** | `run_part_checks(context, None)` grades every part document (`tools/rms_checks.py:103`) |
| RMS assembly rules | **Yes, already** | `run_assembly_checks(context)` takes no selection (`:157`) |
| RMS equations | **Yes, already** | same shape (`:186`) |
| Interference | **Yes** | `groups_of(package)` enumerates every group (`tools/checks_interference.py:32`); already drives `swreview check interference` (`cli.py:756-786`) |
| Fastener joint | **No enumerator exists** | needs `(fastener_id, hole_id, clamped_component_ids)`; the clamped stack is model-chosen |
| Hole alignment | **No enumerator exists** | needs a pair of holes and a drawing tolerance `SourceRef` for a verdict |
| Fit | **No, and probably never** | needs two drawing dimensions identified as bore and shaft |
| Axial stack | **No, and probably never** | needs an ordered list of dimensions with signs and a target gap |

**v1 ships the four that already enumerate themselves.** The fastener-joint enumerator is a later,
separately specified increment (brief Q4): it is a feature-sized piece of engineering judgement
encoded in code, a wrong pairing produces a **deterministic** wrong finding that looks
authoritative, and it deserves its own golden fixtures. Hole alignment is **not** pre-run even
though pairs are enumerable, because `check_hole_alignment` without a tolerance `SourceRef`
returns `unresolved` by design, so pre-running every pair manufactures a large number of
verdictless unresolved findings and degrades the report. The candidate pairs go into the digest
instead.

**Where it goes.** There is already a function in exactly the right place doing exactly this shape
of thing: `record_partial_evidence(session, package)` (`runner.py:157-183`) runs in `start_review`
before any turn and writes a `skipped` coverage item saying what the dump profile never extracted.
The pre-run is its sibling, called from the same place (`runner.py:684`), and **the digest is
prepended to `OPENING_MESSAGE` (`runner.py:88-93`), not to the system prompt**, because the system
prompt is the cacheable prefix and the digest is per package.

**The correctness point that makes this honest**: the pre-run calls the same tool functions
through the same `ToolDispatch`, **not a parallel copy of the check logic**. Every pre-run check
therefore produces a real `InvestigationStep`, real findings through `ToolContext.record_finding`,
real coverage and real `tool.started` and `tool.finished` events. The pane shows the pre-run
happening; the report is structurally indistinguishable from a model-driven run;
`Finding.tool_result_ids` still points at a real step. A pre-run that bypassed the dispatch would
have to synthesize all of that and the report would start lying about provenance.

**The digest** is counts per check with the non-passing ones named, plus a **"NOT evaluated, and
why"** block. That block carries the risk the source document names (the model treats the digest
as complete and stops exploring, RK-6), and it must be **generated from the same coverage
machinery, not written as prose**: each not-evaluated line corresponds to a `skipped` coverage
item written at the same moment, so the report says the same thing the model was told. One source,
two renderings.

```
Deterministic checks were run before this turn. Their findings are already in the session.

  modeling.resilience  34 rules over 7 part documents: 5 fail, 2 unresolved, 27 pass
      fail: rms.core.order (prt:3, prt:5), rms.detail.naming (prt:1)
  interference         3 conditions: 1 demonstrated, 1 excepted, 1 unresolved

NOT evaluated, and why:
  fastener joints   12 screws found; no joint evaluated. The clamped stack for each joint is
                    not derivable from the package, so you must name it.
  hole alignment    8 coaxial hole pairs found; none has a drawing tolerance in the package.
  fit, axial stack  not run: both need drawing dimensions you have to identify.
```

**Expected effect**: for a package with 3 interference groups, a minimal model-driven pass is 3
RMS calls plus 1 `list_interferences` plus 3 group checks, and with `parallel_tool_calls: False`
that is 7 round trips saved, on the order of 60,000 to 100,000 input tokens at 8,500 tokens of
schema plus a growing history per trip. **UNVERIFIED: the actual round-trip count today**, which
is why the instrumentation lands first.

**Touch points**: `agent/runner.py` (the sibling of `record_partial_evidence`, and the
`OPENING_MESSAGE` assembly), `tools/rms_checks.py` and `tools/checks_interference.py` (read, not
changed), the coverage path.

**Tests**: (1) **the pre-run produces the same session a model-driven run does**, compared on the
`_verdict_key` the runner already defines (`runner.py:324-345`) rather than on serialized lists,
which is the strongest possible statement that the pre-run is the same checks and not a second
implementation; (2) the digest names what was not evaluated, and the counts in the digest equal
the counts in the session, with a `skipped` coverage item for each; (3) a pre-run check that fails
does not stop the review (`--fail-tool` already exists, `registry.py:491-525`); (4) an empty
`model_check` package runs nothing, the digest says so, and `record_partial_evidence`'s existing
`skipped` item is **not duplicated**.

**Measurement**: round trips, input tokens, **seconds to first finding** (which should drop
dramatically and is the number an engineer feels), and the full scorecard.
**Lever-specific counter: the count of `check_fit` and `check_axial_stack` calls per run, off and
on.**

**Adoption rule**: the general gate, **plus a specific regression to watch**: those two checks are
never pre-run, so if their call counts fall, the digest is suppressing exploration and the lever
fails the gate regardless of what the token number says.

### Lever 6: parallel tool calls, meaning round-trip batching only

**Flag**: `parallel_tool_calls`. **Default**: off. **Scope**: **OpenAI only** as an A/B. **Read**:
adapter construction, in `cli.provider_factory`, where `max_output_tokens` already comes from. Not
a new argument on `AgentProvider.run`: that signature is the port contract and changing it touches
three adapters and every test that implements it.

**Adopted as the pane default for OpenAI on 2026-09-22 (feature 008, User Story 4).** By the
owner's decision, on the evidence of the one-design study under "Measurements outside the ledger"
(`docs/llm-efficiency-options.md`), superseding the held-out rule for this lever. `pane_efficiency
(provider)` sets `parallel_tool_calls = provider is OPENAI`; `chat.server.build_provider` passes it
to `cli.provider_factory` at construction and `ChatServer._start_review` records the same settings
on `session.efficiency`, so the session says what the adapter was built with. A Gemini or scripted
pane review records it off (Gemini has no switch and already makes parallel calls; the scripted
provider reads no request field). Local dispatch stays serial in response order, so SOLIDWORKS
calls still reach the one STA thread one at a time. `EfficiencySettings.parallel_tool_calls`
itself still defaults off, and so do `swreview review` and `swreview benchmark run`; `--lever
parallel_tool_calls` (or 008's `--pane-defaults` with `--provider openai`) turns it on there.
`GATED_ALONE` and every lever-count pin are unchanged; no pane control exists.

**The two adapters do not behave the same today, and the source document is wrong about one of
them.** OpenAI sends `"parallel_tool_calls": False` on every request (VERIFIED,
`openai_provider.py:308`). Gemini sends no such setting: `_config` (`gemini_provider.py:444-466`)
sets `system_instruction`, `tools`, `automatic_function_calling`, `thinking_config` and
`max_output_tokens` and nothing else, and its loop is already written for multiple calls
(`round_.calls` is a list, `requests` is a slice against the budget, results append as one `tool`
content, `:334-357`). **Gemini already makes parallel tool calls in production.** "One round trip
per query" is true of OpenAI only.

**The OpenAI change is one line.** The loop at `openai_provider.py:240-290` already handles
multiple `function_call` items in one response: `_tool_requests` (`:529`) collects **every**
`function_call` item, the caller iterates them, appends a `function_call_output` for each (`:283`),
and only then loops back. The budget check is per call and over-budget calls get the
`BUDGET_EXHAUSTED` output so the echoed history stays valid (`:279-285`). VERIFIED by reading;
**UNVERIFIED** that a real response comes back with several calls at a useful rate.

**Local execution stays serial, and that is a scope decision, not an omission.** Requesting several
calls in one round trip is the token and latency win and needs no threads. Running those calls on
several threads saves wall clock only if the calls are slow; ours are scans over in-memory
pydantic lists and geometry over already-loaded faces, the one exception being
`check_tool_envelope`, which loads meshes with `trimesh` (`tools/measure.py:218-313`). A thread
pool over five list comprehensions saves nothing and costs three real correctness hazards
(RK-9):

1. **`ToolContext.current_step_id` breaks.** It returns `len(session.steps)` (`context.py:127-140`)
   and its own docstring explains that a tool writing a finding is citing the step it is about to
   be recorded as. Under concurrency two tools read the same value and one cites the other's step.
   `Finding.tool_result_ids` is "the only evidence a check has when its verdict rests on what the
   model was shown". **Silent provenance corruption, not a crash.**
2. **`SequentialIdAllocator.__next__` is not atomic** (`ids.py:14-17`), so two findings can take
   the same `F-003`.
3. **The step log stops being deterministic**, and `tests/golden/` compares sessions.

All three are fixable and none is worth fixing for a thread pool over list scans. With execution
serial in request order, "keep bridge calls serial on the STA thread" is satisfied by construction
and the step log stays deterministic for free.

**Gemini is not A/B-able for this lever.** The flag is a no-op in the "on" direction and a **new
capability** in the "off" direction: there is no disable-parallel switch in `GenerateContentConfig`
(VERIFIED by absence), and dropping all but the first call of a round would throw away work the
model already did and measure something we would never ship. **Lever 6 is measured on OpenAI
only**, and the ledger row says "Gemini: on by default, not measurable as A/B". That is a true
statement and more useful than a fabricated comparison.

**Tests**: the request carries the flag (recorded client, off and on); several calls in one
response are all executed **in order** (three `tool.started` and `tool.finished` pairs, three
`function_call_output` items, three steps with indices 0, 1, 2); the budget still bounds the turn
(three calls with `max_steps=2`: two run, the third gets `BUDGET_EXHAUSTED`, the turn ends
`max_steps`, the runner writes closeout coverage); **`FakeProvider` grows a multi-call round**
(`ScriptedTurn.tool_calls` is already a tuple but the fake appends one assistant message per call,
`fake.py:112-128`, which models the serial shape; add an optional grouping so a script can say
"these three were one round"); determinism (two runs of the same script produce byte-identical
`events.jsonl` apart from timestamps).

**Measurement**: round trips primary; wall clock to session end and input tokens secondary.
**Lever-specific counter: step count read beside round trips.**

**Adoption rule**: the general gate, **plus watch for speculative batching**: a model asked to
batch may call checks it would otherwise have skipped after reading an earlier result. That shows
as **step count going up while round trips go down**, and it can raise false alarms. Both numbers
must be in the ledger row.

### Lever 7: coverage-driven stop

**Flag**: `coverage_stop`. **Default**: off. **Scope**: both providers. **Read**: once at
`start_review`.

**The state already exists**, computed in one place for finalization: open checklist items via
`context.checklist.open_items(review)` (`checklist.py:68-70`, called at `runner.py:246`) and open
evidence requests via `request.status != "open"` (`runner.py:231-245`). The predicate lives beside
`finalize_session` (`runner.py:200`) and is **used by** `finalize_session`, not copied;
finalization's whole job is to enumerate the same two sets.

**The hard part is that a turn cannot be ended from outside.** `_run_turn` (`runner.py:528-576`)
calls `provider.run(...)` once and that call does not return until the model stops or the budget
runs out. The only mid-turn seam is the `ToolSet`, which is exactly what `StoppableTools`
(`chat/server.py:355-379`) uses. Three mechanisms, not equivalent:

- **A. Raise out of `ToolSet.call`, the way Stop does.** `StoppableTools` raises `TurnStopped`, a
  `BaseException` chosen so the runner's `except Exception` does not turn it into an error
  (VERIFIED, `chat/server.py:344-352`). **The trap**: the triggering call gets no output, so on
  OpenAI the history holds a `function_call` with no matching `function_call_output`, and the
  module docstring says plainly that "every `function_call` in the echoed history needs a matching
  `function_call_output` or the next request is rejected" (VERIFIED,
  `openai_provider.py:96-99`). The session could then never be continued or have an evidence
  request answered, which is precisely what `continue_session` and `answer_evidence`
  (`runner.py:462-495`) exist to do. Stop gets away with it because Stop means the engineer
  abandoned the turn; coverage completion does not. **This is the mechanism an implementer would
  reach for by analogy, and it would quietly break `answer_evidence` on OpenAI** (RK-8).
- **B. Soft stop**: answer the call, then append "coverage is complete; write your closing summary
  now" to the result. History stays valid; the model may ignore it. A hint, not a stop.
- **C. Withdraw the tools for the next round**: `tool_choice: "none"` on OpenAI (VERIFIED,
  `openai/types/responses/tool_choice_options.py`, `Literal["none", "auto", "required"]`) or
  `FunctionCallingConfig(mode=NONE)` on Gemini (VERIFIED, `google/genai/types.py:482-483`, "Model
  will not predict any function calls"). The model physically cannot call another tool, writes its
  closing message, and the turn ends `end` through the existing path. Every call has its output;
  the history is valid and resumable.

**The design is C, with B's sentence as the accompanying tool-result text.** C is the only one of
the three that both actually stops the exploration and leaves a session that can be continued. It
costs one adapter change each: Gemini builds `config` once before the loop
(`gemini_provider.py:310`), so this is the one place lever 7 forces a per-round rebuild, and that
rebuild is the same seam a per-round variant of lever 4 would have needed. Build the seam once if
both are ever wanted.

**Two guards ship with the lever, not after it.** This lever converts `mark_coverage` from
bookkeeping into a **turn-ending** call, which changes the incentive: a model that wants to finish
can close the checklist with nine `mark_coverage(bucket="skipped")` calls and stop. Today that
produces a bad report; with lever 7 it also produces a short, cheap run that **looks efficient in
the results table** (RK-7).

1. **The stop predicate ignores `skipped` and `out_of_scope` as closers.** `bucket_of` searches
   `("checked", "skipped", "unresolved", "out_of_scope")` (VERIFIED, `checklist.py:21-27`). For
   *finalization* that is right: an item closed any way is closed. For *stopping early* it is not:
   a review that skipped six of nine items has not finished, it has given up. The predicate
   requires every item closed **by a finding or by `checked`**. **This makes the two functions
   deliberately different and needs a comment saying why, or someone will "DRY" them together later
   and reintroduce the hole.** It also makes the lever fire less often and save less, which is the
   correct trade (brief Q5).
2. **The scorecard must show the closing bucket mix.** `PackageScore`
   (`benchmark/scorecard.py:65-78`) carries `unresolved_count` but no per-bucket breakdown, and
   **lever 7 cannot be gated without it**, so the breakdown is part of this lever's work.

**Touch points**: `agent/runner.py` (the predicate beside `finalize_session`, used by it), a
`ToolSet` wrapper modelled on `StoppableTools`, `openai_provider.py` and `gemini_provider.py`
(per-round `tool_choice` and `ToolConfig`), `benchmark/scorecard.py` (the bucket mix).

**Tests**: the predicate unit-tested directly over hand-built sessions with no provider (all items
closed by findings; one item open; one evidence request open; an item closed only by `skipped`),
since that is where the edge cases live and where they are cheapest; the stop fires (the final
scripted call did not run, the turn ended `end`, no step for it); **resumption survives it** (after
the stop, `answer_evidence` or `continue_session` runs; this needs the recorded-client OpenAI test
because it is the assertion that distinguishes C from A and **the fake cannot see the
difference**); an open evidence request keeps the turn alive; flag off produces byte-identical
`events.jsonl`.

**Measurement**: tokens and steps per run, the coverage bucket mix, and **how often the stop
fired**. A lever that fires on one package in five is not the same lever as one that fires on five
in five, and the token average hides that. **Lever-specific counter: the fire rate.**

**Adoption rule**: the general gate, plus the `skipped` and `out_of_scope` counts must not rise,
plus the fire rate is recorded alongside the saving.

## 6. Tier 3

All three are **invisible to `swreview benchmark run`**, which iterates pre-built package
directories and never dumps (VERIFIED, `benchmark/runner.py:88-104`). They need the workstation
harness and the dump phase timing from Phase 1b, and each carries a **pass/fail precondition that
is stronger and cheaper than the scorecard** and is read first.

### Lever 9: package reuse

**Flag**: `package_reuse`, plus an extractor-side `--reuse`. **Default**: off. **Scope**:
extraction, not the review. **Read**: at dump time.

**Half the premise is false today.** The manifest has seven fields (VERIFIED, `ir/models.py:187-194`,
`Dump/ManifestBuilder.cs:28-65`): `document_id` (SHA-1 of the lowercased normalized **path**, not
the content), `vault_path`, `vault_version` (**null unless the vault writes that property back**,
plus a `not_extracted` gap; the EPDM API is not read by this build), `revision` (**null unless
set**), `configuration`, `local_modified` (**hardcoded null** plus an `unsupported` gap on every
document, every dump, `ManifestBuilder.cs:57,92-98`), `export_method`.

**There is no modification time, no file size and no content hash anywhere in the manifest, in
`Document` or in `EvidencePackage`.** A key built from "path, version and modification time"
reduces today to **path and configuration**, which says "the same files, in the same
configurations" and says nothing about whether they changed. Reusing on it makes the stale-package
failure certain rather than possible (RK-10).

**The key that is honest** requires new `ManifestEntry` fields `file_modified_utc` (from
`FileInfo.LastWriteTimeUtc`) and `file_size_bytes`, both nullable with a gap when the path cannot
be stat'ed, an IR bump to 1.3.0 and a `test_schema_sync` regeneration (brief Q6). The key is a
SHA-256 over, in order:

```
extractor.name, extractor.version, schema_version, extractor.profile,
dump options that change content: meshes (glb|stl|none), faces (needed|all),
                                 features (tree|none), equations (on|off),
design.root_assembly_document_id, design.active_configuration,
for each manifest entry sorted by document_id:
    document_id, configuration, sorted referenced configurations,
    file_modified_utc, file_size_bytes, component suppression state
```

stored as a top-level `reuse_key` on `EvidencePackage` so a reader can see what a package claims to
be. Each part earns its place: the extractor and schema version because a package written by an
older build may be missing a phase a newer reviewer expects; the profile and dump options because
a `model_check` package has empty `holes[]`, `fasteners[]`, `faces[]` and `bodies[]` **by design**
(`Dump/PackageWriter.cs:200-235`) and handing one to a full Review silently narrows it (RK-11);
**every** manifest entry rather than just the root, because `PackageWriter.DocumentPaths`
(`:381-401`) collects every document the traversal referenced, which closes the named risk of a
referenced part edited outside the assembly.

**What the key still cannot catch, each needing an explicit refusal rather than a hope**: unsaved
in-memory edits (mtime does not move until save; `GetSaveFlag` is already consulted by
`suppress-test`, so **refuse reuse when the active document reports unsaved changes** and say so
in the status line); a suppressed or lightweight component later resolved (`MeshExporter` skips
non-resolved components with a gap, `Dump/MeshExporter.cs:57-69`, so resolving one changes what a
review can see with **no file change**, which is why suppression state is in the key); a partial
dump (`PackageWriter.Build` continues past a failed phase and writes the package either way with
gaps, `:38-41,142-235`, and nothing says "this dump aborted"; add `extractor.completed`, or refuse
reuse of any package carrying a phase-level `tool_error` gap). Clock skew produces a **false
miss**, which is the safe direction.

**The lookup.** There is no index of run folders today: `RunFolders.Create` always makes a fresh
timestamped folder (`Review/RunFolders.cs:296-317`), "the pane's latest run" is an in-memory field
cleared on detach (`Review/ReviewHost.cs:258,271,288,380`), and `RunFolders.ProfileOf` reads only
the first 8 KiB of one `package.json` (`:52,125-186`) **precisely because** a full package is tens
of megabytes and the read happens on the SOLIDWORKS application thread. A scan that parses every
`package.json` is the thing those classes were written to avoid. Use
**`run_root/package-index.json`**, appended on every successful dump, one line per run folder
(`reuse_key`, folder, written-at, profile, byte size); a missing or unparseable index means "no
reuse", never an error; the lookup verifies the folder and its `package.json` still exist before
reusing. Fall back to a bounded head scan (the `ProfileOf` technique, capped at the N most recent
folders, with `reuse_key` near the top of the file) when the index is absent.

**The reused package still needs its own run folder**: `chat/server.py` claims a run folder per
chat and refuses a second (`RunDirInUse`, `:233-238,1341-1381`), and `session.json`,
`events.jsonl` and `report.md` are written into it. So reuse means create the new folder as today,
then **copy `package.json` and `meshes/` instead of dumping**. Measure the copy against the dump
time it replaced (probe P4); if the copy dominates, fall back to a `package-source.json` pointer
read by `load_package`, a change to one function (`LoadedPackage.base_dir` is one directory and
`mesh_file` resolves against it, `ir/loader.py:23-32`).

**Three guards, all required if this lever is adopted**: reuse is **stated, never silent**
(`reused_from` and `reused_at` on the package, "Reusing the extraction from `<folder>` (<age>)" in
the pane status line instead of "Extracting evidence from ...", the fact in the report header and
in `session.json`); **reuse never crosses a refusal** (unsaved changes, a non-resolved component,
an aborted dump, a different profile or dump option all mean extract again, because extraction is
minutes and a wrong finding is hours); **the key is recomputed at reuse time** from the live
document's references now, never trusted from the file.

**Touch points**: `Dump/ManifestBuilder.cs`, `Dump/PackageWriter.cs`, `ir/models.py`,
`contracts/ir.schema.json` (1.3.0), `Review/RunFolders.cs`, `Review/ReviewHost.cs`,
`ir/loader.py`, `swreview-extract dump --reuse`.

**Tests**: one unit test per row of the invalidation table asserting the key changes; an
unsaved-changes document refuses reuse; a `model_check` package never matches a `full` request; a
fake phase that throws produces a package that refuses reuse; a golden test that a reused package
produces a `session.json` whose `reused_from` is set.

**Measurement**: dump twice against an unchanged document, once cold and once with `--reuse`,
comparing dump wall clock. **Pass/fail precondition read first: the reused package must be
byte-identical to a fresh dump modulo `package_id`, `created_at`, `reuse_key` and the new reuse
fields.** If the reused package is not the package a fresh dump would write, the lever is wrong
regardless of what the model then says.

**Adoption rule**: byte-identity is a precondition, not a trade. Then a dump wall-clock reduction
worth the code. **Probes**: P3 (what is legitimately non-deterministic in a package: dump the same
unchanged document twice and diff field by field, which defines "byte-identical modulo X"), P4,
P5 (`file_modified_utc` moves on an ordinary save and does not move on open-and-close without
save).

### Lever 10a: lazy meshes

**Flag**: `lazy_meshes`, with extraction settings `extraction.meshes` (`eager` default, `lazy`,
`off`) and `extraction.lazy_fetch_body_limit`. **Default**: off, and `eager` is the extraction
default.

**Meshes are separable; faces are not.** Exactly one reader opens a mesh in the whole reviewer:
`check_tool_envelope` via `_mesh_for` (`tools/measure.py:218-228,283-303`), VERIFIED by
`grep -rn "mesh_file\|load_mesh" reviewer/src/swreview`. `MeshExporter` is a leaf phase and
`--meshes none` already exists.

Faces are a different matter. With the default `--faces needed`, `FaceDumper` describes only faces
**another dumper already asked for** (`Dump/FaceDumper.cs:46-71`), and those requests are minted
with live `IFace2` handles inside the hole, fastener and mate phases (`HoleDumper.cs:364`,
`FastenerDumper.cs:250`, `MateDumper.cs:227,252`). So "faces off, holes on" produces a package
whose `Hole.face_ids` name faces that do not exist, and the extractor already treats the four
geometry phases as one group. **Lever 10 is meshes-only in v1** and lazy faces (10b) is parked as a
redesign, not a flag.

**A second, independent reason to scope it that way**: `ExceptionStore.refresh`
(`exceptions.py:440-473`) recomputes each active exception's fingerprint, and the `geometry`
fingerprint hashes each component's transform **and the sorted parameters of its faces**
(`exceptions.py:184-187,287-295`). A package extracted without faces has empty `faces[]` for every
component, so **every accepted geometry exception would flip to `needs_review` on the first lazy
run and stay there** (RK-13). Nothing is silenced wrongly (the store never clears an exception),
but the exception mechanism becomes noise and engineers learn to ignore it. Meshes are in neither
fingerprint.

**The bridge fetch needs a fifth command.** The protocol vocabulary is exactly four (`ping`,
`capture`, `measure`, `interference`, VERIFIED in `Serve/PROTOCOL.md`, mirrored by
`bridge/client.py:348-409` and `tools/bridge.py`). Add `tessellate` taking a `component_id` and
returning `BodyRef` rows plus written paths. Design notes with their reasons: **reuse
`MeshExporter.ExportBody`** (`Dump/MeshExporter.cs:119-180`) rather than writing a second
tessellator, because a different chord tolerance in the two paths would make an envelope answer
depend on how the mesh arrived; **the host chooses the path**, exactly as `capture` does, because a
filesystem path in a request is a write the agent controls, and the client applies
`_relative_inside_package` (`tools/bridge.py:77-90`) before touching anything; **the read-only
guard passes it today** (`ReadOnlyGuard` is a denylist, `Guard/ReadOnlyGuard.cs:23-80`;
`GetTessellation`, `Tessellate`, `CurveChordTolerance` and `GetBodies2` are not on it and are not
covered by the `FeatureCut*`, `FeatureExtrusion*`, `InsertFeature*` or `SetSystemValue*` prefixes,
so **no guard change is needed and none should be made**); **review scope only** (a mesh fetch
writes a file and can take seconds, so it does not go to general chat; the refusal stays the
indistinguishable `unauthorized` the protocol already specifies); **one STA worker answers in
arrival order**, so a tessellation blocks every other bridge call behind it (probe P2, RK-14);
**bump `PROTOCOL.md` to 1.1** and have `ping` report it.

**Off the workstation there is no bridge**, so a lazily extracted package reviewed later on a
machine with no SOLIDWORKS has no way to answer a tool-access question. That is acceptable only if
the answer is `unresolved` and says why.

**Prerequisite defect, fixed first, as its own commit with its own test (RK-12).** In
`check_tool_envelope` (`tools/measure.py:283-320`), with `bodies == []` both `meshes` and
`unresolved` stay empty, `envelope_raycast` with `meshes=[]` returns `EnvelopeResult(hits=[],
unresolved=[])` (`geometry/envelope.py:180-198`), and the result is `status: "checked",
bodies_swept: 0, hits: []`. A model reading that sees a tool-access check that ran and found
nothing in the way. **It is reachable today** with
`swreview-extract dump --meshes none --profile full`, and lever 10 would make it the normal case.
It violates the module's own docstring ("a tool envelope that could not sweep a body has not
established that the body is out of the way", `tools/measure.py:14-16`). Fix: refuse `checked`
when `bodies_swept == 0`; return `unresolved` with the reason. One guard, one test, and it stands
on its own merits.

**`eager` is the default, and that is the constitution's position rather than a preference**: a
lazily extracted package reviewed off the workstation is a package with less evidence, and **the
flag that reduces evidence is the one that is opted into**. `lazy_fetch_body_limit` bounds how much
one review may pull back so a runaway does not stall the application thread; reaching the limit is
unresolved coverage, not a stop.

**Tests**: the zero-bodies guard; a body that cannot be fetched is named in `unresolved` (the path
`tools/measure.py:285-293` already takes for a missing mesh file); a bridge that refuses; the
fetch limit produces unresolved coverage.

**Measurement**: dump with `--meshes glb` and `--meshes none`, review each with the bridge open;
dump wall clock, bridge `elapsed_ms` per `tessellate`, total review wall clock. **Pass/fail
precondition read first: `check_tool_envelope` returns the same hits and the same `bodies_swept`
in both arms, or `unresolved` naming what it could not fetch.** **Probes**: P1 (does the mesh phase
dominate the dump; **lever 10's entire premise**), P2.

### Lever 11a: incremental re-review, RMS only

**Flag**: `carry_over_rms`. **Default**: off. **Scope**: the second and later reviews of one
design.

**The fingerprints already exist and no second hashing scheme is written.**
`exceptions.fingerprint(package, component_ids, kind)` (`exceptions.py:249-295`) already does both
kinds: `geometry` (per component, the 4x4 transform plus the sorted parameters of its faces;
bounding box and area deliberately excluded because they move under a rebuild that changed nothing,
`:163-181`; rounded to 1e-9 m; order-independent) and `feature_tree` (per document, every feature
row in index order over index, type name, name, depth, folder id, suppressed, described-state,
sketch presence and raw status and consumer count, fillet presence and default radius, child ids,
plus every equation's left-hand side and global flag, `:190-246`). `fingerprint_kind_for(check)`
picks by the `rms.` prefix (`:89-91`), and a component id the package does not hold raises
`LookupError` rather than silently re-binding. **That is the DRY line to hold in code review.**

**A carry-over is a much stronger claim than an exception refresh.** An exception says "this
accepted condition still looks the same"; a carry-over says "re-running this check would produce
the same verdict", which needs everything the check reads. What the fingerprints do not cover:
`fastener.*` reads `Hole.thread_depth`, `hole_depth`, `end_condition`, `Fastener.length`,
`thread_designation`, the `Thickness` **custom property** (`checks_fastener.py:99-116`) and the
answers to open evidence requests; `fit.*` and drawing checks read `DrawingSheet.dimensions`,
`parse_status`, `general_notes`; `interference.*` reads `package.interferences` and
`InterferenceSettings`; **everything** reads `EvidencePackage.gaps`, `extractor.profile`, the
checklist version, `Calculation.function_version` and `exceptions.json`.

**So v1 carries over only the families whose entire input is already inside one fingerprint**,
which on today's tree is `rms.*` and nothing else, excluding
`rms.detail.individually_suppressible` (brief Q7).

**The carry-over key**, per finding rather than per part:

```
finding.check, Calculation.function_version (when present), sorted(finding.component_ids),
fingerprint(package, finding.component_ids, fingerprint_kind_for(finding.check))
```

**Carry-over can never be silent**, and three readers look at three artifacts: the **finding**
gains optional `carried_over_from` (the session id), `carried_over_at` and `carry_over_key` (so
the decision is reproducible by hand), and **`Finding.status` is not touched** (a carried
`demonstrated` finding is still demonstrated; what changed is who demonstrated it and when, which
is provenance, not status; overloading `status` would break the scorecard's matching rules,
`scorecard.py:106-142`); **coverage** reuses the `checked` bucket with a reason starting "carried
over from ", rather than adding a sixth bucket that would touch the schema, the report renderer
and the scorecard aggregate for the same information; **the report** renders the originating run in
the heading line and states how many findings were carried versus re-run, so an engineer can see
at a glance which part of the report was not computed today (Principle VI).

**Six guards, because a carried-over finding looks like a verdict and is actually a memory**
(RK-15): carry only from a session that finished (`ended_at` non-null and no `failed` coverage
naming the check; a verdict from a run cut short by `max_steps` is not a verdict to reuse); **carry
only `demonstrated` and `checked_within_scope`, re-run every `suspected` and `unresolved`** (those
two are where the model's judgement sits, which is exactly what should not be frozen, and an
`unresolved` finding with an open evidence request is precisely what a new run might resolve);
never carry across a disposition (a finding the engineer accepted, rejected or deferred has a human
decision attached); never carry if `ExceptionStore.refresh` moved any exception touching these
components to `needs_review`; never carry across a profile, gap-set, checklist-version or
check-version change (covered by the key); **cap the carry** in age or in runs, because a finding
carried for twenty consecutive runs has not been computed for twenty runs.

**Tests**: the invariant that carried plus re-run equals total, and every carried finding's
`carry_over_key` recomputes to the same value against the current package; **a test that mutates
one feature row and asserts the finding is re-run rather than carried** is the minimum bar; a test
that a disposition blocks carry-over; a scorecard test over a session with carried findings.

**Measurement**: review a package, edit one part, re-dump, review again, flag off and on; tokens
and tool calls on the second review. **Pass/fail precondition read first: every finding touching
the edited part was re-run and not carried.** **Lever-specific counter: the carried count per
arm**, so a reader can see whether the quality came from computation or from memory. **A lever that
"improves" recall by remembering is not an improvement** (RK-16). **Probe**: P8 (the feature-tree
fingerprint moves exactly when it should: edit one feature of `RMS-A.SLDPRT`, re-dump, diff the
per-document fingerprints; **lever 11's premise**).

## 7. The general adoption rule

Four clarifications, **fixed in writing before the first A/B run**, not argued after a result is in
hand (brief Q9). The full protocol is in [ab-harness.md](ab-harness.md).

| Question | Answer | Why |
|---|---|---|
| "No known defect lost" over 3 reps | **Worst case.** Rejected if *any* on-run misses a defect that *any* off-run found | A defect found two times in three is found unreliably; a lever that makes it two in three when it was three in three has cost quality. Conservative is the right direction for a review tool |
| "No new false alarm" | **Median, with the worst case recorded** | Asymmetric on purpose. False alarms are the noisier metric and the cheaper failure (minutes, tracked as `false_alarm_handling_minutes`); a lost defect is the failure the product exists to prevent |
| "Worth the code" threshold | **A median total-token reduction of at least 20 percent, or a median wall-clock reduction of at least 20 percent**, against the off arm's median over the whole set | Below that is inside run-to-run variance at n=3 and does not justify a flag, a settings field, a test suite and a permanent branch in the code |
| The three off-runs disagree with each other about defects found | **The set is too noisy to gate on; fix that first.** Record the disagreement, raise the repetition count for that package, or fix the checklist | A gate whose control arm is unstable cannot decide anything |

**There is no exception to the threshold, at any lever.** `Decision` is computed by the FR-028
rule from the scorecards and nothing else (FR-027, SC-009), so an adoption case resting on a
number that is not in a scorecard - lever 3's observability case being the tempting one - cannot be
rendered, and overtyping the computed column is forbidden. Such a case is recorded where it
belongs: in `decision_reason` beside the computed `keep off`, and in `owner_signed_off`. Levers 9,
10 and 11 have **additional pass/fail preconditions read before the scorecard at all**, stated at
each lever; those narrow adoption, they never widen it.

**Every lever that fails is kept off and its numbers are recorded.** That is why the ledger has a
`Decision` column (`adopt`, `keep off`, `re-measure`) rather than a list of winners.

## 8. Not in this feature, with the reason

### Lever 8: model tiers per job. Deferred.

A scope recommendation, not a measurement result. Of four candidate jobs, only one is routable
today. The review turn is one call with no internal orchestration and judgement split. **The Ask
tab is not ours to route**: it is the SwpilotCLI terminal running Codex or Gemini CLI
(`settings.terminal_cli`) against our stdio MCP server, and the engineer's CLI chooses the model.
What we can do for the Ask tab is make its tool payload smaller, which is levers 2 and 4 - **but
only if both are wired into the MCP path, which is not free and is not yet true**. VERIFIED:
`mcp/server.py:257` builds its own specs (`tuple(spec_for(function) for function in functions)`)
from `MCP_TOOL_FUNCTIONS`, bypassing `ToolRegistry.functions_for`, which is where lever 4's tier
filter lives; the server holds no `EfficiencySettings`; and it has no system prompt to render
lever 2's notes into (`instructions` at `:496-499` is a fixed literal). So this claim is a
**requirement on those levers** (FR-039b for lever 2), not a description of what they already do,
and applying the trim inside `spec_for` to get it for free is forbidden by section 1's
process-global `_SPECS` rule. If the MCP path is not wired, the honest record is that this
compensation was not delivered, and this sentence is withdrawn rather than left standing.
**Tool-result summarisation does not exist**: `summarize_result`
(`agent/providers/__init__.py:270-283`) is a 200-character truncation with no model in it, so
building it is a new feature with its own risk (a summary that drops the number a check needed is a
quality regression no scorecard would attribute to the summariser). That leaves `answer_evidence`
(`runner.py:470-495`), whose job is mechanical and which is the **minority of turns**.

The cost of doing it anyway: `settings.py` needs a second `FAST_MODELS` table (a model id must
never be a literal anywhere else; the module docstring's first point exists because feature 001
wrote a retired vendor's id into `session.json`); `runner.py` needs an injected `fast_provider`;
`report/session.py`'s `ProviderInfo` is singular and `ReviewSession.model` is "the single field
every consumer can rely on", so two models per session breaks an invariant; `chat/server.py` and
`benchmark/runner.py` both grow a parameter; and the measurement needs **cost, not tokens**,
because tokens per tier are not comparable, which means the scorecard grows a price table. **Five
modules and two contracts for a saving on the minority of turns.**

If the owner wants it later, the narrow version is `answer_evidence` on the fast tier, and the test
that matters is that `_reconcile_reruns` (`runner.py:348-379`) still folds the re-run verdict onto
the original finding: a fast model that records a *new* finding instead of replacing the old one
produces two contradictory verdicts in the report.

### Lever 10b: lazy faces. Parked as a redesign, not a flag.

Reason at lever 10a: faces are minted with live handles inside other phases, so a package with
holes and no faces names faces that do not exist; and every accepted geometry exception would flip
to `needs_review` on the first lazy run.

### Lever 11b: per-check declared input digests. Out of scope for v1.

The broad version needs every check to declare and hash its inputs, and a check that forgets one
carries a wrong verdict forever (brief Q7).

### A deterministic fastener-joint enumerator. Out of scope for v1.

Roughly 150 lines plus tests reusing `_is_coaxial`, and a wrong pairing produces a **deterministic**
wrong finding that looks authoritative. It is a separately specified increment with its own golden
fixtures (brief Q4). If the Tier 2 schedule has room, this or lever 12 is a better use of it than
lever 8.

### Concurrent local tool execution. Out of scope, permanently as far as this feature is concerned.

Three correctness hazards for no measurable gain; reason at lever 6.

### Lever 12: rules over tokens. Not a flag. Standing practice.

Every finding class the model keeps producing that a rule can express becomes a deterministic
check, which costs zero tokens per part thereafter. The measurement is the count of findings by
check kind over time, which the instrumented scorecard gives for free. It belongs in the spec as a
practice with a review cadence, not as a phase task.
