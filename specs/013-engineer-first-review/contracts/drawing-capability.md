# Contract: The Drawing Capability and Drawing States

Normative for FR-033 to FR-040 and User Story 4. Research R2.24 to R2.28. Amends feature 011's
`contracts/questions.md` sections 3, 4, 5 and 6, `contracts/confirmed-open.md` sections 1, 2 and 4,
and `contracts/brief.md` section 2; feature 001's `contracts/agent-tools.md` (`check_drawings`,
`request_evidence`, `mark_coverage` rows) and `review-session.schema.json` (`drawing_read`); feature
008's `contracts/answer-batch.md` section 1 (the outcome lines) and `contracts/checks-first.md` (the
`check_drawings` digest line); the bridge `PROTOCOL.md` (a minor version, additive).

## 1. The host reports what it can do

```csharp
// extractor/SwReview.Extractor/Bridge/BridgeDispatcher.cs
public interface IConfirmedDrawingSource
{
    ConfirmedDrawingResult Read(string runId, string documentId);
    bool OpensClosedDrawings { get; }   // NEW: the seat switch of the scope that opens
}
```

`ConfirmedDrawingRead.OpensClosedDrawings` returns its `DrawingOpenScope`'s switch; the scope exposes
the value it was built with (`SeatValidated` as shipped, `Sw/DrawingOpenScope.cs:130`, or the probe's
override). `PingResult` (`BridgeDispatcher.cs:27-50`) gains:

```csharp
[JsonPropertyName("drawing_read")]
public string DrawingRead { get; set; }   // "none" | "open_only" | "opens_closed"
```

filled by `Ping()` (`:456-462`): `none` when `BridgeServices.ConfirmedDrawings` is null (the console
host; an add-in with no review lookup, `ToolServiceHost.cs:861-864`); `open_only` when the source's
`OpensClosedDrawings` is false; `opens_closed` when true. The protocol's minor version rises by one
(1.3 to 1.4 at the time of writing) in `SwBridgeDispatcher.ProtocolVersion`, both `PROTOCOL.md` files
and `bridge/client.PROTOCOL_VERSION` together (the three-way test enforces it).

## 2. The backend reads it once

```python
# reviewer/src/swreview/bridge/client.py
DrawingReadMode = Literal["none", "open_only", "opens_closed"]
def drawing_read_mode(self) -> DrawingReadMode: ...   # pings once and caches
```

An absent field, an older protocol, an unknown value or any `BridgeError` gives `none`; it never
raises. `ToolContext.drawing_read_mode()` is lazy and cached, `none` with no bridge, and is called only
when a custom (or unclear) document has a candidate, so packages without candidates (the replay
fixtures, the `--fail-bridge` quickstart) never ping. The value is recorded as the optional
`ReviewSession.drawing_read`, so a summary re-rendered later (`report/rerender.py`) says the same. A
failed ping counts once toward the client's circuit limit, like any failure.

## 3. Drawing states

```python
# reviewer/src/swreview/checks/drawing_context.py
DrawingState = Literal["attached", "candidate", "absent", "bought"]
def drawing_states(index: DrawingIndex, roles: PartRoles,
                   mode: DrawingReadMode) -> Mapping[str, DocumentDrawingState]: ...
def candidate_files(index: DrawingIndex, roles: PartRoles) -> tuple[CandidateFile, ...]: ...
```

For each reviewed part or assembly document (a drawing root's own document is not a subject, as
today):

| State | When | Coverage `drawing.context` | Reason |
|---|---|---|---|
| `attached` | a usable view of an attached or root drawing shows it | `checked` / `unresolved` as today | today's |
| `bought` | its role is bought (`part-roles.md`) | none (the bought-parts line names it once) | "a bought part: no drawing is expected, and none is asked for" |
| `candidate` | custom or unclear, not attached, a same-name drawing file beside it | `unresolved` | mode `opens_closed`: "a drawing with its name sits beside it (candidate)"; otherwise the instruction (section 4) |
| `absent` | custom or unclear, not attached, no same-name drawing | `unresolved` | "no drawing named {stem}.SLDDRW sits beside it" |

An unclear document's reason ends "(may be a bought part)". A missing drawing is never a finding.

`CandidateFile {key, file_name, document_ids}` groups candidate rows by `_file_key` (moved from
`report/summary.py:706-709` to `drawings/evidence.py`; its four callers - the drawing check, the
brief, the confirmed read and the summary - use it). Candidate rows of bought documents are ignored.

## 4. The offer follows the capability

| Mode | Candidate question | Candidate coverage and the drawings line |
|---|---|---|
| `opens_closed` | today's question, **once per file**: `what` names each file once; `entity_ids` every custom document of the listed files; "A drawing with the same name sits beside {n} reviewed file(s)…" counts files | today's |
| `open_only`, `none` | none | "Open {drawing} in SOLIDWORKS, then press Review again with {model} active" - one line per file, `{model}` the root document's file name |

Words: the words file's `drawings` gains `open_then_review_one` ("Open {drawing} in SOLIDWORKS, then
press Review again with {model} active") and `open_then_review_many` (the same for several files,
named as a sentence names them, past ten "and {n} more"). The summary's drawings line uses them by
`session.drawing_read`. The governing questions skip bought documents.

`read_confirmed_candidates` (`tools/drawings.py:240-296`) rebuilds the question with the same roles
and mode, acts only on an exact match (unchanged rule), and asks the bridge **once per file**, with
the file's first document id; each document of the file gets its `drawing.confirmed_open` item from
that one outcome. The host's `PackageAppender.MergeDrawing` removes every candidate row whose path
matches the merged drawing (`PackageAppender.cs:232-240`), so no second read is refused as "already a
document of the review" (`ConfirmedDrawingRead.cs:141-146`).

## 5. Code answers drawing requests

`request_evidence` with `blocks == "drawing.manufacturing_inputs"` (`re-ask-guard.md` section 3, row
6): each entity id is mapped to its document (a document is itself, a component its document, a hole
or fastener its component's document). When any mapped document has no attached drawing:

```json
{"status": "closed_by_code", "check": "drawing.manufacturing_inputs",
 "drawings": [{"document_id": "doc:0003", "state": "bought",
               "reason": "a bought part: no drawing is expected, and none is asked for"},
              {"document_id": "doc:0002", "state": "candidate",
               "reason": "Open FICT-0002.SLDDRW in SOLIDWORKS, then press Review again with FICT-0001.SLDASM active"}],
 "attached": ["doc:0001"]}
```

Nothing is recorded. `attached` names the documents that do have a drawing, which the model may still
ask about (the drawing's content).

When no attached drawing shows any custom (or unclear) document, `check_drawings` closes the item by
code: one `drawing.manufacturing_inputs` coverage row, `unresolved` when any custom document is
`candidate` or `absent` (a compact per-document reason), `skipped` when every subject is `bought`. In
that state `mark_coverage(check="drawing.manufacturing_inputs")` answers `closed_by_code` (the same
predicate function decides both). When a drawing is attached, the model owns the item as today.

The checklist's drawing item reads: "For each custom part or assembly: its drawing is the same-name
.SLDDRW in its folder; bought parts have none. check_drawings decides which drawings exist and tells
the engineer how to include one; never request a drawing or a drawing's version." System prompt step
6 gains the same last sentence.

## 6. Refusals reach the model

After a confirmed read, the resumed message gains one line per drawing file, before the answers'
text: "Drawing {file}: {outcome}" - the `drawing.confirmed_open` reason, refusals included (the host's
refusal, the bridge error, the ten-drawing bound, no connection). The drawing brief's drawing section
(`drawings/brief.py:335-354`) carries each document's state and, for a candidate, the confirmed-open
outcome when there is one, with candidates deduplicated. The resumed message for a batch with no
confirmed read is byte-identical to today's (replays rebuild it).

## 7. The payload and the digest

`check_drawings`' payload counts candidate **files** and adds the state counts:

```json
{"status": "recorded", "drawings": 0, "candidates": 1, "questions": 0, "findings": 0,
 "finding_ids": [], "states": {"attached": 0, "candidate": 2, "absent": 0, "bought": 1},
 "coverage": {"unresolved": 3}}
```

The digest line renders `PrerunCall.line()` unchanged.

## 8. Tests

C#: `BridgeDispatcherTests` (each of the three values); `BridgeProtocolTests` (the new minor version);
`ToolServiceWiringTests` (the add-in's source reports the shipped switch as `open_only`);
`ConfirmedDrawingReadTests` (the property mirrors the scope); `PackageAppenderTests` (the merge removes
every row of the path); `DrawingOpenTests.TheSeamShipsOffUntilTheSeatConfirmsIt` unchanged. Python:
`test_bridge_client.py` (the three-way version check; mode parsing: field absent, unknown value,
`BridgeError`, one ping cached); a package without candidates makes no ping; `test_drawing_context.py`
(the state matrix; a shared stem gives one file with two documents; a bought document's candidate
ignored; the question only with `opens_closed`; the instruction wording; the question within 140
characters with long names); `test_confirmed_drawing_read.py` (nothing unless `opens_closed`; one read
per file; per-document items; the outcome lines in the resumed message); `test_tools_session.py`
(drawing requests answered by code with states; an attached document recorded; hole and fastener ids
mapped; a mix names both groups); `test_tools_check_drawings.py` (the item closed by code when nothing
is attached; `mark_coverage` answered `closed_by_code` only then; payload counts);
`test_drawing_brief.py`, `test_tools_get_drawing_brief.py`, `test_review_summary.py`,
`test_pane_drawing_fixture.py` (the instruction line versus the question by `drawing_read`); a
fictional fixture shaped like the sitting (an assembly and a custom plate sharing a stem, a vendor pin,
two candidate rows for one file, the switch off), checked by `test_drawing_fixtures_are_fictional.py`:
no question, the instruction once, the pin bought. `test_workstation_test_plan.py`'s pinned strings
follow the test plan's steps 3.9, 4.6 and 4.7.
