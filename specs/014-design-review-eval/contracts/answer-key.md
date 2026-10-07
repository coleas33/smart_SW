# Contract: The Answer Key, Its Format and Its Validation

Normative for FR-003's key half, FR-004's condition ids, FR-009, FR-010, FR-031's tag, and the
key sections FR-017 to FR-020 and FR-060 read. Research D7, D8, SP-5, SP-9, SP-10, SP-12, §8.12,
§8.13; owner decisions 13A, 15A, 16A, 19A. Amends feature 001's `data-model.md` section 3 (the
answer key) and `benchmarks/README.md`'s one line on keys. How a finding is matched against an entry
is `scoring.md` section 2; this contract uses that rule for its overlap test and does not restate
it. The two question sections (unanswerable requests and question counts) are `questions.md`
section 5's, fields, matching and refusals; this contract adds the fields every entry has and runs
those refusals when a key loads. Where a set names a key is the benchmark-set contract's.

Line numbers are at `be01974`; paths are under `reviewer/src/swreview/` unless another root is
given. Every example value is fictional.

## 1. Who reads a key

- `benchmark/answer_key.py` is the one reader (`:1-6` says so today). `score_run` calls it after a
  run has finished; the validation over the committed set (FR-054) calls it to build the oracle
  and the probes (`scoring.md` section 9). Nothing under `tools/`, `agent/`, `checks/` or
  `benchmark/runner.py` imports it or the model below: runs never read keys (FR-032). The
  key-isolation guard (`ir/loader.py:23, 46-62`) keeps committed keys out of the reviewer's reach;
  its extension to every key path a set names is the benchmark-set contract's.
- **The format is data only** (plan decision RF-1). The pydantic models, in
  `benchmark/answer_key_model.py`, are the format's one definition: the key, its entries, `Stamp`,
  the check-pattern grammar of section 3, the table of reference-keyed checks and their kinds of
  section 2.5, and the validators that need nothing but the model (section 4, rows 1, 3, 4, 5, 7
  and row 6's grammar). It imports pydantic and `findings.ReviewModel` only, so the generator
  writes keys through it (`generator.md` 7 and 9) without loading the loader, which imports the
  matcher (`benchmark/matching.py`), the question reader (`benchmark/questions.py`, built on
  `tools/context.context_for`) and `tools/refs.resolve_dimension`. `benchmark/answer_key.py` holds
  `load_answer_key`, `current_stamp()` and the rows that need those modules (rows 2, 6's typo
  guard, 8 to 14). No JSON schema file is written beside the model: two definitions of one format
  drift. The model's two derivations are the only ones: the set's `held_out` flag, which the
  generator writes and `score` and the set summary check, is `holds_held_out()`, and the held-out
  model-produced count, which the scorer and the set summary print, is the length of
  `held_out_model_defect_ids()` (plan decision RF-67).

```python
# reviewer/src/swreview/benchmark/answer_key_model.py  (data only)
class AnswerKey(ReviewModel):           # and KnownDefect, CorrectCondition, ..., Stamp
    def holds_held_out(self) -> bool: ...                  # some entry tagged held_out
    def held_out_model_defect_ids(self) -> list[str]: ...  # held-out known defects, producer model

# reviewer/src/swreview/benchmark/answer_key.py
class AnswerKeyError(ValueError): ...

def load_answer_key(
    path: Path,
    *,
    package: EvidencePackage | None,
    checklist: Checklist,
    words: Words,
) -> AnswerKey: ...
```

`package` is the package the set names, loaded by the caller, or `None` when there is none on disk
(section 6). `checklist` is `agent/checklist.py`'s loaded checklist; `words` is
`report.summary.load_words()` (`report/summary.py:351-353`), whose goals section 4 reads. Every
refusal is an `AnswerKeyError` whose message starts "answer key {file name}:" and names the entry
id or ids; being a `ValueError`, the command line turns it into one line and exit 1
(`cli.py:260-269, 530-542`).

## 2. Format

```json
{
  "key_format": 2,
  "package_id": "fict-r3-press-fit-a",
  "known_defects": [
    {"id": "D-1", "check": "fit.size_only",
     "component_ids": [], "document_ids": ["doc:0004"],
     "references": [{"bore":  {"document_id": "doc:0004", "sheet": "Sheet1", "annotation": "D3"},
                     "shaft": {"document_id": "doc:0004", "sheet": "Sheet1", "annotation": "D4"}}],
     "producer": "model", "expected_status": "suspected",
     "tag": "held_out",
     "held_out_against": {"prompt": "<sha256>", "checklist": "<sha256>", "tools": "<sha256>"},
     "description": "Pin FICT-7002 is drawn wholly above the bore's limits: an interference fit."}
  ],
  "correct_conditions": [
    {"id": "C-1", "check": "hole.coaxiality",
     "component_ids": ["cmp:0001", "cmp:0003"], "document_ids": [],
     "references": [{"holes": ["hol:0002", "hol:0005"]}],
     "tag": "tuned_on", "description": "The locating pair is coaxial within its drawn tolerance."}
  ],
  "forbidden": [
    {"id": "FB-1", "checks": ["rms.*", "hygiene.*"],
     "component_ids": ["cmp:0002"], "document_ids": [],
     "tag": "tuned_on", "description": "No modelling-practice or hygiene finding on the bought pin."}
  ],
  "expected_coverage": [
    {"id": "CV-1", "item": "interference", "statuses": ["unresolved", "skipped"],
     "tag": "tuned_on", "description": "Nothing of the pins was read, so interference is not checked."}
  ],
  "unanswerable_requests": [
    {"id": "U-1", "documents": ["doc:0003"], "item": null,
     "tag": "tuned_on", "description": "The bought pin has no drawing to supply."}
  ],
  "question_counts": [
    {"id": "Q-1", "part_roles": true, "min": 1, "max": 1,
     "tag": "tuned_on", "description": "The part-roles question is asked exactly once."},
    {"id": "Q-2", "item": "interfaces.fit", "max": 1,
     "tag": "tuned_on", "description": "The fit question is asked at most once."}
  ]
}
```

### 2.1 The key

| Field | Rule |
|---|---|
| `key_format` | `2`. A key without it was written for the scorer before this feature and is refused, "written in key format 1; rewrite it in format 2 (specs/014-design-review-eval/contracts/answer-key.md)" |
| `package_id` | equals the file's stem and the set entry's `package_id` |
| `key_only` | optional, `true` only; section 6 |
| the six lists | each optional, default empty. A key with no entry of a list does not grade that list's columns: they read not assessed (FR-021, `scoring.md` section 7) |

The model is strict (`findings.ReviewModel`, `findings.py:60-61`): an unknown field is refused,
never ignored.

### 2.2 Fields every entry has

| Field | Rule |
|---|---|
| `id` | `D-<n>` known defects, `C-<n>` correct conditions, `FB-<n>` forbidden entries, `CV-<n>` expected coverage, `U-<n>` unanswerable requests, `Q-<n>` question counts (the last two as `questions.md` section 5 writes them); unique across the key. The prefix tells a reader of a scorecard which list an id came from, and it is checked. `FB-`, not `F-`: a scorecard also lists finding ids, `F-001` (`findings.py:108`) |
| `tag` | `held_out` or `tuned_on`, required on every entry (15A, FR-031). Held out is recorded here and nowhere else (D7): the set's package flag is derived from it (`scoring.md` section 6) |
| `held_out_against` | required when `tag` is `held_out`, refused otherwise: `{"prompt": <sha256>, "checklist": <sha256>, "tools": <sha256>}` (owner decision 25A adds `tools`: `answer_key.tool_descriptions_digest()`, `digest.canonical_sha256` of `{name: {"description": spec.full_description, "schema": spec.schema}}` over every tool a design review can offer, so every `Args:` entry, which reaches the model as its parameter's schema `description` and not in the full description, is digested too, `cases.md` 5; plan decision RF-64), the first two the digests of `agent/prompts/system_v1.md` (`SYSTEM_PROMPT_FILE`, `agent/runner.py:143` today, moved beside `CHECKLIST_FILE` in `agent/checklist.py` and re-exported by the runner, RF-1) and `agent/checklist_v1.yaml` (`CHECKLIST_FILE`, `agent/checklist.py:20`) through `sha256_of`, the function provenance already uses for the checklist (`cli.py:2326`), over raw bytes; `sha256_of` moves from `benchmark/runner.py:100` to the dependency-free `benchmark/digest.py`, which the runner re-exports (plan decision RF-48), so `current_stamp()` in `benchmark/answer_key.py` names the two files and the tool set once, importing no runner, and is what the generator's stamp, the stamp test and the set summary compare with (`cases.md` 5; plan decision INT-3: the checkouts agree through `.gitattributes` `eol=lf`, the digest never normalises). Lower-case hex of 64 characters. A digest that no longer matches the files or the tool descriptions is **not** a load refusal: the item stays held out until the commit that cites it removes the status (15A); the set summary lists it as stale (US5-2) |
| `description` | non-blank |

### 2.3 Known defects and correct conditions

| Field | Rule |
|---|---|
| `check` | an exact check id, or a family `x.*` (section 3) |
| `component_ids`, `document_ids` | component instance ids and document ids; at least one of the two lists non-empty (FR-003) |
| `references` | required, non-empty, exactly when `check` is a reference-keyed check (section 2.5); refused on any other check. One element per joint, pair, fit or stack the entry covers; no two equal |
| `producer` | known defects only, required: `code` or `model` (SP-12, 16A). Decided by the package's evidence; FR-054 (a) verifies it for committed cases |
| `expected_status` | known defects only, required: `demonstrated`, `suspected` or `unresolved` (13A). `checked_within_scope` is refused: a defect is never expected cleared |
| `id` on a condition | required (SP-5): contradictions and confirmations are reported by condition id |

### 2.4 Forbidden entries

`checks` is a non-empty list of exact ids and `x.*` families (US3-1's "modelling-practice or
hygiene"). `component_ids` and `document_ids` as in 2.3. A forbidden entry never names references:
it stays on parts or documents (FR-003), so a forbidden `hole.*` on a plate covers every joint of
the plate.

Forbidden entries grade only demonstrated and suspected findings (FR-017). R-3's floating-fastener
pass, a `checked_within_scope` joint-map result, is therefore not gradable by a key, and stays
ungraded and visible in the transcript (research §8.13; plan decision SR-21).

### 2.5 References

A **reference-keyed check** is one of these eleven (FR-003, FR-061; research §8.12). Each element
of `references` names one covered item in the shape its kind takes; `scoring.md` section 2.3 reads
the same kinds off a finding.

| Checks | Kind | One element | Resolves against |
|---|---|---|---|
| `fastener.bottoming`, `fastener.engagement`, `fastener.thread_match`, `fastener.head_clearance`, `fastener.unsupported` | joint | `{"fastener": <fastener id>, "hole": <hole id>}` | `package.fasteners`, `package.holes` |
| `fastener.head_fit` | recess | `{"recess": "<hole id>#<n>"}` | the hole id in `package.holes` |
| `hole.coaxiality` | hole pair | `{"holes": [<hole id>, <hole id>]}`, two distinct | `package.holes` |
| `hole.nominal_alignment`, `hole.position_stack` | joint instances | `{"hole_instances": ["<hole id>#<n>", ...]}`, one or more, distinct | the hole ids in `package.holes` |
| `fit.size_only` | fit | `{"bore": <ref>, "shaft": <ref>}` | `tools/refs.resolve_dimension` |
| `stack.worst_case` | stack | `{"contributors": [<ref>, ...], "target": <ref> or null}`, one or more contributors | `tools/refs.resolve_dimension` |

`<ref>` is `{"document_id", "sheet", "annotation"}`, the triple `resolve_dimension` matches on
(`tools/refs.py:73-75`). A hole instance is written as the joint map writes it,
`f"{hole.id}#{number}"` (`checks/joints.py:649`).

**A folded condition is one entry.** The joint map folds joints whose results agree into one
finding whose `inputs` name the first joint only (`checks/joints.py:1185-1226`). An entry keying a
condition the joint map folds names every joint it covers, one element each; keying each joint as
its own entry makes all but one unreachable, which FR-054 (a) fails.

### 2.6 Expected coverage

`item` is a checklist item id. `statuses` is a non-empty set of `checked`, `unresolved`, `skipped`
and `out_of_scope`: the four readings of the report's goal line that a key may expect
(`scoring.md` section 4). "Not reported" is never listable: a goal with no row and no finding is
always a mismatch.

### 2.7 Unanswerable requests and question counts

`questions.md` section 5 fixes both sections' fields (`documents` and `item` for an unanswerable
request; `part_roles`, or `item` with optional `ids`, and `min` and `max` for a count rule), what a
match is, and their load-time refusals (its section 5.3). This contract adds only the fields every
entry has (section 2.2) and runs those refusals at row 11 of section 4, through the one module
`benchmark/questions.py`, so the key loader holds no second copy of them.

## 3. Check patterns

- An exact id: non-empty dot-separated segments of `[a-z0-9_]`, as every check id is today.
- A family: an exact id followed by `.*`. It covers every check that starts with the id and a dot,
  at any depth, never the id itself and never an id that merely starts with the same letters
  (`fastener.*` covers `fastener.head.fit`, not `fastener` or `fasteners.x`; SP-10, US1-2).
- Refused: `*` alone, `x*`, `x.`, a `*` anywhere but a final `.*`, and a family on a known defect or
  correct condition that covers a reference-keyed check (`fastener.*`, `hole.*`, `fit.*`,
  `stack.*`). Such a family would put a joint's thread-match pass and its bottoming defect under one
  entry, so a pass on one rule would clear a defect of another: the sibling credit 19A removed.
  Forbidden entries may use those families (section 2.4). Plan decision AK-4.
- Every exact id, and every family's id, must fall under a goal of the report's words file:
  `finding_groups.goal_of` (`report/finding_groups.py:167-181`) of the id (a family's id with a
  trailing dot) is not `None`. This is the typo guard: `hygeine.*` would otherwise grade nothing
  and pass every test. Plan decision AK-6.

## 4. Load-time refusals

The model's rows (1, 3, 4, 5, 7 and row 6's grammar) run when an `AnswerKey` is built, by the
loader and by the generator alike, each a pydantic `ValidationError` naming the entry, which the
loader re-raises as an `AnswerKeyError`; then the loader's rows (2, 6's typo guard, 8 to 14) run.
Each group runs in the table's order; the first failing row ends the load. Each message names the
entry id, or both ids for an overlap.

| # | Condition | Message gist | Pins |
|---|---|---|---|
| 1 | not JSON, an unknown field, a missing required field, `key_format` other than 2 | the field, or section 2.1's sentence | FR-009 |
| 2 | `package_id` differs from the file's stem or the set entry's | both ids | FR-009 |
| 3 | an id repeated, or with another list's prefix | the id | FR-009 |
| 4 | a known defect with no `producer` or no `expected_status`, `checked_within_scope` expected, any entry with no `tag`, `held_out_against` missing on a held-out entry or present on a tuned-on one | "D-3 states no expected status" and the like | US1-5, FR-031 |
| 5 | an entry naming no parts and no documents | the entry | FR-003 |
| 6 | a check pattern section 3 refuses | the entry and the pattern | US1-2, SP-10 |
| 7 | references missing on a reference-keyed check, present on another, of the wrong kind's shape, empty, or with two equal elements | the entry and the check's kind | FR-003 |
| 8 | two entries that overlap (section 5), for known defect against known defect, known defect against correct condition, and forbidden entry against known defect | both entries | US1-15, SP-9, D7, SC-002 |
| 9 | an expected-coverage `item` not in the checklist; one no goal reads (`goal_of` is `None`: `coverage.closeout`, `report/review_words_v1.yaml:131-185`); two entries whose items one goal reads; a `statuses` value outside section 2.6 | the entry and the item | FR-009, FR-018 |
| 10 | an expected-coverage entry whose goal also reads a known defect's check, unless `statuses` holds `checked` | "a goal holding a finding reads as checked (state issues); expect checked, or drop CV-2" | FR-018, SC-001 |
| 11 | `questions.md` section 5.3's refusals of unanswerable and question-count entries, in its order (their id resolution only with the package present, as row 13) | the entry, as that section words it | FR-009, FR-019, FR-060 |
| 12 | section 6's key-only rows | the package | US1-16, D7 |
| 13 | with the package present: a component, document, hole or fastener id that is not in the package; a hole instance whose hole id is not, or whose suffix is not `#` and a positive integer; a dimension reference `resolve_dimension` refuses, with its message (none, several, or a native dimension while `DRAWING_BINDING_VALIDATED` is false, `tools/refs.py:87-97`). Component and document ids are looked up as `ToolContext.entity_kind` looks them up (`tools/context.py:433-446`), the rule the product applies to the same ids | the entry and the id | FR-009 |
| 14 | with the package present: a reference whose owner the entry does not name: a hole's or fastener's `component_id` not in `component_ids`, a dimension's `document_id` not in `document_ids` | the entry, the reference and its owner | FR-003 |

Row 10 exists because the report's reader reads a goal holding any finding other than a pass as
`issues` (`report/finding_groups.py:231-232`), which a key reads as `checked` (`scoring.md`
section 4): a key expecting `unresolved` on a goal where it also expects a defect found would count
a correct review as a coverage mismatch. Row 14 makes a reference match imply the part-or-document
overlap FR-003 asks for, so the two conditions of `scoring.md` section 2 can never disagree.

Whether a hole instance's number exists is not checked here: instances are computed by the joint
map from face geometry (`checks/joints.py:619-660`, `_instance`), which the reachability check over the committed
set runs (FR-054 (a)). An entry naming an instance the map never forms is unreachable and fails
there. Plan decision AK-5.

## 5. Overlap

Two entries **overlap** when one finding could match both (SP-9, D7, US1-15; research §8.12).
With `scoring.md` section 2's three conditions, that is:

1. **Checks.** Some check of one equals some check of the other, or one is a family covering the
   other, or both are families and one's id equals, or starts with, the other's id and a dot
   (`rms.*` against `rms.sketches.*`). `fastener` against `fastener.*` never overlaps.
2. **Targets.** Their `component_ids` intersect, or their `document_ids` intersect. Either list
   suffices: an entry naming parts and documents overlaps one that shares only a document.
3. **References.** When both name references (both are then of one exact reference-keyed check,
   section 3), they share an equal element, compared as the set of its references. Two
   `fastener.thread_match` defects on different screw-and-hole pairs between the same two parts do
   not overlap and load; two fastener-joint entries covering one joint do, and are refused
   (US1-15). A forbidden entry names no references, so against a reference-keyed defect only 1 and
   2 apply.

Refused pairs: known defect and known defect, known defect and correct condition, forbidden entry
and known defect. Allowed: a forbidden entry overlapping a correct condition (US3-1) or another
forbidden entry, and two correct conditions; `scoring.md` section 3 counts such a finding once.
The test is the matcher's own primitives (`benchmark/matching.py`, `scoring.md` section 2), never a
second implementation.

## 6. Key-only keys

A key is **key-only** when its package is not built (today `rms-part`, whose `benchmarks/native/
rms-part/RECIPE.md` is not yet run on a seat). The key says so with `"key_only": true`:

- `key_only` with `package=None`: loads, every row of section 4 but 13 and 14 applied, and the key
  records `ids_unchecked` naming the missing package (US1-16).
- `key_only` with a package present: refused, "the package now exists; remove key_only so its ids
  are checked".
- no `key_only` with `package=None`: refused, naming the missing package. A mistyped package path
  is never read as key-only.
- `score_run` refuses a set naming a key-only key: "{package}: its key is key-only (package not
  built); it cannot be scored" (D7).

Plan decision AK-3: the marker is explicit, so a missing package is never mistaken for an unbuilt
one.

## 7. The two committed keys (FR-010)

### 7.1 `cover-blind-tap`, regenerated

The case is regenerated by the generator from its case spec (FR-010, FR-027, US5-4), on the
package rebuilt with hole and fastener rows and ingested drawing sheets (research D8, §8.14). Its
key holds, at least:

| Id | Entry |
|---|---|
| `D-1` | `fastener.bottoming`, one element per screw-and-tapped-hole joint (the four screws), `expected_status` `unresolved`, `producer` as the case spec decides and FR-054 (a) verifies (a PDF-ingest package carries no placement geometry, so the joint map cannot place the screws and the defect is expected model-produced). Exact, not `fastener.*`: a thread-match pass on the same joint must not clear it (section 3). Reachable only through 19A's references on the unresolved path (`scoring.md` section 10) |
| `D-2` | `drawing.manufacturing_inputs` on the housing's drawing document, `expected_status` `unresolved`, `producer` `model`: `record_drawing_finding` writes `suspected` or `unresolved` only (`tools/session.py:456-529`), and a value missing from a drawing is `unresolved` |
| `C-1` | `fit.size_only`, the spigot fit, with its bore reference on the housing's drawing document (`Ø40 +0.025/0`) and its shaft reference on the cover's (`Ø40 -0.009/-0.025`); `document_ids` names both drawing documents, as row 14 requires (`cases.md` 6.4). The housing's drawing document also carries D-2: the generator's drawing-document rule does not apply to this pilot-only, all-tuned-on case (`generator.md` 10 row 5; plan decision RF-12), and the two entries' checks differ, so they do not overlap (section 5) |

Every entry is `tuned_on` (prompt-encodes-cbt-answer, research §2): the case is never in the pane
study's set (US5-4).

### 7.2 `rms-part`, hand-kept and key-only

`benchmarks/answer_keys/rms-part.json` is rewritten in place, by hand, with no other change to its
entries:
- `key_format: 2`, `key_only: true`;
- every known defect `producer: "code"` (every rule is graded by an argument-free RMS tool the
  pre-run calls, research §2 rms-key-measures-code) and `expected_status` the status its rule's
  registered severity maps to (`checks/rules/results.py:67-68`, `checks/rms/registry.py:72`); a
  test holds the two equal, so the hand-kept key cannot drift from the rules;
- the 18 correct conditions ids `C-1` to `C-18` in file order (SP-5);
- every entry `tuned_on`. The case is key-only and in no study; tagging it tuned-on keeps digests off
  a key no run reads. Plan decision AK-7.

Under the new matcher its 18 correct conditions start counting contradictions as false alarms
(research §4 cross-check). That is correct, and a reason the scorer lands before any study is
scored (12A).

## 8. What is not in a key

- Scripted answers: the case file (`scripted-answers.md`).
- The evidence a model-produced defect withholds, and the anchor or analyst-found defect a case
  represents: the case spec (FR-027, FR-029).
- The set's package `held_out` flag: derived from the tags and checked at scoring
  (`scoring.md` section 6).
- R-8's "profile likely wrong" line: hygiene writes one `hygiene.revision_present` result per
  document (`checks/hygiene.py:384-387`) and no zero-match line at `be01974` (the only one is the
  part-number convention's, `checks/part_roles.py:194`), so R-8's key grades its forbidden hits
  only (research §3 R-8, §8.13). Plan decision SR-22.

## 9. Tests

Each fails before its behaviour exists (constitution III).

`reviewer/tests/unit/test_answer_key.py`, the one key test file (`questions.md` section 9 puts its
section 5.3 rows here too), over fictional keys and `tests/support` packages:
1. a key in format 1 (today's shape) is refused with section 2.1's sentence; a format 2 key with
   every list loads (FR-009);
2. `package_id` against the stem and the set entry (row 2);
3. a repeated id; an id with another list's prefix (row 3);
4. a known defect with no expected status, with no producer, with `checked_within_scope`; any
   entry with no tag; a held-out entry with no digests; a tuned-on entry with digests; a digest of
   the wrong length (US1-5, FR-031);
5. an entry naming neither parts nor documents (FR-003);
6. patterns: `x.*` loads; `*`, `x*`, `x.`, `x.*.y` refused; `fastener.*`, `hole.*`, `fit.*` and
   `stack.*` refused on a known defect and on a correct condition and loaded on a forbidden entry;
   `hygeine.*` refused by the typo guard, `hygiene.*` loaded (SP-10, US1-2, AK-4, AK-6);
7. references: missing on `fit.size_only`; present on `rms.folders.present`; a joint element on
   `hole.coaxiality`; one hole in a pair; two equal elements (FR-003);
8. overlaps (US1-15, SC-002): a `hygiene.*` defect and a `hygiene.revision_present` condition on
   intersecting parts, refused naming both; two `fastener.bottoming` entries covering one joint,
   refused; two `fastener.thread_match` defects on different pairs between the same parts, loaded;
   a forbidden `fastener.*` against a reference-keyed fastener defect on the same plate, refused; a
   forbidden `rms.*` against an `rms.folders.present` condition on the same part, loaded (US3-1);
   `fastener` against `fastener.*`, loaded; `rms.*` against `rms.sketches.*` defects on one part,
   refused; a wildcard condition against an exact defect, refused; two entries sharing only a
   document, refused; a fit defect and a fit condition on the same sheet with different dimension
   pairs, loaded;
9. coverage: an item not in the checklist; `coverage.closeout` (read by no goal); `interfaces.fit`
   and `interfaces.stack` in two entries (one goal); `issues` as a status; a goal holding a known
   defect with `statuses: ["unresolved"]` refused and with `["checked", "unresolved"]` loaded (FR-018,
   row 10);
10. question sections: each refusal of `questions.md` section 5.3, reached through `load_answer_key`
    at row 11 and named as that section words it (FR-060, FR-019);
11. key-only: `rms-part`-shaped key with no package loads with `ids_unchecked` naming the package;
    with the package present, refused; a key without the marker whose package is missing, refused
    naming the package (US1-16, AK-3);
12. id resolution with the package: an unknown component, document, hole and fastener; a hole
    instance with an unknown hole id and one with the suffix `#0`; a dimension reference naming
    nothing, one naming two dimensions, and one naming a native dimension while the switch is off,
    each with `resolve_dimension`'s message (FR-009);
13. ownership: a hole whose component the entry does not name; a dimension on a document it does
    not name (row 14);
14. the model alone (the generator's path): an `AnswerKey` built in memory with a repeated id, a
    `fastener.*` defect or a reference of the wrong kind's shape raises a `ValidationError` naming
    the entry, with no loader involved; the model's rows run before row 2, so a key failing both
    is named by the model's row (RF-1);
15. `holds_held_out()` and `held_out_model_defect_ids()` on keys with no held-out entry, a held-out
    condition only, and held-out defects of both producers (RF-67).

`reviewer/tests/unit/test_committed_answer_keys.py`, never skipped (the conftest's native-package
skip, `reviewer/tests/conftest.py:70-72`, does not apply: `rms-part` needs no package):
1. every key under `benchmarks/answer_keys/` loads, `cover-blind-tap` against its committed package
   and `rms-part` key-only (FR-009, FR-010);
2. `rms-part`: every defect `producer` `code`, every expected status equal to its rule's registered
   severity mapping, conditions `C-1` to `C-18`, every entry tuned-on (FR-010, AK-7);
3. `cover-blind-tap`: every entry tuned-on; `D-2` expected unresolved on the housing's drawing
   document; `C-1` with its bore and shaft references and both drawing documents (US5-4). In the
   scorer slice this asserts the interim key, `D-2` and `C-1` only (plan decision INT-15); from the
   generator slice, the regenerated key, `D-1` expected unresolved over the four joints as well;
4. SC-002 over every committed key: for each known defect, the oracle finding `scoring.md`
   section 9.2 builds for it matches that defect and no other known defect, `rms-part`'s built on
   its stand-in package (RF-15);
5. SC-001 over every committed key: the oracle and null reviews of `scoring.md` 9.2, each written
   as a package folder with its one-line stream and its stored request results and scored through
   the scorer's per-package function (`score_run` refuses a key-only key): zero on every column the
   key grades, `null` exactly where the key has no entry of the list a column reads and on the two
   answer-log columns, `rms-part` through its stand-in (US1's Independent Test; RF-15, RF-58).

`reviewer/tests/unit/test_cli.py`: the `answer_keys` fixture (`:2395-2417`) rewritten in format 2
through the one test helper `tests/support/answer_keys.write_key` (`scoring.md` 11; plan decision
RF-49), its `drawing.manufacturing_inputs` defect keyed to `doc:1`, a document the minimal support package
holds (`tests/support/packages.py:97-101`), since it names no drawing document, and tagged
`held_out` with `held_out_against` the `current_stamp()` that `write_key` computes, since the
fixture's set marks `cover` held out (`:2373-2393`) and `score` refuses a flag its key does not back; the command's
wiring, not the check, is what the fixture tests (research §4 cross-check). Plan decision SR-23.

`reviewer/tests/integration/test_answer_key_isolation.py`: its one `load_answer_key` call (`:41`)
and the key assertions around it (`:40-47`: the ids `D-1` and `D-2`, `D-1`'s four components, the
condition's check) are deleted in the scorer slice. The interim key drops `D-1` (INT-15) and the
generator slice rebuilds the package with new ids, so those assertions would go stale twice, while
the unmarked `test_committed_answer_keys.py` above asserts the committed keys on every machine. The
module is marked `integration`, so it runs only where the native package is present, and a stale
assertion there would go red only on that machine (plan decisions RF-26, RF-49). Its isolation
checks stay: the pilot set never resolves into `answer_keys`, and `run_benchmark` never passes a key
path, its fake (`:56-64`) taking the `attempt` keyword from the parity slice (`benchmark-run.md` 5;
RF-44) and its call the `PreflightedSet` from the scripted-answers slice. No new pin of this feature
goes in it.
