# Contract: Standards Profile Version 4, the `part_roles` Section

Normative for FR-001 to FR-004. Amends feature 006's `contracts/profile.md` (the schema block, the
field rules, the validation's known versions, the prefix and pattern semantics) and feature 011's
`contracts/profile.md` section 1 (version 4 carries the drawing section unchanged). Research R2.1,
R2.2, R3 C2, C3, C11.

## 1. The section

Version 4 is version 3 plus one required section. Every key is required; every list may be empty;
an empty `purchased_property` with empty `purchased_values` means the signal is not used.

```yaml
# The part_roles section of a version 4 standards profile. FICTIONAL placeholder values.
part_roles:
  # Folder or file prefixes whose documents are bought parts. Relative entries resolve
  # against vault_root; the prefix rules of the library lists apply (case-insensitive,
  # normalized separators, a prefix whether or not it ends in a separator, the longest
  # match named).
  bought_prefixes:
    - "_fict-bought/"
    - "_fict-vendor-cad/"
  # A custom property whose value marks a part purchased, read from the document's
  # configuration-independent properties, compared ignoring case and surrounding spaces.
  purchased_property: "FICT Sourcing"
  purchased_values:
    - "FICT-Bought"
    - "FICT-Vendor"
  # Vendor catalogue names, in the name-pattern vocabulary of section 2, matched against
  # the whole file name with its extension.
  bought_name_patterns:
    - "FICT-@@###*.SLDPRT"
    - "*FICT###A###*.SLD???"
```

The owner's other sections (`vault_root`, `library`, `part_number`, and the rest) are exactly
version 3's and are not repeated here; feature 006's `contracts/profile.md` block, which is
`config/standards.example.yaml` byte for byte, gains this section when T014 lands (the three shipped
profiles keep differing pairwise in every value-bearing field, the new ones included).

## 2. The name-pattern vocabulary

| Character | Matches |
|---|---|
| `#` | one digit |
| `?` | any one character |
| `@` | one letter |
| `*` | any run of characters, the empty run included |
| anything else | itself, ignoring case |

Matched against the **whole** file name, extension included. `part_number.pattern` keeps `#` and `?`
only: `name_matches(pattern, file_name, *, wildcards=False)` is what the data card and the
part-number convention call, and `wildcards=True` is what `bought_name_patterns` call. One matcher
(`checks/standards/traversal.py`), no regular expressions.

## 3. Field rules

| Field | Type | Rules |
|---|---|---|
| `version` | int | `1`, `2`, `3` or `4`; an unknown version refuses naming the known ones |
| `part_roles` | mapping | version 4 only; a version 1 to 3 file carrying it is refused: "part_roles is a version 4 section" |
| `part_roles.bought_prefixes` | list[str] | no blank entry (refused by position); the library prefix semantics |
| `part_roles.purchased_property` | str | may be empty; non-empty requires at least one purchased value |
| `part_roles.purchased_values` | list[str] | no blank entry (by position), no value twice ignoring case; non-empty requires a property |
| `part_roles.bought_name_patterns` | list[str] | no blank entry (by position); a pattern made only of `*`, `?` and `@` is refused ("pattern {i} would mark every part bought") |
| unknown keys under `part_roles` | - | refused, naming them |

A refusal names the field and position, never the value (a failure message can reach a public log).

`_no_section_of_a_later_version` (`checks/standards/profile.py:317-321`), which lists the version 2
and 3 sections by name, derives its list from `SECTIONS_BY_VERSION`, so version 5 would need no third
edit there.

## 4. What leaves the reasoning side

Unchanged: `{path, sha256}` only. No `part_roles` value is written into a finding, a coverage
reason, the session, the report or a message to the page; the classifier's reasons name the rule that
matched ("a bought-parts folder", "a vendor name pattern", "the purchased property"), never the
folder, pattern or value (`part-roles.md` section 3).

## 5. The upgrade helper

```
swreview profile upgrade <profile.yaml> --out <profile-v4.yaml>
```

- Reads a version 3 profile through the loader (a refused profile refuses the upgrade with the
  loader's reason).
- Writes `--out`, never its input (an existing `--out` is refused unless `--force`), as the input's
  text with `version: 4` and a `part_roles` section appended: empty lists, an empty property, and,
  when `library.skip_prefixes` is non-empty, its entries copied under `bought_prefixes` as
  **commented** lines under the comment "Proposed from library.skip_prefixes, which means 'Standards
  skips this', not 'bought'. Uncomment what is bought."
- A version 1 or 2 input is refused naming the sections it lacks (the helper adds one section; it
  does not invent the drawing or general-tolerance values the owner has not written). The owner's
  seat profile and the shipped example are version 3.
- Validates the written file with the loader and prints the path and its sha256; no profile value is
  printed.
- A version 4 input is refused: "already version 4".

## 6. Tests

`test_standards_profile.py`: version 4 loads; version 1 to 3 still load; a version 3 file with
`part_roles` refused, named; version 4 without it refused; each blank entry refused by position; a
wildcard-only pattern refused; a property without values, and values without a property, refused; an
unknown key refused; version 5 refused naming 1 to 4. `test_standards_no_company_values.py`: the
three shipped profiles differ pairwise in the four new fields; the distinctive-value scan covers the
prefixes and patterns. `test_name_patterns.py`: `@` a letter not a digit; `*` an empty and a long
run; whole-name and case-insensitive; `@` and `*` literal with `wildcards=False`. `test_cli_profile_upgrade.py`:
the input untouched; the commented proposal; version 1, 2 and 4 inputs refused; the output
validates; nothing printed but the path and hash.
