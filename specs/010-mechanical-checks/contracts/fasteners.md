# Contract: Fasteners

Normative for FR-011 to FR-013, User Story 4 and SC-002, SC-004.

## 1. The name grammar (`checks/fastener_names.py`)

Parsed in order from the document's `file_name` (extension dropped), its `Description` custom
property, and the component's `referenced_configuration`; the first that yields a size wins, the
others cross-check. Matching is case-insensitive on text with `_` and runs of whitespace
normalized to one space and `×` to `x`.

| Form | Pattern (after normalization) | Example (fictional) |
|---|---|---|
| vendor file name | `^<head code> m<d>-<p>x<L>( .*)?$` | `SHC_M4-0.7X12_FICT-0001` |
| vendor description | `^<kind>, .*\bm<d>-<p> x <L> mm\b` | `SCREW, SOC M4-0.7 X 12 MM, FICTIONAL` |
| Toolbox size and pitch | `^m<d>( x <p>)?( x <L>)?( - .*)?$` (the C# parser's forms) | `M6x1.0 x 20 - 20N` |
| Toolbox size and length | `^m<d> x <L>$` with `L` an integer | `M10x35` |
| unified inch | `^(#<n>\|<a>/<b>\|<a.b>)-<tpi>( x <L>)?$` | `1/4-20 x 1-1/2` |

`<head code>` is looked up in `checks/fastener_names.yaml`
(`SHC: {kind: screw, head_type: socket head cap, drive: hex_socket}`, `FHT` flat head and `BHT`
button head, both `drive: torx` by the owner's answer of 2026-09-23). A head named in words
(`socket head cap screw`) names no drive; only a head code does. A pitch written with a hyphen (`M4-0.7`) is a pitch; a
bare integer after the size is a length; an unknown head code is `kind = null` and the size is
still read. Lengths are mm for metric and inches for unified unless the text carries a unit.

## 2. The shared vector table

`specs/010-mechanical-checks/contracts/fastener-name-vectors.json` (created by T039), fictional
strings only:

```json
[{"source": "file_name", "text": "SHC_M4-0.7X12_FICT-0001",
  "expected": {"kind": "screw", "head_type": "socket head cap", "thread": "M4X0.7",
               "length_mm": 12.0}},
 {"source": "configuration", "text": "garbage", "expected": null}]
```

`reviewer/tests/unit/test_fastener_names.py` and
`extractor/SwReview.Extractor.Tests/FastenerNameParserTests.cs` each read every row and assert
their parser's answer; a row either parser disagrees with fails that parser's suite. The C#
parser need not read `Description` forms it never receives, and such rows carry
`"csharp": false`.

## 3. Recognition (`checks/fastener_identity.py`)

`recognise_fasteners(package, joint_map=None) -> list[RecognisedFastener]`:

1. every `Fastener` row, `identity_source` as written; its name, if parseable, cross-checks;
2. every other resolved component whose document name parses to `kind` screw, bolt or pin, one
   `RecognisedFastener` per instance, `identity_source = "name_parse"`, with an in-memory
   `Fastener` (`data-model.md` section 2);
3. the shank: the component's free cylinder face of largest area (`face`), else none; the band
   `[d3 - 0.05, d + 0.05]` with `d3 = d - 1.226869 · P` decides `agreement`;
4. placement per `joint-map.md` section 5.

A disagreement is one `fastener.identity` finding, **suspected**, per document (all its instances
listed): `"<document> is named <designation> but its shank measures <x> mm, outside the <lo> to
<hi> mm band of that thread"`. SC-004: on the big fixture at least 90 percent of the named screws
are recognised (the fixture's 68 of 68 by file name).

## 4. The placed screw (`checks/fastener.py check_placed_screw`)

For each screw joint with a placed, recognised screw and a tapped instance:

| Quantity | Rule |
|---|---|
| reference axis | the tapped instance's axis; the thread entry is the end of the tapped face extent that lies inside the screw's extent |
| screw extent | the shank face's extent (`face`), else the screw mesh's vertices projected on the axis (`mesh`), else missing |
| protrusion | `entry - tip`, the tip being the screw extent's end beyond the entry |
| usable thread (blind) | `Hole.thread_depth`, measured inward from the entry; missing when null |
| usable thread (through) | the tapped face's axial extent, `derived: through-tapped length from the tapped face` |
| unknown end condition | usable thread missing |
| axis not aligned | protrusion missing (`"the axis is oblique; bounding-box extents are not used"`). A mesh extent of the screw is exact on any axis and is still computed, but the thread entry it is measured from is the tapped face's box, which overruns an oblique face by `r` times the sum of `|a_i| sqrt(1 - a_i^2)` (1.8 mm on a 4.2 mm bore at 30 degrees), so the protrusion stays missing with that reason (joint-map.md section 2: engagement requires an aligned axis; T044 as landed). A through-tapped usable length on an oblique axis is missing for the same reason |
| agreement `disagrees`, or two names that disagree on the size | protrusion missing (`"the parsed size disagrees with the measured shank"`, or the conflicting names) |
| screw extent does not cross exactly one end of the tapped face | wholly inside: missing (`"the screw lies wholly inside the tapped face"`); short of it: missing, with the gap (a placement by origin may be on the wrong hole); across both ends: the smaller of the two protrusions |
| mesh extent precision | a GLB stores single-precision vertices; a mesh extent is rounded to 0.001 mm |

The four results come from the same `_bottoming`, `_engagement`, `_thread_match` and
`_head_clearance` functions as `check_fastener_joint`, each calculation carrying the derivation
lines instead of `"protrusion = screw length - clamped stack - washers"`. `hole_depth` is never
read. `hole_material` is the tapped component's document material. A demonstrated engagement
shortfall in a through-tapped part thinner than the rule's length (`ratio x d`) is severity
`low`, with `sheet_thickness_mm` and `required_engagement_mm` in its result (owner answer
2026-09-23).

The placed-screw results fold by **screw document and tapped part** (`fastener_identity.
fastener_group`), not by pattern group: one screw part mis-threaded into one part at two
unrelated holes is one condition and one finding (SC-002). A screw placed in a joint with no
tapped instance is one skipped `fastener.engagement` coverage item for all such joints, and
with no tool envelope swept head clearance is one skipped `fastener.head_clearance` item.

## 5. The engagement rule

```yaml
  steel:
    min_engagement_ratio: 1.5
    source: "Owner decision 2026-09-23: at least 1.5 x d into steel and aluminium alike"
  aluminum:
    min_engagement_ratio: 1.5
    source: "Owner decision 2026-09-23: at least 1.5 x d into steel and aluminium alike"
```

Every other class unchanged. The file header records that the owner's answer was typed "1.td
into both" and read as 1.5d.

## 6. Acceptance on the big fixture

| Joint | Expected |
|---|---|
| two M4-0.7 screws in M5x0.8 tapped instances | one `fastener.thread_match` finding, demonstrated, 2 joints (SC-002) |
| M10x1.5 screw in a blind 12 mm thread, 10.225 mm engaged | `fastener.engagement` demonstrated, 10.225 against 15.0 |
| M2x0.4 screw in a blind 6 mm thread, 2.205 mm engaged | demonstrated, 2.205 against 3.0 |
| M3x0.5 screw in a 1.725 mm through-tapped hole, 1.394 mm engaged | demonstrated, 1.394 against 4.5, usable thread labelled derived; bottoming not applicable |
| M8x1.25 screw in a blind 16 mm thread, 14.375 mm engaged | checked within scope |
| the M4 in an oblique M5 | thread match demonstrated; engagement unresolved naming the oblique axis unless its mesh gives the extent |
| a screw named M5 whose shank measures 3.3 mm | `fastener.identity` suspected; its engagement unresolved |

## 7. The extractor (seat-validated)

`FastenerNameParser.Parse(configurationName, description, fileName)` accepts the vendor forms of
section 1 and reads the file name. `FastenerDumper` treats a component as a candidate when
`IsToolbox` **or** `FastenerNameParser.IsCandidate(fileName, description, configuration)` finds a
kind and a size; every candidate gets the shank face request it gets today. `IsCandidate` is a
pure static function tested with the vector table. Head diameter and height stay null (the head
table is the Python side's, `tool-access.md`).
