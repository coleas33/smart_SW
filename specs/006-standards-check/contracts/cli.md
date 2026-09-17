# Command-Line Additions

## `swreview` (Python)

| Command | Arguments | Effect |
|---------|-----------|--------|
| `swreview check standards` | `--package <dir>`, `--out <dir>` (required), `--profile <yaml>` (optional), `--json` | Runs all sixteen checks without the agent and prints findings and coverage in the same human and JSON shapes the other `check` commands print, headed by the release verdict, its counts in every bucket and the unresolved check ids. Runs through `run_standards_check`, the single no-language-model evaluation entry point that `POST /checks/standards` also calls (FR-043). **`--out` is the run folder**: `session.json`, `report.md` and `check.json` go there, and the package directory is only read - grading a package must not edit it, which is the rule `check rms` and `check interference` already hold to (SC-010 asserts every byte of the package directory is unchanged). **`--profile`** overrides the configured path; with neither, the command refuses. Before the checks run it carries forward into the run folder the newest `exceptions.json` under the run root whose package carries the same `design_id` (the run root is `--out`'s own parent; a missing candidate is reported and is not an error, an unreadable candidate refuses the run). A candidate is a sibling folder that is **its own package**, so a run folder this command wrote - holding `session.json`, `report.md` and `check.json` and no `package.json` - is never one, and this command carries nothing forward from its own earlier runs; what makes a command-line acceptance survive is the other half of the rule, `swreview exceptions accept-standards` writing `exceptions.json` **beside the package**. **Exit 1 on every validation error or refusal** (below) and **0 otherwise**, with violations in the output rather than in the exit code. |
| `swreview exceptions accept-standards` | `<run_dir>`, `--package <dir>`, `--file <waivers.json>`, `--by <name>`, `--json` | Imports a flat waiver file `{ "<check_id>": "<reason>" }`: accepts every `demonstrated` finding of the run whose `check` is a listed **error**-severity standards check (one `ReviewException` each, `fingerprint_kind: "standards"`, `document_id` set, note = reason), writes `exceptions.json` beside the package, records `exception_id` on the findings, re-renders the report, and prints per check id: `accepted <n>`, `would accept <n>`, `unused`, `invalid (warning check)` or `invalid (unknown check)`. **Exit 1 when any id is invalid; nothing is written in that case.** The `--json` `status` field carries the same five values. This is the **existing `accept-rms` command generalized over the family**, not a second implementation (FR-042): **one command body, two names.** The family comes from the run's `check.json` `family` field, and the command **name** is a guard on it: `accept-standards` pointed at an `rms` run, or `accept-rms` at a `standards` one, is **refused with exit 1 naming both families** rather than quietly grading the other one - which is why a family-named alias is worth having when the family is auto-detected. The per-family status labels and the per-family waivability test are facts on the `CheckFamily` descriptor, not module constants: the rms labels stay **byte-identical** to today's (`invalid (unknown rule)`, `invalid (warn rule)`, `invalid (data-gap rule)`, `invalid (out-of-scope rule)`) so feature 003's tests pass unedited, and this family's are `invalid (unknown check)` and `invalid (warning check)` - the standards catalogue has no coverage-only rule, so it needs only those two. |

`swreview exceptions accept` and `exceptions list` work unchanged on standards findings.

### `swreview check standards` exit-1 conditions

Each names what was wrong and what to do, and **none of them is reported as a check result**:

| Condition | Message names |
|---|---|
| `--package` missing, unreadable, or not a package | The directory and the loader's error |
| The package does not record the phases the standards checks read | **The phase rows**, not the profile name: the `cutlist` row is `skipped`, or for a drawing package the `drawing` row is. The message names the profile that produced the package and the missing phases, and says to extract again with `--profile standards`. This is what stops sixteen unresolved checks reading as a broken model (FR-043). **Any** package that actually ran the phases is accepted, whatever profile produced it |
| No profile: `--profile` absent and no path configured | The setting name and the documented default path |
| The profile file is absent or unreadable | The path and the OS error |
| The profile parses but fails its schema | The path and the full validation error, field by field |
| `--out` is unwritable, or is inside the package directory | Both paths, and that grading a package must not edit it |
| The carry-forward candidate exists and cannot be parsed | The candidate path and the parse error - refused rather than read as an empty store, because an exception nobody can read is one an engineer accepted and would silently be raised again |

Violations - findings, at any severity - are **not** exit-1 conditions. A run that grades a
model with fourteen errors exits 0 and prints them, so a continuous-integration job decides for
itself what to do with the verdict.

## `swreview-extract` (C#)

| Command | Arguments | Effect |
|---------|-----------|--------|
| `dump` | `--profile full\|model-check\|standards` (default `full`) | **`standards`** runs the document, manifest, mate, feature, equation and **cutlist** phases, plus the **drawing** phase and the referenced-model phases when the root document is a drawing, and skips the hole, fastener, face and body phases. `full` now also runs `cutlist`, and `drawing` for a drawing root, so a full extract is never less complete than a standards one (FR-027). The profile that produced the package is recorded as `extractor.profile`, and **every** phase is recorded in `extractor.phases` whether it ran or not, so a consumer tells a partial extract from a complete one from the rows rather than from the name. A drawing root produces: the drawing's own document row and manifest entry, `design.drawing_document_ids`, one `DrawingRecord`, and the model phases over **every document its views reference that is already loaded** - opening, loading and resolving nothing (FR-025, FR-044). Read-only. |
| `probe standards` | `--doc <document>` | Prints all ten workstation probes in one read-only run under the read-only guard (`research.md` R4): the exploded read on the document, a second configuration and each sub-assembly; `HasMaterialPropertyValues` and all nine appearance slots for each component; `Visible` and `GetVisibility` for each component; per sheet, whether the revision table is reachable, whether the cast to the table interface succeeds, `CurrentRevision`, the row and column counts and every cell; per view, the view type, the referenced model name, whether the referenced document handle is non-null, every annotation's name, type and dangling flag, and every display dimension's override flag, override value, type and computed value; the same walk over **every** sheet while sheet 1 stays active, with per-sheet counts so a non-active sheet that came back empty is visible; every feature's type name and name at every depth with body-folder body counts and exclusion flags; `GetSketchTextSegments` for a plain sketch, a text sketch, an empty sketch and a hole-wizard sketch, printing null, empty and length distinctly; and `GetPersistReference3` byte lengths for one instance of each of the seven new entity kinds. **Activates no sheet, opens no document, changes no display state**, and its own gate log is printed at the end so the run proves it. |

## What a standards run writes, and where

```
<out or run_root>/<yyyyMMdd-HHmmss>-<doc>-standards/
├── package.json      the Standards-profile dump (the pane's run; the command line only reads one)
├── exceptions.json   carried forward before the checks run
├── session.json      the recorded tool steps
├── report.md         the check-by-check result
└── check.json        the record, carrying family: "standards"
```

The command line writes the last three (and `exceptions.json` when a carry-forward happened)
into `--out`; `package.json` is the one the command was pointed at and is never copied, moved
or edited.

## Two things this command line deliberately does not offer

| Not offered | Why |
|---|---|
| A `--check` or `--scope` filter | All sixteen checks run on every run; the document kinds decide which apply, and a check that applies to nothing is an out-of-scope row. A filter would produce a verdict whose coverage depended on a flag nobody recorded |
| A `--fix` or `--rebuild` flag | This feature reports and never repairs, and it rebuilds nothing. The rebuild-error counts are as the documents stood, and the report says so (difference g) |
