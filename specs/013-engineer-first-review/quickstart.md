# Quickstart: Engineer-First Review

**Feature**: `013-engineer-first-review` | **Date**: 2026-09-26 | **Plan**: [plan.md](plan.md)

How to see each story work, with no licence (Scenarios 1 to 8) and at the next sitting (Scenario 9).
Every command runs from `reviewer/` unless it says otherwise. Every fixture is fictional; the
sitting-shaped one is `tests/fixtures/sitting/small-assembly/` (tasks T012). Expected results name
the contract that defines them rather than repeating it.

## Prerequisites

- Features 001 to 011 on `main`; `uv sync` done; the tokenizer available
  (`SWREVIEW_REQUIRE_TOKENIZER=1`).
- For the C# and page scenarios: the .NET build tools
  (`dotnet build extractor/SwReview.sln -c Release --nologo -v q` from the repository root).
- For the replay gate: the owner's recording mapping and denylist on this machine (008
  `contracts/replay.md` section 8); without them the replay's recording checks skip, saying why.

## The gates

```powershell
$env:SWREVIEW_REQUIRE_TOKENIZER = "1"
uv run pytest -q -p no:warnings -o addopts="" -m "not live"
uv run ruff check src tests
```

Both green before every commit; the tracked-files guard and the standards census are part of the
first.

## Scenario 1: A version 4 profile, and the upgrade helper (US1)

```powershell
uv run swreview profile upgrade ../config/standards.example.yaml --out $env:TEMP\fict-v4.yaml
```

Expected (once the example is itself version 4, T014, the example is refused as "already version 4";
run the helper on `tests/fixtures/standards/profile-a.yaml` from before T014, or on any version 3
file): the output is written, the input untouched, the `part_roles` section present with every
skip-list entry commented under the proposal comment; stdout carries only the path and its sha256
(`contracts/part-roles-profile.md` section 5). A version 1 or 2 input is refused naming the sections
it lacks. Loading a version 3 file that carries `part_roles` is refused naming the section.

## Scenario 2: Bought parts out of the grading (US1)

```powershell
uv run swreview review tests/fixtures/sitting/small-assembly --provider fake --pane-defaults `
  --standards-profile tests/fixtures/standards/profile-a.yaml --out $env:TEMP\sitting-review
```

Expected in the run folder's `session.json` and `report.md`: no `rms.*` or `hygiene.*` finding on the
vendor pin; `coverage.prerun.bought_parts` names it once, its reason naming "a bought-parts folder" among its signals; one open
request with `allow_text: true` and `source: code` listing the unclear part; the unclear part's RMS
and hygiene findings carry "may be a bought part"; the report's "Bought parts" section
(`contracts/part-roles.md` sections 6 to 8). With `--standards-profile` omitted: only Toolbox skipped,
no question, the bought-parts line says why. Answering "All bought" through the batch route (the
pane, or `test_answer_batch_roles.py`'s script) withdraws the unclear part's findings with
`finding.withdrawn` events before the resumed turn (section 9).

## Scenario 3: The grouped list (US2)

```powershell
uv run swreview attention $env:TEMP\sitting-review
uv run pytest -q tests/unit/test_finding_groups.py tests/unit/test_attention.py
```

Expected: `swreview attention` still prints the five-row Start here for the model, with no pass in it;
`report.md` carries "Findings by type" in the seven groups' order with passes only under "Checked, no
issue" (`contracts/grouped-list.md` sections 1, 3 and 6). On the pane: open the big-assembly pane
fixture in the page tests (`dotnet test --filter ReviewPageAttentionPanelTests`) - groups in the
supplied order, Modelling practice collapsed, no Start here and no "Show all".

## Scenario 4: No vault question, no re-ask (US3)

```powershell
uv run pytest -q tests/unit/test_provenance_closure.py tests/unit/test_tools_session.py -k "provenance or already or covering"
```

Expected: every session carries one `provenance` row, checked by code; `request_evidence` and
`mark_coverage` on `provenance` answer `closed_by_code` and record nothing; the sitting's eight
question calls replayed with fictional ids give `already_answered` for the provenance and fit re-asks
(and, after US4, `closed_by_code` for the drawing requests) (`contracts/re-ask-guard.md` sections 1 to
3). The opening brief of Scenario 2's run prints no `vault_version=?`.

## Scenario 5: Drawings that follow the seat (US4)

```powershell
uv run pytest -q tests/unit/test_drawing_context.py tests/unit/test_confirmed_drawing_read.py tests/unit/test_bridge_client.py
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "BridgeDispatcherTests|PackageAppenderTests"
```

Expected: a host with the switch off answers `drawing_read: "open_only"`; the sitting-shaped package
(an assembly and the custom plate sharing a stem, one candidate file) gives no drawing question and
one instruction line "Open … in SOLIDWORKS, then press Review again with … active"; the vendor pin is
`bought`, no candidate; with `opens_closed`, one question names the file once and a confirmation makes
one read, recorded for both documents; a model drawing request on the pin and the plate is answered
`closed_by_code` with both states (`contracts/drawing-capability.md`). In Scenario 2's run folder the
summary's drawings line carries the instruction.

## Scenario 6: Sources and the basis line (US5)

```powershell
uv run pytest -q tests/unit/test_answer_basis.py tests/unit/test_finding_explanations.py
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "ReviewPageLabelsTests|ReviewPageEventStreamTests"
```

Expected: in Scenario 2's `events.jsonl`, every `text.done` carries `basis`; a turn with no evidence
call reads "No evidence was read for this answer: this is general guidance." plus "No drawing was read
in this review."; `report.md` marks model findings "Source: AI guidance" and the evidence table has a
Source column; no "No model explanation" line anywhere; an explanation batch with one oversized item
keeps the rest and logs the rejected id and rule (`contracts/sources.md`).

## Scenario 7: Answer-turn tokens, and lever 14 (US6)

```powershell
uv run pytest -q tests/unit/test_finalize_closeout.py tests/unit/test_openai_prior_reasoning.py tests/unit/test_replay_lever_14.py
uv run swreview benchmark replay tests/fixtures/replay/big-assembly --standards-profile ../config/standards.example.yaml
uv run swreview benchmark replay tests/fixtures/replay/big-assembly --lever drop_prior_reasoning --standards-profile ../config/standards.example.yaml
```

Expected: one `coverage.closeout` row written by code per session; every coverage result carries
`open_items`; the two replays (pane defaults, the replay's default) lose no finding, and the second prices the follow-up round lower by the
earlier turn's recorded reasoning tokens, reported as an estimate (`contracts/tokens.md` sections 1,
2 and 4). T125 records the decision in feature 005's `levers.md`.

## Scenario 8: Readings that match SOLIDWORKS (US7) and the probe 1 watchdog

```powershell
uv run pytest -q tests/unit/test_standards_drawing_revision.py tests/unit/test_feature_nodes.py tests/unit/test_rms_part_rules.py
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "DrawingDumperTests|RemodelProbeExecutorsTests|RemodelProbeWatchdogTests"
```

Expected: a sheet whose enumeration lacks its own view still yields its revision table and bill of
materials from the per-sheet list; a sheet with the cross-check gap makes the revision check
unresolved, never "not found"; on the absorbed-sketches fixture each sketch is named once and the
planner's output is byte-identical; probe 1's tests pass under a starved thread pool, the flag-set
attempt first (`contracts/readings.md`).

## The replay gate (every story that moves what the model reads)

`contracts/tokens.md` section 5: regenerate the three fixtures with 008 `replay.md` section 8's
commands, then `uv run python tests/fixtures/pane/generate_pane_fixture.py --write`, replay every
configuration of section 9's latest row, hold the absolute rule and the 3, 2 and 0 contacts, and
record the re-measured row.

## Scenario 9: At the next sitting (tasks T141 to T144, T153)

1. **Profile**: `swreview profile upgrade %LOCALAPPDATA%\SwReview\standards.yaml --out <new file>`;
   the owner confirms `part_roles`; validate; point the pane at it (T141).
2. **Probe D14** (test-plan step 3.9); with it passed and 011 T077 committed, `ping` answers
   `opens_closed` (T142).
3. **The small assembly** (step 4.1): drawing closed first, then open; answer as on 2026-09-26; one
   follow-up; `Show-ReviewFacts` - no modelling or hygiene finding on the vendor pin, no vault question,
   no re-ask, the grouped list, every label and basis line, at most 400,000 input tokens (T143).
4. **Standards on the plate's open drawing**: revision table and bill of materials read, no "no
   revision table" warning; the export-control check on a known carrier and a known non-carrier
   (T144).
5. **Lever 14 against the real endpoint** (test-plan step 2.7): `tests/live/test_openai_live_prior_reasoning.py`
   with the key the pane stores; `1 passed` means the endpoint accepts the request without the
   fallback of T152 (T153).

## Results

*(T140 records the no-licence results here; the seat's results go to the sitting's findings document
and the test plan's results sheet.)*

**Run 2026-09-27 on the development machine, no licence, at `main` after the review fixes of that
day** (every command from `reviewer/`, outputs under `%TEMP%`; SOLIDWORKS never started):

| Scenario | Result |
|---|---|
| 1 | pass. The example profile, version 4 since T014, is refused "the profile is already version 4" (exit 1). A version 3 copy of fictional profile A upgrades: exit 0, one line with the path and `sha256:`, the output `version: 4` with a `part_roles` section and the library lists as commented lines, the input unchanged; a second run without `--force` is refused naming the existing file; a version 2 input is refused naming `drawing`; a version 3 file carrying `part_roles` is refused naming the section. Since the review of 2026-09-27, the unfilled output classifies exactly as its version 3 input (`test_cli_profile_upgrade.py`) |
| 2 | pass. `swreview review tests/fixtures/sitting/small-assembly --provider fake --pane-defaults --standards-profile tests/fixtures/standards/profile-a.yaml`: 17 findings, none `rms.*` or `hygiene.*` on the vendor pin; `coverage.prerun.bought_parts` names the pin once among three bought documents, its reason beginning "a bought-parts folder"; one request, `allow_text` true, `source` code, listing the unclear spacer; each of the spacer's six RMS and hygiene findings carries "may be a bought part"; `report.md` has "Bought parts". With no profile: "Bought parts were not told apart: no standards profile is attached", no question. The "All bought" regrade is `test_answer_batch_roles.py` (green) |
| 3 | pass. `swreview attention` prints five rows, no pass (the rms family row first); `report.md`'s "Findings by type" lists the seven groups in order, Interference to Mass and material, above "Findings"; `test_finding_groups.py` and `test_attention.py` 100 passed; `ReviewPageAttentionPanelTests` 17 passed |
| 4 | pass. The provenance, re-ask and covering cases 23 passed; the run of Scenario 2 holds one `provenance` row; its opening brief prints `role=` on each of the six documents and no `vault_version=?` or `local_modified=?` |
| 5 | pass. `test_drawing_context.py`, `test_confirmed_drawing_read.py` and `test_bridge_client.py` 165 passed; `BridgeDispatcherTests` and `PackageAppenderTests` 90 passed. Scenario 2's run, with no bridge (`drawing_read` `none`), asks no drawing question and its drawings line is the instruction "Open {stem}.SLDDRW in SOLIDWORKS, then press Review again with {stem}.SLDASM active", with the fixture's fictional stem (the assembly and the plate share the one candidate file) |
| 6 | pass. `test_answer_basis.py`, `test_finding_explanations.py` and `test_runner_answer_basis.py` 61 passed; `ReviewPageLabelsTests` and `ReviewPageEventStreamTests` 30 passed. Scenario 2's `text.done` carries "Based on 8 results read for this answer. No drawing was read in this review."; its `report.md` has the evidence table's Source column and no "No model explanation" line (it has no model finding to mark "Source: AI guidance"; `test_sources_labels.py` pins that line) |
| 7 | pass, with the expectation amended. `test_finalize_closeout.py`, `test_openai_prior_reasoning.py` and `test_replay_lever_14.py` 40 passed. Since T125 lever 14 is a pane default, so the two replays of the big fixture are the same run: 662,903 requested, no recorded finding lost, the follow-up round 19,899. With lever 14 off (`--no-pane-defaults --lever prerun_checks --lever withhold_prerun_tools --payload-slimming --history-pruning`) it is 665,795, the follow-up round 22,791: the estimate this scenario describes |
| 8 | pass for what landed. `test_standards_drawing_revision.py`, `test_feature_nodes.py` and `test_rms_part_rules.py` 129 passed; `DrawingDumperTests`, `RemodelProbeExecutorsTests` and `RemodelProbeWatchdogTests` 299 passed. The absorbed-sketches expectation (each sketch named once in the RMS and Standards sketch findings) waits for T132-T133, backed out of `main` pending the owner's question T134-Q1; the planner's byte-identical output (T130-T131) holds |
