# Contract: Fasteners

*Amended 2026-09-29 by feature 014 (`specs/014-design-review-eval/`), in scoring.md section 10 (19A), landed 2026-10-07 (014 T026):* references on every path of the fastener check (section 4, last paragraph).

Normative for FR-011 to FR-013, User Story 4 and SC-002, SC-004.

*Amended 2026-10-08 (owner decisions 50A to 53A, research R2.26):* section 8, thread pitch, is
normative for FR-029 to FR-034 and SC-009 to SC-012; it changes section 1's rule for one whole
number after a metric size (section 8.8) and adds `contracts/coarse-pitch.json`.

## 1. The name grammar (`checks/fastener_names.py`)

Parsed in order from the document's `file_name` (extension dropped), its `Description` custom
property, and the component's `referenced_configuration`; the first that yields a size wins, the
others cross-check. Matching is case-insensitive on text with `_` and runs of whitespace
normalized to one space and `×` to `x`.

| Form | Pattern (after normalization) | Example (fictional) |
|---|---|---|
| vendor file name | `^<head code> m<d>-<p>x<L>( .*)?$` | `SHC_M4-0.7X12_FICT-0001` |
| vendor description | `^<kind>, .*\bm<d>-<p> x <L> mm\b` | `SCREW, SOC M4-0.7 X 12 MM, FICTIONAL` |
| Toolbox size and pitch | `^m<d>( x <p>)?( x <L>)?( - .*)?$` (the C# parser's forms) | `M6x1.0 x 20 - 20N` |
| Toolbox size and length | `^m<d> x <L>$` with `L` an integer above the size's coarse pitch (section 8.8, since 2026-10-08) | `M10x35` |
| unified inch | `^(#<n>\|<a>/<b>\|<a.b>)-<tpi>( x <L>)?$` | `1/4-20 x 1-1/2` |

`<head code>` is looked up in `checks/fastener_names.yaml`
(`SHC: {kind: screw, head_type: socket head cap, drive: hex_socket}`, `FHT` flat head and `BHT`
button head, both `drive: torx` by the owner's answer of 2026-09-23). A head named in words
(`socket head cap screw`) names no drive; only a head code does. A pitch written with a hyphen (`M4-0.7`) is a pitch; a
bare integer after the size is a length; an unknown head code is `kind = null` and the size is
still read. Lengths are mm for metric and inches for unified unless the text carries a unit.
*Amended 2026-10-08 (owner decision 52A, section 8.8):* one bare integer after a metric size is
a pitch when it is at most that size's coarse pitch (`M8x1`, `M10x1`, `M20x2`, `M6x1`), and a
length otherwise (`M10x35`); a size with no coarse pitch keeps the rule above.

## 2. The shared vector table

`specs/010-mechanical-checks/contracts/fastener-name-vectors.json` (created by T039), fictional
strings only:

```json
[{"source": "file_name", "text": "SHC_M4-0.7X12_FICT-0001",
  "expected": {"kind": "screw", "head_type": "socket head cap", "thread": "M4X0.7",
               "length_mm": 12.0}},
 {"source": "configuration", "text": "garbage", "expected": null}]
```

`reviewer/tests/unit/test_fastener_names.py` and
`extractor/SwReview.Extractor.Tests/FastenerNameParserTests.cs` each read every row and assert
their parser's answer; a row either parser disagrees with fails that parser's suite. The C#
parser need not read `Description` forms it never receives, and such rows carry
`"csharp": false`.

## 3. Recognition (`checks/fastener_identity.py`)

`recognise_fasteners(package, joint_map=None) -> list[RecognisedFastener]`:

1. every `Fastener` row, `identity_source` as written; its name, if parseable, cross-checks;
2. every other resolved component whose document name parses to `kind` screw, bolt or pin, one
   `RecognisedFastener` per instance, `identity_source = "name_parse"`, with an in-memory
   `Fastener` (`data-model.md` section 2);
3. the shank: the component's free cylinder face of largest area (`face`), else none; the band
   `[d3 - 0.05, d + 0.05]` with `d3 = d - 1.226869 · P` decides `agreement`;
4. placement per `joint-map.md` section 5.

A disagreement is one `fastener.identity` finding, **suspected**, per document (all its instances
listed): `"<document> is named <designation> but its shank measures <x> mm, outside the <lo> to
<hi> mm band of that thread"`. SC-004: on the big fixture at least 90 percent of the named screws
are recognised (the fixture's 68 of 68 by file name).

## 4. The placed screw (`checks/fastener.py check_placed_screw`)

For each screw joint with a placed, recognised screw and a tapped instance:

| Quantity | Rule |
|---|---|
| reference axis | the tapped instance's axis; the thread entry is the end of the tapped face extent that lies inside the screw's extent |
| screw extent | the shank face's extent (`face`), else the screw mesh's vertices projected on the axis (`mesh`), else missing |
| protrusion | `entry - tip`, the tip being the screw extent's end beyond the entry |
| usable thread (blind) | `Hole.thread_depth`, measured inward from the entry; missing when null |
| usable thread (through) | the tapped face's axial extent, `derived: through-tapped length from the tapped face` |
| unknown end condition | usable thread missing |
| axis not aligned | protrusion missing (`"the axis is oblique; bounding-box extents are not used"`). A mesh extent of the screw is exact on any axis and is still computed, but the thread entry it is measured from is the tapped face's box, which overruns an oblique face by `r` times the sum of `|a_i| sqrt(1 - a_i^2)` (1.8 mm on a 4.2 mm bore at 30 degrees), so the protrusion stays missing with that reason (joint-map.md section 2: engagement requires an aligned axis; T044 as landed). A through-tapped usable length on an oblique axis is missing for the same reason |
| agreement `disagrees`, or two names that disagree on the size | protrusion missing (`"the parsed size disagrees with the measured shank"`, or the conflicting names) |
| screw extent does not cross exactly one end of the tapped face | wholly inside: missing (`"the screw lies wholly inside the tapped face"`); short of it: missing, with the gap (a placement by origin may be on the wrong hole); across both ends: the smaller of the two protrusions |
| mesh extent precision | a GLB stores single-precision vertices; a mesh extent is rounded to 0.001 mm |

The four results come from the same `_bottoming`, `_engagement`, `_thread_match` and
`_head_clearance` functions as `check_fastener_joint`, each calculation carrying the derivation
lines instead of `"protrusion = screw length - clamped stack - washers"`. `hole_depth` is never
read. `hole_material` is the tapped component's document material. A demonstrated engagement
shortfall in a through-tapped part thinner than the rule's length (`ratio x d`) is severity
`low`, with `sheet_thickness_mm` and `required_engagement_mm` in its result (owner answer
2026-09-23).

The placed-screw results fold by **screw document and tapped part** (`fastener_identity.
fastener_group`), not by pattern group: one screw part mis-threaded into one part at two
unrelated holes is one condition and one finding (SC-002). A screw placed in a joint with no
tapped instance is one skipped `fastener.engagement` coverage item for all such joints, and
with no tool envelope swept head clearance is one skipped `fastener.head_clearance` item.

Every result of the four rules, from `check_placed_screw` and `check_fastener_joint` alike and on
every path, unresolved included, leads its `inputs` with the fastener's and the hole's ids, then
the lengths it was judged on as read; `fastener.unsupported` names the fastener and the hole its
call names. The ids are the joint's references, which a finding reports and the eval's scorer
matches (feature 014 FR-061, owner decision 19A); `Calculation.inputs` and the words do not
change.

## 5. The engagement rule

```yaml
  steel:
    min_engagement_ratio: 1.5
    source: "Owner decision 2026-09-23: at least 1.5 x d into steel and aluminium alike"
  aluminum:
    min_engagement_ratio: 1.5
    source: "Owner decision 2026-09-23: at least 1.5 x d into steel and aluminium alike"
```

Every other class unchanged. The file header records that the owner's answer was typed "1.td
into both" and read as 1.5d.

## 6. Acceptance on the big fixture

| Joint | Expected |
|---|---|
| two M4-0.7 screws in M5x0.8 tapped instances | one `fastener.thread_match` finding, demonstrated, 2 joints (SC-002) |
| M10x1.5 screw in a blind 12 mm thread, 10.225 mm engaged | `fastener.engagement` demonstrated, 10.225 against 15.0 |
| M2x0.4 screw in a blind 6 mm thread, 2.205 mm engaged | demonstrated, 2.205 against 3.0 |
| M3x0.5 screw in a 1.725 mm through-tapped hole, 1.394 mm engaged | demonstrated, 1.394 against 4.5, usable thread labelled derived; bottoming not applicable |
| M8x1.25 screw in a blind 16 mm thread, 14.375 mm engaged | checked within scope |
| the M4 in an oblique M5 | thread match demonstrated; engagement unresolved naming the oblique axis unless its mesh gives the extent |
| a screw named M5 whose shank measures 3.3 mm | `fastener.identity` suspected; its engagement unresolved |

## 7. The extractor (seat-validated)

`FastenerNameParser.Parse(configurationName, description, fileName)` accepts the vendor forms of
section 1 and reads the file name. `FastenerDumper` treats a component as a candidate when
`IsToolbox` **or** `FastenerNameParser.IsCandidate(fileName, description, configuration)` finds a
kind and a size; every candidate gets the shank face request it gets today. `IsCandidate` is a
pure static function tested with the vector table. Head diameter and height stay null (the head
table is the Python side's, `tool-access.md`).

## 8. Thread pitch (amendment 2026-10-08, owner decisions 50A to 53A)

Normative for FR-029 to FR-034 and SC-009 to SC-012; research R2.26 records the decisions and
the defaults this section takes. The owner's request: "Add check for fine pitch parts and
threaded holes. Call out and flag to user to make sure they mean to use it anywhere. We almost
always use standard threads not fine... so it's a common mistake."

### 8.1 The rule

The shop uses coarse threads, so a fine pitch is flagged for the engineer to confirm (50A).
Every thread the package states is put in exactly one class, against the one table of section
8.3, in this order:

| # | Class | When | Outcome |
|---|---|---|---|
| 1 | unreadable | no designation, or a blank one | listed in the unreadable row, never passed |
| 2 | pipe | `is_pipe_thread` (section 8.8) is true, whatever `parse_thread` reads (`1/8-27 NPT`, `NPT 1/8`, `G1/4`) | listed in the pipe row, never passed |
| 3 | unreadable | text `parse_thread` does not read (`3/8`, `1-8`, `1-1/8-7`, `10-32`, `MF8x1`, `M16xPh3P1.5`) | listed in the unreadable row, never passed |
| 4 | unknown size | read, but its diameter is in no table (`M2.3x0.4`, `M70`) | listed in the unknown-size row, never passed |
| 5 | fine-only size | a metric diameter in `metric_fine_only_mm` (`M25x1.5`, and `M25` with no pitch), or a unified size in `unified_fine_only` (`#0-80`) | `thread.fine_pitch` |
| 6 | coarse | metric: the pitch equals the size's coarse pitch within 1e-6 mm, or **no pitch is written** (`M8`); unified: the threads per inch equal the size's UNC within 0.01 | counted in the checked row |
| 7 | fine | metric: a pitch smaller than the coarse pitch; unified: more threads per inch than UNC, beyond 0.01 (UNF, UNEF, 8-UN and every other constant-pitch series) | `thread.fine_pitch` |
| 8 | non-standard | metric: a pitch larger than the coarse pitch; unified: fewer threads per inch than UNC, beyond 0.01 | `thread.nonstandard_pitch` |

- **No pitch written is coarse, and says so.** ISO 965-1 omits the coarse pitch from a
  designation, so `M8` is M8x1.25 by the standard's own rule (50A). That is a cited rule, not an
  inferred value; every result that relies on it - the checked row - states it (section 8.6).
- **The size is matched first, then the pitch.** A metric size matches a row when its nominal
  diameter equals `size_mm` within 1e-6 mm; a unified size when its nominal diameter in inches
  (`parse_thread`'s millimetres / 25.4; a `#N` size is `parse_thread`'s 0.060 + 0.013 N) is within
  0.001 in of `diameter_in`. So `M10x1.25` is fine although 1.25 is M8's coarse pitch, and
  `M12x1.5` is fine although 1.5 is M10's: a pitch is never compared with "the set of coarse
  pitches".
- **Inch pitches compare as threads per inch,** `25.4 / pitch_mm`, within 0.01 of `unc_tpi`;
  never as millimetres rounded to six places.
- **The letters are not read.** `1/4-20 UNF` is judged by its numbers (20 threads per inch:
  coarse); a designation whose series letters contradict its numbers is not this check's finding.

### 8.2 Sources, owners, bought parts and suppression

| Source | Read from | Owning document |
|---|---|---|
| Hole Wizard tapped hole | `Hole.thread_designation` of every hole whose `hole_type` is `tapped` (null is unreadable); the other hole types carry a screw size, not a thread, and are not read | the document of the hole's component (`ComponentInstance.document_id`) |
| Cosmetic thread | `CosmeticThread.designation` (`""` is unreadable) | the document of the thread's component |
| Fastener row | `Fastener.thread_designation` of every row of any kind - a nut can be fine; a washer's or a pin's size is read the same way. A screw, bolt or nut row with no designation is unreadable; a washer, pin or `other` row with none states no thread and is not a source. A row `recognise_fasteners` does not return (its component or its document is not in the package) is unreadable, "its part is not in the package" | the fastener's own document (`RecognisedFastener.document_id`) |
| Screw recognised by name | the instances `recognise_fasteners(package)` builds in memory for a component with **no row** in `package.fasteners` - those whose `fastener.id` starts with `fst:name:` (`checks/fastener_identity.py` `_named_row`) - their `fastener.thread_designation`: screws and bolts, and pins, which are read as a pin's fastener row is, so one pin is treated alike whichever side recognised it (research R2.26 D13). Not `identity_source`: the extractor writes `name_parse` on every fastener row whose size and length both came from its name rather than its custom properties (`FastenerDumper.cs:153-155`), and `recognise_fasteners` passes a row's `identity_source` through, so a row is read once, as a fastener row, whatever its `identity_source` (D23) | the screw's own document |
| Drawings | not read for pitch: every finding's coverage limits say so | - |

**Bought parts** (52A; feature 013's part roles, read exactly as `checks/hygiene.py` reads them).
A tapped hole or cosmetic thread whose owning document `roles.graded(document_id)` is false - a
bought part that is not the review's root - is listed in the bought row and not classified.
With no roles attached (`review_roles(context)` is `None`) every document is graded; an id the
roles do not know is graded; an unclear document is graded and each finding that holds one of
its tapped holes or cosmetic threads carries the part-roles note while the question is open
(`part_roles.note_unclear`), because the answer can withdraw it. **Fasteners are classified
whatever their role**: choosing a bought fastener is a design choice. So a finding that holds
fasteners only carries no part-roles note: its "may be a bought part" would promise a withdrawal
no answer makes (research R2.26 D21).

**Suppressed features.** A `Hole` row carries no suppression flag. The hole is suppressed when the
`Feature` row with the same `document_id` as its owning document, `name` equal to its
`feature_name` and `configuration` equal to its component's `referenced_configuration` has
`suppressed: true`; it is then listed in the suppressed row and not classified. When no such row
exists or its `suppressed` is null, the hole is classified and each finding it is in carries the
limit "whether <feature> (<hole id>) is suppressed was not read: <reason>", <reason> being the
first of these that holds:

| Case | `<reason>` |
|---|---|
| the owning document has no `Feature` row | `its part's feature tree was not read` |
| it has rows, none in the component's `referenced_configuration` `{y}` | `the feature tree was read in configuration {x}, not {y}` - `{x}` the configuration its rows were read in (one: a tree is read in the document's active configuration; were there more, each through `report/names.and_list`, ascending) |
| it has rows in `{y}`, none named `feature_name` | `the feature tree holds no feature of that name` |
| the row's `suppressed` is null | `its suppression state could not be read` |

A cosmetic thread carries no feature name, so the join is never possible for it; each finding
holding one carries "a cosmetic thread carries no feature name, so whether it is suppressed was
not read". A fastener row whose component's
`suppression` is `suppressed` is listed in the suppressed row, whatever its `identity_source`;
the in-memory name-parsed screws (`fst:name:` ids) are resolved components by construction
(`recognise_fasteners` builds one only for a resolved component).

### 8.3 The table: `contracts/coarse-pitch.json`

One data source, transcribed from the standards (research R2.26 holds both tables and asks the
owner to check them against the shop's copies):

| Key | Shape | What it holds |
|---|---|---|
| `version` | integer | 1 |
| `source` | string | "Owner decision 2026-10-08 (50A): the shop uses coarse threads; fine pitch must be confirmed" |
| `standards` | `{metric, unified}` strings | the standard each table is transcribed from: ISO 261 (with ISO 965-1's omitted-pitch rule), ASME B1.1 |
| `metric` | `[{size_mm, coarse_pitch_mm}]`, ascending | the ISO 261 coarse pitch of every diameter that has one, M1 to M68 (40 rows) |
| `metric_fine_only_mm` | `[number]`, ascending | the ISO 261 diameters to 68 mm with fine pitches only (15) |
| `unified` | `[{size, diameter_in, unc_tpi}]`, ascending | the ASME B1.1 UNC threads per inch, #1 to 2 in (25 rows) |
| `unified_fine_only` | `[{size, diameter_in}]` | the unified sizes with no UNC thread: #0 |

Two copies, each pinned to this file by a test on its own side (the pattern of the shared name
vectors, research R2.11):

- **Python**: `reviewer/src/swreview/checks/coarse_pitch.yaml`, in the house style of
  `engagement_rules.yaml` and `head_dimensions.yaml` - a comment header citing the standards,
  then the same keys and values. `reviewer/tests/unit/test_coarse_pitch.py` asserts
  `yaml.safe_load(coarse_pitch.yaml) == json.load(coarse-pitch.json)`, so a value changed in one
  and not the other fails.
- **C#**: `extractor/SwReview.Extractor/Fasteners/CoarsePitch.cs` holds the `metric` rows only -
  all the C# name grammar reads (section 8.8).
  `extractor/SwReview.Extractor.Tests/CoarsePitchContractTests.cs` asserts they equal the file's
  `metric` rows, in order; the file is copied next to the test assembly by a `Content` item in
  `SwReview.Extractor.Tests.csproj`, as `fastener-name-vectors.json` is.

A change to the table is one commit: this file, then both copies.

### 8.4 Ids, statuses and severities

| Id | Kind | When | Status | Severity | Class (`attention_policy_v1`) |
|---|---|---|---|---|---|
| `thread.fine_pitch` | finding | classes 5 and 7 | `suspected` | `medium` | `interface` |
| `thread.nonstandard_pitch` | finding | class 8 | `suspected` | `medium` | `interface` |
| `thread.pitch` | coverage only | every row of section 8.6 | - | - | none: not a finding id |

- `thread.` joins the attention policy's `needs_judgement` prefixes, so these findings sort with
  the judgement families, never fold, are listed under the gate brief's "Needs your judgement" and
  land in the Review tab's **Decide** group. The policy stays `attention_policy_v1`: no existing id
  starts with `thread.`, so no past ranking moves.
- **No goal line moves** (the owner's decision 63A, research R2.26, which replaced D25). The
  **Fasteners** goal of `report/review_words_v1.yaml` owns the two finding ids by name, in its
  `items` (`items: [fasteners, thread.fine_pitch, thread.nonstandard_pitch]`, `prefixes:
  [fastener.]` unchanged), never the prefix `thread.`: `goal_of` takes a goal's `items` before any
  prefix (`report/finding_groups.py`), so a finding is listed in the Fasteners group and makes
  its goal line "issues found". The coverage-only `thread.pitch` belongs to no goal, as the
  part-roles rows do, and `goal_lines` passes over a row no goal owns, so the rows never reach a
  goal line: a thread-less or bought-only review whose `fasteners` close-out row is out of scope
  keeps "not applicable (out of scope)" (the committed replay sessions of both small assemblies
  read so today, counted 2026-10-08), a joint-less review with coarse holes keeps it too, and a
  review whose only fastener rows are unresolved rule rows keeps "not reached". The rows are listed
  with the review's coverage, as every check's are (`report.md` lists every row of each bucket,
  `report/markdown.py` `_render_coverage`, and the coverage block counts them). Neither finding id
  is ever a coverage row's check, so neither is read as a close-out row (`_goal_line` reads a
  goal's `items` rows as its close-out). T119 pins each case.
- **No checklist item closes on them.** The checklist closes an item on a finding whose check
  starts with the item's `check_prefix` (`agent/checklist.py`), and no item's prefix is `thread.`;
  the `fasteners` item (`check_prefix: fastener.`) is closed by the joint checks as before. The
  checklist text does not change.
- **Every review flags every one (51A).** The engineer confirms with the existing Accept
  disposition (`accepted`), which takes the finding out of the ranking for that review. Nothing is
  remembered across reviews: no allow-list, and `exceptions.json` is not read.
- `calculation` is null: a table lookup is a rule with no calculation, so passes are counted in
  one `checked` row rather than recorded as findings (research R2.21).

### 8.5 One finding per check and part, and its words

The findings are grouped by **(check, owning document)** (the owner's decision 57A, research
R2.26): every fine thread of one part is one `thread.fine_pitch` finding, and every non-standard
thread of it one `thread.nonstandard_pitch` finding, however many designations, hole features,
cosmetic threads or instances it covers. A fastener's part is its own document, the fastener's
file (D11), so a fastener's finding is never merged into the finding of the part it goes into.
Inside a finding the sources are grouped by **designation**, `parse_thread(designation).normalized`,
and each designation is listed with its sources and its coarse alternative, in the order of its
first source (source order: tapped holes by id, then cosmetic threads by id, then fasteners by
component id). Results are ordered by owning document id, then check id. Each is a
`DocumentResult` whose `documents` is the owning document and whose `component_ids` are the
sources' components, each once, in ascending order.

**Why one per check and part.** A finding's verdict key is its check, its component ids, its
drawing places and its configuration (`runner._verdict_key`), and the restate of section 8.7
folds each finding it produces again onto the earlier finding with the same key. Grouped per
designation, as first written (D3), two designations of one part share the check and the
components, so the restate folded both onto one id and withdrew the other as bought although the
part stayed custom (a probe on 2026-10-08; research R2.26, 57A). One finding per check and part
gives every finding a key of its own.

| Field | Text |
|---|---|
| `observed` | the finding's designation clauses, in its designation order, joined by "; ", then ` in {part}`: `{clause}; {clause} in {part}` |
| clause, fine, a size with a coarse pitch | `{designation} is fine pitch ({size}'s coarse pitch is {coarse}) on {sources}: {list}` |
| clause, fine, a metric fine-only size | `{designation} is fine pitch ({size} has no coarse pitch in ISO 261) on {sources}: {list}` |
| clause, fine, unified | `{designation} is fine pitch ({size}'s coarse thread is UNC, {tpi} threads per inch) on {sources}: {list}` |
| clause, fine, a unified fine-only size | `{designation} is fine pitch ({size} has no UNC thread in ASME B1.1) on {sources}: {list}` |
| clause, non-standard, metric | `{designation} is coarser than the standard pitch ({size}'s coarse pitch is {coarse}) on {sources}: {list}` |
| clause, non-standard, unified | `{designation} is coarser than the standard pitch ({size}'s coarse thread is UNC, {tpi} threads per inch) on {sources}: {list}` |
| `requirement`, `thread.fine_pitch` | `threads use the coarse (standard) pitch unless a fine pitch is deliberate` |
| `requirement`, `thread.nonstandard_pitch` | `threads use the coarse (standard) pitch; no standard pitch of a size is coarser than it` |
| `recommended_action`, every designation has a coarse pitch | `Confirm {designations} {is} intended in {part}, or change {it} to the coarse {alternatives}.` |
| `recommended_action`, every designation is a fine-only size | `Confirm {designations} {is} intended in {part}, or change {it} to a size that has a coarse thread.` |
| `recommended_action`, both kinds | `Confirm {designations} are intended in {part}, or change {with_coarse} to the coarse {alternatives}, and {fine_only} to a size that has a coarse thread.` |
| `inputs` | every source's entity id in source order - hole ids, cosmetic thread ids, fastener row ids (a row's id whatever its `identity_source`), and a name-parsed screw's component id (its `fst:name:` id is not an entity id) - then the table row cited for each designation, in the designation order (`ISO 261 coarse pitch of M8: 1.25 mm (coarse_pitch.yaml version 1)`, `ISO 261: M25 has fine pitches only (coarse_pitch.yaml version 1)`, `ASME B1.1 UNC of 1/4: 20 threads per inch (coarse_pitch.yaml version 1)`, `ASME B1.1: #0 has no UNC thread (coarse_pitch.yaml version 1)`), then `written as '{text}' on {id}` for each source whose text differs from its designation's `{designation}` |
| `coverage_limits` | `thread callouts on drawings were not read for pitch`, always; the suppression limits of section 8.2 that apply, in source order; the part-roles note of section 8.2 |

- `{designation}`: the designation's first source's text, trimmed, in source order.
- `{part}`: the owning document's `file_name` - the part, never its id (feature 009 FR-027).
- `{size}`: the table's size (`M8`, `1/4`, `#10`, `#0`); `{coarse}`: the coarse pitch with `:g`
  (`1.25`, `1`); `{tpi}`: the UNC threads per inch with `:g` (`20`, `4.5`).
- `{coarse_designation}`: `{size}x{coarse}` for metric (`M8x1.25`, `M6x1`), `{size}-{tpi}` for
  unified (`1/4-20`, `#10-24`); a fine-only size has none.
- `{designations}`: every designation's `{designation}`, in the designation order, through
  `report/names.and_list` (`M8x1`, `M8x1 and M6x0.75`, `M8x1, M6x0.75 and M10x1.25`);
  `{alternatives}`: the `{coarse_designation}`s of the designations that have one, in the same
  order, through `and_list`; `{with_coarse}` and `{fine_only}`: the designations that have a coarse
  pitch and those that are fine-only sizes, each through `and_list`. `{is}` and `{it}` are `is` and
  `it` for one designation, `are` and `them` for more. A `thread.nonstandard_pitch` finding always
  has a coarse pitch (class 8 needs one), so only `thread.fine_pitch` reaches the other two forms.
- `{sources}`: the designation's non-empty counts, through `report/names.plural` and `and_list`:
  `{k} tapped hole(s)` (k distinct feature names), `{m} cosmetic thread(s)` (m rows: a cosmetic
  thread has no feature name, so a part used twice lists its thread twice), `{f} fastener
  instance(s)`.
- `{list}`: every source of the designation, joined by ", " (never "; ", which separates the
  clauses): each tapped hole feature as `{feature_name} ({hole ids})`, in feature-name order, with
  the ids of every instance of the part; then each cosmetic thread as `cosmetic thread {thread id}`;
  then each fastener instance as its component id. The Review tab's title names each component id
  by its name (`report/titles.display_title`).
- No percent sign anywhere.

Examples (fictional):

- `M8x1 is fine pitch (M8's coarse pitch is 1.25) on 3 tapped holes: Tapped Hole1 (hol:0004), Tapped Hole2 (hol:0005), Tapped Hole3 (hol:0006); M6x0.75 is fine pitch (M6's coarse pitch is 1) on 1 tapped hole: Tapped Hole5 (hol:0009) in PLATE_FICT.SLDPRT`;
  `Confirm M8x1 and M6x0.75 are intended in PLATE_FICT.SLDPRT, or change them to the coarse M8x1.25 and M6x1.` - two designations of one part, one finding.
- `M8x1.5 is coarser than the standard pitch (M8's coarse pitch is 1.25) on 1 tapped hole: Tapped Hole4 (hol:0008) in PLATE_FICT.SLDPRT`;
  `Confirm M8x1.5 is intended in PLATE_FICT.SLDPRT, or change it to the coarse M8x1.25.` - the same part's `thread.nonstandard_pitch` finding, beside its `thread.fine_pitch` one.
- `M10x1.25 is fine pitch (M10's coarse pitch is 1.5) on 1 tapped hole: Tapped Hole1 (hol:0007, hol:0011) in BLOCK_FICT.SLDPRT` - one feature of a part used twice.
- `#10-32 is fine pitch (#10's coarse thread is UNC, 24 threads per inch) on 2 fastener instances: cmp:0012, cmp:0013 in SHC_10-32X0.5_FICT.SLDPRT`.
- `Confirm M8x1 and M25x1.5 are intended in FLANGE_FICT.SLDPRT, or change M8x1 to the coarse M8x1.25, and M25x1.5 to a size that has a coarse thread.` - both kinds in one finding.

### 8.6 The coverage rows

Every row is check `thread.pitch`, its scope the component and document ids of what it covers,
each once, in ascending order, and it is written only when it covers something. Lists are
complete, in source order. Counts go
through `report/names.plural`, and the verb agrees with them ("1 thread has", "2 threads have").

**What a row counts** (D24). A row of sources - checked, unresolved, unknown size, pipe, bought,
suppressed - counts one per source it lists, each by its entity id: a hole row (one Hole Wizard
feature on one component instance, so a part used twice counts each of its tapped-hole features
twice, `hol:0007` and `hol:0011`), a cosmetic thread row, and a fastener instance (a fastener row
by its row id, a screw recognised by name by its component id, as in a finding's `inputs`). Its
`{n}` is the number of ids it lists. A finding counts differently on purpose: its `{sources}`
counts a part's tapped holes by distinct feature name (section 8.5), because a finding is about one
part and the engineer changes the feature, while a row spans the package and counts what it
lists. The not-read row counts gaps, and the phases row counts nothing.

| Bucket | Covers | Reason |
|---|---|---|
| `checked` | every coarse thread | `{n} thread(s) have the coarse pitch: {designation} ({ids}), ...`, one entry per normalized designation; when any was written with no pitch, `; {m} of them have no pitch written, read as coarse because ISO 965-1 omits the coarse pitch from a designation` |
| `unresolved` | unreadable | `{n} thread(s) could not be read for pitch, so their pitch was not checked: {items}`; an item is `'{text}' on {id}`, `no designation on {id}`, or `'{text}' on {id} (its part is not in the package)` |
| `unresolved` | unknown size | `{n} thread(s) have a size in no pitch table (ISO 261 to M68, ASME B1.1 UNC to 2 in), so their pitch was not checked: {items}`; an item is `'{text}' on {id}` |
| `skipped` | pipe | `{n} pipe thread(s) were not checked for pitch; a pipe thread has its own series: {items}` |
| `skipped` | bought | `{n} thread(s) in bought parts were not checked for pitch: {part} ({ids}), ...` |
| `skipped` | suppressed | `{n} thread(s) on suppressed features or components were not checked for pitch: {items}`; an item is `{feature_name} ({hole id})` or `{fastener id} ({component id})` |
| `skipped` | not read by the extractor | `{n} extractor gap(s) left holes, cosmetic threads or fasteners unread, so their pitch was not checked: {reasons}`, each gap's `reason` verbatim, joined by "; ", ordered by `entity_kind` (`hole`, then `thread`, then `fastener`), then `entity_id` with null first, then `reason` - never in the package's gap order, so the row reads the same however the package lists its gaps (research R2.26 D20); its scope the component ids among the gaps' `entity_id`s. Written, on a `full` package, for every gap that names no row of the array its `entity_kind` stands for (research R2.26 D20): **(a)** a `hole` gap that names no row of `package.holes` - its `entity_id` null (a component that is lightweight, suppressed or unloaded, or has no loaded model, `HoleDumper.cs:120-150`; a node whose handle is its document, `:134-138` and `:156-158`, and `ComponentDocuments.cs`, owner decision 166A, research R2.27 and R2.28 - a part reviewed on its own, `'{key}' is reviewed as a document of its own, not as a component of an assembly, so its holes and threads were not read.`, a part a drawing references, `'{key}' is referenced by a drawing, not reviewed as a component of an assembly, so its holes and threads were not read.`, and an assembly a drawing references, the same up to `so the holes and threads of its own assembly features were not read.` (its components are read as components), and none for a document the hole read reached through a resolved component of it in the same configuration, its loaded model (research R2.29); a Hole Wizard feature whose read threw, `:180`; the hole phase failed or aborted, `PackageWriter.cs:809-825`) or an id no hole carries (a hole whose `GetDefinition` returned nothing, `HoleDumper.cs:213-222`, its allocated hole id; and a component's id, as the mechanical fixture's `cmp:0010` gap `no Hole Wizard feature of this component could be read` - a gap its generator writes, `tests/fixtures/mechanical/generate_fixtures.py`, which no extractor code writes today); **(b)** a `thread` gap that names no row of `package.threads` - null (a cosmetic thread whose read threw, `HoleDumper.cs:186`) or an id no thread carries (its `GetDefinition` returned nothing, `:425-434`); **(c)** a `fastener` gap that names no row of `package.fasteners` - null (identifying a component threw, `FastenerDumper.cs:73`, a gap that cannot say whether the component was a fastener, so it is listed; a part whose handle is its document, `'{key}' is reviewed as a document of its own, not as a component of an assembly, so whether it is a fastener was not read.` or, for a part a drawing references, `'{key}' is referenced by a drawing, not reviewed as a component of an assembly, so whether it is a fastener was not read.`, `:89-93` and `:83`, 166A, research R2.28 - none for an assembly a drawing references, whose parts are identified as its components, nor for a document the fastener read reached through a resolved component of it in the same configuration, its loaded model (research R2.29); the fastener phase failed or aborted) or an id no row carries (the read threw after the id was allocated, `:124`). A gap that names a row that was read - a hole's thread depth or axis, a cosmetic thread's callout or hand, a fastener's length, head or axis - is about a row that is classified, and is not one |
| `skipped` | the hole and fastener phases | Written in one of two cases. **(1)** `package.extractor.profile` is `model_check` or `standards`: `tapped holes, cosmetic threads and fastener rows were not read for pitch: the hole and fastener phases did not run (profile {profile})`. **(2)** A `full` package with no `reused_from` whose `extractor.phases` holds a `hole` or `fastener` row with status `skipped` - a phase that never ran because one before it aborted, which records no gap of its own (`PackageWriter.cs:836-874`, the phase log; `ExtractorInfo.phases`): `{what} were not read for pitch: the {phases} did not run in this dump`, `{what}` being `tapped holes and cosmetic threads` for the hole phase, `fastener rows` for the fastener phase and `tapped holes, cosmetic threads and fastener rows` for both, `{phases}` `hole phase`, `fastener phase` or `hole and fastener phases`. A `failed` or `aborted` hole or fastener phase records its own gap with a null `entity_id` (`PackageWriter.cs:809-825`), so it is in the not-read row, not here. A package with no phase rows (written before schema 1.3.0, or assembled from exported files) is read by its gaps alone; a reused package's rows are all `skipped` by design and are not read for this, because reuse refuses a package whose dump failed or aborted (`benchmark/reuse.py` `_aborted_dump_refusals`). In both cases screws named by their parts are still checked (research R2.26 D17) |
| `skipped` | nothing at all | `no tapped hole, cosmetic thread or fastener in the package states a thread`, on a `full` package with no source, no gap of the not-read row and no phases row: while either of those stands, the package may hold threads the extractor did not read, so that row is written instead. A part reviewed on its own, or a model a drawing references, gives no hole row but the `hole` gap (and, for a part, the `fastener` gap) its document node records (research R2.27 and R2.28, 166A, T128 and T132), so it reaches the not-read row and never this one; reading those holes is T130 for a part root and T134 for a model a drawing references |

### 8.7 The tool

`check_threads()` in `reviewer/src/swreview/tools/checks_mechanical.py`, appended to
`CODE_FIRST_CHECKS` after `check_hygiene`, so the pre-run calls it, lever 13 withholds it once it
has completed, and the re-call guard keys it `(tool,)`. It takes no argument and reads the part
roles through `review_roles(context)`; the work is
`checks/thread_pitch.run_thread_checks(package, roles=None)`, a plain function of the package.
Its description, under the 160-character cap:

```text
Flag every fine or non-standard thread pitch on tapped holes, cosmetic threads and fasteners; the shop uses coarse threads.

Notes:
    Takes no argument. Threads it cannot read, pipe threads and threads in bought parts are
    listed, never passed.
```

**Its rows restate, never add.** A call first withdraws every `thread.pitch` row from `checked`,
`skipped` and `unresolved` (`context.withdraw_coverage`, as `check_drawings` restates its rows,
`tools/drawings.py:134`), then records the findings through `_record_documents` and the rows
through `_record_coverage`, and returns `_summary`'s counts with `"threads"` (the sources read) and
`"coarse"` (the passes). The rows state the current classification of every thread, so a second
call leaves one set: the answer to the part-roles question restates the check through the
registry's dispatch (`runner._restate`, a real call the re-call guard does not answer), and
appended rows would keep the old checked row counting a newly bought part's tapped holes beside
the new bought row listing them, every count twice (research R2.26 D14). The restate is with the
other role-reading checks (`runner.ROLES_RESTATED`, D10), and `_restate` reconciles its findings as
it does theirs: a finding the call produces again keeps its id, and one it no longer produces - a
tapped hole or cosmetic thread of a part the engineer then calls bought - is withdrawn with
`runner.BOUGHT_WITHDRAWAL`'s reason, as a hygiene finding is. A fastener's finding stays: its role
does not grade it. Because there is one finding per check and part (section 8.5, 57A), each
finding's verdict key is its own: a part the answer leaves custom keeps its one finding under its
id however many designations it lists, its part-roles note dropped in place, and - once T126 has
landed (58A) - the disposition the engineer recorded on it before the answer, so an Accept that
confirmed a fine thread is not undone by the restate.

### 8.8 The parser fixes

**`parse_thread`** (`reviewer/src/swreview/checks/fastener.py`; Python only - the C# side has no
designation parser):

1. A comma between two digits is a decimal point: `M8x1,25` reads pitch 1.25 (it read 1.0, a
   false fine flag).
2. The multiplication sign `×` is a pitch marker like `x` and `*`: `M8×1` reads pitch 1 (it read
   none, a false coarse).
3. A hyphen after a metric size introduces the pitch when the number after it is not followed by
   a letter or a digit: `M8-1.25` reads 1.25, `M10-1.5-6H` 1.5, `M8-1` 1; `M8-6H` and `M8-6g` read
   no pitch, because `6H` and `6g` are tolerance classes. No pitch is read only for a tolerance
   class: one digit followed by a tolerance position letter, `e`, `f`, `g` or `h` in either case
   (ISO 965-1). Two kinds of letter after the number keep it the pitch: a pitch marker followed
   by a digit starts a length, so `M4-0.7x12` (the vendor form section 1 reads as pitch and
   length) reads 0.7 and `M8-1 x 20` reads 1 (research R2.26 D18); and `LH` or `RH`, ignoring
   case, is the thread's hand, so `M10-1.25LH` reads 1.25 (D19). Any other letter after the
   number makes the designation unreadable (`M10-1.25G`, `M8-1x`): read with no pitch it would
   pass as coarse (D19). (Each read no pitch before.)
4. A pitch marker straight after a metric size with no number after it makes the designation
   unreadable: `M16xPh3P1.5` (a multi-start thread's lead and pitch) and `M8x` (they read as M16
   and M8 with no pitch, which this check would have read as coarse).

Everything else reads as it did: `M6 x 1` is pitch 1, `M10x35` is pitch 35 (text that states a
35 mm pitch is flagged non-standard - the text is what is wrong), whitespace is still removed
before reading, so a tolerance class written after a space joins the pitch (`M8x1.25 6H` reads
1.256, flagged non-standard; `M8-1.25 6g` is unreadable: a known limit, research R2.26, each a
flag or a listing, never a pass), and the unified forms are unchanged.

**`is_pipe_thread(designation) -> bool`**, beside `parse_thread`, the one place pipe tokens are
known (DRY): true when a whole run of letters, ignoring case, is `NPT`, `NPTF`, `NPS`, `NPSM`,
`BSP`, `BSPP` or `BSPT`, or when the trimmed text starts, ignoring case, with `G`, `R`, `RC`,
`RP`, `PT` or `PF` followed by optional spaces and a digit. A tolerance class letter
(`M8x1.25-6G`) is neither. `parse_thread` itself does not change for pipe text: `1/8-27 NPT`
still reads as a unified thread to `fastener.thread_match`.

**The name grammar** (both parsers, `checks/fastener_names.py` and
`extractor/SwReview.Extractor/Fasteners/FastenerNameParser.cs`, pinned by
`fastener-name-vectors.json`): one bare positive integer after a metric size, with nothing after
it, is a **pitch** when it is at most that size's coarse pitch (`coarse-pitch.json`'s `metric`
rows), otherwise a **length**. Zero and a negative number are never a pitch: they keep the rule
they had, a length that is refused, so `M6 x 0` is `M6` with no length, as both parsers read it
today (D22). A size with no coarse pitch - a fine-only or unknown size - keeps the rule it had, a
length. A decimal after the size is a pitch, two values are a pitch and a length, and a hyphen
pitch is a pitch, as before.

### 8.9 Vectors

`parse_thread`, `is_pipe_thread` and the class, for the check (`test_checks_fastener.py`,
`test_coarse_pitch.py`):

| Input | Read as | Class and outcome | Before 2026-10-08 |
|---|---|---|---|
| `M8x1.25` | M8, pitch 1.25 | coarse | same |
| `M8 x 1.25` | M8, pitch 1.25 | coarse | same |
| `M8x1.25-6g` | M8, pitch 1.25 (`6g` a tolerance class) | coarse | same |
| `M8x1.25-6G` | M8, pitch 1.25; not a pipe thread | coarse | same |
| `M8x1.25 6H` | M8, pitch 1.256 (whitespace is removed before reading, so the grade's digit joins the pitch) | `thread.nonstandard_pitch`: a false flag, never a false pass (research R2.26, known limits) | same |
| `M8-1.25 6g` | unreadable (read as `M8-1.256G`; `1.256G` is no tolerance class) | unreadable: listed, never passed (research R2.26, known limits) | M8, no pitch: a false coarse |
| `M8x1,25` | M8, pitch 1.25 | coarse | pitch 1.0: a false fine flag |
| `M8-1.25` | M8, pitch 1.25 | coarse | no pitch |
| `M10-1.5-6H` | M10, pitch 1.5 | coarse | no pitch |
| `M4-0.7x12` | M4, pitch 0.7 (`x12` a length) | coarse | no pitch |
| `M8-1 x 20` | M8, pitch 1 (`x 20` a length) | `thread.fine_pitch` | no pitch: a false coarse |
| `M10-1.25LH` | M10, pitch 1.25 (`LH` the hand) | `thread.fine_pitch` | no pitch: a false coarse |
| `M8-1.25rh` | M8, pitch 1.25 (`rh` the hand, any case) | coarse | no pitch |
| `M10-1.25G` | unreadable (`1.25G` is no tolerance class) | unreadable | M10, no pitch: a false coarse |
| `M8-1x` | unreadable (a pitch marker with no number after it) | unreadable | M8, no pitch: a false coarse |
| `M8-6H` | M8, no pitch (`6H` a tolerance class) | coarse, no pitch written | same |
| `M8-6g6h` | M8, no pitch (`6g6h` a tolerance class) | coarse, no pitch written | same |
| `M8` | M8, no pitch | coarse, no pitch written | same |
| `M6x1` | M6, pitch 1 | coarse (M6's coarse pitch is 1) | same |
| `M7x1` | M7, pitch 1 | coarse | same |
| `M3.5x0.6` | M3.5, pitch 0.6 | coarse | same |
| `M8x1` | M8, pitch 1 | `thread.fine_pitch` | same |
| `m8x1` | M8, pitch 1 | `thread.fine_pitch` | same |
| `M8×1` | M8, pitch 1 | `thread.fine_pitch` | no pitch: a false coarse |
| `M8-1` | M8, pitch 1 | `thread.fine_pitch` | no pitch |
| `M8x1.0` | M8, pitch 1 | `thread.fine_pitch` | same |
| `M8x0.75` | M8, pitch 0.75 | `thread.fine_pitch` | same |
| `M10x1.25` | M10, pitch 1.25 | `thread.fine_pitch` (1.25 is M8's coarse pitch, not M10's 1.5) | same |
| `M12x1.5` | M12, pitch 1.5 | `thread.fine_pitch` (1.5 is M10's, not M12's 1.75) | same |
| `M25x1.5` | M25, pitch 1.5 | `thread.fine_pitch`, a fine-only size | same |
| `M25` | M25, no pitch | `thread.fine_pitch`, a fine-only size | same |
| `M5.5x0.5` | M5.5, pitch 0.5 | `thread.fine_pitch`, a fine-only size | same |
| `M8x1.5` | M8, pitch 1.5 | `thread.nonstandard_pitch` | same |
| `M10x35` | M10, pitch 35 | `thread.nonstandard_pitch` | same |
| `M2.3x0.4` | M2.3, pitch 0.4 | unknown size | same |
| `M70` | M70, no pitch | unknown size | same |
| `M16xPh3P1.5` | unreadable | unreadable | M16, no pitch: a false coarse |
| `M8x` | unreadable | unreadable | M8, no pitch |
| `MF8x1` | unreadable | unreadable | same |
| `1/4-20` | 1/4, 20 threads per inch | coarse | same |
| `1/4-20 UNC-2B` | 1/4, 20 | coarse | same |
| `1/4-20 UNF` | 1/4, 20 (the letters are not read) | coarse; the contradiction is not this check's | same |
| `0.250-20` | 1/4, 20 | coarse | same |
| `#6-32` | #6, 32 | coarse (#6's UNC is 32) | same |
| `#10-24` | #10, 24 | coarse | same |
| `1.000-8` | 1 in, 8 | coarse | same |
| `1/4-28` | 1/4, 28 | `thread.fine_pitch` | same |
| `1/4-28 UNF-2A` | 1/4, 28 | `thread.fine_pitch` | same |
| `1/4-32` | 1/4, 32 (UNEF) | `thread.fine_pitch` | same |
| `#10-32` | #10, 32 | `thread.fine_pitch` | same |
| `#10-32 UNF` | #10, 32 | `thread.fine_pitch` | same |
| `0.190-32` | #10, 32 | `thread.fine_pitch` | same |
| `1.125-8` | 1-1/8, 8 (8-UN) | `thread.fine_pitch` (finer than UNC 7) | same |
| `#0-80` | #0, 80 | `thread.fine_pitch`, a fine-only size | same |
| `1/4-18` | 1/4, 18 | `thread.nonstandard_pitch` | same |
| `1/8-27` | #5's 0.125 in, 27 | `thread.nonstandard_pitch`: a pipe size written with no pipe token reads as a unified thread | same |
| `1/8-27 NPT` | pipe | pipe | read as a unified thread |
| `NPT 1/8`, `1/2-14 NPTF`, `3/4 NPSM`, `1/2 NPS` | pipe | pipe | unreadable, or a unified thread |
| `G1/4`, `G 1/2 A`, `R1/4`, `Rc1/4`, `Rp 1/2`, `PT1/8`, `PF1/4` | pipe | pipe | unreadable |
| `1/4 BSPP`, `1/4 BSPT`, `1/2 BSP` | pipe | pipe | unreadable |
| `3/8` | unreadable (how a Hole Wizard pipe tap arrives) | unreadable | same |
| `1-8`, `1-1/8-7`, `10-32`, `No. 10-32` | unreadable | unreadable | same |
| `""`, null | no designation | unreadable | same |

`fastener.thread_match` through `check_fastener_joint` (`test_checks_fastener.py`), whose outcome
the parser fixes move for these spellings:

| Screw | Tapped hole | `fastener.thread_match` | Before 2026-10-08 |
|---|---|---|---|
| `M8x1,25` | `M8x1.25` | `checked_within_scope`, the pitch compared | `demonstrated`: 1.0 against 1.25, a false mismatch |
| `M8-1.25` | `M8x1.25` | `checked_within_scope`, the pitch compared, no one-sided-pitch limit | `checked_within_scope` on the diameter alone, with the one-sided-pitch limit |
| `M8-1` | `M8x1.25` | `demonstrated`, the pitch compared | `checked_within_scope` on the diameter alone, with the limit: a missed mismatch |
| `M16xPh3P1.5` | `M16x1.5` | `unresolved`, naming `'M16xPh3P1.5'` (D9) | `checked_within_scope` on the diameter alone, with the limit |

The name grammar (the rows FP3 adds to `fastener-name-vectors.json`, source `configuration`,
kind and head null):

| Text | Thread | Length (mm) | Before 2026-10-08 |
|---|---|---|---|
| `M8x1` | `M8X1` | null | `M8`, length 1 |
| `M10x1` | `M10X1` | null | `M10`, length 1 |
| `M20x2` | `M20X2` | null | `M20`, length 2 |
| `M6x1` | `M6X1` (M6's coarse pitch) | null | `M6`, length 1 |
| `M10x35` | `M10` | 35.0 | same |
| `M8x10` | `M8` | 10.0 | same |
| `M3x1` | `M3` (1 is more than M3's 0.5) | 1.0 | same |
| `M25x2` | `M25` (a fine-only size keeps the old rule) | 2.0 | same |
| `M2.3x1` | `M2.3` (an unknown size keeps the old rule) | 1.0 | same |
| `M8x1 x 20` | `M8X1` | 20.0 | same |
| `M6 x 0` | `M6` (zero is never a pitch, and a length must be positive) | null | same |

### 8.10 Reported twice, on purpose

A fine screw in a coarse tapped hole (`M8x1` into `M8x1.25`) is a demonstrated
`fastener.thread_match` mismatch on the joint, exactly as before, **and** a `thread.fine_pitch`
finding on the screw's part: the first says the two do not fit, the second asks whether the fine
pitch was meant. Both stay. The reverse - a screw named `M8` in an `M8x1` hole - still passes
`fastener.thread_match` on its diameter with its one-sided-pitch coverage note (`_thread_match`
in `checks/fastener.py` does not adopt the no-pitch rule), and this check flags the hole. A
screw whose names disagree on the pitch stays `fastener.identity`'s; this check reads the
designation `recognise_fasteners` chose.

### 8.11 Acceptance on the committed fixtures

No replay or mechanical fixture states a fine thread, so the check records **no finding** on any
of them (SC-010; the goldens of T118 are this section's flags and rows, written for it):

| Fixture | Tapped holes | Recognised fasteners | Rows |
|---|---|---|---|
| `tests/fixtures/replay/big-assembly` | 11 coarse, one `3/8` | none | checked (11: each of the 12 holes' feature rows is found in its component's referenced configuration and reads not suppressed, so no suppressed row), unresolved (`'3/8' on hol:0009`), not read by the extractor (3 gaps: two lightweight components and one suppressed) |
| `tests/fixtures/replay/small-assembly-a` | one `M5x0.8` | none | checked |
| `tests/fixtures/replay/small-assembly-b` | one `M5x0.8` | none | checked, not read by the extractor (2 gaps: two lightweight components) |
| `tests/fixtures/mechanical/big-assembly` | 12 coarse | 68 coarse screws | checked, not read by the extractor (1 gap: `cmp:0010`'s `no Hole Wizard feature of this component could be read`) |
| `tests/fixtures/mechanical/small-assembly` | one `M5x0.8` | none | checked |

The replay fixtures' figures and every fixture's `hole` gaps were counted on 2026-10-08 (the other
`hole` gaps of the big replay and mechanical fixtures name holes that were read, so they are not
in the row); no fixture has a `thread` or `fastener` gap that names no row, every fixture is a
`full` package whose `hole` and `fastener` phases are `ok`, so none has a phases row, and every
count is of hole rows (each tapped-hole feature of these fixtures is on one component instance:
12, 1, 1, 12 and 1 rows, counted the same day). The mechanical fixtures hold no feature rows, so whether their holes are suppressed
is not read; they record no finding, so no finding carries that limit.
