# Workstation session 2026-09-20 (evening): Review GUI after a document change

Pilot workstation, SOLIDWORKS 2024, against `local` `d83ecbe` (merge of
`origin/codex/pretest-readiness-2026-09-20` into this lane). This sitting is after the
pretest rebuild. Run folders of real designs stay out of git. This file names documents
only; it carries no vault path.

**Headline: the Review tab still treats one session as the whole pane.** Opening another
document does not clear the last review. Findings stay open as long cards. Start here is
capped at five with no usable path to the rest. The engineer asked for a reset, optional
per-document tabs, headline-only findings, a swap between results and transcript, and
**part drawings in the review context** (extract if they exist; offer to make or improve
them once the assembly is understood; ask intelligent questions when context is missing).

**Remodel on a part of the big assembly [Default] is the designed no-seat refuse.** The banner is
honest. It is not a remodel. It tells a SOLIDWORKS user to run a console command with no
document open.

This seat is still not the place to implement these. The owner machine decides the
surfaces below.

**Ship packet (not git):** `C:\Users\csorkness\smart_SW-handoff-2026-09-20-gui`. Transfer
that whole folder. It is a new packet, not an update of
`smart_SW-handoff-2026-09-20` (that one was the morning U1–U7 sitting).

---

## Machine / documents

| Item | Value |
|---|---|
| Commit | `d83ecbe` (`local` ← `codex/pretest-readiness-2026-09-20`) |
| Provider / model / effort | openai / `gpt-5.6-luna` / high (Review). Check tabs use `gpt-5.6` in the report header only. |
| Review tab | last review still on screen after a new document became active |
| Remodel tab | a part of the big assembly (`.SLDPRT`, `[Default]`); badge `Backend ready` |
| Remodel banner | `this build has no remodel seat; run swreview-extract probe remodel --acknowledge-throwaway-part with no document open.` |
| Packet | `C:\Users\csorkness\smart_SW-handoff-2026-09-20-gui` |

Tonight’s runs (copied into the packet `dumps/`), named by their folders' timestamps: the rest
of each folder name is the design number (owner decision 11B, 2026-09-24). The replay of
feature 008 later took `191314` and `190840` as the small assembly's two recordings and
`192014` as the big assembly's recording.

| Folder | What | Notes |
|---|---|---|
| `20260920-190758-…` | Review of the small assembly, ~4 s, 0 findings | Stop / aborted. Pins still lightweight. |
| `20260920-190840-…` | Review of the small assembly, 7 findings, 1.47M tokens / 37 rounds | Pins still lightweight. Start here F-004…F-005. 2 beyond top five. |
| `20260920-191314-…` | Review of the small assembly, 13 findings, 1.58M tokens / 39 rounds | Pins **resolved**. Interference F-001 / F-002 in Start here. **8 beyond top five.** ER-002 asks for the part drawing package. No drawing sheets extracted. |
| `20260920-192014-…` | Review of the big assembly, **99 findings**, **12.4M tokens** / 41 rounds / 2 turns | Big assembly. Start here is five interference rows. **94 beyond top five.** 3 of 89 instances not read. No drawing graded. |
| `20260920-192739-…-standards` | Standards on the part | Verdict `not_ready`. Notes: **no drawing graded**. |
| `20260920-192814-…-check` | Model check on the part | 3 RMS findings. No drawing record. |
| `logs/tool-service-20260920-192710.log` | Remodel attach | Part opened; no remodel command; process stopped. |

---

## 1. Opening a new model does not reset Review

**Symptom (engineer):** a new model opens. The last review’s findings, Start here cards,
and opened Details stay on the Review tab. There is no control that clears the GUI so the
pane matches the document now on screen.

**What the code does.** `document.changed` in `ReviewPage/app.js` only:

1. clears the **Before this review** preparation panel,
2. writes the new path onto `state.documentInfo`,
3. updates the header name.

It does **not** call `resetTranscript()`. That helper exists, but the only live caller is
a successful `review.start`. So the header can name the part while the body is still the
previous assembly’s session.

`ReviewHost` already keeps a `_sessions` list. The page shows one chat. There is no Clear
/ New review / Dismiss results button.

**What this means for the model.** The engineer can accept, reject, or ask a follow-up
against findings that belong to a different document than the one SOLIDWORKS is showing.
Show in SOLIDWORKS would highlight the wrong tree. A second Review is the only reset, and
that spends tokens. Until the pane is cleared or retargeted, the on-screen model and the
on-screen review are two different claims.

**Recommended fix (owner):** on `document.changed`, if `path` (and configuration) is not
the session that is on screen, hide Start here, hide or collapse every finding, clear the
follow-up box, and disable Open report / Open folder until a review of *this* document is
started or an older session for this document is chosen. A cheap **Clear review** control
should do the same without opening another document. Do not start a review on document
change.

---

## 2. Request: a tab (or session chip) per reviewed model

**Ask (engineer):** can Review keep a tab for each model, so switching documents does not
destroy the last review and does not leave the wrong one painted on the pane?

**What exists today.** One Review WebView. One `state.chatId`. Host-side session records
are already a list. Opening another document does not create a second page.

**What this means for the model.** Real work is not one file. An assembly review, then a
pin, then the plate, is a normal night. Forcing a single sticky transcript means either
the last model’s issues haunt the next one (§1) or the engineer loses the first review
the moment they start the second. Per-document tabs would keep each model’s findings
bound to that model.

**Options (owner decides; this seat does not pick):**

| | Option | Effort | Risk | Maintenance |
|---|---|---|---|---|
| **A** | Session chips under the header: one chip per `chat_id` this SOLIDWORKS session has reviewed, labelled with document name + configuration. Clicking a chip restores that transcript. Opening a new document selects no chip until Review is pressed. | Medium | Must not mix events across `chat_id` (the stream already drops foreign frames) | One extra bar; host already has `_sessions` |
| **B** | True inner tabs, one per document path. Same restore rules as A, heavier chrome on a 300 px pane. | High | Narrow pane + tab overflow | More CSS and focus rules |
| **C** | No tabs. Only the §1 reset / Clear control. | Low | Engineer re-opens the report from disk to compare two models | Smallest change |

**Recommendation: A, not B.** The host already has the list. Chips reuse it. Full inner
tabs fight the docked width. C alone fixes the wrong-model smear but throws away the
ability to flip back to the assembly after opening a part.

---

## 3. Findings stay too detailed; the headline is not the default view

**Symptom (engineer):** after a review there is still so much detail that the general
issue is hard to see. Need a way to close the detail for **each** finding so only the
headline that describes the issue in general is showing.

**What the page already has, and why it is not enough.**

The three-tier rewrite intended: Start here, then one-line findings, then a folded
transcript. In this build that is not what the engineer gets.

1. **Start here is five fat cards**, not headlines. Each row prints id, policy reason,
   full title, check id, status/severity/components, and (after U5) the LLM explanation.
   `#attention-panel` is capped at `14rem` and scrolls, but those five cards still own
   the top of the pane.
2. **Finding cards always show more than a headline.** `render.findingCard` hides the
   `.details` fold (`hidden = true`), but it always prints `observed` as `.facts` under
   the title. That paragraph is the long “mates to faces…” / “53 features…” body, not
   the headline.
3. **Clicking a Start-here row forces Details open** (`revealFinding` → `setDetails(card,
   true)`). There is Hide details on that card, but no Collapse all, and the next ranked
   click opens another fold.
4. **A folded transcript still shows every finding card.** `.transcript.folded` hides
   `.block` and `.card.tool` only. Findings stay in the ledger. So “close the transcript”
   does not produce a headline list.

**What this means for the model.** The first thing the engineer should see is “this pin
is mated to faces” or “this sketch is under-defined”, not the check id, the input list,
and the explanation stacked three times (Start here + card title + `observed`). On a
narrow pane that stack hides the next finding. People miss F-001 and everything past the
top five because they never get a clean list of issues.

**Recommended fix (owner):**

- Default each finding to **headline only**: id + one-line title (or the U5 sentence,
  not both). Hide `observed` until Details is open.
- Keep Hide details; add **Collapse all findings**.
- Start-here click should **scroll to the headline**, not auto-open the fold.
- Optional: Start here as a numbered one-line list; put the explanation only inside the
  finding’s open Details so it is not duplicated.

---

## 4. Request: swap the whole Review GUI between results and transcript

**Ask (engineer):** it would be cleaner to swap the entire GUI to the transcript **or**
the results, not stack both.

**What the page does.** Results (Start here + finding cards) and transcript (tool calls
and prose) share one column. The transcript fold only hides prose/tools. Follow-up stays
sticky at the bottom. After U1 the leftover transcript viewport is usable, but the
engineer still has to share height among Start here, the findings ledger, coverage, and
the follow-up box.

**What this means for the model.** Results answer “what is wrong with this model.”
Transcript answers “how did the reviewer get there.” Mixing them in one scroll makes
both worse: details open in a cramped strip (the 2026-09-20 morning bug), and a
follow-up answer competes with five Start-here cards. A swap would let the engineer
read the issue list as a list, then open the working notes only when they want them.

**Recommended fix (owner):** two mutually exclusive views on Review, same `chat_id`:

| View | Shows | Hides |
|---|---|---|
| **Results** | Start here (headline list), finding headlines, Not-examined, coverage summary, follow-up | tool cards, assistant/engineer blocks |
| **Transcript** | the chat / tool record, follow-up | Start here cards and finding bodies (or a one-line jump list only) |

A segmented control (Results | Transcript) above the session buttons is enough. Do not
add a third native window. Open report remains the full markdown.

---

## 5. Top five is not enough; the rest of the findings are hard to reach

**Symptom (engineer):** on a big assembly, top 5 is not nearly enough. The rest of the
findings should be easier to find.

**What the product already claims.** `attention.py` hard-codes `TOP_N = 5`. The contract
is **amplify, never filter**: every finding is still in the transcript and in
`report.md`. `attention.json` records `not_amplified.beyond_top_n`. The pane’s
`attentionPanel` slices `rows` to `top_n` and does not render a “N more” control. There
is no findings index, search, or Show all.

On the small assembly that already hid **F-001** (`rms.folders.present`) behind the top
five. Tonight’s resolved small-assembly review hid **8 of 13**. The big assembly hid
**94 of 99**. A larger assembly will hide interface and rebuild rows the same way.

**What this means for the model.** Start here is a triage hint, not the bill of
materials for issues. If the only comfortable surface is five cards, the engineer will
treat the other findings as if they were not found. Folders missing, extra RMS rows,
and later interference hits never get a disposition. The model is then “reviewed”
while most of its recorded issues were never looked at.

**Recommended fix (owner), in this order:**

1. **Findings index on Results.** Every finding as one headline row, ranked order,
   Start-here rows marked. Click jumps to that card. This is the missing “rest of the
   findings” path and does not change `TOP_N`.
2. **A visible count** on Start here: `Showing 5 of 17. Open all findings.`
3. Only after (1): consider raising `TOP_N` or making it scale with finding count.
   Do not silently print twenty fat cards on a 300 px pane.

Do not “fix” this by dumping the full ranking into the current Start-here card style.
That would make §3 worse.

---

## 6. Remodel on a part of the big assembly: no-seat copy, not a failed remodel

**Symptom (engineer), verbatim but for the part's name:**

```
<a part of the big assembly>.SLDPRT [Default]
Backend ready
this build has no remodel seat; run swreview-extract probe remodel --acknowledge-throwaway-part with no document open.
```

**What this is.** The pretest U4 refuse-before-start. `RemodelHost.NoSeatMessage` is
that exact sentence. `remodel.js` shows it on init when `remodelAvailable` is false.
The in-process tool-service bridge is still built **without** `RemodelSeat`
(`ToolServiceHost.Attach`). No `remodel.probe_scope` was sent. That is progress versus
the 2026-09-18 / morning error after Start.

The active document is a **part**, which is the only kind Feature 004 will reorganize.
The tab is still a dead end because this **build** has no seat, not because the file is
wrong.

**What this means for the model.** Nothing on the part was remodeled, probed, or
copied. The FeatureManager did not change. The banner is a build capability message
dressed as a command the engineer should type. Following it with this part still open
is the wrong procedure (Task F is: SOLIDWORKS running, **no** document open, console
host). Closing the part to run a throwaway-part probe does not remodel the part
either. Until a seat is wired onto the pane bridge, this tab cannot touch this model.

**Recommended fix (owner):**

1. Keep the refuse. Do not send remodel commands.
2. Replace the CLI string in the pane with engineer language: **Remodel is not in this
   build yet. This tab will not change the open part.** Put the `swreview-extract probe
   remodel --acknowledge-throwaway-part` line in the handover / testing doc, not in the
   Task Pane.
3. Wire `RemodelSeat` onto the in-process bridge only when Feature 004 pane execution
   is actually being delivered. That is a product decision, not a tester action.

Do not treat this screenshot as a probe-ledger result. Do not ask this seat to run
Task F.

---

## 7. FEATURE: put part drawings in the review, then offer to make or improve them

**Ask (engineer):** Review should include **part drawings** in its context. Extraction
from those drawings is an open question — we are not sure how to pull the data yet. If a
part has no drawing, the product should **offer to make one**. If a drawing already
exists, it should **offer to improve it** once the review has the context of the
assembly and how the parts go together. That means feeding the language model the
**right** mechanical-assembly details, not the whole tree every round. We already have
most of that data in the dump; we need to decide how to use it. When context is still
missing, come back to the engineer with **intelligent questions** that will steer the
next suggestions.

**What tonight already proved.** Both paid Reviews asked for drawings and then stopped.

- The small assembly's resolved review (`20260920-191314-…`) coverage:
  `drawing.manufacturing_inputs` — no sheets, no
  dimensions, drawing phase did not run. Fit and stack stayed unresolved for the same
  reason. Evidence request **ER-002** is open: the native part drawing package for
  the small assembly and a readable dimensional spec for the two pins (notes, general
  tolerances, finish, hole/shaft limits, functional gaps).
- The big assembly's review (`20260920-192014-…`): 99 findings, still **no drawing
  graded**. Same gap.
- Standards on the part: `no drawing graded`.
- The agent already called `find_dimensions` on the small assembly. There was nothing to
  find.

So the product already *wants* drawings. It cannot see them when the engineer reviews
an assembly or a part.

**What exists today (so the owner does not reinvent).**

1. Feature 001 already defines one design as **an assembly plus its drawing package**.
   Tools `get_drawing_sheet`, `find_dimensions`, and `record_drawing_finding` are live.
   PDF ingest (`swreview ingest --pdf`) can put exported sheets into `package.json`.
2. Native drawing extract **only runs when the dump root is a drawing**
   (`PackageWriter`: “The dump does not go looking for the drawings of an open
   model”). A Review of the small or the big assembly writes the drawing-phase gap and
   moves on. Opening the `.SLDDRW` on the Standards tab is a different dump.
3. `request_evidence` is the existing “ask the engineer” tool. Tonight it asked for
   the whole drawing package in one ER. That is not yet a short, guided question
   (“which views matter?”, “is this a press fit or a clearance?”, “what is the
   governing datum?”).
4. Creating or finishing drawings is **ADR-001 layer 3**. Feature 001 explicitly
   excludes it (`FR-027`: do not create GD&T or place general drawing dimensions;
   the spec says automated drawing creation is a later feature). Remodel (Feature
   004) reorganizes a **part**, not a drawing.

**The data we already have, and can feed without a new extract.** After an assembly
Review the package already holds: component instances and load state, mates and
mate entities, holes and threads, fasteners, live interference groups, feature-tree
RMS rows, configurations, and the open evidence requests. That is the “how it is
assembled” brief. What is missing is the drawing that **governs** those joints
(limits, notes, views, balloons).

**How extraction can work (owner decides; this seat does not implement).**

| | Option | What it does | Effort | Risk |
|---|---|---|---|---|
| **A** | Attach **sibling / already-open** drawings when the dump root is a part or assembly: same stem next to the part, drawings already loaded in the SOLIDWORKS session, views that already reference the reviewed documents. Do not walk the vault. | Puts sheets into the same package the Review already has. | Medium | Wrong-stem false attach; must stay read-only; lightweight referenced models stay unread |
| **B** | Keep PDF ingest only. Engineer exports drawings first. | Already built. | None | Tonight’s runs never got a PDF, so fit stayed unresolved |
| **C** | Open every related drawing from the file system / vault during Review. | Looks complete. | High | Slow, write-adjacent, the extractor’s “open nothing extra” rule |
| **D** | After assembly context exists, **offer** Create drawing / Improve drawing (layer 3). Uses the assembly brief from the last Review; does not invent limits the engineer did not confirm. | New feature. | High | Must not write a drawing in this build; Feature 001 forbids placing dimensions |
| **E** | When a sheet, limit, datum, or intent is missing, ask **one specific question** in the pane (reuse `request_evidence`, show it above Start here). Do not guess a fit class or a general tolerance. | Makes tonight’s ER-002 usable. | Low–medium | Questions must stay unanswered-as-unresolved |

**Recommendation:** **A + E now, D later.** B stays as a fallback. C is a no.

The efficient LLM feed is a **brief**, not the raw tree: the joints under review
(mates + holes + interference), the few sheets that govern those joints, then
questions for anything still blank. Do not resend every feature folder and every
annotation on every round. Feature 005’s compact-query work is the same idea.

**What this means for the model.**

- **The small assembly:** the two pin joints and the plate holes are in the dump. Without
  the part drawing, the reviewer cannot check fit, stack, finish, or thread callouts.
  It already asked for that package (ER-002) and left those checks unresolved. The
  model is only half-reviewed: geometry and RMS, not manufacture.
- **The big assembly:** 99 findings and still no drawing. A big assembly without sheets
  cannot become a drawing-improvement job; the model has no views or balloons to
  improve. Start here only showed five interference rows, so even the 3D issues
  are mostly unread (§5).
- **The part of the big assembly:** Standards said `no drawing graded`. If this part has no drawing,
  the honest next offer is “make a drawing from the assembly context we just
  learned” — after someone has reviewed the assembly that uses it, not from the
  Remodel tab’s no-seat banner. If a drawing exists and was simply not attached,
  that is the A gap, not a missing file.
- **Missing context:** an unanswered intelligent question must keep the suggestion
  unresolved. A guessed H7, a guessed title-block note, or a guessed view set is a
  false drawing, which is worse than no drawing.

**Recommended fix (owner):**

1. **U14 — attach drawings to a model/assembly dump** when they are already open or
   are the obvious sibling of a reviewed document. Record a gap when none are
   found. Pin: Review of the small assembly with its part drawing already open must put
   sheets in `package.json` and must not leave `drawing.manufacturing_inputs` as
   “phase did not run.”
2. **U15 — pane-visible questions** for the gaps that block manufacture (reuse
   ER-002’s intent: which drawing, which limits, press vs clearance, governing
   datum). One question at a time when possible. Unanswered ⇒ unresolved, never a
   default tolerance.
3. **U16 — later, not this build:** after an assembly Review has a brief, offer
   **Create drawing** (none exists) or **Improve drawing** (one does). That is
   ADR-001 layer 3. Do not implement it by writing views from the Remodel tab or
   by asking this seat to invent a drawing extractor.

Do not treat tonight’s ER-002 as a completed drawing review. Do not commit native
drawings or run folders.

---

## What the other machine should update

Priority is the Review tab’s session and density, then drawing context. Remodel copy
is honest enough to ship a wording change; it is not a new seat. Drawing
create/improve is a later feature.

| # | Kind | Change | Why |
|---|---|---|---|
| **U8** | Bug | On `document.changed` (path or configuration), clear or hide the previous review. Add an explicit Clear review control. Pin: review A, activate document B, assert A’s findings are gone and report buttons are disabled. | §1. Header and body disagree. |
| **U9** | Feature | Session chips (or equivalent) keyed by document + configuration + `chat_id`, so a later document does not destroy the earlier review. | §2. Normal night is more than one file. |
| **U10** | Bug / UX | Headline-only findings by default. Hide `observed` until Details. Collapse all. Start-here click must not force the fold open. | §3. The issue is unreadable as a list. |
| **U11** | Feature | Results \| Transcript swap: one view owns the pane. | §4. Stacked tiers still fight the 300 px strip. |
| **U12** | Feature | Findings index: all headlines, ranked, with “5 of N”. Do not raise `TOP_N` until that list exists. | §5. The big assembly hid 94 of 99. |
| **U13** | Copy | Remodel banner: no CLI in the pane. Same refuse. | §6. U4 worked; the sentence is still a dead end. |
| **U14** | Feature | Attach already-open or sibling part/assembly drawings to a model dump. Gap if none. Do not vault-walk. | §7. Tonight’s Reviews asked for sheets and had none. |
| **U15** | Feature | Show missing-context questions in the pane (drawing, limits, fit intent, datum). Unanswered stays unresolved. | §7. ER-002 was written and not usable as a conversation. |
| **U16** | Later | Offer Create drawing / Improve drawing only after an assembly brief exists. ADR-001 layer 3. Not this build. | §7. Manufacture output, not a Review-tab tweak. |

Do **not**: flip the pane lever-6 default; treat the Remodel banner as a probe
verdict; commit run folders; ask this workstation to implement the tabs or to
write drawings.

## Never

- Flip the pane lever-6 default from this packet.
- Treat the part's Remodel banner as a successful or failed remodel of that part.
- Start a review automatically when the document changes.
- Print the full ranking as twenty Start-here cards to “fix” top five.
- Invent a fit class, general tolerance, or view set when the drawing is missing.
- Implement drawing create/improve on this seat or from the Remodel tab.
- Commit run folders (they carry document paths).
