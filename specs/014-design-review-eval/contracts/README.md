# Contracts: Design-Review Eval

Normative detail for [plan.md](../plan.md), one contract per mechanism. Each states behaviour,
fields, refusals and the failing tests that pin it; where two contracts meet, each names the other
and neither restates it. Integration decisions (INT-1 to INT-18), every area decision, the
review fixes of three rounds (§9.9 to §9.11; RF-1 to RF-81) owner decision 28A's application
(§9.12; RF-82 to RF-84) and the application of owner decisions 33A to 36A, from the owner's review
of the plan on 2026-10-06 (§9.14; RF-87 to RF-91), are in
[research.md](../research.md) §9, whose section 9.7 holds the owner's eight questions: four answered
as owner decisions 24A to 27A, three kept at their defaults, and question 8 answered B (owner decision 30A, §9.13). Line numbers
are at `be01974`.

| Contract | What it fixes | FRs | Other criteria and scenarios | Slice |
|---|---|---|---|---|
| [scoring.md](scoring.md) | The one matcher (checks, targets, references); 13A's outcomes; conditions; false alarms, forbidden and withdrawn hits; coverage through the report's reader; eight origins, the step mark and the session record; producers, tags and recall; the scorecard's fields, including run status and cost; the scoring-rules version; golden scorecards, probes and the version record; 19A | FR-001 to FR-008, FR-017, FR-018, FR-021, FR-031 (tags read), FR-032 (score half), FR-049, FR-061 | SC-001, SC-002, SC-013; US1-1 to US1-17, US3-1 to US3-4, US3-8, US5-12 | 1, 3, 4, 6 |
| [answer-key.md](answer-key.md) | Key format 2, its entries, references and check patterns; load-time refusals and overlap; key-only keys; the two committed keys; `current_stamp` | FR-003 (key half), FR-004, FR-009, FR-010, FR-031 (tag and digests) | US1-5, US1-15, US1-16, US5-4 | 1, 3, 4 |
| [questions.md](questions.md) | Request calls read from steps and stored results; id resolution; the one relation and its four uses; the part-roles identity; unanswerable and question-count entries; the question columns; the oracle's question half and probes | FR-019, FR-020, FR-021 (question columns), FR-053, FR-060 | US3-5 to US3-8 | 3, 4 |
| [scripted-answers.md](scripted-answers.md) | The case file, its location and run-start refusals; `drive_review` through `answer_evidence_batch`; Skip; the answer-turn bound; `answer-log.json`; isolation and the saved set | FR-022 to FR-026, FR-013 (the bound) | US4-1 to US4-9 | 3, 6 |
| [benchmark-run.md](benchmark-run.md) | The resolver shared with `review`; `benchmark run`'s options and refusals; the run folder, attempts and promotion; the worker and wall clock; retries; the served model; provider stops; classification; `run-status.json`; resume; `prompts.json`; cost and the price table; packages at once (`--jobs`, 36A); the one live test (35A); the one atomic writer, the product's three older copies moved onto it (34A) | FR-011, FR-012, FR-015, FR-036 to FR-043, FR-047, FR-050, FR-057 (the record) | SC-003, SC-007, SC-008, SC-012; US2-1, US2-2, US2-7, US7-1 to US7-7 | 2, 3, 5, 6 |
| [provenance.md](provenance.md) | Provenance schema 2; record-against-session cross-checks; the pane study, the pane baseline, the private study; the must-match rule; inert settings; the ledger's columns in their final order and schema 1.1; location-free saved sets; the profile stamp (D12); committable folders; line endings; the committed event streams, packed by `benchmark pack` with their digests (28A); the handoff export | FR-013, FR-014, FR-032 (compare half: the set flag against the scored items, RF-39), FR-051, FR-052, FR-056 (run half) | US2-3 to US2-6, US2-8 to US2-11, US5-12 (compare half), US5-15 | 2, 3, 6 |
| [cases.md](cases.md) | Where case files live and who reads them; the set file, its private entries and refusals ("the benchmark-set contract"); the held-out stamp; the committed set, the pane smoke set (35A) and their counts; anchors; `cover-blind-tap`; the validation (a), (b) and decoys; the set summary | FR-010 (regeneration), FR-022 (location), FR-028 to FR-033, FR-054, FR-056 (set half) | SC-004, SC-014; US5-1 to US5-12, US5-16 | 1, 2, 3, 4 |
| [generator.md](generator.md) | The case spec; seed kinds and withheld evidence; twins; building packages with the fictional builders; the ingested-sheet builder; rendering; fictional strings; the import allowlist; spec refusals | FR-027, FR-048 | SC-006, SC-011; US5-1 | 4 |
| [report.md](report.md) | `benchmark report`: static HTML from run folders; finding packages through the saved set; the page's columns; transcripts walked from the log; the output folder; performance | FR-034, FR-035, FR-057 (the page) | SC-009; US6-1 to US6-3 | 5, 6 |
| [verdict.md](verdict.md) | The package-level interval; the rules and their order; shown measures; verdict refusals; the ledger's pane block; the simulator, its levels and sizes; the noise floor, simulated once and stored; the smoke run before the pilot (35A); the pilot, its measurement, the study's projected wall clock (36A) and the approval; the private row | FR-016, FR-032 (compare half: the floor and the approved size), FR-044 to FR-046, FR-052 (naming), FR-055, FR-056 (compare half), FR-058, FR-059 | SC-005, SC-010; US5-5, US5-13, US5-14, US8-1 to US8-15 | 7, 8 |

Each contract's failing-first tests are tasks in [tasks.md](../tasks.md), in the phase of the slice the contract marks.

Every FR from FR-001 to FR-061 is served by at least one contract above. Amendments to earlier
features' contracts (001, 002, 005, 006, 008, 010) are listed at the top of the contract that makes them
and land with the task that changes the code.
