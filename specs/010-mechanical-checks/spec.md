# Feature Specification: Automatic Mechanical Checks

**Feature Branch**: `010-mechanical-checks`

**Created**: 2026-09-23

**Status**: Draft

**Input**: Owner goal list of 2026-09-22: "Static interference; Fastener thread engagement; Hole alignment (potentially automate the tolerance stackup here too); Tool access above screw heads; Mass/material for all geometry; Hygiene checks (part numbers, etc); TOLERANCES?" Evidence: the check-by-check analysis of the recorded 830-02342 and 810-11249 reviews summarised in `docs/roadmap-2026-09-22.md`. Owner decisions: tolerances from all four sources - Hole Wizard fits and classes, model dimension tolerances and DimXpert/MBD annotations, drawing callouts, and a general tolerance block (2026-09-22); size-for-size contacts as a separate list, not findings; minimum thread engagement 1.5 x diameter into both steel and aluminium (both 2026-09-23).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every Detected Interference Is Judged, and Contacts Are Not Clashes (Priority: P1)

An engineer reviews an assembly with SOLIDWORKS attached. Every interference group the detection finds is judged, not the handful a model happened to pick. Real overlaps are findings with their volume. Size-for-size contacts - a 3.0 mm dowel in a 3.0 mm hole, coincident faces - are listed separately as contacts, naming the two parts, and never outrank a real overlap.

**Why this priority**: the recorded big-assembly review judged 6 of 113 detected groups, and four of the ten "Start here" slots across the two evening runs were zero-volume contacts reported as interference.

**Independent Test**: judge the interference rows of a fixture shaped like the 830-02342 detection (113 groups, some zero volume): every group has an outcome; zero-volume rows appear in the contact list and in no finding; positive-volume rows are findings with their volume.

**Acceptance Scenarios**:

1. **Given** detected interference rows, **When** the checks run, **Then** every group is judged and counted by outcome.
2. **Given** a row with zero volume or only a possible-interference flag, **When** it is judged, **Then** it is recorded as a contact naming both parts and is not a finding.
3. **Given** a row with a positive volume, **When** it is judged, **Then** it is a finding carrying the volume and both parts, exactly as today.

---

### User Story 2 - The Assembly's Joints Are Found by Code (Priority: P1)

Code finds the joints the assembly is built from, from the geometry alone: a screw in a tapped hole, a dowel in a pair of holes, a bolt through two clearance holes, a counterbored or countersunk hole over a tapped one. Each joint names its parts, its holes, its axis and its kind. The joint map is what the alignment, fastener and tool-access checks run on, so none of them waits for a model to choose a pair.

**Why this priority**: the model checked unrelated hole pairs for alignment while five real candidates existed, and fastener checks never ran. Every later story depends on knowing which holes and parts go together.

**Independent Test**: build the joint map of a fixture shaped like 830-02342: it holds the five near-coaxial cross-part pairs the analysis found, each classified, and none of the three unrelated pairs the recorded review checked.

**Acceptance Scenarios**:

1. **Given** holes on different parts whose axes are parallel within the configured angle and whose projections overlap, **When** the joint map is built, **Then** they form one joint classified by the hole kinds (screw, pin, through-bolt, counterbore or countersink over tapped).
2. **Given** a cylinder on a part that sits coaxially in a hole of another part, **When** the joint map is built, **Then** a pin or screw joint is formed with that part.
3. **Given** a hole with no extracted diameter but with cylinder faces, **When** the joint map is built, **Then** its size is taken from the faces and marked derived.
4. **Given** a pair that fails the adjacency or overlap test, **When** the joint map is built, **Then** it is not a joint, and pairs near the threshold are listed as candidates for the engineer rather than findings.

---

### User Story 3 - Holes Line Up, and the Stack-Up Is Computed (Priority: P2)

For every joint, the check compares how far the two axes are apart with the clearance the joint allows: half the difference between the hole and the fastener or pin. A misalignment beyond that is demonstrated. The allowed position budget is reported as the callout the drawing should carry. When tolerances are known - from Hole Wizard, the model, a drawing, or the general tolerance block - the worst-case stack-up along the joint is computed and judged. When they are not known, the stack-up is unresolved and says which tolerance is missing.

**Why this priority**: alignment is the owner's third goal and the stack-up the question the owner asked about; both are arithmetic code can do once it knows the joints and the tolerances.

**Independent Test**: on the fixture, the 3.0/3.1 mm dowel pair with a 0.75 mm offset is demonstrated misaligned; a pair within its clearance passes with its budget reported; a joint with no tolerance source leaves the stack-up unresolved naming the missing tolerance; a joint with Hole Wizard or general tolerances produces a worst-case figure.

**Acceptance Scenarios**:

1. **Given** a joint, **When** alignment is checked, **Then** the axis offset is compared with half the hole-to-fastener clearance, and an offset beyond it is demonstrated with both numbers.
2. **Given** a position or coaxiality tolerance that is a diameter zone, **When** it is compared, **Then** the permitted radial offset is half the zone value (the current check's error of comparing the offset with the full value is corrected).
3. **Given** tolerances for every contributor, **When** the stack-up is computed, **Then** the worst case is reported and judged against the joint's clearance, citing each tolerance's source.
4. **Given** a contributor with no tolerance from any source, **When** the stack-up is computed, **Then** it is unresolved, names the contributor and the sources searched, and no value is assumed.

---

### User Story 4 - Fasteners Are Recognised and Their Threads Checked (Priority: P2)

Screws are recognised whether or not they came from Toolbox: from the part's file name and description ("SHC M4-0.7 X 12"), cross-checked against the measured shank. For every screw joint, the check compares the screw's thread with the tapped hole's, computes how much thread is engaged and whether the screw bottoms, from the placed geometry, and judges engagement against the rule: at least 1.5 times the nominal diameter, into steel and aluminium alike.

**Why this priority**: the recorded big-assembly review cost 12.4M tokens and missed an M4 screw in an M5 tapped hole, because 68 screws were not recognised as fasteners.

**Independent Test**: on the fixture, the 68 screws named in the vendor pattern are recognised; the M4 screw in the M5 tapped hole is a demonstrated thread mismatch; the M10 screw with about 10.2 mm engaged is demonstrated short against the 15 mm the 1.5 x d rule requires; the M3 screw engaging about 1.7 mm is demonstrated short; a screw whose parsed size disagrees with its measured shank is suspected, not recognised silently.

**Acceptance Scenarios**:

1. **Given** a part whose name or description carries a fastener kind and size, **When** fasteners are identified, **Then** it is a fastener with the parsed size, length and pitch, marked as recognised by name, and cross-checked against its measured cylinder.
2. **Given** a screw joint, **When** thread match is checked, **Then** a screw size or pitch that differs from the tapped hole's is demonstrated.
3. **Given** a screw joint with extracted geometry, **When** engagement is checked, **Then** the engaged length is computed from the placed screw and the tapped length, compared with 1.5 x the nominal diameter whatever the tapped material, and a shortfall is demonstrated with both numbers and the rule cited.
4. **Given** a joint whose geometry cannot give the engaged length (an oblique axis, a missing face), **When** engagement is checked, **Then** it is unresolved with the reason; hole depth is never taken as thread depth.

---

### User Story 5 - A Tool Can Reach Every Screw Head (Priority: P3)

For every screw joint, the check knows where the head is and which way it faces from the joint map, picks the tool the head needs (hex key for socket and button heads, socket for hex heads), and sweeps that tool's envelope from the head outward against every other body. A blocked head is a finding naming what blocks it. A counterbore or countersink is checked against the head it must receive.

**Why this priority**: tool access is on the owner's list and today is a measurement nothing calls; the head clearance of every fastener check is always unresolved.

**Independent Test**: on a fixture with one screw head under an overhanging part and one clear, the covered head is a finding naming the blocking part and the clear head passes; a counterbore smaller than its head's diameter is demonstrated.

**Acceptance Scenarios**:

1. **Given** a screw joint, **When** tool access is checked, **Then** the tool is chosen from the head type, its envelope is swept from the head plane outward, and any body intersecting it is named in a finding.
2. **Given** a counterbored or countersunk hole in a screw joint, **When** head fit is checked, **Then** its diameter and depth are compared with the head dimensions from a standard head table.
3. **Given** a head whose type or dimensions are unknown, **When** tool access is checked, **Then** it is unresolved with the reason.

---

### User Story 6 - Every Part Has a Believable Mass and a Material (Priority: P3)

For every part and assembly, the checks confirm a material is assigned or a mass is deliberately overridden, that the density implied by mass and volume fits the named material, that an assembly's mass override is flagged for the engineer, and that bodies the extract could not read are counted rather than forgotten.

**Why this priority**: mass and material for all geometry is on the owner's list; today the override read fails on every part, and no check covers assemblies or density.

**Independent Test**: on the fixture, a part with a named aluminium material and a density near 2700 kg/m3 passes; a part at 1000 kg/m3 (the no-material default) is flagged; the 2.000 kg sub-assembly with unopened parts is flagged as a likely mass override; an unread part is counted in coverage.

**Acceptance Scenarios**:

1. **Given** a part, **When** mass and material are checked, **Then** it passes with a material or a deliberate override, and fails with neither.
2. **Given** a part with a material and a volume, **When** density is checked, **Then** a density outside the named material's range, or at the no-material default, is a finding.
3. **Given** an assembly, **When** mass is checked, **Then** a mass override is reported for the engineer to confirm.
4. **Given** the extractor reads the mass override, **When** it runs on a seat, **Then** the override is recorded for every document (the current read fails on every document and must be fixed).

---

### User Story 7 - The House Rules Are Checked (Priority: P4)

Beyond the release standards, the checks confirm the part-number property matches the file name, that no two different documents share a description or a part number, that every model carries a revision, and that suppressed or lightweight components in the reviewed configuration are reported as findings, not only as coverage.

**Why this priority**: hygiene is on the owner's list, the data is already extracted, and each finding is readable by a non-developer.

**Independent Test**: on the fixture, a document whose part-number property differs from its file name is a finding; two documents sharing a description are one finding naming both; a model missing a revision is a finding; a lightweight component is a finding naming it.

**Acceptance Scenarios**:

1. **Given** a document with a part-number property, **When** hygiene is checked, **Then** a value that differs from the file name's stem is a finding.
2. **Given** two different documents with the same description or part number, **When** hygiene is checked, **Then** one finding names both.
3. **Given** the standards profile's part-number pattern matches no document at all, **When** the data card is checked, **Then** it reports a likely profile error rather than skipping every document.

---

### User Story 8 - Tolerances Are Read Wherever the Team Puts Them (Priority: P2)

The extraction reads tolerances from every place the owner named: Hole Wizard fit and thread classes and its drill, counterbore and countersink sizes; tolerances on model feature dimensions, and DimXpert or MBD annotations when present; drawing callouts (from feature 011's drawing extraction); and the general tolerance block, configured in the standards profile or read from a drawing note, applied only to dimensions without their own tolerance. Every tolerance used cites where it came from. A dimension with no tolerance from any source stays untoleranced.

**Why this priority**: fits, stacks and alignment were unresolved in every recorded review because the extraction carries no tolerance from the model at all.

**Independent Test**: a fixture package with Hole Wizard fit classes, dimension tolerances and a general tolerance setting produces tolerances for the joints' contributors, each citing its source; a dimension outside every source stays untoleranced and the stack-up that needs it is unresolved.

**Acceptance Scenarios**:

1. **Given** a Hole Wizard hole, **When** it is extracted, **Then** its fit class, thread class and drill, counterbore and countersink sizes are recorded.
2. **Given** a model dimension with a tolerance, **When** it is extracted, **Then** the tolerance type and limits are recorded with a reference to the dimension.
3. **Given** a general tolerance block in the profile, **When** a dimension has no tolerance of its own, **Then** the general tolerance applies and is cited as general.
4. **Given** no source, **When** a check needs a tolerance, **Then** the check is unresolved; no tolerance is inferred.

---

### Edge Cases

- **Thread modelled as a cylinder.** A screw overlapping its tapped hole's minor diameter is a contact of the thread model, linked to the screw joint, not an interference finding.
- **Patterned joints.** A pattern of identical joints is judged per joint and reported as one grouped finding with its count.
- **Mixed units.** Metric and inch fasteners and holes are compared in one unit, with the conversion cited.
- **Oblique axes.** Engagement and alignment on axes not aligned with the model axes use the placed geometry or stay unresolved; bounding-box projections are not used on oblique axes.
- **Lightweight parts.** A joint whose part was not read is unresolved and counted, never assumed clear.
- **Parser disagreement.** A name-parsed fastener whose measured shank disagrees by more than the thread's tolerance is suspected, and its engagement is unresolved.
- **General tolerance and explicit tolerance.** An explicit tolerance always wins; the general block never overrides it.
- **Profile without a general tolerance.** The general tolerance source is simply absent; nothing defaults to a standard class.
- **Every new check runs first.** Each check here takes no model-chosen arguments, so it runs in feature 008's code-first pass and costs no model rounds.

## Requirements *(mandatory)*

### Functional Requirements

**Interference**

- **FR-001**: Every detected interference group MUST be judged, and the outcome counts reported.
- **FR-002**: A row with zero volume, or only a possible-interference flag, MUST be recorded as a contact naming both parts, in a contact list separate from findings (owner decision 2026-09-23).
- **FR-003**: A row with a positive volume MUST remain a finding with its volume and parts.

**Joints**

- **FR-004**: The product MUST build a joint map from the extracted geometry: cross-part hole-to-hole and cylinder-to-hole pairs that are parallel within a configured angle, overlap in projection and are axially adjacent, each classified by kind (screw, pin, through-bolt, counterbore or countersink over tapped).
- **FR-005**: A hole's size MUST be taken from its cylinder faces when the feature data lacks it, marked derived.
- **FR-006**: Pairs near the thresholds MUST be listed as candidates, not findings.

**Alignment and stack-up**

- **FR-007**: Each joint MUST be checked for alignment: an axis offset beyond half the hole-to-fastener clearance is demonstrated, with both numbers.
- **FR-008**: The allowed position budget of each joint MUST be reported as a recommended drawing callout.
- **FR-009**: A diameter-zone tolerance MUST be compared as a radius of half its value (correcting the current comparison).
- **FR-010**: When every contributor has a tolerance, the worst-case stack-up MUST be computed and judged against the joint's clearance, citing each source; otherwise it MUST be unresolved, naming the missing contributor and the sources searched.

**Fasteners**

- **FR-011**: Fasteners MUST be recognised from part file names and descriptions as well as Toolbox, for the vendor naming patterns in the recorded packages and the common metric and inch forms, cross-checked against the measured shank diameter.
- **FR-012**: Every screw joint MUST be checked for thread match (size and pitch against the tapped hole).
- **FR-013**: Every screw joint MUST be checked for engagement and bottoming from the placed geometry, against a minimum of 1.5 x the nominal diameter into both steel and aluminium (owner decision 2026-09-23), citing the rule; hole depth MUST never be taken as thread depth.

**Tool access**

- **FR-014**: Every screw joint MUST be checked for tool access: the head plane and direction from the joint map, the tool from the head type, the envelope swept against every other body, a blocking body named.
- **FR-015**: A counterbore or countersink in a screw joint MUST be checked against the head dimensions from a standard head table.

**Mass and material**

- **FR-016**: Every part MUST have a material or a deliberate mass override; every part with a volume MUST have a density consistent with its named material and not at the no-material default.
- **FR-017**: An assembly mass override MUST be reported for confirmation.
- **FR-018**: The extractor MUST read the mass override for every document (fixing today's failing read) and count bodies it could not read.

**Hygiene**

- **FR-019**: The part-number property MUST match the file name's stem; different documents MUST not share a description or part number; every model MUST carry a revision; suppressed and lightweight components in the reviewed configuration MUST be findings.
- **FR-020**: A part-number pattern that matches no document MUST be reported as a likely profile error.

**Tolerances**

- **FR-021**: The extractor MUST record Hole Wizard fit class, thread class, and drill, counterbore and countersink sizes.
- **FR-022**: The extractor MUST record tolerances on model feature dimensions, and DimXpert or MBD annotations when present, each with a reference to its source.
- **FR-023**: The standards profile MUST be able to declare a general tolerance, applied only to dimensions without their own tolerance and cited as general.
- **FR-024**: Drawing tolerances from feature 011 MUST be usable by the stack-up and fit checks with the same citation rules.
- **FR-025**: No tolerance may be inferred; a check needing an absent tolerance is unresolved.

**Integration**

- **FR-026**: Every check in this feature MUST take no model-chosen arguments and MUST run in feature 008's code-first pass.
- **FR-027**: Every new finding MUST carry the evidence and calculation inputs the existing findings carry, and every new check id MUST be classed in the attention policy.
- **FR-028**: New package fields MUST be additive; packages written before this feature MUST load and be checked with the new checks unresolved where their data is missing.

### Key Entities

- **Joint**: two or more parts, their holes or cylinders, the axis, the kind, the derived sizes, and the fastener or pin when present.
- **Contact**: a zero-volume interference between two parts, with the parts and the joint it belongs to when known.
- **Recognised fastener**: kind, size, pitch, length, head type, how it was recognised (Toolbox or name), and its measured shank.
- **Tolerance source**: where a tolerance came from (Hole Wizard, model dimension, annotation, drawing, general block), its type and limits.
- **Stack-up**: the contributors along a joint, each with its tolerance and source, the worst case, and the judgement.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the fixture shaped like 830-02342, every detected interference group is judged (against 6 of 113 in the recorded review), and zero-volume contacts occupy no "Start here" slot.
- **SC-002**: On the same fixture, the M4 screw in the M5 tapped hole is reported as a thread mismatch, with no model involved.
- **SC-003**: On the same fixture, the five near-coaxial joints are checked for alignment and the 0.75 mm dowel offset is reported, against three unrelated pairs in the recorded review.
- **SC-004**: At least 90% of the screws named in the recorded packages' vendor pattern are recognised as fasteners.
- **SC-005**: Every part with an extracted mass and volume receives a mass-and-material verdict.
- **SC-006**: Every check added here runs in the code-first pass: the replay of the recorded runs shows no additional model rounds for them.
- **SC-007**: No check in this feature reports a verdict that depends on a tolerance or thread depth the evidence does not contain.
- **SC-008**: On the next workstation sitting, the Hole Wizard and dimension tolerance reads and the mass-override read return values on the recorded assemblies.

## Assumptions

- Joint-map thresholds (angle, projected overlap, axial adjacency) start at 1 degree and a projected overlap with an adjacency gap under 1 mm, configurable; near-threshold pairs are candidates for the engineer.
- The engagement rule is 1.5 x diameter for steel and aluminium alike; other material classes keep their current rules. The owner's answer "1.td into both" is read as 1.5d.
- Tool envelopes use the existing pilot default ratios until the shop's tool set is supplied; the table is data.
- The standard head-dimension table covers ISO socket, button and flat head cap screws and hex heads; inch heads are added when the recorded packages carry them.
- The mass-override and tolerance reads need a seat to validate; their code and tests are built here with fake readers.
- Drawing tolerances arrive with feature 011; until then the stack-up uses the three model-side sources and the general block.
- The contact list's presentation in the pane belongs to feature 009.
