# Quickstart: Validating the Drawing Context

**Feature**: `011-drawing-context` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

Scenarios 0 to 10 run **offline**, with no SOLIDWORKS licence and no key. Scenarios 11 to 15 are
marked **[W]** and need the licensed seat of the next sitting; they are the workstation tasks T062 to
T068 and follow `contracts/probes.md`.

## Prerequisites

Features 001 to 010 on main. The committed fixtures `reviewer/tests/fixtures/drawings/plate-drawing/`,
`drawing-root/` and `assembly-drawings/`; the version 3 test profiles under
`reviewer/tests/fixtures/standards/`; the SOLIDWORKS 2024 SP5 interop assemblies at `$SwRedist` (the
build already needs them; SOLIDWORKS is never started).

```powershell
cd reviewer
$plate = "tests/fixtures/drawings/plate-drawing"
$root = "tests/fixtures/drawings/drawing-root"
$asm = "tests/fixtures/drawings/assembly-drawings"
```

## Scenario 0: what must not move

```powershell
uv run pytest tests/unit/test_tool_payload.py tests/unit/test_prerun_digest.py tests/golden -q
uv run pytest tests/unit/test_replay_findings.py tests/unit/test_replay_code_first_checks.py -q
```

Expected: every existing payload pin, digest and golden unchanged; the replay of every recorded
review loses no finding, leaves none unreplayable, and reclassifies 3, 2 and 0 contacts (SC-007);
the drawing family is offered on none of them.

## Scenario 1 (Foundational): the guard

```powershell
cd ..
dotnet build extractor/SwReview.sln -c Release --nologo -v q
dotnet test extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~DrawingFamily|FullyQualifiedName~RemodelGuard"
powershell -NoProfile -File extractor/tools/list-writer-members.ps1 | Out-File -Encoding utf8 $env:TEMP/feature-011-table.md
cd reviewer
```

Expected: zero warnings; every generated denial refused; the completeness test finds no writer of the
24 families outside the table and its exclusions; no gated read refused; the re-modeler's five
overriding keys unchanged. The regenerated table equals the "Feature 011" section of
`specs/004-resilient-remodeler/contracts/guard-allowlist.md` byte for byte.

## Scenario 2 (Foundational): the schema and the fixtures

```powershell
uv run pytest tests/unit/test_ir_drawing_context.py tests/unit/test_schema_sync.py tests/unit/test_support_drawings.py tests/unit/test_drawing_fixtures_are_fictional.py -q
```

Expected: every 1.5.0 package in the repository round-trips to its own bytes; the three fixtures
regenerate byte for byte; every path under `C:\Fictional\`; the denylist scan passes or is skipped
naming the missing file.

## Scenario 3 (US1): a drawing on its own

```powershell
dotnet test ../extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~SwSessionAttach|FullyQualifiedName~PackageWriter"
uv run swreview check standards --package $root --profile tests/fixtures/standards/profile-a.yaml --out $env:TEMP/feature-011-root
```

Expected: the refusal answers per purpose (a model purpose still refuses a drawing with today's
sentence; a dump purpose accepts it); a drawing-root extraction with a null configuration writes
`active_configuration: ""`; the four drawing checks grade the `drawing-root` fixture and every
referenced document once.

## Scenario 4 (US2): open drawings attached

```powershell
dotnet test ../extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~OpenDrawingDiscovery|FullyQualifiedName~PackageWriter"
uv run pytest tests/unit/test_drawing_evidence.py -q
```

Expected: of three open drawings the two showing the design are attached and the third is not; the
eleventh drawing is named in the limit gap; the block's same-name file is a candidate and nothing
opens it; drawing ids unique across two drawings; the reuse key differs with and without the drawing;
a `full` part dump with nothing attached carries the "No open drawing shows this design" sentence.

## Scenario 5 (US3): dimensions, precision and the resolver

```powershell
uv run pytest tests/unit/test_native_dimension.py tests/unit/test_drawing_binding.py tests/unit/test_tolerances.py tests/unit/test_drawing_source_acceptance.py -q
uv run python -c "from swreview.ir.loader import load_package; from swreview.drawings.evidence import DrawingIndex; i = DrawingIndex.for_package(load_package('$plate').package); print({d: [(v.view, v.usable) for v in vs] for d, vs in i.views_by_document.items()})"
```

Expected: with the binding switch set in the test, the plate's dowel hole size is bound from drawing
A's bilateral diameter, cited by drawing, sheet, view and `ddm:` id, with the model dimension in
`also_found` (SC-003); the pin hole's two-decimal untoleranced diameter binds the two-decimal general
band under the version 3 profile with `dimension_unit: mm` and nothing under an inch profile or a
version 2 profile (SC-004); drawing B's other-configuration and out-of-date views are listed unusable
with their reasons; with the switch as shipped (false) every answer names the seat validation.

## Scenario 6 (US3): the model's tools on native sheets

```powershell
uv run pytest tests/unit/test_tools_native_drawing.py -q
```

Expected: `find_dimensions` and `get_drawing_sheet` return native records; with the switch set in
the test `check_fit` resolves a native `SourceRef`, and with the switch as shipped it returns an
error naming the seat validation and records no finding (FR-024); a package with no native sheet
returns today's payloads byte for byte.

## Scenario 7 (US4): callouts, symbols, notes and tables

```powershell
dotnet test ../extractor/SwReview.sln -c Release --no-build --nologo --filter "FullyQualifiedName~DrawingDumper"
uv run pytest tests/unit/test_drawing_annotations.py -q
```

Expected: one record per callout kind, every unreadable value a named gap; revision tables exactly as
feature 006 records them; the position GTol on the dowel face binds the hole's position "read in the
drawing's unit, mm"; the bill of materials' rows resolve to three documents and keep one unresolved
path.

## Scenario 8 (US5): the drawing check and its questions

```powershell
uv run pytest tests/unit/test_drawing_context.py tests/unit/test_tools_check_drawings.py tests/unit/test_session_writer.py -q
```

Expected: on `plate-drawing`, one candidate question; on `assembly-drawings`, one governing question
with three drawings and "They all apply"; a repeat adds nothing; on a package with no drawing
evidence the plan, the digest and the offered tools are byte-identical to before (FR-037).

## Scenario 9 (US6): the brief

```powershell
uv run swreview drawing brief --package $plate --document <the plate's document id> --profile tests/fixtures/standards/profile-a.yaml
uv run pytest tests/unit/test_drawing_brief.py tests/unit/test_tools_get_drawing_brief.py tests/unit/test_tool_payload.py -q
```

Expected: the brief's sections in order, at most 6,000 bytes, no persistent reference and no profile
value; the pathological package's brief within the bound with `omitted` exact; the drawing arm of the
payload pins under 38,000 bytes in both encodings (the bridged slim arm pinned and not held to the
ceiling it already exceeds, research R2.20), each new tool within its budget.

## Scenario 10 (US7): conformance

```powershell
uv run pytest tests/unit/test_standards_profile.py tests/unit/test_standards_no_company_values.py tests/unit/test_drawing_conformance.py tests/unit/test_attention_catalogue.py -q
```

Expected: version 3 loads, versions 1 and 2 still load; drawing A conforms to `profile-a` (a
`checked` item); against a version 3 profile written in the test (first angle, another format) it is
one `drawing_profile.conformance` finding naming both settings with the drawing's values; against
`profile-b` every drawing setting is skipped; the checklist's `drawing.manufacturing_inputs` stays
open.

## The regression gate

```powershell
$env:SWREVIEW_REQUIRE_TOKENIZER = "1"; uv run pytest -q -p no:warnings -o addopts=""
uv run ruff check src tests
cd ..; dotnet build extractor/SwReview.sln -c Release --nologo -v q; dotnet test extractor/SwReview.sln -c Release --no-build --nologo
```

## Scenario 11 [W] (T062): a drawing on its own, live

Open a multi-sheet drawing; run `swreview-extract probe drawings --probe D1,D11`; press Standards.
Expected: the drawing and every model its views show are graded; the gate log holds no writer,
activation, open or close member (SC-001). Then run feature 006's T103, T105 and T107.

## Scenario 12 [W] (T063): attaching, live

Open an assembly and the drawings of two of its parts and of one unrelated part; run probes D2, D3,
D12, D13; start a review. Expected: the two drawings are read and the third is not; nothing is opened;
the candidate check on a vault path neither fetches nor stalls (SC-002).

## Scenario 13 [W] (T064, T065): the reads, live

Run D4 to D11 on drawings prepared as `contracts/probes.md` section 2 says; record every answer in
research R4.

## Scenario 14 [W] (T066): the binding validated

On a drawing whose callouts the engineer names beforehand, D6 and D8 tie every checked callout to the
right hole (SC-010); only then is `DRAWING_BINDING_VALIDATED` set, in its own commit.

## Scenario 15 [W] (T067, T068): the pane and the profile

A review with a candidate and a doubly-drawn part shows the two questions; answering them records the
answers, and the part's brief lists them; with the owner's version 3 profile a real drawing is
compared and the finding, if any, names only the drawing's values.
