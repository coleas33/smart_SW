# Workstation findings <date>

The results sheet of `docs/workstation-test-plan-2026-09-23.md`. The plan's step 1.4, once the
update has brought this file, copies it into the handover folder as `pane-findings-<date>.md`,
where the date is the handover folder's own date, the first day of the sitting. Fill it in there as
each step ends; step 6.4 finishes it and step 6.5 hands it over with the folder. Nothing in it is
ever pasted into a chat.

Documents by letter only (the list is `notes\documents.txt` in the handover folder). No vault path,
folder name, property name or value, sheet format or template name, and no key. A run folder is
written as its time stamp and letter (`20261001-101112-A`), never its name. From a D6 or D8 line of
a probe report, its id only: never a dimension's name, view, value or radius. From a Standards
probe report, a component's id only (`cmp:` and four digits), never its name, and no
configuration's or view's name. From a re-modeler probe run, no line that holds a path (the
command line, the `Wrote` line, the answers file's path) and no error's text.

| | |
|---|---|
| Days of the sitting | |
| Commit before the update (1.2) | |
| Commit after the update (1.4) | |
| Versions: git, dotnet, uv, WebView2 (1.4) | |
| SOLIDWORKS version and service pack (1.6) | |
| New machine (0.3): yes or no | |
| Registration (1.5): done or not needed | |
| Provider, model and effort (2.5), never the key | |

## Results

Each result is one word: `pass` (every pass condition the step gives for this task held), `fail`
(the step ran and a condition did not hold: quote the line that shows it in Observed) or `blocked`
(the step could not run, or the case it needs did not arise: name the step, letter or condition in
Notes, for example `blocked by 2.3: profile version 1`). A task spread over several rows passes
only if every row passed, fails if any row failed, and otherwise is blocked. Observed holds a count,
a report file name, a run folder's stamp and letter, or a quoted line: never a path or a name.

| Step | Task | Result | Observed | Notes |
|---|---|---|---|---|
| 1.3 | update, build and gates | | | |
| 1.6 | health checks 1, 2, 3, 6 and 7 | | | |
| 1.7 | 004 T142: FeatureWorks present and enabled, for the record | | | |
| 2.2 | 006 T100: the pane reads the placed profile | | | |
| 2.3 | 008 T101: the profile is version 3 | | | |
| 2.4 | 006 T100: the backend validates the profile (health check 4) | | | |
| 2.5 | the OpenAI key saved, the model and effort chosen | | | |
| 3.1 | 010 T103: mass overrides read on A and B | | | |
| 3.1 | 010 T104: Hole Wizard holes (provisional) | | | |
| 3.1 | 010 T105: model dimensions and annotations | | | |
| 3.1 | 010 T106: the 68 screws with their shank faces | | | |
| 3.1 | 006 T101: PROBE-1 and PROBE-3 on A and B, the Standards probe clean | | | |
| 3.1 | 006 T102: PROBE-2 on A and B, the three appearance kinds | | | |
| 3.1 | real files fingerprinted (the `fingerprint-before` line) | | | |
| 3.2 | 011 T062: D1 and D11 on C, gate log | | | |
| 3.2 | 011 T064: D11 on C | | | |
| 3.2 | 006 T103: C read in under 10 s, sheets and views | | | |
| 3.2 | 006 T105: no Show on drawing subjects; the probe files | | | |
| 3.2 | 006 T107: C graded, models graded once, nothing rebuilt | | | |
| 3.3 | 011 T063: probes D2, D3, D12 and D13 | | | |
| 3.4 | 011 T063: the review reads D-1 and D-2, not D-X, opens nothing | | | |
| 3.4 | 011 T068: the drawing compared; the seat validation named | | | |
| 3.4 | 008 T101: `check_standards` in the pre-run, `standards.release` in the report (health check 5) | | | |
| 3.5 | 011 T063: D3 on sheet 3, D12 out of date on the copy (items 1 and 2) | | | |
| 3.5 | 011 T063: D12 in detailing mode (item 3) | | | |
| 3.5 | 006 T107: a model not loaded is a gap and unresolved (item 3) | | | |
| 3.5 | real files unchanged after 3.5 | | | |
| 3.6 | 011 T064: D4, D5, D8 and D11 on F; preference 24 or 49 | | | |
| 3.7 | 011 T065: D1, D6, D7, D9 and D10 on G, counts against yours | | | |
| 3.8 | 011 T066: every named callout tied to its hole, unit and decimals | | | |
| 3.9 | 011 T077: D14 with J's drawing closed, then open | | | |
| 4.1 | 008 T103: the small assembly's input tokens | | | |
| 4.1 | 009 T079: the small assembly's summary, the engineer's words | | | |
| 4.1 | 007 T059: the Start here panel against `report.md`'s | | | |
| 4.2 | 009 T080: the ten-second read | | | |
| 4.2 | 009 T080: the 300 by 600 screenshot | | | |
| 4.2 | 008 T102: the big assembly's input tokens, groups judged | | | |
| 4.2 | 010 T107: contacts apart, checks first, no model round on them | | | |
| 4.2 | 010 T106: B's run folder for the engagement count | | | |
| 4.2 | 009 T079: the big assembly's summary, the engineer's words | | | |
| 4.3 | 008 T104: the two timings | | | |
| 4.3 | 008 T104: Retry | | | |
| 4.4 | 009 T081: configuration switch on a part and an assembly | | | |
| 4.5 | 009 T083: chips, the restart, the deleted folder | | | |
| 4.5 | 007 T060: A's review timed, its baseline in `session.json` | | | |
| 4.6 | 011 T067: the two questions, at most four, the brief | | | |
| 4.6 | 009 T084: three or more answers in one send | | | |
| 4.6 | 011 T077: the pane half, switch off | | | |
| 4.6 | 011 T101: parts 1 and 3, a candidate left closed | | | |
| 4.7 | 011 T101: parts 2, 3 and 4, a candidate opened first | | | |
| 5.1 | Model check on J | | | |
| 5.1 | 007 T059: Start here above the chips on Model check, against `report.md`'s | | | |
| 5.1 | 004 T003: Model check packages of the owner's parts P-1 to P-5 | | | |
| 5.2 | Standards on J and on A | | | |
| 5.2 | 007 T059: Start here above the chips on Standards, against `report.md`'s | | | |
| 5.3 | Remodel leaves J unchanged | | | |
| 5.4 | 008 T106: the live Gemini test | | | |
| 5.5 | 009 T082: Show before and after the fix | | | |
| 5.6 | 004 T033: PROBE-1, the "Cannot reorder" box with the flag clear and set | | | |
| 5.6 | 004 T034: PROBE-3 and PROBE-4, the reorder and folder contiguity | | | |
| 5.6 | 004 T035: PROBE-2, the equation unit | | | |
| 5.6 | 004 T036: PROBE-6, PROBE-7 and PROBE-21, the equation manager | | | |
| 5.6 | 004 T037: PROBE-12 and PROBE-13, the tag and the copy of an open part | | | |
| 5.6 | 004 T038: PROBE-5, PROBE-9, PROBE-10, PROBE-11 and PROBE-20 | | | |
| 5.6 | 004 T039: PROBE-8, the tolerance calibration | | | |
| 5.6 | SOLIDWORKS's three options as they were before the probes | | | |
| 6.0 | real files unchanged at the end | | | |
| 6.1 | no key in a file (first audit) | | | |
| 6.2 | the exports | | | |
| 6.3 | the evidence zipped | | | |
| 6.5 | no key in a file (second audit) | | | |
| 6.6 | checkout clean, on main, no local commit | | | |

## What each step recorded

### 1. Update and health

### 2. Profile and key

### 3.1 Dumps and the Standards probe

### 3.2 A multi-sheet drawing

### 3.3 to 3.5 Discovery, the review of D, views out of date

### 3.6 to 3.8 Precision, callouts, the named callouts

### 3.9 The read-only open

### 4.1 and 4.2 The two recorded assemblies

### 4.3 to 4.5 Retry, configurations, chips, the timing of A's review

### 4.6 and 4.7 Drawing questions and the confirmed candidate

### 5. The other tabs, the Gemini test, the older build

### 5.6 The re-modeler probes

### 6. Handoff

## What to look at first next time
