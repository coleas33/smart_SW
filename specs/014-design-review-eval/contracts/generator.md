# Contract: The Case Generator

Normative for FR-027, FR-048's generation half, SC-006, SC-011's generation half and the spec's
"Case spec" entity. Research D13, D14.1, §3, §7 ("Case builders and generators", "Dimensions and
tolerance sources"), §8.9, §8.11, §8.14; owner decisions 5A and 16A. `cases.md` fixes what the
generator writes and where; the key's format is `answer-key.md` and the case file's
`scripted-answers.md` 2.2. The generator writes both **through their models**, so it holds no second
copy of either format.

Line numbers are at `5cfb743`; paths are under `reviewer/` unless another root is given. Every
example value is fictional.

## 1. Shape

- **Where**: `reviewer/tests/benchmark_cases/`, the package `tests.benchmark_cases`, beside the
  fixture generators' pattern (`tests/fixtures/mechanical/generate_fixtures.py:918-935`). It is test
  tooling built on the fictional builders under `tests/support/`, so it stays in `tests/`: shipping it
  under `src/` would move the builders out of `tests/` (D14.1). Plan decision GN-1.

  | Module | Holds |
  |---|---|
  | `spec.py` | `CaseSpec`, `Seed`, `SeedKind`, the tags, `ToolCall`, the spec checks (section 10: `check_specs` and `check_anchor_coverage`) |
  | `seeds.py` | the seed kinds (section 3) |
  | `designs/<design>.py` | one per design: its clean base, its places, its case specs; `designs/__init__.py` lists them in order |
  | `stamps.py` | `CURRENT`, the held-out stamp (`cases.md` 5) |
  | `vocabulary.py` | `CASE_VOCABULARY` (section 8) |
  | `render.py` | the package, key, case file and set renderers (section 7): `render_spec(spec)`, one case's files (and its twin's), and `set_entries(spec)`, its set entries, which `render_all()` composes |
  | `generate.py` | `render_all()` and `main()` |

- **Run**, from `reviewer/`: `uv run python -m tests.benchmark_cases.generate`. It renders
  everything in memory, runs the spec checks and the names check, and only then writes. It prints each
  path it wrote, then each **stale** file, a file under `benchmarks/packages/`, `answer_keys/`,
  `case_files/` or `sets/` that it did not write and that is not hand-kept or under the native-package
  slot `packages/bracket-assy/` (`cases.md` 1), as "stale:
  <path>: delete it or restore its spec", and exits 1 if any remains. It never deletes.
- `render_all() -> dict[str, bytes]` maps each repository-relative POSIX path to its bytes; `main()`
  writes exactly those bytes. The regeneration test calls `render_all()`.
- **Nothing is derived from check output** (spec US5 intro, D14.1): the generator reads its specs,
  the builders and `config/standards.example.yaml`, nothing else: no run folder, recording, key,
  owner's list or clock.

## 2. The case spec

```python
# reviewer/tests/benchmark_cases/spec.py
@dataclass(frozen=True)
class HeldOut:
    stamp: Stamp                     # stamps.CURRENT (cases.md 5)

@dataclass(frozen=True)
class TunedOn:
    reason: str                      # "R-3", "prompt-encodes-cbt-answer", ...

Tag = HeldOut | TunedOn
Withheld = Literal["joint_placement", "joint_absent", "tolerance_source", "drawing_only"]

@dataclass(frozen=True)
class ToolCall:
    tool: str                        # a registered tool's name
    arguments: Mapping[str, Any]     # place names resolved to ids at render

@dataclass(frozen=True)
class Seed:
    kind: SeedKind                   # section 3
    at: Mapping[str, str]            # the kind's roles -> the design's place names
    tag: Tag
    represents: str | None = None    # an anchor or analyst-found id

@dataclass(frozen=True)
class CaseSpec:
    case_id: str                     # cases.md 2
    design: Design                   # the design module: its clean base and places
    variant: str | None = None       # a design's named variation of its base (kalo-fit-2)
    seeds: tuple[Seed, ...] = ()     # keyed D-1, D-2, ... in this order
    conditions: tuple[Condition, ...] = ()        # correct conditions a twin does not supply
    forbidden: tuple[Forbidden, ...] = ()
    expected_coverage: tuple[Coverage, ...] = ()
    unanswerable_requests: tuple[Unanswerable, ...] = ()
    question_counts: tuple[QuestionCount, ...] = ()
    answers: tuple[Answer, ...] = ()              # scripted-answers.md 2.2's fields
    represents: tuple[str, ...] = ()
    decoys: tuple[ToolCall, ...] = ()             # cases.md 7
    twin: bool = False                            # derive <case_id>-twin (section 4)
    sets: tuple[Literal["committed", "pilot"], ...] = ("committed",)
```

- **Places, not ids.** A design module exposes its places: each component, document, hole,
  fastener and drawn dimension it builds, by name ("pin", "plate", "bore_a"). Every id a spec, a key
  entry, an answer, a correct call or a decoy carries is written as a place name and resolved at
  render, so no id is typed twice and a builder that renumbers moves every reference with it.
- **What the kind fixes.** A seed's check, producer, expected status and withheld evidence come from
  its kind; a spec never types them. Its family is `benchmark/families.family_of(check)`, never typed
  either.
- **Key-only entries** (`Condition`, `Forbidden`, `Coverage`, `Unanswerable`, `QuestionCount`)
  carry the fields of their `answer-key.md` section 2 entries, with place names for ids, a tag, a
  description and, as a seed does, an optional `represents` (the anchor or analyst-found id the entry
  stands for; plan decision RF-80). Their ids (`C-`, `FB-`, `CV-`, `U-`, `Q-`) are assigned at
  render in spec order.
- **What never leaves the specs**: the withheld evidence, the correct calls and the decoys. The
  validation imports the specs to read them (`cases.md` 7); no committed file holds them, so no reader
  of a package or a key can learn how a defect is found.

## 3. Seed kinds

The core kinds, one module each in spirit, all in `seeds.py`. Every kind has a planted form and a
clean form over the same places, and its correct call names the same references in both.

| Kind | Check | Producer, expected | Withheld | Planted | Clean | Correct call | Decoys |
|---|---|---|---|---|---|---|---|
| `thread_mismatch_unplaced` | `fastener.thread_match` | model, demonstrated | `joint_placement` | a screw one thread size below its tapped hole's (M4-0.7 into M5x0.8, AF-1's shape), its fastener row written, placed on no extracted axis | the screw's thread equals the hole's | `check_fastener_joint(fastener, hole, clamped)` | the same call on a sibling screw's joint |
| `bottoming_unplaced` | `fastener.bottoming` | model, demonstrated | `joint_placement` | a blind tapped hole with a Hole Wizard thread depth shorter than the screw's reach past its clamped stack | a screw length ending inside the thread | as above | as above |
| `engagement_unplaced` | `fastener.engagement` | model, demonstrated | `joint_placement` | a screw that engages less than its rule's ratio of its diameter | an engagement above the rule | as above | as above |
| `coaxiality_drawn` | `hole.coaxiality` | model, demonstrated | `joint_absent`, `tolerance_source` | two holes of two parts meant to align, empty, offset more than half a position tolerance drawn on an ingested sheet | offset 0 | `check_hole_alignment(a, b, tolerance)` | another hole pair between the same parts, with and without the tolerance |
| `coaxiality_undrawn` | `hole.coaxiality` | model, unresolved | `joint_absent` | AF-2's 0.750 mm offset between two empty dowel holes, no tolerance drawn (`checks/hole_alignment.py:98-101`) | offset 0 | `check_hole_alignment(a, b)` | another pair |
| `fit_transition` | `fit.size_only` | model, suspected | `tolerance_source`, `drawing_only` | bore and shaft limits on an ingested sheet that straddle zero clearance, where the part must slide (its summary says so) | clearance limits | `check_fit(bore, shaft)` | the sibling fit on the sheet; the bore against itself |
| `fit_interference_unintended` | `fit.size_only` | model, suspected | `tolerance_source`, `drawing_only` | limits wholly interfering where a slip fit is meant | clearance limits | as above | as above |
| `fit_limit_missing` | `fit.size_only` | model, unresolved | `tolerance_source`, `drawing_only` | one side drawn with no tolerance (`checks/fit.py:85-100`) | both sides toleranced for clearance | as above | as above |
| `stack_out_of_gap` | `stack.worst_case` | model, demonstrated | `tolerance_source`, `drawing_only` | three or four drawn contributors whose worst-case band leaves the drawn target gap | tolerances tightened inside it | `check_axial_stack(contributors, signs, target)` | the stack with one contributor left out |
| `callout_drill_only` | `drawing.manufacturing_inputs` | model, unresolved | `drawing_only` | the part drawing's tapped-hole callout states the drill depth only (the plant reads the model hole's thread, count and drill depth; a core design's hole carries the thread depth its clean form states, while `cover-blind-tap`'s row carries none, `cases.md` 6.4; corrected 2026-10-08, research §9.14) | the callout states the thread depth | `record_drawing_finding(drawing, sheet, observed, requirement, [callout], "unresolved", action)` | none: the entry is document-level |
| `callout_thread_differs` | `drawing.manufacturing_inputs` | model, suspected | `drawing_only` | the callout's thread differs from the model hole's Hole Wizard thread | equal | as above, `"suspected"` | none |
| `callout_count_differs` | `drawing.manufacturing_inputs` | model, suspected | `drawing_only` | the callout's instance count differs from the model hole's instances | equal | as above, `"suspected"` | none |

The statuses are what each check can write: the fit check never writes demonstrated
(`checks/fit.py:75-77, 112`), the model's drawing finding writes suspected or unresolved only
(`tools/session.py:57-58`), a stack outside its target is demonstrated (`checks/stack.py:151-166`),
an offset beyond the drawn zone is demonstrated and without a tolerance unresolved
(`checks/hole_alignment.py:98-101, 130`). A drawing kind's texts quote only numbers the drawing
shows, since the drawing tool refuses an unsourced number (`tools/session.py:673`).

**Anchor kinds** (`cases.md` 6.3) use the same mechanism: `press_fit_drawn` and `press_fit_undrawn`
(R-3, `fit.size_only`, model, suspected and unresolved), `slip_fit` (clean only, a condition),
`interference_positive` (`interference.static`, code, demonstrated), `alignment_offset_placed`
(the joint map's alignment on a placed pin, code), `thread_mismatch_placed`
(`fastener.thread_match`, code, demonstrated), `revision_missing` (`hygiene.revision_present`,
code), `component_lightweight` (`hygiene.component_not_resolved`, code), the four R-7 kinds (code,
the status their rules' registered severities map to, `answer-key.md` 7.2), and
`bottoming_thread_depth_unknown` (`cover-blind-tap`'s D-1, `fastener.bottoming`, model, unresolved,
`joint_placement`).

**Exact checks only.** A known defect or condition of a reference-keyed check is keyed on its exact
check id, never a family (`answer-key.md` 3, AK-4); families appear only on forbidden entries.
`cover-blind-tap`'s D-1 is `fastener.bottoming`, not `fastener.*`. Plan decision GN-9.

**Withheld evidence**, the one vocabulary, and how the builder leaves it out:

| Value | The package holds | So |
|---|---|---|
| `joint_placement` | the screw or pin on no extracted hole axis, none of its faces a hole's member face | the joint map leaves it unplaced (`checks/joints.py:976-1062`); its fastener row still lets `check_fastener_joint` address it |
| `joint_absent` | nothing in the holes, and the two holes' faces more than the joint rules' 1 mm adjacency apart along their axis (`checks/joint_rules.yaml` `adjacency_gap_mm`) | the joint map forms no joint for the pair. Empty holes alone do not keep it out: the joint map pairs two adjacent coaxial holes whether or not anything sits in them, and judges an empty pair's alignment with the fastener size their Hole Wizard size names (`checks/joint_alignment.py` `fastener_size`), so an offset adjacent pair would be a code-produced `hole.nominal_alignment`. `check_hole_alignment` reads the two holes' axes and needs no adjacency (corrected 2026-10-08, research §9.14) |
| `tolerance_source` | no toleranced model dimension, model position tolerance, ISO 286 Hole Wizard class or validated drawing binding **anywhere in the package** (`checks/tolerances.py:1007-1030`) | the joint map's stack, which runs on every joint once any source is held (`checks/joint_alignment.py:698-712`), stays off, and the limits live only on an ingested sheet |
| `drawing_only` | the evidence only on an ingested sheet | no argument-free check reads it for this rule |

A kind's withheld set is non-empty exactly when its producer is model (16A). FR-054 (a) proves the
claim on every committed case (`cases.md` 7); the generator does not re-check it, since that would
need the check logic it may not import.

## 4. Twins (FR-028; `cases.md` 6.2, rule B)

`twin(spec) -> CaseSpec`, for a spec with `twin=True` (every core case, no anchor):

- id `<case_id>-twin`, the same design, variant and places, no seeds, no decoys;
- the package: each seed's **clean** form at the same places;
- the key: each seed becomes a correct condition, in seed order `C-1`, `C-2`: the kind's check, the
  seed's parts, documents and references, the seed's tag (a held-out seed's condition is held out
  with the same stamp), and the description "clean twin of <case> D-<n>: <the clean form>";
- the correct call: the kind's, on the same references, for every kind whose call confirms its
  clean form (`SeedKind.confirms_clean`). Two have none: the drawing kinds (a correct reviewer
  records nothing on a complete drawing) and `coaxiality_undrawn` (with no tolerance drawn,
  `check_hole_alignment` writes unresolved on aligned holes too, `checks/hole_alignment.py:98-101`;
  owner decision 55A). Such a condition carries no correct call, so the validation's leg (b) rule 4
  (`cases.md` 7) never asks it to confirm, and it still catches a false alarm: a finding that
  contradicts it;
- the set entry: `twin_of` the source case, the same `design`, `held_out` derived.

A twin is never written by hand: a spec that names a `-twin` id is refused (section 10, row 1).
Plan decision CS-4 (twin rule B) and GN-8.

## 5. Building a package

### 5.1 The builders and how they compose

| Builder | Where | Used for |
|---|---|---|
| `PackageBuilder` | `tests/support/mechanical.py:438` (`document` `:471`, `component` `:535`, `hole` `:656`, `screw_document` `:827`, `screw` `:859`, `interference` `:923`, `build` `:959`) | every design's documents, components, holes, faces, screws, interference rows and meshes |
| feature trees | `tests/support/features.py` `build_features` `:258`, and `part_trees`, extracted from `rms_package`'s per-part loop (`:636-656`) so the generator lays trees and equations on a `PackageBuilder` package with the same code; `rms_package` calls it and its output is unchanged | compliant trees on every custom part; R-1's and R-7's trees |
| `standards_package` and `card` | `tests/support/standards.py:264`; `card`, moved here from `tests/checks/standards_fixtures.py:43-63` (section 9), which re-exports it | the data card and revision properties in the example profile's names |
| `DrawingBuilder` | `tests/support/drawings.py:182`, `candidate` `:570` | R-2's same-name drawing candidates |
| `SheetBuilder` | new, section 6 | every ingested sheet: fits, stacks, drawn tolerances, callouts, `cover-blind-tap` |

A design builds its clean base with `PackageBuilder`, lays trees with `part_trees`, sets folders,
custom and configuration properties by `model_copy` after `build()` as `sitting_package` does
(`tests/support/sitting.py:315-373`), then adds sheets and candidates. Seeds edit the base through
the same calls. **No builder but `SheetBuilder` is added** (D14.1; FR-027); `PackageBuilder.screw`
gains one option (5.4). Plan decision GN-3.

### 5.2 The example profile's names (FR-027; research §8.14)

The generator loads `config/standards.example.yaml` with `load_profile`
(`checks/standards/profile.py:617`) and reads every name from it:

- **custom parts and assemblies**: named by the profile's part-number pattern with a custom prefix
  (`config/standards.example.yaml:51-55, 169-171`), "EX-1101-01.SLDPRT" (the pattern's two free
  characters are digits, which the names check reads as a number); the full data card from
  `card(profile)` (`:41-49`); the revision under `revision.property` (`:57-60`); the hygiene part
  number equal to the stem and a summary unique in the package (`:97-101`). A custom prefix (medium)
  and sparse properties agree, so `_decide` reads custom (`checks/part_roles.py:612-619`);
- **bought parts** (screws, pins): the vendor file shape `PackageBuilder` writes, in a folder
  `part_roles.bought_folder_names` names, with a vendor property (`:136-137, 148-150`): strong and
  agreeing, so bought;
- so no part is unclear and no part-roles question is asked, unless a spec plants the conflict
  (R-1, `cases.md` 6.3), and the guard that fires when no part is decided (`checks/part_roles.py:721`)
  never fires.

Profile A's names (`tests/support/mechanical.py:108`, `tests/support/sitting.py:187-198`) never
appear in a generated case: a document in them would carry no `DocRev` and raise a revision finding
FR-054 (a) fails.

### 5.3 The clean base

Every design's clean base holds what the argument-free checks need to read nothing wrong: a
compliant feature tree and one global equation on every custom part (26 of 27 recorded dumps carry
trees, research §2 distribution-shape-mismatch; a part with no tree is graded as an empty tree and
raises RMS findings, fa-rate-rewards-ignoring-instructions); a fixed first component; masses
consistent with their materials; drawing documents with the house card. FR-054 (a) on each twin,
whose package is the clean base with the clean forms, proves it; a finding it names is fixed in the
design, never keyed away.

### 5.4 Every screw has a fastener row (plan decision GN-2)

`PackageBuilder.screw(..., fastener_row: bool = False)`: when true it also writes a `Fastener` row
(next `fst:NNNN`) with kind `screw`, identity `toolbox`, the thread and length its file name states
(so the identity check sees no conflict), and the placement's axis; `build()` writes
`package.fasteners`. The default writes none, so every committed mechanical fixture stays byte for
byte (its regeneration test proves it). The generator passes true for every screw, because:

- a joint reference resolves its fastener against `package.fasteners` (`answer-key.md` 2.5, row 13);
  a screw recognised from its name alone is `fst:name:<component>` inside the joint map
  (`checks/fastener_identity.py:224`) and in no package row;
- `check_fastener_joint` resolves only those rows (`tools/context.py:192, 430`;
  `tools/checks_fastener.py:221-223`), and `list_fasteners` lists only them (`tools/query.py:596`), so
  without a row no model can check a withheld joint, and 16A's model-produced joints have no route.

### 5.5 Identity, schema and paths

- The IR `package_id` in `package.json` is `uuid5(CASE_NAMESPACE, case_id)`, `CASE_NAMESPACE` a
  fixed UUID in `spec.py`: a UUID distinct from the set's and the key's `package_id`, which is the
  case id (`cases.md` 2); neither is set from the other. `created_at` is `mechanical.CREATED_AT`
  (`tests/support/mechanical.py:196`).
- `design.design_id` is the case id, overriding the builders' `dsn:fict` (`tests/support/mechanical.py:1015`)
  and `dsn:1` (`tests/support/packages.py:93`), so `test_validate_reads_the_committed_benchmark_package`
  (`reviewer/tests/unit/test_cli.py:346-355`, `design_id == "cover-blind-tap"`) passes on the
  regenerated package unchanged (plan decision RF-75).
- Every generated package is written at `CASE_SCHEMA_VERSION = "1.6.0"`, set after the builders ran:
  they pin 1.4.0 (`mechanical.py:103`), 1.6.0 (`drawings.py:78`) or follow `SCHEMA_VERSION`
  (`tests/support/packages.py:75`), and a case must not change when the IR's minor does.
- The design's name is the root document's stem.
- Paths lie under the named fictional roots of research §8.8 only: `FICTIONAL_ROOT`
  (`mechanical.py:104`) for every `PackageBuilder` and `SheetBuilder` document, `/Designs/` and the
  example profile's `vault_root` where the features and standards builders write them.

## 6. The ingested-sheet builder (FR-027's one builder; research §8.14)

`check_fit`, `check_axial_stack` and a toleranced `check_hole_alignment` read dimensions only
through `resolve_dimension`, which matches PDF-ingested sheets and refuses a native drawing
dimension while `DRAWING_BINDING_VALIDATED` is false (`tools/refs.py:49-100`; `drawings/binding.py:59`).
No builder writes an ingested sheet; the shape exists only inline in
`tests/unit/test_tools_checks_fit.py:112-156`.

```python
# reviewer/tests/support/drawings.py
Limits = (tuple[Literal["bilateral"], float, float]      # upper, lower, signed, mm
          | tuple[Literal["symmetric"], float]           # half-width, mm
          | None)                                        # drawn with no tolerance

class SheetBuilder:
    """Adds PDF-ingested drawing sheets on top of `base`; never changes a base row."""
    def __init__(self, base: EvidencePackage) -> None: ...
    def drawing(self, stem: str, *, properties: Mapping[str, str] | None = None) -> str: ...
    def sheet(self, drawing_id: str, name: str = "Sheet1", *, page: int,
              readable: bool = True, notes: Sequence[tuple[str, NoteKind]] = ()) -> None: ...
    def dimension(self, drawing_id: str, sheet: str, nominal_mm: float, *,
                  limits: Limits, text: str) -> SourceRef: ...
    def build(self) -> EvidencePackage: ...
```

- `drawing`: a document of kind `drawing` (the next `doc:NNNN`), at
  `{FICTIONAL_ROOT}Vault\<stem>.SLDDRW`, configuration `Default` as ingest writes one (the committed
  `cover-blind-tap` package), and its manifest entry with `export_method` `pdf`. The document and
  its entry are written by **one function shared with `DrawingBuilder.drawing_document`**
  (`tests/support/drawings.py:212-242`), taking the export method and configuration, so the two
  builders cannot disagree about what a drawing document is.
- `sheet`: a `DrawingSheet` in mm, scale "1:1", `parse_status` `text`; `readable=False` writes
  `no_text`, no dimensions, and the gap ingest writes for such a page (`no_text`, `drawing_sheet`,
  `<document>:<page>`).
- `dimension`: annotation `dim-<page>-<n>` in call order, the parser's shape; nominal in mm; a
  `Tolerance` of kind `bilateral`, `symmetric` or `none` carrying its source; `text_as_read` the
  text given. It returns the `SourceRef`, the document, sheet and annotation triple
  `resolve_dimension` matches (`tools/refs.py:73-75`), which the key's references carry.
- `build`: the base with the drawing documents appended to `documents` and
  `design.drawing_document_ids`, their entries to the manifest, the sheets to `drawings`, the gaps to
  `gaps`; nothing else changes.
- **Refusals** (`ValueError` naming the argument): an unknown drawing id; a sheet named twice on one
  drawing; a dimension on a missing or unreadable sheet; a bilateral upper below its lower; a
  symmetric half-width not above zero. Sheets are mm only: no case needs an inch sheet, and a unit
  switch would be configurability no one asked for.

## 7. Rendering

- **Package**: `Built.render()`'s bytes (`tests/support/mechanical.py:421-430`): `package.json`
  indented 2 with a final newline, and the GLB meshes the builder exports, as the mechanical fixtures
  are committed.
- **Key**: an `AnswerKey` instance (`benchmark/answer_key_model.py`, the format's data-only
  definition, format 2, `answer-key.md` 1 and 2; plan decision RF-1) built
  from the spec: each seed a known defect (`D-<n>`, the kind's check, the seed's parts, documents and
  references with every reference's owner among them, `answer-key.md` row 14; producer, expected
  status, tag, `held_out_against`, description), then conditions, forbidden entries, coverage,
  unanswerable requests and question counts. Field names are the model's: a spelling change in the
  key contract changes the output and no generator code.
- **Case file**: a `CaseFile` instance of `scripted-answers.md` 2.2's format, only for a spec with
  answers. The model must live in a data-only module, `benchmark/case_file.py`, which
  `benchmark/answers.load_case_file` imports: `answers.py` also holds the driver, which imports the
  agent's runner (`scripted-answers.md` 3), and the generator may not import it (section 9).
- **Sets**: `committed.json`, `pilot.json` and `pane-smoke.json` (`cases.md` 6.1: `committed.json`'s
  entries for `PANE_SMOKE_CASES = ("kalo-1", "kalo-fit-1")`, in its order; owner decision 35A),
  `BenchmarkSet` instances written through
  `BenchmarkSet.file_form(root=...)` (`cases.md` 4.2; plan decision RF-54), the one serializer of the
  committed form, shared with `saved_form()`: repository-relative POSIX paths on every platform,
  `key` and `design` on every entry, `held_out` the rendered key's `holds_held_out()` (RF-67), optional fields
  omitted when absent, never `case_file_sha256`. Entry order: the designs in
  `designs/__init__.py`'s order, within a design its specs' order, each twin after its case.
- Every JSON file: UTF-8, LF, indented 2, a final newline, non-ASCII written as itself.

## 8. Fictional strings (FR-048, SC-011, D13)

- **The vocabulary.** `CASE_VOCABULARY` is `DRAWING_VOCABULARY` (`tests/support/drawings.py:96`),
  plus every token of the example profile's string values, read from the loaded profile so the list
  cannot drift from it (research §8.14), plus four short committed lists: generic part nouns
  (plate, pin, dowel, cover, housing, bracket, base, shaft, bushing, spacer, flange, clevis,
  carriage, rail, shim, clamp, block, mount, gear, bearing, assy, blind, tap), callout words (drill,
  thread, deep, thru, fixture, value), case-id words (twin, fit, clean, contact, positive,
  lightweight, empty, sitting, groups, committed, pilot, pane, smoke) and the Resilient Modeling
  group words (ref, construction, core, detail, modify, quarantine: the words of the six group
  folders' names `1-Ref` to `6-Quarantine`, which every compliant tree (5.3) and R-7 lay and RMS
  matches exactly; owner decision 54A; `test_benchmark_case_generator.py` holds the list equal to
  `checks/rms_types.yaml`'s `groups`, which the generator may not import, section 9). A thread or
  fit class token (`6H`, `H7`, `g6`) passes as a size. Plan decision GN-6.
- **Names** are held to it with `fictional_offences(text, CASE_VOCABULARY)`
  (`tests/support/mechanical.py:173`): file, component, configuration and feature names, property
  names and values, package, case, design and set names, every path. **Sentences** are the author's
  English and are not: key descriptions, answers, drawing notes, the correct calls' texts. The owner's
  denylist checks them by whole word where the list exists (`tests/support/fixture_denylist.py:78`),
  as it checks the vector table's notes.
- **At generation, on every machine**, the names check runs over everything rendered before
  anything is written; an offence refuses the run naming the case, the file, the JSON pointer and
  the token. The tokens are generated, never recorded, so naming them leaks nothing.
- **The owner's lists**: `test_benchmark_cases_are_fictional.py` checks every rendered string
  against the denylist (names by substring, `offending_tokens` `:69`; sentences by whole word; GLB
  JSON chunks, `glb_json` `:105`) and skips, naming the missing file, where it is absent; it never
  passes on a machine without it. Once committed, the generator's output is scanned for the
  identifier list by `test_tracked_files_carry_no_recorded_number.py` like every tracked file
  (`:176, 196`).

## 9. Imports (SC-006; research §8.9)

`test_benchmark_generator_imports.py` parses (`ast`) every module under
`reviewer/tests/benchmark_cases/` and every `tests.support` module they import, and fails on any
`swreview` import outside this list, naming module and import:

| Allowed | Why |
|---|---|
| `swreview.ir`, `swreview.ir.models` | the IR's data models |
| `swreview.checks.standards.profile` | the profile's data model and `load_profile` (research §8.9) |
| `swreview.benchmark.answer_key_model`, `swreview.benchmark.case_file`, `swreview.benchmark.sets` | the three formats' data-only models, which the generator writes through. Never `swreview.benchmark.answer_key`, the key's loader: its load-time refusals call the matcher, the question reader (built on `tools/context.context_for`) and `tools/refs.resolve_dimension` (`answer-key.md` 1; plan decision RF-1) |
| `swreview.benchmark.families` | `family_of`, for the per-package family rule |

Direct imports are checked for every module. For the allowlisted `profile` module, what it imports is
allowed (research §8.9, settled): the standards profile module's package imports the standards
checks (`reviewer/src/swreview/checks/standards/__init__.py:16`), and nothing the generator writes
calls them. The four data-only format modules (`answer_key_model`, `case_file`, `sets`, `families`),
and `benchmark.digest`, the dependency-free home of `sha256_of` that `sets` imports (plan decision
RF-48), are also checked **transitively**: the test imports each alone in a fresh interpreter
(`subprocess`) and fails when `sys.modules` then holds any `swreview.tools`, `swreview.agent` or
`swreview.checks` module, naming the module and the one it loaded. That holds today for
`benchmark.sets` (8 `swreview` modules, none of those three) and keeps "imports only data models"
true of the formats the generator writes through, as INT-6 made it true of the case file. Any
`tests.checks` import is refused: `tests/checks/standards_fixtures.py` imports
`tests/checks/golden_standards.py`, which imports the standards check run (`:39`). That is why `card`
moves to `tests/support/standards.py` (5.1). The validation is not the generator and is outside this
test (`cases.md` 7). Plan decisions GN-5 and RF-1.

## 10. Refusals

The spec checks run on every spec before anything renders. Each is a `CaseSpecError` (a
`ValueError`) whose message starts "case spec {case id}:"; the first failing row ends the run and
nothing is written.

| # | Condition | Message gist | Pins |
|---|---|---|---|
| 1 | a case id repeated, outside the grammar of `cases.md` 2, or ending `-twin` | the id | SC-006 |
| 2 | a place name the design does not define, in a seed, entry, answer, call or decoy | the name and where | FR-027 |
| 3 | more than two held-out model-produced seeds in a case, or two of one judgement family (`family_of`) | the seeds | FR-028 |
| 4 | a held-out seed whose stamp is not `stamps.CURRENT`; a tuned-on seed with no reason | the seed | FR-031 |
| 5 | a drawing-family seed whose drawing document carries another seed's or a condition's reference, or a second drawing seed (`cases.md` 6.2). Not applied to a spec whose `sets` is `("pilot",)` alone and whose every item is tuned-on: the rule protects held-out drawing defects keyed by document, and `cover-blind-tap`, which holds nothing out and is in no pane study, keeps its housing sheet's callout and bore together as its package always has (plan decision RF-12) | both | FR-028, US5-16 |
| 6 | `twin=True` on a case holding a kind with no clean form | the seed | FR-028 |
| 7 | a held-out seed in a spec outside `committed` (`cover-blind-tap` is tuned-on only) | the seed | US5-4 |
| 8 | a `represents` value outside R-1 to R-8 and AF-1 to AF-3; an anchor or analyst-found defect no spec represents; a seed or key-only entry whose `represents` is an anchor (R-1 to R-8) and whose tag is not `TunedOn` (15A: anchors are tuned-on; RF-80) | the value, the missing ids, or the entry | FR-029 |
| 9 | a names-check offence (section 8) | case, file, JSON pointer, token | FR-048, SC-011 |
| 10 | a path outside the named fictional roots (5.5) | case, file, path | FR-051, D13 |
| 11 | a key, case-file or set model that refuses its own construction | the model's message, naming the case | FR-027 |

Row 8 has two halves. Its per-entry halves (a value outside R-1 to R-8 and AF-1 to AF-3; an
anchor on an entry not tuned-on) hold for any list of specs and run in `check_specs(specs)` with
rows 1 to 7, so one design's specs, or `cover-blind-tap`'s alone, pass it. Its coverage half (an
anchor or analyst-found defect no spec represents) holds only over the whole set:
`check_anchor_coverage(specs)` runs it, and only `render_all()` calls it, over every spec of
`designs/__init__.py`'s designs, after `check_specs` and before anything renders.

What the spec checks do not repeat: the key's load-time refusals (`answer-key.md` 4) and the case
file's run-start refusals (`scripted-answers.md` 2.3), which section 11's tests run over every
rendered key and case file through their own loaders, and the producer and reachability claims,
which are FR-054's (`cases.md` 7).

## 11. Tests

Each fails before its behaviour exists (constitution III).

`reviewer/tests/unit/test_benchmark_case_generator.py`:
1. **Regeneration** (SC-006, US5-1): `render_all()` equals the committed tree under
   `benchmarks/packages/`, `answer_keys/`, `case_files/` and `sets/`, less the hand-kept files, each
   committed file read with CRLF as LF (`as_committed`, moved once from both of its copies,
   `tests/unit/test_support_mechanical.py:266` and `tests/unit/test_support_drawings.py:253`, into
   `tests/support/mechanical.py` beside `load_generator`, `:1034`, both test modules and the golden
   digest importing it; plan decision RF-55); both sides name the same files, a file under
   `packages/bracket-assy/` on neither; a stale file fails
   naming it.
2. **Determinism**: two `render_all()` calls in one process are equal; each IR `package_id` is the
   case id's uuid5 and each `design.design_id` the case id (RF-75); rendering with the clock patched to raise succeeds.
3. **The example profile** (FR-027): every custom document carries the profile's revision, data-card
   and hygiene property names; no rendered string equals a profile A property name
   (`tests/support/mechanical.py:108`).
4. **Through the loaders**: every rendered key loads with `load_answer_key(path, package=<its
   package>, ...)` (`answer-key.md` 1, every row of its section 4); every rendered case file passes
   `scripted-answers.md` 2.3 against its package and the example profile.
5. **Twins** (FR-028): every committed twin equals `twin(<its case>)`; its conditions carry the
   case's checks, references and tags, `C-1` onward; its set entry names `twin_of`.
6. **Refusals**: each row of section 10 on an in-memory spec, with its message; row 5 also on a
   pilot-only spec holding one held-out item (refused), `cover-blind-tap`'s own spec passing
   `check_specs` (RF-12), and row 8's coverage half through `check_anchor_coverage` over a
   partial list.
7. **Seed kinds**: each kind's family is `family_of(check)`; withheld non-empty exactly when the
   producer is model; no kind's check is a family; planted and clean forms of each kind yield the
   same check and references.
8. **Owner decisions 54A to 56A**: `RMS_GROUP_WORDS` equals the words of `checks/rms_types.yaml`'s
   `groups`, and a case with a tree on its custom parts, and its twin, pass the names check; the
   kinds whose call cannot confirm their clean form are exactly the drawing kinds and
   `coaxiality_undrawn`, whose twin condition carries no correct call; an as-written nominal
   renders `kalo-fit-1`'s sheet texts as `cases.md` 6.3 writes them.

`reviewer/tests/unit/test_benchmark_generator_imports.py`: section 9 (SC-006, FR-027), with a
planted import of `swreview.tools.checks_fit`, of `swreview.benchmark.answer_key` and of
`tests.checks.standards_fixtures` each named in its failure; and the transitive half: each of the
four data-only format modules, and `benchmark.digest`, imported alone loads no `swreview.tools`,
`swreview.agent` or `swreview.checks` module (RF-48), and a temporary module importing `swreview.tools.refs`, checked the same
way, fails naming it (RF-1).

`reviewer/tests/unit/test_support_sheets.py` (FR-027, research §8.14):
- a dimension resolves through `resolve_dimension` to the one written;
- each `Limits` form maps to its tolerance kind and values; `check_fit` over a builder bore "40
  +0.025/0" and shaft "40 -0.009/-0.025" writes the finding `test_tools_checks_fit.py` pins
  (clearance, 0.009 to 0.05 mm);
- an unreadable sheet writes `no_text`, no dimension and its gap;
- every base row is unchanged; the drawing document and its `pdf` entry are written by the shared
  writer, and `DrawingBuilder`'s drawing documents stay byte for byte (the drawing fixtures'
  regeneration test);
- each refusal of section 6.

`reviewer/tests/unit/test_support_mechanical.py`: `screw(fastener_row=True)` writes one `Fastener`
row with the screw's thread, length and axis, identity `toolbox`, and `check_fastener_joint`
resolves it; the default writes none, and the committed fixtures regenerate unchanged (GN-2).

`reviewer/tests/unit/test_support_features.py`: `part_trees(parts)` equals `rms_package(parts=
parts)`'s features and equations; the golden generators regenerate unchanged (GN-3).

`reviewer/tests/unit/test_benchmark_cases_are_fictional.py` (FR-048, SC-011): the names check over
every committed generated file on every machine; the denylist half over every rendered string and
GLB JSON chunk, skipped naming the file where it is absent, never passed.

The four standards goldens' regeneration tests pass unchanged after `card` moves (5.1).
