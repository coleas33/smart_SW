# Contract: The Drawing Brief

Normative for FR-038 to FR-043, User Story 6 and SC-006.

## 1. The function, the tool and the command

```python
# reviewer/src/swreview/drawings/brief.py
BRIEF_VERSION = 1
BRIEF_MAX_BYTES = 6_000

def build_brief(package: EvidencePackage, session: ReviewSession | None,
                profile: StandardsProfile | None, document_id: str) -> DrawingBrief: ...
```

| Entry | Arguments | Where |
|---|---|---|
| `get_drawing_brief(document_id)` | the context's package, session and attached standards run's profile (never loaded by the tool) | the drawing family (`questions.md` section 1) |
| `swreview drawing brief --package DIR --document ID [--run RUN_DIR] [--profile PATH]` | the package (the CLI's existing `PackageOption`); the run folder's `session.json` for answers, when given; the profile, when given | `cli.py`, a new `drawing` sub-application beside `check`, `rms` and `remodel`; prints the brief's JSON and exits 0, or the refusal and exits 2 |

## 2. The sections, in order

| Key | Source (reused, never recomputed) | Content | Bound |
|---|---|---|---|
| `brief_version` | constant | `1` | |
| `document` | `documents[]`, `components[]`, the profile's `hygiene.description_property` when a version 2 or 3 profile names one | id, file name, kind, the configuration(s) its instances use, description, material, mass, instance count | |
| `assembly` | feature 010's joint map via `tools/joint_context.joint_analysis` (session) or `build_joint_map` (command); the session's contacts and interference findings | per pattern group: joint ids, kind, the partner documents' file names, the fastener's parsed size, the largest offset; the contact count; the interference finding ids naming the document | 20 pattern groups |
| `interfaces` | for every joint instance on the document: 010's `ToleranceSubject`s through `ResolverLookup` (with 011's drawing source); 010's `check_nominal_alignment` result's `callout` | per subject: its label, its joint, `{source, cited}` or `{unresolved: [[source, why], ...]}`, the drawing record bound or why none (`drawing-source.md`), the position budget callout | 20 subjects |
| `drawing` | `DrawingIndex`, the records | per attached or root drawing showing the document: document id, file name, sheet count, views showing the document, usable views, the unusable views' reasons, and counts of dimensions, toleranced dimensions, hole callouts, geometric tolerances, datums (labels), surface finishes; notes on those sheets verbatim; tables by kind with title and rows; and the document's candidate file, if any | 10 notes of at most 200 characters, 5 tables of at most 10 rows, 10 candidates |
| `answers` | the session's answered `EvidenceRequest`s whose `entity_ids` include the document or one of its component ids, in session order | request id, the short `question` or else `what`, the answer | 10 |
| `conformance` | US7's comparison for each drawing showing the document | the setting names that differ, and those skipped | |
| `omitted` | the trimming | per list, how many items were left out; empty object when none | |

Every list is in a fixed order (traversal, then id); the whole is deterministic for a package,
session and profile, and shuffling any array of the package changes no byte.

## 3. The bound

Compact JSON (`separators=(",", ":")`, UTF-8) of at most `BRIEF_MAX_BYTES`. Each list is first cut
to its bound above; if the whole still exceeds 6,000 bytes, items are removed one at a time from the
end of the currently longest list (ties by the key order above) until it fits, each removal counted
in `omitted`. A brief never fails for size.

## 4. What it never carries

- **A persistent reference**: no base64 reference, no `persist_ref` key; entities are named by
  package id.
- **A profile value**: the profile is named by identity (the first 12 hex of its sha256) when
  attached; `conformance` names settings, never their values (006 FR-034).
- **A number the evidence does not contain**: every tolerance comes from the resolver with its
  citation; a missing one is `unresolved` with what was searched.

## 5. Refusals

| Input | Refusal |
|---|---|
| an id that is not a document of the package | "document {id} is not in this package; the documents that can be briefed are: {part and assembly ids, first 20}" |
| a drawing document's id | "{id} is a drawing; a brief is of a part or assembly. The documents it shows: {ids}" |

## 6. The tests

`test_drawing_brief.py` over the `plate-drawing` fixture (with the binding switch set): every
section's content for the plate - its two joints, the dowel hole's size bound by the drawing with
the model dimension also found, its position budget callout, the drawing's sheets and callouts, the
one answered question; the block's brief naming its candidate; determinism under shuffling; no
persistent reference and no fictional profile value in the bytes; the refusals; a pathological
package built in the test (500 notes, 300 dimensions, 60 joints) at most 6,000 bytes with `omitted`
counting exactly what was cut. `test_tools_get_drawing_brief.py`: the tool through the dispatch and
the command's output equal for the same inputs.
