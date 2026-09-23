# Contract: The Attach

Normative for FR-001 to FR-004, User Story 1 and SC-001.

## 1. Two entry points, one refusal rule

```csharp
// extractor/SwReview.Extractor/Sw/SwSession.cs
public enum AttachPurpose { Model, Dump }

public static SwSession Attach(ISldWorks swApp, string? documentPath, string? configurationName,
                               SwGate? gate = null);          // purpose Model, unchanged callers
public static ISwSession AttachForDump(ISldWorks swApp, string? documentPath,
                                       string? configurationName, SwGate? gate = null);
public static string? AttachRefusal(DocumentKind kind, string documentPath, AttachPurpose purpose);
```

| Purpose | Part | Assembly | Drawing |
|---|---|---|---|
| `Model` | attached | attached | refused: today's sentence, unchanged word for word ("'{path}' is a drawing, which has no configuration to bind a session to; open the part or assembly it documents.") |
| `Dump` | attached | attached | attached, with no configuration |

`AttachRefusal` stays pure and static; today's three `SwSessionAttachTests` pass `Model` and keep
their assertions. `Attach` is `AttachForDump`'s model-only form and keeps returning the concrete
`SwSession` with a non-null `Configuration`.

## 2. A drawing session

`ISwSession.Configuration` becomes `IConfiguration?`; `ISwSession.ConfigurationName` is the bound
configuration's name, or `null` for a drawing. A drawing session:

- is never handed to a caller of `Attach` - the tool service, the terminal, the review's reuse
  probe, interference, suppress test, remodel, the bridge - so none of them meets a null;
- is read by the extraction only: `ComponentTreeDumper.Traverse` reads the root kind **before** it
  reads a configuration, and for a drawing root sets `ComponentTreeResult.ActiveConfiguration` to the
  empty string and walks the forest exactly as feature 006 wrote it;
- writes `design.active_configuration: ""` and the drawing's manifest entry `configuration: ""`,
  which `ir/models.py`'s `Design.active_configuration` description states ("empty for a drawing
  root, which has none"); a referenced model's configuration is its own, as today;
- sets `DumpOptions.Configuration` to null (the document's active configuration, which a drawing
  does not have and no phase asks for).

A configuration name passed with a drawing is refused naming both: "'{path}' is a drawing and has no
configuration; '{name}' cannot be selected".

## 3. The paths that use each

| Caller | Entry | File |
|---|---|---|
| `SwDump.Run` (console `dump`) | `AttachForDump` | `Dump/SwDump.cs` |
| `SwReviewDump.Run` (Review, Model check and Standards tabs) | `AttachForDump` | `SwReview.AddIn/Review/SwReviewDump.cs` |
| `probe standards`, `probe drawings` | `AttachForDump` | `SwReview.Extractor.Console/Program.cs` |
| `SwReviewDump.Prepare`, the tool service, the terminal, `interference`, `capture`, `resolve`, `serve`, `suppress-test`, `probe rms`, `probe remodel` | `Attach` | unchanged |

The Review and Model check tabs keep refusing a drawing **before** they call the dump, through
`PageDocument.IsAttachable` and the Model check's part-only rule; only the Standards tab passes a
drawing to `SwReviewDump.Run`.

## 4. A drawing that is not open

`AttachForDump` with a `documentPath` ending `.slddrw` that `GetOpenDocumentByName` does not answer
refuses before `OpenReadOnly`: "'{path}' is a drawing that is not open in SOLIDWORKS. Open it
first: the extractor does not open drawings, because opening one loads every model its views
show." `OpenReadOnly` opens part and assembly files only. The one product path that opens a
drawing is not an attach: it is the read-only open of a candidate the engineer confirmed, through
its own guarded seam (`confirmed-open.md`, owner 2026-09-23).

## 5. The Review tab's refusal

`ReviewHost`'s sentence for a drawing gains one clause: "...; open the part or assembly it
documents - this drawing is read with it while it stays open." The sentence test is edited
deliberately in the same task (T015).

## 6. What SC-001 checks at the seat

Pressing Standards on a multi-sheet drawing grades it; the gate log of that extraction holds no
member of `contracts/guard.md`'s denials, no `ActivateSheet`, `ActivateView` or `ActivateDoc*`, and
no `OpenDoc*` member at all (the drawing was already open). Feature 006's T103, T105 and T107 run in
the same sitting (T062).
