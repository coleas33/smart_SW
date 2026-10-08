# Feature Specification: Design-Review Eval

**Feature Branch**: `014-design-review-eval` (branched from `main` at be01974)

**Created**: 2026-09-28. **Revised**: 2026-09-29, after a four-lens review, three re-reviews and owner decisions 17A to 27A; 2026-09-30, owner decision 30A; 2026-10-06, owner decisions 33A to 36A, from the owner's review of the plan.

**Status**: Draft. Decisions 1A to 30A and 33A to 36A are the owner's (research §1, which also records 31A and 32A, the form of the owner's review of the plan on 2026-10-06). Defaults D1 to D17 (D15 now 17A) are reversible, with their alternatives in research §5.

**Input**:
- The 2026-09-28 audit of `benchmark run`, `score` and `compare` (research §2): `cover-blind-tap` scores 0 of 2 for any reviewer; sibling rules are credited; a contradicted correct condition is no false alarm; `rms-part` measures argument-free checks; the pane's configuration cannot run; stopped reviews score as finished; a provider error stops the set.
- Anchors R-1 to R-8 (research §3), from engineers' debriefs kept outside this repository and an owner's ruling.

## Owner Decisions

| # | Date | Decision |
|---|---|---|
| 1A | 2026-09-28 | The eval stays on the product's providers, OpenAI (default) and Gemini. Any future judge is OpenAI or Gemini, never Claude. |
| 2A | 2026-09-28 | The flow under evaluation is the agentic design review of a package, graded against answer keys. |
| 3A | 2026-09-28 | The first study is the Task Pane defaults against all levers off. The pane defaults are checks-first pre-run, withheld pre-run tools, payload slimming, history pruning, dropped prior reasoning, and parallel tool calls. The headline is recall on defects only the model can find, plus false alarms. Recall on defects code finds is a regression guard. |
| 4A | 2026-09-28 | The benchmark scorer is fixed in place, tests first. User Story 1 lists the behaviours. |
| 5A | 2026-09-28 | The cases are a committed seeded-case generator plus a private held-out slice of real designs, whose keys the owner writes and which stays outside the repository. |
| 6A | 2026-09-28 | `benchmark run` can run the pane's configuration through the resolver `review` already uses, and records it (User Story 2). |
| 7A | 2026-09-28 | The anchors are the eight real cases R-1 to R-8 (User Story 5). The big assembly's three analyst-found defects are also taken as real: M4 screws in M5x0.8 tapped holes, a 0.75 mm dowel offset, and interference groups of about 250 mm³. |
| 8A | 2026-09-28 | The answer key also grades forbidden findings, expected coverage, and question rules, all by code, with no judge (User Story 3). |
| 9A | 2026-09-28 | Cases carry scripted engineer answers, played through the answer path the pane uses. The final state is graded (User Story 4). |
| 10A | 2026-09-28 | The set must detect a 10-point drop in model-judgement recall: about 34 held-out model-produced defects at 3 repetitions. |
| 11A | 2026-09-28 | The planning pass's 23 lower-level choices take their recommended defaults (research §4). Five change behaviour a user would notice: five origin buckets rather than three; a scorer version that refuses scorecards scored under the old rule; `review --pane-defaults` also running the explanation pass; explanations held equal, and stated, on both arms of the pane study; and the pane study's decision row guarding the call counts of the two checks no rule enumerates. |
| 12A | 2026-09-28 | Delivered as this feature, in order: the scorer, then parity with the pane, then the key extensions and scripted answers, then the generator, the report and runner robustness. Each part is test-first. |
| 13A | 2026-09-29 | Every known defect states its expected status. An unresolved finding on a defect expected demonstrated or suspected is counted as *flagged below expected*, in its own column, and does not count toward headline recall, so a change that makes the model hedge shows as a loss. 4A's rule stays: an unresolved finding on a defect expected unresolved credits it as flagged and counts toward recall; a demonstrated or suspected finding on such a defect credits it and counts as a status mismatch. |
| 14A | 2026-09-29 | 34 held-out model-produced defects is the floor, not the plan. Before the paid pane study, a small paid pilot of the off arm measures each held-out model-produced defect's detection rate and how the defects of one package move together. Repetitions grow first, then cases, until simulated studies detect a true 10-point drop in model-judgement recall at least 80% of the time and call identical arms a loss at most 5% of the time. The owner approves the resulting size and cost at the cost gate; 6 to 10 repetitions are likely if detection rates are spread. |
| 15A | 2026-09-29 | Held out is decided per graded item. Anything the prompt or checklist was written around, meaning every anchor R-1 to R-8 behaviour and every debrief item, is tagged *tuned-on* and graded as a regression guard, never counted in held-out recall. Everything else in a case may be held out, including the big assembly's three analyst-found defects. Each held-out item records the prompt and checklist digests it was held out against, and loses held-out status in the same commit as a prompt or checklist change that cites it. |
| 16A | 2026-09-29 | Producer is decided per defect, in its own package. Model-produced: fits and axial stacks the model must set up, drawing readings, and fastener or alignment joints whose geometry is deliberately withheld so that only a check the model sets up can find them. Code-produced regression guards: interference, the joint map's fastener and alignment defects, and any defect a pre-run check or a check with no arguments can find from the package's evidence. The generator records, for each model-produced defect, which evidence it withheld. |
| 17A | 2026-09-29 | Only model-origin false alarms decide the pane study's verdict: the model's own findings and those of checks the model chose to call. Pre-run and regrade (code) false alarms are shown with a paired interval and named, never decide. (Was default D15.) |
| 18A | 2026-09-29 | The fit and axial-stack call-count guard (11A, PP-8) is shown with a paired interval and named when the interval excludes zero, but never decides. |
| 19A | 2026-09-29 | A product change: every fastener-joint and hole-alignment result records its fastener and hole ids (the joint's references) on every path, unresolved results included, so a finding points at the exact joint (constitution Principle IV) and the scorer matches the exact joint, not only shared parts; fixtures regenerate with it. |
| 20A | 2026-09-29 | Under 17A, a call of a tool the pre-run also calls, or of a check with no arguments, is code origin whoever makes it: it gives the same findings whoever calls it. Only checks the model sets up with its own arguments (configured checks) are model origin. |
| 21A | 2026-09-29 | "Identical arms" for the 5% bound means the model behaves the same in both arms while code-produced defects behave as each configuration does. Both arms at the off arm's code rate is printed as a stress case, not bounded. |
| 22A | 2026-09-29 | Repetitions grow first, up to a cap of 10, then cases. The owner may set another cap at the cost gate. |
| 23A | 2026-09-29 | The private real-design slice is its own study, with the real profile and its own row, reported beside the pane study's verdict and never deciding it. |
| 24A | 2026-09-29 | One fully clean twin per core case (research §8.11's rule B): about 47 packages, 94 × R paid reviews per study; no key-format change. |
| 25A | 2026-09-29 | A held-out item's stamp digests the system prompt, the checklist and every registered tool description the model reads; the item loses held-out status in the same commit as a change to any of them that cites it. |
| 26A | 2026-09-29 | A review that overflows the model's context window (OpenAI's `context_length_exceeded`, Gemini's input-token limit) is a behavioural stop, class `provider_stop` with its reason recorded, never an infrastructure failure. |
| 27A | 2026-09-29 | The paid pilot is 3 off-arm repetitions over the whole committed pane set. |
| 28A | 2026-09-29 | The committed study and pilot folders carry their event streams gzip-compressed (`events.jsonl.gz`), with each stream's sha256 digest recorded. The `.gitignore` exception targets the compressed form; readers (re-scoring, the report) read it transparently; the plain `events.jsonl` stays the working form while a run writes. |
| 29A | 2026-09-29 | The tasks are generated now; the owner reviews the plan and the tasks together before implementation. |
| 30A | 2026-09-30 | Held-out core cases take no answer turn (research §9.7, question 8, option B). Every verdict names dropped reasoning as a setting it does not test, and the anchors show it with paired intervals. |
| 33A | 2026-10-06 | The gates of slices 1, 2 and 6 re-run the add-in's page and host tests and replay the recorded pane sessions, which must show the pane's behaviour unchanged but for the evidence fields the plan allows. After slice 6's gate and before any paid run, one smoke review of the small assembly in the Task Pane on the pilot workstation, written into the workstation handover; no paid study until it passes. |
| 34A | 2026-10-06 | One atomic writer: the product's three older atomic writes (the attention record, the tokenizer vocabulary and the package that a live interference run updates) move onto the eval's writer, each with a failing-first test. The attention record's bytes become LF on Windows, a change no reader sees. |
| 35A | 2026-10-06 | A paid smoke run before the pilot (quickstart P0): two packages, an anchor with a case file and a core case, one repetition per arm, about four reviews; every row is read (served model, usage, priced cost, run status, answer log, finding origins, transcript) and any wiring is fixed before the pilot. One live test, run only on demand, drives one real benchmark attempt end to end. |
| 36A | 2026-10-06 | The cost gate prints the approved study's projected wall clock, from the smoke run's and the pilot's review times, at the chosen concurrency. `benchmark run --jobs N` (default 1) reviews up to N packages at once, each in its own folder, the run's shared records never interleaved; N is recorded and is not a must-match field, since it changes nothing that is measured. |
| 37A | 2026-10-07 | The matcher's family rows that slice 1 tests (tasks.md T022) read on `fastener.head.*`, a family a known defect or a correct condition may hold, since AK-4 refuses `fastener.*` on both; the contract's own `fastener.*` rows are tested on a forbidden entry, where that family may stand (T083). |
| 38A | 2026-10-07 | The one event-line reader ends a line where text mode ends it, a lone carriage return included, exactly as at `be01974`, while a line cut inside a multibyte character still ends the replay at that line and is reported, never raised. |
| 39A | 2026-10-07 | The `joint-unknown-role` check golden stays at schema 1.3.0 inside the golden gate, which is not widened, so it carries no tolerance source (every source is a 1.5.0 member): it pins `hole.nominal_alignment`'s unknown-role result naming every instance of the joint and the stack check's "no tolerance source" skipped row, and `hole.position_stack`'s unknown-role result is pinned by a unit test. |
| 40A | 2026-10-07 | `check_interference_group` cites its own step on every finding, as on every contact, so a pre-run interference finding reads as the pre-run's and a model-called one as a code-only call, never as model origin for want of a step. The big-assembly replay fixture and the pane fixture are regenerated, and the recorded input moves by the one step id the model reads per interference finding. |
| 41A | 2026-10-07 | The scorer's end-to-end test of origins (tasks.md T032, test 5) takes its code-only-call findings from the same package's off arm, where the model's scripted part and mass checks write them; the checks-first review shows pre-run and configured-check findings, and a guarded repeat of the hygiene check adds nothing. |
| 44A | 2026-10-07 | The too-small-set override is a must-match field of a study, so both arms carry it or neither does: the compare test of a study carrying it has both arms carry it, its decision row still refused for it, and a study one arm of which carries it alone is refused at the study. |
| 47A | 2026-10-08 | When a study is refused for a field its runs record differently, a value a record lacks reads "not recorded" only for the fields whose absence can only mean a record an older build wrote, named in one list beside the exemptions: the answer-turn bound now, the robustness slice's clock, retry and jobs fields later. Every other field's value is quoted as it is, since its empty value means something in a current record (no profile, or a commit git could not name). |
| 48A | 2026-10-08 | A package id equal to `attempts` in any case is refused before any review: its folder would be the run's attempts folder, and Windows and macOS fold case. |
| 54A | 2026-10-08 | The case vocabulary gains a fourth committed list, the words of the six Resilient Modeling group folders' names (ref, construction, core, detail, modify, quarantine), so a generated custom part's compliant tree passes the names check; a test holds the list equal to the RMS type table's groups. |
| 55A | 2026-10-08 | `coaxiality_undrawn` is treated like a drawing kind: with no tolerance drawn its call cannot confirm aligned holes, so its twin's condition carries no correct call, which the validation then never asks to confirm; the condition is still keyed and still catches a false alarm. |
| 56A | 2026-10-08 | A generated drawing dimension may carry its nominal as the drawing writes it ("3.0"), so `kalo-fit-1`'s sheet reads "2X Ø3.0 +0.010/0" over "Ø3.0 +0.020/+0.014" exactly as its anchor pins them. |

Refinements of earlier rows:
- 13A completes 4A's status rule; 15A replaces the first draft's per-case held-out rule; D9 extends 11A's five origin buckets to seven.
- 14A makes 10A's 34 a floor and puts the simulator (User Story 8), pilot and cost gate after 12A's robustness, before the paid study.
- 17A narrows 3A's "plus false alarms" to model origin; 20A reads its "checks the model chose to call" as configured checks, and D15 keeps tuned-on hits out (15A).
- 18A narrows 11A's PP-8: the fit and axial-stack call counts are shown, never deciding.
- 21A and 22A confirm 14A's reading of identical arms (D17 adds the second 5% bound) and its repetition cap (FR-055); 23A keeps 5A's private slice out of the verdict (FR-056).
- 25A extends 15A's stamp to tool descriptions; 26A extends D2's behavioural stops to a context overflow; 24A settles FR-028's twins and 27A the size of 14A's pilot.
- 30A settles CS-9 against 9A: lever 14 is observed on the anchors only.
- 33A to 36A, from the owner's review of the plan, change no requirement: 33A adds checks of the pane to 12A's gates, 35A puts a smoke run before 14A's pilot and confirms SC-008 there first, 36A adds concurrency to `benchmark run` and a wall clock to 14A's cost gate, and 34A extends the eval's one atomic writer to the product's three older copies.

### Defaults (reversible; research §5)

| # | Default |
|---|---|
| D1 | The pane study's verdict comes from paired rules and worst-case guards (17A, 18A, D17). |
| D2 | Infrastructure failures are excluded and re-run; behavioural stops are the arm's own outcome (D16). |
| D3 | An unscripted question gets nothing, as the pane's Skip. |
| D4 | One question matcher, by checklist item and ids, counting the model's request calls. |
| D5 | Arms differ only in levers and model view; the pane baseline is its own row; a bad profile stops only the benchmark. |
| D6 | Expected coverage is read with the product's own report reader. |
| D7 | Key validation and locations; runs never read keys; held out is recorded once, in the keys. |
| D8 | Two reachability checks per case, in a validation over the committed set; `cover-blind-tap` regenerated. |
| D9 | Seven finding origins; sessions record that they carry origin marks. |
| D10 | A committed, dated price table; no price or no usage gives cost unknown. |
| D11 | Runs record the system prompt and opening message. |
| D12 | Standards findings stamp the profile's digest and file name, never its folder. |
| D13 | Fictional builders only; identifier tests where the owner's lists exist. |
| D14 | Builder reuse, one ingested-sheet builder, scorer versioning, answer-turn bound, withdrawn forbidden hits, OpenAI first, tokenizer, acceptance suite, terms, stale facts, complexity tracking. |
| D15 | Now owner decision 17A. Kept here: hits on tuned-on items never decide (15A); code-only calls' false alarms are code origin (round 3). |
| D16 | A review that reaches the answer-turn bound is completed and graded, counted as bound-reached. |
| D17 | No control-stability rule; any deciding rule's loss wins, below the floor too (round 3); the cleared guard decides only if the simulation allows; the 5% bounds are simulated on the whole verdict. |

## Terms

- **Credited**, **flagged**, **flagged below expected**, **status mismatch** and **cleared** are defined by User Story 1's table. **Detected**: credited or flagged. **Missed**: no finding matched. Cleared is Principle I's worst outcome.
- **Producer**: code or model, decided per defect in its own package (16A).
- **Judgement family**: a check family in which the set plants defects: fastener (fastener and alignment joints), fit and axial stack, interference, drawing, part role. A family is not a producer.
- **Held out** or **tuned-on**: every graded item's tag (15A, FR-031).
- **Regression guard**: a graded item reported beside the headline, never in held-out recall: every code-produced defect (3A) and tuned-on item (15A). In the pane study one decides only through FR-045's guards; otherwise it is shown with paired intervals.
- **Completed repetition**: one that ended in neither an infrastructure failure nor a behavioural stop. Reaching the answer-turn bound is completed (D16).
- **Model-judgement recall**: the headline (3A): over held-out model-produced defects, the mean detection rate, each defect's rate being the share of its package's completed repetitions that detected it.
- **Code-only call**: a call of any tool the pre-run calls, or of a check with no required parameter, whatever arguments are passed and whoever makes it (16A, D9). A **configured check** is any other check call the model made.
- **False alarm**: a demonstrated or suspected finding that credits no known defect, including one that contradicts a correct condition or hits a forbidden entry; at most one per finding. It is of **model origin** when the model wrote it or a configured check did; a code-only call's is code origin (16A, 17A).
- **Clean twin**: a copy of a core case with every planted defect removed, each removal keyed as a correct condition (24A).
- **Oracle review**: the key's expected findings, coverage and requests fed to the scorer. **Null review**: a review that records nothing. **Correct-reviewer check**: a scripted review using the real tools as a correct reviewer would.
- **Identical arms**: the null of the 5% loss bound: equal model-judgement detection, clearance, behavioural-stop and model-origin false-alarm rates in both arms; code-produced defects detected as each configuration does (the on arm's pre-run on every run, FR-054; the off arm at the pilot's rate). Both arms at the off arm's code rate is a printed stress case, not bounded.
- **Drop shapes**: two spreads of a true drop in mean detection over held-out model-produced defects: **proportional**, each defect falling by the drop times its off-arm rate over the mean rate; **room**, equal shares to the defects with a rate above 0, each capped at its rate, the remainder re-shared among those still with room. Power is the recall rule's on the main figure at a 10-point drop, under the lower of the two.
- **Noise floor**: the smallest true drop in model-judgement recall detected with 80% power (drop shapes) in this study, found by simulation with the recorded seed (about 2.8 standard errors) and printed with the verdict.
- **Pane defaults**: the six settings 3A names (four levers and two model-view settings). `--pane-defaults` also turns the explanation pass on (FR-015); the pane study instead holds it equal and stated on both arms (PP-2).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Scorer Credits Only What Was Actually Found (Priority: P1)

A finding credits a known defect only on that defect's own check (or its `.*` family) and on its parts or documents; joints, alignments, fits and stacks also on their references (FR-003). Every known defect states its producer and expected status, and a matching finding scores by the pair:

| The key expects | The finding says | Scored as | Detected |
|---|---|---|---|
| unresolved | unresolved | flagged | yes |
| unresolved | demonstrated or suspected | credited, status mismatch | yes |
| demonstrated or suspected | demonstrated or suspected | credited | yes |
| demonstrated or suspected | unresolved | flagged below expected | no |
| any | checked within scope | cleared | no |

**Why this priority**: everything else reads the scorer, which today credits no reviewer on the only benchmarked package and credits sibling rules on the planned one.

**Independent Test**: offline, SC-001 holds on both committed keys and the regenerated `cover-blind-tap`, as do scenarios 1, 6, 15 and 17.

**Acceptance Scenarios**:

1. **Given** `fastener.bottoming` keyed on four screws, **When** `fastener.thread_match` is raised on one, **Then** the defect is missed and the finding scored on its own merits.
2. **Given** an entry ending in `.*`, **Then** a finding whose check starts with that family and a dot, at any depth, credits it; `fastener.*` never matches `fastener` or `fasteners.x`.
3. **Given** a defect expected unresolved, **Then** an unresolved match flags it and a demonstrated one credits it with a status mismatch.
4. **Given** a defect expected demonstrated whose only match is unresolved, **Then** it is flagged below expected, in no recall figure, and no false alarm.
5. **Given** a known defect with no expected status or producer, or an item with no held-out or tuned-on tag, **Then** the key is refused, naming the entry.
6. **Given** a drawing defect keyed to a drawing document, **When** the model records a drawing finding on it, **Then** the table scores it, with no false alarm.
7. **Given** an entry keyed to a document, **Then** a finding naming no parts or drawing locations overlaps it through its provenance documents.
8. **Given** a correct condition, **Then** a demonstrated finding contradicting it is a false alarm and a contradiction, even beside a known defect of its family on that part, and a checked-within-scope one agreeing is a confirmation.
9. **Given** a checked-within-scope finding on a known defect, **Then** it is cleared, not detected unless another finding detects it.
10. **Given** code- and model-produced defects, **Then** recall is reported per producer and overall, findings and false alarms per origin.
11. **Given** a scorecard of another scoring-rules version, **Then** comparison refuses it with the re-score command, which needs only the saved session.
12. **Given** a session without the origin-marks record, **Then** its code findings' origin is unknown, never guessed; **given** an off-arm session recorded after this feature, with no pre-run steps, **Then** they are "a check the model called"; a pane study refuses a session without the record, naming it and its re-run.
13. **Given** a scripted "All bought", **Then** a finding that survives code's re-run has the origin code re-run after an answer.
14. **Given** a golden scorecard changed without a version change, or the reverse, **Then** the tests fail.
15. **Given** two entries one finding could both match (a `hygiene.*` defect and a `hygiene.revision_present` correct condition on intersecting parts, or two fastener-joint entries covering one joint), **Then** the key is refused, naming both; two `fastener.thread_match` defects on different screw and hole pairs between the same parts load.
16. **Given** the `rms-part` key, whose package is not built, **Then** it loads key-only: every validation but id resolution runs, naming the missing package.
17. **Given** four screws in one plate, each joint's `fastener.bottoming` keyed as its own defect expected unresolved, **When** one joint's check cannot obtain an input, **Then** its unresolved finding names that joint's fastener and hole and flags that defect only.

### User Story 2 - The Benchmark Runs What the Pane Ships (Priority: P1)

The benchmark runs and records the pane's configuration and refuses to compare runs made under different ones.

**Why this priority**: the pane defaults were adopted on offline replay estimates; no measured run has checked their quality.

**Independent Test**: offline, with the scripted provider, SC-003 holds.

**Acceptance Scenarios**:

1. **Given** `--pane-defaults`, **Then** the benchmark uses the pane's levers, model view and explanation pass, resolved by `review`'s code.
2. **Given** an unreadable or invalid `--standards-profile`, **Then** the benchmark stops before any review with one line, while `review` records the refusal and goes on.
3. **Given** a run with a profile, **Then** provenance holds its digest, standards findings stamp the digest and file name, never the folder, and the ledger shows the model view and digest.
4. **Given** the pane study, **Then** an arm that does not state whether explanations run is refused, and comparison refuses unequal explanation settings and arms whose levers and model view are not the pane defaults' and all-off.
5. **Given** a pane baseline and an all-off baseline, **Then** they are two rows, neither in the pane study's verdict.
6. **Given** runs of one study differing in any recorded field but run identity (repetition, start time, run id, responding model within documented aliasing), live tools (shown) and, across arms, the arm, levers, model view and pane-defaults flag, **Then** comparison is refused, naming the field.
7. **Given** `review --pane-defaults --no-explain-findings`, **Then** no explanation pass runs, and the session records it off.
8. **Given** a Gemini pane study, **Then** parallel calls and dropped reasoning are recorded as inert, and the verdict names the settings the arms differed in.
9. **Given** a pane-defaults run exported with `swreview handoff`, **Then** the bundle carries the model view, digest, pane-defaults flag and live tools, never the profile's path.
10. **Given** the committed ledger, **Then** a run with another profile than the fictional example, or over a private package, is refused.
11. **Given** a run over committed packages, **Then** no file in its folder holds a local absolute path (FR-051), and runs of one study from checkouts at different locations share a set digest.

### User Story 3 - The Key Grades What Engineers Actually Complained About (Priority: P1)

Most pilot failures were not missed defects but findings that should never have appeared (R-1, R-2, R-4, R-8), coverage claiming "checked" when nothing was read (R-5), and unanswerable or repeated questions (R-2, R-3, R-6). A key now grades all three by code.

**Why this priority**: an eval that grades only matched defects would score the pilot's worst sessions as fine.

**Independent Test**: offline, the key's own expected behaviour scores zero on every new column, and one review per behaviour moves exactly the columns its behaviour defines, by one each; these are golden probes (FR-049).

**Acceptance Scenarios**:

1. **Given** a forbidden entry "no modelling-practice or hygiene finding on this bought part" (`rms.*`, `hygiene.*`), **When** the final state holds one, **Then** one forbidden hit and one false alarm, still one if it also contradicts a correct condition.
2. **Given** that entry, **When** the part-roles answer withdraws such a finding, **Then** it is a withdrawn forbidden hit, not a false alarm.
3. **Given** expected coverage "interference: unresolved or skipped" where the pins were not read (R-5), **When** the report shows interference checked, **Then** one coverage mismatch naming the item; unresolved or skipped gives none.
4. **Given** an item whose only coverage row failed, **Then** it reads unresolved.
5. **Given** an unanswerable-request entry for a bought part's drawing, **When** the review requests it among others and the product answers by code without recording, **Then** one unanswerable request.
6. **Given** the anchors' question behaviours, **Then**:
   - R-2: requesting the bought pin's drawing is one unanswerable request; asking again while it is open, refused as already asked, is one repeat of an open question and a second unanswerable request (FR-019), not a re-ask.
   - R-3: after the scripted "press fit" on the pin and hole, a follow-up naming the fit item and no ids ("now give numeric limits") is one re-ask.
   - R-6: the fasteners question asked once, answered and not asked again is one question, no re-ask.
   - A later question naming an answered part under another checklist item is not a re-ask.
   - R-1: with the part-roles question bounded to exactly one, one such question is no question-count miss; none or two is one.
7. **Given** a request naming no checklist item and no resolvable id, not the part-roles question, **Then** it is counted as unmatched.
8. **Given** a key without these entries, **Then** the new columns read not assessed, never zero.

### User Story 4 - Cases Carry the Engineer's Answers (Priority: P1)

A case can carry its engineer's answers ("press fit"; "the screws are in a separate assembly"; "All bought") in a case file. The benchmark plays them through the pane's answer path, so the review can use, ignore or re-ask them; an unscripted question gets nothing. The final state is graded.

**Why this priority**: three anchors (R-1, R-3, R-6) and the dropped-reasoning lever act only between turns.

**Independent Test**: offline, a case whose script answers the fit question records one answer turn, a scripted re-ask is counted, and the session shows the answer as the pane would.

**Acceptance Scenarios**:

1. **Given** a scripted answer to the fit question, **When** it is asked, **Then** the answer arrives through the pane's answer path and the review continues.
2. **Given** an unscripted question, **Then** nothing is sent, it ends unresolved, and it is listed as unscripted.
3. **Given** a turn whose open questions are all unscripted, **Then** no answer turn follows and the review ends.
4. **Given** two scripted questions and one unscripted in a turn, **Then** the two answers go in one answer turn.
5. **Given** a review that reaches the answer-turn bound (3 by default, in provenance), **Then** it ends, is graded from its final state as completed, and is counted as bound-reached.
6. **Given** the pane study, **Then** both arms get the same scripted answers.
7. **Given** a scripted "All bought", **Then** the named parts are regraded before the next turn, as in the pane, and forbidden entries are graded on the final state.
8. **Given** a case file with a part-roles answer whose question the run's profile would never ask, an unresolvable id, or two answers on one item whose resolved ids intersect, **When** the run starts, **Then** it is refused before any review, naming the entry.
9. **Given** a case file, **Then** the key-isolation guard refuses its path to the reviewer.

### User Story 5 - A Case Set That Can See a 10-Point Drop (Priority: P1)

A committed generator writes each fictional case from one case spec, so gold answers never come from check output. The set is weighted towards model-produced defects (16A); interference and joint-map defects are code-produced regression guards.

Every anchor is represented and tagged tuned-on (15A; research §3): **R-1** a bought pin graded for modelling practice; **R-2** drawing advice with nothing read, a bought part's drawing requested; **R-3** a press-fit dowel passed as floating, then re-asked; **R-4** zero-volume contacts as interference; **R-5** lightweight pins, interference "checked"; **R-6** empty holes rightly left alone; **R-7** a custom plate's modelling defects; **R-8** revision findings under a property the example profile does not name. The big assembly's three analyst-found defects are represented as fictional equivalents and may be held out.

The private slice (the small assembly, then the big one) stays outside the repository (FR-056).

**Why this priority**: no model-judgement defect can be scored today, so no study can decide anything.

**Independent Test**: offline, SC-001, SC-004, SC-006, SC-011 and SC-014 hold.

**Acceptance Scenarios**:

1. **Given** a case spec, **When** the generator runs, **Then** it writes the package, key and case file; a case changes only through its spec.
2. **Given** the committed set, **Then** its summary shows per judgement family, and for the other check families together (modelling practice, hygiene, standards): held-out model-produced defects, code-produced guards, tuned-on items, clean twins, anchors and analyst-found defects covered, the largest single-design share, and held-out items whose recorded digest is stale.
3. **Given** a set naming a missing private package, **Then** a run is refused, naming it.
4. **Given** `cover-blind-tap` regenerated, **Then** every item is tuned-on, it is never in the pane study's set, and D-1 (expected unresolved) and D-2 (expected unresolved, keyed to its drawing document) are reachable.
5. **Given** a pane study below 34 held-out model-produced defects, or below the approved size or repetitions, **Then** the verdict is refused, naming the count and the floor or approval.
6. **Given** a tuned-on item, **Then** it is graded as a regression guard, never in held-out recall.
7. **Given** a held-out item, **When** a commit changes the prompt, the checklist or a tool description and cites it, **Then** that commit removes its held-out status.
8. **Given** a defect tagged model-produced that code alone detects, **Then** the validation fails, naming it as code-produced.
9. **Given** a model-produced defect the correct-reviewer check cannot detect, **Then** the validation fails, naming it.
10. **Given** a committed set file, **Then** it names no absolute path.
11. **Given** a private entry naming its own key or case-file location, **Then** the key-isolation guard refuses that path to the reviewer.
12. **Given** a set whose package held-out flag disagrees with its key's item tags, **Then** scoring and comparison refuse it, naming the package.
13. **Given** the pilot's measurements, **Then** sizing grows repetitions, then cases, until SC-005 holds, and prints size, repetitions, deciding rules, levels and cost for approval.
14. **Given** a held-out defect the pilot never detected, **Then** it is listed with the findings raised on its parts or documents under other checks.
15. **Given** a pane-study set naming a private package, **Then** it is refused; the private slice's study is its own row, never in the verdict.
16. **Given** a fit defect on one pin in two plates whose fits cite one drawing, and an alignment defect between plates with other hole pairs, **Then** the generator writes the case, each entry naming its references, and a finding on the other fit, another hole pair or the bore against itself neither credits nor clears either defect.

### User Story 6 - One Report the Owner Reads (Priority: P2)

One command rebuilds, offline from run folders, one static page: every case with its tags and per-repetition headline outcome; tokens, cost and time; and a link to each full transcript (system prompt and opening message as sent, every tool call with its full result, the model's text, every answer turn).

**Why this priority**: the grading sign-off means reading graded transcripts; the ledger holds numbers only.

**Independent Test**: offline, a scripted run of three cases builds a page whose counts match the scorecards, each row linking to a transcript that starts with the recorded system prompt.

**Acceptance Scenarios**:

1. **Given** run folders of a baseline and a variant, **Then** both appear; a failed repetition shows as failed with kind and class, never zero; an unknown cost as unknown.
2. **Given** a transcript with answer turns, **Then** it starts with the system prompt and opening message as sent, each answer shown as the engineer's turn, in order.
3. **Given** a run folder from before prompts were saved, **Then** they read "not recorded".

### User Story 7 - A Run That Fails Says So (Priority: P2, before any paid study)

A failed repetition is recorded with its kind and class and does not stop the set.
- **Infrastructure failures** say nothing about the configuration: a provider error after retries; a different model answered; the wall-clock limit with no stream activity.
- **Behavioural stops** are the arm's own outcome: the step or output limit; the wall-clock limit while the stream is active; a provider stop (Gemini's safety, recitation or other stop; OpenAI's content filter or other incomplete reason); a review that overflows the model's context window, class `provider_stop` with its reason (26A).

**Why this priority**: a failed review scored as "found nothing" looks like a real miss, and a lever that makes reviews stop must not gain from its worst runs leaving the score.

**Independent Test**: SC-007.

**Acceptance Scenarios**:

1. **Given** a provider error persisting after retries, **Then** the other packages complete, and the failure records its exact retry count.
2. **Given** a Gemini safety stop or an OpenAI content-filter cut-off, **Then** it is a behavioural stop, never a provider error or a finished review.
3. **Given** a response from a model other than requested, beyond documented aliasing, **Then** the attempt fails as an infrastructure failure.
4. **Given** the wall-clock limit, **Then** a silent stream is an infrastructure failure, and an active one a behavioural stop, not re-run.
5. **Given** a run folder with one infrastructure failure and one behavioural stop, **When** resumed, **Then** only the failure re-runs, from the start, its attempt kept; no session is appended to a completed package; a differing responding model is refused.
6. **Given** a finished run, **Then** each completed package carries the responding model, usage and cost; a model missing from the price table, or missing usage, gives "cost unknown", naming what is missing.
7. **Given** a review cut short at its step limit, **Then** it is a behavioural stop: out of the main figures, its re-asks and forbidden hits counted, its defects not detected in the sensitivity figure.

### User Story 8 - The Pane Study Reaches a Verdict Noise Cannot Flip (Priority: P2, before the pane study)

Model-produced defects are found on some runs only, so the lever studies' adoption rules do not apply. The verdict is **quality loss**, **no 10-point loss** or **inconclusive**, from paired rules and worst-case guards (FR-044, FR-045), and calls identical arms a loss at most 5% of the time by simulation. No token or wall-clock threshold applies: the pane defaults are already adopted.

**Why this priority**: a verdict that flips between identical runs decides nothing.

**Independent Test**: SC-010.

**Acceptance Scenarios**:

1. **Given** a pane study, **Then** the verdict names both differences with intervals, the sensitivity figure, both guards, the deciding rules and levels, SC-005's simulated rates, the noise floor and the seed, beside the shown-only measures.
2. **Given** a code-produced defect detected on every completed off-run and not on one completed on-run, **Then** quality loss, whatever else holds.
3. **Given** completed off-runs that disagree on a code-produced defect, **Then** it is named and the guard does not fire on it; that alone never makes the verdict inconclusive.
4. **Given** a held-out defect cleared on one on-run and no off-run, **Then** it is named, and is a quality loss only if the approved levels make the cleared guard decide.
5. **Given** unchanged model-origin false alarms while the on arm's pre-run false alarms rise (R-8's hygiene findings), **Then** the rise is shown and named, not a loss.
6. **Given** a finding hitting a tuned-on forbidden entry, **Then** it is shown among the regression guards, outside the deciding false-alarm figure.
7. **Given** fewer fit and axial-stack calls on the on arm, **Then** the fall is shown with its interval, named when it excludes zero, and the verdict is unchanged.
8. **Given** the same run folders compared twice, **Then** verdict, intervals and noise floor are identical, the seed recorded.
9. **Given** a zero-width recall interval, **Then** it is not computable and the verdict inconclusive, saying why; **given** a zero-width false-alarm interval, **Then** it calls no loss and shows as not computable.
10. **Given** a recall interval of -18 to +4 points, **Then** inconclusive, never "no 10-point loss".
11. **Given** an infrastructure failure or behavioural stop in one arm, **Then** rates are over its completed repetitions; a defect with none there is dropped from both arms, counted and named.
12. **Given** behavioural stops leaving the main recall figure without a loss, or below the floor, but the sensitivity figure with one, **Then** quality loss.
13. **Given** drops of either kind leaving fewer held-out model-produced defects than the floor, and no deciding rule calling a loss, **Then** inconclusive, naming the count.
14. **Given** a rise in median false alarms while the paired false-alarm interval includes zero, **Then** not a loss.
15. **Given** an off-arm model's code-only call whose finding hits a held-out forbidden entry, **Then** a code-origin false alarm, shown beside the pre-run's, not deciding.

### Edge Cases

- **Overlapping entries.** Two entries overlap when their checks can match one common check (equal, or one a `.*` family containing the other) and one finding could match both, by intersecting parts or documents or by naming the references of both (FR-003). A known defect overlapping a correct condition, another known defect or a forbidden entry is refused; a forbidden entry may overlap a correct condition (US3-1).
- **Two findings on one defect.** Expected unresolved: an unresolved plus a demonstrated finding credit it with a status mismatch, in either order; otherwise it is credited.
- **Cleared and credited in one review.** Both recorded: detected for recall, cleared for the cleared guard.
- **An empty key** scores every demonstrated or suspected finding as a false alarm, recall not computable.
- **The live SOLIDWORKS tools** are absent offline; both arms record it, and a confirmed drawing read records no connection, as the pane does without the add-in.
- **A request naming an item and no ids**, on an item with several scripted answers, is unscripted, the ambiguity named.
- **Near-duplicate real designs** are one case in the private slice.

## Requirements *(mandatory)*

### Functional Requirements

Brackets name the scenarios and criteria testing each requirement; "defined in the plan" means research §8 holds the starting design.

**Scoring (User Story 1)**

- **FR-001**: A finding MUST credit a known defect only on the entry's check, or inside its `.*` family, and only when they overlap (FR-003). [US1-1, US1-2; SC-002]
- **FR-002**: Findings MUST be scored by User Story 1's table against each defect's stated expected status, flagged defects also in their own column; flagged below expected counts in no recall figure and as no false alarm. [US1-3, US1-4; SC-001]
- **FR-003**: Every key entry MUST name parts, documents or both. A finding overlaps it through its parts, its cited drawing documents, or, naming neither parts nor drawing locations, its provenance documents. A known defect or correct condition of a fastener-joint, hole-alignment, fit or axial-stack check MUST also name the references (fastener and hole, both holes, or dimensions) of each joint, pair, fit or stack it covers; a finding overlaps it only when its inputs, calculation inputs or drawing locations name all those of one. Forbidden entries stay on parts or documents. The plan names the checks and fields. [US1-6, US1-7, US5-16]
- **FR-061**: On every path, unresolved included, every result of the four fastener rules (`fastener.bottoming`, `.engagement`, `.thread_match`, `.head_clearance`) MUST record its joint's fastener and hole ids, and every `hole.coaxiality`, `hole.nominal_alignment` and `hole.position_stack` result both hole ids or the joint's hole instances; `fastener.unsupported` records the hole id too wherever its call names a hole, and `fastener.head_fit` keeps its one reference (research §8.12). So a finding names the exact joint (Principle IV) and FR-003 matches that joint only (19A). Golden and replay fixtures MUST regenerate in the same change (feature 008's decision 3A: fixtures follow the code). [US1-17]
- **FR-004**: Correct conditions MUST carry ids. A demonstrated or suspected finding matching one MUST be a false alarm and a contradiction, never a credit; a checked-within-scope one, a confirmation. [US1-8]
- **FR-005**: A checked-within-scope finding on a known defect MUST clear it, not detect it. [US1-9]
- **FR-006**: Each known defect's producer MUST follow its own package's evidence (16A): code when a code-only call (Terms) can find it, else model. Recall MUST be reported per producer and overall. [US1-10, US5-8; SC-014]
- **FR-007**: Every finding MUST have one of seven origins (pre-run code; code re-run after an answer; a check the model called, code-only or configured (Terms); the model; carried; set-up; unknown), findings and false alarms split by it. The first two MUST come from a mark on each step, never event order. New sessions MUST record that they carry marks; a session without that record reads unknown, as does a finding citing a step its session does not hold, and a pane study MUST refuse such a session or such a false alarm. [US1-10, US1-12, US1-13]
- **FR-008**: Scorecards MUST record the scoring rules' version, changed by any matching or counting change; comparison MUST refuse other versions, naming the re-score command. [US1-11; SC-013]
- **FR-009**: Keys MUST be validated at load as US1-5, US1-15 and US1-16 show, refusals naming the entry; ids that resolve nowhere, coverage items not in the checklist and unresolvable request ids are refused too. [US1-5, US1-15, US1-16; SC-002]
- **FR-010**: `cover-blind-tap` MUST be regenerated as US5-4 states. `rms-part` MUST be key-only, with producers, statuses and condition ids. [US1-16, US5-4; SC-001, SC-014]
- **FR-049**: Golden scorecards, written and checked by the validation (FR-054), MUST pin each committed case's oracle and null reviews and, over committed cases, a probe review per scored column and per matching rule (User Stories 1, 3 and 4), each scoring exactly its behaviour, under SC-013's version rule. [US1-14; SC-013]

**Parity with the pane (User Story 2)**

- **FR-011**: `benchmark run` MUST accept the pane-defaults and model-view switches and a profile, resolved by `review`'s code alone. [US2-1]
- **FR-012**: The benchmark MUST start reviews as the pane does, as SC-003's test shows. [US2-1; SC-003]
- **FR-013**: Provenance MUST record the fields US2-3 and US2-9 name plus the explanation setting and answer-turn bound, never the profile's path; comparison MUST refuse mixed runs as US2-6 states. [US2-3, US2-6, US2-9]
- **FR-014**: The pane study MUST have the all-off and pane arms US2-4 checks, differing only in levers and model view; the pane baseline MUST be its own row, and no baseline enters the verdict. [US2-4, US2-5]
- **FR-015**: `--pane-defaults` MUST mean the same on `review` and `benchmark run`, explanations included unless `--no-explain-findings` is typed. [US2-1, US2-7]
- **FR-016**: Fit and axial-stack call counts MUST be shown per arm with a paired interval, named when it excludes zero, never deciding (18A). [US8-7]
- **FR-050**: `benchmark run` MUST stop before any review, with one line, on an unreadable or invalid profile; `review` and the pane keep recording the refusal and going on. [US2-2]
- **FR-051**: Nothing a run writes where it may be committed MUST carry a local absolute path: the saved set names repository packages relatively, so its digest ignores the checkout's location, and standards findings stamp no folder (D12). A test MUST fail on any local absolute path, or private set entry, in a committable folder; the named fictional roots (the builders', the golden fixtures' and the example profile's) are not local (research §8.8). The committed ledger holds only fictional-profile studies over committed cases; private-slice files never enter it. [US2-3, US2-10, US2-11]
- **FR-052**: A Gemini pane study MUST record parallel calls and dropped reasoning as inert and name the settings the arms differed in. [US2-8]

**Beyond matched defects (User Story 3)**

- **FR-017**: Forbidden entries match as FR-001 and FR-003 do. A hit in the final state MUST count as a forbidden hit and a false alarm (at most one per finding); a hit withdrawn before the end, as a withdrawn forbidden hit only. [US3-1, US3-2]
- **FR-018**: Expected coverage names a checklist item and the statuses the report may show. The status MUST be the one the product's own report reader shows, with no second reader. This feature does not change which rows that reader files under a goal: of the pre-run's `coverage.prerun` rows only interference and standards are goal items, the others are read by no goal, and no committed key may expect a status only they would give (research §8.4). A failed row reads unresolved, and any other status is a mismatch naming the item. The mapping is defined in the plan and MUST read R-5's "checked" as a mismatch. [US3-3, US3-4]
- **FR-019**: Every request call matching an unanswerable-request entry MUST be counted, recorded or not. [US3-5, US3-6]
- **FR-020**: A request call matching an answered question MUST be a re-ask, split into refused and seen; one matching a still-open question (unscripted, or not yet answered), a repeat of an open question. [US3-6]
- **FR-021**: Columns a key does not grade MUST read not assessed, never zero. [US3-8]
- **FR-053**: One matcher MUST pair request calls with scripted answers, key entries and earlier questions by checklist item and ids, never by wording, and the part-roles question by its identity; a request naming neither, and not that question, is unmatched. The rule is defined in the plan and MUST classify US3-6 as stated. [US3-6, US3-7, US4-1]
- **FR-060**: A key MAY bound how many questions of a kind are asked; a count outside the bound MUST be a question-count miss. [US3-6]

**Scripted answers (User Story 4)**

- **FR-022**: Scripted answers MUST live in a case file apart from the key and outside the package, keyed to a checklist item (or none) and parts or documents, or to the part-roles question. Only the answer driver reads it; the key-isolation guard MUST refuse it to the reviewer. The run MUST refuse it before any review when US4-8's conditions hold. [US4-1, US4-7, US4-8, US4-9]
- **FR-023**: Answers MUST go through the pane's answer path, one answer turn per turn's questions, recorded as the pane records them, alike in both arms. [US4-1, US4-4, US4-6]
- **FR-024**: An unscripted question MUST get nothing and end unresolved, listed as unscripted; a turn of only unscripted questions ends the review. [US4-2, US4-3]
- **FR-025**: Answer turns MUST stop at a bound (3 by default, an option, in provenance); a review reaching it is completed, graded, and counted as bound-reached (D16). [US4-5, US2-6]
- **FR-026**: Grading MUST read the final state after all answer turns. [US4-7]

**Cases (User Story 5)**

- **FR-027**: A committed generator MUST write each case's fictional package, key and case file from one case spec, byte for byte, with the builders the golden and fixture generators use (research §7) plus one fictional builder of ingested drawing-sheet dimensions, which the fit, stack and toleranced alignment checks need (D14.1). It MUST import no check, tool or agent logic beyond the data models and fictional builders the plan names. Every committed case MUST be built and keyed against the repository's fictional example profile. [US5-1; SC-006, SC-014]
- **FR-028**: The committed set MUST hold at least 34 held-out model-produced defects (a floor), none tuned-on, over at least 8 designs (a template with its twins and variants): no design over a fifth of them, no package over 2, never two of one judgement family. Each MUST have a clean twin. [US5-2; SC-004]
- **FR-029**: Every anchor and analyst-found defect MUST have a committed case recording which; anchor behaviours are tuned-on. [US5-2; SC-004]
- **FR-030**: Sets MUST be able to name outside packages by absolute path, with per-entry key and case-file locations. A missing package MUST refuse the run; the key-isolation guard MUST refuse every key and case-file path a set names; a committed set file holds no absolute path. [US5-3, US5-10, US5-11, US4-9]
- **FR-031**: Held out MUST be recorded once, as a tag on every graded item. Items the prompt or checklist was written around are tuned-on. Held-out items MUST carry their prompt, checklist and tool-description digests (25A) and lose the status in the commit whose change cites them. [US5-6, US5-7]
- **FR-032**: Runs MUST never read a key. A set's package held-out flag MUST be derived from its key and checked against it by score and compare; held-out recall reads item tags; `benchmark run`'s refusal of a set holding nothing out reads the flags. Score MUST record the held-out count the keys name, before failures; compare MUST refuse a pane-study verdict below 34 or below the approved size and repetitions. [US5-5, US5-12]
- **FR-033**: The set MUST print US5-2's per-family summary. [US5-2]
- **FR-054**: An offline validation over the committed set, apart from the generator, MUST fail a case when, with no model, the pre-run's calls and every other check with no required parameter do not detect exactly its code-produced defects, or raise a demonstrated or suspected finding matching neither a known defect nor a forbidden entry (one contradicting a correct condition fails the case), or when the correct-reviewer check misses a model-produced defect. The case spec records each model-produced defect's withheld evidence. [US5-8, US5-9; SC-014]
- **FR-055**: An off-arm pilot MUST measure per-defect detection rates, package co-movement, the off arm's detection of code-produced defects, and behavioural-stop, clearance and false-alarm rates, from which simulations set size, repetitions and FR-044's levels (repetitions first, up to a cap of 10 unless the owner sets another at the cost gate, then cases) until SC-005 holds, for the owner's recorded approval. Held-out defects it never detected MUST be listed with the findings on their parts or documents. [US5-13, US5-14; SC-005]
- **FR-056**: A pane-study set naming a private package MUST be refused. The private slice is its own study, set and row, with the real profile, never in the verdict. [US5-15]

**Report (User Story 6)**

- **FR-034**: One command MUST build User Story 6's page offline from run folders as `benchmark run` writes them. A run folder holds no package copy, so the report finds each package through the folder's saved set (FR-051); a repetition with no usage (failed before its first round) still shows (FR-035). [US6-1, US6-2; SC-009]
- **FR-035**: A failed repetition MUST show as failed with kind and class, never zero; an unknown cost as unknown. [US6-1]
- **FR-057**: Runs MUST record the system prompt and opening message they sent; older folders show "not recorded". [US6-2, US6-3]

**Robustness (User Story 7)**

- **FR-036**: A failed repetition MUST be recorded with User Story 7's kind and class and never stop the set; reaching the answer-turn bound is no failure. [US7-1, US7-2, US7-4; SC-007]
- **FR-037**: Every package MUST run under a wall-clock limit independent of the stream. [US7-4; SC-007]
- **FR-038**: Retries MUST back off with jitter and be counted exactly, library retries off or counted. [US7-1]
- **FR-039**: The responding model MUST be recorded; a model other than requested, beyond documented aliasing, fails the attempt as an infrastructure failure. [US7-3]
- **FR-040**: A provider's own stop, on either provider, MUST be a behavioural stop, including any stop or incomplete reason the provider reports that User Story 7 does not name. [US7-2]
- **FR-041**: Infrastructure failures MUST be excluded from every score and re-run on resume. Behavioural stops MUST be counted per arm and class and kept out of the main figures, their re-asks, forbidden hits, unanswerable requests and clears still counted; the sensitivity figure MUST include them, their defects not detected and their model-origin false alarms up to the stop counted. [US7-7, US8-12; SC-007]
- **FR-042**: Cost MUST come from each completed package's usage and a committed price table (per model, three prices with source and date); no price or no usage reads "cost unknown", naming what is missing, never 0 and never a scoring failure. Cached input is priced apart only where the provider's counting is verified, and says so otherwise; scripted, oracle and null runs are synthetic and unpriced. [US7-6, US6-1; SC-008]
- **FR-043**: A resume MUST re-run from the start only infrastructure failures, keeping their records, never append to a completed session, and refuse a differing responding model. [US7-5; SC-007]

**Verdict (User Story 8)**

- **FR-044**: The verdict MUST be quality loss, no 10-point loss or inconclusive, from rules taking the package as the unit, each with a package-level interval (resampled with a recorded seed, or analytic): **recall**, the mean over held-out model-produced defects of on minus off detection rate, a loss when its interval lies below zero; **false alarms**, the mean over every package of the study's set of on minus off model-origin false alarms per completed repetition (17A), tuned-on hits excluded (D15), a loss when its interval lies above zero; both again on the sensitivity figure; and FR-045's guards. Any deciding rule's loss is a quality loss, below the floor included (FR-058). The interval method and levels are defined in the plan, fixed at the cost gate, printed with the verdict, and MUST meet SC-005's two 5% bounds by simulation. No 10-point loss needs no loss called and a lower end of the recall rule's own interval above -10 points on both figures; anything else is inconclusive, naming why. A zero-width interval is not computable: inconclusive for recall, no loss for false alarms. [US8-1, US8-9, US8-10, US8-12, US8-15; SC-005, SC-010]
- **FR-045**: Guards (D17). **Code-produced defects**, held out or tuned-on: a loss when every completed off-run detected one and some completed on-run did not; off-runs that disagree only stop the guard firing on that defect, which is named. **Cleared defects**: one cleared on some on-run and no off-run (clears before a behavioural stop count) MUST be named, deciding for an item not tuned-on only where FR-044's recorded levels say so. The lever studies' other adoption rules MUST NOT apply. [US8-2, US8-3, US8-4, US8-14]
- **FR-046**: The same run folders MUST give the same verdict, intervals and noise floor. [US8-8]
- **FR-058**: Main-figure rates MUST be over each arm's completed repetitions, the sensitivity figure's also over behavioural stops (FR-041). A defect with none in an arm is dropped from both arms of that figure, and a package with none from both arms of its false-alarm rule, each counted and named. Drops of either kind below the floor rule out "no 10-point loss": the verdict is inconclusive, naming the count, unless a deciding rule (a guard, or a paired rule on either figure) calls a loss. [US8-11, US8-12, US8-13]
- **FR-059**: Beside the verdict, never deciding, the comparison MUST show per arm, with paired intervals named when they exclude zero, every regression guard and every other scorecard column (false alarms by origin, the model's code-only calls' beside the pre-run's; unresolved coverage), bound-reached reviews and fit and axial-stack calls; also failures by kind and class, the noise floor, code-produced defects the off arm detected only sometimes, cleared defects, and the held-out defects every run, or no run, of both arms detected. [US8-1, US8-5, US8-6, US8-7]

**Throughout**

- **FR-047**: Everything but the paid review calls MUST run offline, with no API key and no SOLIDWORKS licence. Without the tokenizer vocabulary, token counts read unknown, never 0, and nothing is refused (D14.6). [SC-012]
- **FR-048**: Nothing committed may carry a company identifier. The generator MUST build every string from the fictional builders and fail on its own fictional-string checks, on every machine; the identifier tests MUST pass over the committed output where the owner's lists exist, and show skipped, never passed, elsewhere. [SC-011]

### Key Entities

- **Case spec**: the one source of a case's package, key and case file, recording its template, the evidence each model-produced defect withholds, and the anchor or analyst-found defect it represents.
- **Answer key**: known defects, correct conditions (with ids), forbidden entries, expected coverage, unanswerable requests and question-count rules, each tagged held out (with digests) or tuned-on; a key-only marker.
- **Case file**: the scripted answers (FR-022).
- **Benchmark set**: per case, the package location, a held-out flag derived from its key, and for a private case its key and case-file locations.
- **Run provenance**: FR-013's fields, the responding model and a location-independent set digest; beside it, the system prompt and opening message.
- **Scorecard**: per package, detection outcomes, recall by producer, findings and false alarms by origin, contradictions and confirmations, forbidden and withdrawn forbidden hits, coverage mismatches, unresolved coverage, unanswerable requests, re-asks, repeats of open questions, unmatched requests, question-count misses, unscripted questions, run status (completed, bound-reached, or a failure with kind and class), usage and cost, version, held-out count.
- **Pilot measurement**: the rates FR-055 names; the resulting size, repetitions, deciding rules, levels and cost; the owner's approval.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On every committed key with a known defect, the oracle review detects 100% and scores zero on every failure-mode column (false alarms, contradictions, the Scorecard's question, coverage and forbidden columns, flagged below expected, status mismatches, cleared defects), or not assessed where the key does not grade it (FR-021), and the null review detects 0% with no false alarm; with no known defect, both read recall not computable with no false alarm.
- **SC-002**: No finding can credit more than one known defect in any committed key.
- **SC-003**: A pane-defaults benchmark run and a pane review of one package differ in no recorded setting outside the named transport fields and the live tools.
- **SC-004**: The committed set meets FR-028's floor, caps and clean twins, and represents every anchor and analyst-found defect.
- **SC-005**: Before the paid study, simulations on the pilot's measurements, at the size, repetitions, rules and levels approved at the cost gate, show the recall rule on the main figure calling a true 10-point drop a loss at least 80% of the time under both drop shapes, and, as upper 95% Monte Carlo bounds, the verdict calling identical arms a loss, or a true 10-point drop no 10-point loss, each at most 5% of the time. The size is never below 34 held-out model-produced defects or 3 repetitions.
- **SC-006**: Regeneration reproduces every package, key and case file byte for byte, and the validation every golden scorecard. A structural test shows the generator imports no check, tool or agent module beyond the allowed data models and fictional builders (research §8.9 settles direct or transitive imports).
- **SC-007**: Offline, with a scripted provider that fails on one package, hangs silently on a second and safety-stops a third, the set completes; the first two are counted as failures, in no score, and alone re-run on resume; the third is a behavioural stop with its re-asks and forbidden hits counted.
- **SC-008**: Every completed package of a paid run carries the responding model, non-zero usage and a priced cost; none reads "cost unknown" on the pilot. Checked offline on recorded responses; confirmed on the smoke run (quickstart P0, 35A) before the pilot, and on the pilot.
- **SC-009**: On the development machine, the report for 40 cases at 10 repetitions, with pilot-size transcripts, builds offline in under one minute, every row linking to a transcript that opens.
- **SC-010**: Offline, at every reference scenario, the simulator prints its inputs, holds SC-005's two 5% bounds at the size, repetitions and levels it picks, and prints power under each drop shape and the smallest repetitions, up to the cap of 10, then cases, for 80%; the every-0.5 scenarios with shock SD 1.0 reach the cap and grow cases. Stated rates and the drop are marginal, averaged over the shock: the simulator solves each defect's logit intercept in each arm to meet them, and a rate of 0 or 1 is unaffected by the shock. Scenarios: 17 packages of 2 held-out model-produced defects plus 34 clean twins (research §8.11's rule A layout, kept as the simulator's reference), from 3 repetitions; off-arm rates all 0.5, uniform on 0 to 1, or three in four always or never (evenly), the rest 0.5; a per-run package logit shock of SD 0 or 1.0; model-origin false alarms per package run negative-binomial, mean 0.2, 1 or 3, dispersion 0.5 or Poisson; and, each alone on the uniform co-moving scenario of mean 1, dispersion 0.5, stops on 5% of runs per arm, 10 held-out defects cleared on 5% of runs, and 10 code-produced defects the off arm detects on 95% of runs. With clearance it drops the cleared guard from the deciding rules or shows the bound held, printing which. 4,000 simulations per scenario, seed fixed in the test; cases are added as packages of 2 defects and 2 twins from the scenario.
- **SC-011**: The generator's fictional-string checks pass over every generated file on every machine; on the owner's machine, the identifier tests pass over every file this feature commits.
- **SC-012**: Everything but the paid review calls runs with no API key and no SOLIDWORKS licence.
- **SC-013**: A matching or counting change that alters a golden scorecard fails the tests unless the version changes in the same commit, and a version change with no golden change fails them too.
- **SC-014**: Every committed case, `cover-blind-tap` included, passes both reachability checks of FR-054.

## Assumptions

- **Paid runs happen elsewhere or later**: this machine has no provider key.
- **The first pane study runs on OpenAI**, the production default (D14.5).
- **The owner writes the private keys and case files**, and uses the real profile only with the private slice.
- **No judge**: R-2's prose is not graded; its structure is.
- **`rms-part`** stays key-only until built on the seat.
- **The acceptance suite** (constitution; D14.7): the committed set's 8 to 10 generated designs, keys withheld, some items held out; the private slice's real designs are shown beside it and never decide (23A); the plan's Constitution Check records how representative they are.
- **Complexity**: the plan's Complexity Tracking justifies D14.10's list.
