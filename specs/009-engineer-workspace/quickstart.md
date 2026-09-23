# Quickstart: Validating the Engineer's Workspace

**Feature**: `009-engineer-workspace` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

Scenarios 0 to 7 run **offline** on the development machine, with no SOLIDWORKS licence and no key:
the backend with pytest, the pane with the offscreen WebView2 suites. Scenarios 8 to 12 are marked
**[W]** and need the next workstation sitting: a licensed seat, the two recorded assemblies
(810-11249 and 830-02342) and, for Scenario 12, a provider key.

## Prerequisites

Everything from features 001 to 007, and from feature 008 at least its Setup (the committed replay
fixtures under `reviewer/tests/fixtures/replay/`, 008 T018), its family fold (008 T030, T032) and its
answer batch (008 T083-T085). Offline: `reviewer/tests/fixtures/replay/big-assembly/` (shaped like
the 830-02342 review, fictional throughout) and the pane fixture generated from it,
`extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json`.

```powershell
cd reviewer
$fx = "tests/fixtures/replay/big-assembly"
```

## Scenario 0: what must not move

```powershell
uv run pytest tests/unit/test_attention.py tests/unit/test_attention_record.py tests/unit/test_report_start_here.py tests/unit/test_report_tokens.py tests/unit/test_chat_checks_routes.py tests/unit/test_chat_standards_routes.py tests/unit/test_docstring_split.py tests/unit/test_prefix_stability.py -q
cd ..\extractor; dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~PageRuleScanTests|FullyQualifiedName~ReviewPageUsageLineTests|FullyQualifiedName~SharedAttentionScriptTests"
```

Expected: the ranking, the record and both check bodies unchanged (a `summary` key on none of them);
the report goldens byte-identical; the docstring and prefix pins unedited; no page script sorts or
compares; 008's usage line tests green unedited; the Review and check tabs still render identical
Start-here rows.

## Scenario 1 (US3): the summary of the big assembly, in Python

```powershell
cd reviewer
uv run python -c "from pathlib import Path; from swreview.report.session import load_session; from swreview.ir.loader import load_package; from swreview.report.attention import rank; from swreview.report.summary import review_summary; d=Path('$fx'); s=load_session(d/'session.json'); p=load_package(d).package; r=review_summary(rank(s), s, p); print(r.headline); [print(g.label, g.text, [(b.title, b.count) for b in g.by_goal]) for g in r.groups]; print(r.questions.text); print(r.not_loaded.text); [print(g.title, '-', g.state_label, '-', g.reason) for g in r.goals]"
uv run pytest tests/unit/test_review_summary.py tests/unit/test_review_goals.py tests/unit/test_review_summary_fixture.py tests/unit/test_review_words.py -q
```

Expected: "99 findings in 18 issues"; Decide 9 (Interference 6, Hole alignment 3), Fix 56, Verify 34;
"4 questions for you"; "3 of 89 parts not loaded"; nine goal lines (modelling practice is the ninth,
research R2.4), each with its state, the ones not reached with a few words; the tests green, including the owner's three labels pinned.

## Scenario 2 (US3): the summary in the pane

```powershell
cd ..\extractor
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~ReviewPageSummary|FullyQualifiedName~ReviewPageFindingGroup|FullyQualifiedName~ReviewPageContacts|FullyQualifiedName~ReviewPageNames"
```

Expected: the summary is the first block of Results, in the order of the Independent Test; the
modelling-practice cards sit in one shut group; the contacts in one shut list after the findings;
names in the Start-here meta; at 300 by 600 the headline, the three groups and the not-reached goals
are visible without scrolling (SC-001); a ranking with no summary renders exactly as before.

## Scenario 3 (US4): questions for you

```powershell
cd ..\reviewer
uv run pytest tests/unit/test_tools_session.py tests/unit/test_session.py tests/unit/test_events_schema.py tests/unit/test_usage_ledger_resume.py tests/unit/test_tool_payload.py -q
cd ..\extractor
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~ReviewPageQuestions"
```

Expected: `request_evidence` records the short form and refuses each over-long, blank, repeated or
unknown value naming it; old sessions re-dump byte-identically; the tool array pins regenerated once
for the short form (32 tools then, 35 since feature 010's three checks); the panel asks "Question 1 of 3", sends two answers and skips one in one `POST`, shows
the resume sentence before sending, and names the question a refusal was about.

## Scenario 4 (US5): Results or Transcript

```powershell
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~ReviewPageViews|FullyQualifiedName~ReviewPageEventStream|FullyQualifiedName~ReviewPageScale|FullyQualifiedName~ReviewPageNarrowLayout"
```

Expected: Results by default with no tool card, argument or token count; Transcript with every prose
block and tool call in order and a marker per finding; a follow-up answer pinned in Results without
switching; every finding of the fixture within two clicks (SC-006); 1,000 findings rendered within
the bound.

## Scenario 5 (US6): one review per model

```powershell
cd ..\reviewer
uv run pytest tests/unit/test_chat_review_routes.py tests/unit/test_review_snapshot.py -q
cd ..\extractor
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~ReviewPageSessions|FullyQualifiedName~ReviewHostTests|FullyQualifiedName~PaneActionsTests|FullyQualifiedName~RunPackageIndexTests|FullyQualifiedName~ActiveConfigurationWatch"
```

Expected: the live snapshot equals the builder's output and writes nothing; the disk route serves a
folder after a backend restart, read-only, and refuses anything else as an unknown review; the host
lists reviews only and forgets one; Show with a chat id resolves against that chat's package after a
check became latest; choosing a chip is one `GET` and no `POST`; returning to a document shows its
newest review; a configuration switch hides a review of another configuration.

## Scenario 6 (US7): plain words

```powershell
cd ..\reviewer
uv run pytest tests/unit/test_recording.py tests/unit/test_plain_words_fixture.py tests/golden -q
cd ..\extractor
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~ReviewPageDefaultViewScan|FullyQualifiedName~ReviewPageLabels|FullyQualifiedName~ReviewPageErrors|FullyQualifiedName~ErrorLabelsCoverTheHost|FullyQualifiedName~ReviewPageInjection"
```

Expected: titles whole and named (not yet: T061's title half, T062 and T065's fourth check are
open, so titles are still cut at 80 characters and keep component ids); the regenerated goldens
differ from before in `title:` values only; the default view holds no named component id, no raw status token, no check id outside a fold
and no error class name (SC-003); every error says what to do next.

## Scenario 7 (US7): Model check

```powershell
dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~ModelCheckPageTests|FullyQualifiedName~SharedCheckPageTests|FullyQualifiedName~StandardsPageTests"
```

Expected: the grade header names the unresolved rules by their statements, with the ids in a fold,
and no fraction; the Standards header unchanged; rule ids inside each rule's fold on both tabs.

## Scenario 8 [W]: the sitting's verdict (SC-007)

Review 810-11249 and 830-02342 through the pane. With the engineer, read the summary: do the Decide
lines name the decisions that were theirs, and do the goal lines name what the review did not reach?
Record their words in the sitting's handover.

## Scenario 9 [W]: ten seconds (SC-002, SC-001)

Show a non-developer engineer the 830-02342 summary for ten seconds; they say how many decisions are
theirs and which goals were not reached. Screenshot the docked pane at 300 by 600.

## Scenario 10 [W]: configurations and Show

With a finished review of a part and of an assembly, switch configuration: the review hides and
comes back. On the previous build, review A, Model check part B, press Show on an A finding and note
what it selects; on this build it selects A's entity.

## Scenario 11 [W]: a night of reviews

Review an assembly, a pin, a plate; each chip restores its review with the usage line unchanged.
Save Settings; a chip restores read-only with the reason. Remove a copied run folder; its chip says
it can no longer be restored and offers Remove.

## Scenario 12 [W] [K]: three answers, one turn (SC-004)

On a review with three open questions, answer all three in one send. `events.jsonl` holds three
`evidence.answered` events and one resumed turn; record the resumed turn's first round input beside
the pane's resume sentence.

## Regression gate

```powershell
cd reviewer; uv run pytest -q; uv run ruff check src tests
cd ..\extractor; dotnet build SwReview.sln -c Release; dotnet test SwReview.sln -c Release
```
