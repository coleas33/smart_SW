# Contract: Standards Profile Version 4, the `part_roles` Section

Normative for FR-001 to FR-004. Amends feature 006's `contracts/profile.md` (the schema block, the
field rules, the validation's known versions, the prefix and pattern semantics) and feature 011's
`contracts/profile.md` section 1 (version 4 carries the drawing section unchanged). Research R2.1,
R2.2, R2.4, R3 C2, C3, C11.

*Amended 2026-09-26, before any code, from the owner's guidance of the same day ("the custom
properties should also hint at whether the part is custom or COTS; the purchased vs built switch
can be flipped by the user; also look for part numbers, vendors, etc.; custom parts usually have
little detail: the custom-prefix file name or the custom-prefix part number") and the local census
of that day (research R2.4, "Revised"): the section names every signal of `part-roles.md` section
2.1, each voting custom or bought with a strength, where it had named three bought rules. Every
company value lives in the owner's profile, never in code.*

## 1. The section

Version 4 is version 3 plus one required section. Every key is required; every list may be empty,
and an empty list or an empty property means that signal is not used.

```yaml
part_roles:
  # Tells custom parts (designed here) from bought ones (catalogue, vendor, library), so
  # modelling-practice and hygiene checks grade custom parts only (feature 013). Each entry
  # below is one signal that votes custom or bought with a strength; a part the votes do
  # not decide is asked about. An empty list or property means that signal is not used.
  #
  # STRONG, bought: a document under one of these prefixes (the library prefix rules:
  # relative entries resolve against vault_root, case-insensitive, at a folder boundary),
  # or inside a folder of one of these names anywhere in its path.
  bought_prefixes:
    - "_library/purchased/"
  bought_folder_names:
    - "FICT Purchased"
  # The make-or-buy switch the engineer sets: a custom property, read from the
  # configuration a component uses first, then from the document. A bought value is STRONG
  # (it is set on purpose); a custom value is WEAK (it is often the template's default).
  switch:
    property: "Make or Buy"
    bought_values:
      - "Buy"
    custom_values:
      - "Make"
  # STRONG, bought: any of these properties carrying a value.
  vendor_properties:
    - "FICT Vendor"
    - "FICT Vendor Number"
  # STRONG, bought: a distributor's download block - at least min_valued of these
  # properties carrying a value. An empty list with min_valued 0 means not used.
  distributor_block:
    properties:
      - "FICT Catalog Page"
      - "FICT Terms of Use"
      - "FICT Item Text"
    min_valued: 2
  # MEDIUM, bought: a catalogue number, in the name-pattern vocabulary ('#' a digit, '@' a
  # letter, '?' any one character, '*' any run), found as a whole token of the file name,
  # as a configuration name, or as the whole value of one of these properties.
  catalogue_numbers:
    shapes:
      - "FICT-####@##"
    properties:
      - "FICT Vendor Number"
  # MEDIUM, custom: the company's own part-number prefixes. The file name (when it follows
  # part_number.pattern) or the hygiene part-number property starts with one.
  custom_prefixes:
    - "EX-1"
    - "EX-2"
  # MEDIUM, bought: the part-number ranges the company gives bought parts, read the same way.
  bought_number_prefixes:
    - "EX-9"
  # WEAK, custom: properties only catalogue parts carry. A part whose properties were read
  # and carry none of these, none of vendor_properties and none of distributor_block's is
  # sparse, which is how custom parts usually look.
  detail_properties:
    - "FICT Thread Size"
    - "FICT Unit Cost"
```

This block is the `part_roles` section of `config/standards.example.yaml`. The owner's other
sections (`vault_root`, `library`, `part_number`, `hygiene`, and the rest) are exactly version 3's
and are not repeated here; feature 006's `contracts/profile.md` block, which is
`config/standards.example.yaml` byte for byte, gains this section when T014 lands, and feature 006's
research R5 gains one row per new field, each "not carried by the macro" (the three shipped
profiles keep differing pairwise in every value-bearing field, the new ones included). The example's
custom and bought prefixes follow the example's own part-number pattern (`EX-####-??.SLD???`), so the
example is coherent; every free-form name in it is marked `FICT`.

## 2. The name-pattern vocabulary, and how names and properties are compared

| Character | Matches |
|---|---|
| `#` | one digit |
| `?` | any one character |
| `@` | one letter |
| `*` | any run of characters, the empty run included |
| anything else | itself, ignoring case |

A pattern matches the **whole** string it is given. `part_number.pattern` keeps `#` and `?` only and
is matched against the whole file name, extension included: `name_matches(pattern, text, *,
wildcards=False)` is what the data card and the part-number convention call. `wildcards=True` is
what `catalogue_numbers.shapes` call, against one token, one configuration name or one property
value at a time (`part-roles.md` section 2.1). One matcher (`checks/standards/profile.py`,
re-exported by `traversal.py`); the owner writes no regular expression.

**Property names** are compared ignoring case **and every space**: real files spell one property
both with and without a space (a part-number property is written "Part Ref" on some documents and
"PartRef" on others, and both are the same property). `property_key(name)` is the one
normalisation, in `checks/standards/profile.py` (re-exported by `traversal.py`), and every reader of a named property in
`checks/part_roles.py` and `checks/hygiene.py` compares through it. **Property values** (the
switch's values, the prefixes, the shapes) are compared ignoring case and surrounding spaces.

**Folder names** (`bought_folder_names`) are compared with one whole folder segment of the path,
ignoring case; the file name itself is not a folder. **Prefixes** (`custom_prefixes`,
`bought_number_prefixes`) are compared with the start of a number, ignoring case.

## 3. Field rules

| Field | Type | Rules |
|---|---|---|
| `version` | int | `1`, `2`, `3` or `4`; an unknown version refuses naming the known ones |
| `part_roles` | mapping | version 4 only; a version 1 to 3 file carrying it is refused: "part_roles (a version 4 section)" |
| `part_roles.bought_prefixes` | list[str] | no blank entry (refused by position); the library prefix semantics |
| `part_roles.bought_folder_names` | list[str] | no blank entry; no entry holding `/` or `\` ("folder name {i} holds a path separator; name one folder"); no name twice ignoring case |
| `part_roles.switch.property` | str | may be empty; non-empty requires at least one bought or custom value |
| `part_roles.switch.bought_values`, `.custom_values` | list[str] | no blank entry; no value twice ignoring case, within or across the two lists; non-empty requires a property |
| `part_roles.vendor_properties` | list[str] | no blank entry; no name twice (ignoring case and spaces) |
| `part_roles.distributor_block.properties` | list[str] | no blank entry; no name twice (ignoring case and spaces) |
| `part_roles.distributor_block.min_valued` | int | `0` exactly when `properties` is empty; otherwise from `1` to the number of properties |
| `part_roles.catalogue_numbers.shapes` | list[str] | no blank entry; a shape made only of `*`, `?` and `@` is refused ("shape {i} would match every token") |
| `part_roles.catalogue_numbers.properties` | list[str] | no blank entry; no name twice; non-empty requires at least one shape |
| `part_roles.custom_prefixes`, `.bought_number_prefixes` | list[str] | no blank entry; no prefix twice; no entry of one list that starts with, or is the start of, an entry of the other, ignoring case ("custom prefix {i} overlaps bought prefix {j}"): a number could then vote both ways |
| `part_roles.detail_properties` | list[str] | no blank entry; no name twice (ignoring case and spaces) |
| unknown keys under `part_roles` or its three mappings | - | refused, naming them |

A refusal names the field and position, never the value (a failure message can reach a public log).

`_no_section_of_a_later_version` (`checks/standards/profile.py:317-321`), which lists the version 2
and 3 sections by name, derives its list from `SECTIONS_BY_VERSION`, so version 5 would need no third
edit there.

## 4. What leaves the reasoning side

Unchanged: `{path, sha256}` only. No `part_roles` value is written into a finding, a coverage
reason, the session, the report or a message to the page; the classifier's reasons name the signal
that voted ("a bought-parts folder", "a catalogue number", "marked bought by its make-or-buy
property"), never the folder, shape, property or value (`part-roles.md` section 3).

## 5. The upgrade helper

```
swreview profile upgrade <profile.yaml> --out <profile-v4.yaml>
```

- Reads a version 3 profile through the loader (a refused profile refuses the upgrade with the
  loader's reason).
- Writes `--out`, never its input (an existing `--out` is refused unless `--force`), as the input's
  text with `version: 4` and a `part_roles` section appended in which **every signal is unused**:
  empty lists, an empty switch property, `distributor_block` with no properties and `min_valued: 0`,
  `catalogue_numbers` with no shapes and no properties. When `library.skip_prefixes` or
  `library.sketch_exempt_prefixes` is non-empty, its entries are copied under `bought_prefixes` as
  **commented** lines, each list under its own comment: "Proposed from library.skip_prefixes, which
  means 'Standards skips this', not 'bought'. Uncomment what is bought." and "Proposed from
  library.sketch_exempt_prefixes, which means 'no sketch check here', not 'bought'. Uncomment what is
  bought." (the local census found the library root on the sketch-exempt list, with every skip entry
  under it).
- A version 1 or 2 input is refused naming the sections it lacks (the helper adds one section; it
  does not invent the drawing or general-tolerance values the owner has not written). The owner's
  seat profile and the shipped example are version 3 until T014.
- Validates the written file with the loader and prints the path and its sha256; no profile value is
  printed.
- A version 4 input is refused: "already version 4".

## 6. Tests

`test_standards_profile.py`: version 4 loads; version 1 to 3 still load; a version 3 file with
`part_roles` refused, named; version 4 without it refused; each blank entry refused by position; a
folder name with a separator refused; a wildcard-only shape refused; a switch property without
values, and values without a property, refused; a value in both switch lists refused; `min_valued`
out of range and non-zero with no properties refused; catalogue properties with no shape refused;
overlapping custom and bought prefixes refused; a repeated property name refused, also when it
differs only by case and spaces; an unknown key refused, at each level; version 5 refused naming 1 to
4; no refusal message carries a value. `test_standards_no_company_values.py`: the three shipped
profiles differ pairwise in every new field; the distinctive-value scan covers the bought prefixes,
the folder names and the shapes. `test_name_patterns.py`: `@` a letter not a digit; `*` an empty and
a long run; whole-string and case-insensitive; `@` and `*` literal with `wildcards=False`;
`property_key` folds case and removes every space. `test_cli_profile_upgrade.py`: the input untouched;
the commented proposals from both library lists; every signal unused; version 1, 2 and 4 inputs
refused; the output validates; nothing printed but the path and hash.
