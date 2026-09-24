# smart_SW handoff — 2026-09-20 (pilot → owner)

**Location on the pilot machine:** `C:\Users\csorkness\smart_SW-handoff-2026-09-20`

You are picking this up with **no prior context**. This folder is what the
pilot seat learned after absorbing your 2026-09-20 handover (`e04c027`) and
running the reworked tabs on the small assembly.

**Do not treat this as a git branch to merge.** Findings packet only. The
workstation stays on `local` and does not push.

**This seat is done testing.** Do not send Task A2 / E / F, another Review,
or a resolved-pin pair back here. Build and verify on the development
machine. The punch list is below and in
`docs/pane-findings-2026-09-20.md`.

## Machine state

| Item | Value |
|---|---|
| Commit | `c36f183` (`local`, merge of GitHub `main` `e04c027`) |
| SOLIDWORKS | 2024 |
| Provider / model / effort | openai / `gpt-5.6-luna` / high |
| Last packet you already have | 2026-09-19 (Task A, lever 6 A/B, lightweight request) |

## What to read

1. `docs/pane-findings-2026-09-20.md` — the whole sitting, token table, and
   **What the other machine should update** (U1–U7). Start there.
2. `dumps/20260919-184136-…/` — the small assembly's Review run (hidden follow-up in
   `events.jsonl` after the first `session.ended`).
3. `dumps/20260919-184809-…-standards/` — the small assembly's later Standards run.

(The run folders' names end in the assembly's design number, which the repository no longer
carries: owner decision 11B, 2026-09-24.)
4. `logs/tool-service-20260919-184725.log` — Remodel-tab refusal
   (`remodel.probe_scope`).

## Headline

- **Review layout is broken after a session ends.** Start-here cards eat the
  pane. Finding Details open in a few-pixel sliver. Follow-up answers are
  written then hidden by `.transcript.folded .block`.
- **No token savings.** Same levers all off. Tonight’s review 1.54M / 38
  rounds vs this morning 1.22M / 32 (+27%). Follow-up +62k. CLI lever-6 on
  was 464k / 11; the pane never got that.
- **Lightweight warning is in the report, not on Review.** Badge clips to
  `Reviewing 4 compon…`. No popup by design.
- **Remodel tab is still “no remodel seat.”** Not Task F. CLI probes not run.
- **New feature ask:** under each Start-here item, the LLM says what the
  finding **means for this model** (findings §8 / U5). Check titles are not
  readable as issues.

## What you should update (owner machine)

| ID | Change |
|---|---|
| **U1** | Cap Start here; give the transcript a real min-height so Details are readable. |
| **U2** | Unfold / show follow-up answers (do not leave them in folded `.block`). |
| **U3** | Not-examined sentence on Review above Start here, not in the ellipsis badge. |
| **U4** | Remodel tab refuses before Start until a seat exists. |
| **U5** | LLM plain-language “what this means for this model” under each Start-here row and its finding card; same text in `report.md`. |
| **U6** | Attention-retry flake; IDimension string scan vs `RemodelProbe.cs`. |
| **U7** | Later: held-out package before any lever-6 pane default. Not this packet. |

Do not flip the pane lever-6 default. Do not treat tonight’s Remodel error
as a probe verdict. Do not commit run folders.

## Dumps included

Each folder is `package.json`, `session.json`, `attention.json`,
`report.md`, `events.jsonl` (plus `check.json` on Standards). Local paths
appear inside those files the way the extractor wrote them.

## Still absent

- API keys, pane settings, the standards profile.
- Task E resolved-pin pair, Task F CLI ledger, Model check tonight.
- Task B / C / D.
- Any further testing from this seat.
