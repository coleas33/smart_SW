# Future capabilities roadmap: drawings and engineering load context

Status snapshot: 2026-10-14, after main `8a8682f` and
`015-review-send-gate` `c4f17d5`. This began as a planning record. The shared
engineering-context foundation was subsequently authorized as
[Feature 016](../specs/016-engineering-context/quickstart.md); its first delivery
provides offline requirements/forces, revision history, explicit confirmation and
bounded LLM reads. The later stages, probes, drawing writers and structural analysis
remain proposals. No constitution or native capability gate is changed.

## Current roadmap

| Track | Current position | Next work when authorised |
|---|---|---|
| Review foundation, 008–013 | Checks first, mechanical checks, bounded evidence/context, questions, labels, existing-drawing reads and drawing briefs are implemented. | Workstation regression and coverage validation; preserve unresolved evidence. |
| Evaluation, 014 | Slices 1–4 complete, through T158 and the golden scorecards. | Slice 5 T159–T170: linked offline reporting and prompt/recording evidence; then robustness, recovery, cost and workstation gates before paid studies. |
| Review send gate, 015 | US1–3, T001–T091 complete on its branch: checks-only review, deliberate Send, opening-size estimate and waiting-state answers. | US4 T092–T110: restart/recheck/recovery and carrying matching answers/decisions; then polish T111–T118 and pilot T119. |
| Remodel, 004 | Stage 1 organises a copied feature tree. Plan and prerequisite repairs exist; the latest lifetime/settings and geometry-override repairs are on 015. | Blocking native probes, measured calibration and actual Plan/cleanup/Start validation. Stage 2 geometry reconstruction needs its own later specification. |
| Drawing context, 011/013 | Related already-open drawings can be read during Full Review; annotations/tables and a bounded per-part brief exist. | Closed-drawing approval opening needs D14; numerical use needs D4/D5 unit/precision confirmation and separate D6/D8 entity-binding evidence. |
| Drawing creation, reserved 012 | Architecture direction exists; no 012 feature package or production creator exists. | Evaluate the owner's generator base, define a narrow drawing family, then specify a reviewed plan and new-output executor. |
| Load context and estimates | Feature 016 provides the offline requirement/applied-force sidecar and explicit confirmation; no broader load-case model, structural solver or Simulation executor exists. | Native selection/rebinding and unsaved-state attestation on the workstation; then separately specified load cases, validated calculations and existing-study import. |

The three production gates remain separate: drawing approval opening, drawing
numerical binding and Remodel Start are all off. A successful drawing-open probe
does not establish that a drawing tolerance is correctly bound to a model hole.

The near-term delivery sequence remains: retest the October 13 fixes on the
separate SOLIDWORKS workstation; complete 014 slice 5 and 015 US4 at their gates;
collect native drawing/Remodel evidence; then publish measured calibration and
any justified capability enablement separately. Documentation preparation for
future capabilities can proceed alongside that sequence once requested.

Sources: [current workstation follow-up](testing-feedback-2026-10-13.md),
[014 tasks](../specs/014-design-review-eval/tasks.md),
[015 branch package](https://github.com/coleas33/smart_SW/tree/c4f17d573db1e230d13e2795ff3422d3b8f53b9d/specs/015-review-send-gate),
[011 tasks](../specs/011-drawing-context/tasks.md),
[004 plan](../specs/004-resilient-remodeler/plan.md).

## Foundations shared by drawings and loads

The [engineering-context foundation draft](engineering-context-foundation.md)
expands the first structure, record lifecycle, reuse boundaries and initial milestone.
The first offline implementation is delivered in Feature 016. Native binding adapters,
broader load cases and drawing/solver execution remain later work.

Prepare one evidence-binding contract for both capabilities. It should name the
model, configuration, component instance, evidence package/hash, relevant source
revision, scoped entity reference and geometry/placement fingerprints. The LLM
sees short entity IDs; native persistent references remain behind the tools.

Record coordinate frames and transformations explicitly, including assembly and
component frames, origins, direction/sign conventions and units. Geometry,
configuration, placement, material or referenced-entity changes must mark affected
plans/load inputs as needing review. Changed loads, supports/contacts, combinations,
factors and applicable rule/template revisions also require renewed review, even
when the CAD geometry is unchanged. A matching filename or the current extraction
reuse key alone is insufficient proof that engineering context is still current.

Keep engineer-confirmed inputs, extracted evidence, catalogue facts, deterministic
derivations and unconfirmed AI proposals distinct. The existing questions,
source labels, bounded summaries, detail tools and offline replay provide the
foundation. Company templates, policy values, material databases and real design
examples stay outside the public repository; public examples remain fictional.

## Preparing automated drawings

### D0 — Inventory the existing generator and drawing requirements

The September roadmap already requires evaluating the owner's drawing-generation
base repository and flat-pattern macros before specifying 012. The base repository
location is still an input to obtain later. Record its operations, supported part
families, API/version requirements, inputs, licence, placement/dimension rules,
error handling and write behaviour. Evaluate prior art before choosing reuse,
porting or a separate executor.

Propose one first family, such as machined plates/brackets; the family is not yet
a decision. Gather accepted drawings and their manufacturing intent: functional
interfaces, required views/sections, chosen datums, meaningful dimensions, finish,
tolerance sources, inspection requirements and title/revision rules. Identify
what the existing 6,000-byte drawing brief supplies and what it lacks.

Document private template/sheet-format identities and versions, projection, units,
BOM/balloon conventions and general tolerances. Importing every modelling dimension
is not the acceptance criterion; the drawing must communicate the manufacturing
requirements the engineer confirmed.

### D1 — Specify an offline drawing plan and review flow

A proposed versioned drawing-plan contract should carry:

| Field group | Required meaning |
|---|---|
| Evidence binding | Exact model/configuration, source/evidence identity, real referenced entities and staleness checks. |
| Sheet policy | Template/format identity, units, projection, allowed sheet/scale policy and required metadata. |
| Views | Named orientation, section/detail/flat-pattern intent, referenced configuration and layout constraints. |
| Annotations | Dimension purpose and real source geometry; confirmed datums; sourced tolerances, hole callouts, notes, finish and tables. |
| Uncertainty | Missing input, unsupported operation, proposed callout and engineer decision recorded explicitly. |
| Review | Which plan version was reviewed, decisions and approval invalidation after an affected input changes. |

Reuse the existing per-part brief. The LLM proposes coverage and asks about intent;
tested software supplies numeric values, transformations and layout. A tolerance
or GD&T choice requires a cited requirement or engineer decision. A recommended
callout from a check remains a proposal until accepted.

The first useful future milestone is a reviewable plan/report outside CAD. It can
be specified and later validated against fictional packages without a SOLIDWORKS
seat. Approval of a plan and engineering acceptance of its eventual drawing are
two separate records.

### D2 — Specify a deterministic creator for new outputs

SOLIDWORKS 2024 already exposes APIs for views, model annotations, BOMs and balloons.
The practical baseline is a template/rule-driven executor for the chosen family.
Official examples demonstrate these operations, while `AutoDimension` has datum
defaults that cannot substitute for engineering intent.
[2024 views and annotations](https://help.solidworks.com/2024/english/api/sldworksapi/Get_Annotations_Array_Example_VB.htm?format=P&value=),
[2024 BOM/balloons](https://help.solidworks.com/2024/english/api/sldworksapi/insert_bom_table_and_bom_balloon_example_vb.htm?format=P&value=),
[2024 AutoDimension](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~AutoDimension.html).

Creation requires its own specification and a constitution amendment for a bounded
new write path. The executor would own only a fresh run-folder drawing, refuse
overwrite, revalidate source/entity identity, log operations and cancel/discard
without touching other documents. First saving an unsaved drawing needs an
explicitly designed mechanism; Remodel's path-bound copy and `Save3` allowance
cannot simply be reused. A new write exception alone does not authorise autonomous
GD&T or general dimensioning: supported annotation scope and engineering acceptance
need their own specification and validation under the constitution. The current
guard stays unchanged during preparation.

Define future native probes and an acceptance matrix: correct template, view
configuration/orientation, projection, units/scale, dimension provenance, selected
datums, required sections, BOM/balloon consistency, layout/readability, missing
requirements, source-file/save-flag preservation and failure cleanup. Measure
manufacturing coverage, incorrect callouts and manual cleanup time.

### D3 — Optional newer-version generation

Keep the 2026 built-in Auto-Generate Drawing capability as a separately verified
option if the team later changes its workstation platform. Official help describes
it for 3DEXPERIENCE users; SP4/FD04 adds custom template/format and annotation settings.
That does not establish entitlement, supported API/batch invocation or compatibility
on this project's 2024 SP5 seat. No callable Auto-Generate API has been verified for
this project. Recheck actual product access and integration before choosing it.
[2026 generation](https://help.solidworks.com/2026/english/SolidWorks/sldworks/c_auto_generate_drawings.htm?id=13.12.14),
[SP4/FD04 changes](https://help.solidworks.com/2026/english/WhatsNew/c_wn2026_drawings_auto_generate_drawings_sp4.htm?id=11.0).

## Preparing engineering load context in SOLIDWORKS

### L0 — Context first, without Simulation

The highest-value first proposal is an engineer-confirmed load-case record attached
to the extracted model, presented in the existing Review/questions/report flow.
It needs no Simulation licence and initially writes context into the run's evidence,
not into the CAD model. UI placement is a future decision; a Loads mode in Review is
a reasonable proposal, not an approved new tab.

A future workflow would let the engineer select a face/component, enter a typed
load, or describe an operating scenario. Natural language produces a draft with
explicit target, magnitude, units and direction; the engineer confirms it before
it becomes an input. Existing capture/persistent-reference infrastructure can be
reused, but selection-to-load mapping and bounded reads of missing selected entities
still need specification and native validation.

A proposed load-context contract should include:

| Field group | Required meaning |
|---|---|
| Case | Case ID/name, operating condition, baseline or what-if, design/configuration/evidence identity. |
| Loads | Distinct force, moment, pressure, gravity, acceleration/motion and preload records; original values/units plus canonical quantities calculated by code. |
| Application | Component instance and selected point/region/entity; total force versus distribution; coordinate frame, origin, signed direction and transformation. |
| Supports/connections | Confirmed restraints/degrees of freedom, real mounting, contact behaviour, connectors and load-sharing assumptions. |
| Engineering inputs | Material source/properties, masses, relevant sections, fastener grade/preload/friction, welds and vendor ratings when needed. |
| Combinations | Simultaneous versus alternative conditions, duty/time information and explicitly sourced factors; avoid double-counting gravity or inertial effects. |
| Provenance/state | Source per value, draft/confirmed-input/needs-review/unresolved, assumptions, omissions and confirmation history. |

A fixed CAD component is not automatically a structural support. Mates and geometric
contacts suggest questions about connectivity; they do not prove a load path,
friction, preload or stiffness sharing. Material names alone do not supply strength
or modulus. Unknown mass/overrides and simplified vendor geometry limit derived
loads until supported inputs exist.

Current groundwork includes component transforms, scoped references, mass/centre
of mass, materials, mates, joints, evidence labels and calculation records. The
product still lacks load cases, force/moment/pressure conversion APIs, material
strength/modulus and public-IR inertia tensors. Specify these additions only as
needed by the chosen increment.

Define a bounded load summary and on-demand details for the LLM: which cases exist,
where loads/supports act, confirmed assumptions and missing inputs. The LLM can
ask questions, describe hypotheses and explain computed evidence. Unit conversion,
resultants, reactions and stress calculations belong to validated software.
Confirmed input is not structural acceptance. What-if proposals remain separate
from the confirmed baseline.

### L1 — Add validated calculations incrementally

A later, separately specified estimate feature can introduce one method at a time:
gravity/resultants, determinate reactions, a supported simple bolt-group model,
then a narrowly defined bracket calculation. Each method needs published examples,
independent checks where available, unit/boundary/missing-input tests and explicit
idealisations. Indeterminate or unsupported cases remain unresolved.

The September hand-calculation proposal is a much larger candidate library, not the
minimum needed to give an LLM load context. Its scope amendment, assumptions and
validation gates require review before calculations ship. Structural approval
remains outside the current pilot; no new scope amendment is applied here.

### L2 — Import existing Simulation context/results

SOLIDWORKS 2024 documents existing study, load/restraint and results interfaces.
A future read-only adapter could import an explicitly supported subset of existing
studies. API presence is not proof of availability: first document the testing
workstation's installed version, available Simulation product/licence, loaded
add-in and supported study types. An interop DLL alone establishes none of these.
[2024 study interface](https://help.solidworks.com/2024/english/api/swsimulationapi/SolidWorks.Interop.cosworks~SolidWorks.Interop.cosworks.ICWStudy.html?id=11.4.1.63),
[2024 load/restraint members](https://help.solidworks.com/2024/English/api/swsimulationapi/SolidWorks.Interop.cosworks~SolidWorks.Interop.cosworks.ICWLoadsAndRestraints_members.html?id=9e694b2b51f8465385021a3e4f37d8e8),
[2024 Simulation products](https://help.solidworks.com/2024/english/WhatsNew/c_wn_simulation.htm?id=15).

The import contract should retain study type/configuration, load/contact/material
setup, mesh/setup/result fingerprints, solver/version, solve state and warnings.
Results need units, step/time, region/location, coordinate frame, quantity definition
and nodal/elemental/averaging basis where relevant. A contour screenshot or an API
returning numbers is insufficient evidence of a current solved study. Missing,
unsolved, partial or unverifiably current results stay unresolved.
[2024 results example](https://help.solidworks.com/2024/english/api/swsimulationapi/Create_Dynamic_Response_Spectrum_Study_Example_CSharp.htm).

Document native getter/guard probes first. Importing should not create studies,
mesh, solve, activate a different configuration or silently load a licence-consuming
add-in. Reuse known solved cases to validate the later importer and calculations.

### L3 — Author and solve studies only as a later capability

Creating/editing loads or studies is CAD authoring. A future executor would need a
reviewed typed proposal, separate bounded write scope, a cosworks-specific guard,
owned output/copy lifecycle, source attestation, solver validation and licensed
native tests. Existing Remodel permission does not authorise arbitrary Simulation
writes. Loads recorded as review context are not loads applied to a native study.

## Preparation backlog and decisions to obtain later

| Priority | Documentation deliverable | Completion criterion |
|---|---|---|
| P0 | Current native-gate and feature-status map | Existing implementation is distinguished from native confirmation and future proposals. |
| P1 | Shared evidence/coordinate/provenance contract draft | Identity, units, frames, confirmation and invalidation rules agree across both tracks. |
| P1 | Drawing-base inventory worksheet and first-family requirements | Repository location and representative accepted drawings can be supplied privately; reuse gaps and required brief fields can be evaluated. |
| P1 | Load-context contract and fictional case descriptions | Input loads/supports can be stated without a solver or a structural verdict. |
| P2 | Drawing-plan/review/output lifecycle proposal | Concrete plans, missing inputs and later new-output ownership can be independently reviewed. |
| P2 | Native capability/validation matrix | Tests to run on the other machine are defined before any writer or Simulation adapter is admitted. |
| P3 | Method-by-method estimate and existing-study import proposals | Intended inputs, limitations and acceptance examples are defined before implementation. |

Useful future examples include a plate drawing, a flat-pattern drawing and an
assembly BOM; mixed force/mass units, local/reversed axes, pressure versus resultant
force, unresolved targets, changed configuration, missing material/mass, redundant
supports, unconfirmed language inputs and unsolved/stale studies. These are proposed
case descriptions, not fixtures created by this documentation pass.

Obtain later: the drawing-base location/licence; first part family and accepted
examples; private templates/standards; representative operating loads and actual
supports; relevant catalogue/material sources; desired context UI; and actual
Simulation availability. No delivery dates or new feature numbers are assigned.
012 remains reserved; 014 and 015 are already in use.

## Earlier research and governing scope

[September roadmap](roadmap-2026-09-22.md) and
[concept/hand-calculation research](future/llm-assistants-2026-09-28.md) remain historical
inputs. Their estimates are not a current schedule; the older claim that 014/015
are the next free feature numbers is obsolete. The architecture's September 22
amendment selects rule-driven drawing creation first for 2024; its older 2026-first
action list is not the current backlog.

[Drawing brief contract](../specs/011-drawing-context/contracts/brief.md),
[drawing capability contract](../specs/013-engineer-first-review/contracts/drawing-capability.md),
[architecture](../sw-review-architecture-proposal.md) and
[constitution](../.specify/memory/constitution.md) define the existing foundation.
This roadmap proposes future specifications. It grants no new native write surface,
structural approval or production capability enablement.
