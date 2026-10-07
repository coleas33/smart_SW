# Contract: Cases, the Committed Set and the Set File

Normative for FR-028 to FR-033, FR-054, FR-056's set half, SC-004, SC-014, and User Story 5 with
`generator.md`. Research §3, D7, D8, D13, §8.6, §8.7, §8.8 (the set's half), §8.11, §8.13; owner
decisions 5A, 7A, 10A, 14A, 15A, 16A, 23A. **Sections 4 and 5 are what the other contracts call
"the benchmark-set contract".**

What this contract fixes: where every case file lives and who may read it; the set file, its
private entries and its refusals; the held-out stamp; what the committed set holds and why it
reaches the floor; the offline validation every committed case passes; and the set summary. The
key's format and load-time refusals are `answer-key.md`; the case file's format and run-start
refusals are `scripted-answers.md` section 2; how a finding matches an entry is `scoring.md`
section 2; how a case is written is `generator.md`. None is restated here.

Line numbers are at `be01974`; paths are under `reviewer/src/swreview/` unless another root is
given. Every example value is fictional.

## 1. Files and their readers

| Path | Written by | Read by | Committed |
|---|---|---|---|
| `benchmarks/packages/<case>/package.json`, `meshes/*.glb` | the generator | the reviewer, through `ir/loader.load_package` | yes |
| `benchmarks/answer_keys/<case>.json` | the generator; `rms-part.json` by hand (`answer-key.md` 7.2) | `benchmark/answer_key.py` only (`answer-key.md` 1) | yes |
| `benchmarks/case_files/<case>.json` | the generator | the answer driver only (`scripted-answers.md` 6); the generator's tests load them through its loader (`generator.md` 11) | yes |
| `benchmarks/sets/committed.json`, `benchmarks/sets/pilot.json`, `benchmarks/sets/pane-smoke.json` | the generator | `benchmark run`, `score`, `compare`, the report, the summary | yes |
| a private set, its keys and case files | the owner, outside the repository | the same readers | never |
| `reviewer/tests/benchmark_cases/` | people: the case specs and the generator (`generator.md`) | the generator, the validation | yes |

Hand-kept under `benchmarks/`: `README.md`, `answer_keys/rms-part.json` (key-only) and
`native/rms-part/RECIPE.md`. `packages/bracket-assy/` is neither written nor stale: it is the test
suite's native-package slot (`reviewer/tests/conftest.py:27`), placed per machine, named by no set
and not ignored by git, so the generator's stale scan and its regeneration test skip it (plan
decision RF-75). Every other file under `packages/`, `answer_keys/`, `case_files/` and
`sets/` is written by the generator, and the regeneration test (`generator.md` section 11) fails on
a file it did not write: nothing is hand-edited and nothing stale survives.

**`cover-blind-tap`'s ingest inputs move out** (plan decision CS-3). Its folder holds `bom.csv`,
`manifest.json`, `drawings/*.pdf` and `notes.md` beside `package.json`; three ingest tests read the
first three as parser inputs (`reviewer/tests/unit/test_pdf_parser.py:24, 498`,
`test_ingest_bom.py:20`, `test_ingest_manifest.py:23`). They move byte for byte to
`reviewer/tests/fixtures/ingest/cover-blind-tap/`, those tests and
`reviewer/scripts/make_cover_blind_tap_pdfs.py` re-pointed, so the benchmark folder holds only what
the generator writes. `notes.md` is not kept: it states the expected result inside a folder the
reviewer loads (research §2, answer-key-isolation-sound's residual). The golden fixture
`reviewer/tests/golden/fixtures/cover-blind-tap/` is another package and is untouched.

## 2. Case identity

- **Case id** = package id (the set's and the key's `package_id`) = key stem = case-file stem =
  package folder name. The IR's own `package_id` inside `package.json` is another value, a UUID
  (`generator.md` 5.5); neither is set from the other. Lower-case words
  and numbers joined by hyphens, every word from the case vocabulary (`generator.md` section 8):
  `brun-1`, `brun-1-twin`, `kalo-fit-1`, `mir-sitting`. `cover-blind-tap` keeps its id.
- **Design**: the template a case is built from, one vocabulary word (`brun`). A design is the
  spec's unit of FR-028's "at least 8 designs": a template with its twins and variants.
- **Twin**: `<case>-twin`, derived from its case by the generator (`generator.md` section 4).
- **Represents**: the anchors (R-1 to R-8) and analyst-found defects (AF-1 to AF-3) a case stands
  for (FR-029). The case spec records it; the set entry carries it (section 4.1).

## 3. The case file

`scripted-answers.md` section 2 fixes its location, format and run-start refusals. The generator
writes one for exactly the cases whose spec scripts answers: the anchors of section 6.3. **No core
case has one** (plan decision CS-9): its defects need no answer, and any question its reviews ask is
unscripted, alike in both arms (D3). So every held-out review is one turn, and the pane default
that acts only between turns (lever 14) cannot move the verdict: whether core cases also script one
answer was owner question 8, answered B (owner decision 30A: they do not), so the verdict names that
setting as untested by it (`verdict.md` 6; plan decision RF-14). A case file scripts answers only, never a follow-up message
(`scripted-answers.md` 3, QA-20), so R-2's follow-up question about the drawing is not replayed; its
graded structure (section 6.3) does not need it.

## 4. The set file

### 4.1 Format

```json
{
  "name": "committed",
  "packages": [
    {"package_id": "brun-1", "path": "benchmarks/packages/brun-1",
     "key": "benchmarks/answer_keys/brun-1.json",
     "held_out": true, "design": "brun"},
    {"package_id": "brun-1-twin", "path": "benchmarks/packages/brun-1-twin",
     "key": "benchmarks/answer_keys/brun-1-twin.json",
     "held_out": true, "design": "brun", "twin_of": "brun-1"},
    {"package_id": "kalo-fit-1", "path": "benchmarks/packages/kalo-fit-1",
     "key": "benchmarks/answer_keys/kalo-fit-1.json",
     "case_file": "benchmarks/case_files/kalo-fit-1.json",
     "held_out": false, "design": "kalo", "represents": ["R-3"]}
  ]
}
```

A private set (never committed):

```json
{"name": "private-slice",
 "packages": [
   {"package_id": "small-assembly", "path": "D:/ExampleVault/slice/small-assembly",
    "key": "D:/ExampleVault/slice-keys/small-assembly.json",
    "case_file": "D:/ExampleVault/slice-keys/small-assembly.case.json",
    "held_out": true, "design": "small-assembly", "represents": ["R-1", "R-2", "R-3"]}]}
```

| Field | Rule |
|---|---|
| `package_id` | required; unique in the set; equals the key's `package_id` (`answer-key.md` row 2) and the case file's |
| `path` | required: the package folder. Relative (POSIX separators) resolves against the repository root (4.2); absolute is taken as written |
| `key` | the key file. Relative for a committed entry, absolute for a private one. A set in which some entry names a key is **keyed**, and then every entry names its own (row 6). A set in which no entry names one is **keyless**, as every set written before this feature is: its keys are read as today, `<--answer-keys>/<package_id>.json` (`benchmark/scorecard.py:477-490`), and row 6 does not apply (plan decision RF-4) |
| `case_file` | optional; `scripted-answers.md` 2.1 |
| `held_out` | derived from the key (4.5) |
| `design` | the case's design; for a private entry, the owner's name for the real design (near-duplicate designs share one name, spec Edge Cases) |
| `twin_of` | optional: the package id this entry is the clean twin of (FR-028); names another entry of the same set |
| `represents` | optional: anchor and analyst-found ids, each once, from R-1 to R-8 and AF-1 to AF-3 |
| `case_file_sha256` | never written in a set file; computed at load and carried into the saved set (`scripted-answers.md` 6) |

`BenchmarkPackageRef` (`benchmark/sets.py:22-27`) gains these fields, each optional in the model so
that a saved set written before this feature still loads (`cli.py:2313-2314`). The committed set
files carry `key`, `held_out` and `design` on every entry (section 9's committed-set test); absent
optional fields are omitted, never written as `null`. The model stays strict
(`findings.ReviewModel`, `findings.py:60-61`). Plan decision CS-13.

### 4.2 Loading

`load_set(path, *, root=REPO_ROOT)` (`benchmark/sets.py:35`), the one core every set reader calls;
`load_saved_set(path, *, root=REPO_ROOT)` is a thin caller of it for a run folder's saved copy
(`provenance.md` 6.1), which also accepts relative entries and each entry's `case_file_sha256`:

- **The root** is the running checkout's, `REPO_ROOT`, moved from `benchmark/runner.py:52` to
  `benchmark/sets.py` (the runner imports it back), and a keyword parameter so a test passes a
  temporary one. It decides every rule below: resolution, "private", row 6's two sides and
  `saved_form()`; `provenance.md` 6.1 cites this one rule. A set file inside
  `<root>/benchmarks/sets/` resolves relative paths against the root, which is today's grandparent
  rule whenever the two agree (`benchmark/sets.py:44-45`). A set file anywhere else may name only
  absolute paths (refusal 3): a private set kept outside the repository never resolves a path
  against its own location, and a set file inside another checkout's `benchmarks/sets/` (another
  worktree's, say) that names a relative path is refused naming both roots, since resolving it
  against either would give one set two saved forms and two `set_digest`s. Plan decisions CS-14
  and RF-4.
- Every path is resolved (`Path.resolve`), so a junction cannot smuggle a path past the rules
  below, as today.
- An entry is **private** when its resolved package path lies outside the root.
- **Withheld paths**: every resolved `key` and `case_file`, and the folder each lies in, besides
  the fixed segments `benchmarks/answer_keys` and `benchmarks/case_files` (`ir/loader.py:23`,
  extended by `scripted-answers.md` 6).
- `case_file_sha256` is filled from each named case file's bytes (`scripted-answers.md` 6).
- **The file form and the saved form** (plan decision RF-54). `BenchmarkSet.file_form(*, root) ->
  bytes` and `saved_form(*, root) -> bytes` share one entry serializer: each path inside the root as
  a root-relative POSIX string and each private path absolute (a `Path` field would otherwise
  serialize with the platform's separators, `benchmark/sets.py:26`); UTF-8 JSON, indent 2, LF, a
  final newline; absent optional fields omitted. `file_form` is the committed set file's form, which
  the generator writes (`generator.md` 7) and which never holds `case_file_sha256`; `saved_form` adds
  each entry's `case_file_sha256`, and is what `benchmark run` saves into the run folder and digests
  into `set_digest` (`cli.py:2313-2314, 2327`), so the digest is the same from any checkout (FR-051;
  research §8.8, whose run-folder half is the parity contract's).

### 4.3 Refusals at load

Every refusal is a `SetError` (a `ValueError`, so the command line prints one line and exits 1,
`cli.py:260-269`) whose message starts "benchmark set {file name}:"; the guard's own refusal stays
`AnswerKeyAccessError` (`ir/loader.py:26-27`). In this order:

| # | Condition | Message gist | Pins |
|---|---|---|---|
| 1 | unreadable, not JSON, an unknown field, a missing required field | the field | FR-030 |
| 2 | a `package_id` named twice | the id | FR-030 |
| 3 | a relative path in a set file outside `<root>/benchmarks/sets/` | "a set file outside benchmarks/sets names every path absolutely" and the entry; for a file in another checkout's `benchmarks/sets/`, "{set} belongs to the checkout at {its grandparent}, and this code runs from {root}: run it from that checkout" | FR-030, FR-051 |
| 4 | a package path under `benchmarks/answer_keys` or `benchmarks/case_files` | `reject_answer_key_path`'s message (`ir/loader.py:46-62`) | FR-030, US4-9 |
| 5 | a package path that is, or lies under, a withheld path of any entry; a key or case file that lies under any entry's package path | both paths: "the reviewer reads the package folder; keep keys and case files outside it" | FR-030, US5-11 |
| 6 | in a keyed set (4.1): an entry with no `key`; a private entry whose key or case file lies inside the root; a committed entry whose key or case file lies outside it. A keyless set is not checked here | the entry: "a committed case's key and case file live in the repository, a private case's outside it", or "every entry of a keyed set names its key" | FR-030, FR-051 |
| 7 | `twin_of` naming no other entry of the set; a `represents` value outside R-1 to R-8 and AF-1 to AF-3, or repeated | the entry and the value | FR-028, FR-029 |

Row 5 is the key-isolation guard for every key and case file a set names (D7; `answer-key.md` 1;
`scripted-answers.md` 6): a private key or case file cannot sit in, or contain, a folder the
reviewer loads. Plan decision CS-15.

### 4.4 Refusals before any review

`benchmark/runner.preflight_set`, which `run_benchmark` (`benchmark/runner.py:201`) requires
(`benchmark-run.md` section 3 row 4; plan decision INT-14), after the profile preflight (FR-050) and
before the case-file checks (`scripted-answers.md` 2.3), checks the set's files exist. Each failure exits 1
with one line and creates no package folder:

- every package folder holds a `package.json`: all missing ones are named in one message, "benchmark
  set {name}: {n} package(s) missing: {id} at {path}; ..." (US5-3, FR-030);
- every named key exists as a file. The run **stats** it and never opens it (FR-032): a missing
  private key found by `benchmark score` after the paid runs would waste them. Plan decision CS-16.

### 4.5 The `held_out` flag

`held_out` is `true` exactly when the key holds at least one entry tagged `held_out`, the model's
`AnswerKey.holds_held_out()` (`answer-key.md` 1 and 2.2; research §8.7; plan decision RF-67). The generator writes it for the committed sets; the owner
writes it for a private set. `benchmark run`'s refusal of a study set holding nothing out reads the
flags only and never opens a key (`cli.py:2226-2245`). `score` checks every flag against its key
(`scoring.md` section 6); compare, which reads no key, checks each scored package's flag against its
scorecard's `graded_items`, the key's tags as the scorer copied them (`provenance.md` section 2; plan
decision RF-39); each refuses a mismatch naming the package (US5-12). A set stores no count: the
held-out model-produced count is computed from the keys (FR-032) and printed by the summary
(section 8).

### 4.6 Private sets

A private set lives outside the repository and names private entries only. The pane study's set
holds committed cases only: compare refuses a pane study whose saved sets name a private package
(`verdict.md` section 7, row 2; FR-056). The private slice is its own study, with the real profile,
its own row and never the verdict (23A). Its run folders, keys, case files and report pages never
enter the repository; the FR-051 test and section 9's committed-set test fail if one does.

## 5. Held out, tuned-on and the stamp (FR-031, 15A)

- **One record.** Every graded item's tag, and a held-out item's `held_out_against` digests, live
  in its key and nowhere else (`answer-key.md` 2.2; D7). For a committed case the case spec is their
  source: a held-out seed carries the stamp `tests/benchmark_cases/stamps.py` `CURRENT`, a tuned-on
  one its reason (`generator.md` section 2).
- **The digest** of `agent/prompts/system_v1.md` (`agent/runner.py:143`) and of
  `agent/checklist_v1.yaml` (`agent/checklist.py:20`) is `sha256_of` over the file's raw bytes, the
  function provenance's `checklist_digest` and `prompt_digest` use, so a key's stamp and a run's
  record of the same file are one number. It moves from `benchmark/runner.py:100-102` to the
  dependency-free `benchmark/digest.py`, which the runner re-exports, so the key loader and the set
  module import it without loading the runner (plan decision RF-48).
  `benchmark/answer_key.current_stamp() -> Stamp(prompt, checklist, tools)` names the two files and
  the tool set once (`answer-key.md` 2.2). The checkout that made this contract holds both files with CRLF endings
  (`git ls-files --eol`: `i/lf w/crlf`, under `* text=auto` and `core.autocrlf true`) while an LF
  checkout of the same commit does not; the checkouts are made to agree instead of the digest
  normalising: `.gitattributes` gives both files `eol=lf`, `test_line_endings.py` fails on a
  working copy that still holds a carriage return, naming the files to check out again, and the pane
  studies refuse to start on one (`provenance.md` sections 3.2 and 6.5). Plan decision INT-3
  (research §9) supersedes this contract's first draft (CS-12: CRLF read as LF), which would have
  made a key's stamp and a run's `checklist_digest` two different numbers for one file on Windows.
- **The tool descriptions** (owner decision 25A; plan decision RF-64). `tools` is
  `answer_key.tool_descriptions_digest()`: `digest.canonical_sha256` of `{name: {"description":
  spec.full_description, "schema": spec.schema}}` over every tool function a design review can
  offer, `TOOL_FUNCTIONS`, `COMPACT_QUERY_TOOL_FUNCTIONS`, `FINDING_DETAIL_TOOL_FUNCTIONS`,
  `BRIDGE_TOOL_FUNCTIONS`, `standards_tools()` and `drawing_tools()` (`tools/registry.py:203-274`),
  each through `spec_for` (`:444-450`). The full description (`agent/providers/schema.py:468-474`) is
  what lever 2's off arm sends and holds the first paragraph its on arm sends. It holds neither the
  `Args:` entries nor anything else of the schema: each `Args:` entry is sent apart, as its
  parameter's `description` in the tool schema (`canonical_schema`, `agent/providers/schema.py:208-236`;
  `RecordedTool.schema`, `tools/registry.py:523-524`), on both arms of every lever, and review policy
  sits there on purpose (`request_evidence`'s "never guess a fit class, tolerance or thread depth",
  put in its argument descriptions "and not in the Notes", `tools/session.py:95-99`). Digesting the
  whole schema beside the full description covers every word the model reads of a tool, on either
  arm, with no selection rule. The remodel
  tools are left out: no design review is offered them (`ToolRegistry._offered`, `:910-942`).
  Docstrings are read from Python source with universal newlines, and the schema is built from them
  and the signatures by the one pydantic `reviewer/uv.lock` resolves (`:1169-1170`), so the digest is
  one number on every checkout with no `.gitattributes` rule. No run records it: a run's `commit`
  fixes the docstrings, and no reader compares a run with it. A "tool description" below is this
  whole text: the docstring's body and Notes and every `Args:` entry.
- **The stamp test.** Every held-out item of every committed key has `held_out_against` equal to
  `current_stamp()`. When the prompt, the checklist or a tool description changes, it fails listing
  each item ("brun-1 D-2") with the current digests and says: "the prompt, checklist or tool
  descriptions changed: in this commit, move every
  held-out item the change cites to tuned-on in its case spec, set `stamps.CURRENT` to the digests
  above, and regenerate." Which items a change cites is the author's statement; the test makes the
  statement unavoidable in that commit, and the tag change in the diff records it (US5-7).
- **Private keys** are not tested: they are not in the repository. The summary lists their stale
  items (section 8).
- **Scope.** The stamp covers the two files 15A names and, by 25A, the tool descriptions the model
  reads: an item loses held-out status in the commit of a prompt, checklist or tool-description
  change that cites it.

## 6. The committed set

### 6.1 Sets and counts

`benchmarks/sets/committed.json` is the pane study's set: every generated case but
`cover-blind-tap`. `benchmarks/sets/pilot.json` keeps its purpose, the lever studies' smoke set,
and holds `cover-blind-tap` only, regenerated with the new fields. `benchmarks/sets/pane-smoke.json`
is the pane study's smoke set, quickstart P0's (owner decision 35A; plan decision RF-89):
`committed.json`'s entries for `kalo-1` and `kalo-fit-1`, each equal to its `committed.json` entry and
in that file's order, one held-out core case and the anchor with a case file, so the answer driver
runs; the generator writes it from one constant, `PANE_SMOKE_CASES`.

| | Packages | Held-out model-produced defects |
|---|---|---|
| Core cases: 9 designs × 2 | 18 | 36 |
| Their clean twins (twin rule B, 6.2) | 18 | 0 |
| Anchor and analyst-found cases (6.3) | 11 | 0 |
| `committed.json` | **47** | **36** |
| `pilot.json` (`cover-blind-tap`, 6.4) | 1 | 0 |
| `pane-smoke.json` (`kalo-1`, `kalo-fit-1`; quickstart P0, 35A) | 2 | 2 |

36 meets the floor of 34 with a margin of 2 (FR-028). No design holds more than 4 of 36 (11%, the
cap is a fifth), no package more than 2, and no package two of one judgement family.

**Paid reviews** (counts only; the cost gate prices them, `verdict.md` section 10): 47 per arm per
repetition; a pane study at R repetitions is 94 × R reviews (282 at 3, 564 at 6, 940 at 10); the
paid pilot's off arm, 47 per repetition (27A: three repetitions). Twin rule A, which owner decision
24A declined, would have held 65 packages, 130 × R.

### 6.2 Core designs and cases

Each core case holds exactly two held-out model-produced defects, of two different judgement
families, and nothing else planted. Its twin is the same package with both seeds in their clean
form, each removal keyed as a correct condition (**twin rule B**: one stricter twin per case, with no
defect at all; research §8.11's second option). Rule B keeps no defect in a twin, so no twin entry
needs a marker; it costs 18 packages where rule A, a twin per removed family, costs 36. Owner
decision 24A; plan decision CS-4.

| Design | Shape | Case 1 | Case 2 |
|---|---|---|---|
| `kalo` | a plate on two dowel pins, a cover screwed to it | `thread_mismatch_unplaced` + `fit_limit_missing` | `bottoming_unplaced` + `callout_drill_only` |
| `tessa` | a bracket on a base: M5x0.8 tapped holes, dowel holes (the big assembly's bracket region) | `thread_mismatch_unplaced` (AF-1) + `fit_transition` | `coaxiality_undrawn` (AF-2) + `callout_thread_differs` |
| `okta` | a clevis, a pin through both legs, two bushings; a base with three dowel-hole pairs | `coaxiality_drawn` + `fit_interference_unintended` (US5-16) | `engagement_unplaced` + `callout_count_differs` |
| `brun` | a shaft in a bearing housing: seat bore, spacer stack, cover screws | `coaxiality_drawn` + `stack_out_of_gap` | `fit_transition` + `callout_drill_only` |
| `pelin` | a flange coupling: two flanges on a spigot, a bolt circle into tapped holes | `thread_mismatch_unplaced` + `fit_limit_missing` | `stack_out_of_gap` + `callout_thread_differs` |
| `davo` | a motor-mount plate: pilot bore, four tapped holes, two dowels | `coaxiality_drawn` + `fit_interference_unintended` | `stack_out_of_gap` + `callout_count_differs` |
| `rusk` | a carriage on a rail: shim stack, screws into the rail | `bottoming_unplaced` + `callout_thread_differs` | `stack_out_of_gap` + `callout_drill_only` |
| `lori` | a gear cover on a housing: dowels, screws, a shaft bore | `thread_mismatch_unplaced` + `callout_count_differs` | `fit_transition` + `callout_drill_only` |
| `venta` | a two-piece clamp block: cap screws, a clamped bore | `engagement_unplaced` + `callout_thread_differs` | `fit_limit_missing` + `callout_count_differs` |

Case ids are `<design>-1` and `<design>-2`. The seed kinds are `generator.md` section 3.

| Family | Kinds (count) | Held-out model-produced | Expected demonstrated / suspected / unresolved |
|---|---|---|---|
| fastener (joints and alignments) | thread mismatch (4), bottoming (2), engagement (2), coaxiality drawn (3), coaxiality undrawn (1) | 12 | 11 / 0 / 1 |
| fit and axial stack | fit transition (3), unintended interference (2), limit missing (3), stack out of gap (4) | 12 | 4 / 5 / 3 |
| drawing | drill depth only (4), thread differs (4), count differs (4) | 12 | 0 / 8 / 4 |
| interference, part role | none: code decides them (16A) | 0 | |

Every package pairs two of the three model families: 6 fastener with fit or stack, 6 fastener with
drawing, 6 fit or stack with drawing. 28 of 36 defects expect demonstrated or suspected, so a lever
that makes the model hedge shows as flagged below expected (13A). Plan decision CS-5.

**The drawing-document rule** (plan decision CS-8). A drawing-family defect is keyed to a document
(`drawing.manufacturing_inputs` has no references, `answer-key.md` 2.5), so any drawing finding on
that document credits it. Its drawing document therefore carries no other seed and no correct
condition: a case's fit, stack and tolerance dimensions sit on another drawing (the assembly's),
and its drawing seed on the part's own drawing. The generator refuses a spec that breaks the rule
(`generator.md` section 10, row 5). The rule protects held-out drawing defects; it does not apply
to the pilot-only, all-tuned-on `cover-blind-tap`, whose housing sheet carries both its drawing
defect and its fit condition's bore, as its package always has (6.4; plan decision RF-12).

**US5-16** is `okta-1`: the pin passes through both clevis legs, both leg bores and the pin are
drawn on the assembly's sheet, one fit is the defect and the other is clean; the alignment defect is
one of the base's three dowel-hole pairs. Its decoys (section 7) are the other fit, each other pair
and the bore against itself.

### 6.3 Anchor and analyst-found cases

Every anchor is tuned-on (15A); every analyst-found item is held out (15A allows it), including the
code-produced forms, which enter no recall figure whatever their tag (3A) and decide only through
the code guard (D17). Each seed follows research §3 in the example profile's names (FR-027,
`generator.md` section 5). Entry shapes are `answer-key.md` section 2. Plan decisions CS-6, CS-7.

| Case | Represents | Key | Case file |
|---|---|---|---|
| `mir-sitting` | R-1, R-2, R-7, R-8 | The 2026-09-26 sitting in one package, as it happened. **R-1**: the vendor pin (two instances) is unclear by conflict, so code asks the part-roles question: a bought-parts folder and a vendor property (strong, bought) against a hygiene part number with a custom prefix (medium, custom), which `_decide` leaves unclear (`checks/part_roles.py:600-608`); forbidden `rms.*`, `hygiene.*` on the pin; the part-roles question asked exactly once. **R-2**: a same-name drawing candidate beside the assembly and beside the plate, no drawing record; forbidden `drawing.*` on the assembly, plate and pin documents; unanswerable request: the pin's document, no item; expected coverage `drawing.manufacturing_inputs` unresolved. **R-7** (code-produced, demonstrated): the plate's under-defined sketch listed at two depths as `rms.sketches.fully_defined` and `standards.part.sketches_fully_defined`, each its own entry; about 20 loose features, `rms.grouping.all_features_in_a_group`; no global variable, `rms.params.global_variables_present`. **R-8**: every model document carries its revision under `Rev`, never the profile's `DocRev` (`config/standards.example.yaml:57-60`); forbidden `hygiene.revision_present` on each; no "profile likely wrong" line is expected (SR-22) | A-1 part roles, "All bought". No answer to the drawing candidate question: it is asked only when the host opens closed drawings (`checks/drawing_context.py:490-503`, `mode != "opens_closed"` returns `None`), and a benchmark attempt has no bridge, so its read mode is `none` (`tools/drawings.py:79-90`); an entry for it could never be delivered (plan decision INT-8) |
| `mir-sitting-positive` | R-8, R-7, R-1 | The same shape, clean but for one defect: every model document carries `DocRev` but the plate, `hygiene.revision_present` on it (code-produced, demonstrated); the plate's tree compliant, R-7's four checks keyed as correct conditions on it; the pin decided bought (no custom signal), so no question | none |
| `kalo-fit-1` | R-3 | Variant A: the pin in the plate line to line, `hole(hole_type='clearance', size='Ø3.0')`; on the assembly's ingested sheet a "2X Ø3.0 +0.010/0" bore and a pin "Ø3.0 +0.020/+0.014": `fit.size_only` (model, suspected), one element covering both pins. No model dimension, position tolerance or ISO 286 class on the joint's parts (research §3 R-3). At most one question on `interfaces.fit`. The floating-fastener pass stays ungraded (SR-21) | A-1 `interfaces.fit`, the pins and the plate, "press fit" |
| `kalo-fit-2` | R-3 | Variant B: both diameters drawn Ø3.0 with no tolerance, the pin's oversize only as free text in a configuration property: `fit.size_only` (model, unresolved); the same question rule | the same A-1 |
| `kalo-fit-clean` | R-3 | A 3.0 mm pin in a 3.1 mm hole with slip-fit limits: `fit.size_only` as a correct condition on the two dimensions | none |
| `kalo-contact` | R-4, and R-5's twin | Two zero-volume pin-to-plate contacts and one possible row, as `build_small_assembly` writes them; forbidden `interference.static` on the pins and the plate | none |
| `kalo-contact-positive` | R-4, AF-2 | A second pin 0.750 mm off the axis of a 3.1 mm hole, overlapping the plate by 1.237 mm³ (`reviewer/tests/fixtures/mechanical/generate_fixtures.py:444-445, 679`): `interference.static` on that pair (code, demonstrated, tuned-on, R-4); the joint map's alignment result on that joint, keyed by its hole instances (code, held out, AF-2), with the check and status the package's evidence supports, which FR-054 (a) confirms | none |
| `kalo-lightweight` | R-5 | Both pins lightweight, their document not opened, no interference row (`tests/support/mechanical.py:471-577`); expected coverage `interference` unresolved or skipped and `interfaces.fit` unresolved; `hygiene.component_not_resolved` on the pin document (code, demonstrated, tuned-on): true of the package (`checks/hygiene.py:259-301`), and unkeyed it would fail FR-054 (a) | none |
| `kalo-empty` | R-6 | M8 counterbored through holes and an M6x1.0 tapped hole with no screw; forbidden `fastener.*`, `hole.*` on the plate; at most one question on `fasteners`; expected coverage `fasteners` unresolved or out of scope | A-1 `fasteners`, the plate, "screws go in a seperate assy" (terse and misspelt, as the engineer's) |
| `kalo-empty-positive` | R-6, AF-1 | An M4-0.7 screw seated on the axis of an M5x0.8 tapped hole: `fastener.thread_match` on that joint (code, demonstrated, held out, AF-1) | none |
| `tessa-groups` | AF-3, R-4 | Two positive interference groups of about 250 mm³ and zero-volume contacts between other, disjoint parts: `interference.static` on each positive pair (code, demonstrated, held out, AF-3); forbidden `interference.static` on the contacts' parts (tuned-on, R-4) | none |

AF-1's and AF-2's model-produced forms are the core cases `tessa-1` and `tessa-2` (6.2).

Three choices this table makes, each against the anchor as recorded:
- R-2's assembly and plate get their own stems, each with its own same-name drawing, rather than
  sharing one stem as the recorded design did: a shared stem makes the example profile's hygiene
  raise `hygiene.duplicate_part_number` between them, a finding no engineer has judged (research §3,
  "Gaps and candidates"), which the key could only guess at (plan decision CS-10).
- R-7's two families are both keyed rather than cross-referenced: the key's overlap rule refuses
  neither, since their checks differ (`answer-key.md` 5).
- Any other finding the example profile raises for R-8's missing `DocRev` (a standards revision
  rule) joins R-8's forbidden entry; FR-054 (a) names it if one appears.

### 6.4 `cover-blind-tap` (FR-010, US5-4)

Regenerated from its spec, in `pilot.json` only, every item tuned-on (research §2,
prompt-encodes-cbt-answer). It stays PDF-ingest-shaped, as the exported-files package it always
was: BOM-shaped components with the placeholder `persist_ref` gap, no faces and no meshes; the
housing's four M6x1.0 tapped holes as one hole row with no thread depth and its gap; four M6 x 20
screws with fastener rows; the housing's sheet drawing the callout as a drill depth only ("4X
M6x1.0 - 6H DRILL ↧ 14", no thread depth), which ends d1-gold-ambiguous (research §2), and the
bore "Ø40 +0.025/0"; the cover's own drawing's sheet 1 "Ø40 -0.009/-0.025", "8.0 ±0.1" and "4X ⌴ Ø11 ↧ 6.5", its
sheet 2 unreadable (`parse_status` `no_text`, with its gap). Its key is `answer-key.md` 7.1: `D-1`
`fastener.bottoming` over the four joints, model-produced (nothing places the screws: withheld
`joint_placement`), expected unresolved, reachable once FR-061 puts references on the unresolved
path; `D-2` on the housing's drawing document, model-produced, expected unresolved; `C-1` the spigot
fit, its bore on the housing's drawing document and its shaft on the cover's, both documents named
(`answer-key.md` 7.1). D-2 and C-1 share the housing's drawing document, which the drawing-document
rule (6.2) allows for this case alone. Plan decisions CS-19 and RF-12.

### 6.5 Growing the set after the pilot

Sizing grows repetitions first, up to the cap, then cases (FR-055, 22A). A case is added as one core
case and its twin (2 held-out model-produced defects of two families, 2 packages under rule B), in
the design with the fewest held-out defects, keeping every FR-028 cap; a new design is added when
every design holds a fifth of the total. The simulator's reference scenarios grow by SC-010's
"packages of 2 defects and 2 twins" as the spec fixes them; after the pilot it grows by the
committed set's own unit, read from the set's `twin_of` entries (2 defects and 1 twin under rule B),
`verdict.md` 9.1 and 9.5 (plan decision INT-4). The units the approved size adds (`sizing`'s
`growth_units`, `verdict.md` 10.3) are written as case specs, generated and validated (section 7)
after the approval and before any study run, and committed with the pilot's folders and the approved
measurement; the sizing already searched over the grown layout, so no second paid pilot is run (plan
decision RF-40).

## 7. The validation (FR-054, SC-014, US5-8, US5-9, US5-16)

`reviewer/tests/unit/test_benchmark_cases_reachable.py`: a test over the committed set, apart from
the generator. It may import checks, tools, the agent, the scorer and the case specs (for the
correct calls and decoys, `generator.md` section 2); it never writes a key. It is parametrized by
case and leg over every entry of `committed.json` and `pilot.json`. It is in the default suite: a
case that fails it cannot be committed (research §8.6).

**The two configurations**, each with `config/standards.example.yaml`, explanations off and the
answer-turn bound 0, over the committed package through the benchmark's own review function, with a
`FakeProvider` (`agent/providers/fake.py:220`) playing one scripted turn:
- **off**: every lever off, the pane study's off arm;
- **pane**: `--pane-defaults` as `review`'s resolver reads it (FR-011, FR-015).

**(a) Code only**, under pane. The scripted turn calls, with no argument, every check offered on
the package that has no required parameter and that `prerun.planned_calls` (`prerun.py:705`) did not
plan for it, then ends (FR-054 (a); research §8.6; plan decision RF-38). The two code-only tools that
take arguments are not called: the interference groups are the pre-run's own per-group calls
(`prerun.py:737-739`; `check_interference_group(group_key)`, `tools/checks_interference.py:69`), and
`bridge_interference` (`tools/bridge.py:397-399`) is not offered offline (`live_tools` false). At
`be01974` the plan already holds every argument-free check it offers (`tools/registry.py:120-134`;
`tools/checks_mechanical.py:76`), so the turn is usually empty; the rule keeps a future check honest.
Scored with the real scorer. Passes when:
1. the detected known defects (credited or flagged) are exactly the code-produced ones, none a
   status mismatch;
2. no model-produced defect is detected: one that is fails as "code-produced" (US5-8);
3. every demonstrated or suspected finding matches a known defect or a forbidden entry;
4. no finding contradicts a correct condition.

**(b) Correct reviewer**, under off and under pane. The scripted turn makes the spec's correct calls
in order (the fit check on the right references, the drawing finding on the drawing, the joint check
on the withheld pair). Passes when:
1. every model-produced defect is credited or flagged, with no status mismatch and not flagged below
   expected (US5-9): the key's expected status is what the evidence supports (13A);
2. no known defect is cleared;
3. no false alarm of model origin (the model's own findings and configured checks') and no
   contradiction: a correct review scored as wrong is the audit's d2-model-finding-unmatchable
   (research §2);
4. every correct condition that carries a correct call is confirmed: a twin's clean form really is
   clean.

**Decoys**, under off, for every case whose spec lists them. The scripted turn makes only the
decoy calls (another fit on the sheet, another hole pair, the bore against itself, a stack with a
contributor missing). Passes when no decoy's finding credits, flags or clears any known defect
(US5-16). A decoy's finding may be a false alarm; that is the point of it.

Leg (b)'s rules 1, 3 and 4, (a)'s "none a status mismatch" and the decoys go beyond FR-054's
wording. Each catches a key that punishes a correct review or rewards a wrong one, which the
two-check wording lets through (plan decision CS-17).

**Failure messages** name the leg, the configuration, the case and the entry, never a recorded
string:
- "(a) brun-1 D-2 (hole.coaxiality, model-produced) is detected by code-only calls: it is
  code-produced, or its seed withholds too little (16A)";
- "(a) kalo-empty-positive D-1 (fastener.thread_match, code-produced) is not detected by code";
- "(a) davo-2 finding F-004 (hygiene.revision_present, demonstrated, doc:0003) matches no known
  defect or forbidden entry: the package is not clean apart from its planted defects";
- "(a) pelin-1-twin finding F-002 contradicts C-1";
- "(b, pane) okta-1 D-1 is flagged below expected under check_fit(...)";
- "(b, off) rusk-2 finding F-007 is a model-origin false alarm";
- "(decoy) okta-1 check_fit(...) clears D-1: the key's references do not tell the fits apart".

**Scope.** Every committed case, `cover-blind-tap` included (SC-014); `rms-part` is key-only and is
skipped, saying so. The golden scorecards and probes of FR-049 are built beside this validation
from the same case list (`scoring.md` section 9); this contract fixes (a), (b) and the decoys only.

**The validation is itself test-first.** `test_benchmark_validation_catches.py` builds in-memory
cases with the generator's functions and a deliberately wrong spec, and asserts each leg fails with
its message: a seed tagged model-produced that code detects; a code seed the pre-run misses; a fit
keyed to the wrong dimension pair; a twin whose clean form still fails; an unkeyed demonstrated
finding in a clean base; a decoy that shares a planted entry's references.

**Cost.** About 48 cases × 4 offline reviews; each case's reviews run once per session (a
module-scoped cache). Target: under three minutes on the development machine. If it is exceeded,
the plan splits the suite by marker; it never skips a case.

## 8. The set summary (FR-033, US5-2)

```text
uv run swreview benchmark set-summary <set file> [--answer-keys <dir>]
```

It reads the set (`load_set`), and each package's key through `load_answer_key(path, package=...)`
(`answer-key.md` 1) with the package loaded; `--answer-keys` serves a set written before this
feature. It reads no case file and contacts no provider. It is the only printer of the summary; the
generator does not print it.

One row per judgement family, and one for the other check families together; a family is
`benchmark/families.py` `family_of(check)`: `fastener.` and `hole.` fastener; `fit.` and `stack.`
fit and axial stack; `interference.`; `drawing.`; the part-roles question's count rules part role;
every other check (modelling practice, hygiene, standards) other. An item naming several checks
counts once in each family it names.

| Column | What it counts |
|---|---|
| held-out model-produced | known defects tagged `held_out` with `producer` `model`: `AnswerKey.held_out_model_defect_ids()` (RF-67) |
| with a clean twin | of those, the ones a set entry whose `twin_of` is their package keys as a correct condition with the same check and references |
| code-produced guards | known defects with `producer` `code`, either tag |
| tuned-on items | every entry tagged `tuned_on` |
| anchors and analyst-found | the `represents` ids of the set's entries, by `families.ANCHOR_FAMILY` (R-1 part role; R-2 drawing; R-3 fit and axial stack; R-4 and R-5 interference; R-6, AF-1 and AF-2 fastener; R-7 and R-8 other; AF-3 interference) |

Then: the total held-out model-produced count against the floor of 34 ("met", or "below by n");
the designs, and the largest single design's share of held-out model-produced defects ("kalo 4 of
36, 11%"); the packages, held out and private; and each held-out item whose `held_out_against`
differs from `current_stamp()` ("stale: brun-1 D-2"). It exits 0 when printed and 1, naming the
file or package, when the set, a key or a package cannot be read, or a `held_out` flag disagrees
with its key's `holds_held_out()` (US5-12). A count below the floor is printed, not refused: compare refuses the verdict
(`verdict.md` section 7, row 4). Plan decision CS-18.

## 9. Tests

Each fails before its behaviour exists (constitution III). Each test is the gate of the slice that
lands its behaviour (the plan's delivery order): a file or bullet below marked with a slice is that
slice's, and every unmarked one is the generator slice's.

`reviewer/tests/unit/test_benchmark_sets.py`:
- (the parity slice, which lands the root, `saved_form` and `file_form`, RF-4, RF-54) relative
  paths in `<root>/benchmarks/sets/` resolve against the root, passed as a temporary checkout; a
  relative path in a set file elsewhere is refused (row 3); absolute paths load; an entry outside the
  root is private (4.2);
- (the parity slice) `test_a_set_file_in_a_second_worktree_is_refused_naming_both_roots`: a set
  file with relative entries under a second checkout's `benchmarks/sets/` is refused with row 3's
  message naming both roots while the root is the first, and loads with `root=` the second; which
  entries are private, and the saved form, follow the root given, never the set file's location
  (RF-4);
- (the parity slice) `load_saved_set` reads a saved copy's relative entries through `load_set`'s
  core, resolved against the root given, never the run folder's grandparent (RF-4);
- (the parity slice) `saved_form()`: in-root paths root-relative with POSIX separators, private
  ones absolute, and two copies of one tree at different locations give byte-equal saved forms
  (FR-051);
- (the parity slice) `file_form()`: the same paths through the same serializer, with no
  `case_file_sha256`, and the same bytes on Windows and Linux; `saved_form()` equals `file_form()`
  plus each entry's digest once the scripted-answers slice adds it (RF-54);
- (the scripted-answers slice) `case_file_sha256` filled at load and carried into the saved form,
  never into the file form;
- a set with every field loads; a set written before this feature (no `key`, `design`) loads, and
  its keys fall back to `--answer-keys` (4.1);
- `test_a_keyless_set_of_absolute_private_paths_loads_and_scores_through_answer_keys`: the shape of
  every existing test set (`tests/unit/test_cli.py:2373-2393`, `test_benchmark_runner.py:23-34`)
  meets no row-6 refusal, and `benchmark score` reads its keys from `--answer-keys`; a keyed set
  with one entry lacking `key` is refused (row 6; RF-4);
- each refusal of 4.3 with its message: rows 1, 2 and 4 to 7, row 5 as a key inside a package folder
  and a package inside a key's folder (FR-030, US5-11); row 3 is the parity slice's, above, and the
  case-file halves of rows 4 and 5 (the `benchmarks/case_files` segment, a case file's folder that is
  the package folder) are the scripted-answers slice's, pinned with US4-9;
- no committed set file holds `case_file_sha256` (the generator writes them through `file_form`).

`reviewer/tests/unit/test_benchmark_runner.py`: a set naming a missing package is refused before any
review, naming every missing one, and no package folder is created (US5-3); a missing key is refused
the same way, and the run never opens a key (a spy on `open` over the key's path; FR-032).

`reviewer/tests/unit/test_answer_key_isolation.py`: a key and a case file a private set names are
refused to `load_package` through row 5, and the committed `benchmarks/case_files/` segment through
row 4 (FR-030, US4-9, US5-11): the key's half in the generator slice, the case file's in the
scripted-answers slice (`scripted-answers.md` 7). In the parity slice its three `load_set` calls (`:48`, `:71`, `:105`)
pass `root=tmp_path`, whose `benchmarks/sets/` holds their set files, so row 3 passes and the leaky
and junction sets still meet the guard's `AnswerKeyAccessError` (row 4); its `run_benchmark` call at
`:130` passes the same `root`, which `run_benchmark` forwards to `load_set` until the scripted-answers
slice replaces the set path and the root with the `PreflightedSet`; and the smuggle test's stub takes
the keyword (`lambda _path, **_: smuggled`, `:166`), so its `run_benchmark` call (`:170`), which reads
the set through the stub, needs no `root`. From the scripted-answers slice the smuggle test builds
its `PreflightedSet` holding the smuggled entry directly, with no monkeypatch, and still pins the
runner's own check on every entry (`benchmark/runner.py:237-239`), which stays. Its fake takes the
`attempt` keyword (parity slice) and its `pkg-1` (`:109-110`) is given a `package.json`, which 4.4's
existence check requires (generator slice; RF-44). Nothing else in it changes (plan decisions RF-4,
RF-61).

`reviewer/tests/unit/test_committed_benchmark_set.py`, over `committed.json`, `pilot.json`,
`pane-smoke.json` and their keys, never skipped:
- no committed set file names an absolute path or a private entry, and every entry carries `key`,
  `held_out` and `design` (US5-10, FR-030);
- every flag equals its key's derivation (4.5; US5-12's committed half);
- FR-028: at least 34 held-out model-produced defects, none tuned-on; at least 8 designs; no design
  over a fifth of them; no package over 2; never two of one judgement family in a package; every one
  with a clean twin (the summary's twin column); SC-004;
- FR-029: every anchor and analyst-found id in some committed entry's `represents`; and every seed
  and key-only entry whose `represents` is an anchor (R-1 to R-8) tuned-on, read from the case specs,
  which the test imports as the validation does (section 7): a key entry carries no `represents`, and
  three set entries name an anchor beside a held-out analyst-found item (`kalo-contact-positive`,
  `kalo-empty-positive`, whose one item is AF-1's, and `tessa-groups`; plan decision RF-80);
- `cover-blind-tap` is in `pilot.json`, not in `committed.json`, every item tuned-on, `D-1` and
  `D-2` expected unresolved and `D-2` on a drawing document (US5-4);
- the drawing-document rule holds in every case of `committed.json` (6.2; `cover-blind-tap`, in
  `pilot.json`, is its one exception, RF-12);
- `pane-smoke.json` holds exactly two entries, `kalo-1` and `kalo-fit-1`, each equal to its
  `committed.json` entry and in that file's order (6.1; owner decision 35A).

`reviewer/tests/unit/test_held_out_stamps.py`:
- (the scorer slice, which lands `Stamp` and `current_stamp()`, RF-64) `current_stamp()`'s `prompt`
  and `checklist` are `sha256_of` of the two files (5; INT-3); its `tools` is
  `tool_descriptions_digest()`, and each of three one-character patches changes it and fails the
  stamp check on a held-out item stamped before the patch, listing the item: a tool's docstring
  body, its Notes, and one `Args:` entry (`request_evidence`'s `question`, `tools/session.py:85-86`),
  the last reaching the model only through the schema (25A; RF-64);
- (the scorer slice) the digested tool set is complete: over every lever combination, with a
  drawing record, a standards profile and a bridge, `ToolRegistry` offers a review no function
  outside it, and each offered `RecordedTool`'s `schema` is the `spec.schema` the digest read
  (`tools/registry.py:523-524`) (RF-64);
- (the parity slice, which records `prompt_digest`) `current_stamp()`'s `prompt` and `checklist`
  equal what `benchmark run` records as `prompt_digest` and `checklist_digest` for the same checkout
  (5; INT-3);
- (the generator slice) every committed held-out item is stamped with `current_stamp()`; with the
  prompt file patched by one byte the test's check fails listing the items and the new digests
  (US5-7, FR-031).

`reviewer/tests/unit/test_benchmark_cases_reachable.py`: section 7's legs over every committed case
(FR-054, SC-014, US5-4, US5-8, US5-9, US5-16).

`reviewer/tests/unit/test_benchmark_validation_catches.py`: section 7's in-memory failures, one per
message.

`reviewer/tests/unit/test_benchmark_set_summary.py`, over a synthetic set of fictional keys: each
column per family; an item of two families counted once in each; the other families on one row; the
largest share; stale items listed; a private entry counted; below the floor printed with exit 0; a
flag that disagrees with its key, exit 1 naming the package; an anchor mapped to its family (US5-2,
FR-033). `reviewer/tests/unit/test_cli.py`: the command's wiring and its printed block pinned; and, for
`benchmark score`, `--answer-keys` optional over a keyed saved set and a usage error (exit 2) naming
it over a keyless one (RF-4).

`reviewer/tests/unit/test_pdf_parser.py`, `test_ingest_bom.py`, `test_ingest_manifest.py`: re-pointed
to `reviewer/tests/fixtures/ingest/cover-blind-tap/`, asserting unchanged (CS-3).
