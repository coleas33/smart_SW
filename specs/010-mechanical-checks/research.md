# Research: Automatic Mechanical Checks

**Feature**: `010-mechanical-checks` | **Date**: 2026-09-23 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the analyst's check-by-check pass over the two recorded evening packages
(34 facts, 8 recommendations, 10 open questions, 2026-09-22); a second reading pass on
2026-09-23 over every module the plan names, at tip `5530e22`; and three read-only probes run
on 2026-09-23 over the recorded packages of the big assembly's recording and the small
assembly's (the one `small-assembly-a` was generated from), outside the repository. The probes print ids, sizes and
millimetres only; no name, path or property value of either package is written anywhere in this
package or in any file a task creates. Where this document says VERIFIED, the file was opened
on 2026-09-23 and, where the claim is behavioural or numeric, the code or the probe was run.
Line numbers are as of `5530e22` and will drift; every task re-verifies before editing.

---

## R1. What the sources are, and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | Eight user stories, FR-001 to FR-028, SC-001 to SC-008, and the owner's three decisions | Normative for what is built; amended in the places R4 names, each with its reason |
| The analyst's findings (2026-09-22) | Facts with path:line and computed numbers; recommendations 1 to 8 as the starting design | The design intent; superseded by R2 wherever this pass found the code or the data disagree (R6 lists every difference) |
| The 2026-09-23 probes | Per-instance hole geometry, screw placement, material classes, densities | Normative for the numbers the fixtures and the acceptance tests pin (R3) |
| `specs/008-checks-first-review/` (in progress) | The code-first pass every check here must join (010 FR-026) | The dependency; 010 designs its registration point so it lands before or after 008 (R2.20) |
| The constitution | Principles I to VI and the technical constraints | The gate every decision below is checked against in `plan.md` |

## R2. Decisions, alternatives and rationale

### R2.1 A `Hole` row is a feature; the joint map works on hole instances

**Decision**: the joint map explodes every `Hole` row into **instances**, one per group of its
cylinder faces that share an axis (coaxial within 0.001 mm and parallel within 0.01 degrees),
ordered by the smallest face id in the group and named `<hole id>#<n>` from 1. An instance
carries every diameter of its faces (a counterbore instance holds 9.0 and 14.0), its bore (the
smallest), and the axis of its first face. A row with no cylinder face yields no instance and a
`JointMapGap`.

**Why**: VERIFIED that `HoleDumper.AddAxisAndFaces` adds **every** cylinder face of the feature
to `face_ids` and takes the axis from the **first** one only
(`extractor/SwReview.Extractor/Dump/HoleDumper.cs:351-377`). On the big assembly the 27 hole rows are
132 instances (`hol:0014` 15, `hol:0016` 16, `hol:0019` 15, `hol:0023` 16, `hol:0008` 9,
`hol:0003` 8); `hol:0007` and `hol:0009` carry no cylinder face at all. The two existing
consumers compare first-instance axes only: `check_hole_alignment` calls
`axis_distance(a.axis, b.axis)` (`reviewer/src/swreview/checks/hole_alignment.py:62`) and
`prerun.coaxial_hole_pairs` does the same (`reviewer/src/swreview/prerun.py:203-216`). That is
why the recorded review found `hol:0004` and `hol:0010` "25.0 mm apart": per instance those two
features form **three coaxial joints at 0.000 mm**.

**Alternatives**: one axis per `Hole` row, as the analyst's recommendation 2 assumed (rejected:
it finds 3 of the 50 joints on the big assembly and pairs the wrong instances); an extractor change
emitting one `Hole` per instance (rejected for this feature: an IR change and a seat run to buy
what the faces already say exactly; recorded as a possible later clean-up).

### R2.2 Three geometric gates, one partner per component, clusters by union

**Decision**: two instances on **different components** form a joint pair when all three gates
pass - parallel within `parallel_deg` (1.0), the lateral offset between the axes below the sum
of the two bore radii (their projections overlap), and the axial gap between their face extents
along the first axis below `adjacency_gap_mm` (1.0). Each instance keeps **at most one partner
per other component**: the one with the smallest offset, ties broken by instance id; a pair that
passes the gates but lost that assignment is a candidate (`assigned_elsewhere`). Joints are the
connected clusters of kept pairs (union by instance), so a screw through two clamped plates into
a tapped hole is one joint of three instances. The thresholds live in
`checks/joint_rules.yaml`, each with a source line, and every joint and candidate records the
values it was judged on.

**Why**: the spec's assumption (1 degree, overlap, a gap under 1 mm) made precise. VERIFIED on
the big assembly: 48 instance pairs pass the three gates - 35 tapped under countersink, 10 tapped under
counterbore, 3 clearance over clearance - including `hol:0017`/`hol:0027` at 0.000 mm and two
`hol:0018`/`hol:0027` pairs at 0.750 mm. One `hol:0027` instance passes the gates with both a
`hol:0017` instance (0.000 mm) and a `hol:0018` instance (0.750 mm), both on `cmp:0004`; without
the one-partner rule that instance would sit in two joints and one misalignment would be reported
twice. With it: 47 kept pairs and one `assigned_elsewhere` candidate. With the cylinder members
of R2.3 the map holds **50 joints in 11 pattern groups**: 45 screw joints from hole pairs, 2 screw
joints formed by a screw face in a lone tapped instance (`hol:0013#1` with `cmp:0007`,
`hol:0021#1` with `cmp:0008`), 2 pin joints, and 1 unclassified (a 6.75 mm cylinder in an M8
counterbore instance, `hol:0025#2`, a screw once US4 recognises it). The only pair that fails a
gate by less than 1 mm is `hol:0018`/`hol:0024` (offset 7.006 mm against a radius sum of
6.05 mm), which becomes an `overlap_near` candidate. The analyst's two 1-5 mm first-axis pairs
(`hol:0014`/`hol:0023` at 1.576 mm, `hol:0015`/`hol:0019` at 3.950 mm) are **49.0 and 47.5 mm
apart along the axis**: they fail adjacency by a wide margin and are neither joints nor
candidates.

**Alternatives**: the analyst's `<= 1 mm` lateral band (rejected: a lateral band is not the
spec's overlap gate and admits the 49 mm-apart pairs); all-pairs clusters without assignment
(rejected: the double report above); a mate-based pairing (rejected: VERIFIED mate entity
persist refs match 0 of 110 extracted face refs, analyst fact 21).

### R2.3 Screws and pins enter a joint as cylinder members, placed by face or by origin

**Decision**: a **free** cylinder face (one in no `Hole.face_ids`) on another component is a
member of a hole instance when its component has no `Hole` row of its own, it is coaxial within
`member_coaxial_mm` (0.2) and parallel within `parallel_deg`, its axial extent overlaps the
instance's, and its diameter is no larger than the instance's bore plus 0.05 mm - for a tapped
instance, no larger than the thread's nominal major diameter plus 0.05 mm (it sits **in** the
bore) - or, for a counterbore instance, no larger than the counterbore diameter while overlapping
the counterbore's extent (a head **in** the counterbore, used by head fit). A recognised fastener with no extracted face is placed by its
**component origin**: the translation of `ComponentInstance.transform` (row-major, translation in
the last column, `reviewer/src/swreview/ir/models.py:140-141`, VERIFIED on a sample) within
`origin_on_axis_mm` (0.2) of an instance axis with one of the transform's basis vectors parallel
within `parallel_deg`. Every placement records how it was made (`face` or `origin`); a fastener
that neither rule places is `unplaced` and counted in coverage, never guessed.

**Why**: VERIFIED 27 free cylinder faces on 18 components in the big assembly. 13 of them are on parts
that have Hole rows of their own - among them a 4.5 mm plain bore of the clamped part over
`hol:0013` - and the package does not say whether a face is a bore or a boss, so a face on a part
with holes is a `JointMapGap`, never a member. A screw may be modelled anywhere between its minor
and major diameter (3.0 mm in `hol:0021`'s 2.5 mm tapped bore), hence the tapped limit. The
members include every case the spec names: `cmp:0018` (8.5 mm) in `hol:0006`, `cmp:0007` (3.3 mm) in `hol:0013`, `cmp:0008`
(3.0 mm) in `hol:0021`, and an M8 head (13.0 mm) inside the 14.0 mm counterbore of `hol:0024`. In
the small assembly the pin `cmp:0003` (3.0 mm) sits in `hol:0004` (3.0 mm) at 0.000 mm with 8.475 mm of
overlap. Of the 68 screws named in the vendor pattern, 11 have an extracted face; placement by
origin places **57 of 68** on a hole-instance axis, **48** of them on a tapped instance.

**Alternatives**: face-only placement (rejected: 11 of 68); placement by bounding-box centre
(rejected: a bounding box is documented as approximate, `HoleDumper.cs:29-30`); by concentric
mates (rejected, R2.2).

### R2.4 Joint kinds from the members, not from a model

**Decision**: a joint is classified by its members, in this order: a tapped instance with any
clearance, counterbore or countersink instance, or with a screw member, is a **screw** joint; two
or more clearance instances and no tapped one are a **pin** joint when the Hole Wizard `size`
is a plain diameter (`parse_thread` does not recognise it and it reads as a number, such as the
`Ø3.0` of the dowel holes) and a **through-bolt** joint when it is a thread designation (`M8`);
a single instance with a non-screw cylinder member is a **pin** joint; anything else is
**unclassified**, listed, and still checked for alignment when a fastener size is known.

**Why**: FR-004's four kinds, decided from data the package carries. VERIFIED the Hole Wizard
`size` field holds `Ø3.0` for the four dowel holes and a thread size for every clearance,
counterbore and countersink hole in both packages (probe of `holes[].size`).

**Alternatives**: classifying by hole type pairs only (rejected: misses the small assembly's pin, which
has no partner hole); treating a size disagreement (an M4 counterbore over an M5 tapped hole) as
"not a joint" (rejected: the joint is geometric; the disagreement is the defect, and R2.7 reports
it as a negative clearance).

### R2.5 Sizes: native first, face-derived second, labelled; the fastener size by convention

**Decision**: the hole size `H` of an instance is the Hole Wizard diameter when the package has
one (`Hole.diameter`, or the US8 `wizard` sizes), otherwise the instance's bore from its faces,
labelled `derived from the cylinder face`. The fastener size `F` is, in order: the nominal major
diameter of the recognised screw's thread (the floating- and fixed-fastener convention takes the
fastener at its maximum material size, which is its nominal); the measured diameter of a pin
member; the tapped instance's thread nominal for a screw joint with no recognised screw; the
clearance hole's Hole Wizard `size` read as the fastener it was made for (`Ø3.0` gives 3.0,
`M8` gives 8.0), labelled `the fastener size the Hole Wizard hole was made for`. With none of
these `F` is unknown and every check that needs it is unresolved.

**Why**: VERIFIED `Hole.diameter` is null on 27 of 27 and 4 of 4 holes because only
`IWizardHoleFeatureData2.Diameter` is read (`HoleDumper.cs:181`), while face radii exist for 25 of
27 and 4 of 4 (analyst fact 14; the probe confirms 132 instances with a bore). FR-005.

### R2.6 Allowed offset and position budget, fixed and floating

**Decision**: at nominal sizes a joint's allowed axis offset is the sum over its **clearance**
instances (clearance, counterbore bore, countersink bore) of `(H - F) / 2`; a tapped instance
contributes 0 (the screw is centred on its thread) and so does a line-to-line instance
(`H == F`). A negative term means the fastener cannot pass that hole and is demonstrated with
both numbers. The **position budget** is twice the allowed offset, reported as a recommended
callout: for a fixed-fastener joint (screw into a tapped hole) the total position tolerance
`H - F` to be shared between the clearance hole and the tapped hole; for a floating joint (pin or
bolt through clearance holes) `H_i - F` for each hole.

**Why**: FR-007 and FR-008. The two formulas are the fixed- and floating-fastener relations of
ASME Y14.5 at nominal sizes; stating both removes the analyst's single `(H - F)/2`, which is right
only for a screw into a tapped hole. On the dowel pair the 3.1 mm hole allows 0.05 mm and the
3.0 mm hole 0 mm, so the 0.750 mm offset is demonstrated against 0.050 mm allowed. On the small assembly
the 3.0 mm pin in the 3.0 mm hole at 0.000 mm passes with a budget of zero and a coverage limit
saying the fit is line to line.

### R2.7 The worst-case stack-up declares its model, and has three outcomes

**Decision**: the stack-up of a joint is computed over the richest calculation model whose
contributors all have a tolerance from some source (R2.18): **size and position** when every
hole size, the fastener or pin size and every hole's position tolerance resolve; **size only**
when the sizes resolve and a position does not, in which case position is listed in
`excluded_effects` with the sources searched; **unresolved** when any size contributor has no
source, naming it and the sources searched. With the worst-case clearance
`c_min = Σ (H_i,min - F_max)/2`, the best case `c_max = Σ (H_i,max - F_min)/2`, the modelled
offset `e`, and the sum of position half-zones `z` (0 in the size-only model): the offset is
**demonstrated** too large when even `max(0, e - z) > c_max`; **checked within scope** when even
`e + z <= c_min`; otherwise **suspected** (it fails at some sizes inside the tolerances). When
the package holds no tolerance source of any kind, one `skipped` coverage item says so for every
joint rather than one unresolved finding per joint.

**Why**: FR-010 and Principle I. The size-only model is the precedent the constitution itself
names ("size-only fit; position, form, coating not included") and `checks/fit.py` already
implements as `fit.size_only`; a stack that silently dropped position would be the unearned pass
the constitution forbids, and a stack that required position would be unresolved on every joint
until feature 011, because no model-side source binds a position today (R2.18). The three-way
verdict is the worst-case logic stated once: a demonstrated finding must fail at every
permitted size.

**Alternatives**: requiring positions (rejected: always unresolved before 011 and MBD, and says
nothing the size tolerances already establish); a statistical (RSS) stack (rejected: the spec
says worst case; recorded as a possible later model).

### R2.8 A position or coaxiality zone permits half its value, always

**Decision**: one helper in `checks/result.py`, `permitted_radial_offset_mm(zone_value_mm)`,
returns `zone / 2`, and both `hole.coaxiality` and the joint stack use it. The existing check
records `zone_mm` (the value it compared with before) and `permitted_offset_mm`, and compares
the offset with the latter.

**Why**: FR-009. VERIFIED the check compares the offset with the tolerance nominal directly
(`hole_alignment.py:118-124`, `:155-156` states the reading). A cylindrical zone of diameter `t`
and a band of width `t` both let the axis move `t/2` from true position, so the halving does not
depend on recognising a diameter symbol. VERIFIED the two existing assertions survive: an offset
of 0.1 mm against a 0.2 mm zone is still within (0.1 <= 0.1,
`reviewer/tests/unit/test_checks_hole_alignment.py:67-80`) and 0.5 mm is still demonstrated
(`:82-92`); a new boundary row (0.15 mm against 0.2 mm, within before and demonstrated after)
pins the change.

### R2.9 Contacts are a first-class list on the session, not findings and not coverage

**Decision**: an interference group whose computed members all have a volume at or below
`CONTACT_VOLUME_MM3` (1e-6 mm3), or no volume with `is_possible` true, is a **contact**: one
`Contact` record on the new optional `ReviewSession.contacts` list, naming both parts, the
configuration, the kind (`zero_volume`, `possible_only`, and from US4 `thread_model`), the volume
as reported, the joint when the joint map has one for those components, and the step that judged
it. A group with any positive-volume member stays a finding exactly as today, the zero-volume
members listed in its inputs. The decision order is unchanged ahead of the new rule: an
uncomputed member makes the group unresolved; an active exception clears it; a needs-review
exception makes it suspected; then contact; then finding. The report renders `## Contacts` after
the findings only when the list is non-empty; the ranking never reads it.

**Why**: FR-001 to FR-003 and SC-001. VERIFIED `_reported` treats any non-null volume as
demonstrated (`reviewer/src/swreview/checks/interference.py:363-377`), which is how 5 of the 8
interference findings across the two evenings (the small assembly's F-001, F-002; the big
assembly's F-092, F-095, F-096, all 0.0 mm3) took four of the ten Start-here slots (analyst fact 7). A list the ranking
never reads cannot occupy a slot, by construction. The owner decided "a separate contact list,
not findings" (2026-09-23). The epsilon is named because a float `0.0` from the host may arrive as
a denormal; 1e-6 mm3 is a thousandth of a cubic micrometre, below any material meaning.

**Alternatives**: low-severity findings (rejected: the owner's decision; they would still sort
above hygiene in the ranking); `checked` coverage items with a marker check id (rejected: a list
hidden inside a bucket, found by string convention, is the clever option the owner's preferences
rule out, and feature 009 would have to filter coverage to render it); hiding them (rejected:
Principle VI, and a line-to-line press fit must stay visible).

### R2.10 Thread-model contacts are bounded by the annulus the model can explain

**Decision**: a positive-volume group whose two components are the screw and the tapped part of
one screw joint is a `thread_model` contact linked to that joint when its largest member volume
is at most `π/4 · (d² - D²) · L`, with `d` the screw's nominal major diameter, `D` the tapped
instance's measured bore and `L` their axial overlap; anything larger stays a finding. It lands
with US4 because it needs the recognised screw and the placed overlap.

**Why**: the spec's edge case, bounded so it cannot hide a real overlap (Principle VI forbids
blanket exclusions). A screw modelled at its major diameter in a tap-drill bore overlaps exactly
that annulus; one modelled at its minor diameter (`cmp:0018` at 8.5 mm in an 8.5 mm bore,
VERIFIED) overlaps nothing and never reaches this rule.

### R2.11 Fastener recognition: one Python parser, one shared vector table, the C# parser widened

**Decision**: `checks/fastener_names.py` parses a fastener's kind, head, size, pitch and length
from, in order, the document's file name, its `Description` property and the component's
referenced configuration name, for the vendor forms `<HEAD>_M<d>-<p>X<L>_...` and
`<KIND>, <head> M<d>-<p> X <L> MM, ...`, the Toolbox forms `FastenerNameParser` already reads, and
the common inch forms `parse_thread` knows. Head codes (`SHC`, `BHT`, `FHT`, ...) map to a kind,
a head type and a drive in a data file, `checks/fastener_names.yaml`; a drive the table leaves
null stays unknown. A Toolbox `Fastener` row, when present, wins; the name then only
cross-checks it. The same cases, fictional strings only, are one JSON vector table read by
`reviewer/tests/unit/test_fastener_names.py` and by `FastenerNameParserTests.cs`, so the two
parsers cannot drift.

**Why**: FR-011 and SC-004. VERIFIED 68 of 89 instances in the big assembly are screws by the file-name
pattern (`SHC` 32, `FHT` 35, `BHT` 1, over 9 documents and 9 size/length combinations); 48 of
those 68 also parse from the Description; every screw document carries a material; 36 of the
68 reference a configuration that is not `Default`. VERIFIED the C# parser needs the size as the
first token and `M<d>x<p>`, never reads the file name, and is reached only for Toolbox
components (`Fasteners/FastenerNameParser.cs:82-83,111-127,193-214`,
`Dump/FastenerDumper.cs:53-58`), and `is_toolbox` is false on 89 of 89 components. The
Descriptions name no head or drive word a vocabulary could match (probe), so the head comes from
the head code, and the trailing letter of `FHT`/`BHT` is not assumed to mean a drive (R5).

**Alternatives**: extractor only (rejected: every recorded package would stay unrecognised
until a seat re-dumps it); Python only (rejected: the extractor must still pick candidates to
request their shank faces, R2.12); two parsers with separate tests (rejected: DRY across the two
languages is exactly where drift hides).

### R2.12 The measured shank cross-checks the parsed size, in both modelling conventions

**Decision**: a name-parsed screw agrees with its measured shank when the shank diameter lies
in `[d3 - 0.05, d + 0.05]` mm, with `d` the nominal major diameter and
`d3 = d - 1.226869 · P` the basic external minor diameter of ISO 68-1 (for an inch thread
`P = 25.4 / tpi`). Outside the band the screw is `fastener.identity` **suspected**, naming both
numbers, and its engagement is unresolved (the spec's parser-disagreement edge case). With no
measured shank the agreement is `unmeasured` and nothing is suspected.

**Why**: VERIFIED both conventions occur in one package: shank faces of 8.5 mm for an M10x1.5
(`d - P`), 3.3 mm for an M4-0.7, 6.75 mm for an M8x1.25, and 3.0 mm for an M3 (`d`). A test
against `d` alone would flag three correctly named screws; the minor-diameter bound admits every
real screw of the named size and rejects the next size down (an M4 shank of 3.3 mm is outside an
M5x0.8's `[3.97, 5.05]`). The 0.05 mm is a stated modelling allowance, not a tolerance.

### R2.13 Engagement and bottoming from placed geometry reuse the four joint rules

**Decision**: `checks/fastener.py` gains `check_placed_screw(fastener, hole, placement, ...)`
beside `check_fastener_joint`. It builds the same internal stack from measured quantities
instead of a clamped list - the protrusion is the depth of the screw's tip below the thread entry
along the tapped instance's axis; the usable thread is the Hole Wizard `thread_depth` measured
inward from the tapped face's entry end for a blind hole, or the tapped face's whole axial extent
for a through-tapped hole, labelled `derived: through-tapped length from the tapped face`; a blind
hole with no `thread_depth`, an `unknown` end condition, or an oblique axis leaves it
unresolved - and returns the same four results through the same four rule functions, each with
the derivation in its assumptions. The screw's axial extent comes from its extracted shank face,
or, when it has none, from its exported mesh projected on the axis, labelled
`supplementary: exported mesh`. `check_fastener_joint` and its goldens do not move.

**Why**: FR-012, FR-013 and Principle I. VERIFIED `check_fastener_joint` takes a model-chosen
clamped list and derives a layer's thickness from a bounding box
(`reviewer/src/swreview/tools/checks_fastener.py:119-177`), which is wrong for a counterbored
part, and uses `hole.thread_depth` as the usable depth (`checks/fastener.py:256-259`). The placed
protrusion needs no clamped list. `hole_depth` is never read. A blind tapped face runs deeper than
its thread (the tap drill), so its extent is **never** the usable depth; a through-tapped hole's
thread runs the face's length, which is why the extractor leaves it null on purpose
(`HoleDumper.cs:207-212`) and why the derived value is labelled. The mesh is supplementary
geometry used only where no native face exists (Principle IV) and never for a thread, a
size or a tolerance. VERIFIED on the big assembly (tapped parts' classes from `engagement_rules`):

| Screw | Hole | Tapped class | Engaged (mm) | 1.5 x d (mm) | Outcome |
|---|---|---|---|---|---|
| `cmp:0018` M10x1.5 | `hol:0006`, blind, 12 mm thread | steel | 10.225 | 15.0 | demonstrated short |
| `cmp:0017` M2x0.4 | `hol:0016`, blind, 6 mm thread | steel | 2.205 | 3.0 | demonstrated short (1.10 x d; it passed the old 1.0 x d rule) |
| `cmp:0008` M3x0.5 | `hol:0021`, through-tapped, 1.725 mm long | steel | 1.394 | 4.5 | demonstrated short |
| `cmp:0016` M8x1.25 | `hol:0004`, blind, 16 mm thread | steel | 14.375 | 12.0 | checked within scope |
| `cmp:0027`, `cmp:0024` M3x0.5 | `hol:0014`, `hol:0015` | steel | 5.133, 5.883 | 4.5 | checked within scope |
| `cmp:0007` M4-0.7 | `hol:0013` M5x0.8 | steel | oblique axis | - | engagement unresolved; thread mismatch demonstrated |

The 1.394 mm is the screw's own overlap: the 4 mm screw's tip stops short of the far side of the
1.725 mm tapped length (R4 amends the spec's "about 1.7 mm").

### R2.14 The engagement rule is 1.5 x d into steel and aluminium; "1.td" is read as 1.5d

**Decision**: `engagement_rules.yaml` steel row: `min_engagement_ratio: 1.5`; the steel and
aluminium `source` lines both cite the owner decision of 2026-09-23; every other class unchanged.

**Why**: owner decision. The answer was typed "1.td into both"; the only reading that is a
ratio and matches the aluminium row already in the file is 1.5d, and the spec's Assumptions and
checklist say so, so a wrong reading is visible in three places. VERIFIED the change moves
`test_engagement_rules.py:42-43` (steel 1.0), `test_checks_fastener.py:229-254` (a 6 mm steel
engagement of an M6 was a pass), and the three goldens whose engagement cites the aluminium
`source` (`joint-ok`, `joint-bottoming`, `thread-mismatch`), the unit assertions edited in T042 and
the goldens regenerated in T043, each deliberately.

### R2.15 Tool access: the head from the joint, the tool and reach from tables

**Decision**: for each screw joint the head end is the end of the screw's extent away from the
tapped instance and the outward direction points away from the tapped part. The head plane is
the far end of the screw's mesh extent, or the end of its shank face plus the head height `k`
from the head table, labelled derived; a screw placed by origin with neither is unresolved. The
tool comes from the head code's drive, or from the head type (`hex_key` for socket, button and
socket-countersunk heads, `socket` for hex heads) when the drive is not stated; the swept radius
from the existing table and the reach from a new `reach_diameter_ratio` per tool, both pilot
defaults that say so. The sweep is `geometry.envelope_raycast` over every other body's mesh, and
its result is what `fastener.head_clearance` is decided on. Head fit compares a counterbore's
diameter (the instance's larger diameter) and depth (its face extent, derived) with the head's
`dk` and `k` from `checks/head_dimensions.yaml` (ISO 4762, 7380, 10642, 4017 and 4014), and a
countersink's diameter once US8 reads it.

**Why**: FR-014 and FR-015. VERIFIED the raycast assumes `axis.origin` is the head plane and the
direction runs head to tip (`reviewer/src/swreview/geometry/envelope.py:76-85,164-165`), and the
extractor provides neither (`FastenerDumper.cs:244-258`); the tool takes a model-typed `length`
and records no finding (`tools/measure.py:235-345`); `check_fastener_joint` always passes
`envelope=None` (`tools/checks_fastener.py:287`). The joint map knows which end is in the thread.

### R2.16 Mass and material: one material-class table for engagement and density

**Decision**: the material classes (name, match tokens, density range, source) move out of
`engagement_rules.yaml` into `checks/material_classes.yaml`; `engagement_rules.yaml` keeps one
ratio and source per class name. Three new checks: `mass.material_assigned` (a part passes with a
material, or with an override read as true; fails with neither when the override was read as
false; unresolved when there is no material and the override was not read), `mass.density` (a
part with a material, a mass and a volume whose density is outside its class range, or within
2 percent of 1000 kg/m3, the no-material default, is demonstrated), and `mass.assembly_override`
(an assembly whose override was read as true is suspected for confirmation; with the override
unread, an assembly whose mass is not the sum of its read children, or is a whole number of grams
while a child is unread, is suspected). Unread components and body gaps are counted in one
`skipped` coverage item. The standards family's `material_assigned` is not touched.

**Why**: FR-016 to FR-018. VERIFIED densities of 2700 and 7700-8000 kg/m3 on the read parts, an
assembly of exactly 2.000 kg (effective 4068 kg/m3) whose children were never opened, and the
small assembly, whose 0.3722 kg equals its part plus two pins; `mass_overridden` absent on 26
of 26 and 3 of 3 documents, every read a `tool_error` gap (analyst facts 26, 29). VERIFIED the
standards check is the release macro's exclusive-or with a configuration gate
(`checks/standards/part.py:444-542`): it answers a different question and stays as it is. One
table serves both engagement and density because both classify a material name, and two token
lists would drift.

**Alternatives**: a density column in `engagement_rules.yaml` (rejected: the file name would lie);
a fallback of `material_assigned` to the active configuration (the analyst's 5(b); rejected
here: it changes a release rule the owner has not decided, R5).

### R2.17 Hygiene reads its property names from the standards profile

**Decision**: five document-scope checks in `checks/hygiene.py`:
`hygiene.part_number_matches_file` (the profile's part-number property against the file name's
stem, case-insensitive), `hygiene.duplicate_description` and `hygiene.duplicate_part_number`
(one finding per value naming every distinct document that shares it),
`hygiene.revision_present` (the profile's `revision.property` on every part and assembly), and
`hygiene.component_not_resolved` (every lightweight or suppressed component of the reviewed
configuration, one finding per document with its instance count). With no standards profile
attached, the three property-dependent checks are one `skipped` coverage item naming the
missing setting; the component check needs no profile. FR-020 is met inside the standards
data-card check: when a non-empty pattern matches none of the graded documents, each document's
data-card result is unresolved with "the part-number pattern matched 0 of N documents, which is
likely a profile error" instead of skipped.

**Why**: FR-019 and FR-020. VERIFIED the data card was graded on 0 of 30 documents across three
real-profile runs, every one skipped for the pattern (analyst fact 31;
`checks/standards/traversal.py:164-179`, `checks/standards/document.py:161-170`). A property name
guessed in code would be a company value compiled into the source, which
`test_standards_no_company_values.py` forbids.

**Alternatives**: new standards checks (rejected: they would move the release verdict and the
pinned sixteen, and the owner framed hygiene as "beyond the release standards"); matching the
pattern against the stem (the analyst's recommendation 6; not in the spec, changes feature 006's
contract; R5).

### R2.18 Tolerances: four sources, one resolver, a fixed precedence, binding by geometry

**Decision**: `checks/tolerances.py` resolves a tolerance for a **subject** - a hole instance's
size, a pin's or fastener's size, a hole instance's position - by walking the sources in this
order and returning the first that binds, with every other source that also carried one listed:

| # | Source | Binds a subject when | Available |
|---|---|---|---|
| 1 | drawing callout (feature 011) | 011's native dimension or hole callout references one of the subject's faces | after 011; until then listed as "not available (feature 011)". *Note 2026-09-23 (feature 011): filled as `drawing_answer(package, subject) -> DrawingAnswer` - limits, or a written precision and unit handed to source 5 - per `specs/011-drawing-context/contracts/drawing-source.md` section 4, behind `DRAWING_BINDING_VALIDATED`; nothing else in this precedence changes* |
| 2 | model annotation (DimXpert or MBD) | an attached face's persist ref equals one of the subject's face persist refs | after the US8 reads, seat-validated |
| 3 | model dimension | same document, a diameter or radius dimension, its nominal equal to the subject's size within 1e-6 mm, and the only such dimension in the document | after the US8 reads, seat-validated |
| 4 | Hole Wizard class | the subject's hole carries a fit class that names an ISO 286 tolerance class in `checks/iso286.yaml` | after the US8 reads, seat-validated |
| 5 | general tolerance block | a size subject with no tolerance from 1 to 4, and the standards profile (version 2) declares a band containing its nominal | Python only, now |

A position subject is never given a general tolerance (a linear block tolerances the locating
dimensions, not a position zone). Two explicit sources that disagree resolve to the higher one
and add a coverage limit naming both. A subject no source binds is unresolved with the list of
sources searched and why each did not bind. Nothing is inferred.

**Why**: FR-021 to FR-025 and the owner's decision (all four sources). VERIFIED the IR carries a
tolerance only on a PDF-ingest `Dimension` (`ir/models.py:226-237,794-805`), the native
`DisplayDimensionRecord` holds value and override only (`:964-1014`), `Hole` has no class field
(`:573-593`), and the extractor reads no `IDimension` tolerance, `IGtol`, `IDatumTag` or DimXpert
data (analyst fact 34). Binding by face persist ref and by unique value is what the package can
support; anything looser would attach a tolerance to the wrong hole.

**Alternatives**: a general tolerance applied to every hole regardless of explicit sources
(rejected: the spec's "an explicit tolerance always wins"); an ISO 2768 table in code for the
general block (rejected: the company's title block is data the profile declares, and a standard
class default would be a tolerance the evidence does not contain, SC-007).

### R2.19 The general tolerance and the hygiene names are standards profile version 2

**Decision**: `PROFILE_VERSION` becomes 2 and the loader accepts 1 and 2. Version 2 requires two
new sections - `general_tolerance` (a list of linear bands `{over_mm, up_to_mm, plus_minus_mm}`
and an optional angular value, where an empty list means "the company declares none") and
`hygiene` (`part_number_property`, `description_property`, each possibly empty) - and a version 1
profile loads with both absent: no general tolerance source, and the hygiene property checks
skipped naming the missing setting.

**Why**: VERIFIED the profile is strict and closed and every key is required
(`checks/standards/profile.py:10-16,55,143-152`), so adding keys to version 1 would refuse the
owner's real profile on the next sitting. VERIFIED `test_standards_no_company_values.py` requires
the example, both fixtures and the contract block to carry exactly the same fields with values
that differ everywhere, and `specs/006-standards-check/research.md` R5 to carry one row per
value-bearing field (`test_the_r5_table_parses_and_names_exactly_the_profile_fields`), so the
change lands in all five files at once (T016). Feature 011 also plans a `drawing` profile section
with a general tolerance; it should reference this section rather than restate it (R5).

### R2.20 The registration point: a tuple the pre-run reads, three argument-free tools

**Decision**: `tools/checks_mechanical.py` holds the three new tools - `check_joints()`,
`check_mass_material()`, `check_hygiene()`, none taking an argument - and
`CODE_FIRST_CHECKS: tuple[str, ...]`, the names in the order the pre-run calls them.
`prerun.planned_calls` appends `(name, {})` for each name not withheld, after the interference
groups and before `check_standards`; `PRERUN_TOOLS` includes them so a withheld one carries its
tier's sentence. The tuple is empty until US2 lands `check_joints`, so with it empty the plan and
the digest are byte-identical to today. When `check_joints` ran, the `fastener joints` and `hole
alignment` not-evaluated lines are rewritten to what the joint map could not reach (unplaced
screws, instances with no face, screws whose tapped part was not extracted) and
`coaxial_hole_pairs`, orphaned by that change, is removed (it has no test of its own).

**Why**: FR-026 and SC-006. VERIFIED `planned_calls` is the pre-run's one plan
(`reviewer/src/swreview/prerun.py:377-410`) and feature 008 keeps it ("It then computes
`planned_calls`, which is unchanged", 008 research R2.16), so a tuple read there joins the
code-first pass whether 008 has landed or not: before 008, under lever 5 or 11; after 008, under
the pane default. Each check is also a plain function over the package (callable from a test or
a script) and an ordinary tool the model can call when checks first is off, as `check_rms_assembly`
is today. When 008's re-call guard exists, the three names key as `(tool,)` (T092).

**Alternatives**: one `check_mechanical()` tool (rejected: a grab-bag whose payload and
docstring mix joints, mass and hygiene; one tool-array change fewer is not worth the loss of a
purpose-named digest line); one tool per story (rejected: US3 to US5 all run over the same joint
map, and three tools over one map would rebuild it three times or share hidden state).

### R2.21 Patterned joints fold into one finding; passes stay findings

**Decision**: joints with the same kind and the same members by hole feature and component
(the 15 `hol:0014`/`hol:0019` joints) form a **pattern group**. Each check runs per joint; results
with the same check, status, severity and calculation result within a pattern group become one
finding naming every joint, its instance ids and its count. A pass is a `checked_within_scope`,
`info` finding with its calculation, as every numeric family records it today. The joint map
itself is coverage: one `checked` item per pattern group, one `skipped` item per candidate and
per unplaced fastener, one per instance the map could not use.

The rule for passes follows the family precedent: a check that has a calculation (every joint
check, `mass.density`) records a pass as a finding; a rule with no calculation
(`mass.material_assigned` and the five `hygiene.` checks) counts its passes in one `checked`
coverage item per check, as the standards family's `passed()` does.

**Why**: the spec's patterned-joints edge case. VERIFIED `check_fastener_joint`, `check_fit`,
`check_axial_stack` and `check_hole_alignment` all record passes as findings
(`checks/fastener.py:362`, `fit.py:112`, `stack.py:151`, `hole_alignment.py:124`), and feature
007 ranks them last and counts them in the not-amplified line. Recording passes as coverage would
drop the calculation an engineer needs to see why a joint passed. Without the fold, 50 joints and
up to eight checks each would be about 300 findings on the big assembly; with it, 11 pattern groups.

### R2.22 New check ids and their classes, added to policy v1

**Decision**: twelve new finding ids - `hole.nominal_alignment`, `hole.position_stack`,
`fastener.identity`, `fastener.head_fit`, `mass.material_assigned`, `mass.density`,
`mass.assembly_override`, `hygiene.part_number_matches_file`, `hygiene.duplicate_description`,
`hygiene.duplicate_part_number`, `hygiene.revision_present`, `hygiene.component_not_resolved` -
classed `interface` (the four `hole.`/`fastener.` ids, already under the needs-judgement
prefixes), `manufacturing` (the three `mass.` ids) and `hygiene` (the five `hygiene.` ids),
added to `attention_policy_v1.yaml` without a version change. `test_attention_catalogue.py`
gains the new modules as sources.

**Why**: FR-027. VERIFIED the catalogue test pins `len(NUMERIC_CHECKS) == 9` and
`len(emittable()) == 60` (`reviewer/tests/unit/test_attention_catalogue.py:72,74`), so every new
id is a deliberate edit in the task that lands it. Adding classes changes no existing row, so
every past `attention.json` still reproduces under v1; feature 007's rule "a change to a class is
a new version" is about changing a row. The classes are a first opinion for the owner's
read-through (R5), as feature 007's were.

### R2.23 IR schema 1.5.0: additive and omitted when empty

**Decision**: `Hole.wizard: HoleWizardData | None` (fit class raw, thread class raw, thru-hole,
tap-drill, counterbore and countersink diameters, counterbore depth, countersink angle, head
clearance - each nullable with a gap), `EvidencePackage.model_dimensions: list[ModelDimension]`
and `model_annotations: list[ModelAnnotation]`, each entity with an id pattern, a persist ref and
its scope, serialized through `omit_additive` so a package without them round-trips to the bytes
a 1.4.0 build wrote. The C# models mirror them; `ir.schema.json` is regenerated.

**Why**: FR-021, FR-022, FR-028 and Principle IV. VERIFIED the additivity rule and its helper
(`ir/models.py:92-117`), the strict `extra="forbid"` base (`:157-160`), and the 1.4.0 precedent
(`:350-363`, `:1351-1364`). Feature 011 also adds drawing tolerance fields; whichever feature lands
first takes 1.5.0 and the other the next minor (R5).

### R2.24 Extractor reads behind reader seams, validated on the next sitting

**Decision**: every new interop read goes through a one-method reader seam with a fake in
`SwReview.Extractor.Tests/Fakes/`, as `PropertyDumper` already does with its delegate reads: the
Hole Wizard reads (`IHoleWizardReader`), the model dimension tolerances (`IDimensionToleranceReader`
over `IDimension.GetToleranceType/Values/FitValues`), the annotations (`IModelAnnotationReader`
over `IGtol` and `IDatumTag`), the mass override (a second read through
`IModelDocExtension.CreateMassProperty()` and `IMassProperty.OverrideMass`, with
`IMassProperty2.GetOverrideOptions()` as the fallback), and the fastener candidate predicate (a
pure static function). The guard's denylist grows by the setters beside each family in the same
change. Every code path is tested without a seat; SC-008 is the seat run.

**Why**: the constitution's read-only rule and the development machine's lack of a licence.
VERIFIED the override read casts `CreateMassProperty2`'s object to `IMassProperty`
(`extractor/SwReview.Extractor/Dump/PropertyDumper.cs:132-140`), which raised on every document;
the analyst's reflection found `OverrideMass` on `MassProperty` and not on `IMassProperty2`
(fact 27). VERIFIED the denylist and its rule (`Guard/ReadOnlyGuard.cs:23-149`) and that two test
classes pin its membership (`GuardTests.cs:303` `StandardsDenylistTests`, `RemodelGuardTests.cs`).

### R2.25 The mass and hygiene families close their checklist items with one summary row each (amendment 2026-09-23)

**Decision** (2026-09-23, recorded with the owner's decision 3A work that lands T098-T099;
T108; `contracts/mass-material.md` section 3, `contracts/hygiene.md` section 2).
`check_mass_material` and `check_hygiene` each end by writing one coverage row under their
checklist item's id - `mass.material` and `hygiene`, each family module's `SUMMARY_CHECK` - as
the RMS and standards families write `modeling.resilience` and `standards.release`. The row is
`checked` or `skipped` by what the call did (amended below; first written always `checked`), its reason
counts what the call wrote and found - `"<c> checked, <s> skipped coverage item(s) over <n>
document(s); <f> finding(s)"` - and its scope is the configuration reviewed. It is written with
`replace_coverage`, so a repeated call leaves one row. The tools' results do not change: their
`coverage` counts stay the per-check rows. The two checklist items name no tool, as
`standards.release` names none: "Closed by a mass finding, or by the family's summary coverage
item" and the same for hygiene.

**Why.** The checklist closes an item on a finding under its prefix, or on a coverage row whose
check *is* the item id; it never matches coverage by prefix. Both tools write per-check rows
only (`mass.material_assigned`, `mass.coverage`, `hygiene.revision_present`, ...), so a run with
no finding would leave its item open and the review would end saying the item "ended without a
finding or a coverage entry" - false, since the family ran. The first attempt at T098-T099
found this. Naming `check_mass_material` or `check_hygiene` in an item would tell the model to
call a tool lever 13 withholds once checks first has run it (008 FR-030): the sweep in
`test_withheld_wording.py` forbids that, and a rewording per item would be two more sentences
to keep matching exactly; with checks first off, the tool's own description tells the model
what it checks, as it does for `check_standards`.

**Amended 2026-09-23: the row's bucket.** As first landed the row was always `checked`, so a run
that checked nothing - no standards profile, every part lightweight, every per-check row skipped -
put a `checked` row under the goal's own item and the Review summary's goal line read "checked, no
issue" instead of "not reached" (009 `contracts/review-summary.md` section 3, row 3 before row 5).
The row is now `checked` only when the call wrote at least one `checked` per-check row or recorded
a finding; otherwise `skipped`, with the same counts in its reason, so row 2 answers: not reached,
"skipped", the counts as the detail. A call whose finding is refused stops before its per-check
rows, as every check tool stops at one, and writes the row `failed` with the refusal as its
`error` - never `checked`, whatever it recorded before the refusal - so the goal line says "a
check failed" unless an earlier finding is an issue. It is one row across `checked`, `skipped` and
`failed` (`checks_mechanical.SUMMARY_BUCKETS`): `replace_coverage` clears one bucket, so the other
two are cleared first, as the rules and standards families clear theirs. Pinned by
`tests/unit/test_mechanical_family_summaries.py` on scripted runs (all skipped, one checked,
findings only, a refusal first, with passes and after a finding, each with its goal line) and on
the packages it was found on. One consequence, accepted: the hygiene component check writes no row
for its passes, so a hygiene run with no profile whose components are all resolved reads `skipped`
- its four property checks were skipped, and the reason's counts say so.

*Amended again 2026-09-23 (a defect found in review): finalization and the `failed` row.* `failed`
closes no checklist item (`agent/checklist.COVERAGE_BUCKETS`, 005 FR-051), so after a refused
call the item was still open and `finalize_session` added its close-out row - `unresolved`, "the
review ended without a finding or a coverage entry for it" - beside the family's own row. That
sentence is false, and the unresolved bucket comes first in the goal line's reason order, so the
saved session's goal line read "evidence missing" rather than "a check failed". Finalization now
adds no close-out row for an item that has a `failed` row under its own id; a `failed` row under
another check (the registry's `tool.<name>`) leaves the close-out as it was. `failed` still closes
nothing, for `Checklist.bucket_of` and for lever 7. Pinned in the same module: every scripted case,
refusals included, keeps its one row and its goal line through finalization.

**Alternatives.**

| Option | Why not |
|---|---|
| Match coverage by prefix in the checklist | Every per-check row of every family would close items, `mass.coverage`'s skipped row among them. |
| Leave the item to the model's `mark_coverage` | A check tool can answer it; the system prompt's rule for the RMS item is not to mark by hand. |
| A bucket that follows what was skipped | The hygiene component check writes no row for its passes, so "nothing checked" cannot be told from "nothing to find"; the reason carries the counts instead. *Taken by the amendment above* in the form "checked only on a checked row or a finding": an always-`checked` row made a run that checked nothing read "checked" on the summary, which is worse than the component check's silent passes reading `skipped`. |
| Name the tools and add two lever 13 rewordings | Above: more exact sentences to keep matching, for words the tools' descriptions already carry. |

## R3. Verified facts the plan relies on

**Packages** (analyst fact 1, re-checked). The big assembly: 26 documents (23 parts, 3 assemblies), 89
components (86 resolved, 2 lightweight, 1 suppressed), 27 hole rows (132 instances), 0 fasteners,
0 interferences on disk, 245 faces on 21 components, 141 bodies on 83 components, 23
`mass_override` tool-error gaps, 4 parts with no material (3 unopened, 1 surface-only), part
classes steel 15, aluminium 4, unknown 4. The small assembly: 3 documents, 4 components, 4 hole rows (16
instances), 0 hole-to-hole joints, one pin-in-hole joint, 3 `mass_override` gaps.

**The recorded review's choices.** 6 of 113 detected interference groups judged; 8 interference
findings, 5 of them 0.0 mm3; alignment pairs `hol:0004`/`hol:0010`, `hol:0010`/`hol:0024` and
`hol:0017`/`hol:0027`. Per instance, `hol:0004`/`hol:0010` are three joints at 0.000 mm and
`hol:0017`/`hol:0027` one joint at 0.000 mm; `hol:0010`/`hol:0024` are at 90 degrees and are not a
joint.

**Screws** (the big assembly, probe). 68 named, 57 placed on an instance axis, 48 on a tapped instance,
46 agreeing in size, **2** M4 screws on M5x0.8 tapped instances (the analyst reported one); 9 on a
counterbore or clearance axis whose tapped part has no extracted hole; 11 on no extracted axis;
68 of 68 have a body mesh; 11 have a face.

**The tests that go red by design**, each named in the task that lands it and edited
deliberately, never loosened: `test_checks_interference.py:314-320` (a possible-only group becomes
a contact, T017); `test_engagement_rules.py:42-43`, `test_checks_fastener.py:229-254`, and the
`joint-ok`, `joint-bottoming`, `thread-mismatch` goldens (T042, T043); `test_prerun_digest.py:124-135`
("1 fastener", "1 coaxial hole pair", T036 and T046); `test_attention_catalogue.py:72,74` (T036,
T046, T060, T066, T074); `test_provider_schema.py:148` and the curated-tool rows of
`specs/001-agentic-design-review/contracts/agent-tools.md`, `test_tool_payload.py:299-325`
(`REVIEW_TOOL_COUNT` and the array byte pins) and the byte counts quoted in
`specs/005-llm-efficiency/contracts/levers.md` (T027-T028, T066-T067, T074-T075); `test_standards_no_company_values.py`
field tests, `specs/006-standards-check/research.md` R5, and the ten `standards-*.yml` goldens that record a fixture profile's `sha256` (T015-T016); the standards goldens whose
pattern matches no document (T072, which lists them); `test_tool_envelopes.py` shape rows
(T056); `test_engagement_rules.py` shape rows when the match tokens move (T062);
`tests/integration/test_coverage_stop.py` round counts, the `cover-blind-tap` golden and
`test_checklist.py` (T098); `StandardsDenylistTests` and `RemodelGuardTests` counts and
`specs/004-resilient-remodeler/contracts/guard-allowlist.md` (T086); the IR serializer and
contract tests for 1.5.0 (T076, T078).

**What does not move**: `check_fastener_joint`, `check_hole_alignment`'s inputs,
`check_tool_envelope` and every other model-facing tool's signature; the RMS and standards
registries (the standards data-card change is inside one rule); `Finding`'s shape; the event
schema (a contact rides the judging tool's own `tool.finished`); the MCP function list and the
terminal profile (check tools are in neither); every golden of `report/markdown.render_report`
(the Contacts section renders only when contacts exist).

## R4. Amendments to the spec made by this pass

| Where | Was | Now | Why |
|---|---|---|---|
| US2 Independent Test, SC-003 | "the five near-coaxial cross-part pairs the analysis found ... none of the three unrelated pairs the recorded review checked" | the three first-instance joints the analysis found within 1 mm (`hol:0012`/`hol:0024`, `hol:0016`/`hol:0023`, `hol:0018`/`hol:0027` at 0.750 mm) plus every per-instance joint (50 in 11 pattern groups on the shaped fixture); the two 1-5 mm first-instance pairs are not joints (47.5 and 49.0 mm apart along the axis); of the recorded review's three pairs, `hol:0010`/`hol:0024` is absent and `hol:0004`/`hol:0010` and `hol:0017`/`hol:0027` are real joints the old check compared on the wrong instances | R2.1, R2.2 |
| US4 Independent Test, SC-002 | "the M4 screw in the M5 tapped hole" | two M4 screws in M5x0.8 tapped instances, one folded finding with a count of two | R3 |
| US4 Independent Test | "the M3 screw engaging about 1.7 mm" | about 1.4 mm engaged of a 1.725 mm through-tapped length | R2.13 |
| FR-007 | "half the hole-to-fastener clearance" | the fixed- and floating-fastener sums of R2.6 | a pin through two clearance holes has two clearances |
| FR-010 | worst case "when every contributor has a tolerance" | the declared-model rule of R2.7 (size and position, or size only with position excluded and named) | Principle I; `fit.size_only` precedent |
| FR-018 | "count bodies it could not read" | met by the existing `body` gaps, counted in the Python mass coverage item; no new extractor field | the gaps exist (R3) |
| FR-019 | the part number "property" and "revision" | the property names the standards profile (version 2) declares; skipped coverage without a profile | R2.17, R2.19 |
| Polish, T098-T099 (2026-09-23) | two checklist items closed "on their findings and on their summary coverage", which neither tool wrote | each tool writes one summary row under its item's id (T108); the items name no tool | R2.25 |

## R5. Open items, and the owner's answers of 2026-09-23

Settled on 2026-09-23 (owner's answers, or settled by the real standards profile):

| Item | Answer | Effect on the tasks |
|---|---|---|
| The drive of the head codes `FHT` and `BHT` | **Torx**: FHT = flat head Torx, BHT = button head Torx (owner) | `fastener_names.yaml` ships `FHT` and `BHT` with drive `torx`; `tool_envelopes.yaml` gains a Torx key envelope; tool access for those 36 screws reaches a verdict (US5) |
| The shop's tool set | **Pilot defaults for now** (owner); the table is data and is replaced later | US5 ships the pilot envelopes labelled "pilot default" on every result |
| The general tolerance | **By decimal places** (owner): the bands are declared in standards profile version 2 (for example `.X`, `.XX`, `.XXX` and angles); no standard table in code | US8's general source reads the declared bands; the actual band values are still to be supplied with the regenerated profile |
| A screw through-tapped into thin sheet | **A finding at low severity** (owner), carrying the sheet thickness | US4's engagement check emits `fastener.engagement` at `low` when the tapped part is through-tapped and thinner than 1.5 x d, and at the normal severity otherwise |
| Whether the part-number pattern should match the file stem | **No change**: the real profile's pattern includes the extension, so whole-name matching is right; the 0-of-30 result came from the workstation's example profile | none |
| Whether `material_assigned` falls back to the active configuration | **No**: the real profile names `Default`, which the recorded parts carry | none |
| Which feature lands IR 1.5.0 and profile version 2 first | **010**, which comes before 011 in the roadmap's waves | 011 takes the next versions |

Still open:

| Item | Owner | Blocks |
|---|---|---|
| The real standards profile regenerated at version 2 with the decimal-place general tolerance bands and the part-number and description property names | owner | the general source (US8) and the hygiene property checks (US7) on real runs |
| Confirmation of the twelve new ids' consequence classes (R2.22) at the next read-through | owner | nothing; they ship as a first opinion |
| The interference volume unit and `IsPossibleInterference` on zero-volume rows (T069 of feature 001) | next sitting | the contact rule's inputs being verified at the source |

## R6. Where this design differs from the analyst's recommendations

| # | Recommendation | Here | Reason |
|---|---|---|---|
| 1 | Zero-volume rows as low-severity "contact at nominal" **findings** | a contact list on the session, never a finding | owner decision 2026-09-23 (R2.9) |
| 1 | Run `bridge_interference` at review start and persist the rows | not in 010 | feature 008 FR-009 owns it (008 `contracts/checks-first.md` section 3) |
| 2 | Joint map over `Hole` rows with one axis each | over hole instances from the faces | R2.1: 3 of 50 joints otherwise |
| 2 | `<= 1 mm` lateral band | overlap gate plus a 1 mm axial adjacency gap, and one partner per component | R2.2 |
| 2 | Offset against `(H - F)/2` | fixed and floating sums | R2.6 |
| 2 | Flag a clearance size that disagrees with the tapped size | a negative clearance term, demonstrated by the alignment check | R2.4, R2.6 |
| 3 | Name-parse fasteners marked `suspected` | recognised and cross-checked; `fastener.identity` suspected only on a shank disagreement | R2.12: a correct name is not a suspicion |
| 3 | Shank cross-check against the nominal | a band from the basic minor to the major diameter | R2.12: both modelling conventions occur |
| 4 | One derived clamped layer into `check_fastener_joint` | `check_placed_screw` sharing the four rule functions | R2.13: no fake layer, no fake hole |
| 4 | Faces or meshes for the screw extent | face first, mesh only without a face, labelled | R2.13, Principle IV |
| 5(b) | Grade the active configuration for `material_assigned` | not done; a separate profile-independent check | R2.16, R5 |
| 6 | Match the part-number pattern against the stem | not done; the zero-match profile error only | R2.17, R5 |
| 7 | Default tool from the head code | from the head code's drive when known, else the head type, else unresolved | R2.15, R5 |
| 8(d) | General tolerance from a profile class such as ISO 2768 | bands the profile declares, no standard table in code | R2.18 |
| 8(a) | Hole Wizard fit classes | recorded raw; converted to limits only for an ISO 286 class the shipped table carries | R2.18 |
