# Contract: Profile Version 3 and Conformance

Normative for FR-022, FR-044 to FR-047 and User Story 7. The section and its loader land with User
Story 3, because the general tolerance's unit rule reads `drawing.dimension_unit`
(`drawing-source.md` section 4); the comparison lands with User Story 7.

## 1. Version 3

```yaml
version: 3
# ... every version 2 section, unchanged, general_tolerance included ...
drawing:
  sheet_formats: ["EXAMPLE-FORMAT-1", "EXAMPLE-FORMAT-2"]
  drafting_standard: "EXAMPLE-STANDARD"
  projection: "first_angle"        # first_angle | third_angle | ""
  dimension_unit: "in"             # mm | in | "" - the unit general_tolerance's decimal places are counted in
  drawing_template: "example-template.drwdot"
  bom_template: "example-bom.sldbomtbt"
```

Values are placeholders; the company's are the owner's to write (research R5, Q4). The three shipped
profiles differ pairwise in every value-bearing field (`test_standards_no_company_values.py`), so
each three-member setting takes a different member in each: the example as above, `profile-a`
`third_angle`, `mm`, `["FICTIONAL-FORMAT-A"]` and `FICTIONAL-STANDARD` (what the `plate-drawing`
fixture's drawing A carries), `profile-b` every drawing setting empty. The loader:

- `PROFILE_VERSION = 3`, `KNOWN_VERSIONS = (1, 2, 3)`; `drawing` required on version 3 and refused
  on 1 and 2 naming it; version 3 also requires every version 2 section;
- `DrawingSection` is strict and closed like every section: every key required, every string and
  list may be empty; `projection` outside the three values and `dimension_unit` outside the three are
  refused naming the key and the allowed values; a repeated `sheet_formats` entry is refused naming it;
- `general_tolerance` is **not** restated: a `drawing.general_tolerance` key is an unknown key and
  refused like any other.

The example profile, `reviewer/tests/fixtures/standards/profile-a.yaml` and `profile-b.yaml`, and
the block in `specs/006-standards-check/contracts/profile.md` move to version 3 together, with
fictional values that agree nowhere; `specs/006-standards-check/research.md` R5 gains one row per
new value-bearing field ("not carried by the macro"), as `test_standards_no_company_values.py`
requires; the standards goldens that record a fixture profile's `sha256` are regenerated and their
diffs are the `sha256` line only.

## 2. The comparison

`checks/drawing_context.compare_with_profile(package, profile) -> list[CheckResult]`, one per
attached or root drawing, each setting compared only when non-empty:

| Setting | The drawing's value | Differs when |
|---|---|---|
| `sheet_formats` | each sheet's `sheet_format_name` | any sheet's name is not in the list |
| `drafting_standard` | `drafting_standard_name` | not equal, ignoring case and surrounding spaces |
| `projection` | each sheet's `first_angle` | any sheet's projection is the other one |
| `dimension_unit` | `length_unit_raw`, named | not equal |

| Outcome | Result |
|---|---|
| one or more settings differ | `drawing_profile.conformance`, demonstrated, severity `medium`, one finding naming each differing setting and the drawing's own value (and which sheets), never the profile's value |
| every compared setting agrees | a `checked` coverage item for the drawing (a rule with no calculation counts passes in coverage, feature 010 R2.21) |
| a compared value was not read | `unresolved` coverage naming the setting and the gap |
| a setting is empty | `skipped` coverage naming the setting, never a pass |
| no version 3 profile | one `skipped` coverage item: "the standards profile is version {v} (or absent), which has no drawing section" |

`drawing_template` and `bom_template` are not compared: a finished drawing does not record the
template it was made from. They are read by feature 012.

## 3. The id, its class and the checklist

`drawing_profile.conformance` is classed `manufacturing` in `report/attention_policy_v1.yaml`
(a first opinion, research R5), added to `test_attention_catalogue.py` deliberately. Its prefix is
not `drawing.`, so it cannot close `drawing.manufacturing_inputs` (`agent/checklist_v1.yaml`); a test
asserts the checklist item stays open after it. It is not a standards check: the Standards tab's
sixteen checks and verdict are unchanged.

## 4. The tests

`test_standards_profile.py` extended (section 1, each refusal naming what it refuses; versions 1 and
2 still load; version 4 refused naming the known ones); `test_drawing_conformance.py` (section 2,
each row; one finding per drawing listing every difference; the finding's bytes free of every
fictional profile value); `test_attention_catalogue.py` and the checklist assertion (section 3).
