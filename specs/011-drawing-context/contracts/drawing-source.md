# Contract: The Drawing Source

Normative for FR-017 to FR-025, FR-029, User Stories 3 and 4, SC-003, SC-004 and SC-010. Python
only; every function here is pure over the package (and the profile where named).

## 1. Which views are usable (`drawings/evidence.py`)

`DrawingIndex.for_package(package)` walks `drawing_records` in document-id order, sheets by `index`,
views by id, and yields a `ViewEvidence` for each view whose `referenced_document_id` is a package
document. A view is **usable** for a component `c` of that document when all hold, and otherwise
carries the first failing reason:

| # | Condition | Reason when it fails |
|---|---|---|
| 1 | the drawing is not in detailing mode (`is_detailing_mode` is false) | "drawing {id} is in detailing mode, so its views load no model" (null: "whether drawing {id} is in detailing mode was not read") |
| 2 | `is_model_loaded` is true | "view {name} of {drawing} shows a model that is not loaded" |
| 3 | `is_model_out_of_date` is false | "view {name} of {drawing} is out of date with its model" (null: "whether view {name} is up to date was not read") |
| 4 | `referenced_configuration` equals `c.referenced_configuration` | "view {name} of {drawing} shows configuration '{a}'; the review read '{b}'" (null: "the configuration view {name} shows was not read") |

For a part used in two configurations, a view is usable for the instances of the configuration it
shows and for no others; a subject names its component, so the question is always per instance.

## 2. The native conversion (`drawings/native.py`)

`native_dimension(record, view, sheet, drawing) -> Dimension | str`:

- `nominal` is `record.value` (a length in the unit recorded, or an angle); no value, or a value
  with no unit (feature 006's `dimension_unit` gap), returns the reason instead;
- `tolerance` is `record.tolerance` when set; a `NONE`, `BLOCK` or `GENERAL` type, or an unread
  tolerance, is `Tolerance(kind="none", ...)` - the IR's "not stated on the drawing", which is what
  `find_dimensions` has always reported for an untoleranced PDF dimension;
- `source` is `SourceRef(document_id=drawing.document_id, sheet=sheet.name, view=view.name,
  annotation=record.id, persist_ref=record.persist_ref)`;
- `text_as_read` is composed: `text_prefix` + the value at `written_precision` decimals + the
  tolerance text + `text_suffix`, with `above`/`below` on their own lines, and the word
  `(composed)` appended, because the rendered string is not read (probe D7).

`written_precision(record, drawing)`: `precision_raw` when `uses_document_precision` is false;
`drawing.dimension_precision_raw` when it is true (the default probe D4 is expected to confirm; if
D4 finds `units_decimal_places_raw` governs, T064 changes this one line); `None` when a needed read
is null or negative. `written_unit(record, drawing)`: `units_raw` when `uses_document_units` is
false, else `drawing.length_unit_raw`; `mm` for 0, `in` for 3, `None` otherwise.

`get_drawing_sheet`, `find_dimensions` and `refs.resolve_dimension` read native sheets through
`native_sheets(package, document_id)` and `native_dimension` beside the PDF-ingested ones:

| Tool | Native behaviour |
|---|---|
| `get_drawing_sheet(document_id, sheet_name)` | a native sheet by `name`, preferred over an ingested sheet of the same name; `available_sheets` lists `{name, source}` for both kinds when a document has native sheets (today's plain list otherwise); the payload is the sheet record with its views, dimensions, annotations, notes, revision tables and tables, persistent references removed by feature 008's view |
| `find_dimensions(document_id, text_regex, near_view)` | every native dimension that converts, filtered on `text_as_read`; `near_view` matches the view name for a native dimension (no bounding boxes) |
| `resolve_dimension(package, ref)` | matches `document_id`, `sheet` and `annotation` (the `ddm:` id) across both kinds; still refuses none or more than one |

A package with no native sheet returns exactly today's payloads (FR-037).

## 3. The binding (`drawings/binding.py`)

```python
DRAWING_BINDING_VALIDATED: bool = False   # T066 sets True, one edit, citing probe D6 and D8
```

`bindings_for(index, package, subject) -> tuple[DrawingBinding, ...]` returns, in the index's order,
every record that ties to `subject` (feature 010's `ToleranceSubject`, which names the instance,
component, document and faces):

| Subject kind | Record | Route `attached_face` | Route `model_dimension` |
|---|---|---|---|
| `hole_size`, `pin_size` | a display dimension of type diameter (6), radial (5), diametric linear (15) or radial linear (14), or `is_hole_callout` | an `attached_faces` reference, scoped to the subject's document, equals the persistent reference of one of the subject's faces | `record.name` without its `@document` suffix equals the name, without suffix, of the one `ModelDimension` feature 010's source 3 binds to this subject (unique by value in the document) |
| `hole_position` | an annotation of type 5 with a position or coaxiality frame | as above | - |

Only records in a view usable for the subject's component (section 1) are considered; a record
excluded by section 1 is listed in the answer's reason with that section's words. A display
dimension whose `is_overridden` is true, or unread, binds nothing: its displayed value is not the
model's ("dimension {id} is overridden on the drawing", the defect
`standards.drawing.dimensions_not_overridden` reports). While
`DRAWING_BINDING_VALIDATED` is false, `bindings_for` returns nothing and the drawing answer's reason
is "drawing callouts are read but not yet validated on a seat against a drawing whose callouts are
known (feature 011 research R2.8)".

## 4. The drawing answer and the resolver (`checks/tolerances.py`)

`drawing_answer(package, subject, index=None) -> DrawingAnswer` replaces `drawing_tolerance`:

1. **Limits.** The first binding whose record states a tolerance (`bilateral`, `symmetric`,
   `limits`, or a fit class the ISO 286 table carries, through 010's `iso_dimension`) is the
   `dimension`, converted by `native_dimension`; a radius's limits are doubled (010's `_doubled`).
   A later binding with limits differing by more than `LENGTH_EQUAL_MM` sets `conflict`: "drawing
   {a} and drawing {b} give {subject} different tolerances; {a} is used".
2. **Written precision.** Otherwise, the bindings whose tolerance type is `NONE` (0) or `BLOCK` (10)
   supply `decimal_places` and `unit` when every one of them agrees; disagreement supplies neither and
   says "{a} writes {n} decimals and {b} writes {m}". A `GENERAL` (11) binding supplies nothing:
   "{record} is governed by the drawing's general tolerance table, which is not converted".
3. **Position.** For `hole_position`, the first bound frame's zone through 010's `_frame_zone`
   (generalised to take a list of `GtolFrame`); a value without a unit is read in the drawing's
   `length_unit_raw`, cited "read in the drawing's unit, {mm|in}"; an unread unit binds nothing.
4. Nothing bound: `why` names the first failing reason in the order binding switch, no usable view,
   no attachment or model dimension, no tolerance.

`resolve_tolerance` changes in two lines' worth of behaviour and no others:

- source 1's answer is `(answer.dimension, answer.cited)` when a dimension bound, else `answer.why`;
  a source-1 `conflict` is joined to the resolved tolerance's `conflict`;
- source 5 (general) is asked about `replace(subject, decimal_places=answer.decimal_places)` when the
  subject has none and the drawing supplied one, **and** only when `answer.unit` equals the
  profile's `drawing.dimension_unit` (version 3); with a version 2 profile, or an empty
  `dimension_unit`, the general answer is "the profile does not say which unit its decimal places
  are counted in (drawing.dimension_unit)"; with another unit, "the drawing writes {subject} in
  {unit} and the profile's bands are counted in {unit}".

`ResolverLookup.holds_any_source()` is also true when `DRAWING_BINDING_VALIDATED` and some usable
view carries a dimension that could bind - one with a stated tolerance, or an untoleranced one with a
written precision under a version 3 profile with bands and a unit.

Precedence, `also_found` and the conflict rule of 010 section 4 are otherwise unchanged; with no
drawing record, every answer is byte-identical to today's except source 1's reason, which becomes
"no drawing of {document} was read" instead of "not available before feature 011".

## 5. The tests

`test_drawing_evidence.py` (section 1, each row at its boundary, a part in two configurations,
shuffled input); `test_native_dimension.py` (section 2: value and unit, angle, no unit, tolerance
kinds, composed text, precision and unit derivation, the three tools on native and mixed sheets,
and a package with no native sheet byte-identical); `test_drawing_binding.py` (section 3: each route,
each kind, an edge-derived face, a suffix-spelled name, an ambiguous model dimension, the switch
off); `test_tolerances.py` extended (section 4: every numbered rule, the unit rule both ways, the
version 2 profile, `holds_any_source`, and the "not available before feature 011" rows edited
deliberately). SC-003 and SC-004 are the acceptance test over the `plate-drawing` fixture with the
switch set (T038).
