# Workstation session 2026-09-20: reworked-tab layout, hidden follow-up, Remodel tab

Pilot workstation, SOLIDWORKS 2024, against `local` `c36f183` (merge of GitHub `main`
`e04c027` into this lane). Findings for the 2026-09-20 handover
(`docs/workstation-handover-2026-09-20.md`). Run folders of real designs stay out of git.
This file names folders only; it carries no vault path.

**Headline: the new Review layout hides the three things an engineer needs after a
run — finding details, follow-up answers, and the lightweight warning.** The backend
did the right work. The pane did not show it. Tonight did **not** save tokens (pane
still all levers off; +27% vs this morning). The Remodel tab is still the 2026-09-18
refusal. **This seat is done testing.** The owner machine builds and verifies the
updates below.

---

## Machine / runs

| Item | Value |
|---|---|
| Commit | `c36f183` (`local` ← `e04c027`) |
| Provider / model / effort | openai / `gpt-5.6-luna` / high |
| Assembly | the small assembly. Both dowel pins **lightweight** (FeatureManager feathers). Not resolved this sitting. |
| Review | `20260919-184136-…` (18:41–18:49; follow-up at 18:49) |
| Standards | `20260919-184738-…-standards`, then `20260919-184809-…-standards` |
| Model check | not run tonight |
| Remodel tab | 18:47, `tool-service-20260919-184725.log` |
| Task E resolved pair | not run |
| Task F CLI probes | not run (no `remodel-probes` ledger) |

Review Start-here ids (pane / `report.md` / `attention.json` agree):
**F-004, F-003, F-002, F-005, F-006**. Same set as 2026-09-19. No `interference.static`.

---

## 1. NEW BUG: finding Details open in a few-pixel strip

**Symptom (engineer):** expand the first finding (Start here #1 = F-004). The fold
appears in a sliver at the bottom of the pane, a few pixels tall, not readable, and
there is nothing to drag to make it taller.

**What the report holds for F-004** (so this is not empty content): mates to faces
(`swMateCONCENTRIC` / `swMateCOINCIDENT`) on the assembly and one pin instance;
status demonstrated; check `rms.assembly.mates_to_reference_geometry`. F-002, if
opened, is worse: 53 ungrouped features and a long inputs list.

**Root cause.** After `session.ended` the Review page is a column of
non-shrinking chrome plus one leftover flex child:

1. Header, session buttons, meta line.
2. `#attention-panel` — five Start-here **cards**, no `max-height`, no internal
   scroll (`app.css` `.attention-row` is a four-row card).
3. Transcript **header** (the fold toggle).
4. `#transcript` — `flex: 1 1 auto; overflow-y: auto` (`app.css` ~491). **No
   `min-height`.** Findings and their `.details` live only here.
5. `#coverage-panel` ("Not reached").
6. `#followup` — `position: sticky; bottom: 0` (`app.css` ~927), so it always
   keeps its height.

The leftover for (4) on a docked Task Pane is a few pixels. Clicking a Start-here
card calls `revealFinding` (`app.js` ~966): it **opens Details and
`scrollIntoView`s into that sliver**. There is no splitter. The engineer cannot
expand it.

The three-tier rewrite (`1d0209b`) moved details into the transcript on purpose.
It did not cap the Start-here stack that now sits above it.

**Not the cause:** empty details, a failed dump, or a hidden `[hidden]` toggle
(tokens.css `[hidden] { display: none !important }` works; the fold is open, just
clipped).

**Recommended fix (owner):** give `#attention-panel` a max-height and its own
scroll; give `#transcript` `flex: 1 1 0; min-height: 8rem` (or similar) so findings
cannot shrink to a sliver. Pin it with a page test at a 300×600 viewport: open
five Start-here rows, press the first card, assert the finding `.details` has a
usable client height. Do not add a native popup.

---

## 2. NEW BUG: follow-up answers are written, then hidden

**Symptom (engineer):** asked what the first warning means. No answer appeared.
Guessed the transcript window was too small (related to §1, but not sufficient).

**What actually happened.** The POST succeeded. `events.jsonl` on
`20260919-184136-…`:

- First `session.ended` at 22:43:10Z — turn 1, 38 rounds.
- Follow-up answer starts at seq 1076 (22:49:08Z).
- Second `session.ended` at 22:49:11Z — **turns: 2**, follow-up ~61k tokens / 5.9 s.

The model **did** answer. The page hid it.

**Root cause (two layers).**

1. Default `state.transcriptFolded = true` (`app.js` ~114). Folded CSS
   (`app.css` ~502):

   ```
   .transcript.folded .block,
   .transcript.folded .card.tool { display: none; }
   ```

   Findings stay visible (`.card.finding`). Follow-up prose is
   `render.textBlock('engineer' | 'assistant')` → class `block`. **Both the
   question and the answer are `display: none` until the engineer opens
   Transcript.** `sendFollowUp` (`app.js` ~841) does not unfold.

2. Even after unfolding, the transcript viewport may be the sliver in §1, so the
   answer is still easy to miss.

**The hidden answer** (so the engineer does not have to hunt the events file).
The model treated “#1” as the provenance / revision gap, not as Start-here F-004
(mates to faces) and not as the lightweight “Not examined” line:

> #1 is a **configuration-control and traceability issue**, not a demonstrated
> geometry defect.
>
> The review examined configuration Default. The assembly and main part report
> revision 1. The dowel-pin document has no extracted revision. The package does
> not establish vault version or local-vs-vault modification for any document.
> Findings apply to the extracted snapshot only. ER-003 is the open request.

**Recommended fix (owner):** on `sendFollowUp`, unfold the transcript (and
scroll the new `.block.assistant` into view). Optionally keep engineer/assistant
blocks visible while tools stay folded. Pin: post a follow-up with the transcript
folded; assert the answer node is visible. Decide whether “first warning” should
bind to Start-here #1 — that is a prompt/policy question, not this bug.

---

## 3. Lightweight warning: present in the report, invisible on Review

**Symptom (engineer):** pins still lightweight; expected a popup; saw none.

**The dump and the report are correct.** `package.json` records both pin
instances as `lightweight`. Review `report.md` Summary:

> Not examined: 2 of 4 component instances were not read: [both dowel pins]
> (lightweight). Interference, fit and the feature-tree rules cannot see them.

Same sentence in both Standards reports. Coverage rows still say
`lightweight; tree not read`. No `interference.static` in Start here — same as
2026-09-19, expected.

**There is no popup, by design.** Handover 2026-09-20 Task E named three
surfaces: Review **status line**, report Summary, check-tab sentence above
Start here. Nothing is a modal.

**Why Review still looks silent.**

1. The Review tab has **no** `#not-examined` block. Model check and Standards
   do (`check-page.js` `renderNotExamined`, `.not-examined` warn stripe).
2. Review posts the sentence on the header **badge**
   (`ReviewHost.ReadyMessage` → `showStatus` → `#backend-state`).
3. That badge is `max-width: 45%; overflow: hidden; white-space: nowrap;
   text-overflow: ellipsis` (`app.css` ~62–70), commented as necessary so a
   long “Reviewing 4 components (23 gaps).” does not squeeze the document
   name. On a ~300 px pane the visible text is roughly
   `Reviewing 4 compon…`. The words **not read** / **lightweight** never
   appear.

So Task E’s Review-tab warning was implemented and then clipped by the same
header rule that the three-tier rewrite kept.

Standards should have shown the warn-striped paragraph above Start here. If
that was missed, it is still a weaker signal than a modal, and Review — the
tab they were on — has none.

**Recommended fix (owner):** reuse the check-tab `#not-examined` sentence on
Review (same `unexamined.py` string), above Start here, not in the badge.
Keep the badge as `Reviewing 4 components` / backend health. Do not add a
Win32 popup. Pin: a package with two lightweight instances must put the
full sentence in a visible, wrapping node at 300 px width.

Nothing was resolved; the extractor still will not change the open session.
The resolve-per-component request from 2026-09-19 still stands.

---

## 4. Remodel tab: same refusal as 2026-09-18 (not Task F)

**Symptom (engineer):**

```
the bridge returned status 'error': this bridge was not built with a remodel
seat, so no remodel command can reach SOLIDWORKS
```

**What they pressed.** The **Remodel tab**, with the assembly still open.
`%LOCALAPPDATA%\SwReview\logs\tool-service-20260919-184725.log`:

```
command=remodel.probe_scope status=error
error="this bridge was not built with a remodel seat..."
```

**Root cause.** `ToolServiceHost.Attach` builds `BridgeServices` with
`RemodelGate` and **no** `RemodelSeat` (`ToolServiceHost.cs` ~831–835).
`BridgeDispatcher.Seat()` throws that exact sentence
(`BridgeDispatcher.cs` ~1751–1755). Recorded as “not a bug” on 2026-09-18
§4. Still true.

Phase 2 on this pull (`eb037b4`…`e04c027`) added `swreview-extract probe remodel`
and fifteen probe bodies. That command uses `SwRemodelProbeHost` and a
throwaway part. It is **not** the Remodel tab. The tab still talks to the
in-process bridge that has no seat. `SwRemodelSeat` exists on the add-in
pipeline; it is never assigned onto that bridge.

Task F was: SOLIDWORKS running, **no document open**, CLI
`swreview-extract probe remodel --acknowledge-throwaway-part`. That was not
run. A Remodel-tab press with the assembly open is the wrong command.

**Recommended fix (owner):**

1. Remodel tab: refuse **before** Start — “this build has no remodel seat;
   run `swreview-extract probe remodel` with no document open.” Same
   recommendation as 2026-09-18.
2. Do not treat tonight’s error as a probe-ledger result.
3. Run Task F (`swreview-extract probe remodel`, no document open) on a
   machine that will keep testing. **Not this seat.**

---

## 5. What the review actually found (so the layout bugs are not the whole story)

Same six findings as 2026-09-19, pins lightweight:

| Id | Check | Status | What it is |
|---|---|---|---|
| F-004 | `rms.assembly.mates_to_reference_geometry` | demonstrated | First Start-here. Concentric/coincident mates to faces, not reference geometry. |
| F-003 | `rms.sketches.fully_defined` | demonstrated | Sketch2 under-defined. |
| F-002 | `rms.grouping.all_features_in_a_group` | demonstrated | 53 features outside every group. |
| F-005 | `rms.params.global_variables_present` | demonstrated | Equation manager empty. |
| F-006 | `rms.params.dimensions_driven_by_equations` | suspected | No equation-driven dimensions. |
| F-001 | `rms.folders.present` | suspected | Six group folders missing. Not in the top five. |

Live interference ran and returned **no groups** (`report.md` Coverage /
Checked). That is the lightweight hollow, not a clean assembly. Fit / stack /
hole alignment unresolved: pins have no loaded geometry. Three evidence
requests still open (drawing package, resolve pins, vault/revision metadata).

Standards Start here: **F-001** `standards.part.sketches_fully_defined` (same
as 2026-09-19).

---

## 6. Tokens: tonight did not save any

Same assembly, same model (`gpt-5.6-luna` / high), **every efficiency flag
false** on both pane runs — including `parallel_tool_calls`. The lever-6 CLI
cut never reached the pane (default still off; `SET TOO SMALL`).

| Run | What | Rounds | Total tokens | Notes |
|---|---|---|---|---|
| `20260919-135032` | This morning’s pane baseline | 32 | **1,215,720** | 95.3% cached input, 83 s |
| `20260919-184136` turn 1 | Tonight’s review only | 38 | **1,538,990** | 96.1% cached input, 93 s |
| same folder, both turns | Review + follow-up | 39 | **1,600,549** | Follow-up +61,559 (5.9 s) |

Turn 1 alone is **+323k tokens (+27%)** and **+6 rounds** versus this morning.
Uncached input was about the same (~57k vs ~60k). The extra bill is the extra
rounds: the conversation was resent six more times. The follow-up was cheap
relative to the review (mostly cache).

CLI lever-6 **on** median on this dump was **464k / 11 rounds**. Tonight was
still the off-shaped run. Do not flip the pane default from this packet. If
command-line studies hold lever 6 on (the decision already recorded), that is
CLI only.

---

## 7. Gate leftovers from the absorb (not pane)

`update-workstation.ps1 -NoPull` stopped on pytest before the C# build. We
built Release anyway. C# suites green: 1843 extractor + 1266 add-in.

| Test | Kind |
|---|---|
| `test_a_retry_moves_the_attention_record_to_the_same_index_as_the_session` | Flake. Failed once (empty `attention.json` / EOF). Passed on rerun. |
| `test_no_code_path_in_stage_1_reads_or_writes_any_idimension_member` | Reproducible. `RemodelProbe.cs` names `IDimension` in a string that says v1 does not read it. |

---

## 8. FEATURE: say what each important finding means for this model

**Ask (engineer):** Start-here titles are check jargon
(`mat:0002 (swMateCONCENTRIC) references swSelFACES…`, `53 content feature(s)
sit outside every group`). It is hard to know what the issue is for *this*
assembly. The follow-up tonight existed because of that, and then the answer
was hidden (§2).

**What to build.** Under each Start-here row — and under each finding’s one-line
title on Review — the model writes one or two short sentences: **what this
means for the model that was just reviewed.** Not a restatement of the check
id. Not a second ranking. Same text in `report.md`’s Start-here section so the
three surfaces stay aligned.

Example, for tonight’s F-004 (do not ship this string; it is the shape):

> These mates locate a dowel pin on faces of the plate. If those faces are
> edited, the mate can fail. Reference planes or axes would survive that
> change.

F-003: which sketch is under-defined and that a later edit can drift.
F-002: the tree has no group folders, so 53 features are loose.
F-005 / F-006: nothing is named as a global, so diameters and depths are
raw dimensions.

**Constraints.**

- LLM-authored, after the findings exist; do not invent a deterministic
  paraphrase that guesses intent.
- Only the amplified Start-here set (and the matching finding cards). Do not
  write an essay under every coverage row.
- No extra ranking, no severity invented on the page.
- If the model is unsure, say so; do not dress a suspected row as demonstrated.
- The explanation is for the engineer, not a new check.

This is the owner’s feature. This seat will not prototype it.

---

## What the other machine should update

This workstation will not run another SOLIDWORKS pass, Task E resolved pair,
Task F probes, or a lever A/B. Build and verify on the development machine
(or a later handover). Priority is the order below.

| # | Kind | Change | Why |
|---|---|---|---|
| **U1** | Bug | Review layout: cap `#attention-panel` (max-height + scroll); `#transcript` `flex: 1 1 0; min-height: ~8rem`. Pin at 300×600: first Start-here card opens Details with a usable height. | §1. Details are a few-pixel sliver. Makes the tab unusable after a run. |
| **U2** | Bug | On follow-up send: unfold the transcript and scroll the assistant `.block` into view. Or keep engineer/assistant blocks visible while tools stay folded. Pin: folded transcript + follow-up → answer node visible. | §2. Tonight’s answer was written and hidden. |
| **U3** | Bug | Put the `unexamined.py` Not-examined sentence on Review above Start here (same warn stripe as the check tabs). Stop putting that sentence in the 45% ellipsis badge. | §3. Pins were lightweight; engineer saw no warning. |
| **U4** | Bug | Remodel tab: refuse **before** Start — no seat on this bridge. Do not send `remodel.probe_scope` into the in-process tool service until a seat is wired. | §4. Same 2026-09-18 error. Not Task F. |
| **U5** | Feature | Under each Start-here item (pane + `report.md`), the LLM writes what the finding **means for this model**. Same text on the finding card. See §8. | Engineer cannot tell what the issue is from check titles. |
| **U6** | Test debt | Name/fix the flake `test_a_retry_moves_the_attention_record_to_the_same_index_as_the_session`. Stop `test_no_code_path_in_stage_1_reads_or_writes_any_idimension_member` failing on `RemodelProbe.cs` documentation strings. | §7. Official `-NoPull` gate is red. |
| **U7** | Later, not this packet | Held-out second design before any lever-6 **pane** default. CLI studies may keep `--lever parallel_tool_calls` on. Task F CLI probes and the real standards profile when someone is testing again. | §6. Tonight cost more tokens, not less. |

Do **not**: flip the pane lever-6 default; treat the Remodel-tab error as a
probe verdict; send more test tasks to this seat; commit run folders.

## Never

- Flip the pane lever-6 default from this packet.
- Treat the Remodel-tab error as a probe verdict.
- Commit run folders (they carry vault paths).
- Ask this workstation to re-run Task A2 / E / F to prove the fixes.
