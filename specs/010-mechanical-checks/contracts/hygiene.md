# Contract: Hygiene

Normative for FR-019, FR-020 and User Story 7. `checks/hygiene.py`; the data-card change in
`checks/standards/document.py`.

## 1. The documents

The part and assembly documents reached by the component tree from the root, each once. A
document whose properties were not read (a `document` gap naming its properties) is left out of
every property check and named in one `skipped` item `hygiene.coverage`.

## 2. The checks

| Check | Needs | Rule | Finding |
|---|---|---|---|
| `hygiene.part_number_matches_file` | `hygiene.part_number_property` | the property (configuration property of the active configuration first, then the custom property) compared, stripped and case-insensitive, with the file name's stem | demonstrated per document, both values; a document without the property is demonstrated `"has no <property>"` |
| `hygiene.duplicate_description` | `hygiene.description_property` | two or more **different** documents with the same non-empty value, compared stripped and case-insensitive | one demonstrated finding per value, naming every document |
| `hygiene.duplicate_part_number` | `hygiene.part_number_property` | as above for the part number | one per value |
| `hygiene.revision_present` | the existing `revision.property` | a part or assembly with the property absent or empty | demonstrated per document |
| `hygiene.component_not_resolved` | nothing | a component of the reviewed configuration whose `suppression` is `lightweight` or `suppressed` | one demonstrated finding per document, with the instance ids and the count; `unloaded` is left to the coverage item |

A check whose setting is absent (a version 1 profile) or empty, or run with no standards profile
attached, records no finding and one `skipped` item naming the setting:
`"hygiene.part_number_matches_file not evaluated: the standards profile names no part-number
property (hygiene.part_number_property)"`. Passes are not findings: a document that satisfies a
check is counted in one `checked` item per check, because these checks have no calculation to
keep.

## 3. The profile names

Read from the standards run attached to the context (`tools/standards_checks.standards_run`); the
hygiene tool never loads a profile itself. No property name appears in the source; the test
profiles carry fictional ones.

## 4. The data card's zero-match profile error (FR-020)

In `data_card_complete`, before the per-document skip: when `part_number.pattern` is non-empty
and matches **none** of the graded documents, each document's result is `unresolved` with the
reason `"the part-number pattern matched 0 of <n> graded documents, which is likely a profile
error; check part_number.pattern"` rather than the per-document "does not follow the convention"
skip. A pattern that matches at least one document keeps today's behaviour for the others.
Matching semantics (whole file name, extension included) do not change.

## 5. Acceptance on the big fixture

A document whose part-number property differs from its file stem is a finding; two documents
sharing a description are one finding naming both; a model missing its revision is a finding; the
lightweight component is a finding naming it; with a version 1 profile the two property checks are
skipped naming the setting and the component check still runs.
