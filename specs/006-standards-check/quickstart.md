# Quickstart: Validating the Standards Check

**Feature**: `006-standards-check` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

Scenarios 1 to 6 run **offline**, on fixtures, with no SOLIDWORKS licence and with a
**fictional** profile. Scenarios 7 to 12 are marked **[W]** and run on the pilot workstation on
the test day; they are the only scenarios that touch a real document or the owner's real
profile.

## Prerequisites

Everything from features 001, 002 and 003, including feature 003's User Story 6 (the Model
check tab), whose `PaneActions`, `RunFolders`, `web/shared/dom.js` and run-folder skeleton this
feature reuses.

**Offline**: everything `reviewer/tests/support/standards.py` writes, named rather than
counted - **ten golden packages** graded by scenarios 1 to 4 and 4b
(`tests\golden\fixtures\standards-seeded`, `-compliant`, `-compliant-flat`, `-unknown`,
`-multiplicity`, and the **five** cases of the `standards-drawings` case *group*, which holds
one package per root drawing - `-seeded`, `-compliant`, `-ingested`, `-two-models`, `-no-views` -
because a run grades the drawing that was opened and no other), the **two matched-pair packages**
of SC-005
(`standards-profile-a`, `standards-profile-b`, graded in scenario 6), and the **second-subject
package** of SC-008 (`standards-seeded-second-subject`, copied and graded in scenario 5) - plus
the two fictional profiles `reviewer/tests/fixtures/standards/profile-a.yaml` and
`profile-b.yaml`.

**[W] Workstation**: SOLIDWORKS 2024 SP5; the owner's real profile written per "Setting up the
profile" below; and the documents named in scenario 12's sample - two assemblies, two parts and
one multi-sheet drawing - plus, for the probes, one weldment or sheet-metal part, one assembly
with a deliberately transparent component and a deliberately hidden one, and one six-sheet
drawing with a revision table on a sheet other than the first.

### Where the runs land

`swreview check standards` requires `--out <dir>`: `session.json`, `report.md` and `check.json`
go into that run folder, and **the package directory is only read**. The fixtures are therefore
graded where they are and nothing is copied for the scenarios below. The one command that
writes beside a package is `exceptions accept-standards`, which records an acceptance - that is
what it is for - and it is pointed at a **copy** in scenario 5 and never at a fixture.

```powershell
cd reviewer
$runs = "$env:TEMP\swreview-standards-quickstart"
Remove-Item -Recurse -Force $runs -ErrorAction Ignore
New-Item -ItemType Directory -Force $runs | Out-Null
$pa = "tests\fixtures\standards\profile-a.yaml"
$pb = "tests\fixtures\standards\profile-b.yaml"
```

---

## Scenario 0 (Foundational): The IR bump, and what must not move

```powershell
cd reviewer
uv run python -m swreview.ir.schema --write ..\specs\001-agentic-design-review\contracts\ir.schema.json
uv run pytest tests/golden tests/unit/test_schema_sync.py tests/unit/test_ir_*.py tests/unit/test_reuse_key.py
git -C .. status --porcelain reviewer/tests/golden
```

Expected: the schema command rewrites the contract, the tests pass, and the last command prints
**nothing but this feature's own new goldens as `??`, plus the two golden harness modules**
(`tests/golden/test_golden.py` and `tests/golden/test_standards_goldens.py`, which are code and
not artefacts) - no line naming a feature 001, 002 or 003 baseline, and no `standards-*` artefact
of this feature's own in any state but `??` except the ones
`REWRITTEN_BY_THE_DRAWING_CHECKS` names. That rule as an executable assertion is
`tests/unit/test_ir_golden_fixtures_load.py::test_the_golden_tree_holds_only_this_feature_s_new_goldens`,
which this scenario's pytest run executes; read the `git status` output against it rather than
against a bare "prints nothing". The `-C ..` matters: `git status` resolves a pathspec against the
current directory, so the same command run from `reviewer\` asks about `reviewer\reviewer\tests`,
prints a warning to standard error and **nothing** to standard output - which reads as the gate
passing when it measured nothing at all. The three regression gates this scenario measures are
gates 2, 3 and 5 below, and the artefact gate 2 is about is **`reviewer/tests/golden/test_golden/*.yml`**,
the pytest-regressions baselines, which are regenerated from callable output and would move if a
new IR field reached a summary or a coverage row. The input fixtures
(`reviewer/tests/golden/fixtures/*/package.json`) are static files nothing rewrites, so they are
byte-identical by construction; what proves they still **load** is a test that parses every one
of them under the 1.4.0 models unchanged, which is added here.

Also run, in this scenario, the C# half: the serializer test over a package carrying cut-list
items, a drawing record and every new field, and the test that a package carrying **none** of
this feature's evidence serializes to bytes identical to the pre-1.4.0 output - which is the
only thing that proves the per-property `JsonIgnoreCondition.WhenWritingNull` overrides and the
null-when-empty arrays actually work on the C# side (`contracts/ir-additions.md`, additivity
rule point 3).

---

## Scenario 1 (US1): The seeded fixture - one violation of each check

```powershell
uv run swreview check standards --package tests\golden\fixtures\standards-seeded --out $runs\seeded\run --profile $pa
```

The fixture seeds **one violation, in one document, of each** of the sixteen checks - that is
what makes the finding count below sharp, so a regression in any single check shows up as an
off-by-one in the total - and, because difference z is the one an implementation silently
regresses, **seeds two of them at depth**: an under-defined sketch inside a derived feature, and
a sub-feature carrying a non-zero error code.

**The package contains exactly one assembly document**: a single-level root assembly whose
children are parts, plus those parts and the drawing the drawing checks need. That is
deliberate. A second assembly would force difference h's rows - `mate_references` unresolved
once per sub-assembly, and the mate-count branch of `fully_mated` - which the count below
excludes; it is the same reason spec.md states that the US1 compliant package's root assembly
contains no sub-assembly. One single-level root assembly still seeds every assembly check:
`not_exploded`, `rebuild_errors`, `mate_references`, `one_fixed`, `fully_mated`,
`not_transparent` and `not_hidden` all evaluate on the root, and the drawing may reference that
same root assembly, since FR-003 grades a document once however it is reached.

**It also carries the multiplicity SC-006 measures**: the failing part is reached through
**twenty component instances**, and the seeded overridden-dimension violation is **six
dimensions on one drawing**. Neither changes the count below - one finding per failing check per
document is the whole point - and both make the counting rule a real test rather than an
assertion. (The shared-sub-assembly half of SC-006 cannot live here, because a sub-assembly is
exactly what this fixture must not have; `standards-multiplicity` carries it - scenario 4b.)

Expected: **fifteen findings**, one per check, each with the right check id, the right severity
and the right subject named, and `standards.assembly.not_transparent` as **one unresolved row**
naming the unsettled transparency polarity and PROBE-2. No sixteenth finding and no seventeenth
**check** result of any kind. (`standards.release`, the family's summary coverage item, is
always present and is not a check - `contracts/rules.md`.) Specifically:

- `standards.assembly.rebuild_errors` fails **once**, on the package's one assembly document,
  whose document-level count is non-zero, and the finding states that the count is as the
  document stood and that nothing was rebuilt.
- Each failing check yields **exactly one finding for its document, naming all twenty
  instances** where the document is the twenty-times-used part, and the error count equals the
  number of distinct failing **check-and-document pairs** - not the number of instances, not the
  number of subjects and not the number of blank fields (SC-006, difference a and difference n).
  The six overridden dimensions are six subjects inside **one** finding.
- `standards.part.rebuild_errors` names **both** the feature with the non-zero code at depth,
  with its chain of parent features, **and** the document-level count.
- `standards.part.sketches_fully_defined` names the under-defined sketch inside the derived
  feature, with its chain of parents, and the text-containing sketch appears in the check's
  skipped coverage with the sketch-text reason.
- `standards.document.data_card_complete` produces **one** finding for the document with one
  blank field and one absent field, naming which is which - not two findings and not two
  counts (difference m and difference n).
- `standards.drawing.revision_matches` and `standards.drawing.no_itar_statement` are the only
  two at **warning** severity, and neither offers an Accept.
- The verdict is `not_ready`, and the unresolved check id travels with it.

After SC-014 has settled the polarity and the fixture expectation is updated, all sixteen
produce exactly one finding each and the unresolved row is gone.

## Scenario 2 (US1): The compliant fixtures, and what "ready" costs

```powershell
uv run swreview check standards --package tests\golden\fixtures\standards-compliant --out $runs\compliant\run --profile $pa
uv run swreview check standards --package tests\golden\fixtures\standards-compliant-flat --out $runs\flat\run --profile $pa
```

The first fixture has parts, sub-assemblies and drawings; the second is a single-level root
assembly with no sub-assembly, its parts and one drawing.

Expected, first run: **zero findings**; every check is checked or skipped coverage with a
stated reason; and exactly the two known gaps appear as named unresolved rows -
`standards.assembly.mate_references` and the mate-count branch of
`standards.assembly.fully_mated`, each naming **each sub-assembly** and the missing
sub-assembly mate data (difference h), plus `standards.assembly.not_transparent` until SC-014.
The verdict is `ready_coverage_incomplete`, naming exactly those check ids.

Expected, second run, **after SC-014 has landed**: zero findings, **zero unresolved checks**,
and the verdict `ready`. This is the only scenario that produces `ready`, and it is
deliberately the narrowest fixture in the suite - a verdict of `ready` is expensive and the
suite should say so.

## Scenario 3 (US1): Unknown stays unknown

```powershell
uv run swreview check standards --package tests\golden\fixtures\standards-unknown --out $runs\unknown\run --profile $pa
```

The fixture is otherwise compliant - its error count is zero - and carries a lightweight
component, a suppressed component, a sub-assembly, a sketch with unreadable status, a drawing
note whose text could not be read, and a part whose mass-override flag could not be read.

Expected: every affected check is **unresolved** coverage naming the exact missing signal; no
affected check passes and none fails; the verdict is `ready_coverage_incomplete` with those
check ids named. Specifically, and this is the whole point of the fixture:

- The **suppressed** component is named in the *skipped* coverage of
  `standards.assembly.one_fixed`, `fully_mated`, `not_transparent` and `not_hidden` with
  "suppressed in `<configuration>`" as the reason, and in the *unresolved* coverage of every
  check whose evidence its referenced document would have supplied (FR-005). It is **never** a
  hidden finding (difference c) and never a pass.
- The **lightweight** component is the same, with its state as the reason; nothing resolves it.
- `standards.drawing.no_itar_statement` is **unresolved** naming the unread note - an unread
  note cannot be shown not to carry the statement.
- `standards.part.material_assigned` is **unresolved** naming the mass-override read, because
  pass and fail differ only by that flag.

## Scenario 4 (US2): Drawings, every sheet

```powershell
$group = "tests\golden\fixtures\standards-drawings"
uv run swreview check standards --package $group\standards-drawings-seeded      --out $runs\drawings\seeded      --profile $pa
uv run swreview check standards --package $group\standards-drawings-compliant   --out $runs\drawings\compliant   --profile $pa
uv run swreview check standards --package $group\standards-drawings-ingested    --out $runs\drawings\ingested    --profile $pa
uv run swreview check standards --package $group\standards-drawings-two-models  --out $runs\drawings\two-models  --profile $pa
uv run swreview check standards --package $group\standards-drawings-no-views    --out $runs\drawings\no-views    --profile $pa
```

Five packages and not one, because a standards run grades the drawing that was **opened** and
no other (`checks/standards/traversal.py`): the five relationships below are five root
drawings. `standards-drawings` is therefore a case *group* holding one case directory each,
the way `fixtures/remodel-plan/` holds feature 004's, and it carries no `package.json` of its
own - pointing `--package` at the group itself is refused, naming the missing file.

`-seeded` carries a hand-written three-sheet drawing record with one overridden dimension,
one dangling annotation, a revision table whose last data row disagrees with the drawing's
revision property, and the profile's export-control phrase in a note **on sheet 3**;
`-compliant` is a drawing whose file name conforms to the part-number pattern, whose revision
table's last data row agrees with its revision property, and whose referenced model is present
in the package with the same revision.

Expected: four findings on `-seeded`, with the right check ids, severities and
subjects; each drawing finding naming its **sheet, view and entity identity** (difference o,
difference q); the overridden dimension rendered **with the unit the package recorded it in**,
never a bare number (difference p); five checked-coverage rows on `-compliant`'s **drawing
document** - its scope's four plus `standards.document.data_card_complete`, out of the 14
checked rows the four-document package produces - and zero findings anywhere in that package;
and, on `-ingested`, whose only sheet evidence carries `source: "pdf_ingest"`,
all four drawing checks **unresolved** naming the evidence source. The report states that the
drawings were read as they stood and were not rebuilt.

The other two cases: `-two-models`, a drawing whose views reference **two** models (both
graded, both revisions compared, both disagreements named in the one revision warning, and a
document reached both from the root and from a drawing's reference graded **once**), and
`-no-views` (the drawing's own checks still run, the model comparison is unresolved naming the
missing referenced document, nothing crashes - difference f).

## Scenario 4b (US1 and US2): The counting rule, proved

```powershell
uv run swreview check standards --package tests\golden\fixtures\standards-multiplicity --out $runs\mult\run --profile $pa
```

The fixture is the one SC-006 names: **one sub-assembly appears under two parents**, and the
failing documents are reached through many instances. It exists separately from the seeded
fixture because that one must contain exactly one assembly document (scenario 1), and a shared
sub-assembly is exactly what it must not have.

Expected: each failing check produces **exactly one finding per document**, naming every
instance and every path through which the document is reached; the sub-assembly under two
parents gets **one** set of assembly rows naming both paths, not two; and the error count equals
the number of distinct failing **check-and-document pairs** - not instances, not parents, not
subjects (SC-006, difference a and difference n). This fixture carries **no drawing**, so its
four drawing rows are out-of-scope coverage in every run: the other two halves of SC-006 - the
part reached through twenty instances and the drawing carrying six overridden dimensions - live
in `standards-seeded` (scenario 1), and the drawing half of them is graded only once US2 has
landed the drawing checks.

## Scenario 5 (US4): Waivers, twice over

```powershell
$accept = "$runs\accept"
New-Item -ItemType Directory -Force $accept | Out-Null
Copy-Item -Recurse "tests\golden\fixtures\standards-seeded" "$accept\package"
uv run swreview check standards --package $accept\package --out $accept\run-1 --profile $pa

# Write the waiver file the next command reads. Set-Content -Encoding utf8 on Windows
# PowerShell 5.1 writes a BOM, which the reader rejects, so write the bytes directly.
# <failing-id> is standards.part.cut_list_excluded: the re-review step below needs the
# check the second-subject package seeds its extra subject of, and any other failing id
# leaves the exception matching and the finding quietly waived in run-3, which is the one
# outcome this scenario exists to rule out. <passing-id> is standards.assembly.not_transparent,
# the one error-severity check standards-seeded does not fail; the other two are fixed.
$waivers = @'
{
  "<failing-id>": "legacy part, deviation accepted at release review",
  "<passing-id>": "this one did not fail",
  "standards.drawing.revision_matches": "a warning check, so not waivable",
  "standards.not.a.check": "an id that does not exist"
}
'@
[System.IO.File]::WriteAllText("$accept\waivers.json", $waivers, (New-Object System.Text.UTF8Encoding $false))

uv run swreview exceptions accept-standards $accept\run-1 --package $accept\package --file $accept\waivers.json --by "quickstart"
uv run swreview check standards --package $accept\package --out $accept\run-2 --profile $pa
```

This is the one scenario that copies a fixture, because `accept-standards` writes
`exceptions.json` **beside the package** it accepts against.

With the four ids above, expected from the import: exit **1**, **nothing written**, and the four
reported as `would accept 1`, `unused`, `invalid (warning check)` and `invalid (unknown check)`.
The file must be UTF-8 **without** a byte-order mark - the waiver file is read as plain `utf-8`,
and Windows PowerShell 5.1's `Out-File -Encoding utf8` and `Set-Content -Encoding utf8` both
prepend a BOM the reader rejects, which is why the command above writes the bytes directly.

Also confirm the family guard: `accept-rms` pointed at this standards run folder is refused with
exit 1 naming both families, rather than grading it as an rms run (`contracts/cli.md`).

With only the first id, expected: `accepted 1`, `exceptions.json` written, exit 0. Then run-2
reports that check as **checked within scope carrying the exception id and the note**, and the
verdict's headline names the waived count - a `ready` verdict reached with waivers says so
(FR-032).

Then the re-review case, which is the one that matters:

```powershell
# The builder writes a package identical to standards-seeded except that the accepted
# check fails on a SECOND subject of the same document.
Copy-Item -Recurse "tests\golden\fixtures\standards-seeded-second-subject" "$accept\package-with-second-subject"
Copy-Item "$accept\package\exceptions.json" "$accept\package-with-second-subject\exceptions.json"
uv run swreview check standards --package $accept\package-with-second-subject --out $accept\run-3 --profile $pa
```

Expected: the fingerprint no longer matches, the finding **stands** and names the exception as
needing re-review, and it is never silently silenced.

And the drawing case: an acceptance recorded on one drawing does **not** silence the same check
on another, because the exception is bound to the drawing document it was accepted on.

## Scenario 6 (US1 to US4): No company value is compiled in

```powershell
uv run swreview check standards --package tests\golden\fixtures\standards-profile-a --out $runs\pair-a\run --profile $pa
uv run swreview check standards --package tests\golden\fixtures\standards-profile-b --out $runs\pair-b\run --profile $pb
```

Two matched fixture packages whose paths, file names and property names are written for two
**different** fictional profiles, which differ in every field.

Expected: the two runs produce **the same sixteen coverage rows and the same findings by check
id**. A value compiled into the source can pass a repository grep if it was spelled
differently; it cannot pass this (SC-005). The other two halves of SC-005 run in the same pass
and are described in `contracts/profile.md` under "How SC-005 measures this": a **field-by-field
comparison** of every configured profile in the repository - the two fixtures,
`config/standards.example.yaml` **and the example YAML block inside `contracts/profile.md`** -
against the R5 table parsed out of `research.md`, and a literal grep for R5's distinctive values
only. `research.md` R5 is the single documented exception and is excluded from the grep.

Also assert, in the same pass: no provider is constructed and no API key is read on the
command-line path, with the provider factories monkeypatched to raise; and every byte of both
package directories is unchanged after the runs.

---

## Setting up the profile (for the owner, on the workstation)

**Do this once, before scenario 7.** The file this creates is never committed and this
repository never sees it.

1. Copy the example: `config/standards.example.yaml` ->
   `%LOCALAPPDATA%\SwReview\standards.yaml`. Create the directory if it does not exist; it is
   where the add-in's other user settings already live.
2. Open it and **replace every value**. The example is fictional placeholder data, and none of
   it is a default - there is no fallback, so a value left as the example will simply grade
   documents against a standard nobody uses.
3. The starting point for each field - the values the macro carried - is the table in
   `research.md` section R5, which names the profile field each one feeds. Before copying them,
   read the handling note at the top of that section: this repository is public.
4. Set `vault_root` to the vault's root on this machine, and write the library prefixes
   **relative** to it, so the same file works on a second machine whose vault is mounted
   elsewhere.
5. `revision.cell` is a row selector counted from the end and a column index. Open the drawing
   template's revision table and count: `row_from_end: 0` is the last row.
6. In the pane, open **Settings** and confirm `StandardsProfilePath` points at the file. The
   Standards tab refuses with `NoProfile`, naming the path, if it does not.
7. Confirm the schema: `uv run swreview check standards --package <any standards package>
   --out <scratch> --profile %LOCALAPPDATA%\SwReview\standards.yaml`. A schema error is
   reported field by field, and nothing is graded until it is fixed.

Two things that are **not** in the profile and must not be added to it: the transparency
polarity (a fact about SOLIDWORKS, settled by PROBE-2 into a named constant) and any switch
that turns a check off (all sixteen run on every run).

---

## Scenario 7 [W] (US3): The tab, end to end

1. Open an assembly in SOLIDWORKS 2024 with the add-in attached.
2. Press **Standards**.

Expected: the host refuses **before creating anything** if no profile path is configured or the
file cannot be read, naming the path; otherwise it creates the run folder, dumps with the
`Standards` profile, registers the folder as the pane's latest run, and replies with the
document, the configuration and the counts it extracted. The page then calls
`POST /checks/standards` itself and renders: the verdict headline, the counts in **every**
bucket beside it, the unresolved check ids beside them **in every state**, the sixteen check
rows each showing every bucket it landed in with the documents and the per-document reason, and
the findings with their subjects.

Confirm, in this order:

- The headline reads "ready to release" **only** with zero errors **and** zero unresolved
  checks; with zero errors and one or more unresolved checks it says the verdict is incomplete
  and names every unresolved check id; with any error it never says "ready", however many
  checks passed.
- No letter grade and no single percentage is rendered as the result.
- "no drawing graded" appears on the headline, because the root is an assembly.
- The report states that nothing was rebuilt.
- Press **Show** on one finding's subject: the shared resolver selects the entity, or replies
  `ok: false` naming what it could not reach. Nothing reports success while selecting nothing.
- A subject with no selectable entity - a data-card property name, a note, a revision-table
  row, a cut-list item, a mate - renders **no Show control at all**.
- Press the report, folder and log controls; each opens from the host's own record.
- Switch the active document to a part and confirm the tab updates what it says it can grade.
- Confirm Review, Ask, Extract, Model check and Remodel are all still present, unchanged, in
  that order with Standards sixth; and that the Standards tab's banner and tooltip carry the
  same sentence, stating it needs no AI and no key.

3. Restart the pane and **open the Standards tab without pressing Standards** - the page sends
   `ready`, the host answers `init` carrying `latest_check` (found by the new
   `RunFolders.NewestCheckFolder(runRoot, "-standards")` scan), and the page calls
   `GET /checks/{check_id}` itself. Confirm the previous check comes back with the same verdict,
   the same sixteen coverage rows and the same findings, with **no dump and no SOLIDWORKS
   interaction**. Pressing Standards would run a **new** check, so it is not how a previous one
   is read back.
4. Confirm the pane's step strip names **standards-only evidence** and offers **Extract full
   evidence**, and that the standards run folder is not offered as the Extract tab's output.

## Scenario 8 [W] (US2): A drawing, end to end

1. Open the six-sheet drawing.
2. Press **Standards**.

Expected: the drawing is graded by the four drawing checks and the data-card check; every
document its views reference **that is already loaded** is graded by the part and assembly
checks exactly once, including everything reachable through a referenced assembly's component
tree; a referenced model that is **not** loaded is a named gap and its checks are unresolved
(nothing is opened); the drawing phase reads all six sheets in **under 10 s**; and no sheet is
activated - confirm from the gate log, which must show no sheet-activation member (SC-013,
SC-010).

Record the wall clock for the dump and for the render.

## Scenario 9 [W]: The ten probes

```powershell
swreview-extract probe standards --doc <document>
```

Run it on each of the documents the probes need (the assembly with the transparent and hidden
components, the weldment or sheet-metal part, the six-sheet drawing) and **paste the output
into the Answer column of `research.md` R4**. Read every line. Then:

- **PROBE-2** decides `TRANSPARENCY_POLARITY`. Flip the constant, update the fixture
  expectation for `standards.assembly.not_transparent`, and re-run scenarios 1, 2 and 3
  (SC-014). Until this is done the check is unresolved on the workstation as well as on
  fixtures, which is the correct behaviour and not a defect.
- **PROBE-4** decides whether a sheet can carry more than one revision table, and whether the
  `IView.GetTableAnnotations()` walk finds all of them where `ISheet.RevisionTable` (a
  single-valued property) finds at most one. A table the walk misses would be a silent miss in
  a coverage check.
- **PROBE-5** and **PROBE-7** decide whether the **type-1 sheet-format pseudo-view** is returned
  by `ISheet.GetViews()` at all. If it is not, confirm the phase falls back to
  `IDrawingDoc.GetFirstView()` / `IView.GetNextView()` - still activating nothing - and that a
  sheet recording no type-1 view leaves `standards.drawing.no_itar_statement` **unresolved**
  rather than checked.
- **PROBE-6** also compares `GetAnnotations()` against the macro's
  `GetFirstAnnotation3`/`GetNext3` walk per view. A smaller set from `GetAnnotations()` would be
  a silent under-report rather than an unresolved row, and SC-016's per-(check, document) parity
  depends on the answer.
- **PROBE-7** decides whether non-active sheets are read or recorded as gaps. If they come back
  empty, confirm the dump writes a gap **per non-active sheet** and the affected checks are
  unresolved for those sheets - and that no sheet was activated either way.
- **PROBE-8** and **PROBE-9** record the cut-list folder type names and the sketch text-segment
  behaviour; then dump and grade the weldment or sheet-metal part end to end and confirm **no
  value is silently absent** (SC-015).
- **PROBE-10** records which of the seven new entity kinds carry a persistent reference, which
  is what decides which subjects get a Show control.

Confirm the probe's own gate log at the end of its output shows **zero mutating interop
members and no sheet-activation member**.

## Scenario 10 [W] (US3): Performance

Measure and record:

- Pressing Standards on a **40-component assembly**: rendered verdict in **under 10 s** end to
  end (dump, evaluation, render).
- The standards additions against the **200-component pilot assembly**: dump it with and
  without the two new phases and confirm the additions add **under 10 s** (SC-012).
- The **six-sheet drawing**: the drawing phase in under 10 s (SC-013).

The CI-side number, evaluating all sixteen checks over a fixture package representing a
200-component assembly with three drawings in **under 2 s**, is the marked perf test (SC-011)
and is measured offline, not here.

## Scenario 11 [W]: Read-only, proved

From the gate log of a standards dump of an assembly and of a drawing, confirm **zero** mutating
interop members and **no** sheet-activation member passed the read-only gate (SC-010). Confirm
the source documents' size, last-write time and content hash are unchanged after every run in
scenarios 7 to 10.

## Scenario 12 [W]: Agreement with the macro

On a fixed sample of **at least five documents** - two assemblies, two parts and one multi-sheet
drawing, named here on the test day and kept fixed thereafter - run with the owner's real
profile:

| Document | Kind | Why it is in the sample |
|---|---|---|
| *(named on the test day)* | assembly | A release-representative top assembly |
| *(named on the test day)* | assembly | One with a sub-assembly, so difference h is exercised |
| *(named on the test day)* | part | A weldment or sheet-metal part, so the cut-list check is exercised |
| *(named on the test day)* | part | A library-prefixed part, so the skip lists are exercised |
| *(named on the test day)* | drawing | Multi-sheet, with a revision table on a sheet other than the first |

**Order matters**: run **this feature first**, on the unmodified documents, because the legacy
macro force-rebuilds every drawing it checks. Then run the macro on **copies**.

For **every (check, document) pair**, the macro's report and the tab's result must agree on
pass or fail. Counts are compared per the counting rule of difference n, not line for line; for
the checks whose macro output carries no subject identity (differences o and u) the tab's
subject set need only be a **superset** of the macro's; and rebuild-error counts are expected to
differ, per difference g.

**Every disagreement must map to a lettered row of the spec's "Differences from the Macro"
table.** Zero unattributed disagreements is the pass threshold. A disagreement that maps to no
row is a defect to fix before the feature is accepted - not a row to add.

---

## Regression gate

Every item below is a pass condition for this feature, checked before it is accepted.

| # | Gate |
|---|---|
| 1 | **Every `checks/rms` unit test and every `rms-*` golden passes with no edits** after the family machinery moves to `checks/rules/`. This is the proof that the move was a move (RK-7), and its task contains none of this feature's own code |
| 2 | **Scenario 0.** The pytest-regressions baselines `reviewer/tests/golden/test_golden/*.yml` are **byte-identical** after the IR bump - `git status --porcelain reviewer/tests/golden` prints nothing but this feature's own new goldens as `??` and the two golden harness modules, with no feature 001, 002 or 003 baseline named and no `standards-*` artefact in any state but `??` except those `REWRITTEN_BY_THE_DRAWING_CHECKS` names; `test_the_golden_tree_holds_only_this_feature_s_new_goldens` in `tests/unit/test_ir_golden_fixtures_load.py` is that rule as an assertion - every existing golden `package.json` still loads unchanged under the 1.4.0 models, and every new field and model is optional, defaulted, omitted when null (arrays when empty) and absent from the required set (SC-004). The input fixtures are static files nothing rewrites, so the baselines are the artefact at risk |
| 3 | **Scenario 0.** `test_schema_sync` passes against the regenerated 1.4.0 contract; the C# serializer test validates a package carrying cut-list items, a drawing record and every new field of `contracts/ir-additions.md` section 1; and a second C# test asserts a package carrying **none** of this feature's evidence serializes to bytes identical to the pre-1.4.0 output |
| 3b | **Scenario 0.** The 1.3.0 -> 1.4.0 bump edits **exactly** the version pins listed in `plan.md`'s Source Code block and nothing else, and `ReuseFixture.cs` plus both pinned cross-language canonical-form strings change in the same commit |
| 4 | A **`model_check`** dump of a part or assembly produces the same gap set **except for the drawing gap's new message** (which now names the profile that skipped the phase) - a `model_check` dump never runs the drawing phase, so it always carries that gap with the new wording; the comparison is over gap kinds, entity kinds, entity ids and count, with the one changed message asserted separately. A **`full`** dump of a part or assembly produces the same gap set except for the drawing gap's new message (which now names the profile that skipped the phase) and any gap the new `cutlist` phase records. A `full` dump of a **drawing root** omits the drawing gap entirely, which is its own assertion (SC-004, `contracts/ir-additions.md` section 5) |
| 5 | The tests that pin the **full phase list**, and `DumpPhase.name`'s field description with its C# XML-doc mirror, are updated in the task that adds the `cutlist` and `drawing` phases - named edits, not discovered ones |
| 6 | The **MCP function list**, the terminal profile's `enabled_tools` and the function list are unchanged, with the existing tests that pin them **passing unedited** (FR-035) |
| 7 | The `PaneActions` tests are **parameterized over three hosts**, not copied; `ReviewHostTests` and `ModelCheckHostTests` pass with no edits beyond that parameterization |
| 7b | The two C#-side extractions are proved the way the Python move is: **`ModelCheckHostTests` passes unedited** after `ModelCheckHost` is rebuilt on `Review/CheckPaneHost.cs`, and the **Model check page's contract and injection tests pass unedited** after the family-neutral half of `check.js` and `check.css` moves to `web/shared/check-page.js` and `check-page.css` |
| 8 | The guard tests show **every new denied member enumerated in research R8** refused - with the expected set derived from that table rather than a hand-typed count - and `ForceRebuild3` still refused everywhere except feature 003's suppress-test gate. Feature 004's `RemodelGuardTests.ExpectedDeniedMembers`, which asserts set equality on the whole denied surface, and `specs/004-resilient-remodeler/contracts/guard-allowlist.md` are updated in the same commit |
| 9 | A `check.json` written **without** a `family` field reads back as the feature 003 model check shape, and a standards record and a model check record under the same run root each return their own family's shape and never the other's (SC-009) |
| 10 | No company-specific value appears in any source file, test, fixture, golden, contract or example profile - `research.md` R5 is the single documented exception - by all three measurements of `contracts/profile.md`, "How SC-005 measures this": the **field-by-field comparison** against the R5 table of every configured profile **including the example block inside `contracts/profile.md`**, the literal grep for R5's distinctive values with `research.md` excluded, and the matched-pair run of scenario 6 (SC-005) |
| 11 | The provider factories raise and every standards path still completes: the check path, the tab path and the command-line path (SC-010) |
| 12 | The command-line run leaves **every byte** of the package directory unchanged (SC-010) |
| 13 | The injection tests assert that a component named `<img src=x onerror=alert(1)>`, a note containing `</script>` and a revision-table cell of markup all render as **text** and execute nothing, through the shared DOM helpers; the CSP meta tag is byte-identical to the pane host-messages contract's |
| 14 | All five existing tabs are present, unchanged and in order, with Standards sixth, and the Standards tab's content is created on **first activation** from a named placeholder note rather than at add-in load |
