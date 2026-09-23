# The Standards Profile

The company's configuration for the sixteen checks. **This file is not committed to this
repository** (FR-001). The repository ships `config/standards.example.yaml` with fictional
placeholder values; the tests use two fictional fixtures whose values differ in every field;
the owner writes the real file on the workstation.

**There are no built-in fallback values.** A missing, unreadable or schema-invalid profile
refuses the run. A default would grade a document against the wrong standard and report a
clean result, which is the worst failure a release gate has.

## Where it lives

| | |
|---|---|
| Setting | `StandardsProfilePath` in the add-in's user settings |
| Default | `%LOCALAPPDATA%\SwReview\standards.yaml` |
| Override | `swreview check standards --profile <yaml>`, which is what lets CI grade a fixture package against a fictional profile |
| Who validates it | **Exactly one place**: `checks/standards/profile.py` on the reasoning side. The host checks only that a path is configured and the file is readable, and refuses before it creates a run folder or dumps anything (FR-002) |
| What leaves the reasoning side | `{path, sha256}` only. **No profile value is written into the check record, the session, the report, a finding or any message to the page as a profile field** (FR-034); a coverage reason may quote the one value a check compared against where FR-016 requires both configurations to be named |

## Schema

```yaml
# standards.yaml - the company's release checklist configuration.
# Every value below is FICTIONAL placeholder data. Replace all of it.
# Version 2 adds general_tolerance and hygiene; version 3 adds drawing. A version 1 or 2
# file still loads without the sections it predates.
version: 3

# Absolute path to the vault or project root. Library prefixes below may be written
# relative to it; an absolute prefix is matched as written. A root that does not exist
# on this machine is accepted - a package can come from another machine, and the prefix
# match is textual.
vault_root: "D:/ExampleVault"

library:
  # Part documents under these prefixes get the four part checks and the data-card
  # check as SKIPPED coverage naming the matched prefix. Assembly documents under the
  # same prefixes are graded normally.
  skip_prefixes:
    - "_library/bonding/"
    - "_library/wiring/"
    - "_library/inserts/"

  # Part documents under these prefixes are exempt from the sketch check only.
  sketch_exempt_prefixes:
    - "_library/"

  # An under-constrained component under these prefixes needs at least ONE
  # unsuppressed mate.
  one_mate_prefixes:
    - "_library/fasteners/flathead/"

  # An under-constrained component under these prefixes needs at least TWO
  # unsuppressed mates. A prefix is a prefix whether or not it ends in a separator,
  # so an entry may name a single file.
  two_mate_prefixes:
    - "_library/fasteners/"
    - "_library/washers/"
    - "_library/nuts/"
    - "_library/seals/"
    - "projects/_shared/EX-00001.SLDPRT"

data_card:
  # Custom property names that must be present and non-blank on every document whose
  # file name matches part_number.pattern. Read from the configuration-independent
  # property set.
  properties:
    - "Item Code"
    - "Summary"
    - "Coating"
    - "Stock"

part_number:
  # '#' is one digit, '?' is one character, every other character is literal.
  # Matched case-insensitively, whole-string, against the FILE NAME INCLUDING ITS
  # EXTENSION.
  pattern: "EX-####-??.SLD???"

revision:
  # The custom property holding the revision, on the drawing and on its referenced
  # models. Written into the file by the vault; no vault API is used.
  property: "DocRev"
  # What a revision table holding only its header row means.
  initial: "NEW"
  # The text in the header row's identifying cell.
  header_text: "REVISION"
  # Which cell holds the current revision. row_from_end 0 is the LAST row, 1 the row
  # above it; column is a zero-based index. The values below are placeholders, not
  # defaults - most templates want row_from_end 0, and this example deliberately does
  # not use it so that no field of this example is a real-world value.
  cell:
    row_from_end: 1
    column: 2

material:
  # The configuration whose material standards.part.material_assigned compares.
  configuration: "AsBuilt"

export_control:
  # Presence of this phrase anywhere in a drawing's note text is the defect.
  # Matched case-insensitively as a substring.
  phrase: "EXAMPLE-RESTRICTED"

general_tolerance:
  # The title block's general tolerance, by decimal places: a dimension written to
  # decimal_places decimals (.XX is 2) and carrying no tolerance of its own takes
  # plus_minus_mm. Bands ascend by decimal places. An empty list and a null angular_deg
  # mean the company declares none; nothing defaults to a standard class.
  linear:
    - {decimal_places: 1, plus_minus_mm: 0.3}
    - {decimal_places: 2, plus_minus_mm: 0.13}
    - {decimal_places: 3, plus_minus_mm: 0.05}
  angular_deg: 0.75

hygiene:
  # The custom properties the hygiene checks read: the part number compared with the file
  # name, and the description two documents must not share. Empty skips those checks.
  part_number_property: "Fictional Number"
  description_property: "Fictional Summary"

drawing:
  # The company's drawing standard (profile version 3), compared with every drawing a
  # review reads; one review finding per drawing names each setting it differs in, never a
  # release-verdict failure. An empty value skips its comparison - it is never a pass.
  #
  # The sheet format names a drawing's sheets may use (ISheet.GetSheetFormatName).
  sheet_formats:
    - "EXAMPLE-FORMAT-1"
    - "EXAMPLE-FORMAT-2"
  # The drawing's dimensioning standard, compared ignoring case and surrounding spaces.
  drafting_standard: "EXAMPLE-STANDARD"
  # first_angle, third_angle, or empty.
  projection: "first_angle"
  # mm, in, or empty: the unit general_tolerance's decimal places are counted in. The
  # general tolerance binds a drawing dimension by its decimals only when the drawing
  # writes it in this unit; the general tolerance itself is not restated here.
  dimension_unit: "in"
  # Recorded for drawing creation (feature 012); a finished drawing does not record the
  # template it was made from, so neither is compared.
  drawing_template: "example-template.drwdot"
  bom_template: "example-bom.sldbomtbt"
```

**This block is itself an example profile, and SC-005 scans it.** The YAML above is what the
owner is told to copy (`quickstart.md`, "Setting up the profile") and is the model for
`config/standards.example.yaml`, so every value in it is fictional and **differs from the
corresponding value in `research.md` R5**, field by field - including `revision.cell`, which
is deliberately not the last row and not column 0 even though that is what most templates
want. The comment above it says what `row_from_end: 0` means so the semantics stay
documented without the example carrying the real cell. SC-005's scan is described under
"How SC-005 measures this" below and covers this block, `config/standards.example.yaml` and
both fixture profiles.

## Field rules

| Field | Type | Required | Rules |
|---|---|---|---|
| `version` | int | yes | `1`, `2` or `3`. A profile whose version this build does not know **refuses the run naming it and the known versions**, rather than ignoring the fields it does not recognize. Version 2 (feature 010 research R2.19) requires the two sections below and version 1 must carry neither, so the owner's version 1 file keeps loading until it is rewritten. Version 3 (feature 011, *amended 2026-09-23*) requires everything version 2 requires and the `drawing` section, which versions 1 and 2 must not carry |
| `drawing` | mapping | version 3 | Feature 011 `contracts/profile.md` section 1: `sheet_formats` (list of accepted sheet format names, no name twice), `drafting_standard` (str), `projection` (`first_angle`, `third_angle` or empty), `dimension_unit` (`mm`, `in` or empty - the unit `general_tolerance`'s decimal places are counted in), `drawing_template` and `bom_template` (str, recorded for feature 012 and not compared). Every key required, every value may be empty, which skips that comparison. `general_tolerance` is not restated here; a `drawing.general_tolerance` key is an unknown key |
| `general_tolerance` | mapping | version 2 | `linear`: a list of `{decimal_places, plus_minus_mm}` bands, ascending by decimal places (owner answer 2026-09-23: the general tolerance is by decimal places), `decimal_places` a whole number from 0, `plus_minus_mm` above 0; `angular_deg` above 0 or null. An empty list and a null angle mean the company declares none. Read by feature 010's tolerance resolver only for a dimension with no tolerance of its own |
| `hygiene` | mapping | version 2 | `part_number_property` and `description_property`, the property names feature 010's hygiene checks read; either may be empty, which skips the checks that need it |
| `vault_root` | str | yes | An absolute path. May name a directory that does not exist on this machine. Trailing separators are normalized away |
| `library.skip_prefixes` | list[str] | yes (may be empty) | See "Prefix semantics". Applies to **part documents only** |
| `library.sketch_exempt_prefixes` | list[str] | yes (may be empty) | Affects `standards.part.sketches_fully_defined` and no other check |
| `library.one_mate_prefixes` | list[str] | yes (may be empty) | Requirement: one unsuppressed mate |
| `library.two_mate_prefixes` | list[str] | yes (may be empty) | Requirement: two unsuppressed mates |
| `data_card.properties` | list[str] | yes (may be empty) | Property names, compared exactly as written against the names the package recorded |
| `part_number.pattern` | str | yes (may be empty) | `#` one digit, `?` one character, everything else literal. Whole-string, case-insensitive, against the file name **with** its extension |
| `revision.property` | str | yes (may be empty) | |
| `revision.initial` | str | yes (may be empty) | |
| `revision.header_text` | str | yes (may be empty) | |
| `revision.cell.row_from_end` | int >= 0 | yes | `0` is the last row of the table |
| `revision.cell.column` | int >= 0 | yes | |
| `material.configuration` | str | yes (may be empty) | |
| `export_control.phrase` | str | yes (may be empty) | |

**Every key is required; every value may be empty.** A required key with an empty value is a
deliberate statement ("we do not use this yet"); a **missing** key is an incomplete file, and
telling them apart is the difference between "this check is skipped" and "this profile was
half written". Unknown keys are **refused**, naming them, so a typo in `skip_prefixes` cannot
silently disable a skip list.

## Prefix semantics

1. **Case-insensitive, path-normalized, anchored at the start.** Separators are normalized
   (`\` and `/` are the same), `.` and `..` segments are resolved, and a trailing separator on
   the *path* being matched is ignored.
2. **Relative prefixes resolve against `vault_root`; absolute prefixes match as written.**
   One profile is therefore portable between machines whose vault is mounted differently,
   which is why `vault_root` exists at all.
3. **A prefix is a prefix whether or not it ends in a separator.** An entry naming a single
   file matches that file and any path that starts with it. This is deliberate and matches the
   macro's own behaviour, whose two-mate list mixed folder prefixes with one specific file.
4. **The four lists are matched independently.** A match in one never cancels a match in
   another: they answer four different questions about the same path.
5. **Within one list the longest matching prefix decides**, and **every** match in that list is
   named in the coverage reason. This replaces the macro's accident, where a catch-all
   fasteners folder in the two-mate list was overridden by its flat-head sub-folders in the
   one-mate list only because the one-mate list happened to be tested first.
6. **Across the two mate-count lists the longest matching prefix decides; on an exact tie the
   one-mate requirement wins.** One rule, not two: rule 5 already says the longest match wins
   within a list, and a mate-count requirement is the one question the two lists both answer,
   so the same rule settles it between them. The tie-break exists only for the case where a
   path matches a one-mate prefix and a two-mate prefix of **identical length**. This replaces
   the macro's accident, where a catch-all fasteners folder in the two-mate list was overridden
   by its flat-head sub-folders in the one-mate list only because the one-mate list happened to
   be tested first - under this rule the same answer falls out of the longer prefix. The two
   fixture profiles include a row where the **two-mate** prefix is the longer one, so the
   reversed case is exercised rather than assumed (FR-006).

## Validation rules

A profile is **valid** when it parses as YAML, is a mapping, carries every required key with
the right type, carries no unknown key, and has `version` 1, 2 or 3 with exactly that version's
sections. Anything else is a refusal
whose message names:

| Failure | `error_class` | Message names |
|---|---|---|
| No path configured, or the file does not exist | `ProfileUnreadable` | The path, and that the setting is `StandardsProfilePath` |
| The file exists and cannot be read | `ProfileUnreadable` | The path and the OS error |
| The file is not valid YAML, or is not a mapping | `ProfileInvalid` | The path and the parser's line and column |
| A required key is missing, a type is wrong, an unknown key is present, or `version` is unknown | `ProfileInvalid` | The path and the full validation error, field by field |

**A run folder created before a `ProfileInvalid` refusal is reported as an empty run, not as a
result** (FR-002): the host creates the folder and dumps before the backend has seen the
profile, so the page must say "this run produced nothing, and here is why" rather than
rendering a check list.

## What is deliberately *not* in the profile

| Not here | Where it lives | Why |
|---|---|---|
| The transparency polarity | A named module constant, `TRANSPARENCY_POLARITY`, settled by PROBE-2 | It is a fact about SOLIDWORKS, not about the company; putting it in the profile would ask the owner a question they cannot answer and let two machines disagree about physics |
| Cut-list item naming | Nowhere - identification is structural, from the package's cut-list records | A rename is not a waiver (difference bb) |
| Document-kind extensions | Nowhere - the kind comes from the package | Difference k |
| Mate type names, pattern feature type names, sketch feature type names, body-folder type names | Nowhere, or the extractor's raw reading | SOLIDWORKS vocabulary, not company policy |
| The unit an overridden dimension is rendered in | The package, per dimension | The macro assumed metres and lost its own formatting; recording the unit is difference p |
| The vault API, vault variables, a vault login | Nowhere. No vault API is used anywhere in this repository | The macro uses none either: every "vault revision" is an ordinary custom property the vault writes into the file |
| Which checks are enabled | Nowhere | All sixteen run on every run; a check that does not apply to a graded document is an out-of-scope row. A profile that could switch checks off would produce a verdict whose coverage depended on a control nobody recorded |

## Two fictional fixtures, and why there are two

`reviewer/tests/fixtures/standards/profile-a.yaml` and `profile-b.yaml` differ in **every**
field: different vault roots, different library folder names, different data-card property
names, a different part-number pattern, a different revision property, a different header
text, a different revision cell, a different material configuration and a different
export-control phrase. Two fixture **packages** are written to match them, one each.

They must also differ **from every value in `research.md` R5**, field by field, not only from
each other. Differing only from each other would let the macro's real value sit in one of them
and the leak reappear in a fixture, which is the same defect as an example profile carrying
it. One of the two also carries a `two_mate_prefixes` entry that is **longer** than the
`one_mate_prefixes` entry it overlaps, so prefix rule 6's reversed case is exercised.

SC-005 requires that the two packages produce **the same sixteen coverage rows and the same
findings by check id**. A value compiled into the source passes a repository grep if it was
spelled differently, but it cannot pass this: the only way both packages grade identically is
if every value came from the profile.

## How SC-005 measures this

Three assertions, not one grep, because several of R5's values are single characters, small
integers or ordinary English words that a repository-wide grep would match everywhere, and
because `research.md`, the one documented exception, is itself the source of the list a grep
would be built from:

1. **A structured, field-by-field comparison.** A test parses R5's table in `research.md`
   into a `{profile field -> macro value}` map, loads `config/standards.example.yaml`, both
   fixture profiles **and the YAML block extracted from this contract**, and asserts that for
   every field the configured value differs from the R5 value (for a list field: no element in
   common). The contract's own block is included because it is what a reviewer reads and copies;
   a test that read only the shipped `.yaml` would have missed the leak this rule exists to stop.
2. **A literal repository grep, for the distinctive values only** - the vault root, the library
   folder names, the part-number pattern string, the export-control phrase and the qualified
   data-card property name - over the whole tree with `specs/006-standards-check/research.md`
   excluded as the single documented exception.
3. **The matched-pair run** of `quickstart.md` scenario 6, which is what catches a value that
   was compiled in under a different spelling.
