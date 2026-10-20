# Research: Automatic Mechanical Checks

**Feature**: `010-mechanical-checks` | **Date**: 2026-09-23 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the analyst's check-by-check pass over the two recorded evening packages
(34 facts, 8 recommendations, 10 open questions, 2026-09-22); a second reading pass on
2026-09-23 over every module the plan names, at tip `c83e8be`; and three read-only probes run
on 2026-09-23 over the recorded packages of the big assembly's recording and the small
assembly's (the one `small-assembly-a` was generated from), outside the repository. The probes print ids, sizes and
millimetres only; no name, path or property value of either package is written anywhere in this
package or in any file a task creates. Where this document says VERIFIED, the file was opened
on 2026-09-23 and, where the claim is behavioural or numeric, the code or the probe was run.
Line numbers are as of `c83e8be` and will drift; every task re-verifies before editing.

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

### R2.26 Fine and non-standard thread pitch is flagged for the engineer to confirm (amendment 2026-10-08, owner decisions 50A to 53A)

**Decision** (2026-10-08, the owner's decisions 50A to 53A, recorded before their code;
`contracts/fasteners.md` section 8, `contracts/coarse-pitch.json`, tasks T110 to T126). The
owner's request, verbatim: "Add check for fine pitch parts and threaded holes. Call out and flag
to user to make sure they mean to use it anywhere. We almost always use standard threads not
fine... so it's a common mistake." The owner chose the first option of each of four questions:

- **50A, ISO and UNC table** (question 50: "What should count as fine pitch, and how should a
  thread written with no pitch (M8) be treated?"). A per-diameter table of the ISO 261 metric
  coarse pitch and the ASME B1.1 UNC threads per inch, held in one cited YAML data file in
  `reviewer/src/swreview/checks/` (`coarse_pitch.yaml`, with `version` and `source` lines; source
  "Owner decision 2026-10-08 (50A): the shop uses coarse threads; fine pitch must be confirmed").
  Flagged: a metric pitch finer than that diameter's coarse pitch; an ISO 261 size with no coarse
  pitch at all; an inch thread finer than UNC (UNF, UNEF, 8-UN and the other constant-pitch
  series); and a pitch coarser than the coarse pitch, as non-standard. A metric thread written
  with no pitch (`M8`) is coarse by the ISO designation rule (ISO 965-1 omits the coarse pitch
  from the designation), stated on every result that relies on it. Threads whose pitch cannot be
  read (unrecognised text, a size in no table such as M2.3, a mixed fraction the parser does not
  read) and pipe threads (`NPT`, `NPTF`, `NPS`, `NPSM`, `BSP`, `BSPP`, `BSPT`, `G`, `R`, `Rc`,
  `Rp`, `PT`, `PF`; a Hole Wizard pipe tap that arrives as a bare `3/8`) are listed as not
  checked, never passed.
- **51A, flag all, Accept** (question 51: "How should fine threads you mean to use (hydraulic
  ports, locknuts) be handled?"). Every fine or non-standard thread is flagged on every review;
  the engineer confirms with the existing Accept disposition. No allow-list and no persistence
  across reviews now.
- **52A, all model sources and the parser fixes** (question 52: "Which sources should the check
  read?"). Hole Wizard tapped holes (`Hole.thread_designation` where `hole_type` is tapped),
  cosmetic threads (`package.threads` designation), fastener rows (`package.fasteners`
  `thread_designation`, any kind: a nut can be fine) and screws parsed from their names
  (`recognise_fasteners`). Fasteners are flagged even when bought (choosing a fastener is a design
  choice); tapped holes and cosmetic threads inside bought parts (feature 013's part roles) are
  listed once in one coverage row, not flagged; drawings are out of scope and named in the
  coverage limits as not read for pitch. The parsers are fixed in Python and C#: `parse_thread`
  reads a decimal comma, a hyphen pitch (but `M8-6H` is a tolerance class) and the
  multiplication sign, with pipe tokens recognised by one helper beside it; the name grammar
  reads one whole number after a metric size as a pitch when it is at most that diameter's coarse
  pitch, otherwise as a length, a size with no coarse pitch keeping today's rule; and the C# side
  holds its own copy of the table, both copies pinned by a test on each side to one contract file,
  `contracts/coarse-pitch.json` (the pattern of R2.11's shared name vectors).
- **53A, a feature 010 amendment on a new branch** (question 53: "Where should this work
  live?"). Feature 010's documents are amended - this entry, `contracts/fasteners.md` section 8
  and dated tasks - before the code, on a new branch and worktree off main; test-first, with
  adversarial review and the full gate; no push, merged on the owner's word.

**Defaults taken on 2026-10-08 and stated to the owner, who did not override them** (each a
default the owner may revise):

| # | Default | Where |
|---|---|---|
| D1 | One new argument-free code-first tool, `check_threads`, appended to `CODE_FIRST_CHECKS` after `check_hygiene`, so the pre-run runs it and lever 13 withholds it once it has completed; its description within the 160-character cap | `contracts/fasteners.md` 8.7 |
| D2 | Two finding ids: `thread.fine_pitch` (finer than coarse, a fine-only size, an inch thread finer than UNC) and `thread.nonstandard_pitch` (coarser than coarse); `suspected`, `medium`. Not a `fastener.` id, so a pitch finding never closes the "Fastener joints" checklist item; `thread.` joins the needs-judgement prefixes, so the findings land in the Review tab's Decide group; the Fasteners goal owns the two finding ids by name, in its `items`, so they are listed in the Fasteners group, and the coverage-only `thread.pitch` rows belong to no goal (the owner's decision 63A, below, which replaced D25; first written as the Fasteners goal and group owning the prefix); each id is classed `interface`, like `fastener.thread_match`; the checklist text does not change | 8.4 |
| D3 | *Its grouping and words superseded the same day by the owner's decision 57A (below): one finding per (check, owning part), listing each designation with its sources and its coarse alternative.* As first written: one finding per (owning document, normalised designation), listing every hole feature, cosmetic thread or fastener instance with its entity id (Principle IV); the words name the part, not its id: "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 3 tapped holes in <part>: <features>", "Confirm M8x1 is intended in <part>, or change it to the coarse M8x1.25.", requirement "threads use the coarse (standard) pitch unless a fine pitch is deliberate"; no percent sign. The ids on every source, the part named by its file, the requirement and no percent sign stand | 8.5 |
| D4 | Passes have no calculation, so (R2.21) they are counted in one checked row ("N threads have the coarse pitch"), not one finding each; unreadable designations (a tapped hole with no designation among them) and unknown sizes are one unresolved row each, pipe threads, threads in bought parts and suppressed hole features one skipped row each; a package with no thread says so in one row | 8.6 |
| D5 | Suppressed features: a `Hole` row carries no suppression flag, so it is joined on its owning document and `feature_name` to the `Feature` rows (`Feature.suppressed`); a suppressed hole is skipped, never flagged; where the join is not possible the coverage limits say so | 8.2 |
| D6 | A fine screw in a coarse tapped hole is reported by `fastener.thread_match` (the mismatch, as today) and by `thread.fine_pitch` on the screw (the deliberate-choice question); both stay | 8.10 |
| D7 | Inch pitches are compared as threads per inch (25.4 / `pitch_mm`, within 0.01), never as rounded millimetres; `#N` diameters come from `parse_thread`; `#0` has no UNC thread, so it is a fine-only size and is flagged like M25 | 8.1 |
| D8 | The two tables below, as transcribed | `coarse-pitch.json` |

**Defaults this entry takes in writing the design down** (2026-10-08; each a default the owner
may revise):

| # | Default | Why |
|---|---|---|
| D9 | A pitch marker straight after a metric size with no number after it (`M16xPh3P1.5`, `M8x`) makes the designation unreadable (`contracts/fasteners.md` 8.8, rule 4) | `parse_thread` reads `M16xPh3P1.5`, a multi-start thread's lead and pitch, as M16 with no pitch, which the no-pitch rule would pass as coarse; 50A says a thread whose pitch cannot be read is listed, never passed. The change reaches `fastener.thread_match` too, which then reads such text as unresolved rather than as a diameter-only match - the same rule, Principle I |
| D10 | The answer to the part-roles question restates `check_threads` (`runner.ROLES_RESTATED` gains it, after `check_hygiene`) | `ROLES_RESTATED` is "every check whose grading reads the roles" (`reviewer/src/swreview/agent/runner.py:917-920`), and the thread check grades holes by role (52A); without it a finding on a part the engineer then calls bought would stay until the next review. It moves feature 013's `contracts/part-roles.md` section 6 table and 008's `contracts/answer-batch.md`. The restated-tools assertions of `test_answer_batch_roles.py:270` and `:521` do not move: neither review runs the check (no pre-run, and `_restate` restates only a check the session ran, `test_a_tool_that_never_ran_is_not_restated`). A restate is a real call through the dispatch, so the check's rows restate rather than add (D14), and T119 tests the regrade end to end |
| D11 | The owning document is the document of the row's component for holes and cosmetic threads, and the fastener's own document for fasteners | the bought test (`roles.graded(document_id)`) and the grouping read one document per source; a fastener's part is what the engineer chose |
| D12 | The suppression join also requires the `Feature` row's `configuration` to equal the component's `referenced_configuration`; a null `suppressed`, or no such row, is "not read" and said on the finding | a feature tree is read in the document's active configuration (`reviewer/src/swreview/ir/models.py:499-501`), `suppressed` is per that configuration and null when unreadable (`:514`), and a feature suppressed in one configuration may be active in another |
| D13 | Fastener rows: any row with a designation is read, whatever its kind; a screw, bolt or nut row with none is unreadable; a washer, pin or `other` row with none states no thread and is not a source; a row whose component is `suppressed` is skipped as suppressed; a row `recognise_fasteners` does not return (its component or document absent) is unreadable | 52A reads every kind; a washer with no size has no thread to judge, and listing every one as unreadable would bury the real gaps. A pin's or washer's designation is its nominal size, read like a thread: a pin named for a fine-only size (`M25`) is flagged and confirmed like any other, and a pin recognised by name is read as a pin row is, so the same pin is treated alike whether the extractor or the name grammar recognised it; the owner may narrow the kinds |
| D14 | Every coverage row is the coverage-only id `thread.pitch`; it needs no attention class (only finding ids do). A call withdraws every `thread.pitch` row from `checked`, `skipped` and `unresolved` before it records its own (`context.withdraw_coverage`), so the rows restate the current state (`contracts/fasteners.md` 8.7) | one id, which belongs to no goal, so the rows change no goal line (the owner's decision 63A; first written as owned by the Fasteners goal's prefix). *Amended 2026-10-08 in review:* the rows were first appended as `check_joints` appends its rows, a repeat left to the re-call guard; but the part-roles answer restates the check through the dispatch (D10, `runner._restate`), a real call the guard does not answer, and `record_coverage` only appends (`reviewer/src/swreview/tools/context.py:271-280`), so after "All bought" the old checked row would still count the newly bought part's tapped holes beside the new bought row listing them, every count twice. `check_drawings` restates its rows the same way (`reviewer/src/swreview/tools/drawings.py:134`); `test_coverage_withdrawn.py`'s set of code-first checks whose second call withdraws gains `check_threads` (T119) |
| D15 | The C# copy holds the `metric` rows only; the Python copy holds every key; the contract file also carries a `standards` key naming the standard each table comes from | the C# name grammar reads nothing else; the standards belong with the numbers they cite |
| D16 | The table and its classifier are `checks/coarse_pitch.py` (with the YAML); the check is `checks/thread_pitch.py` | the name grammar needs the table, and a single module holding the check would import `fastener_identity`, which imports `fastener_names`, which would import it back |
| D17 | A package dumped with the `model_check` or `standards` profile says in one skipped row that the hole and fastener phases did not run; screws named by their parts are still checked. *Amended 2026-10-08 in the second review:* the same row is written on a freshly dumped `full` package (no `reused_from`) whose `extractor.phases` row for `hole` or `fastener` is `skipped`, naming the phases that did not run (`contracts/fasteners.md` 8.6) | the arrays are empty by design there (`reviewer/src/swreview/ir/models.py:1750-1761`), and "no thread" would be false. On a `full` package a hole or fastener phase is skipped only behind one that aborted (`extractor/SwReview.Extractor/Dump/PackageWriter.cs:334-370`), and a skipped phase records no gap of its own (the phase log, `:836-874`), so without the row its threads would be neither flagged nor listed and "no ... states a thread" could be false. A failed or aborted phase records its own null-id gap (`:809-825`) and is D20's. A reused package's rows are all `skipped` by design, and reuse refuses a dump that failed or aborted (`reviewer/src/swreview/benchmark/reuse.py` `_aborted_dump_refusals`), so its rows are not read |
| D18 | A hyphen number followed by a pitch marker and a digit (`M4-0.7x12`, `M8-1 x 20`) is the pitch, the rest a length (`contracts/fasteners.md` 8.8, rule 3) | 52A counts a hyphen number as the pitch only when no letter or digit follows it, which keeps `M8-6H`'s tolerance class out; read literally, the `x` of a length is a letter, so `M8-1 x 20` would be a thread with no pitch, which the no-pitch rule passes as coarse - a false pass 50A forbids. Section 1 of `contracts/fasteners.md` already reads the vendor form `m<d>-<p>x<L>` as a pitch and a length, so the two parsers read it alike |

**Defaults added on 2026-10-08 in the documents' review** (before any code; each a default the
owner may revise):

| # | Default | Why |
|---|---|---|
| D19 | After a hyphen number, `LH` or `RH` (any case) is the thread's hand and keeps the number the pitch (`M10-1.25LH` reads 1.25); no pitch is read only for a tolerance class, one digit followed by `e`, `f`, `g` or `h` in either case (`M8-6H`, `M8-6g6h`); any other letter after the number makes the designation unreadable (`M10-1.25G`, `M8-1x`) (`contracts/fasteners.md` 8.8, rule 3) | read literally, 52A's "not followed by a letter" gives `M10-1.25LH` no pitch, which the no-pitch rule passes as coarse - the false coarse 50A forbids - and so would any other letter after a pitch. A tolerance grade is one digit and its position a letter from `e` to `h` (ISO 965-1), so recognising the class itself, rather than "any letter", is the one reading in which no pitch is never reached by accident; everything else is listed, never passed |
| D20 | One skipped row lists the package's `hole` gaps that name no hole row - components the hole phase did not read (lightweight, suppressed, unloaded, no loaded model) and hole-phase steps that failed - and the "nothing at all" row is written only when there is none (`contracts/fasteners.md` 8.6) | the extractor reads holes and cosmetic threads only from resolved components with a loaded model and records a `hole` gap for each other one (`extractor/SwReview.Extractor/Dump/HoleDumper.cs:119-147`); without the row a fine thread on a lightweight component would be neither flagged nor listed, and on a package whose only threads are there "no ... states a thread" would be false. The gap names no component id when it was written for a skipped component (its reason names it), so the row quotes each reason and scopes the ids the gaps carry. A gap about a hole that was read (thread depth, axis) is not about pitch. A part reviewed on its own gives no gap at all (open item 2), which stays T124's. *Amended 2026-10-08 in the second review:* the row covers every gap that names no row of the array its `entity_kind` stands for - `hole` gaps as above, `thread` gaps that name no cosmetic thread (a read that threw, `HoleDumper.cs:180`, null; a `GetDefinition` that returned nothing, `:419-428`, an id no row carries) and `fastener` gaps that name no fastener row (an identification that threw, `FastenerDumper.cs:72`, null; a read that threw after its id was allocated, `:116`) - because each leaves a cosmetic thread or a fastener neither flagged nor listed, exactly as a lightweight component's `hole` gap does; a failed or aborted hole or fastener phase is among them, by its null-id gap (`PackageWriter.cs:809-825`). *Amended 2026-10-08 in the third review:* the row orders its gaps by `entity_kind` (`hole`, `thread`, `fastener`), then `entity_id` with null first, then `reason`, never in the package's order, so it reads the same however the package lists them, as T116's shuffled packages require |
| D21 | A finding that holds a tapped hole or cosmetic thread of an unclear part carries the part-roles note; one that holds fasteners only carries none (`contracts/fasteners.md` 8.2) | the note (`part_roles.NOTE`, "may be a bought part: ...") tells the engineer the answer may withdraw the finding; fasteners are classified whatever their role (52A), so on a fastener's finding it would promise a withdrawal no answer makes |
| D22 | The name grammar's one whole number is a pitch only when it is positive: `M6 x 0` stays `M6` with no length (`contracts/fasteners.md` 8.8; a vector row) | 50A's rule ("at most that diameter's coarse pitch") read literally makes `M6 x 0` a zero pitch, `M6x0`, which `fastener.thread_match` and this check would then judge; both parsers refuse a length that is not positive today (`FastenerNameParserTests.Parse_LengthZeroOrNegative_IsRejected`), and the vector pins the thread too |

**Defaults added on 2026-10-08 in the second review** (after 57A and 58A, before any code; each a
default the owner may revise; D17 and D20 were amended in the same review):

| # | Default | Why |
|---|---|---|
| D23 | The "screw recognised by name" source is the instances `recognise_fasteners` builds in memory for a component with no row in `package.fasteners`, whose `fastener.id` starts with `fst:name:`; `identity_source` never tells the two sources apart, and a fastener row is read once, as a row, whatever its `identity_source` (`contracts/fasteners.md` 8.2) | the extractor writes `name_parse` on every fastener row whose size and length both came from its name (`extractor/SwReview.Extractor/Dump/FastenerDumper.cs:153-155`), and `recognise_fasteners` passes a row's `identity_source` through (`reviewer/src/swreview/checks/fastener_identity.py:296-308`). Told apart by `identity_source`, such a row would be read twice - its sources doubled in its finding and in the checked count - would carry its component id in `inputs` instead of its row id, and would be classified when its component is suppressed, because only the in-memory screws are resolved by construction (`_named_row`, `:224`; built only for a resolved component, `:312`) |
| D24 | Every coverage row of sources counts one per source it lists - a hole row (one feature on one component instance), a cosmetic thread row, a fastener instance - each by its id, so its number is the number of ids it lists; a finding's `{sources}` counts a part's tapped holes by distinct feature name (`contracts/fasteners.md` 8.5, 8.6) | a row spans the package and lists ids, so the count and the list must agree; a finding is about one part, whose feature is what the engineer changes, so a part used twice is one feature there and two hole rows in a row. Section 8.11's fixture figures are hole rows (on those fixtures each tapped-hole feature is on one component instance, so the two counts agree there) |
| D25 | *Replaced the same day, before any code, by the owner's decision 63A (below): the Fasteners goal owns the two finding ids by name and the `thread.pitch` rows belong to no goal, so no goal line moves.* As first written: the Fasteners goal owns `thread.` (D2), so a coarse-pitch pass lifts its goal line to "checked" on a review whose `fasteners` close-out row is out of scope or whose only fastener rows are unresolved rule rows with no close-out row; an unresolved, skipped or failed close-out row still outranks it | it is the review-summary rule for every goal, one passed check reads "checked" (`reviewer/src/swreview/report/finding_groups.py:231-247`; 009 `contracts/review-summary.md` section 3). The third review found what it missed: with no checked row, a `thread.pitch` row bucketed `skipped` - the "nothing at all", bought, pipe, not-read or phases row - is a rule row that turns "not applicable (out of scope)" into "not reached" (`_goal_line`'s rule-row case), so every thread-less or bought-only design would read "Fasteners: not reached". Both moves went to the owner, who chose 63A |

**The owner's later decisions** (2026-10-08, on three questions the documents' reviews raised;
recorded before their code):

- **57A, one finding per check and part.** The question: grouped per designation as D3 first had
  it, two fine designations of one part share a verdict key - the check, the component ids, the
  drawing places and the configuration (`reviewer/src/swreview/agent/runner.py:802-823`) - so the
  part-roles restate (D10) folds both onto one id and withdraws the other. A probe on 2026-10-08
  (scratch code over `4818c62`, not committed) recorded two `thread.fine_pitch` findings, `M6x0.75` and
  `M8x1`, on the custom plate of `reviewer/tests/support/roles_review.py` and answered "All
  bought": the plate stayed custom, yet one id was withdrawn as "bought part (your answer to
  ER-001)" and the other kept the `M8x1` words, so `M6x0.75` left the review. The owner chose one
  finding per (check, owning part): it lists each fine (or non-standard) designation with its
  sources (entity ids) and its coarse alternative; `observed` is the designations' clauses joined
  by "; ", then "in {part}"; the recommended action names every designation and its coarse
  alternative ("Confirm M8x1 and M6x0.75 are intended in {part}, or change them to the coarse
  M8x1.25 and M6x1."); a fastener keeps its own document, the fastener's file, as its part (D11).
  It supersedes D3's grouping and words (`contracts/fasteners.md` 8.5 and 8.7, FR-030, T116, T118
  and T119); the restate (D10) and its withdraw-before-record rows (D14) stand.
- **58A, a restated finding keeps its disposition.** The owner's words: "Fix on this branch
  (Recommended): own test-first commit: a restated finding keeps the earlier finding
  disposition". Found in the same review: `_reconcile_restated` puts the restated finding in the
  earlier one's place under the earlier id (`reviewer/src/swreview/agent/runner.py:1295`,
  `finding.model_copy(update={"id": ...})`), and the restated finding carries no disposition, so
  an Accept, a Reject or a Defer the engineer recorded before answering the part-roles question is
  lost when the answer restates the check - in the session and in the re-announced `finding`
  event, whose body is the whole finding. It predates this amendment (feature 013) and reaches
  every restated check; it matters here because 51A makes Accept the one way to confirm a fine
  thread, and the answer restates `check_threads` (D10). Fixed on this branch in its own
  test-first commit before FP1 (group FPR, tasks T125 and T126): the restated finding keeps the
  earlier finding's disposition; a finding the restate withdraws is withdrawn as before.
  `_reconcile_reruns` (rule 3, `runner.py:826-857`), which folds a check the model itself runs
  again in the resumed turn, copies the same way; it is not a restate, so 58A leaves it as it is,
  recorded here for the owner.
- **63A, the goal lines stay as they are.** The question (the third review, D25): with the
  Fasteners goal owning `thread.`, the `thread.pitch` rows reach its goal line - a coarse pass
  lifts it to "checked", and with none a skipped row turns "not applicable (out of scope)" into
  "not reached" on every thread-less or bought-only design. The owner's words: "Keep goal lines as
  is: fine-pitch findings land in Decide under Fasteners; pass/skip/unreadable rows show in
  coverage but do not change the Fasteners line, so no existing review reads differently". So the
  Fasteners goal of `review_words_v1.yaml` owns `thread.fine_pitch` and `thread.nonstandard_pitch`
  by name, in its `items` (`goal_of` takes a goal's `items` before any prefix,
  `reviewer/src/swreview/report/finding_groups.py:167-180`), never the prefix `thread.`; the
  coverage-only `thread.pitch` belongs to no goal, as the part-roles rows already do
  (`reviewer/tests/unit/test_report_bought_parts.py:216-217`,
  `reviewer/tests/unit/test_prerun_digest.py:710-715`), and `goal_lines` passes over a row no goal
  owns (`finding_groups.py:199-203`). Neither finding id is ever a coverage row's check, so
  neither is read as a close-out row. A probe on 2026-10-08 (scratch, over `4818c62`, the two ids
  added to the Fasteners `items` in memory) gave the Fasteners line "not applicable (out of
  scope)" for a `fasteners` close-out row out of scope beside the "nothing at all" row, beside a
  bought row and beside a coarse checked row, and "not reached (evidence missing)" for unresolved
  `fastener.` rule rows beside a checked row - each the line of the same session without the
  `thread.pitch` row - and "issues found" with a `thread.fine_pitch` finding. What moves:
  `test_review_words.py`'s goal table, and its test that every id the policy classes starts with
  a goal's prefix, which fails once the two ids are classed and is edited to `goal_of`'s own rule,
  items first (T119). It replaces D25 (`contracts/fasteners.md` 8.4, FR-030, FR-031, T119,
  T120); 63B and 63C were rejected (the table below).

**Why**: VERIFIED on 2026-10-08 at `4818c62`; behaviour was run, not read.

- **Nothing classifies a pitch today.** No coarse-pitch, UNC or pipe-thread table exists in the
  repository; `ThreadSpec` carries a series (`metric` or `unified`), a diameter and a pitch and
  nothing else (`reviewer/src/swreview/checks/fastener.py:110,124-136`).
- **The parser misreads the spellings 52A names** (`parse_thread`, `fastener.py:157-204`, its
  metric pattern `:113`; run on 2026-10-08): `M8x1,25` reads pitch 1.0 (a false fine flag);
  `M8-1.25`, `M10-1.5-6H`, `M8×1`, `M4-0.7x12` and `M8-1 x 20` read no pitch (a false coarse
  under the no-pitch rule);
  `M16xPh3P1.5` reads M16 with no pitch; `1/8-27 NPT` reads as a unified 3.175 mm thread of
  0.940741 mm pitch, which against #5's UNC 40 would be judged non-standard; `3/8`, `1-8`, `1-1/8-7`, `10-32`,
  `G1/4` and `MF8x1` are not read; `M10x35` reads pitch 35; `1.000-8` and `1.125-8` read, so the
  table's rows above 7/8 in are reachable through the decimal form; `2.000-4.5` is not read (the
  pattern takes whole threads per inch only).
- **The name grammar loses the common fine pitches** (`reviewer/src/swreview/checks/fastener_names.py:227-231`;
  `extractor/SwReview.Extractor/Fasteners/FastenerNameParser.cs:396-406`; run on 2026-10-08):
  `M8x1`, `M10x1`, `M20x2` and `M6x1` read as M8, M10, M20 and M6 with lengths of 1, 1, 2 and 1
  mm. The `M10x35` row of `contracts/fastener-name-vectors.json` pins the rule; both parsers read
  every row (`reviewer/tests/unit/test_fastener_names.py:32`;
  `extractor/SwReview.Extractor.Tests/FastenerNameVectors.cs`, the file copied by a `Content` item
  of `SwReview.Extractor.Tests.csproj`).
- **Where threads enter.** A tapped hole's `thread_designation` is the Hole Wizard `FastenerSize`
  verbatim, null for the other hole types (`extractor/SwReview.Extractor/Dump/HoleDumper.cs:288,293`);
  a cosmetic thread's `designation` is its `ThreadCallout`, else its `Size`, else ""
  (`HoleDumper.cs:433-435`), it has no feature name (`reviewer/src/swreview/ir/models.py:688-699`),
  and it is always recorded internal (`HoleDumper.cs:454`); a fastener row's designation is a
  `Size`-style configuration property verbatim, else the C# name parse
  (`extractor/SwReview.Extractor/Dump/FastenerDumper.cs:151`), and its `identity_source` is
  `name_parse` whenever neither its size nor its length came from a property (`:153-155`);
  `recognise_fasteners` returns every row whatever its kind, with the `identity_source` the row
  carries, and builds in memory the name-parsed screws, bolts and pins of resolved components with
  no row, one per instance, each with the id `fst:name:{component id}`
  (`reviewer/src/swreview/checks/fastener_identity.py:224,279-327`; D23).
- **The committed fixtures state no fine thread** (counted 2026-10-08): the replay big-assembly has
  12 tapped holes - 11 coarse, M2x0.4 to M10x1.5, and one `3/8`, the Hole Wizard pipe tap - no
  cosmetic thread, no fastener row and no screw recognised by name, and 1,153 feature rows, in
  which every tapped hole's feature is found in its component's referenced configuration and reads
  not suppressed; the replay small assemblies one M5x0.8 tapped hole each, likewise joined and not
  suppressed; the mechanical big assembly 12 coarse tapped holes and 68 coarse screws by name, and
  no feature rows; the mechanical small assembly one M5x0.8. Their `hole` gaps that name no hole
  row (D20): three on the replay big assembly (two lightweight components, one suppressed), two on
  the replay small-assembly-b (two lightweight components), one on the mechanical big assembly
  (`cmp:0010`, "no Hole Wizard feature of this component could be read"), none on the other two;
  none has a `thread` or `fastener` gap that names no row, and every one is a freshly dumped
  `full` package whose `hole` and `fastener` phases are `ok` (D17). Each tapped-hole feature is on
  one component instance, so their hole rows and their features count alike (D24). So the check
  records no finding on any of them (SC-010), and the replay's added findings ("62, 7 and 5", 008
  `contracts/replay.md` section 9) do not move.
- **The pre-run hook and the cap.** `CODE_FIRST_CHECKS` is the one hook
  (`reviewer/src/swreview/tools/checks_mechanical.py:76`); `repeat_key` keys every name in it
  `(tool,)` (`reviewer/src/swreview/prerun.py:1413-1419`); a description is capped at 160
  characters (`reviewer/src/swreview/agent/providers/schema.py:100`). The proposed first paragraph is
  123.
- **Why `thread.` and not `fastener.`.** The checklist closes an item on any finding whose check
  starts with the item's prefix (`reviewer/src/swreview/agent/checklist.py:68-76`), and the
  `fasteners` item's prefix is `fastener.` (`reviewer/src/swreview/agent/checklist_v1.yaml:33-35`),
  so a `fastener.` pitch id would close "Fastener joints" on a run where no joint was checked. The
  needs-judgement prefixes are `interference.`, `fit.`, `fastener.`, `hole.`
  (`reviewer/src/swreview/report/attention_policy_v1.yaml:28-32`, pinned at
  `reviewer/tests/unit/test_attention_policy_file.py:74-75`); the Fasteners goal owns `fastener.`
  (`reviewer/src/swreview/report/review_words_v1.yaml:137-141`, pinned at
  `reviewer/tests/unit/test_review_words.py:250`); `goal_of` takes exact items, then the longest
  prefix (`reviewer/src/swreview/report/finding_groups.py:167-180`), so a `thread.` id no goal
  names would fall to "Other checks" and fail `test_every_classified_check_lands_in_one_of_the_seven_groups`.
- **How the custom-parts-only checks read the roles.** `PartRoles.graded` grades an unknown id and
  every document but a bought non-root one (`reviewer/src/swreview/checks/part_roles.py:294-298`);
  hygiene grades `roles is None or roles.graded(document_id)` (`reviewer/src/swreview/checks/hygiene.py:312-315`)
  and notes an unclear document's findings while the question is open (`:318-327`,
  `part_roles.note_unclear`); `review_roles` is `None` when no roles are attached
  (`reviewer/src/swreview/tools/checks_mechanical.py:185-189`).
- **Suppression.** `Hole` has no suppression flag (`reviewer/src/swreview/ir/models.py:651-685`);
  `Feature` carries `document_id`, `configuration` (the active one it was read in) and
  `suppressed`, null when unreadable (`:485-514`); `HoleDumper` never asks whether a feature is
  suppressed (`HoleDumper.cs:163-186`).
- **The pins a new id moves.** `test_attention_catalogue.py:121-127` (13 numeric, 8 rule and 73
  emittable ids) and `:166-179` (the judgement families are the numeric checks except the axial
  stack). A table lookup records no calculation, so its passes are a count (R2.21), and a document
  finding is a `DocumentResult` (`reviewer/src/swreview/checks/result.py:71-88`).
- **Principle I and `M8`.** The constitution forbids inferring a favourable value
  (`.specify/memory/constitution.md:62`). Reading `M8` as coarse is not an inference about this
  part: it is the standard's designation rule, which the owner chose to apply (50A) over listing
  every such thread as unknown (50B), and the checked row states it.

**The two tables as transcribed on 2026-10-08** from ISO 261 and ASME B1.1. This is the record of
that transcription, kept for the owner to check against the shop's copies of the two standards
before relying on it; it is not maintained. `contracts/coarse-pitch.json` supersedes it: the
contract file is the one source the check reads (through its two pinned copies), and a correction
is an edit of that file and its two copies, never of these tables, which then record what was first
transcribed.

ISO 261, coarse pitch (mm) by nominal diameter:

| Size | Pitch | Size | Pitch | Size | Pitch | Size | Pitch |
|---|---|---|---|---|---|---|---|
| M1 | 0.25 | M3 | 0.5 | M10 | 1.5 | M27 | 3 |
| M1.1 | 0.25 | M3.5 | 0.6 | M11 | 1.5 | M30 | 3.5 |
| M1.2 | 0.25 | M4 | 0.7 | M12 | 1.75 | M33 | 3.5 |
| M1.4 | 0.3 | M4.5 | 0.75 | M14 | 2 | M36 | 4 |
| M1.6 | 0.35 | M5 | 0.8 | M16 | 2 | M39 | 4 |
| M1.8 | 0.35 | M6 | 1 | M18 | 2.5 | M42 | 4.5 |
| M2 | 0.4 | M7 | 1 | M20 | 2.5 | M45 | 4.5 |
| M2.2 | 0.45 | M8 | 1.25 | M22 | 2.5 | M48 | 5 |
| M2.5 | 0.45 | M9 | 1.25 | M24 | 3 | M52 | 5 |
| | | | | | | M56 | 5.5 |
| | | | | | | M60 | 5.5 |
| | | | | | | M64 | 6 |
| | | | | | | M68 | 6 |

ISO 261 diameters to 68 mm with fine pitches only (no coarse pitch): M5.5, M15, M17, M25, M26,
M28, M32, M35, M38, M40, M50, M55, M58, M62, M65. Any other metric diameter is an unknown size.

ASME B1.1, UNC threads per inch (the diameter in inches; `#N` is 0.060 + 0.013 N):

| Size | Diameter | UNC | Size | Diameter | UNC |
|---|---|---|---|---|---|
| #1 | 0.073 | 64 | 1/2 | 0.5 | 13 |
| #2 | 0.086 | 56 | 9/16 | 0.5625 | 12 |
| #3 | 0.099 | 48 | 5/8 | 0.625 | 11 |
| #4 | 0.112 | 40 | 3/4 | 0.75 | 10 |
| #5 | 0.125 | 40 | 7/8 | 0.875 | 9 |
| #6 | 0.138 | 32 | 1 | 1 | 8 |
| #8 | 0.164 | 32 | 1-1/8 | 1.125 | 7 |
| #10 | 0.19 | 24 | 1-1/4 | 1.25 | 7 |
| #12 | 0.216 | 24 | 1-3/8 | 1.375 | 6 |
| 1/4 | 0.25 | 20 | 1-1/2 | 1.5 | 6 |
| 5/16 | 0.3125 | 18 | 1-3/4 | 1.75 | 5 |
| 3/8 | 0.375 | 16 | 2 | 2 | 4.5 |
| 7/16 | 0.4375 | 14 | | | |

`#0` (0.060 in) has no UNC thread: a fine-only size, flagged like M25. Any other unified diameter
is an unknown size.

**What this moves**, each a deliberate edit in the task that lands it, never a loosened
assertion: nothing committed through the parser fixes, which reach every caller of
`parse_thread` - `fastener.thread_match`, the identity shank band, the head table's key, the name
grammar - because no fixture spells a thread those ways (T111's acceptance holds the fastener
tests and goldens unchanged), while the new `fastener.thread_match` outcomes for those spellings
are pinned by T110's joint vectors (`contracts/fasteners.md` 8.9); the shared name vectors (T114); the tool-array pins of `test_tool_payload.py`,
regenerated by its `--write`, and the tool lists of `test_docstring_split.py`,
`test_tool_notes_prompt.py`, `test_provider_schema.py` (with 001's `contracts/agent-tools.md`),
`test_tool_tiers.py` and `test_model_view.py`; the pre-run order of `test_tools_check_joints.py`,
`test_joint_map_acceptance.py`, `test_prerun_digest.py`, `tests/support/prerun.py` and
`test_withheld_prerun_tools.py`; `WITHHELD_ON_THE_FIXTURES` in `test_replay_fixtures.py`; the
attention catalogue's counts and judgement families, `test_attention_policy_file.py`'s prefixes,
`test_review_words.py`'s goal table and its classed-check routing test (63A), and `test_coverage_withdrawn.py`'s set of code-first checks
whose second call withdraws (D14) (T119); the golden tree's allowed new paths in
`test_ir_golden_fixtures_load.py` (T118); and the requested figures of 008
`contracts/replay.md` section 9 (T121). The recorded totals of the replay do not move: no recorded
tool's result, the prompt or the checklist changes.

**Merging with the 014 branch** (noted for the owner, who merges): `[014] 247797f` changed
`checks/fastener.py`'s result `inputs` beside `_thread_match`, and 014 regenerated the replay and
pane fixtures; T111 touches `parse_thread` only, and generated figures are re-measured after a
merge, never hand-merged.

**Open at the seat** (tasks T123 and T124, SC-012):

1. What Hole Wizard writes for an ISO fine tapped hole, a UNF tapped hole and a cosmetic thread
   callout has never been seen: no recording holds one, and only coarse metric strings and the bare
   `3/8` pipe tap are on record. The seat dumps each and the check must flag each.
2. Whether a part reviewed on its own yields any hole rows: `HoleDumper.cs:133-136` skips, with no
   gap, every scope node whose handle is not an `IComponent2` (and `FastenerDumper.cs:87` the same),
   and a part root's handle is its `IModelDoc2` (`extractor/SwReview.Extractor/Dump/ComponentTreeDumper.cs:315`),
   so a part review may carry no tapped hole and no cosmetic thread at all. Read from the code only;
   the seat confirms it, and until then a part review's thread check covers only what it was given.

**Known limits, recorded rather than fixed** (2026-10-08, in the documents' review):

- **Pipe series outside 50A's token list** (`NPSF`, `NPSI`, `NPSC`, `NPSL`, `NPSH`, `ANPT` and
  others) are not recognised by `is_pipe_thread`, so `1/8-27 NPSF` reads as a unified thread and is
  judged as one. It is flagged, never passed: up to 2 in no pipe size has its own size's UNC threads
  per inch (pipe threads are 27, 18, 14 and 11.5 per inch there, UNC at 1/8 (#5), 1/4, 3/8, 1/2, 3/4
  and 1 in is 40, 20, 16, 13, 10 and 8), `1-11.5` and the other decimal threads per inch are
  unreadable, and `1/16` is a size in no table. The owner may add the tokens; it is one edit of the
  one list beside `parse_thread`, with its vectors.
- **A part reviewed on its own** may give no hole row and no gap (open item 2 above, T124), so the
  "nothing at all" row cannot yet tell such a part from one with no thread.
- **A tolerance class written after a space** joins the pitch: `parse_thread` removes all
  whitespace before reading (`reviewer/src/swreview/checks/fastener.py:164`), which is how it
  reads `M8 x 1.25`, so `M8x1.25 6H` reads pitch 1.256 and is flagged non-standard, and
  `M8-1.25 6g` reads `M8-1.256G` and is unreadable (both run on 2026-10-08; vectors of
  `contracts/fasteners.md` 8.9). A false flag or a listing, never a false pass; reading a space as
  a separator is a parser change 52A did not ask for, left to the owner.

**The sitting documents** (a decision of the orchestrating session on 2026-10-08, not the owner's;
the owner may revise it). The open-seat guards hold the current handover and test plan to every
open `[W]` task of feature 010 (`reviewer/tests/unit/test_workstation_handover.py:39-48`,
`reviewer/tests/unit/test_workstation_test_plan.py:727-757`, through `tests/support/seat_tasks.py`),
so T123 and T124 fail them until the documents say where they go. Option 1 was taken: the
documents commit makes exactly two small edits outside this feature's folder - one row of the
"Not in this sitting" table of `docs/test-plan-2026-09-27/workstation-test-plan.md` setting
010 T123 and T124 aside for the next sitting plan, and one sentence in section 4 of
`docs/test-plan-2026-09-27/workstation-handover.md` naming them. Rejected: writing them as steps
and results rows of the 2026-09-27 plan (a sitting written and partly run, which the next sitting
plan replaces), and leaving them without the `[W]` tag (seat work the guards would no longer see).

**Alternatives rejected** (the owner's other options, as offered on 2026-10-08, and the ones this
entry considered):

| Option | Why not |
|---|---|
| 50B, "M8 = pitch unknown": the same table, but a thread with no pitch stated listed as "pitch unknown" rather than coarse | strict, but every Toolbox `M6 x 20` screw would land there, burying the real gaps; the owner chose the ISO naming rule, stated on the result (50A) |
| 50C, metric only: leave inch threads alone (`#10-32` not flagged) | the owner's "anywhere"; a UNF thread is the same mistake in inch |
| 51B, a profile allow-list: a standards-profile list of pre-approved fine threads | a profile version 5 section, every profile file and the replay fixtures regenerated; kept as a recorded alternative (hydraulic ports and locknuts would use it) |
| 51C, acceptance persists: an accepted fine thread stays accepted on later reviews, bound to the part or feature through the exceptions store | the fastener checks never read `exceptions.json` today, and a binding for a thread needs its own fingerprint; kept as a recorded alternative |
| 52B, rows only, no parser fix: holes, cosmetic threads and fastener rows, the parsers untouched | `M8x1`-style names would be missed, and `M8x1,25` would stay a false fine flag |
| 52C, 52A plus drawing callouts | what a native tapped-hole callout holds has not been checked on a licensed seat (011 probe D7, task T065), and the PDF grammar reads no unified thread; drawings are named as not read instead |
| 53B, a new feature 015, the full speckit cycle before code | the check is one rule of User Story 4's thread checks, and the amendment pattern (`833d23e`) records it before its code at a fraction of the paperwork |
| 53C, on the 014 branch, after its slice 4 | no merge clash, but a product change would ride with the evaluation's branch |
| A `fastener.` id | it would close the "Fastener joints" checklist item by prefix on a run that checked no joint |
| Inside `check_joints` or `check_hygiene` | `check_joints` is about placed joints and a fine thread needs none; hygiene closes its own checklist item and sorts as hygiene, last, where a judgement belongs in Decide |
| A question to the engineer per thread (`QuestionSpec`) | the Accept disposition already records the engineer's confirmation on the finding; a question would block nothing and be asked again every review |
| A finding per hole, cosmetic thread or fastener instance | a part used forty times would be forty findings for one choice (D3, 57A) |
| A finding per part and designation (D3 as first written) | two designations of one part share a verdict key, so the part-roles restate kept one and withdrew the other although the part stayed custom; superseded by the owner's decision 57A |
| Leaving the restate fold as it is (an earlier finding's disposition dropped) | an Accept recorded before the part-roles answer would be lost when the answer restates the check, and Accept is how the engineer confirms a fine thread (51A); fixed by the owner's decision 58A |
| 63B, a goal of its own, "Thread pitch", in the Fasteners group | one more line on every Review summary, "not applicable" or "not reached" on most designs, and `test_review_words.py`'s goal table and every summary pin that counts goals move; the owner chose that no existing review reads differently (63A) |
| 63C, the rows feed the Fasteners goal line (the prefix `thread.`, D25 as first written) | a coarse pass lifts the line to "checked", and with none a skipped row turns "not applicable (out of scope)" into "not reached", so the line moves on designs with threads and on designs without; the owner chose 63A |

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
| The **Amended** line, US4 acceptance scenarios 5 to 7, the thread pitch edge cases, FR-029 to FR-034, the coarse-pitch table entity, SC-009 to SC-012 and two assumptions (2026-10-08) | no thread pitch rule; one whole number after a metric size always a length | the owner's decisions 50A to 53A, 57A, 58A and 63A, and the defaults D1 to D25 | R2.26 |

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
| The coarse-pitch table checked against the shop's copies of ISO 261 and ASME B1.1 (R2.26, added 2026-10-08) | owner | nothing; it ships as transcribed, and a correction is one edit of `contracts/coarse-pitch.json` and its two pinned copies |
| The defaults D1 to D25 of R2.26 (2026-10-08), except D3 and D25, which the owner's decisions 57A and 63A replaced | owner | nothing; each ships as written until revised |
| Whether a check the model runs again in a resumed turn (`_reconcile_reruns`, rule 3) should keep an earlier finding's disposition as a restate does after 58A (R2.26, 2026-10-08) | owner | nothing; 58A fixes the restate only |
| What Hole Wizard writes for an ISO fine tapped hole, a UNF tapped hole and a cosmetic thread callout, and whether a part reviewed on its own yields any hole rows (R2.26, T123, T124) | next sitting | SC-012 |

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
